from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.base import Base
from src.db.models import Slot, SlotStatus
from src.services import admin_schedule as admin_schedule_service


@pytest.mark.asyncio
async def test_delete_schedule_period_removes_only_non_booked_slots() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        now = datetime.now(UTC)
        free_slot = Slot(start_at=now + timedelta(days=1), status=SlotStatus.FREE)
        blocked_slot = Slot(start_at=now + timedelta(days=2), status=SlotStatus.BLOCKED)
        booked_slot = Slot(start_at=now + timedelta(days=3), status=SlotStatus.BOOKED)
        session.add_all([free_slot, blocked_slot, booked_slot])
        await session.commit()

        result = await admin_schedule_service.delete_schedule_period(
            session,
            tz_name="Europe/Moscow",
            period_kind="week",
        )

        assert result.deleted_count == 2
        assert await session.get(Slot, free_slot.id) is None
        assert await session.get(Slot, blocked_slot.id) is None
        booked = await session.get(Slot, booked_slot.id)
        assert booked is not None
        assert booked.status == SlotStatus.BOOKED

    await engine.dispose()


@pytest.mark.asyncio
async def test_move_schedule_slot_detects_collisions() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        moving_slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.FREE,
        )
        existing_slot = Slot(
            start_at=datetime.now(UTC).replace(hour=15, minute=0, second=0, microsecond=0)
            + timedelta(days=7),
            status=SlotStatus.BLOCKED,
        )
        session.add_all([moving_slot, existing_slot])
        await session.commit()

        result = await admin_schedule_service.move_schedule_slot(
            session,
            slot_id=moving_slot.id,
            raw_text=existing_slot.start_at.strftime("%d.%m %H:%M"),
            tz_name="UTC",
        )

        assert result.ok is False
        assert result.reason == "collision"

    await engine.dispose()


@pytest.mark.asyncio
async def test_block_schedule_slot_rejects_booked_slot() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.BOOKED,
        )
        session.add(slot)
        await session.commit()

        result = await admin_schedule_service.block_schedule_slot(session, slot_id=slot.id)

        assert result.ok is False
        assert result.reason == "booked"
        refreshed = await session.get(Slot, slot.id)
        assert refreshed is not None
        assert refreshed.status == SlotStatus.BOOKED

    await engine.dispose()
