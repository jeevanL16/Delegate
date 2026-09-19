"""Router stage — decides which tools to call or escalates directly.

Also injects Cognee memory context (<past_context>) before calling the LLM.
Per §8.8: recalled context is labeled as background info, not instructions.
"""
import logging
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session

# Import with backward-compat alias so test patches on 'call_claude_json' still work
from app.agent.llm_client import call_llm_json as call_claude_json
from app.agent.prompts import ROUTER_SYSTEM_PROMPT
from app.db.models import AuditLog, Ticket
from app.schemas.tool_io import AnalyzerOutput, RouterDecision

logger = logging.getLogger(__name__)

VALID_TOOLS = {
    "get_order_status",
    "issue_refund",
    "update_ticket_status",
    "escalate_to_human",
    "notify_customer",
}


def run_router(
    db: Session,
    ticket: Ticket,
    analyzer_output: AnalyzerOutput,
) -> RouterDecision:
    """
    Run the Router stage.

    If suspected_injection is True, immediately escalate without calling the LLM
    (§8 rule 4 — skip all tool execution).
    """
    # ── Hard rule: injection → immediate escalation, no LLM call needed ──────
    if analyzer_output.suspected_injection:
        decision = RouterDecision(
            tools_to_call=[],
            escalate_directly=True,
            escalate_reason="suspected_prompt_injection",
            reasoning="Analyzer flagged suspected prompt injection — routing directly to human.",
        )
        _write_audit(db, ticket.id, analyzer_output, decision)
        return decision

    # ── Hard rule: low confidence → escalate ─────────────────────────────────
    if not analyzer_output.confident:
        decision = RouterDecision(
            tools_to_call=[],
            escalate_directly=True,
            escalate_reason="unclear_issue_type",
            reasoning="Analyzer could not confidently classify the issue type.",
        )
        _write_audit(db, ticket.id, analyzer_output, decision)
        return decision

    user_message = (
        f"Analyzer output:\n{analyzer_output.model_dump_json(indent=2)}\n\n"
        f"Ticket metadata:\n"
        f"  ticket_id: {ticket.id}\n"
        f"  customer_id: {ticket.customer_id}\n"
        f"  order_id: {ticket.order_id or 'not provided'}\n"
    )

    try:
        raw = call_claude_json(ROUTER_SYSTEM_PROMPT, user_message)
        decision = RouterDecision(**raw)
        # Validate tool names — only our 5 tools are allowed
        invalid = [t for t in decision.tools_to_call if t not in VALID_TOOLS]
        if invalid:
            raise ValueError(f"router_proposed_invalid_tools: {invalid}")
    except (ValueError, ValidationError) as exc:
        logger.error("Router stage failed for ticket %s: %s", ticket.id, exc)
        decision = RouterDecision(
            tools_to_call=[],
            escalate_directly=True,
            escalate_reason="internal_error",
            reasoning=f"Router error: {type(exc).__name__}",
        )

    _write_audit(db, ticket.id, analyzer_output, decision)
    logger.info(
        "Router ticket=%s escalate=%s tools=%s reason=%s",
        ticket.id, decision.escalate_directly, decision.tools_to_call,
        decision.escalate_reason,
    )
    return decision


def _write_audit(db: Session, ticket_id: uuid.UUID, inp: AnalyzerOutput, out: RouterDecision) -> None:
    entry = AuditLog(
        ticket_id=ticket_id,
        stage="router",
        action="route_ticket",
        input_json=inp.model_dump(),
        output_json=out.model_dump(),
        decision_reason=(
            out.escalate_reason or f"tools:{','.join(out.tools_to_call)}"
        ),
    )
    db.add(entry)
    db.flush()
