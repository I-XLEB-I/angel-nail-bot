from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot import texts
from src.bot.handlers.admin import manual_booking as manual_booking_handler
from src.config import Settings
from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, SlotStatus, User
from src.services import booking_completion as booking_completion_service


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object | None]] = []

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
        return type("SentMessage", (), {"chat": type("Chat", (), {"id": chat_id})(), "message_id": 90})()


class FakeMessage:
    def __init__(self, *, bot: FakeBot | None = None) -> None:
        self.bot = bot or FakeBot()
        self.chat = type("Chat", (), {"id": 700})()
        self.message_id = 55
        self.edits: list[tuple[str, object | None]] = []
        self.answers: list[tuple[str, object | None]] = []

    async def edit_text(self, text: str, reply_markup=None, parse_mode=None) -> None:
        del parse_mode
        self.edits.append((text, reply_markup))

    async def answer(self, text: str, reply_markup=None, parse_mode=None) -> None:
        del parse_mode
        self.answers.append((text, reply_markup))


class FakeCallback:
    def __init__(self, *, message: FakeMessage | None = None, bot: FakeBot | None = None) -> None:
        self.bot = bot or FakeBot()
        self.message = message or FakeMessage(bot=self.bot)
        self.answered = False

    async def answer(self, *args, **kwargs) -> None:
        del args, kwargs
        self.answered = True


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = dict(data or {})

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def clear(self) -> None:
        self.data.clear()


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="9001",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


def build_base_service() -> Service:
    return Service(
        name="Маникюр",
        price=2400,
        price_variable=False,
        duration_min=120,
        kind=ServiceKind.BASE,
        is_active=True,
        display_order=0,
    )


@pytest.mark.asyncio
async def test_manual_booking_confirm_sends_unified_client_confirmation(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(
        booking_completion_service,
        "create_booking_event",
        lambda *args, **kwargs: None,
    )

    async with session_factory() as session:
        user = User(
            tg_id=6001,
            display_name="Клиентка",
            is_admin=False,
            is_blocked=False,
        )
        service = build_base_service()
        slot = Slot(start_at=datetime.now(UTC) + timedelta(days=1), status=SlotStatus.FREE)
        session.add_all([user, service, slot])
        await session.commit()

        bot = FakeBot()
        callback = FakeCallback(message=FakeMessage(bot=bot), bot=bot)
        state = FakeState(
            {
                "manual_booking_client_id": user.id,
                "manual_booking_service_id": service.id,
                "manual_booking_slot_id": slot.id,
            }
        )

        await manual_booking_handler.manual_booking_confirm(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=build_settings(),
        )

        bookings = list((await session.execute(select(Booking))).scalars())
        assert len(bookings) == 1
        assert bookings[0].status == BookingStatus.CONFIRMED

        refreshed_slot = await session.get(Slot, slot.id)
        assert refreshed_slot is not None
        assert refreshed_slot.status == SlotStatus.BOOKED

        assert callback.message.edits[-1][0] == texts.ADMIN_MANUAL_BOOKING_DONE_TEXT
        assert any(message["chat_id"] == user.tg_id for message in bot.sent_messages)
        client_message = next(message for message in bot.sent_messages if message["chat_id"] == user.tg_id)
        assert client_message["reply_markup"] is not None
        callback_data = [
            button.callback_data
            for row in client_message["reply_markup"].inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        assert "client_menu:my_bookings" in callback_data
        assert "client:to_menu" in callback_data

    await engine.dispose()


@pytest.mark.asyncio
async def test_manual_booking_confirm_skips_client_notification_for_guest(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(
        booking_completion_service,
        "create_booking_event",
        lambda *args, **kwargs: None,
    )

    async with session_factory() as session:
        guest = User(
            tg_id=-6002,
            display_name="Гость",
            is_admin=False,
            is_blocked=False,
        )
        service = build_base_service()
        slot = Slot(start_at=datetime.now(UTC) + timedelta(days=2), status=SlotStatus.FREE)
        session.add_all([guest, service, slot])
        await session.commit()

        bot = FakeBot()
        callback = FakeCallback(message=FakeMessage(bot=bot), bot=bot)
        state = FakeState(
            {
                "manual_booking_client_id": guest.id,
                "manual_booking_service_id": service.id,
                "manual_booking_slot_id": slot.id,
            }
        )

        await manual_booking_handler.manual_booking_confirm(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=build_settings(),
        )

        bookings = list((await session.execute(select(Booking))).scalars())
        assert len(bookings) == 1
        assert bookings[0].status == BookingStatus.CONFIRMED
        assert not any(message["chat_id"] == guest.tg_id for message in bot.sent_messages)
        assert callback.message.edits[-1][0] == texts.ADMIN_MANUAL_BOOKING_DONE_TEXT

    await engine.dispose()
