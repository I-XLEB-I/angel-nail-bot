"""Add anti-abuse fields, counters, and audit events."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table_name)}


def _table_names(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    pk_type = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

    user_columns = _column_names(bind, "user")
    if "is_shadow_banned" not in user_columns:
        op.add_column(
            "user",
            sa.Column("is_shadow_banned", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "strikes" not in user_columns:
        op.add_column(
            "user",
            sa.Column("strikes", sa.Integer(), nullable=False, server_default="0"),
        )
    if "requires_manual_approval" not in user_columns:
        op.add_column(
            "user",
            sa.Column(
                "requires_manual_approval",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "duplicate_phone_flag" not in user_columns:
        op.add_column(
            "user",
            sa.Column(
                "duplicate_phone_flag", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )

    booking_columns = _column_names(bind, "booking")
    if "reschedules_count" not in booking_columns:
        op.add_column(
            "booking",
            sa.Column("reschedules_count", sa.Integer(), nullable=False, server_default="0"),
        )

    if "rate_limit_events" not in _table_names(bind):
        op.create_table(
            "rate_limit_events",
            sa.Column("id", pk_type, primary_key=True),
            sa.Column("user_id", pk_type, sa.ForeignKey("user.id"), nullable=False),
            sa.Column("kind", sa.String(length=50), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            op.f("ix_rate_limit_events_user_id"), "rate_limit_events", ["user_id"], unique=False
        )
        op.create_index(
            op.f("ix_rate_limit_events_kind"), "rate_limit_events", ["kind"], unique=False
        )
        op.create_index(
            op.f("ix_rate_limit_events_created_at"),
            "rate_limit_events",
            ["created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()

    if "rate_limit_events" in _table_names(bind):
        op.drop_index(op.f("ix_rate_limit_events_created_at"), table_name="rate_limit_events")
        op.drop_index(op.f("ix_rate_limit_events_kind"), table_name="rate_limit_events")
        op.drop_index(op.f("ix_rate_limit_events_user_id"), table_name="rate_limit_events")
        op.drop_table("rate_limit_events")

    booking_columns = _column_names(bind, "booking")
    if "reschedules_count" in booking_columns:
        op.drop_column("booking", "reschedules_count")

    user_columns = _column_names(bind, "user")
    if "duplicate_phone_flag" in user_columns:
        op.drop_column("user", "duplicate_phone_flag")
    if "requires_manual_approval" in user_columns:
        op.drop_column("user", "requires_manual_approval")
    if "strikes" in user_columns:
        op.drop_column("user", "strikes")
    if "is_shadow_banned" in user_columns:
        op.drop_column("user", "is_shadow_banned")
