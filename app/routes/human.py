"""Human agent queue routes — GET /human/queue, POST /human/tickets/{id}/approve."""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Customer, Order, Refund, Ticket
from app.db.session import get_db
from app.deps import require_human_agent
from app.policy.engine import PolicyResult, authorize_refund
from app.schemas.ticket import AuditEntryOut, HumanApproveRequest, TicketDetailResponse, TicketListItem

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/human", tags=["human"], dependencies=[Depends(require_human_agent)])


@router.get("/queue", response_model=list[TicketListItem])
def get_queue(db: Session = Depends(get_db)) -> list[TicketListItem]:
    """Escalated tickets awaiting human review."""
    tickets = (
        db.query(Ticket)
        .filter(Ticket.status == "escalated")
        .order_by(Ticket.created_at.desc())
        .limit(100)
        .all()
    )
    return [TicketListItem.model_validate(t) for t in tickets]


@router.get("/tickets/{ticket_id}", response_model=TicketDetailResponse)
def get_human_ticket(ticket_id: uuid.UUID, db: Session = Depends(get_db)) -> TicketDetailResponse:
    """Full ticket detail including audit trail for human review."""
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail={"code": "ticket_not_found", "message": "Ticket not found"})

    audit_entries = (
        db.query(AuditLog)
        .filter(AuditLog.ticket_id == ticket_id)
        .order_by(AuditLog.created_at)
        .all()
    )
    return TicketDetailResponse(
        id=ticket.id,
        customer_id=ticket.customer_id,
        order_id=ticket.order_id,
        raw_text=ticket.raw_text,
        issue_type=ticket.issue_type,
        status=ticket.status,
        resolution=ticket.resolution,
        suspected_injection=ticket.suspected_injection,
        created_at=ticket.created_at,
        resolved_at=ticket.resolved_at,
        audit_trail=[AuditEntryOut.model_validate(a) for a in audit_entries],
    )


@router.post("/tickets/{ticket_id}/approve")
def approve_ticket(
    ticket_id: uuid.UUID,
    body: HumanApproveRequest,
    db: Session = Depends(get_db),
    agent: dict = Depends(require_human_agent),
) -> dict:
    """
    Human agent approves an escalated ticket.

    Still goes through the Policy Engine — a human approval does NOT bypass
    the hard refund cap. Raising the cap is a config change, not a runtime override.
    """
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail={"code": "ticket_not_found", "message": "Ticket not found"})
    if ticket.status != "escalated":
        raise HTTPException(
            status_code=400,
            detail={"code": "ticket_not_escalated", "message": "Only escalated tickets can be approved"},
        )

    agent_sub = agent.get("sub", "unknown_agent")

    if body.action == "issue_refund":
        if ticket.order_id is None:
            raise HTTPException(
                status_code=400,
                detail={"code": "no_order_on_ticket", "message": "No order associated with this ticket"},
            )
        # Policy engine still applies — human cannot bypass hard cap
        decision = authorize_refund(
            db=db,
            ticket_id=ticket_id,
            order_id=ticket.order_id,
            requesting_customer_id=ticket.customer_id,
            requested_reason=f"human_approved_by:{agent_sub} note:{body.note}",
        )
        if decision.result == PolicyResult.APPROVE:
            amount_cents = decision.amount_cents or 0
            refund = Refund(
                ticket_id=ticket_id,
                order_id=ticket.order_id,
                amount_cents=amount_cents,
            )
            db.add(refund)
            order = db.get(Order, ticket.order_id)
            if order:
                order.status = "refunded"
            ticket.status = "resolved"
            ticket.resolution = f"Human agent issued refund. Note: {body.note}"
            ticket.resolved_at = datetime.now(timezone.utc)
            _write_audit(db, ticket_id, "human_approve_refund", body, agent_sub, "refund_issued_by_human")
            db.flush()
            return {"status": "resolved", "action": "refund_issued", "amount_cents": amount_cents, "amount_usd": round(amount_cents / 100, 2)}
        else:
            return {"status": "policy_denied", "reason": decision.reason}

    else:  # close_no_action
        ticket.status = "resolved"
        ticket.resolution = f"Closed without action by human agent. Note: {body.note}"
        ticket.resolved_at = datetime.now(timezone.utc)
        _write_audit(db, ticket_id, "human_close_no_action", body, agent_sub, "closed_no_action_by_human")
        db.flush()
        return {"status": "resolved", "action": "closed_no_action"}


def _write_audit(
    db: Session,
    ticket_id: uuid.UUID,
    action: str,
    body: HumanApproveRequest,
    agent_sub: str,
    reason: str,
) -> None:
    entry = AuditLog(
        ticket_id=ticket_id,
        stage="reviewer",
        action=action,
        input_json={"action": body.action, "agent": agent_sub},
        output_json={"note": body.note},
        decision_reason=reason,
    )
    db.add(entry)
    db.flush()
