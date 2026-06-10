"""store admin morning summary message ids for live confirmation updates

Revision ID: 0016_morning_summary_delivery
Revises: 0015_reminder_admin_alert_delivery
Create Date: 2026-05-18 15:15:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_morning_summary_delivery"
down_revision = "0015_reminder_admin_alert_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "morning_summary_delivery" in tables:
        return

    op.create_table(
        "morning_summary_delivery",
        # ``id`` is Integer (not BigInteger) so SQLite treats it as an alias
        # for ROWID and autoincrements on inserts without an explicit id.
        # Past incident 2026-05-19: BigInteger primary keys break inserts on SQLite.
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("admin_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("summary_local_date", sa.Date(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "admin_tg_id",
            name="uq_morning_summary_delivery_admin_tg_id",
        ),
    )
    op.create_index(
        op.f("ix_morning_summary_delivery_admin_tg_id"),
        "morning_summary_delivery",
        ["admin_tg_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_morning_summary_delivery_summary_local_date"),
        "morning_summary_delivery",
        ["summary_local_date"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "morning_summary_delivery" not in tables:
        return

    op.drop_index(
        op.f("ix_morning_summary_delivery_summary_local_date"),
        table_name="morning_summary_delivery",
    )
    op.drop_index(
        op.f("ix_morning_summary_delivery_admin_tg_id"),
        table_name="morning_summary_delivery",
    )
    op.drop_table("morning_summary_delivery")
