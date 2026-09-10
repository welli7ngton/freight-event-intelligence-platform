"""Add transactional outbox for recorded shipment notifications."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "9c8d7e6f5a4b"
down_revision = "8b7c3d2e1f0a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("shipment_events.event_id"), nullable=False),
        sa.Column("shipment_id", sa.Uuid(), nullable=False),
        sa.Column("message_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(100)),
        sa.UniqueConstraint("event_id", "message_type", name="uq_outbox_event_type"),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts_nonnegative"),
    )
    op.create_index(
        "ix_outbox_pending", "outbox_events", ["next_attempt_at", "created_at", "id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_pending", table_name="outbox_events")
    op.drop_table("outbox_events")
