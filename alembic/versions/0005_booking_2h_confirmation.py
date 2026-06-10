"""Add 2h reminder confirmation timestamp and unconfirmed-alert flag."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    booking_columns = _column_names(bind, "booking")

    if "reminder_2h_confirmed_at" not in booking_columns:
        op.add_column(
            "booking",
            sa.Column("reminder_2h_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "reminder_2h_unconfirmed_alert_sent_at" not in booking_columns:
        op.add_column(
            "booking",
            sa.Column(
                "reminder_2h_unconfirmed_alert_sent_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    booking_columns = _column_names(bind, "booking")

    if "reminder_2h_unconfirmed_alert_sent_at" in booking_columns:
        op.drop_column("booking", "reminder_2h_unconfirmed_alert_sent_at")
    if "reminder_2h_confirmed_at" in booking_columns:
        op.drop_column("booking", "reminder_2h_confirmed_at")
