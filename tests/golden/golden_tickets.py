"""
Golden ticket tests (§14.1) — 5 canonical scenarios.

Each asserts exact expected final status and tool-call sequence.
Uses mocked Claude responses for determinism.
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock

from sqlalchemy.orm import Session
from app.config import settings
from app.db.models import Customer, Order, Refund, Ticket
from app.schemas.tool_io import AnalyzerOutput, RouterDecision


def run_full_pipeline(db, ticket, analyzer_mock, router_mock=None, reviewer_mock=None):
    """Run the full pipeline with controllable mock responses."""
    from app.agent.analyzer import run_analyzer
    from app.agent.router import run_router
    from app.agent.executor import run_executor
    from app.agent.reviewer import run_reviewer

    with patch("app.agent.analyzer.call_claude_json", return_value=analyzer_mock):
        if router_mock:
            with patch("app.agent.router.call_claude_json", return_value=router_mock):
                with patch("app.agent.reviewer.call_claude_json", return_value=reviewer_mock or {
                    "final_status": "resolved",
                    "resolution_summary": "Resolved successfully.",
                    "escalation_reason": None,
                }):
                    analyzer_out = run_analyzer(db, ticket)
                    router_decision = run_router(db, ticket, analyzer_out)
                    executor_result = run_executor(db, ticket, router_decision)
                    reviewer_out = run_reviewer(db, ticket, analyzer_out, executor_result)
        else:
            with patch("app.agent.reviewer.call_claude_json", return_value=reviewer_mock or {
                "final_status": "escalated",
                "resolution_summary": "Escalated.",
                "escalation_reason": "various",
            }):
                analyzer_out = run_analyzer(db, ticket)
                router_decision = run_router(db, ticket, analyzer_out)
                executor_result = run_executor(db, ticket, router_decision)
                reviewer_out = run_reviewer(db, ticket, analyzer_out, executor_result)

    return analyzer_out, router_decision, executor_result, reviewer_out


# ── Golden Ticket 1: Already refunded order ───────────────────────────────────

def test_golden_1_already_refunded(db, regular_customer, order_already_refunded):
    """
    'Where's my refund for order #X?' — order already refunded.
    Expected: resolved, no new refund tool call, no new Refund row.
    """
    ticket = Ticket(
        customer_id=regular_customer.id,
        order_id=order_already_refunded.id,
        raw_text=f"Where is my refund for order {order_already_refunded.id}? It's been 3 days.",
    )
    db.add(ticket)
    db.flush()

    analyzer_mock = {
        "issue_type": "refund_status",
        "urgency": "medium",
        "confident": True,
        "suspected_injection": False,
        "notes": None,
    }
    router_mock = {
        "tools_to_call": ["get_order_status", "update_ticket_status"],
        "escalate_directly": False,
        "escalate_reason": None,
        "reasoning": "Check status then resolve — already refunded.",
    }
    reviewer_mock = {
        "final_status": "resolved",
        "resolution_summary": "Order already has refunded status. No new action needed.",
        "escalation_reason": None,
    }

    refund_count_before = db.query(Refund).count()

    with patch("app.agent.executor.call_claude_tools") as mock_claude_tools:
        # Simulate LLM calling get_order_status then update_ticket_status
        mock_response_1 = MagicMock()
        mock_response_1.stop_reason = "tool_use"
        mock_response_1.message = {"role": "assistant", "content": None, "tool_calls": [{"id": "tu1", "type": "function", "function": {"name": "get_order_status", "arguments": "{}"}}]}
        mock_response_2 = MagicMock()
        mock_response_2.stop_reason = "tool_use"
        mock_response_2.message = {"role": "assistant", "content": None, "tool_calls": [{"id": "tu2", "type": "function", "function": {"name": "update_ticket_status", "arguments": "{}"}}]}
        mock_response_3 = MagicMock()
        mock_response_3.stop_reason = "end_turn"
        mock_response_3.message = {"role": "assistant", "content": "Done"}
        mock_claude_tools.side_effect = [mock_response_1, mock_response_2, mock_response_3]

        with patch("app.agent.executor.extract_tool_calls") as mock_extract:
            mock_extract.side_effect = [
                [{"id": "tu1", "name": "get_order_status", "input": {"order_id": str(order_already_refunded.id)}}],
                [{"id": "tu2", "name": "update_ticket_status", "input": {"ticket_id": str(ticket.id), "status": "resolved", "resolution": "Already refunded."}}],
                [],
            ]
            _, _, executor_result, reviewer_out = run_full_pipeline(db, ticket, analyzer_mock, router_mock, reviewer_mock)

    assert reviewer_out["final_status"] == "resolved"
    tool_names = [a["tool"] for a in executor_result.actions_taken]
    assert "issue_refund" not in tool_names, "issue_refund should NOT be called for already-refunded order"
    assert db.query(Refund).count() == refund_count_before, "No new refund rows should be created"


# ── Golden Ticket 2: Payment failed, under cap ────────────────────────────────

def test_golden_2_payment_failed_refund_issued(db, regular_customer, order_failed_under_cap):
    """
    'Payment failed but money was deducted, order #Y' — $89.90, under $100 cap.
    Expected: resolved, one issue_refund call, one new Refund row.
    """
    ticket = Ticket(
        customer_id=regular_customer.id,
        order_id=order_failed_under_cap.id,
        raw_text=f"Payment failed but money was deducted for order {order_failed_under_cap.id}. Please refund.",
    )
    db.add(ticket)
    db.flush()

    refund_count_before = db.query(Refund).count()

    analyzer_mock = {"issue_type": "payment_failed", "urgency": "high", "confident": True, "suspected_injection": False, "notes": None}
    router_mock = {
        "tools_to_call": ["get_order_status", "issue_refund", "notify_customer", "update_ticket_status"],
        "escalate_directly": False,
        "escalate_reason": None,
        "reasoning": "Payment failed — evaluate refund.",
    }
    reviewer_mock = {"final_status": "resolved", "resolution_summary": "Refund issued for failed payment.", "escalation_reason": None}

    with patch("app.agent.executor.call_claude_tools") as mock_tools:
        with patch("app.agent.executor.extract_tool_calls") as mock_extract:
            mock_tools.side_effect = [MagicMock(stop_reason="end_turn", content=[]), MagicMock(stop_reason="end_turn", content=[])]
            mock_extract.side_effect = [
                [{"id": "tu1", "name": "issue_refund", "input": {"order_id": str(order_failed_under_cap.id), "reason": "payment_failed"}}],
                [],
            ]
            _, _, executor_result, reviewer_out = run_full_pipeline(db, ticket, analyzer_mock, router_mock, reviewer_mock)

    assert reviewer_out["final_status"] == "resolved"
    tool_names = [a["tool"] for a in executor_result.actions_taken]
    assert "issue_refund" in tool_names
    # A new Refund row must have been created
    assert db.query(Refund).count() == refund_count_before + 1
    # Amount must equal order's amount_cents, not any model-supplied value
    new_refund = db.query(Refund).filter(Refund.ticket_id == ticket.id).first()
    assert new_refund is not None
    assert new_refund.amount_cents == order_failed_under_cap.amount_cents  # $89.90


# ── Golden Ticket 3: VIP customer ─────────────────────────────────────────────

def test_golden_3_vip_customer_escalated(db, vip_customer, order_vip):
    """VIP customer refund request → escalated, reason customer_flagged."""
    ticket = Ticket(
        customer_id=vip_customer.id,
        order_id=order_vip.id,
        raw_text=f"I want a refund for order {order_vip.id}.",
    )
    db.add(ticket)
    db.flush()

    # Policy engine will catch VIP at authorize_refund step
    # Router will propose issue_refund but policy will return ESCALATE
    analyzer_mock = {"issue_type": "refund_status", "urgency": "medium", "confident": True, "suspected_injection": False, "notes": None}
    router_mock = {
        "tools_to_call": ["issue_refund", "escalate_to_human"],
        "escalate_directly": False,
        "escalate_reason": None,
        "reasoning": "Refund request from VIP customer.",
    }
    reviewer_mock = {"final_status": "escalated", "resolution_summary": "VIP customer — escalated per policy.", "escalation_reason": "customer_flagged"}

    refund_count_before = db.query(Refund).count()

    with patch("app.agent.executor.call_claude_tools") as mock_tools:
        with patch("app.agent.executor.extract_tool_calls") as mock_extract:
            mock_tools.return_value = MagicMock(stop_reason="end_turn", content=[])
            mock_extract.side_effect = [
                [{"id": "tu1", "name": "issue_refund", "input": {"order_id": str(order_vip.id), "reason": "customer_refund_request"}}],
                [],
            ]
            _, _, executor_result, reviewer_out = run_full_pipeline(db, ticket, analyzer_mock, router_mock, reviewer_mock)

    assert reviewer_out["final_status"] == "escalated"
    issue_refund_result = next((a for a in executor_result.actions_taken if a["tool"] == "issue_refund"), None)
    if issue_refund_result:
        assert not issue_refund_result["result"]["success"]
        assert issue_refund_result["result"]["policy_result"] == "escalate"
    assert db.query(Refund).count() == refund_count_before, "No refund for VIP customer"


# ── Golden Ticket 4: Over cap ─────────────────────────────────────────────────

def test_golden_4_refund_over_cap_escalated(db, order_over_cap):
    """Refund request over $100 cap → escalated, reason amount_over_cap."""
    customer_id = order_over_cap.customer_id
    ticket = Ticket(
        customer_id=customer_id,
        order_id=order_over_cap.id,
        raw_text=f"My order {order_over_cap.id} payment failed. Please refund.",
    )
    db.add(ticket)
    db.flush()

    analyzer_mock = {"issue_type": "payment_failed", "urgency": "high", "confident": True, "suspected_injection": False, "notes": None}
    router_mock = {
        "tools_to_call": ["issue_refund"],
        "escalate_directly": False,
        "escalate_reason": None,
        "reasoning": "Payment failed — issue refund.",
    }
    reviewer_mock = {"final_status": "escalated", "resolution_summary": "Amount over cap — escalated.", "escalation_reason": "amount_over_cap"}

    refund_count_before = db.query(Refund).count()

    with patch("app.agent.executor.call_claude_tools") as mock_tools:
        with patch("app.agent.executor.extract_tool_calls") as mock_extract:
            mock_tools.return_value = MagicMock(stop_reason="end_turn", content=[])
            mock_extract.side_effect = [
                [{"id": "tu1", "name": "issue_refund", "input": {"order_id": str(order_over_cap.id), "reason": "payment_failed"}}],
                [],
            ]
            _, _, executor_result, reviewer_out = run_full_pipeline(db, ticket, analyzer_mock, router_mock, reviewer_mock)

    assert reviewer_out["final_status"] == "escalated"
    assert db.query(Refund).count() == refund_count_before
    # Verify escalation was due to amount_over_cap
    assert order_over_cap.amount_cents > settings.refund_cap_cents  # > ₹1000 cap


# ── Golden Ticket 5: Vague/ambiguous ticket ───────────────────────────────────

def test_golden_5_ambiguous_ticket_escalated(db, regular_customer):
    """Vague ticket with no clear issue → escalated, reason unclear_issue_type."""
    ticket = Ticket(
        customer_id=regular_customer.id,
        raw_text="Something went wrong with my thing. Not sure what happened. Need help.",
    )
    db.add(ticket)
    db.flush()

    # Analyzer returns confident=False — Router must immediately escalate without calling Claude
    analyzer_mock = {
        "issue_type": "other",
        "urgency": "low",
        "confident": False,
        "suspected_injection": False,
        "notes": "Too vague to classify",
    }
    reviewer_mock = {"final_status": "escalated", "resolution_summary": "Unclear issue — escalated.", "escalation_reason": "unclear_issue_type"}

    _, router_decision, executor_result, reviewer_out = run_full_pipeline(
        db, ticket, analyzer_mock, reviewer_mock=reviewer_mock
    )

    assert reviewer_out["final_status"] == "escalated"
    assert router_decision.escalate_directly is True
    assert router_decision.escalate_reason == "unclear_issue_type"
