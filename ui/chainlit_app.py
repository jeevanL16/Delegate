"""
ui/chainlit_app.py
Delegate: Resolve — Chainlit UI implementation.

Changes vs. the previous version (cosmetic/structural only — no backend,
API, or policy logic touched):
  1. All repeated HTML snippets moved to ui/ui_helpers.py (single source
     of truth instead of four hand-copied strings).
  2. The whole Analyzer -> Router -> Executor -> Reviewer -> Policy Outcome
     trail is now ONE collapsible parent Step per turn ("Resolution
     Pipeline") instead of five separate top-level messages plus a sixth
     HTML "header" message — cuts a 6-bubble turn down to 2 (reply +
     one collapsed step block).
  3. The old inline HTML "header" bubble is gone. A real, persistent
     header now lives outside the chat stream (see public/custom.js +
     public/style.css) so it doesn't scroll away.
  4. Requires features.unsafe_allow_html = true in .chainlit/config.toml
     for the order banner / empty-state / policy footer to render as
     anything other than literal text — this ships with that flag set.

Features (unchanged from before):
- Live Customer Support with humanized replies (no internal leaks).
- Expandable native Chainlit steps showing Analyzer -> Router -> Executor
  -> Reviewer reasoning.
- Predefined login for Seeded Customers + Staff (password: demo123).
- Chat profiles: Customer / Staff.
- Staff operations desk: left-sidebar thread history + live escalation
  queue with 1-click actions.
- Persistent conversation threads via Neon PostgreSQL SQLAlchemy Data Layer.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Ensure project root directory is in sys.path so 'ui' and 'app' modules resolve
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_ui_dir = str(Path(__file__).resolve().parent)
if _ui_dir not in sys.path:
    sys.path.insert(0, _ui_dir)

import chainlit as cl
from chainlit.data.base import BaseDataLayer
from dotenv import load_dotenv

load_dotenv()

if not os.getenv("CHAINLIT_AUTH_SECRET"):
    os.environ["CHAINLIT_AUTH_SECRET"] = os.getenv(
        "HUMAN_JWT_SECRET", "7f9b2d4e6a8c0e1f3a5b7c9d1e3f5a7b9c1d3e5f7a9b1c3d5e7f9a1b3c5d7e9f"
    )

from ui.api_client import (
    approve_human_ticket,
    create_ticket,
    get_customers,
    get_human_queue,
    get_latest_order,
    get_ticket,
    resolve_ticket,
    send_n8n_notification,
    send_slack_notification,
)
from ui.cl_data import get_data_layer, init_chainlit_tables
from ui.humanizer import fmt_inr, humanize
from ui.ui_helpers import (
    render_empty_state,
    render_order_banner,
    render_policy_footer,
    render_section_header,
)

logger = logging.getLogger(__name__)


# ── Chainlit Data Layer (Thread persistence in Neon DB) ───────────────────────

_dl = get_data_layer()
if _dl is not None:
    @cl.data_layer
    def setup_data_layer() -> BaseDataLayer:
        assert _dl is not None
        return _dl


@cl.on_app_startup
async def on_app_startup():
    await init_chainlit_tables()


# ── Authentication Callback ───────────────────────────────────────────────────

@cl.password_auth_callback
async def auth_callback(username: str, password: str) -> Optional[cl.User]:
    """Authenticate against seeded customers (live from DB/API) or staff account."""
    demo_mode = os.getenv("DEMO_MODE", "true").lower() == "true"
    if demo_mode:
        if password.strip() != "demo123":
            return None
    else:
        expected_pwd = os.getenv(f"USER_PWD_{username.strip().upper()}", "")
        if not expected_pwd or password.strip() != expected_pwd:
            return None

    identifier = username.strip().lower()

    if identifier in ("staff", "admin"):
        return cl.User(
            identifier="staff",
            display_name="Staff Support Agent",
            metadata={
                "role": "staff",
                "id": "staff-agent-1",
                "name": "Staff Support Agent",
                "email": "staff@delegate.internal",
            },
        )

    customers = get_customers()
    for c in customers:
        c_email = str(c.get("email", "")).strip().lower()
        c_name = str(c.get("name", "")).strip().lower()
        c_id = str(c.get("id", "")).strip().lower()
        c_first = c_name.split()[0] if c_name else ""

        if identifier in (c_email, c_name, c_id, c_first):
            return cl.User(
                identifier=c.get("email", identifier),
                display_name=c.get("name", "Customer"),
                metadata={
                    "role": "customer",
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "email": c.get("email"),
                    "tier": c.get("tier", "regular"),
                    "flags": c.get("flags", []),
                },
            )

    return None


# ── Chat Profiles (Customer vs Staff) ────────────────────────────────────────

@cl.set_chat_profiles
async def chat_profiles(current_user: Optional[cl.User] = None):
    return [
        cl.ChatProfile(
            name="Customer",
            markdown_description="Delegate Support for customers — order tracking, issues, and instant resolutions.",
            icon="https://api.iconify.design/lucide:user.svg",
        ),
        cl.ChatProfile(
            name="Staff",
            markdown_description="Staff Operations Desk — browse escalation queue, approve refunds, resend notifications.",
            icon="https://api.iconify.design/lucide:shield-check.svg",
        ),
    ]


# ── Helper: Determine Policy Outcome Line ─────────────────────────────────────

def _get_policy_outcome_line(ticket: dict[str, Any], resolve_res: Optional[dict[str, Any]] = None) -> str:
    """Derive one plain-English line for the policy outcome from audit trail & reasoning."""
    status = (ticket.get("status") or (resolve_res.get("status") if resolve_res else "") or "").lower()
    reason = ticket.get("escalation_reason") or (resolve_res.get("escalation_reason") if resolve_res else "")
    resolution = ticket.get("resolution") or (resolve_res.get("resolution") if resolve_res else "") or ""

    audit_reasons = [
        e.get("decision_reason", "")
        for e in ticket.get("audit_trail", [])
        if e.get("decision_reason")
    ]

    if status == "escalated":
        if any("vip" in str(r).lower() for r in audit_reasons) or "vip" in str(reason).lower():
            return "Escalated — VIP customer requires human specialist approval"
        if any("repeat" in str(r).lower() for r in audit_reasons) or "repeat" in str(reason).lower():
            return "Escalated — Repeat complaints flagged; transferred to human specialist"
        if any("cap" in str(r).lower() or "limit" in str(r).lower() for r in audit_reasons) or "cap" in str(reason).lower():
            return "Escalated — Refund amount exceeds automated policy limit (₹1,000.00 cap)"
        if "ambiguous" in str(reason).lower() or any("ambiguous" in str(r).lower() for r in audit_reasons):
            return "Escalated — Ambiguous customer intent; transferred to human specialist"
        if "tool_limit" in str(reason).lower() or any("tool_limit" in str(r).lower() for r in audit_reasons):
            return "Escalated — Tool invocation limit reached; safety escalation triggered"
        if reason:
            clean_r = str(reason).replace("_", " ").capitalize()
            return f"Escalated — {clean_r}"
        return "Escalated — Policy evaluation requires human approval"

    if "already" in resolution.lower() and "refund" in resolution.lower():
        return "Verified — Transaction was previously refunded under policy rules"

    if "refund" in resolution.lower():
        return "Approved — Full refund authorized within policy limits"

    if "delivered" in resolution.lower():
        return "Resolved — Verified order delivery status with carrier"

    return "Approved — Request verified and resolved under standard policy"


# ── Chat Session Start ────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start():
    user = cl.user_session.get("user")
    profile = cl.user_session.get("chat_profile") or "Customer"

    if user and user.metadata and user.metadata.get("role") == "customer":
        cust_id = user.metadata.get("id")
        cust_name = user.metadata.get("name", "Customer")
        cl.user_session.set("customer_id", cust_id)
        cl.user_session.set("customer_name", cust_name)
        cl.user_session.set("customer_email", user.metadata.get("email"))
        cl.user_session.set("customer_tier", user.metadata.get("tier", "regular"))
    else:
        customers = get_customers()
        c = customers[0] if customers else {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "Arjun Sharma",
            "email": "arjun.sharma@example.in",
            "tier": "regular",
        }
        cl.user_session.set("customer_id", c["id"])
        cl.user_session.set("customer_name", c["name"])
        cl.user_session.set("customer_email", c.get("email"))
        cl.user_session.set("customer_tier", c.get("tier", "regular"))

    if profile == "Staff":
        await render_staff_dashboard()
    else:
        await render_customer_welcome()


async def render_customer_welcome():
    cust_id_raw = cl.user_session.get("customer_id")
    cust_id = str(cust_id_raw) if cust_id_raw else None
    cust_name = cl.user_session.get("customer_name") or "Customer"
    first_name = str(cust_name).split()[0]

    latest_order = (await asyncio.to_thread(get_latest_order, cust_id)) if cust_id else None
    cl.user_session.set("latest_order", latest_order)

    welcome_text = (
        f"Hi **{first_name}**! 👋 Welcome to **Delegate Support**."
        f"{render_order_banner(latest_order)}\n\n"
        "How can I help you today?"
    )
    await cl.Message(content=welcome_text).send()


async def render_staff_dashboard():
    queue = await asyncio.to_thread(get_human_queue)
    customers_list = await asyncio.to_thread(get_customers)
    customers_map = {c["id"]: c for c in customers_list}

    if not queue:
        await cl.Message(
            content=render_empty_state(
                "All Caught Up!",
                "There are currently no escalated tickets awaiting human review. "
                "The Policy Engine is handling customer requests within automated limits.",
            )
        ).send()
        return

    await cl.Message(
        content=(
            render_section_header("Escalated Tickets Awaiting Review", count=len(queue))
            + "\n\n*High-priority cases escalated by the Policy Engine for human specialist authorization:*"
        )
    ).send()

    for t in queue:
        t_id = str(t.get("id", ""))
        cust_id = str(t.get("customer_id", ""))
        c_info = customers_map.get(cust_id, {})
        c_name = c_info.get("name", cust_id[:8] + "…")
        c_tier = c_info.get("tier", "regular").upper()
        issue = t.get("issue_type", "unclassified")
        raw_text = t.get("raw_text", "")
        created = str(t.get("created_at", ""))[:19].replace("T", " ")
        order_id = t.get("order_id")
        order_str = f"`#{str(order_id)[:8]}…`" if order_id else "*None*"

        detail = get_ticket(t_id)
        esc_reason = "Requires human agent authorization"
        if detail and detail.get("audit_trail"):
            for entry in reversed(detail["audit_trail"]):
                if entry.get("decision_reason"):
                    esc_reason = entry["decision_reason"]
                    break

        card_md = (
            f"### ⚠️ Ticket `#{t_id[:8]}…`\n"
            f"- **Customer:** **{c_name}** (`{c_tier}`)\n"
            f"- **Order:** {order_str}\n"
            f"- **Issue Type:** `{issue}`\n"
            f"- **Customer Message:** *\"{raw_text}\"*\n"
            f"- **Escalation Reason:** `{esc_reason}`\n"
            f"- **Created:** {created}"
        )

        actions = [
            cl.Action(name="approve_refund", payload={"ticket_id": t_id}, label="Approve Refund"),
            cl.Action(name="close_ticket", payload={"ticket_id": t_id}, label="Close Without Action"),
            cl.Action(name="resend_notification", payload={"ticket_id": t_id}, label="Resend Notification"),
        ]

        await cl.Message(content=card_md, actions=actions).send()


# ── Action Callbacks for Staff ────────────────────────────────────────────────

@cl.action_callback("approve_refund")
async def on_approve_refund(action: cl.Action):
    raw_id = action.payload.get("ticket_id")
    if not raw_id:
        return
    ticket_id = str(raw_id)
    await action.remove()
    res = approve_human_ticket(ticket_id, action="issue_refund", note="Approved by staff via console")
    if res and res.get("status") == "resolved":
        amt = fmt_inr(res.get("amount_cents"))
        await cl.Message(
            content=f"✅ **Refund Approved:** Ticket `#{ticket_id[:8]}…` has been resolved. Refund issued: **{amt}**."
        ).send()
    else:
        err = res.get("reason") if res else "Failed to process approval"
        await cl.Message(content=f"⚠️ **Could not approve refund:** {err}").send()


@cl.action_callback("close_ticket")
async def on_close_ticket(action: cl.Action):
    raw_id = action.payload.get("ticket_id")
    if not raw_id:
        return
    ticket_id = str(raw_id)
    await action.remove()
    res = approve_human_ticket(ticket_id, action="close_no_action", note="Closed without action by staff")
    if res and res.get("status") == "resolved":
        await cl.Message(
            content=f"🚫 **Ticket Closed:** Ticket `#{ticket_id[:8]}…` closed without action."
        ).send()
    else:
        await cl.Message(content="⚠️ **Could not close ticket:** Unexpected error.").send()


@cl.action_callback("resend_notification")
async def on_resend_notification(action: cl.Action):
    raw_id = action.payload.get("ticket_id")
    if not raw_id:
        return
    ticket_id = str(raw_id)
    await action.remove()
    ok = send_n8n_notification(ticket_id, template="escalated")
    if ok:
        await cl.Message(
            content=f"📧 **Notification Resent:** Dispatched webhook to n8n for ticket `#{ticket_id[:8]}…`."
        ).send()
    else:
        await cl.Message(
            content=f"⚠️ **Notification Failed:** n8n webhook could not be reached for ticket `#{ticket_id[:8]}…`."
        ).send()


# ── Message Handler ───────────────────────────────────────────────────────────

@cl.on_message
async def on_message(message: cl.Message):
    profile = cl.user_session.get("chat_profile") or "Customer"

    if profile == "Staff":
        user_input = message.content.strip().lower()
        if "queue" in user_input or "refresh" in user_input or "list" in user_input:
            await render_staff_dashboard()
        else:
            await cl.Message(
                content="*Staff Console ready. Type 'queue' or 'refresh' to view updated escalation items.*"
            ).send()
        return

    cust_id_raw = cl.user_session.get("customer_id")
    customer_id = str(cust_id_raw) if cust_id_raw else "11111111-1111-1111-1111-111111111111"
    latest_order = cl.user_session.get("latest_order")
    order_id = str(latest_order.get("id")) if latest_order and latest_order.get("id") else None

    transient_msg = cl.Message(content="*Delegate is checking your order…*")
    await transient_msg.send()

    ticket_res = await asyncio.to_thread(create_ticket, customer_id=customer_id, raw_text=message.content, order_id=order_id)
    if not ticket_res or "ticket_id" not in ticket_res:
        await transient_msg.remove()
        await cl.Message(
            content="We're having trouble connecting to support right now. Please try again shortly."
        ).send()
        return

    ticket_id = ticket_res["ticket_id"]

    resolve_res = await asyncio.to_thread(resolve_ticket, ticket_id)
    ticket_detail = (await asyncio.to_thread(get_ticket, ticket_id)) or {}
    if not resolve_res and not ticket_detail:
        await transient_msg.remove()
        await cl.Message(
            content="We're having trouble resolving your request right now. Please try again shortly."
        ).send()
        return

    await transient_msg.remove()

    # ── Visible reasoning: ONE collapsible parent step per turn (hidden by default) ──
    audit_trail = ticket_detail.get("audit_trail", [])
    outcome_line = _get_policy_outcome_line(ticket_detail, resolve_res)

    if os.getenv("SHOW_REASONING_TO_CUSTOMER", "false").lower() == "true":
        pipeline_step = cl.Step(name="🧠 How Delegate resolved this", type="run", default_open=False)
        await pipeline_step.send()

        analyzer_entries = [e for e in audit_trail if e.get("stage") == "analyzer"]
        analyzer_step = cl.Step(name="🔎 Analyzer", type="run", parent_id=pipeline_step.id, default_open=False)
        analyzer_step.input = message.content
        analyzer_step.output = json.dumps(
            analyzer_entries[-1].get("output_json", {}) if analyzer_entries
            else {"intent": "classified", "ticket_id": ticket_id},
            indent=2,
        )
        await analyzer_step.send()

        router_entries = [e for e in audit_trail if e.get("stage") == "router"]
        router_step = cl.Step(name="🧭 Router", type="run", parent_id=pipeline_step.id, default_open=False)
        if router_entries:
            r_entry = router_entries[-1]
            router_step.input = json.dumps(r_entry.get("input_json", {}), indent=2)
            router_step.output = (
                f"Action: {r_entry.get('action')}\n"
                f"Decision: {r_entry.get('decision_reason', 'Route selected')}\n"
                f"Output: {json.dumps(r_entry.get('output_json', {}), indent=2)}"
            )
        else:
            router_step.output = "Standard routing workflow engaged."
        await router_step.send()

        executor_entries = [e for e in audit_trail if e.get("stage") == "executor"]
        executor_step = cl.Step(name="⚙️ Executor", type="run", parent_id=pipeline_step.id, default_open=False)
        await executor_step.send()

        if executor_entries:
            executor_step.output = f"Executed {len(executor_entries)} tool call(s)."
            await executor_step.update()
            for tool_entry in executor_entries:
                raw_action = tool_entry.get("action", "tool")
                lowered = raw_action.lower()
                if "status" in lowered or "order" in lowered:
                    tool_label = f"🔍 {raw_action}"
                elif "refund" in lowered:
                    tool_label = f"💰 {raw_action}"
                elif "notify" in lowered:
                    tool_label = f"📧 {raw_action}"
                else:
                    tool_label = f"🔧 {raw_action}"

                tool_step = cl.Step(
                    name=tool_label,
                    type="tool",
                    parent_id=executor_step.id,
                    default_open=False,
                )
                tool_step.input = json.dumps(tool_entry.get("input_json", {}), indent=2)
                tool_step.output = json.dumps(tool_entry.get("output_json", {}), indent=2)
                await tool_step.send()
        else:
            executor_step.output = "No external tools required."
            await executor_step.update()

        reviewer_entries = [e for e in audit_trail if e.get("stage") == "reviewer"]
        reviewer_step = cl.Step(name="🛡️ Reviewer", type="run", parent_id=pipeline_step.id, default_open=False)
        if reviewer_entries:
            rev_entry = reviewer_entries[-1]
            reviewer_step.input = json.dumps(rev_entry.get("input_json", {}), indent=2)
            out = rev_entry.get("output_json", {})
            reviewer_step.output = (
                f"Final Status: {out.get('final_status')}\n"
                f"Decision Reason: {rev_entry.get('decision_reason')}\n"
                f"Summary: {out.get('resolution_summary')}"
            )
        else:
            reviewer_step.output = f"Status validated: {ticket_detail.get('status', 'resolved')}"
        await reviewer_step.send()

        policy_step = cl.Step(name="📋 Policy Outcome", type="run", parent_id=pipeline_step.id, default_open=False)
        policy_step.output = outcome_line
        await policy_step.send()

        # Show the outcome on the COLLAPSED parent too, so it's visible without expanding.
        pipeline_step.output = outcome_line
        await pipeline_step.update()

    # ── Notifications (unchanged logic, just moved below the trimmed step block) ──
    cust_email = cl.user_session.get("customer_email")
    stat = (ticket_detail.get("status") or (resolve_res.get("status") if resolve_res else "") or "").lower()
    res_str = (ticket_detail.get("resolution") or (resolve_res.get("resolution") if resolve_res else "") or "").lower()
    if "refund" in res_str and stat == "resolved":
        email_tpl = "refund_issued"
    elif stat == "escalated":
        email_tpl = "escalated"
    else:
        email_tpl = "info_needed"

    await asyncio.to_thread(
        send_n8n_notification,
        ticket_id=ticket_id,
        template=email_tpl,
        customer_email=cust_email,
        source="customer_chat_resolution",
    )

    cust_name = cl.user_session.get("customer_name") or "Customer"
    await asyncio.to_thread(
        send_slack_notification,
        ticket_id=ticket_id,
        customer_name=str(cust_name),
        customer_email=str(cust_email or "customer@example.in"),
        user_message=message.content,
        status=stat,
        summary=ticket_detail.get("resolution") or f"Issue: {message.content[:80]}",
    )

    try:
        reply_text = await asyncio.to_thread(
            humanize,
            ticket=ticket_detail or resolve_res or {},
            order=latest_order,
            user_message=message.content,
            customer_name=str(cust_name),
        )
    except Exception as exc:
        logger.exception("Error humanizing reply: %s", exc)
        reply_text = "Thank you for contacting us. Your request is being reviewed by our support team."

    email_display = cust_email if cust_email else "your registered email"
    reply_text += (
        f"\n\n📧 *A confirmation and status update has also been sent to {email_display}.*"
        f"{render_policy_footer()}"
    )

    await cl.Message(content=reply_text).send()

    updated_order = await asyncio.to_thread(get_latest_order, customer_id)
    cl.user_session.set("latest_order", updated_order)