from datetime import datetime
from uuid import UUID

from app.infra.database.base import Base
from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column


class ShipmentModel(Base):
    __tablename__ = "shipments"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
    )

    reference_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    origin: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    destination: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    carrier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    current_latitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    current_longitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    last_location_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
