"""Add winback_sent_at column to user table."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    user_columns = _column_names(bind, "user")

    if "winback_sent_at" not in user_columns:
        op.add_column(
            "user",
            sa.Column("winback_sent_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    user_columns = _column_names(bind, "user")

    if "winback_sent_at" in user_columns:
        op.drop_column("user", "winback_sent_at")
