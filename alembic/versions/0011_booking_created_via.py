"""booking created_via source marker

Revision ID: 0011_booking_created_via
Revises: 0010_repeat_prompt_preferences
Create Date: 2026-05-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_booking_created_via"
down_revision = "0010_repeat_prompt_preferences"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    """Return whether one column already exists in the live database."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = inspector.get_columns(table_name)
    return any(column.get("name") == column_name for column in columns)


def upgrade() -> None:
    if not _has_column("booking", "created_via"):
        op.add_column(
            "booking",
            sa.Column(
                "created_via",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'unknown'"),
            ),
        )
    op.execute("UPDATE booking SET created_via = 'unknown' WHERE created_via IS NULL")


def downgrade() -> None:
    if _has_column("booking", "created_via"):
        op.drop_column("booking", "created_via")
