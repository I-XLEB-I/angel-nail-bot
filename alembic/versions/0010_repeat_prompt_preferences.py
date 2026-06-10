"""repeat prompt snooze and client preferences

Revision ID: 0010_repeat_prompt_preferences
Revises: 0009
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_repeat_prompt_preferences"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("repeat_prompt_snoozed_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("user", sa.Column("preferred_days_note", sa.Text(), nullable=True))
    op.add_column("user", sa.Column("preferred_time_note", sa.Text(), nullable=True))
    op.add_column("user", sa.Column("preferred_length_note", sa.Text(), nullable=True))
    op.add_column("user", sa.Column("preferred_shape_note", sa.Text(), nullable=True))
    op.add_column("user", sa.Column("preferred_design_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "preferred_design_note")
    op.drop_column("user", "preferred_shape_note")
    op.drop_column("user", "preferred_length_note")
    op.drop_column("user", "preferred_time_note")
    op.drop_column("user", "preferred_days_note")
    op.drop_column("user", "repeat_prompt_snoozed_until")
