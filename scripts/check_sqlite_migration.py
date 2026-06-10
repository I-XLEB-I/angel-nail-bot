"""Smoke-test SQLite migrations on an empty database.

Catches the class of bugs that produced incidents 0011 and 0015/0016:

- ``ALTER TABLE ... ALTER COLUMN ...`` syntax that SQLite cannot parse.
- ``sa.BigInteger() primary_key=True`` columns: under SQLite these become
  ``BIGINT PRIMARY KEY``, which is **not** an alias for ROWID and therefore does
  not autoincrement. Inserts without an explicit id fail with
  ``NOT NULL constraint failed``.

Run as part of CI to prevent these from reaching production.

Usage::

    python scripts/check_sqlite_migration.py [optional/path/to.db]

Exits with non-zero status on any detected issue.
"""

from __future__ import annotations

import os
import subprocess
import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def run_migrations(db_path: Path) -> None:
    """Run ``alembic upgrade head`` against the given SQLite database."""
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
    )


def check_autoincrement_pks(db_path: Path) -> list[str]:
    """Return tables whose integer primary key is not ROWID-aliased on SQLite."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' "
            "AND name NOT LIKE 'alembic%' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        broken: list[str] = []
        for name, sql in cursor.fetchall():
            # Heuristic: if a column called `id` is declared as something other
            # than INTEGER and acts as the PK, autoincrement is broken.
            cols = list(conn.execute(f"PRAGMA table_info({name})"))
            id_col = next((row for row in cols if row[1] == "id"), None)
            if id_col is None:
                continue
            col_type = str(id_col[2]).upper()
            is_pk = bool(id_col[5])
            if not is_pk:
                continue
            if col_type != "INTEGER":
                broken.append(f"{name}: id is {col_type}, expected INTEGER (SQLite alias for ROWID)")
        return broken
    finally:
        conn.close()


def main() -> int:
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_path = Path(tmp.name)

    print(f"Running alembic upgrade head against {db_path}…")
    try:
        run_migrations(db_path)
    except subprocess.CalledProcessError as exc:
        print(f"\nFAIL: alembic upgrade head exited with code {exc.returncode}")
        return 1

    print("Checking that integer primary keys autoincrement on SQLite…")
    broken = check_autoincrement_pks(db_path)
    if broken:
        print("\nFAIL: the following tables would fail INSERT without an explicit id on SQLite:")
        for line in broken:
            print(f"  - {line}")
        print(
            "\nFix: in alembic migrations, declare auto-generated PKs as `sa.Integer()` "
            "(not `sa.BigInteger()`). In SQLAlchemy models you can use "
            "`BIGINT_PK = BigInteger().with_variant(Integer, 'sqlite')` from src/db/base.py."
        )
        return 1

    print(f"\nOK: alembic upgrade head succeeded and all PKs are SQLite-safe ({db_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
