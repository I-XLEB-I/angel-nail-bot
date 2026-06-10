from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import all_bookings as all_bookings_handler
from src.bot.handlers.admin import booking_cards as booking_cards_handler
from src.config import Settings
from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, SlotStatus, User


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = dict(data or {})

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def clear(self) -> None:
        self.data.clear()


class FakeChat:
    id = 500


class FakeBot:
    async def delete_message(self, *, chat_id: int, message_id: int) -> None:
        del chat_id, message_id


class FakeMessage:
    def __init__(self) -> None:
        self.chat = FakeChat()
        self.message_id = 40
        self.bot = FakeBot()
        self.answers: list[tuple[str, object | None]] = []
        self.edits: list[tuple[str, object | None]] = []
        self.photos: list[dict[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None):
        self.answers.append((text, reply_markup))
        return type("AnsweredMessage", (), {"chat": self.chat, "message_id": 41})()

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))

    async def answer_photo(self, photo, caption: str | None = None, reply_markup=None) -> None:
        self.photos.append({"photo": photo, "caption": caption, "reply_markup": reply_markup})


class FakeCallback:
    def __init__(self, data: str) -> None:
        self.data = data
        self.message = FakeMessage()
        self.answers: list[dict[str, object | None]] = []

    async def answer(self, text: str | None = None, show_alert: bool | None = None) -> None:
        self.answers.append({"text": text, "show_alert": show_alert})


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


def local_slot(day_offset: int, hour: int = 10) -> Slot:
    tz = ZoneInfo("Europe/Moscow")
    local_now = datetime.now(tz)
    local_dt = local_now.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(
        days=day_offset
    )
    return Slot(start_at=local_dt.astimezone(UTC), status=SlotStatus.BOOKED)


async def setup_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, session_factory


async def seed_bookings(session, *, count: int = 20, cancelled_day: int | None = None):
    user = User(
        tg_id=1001,
        tg_username="anna_k",
        display_name="Анна",
        is_admin=False,
        is_blocked=False,
    )
    service = Service(
        name="Маникюр",
        price=2500,
        price_variable=False,
        duration_min=120,
        kind=ServiceKind.BASE,
        is_active=True,
        display_order=10,
    )
    slots = [local_slot(day) for day in range(count)]
    session.add_all([user, service, *slots])
    await session.flush()
    bookings = []
    for day, slot in enumerate(slots):
        status = BookingStatus.CONFIRMED
        if cancelled_day is not None and day == cancelled_day:
            status = BookingStatus.CANCELLED_BY_CLIENT
        bookings.append(
            Booking(
                client_id=user.id,
                slot_id=slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=2500,
                has_variable_price=False,
                status=status,
            )
        )
    session.add_all(bookings)
    await session.commit()
    return user, service, slots, bookings


@pytest.mark.asyncio
async def test_all_bookings_first_page_shows_14_days() -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        await seed_bookings(session)
        message = FakeMessage()

        await all_bookings_handler.show_all_bookings_page(
            message,
            FakeState(),
            db_session=session,
            settings=build_settings(),
        )

        text = message.answers[0][0]
        assert "стр. 1/2" in text
        assert "Показано: активные" in text
        assert text.count("₽") == 14

    await engine.dispose()


@pytest.mark.asyncio
async def test_all_bookings_pagination_next_prev() -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        await seed_bookings(session)
        callback = FakeCallback("admin_bookings:page:14:0")
        state = FakeState()

        await all_bookings_handler.open_all_bookings_page(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=build_settings(),
        )

        text, markup = callback.message.edits[0]
        callback_data = [button.callback_data for row in markup.inline_keyboard for button in row]
        assert "стр. 2/2" in text
        assert "admin_bookings:page:0:0" in callback_data

    await engine.dispose()


