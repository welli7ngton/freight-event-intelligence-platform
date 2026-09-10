from datetime import datetime
from uuid import UUID

from app.infra.database.base import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("event_id", "message_type", name="uq_outbox_event_type"),
        CheckConstraint("attempts >= 0", name="ck_outbox_attempts_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("shipment_events.event_id"), nullable=False
    )
    shipment_id: Mapped[UUID] = mapped_column(nullable=False)
    message_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(100))


Index(
    "ix_outbox_pending",
    OutboxEventModel.next_attempt_at,
    OutboxEventModel.created_at,
    OutboxEventModel.id,
    postgresql_where=OutboxEventModel.published_at.is_(None),
)
