"""escalate_to_human tool — always safe to call, no policy gate needed.

After the DB write, posts one synchronous HTTP POST to the n8n webhook
(§13 of MASTER_BUILD_PROMPT). Best-effort: n8n failure does NOT change
the ticket's already-correct DB state.
"""
import logging
import uuid
from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AuditLog, Customer, Ticket
from app.schemas.tool_io import EscalateToHumanInput, EscalateToHumanOutput

logger = logging.getLogger(__name__)


def escalate_to_human(
    db: Session,
    ticket_id: uuid.UUID,
    customer_id: uuid.UUID,
    raw_input: dict,
) -> EscalateToHumanOutput:
    inp = EscalateToHumanInput(**raw_input)
    tid = uuid.UUID(inp.ticket_id)

    if tid != ticket_id:
        _audit(db, ticket_id, inp, error="ticket_id_mismatch")
        raise ValueError("ticket_id_mismatch")

    ticket = db.get(Ticket, ticket_id)
    if ticket:
        ticket.status = "escalated"
        ticket.resolution = inp.summary
        ticket.resolved_at = datetime.now(timezone.utc)
    db.flush()

    _audit(
        db,
        ticket_id,
        inp,
        output={"queued": True, "reason": inp.reason},
    )

    # ── n8n webhook (§13 — one sync POST, best-effort) ────────────────────────
    _post_n8n(db, ticket_id, inp, ticket)

    logger.info("Ticket %s escalated reason=%s", ticket_id, inp.reason)
    return EscalateToHumanOutput(ticket_id=ticket_id, queued=True, reason=inp.reason)


def _post_n8n(
    db: Session,
    ticket_id: uuid.UUID,
    inp: EscalateToHumanInput,
    ticket: "Ticket | None",
) -> None:
    """Best-effort n8n webhook POST. Failure is logged, never raises."""
    webhook_url = settings.n8n_webhook_url
    if not webhook_url:
        logger.debug("N8N_WEBHOOK_URL not set — skipping escalation notification")
        return

    customer_name = "Unknown"
    if ticket and ticket.customer_id:
        customer = db.get(Customer, ticket.customer_id)
        if customer:
            customer_name = customer.name

    payload = {
        "type": "escalation",
        "ticket_id": str(ticket_id),
        "customer_name": customer_name,
        "reason": inp.reason,
        "summary": inp.summary,
    }

    try:
        headers = {"Content-Type": "application/json"}
        if settings.n8n_webhook_secret:
            headers["X-Delegate-Secret"] = settings.n8n_webhook_secret

        resp = requests.post(webhook_url, json=payload, headers=headers, timeout=5)
        resp.raise_for_status()
        logger.info("n8n notified ticket=%s type=escalation status=%s", ticket_id, resp.status_code)

        _audit_n8n(db, ticket_id, "n8n_escalation_sent", {"status_code": resp.status_code}, "n8n_webhook_ok")

    except Exception as exc:
        logger.warning("n8n webhook failed ticket=%s (non-fatal): %s", ticket_id, exc)
        _audit_n8n(db, ticket_id, "n8n_notify_failed", {"error": str(exc)[:200]}, "n8n_webhook_failed")


def _audit(
    db: Session,
    ticket_id: uuid.UUID,
    inp: EscalateToHumanInput,
    output: dict | None = None,
    error: str | None = None,
) -> None:
    entry = AuditLog(
        ticket_id=ticket_id,
        stage="executor",
        action="escalate_to_human",
        input_json=inp.model_dump(),
        output_json=output or {"error": error},
        decision_reason=error or f"escalated:{inp.reason}",
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
