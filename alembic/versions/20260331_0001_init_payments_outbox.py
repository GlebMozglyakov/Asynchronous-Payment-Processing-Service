"""Create payments and outbox tables.

Revision ID: 20260331_0001
Revises:
Create Date: 2026-03-31 00:00:01.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260331_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("webhook_url", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("webhook_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("webhook_last_error", sa.Text(), nullable=True),
        sa.Column("webhook_lock_id", sa.String(length=64), nullable=True),
        sa.Column("webhook_locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
        sa.CheckConstraint("currency IN ('RUB','USD','EUR')", name="ck_payments_currency"),
        sa.CheckConstraint(
            "status IN ('pending','succeeded','failed')",
            name="ck_payments_status",
        ),
    )
    op.create_index("ix_payments_idempotency_key", "payments", ["idempotency_key"])
    op.create_index("ix_payments_webhook_lock_id", "payments", ["webhook_lock_id"])

    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lock_id", sa.String(length=64), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending','in_progress','published','failed')",
            name="ck_outbox_status",
        ),
    )
    op.create_index("ix_outbox_event_type", "outbox", ["event_type"])
    op.create_index("ix_outbox_aggregate_id", "outbox", ["aggregate_id"])
    op.create_index("ix_outbox_status", "outbox", ["status"])
    op.create_index("ix_outbox_lock_id", "outbox", ["lock_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_webhook_lock_id", table_name="payments")
    op.drop_index("ix_outbox_lock_id", table_name="outbox")
    op.drop_index("ix_outbox_status", table_name="outbox")
    op.drop_index("ix_outbox_aggregate_id", table_name="outbox")
    op.drop_index("ix_outbox_event_type", table_name="outbox")
    op.drop_table("outbox")

    op.drop_index("ix_payments_idempotency_key", table_name="payments")
    op.drop_table("payments")
