"""Track whether a slot is blocked by Google Calendar sync."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {column["name"] for column in inspect(bind).get_columns("slot")}
    if "blocked_by_gcal" in existing_columns:
        return

    op.add_column(
        "slot",
        sa.Column("blocked_by_gcal", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {column["name"] for column in inspect(bind).get_columns("slot")}
    if "blocked_by_gcal" not in existing_columns:
        return
    op.drop_column("slot", "blocked_by_gcal")
