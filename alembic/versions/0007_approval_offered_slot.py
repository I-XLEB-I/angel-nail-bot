"""Add offered_slot_id to approval_request and OFFERED status value."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table_name)}


def _foreign_key_columns(bind, table_name: str) -> set[str]:
    columns: set[str] = set()
    for foreign_key in inspect(bind).get_foreign_keys(table_name):
        columns.update(str(column) for column in foreign_key.get("constrained_columns") or [])
    return columns


def upgrade() -> None:
    bind = op.get_bind()
    approval_columns = _column_names(bind, "approval_request")
    approval_foreign_key_columns = _foreign_key_columns(bind, "approval_request")
    needs_column = "offered_slot_id" not in approval_columns
    needs_foreign_key = "offered_slot_id" not in approval_foreign_key_columns

    # `approval_request.status` uses a string-backed SQLAlchemy enum
    # (`native_enum=False`), so adding `ApprovalRequestStatus.OFFERED`
    # requires no separate schema change on SQLite.
    if not needs_column and not needs_foreign_key:
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("approval_request", recreate="always") as batch_op:
            if needs_column:
                batch_op.add_column(
                    sa.Column(
                        "offered_slot_id",
                        sa.BigInteger(),
                        nullable=True,
                    )
                )
            if needs_foreign_key:
                batch_op.create_foreign_key(
                    "fk_approval_request_offered_slot_id_slot",
                    "slot",
                    ["offered_slot_id"],
                    ["id"],
                )
        return

    if needs_column:
        op.add_column(
            "approval_request",
            sa.Column(
                "offered_slot_id",
                sa.BigInteger(),
                nullable=True,
            ),
        )
    if needs_foreign_key:
        op.create_foreign_key(
            "fk_approval_request_offered_slot_id_slot",
            "approval_request",
            "slot",
            ["offered_slot_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    approval_columns = _column_names(bind, "approval_request")

    if "offered_slot_id" in approval_columns:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("approval_request", recreate="always") as batch_op:
                batch_op.drop_column("offered_slot_id")
            return
        op.drop_column("approval_request", "offered_slot_id")
