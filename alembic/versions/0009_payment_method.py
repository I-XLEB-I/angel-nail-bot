"""Add payment method snapshots to bookings and approval requests."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    booking_columns = _column_names(bind, "booking")
    approval_columns = _column_names(bind, "approval_request")

    if "payment_method" not in booking_columns:
        op.add_column(
            "booking",
            sa.Column(
                "payment_method",
                sa.String(length=20),
                nullable=False,
                server_default="transfer",
            ),
        )

    if "payment_method" not in approval_columns:
        op.add_column(
            "approval_request",
            sa.Column("payment_method", sa.String(length=20), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    booking_columns = _column_names(bind, "booking")
    approval_columns = _column_names(bind, "approval_request")

    if "payment_method" in approval_columns:
        op.drop_column("approval_request", "payment_method")
    if "payment_method" in booking_columns:
        op.drop_column("booking", "payment_method")
