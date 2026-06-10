from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import schedule as schedule_handler
from src.bot.keyboards.admin import (
    build_admin_schedule_month_keyboard,
    build_admin_schedule_slot_detail_keyboard,
)
from src.config import Settings
from src.db.base import Base
from src.db.models import Slot, SlotStatus


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = dict(data or {})

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)


class FakeChat:
    id = 500


class FakeMessage:
    def __init__(self) -> None:
        self.chat = FakeChat()
        self.message_id = 40
        self.edits: list[tuple[str, object | None]] = []
        self.answers: list[tuple[str, object | None]] = []

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))

    async def answer(self, text: str, reply_markup=None):
        self.answers.append((text, reply_markup))
        return type("AnsweredMessage", (), {"chat": self.chat, "message_id": 41})()


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


def local_slot(day_offset: int, hour: int, status: SlotStatus = SlotStatus.FREE) -> Slot:
    tz = ZoneInfo("Europe/Moscow")
    local_now = datetime.now(tz)
    local_dt = local_now.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(
        days=day_offset
    )
    return Slot(start_at=local_dt.astimezone(UTC), status=status)


async def setup_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, session_factory


def test_month_renders_days_with_slots_only() -> None:
    tz_name = "Europe/Moscow"
    slots = [
        local_slot(1, 17, SlotStatus.FREE),
        local_slot(1, 19, SlotStatus.BLOCKED),
        local_slot(3, 18, SlotStatus.BOOKED),
    ]
    first_day = slots[0].start_at.astimezone(ZoneInfo(tz_name)).date()
    empty_day = first_day + timedelta(days=1)
    third_day = slots[2].start_at.astimezone(ZoneInfo(tz_name)).date()

    text = schedule_handler.build_schedule_month_text(
        slots,
        tz_name=tz_name,
        offset=0,
        page_size=10,
    )

    assert f"{first_day:%d.%m}" in text
    assert "🟢 17:00" in text
    assert "⚫️ 19:00" in text
    assert f"{empty_day:%d.%m}" not in text
    assert f"{third_day:%d.%m}" in text
    assert "🔴 18:00" in text


def test_month_paginates_correctly() -> None:
    tz_name = "Europe/Moscow"
    slots = [local_slot(day_offset, 17) for day_offset in range(1, 12)]
    first_day = slots[0].start_at.astimezone(ZoneInfo(tz_name)).date()
    eleventh_day = slots[10].start_at.astimezone(ZoneInfo(tz_name)).date()

    text = schedule_handler.build_schedule_month_text(
        slots,
        tz_name=tz_name,
        offset=10,
        page_size=10,
    )
    for index, slot in enumerate(slots, start=1):
        slot.id = index
    markup = build_admin_schedule_month_keyboard(
        offset=10,
        total_days=11,
        page_size=10,
        slots_page=[slots[10]],
        tz_name=tz_name,
    )
    callback_data = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert f"{first_day:%d.%m}" not in text
    assert f"{eleventh_day:%d.%m}" in text
    assert f"admin_schedule:slot:{slots[10].id}:month:10" in callback_data
    assert "admin_schedule:delete_period:month" in callback_data
    assert "admin_schedule:month:page:0" in callback_data
    assert "admin_schedule:month:page:20" not in callback_data


def test_month_slot_detail_keyboard_preserves_month_context() -> None:
    slot = local_slot(2, 18, SlotStatus.FREE)
    slot.id = 42

    markup = build_admin_schedule_slot_detail_keyboard(
        slot,
        origin_view="month",
        origin_value=10,
    )
    callback_data = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert f"admin_schedule:move:{slot.id}:month:10" in callback_data
    assert f"admin_schedule:delete:{slot.id}:month:10" in callback_data
    assert f"admin_schedule:block:{slot.id}:month:10" in callback_data
    assert "admin_schedule:month:page:10" in callback_data


@pytest.mark.asyncio
async def test_month_empty_message_when_no_slots() -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()

    async with session_factory() as session:
        message = FakeMessage()

        await schedule_handler.show_schedule_month_page(
            message,
            db_session=session,
            settings=settings,
            edit=True,
        )

        assert message.edits
        assert "На ближайшие 30 дней окошек пока нет" in message.edits[0][0]

    await engine.dispose()
