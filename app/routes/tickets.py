"""Ticket routes — POST /tickets, POST /tickets/{id}/resolve, GET /tickets/{id}, GET /tickets."""
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.agent.analyzer import run_analyzer
from app.agent.executor import run_executor
from app.agent.reviewer import run_reviewer
from app.agent.router import run_router
from app.db.models import AuditLog, Customer, Order, Ticket
from app.db.session import get_db
from app.deps import require_api_key
from app.schemas.ticket import (
    ActionTaken,
    AuditEntryOut,
    CreateTicketRequest,
    CreateTicketResponse,
    ResolveTicketResponse,
    TicketDetailResponse,
    TicketListItem,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tickets", tags=["tickets"], dependencies=[Depends(require_api_key)])


@router.post("", response_model=CreateTicketResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(body: CreateTicketRequest, db: Session = Depends(get_db)) -> CreateTicketResponse:
    """Create a new support ticket. Validates customer and order existence."""
    # Validate customer exists
    customer = db.get(Customer, body.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail={"code": "customer_not_found", "message": "Customer not found"})

    # Validate order belongs to customer (defense in depth — checked again in policy engine)
    if body.order_id is not None:
        order = db.get(Order, body.order_id)
        if order is None or order.customer_id != body.customer_id:
            raise HTTPException(
                status_code=400,
                detail={"code": "order_customer_mismatch", "message": "Order does not belong to this customer"},
            )

    ticket = Ticket(
        customer_id=body.customer_id,
        order_id=body.order_id,
        raw_text=body.raw_text,
    )
    db.add(ticket)
    db.flush()
    logger.info("Ticket created id=%s customer=%s", ticket.id, ticket.customer_id)
    return CreateTicketResponse(ticket_id=ticket.id, status="open")


@router.post("/{ticket_id}/resolve", response_model=ResolveTicketResponse)
def resolve_ticket(ticket_id: uuid.UUID, db: Session = Depends(get_db)) -> ResolveTicketResponse:
    """
    Run the full Analyzer→Router→Executor→Reviewer pipeline synchronously.

    On any internal error: respond 200 with status='escalated' and
    escalation_reason='internal_error' — never surface a raw 500 for ticket processing.
    """
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail={"code": "ticket_not_found", "message": "Ticket not found"})

    if ticket.status != "open":
        return ResolveTicketResponse(
            ticket_id=ticket.id,
            status=ticket.status,
            resolution=ticket.resolution,
            actions_taken=[],
            escalation_reason=None,
        )

    try:
        # ── Stage 1: Analyzer ─────────────────────────────────────────────
        analyzer_out = run_analyzer(db, ticket)

        # ── Stage 2: Router ───────────────────────────────────────────────
        router_decision = run_router(db, ticket, analyzer_out)

        # ── Stage 3: Executor ─────────────────────────────────────────────
        executor_result = run_executor(db, ticket, router_decision)

        # ── Stage 4: Reviewer ─────────────────────────────────────────────
        reviewer_out = run_reviewer(db, ticket, analyzer_out, executor_result)

        return ResolveTicketResponse(
            ticket_id=ticket.id,
            status=reviewer_out["final_status"],
            resolution=reviewer_out["resolution_summary"],
            actions_taken=[ActionTaken(**a) for a in executor_result.actions_taken],
            escalation_reason=reviewer_out.get("escalation_reason"),
        )

    except Exception as exc:
        # Fail closed — any unexpected error → escalation, not 500
        logger.exception("Unexpected error resolving ticket %s: %s", ticket_id, exc)
        try:
            ticket.status = "escalated"
            ticket.resolution = "System error — escalated for human review."
            from datetime import datetime, timezone
            ticket.resolved_at = datetime.now(timezone.utc)
            entry = AuditLog(
                ticket_id=ticket.id,
                stage="reviewer",
                action="emergency_escalation",
                input_json={},
                output_json={"error": type(exc).__name__},
                decision_reason="internal_error",
            )
            db.add(entry)
            db.flush()
        except Exception:
            pass

        return ResolveTicketResponse(
            ticket_id=ticket_id,
            status="escalated",
            resolution="System error — escalated for human review.",
            actions_taken=[],
            escalation_reason="internal_error",
        )


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
def get_ticket(ticket_id: uuid.UUID, db: Session = Depends(get_db)) -> TicketDetailResponse:
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


@router.get("", response_model=list[TicketListItem])
def list_tickets(
    status: Optional[str] = Query(None, pattern="^(open|resolved|escalated)$"),
    db: Session = Depends(get_db),
) -> list[TicketListItem]:
    q = db.query(Ticket).order_by(Ticket.created_at.desc())
    if status:
        q = q.filter(Ticket.status == status)
    return [TicketListItem.model_validate(t) for t in q.limit(100).all()]
