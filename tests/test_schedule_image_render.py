from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.base import Base
from src.db.models import Slot, SlotStatus
from src.services.schedule_image import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    build_schedule_image_bytes,
    build_schedule_image_pages_bytes,
)


@pytest.mark.asyncio
async def test_schedule_image_renders_vertical_png() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add_all(
            [
                Slot(
                    start_at=datetime.now(UTC) + timedelta(days=1, hours=10),
                    status=SlotStatus.FREE,
                ),
                Slot(
                    start_at=datetime.now(UTC) + timedelta(days=1, hours=13),
                    status=SlotStatus.FREE,
                ),
                Slot(
                    start_at=datetime.now(UTC) + timedelta(days=2, hours=16),
                    status=SlotStatus.FREE,
                ),
            ]
        )
        await session.commit()

        image_bytes = await build_schedule_image_bytes(session, tz_name="Europe/Moscow")

        assert image_bytes.startswith(b"\x89PNG")
        with Image.open(io.BytesIO(image_bytes)) as image:
            assert image.size == (IMAGE_WIDTH, IMAGE_HEIGHT)

    await engine.dispose()


@pytest.mark.asyncio
async def test_schedule_image_builds_multiple_pages_when_many_days_are_open() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        base_dt = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        session.add_all(
            [
                Slot(
                    start_at=base_dt + timedelta(days=day_offset + 1, hours=10),
                    status=SlotStatus.FREE,
                )
                for day_offset in range(24)
            ]
        )
        await session.commit()

        pages = await build_schedule_image_pages_bytes(session, tz_name="Europe/Moscow")

        assert len(pages) > 1
        assert all(page.startswith(b"\x89PNG") for page in pages)

    await engine.dispose()
