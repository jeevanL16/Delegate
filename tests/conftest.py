"""pytest configuration and shared fixtures."""
import os
import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from unittest.mock import MagicMock, patch

# Set env vars before any app imports
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_delegate.db")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("SERVICE_API_KEY", "test-service-key")
os.environ.setdefault("HUMAN_JWT_SECRET", "test-jwt-secret")

# Import models (now handle SQLite/PG detection themselves)
from app.db.models import Base, Customer, Order, Ticket
from app.db.session import get_db
from app.main import app


# ── Test database ─────────────────────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite:///./test_delegate.db"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Session:
    connection = engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ── Seed fixture IDs (match seed/customers.json and seed/orders.json) ─────────

CUSTOMER_REGULAR_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
CUSTOMER_VIP_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
CUSTOMER_COMPLAINER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
CUSTOMER_B_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")

ORDER_ALREADY_REFUNDED_ID = uuid.UUID("aaaa0001-0000-0000-0000-000000000001")
ORDER_FAILED_UNDER_CAP_ID = uuid.UUID("aaaa0002-0000-0000-0000-000000000002")
ORDER_VIP_ID = uuid.UUID("aaaa0003-0000-0000-0000-000000000003")
ORDER_OVER_CAP_ID = uuid.UUID("aaaa0004-0000-0000-0000-000000000004")
ORDER_CUSTOMER_B_ID = uuid.UUID("aaaa0005-0000-0000-0000-000000000005")


@pytest.fixture
def regular_customer(db: Session) -> Customer:
    c = Customer(
        id=CUSTOMER_REGULAR_ID,
        name="Arjun Sharma",
        email="arjun@test.in",
        tier="regular",
        flags=[],
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def vip_customer(db: Session) -> Customer:
    c = Customer(
        id=CUSTOMER_VIP_ID,
        name="Priya Nair",
        email="priya@test.in",
        tier="vip",
        flags=[],
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def complainer_customer(db: Session) -> Customer:
    c = Customer(
        id=CUSTOMER_COMPLAINER_ID,
        name="Rohit Mehta",
        email="rohit@test.in",
        tier="regular",
        flags=["repeat_complainer"],
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def customer_b(db: Session) -> Customer:
    c = Customer(
        id=CUSTOMER_B_ID,
        name="Vikram Patel",
        email="vikram@test.in",
        tier="regular",
        flags=[],
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def order_already_refunded(db: Session, regular_customer: Customer) -> Order:
    o = Order(
        id=ORDER_ALREADY_REFUNDED_ID,
        customer_id=regular_customer.id,
        amount_cents=4990,  # $49.90 — already refunded
        status="refunded",
    )
    db.add(o)
    db.flush()
    return o


@pytest.fixture
def order_failed_under_cap(db: Session, regular_customer: Customer) -> Order:
    o = Order(
        id=ORDER_FAILED_UNDER_CAP_ID,
        customer_id=regular_customer.id,
        amount_cents=8990,  # $89.90 — under $100 cap
        status="failed",
    )
    db.add(o)
    db.flush()
    return o


@pytest.fixture
def order_vip(db: Session, vip_customer: Customer) -> Order:
    o = Order(
        id=ORDER_VIP_ID,
        customer_id=vip_customer.id,
        amount_cents=4990,  # $49.90 — VIP customer (under $100 cap so VIP triggers escalation)
        status="delivered",
    )
    db.add(o)
    db.flush()
    return o


@pytest.fixture
def order_over_cap(db: Session, regular_customer: Customer) -> Order:
    c = Customer(id=uuid.UUID("44444444-4444-4444-4444-444444444444"), name="Deepa", email="d@t.in", tier="regular", flags=[])
    db.add(c)
    db.flush()
    o = Order(
        id=ORDER_OVER_CAP_ID,
        customer_id=c.id,
        amount_cents=150_000,  # ₹1500.00 — over ₹1000 cap
        status="failed",
    )
    db.add(o)
    db.flush()
    return o


@pytest.fixture
def order_customer_b(db: Session, customer_b: Customer) -> Order:
    o = Order(
        id=ORDER_CUSTOMER_B_ID,
        customer_id=customer_b.id,
        amount_cents=3490,  # $34.90
        status="delivered",
    )
    db.add(o)
    db.flush()
    return o
