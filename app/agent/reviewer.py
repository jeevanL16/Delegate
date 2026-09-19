"""Reviewer stage — confirms outcome and writes final resolution.

Also stores the ticket outcome in Cognee memory (§13) after DB write.
"""
import logging
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session

# Import with backward-compat alias so test patches on 'call_claude_json' still work
from app.agent.llm_client import call_llm_json as call_claude_json
from app.agent.executor import ExecutorResult
from app.agent.prompts import REVIEWER_SYSTEM_PROMPT
from app.db.models import AuditLog, Ticket
from app.schemas.tool_io import AnalyzerOutput

logger = logging.getLogger(__name__)


def run_reviewer(
    db: Session,
    ticket: Ticket,
    analyzer_output: AnalyzerOutput,
    executor_result: ExecutorResult,
) -> dict:
    """
    Run the Reviewer stage to confirm the final status and write the resolution.
    Returns a dict with keys: final_status, resolution_summary, escalation_reason.
    """
    user_message = (
        f"Ticket ID: {ticket.id}\n"
        f"Issue type: {analyzer_output.issue_type}\n"
        f"Executor result:\n"
        f"  final_status: {executor_result.final_status}\n"
        f"  escalation_reason: {executor_result.escalation_reason}\n"
        f"  actions_taken: {executor_result.actions_taken}\n\n"
        f"Confirm the final status and write a brief factual resolution summary."
    )

    try:
        raw = call_claude_json(REVIEWER_SYSTEM_PROMPT, user_message)
        # Validate expected keys
        final_status = raw.get("final_status", executor_result.final_status)
        resolution_summary = raw.get("resolution_summary", "")
        escalation_reason = raw.get("escalation_reason")

        if final_status not in ("resolved", "escalated"):
            raise ValueError(f"invalid_final_status: {final_status}")

    except (ValueError, ValidationError) as exc:
        logger.error("Reviewer failed for ticket %s: %s — defaulting to escalation", ticket.id, exc)
        final_status = "escalated"
        resolution_summary = "Reviewer stage error — escalated for human review."
        escalation_reason = "internal_error"

    # Update ticket record
    ticket.status = final_status
    ticket.resolution = resolution_summary
    if not ticket.resolved_at and final_status in ("resolved", "escalated"):
        ticket.resolved_at = datetime.now(timezone.utc)
    db.flush()

    # Write audit
    entry = AuditLog(
        ticket_id=ticket.id,
        stage="reviewer",
        action="confirm_resolution",
        input_json={
            "executor_final_status": executor_result.final_status,
            "actions_count": len(executor_result.actions_taken),
        },
        output_json={
            "final_status": final_status,
            "resolution_summary": resolution_summary,
            "escalation_reason": escalation_reason,
        },
        decision_reason=f"final_status={final_status}",
    )
    db.add(entry)
    db.flush()

    logger.info("Reviewer ticket=%s final_status=%s", ticket.id, final_status)

    return {
        "final_status": final_status,
        "resolution_summary": resolution_summary,
        "escalation_reason": escalation_reason,
    }
