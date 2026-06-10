"""Add late-arrival notices and repair-request fields."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    approval_columns = _column_names(bind, "approval_request")

    if "repair_nails_count" not in approval_columns:
        op.add_column(
            "approval_request",
            sa.Column("repair_nails_count", sa.Integer(), nullable=True),
        )
    if "repair_issue_code" not in approval_columns:
        op.add_column(
            "approval_request",
            sa.Column("repair_issue_code", sa.String(length=50), nullable=True),
        )
    if "offered_start_at" not in approval_columns:
        op.add_column(
            "approval_request",
            sa.Column("offered_start_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "late_arrival_notice" not in _table_names(bind):
        op.create_table(
            "late_arrival_notice",
            # ``id`` is Integer (not BigInteger) so SQLite treats it as an
            # alias for ROWID and autoincrements on inserts without an
            # explicit id. Past incident 2026-05-19.
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("booking_id", sa.BigInteger(), nullable=False),
            sa.Column("client_id", sa.BigInteger(), nullable=False),
            sa.Column("minutes", sa.Integer(), nullable=False),
            sa.Column("reason_code", sa.String(length=50), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="active",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["booking_id"], ["booking.id"]),
            sa.ForeignKeyConstraint(["client_id"], ["user.id"]),
        )
        op.create_index(
            "ix_late_arrival_notice_booking_id",
            "late_arrival_notice",
            ["booking_id"],
        )
        op.create_index(
            "ix_late_arrival_notice_client_id",
            "late_arrival_notice",
            ["client_id"],
        )
        op.create_index(
            "ix_late_arrival_notice_status",
            "late_arrival_notice",
            ["status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    table_names = _table_names(bind)
    if "late_arrival_notice" in table_names:
        op.drop_index("ix_late_arrival_notice_status", table_name="late_arrival_notice")
        op.drop_index("ix_late_arrival_notice_client_id", table_name="late_arrival_notice")
        op.drop_index("ix_late_arrival_notice_booking_id", table_name="late_arrival_notice")
        op.drop_table("late_arrival_notice")

    approval_columns = _column_names(bind, "approval_request")
    if "offered_start_at" in approval_columns:
        op.drop_column("approval_request", "offered_start_at")
    if "repair_issue_code" in approval_columns:
        op.drop_column("approval_request", "repair_issue_code")
    if "repair_nails_count" in approval_columns:
        op.drop_column("approval_request", "repair_nails_count")
