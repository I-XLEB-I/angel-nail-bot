from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import schedule as schedule_handler
from src.bot.states import AdminSchedule
from src.config import Settings
from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, SlotStatus, User


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = dict(data or {})
        self.state = None
        self.cleared = False

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def set_state(self, state) -> None:
        self.state = state

    async def clear(self) -> None:
        self.data.clear()
        self.state = None
        self.cleared = True

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)


class FakeChat:
    def __init__(self, chat_id: int = 500) -> None:
        self.id = chat_id


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
    ) -> None:
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
        payload = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.sent_messages.append(payload)
        return type(
            "SentMessage",
            (),
            {
                "chat": FakeChat(chat_id),
                "message_id": len(self.sent_messages) + 100,
            },
        )()


class FakeMessage:
    def __init__(
        self,
        text: str | None = None,
        *,
        bot: FakeBot | None = None,
        message_id: int = 40,
    ) -> None:
        self.text = text
        self.bot = bot or FakeBot()
        self.chat = FakeChat()
        self.message_id = message_id
        self.answers: list[tuple[str, object | None]] = []
        self.edits: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None):
        self.answers.append((text, reply_markup))
        return type(
            "AnsweredMessage",
            (),
            {
                "chat": self.chat,
                "message_id": self.message_id + len(self.answers),
            },
        )()

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))


class FakeCallback:
    def __init__(
        self,
        data: str,
        *,
        message: FakeMessage | None = None,
        bot: FakeBot | None = None,
    ) -> None:
        self.data = data
        self.bot = bot or FakeBot()
        self.message = message or FakeMessage(bot=self.bot)
        self.answered = False

    async def answer(self, *args, **kwargs) -> None:
        del args, kwargs
        self.answered = True


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_schedule_add_start_reuses_current_panel() -> None:
    callback = FakeCallback("admin_schedule:add")
    state = FakeState()

    await schedule_handler.schedule_add_start(
        callback,
        state,
        is_admin=True,
    )

    assert callback.answered is True
    assert state.state == AdminSchedule.input_text
    assert callback.message.edits
    text, markup = callback.message.edits[0]
    assert "ДОБАВИТЬ ОКОШКИ" in text
    assert markup is not None
    assert callback.message.answers == []


@pytest.mark.asyncio
async def test_schedule_parse_input_updates_saved_panel() -> None:
    bot = FakeBot()
    message = FakeMessage("07.04 17:00 19:00", bot=bot)
    state = FakeState(
        {
            "admin_panel_chat_id": 500,
            "admin_panel_message_id": 77,
        }
    )

    await schedule_handler.schedule_parse_input(
        message,
        state,
        settings=build_settings(),
    )

    assert state.state == AdminSchedule.preview
    assert bot.edits
    assert "Распознала" in str(bot.edits[0]["text"])
    assert "07.04" in str(bot.edits[0]["text"])
    assert bot.edits[0]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_schedule_week_renders_single_panel_page() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                Slot(start_at=now + timedelta(days=1), status=SlotStatus.FREE),
                Slot(start_at=now + timedelta(days=2), status=SlotStatus.BLOCKED),
                Slot(start_at=now + timedelta(days=3), status=SlotStatus.BOOKED),
            ]
        )
        await session.commit()

        callback = FakeCallback("admin_schedule:week")
        state = FakeState()

        await schedule_handler.schedule_week(
            callback,
            state,
            db_session=session,
            settings=settings,
        )

        assert callback.answered is True
        assert callback.message.edits
        text, markup = callback.message.edits[0]
        assert "Ближайшие 7 дней" in text
        assert "🟢" in text or "⚫️" in text or "🔴" in text
        assert markup is not None
        callback_data = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        assert "admin_schedule:delete_period:week" in callback_data
        assert callback.message.answers == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_schedule_delete_period_confirmed_removes_only_non_booked_slots() -> None:
    settings = build_settings()
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

        callback = FakeCallback("admin_schedule:delete_period_confirm:week")

        await schedule_handler.schedule_delete_period_confirmed(
            callback,
            db_session=session,
            settings=settings,
        )

        assert await session.get(Slot, free_slot.id) is None
        assert await session.get(Slot, blocked_slot.id) is None
        booked = await session.get(Slot, booked_slot.id)
        assert booked is not None
        assert booked.status == SlotStatus.BOOKED
        assert callback.message.edits
        assert "Удалила 2 окошек" in callback.message.edits[0][0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_schedule_block_slot_keeps_booked_slot_unchanged() -> None:
    settings = build_settings()
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

        callback = FakeCallback(f"admin_schedule:block:{slot.id}:page:0")
        state = FakeState()

        await schedule_handler.schedule_block_slot(
            callback,
            state,
            db_session=session,
            settings=settings,
        )

        refreshed = await session.get(Slot, slot.id)
        assert refreshed is not None
        assert refreshed.status == SlotStatus.BOOKED
        assert callback.message.edits
        assert "Нельзя удалить слот с активной записью" in callback.message.edits[0][0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_booked_slot_opens_client_card_with_month_return_context(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=7001,
            display_name="Клиентка",
            is_admin=False,
            is_blocked=False,
        )
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=0,
        )
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.BOOKED,
        )
        session.add_all([user, service, slot])
        await session.flush()
        session.add(
            Booking(
                client_id=user.id,
                slot_id=slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=service.price,
                has_variable_price=False,
                status=BookingStatus.CONFIRMED,
            )
        )
        await session.commit()

        captured: dict[str, object] = {}

        async def fake_show_client_card(
            target,
            *,
            db_session,
            settings,
            client_id,
            back_callback,
            edit=False,
            notice_text=None,
        ) -> None:
            del target, db_session, settings, notice_text
            captured["client_id"] = client_id
            captured["back_callback"] = back_callback
            captured["edit"] = edit

        monkeypatch.setattr(schedule_handler, "show_client_card", fake_show_client_card)

        callback = FakeCallback(f"admin_schedule:open_client:{slot.id}:month:10")
        state = FakeState()

        await schedule_handler.schedule_open_client_card(
            callback,
            state,
            db_session=session,
            settings=settings,
        )

        assert captured["client_id"] == user.id
        assert captured["back_callback"] == "admin_schedule:month:page:10"
        assert captured["edit"] is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_booked_slot_opens_booking_card_with_week_return_context(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=7002,
            display_name="Клиентка 2",
            is_admin=False,
            is_blocked=False,
        )
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=0,
        )
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.BOOKED,
        )
        session.add_all([user, service, slot])
        await session.flush()
        booking = Booking(
            client_id=user.id,
            slot_id=slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=service.price,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.commit()

        captured: dict[str, object] = {}

        async def fake_show_booking_card(
            target,
            *,
            db_session,
            settings,
            booking_id,
            back_callback,
            edit=False,
            notice_text=None,
        ) -> None:
            del target, db_session, settings, notice_text
            captured["booking_id"] = booking_id
            captured["back_callback"] = back_callback
            captured["edit"] = edit

        monkeypatch.setattr(schedule_handler, "show_booking_card", fake_show_booking_card)

        callback = FakeCallback(f"admin_schedule:open_booking:{slot.id}:week:2")
        state = FakeState()

        await schedule_handler.schedule_open_booking_card(
            callback,
            state,
            db_session=session,
            settings=settings,
        )

        assert captured["booking_id"] == booking.id
        assert captured["back_callback"] == "admin_schedule:week:2"
        assert captured["edit"] is True

    await engine.dispose()
