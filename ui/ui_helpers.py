"""
ui/ui_helpers.py
Reusable HTML and UI rendering helpers for the Delegate: Resolve Chainlit application.
Provides dark-metallic glass card components for order banners, section headers,
empty states, and policy badges.
"""

from typing import Any, Optional
from ui.humanizer import fmt_inr


def render_order_banner(order: Optional[dict[str, Any]]) -> str:
    """Render an elevated glass banner showing the customer's active order status."""
    if not order:
        return ""

    order_id = str(order.get("id", ""))
    short_id = order_id[:8] if order_id else "N/A"
    amount = order.get("amount_cents")
    amt_display = fmt_inr(amount) if amount is not None else ""
    status = str(order.get("status", "processing")).upper()

    order_details = f"Order <strong>#{short_id}</strong>"
    if amt_display and amt_display != "—":
        order_details += f" &bull; <strong>{amt_display}</strong>"

    return (
        f'\n\n<div class="order-banner">'
        f'<img src="/public/icons/package.svg" width="20" height="20" class="order-banner-icon" alt="Order" />'
        f'<span>Active {order_details} &bull; <span class="status-pill">{status}</span></span>'
        f'</div>'
    )


def render_empty_state(title: str, description: str) -> str:
    """Render a clean empty state card with illustration when the escalation queue is empty."""
    return (
        f'<div class="empty-state-card">'
        f'<img src="/public/empty_state.svg" width="100" height="100" alt="Empty Queue" style="margin: 0 auto 12px; display: block;" />'
        f'<h3>{title}</h3>'
        f'<p>{description}</p>'
        f'</div>'
    )


def render_section_header(title: str, count: Optional[int] = None) -> str:
    """Render a prominent section header for staff dashboard with pending count badge."""
    badge_html = f'<span class="badge-count">{count} Pending</span>' if count is not None else ""
    return (
        f'<div class="section-header">'
        f'<div class="section-title-wrap">'
        f'<img src="/public/icons/shield-check.svg" width="22" height="22" alt="Section" />'
        f'<span class="section-title">{title}</span>'
        f'</div>'
        f'{badge_html}'
        f'</div>'
    )


def render_policy_footer() -> str:
    """Render a subtle trust badge at the footer of automated resolutions."""
    return (
        '\n\n<div class="policy-footer-badge">'
        '<img src="/public/icons/lock.svg" width="13" height="13" alt="Policy" />'
        '<span>Protected &amp; authorized under Delegate Policy Engine v2.4</span>'
        '</div>'
    )
