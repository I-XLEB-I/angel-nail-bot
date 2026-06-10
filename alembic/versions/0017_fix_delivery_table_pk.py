"""fix BIGINT PK on reminder_admin_alert_delivery and morning_summary_delivery

On SQLite, only ``INTEGER PRIMARY KEY`` becomes a ROWID alias with autoincrement.
The original migrations 0015/0016 used ``sa.BigInteger()`` for the ``id`` column,
which under SQLite renders as ``BIGINT PRIMARY KEY`` — a regular PK that does
**not** auto-generate values. Inserts without an explicit ``id`` fail with
``NOT NULL constraint failed``.

This migration rebuilds both tables so that ``id`` is ``INTEGER PRIMARY KEY``.
Postgres deployments are unaffected (BIGINT autoincrements via SERIAL there),
but we still run the migration there to keep schemas in sync with the ORM
models (which use ``BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")``).

See also 0018 for the same fix applied to ``late_arrival_notice``.

Revision ID: 0017_fix_delivery_table_pk
Revises: 0016_morning_summary_delivery
Create Date: 2026-05-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_fix_delivery_table_pk"
down_revision = "0016_morning_summary_delivery"
branch_labels = None
depends_on = None


_TABLES = ("reminder_admin_alert_delivery", "morning_summary_delivery")


def _id_needs_rebuild(inspector: sa.engine.reflection.Inspector, table_name: str) -> bool:
    """Return True if the ``id`` column is not INTEGER (i.e. would not autoincrement on SQLite)."""
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
    # No-op: switching back to BIGINT would re-break inserts on SQLite,
    # and there is nothing to "restore" — the new schema is strictly more correct.
    pass
