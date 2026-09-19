"""get_order_status tool — read-only, no policy engine needed.

Still validates that the order belongs to the requesting customer (§8 rule 5).
"""
import logging
import uuid

from sqlalchemy.orm import Session

from app.db.models import AuditLog, Order
from app.schemas.tool_io import GetOrderStatusInput, GetOrderStatusOutput

logger = logging.getLogger(__name__)


def get_order_status(
    db: Session,
    ticket_id: uuid.UUID,
    customer_id: uuid.UUID,
    raw_input: dict,
) -> GetOrderStatusOutput:
    inp = GetOrderStatusInput(**raw_input)
    order_id = uuid.UUID(inp.order_id)

    order = db.get(Order, order_id)

    # Ownership check — defense in depth even for read-only tools
    if order is None or order.customer_id != customer_id:
        # Write audit entry and raise so Executor catches it
        _audit(db, ticket_id, inp, error="order_not_found_or_mismatch")
        raise ValueError("order_customer_mismatch")

    result = GetOrderStatusOutput(
        order_id=order.id,
        status=order.status,
        amount_cents=order.amount_cents,
        amount_usd=round(order.amount_cents / 100, 2),
        customer_id=order.customer_id,
    )
    _audit(db, ticket_id, inp, output=result.model_dump(mode="json"))
    return result


def _audit(db: Session, ticket_id: uuid.UUID, inp: GetOrderStatusInput, output: dict | None = None, error: str | None = None) -> None:
    entry = AuditLog(
        ticket_id=ticket_id,
        stage="executor",
        action="get_order_status",
        input_json=inp.model_dump(),
        output_json=output or {"error": error},
        decision_reason=error or "order_status_retrieved",
    )
    db.add(entry)
    db.flush()
