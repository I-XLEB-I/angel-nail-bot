from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.base import Base
from src.db.models import Slot, SlotStatus
from src.db.repositories.slots import PUBLIC_BOOKING_HORIZON_DAYS, SlotRepository


@pytest.mark.asyncio
async def test_list_free_future_can_limit_public_horizon() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now_utc = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all(
            [
                Slot(
                    start_at=now_utc + timedelta(days=2),
                    status=SlotStatus.FREE,
                ),
                Slot(
                    start_at=now_utc + timedelta(days=PUBLIC_BOOKING_HORIZON_DAYS + 40),
                    status=SlotStatus.FREE,
                ),
            ]
        )
        await session.commit()

        slots = await SlotRepository(session).list_free_future(
            now_utc=now_utc,
            horizon_days=PUBLIC_BOOKING_HORIZON_DAYS,
        )

        assert len(slots) == 1
        assert slots[0].start_at.date() == (now_utc + timedelta(days=2)).date()

    await engine.dispose()
