from pathlib import Path

import pytest

from src.db.startup import inspect_database_startup


def test_new_database_uses_database_url_path_and_needs_seed(tmp_path: Path) -> None:
    state = inspect_database_startup(
        environ={"DATABASE_URL": "sqlite+aiosqlite:///./railway/data/bot.db"},
        cwd=tmp_path,
    )

    assert state.path == tmp_path / "railway/data/bot.db"
    assert state.needs_seed is True
    assert state.path.parent.is_dir()


def test_existing_database_is_not_seeded_again(tmp_path: Path) -> None:
    database_path = tmp_path / "volume/bot.db"
    database_path.parent.mkdir()
    database_path.write_bytes(b"existing database")

    state = inspect_database_startup(
        environ={"DATABASE_URL": f"sqlite+aiosqlite:///{database_path}"},
        cwd=tmp_path,
    )

    assert state.path == database_path
    assert state.needs_seed is False


def test_railway_database_must_be_inside_attached_volume(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="outside Railway volume"):
        inspect_database_startup(
            environ={
                "DATABASE_URL": "sqlite+aiosqlite:////app/data/bot.db",
                "RAILWAY_ENVIRONMENT": "production",
                "RAILWAY_VOLUME_MOUNT_PATH": "/data",
            },
            cwd=tmp_path,
        )


def test_railway_sqlite_requires_an_attached_volume(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="requires a persistent volume"):
        inspect_database_startup(
            environ={
                "DATABASE_URL": "sqlite+aiosqlite:////app/data/bot.db",
                "RAILWAY_PROJECT_ID": "project-id",
            },
            cwd=tmp_path,
        )


def test_matching_railway_volume_allows_startup(tmp_path: Path) -> None:
    volume_path = tmp_path / "app/data"
    database_path = volume_path / "bot.db"
    state = inspect_database_startup(
        environ={
            "DATABASE_URL": f"sqlite+aiosqlite:///{database_path}",
            "RAILWAY_ENVIRONMENT": "production",
            "RAILWAY_VOLUME_MOUNT_PATH": str(volume_path),
        },
        cwd=tmp_path,
    )

    assert state.path == database_path
    assert state.needs_seed is True


def test_conflicting_db_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="point to different"):
        inspect_database_startup(
            environ={
                "DATABASE_URL": "sqlite+aiosqlite:///./data/bot.db",
                "DB_FILE": "./other/bot.db",
            },
            cwd=tmp_path,
        )


def test_non_sqlite_database_does_not_use_file_bootstrap(tmp_path: Path) -> None:
    state = inspect_database_startup(
        environ={"DATABASE_URL": "postgresql+asyncpg://user:secret@example/db"},
        cwd=tmp_path,
    )

    assert state.path is None
    assert state.needs_seed is False
