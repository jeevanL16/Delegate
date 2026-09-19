"""Executor stage — calls tools via LLM tool-use, enforcing policy at every step.

Every tool call is routed through the Policy Engine before touching the DB.
MAX_TOOL_CALLS_PER_TICKET is enforced here.

Uses OpenAI-compatible message format (Groq) — tool results are individual
{"role": "tool", "tool_call_id": ..., "content": "..."} messages.
"""
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

# Import with backward-compat aliases so test patches still work
from app.agent.llm_client import call_llm_tools as call_claude_tools
from app.agent.llm_client import extract_tool_calls
from app.agent.prompts import EXECUTOR_SYSTEM_PROMPT, TOOL_DEFINITIONS
from app.db.models import AuditLog, Ticket
from app.policy.engine import PolicyResult, check_tool_limit
from app.schemas.tool_io import RouterDecision
from app.tools.escalate_to_human import escalate_to_human
from app.tools.get_order_status import get_order_status
from app.tools.issue_refund import issue_refund
from app.tools.notify_customer import notify_customer
from app.tools.update_ticket_status import update_ticket_status

logger = logging.getLogger(__name__)


@dataclass
class ExecutorResult:
    actions_taken: list[dict] = field(default_factory=list)
    escalation_reason: str | None = None
    final_status: str = "open"


# ── Tool dispatch table ───────────────────────────────────────────────────────

TOOL_DISPATCH = {
    "get_order_status": get_order_status,
    "issue_refund": issue_refund,
    "update_ticket_status": update_ticket_status,
    "escalate_to_human": escalate_to_human,
    "notify_customer": notify_customer,
}


def run_executor(
    db: Session,
    ticket: Ticket,
    router_decision: RouterDecision,
) -> ExecutorResult:
    """
    Run the Executor stage using LLM tool-use (Groq / OpenAI-compatible format).

    If the Router said escalate_directly, we call escalate_to_human immediately
    without any LLM tool-use loop.
    """
    result = ExecutorResult()

    # ── Direct escalation (injection, unclear issue, etc.) ────────────────────
    if router_decision.escalate_directly:
        reason = router_decision.escalate_reason or "router_escalation"
        out = escalate_to_human(
            db=db,
            ticket_id=ticket.id,
            customer_id=ticket.customer_id,
            raw_input={
                "ticket_id": str(ticket.id),
                "reason": reason,
                "summary": router_decision.reasoning,
            },
        )
        result.actions_taken.append({"tool": "escalate_to_human", "result": out.model_dump()})
        result.escalation_reason = reason
        result.final_status = "escalated"
        return result

    # ── Build initial messages for LLM tool-use (OpenAI format) ──────────────
    # System prompt is passed separately inside call_claude_tools — messages list
    # contains ONLY user/assistant/tool roles.
    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"Process this customer support ticket.\n\n"
                f"Ticket ID: {ticket.id}\n"
                f"Customer ID: {ticket.customer_id}\n"
                f"Order ID: {ticket.order_id or 'none'}\n\n"
                f"Planned tools (in order): {', '.join(router_decision.tools_to_call)}\n\n"
                f"Router reasoning: {router_decision.reasoning}\n\n"
                f"Call the tools now, in the order listed, then stop."
            ),
        }
    ]

    tool_call_count = 0
    max_iterations = 10  # safety cap on the loop itself

    for _ in range(max_iterations):
        # ── Enforce tool call limit ───────────────────────────────────────────
        limit_check = check_tool_limit(db, ticket.id, tool_call_count)
        if limit_check.result == PolicyResult.ESCALATE:
            out = escalate_to_human(
                db=db,
                ticket_id=ticket.id,
                customer_id=ticket.customer_id,
                raw_input={
                    "ticket_id": str(ticket.id),
                    "reason": "tool_call_limit_exceeded",
                    "summary": f"Tool call limit ({tool_call_count}) reached during execution.",
                },
            )
            result.actions_taken.append({"tool": "escalate_to_human", "result": out.model_dump()})
            result.escalation_reason = "tool_call_limit_exceeded"
            result.final_status = "escalated"
            return result

        # ── Call LLM ─────────────────────────────────────────────────────────
        try:
            response = call_claude_tools(
                system_prompt=EXECUTOR_SYSTEM_PROMPT,
                messages=messages,
                tools=TOOL_DEFINITIONS,
            )
        except Exception as exc:
            logger.error("LLM call failed in executor ticket=%s: %s", ticket.id, exc)
            _force_escalate(db, ticket, result, "internal_error", str(exc))
            return result

        tool_calls = extract_tool_calls(response)

        # ── No more tool calls → done ─────────────────────────────────────────
        if not tool_calls:
            break

        # Append assistant message (includes tool_calls list in OpenAI format)
        messages.append(response.message)  # type: ignore[arg-type]

        # ── Execute each tool call, append result as individual tool messages ─
        for tc in tool_calls:
            tool_call_count += 1
            tool_name = tc["name"]
            tool_input = tc["input"]

            # Only dispatch to our known tools
            if tool_name not in TOOL_DISPATCH:
                logger.error("Model called unknown tool %s ticket=%s", tool_name, ticket.id)
                _force_escalate(db, ticket, result, "invalid_model_output", f"unknown_tool:{tool_name}")
                return result

            try:
                tool_fn = TOOL_DISPATCH[tool_name]
                tool_out = tool_fn(
                    db=db,
                    ticket_id=ticket.id,
                    customer_id=ticket.customer_id,
                    raw_input=tool_input,
                )
                tool_result_str = tool_out.model_dump_json()
                result.actions_taken.append({"tool": tool_name, "result": tool_out.model_dump()})

                # Track escalation from tools
                if tool_name == "escalate_to_human":
                    result.escalation_reason = tool_out.reason  # type: ignore[attr-defined]
                    result.final_status = "escalated"
                elif tool_name == "update_ticket_status":
                    result.final_status = tool_out.new_status  # type: ignore[attr-defined]

                # Check if a refund policy escalation was returned
                if tool_name == "issue_refund" and not tool_out.success:  # type: ignore[attr-defined]
                    if tool_out.policy_result == "escalate":  # type: ignore[attr-defined]
                        result.escalation_reason = tool_out.reason  # type: ignore[attr-defined]
                        result.final_status = "escalated"

            except Exception as exc:
                logger.error("Tool %s failed ticket=%s: %s", tool_name, ticket.id, exc)
                _force_escalate(db, ticket, result, "internal_error", f"tool_{tool_name}_error")
                return result

            # Append tool result in OpenAI format (one message per tool call)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": tool_result_str,
            })

        # If we've already escalated, stop the loop
        if result.final_status == "escalated":
            break

        # If LLM said end_turn with no tool calls, we're done
        if response.stop_reason == "end_turn":
            break

    return result


def _force_escalate(
    db: Session,
    ticket: Ticket,
    result: ExecutorResult,
    reason: str,
    detail: str,
) -> None:
    """Force escalation on any internal error — fail closed."""
    try:
        out = escalate_to_human(
            db=db,
            ticket_id=ticket.id,
            customer_id=ticket.customer_id,
            raw_input={
                "ticket_id": str(ticket.id),
                "reason": reason,
                "summary": f"System error during execution: {detail}",
            },
        )
        result.actions_taken.append({"tool": "escalate_to_human", "result": out.model_dump()})
    except Exception:
        pass  # Last resort — at least set the result flags
    result.escalation_reason = reason
    result.final_status = "escalated"
