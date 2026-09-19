"""
ui/api_client.py
HTTP API client for communicating with the Delegate: Resolve backend service.
Provides typed access to ticket workflows, human escalation queue, customer data, and n8n notifications.
"""

import json
import logging
import os
from typing import Any, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
SERVICE_API_KEY = os.getenv("SERVICE_API_KEY", "4a2c9f8e1d5b3a7c6e0f2d4b8a1c3e5f")
HUMAN_JWT_SECRET = os.getenv("HUMAN_JWT_SECRET", "7f9b2d4e6a8c0e1f3a5b7c9d1e3f5a7b9c1d3e5f7a9b1c3d5e7f9a1b3c5d7e9f")
HUMAN_JWT_TOKEN = os.getenv("HUMAN_JWT_TOKEN", "")

if not HUMAN_JWT_TOKEN:
    try:
        from jose import jwt
        HUMAN_JWT_TOKEN = jwt.encode(
            {"sub": "human-agent-staff", "role": "human_agent"},
            HUMAN_JWT_SECRET,
            algorithm="HS256",
        )
    except Exception as exc:
        logger.warning("Could not generate HUMAN_JWT_TOKEN: %s", exc)


def _get_api_headers() -> dict[str, str]:
    return {
        "X-API-Key": SERVICE_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _get_human_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {HUMAN_JWT_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ── Customer and Order Data Access ──────────────────────────────────────────

def get_customers() -> list[dict[str, Any]]:
    """
    Fetch customers dynamically from DB if available, falling back to seed JSON.
    """
    # 1. Attempt reading from DB via SessionLocal
    try:
        from app.db.session import SessionLocal
        from app.db.models import Customer
        with SessionLocal() as db:
            customers = db.query(Customer).order_by(Customer.name).all()
            if customers:
                return [
                    {
                        "id": str(c.id),
                        "name": c.name,
                        "email": c.email,
                        "tier": c.tier,
                        "flags": c.flags or [],
                    }
                    for c in customers
                ]
    except Exception as exc:
        logger.debug("Could not read customers directly from DB session: %s", exc)

    # 2. Fallback to seed/customers.json
    try:
        seed_path = os.path.join(os.path.dirname(__file__), "..", "seed", "customers.json")
        if os.path.exists(seed_path):
            with open(seed_path, encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        logger.warning("Could not load seed/customers.json: %s", exc)

    # 3. Static fallback
    return [
        {"id": "11111111-1111-1111-1111-111111111111", "name": "Arjun Sharma", "email": "arjun.sharma@example.in", "tier": "regular", "flags": []},
        {"id": "22222222-2222-2222-2222-222222222222", "name": "Priya Nair", "email": "priya.nair@example.in", "tier": "vip", "flags": []},
        {"id": "33333333-3333-3333-3333-333333333333", "name": "Rohit Mehta", "email": "rohit.mehta@example.in", "tier": "regular", "flags": ["repeat_complainer"]},
        {"id": "44444444-4444-4444-4444-444444444444", "name": "Deepa Krishnan", "email": "deepa.k@example.in", "tier": "regular", "flags": []},
        {"id": "55555555-5555-5555-5555-555555555555", "name": "Vikram Patel", "email": "vikram.patel@example.in", "tier": "regular", "flags": []},
    ]


def get_customer_orders(customer_id: str) -> list[dict[str, Any]]:
    """Fetch orders for a given customer."""
    try:
        from app.db.session import SessionLocal
        from app.db.models import Order
        import uuid
        with SessionLocal() as db:
            orders = (
                db.query(Order)
                .filter(Order.customer_id == uuid.UUID(customer_id))
                .order_by(Order.created_at.desc())
                .all()
            )
            if orders:
                return [
                    {
                        "id": str(o.id),
                        "customer_id": str(o.customer_id),
                        "amount_cents": o.amount_cents,
                        "status": o.status,
                        "created_at": o.created_at.isoformat() if o.created_at else None,
                    }
                    for o in orders
                ]
    except Exception as exc:
        logger.debug("Could not read orders from DB: %s", exc)

    # Fallback to seed/orders.json
    try:
        seed_path = os.path.join(os.path.dirname(__file__), "..", "seed", "orders.json")
        if os.path.exists(seed_path):
            with open(seed_path, encoding="utf-8") as f:
                all_orders = json.load(f)
                return [o for o in all_orders if str(o.get("customer_id")) == customer_id]
    except Exception as exc:
        logger.warning("Could not read seed/orders.json: %s", exc)

    return []


def get_latest_order(customer_id: str) -> Optional[dict[str, Any]]:
    """Return customer's latest order if present."""
    orders = get_customer_orders(customer_id)
    return orders[0] if orders else None


# ── Ticket Operations (FastAPI Routes) ────────────────────────────────────────

def create_ticket(customer_id: str, raw_text: str, order_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Call POST /tickets to create a new ticket."""
    url = f"{API_BASE_URL}/tickets"
    payload: dict[str, Any] = {
        "customer_id": customer_id,
        "raw_text": raw_text,
    }
    if order_id:
        payload["order_id"] = order_id

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json=payload, headers=_get_api_headers())
            if resp.status_code in (200, 201):
                return resp.json()
            logger.error("POST /tickets failed (%s): %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.exception("Error calling POST /tickets: %s", exc)
    return None


def resolve_ticket(ticket_id: str) -> Optional[dict[str, Any]]:
    """Call POST /tickets/{ticket_id}/resolve."""
    url = f"{API_BASE_URL}/tickets/{ticket_id}/resolve"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json={}, headers=_get_api_headers())
            if resp.status_code == 200:
                return resp.json()
            logger.error("POST /tickets/%s/resolve failed (%s): %s", ticket_id, resp.status_code, resp.text)
    except Exception as exc:
        logger.exception("Error calling POST /tickets/%s/resolve: %s", ticket_id, exc)
    return None


def get_ticket(ticket_id: str) -> Optional[dict[str, Any]]:
    """Call GET /tickets/{ticket_id} to fetch full details including audit_trail."""
    url = f"{API_BASE_URL}/tickets/{ticket_id}"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=_get_api_headers())
            if resp.status_code == 200:
                return resp.json()
            logger.error("GET /tickets/%s failed (%s): %s", ticket_id, resp.status_code, resp.text)
    except Exception as exc:
        logger.exception("Error calling GET /tickets/%s: %s", ticket_id, exc)
    return None


# ── Staff / Human Queue Operations ────────────────────────────────────────────

def get_human_queue() -> list[dict[str, Any]]:
    """Call GET /human/queue using JWT Bearer token."""
    url = f"{API_BASE_URL}/human/queue"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=_get_human_headers())
            if resp.status_code == 200:
                return resp.json()
            logger.error("GET /human/queue failed (%s): %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.exception("Error calling GET /human/queue: %s", exc)
    return []


def approve_human_ticket(ticket_id: str, action: str, note: str = "") -> Optional[dict[str, Any]]:
    """
    Call POST /human/tickets/{ticket_id}/approve.
    action: "issue_refund" | "close_no_action"
    """
    url = f"{API_BASE_URL}/human/tickets/{ticket_id}/approve"
    payload = {"action": action, "note": note}
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json=payload, headers=_get_human_headers())
            if resp.status_code == 200:
                return resp.json()
            logger.error("POST /human/tickets/%s/approve failed (%s): %s", ticket_id, resp.status_code, resp.text)
    except Exception as exc:
        logger.exception("Error calling POST /human/tickets/%s/approve: %s", ticket_id, exc)
    return None


def send_n8n_notification(
    ticket_id: str,
    template: str = "escalated",
    customer_email: Optional[str] = None,
    source: str = "customer_support_chat",
) -> bool:
    """Send notification trigger to n8n webhook with recipient email."""
    n8n_url = os.getenv("N8N_WEBHOOK_URL", "")
    n8n_secret = os.getenv("N8N_WEBHOOK_SECRET", "")
    if not n8n_url:
        logger.warning("N8N_WEBHOOK_URL not configured.")
        return False
    try:
        headers = {"Content-Type": "application/json"}
        if n8n_secret:
            headers["X-Delegate-Secret"] = n8n_secret
        payload = {
            "type": "notify_customer",
            "ticket_id": ticket_id,
            "customer_email": customer_email or "customer@example.in",
            "template": template,
            "source": source,
        }
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(n8n_url, json=payload, headers=headers)
            return resp.status_code in (200, 201)
    except Exception as exc:
        logger.exception("Error calling n8n webhook: %s", exc)
        return False


def send_slack_notification(
    ticket_id: str,
    customer_name: str,
    customer_email: str,
    user_message: str,
    status: str,
    summary: str = "",
) -> bool:
    """
    Dispatch Slack alert for customer conversations & issues:
    1. Sends type='escalation' to N8N_WEBHOOK_URL (which triggers the n8n Slack Node).
    2. If SLACK_WEBHOOK_URL is set in environment, also posts directly to Slack.
    """
    success = False

    # 1. Dispatch via n8n escalation/Slack branch
    n8n_url = os.getenv("N8N_WEBHOOK_URL", "")
    n8n_secret = os.getenv("N8N_WEBHOOK_SECRET", "")
    if n8n_url:
        try:
            headers = {"Content-Type": "application/json"}
            if n8n_secret:
                headers["X-Delegate-Secret"] = n8n_secret
            payload = {
                "type": "escalation",
                "ticket_id": ticket_id,
                "customer_name": customer_name,
                "customer_email": customer_email,
                "reason": "customer_support_conversation",
                "summary": summary or f"Customer query: '{user_message}'",
                "message": user_message,
                "status": status,
            }
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(n8n_url, json=payload, headers=headers)
                if resp.status_code in (200, 201):
                    success = True
                    logger.info("Dispatched Slack alert via n8n for ticket %s", ticket_id)
        except Exception as exc:
            logger.warning("Error dispatching n8n Slack notification: %s", exc)

    # 2. Direct Slack Incoming Webhook (if configured)
    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if slack_webhook_url:
        try:
            slack_payload = {
                "text": (
                    f"💬 *Customer Support Conversation Alert*\n"
                    f"• *Customer:* {customer_name} (`{customer_email}`)\n"
                    f"• *Customer Message:* \"{user_message}\"\n"
                    f"• *Status:* `{status.upper()}`\n"
                    f"• *Ticket ID:* `#{ticket_id[:8]}…`"
                )
            }
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(slack_webhook_url, json=slack_payload)
                if resp.status_code in (200, 201):
                    success = True
                    logger.info("Direct Slack webhook notification sent for ticket %s", ticket_id)
        except Exception as exc:
            logger.warning("Error posting to direct SLACK_WEBHOOK_URL: %s", exc)

    return success
