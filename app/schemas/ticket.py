import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ── Request schemas ────────────────────────────────────────────────────────────

class CreateTicketRequest(BaseModel):
    customer_id: uuid.UUID
    order_id: Optional[uuid.UUID] = None
    raw_text: str = Field(..., min_length=1, max_length=4000)

    @field_validator("raw_text")
    @classmethod
    def no_empty_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("raw_text must not be blank")
        return v


class HumanApproveRequest(BaseModel):
    action: str = Field(..., pattern="^(issue_refund|close_no_action)$")
    note: str = Field(..., min_length=1, max_length=2000)


# ── Response schemas ───────────────────────────────────────────────────────────

class CreateTicketResponse(BaseModel):
    ticket_id: uuid.UUID
    status: str


class ActionTaken(BaseModel):
    tool: str
    result: dict


class ResolveTicketResponse(BaseModel):
    ticket_id: uuid.UUID
    status: str
    resolution: Optional[str] = None
    actions_taken: list[ActionTaken] = []
    escalation_reason: Optional[str] = None


class CustomerOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    tier: str
    flags: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    amount_cents: int
    amount_usd: float  # computed for display
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: object) -> "OrderOut":  # type: ignore[override]
        return cls(
            id=obj.id,  # type: ignore[attr-defined]
            customer_id=obj.customer_id,  # type: ignore[attr-defined]
            amount_cents=obj.amount_cents,  # type: ignore[attr-defined]
            amount_usd=obj.amount_cents / 100,  # type: ignore[attr-defined]
            status=obj.status,  # type: ignore[attr-defined]
            created_at=obj.created_at,  # type: ignore[attr-defined]
        )


class AuditEntryOut(BaseModel):
    id: uuid.UUID
    stage: str
    action: str
    input_json: Optional[dict] = None
    output_json: Optional[dict] = None
    decision_reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TicketDetailResponse(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    order_id: Optional[uuid.UUID]
    raw_text: str
    issue_type: Optional[str]
    status: str
    resolution: Optional[str]
    suspected_injection: bool
    created_at: datetime
    resolved_at: Optional[datetime]
    audit_trail: list[AuditEntryOut] = []

    model_config = {"from_attributes": True}


class TicketListItem(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    order_id: Optional[uuid.UUID]
    issue_type: Optional[str]
    status: str
    suspected_injection: bool
    created_at: datetime
    resolved_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Error envelope ─────────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
