"""
ui/humanizer.py
Converts backend ticket responses, statuses, and audit trails into natural,
customer-friendly language that directly answers the customer's query without
leaking internal system details or tool names.
Uses LLM-based intelligent response synthesis with a safe rule-based fallback.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logger = logging.getLogger(__name__)


def fmt_inr(cents: Optional[int]) -> str:
    """Format integer cents into Indian Rupee (INR) representation."""
    if cents is None:
        return "—"
    rupees = cents / 100.0
    return f"₹{rupees:,.2f}"


def _generate_llm_response(
    ticket: dict[str, Any],
    order: Optional[dict[str, Any]] = None,
    user_message: Optional[str] = None,
    customer_name: Optional[str] = None,
) -> Optional[str]:
    """Use Groq LLM to synthesize a tailored, empathetic answer directly addressing the customer's inquiry."""
    try:
        from app.agent.llm_client import _get_client, _resolve_model
        client, provider = _get_client()
        active_model = _resolve_model(provider)

        status = (ticket.get("status") or "").lower()
        resolution = ticket.get("resolution") or ""
        cust_name = customer_name or "Customer"

        order_str = "None on file"
        if order:
            amt = fmt_inr(order.get("amount_cents"))
            stat = order.get("status", "unknown")
            order_str = f"Order #{str(order.get('id', ''))[:8]}… (Amount: {amt}, Status: {stat})"

        system_prompt = (
            "You are Delegate Support AI, an empathetic, highly professional customer support specialist for an e-commerce platform in India.\n"
            "Your job is to directly, warmly, and accurately answer the customer's specific question using their order status and support resolution.\n\n"
            "Guidelines:\n"
            "1. Answer what the customer asked directly and clearly in 2 to 4 concise sentences.\n"
            "2. If the customer asks why their order or payment failed, explain empathetically that payment failures typically happen due to bank authorization timeouts, network drops, or payment gateway security checks.\n"
            "3. Reassure the customer regarding their funds: confirm any processed refund (with amount in ₹ and 3-5 business day timeline) or reassure them that any debited amount automatically reverses.\n"
            "4. Always format currency in Indian Rupees (₹).\n"
            "5. NEVER reveal internal tool names, internal policy rule names, or raw JSON structures.\n"
            "6. If the ticket is escalated, explain clearly and reassure the customer that our senior priority specialist team is personally reviewing their case.\n"
            "7. Always address the customer warmly by name."
        )

        user_prompt = (
            f"Customer Name: {cust_name}\n"
            f"Customer Inquiry: \"{user_message or 'Order support inquiry'}\"\n"
            f"Active Order Info: {order_str}\n"
            f"Ticket Status: {status}\n"
            f"Resolution Summary: {resolution}\n"
        )

        resp = client.chat.completions.create(
            model=active_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=300,
            timeout=8.0,
        )
        content = resp.choices[0].message.content
        if content and content.strip():
            return content.strip()
    except Exception as exc:
        logger.warning("LLM response synthesis failed (falling back to rule-based template): %s", exc)

    return None


def humanize(
    ticket: dict[str, Any],
    order: Optional[dict[str, Any]] = None,
    user_message: Optional[str] = None,
    customer_name: Optional[str] = None,
) -> str:
    """
    Generate a clean, empathetic, natural sentence response for the customer.
    Attempts LLM synthesis first for personalized answers to user queries,
    with an immediate robust rule-based fallback.
    """
    # 1. Attempt AI-powered contextual answer
    ai_reply = _generate_llm_response(ticket, order, user_message, customer_name)
    if ai_reply:
        return ai_reply

    # 2. Rule-based Fallback
    status = (ticket.get("status") or "").lower()
    resolution = ticket.get("resolution") or ""
    issue_type = (ticket.get("issue_type") or "").lower()

    amount_str = None
    if order and "amount_cents" in order:
        amount_str = fmt_inr(order.get("amount_cents"))

    # Case 1: Escalated to human specialist
    if status == "escalated":
        return (
            "Thank you for reaching out. I have looped in a senior specialist on our priority "
            "team to carefully review your account and order details. They will follow up "
            "with you directly via email shortly."
        )

    # Case 2: Order already refunded previously
    if "already" in resolution.lower() and "refund" in resolution.lower():
        if amount_str:
            return (
                f"We checked your account records, and a full refund of {amount_str} has already "
                "been processed for this order. It typically takes 3–5 business days to reflect on "
                "your card or bank statement. Please let us know if you have not received it yet."
            )
        return (
            "Our records indicate that this transaction has already been refunded. "
            "It usually reflects in your account within 3–5 business days. Please feel free "
            "to reach back out if you do not see it reflected on your statement."
        )

    # Case 3: Refund newly issued
    if status == "resolved" and ("refund" in issue_type or "refund" in resolution.lower()):
        if amount_str:
            return (
                f"Good news! We have approved and processed a full refund of {amount_str} for your "
                "order. The amount will be credited back to your original payment method within "
                "3–5 business days."
            )
        return (
            "Good news! Your refund request has been approved and processed. "
            "The funds should be credited back to your original payment method within "
            "3–5 business days."
        )

    # Case 4: Order status query (delivered, in transit, failed)
    if order and order.get("status") == "delivered":
        return (
            "According to our carrier tracking details, your order has been successfully delivered. "
            "Please check around your delivery location or reception, and let us know if you need "
            "any further assistance!"
        )

    if order and order.get("status") == "failed":
        return (
            f"We noticed that payment for this order ({amount_str or 'recent transaction'}) "
            "did not go through successfully. If any funds were deducted from your account, "
            "they will be automatically reversed by your bank within 2–4 business days."
        )

    # Case 5: Resolved general inquiry
    if status == "resolved" and resolution:
        lowered = resolution.lower()
        leaked_keywords = ["tool", "policy", "executor", "router", "analyzer", "trace", "json", "cents", "error", "auth"]
        if any(k in lowered for k in leaked_keywords):
            return (
                "Your request has been successfully processed. Please let us know if you have "
                "any questions or if there is anything else we can assist you with."
            )
        return resolution.strip()

    # Case 6: Generic polite fallback
    return (
        "Thank you for contacting Delegate Support. We are reviewing your order details "
        "and will ensure this is resolved for you right away."
    )
