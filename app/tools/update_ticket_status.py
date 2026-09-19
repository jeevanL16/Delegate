"""update_ticket_status tool."""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import AuditLog, Ticket
from app.schemas.tool_io import UpdateTicketStatusInput, UpdateTicketStatusOutput

logger = logging.getLogger(__name__)


def update_ticket_status(
    db: Session,
    ticket_id: uuid.UUID,
    customer_id: uuid.UUID,
    raw_input: dict,
) -> UpdateTicketStatusOutput:
    inp = UpdateTicketStatusInput(**raw_input)
    tid = uuid.UUID(inp.ticket_id)

    # Safety: tool can only update the ticket it was called for
    if tid != ticket_id:
        _audit(db, ticket_id, inp, error="ticket_id_mismatch")
        raise ValueError("ticket_id_mismatch")

    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        _audit(db, ticket_id, inp, error="ticket_not_found")
        raise ValueError("ticket_not_found")

    ticket.status = inp.status
    ticket.resolution = inp.resolution
    if inp.status in ("resolved", "escalated"):
        ticket.resolved_at = datetime.now(timezone.utc)
    db.flush()

    _audit(db, ticket_id, inp, output={"new_status": inp.status})
    logger.info("Ticket %s updated to status=%s", ticket_id, inp.status)
    return UpdateTicketStatusOutput(ticket_id=ticket_id, new_status=inp.status, success=True)


def _audit(
    db: Session, ticket_id: uuid.UUID, inp: UpdateTicketStatusInput, output: dict | None = None, error: str | None = None
) -> None:
    entry = AuditLog(
        ticket_id=ticket_id,
        stage="executor",
        action="update_ticket_status",
        input_json=inp.model_dump(),
        output_json=output or {"error": error},
        decision_reason=error or f"ticket_status_set_to_{inp.status}",
    )
    db.add(entry)
    db.flush()
