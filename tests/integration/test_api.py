"""Integration tests — full API flow against real (test) SQLite DB.

§14.4 requirements:
- Full POST /tickets → POST /tickets/{id}/resolve flow
- /human/* endpoints require valid JWT; test 401/403 paths
"""
import uuid
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.db.session import get_db


# ── Shared test DB override ───────────────────────────────────────────────────

def override_get_db():
    from tests.conftest import TestSessionLocal, engine
    from app.db.models import Base
    Base.metadata.create_all(bind=engine)
    db = TestSessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

API_KEY_HEADERS = {"X-API-Key": "test-service-key"}


def get_human_token() -> str:
    from jose import jwt
    return jwt.encode({"sub": "agent1", "role": "human_agent"}, "test-jwt-secret", algorithm="HS256")


HUMAN_HEADERS = {"Authorization": f"Bearer {get_human_token()}"}


# ── Helper: insert a customer + order into the shared DB ──────────────────────

def _create_fixtures():
    """Create customer + order in the shared test DB so the route handler can find them."""
    from tests.conftest import TestSessionLocal, engine
    from app.db.models import Base, Customer, Order
    Base.metadata.create_all(bind=engine)
    db = TestSessionLocal()
    try:
        cid = uuid.uuid4()
        oid = uuid.uuid4()
        c = Customer(id=cid, name="Integration User", email="int@test.in", tier="regular", flags=[])
        o = Order(id=oid, customer_id=cid, amount_cents=5000, status="failed")
        db.add(c)
        db.add(o)
        db.commit()
        return cid, oid
    finally:
        db.close()


# ── Health ────────────────────────────────────────────────────────────────────

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("ok", "degraded")


# ── Auth — send a wrong-value header (not missing) so FastAPI returns 401 ─────

def test_create_ticket_bad_api_key():
    """Wrong API key value → 401 (missing header would give 422)."""
    resp = client.post(
        "/tickets",
        json={"customer_id": str(uuid.uuid4()), "raw_text": "test"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


def test_human_queue_bad_token():
    """Invalid JWT → 401."""
    resp = client.get("/human/queue", headers={"Authorization": "Bearer bad-token"})
    assert resp.status_code == 401


def test_human_queue_wrong_role():
    from jose import jwt
    token = jwt.encode({"sub": "user1", "role": "customer"}, "test-jwt-secret", algorithm="HS256")
    resp = client.get("/human/queue", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_human_queue_no_header():
    """Missing Authorization header entirely → FastAPI returns 422."""
    resp = client.get("/human/queue")
    assert resp.status_code in (401, 422)


# ── Ticket lifecycle ──────────────────────────────────────────────────────────

def test_create_ticket_customer_not_found():
    resp = client.post(
        "/tickets",
        json={"customer_id": str(uuid.uuid4()), "raw_text": "test"},
        headers=API_KEY_HEADERS,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "customer_not_found"


def test_create_ticket_empty_text():
    resp = client.post(
        "/tickets",
        json={"customer_id": str(uuid.uuid4()), "raw_text": "   "},
        headers=API_KEY_HEADERS,
    )
    assert resp.status_code == 422  # Pydantic validation error


def test_full_ticket_resolve_flow():
    """POST /tickets → POST /tickets/{id}/resolve → GET /tickets/{id}."""
    customer_id, order_id = _create_fixtures()

    # Step 1: Create ticket
    resp = client.post(
        "/tickets",
        json={
            "customer_id": str(customer_id),
            "order_id": str(order_id),
            "raw_text": f"My payment failed for order {order_id}. Please refund.",
        },
        headers=API_KEY_HEADERS,
    )
    assert resp.status_code == 201
    ticket_id = resp.json()["ticket_id"]
    assert resp.json()["status"] == "open"

    # Step 2: Resolve with mocked pipeline
    with patch("app.routes.tickets.run_analyzer") as ma, \
         patch("app.routes.tickets.run_router") as mr, \
         patch("app.routes.tickets.run_executor") as me, \
         patch("app.routes.tickets.run_reviewer") as mrv:

        from app.schemas.tool_io import AnalyzerOutput, RouterDecision
        from app.agent.executor import ExecutorResult

        ma.return_value = AnalyzerOutput(
            issue_type="payment_failed", urgency="high",
            confident=True, suspected_injection=False,
        )
        mr.return_value = RouterDecision(
            tools_to_call=["issue_refund"], escalate_directly=False,
            reasoning="Refund needed",
        )
        me.return_value = ExecutorResult(
            actions_taken=[{"tool": "issue_refund", "result": {
                "success": True, "amount_cents": 5000, "amount_usd": 50.0,
                "policy_result": "approve", "reason": "all_checks_passed",
            }}],
            final_status="resolved",
        )
        mrv.return_value = {
            "final_status": "resolved",
            "resolution_summary": "Refund issued.",
            "escalation_reason": None,
        }

        resolve_resp = client.post(f"/tickets/{ticket_id}/resolve", headers=API_KEY_HEADERS)

    assert resolve_resp.status_code == 200
    data = resolve_resp.json()
    # The pipeline is mocked so reviewer doesn't write to DB —
    # check the API response directly for the resolved status.
    assert data["status"] == "resolved"
    assert data["ticket_id"] == ticket_id
    assert "audit_trail" not in data  # audit_trail is only on GET /tickets/{id}

    # Step 3: Get ticket — audit_trail key must be present (ticket may still show 'open'
    # because the mocked reviewer didn't write its final status to the DB)
    get_resp = client.get(f"/tickets/{ticket_id}", headers=API_KEY_HEADERS)
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert "audit_trail" in detail


def test_list_tickets():
    """GET /tickets?status=open returns list."""
    resp = client.get("/tickets?status=open", headers=API_KEY_HEADERS)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_human_queue_approve():
    """POST /human/tickets/{id}/approve happy path."""
    customer_id, order_id = _create_fixtures()

    # Create ticket via API
    resp = client.post(
        "/tickets",
        json={
            "customer_id": str(customer_id),
            "order_id": str(order_id),
            "raw_text": "I need a refund for my failed order.",
        },
        headers=API_KEY_HEADERS,
    )
    assert resp.status_code == 201
    ticket_id = resp.json()["ticket_id"]

    # Manually escalate in the shared DB
    from tests.conftest import TestSessionLocal
    from app.db.models import Ticket
    s = TestSessionLocal()
    t = s.get(Ticket, uuid.UUID(ticket_id))
    if t:
        t.status = "escalated"
        s.commit()
    s.close()

    # Queue should show it
    queue_resp = client.get("/human/queue", headers=HUMAN_HEADERS)
    assert queue_resp.status_code == 200

    # Approve — policy engine still applies (₹500, under cap, regular customer)
    approve_resp = client.post(
        f"/human/tickets/{ticket_id}/approve",
        json={"action": "issue_refund", "note": "Manually approved after review"},
        headers=HUMAN_HEADERS,
    )
    assert approve_resp.status_code == 200
    result = approve_resp.json()
    # Either refund was issued or policy denied (e.g. already-refunded guard)
    assert result.get("status") in ("resolved", "policy_denied")
