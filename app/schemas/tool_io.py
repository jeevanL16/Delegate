"""Pydantic schemas for every tool's input and output."""
import uuid
from typing import Literal, Optional
from pydantic import BaseModel


# ── Tool inputs (what the model passes; validated before any action) ──────────

class GetOrderStatusInput(BaseModel):
    order_id: str


class IssueRefundInput(BaseModel):
    order_id: str
    reason: str


class UpdateTicketStatusInput(BaseModel):
    ticket_id: str
    status: Literal["resolved", "escalated"]
    resolution: str


class EscalateToHumanInput(BaseModel):
    ticket_id: str
    reason: str
    summary: str


class NotifyCustomerInput(BaseModel):
    ticket_id: str
    template: Literal["refund_issued", "escalated", "info_needed"]


# ── Tool outputs (what tools return to the Executor) ─────────────────────────

class GetOrderStatusOutput(BaseModel):
    order_id: uuid.UUID
    status: str
    amount_cents: int
    amount_usd: float
    customer_id: uuid.UUID


class IssueRefundOutput(BaseModel):
    success: bool
    refund_id: Optional[uuid.UUID] = None
    amount_cents: Optional[int] = None
    amount_usd: Optional[float] = None
    policy_result: str
    reason: str


class UpdateTicketStatusOutput(BaseModel):
    ticket_id: uuid.UUID
    new_status: str
    success: bool


class EscalateToHumanOutput(BaseModel):
    ticket_id: uuid.UUID
    queued: bool
    reason: str


class NotifyCustomerOutput(BaseModel):
    ticket_id: uuid.UUID
    template: str
    delivered: bool  # always stub/log at this scope


# ── Analyzer structured output ────────────────────────────────────────────────

class AnalyzerOutput(BaseModel):
    issue_type: Literal["refund_status", "payment_failed", "cancellation", "other"]
    urgency: Literal["low", "medium", "high"]
    confident: bool
    suspected_injection: bool
    notes: Optional[str] = None


# ── Router structured output ──────────────────────────────────────────────────

class RouterDecision(BaseModel):
    tools_to_call: list[str]          # ordered list of tool names
    escalate_directly: bool
    escalate_reason: Optional[str] = None
    reasoning: str
