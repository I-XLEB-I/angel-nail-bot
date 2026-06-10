from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import schedule as schedule_handler
from src.bot.keyboards.admin import build_admin_schedule_slot_detail_keyboard
from src.bot.states import AdminScheduleMove
from src.config import Settings
from src.db.base import Base
from src.db.models import Slot, SlotStatus


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = dict(data or {})
        self.state = None

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def set_state(self, state) -> None:
        self.state = state

    async def clear(self) -> None:
        self.data.clear()
        self.state = None

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)


class FakeChat:
    id = 500


class FakeBot:
    def __init__(self) -> None:
        self.edits: list[dict[str, object | None]] = []
        self.sent_messages: list[dict[str, object | None]] = []

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup=None,
        parse_mode=None,
    ):
        self.edits.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup=None,
        parse_mode=None,
    ):
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )
        return type("SentMessage", (), {"chat": FakeChat(), "message_id": 101})()


class FakeMessage:
    def __init__(self, text: str, *, bot: FakeBot | None = None) -> None:
        self.text = text
        self.bot = bot or FakeBot()
        self.chat = FakeChat()
        self.message_id = 40
        self.answers: list[tuple[str, object | None]] = []

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


def local_to_utc(value: datetime, tz_name: str = "Europe/Moscow") -> datetime:
    return value.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC)


def move_text_for(days_from_now: int, hour: int) -> tuple[str, datetime]:
    tz = ZoneInfo("Europe/Moscow")
    target_local = datetime.now(tz).replace(
        hour=hour,
        minute=0,
        second=0,
        microsecond=0,
    ) + timedelta(days=days_from_now)
    text = f"{target_local:%d.%m.%Y %H:%M}"
    return text, target_local.astimezone(UTC)


async def setup_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, session_factory


@pytest.mark.asyncio
async def test_move_free_slot_to_free_time_succeeds() -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()

    async with session_factory() as session:
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.FREE,
        )
        session.add(slot)
        await session.commit()

        text, expected_utc = move_text_for(days_from_now=5, hour=17)
        bot = FakeBot()
        message = FakeMessage(text, bot=bot)
        state = FakeState(
            {
                "admin_panel_chat_id": 500,
                "admin_panel_message_id": 77,
                "admin_schedule_move_slot_id": slot.id,
                "admin_schedule_move_page": 0,
            }
        )
        await state.set_state(AdminScheduleMove.input_text)

        await schedule_handler.schedule_move_parse_input(
            message,
            state,
            db_session=session,
            settings=settings,
        )

        refreshed = await session.get(Slot, slot.id)
        assert refreshed is not None
        assert refreshed.start_at == expected_utc
        assert refreshed.status == SlotStatus.FREE
        assert "Перенесла" in str(bot.edits[-1]["text"])

    await engine.dispose()


@pytest.mark.asyncio
async def test_move_blocked_slot_to_free_time_succeeds() -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()

    async with session_factory() as session:
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.BLOCKED,
        )
        session.add(slot)
        await session.commit()

        text, expected_utc = move_text_for(days_from_now=6, hour=19)
        bot = FakeBot()
        message = FakeMessage(text, bot=bot)
        state = FakeState(
            {
                "admin_panel_chat_id": 500,
                "admin_panel_message_id": 77,
                "admin_schedule_move_slot_id": slot.id,
                "admin_schedule_move_page": 0,
            }
        )

        await schedule_handler.schedule_move_parse_input(
            message,
            state,
            db_session=session,
            settings=settings,
        )

        refreshed = await session.get(Slot, slot.id)
        assert refreshed is not None
        assert refreshed.start_at == expected_utc
        assert refreshed.status == SlotStatus.BLOCKED

    await engine.dispose()


@pytest.mark.asyncio
async def test_move_rejects_collision_with_existing_slot() -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()

    async with session_factory() as session:
        text, target_utc = move_text_for(days_from_now=7, hour=18)
        moving_slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.FREE,
        )
        existing_slot = Slot(start_at=target_utc, status=SlotStatus.BLOCKED)
        session.add_all([moving_slot, existing_slot])
        await session.commit()
        original_start_at = moving_slot.start_at

        bot = FakeBot()
        message = FakeMessage(text, bot=bot)
        state = FakeState(
            {
                "admin_panel_chat_id": 500,
                "admin_panel_message_id": 77,
                "admin_schedule_move_slot_id": moving_slot.id,
                "admin_schedule_move_page": 0,
            }
        )

        await schedule_handler.schedule_move_parse_input(
            message,
            state,
            db_session=session,
            settings=settings,
        )

        refreshed = await session.get(Slot, moving_slot.id)
        assert refreshed is not None
        assert refreshed.start_at == original_start_at
        assert "Это время уже в расписании" in str(bot.edits[-1]["text"])
        assert state.data["admin_schedule_move_slot_id"] == moving_slot.id

    await engine.dispose()


def test_move_for_booked_slot_is_not_offered() -> None:
    slot = Slot(
        id=10,
        start_at=datetime.now(UTC) + timedelta(days=1),
        status=SlotStatus.BOOKED,
    )

    markup = build_admin_schedule_slot_detail_keyboard(
        slot,
        origin_view="week",
        origin_value=0,
    )
    button_texts = [button.text for row in markup.inline_keyboard for button in row]

    assert "✏️ Перенести" not in button_texts
