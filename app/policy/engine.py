"""
Policy Engine — THE single authorization chokepoint.

This is a plain Python module (not an LLM call). It is the ONLY code path
allowed to write a refund row or call notify_customer. Any other code path
that writes to `refunds` or changes `orders.status` is a bug.

Rules (from §7 of MASTER_BUILD_PROMPT):
1. Refund amount always comes from the orders table, never from model args.
2. Every PolicyDecision is written to audit_log (stage='policy') before the
   tool proceeds.
3. Any tool call outside this chokepoint that writes to refunds or changes
   order status is caught by tests/unit/test_policy_engine.py.
4. MAX_TOOL_CALLS_PER_TICKET is enforced in executor.py via check_tool_limit().
"""
import logging
import uuid
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AuditLog, Customer, Order, Refund

logger = logging.getLogger(__name__)


class PolicyResult(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    ESCALATE = "escalate"


@dataclass
class PolicyDecision:
    result: PolicyResult
    reason: str
    amount_cents: int | None = None  # only set when APPROVE for a refund


# ── Internal helper ────────────────────────────────────────────────────────────

def _audit(
    db: Session,
    ticket_id: uuid.UUID,
    action: str,
    input_data: dict,
    decision: "PolicyDecision",
) -> None:
    """Write policy decision to audit_log BEFORE the tool proceeds."""
    entry = AuditLog(
        ticket_id=ticket_id,
        stage="policy",
        action=action,
        input_json=input_data,
        output_json={
            "result": decision.result.value,
            "reason": decision.reason,
            "amount_cents": decision.amount_cents,
        },
        decision_reason=decision.reason,  # NOT NULL — always set
    )
    db.add(entry)
    db.flush()  # write immediately, within the caller's transaction


# ── Public API ─────────────────────────────────────────────────────────────────

def authorize_refund(
    db: Session,
    ticket_id: uuid.UUID,
    order_id: uuid.UUID,
    requesting_customer_id: uuid.UUID,
    requested_reason: str,
) -> PolicyDecision:
    """
    Authorize (or deny/escalate) a refund request.

    Amount comes from orders.amount_cents — never from the model's tool call.
    Escalation policy table (§11 of MASTER_BUILD_PROMPT):
      - Row 1: amount > REFUND_CAP_CENTS    → escalate, amount_over_cap
      - Row 3: tier==vip or repeat_complainer flag → escalate, customer_flagged
      - Row 5: already hit MAX_REFUNDS_PER_TICKET → deny, refund_limit_reached
      - Row 8: order doesn't belong to customer → deny, order_customer_mismatch
    """
    input_data = {
        "ticket_id": str(ticket_id),
        "order_id": str(order_id),
        "requesting_customer_id": str(requesting_customer_id),
        "requested_reason": requested_reason,
    }

    # ── Check 1: order exists and belongs to this customer ────────────────────
    order = db.get(Order, order_id)
    if order is None or order.customer_id != requesting_customer_id:
        d = PolicyDecision(PolicyResult.DENY, "order_customer_mismatch")
        _audit(db, ticket_id, "authorize_refund", input_data, d)
        logger.warning("Policy DENY order_customer_mismatch ticket=%s order=%s", ticket_id, order_id)
        return d

    # ── Check 2: not already refunded ─────────────────────────────────────────
    if order.status == "refunded":
        d = PolicyDecision(PolicyResult.DENY, "already_refunded")
        _audit(db, ticket_id, "authorize_refund", input_data, d)
        return d

    # ── Check 3: amount within cap (₹REFUND_CAP_CENTS/100) ───────────────────
    if order.amount_cents > settings.refund_cap_cents:
        d = PolicyDecision(PolicyResult.ESCALATE, "amount_over_cap")
        _audit(db, ticket_id, "authorize_refund", input_data, d)
        logger.info(
            "Policy ESCALATE amount_over_cap ticket=%s amount_cents=%s cap=%s",
            ticket_id, order.amount_cents, settings.refund_cap_cents,
        )
        return d

    # ── Check 4: refund count for this ticket ─────────────────────────────────
    existing = db.query(Refund).filter(Refund.ticket_id == ticket_id).count()
    if existing >= settings.max_refunds_per_ticket:
        d = PolicyDecision(PolicyResult.DENY, "refund_limit_reached")
        _audit(db, ticket_id, "authorize_refund", input_data, d)
        return d

    # ── Check 5: customer tier / flags ────────────────────────────────────────
    customer = db.get(Customer, requesting_customer_id)
    if customer is None:
        d = PolicyDecision(PolicyResult.DENY, "customer_not_found")
        _audit(db, ticket_id, "authorize_refund", input_data, d)
        return d
    if customer.tier == "vip" or "repeat_complainer" in (customer.flags or []):
        d = PolicyDecision(PolicyResult.ESCALATE, "customer_flagged")
        _audit(db, ticket_id, "authorize_refund", input_data, d)
        return d

    # ── All checks passed — approve ───────────────────────────────────────────
    # Amount comes from the order record, NEVER from model-supplied value
    d = PolicyDecision(PolicyResult.APPROVE, "all_checks_passed", amount_cents=order.amount_cents)
    _audit(db, ticket_id, "authorize_refund", input_data, d)
    logger.info("Policy APPROVE refund ticket=%s amount_cents=%s", ticket_id, order.amount_cents)
    return d


def authorize_notification(
    db: Session,
    ticket_id: uuid.UUID,
    template: str,
) -> PolicyDecision:
    """
    Authorize a customer notification. Only template enum values are allowed —
    no free-text model-composed bodies.
    """
    allowed = {"refund_issued", "escalated", "info_needed"}
    input_data = {"ticket_id": str(ticket_id), "template": template}

    if template not in allowed:
        d = PolicyDecision(PolicyResult.DENY, f"invalid_template:{template}")
        _audit(db, ticket_id, "authorize_notification", input_data, d)
        return d

    d = PolicyDecision(PolicyResult.APPROVE, "valid_template")
    _audit(db, ticket_id, "authorize_notification", input_data, d)
    return d


def check_tool_limit(
    db: Session,
    ticket_id: uuid.UUID,
    current_count: int,
) -> PolicyDecision:
    """Enforce MAX_TOOL_CALLS_PER_TICKET (§11 row 6)."""
    if current_count >= settings.max_tool_calls_per_ticket:
        d = PolicyDecision(PolicyResult.ESCALATE, "tool_call_limit_exceeded")
        _audit(db, ticket_id, "check_tool_limit", {"count": current_count}, d)
        return d
    return PolicyDecision(PolicyResult.APPROVE, "within_limit")
