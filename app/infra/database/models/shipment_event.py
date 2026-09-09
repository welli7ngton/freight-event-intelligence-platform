from datetime import datetime
from uuid import UUID

from app.infra.database.base import Base
from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Uses JSONB on Postgres and act as fallback for JSON on SQLite
JSONType = JSONB().with_variant(JSON, "sqlite")


class ShipmentEventModel(Base):
    __tablename__ = "shipment_events"

    event_id: Mapped[UUID] = mapped_column(
        primary_key=True,
    )

    shipment_id: Mapped[UUID] = mapped_column(
        ForeignKey("shipments.id"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    payload: Mapped[dict] = mapped_column(
        JSONType,
        nullable=False,
    )

    processing_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="APPLIED",
    )
