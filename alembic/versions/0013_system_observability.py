"""Add system alert and scheduler health tables.

Revision ID: 0013_system_observability
Revises: 0012_booking_24h_unconfirmed_alert
Create Date: 2026-05-18
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0013_system_observability"
down_revision = "0012_booking_24h_unconfirmed_alert"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)
    pk_type = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

    if "system_alert_event" not in tables:
        op.create_table(
            "system_alert_event",
            sa.Column("id", pk_type, primary_key=True),
            sa.Column("kind", sa.String(length=50), nullable=False),
            sa.Column("signature", sa.String(length=255), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("repeat_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("kind", "signature", name="uq_system_alert_event_kind_signature"),
        )
        op.create_index(
            op.f("ix_system_alert_event_kind"),
            "system_alert_event",
            ["kind"],
            unique=False,
        )
        op.create_index(
            op.f("ix_system_alert_event_signature"),
            "system_alert_event",
            ["signature"],
            unique=False,
        )

    if "system_job_status" not in tables:
        op.create_table(
            "system_job_status",
            sa.Column("job_name", sa.String(length=100), primary_key=True),
            sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_outcome", sa.String(length=20), nullable=True),
            sa.Column("last_error_type", sa.String(length=100), nullable=True),
            sa.Column("last_error_message", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)

    if "system_job_status" in tables:
        op.drop_table("system_job_status")

    if "system_alert_event" in tables:
        op.drop_index(op.f("ix_system_alert_event_signature"), table_name="system_alert_event")
        op.drop_index(op.f("ix_system_alert_event_kind"), table_name="system_alert_event")
        op.drop_table("system_alert_event")
