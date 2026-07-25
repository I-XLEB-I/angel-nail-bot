from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/bot.db"


@dataclass(frozen=True, slots=True)
class DatabaseStartupState:
    path: Path | None
    needs_seed: bool


def _absolute_path(path: Path, *, cwd: Path) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (cwd / path).resolve()


def inspect_database_startup(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> DatabaseStartupState:
    """Resolve the runtime SQLite file and guard Railway volume persistence."""
    env = os.environ if environ is None else environ
    working_directory = Path.cwd() if cwd is None else cwd
    database_url = env.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    url = make_url(database_url)

    if url.get_backend_name() != "sqlite":
        return DatabaseStartupState(path=None, needs_seed=False)

    database_name = url.database
    if not database_name or database_name == ":memory:":
        if env.get("RAILWAY_ENVIRONMENT") or env.get("RAILWAY_PROJECT_ID"):
            raise RuntimeError("Railway cannot use an in-memory SQLite database")
        return DatabaseStartupState(path=None, needs_seed=False)

    database_path = _absolute_path(Path(database_name), cwd=working_directory)
    configured_db_file = env.get("DB_FILE", "").strip()
    if configured_db_file:
        db_file_path = _absolute_path(Path(configured_db_file), cwd=working_directory)
        if db_file_path != database_path:
            raise RuntimeError("DB_FILE and DATABASE_URL point to different SQLite database files")

    is_railway = bool(env.get("RAILWAY_ENVIRONMENT") or env.get("RAILWAY_PROJECT_ID"))
    volume_mount = env.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if is_railway:
        if not volume_mount:
            raise RuntimeError(
                "Railway SQLite requires a persistent volume; mount it and point "
                "DATABASE_URL inside that volume"
            )
        volume_path = _absolute_path(Path(volume_mount), cwd=working_directory)
        if not database_path.is_relative_to(volume_path):
            raise RuntimeError(
                f"SQLite database path {database_path} is outside Railway volume {volume_path}"
            )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    needs_seed = not database_path.exists() or database_path.stat().st_size == 0
    return DatabaseStartupState(path=database_path, needs_seed=needs_seed)


def main() -> int:
    state = inspect_database_startup()
    print("1" if state.needs_seed else "0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
