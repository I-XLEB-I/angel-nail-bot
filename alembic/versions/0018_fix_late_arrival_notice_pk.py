"""fix BIGINT primary key on late_arrival_notice

Same class of bug as migration 0017: ``id`` was declared with
``sa.BigInteger()`` in migration 0008, so on SQLite it becomes
``BIGINT PRIMARY KEY`` — not a ROWID alias, no autoincrement. Inserts
without an explicit id fail.

The previous fix (0017) handled reminder_admin_alert_delivery and
morning_summary_delivery. This one extends the same treatment to
late_arrival_notice, which is created in migration 0008 and would silently
break the first time a client uses the "Опаздываю" flow.

Revision ID: 0018_fix_late_arrival_notice_pk
Revises: 0017_fix_delivery_table_pk
Create Date: 2026-05-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_fix_late_arrival_notice_pk"
down_revision = "0017_fix_delivery_table_pk"
branch_labels = None
depends_on = None


_TABLES = ("late_arrival_notice",)


def _id_needs_rebuild(inspector: sa.engine.reflection.Inspector, table_name: str) -> bool:
    columns = {column["name"]: column for column in inspector.get_columns(table_name)}
    id_column = columns.get("id")
    if id_column is None:
        return False
    column_type = str(id_column["type"]).upper()
    return column_type != "INTEGER"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table_name in _TABLES:
        if table_name not in existing_tables:
            continue
        if not _id_needs_rebuild(inspector, table_name):
            continue
        with op.batch_alter_table(table_name, recreate="always") as batch_op:
            batch_op.alter_column(
                "id",
                existing_type=sa.BigInteger(),
                type_=sa.Integer(),
                existing_nullable=False,
            )


def downgrade() -> None:
    # No-op: switching back to BIGINT would re-break inserts on SQLite.
    pass
