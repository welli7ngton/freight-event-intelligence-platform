"""add shipment event processing status

Revision ID: 8b7c3d2e1f0a
Revises: 6f8e4c7a1b2d
Create Date: 2026-09-09
"""

import sqlalchemy as sa
from alembic import op


revision = "8b7c3d2e1f0a"
down_revision = "6f8e4c7a1b2d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shipment_events",
        sa.Column(
            "processing_status",
            sa.String(length=32),
            nullable=False,
            server_default="APPLIED",
        ),
    )
    op.add_column(
        "shipments",
        sa.Column("last_lifecycle_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shipments", "last_lifecycle_at")
    op.drop_column("shipment_events", "processing_status")
