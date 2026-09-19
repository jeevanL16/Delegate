"""
Delegate: Resolve — Customer Support Chat + Hidden Admin
Single-screen chatbot with hidden double-click admin access.
"""
import os
import json
import uuid
import time
import hashlib
import requests
import streamlit as st
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("SERVICE_API_KEY", "4a2c9f8e1d5b3a7c6e0f2d4b8a1c3e5f")
JWT_TOKEN = os.getenv("HUMAN_JWT_TOKEN", "")

if not JWT_TOKEN:
    try:
        from jose import jwt
        jwt_secret = os.getenv("HUMAN_JWT_SECRET", "7f9b2d4e6a8c0e1f3a5b7c9d1e3f5a7b9c1d3e5f7a9b1c3d5e7f9a1b3c5d7e9f")
        JWT_TOKEN = jwt.encode({"sub": "human-agent-demo", "role": "human_agent"}, jwt_secret, algorithm="HS256")
    except Exception:
        pass

HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
HUMAN_HEADERS = {"Authorization": f"Bearer {JWT_TOKEN}", "Content-Type": "application/json"}

# ── Admin PIN derived from HUMAN_JWT_SECRET (last 4 hex chars → 4-digit numeric PIN) ──
_jwt_secret_raw = os.getenv("HUMAN_JWT_SECRET", "7f9b2d4e6a8c0e1f3a5b7c9d1e3f5a7b9c1d3e5f7a9b1c3d5e7f9a1b3c5d7e9f")
_pin_hash = hashlib.sha256(_jwt_secret_raw.encode()).hexdigest()
ADMIN_PIN = str(int(_pin_hash[:8], 16) % 10000).zfill(4)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Delegate Support",
    page_icon="🎧",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

