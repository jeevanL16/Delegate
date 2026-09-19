"""issue_refund tool — MUST go through policy engine before any DB write.

This is the most security-critical tool. The amount is ALWAYS sourced from
orders.amount_cents — the model's tool call arguments never include an amount.
"""
import logging
import uuid

from sqlalchemy.orm import Session

from app.db.models import AuditLog, Order, Refund
from app.policy.engine import PolicyResult, authorize_refund
from app.schemas.tool_io import IssueRefundInput, IssueRefundOutput

logger = logging.getLogger(__name__)


def issue_refund(
    db: Session,
    ticket_id: uuid.UUID,
    customer_id: uuid.UUID,
    raw_input: dict,
) -> IssueRefundOutput:
    inp = IssueRefundInput(**raw_input)
    order_id = uuid.UUID(inp.order_id)

    # ── Policy check FIRST, before any DB write ───────────────────────────────
    decision = authorize_refund(
        db=db,
        ticket_id=ticket_id,
        order_id=order_id,
        requesting_customer_id=customer_id,
        requested_reason=inp.reason,
    )

    if decision.result == PolicyResult.APPROVE:
        # Write refund row — amount from DB, not from model
        refund = Refund(
            ticket_id=ticket_id,
            order_id=order_id,
            amount_cents=decision.amount_cents,  # from orders table, never from model
        )
        db.add(refund)

        # Update order status
        order = db.get(Order, order_id)
        if order:
            order.status = "refunded"

        db.flush()

        _audit_tool(
            db,
            ticket_id,
            inp,
            output={
                "success": True,
                "refund_id": str(refund.id),
                "amount_cents": decision.amount_cents,
            },
            reason="refund_approved_and_issued",
        )
        logger.info("Refund issued ticket=%s order=%s amount_cents=%s", ticket_id, order_id, decision.amount_cents)
        return IssueRefundOutput(
            success=True,
            refund_id=refund.id,
            amount_cents=decision.amount_cents,
            amount_usd=round(decision.amount_cents / 100, 2),  # type: ignore[arg-type]
            policy_result=decision.result.value,
            reason=decision.reason,
        )

    elif decision.result == PolicyResult.ESCALATE:
        _audit_tool(db, ticket_id, inp, output={"success": False, "policy_result": "escalate"}, reason=decision.reason)
        return IssueRefundOutput(
            success=False,
            policy_result=decision.result.value,
            reason=decision.reason,
        )
    else:  # DENY
        _audit_tool(db, ticket_id, inp, output={"success": False, "policy_result": "deny"}, reason=decision.reason)
        return IssueRefundOutput(
            success=False,
            policy_result=decision.result.value,
            reason=decision.reason,
        )


def _audit_tool(
    db: Session, ticket_id: uuid.UUID, inp: IssueRefundInput, output: dict, reason: str
) -> None:
    entry = AuditLog(
        ticket_id=ticket_id,
        stage="executor",
        action="issue_refund",
        input_json=inp.model_dump(),
        output_json=output,
        decision_reason=reason,
    )
    db.add(entry)
    db.flush()
