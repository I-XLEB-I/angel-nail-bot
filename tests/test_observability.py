from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import Settings
from src.db import base as db_base
from src.db.base import Base, get_sqlite_runtime_pragmas
from src.db.repositories.system_alert_events import SystemAlertEventRepository
from src.services import observability


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'obs.db'}",
    )


class FakeBot:
    pass


@pytest.mark.asyncio
async def test_system_alert_deduplicates_and_resolves(monkeypatch, tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sent_texts: list[str] = []

    async def fake_send_text_to_admins(_bot, *, admin_tg_ids, text, reply_markup=None) -> None:
        assert admin_tg_ids == {1}
        assert reply_markup is None
        sent_texts.append(text)

    monkeypatch.setattr(observability, "send_text_to_admins", fake_send_text_to_admins)
    settings = Settings(BOT_TOKEN="test-token", ADMIN_TG_IDS="1", TZ="Europe/Moscow")
    first = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)
    second = first + timedelta(minutes=30)

    async with session_factory() as session:
        sent = await observability.maybe_send_system_alert(
            session,
            bot=FakeBot(),
            settings=settings,
            kind="job_failure",
            signature="gcal_pull",
            text="fail",
            now_utc=first,
        )
        assert sent is True
        sent = await observability.maybe_send_system_alert(
            session,
            bot=FakeBot(),
            settings=settings,
            kind="job_failure",
            signature="gcal_pull",
            text="fail again",
            now_utc=second,
        )
        assert sent is False
        await session.commit()

        alert = await SystemAlertEventRepository(session).get_open_by_kind_signature(
            kind="job_failure",
            signature="gcal_pull",
        )
        assert alert is not None
        assert alert.repeat_count == 2

        resolved = await observability.resolve_system_alert(
            session,
            bot=FakeBot(),
            settings=settings,
            kind="job_failure",
            signature="gcal_pull",
            text="resolved",
            now_utc=second + timedelta(minutes=31),
        )
        assert resolved is True
        await session.commit()

    assert sent_texts == ["fail", "resolved"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_runtime_pragmas_are_enabled(tmp_path: Path) -> None:
    db_base._engine = None
    db_base._session_factory = None
    settings = build_settings(tmp_path)
    pragmas = await get_sqlite_runtime_pragmas(settings)

    assert pragmas is not None
    assert pragmas["journal_mode"].lower() == "wal"
    assert pragmas["busy_timeout"] == "5000"
    assert pragmas["foreign_keys"] == "1"

    await db_base.get_engine(settings).dispose()
    db_base._engine = None
    db_base._session_factory = None
