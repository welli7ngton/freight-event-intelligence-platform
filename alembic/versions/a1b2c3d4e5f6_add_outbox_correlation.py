"""Persist optional transport correlation without changing v1 envelopes."""

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "9c8d7e6f5a4b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("correlation_id", sa.String(64)))


def downgrade() -> None:
    op.drop_column("outbox_events", "correlation_id")