.main { background: #0a0a0f; }

/* Hide sidebar completely in chat mode */
section[data-testid="stSidebar"] { display: none !important; }
button[data-testid="stSidebarCollapsedControl"] { display: none !important; }

/* Hero header */
.hero-title {
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #a78bfa 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-size: 2.4rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    margin: 0;
    line-height: 1.1;
}
.hero-sub {
    color: #94a3b8;
    font-size: 0.95rem;
    margin-top: 0.3rem;
}

/* Stage card */
.stage-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 1rem 1.25rem;
    margin: 0.5rem 0;
    transition: all 0.2s;
}
.stage-card:hover {
    border-color: rgba(99,102,241,0.4);
    background: rgba(99,102,241,0.06);
}
.stage-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.badge-analyzer  { background: rgba(59,130,246,0.2); color: #60a5fa; border: 1px solid rgba(59,130,246,0.3); }
.badge-router    { background: rgba(168,85,247,0.2); color: #c084fc; border: 1px solid rgba(168,85,247,0.3); }
.badge-executor  { background: rgba(245,158,11,0.2); color: #fbbf24; border: 1px solid rgba(245,158,11,0.3); }
.badge-reviewer  { background: rgba(16,185,129,0.2); color: #34d399; border: 1px solid rgba(16,185,129,0.3); }
.badge-policy    { background: rgba(239,68,68,0.2);  color: #f87171; border: 1px solid rgba(239,68,68,0.3); }

/* Tool call card */
.tool-card {
    background: rgba(245,158,11,0.06);
    border: 1px solid rgba(245,158,11,0.2);
    border-radius: 10px;
    padding: 0.8rem 1rem;
    margin: 0.4rem 0;
    font-size: 0.85rem;
}
.tool-name {
    color: #fbbf24;
    font-weight: 700;
    font-size: 0.9rem;
}

/* Result banner */
.result-resolved {
    background: linear-gradient(135deg, rgba(16,185,129,0.15) 0%, rgba(5,150,105,0.1) 100%);
    border: 2px solid rgba(16,185,129,0.4);
    border-radius: 16px;
    padding: 1.25rem 1.5rem;
    text-align: center;
}
.result-escalated {
    background: linear-gradient(135deg, rgba(245,158,11,0.15) 0%, rgba(217,119,6,0.1) 100%);
    border: 2px solid rgba(245,158,11,0.4);
    border-radius: 16px;
    padding: 1.25rem 1.5rem;
    text-align: center;
}
.result-injection {
    background: linear-gradient(135deg, rgba(239,68,68,0.15) 0%, rgba(185,28,28,0.1) 100%);
    border: 2px solid rgba(239,68,68,0.5);
    border-radius: 16px;
    padding: 1.25rem 1.5rem;
    text-align: center;
}

/* Stats pill */
.stat-pill {
    display: inline-block;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    padding: 0.6rem 1rem;
    text-align: center;
    margin: 0.3rem;
}

.usd-amount { color: #10b981; font-weight: 700; font-family: monospace; }
.escalated-badge { color: #fbbf24; }
.resolved-badge  { color: #10b981; }
.injection-badge { color: #ef4444; }

/* Support Chat Styling */
.chat-header {
    background: linear-gradient(135deg, rgba(30, 30, 46, 0.9) 0%, rgba(37, 37, 56, 0.9) 100%);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 14px;
    padding: 0.85rem 1.25rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.75rem;
    cursor: default;
    user-select: none;
}
.chat-agent-info {
    display: flex;
    align-items: center;
    gap: 0.85rem;
}
.chat-avatar {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    background: linear-gradient(135deg, #0ea5e9 0%, #6366f1 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.35rem;
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}
.chat-title {
    font-weight: 700;
    font-size: 1.15rem;
    color: #f8fafc;
    margin: 0;
    line-height: 1.2;
}
.chat-subtitle {
    font-size: 0.8rem;
    color: #94a3b8;
    margin: 0;
}
.chat-online-badge {
    background: rgba(16, 185, 129, 0.15);
    color: #10b981;
    border: 1px solid rgba(16, 185, 129, 0.3);
    border-radius: 20px;
    padding: 0.25rem 0.65rem;
    font-size: 0.75rem;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 0.35rem;
}
.order-chip {
    background: rgba(99, 102, 241, 0.08);
    border: 1px solid rgba(99, 102, 241, 0.25);
    border-radius: 10px;
    padding: 0.45rem 0.85rem;
    margin-bottom: 1rem;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.82rem;
    color: #c7d2fe;
}

/* Admin view */
.admin-header {
    background: linear-gradient(135deg, rgba(239,68,68,0.08) 0%, rgba(168,85,247,0.08) 100%);
    border: 1px solid rgba(239,68,68,0.2);
    border-radius: 14px;
    padding: 1rem 1.5rem;
    margin-bottom: 1rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.admin-title {
    color: #f87171;
    font-size: 1.3rem;
    font-weight: 800;
    letter-spacing: -0.02em;
}
.admin-subtitle {
    color: #94a3b8;
    font-size: 0.78rem;
}
.ticket-row {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 1rem 1.25rem;
    margin: 0.5rem 0;
}
.ticket-row:hover {
    border-color: rgba(99,102,241,0.3);
}
.pin-container {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 16px;
    padding: 2rem;
    max-width: 380px;
    margin: 3rem auto;
    text-align: center;
}
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_inr(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"₹{cents/100:,.2f}"

fmt_usd = fmt_inr


def api_get(path: str, human: bool = False) -> Any:
    try:
        h = HUMAN_HEADERS if human else HEADERS
        r = requests.get(f"{API_BASE}{path}", headers=h, timeout=10)
        if r.ok:
            return r.json()
        st.error(f"API {r.status_code}: {r.text[:200]}")
    except requests.exceptions.ConnectionError:
        st.error("⚠️ Cannot connect to API. Is `uvicorn app.main:app` running?")
    return None


def api_post(path: str, payload: dict, human: bool = False) -> Any:
    try:
        h = HUMAN_HEADERS if human else HEADERS
        r = requests.post(f"{API_BASE}{path}", json=payload, headers=h, timeout=120)
        if r.ok:
            return r.json()
        st.error(f"API {r.status_code}: {r.text[:300]}")
    except requests.exceptions.ConnectionError:
        st.error("⚠️ Cannot connect to API. Is `uvicorn app.main:app` running?")
    return None


def render_stage_badge(stage: str) -> str:
    return f'<span class="stage-badge badge-{stage}">{stage}</span>'


def render_audit_entry(entry: dict) -> None:
    stage = entry.get("stage", "")
    action = entry.get("action", "")
    reason = entry.get("decision_reason", "")
    ts = entry.get("created_at", "")[:19].replace("T", " ")

    st.markdown(f"""
    <div class="stage-card">
        {render_stage_badge(stage)}
        <strong style="color:#e2e8f0; margin-left:0.5rem;">{action}</strong>
        <span style="color:#64748b; float:right; font-size:0.75rem;">{ts}</span>
        <div style="color:#94a3b8; font-size:0.82rem; margin-top:0.4rem;">Reason: <code style="color:#a78bfa;">{reason}</code></div>
    </div>
    """, unsafe_allow_html=True)

    out = entry.get("output_json")
    if out:
        with st.expander("📦 Output JSON", expanded=False):
            st.json(out)


def render_action_card(action: dict) -> None:
    tool = action.get("tool", "")
    result = action.get("result", {})
    st.markdown(f"""
    <div class="tool-card">
        🔧 <span class="tool-name">{tool}</span>
    </div>
    """, unsafe_allow_html=True)
    with st.expander(f"Result: {tool}", expanded=False):
        st.json(result)


def send_n8n_notification(ticket_id: str, template: str = "escalated") -> bool:
    """Fire a manual notification through the n8n webhook (best-effort)."""
    n8n_url = os.getenv("N8N_WEBHOOK_URL", "")
    n8n_secret = os.getenv("N8N_WEBHOOK_SECRET", "")
    if not n8n_url:
        return False
    try:
        headers_n8n: dict[str, str] = {"Content-Type": "application/json"}
        if n8n_secret:
            headers_n8n["X-Delegate-Secret"] = n8n_secret
        payload = {
            "type": "notify_customer",
            "ticket_id": ticket_id,
            "template": template,
            "source": "admin_manual_resend",
        }
        resp = requests.post(n8n_url, json=payload, headers=headers_n8n, timeout=5)
        return resp.ok
    except Exception:
        return False


# ── Dynamic Seed Data Loading ──────────────────────────────────────────────────
def load_seed_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        base_dir = os.path.dirname(__file__)
        customers_path = os.path.join(base_dir, "..", "seed", "customers.json")
        orders_path = os.path.join(base_dir, "..", "seed", "orders.json")
        if os.path.exists(customers_path) and os.path.exists(orders_path):
            with open(customers_path, encoding="utf-8") as f:
                customers: list[dict[str, Any]] = json.load(f)
            with open(orders_path, encoding="utf-8") as f:
                orders: list[dict[str, Any]] = json.load(f)
            for o in orders:
                if "label" not in o:
                    amount_str = f"₹{o['amount_cents']/100:.2f}"
                    note = o.get("note", o.get("status", ""))
                    if note.startswith("$") or note.startswith("₹"):
                        parts = note.split("—", 1)
                        if len(parts) > 1:
                            note = parts[1].strip()
                    o["label"] = f"{amount_str} — {note}"
            return customers, orders
    except Exception:
        pass
    fallback_customers: list[dict[str, Any]] = [
        {"id": "11111111-1111-1111-1111-111111111111", "name": "Arjun Sharma", "email": "arjun.sharma@example.in", "tier": "regular", "flags": []},
        {"id": "22222222-2222-2222-2222-222222222222", "name": "Priya Nair", "email": "priya.nair@example.in", "tier": "vip", "flags": []},
        {"id": "33333333-3333-3333-3333-333333333333", "name": "Rohit Mehta", "email": "rohit.mehta@example.in", "tier": "regular", "flags": ["repeat_complainer"]},
        {"id": "44444444-4444-4444-4444-444444444444", "name": "Deepa Krishnan", "email": "deepa.k@example.in", "tier": "regular", "flags": []},
        {"id": "55555555-5555-5555-5555-555555555555", "name": "Vikram Patel", "email": "vikram.patel@example.in", "tier": "regular", "flags": []},
    ]
    fallback_orders: list[dict[str, Any]] = [
        {"id": "aaaa0001-0000-0000-0000-000000000001", "customer_id": "11111111-1111-1111-1111-111111111111", "amount_cents": 4990, "status": "refunded", "label": "₹49.90 — already refunded"},
        {"id": "aaaa0002-0000-0000-0000-000000000002", "customer_id": "11111111-1111-1111-1111-111111111111", "amount_cents": 8990, "status": "failed", "label": "₹89.90 — payment failed"},
        {"id": "aaaa0003-0000-0000-0000-000000000003", "customer_id": "22222222-2222-2222-2222-222222222222", "amount_cents": 4990, "status": "delivered", "label": "₹49.90 — delivered (VIP)"},
        {"id": "aaaa0004-0000-0000-0000-000000000004", "customer_id": "44444444-4444-4444-4444-444444444444", "amount_cents": 150000, "status": "failed", "label": "₹1,500.00 — over cap"},
        {"id": "aaaa0005-0000-0000-0000-000000000005", "customer_id": "55555555-5555-5555-5555-555555555555", "amount_cents": 3490, "status": "delivered", "label": "₹34.90 — Vikram's order"},
        {"id": "aaaa0006-0000-0000-0000-000000000006", "customer_id": "33333333-3333-3333-3333-333333333333", "amount_cents": 7500, "status": "failed", "label": "₹75.00 — repeat complainer"},
        {"id": "aaaa0007-0000-0000-0000-000000000007", "customer_id": "11111111-1111-1111-1111-111111111111", "amount_cents": 29990, "status": "delivered", "label": "₹299.90 — delivered"},
    ]
    return fallback_customers, fallback_orders

SEED_CUSTOMERS, SEED_ORDERS = load_seed_data()

# Build customer lookup for admin view
CUSTOMER_MAP: dict[str, dict[str, Any]] = {c["id"]: c for c in SEED_CUSTOMERS}


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE INITIALIZATION
# ══════════════════════════════════════════════════════════════════════════════

if "admin_mode" not in st.session_state:
    st.session_state["admin_mode"] = False
if "admin_authenticated" not in st.session_state:
    st.session_state["admin_authenticated"] = False
if "admin_click_ts" not in st.session_state:
    st.session_state["admin_click_ts"] = 0.0
if "pin_attempts" not in st.session_state:
    st.session_state["pin_attempts"] = 0


# ══════════════════════════════════════════════════════════════════════════════
# ROUTING: Chat vs Admin
# ══════════════════════════════════════════════════════════════════════════════

# Check for query param admin trigger
qp = st.query_params
if qp.get("admin") == "1" and not st.session_state["admin_mode"]:
    st.session_state["admin_mode"] = True


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN VIEW — PIN Gate + Merged Conversations & Escalation Queue
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state["admin_mode"]:
    # ── PIN Authentication Gate ───────────────────────────────────────────────
    if not st.session_state["admin_authenticated"]:
        st.markdown("""
        <div class="pin-container">
            <div style="font-size:2.5rem; margin-bottom:0.5rem;">🔐</div>
            <div style="color:#e2e8f0; font-size:1.1rem; font-weight:700; margin-bottom:0.3rem;">Admin Access</div>
            <div style="color:#64748b; font-size:0.82rem; margin-bottom:1.5rem;">Enter the 4-digit PIN to continue</div>
        </div>
        """, unsafe_allow_html=True)

        col_l, col_pin, col_r = st.columns([1, 1.5, 1])
        with col_pin:
            pin_input = st.text_input(
                "PIN",
                type="password",
                max_chars=4,
                placeholder="• • • •",
                key="admin_pin_input",
                label_visibility="collapsed",
            )
            col_sub, col_back = st.columns(2)
            with col_sub:
                if st.button("🔓 Unlock", type="primary", use_container_width=True):
                    if pin_input == ADMIN_PIN:
                        st.session_state["admin_authenticated"] = True
                        st.session_state["pin_attempts"] = 0
                        st.rerun()
                    else:
                        st.session_state["pin_attempts"] += 1
                        if st.session_state["pin_attempts"] >= 5:
                            st.session_state["admin_mode"] = False
                            st.session_state["pin_attempts"] = 0
                            st.query_params.clear()
                            st.rerun()
                        st.error(f"❌ Incorrect PIN ({5 - st.session_state['pin_attempts']} attempts remaining)")
            with col_back:
                if st.button("← Back", use_container_width=True):
                    st.session_state["admin_mode"] = False
                    st.session_state["pin_attempts"] = 0
                    st.query_params.clear()
                    st.rerun()
        st.stop()

    # ══════════════════════════════════════════════════════════════════════════
    # ADMIN VIEW — Authenticated
    # ══════════════════════════════════════════════════════════════════════════

    # ── Admin Header ──────────────────────────────────────────────────────────
    st.markdown("""
    <div class="admin-header">
        <div>
            <div class="admin-title">🛡️ Admin Console</div>
            <div class="admin-subtitle">Conversations · Escalation Queue · Notifications</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_back, col_refresh, col_logout = st.columns([1, 1, 1])
    with col_back:
        if st.button("← Back to Chat", use_container_width=True):
            st.session_state["admin_mode"] = False
            st.session_state["admin_authenticated"] = False
            st.query_params.clear()
            st.rerun()
    with col_refresh:
        if st.button("🔄 Refresh", use_container_width=True, key="admin_refresh"):
            st.rerun()
    with col_logout:
        if st.button("🚪 Logout Admin", use_container_width=True):
            st.session_state["admin_mode"] = False
            st.session_state["admin_authenticated"] = False
            st.query_params.clear()
            st.rerun()

    # ── Section 1: Escalated Queue ────────────────────────────────────────────
    st.markdown("---")
    st.markdown("""
    <div style="margin-bottom:0.5rem;">
        <span style="font-size:1.2rem; font-weight:800; color:#fbbf24;">⚠️ Escalated Queue</span>
        <span style="color:#64748b; font-size:0.82rem; margin-left:0.5rem;">Tickets awaiting human review</span>
    </div>
    """, unsafe_allow_html=True)

    queue = api_get("/human/queue", human=True) or []

    if not queue:
        st.success("🎉 Queue is empty — no escalated tickets pending review.")
    else:
        st.markdown(f"**{len(queue)} ticket(s) awaiting review**")

        for ticket in queue:
            tid = ticket["id"]
            detail = api_get(f"/human/tickets/{tid}", human=True)

            # Get last escalation reason from audit trail
            audit = detail.get("audit_trail", []) if detail else []
            escalation_reason = "—"
            for entry in reversed(audit):
                if "escalat" in entry.get("decision_reason", "").lower():
                    escalation_reason = entry["decision_reason"]
                    break

            # Resolve customer name
            cust_id_str = str(ticket.get("customer_id", ""))
            cust_info = CUSTOMER_MAP.get(cust_id_str, {})
            cust_name = cust_info.get("name", cust_id_str[:8] + "…")

            inj = ticket.get("suspected_injection", False)
            border = "rgba(239,68,68,0.4)" if inj else "rgba(245,158,11,0.3)"
            icon = "🛡️" if inj else "⚠️"

            st.markdown(f"""
            <div style="background:rgba(255,255,255,0.03); border:1px solid {border};
                        border-radius:14px; padding:1.2rem 1.5rem; margin:0.8rem 0;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        {icon} <strong style="color:#e2e8f0;">{tid[:8]}…</strong>
                        <span style="color:#c7d2fe; margin-left:0.5rem;">{cust_name}</span>
                        {'<span style="color:#ef4444; font-size:0.8rem; margin-left:0.5rem;"> INJECTION FLAG</span>' if inj else ''}
                    </div>
                    <span style="color:#64748b; font-size:0.8rem;">{ticket['created_at'][:19]}</span>
                </div>
                <div style="color:#94a3b8; margin-top:0.5rem; font-size:0.85rem;">
                    Issue: <code>{ticket.get('issue_type','—')}</code> ·
                    Escalation: <code style="color:#fbbf24;">{escalation_reason}</code>
                </div>
            </div>
            """, unsafe_allow_html=True)

            with st.expander(f"📋 Details & Actions — {tid[:8]}…"):
                if detail:
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown("**Ticket text (untrusted):**")
                        st.markdown(f"> {detail['raw_text'][:400]}{'…' if len(detail.get('raw_text','')) > 400 else ''}")

                    with col_b:
                        st.markdown("**Audit Trail:**")
                        for entry in detail.get("audit_trail", [])[-6:]:
                            render_audit_entry(entry)

                st.divider()

                # ── Action buttons ────────────────────────────────────────
                if not inj:
                    col_approve, col_close, col_notify = st.columns(3)
                    with col_approve:
                        note_approve = st.text_input("Note (approve)", key=f"note_a_{tid}", placeholder="Reason for approving refund")
                        if st.button("✅ Issue Refund", key=f"approve_{tid}", type="primary"):
                            if note_approve:
                                resp = api_post(
                                    f"/human/tickets/{tid}/approve",
                                    {"action": "issue_refund", "note": note_approve},
                                    human=True,
                                )
                                if resp:
                                    st.success(f"Refund issued! {resp}")
                                    time.sleep(1)
                                    st.rerun()
                            else:
                                st.warning("Please enter a note.")
                    with col_close:
                        note_close = st.text_input("Note (close)", key=f"note_c_{tid}", placeholder="Reason for closing")
                        if st.button("🚫 Close Without Action", key=f"close_{tid}"):
                            if note_close:
                                resp = api_post(
                                    f"/human/tickets/{tid}/approve",
                                    {"action": "close_no_action", "note": note_close},
                                    human=True,
                                )
                                if resp:
                                    st.success(f"Ticket closed. {resp}")
                                    time.sleep(1)
                                    st.rerun()
                            else:
                                st.warning("Please enter a note.")
                    with col_notify:
                        notify_template = st.selectbox(
                            "Notification template",
                            ["escalated", "refund_issued", "info_needed"],
                            key=f"notify_tpl_{tid}",
                        )
                        if st.button("📧 Send Notification", key=f"notify_{tid}"):
                            ok = send_n8n_notification(tid, notify_template)
                            if ok:
                                st.success("📧 Notification sent via n8n!")
                            else:
                                st.warning("⚠️ n8n webhook not configured or failed.")
                else:
                    st.error("🛡️ This ticket was flagged for prompt injection. Review carefully.")
                    col_close_inj, col_notify_inj = st.columns(2)
                    with col_close_inj:
                        note_close = st.text_input("Note (close injection ticket)", key=f"note_inj_{tid}")
                        if st.button("🚫 Close Injection Ticket", key=f"close_inj_{tid}"):
                            if note_close:
                                api_post(f"/human/tickets/{tid}/approve", {"action": "close_no_action", "note": note_close}, human=True)
                                st.rerun()
                    with col_notify_inj:
                        if st.button("📧 Notify Customer", key=f"notify_inj_{tid}"):
                            ok = send_n8n_notification(tid, "escalated")
                            if ok:
                                st.success("📧 Notification sent!")
                            else:
                                st.warning("⚠️ n8n webhook not configured or failed.")

    # ── Section 2: All Conversations ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("""
    <div style="margin-bottom:0.5rem;">
        <span style="font-size:1.2rem; font-weight:800; color:#a78bfa;">📂 All Conversations</span>
        <span style="color:#64748b; font-size:0.82rem; margin-left:0.5rem;">Every ticket with full pipeline detail</span>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([2, 1])
    with col1:
        filter_status = st.selectbox("Filter by status", ["all", "open", "resolved", "escalated"], key="admin_filter_status")

    path = "/tickets" + (f"?status={filter_status}" if filter_status != "all" else "")
    tickets_list = api_get(path) or []

    if tickets_list:
        for t in tickets_list[:30]:
            status_icon = {"resolved": "✅", "escalated": "⚠️", "open": "🔵"}.get(t["status"], "❓")
            inj_badge = " 🛡️ INJECTION" if t.get("suspected_injection") else ""

            # Resolve customer name
            cust_id_str = str(t.get("customer_id", ""))
            cust_info = CUSTOMER_MAP.get(cust_id_str, {})
            cust_name = cust_info.get("name", cust_id_str[:8] + "…")

            with st.expander(f"{status_icon} `{t['id'][:8]}…` · {cust_name} · {t['status'].upper()}{inj_badge} · {t.get('issue_type','—')}"):
                st.caption(f"Customer: **{cust_name}** (`{cust_id_str[:8]}…`) · Created: {t['created_at'][:19]}")

                detail = api_get(f"/tickets/{t['id']}")
                if detail:
                    col_msg, col_trail = st.columns(2)
                    with col_msg:
                        st.markdown("**Customer Message:**")
                        st.markdown(f"> {detail.get('raw_text', '—')[:500]}")
                        if detail.get("resolution"):
                            st.markdown(f"**Resolution:** {detail['resolution']}")

                    with col_trail:
                        st.markdown("**Audit Trail:**")
                        for entry in detail.get("audit_trail", [])[-8:]:
                            render_audit_entry(entry)

                    # Notification resend for any ticket
                    if st.button("📧 Re-send Notification", key=f"conv_notify_{t['id']}"):
                        tpl = "refund_issued" if t["status"] == "resolved" else "escalated"
                        ok = send_n8n_notification(t["id"], tpl)
                        if ok:
                            st.success("📧 Notification sent!")
                        else:
                            st.warning("⚠️ n8n webhook not configured or failed.")
    else:
        st.info("No tickets found.")


# ══════════════════════════════════════════════════════════════════════════════
# CHAT VIEW — Default single-screen customer chatbot
# ══════════════════════════════════════════════════════════════════════════════

else:
    # ── Switch Demo Customer (Collapsed at very top) ──────────────────────────
    with st.expander("⚙️ Switch demo customer", expanded=False):
        cust_labels = [f"{c['name']} ({str(c['tier']).upper()}{' ⚠' if c.get('flags') else ''}) · {c['email']}" for c in SEED_CUSTOMERS]
        active_cust_idx = st.selectbox(
            "Demo Customer Profile",
            range(len(SEED_CUSTOMERS)),
            format_func=lambda i: cust_labels[i],
            key="chat_customer_picker",
        )
        current_customer = SEED_CUSTOMERS[active_cust_idx]
        st.caption(f"Currently simulating customer: **{current_customer['name']}** (`{current_customer['email']}`).")

    current_customer = SEED_CUSTOMERS[st.session_state.get("chat_customer_picker", 0)]
    customer_id = current_customer["id"]

    # Reset chat history if user switches demo customer
    if st.session_state.get("chat_active_cust_id") != customer_id:
        st.session_state["chat_active_cust_id"] = customer_id
        first_name = current_customer["name"].split()[0]
        st.session_state["chat_messages"] = [
            {
                "role": "assistant",
                "content": f"Hi {first_name}! 👋 Welcome to Delegate Support. How can I help you today?",
                "timestamp": datetime.now().strftime("%I:%M %p"),
            }
        ]

    # Find customer's latest relevant order
    cust_orders = [o for o in SEED_ORDERS if o["customer_id"] == customer_id]
    latest_order = cust_orders[0] if cust_orders else None

    # ── Paytm-style Top Header Bar (with hidden double-click admin trigger) ───
    # The header is rendered as HTML. The double-click detection uses a Streamlit
    # button that tracks rapid clicks via session_state timestamps.

    st.markdown("""
    <div class="chat-header" id="chat-header-dblclick">
        <div class="chat-agent-info">
            <div class="chat-avatar">🎧</div>
            <div>
                <div class="chat-title">Delegate Support</div>
                <div class="chat-subtitle">Usually replies in seconds</div>
            </div>
        </div>
        <div class="chat-online-badge">
            <span>●</span> Online
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Hidden double-click detector ──────────────────────────────────────────
    # Tiny JS component that detects double-click on the chat header and
    # triggers a Streamlit rerun with ?admin=1 query param.
    st.iframe("""
    <script>
    (function() {
        // Find the chat header by its ID in the parent document
        const parentDoc = window.parent.document;
        const header = parentDoc.getElementById('chat-header-dblclick');
        if (header && !header._dblClickBound) {
            header._dblClickBound = true;
            header.style.cursor = 'default';
            header.addEventListener('dblclick', function(e) {
                e.preventDefault();
                // Navigate with admin query param to trigger admin mode
                const url = new URL(window.parent.location.href);
                url.searchParams.set('admin', '1');
                window.parent.location.href = url.toString();
            });
        }
    })();
    </script>
    """, height=0)

    # ── Compact Order Context Chip ────────────────────────────────────────────
    if latest_order:
        status_colors = {
            "failed": "#ef4444",
            "refunded": "#10b981",
            "delivered": "#3b82f6",
            "pending": "#f59e0b",
        }
        status_clr = status_colors.get(latest_order.get("status", ""), "#94a3b8")
        order_short_id = latest_order['id'][:8]
        order_amt = fmt_usd(int(latest_order['amount_cents']))
        order_stat = str(latest_order['status']).capitalize()

        st.markdown(f"""
        <div class="order-chip">
            <span>📦</span>
            <span><strong>Order #{order_short_id}…</strong> · {order_amt} · <span style="color:{status_clr}; font-weight:600;">{order_stat}</span></span>
        </div>
        """, unsafe_allow_html=True)

    # ── Chat Messages Body ────────────────────────────────────────────────────
    chat_box = st.container()
    with chat_box:
        for m in st.session_state.get("chat_messages", []):
            avatar_icon = "🎧" if m["role"] == "assistant" else "👤"
            with st.chat_message(m["role"], avatar=avatar_icon):
                st.write(m["content"])
                if "timestamp" in m:
                    st.caption(f"<span style='font-size:0.7rem; color:#64748b;'>{m['timestamp']}</span>", unsafe_allow_html=True)

    # ── Chat Input & Live Resolution ──────────────────────────────────────────
    chat_prompt = st.chat_input("Type your message…")
    if chat_prompt and chat_prompt.strip():
        user_text = chat_prompt.strip()
        time_now = datetime.now().strftime("%I:%M %p")

        st.session_state["chat_messages"].append({
            "role": "user",
            "content": user_text,
            "timestamp": time_now,
        })

        with chat_box:
            with st.chat_message("user", avatar="👤"):
                st.write(user_text)
                st.caption(f"<span style='font-size:0.7rem; color:#64748b;'>{time_now}</span>", unsafe_allow_html=True)

            with st.chat_message("assistant", avatar="🎧"):
                with st.spinner("Delegate is typing…"):
                    payload: dict[str, Any] = {
                        "customer_id": customer_id,
                        "raw_text": user_text,
                    }
                    if latest_order:
                        payload["order_id"] = latest_order["id"]

                    ticket_response = api_post("/tickets", payload)
                    if ticket_response and "ticket_id" in ticket_response:
                        t_id = ticket_response["ticket_id"]
                        resolve_result = api_post(f"/tickets/{t_id}/resolve", {})
                        if resolve_result:
                            res_stat = resolve_result.get("status", "unknown")
                            if res_stat == "resolved":
                                natural_res = resolve_result.get("resolution", "")
                                reply_text = natural_res if natural_res else "Your request has been resolved. Please let us know if you need anything else!"
                            elif res_stat == "escalated":
                                reply_text = "Thanks for your patience — I've looped in a specialist on our priority team, and they will follow up with you via email shortly."
                            else:
                                reply_text = "Thank you for contacting us. We have received your message and our team is reviewing it."
                        else:
                            reply_text = "I'm experiencing a brief connection delay. Please try sending your message again."
                    else:
                        reply_text = "Unable to process your request at this moment. Please check your connection and try again."

                st.write(reply_text)
                reply_time = datetime.now().strftime("%I:%M %p")
                st.caption(f"<span style='font-size:0.7rem; color:#64748b;'>{reply_time}</span>", unsafe_allow_html=True)

        st.session_state["chat_messages"].append({
            "role": "assistant",
            "content": reply_text,
            "timestamp": reply_time,
        })
        st.rerun()
