from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import Settings
from src.db.base import Base
from src.db.models import Slot, SlotStatus
from src.services import calendar_sync


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        GCAL_ENABLED="true",
        GCAL_CALENDAR_ID="calendar-id",
        GCAL_CREDENTIALS_PATH="./secrets/google_service_account.json",
    )


@asynccontextmanager
async def make_session_scope(session_factory):
    async with session_factory() as session:
        yield session


class FakeBot:
    pass


@pytest.mark.asyncio
async def test_sync_external_calendar_blocks_blocks_matching_free_slots(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    base_start = datetime.now(UTC) + timedelta(days=1)
    async with session_factory() as session:
        session.add_all(
            [
                Slot(start_at=base_start, status=SlotStatus.FREE, blocked_by_gcal=False),
                Slot(
                    start_at=base_start + timedelta(hours=1),
                    status=SlotStatus.FREE,
                    blocked_by_gcal=False,
                ),
            ]
        )
        await session.commit()

    monkeypatch.setattr(
        calendar_sync, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    monkeypatch.setattr(
        calendar_sync,
        "list_calendar_events",
        lambda _settings, *, time_min, time_max: [
            {
                "id": "external-1",
                "status": "confirmed",
                "start": {"dateTime": (base_start - timedelta(minutes=10)).isoformat()},
                "end": {"dateTime": (base_start + timedelta(minutes=30)).isoformat()},
            }
        ],
    )

    await calendar_sync.sync_external_calendar_blocks(FakeBot(), settings)

    async with session_factory() as session:
        first_slot = await session.get(Slot, 1)
        second_slot = await session.get(Slot, 2)
        assert first_slot is not None
        assert second_slot is not None
        assert first_slot.status == SlotStatus.BLOCKED
        assert first_slot.blocked_by_gcal is True
        assert second_slot.status == SlotStatus.FREE
        assert second_slot.blocked_by_gcal is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_sync_external_calendar_blocks_releases_only_gcal_blocks(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    base_start = datetime.now(UTC) + timedelta(days=1)
    async with session_factory() as session:
        session.add_all(
            [
                Slot(start_at=base_start, status=SlotStatus.BLOCKED, blocked_by_gcal=True),
                Slot(
                    start_at=base_start + timedelta(hours=1),
                    status=SlotStatus.BLOCKED,
                    blocked_by_gcal=False,
                ),
            ]
        )
        await session.commit()

    monkeypatch.setattr(
        calendar_sync, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    monkeypatch.setattr(
        calendar_sync, "list_calendar_events", lambda _settings, *, time_min, time_max: []
    )

    await calendar_sync.sync_external_calendar_blocks(FakeBot(), settings)

    async with session_factory() as session:
        gcal_slot = await session.get(Slot, 1)
        manual_slot = await session.get(Slot, 2)
        assert gcal_slot is not None
        assert manual_slot is not None
        assert gcal_slot.status == SlotStatus.FREE
        assert gcal_slot.blocked_by_gcal is False
        assert manual_slot.status == SlotStatus.BLOCKED
        assert manual_slot.blocked_by_gcal is False

    await engine.dispose()


def test_build_external_block_ranges_skips_bot_events() -> None:
    start_at = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    events = [
        {
            "id": "bot-event",
            "status": "confirmed",
            "start": {"dateTime": start_at.isoformat()},
            "end": {"dateTime": (start_at + timedelta(hours=1)).isoformat()},
            "extendedProperties": {"private": {"bot_booking_id": "123"}},
        },
        {
            "id": "external-event",
            "status": "confirmed",
            "start": {"dateTime": start_at.isoformat()},
            "end": {"dateTime": (start_at + timedelta(hours=1)).isoformat()},
        },
    ]

    ranges = calendar_sync.build_external_block_ranges(events, fallback_tz_name="Europe/Moscow")

    assert len(ranges) == 1
    assert ranges[0].event_id == "external-event"


def test_google_request_retries_before_success(monkeypatch) -> None:
    sleep_calls: list[int] = []
    attempts = {"count": 0}

    def fake_sleep(delay: int) -> None:
        sleep_calls.append(delay)

    def flaky_request() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary")
        return "ok"

    monkeypatch.setattr(calendar_sync.time, "sleep", fake_sleep)

    result = calendar_sync._execute_google_request("calendar_test", flaky_request)

    assert result == "ok"
    assert attempts["count"] == 3
    assert sleep_calls == [1, 3]
