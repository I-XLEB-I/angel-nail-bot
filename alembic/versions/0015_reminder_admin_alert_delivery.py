"""store admin reminder alert message ids for live status updates

Revision ID: 0015_reminder_admin_alert_delivery
Revises: 0014_force_majeure_notice_sent_at
Create Date: 2026-05-18 11:35:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_reminder_admin_alert_delivery"
down_revision = "0014_force_majeure_notice_sent_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "reminder_admin_alert_delivery" in tables:
        return

    op.create_table(
        "reminder_admin_alert_delivery",
        # ``id`` is Integer (not BigInteger) so SQLite treats it as an alias
        # for ROWID and autoincrements on inserts without an explicit id.
        # Past incident 2026-05-19: BigInteger primary keys break inserts on SQLite.
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("booking_id", sa.BigInteger(), sa.ForeignKey("booking.id"), nullable=False),
        sa.Column("admin_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("reminder_kind", sa.String(length=10), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "booking_id",
            "admin_tg_id",
            "reminder_kind",
            name="uq_reminder_admin_alert_delivery_booking_admin_kind",
        ),
    )
    op.create_index(
        op.f("ix_reminder_admin_alert_delivery_booking_id"),
        "reminder_admin_alert_delivery",
        ["booking_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reminder_admin_alert_delivery_admin_tg_id"),
        "reminder_admin_alert_delivery",
        ["admin_tg_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reminder_admin_alert_delivery_reminder_kind"),
        "reminder_admin_alert_delivery",
        ["reminder_kind"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "reminder_admin_alert_delivery" not in tables:
        return

    op.drop_index(
        op.f("ix_reminder_admin_alert_delivery_reminder_kind"),
        table_name="reminder_admin_alert_delivery",
    )
    op.drop_index(
        op.f("ix_reminder_admin_alert_delivery_admin_tg_id"),
        table_name="reminder_admin_alert_delivery",
    )
    op.drop_index(
        op.f("ix_reminder_admin_alert_delivery_booking_id"),
        table_name="reminder_admin_alert_delivery",
    )
    op.drop_table("reminder_admin_alert_delivery")
