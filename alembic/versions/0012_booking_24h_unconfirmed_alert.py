"""Add 24h reminder unconfirmed-alert timestamp.

Revision ID: 0012_booking_24h_unconfirmed_alert
Revises: 0011_booking_created_via
Create Date: 2026-05-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012_booking_24h_unconfirmed_alert"
down_revision = "0011_booking_created_via"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    """Return whether one column already exists in the live database."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = inspector.get_columns(table_name)
    return any(column.get("name") == column_name for column in columns)


def upgrade() -> None:
    if not _has_column("booking", "reminder_24h_unconfirmed_alert_sent_at"):
        op.add_column(
            "booking",
            sa.Column(
                "reminder_24h_unconfirmed_alert_sent_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )


def downgrade() -> None:
    if _has_column("booking", "reminder_24h_unconfirmed_alert_sent_at"):
        op.drop_column("booking", "reminder_24h_unconfirmed_alert_sent_at")
