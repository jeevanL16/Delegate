"""notify_customer tool — template-only, goes through policy engine.

No free-text body is allowed. The model picks from an enum of templates.
After policy approval, posts one synchronous HTTP POST to the n8n webhook
(§13 of MASTER_BUILD_PROMPT). Best-effort: n8n failure does NOT change
the ticket's already-correct DB state.
"""
import logging
import uuid

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AuditLog, Customer
from app.policy.engine import PolicyResult, authorize_notification
from app.schemas.tool_io import NotifyCustomerInput, NotifyCustomerOutput

logger = logging.getLogger(__name__)

# Template messages — never composed by the model (§8 rule 4)
TEMPLATES: dict[str, str] = {
    "refund_issued": "Your refund has been successfully processed.",
    "escalated": "Your request has been forwarded to our support team.",
    "info_needed": "We need more information to process your request.",
}


def notify_customer(
    db: Session,
    ticket_id: uuid.UUID,
    customer_id: uuid.UUID,
    raw_input: dict,
) -> NotifyCustomerOutput:
    inp = NotifyCustomerInput(**raw_input)
    tid = uuid.UUID(inp.ticket_id)

    # Policy check — validates template enum value
    decision = authorize_notification(db=db, ticket_id=ticket_id, template=inp.template)

    if decision.result != PolicyResult.APPROVE:
        _audit(db, ticket_id, inp, output={"delivered": False, "reason": decision.reason}, reason=decision.reason)
        return NotifyCustomerOutput(ticket_id=tid, template=inp.template, delivered=False)

    # Stub delivery — log the template text; real delivery goes via n8n
    message = TEMPLATES.get(inp.template, "")
    logger.info(
        "NOTIFY_CUSTOMER template=%s message=%s ticket=%s",
        inp.template, message, ticket_id,
    )
    _audit(
        db, ticket_id, inp,
        output={"delivered": True, "template": inp.template},
        reason="notification_logged",
    )

    # ── n8n webhook (§13 — one sync POST, best-effort) ────────────────────────
    _post_n8n(db, ticket_id, inp, customer_id)

    return NotifyCustomerOutput(ticket_id=tid, template=inp.template, delivered=True)


def _post_n8n(
    db: Session,
    ticket_id: uuid.UUID,
    inp: NotifyCustomerInput,
    customer_id: uuid.UUID,
) -> None:
    """Best-effort n8n webhook POST. Failure is logged, never raises."""
    webhook_url = settings.n8n_webhook_url
    if not webhook_url:
        logger.debug("N8N_WEBHOOK_URL not set — skipping customer notification webhook")
        return

    customer_email = "unknown"
    customer = db.get(Customer, customer_id)
    if customer:
        customer_email = customer.email

    payload = {
        "type": "notify_customer",
        "ticket_id": str(ticket_id),
        "customer_email": customer_email,
        "template": inp.template,
    }

    try:
        headers = {"Content-Type": "application/json"}
        if settings.n8n_webhook_secret:
            headers["X-Delegate-Secret"] = settings.n8n_webhook_secret

        resp = requests.post(webhook_url, json=payload, headers=headers, timeout=5)
        resp.raise_for_status()
        logger.info("n8n notified ticket=%s type=notify_customer status=%s", ticket_id, resp.status_code)

        _audit_n8n(db, ticket_id, "n8n_notify_sent", {"status_code": resp.status_code}, "n8n_webhook_ok")

    except Exception as exc:
        logger.warning("n8n webhook failed ticket=%s (non-fatal): %s", ticket_id, exc)
        _audit_n8n(db, ticket_id, "n8n_notify_failed", {"error": str(exc)[:200]}, "n8n_webhook_failed")


def _audit(
    db: Session,
    ticket_id: uuid.UUID,
    inp: NotifyCustomerInput,
    output: dict | None = None,
    reason: str = "notification_logged",
) -> None:
    entry = AuditLog(
        ticket_id=ticket_id,
        stage="executor",
        action="notify_customer",
        input_json=inp.model_dump(),
        output_json=output,
        decision_reason=reason,
    )
    db.add(entry)
    db.flush()


def _audit_n8n(db: Session, ticket_id: uuid.UUID, action: str, output: dict, reason: str) -> None:
    """Separate audit entry for the n8n call outcome."""
    try:
        entry = AuditLog(
            ticket_id=ticket_id,
            stage="executor",
            action=action,
            input_json=None,
            output_json=output,
            decision_reason=reason,
        )
        db.add(entry)
        db.flush()
    except Exception:
        pass  # Never let audit failure cascade
