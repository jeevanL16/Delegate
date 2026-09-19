import uuid
import json as _json
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Cross-database compatible types ───────────────────────────────────────────

try:
    from sqlalchemy.dialects.postgresql import ARRAY as _PG_ARRAY, JSONB as _PG_JSONB
    from sqlalchemy.dialects.postgresql import UUID as _PG_UUID
    _HAVE_PG = True
except ImportError:
    _HAVE_PG = False


class _JSONList(TypeDecorator):
    """Stores a list as JSON — works on SQLite and PostgreSQL alike."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return "[]"
        if isinstance(value, list):
            return _json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        try:
            return _json.loads(value)
        except Exception:
            return []


class _UUIDType(TypeDecorator):
    """Stores UUID as string — works on SQLite and PostgreSQL alike."""
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))



class _CompatibleArray(TypeDecorator):
    """Postgres ARRAY(Text) on PostgreSQL, JSON on SQLite."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PG_ARRAY(Text))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return []
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return _json.loads(value)
            except Exception:
                return []
        return list(value)


class _CompatibleJSON(TypeDecorator):
    """Postgres JSONB on PostgreSQL, JSON on SQLite."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PG_JSONB())
        return dialect.type_descriptor(JSON())


from sqlalchemy import Uuid

def _uuid_col():
    return Uuid(as_uuid=True)

def _jsonb_col():
    return _CompatibleJSON()

def _array_col():
    return _CompatibleArray()



class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(_uuid_col(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    flags: Mapped[list] = mapped_column(_array_col(), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (CheckConstraint("tier IN ('regular','vip')", name="ck_customers_tier"),)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(_uuid_col(), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(_uuid_col(), ForeignKey("customers.id"), nullable=False)
    # amount stored in cents (1 USD = 100 cents) per MASTER_BUILD_PROMPT §6
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        CheckConstraint("status IN ('delivered','failed','pending','refunded')", name="ck_orders_status"),
        Index("idx_orders_customer", "customer_id"),
    )


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(_uuid_col(), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(_uuid_col(), ForeignKey("customers.id"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(_uuid_col(), ForeignKey("orders.id"), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    issue_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspected_injection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('open','resolved','escalated')", name="ck_tickets_status"),
        Index("idx_tickets_customer", "customer_id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(_uuid_col(), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(_uuid_col(), ForeignKey("tickets.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    input_json: Mapped[dict | None] = mapped_column(_jsonb_col(), nullable=True)
    output_json: Mapped[dict | None] = mapped_column(_jsonb_col(), nullable=True)
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False)  # NOT NULL — schema-enforced
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        CheckConstraint(
            "stage IN ('analyzer','router','executor','reviewer','policy')",
            name="ck_audit_stage",
        ),
        Index("idx_audit_ticket", "ticket_id"),
    )


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = mapped_column(_uuid_col(), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(_uuid_col(), ForeignKey("tickets.id"), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(_uuid_col(), ForeignKey("orders.id"), nullable=False)
    # amount in cents — always copied from orders.amount_cents, never from model output
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("idx_refunds_ticket", "ticket_id"),)
