"""add shipment location fields

Revision ID: 6f8e4c7a1b2d
Revises: 34fe2111c108
Create Date: 2026-09-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6f8e4c7a1b2d"
down_revision: Union[str, Sequence[str], None] = "34fe2111c108"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shipments",
        sa.Column("current_latitude", sa.Float(), nullable=True),
    )
    op.add_column(
        "shipments",
        sa.Column("current_longitude", sa.Float(), nullable=True),
    )
    op.add_column(
        "shipments",
        sa.Column(
            "last_location_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("shipments", "last_location_at")
    op.drop_column("shipments", "current_longitude")
    op.drop_column("shipments", "current_latitude")