@pytest.mark.asyncio
async def test_all_bookings_hides_cancelled_by_default() -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        await seed_bookings(session, count=3, cancelled_day=1)
        message = FakeMessage()

        await all_bookings_handler.show_all_bookings_page(
            message,
            FakeState(),
            db_session=session,
            settings=build_settings(),
        )

        assert message.answers[0][0].count("₽") == 2
        assert "✖️" not in message.answers[0][0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_all_bookings_shows_cancelled_when_toggled() -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        await seed_bookings(session, count=3, cancelled_day=1)
        callback = FakeCallback("admin_bookings:toggle_cancelled:0")
        state = FakeState({"admin_bookings_show_cancelled": False})

        await all_bookings_handler.toggle_cancelled_bookings(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=build_settings(),
        )

        assert "Показано: активные + отменённые" in callback.message.edits[0][0]
        assert callback.message.edits[0][0].count("₽") == 3
        assert "✖️" in callback.message.edits[0][0]
        assert state.data["admin_bookings_show_cancelled"] is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_all_bookings_empty_period_message() -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        message = FakeMessage()

        await all_bookings_handler.show_all_bookings_page(
            message,
            FakeState(),
            db_session=session,
            settings=build_settings(),
        )

        assert "За этот период записей нет" in message.answers[0][0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_booking_callback_routes_to_booking_card(monkeypatch) -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        user, _, _, bookings = await seed_bookings(session, count=1)
        captured: dict[str, object] = {}

        async def fake_show_booking_card(target, **kwargs):
            del target
            captured.update(kwargs)

        monkeypatch.setattr(all_bookings_handler, "show_booking_card", fake_show_booking_card)
        callback = FakeCallback(f"admin_bookings:open:{bookings[0].id}")
        state = FakeState(
            {
                "admin_bookings_offset_days": 14,
                "admin_bookings_show_cancelled": True,
            }
        )

        await all_bookings_handler.open_booking_client_card(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=build_settings(),
        )

        assert captured["booking_id"] == bookings[0].id
        assert captured["back_callback"] == "admin_bookings:page:14:1"
        assert captured["edit"] is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_new_booking_card_callback_renders_card() -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        user, _, _, bookings = await seed_bookings(session, count=1)
        callback = FakeCallback(f"admin_booking_card:open:{bookings[0].id}:all:0:0")

        await booking_cards_handler.open_booking_card(
            callback,
            db_session=session,
            is_admin=True,
            settings=build_settings(),
        )

        assert callback.answers
        assert callback.message.edits
        text, markup = callback.message.edits[0]
        assert "📅 Запись" in text
        assert user.display_name in text
        callback_data = [button.callback_data for row in markup.inline_keyboard for button in row]
        assert "admin_bookings:page:0:0" in callback_data

    await engine.dispose()


@pytest.mark.asyncio
async def test_load_booking_addons_tolerates_legacy_null_value() -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        _, service, _, bookings = await seed_bookings(session, count=1)
        booking = bookings[0]
        booking.addons = None  # type: ignore[assignment]

        addons = await booking_cards_handler.load_booking_addons(session, booking)

        assert addons == []
        assert service.name == "Маникюр"

    await engine.dispose()


@pytest.mark.asyncio
async def test_all_bookings_keyboard_has_no_image_button() -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        await seed_bookings(session, count=3)
        message = FakeMessage()

        await all_bookings_handler.show_all_bookings_page(
            message,
            FakeState(),
            db_session=session,
            settings=build_settings(),
        )

        _, markup = message.answers[0]
        callback_data = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        assert all(not value.startswith("admin_bookings:image:") for value in callback_data)
        assert "admin_bookings:summary:0:0" in callback_data
        assert "admin_bookings:delete_period:0:0" not in callback_data

    await engine.dispose()


@pytest.mark.asyncio
async def test_all_bookings_summary_screen_opens() -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        await seed_bookings(session, count=3)
        callback = FakeCallback("admin_bookings:summary:0:0")
        state = FakeState()

        await all_bookings_handler.open_all_bookings_summary(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=build_settings(),
        )

        text, markup = callback.message.edits[0]
        callback_data = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        assert "📊 Сводка периода" in text
        assert "Ожидаемая выручка" in text
        assert "admin_bookings:page:0:0" in callback_data

    await engine.dispose()


@pytest.mark.asyncio
async def test_all_bookings_include_pending_requests_in_period() -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        _, _, _, bookings = await seed_bookings(session, count=1)
        bookings[0].status = BookingStatus.PENDING_MASTER
        await session.commit()
        message = FakeMessage()

        await all_bookings_handler.show_all_bookings_page(
            message,
            FakeState(),
            db_session=session,
            settings=build_settings(),
        )

        text = message.answers[0][0]
        assert "⏳" in text
        assert "Показано: активные" in text

    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_period_confirmation_screen_opens() -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        await seed_bookings(session, count=3)
        callback = FakeCallback("admin_bookings:delete_period:0:0")

        await all_bookings_handler.ask_delete_bookings_period(
            callback,
            FakeState(),
            db_session=session,
            is_admin=True,
            settings=build_settings(),
        )

        text, markup = callback.message.edits[0]
        callback_data = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        assert "УДАЛИТЬ ЗАПИСИ ЗА ПЕРИОД" in text
        assert "admin_bookings:delete_period_confirm:0:0" in callback_data

    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_period_removes_bookings_and_frees_slots(monkeypatch) -> None:
    engine, session_factory = await setup_session()
    async with session_factory() as session:
        _, _, slots, bookings = await seed_bookings(session, count=2)
        monkeypatch.setattr(
            all_bookings_handler,
            "delete_booking_event",
            lambda *args, **kwargs: None,
        )
        callback = FakeCallback("admin_bookings:delete_period_confirm:0:0")
        state = FakeState()

        await all_bookings_handler.delete_bookings_period(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=build_settings(),
        )

        remaining = await all_bookings_handler.BookingRepository(session).list_for_range(
            min(slot.start_at for slot in slots),
            max(slot.start_at for slot in slots),
            include_cancelled=True,
        )
        for booking in bookings:
            assert all(item.id != booking.id for item in remaining)

        refreshed_slots = [
            await session.get(Slot, slot.id)
            for slot in slots
        ]
        assert all(slot is not None and slot.status == SlotStatus.FREE for slot in refreshed_slots)
        assert "Удалила 2 записей" in callback.message.edits[0][0]

    await engine.dispose()
