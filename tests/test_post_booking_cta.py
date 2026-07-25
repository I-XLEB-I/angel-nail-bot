from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot import texts
from src.bot.handlers.client import booking_flow
from src.config import Settings
from src.db.base import Base
from src.db.models import (
    Booking,
    BookingStatus,
    Service,
    ServiceKind,
    Slot,
    SlotStatus,
    User,
)
from src.db.repositories.bookings import BookingRepository


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[tuple[str, object | None]] = []
        self.edits: list[tuple[str, object | None]] = []
        self.deleted = 0

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))

    async def delete(self) -> None:
        self.deleted += 1


class FakeState:
    def __init__(self) -> None:
        self.cleared = False
        self.data: dict[str, object] = {}

    async def clear(self) -> None:
        self.cleared = True
        self.data.clear()

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def set_state(self, state) -> None:
        self.data["state"] = state


class FakeCallback:
    def __init__(self, data: str | None = None) -> None:
        self.data = data
        self.message = FakeMessage()
        self.answered = False

    async def answer(self) -> None:
        self.answered = True


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_booking_success_message_has_post_booking_cta() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=1001,
            display_name="Дарина",
            phone="+79991234567",
            is_admin=False,
            is_blocked=False,
        )
        session.add(user)
        await session.commit()

        message = FakeMessage()

        await booking_flow.send_booking_success_message(
            message,
            db_session=session,
            user=user,
            settings=build_settings(),
            start_at=datetime.now(UTC),
            base_service_name="Маникюр",
        )

        assert message.answers
        _, markup = message.answers[0]
        callback_data = [button.callback_data for row in markup.inline_keyboard for button in row]
        button_texts = [button.text for row in markup.inline_keyboard for button in row]
        assert "client_menu:my_bookings" in callback_data
        assert "client:to_menu" in callback_data
        assert texts.POST_BOOKING_MY_BOOKINGS_BUTTON_TEXT in button_texts
        assert texts.POST_BOOKING_MENU_BUTTON_TEXT in button_texts

    await engine.dispose()


@pytest.mark.asyncio
async def test_post_reference_entry_rejects_another_clients_booking() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        owner = User(tg_id=1101, display_name="Владелица")
        stranger = User(tg_id=1102, display_name="Другая клиентка")
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.BOOKED,
        )
        booking = Booking(
            client=owner,
            slot=slot,
            base_service=service,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add_all([owner, stranger, service, slot, booking])
        await session.commit()

        callback = FakeCallback(f"client:post_reference:{booking.id}")
        state = FakeState()
        await booking_flow.post_reference_start(
            callback,
            state,
            db_session=session,
            user=stranger,
        )

        assert callback.answered is True
        assert callback.message.edits[-1][0] == texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT
        assert "state" not in state.data

    await engine.dispose()


@pytest.mark.asyncio
async def test_post_reference_repository_rejects_inactive_booking() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(tg_id=1103, display_name="Клиентка")
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        slot = Slot(
            start_at=datetime.now(UTC) - timedelta(days=1),
            status=SlotStatus.BOOKED,
        )
        booking = Booking(
            client=user,
            slot=slot,
            base_service=service,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.COMPLETED,
        )
        session.add_all([user, service, slot, booking])
        await session.commit()

        updated = await BookingRepository(session).attach_design_photos(
            booking.id,
            user.id,
            ["photo-id"],
            "Комментарий",
        )

        assert updated is False
        assert booking.design_photos == []
        assert booking.design_comment is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_post_booking_to_menu_uses_existing_menu(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_show_client_menu(message, *, db_session, user, replace_current=False):
        captured["message"] = message
        captured["db_session"] = db_session
        captured["user"] = user
        captured["replace_current"] = replace_current

    monkeypatch.setattr(booking_flow, "show_client_menu", fake_show_client_menu)
    callback = FakeCallback()
    state = FakeState()
    user = User(tg_id=1001, display_name="Дарина", is_admin=False, is_blocked=False)

    await booking_flow.post_booking_to_menu(
        callback,
        state,
        db_session=object(),
        user=user,
    )

    assert callback.answered is True
    assert captured["user"] is user
    assert captured["replace_current"] is True


@pytest.mark.asyncio
async def test_post_booking_to_my_bookings_uses_existing_entry(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_show_my_bookings_entry(message, state, **kwargs):
        captured["message"] = message
        captured["state"] = state
        captured.update(kwargs)

    monkeypatch.setattr(booking_flow, "show_my_bookings_entry", fake_show_my_bookings_entry)
    callback = FakeCallback()
    state = FakeState()
    user = User(tg_id=1001, display_name="Дарина", is_admin=False, is_blocked=False)
    settings = build_settings()

    await booking_flow.post_booking_to_my_bookings(
        callback,
        state,
        db_session=object(),
        user=user,
        settings=settings,
    )

    assert callback.answered is True
    assert captured["user"] is user
    assert captured["settings"] is settings
    assert captured["replace_current"] is True
