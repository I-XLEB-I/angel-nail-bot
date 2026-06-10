"""Track one-shot force-majeure client notifications."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0014_force_majeure_notice_sent_at"
down_revision = "0013_system_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "booking",
        sa.Column(
            "force_majeure_notice_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("booking", "force_majeure_notice_sent_at")
