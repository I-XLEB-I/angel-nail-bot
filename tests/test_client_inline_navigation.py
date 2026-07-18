from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import ANY, AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.client import address as address_handler
from src.bot.handlers.client import ask_master as ask_master_handler
from src.bot.handlers.client import booking_flow as booking_flow_handler
from src.bot.handlers.client import my_bookings as my_bookings_handler
from src.bot.handlers.client import portfolio as portfolio_handler
from src.bot.handlers.client import reminders as reminders_handler
from src.bot.handlers.client import services_list as services_handler
from src.bot.states import AskingMaster
from src.bot.states import Booking as BookingStates
from src.config import Settings
from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, SlotStatus, User
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository


class FakeState:
    def __init__(self) -> None:
        self.state = None
        self.cleared = False
        self.data: dict[str, object] = {}

    async def set_state(self, state) -> None:
        self.state = state

    async def clear(self) -> None:
        self.cleared = True

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)


class FakeMessage:
    def __init__(self, *, fail_edit_text: bool = False) -> None:
        self.answers: list[tuple[str, object | None]] = []
        self.edits: list[tuple[str, object | None]] = []
        self.photos: list[dict[str, object | None]] = []
        self.media_edits: list[dict[str, object | None]] = []
        self.deleted = 0
        self.fail_edit_text = fail_edit_text

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))

    async def edit_text(self, text: str, reply_markup=None) -> None:
        if self.fail_edit_text:
            raise RuntimeError("there is no text in the message to edit")
        self.edits.append((text, reply_markup))

    async def answer_photo(self, photo, caption: str | None = None, reply_markup=None) -> None:
        self.photos.append(
            {
                "photo": photo,
                "caption": caption,
                "reply_markup": reply_markup,
            }
        )

    async def edit_media(self, media, reply_markup=None) -> None:
        self.media_edits.append(
            {
                "media": media,
                "caption": getattr(media, "caption", None),
                "reply_markup": reply_markup,
            }
        )

    async def delete(self) -> None:
        self.deleted += 1


class FakeCallback:
    def __init__(self, message: FakeMessage | None = None, data: str | None = None) -> None:
        self.message = message or FakeMessage()
        self.data = data
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
        PORTFOLIO_CHANNEL_URL="https://t.me/example_portfolio",
    )


@pytest.mark.asyncio
async def test_ask_master_entry_replaces_current_message_in_place(monkeypatch) -> None:
    async def fake_clear_state(state) -> None:
        await state.clear()

    monkeypatch.setattr(
        ask_master_handler,
        "clear_state_preserving_admin_mode",
        fake_clear_state,
    )
    monkeypatch.setattr(
        ask_master_handler,
        "load_all_button_configs",
        AsyncMock(return_value={}),
    )

    callback = FakeCallback()
    state = FakeState()

    await ask_master_handler.ask_master_entry(
        callback,
        state,
        db_session=object(),
    )

    assert callback.answered is True
    assert state.cleared is True
    assert state.state == AskingMaster.input_message
    assert (
        callback.message.media_edits[0]["caption"]
        == ask_master_handler.texts.ASK_MASTER_PROMPT_TEXT
    )
    assert callback.message.answers == []
    assert callback.message.deleted == 0


@pytest.mark.asyncio
async def test_show_address_replaces_current_message_in_place() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await TemplateRepository(session).upsert(
            key="navigation_public",
            content="📍 Тестовый адрес",
        )
        await SettingRepository(session).upsert(
            key="studio_address_copy_text",
            value="Тестовая улица, 10",
        )
        await session.commit()

        callback = FakeCallback()

        await address_handler.show_address(
            callback,
            db_session=session,
        )

        assert callback.answered is True
        assert callback.message.media_edits
        assert "Тестовый адрес" in str(callback.message.media_edits[0]["caption"])
        markup = callback.message.media_edits[0]["reply_markup"]
        assert markup is not None
        first_button = markup.inline_keyboard[0][0]
        assert first_button.text == "🗺 Открыть в Яндекс Картах"
        assert first_button.url == address_handler.ADDRESS_MAP_URL
        copy_button = markup.inline_keyboard[1][0]
        assert copy_button.text == "📋 Скопировать адрес"
        assert copy_button.copy_text is not None
        assert copy_button.copy_text.text == "Тестовая улица, 10"
        assert callback.message.answers == []
        assert callback.message.deleted == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_address_screen_normalizes_previous_studio_building() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await TemplateRepository(session).upsert(
            key="navigation_public",
            content="📍 АДРЕС\n\nОчаковское шоссе, 5к3, подъезд 2",
        )
        await SettingRepository(session).upsert(
            key="studio_address_copy_text",
            value="Очаковское шоссе, 5к3, подъезд 2",
        )
        await session.commit()

        callback = FakeCallback()
        await address_handler.show_address(callback, db_session=session)

        caption = str(callback.message.media_edits[0]["caption"])
        assert "Очаковское шоссе, 5к4" in caption
        assert "5к3" not in caption
        copy_button = callback.message.media_edits[0]["reply_markup"].inline_keyboard[1][0]
        assert copy_button.copy_text.text == "Очаковское шоссе, 5к4, подъезд 2"

    await engine.dispose()


@pytest.mark.asyncio
async def test_show_portfolio_replaces_current_message_in_place() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await TemplateRepository(session).upsert(
            key="about_master",
            content="Ангела делает аккуратный маникюр",
        )
        await TemplateRepository(session).upsert(
            key="portfolio_intro",
            content="Портфолио здесь",
        )
        await SettingRepository(session).upsert(
            key="portfolio_channel_url",
            value="https://t.me/angels_test",
        )
        await session.commit()

        callback = FakeCallback()

        await portfolio_handler.show_portfolio(
            callback,
            db_session=session,
            settings=settings,
        )

        assert callback.answered is True
        assert callback.message.edits
        assert callback.message.edits[0][0] == (
            "Ангела делает аккуратный маникюр\n\nПортфолио здесь"
        )
        assert callback.message.edits[0][1] is not None
        assert callback.message.media_edits == []
        assert callback.message.answers == []
        assert callback.message.deleted == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_show_services_edits_current_message_with_price_template() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(
            Service(
                name="Маникюр",
                price=2400,
                price_variable=False,
                duration_min=120,
                kind=ServiceKind.BASE,
                is_active=True,
                display_order=10,
            )
        )
        await TemplateRepository(session).upsert(
            key="price",
            content="Прайс из шаблона",
        )
        await session.commit()

        callback = FakeCallback()

        await services_handler.show_services(
            callback,
            db_session=session,
        )

        assert callback.answered is True
        if callback.message.media_edits:
            assert "Прайс из шаблона" in (callback.message.media_edits[0]["caption"] or "")
            assert callback.message.edits == []
        else:
            assert callback.message.edits
            assert "Прайс из шаблона" in callback.message.edits[0][0]
            assert callback.message.photos == []
        assert callback.message.deleted == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_show_services_routes_through_template_message(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(
            Service(
                name="Маникюр",
                price=2400,
                price_variable=False,
                duration_min=120,
                kind=ServiceKind.BASE,
                is_active=True,
                display_order=10,
            )
        )
        await TemplateRepository(session).upsert(
            key="price",
            content="Шаблонный прайс",
        )
        await session.commit()

        calls: list[dict[str, object]] = []

        async def fake_send_template_message(
            message,
            *,
            template_key,
            caption,
            reply_markup=None,
            replace_current=False,
        ) -> None:
            del message
            calls.append(
                {
                    "template_key": template_key,
                    "caption": caption,
                    "reply_markup": reply_markup,
                    "replace_current": replace_current,
                }
            )

        monkeypatch.setattr(
            services_handler,
            "send_template_message",
            fake_send_template_message,
        )

        callback = FakeCallback()

        await services_handler.show_services(
            callback,
            db_session=session,
        )

        assert len(calls) == 1
        assert calls[0]["template_key"] == "price"
        assert calls[0]["caption"] == "Шаблонный прайс"
        assert calls[0]["reply_markup"] is not None
        assert calls[0]["replace_current"] is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_show_payment_step_routes_through_brand_message(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await TemplateRepository(session).upsert(
            key="price",
            content="Шаблонный прайс",
        )
        await session.commit()

        calls: list[dict[str, object]] = []

        async def fake_send_brand_message(
            message,
            *,
            caption,
            reply_markup=None,
            replace_current=False,
        ) -> None:
            del message
            calls.append(
                {
                    "caption": caption,
                    "reply_markup": reply_markup,
                    "replace_current": replace_current,
                }
            )

        monkeypatch.setattr(
            booking_flow_handler,
            "send_brand_message",
            fake_send_brand_message,
        )

        state = FakeState()
        await booking_flow_handler.show_payment_step(
            FakeMessage(),
            db_session=session,
            state=state,
            replace=True,
        )

        assert state.state == BookingStates.choose_payment
        assert len(calls) == 1
        assert calls[0]["caption"] == booking_flow_handler.texts.BOOKING_CHOOSE_PAYMENT_TEXT
        assert calls[0]["reply_markup"] is not None
        assert calls[0]["replace_current"] is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_vacation_screen_uses_configured_template_media(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await SettingRepository(session).upsert(key="vacation_mode", value="1")
        await TemplateRepository(session).upsert(
            key="vacation_notice",
            content="Ангела сейчас в отпуске, скоро вернусь 🌸",
        )
        await session.commit()
        calls: list[dict[str, object]] = []

        async def fake_send_template_message(message, **kwargs) -> None:
            del message
            calls.append(kwargs)

        monkeypatch.setattr(
            booking_flow_handler,
            "send_template_message",
            fake_send_template_message,
        )

        await booking_flow_handler.show_day_step(
            FakeMessage(),
            db_session=session,
            state=FakeState(),
            settings=settings,
            replace=True,
        )

        assert calls[0]["template_key"] == "vacation_notice"
        assert calls[0]["caption"] == "Ангела сейчас в отпуске, скоро вернусь 🌸"
        assert calls[0]["replace_current"] is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_repeat_prompt_later_edits_current_message() -> None:
    callback = FakeCallback(data="repeat_prompt:later")

    await reminders_handler.repeat_prompt_later(callback)

    assert callback.answered is True
    assert callback.message.edits == [(reminders_handler.texts.REPEAT_PROMPT_LATER_TEXT, None)]
    assert callback.message.answers == []


@pytest.mark.asyncio
async def test_show_my_bookings_from_photo_message_falls_back_to_new_text_message() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=1001,
            display_name="Матвей",
            is_admin=False,
            is_blocked=False,
        )
        session.add(user)
        await session.commit()

        message = FakeMessage(fail_edit_text=True)
        state = FakeState()

        await my_bookings_handler.show_my_bookings_entry(
            message,
            state,
            db_session=session,
            user=user,
            settings=settings,
            replace_current=True,
        )

        assert state.cleared is True
        assert message.edits == []
        assert message.deleted == 1
        assert message.media_edits == []
        assert message.answers == [(my_bookings_handler.texts.NO_BOOKINGS_YET_TEXT, ANY)]

    await engine.dispose()


@pytest.mark.asyncio
async def test_show_my_bookings_overview_uses_summary_text_and_history_button() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=1002,
            display_name="Мария",
            phone="+79991234567",
            is_admin=False,
            is_blocked=False,
        )
        service = Service(
            name="Маникюр + покрытие гель",
            price=2400,
            price_variable=False,
            duration_min=90,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        upcoming = Slot(start_at=datetime.now(UTC) + timedelta(days=3), status=SlotStatus.BOOKED)
        completed = Slot(start_at=datetime.now(UTC) - timedelta(days=10), status=SlotStatus.BOOKED)
        session.add_all([user, service, upcoming, completed])
        await session.flush()
        session.add_all(
            [
                Booking(
                    client_id=user.id,
                    slot_id=upcoming.id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.CONFIRMED,
                ),
                Booking(
                    client_id=user.id,
                    slot_id=completed.id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
            ]
        )
        await session.commit()

        message = FakeMessage()
        state = FakeState()

        await my_bookings_handler.show_my_bookings_entry(
            message,
            state,
            db_session=session,
            user=user,
            settings=settings,
            replace_current=False,
        )

        assert len(message.answers) == 1
        text = message.answers[0][0]
        assert "Привет, Мария" in text
        assert "Ближайшая встреча" in text
        assert "С нами уже 1 раз" in text
        reply_markup = message.answers[0][1]
        callback_data = [
            button.callback_data
            for row in reply_markup.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        assert "my_bookings:history" in callback_data

    await engine.dispose()


@pytest.mark.asyncio
async def test_request_reschedule_other_day_edits_current_message(monkeypatch) -> None:
    callback = FakeCallback(data="my_bookings:reschedule_other_day:42")
    state = FakeState()
    monkeypatch.setattr(
        my_bookings_handler,
        "load_runtime_button_configs",
        AsyncMock(return_value={}),
    )

    await my_bookings_handler.request_reschedule_other_day(
        callback,
        state,
        db_session=object(),
    )

    assert callback.answered is True
    assert state.data["custom_request_kind"] == "reschedule"
    assert state.data["related_booking_id"] == 42
    assert callback.message.edits == [
        (my_bookings_handler.texts.BOOKING_CUSTOM_TIME_RESCHEDULE_PROMPT_TEXT, ANY)
    ]
    assert callback.message.answers == []


@pytest.mark.asyncio
async def test_request_reschedule_other_time_edits_current_message(monkeypatch) -> None:
    callback = FakeCallback(data="my_bookings:reschedule_other_time:42:2026-04-24")
    state = FakeState()
    monkeypatch.setattr(
        my_bookings_handler,
        "load_runtime_button_configs",
        AsyncMock(return_value={}),
    )

    await my_bookings_handler.request_reschedule_other_time(
        callback,
        state,
        db_session=object(),
    )

    assert callback.answered is True
    assert state.data["custom_request_kind"] == "reschedule"
    assert state.data["custom_request_preferred_day"] == "2026-04-24"
    assert state.data["related_booking_id"] == 42
    assert callback.message.edits == [
        (my_bookings_handler.texts.BOOKING_CUSTOM_TIME_RESCHEDULE_PROMPT_TEXT, ANY)
    ]
    assert callback.message.answers == []


@pytest.mark.asyncio
async def test_request_other_day_uses_contextual_back_callback(monkeypatch) -> None:
    callback = FakeCallback(data="booking:other_day")
    state = FakeState()
    monkeypatch.setattr(
        booking_flow_handler,
        "load_runtime_button_configs",
        AsyncMock(return_value={}),
    )

    await booking_flow_handler.request_other_day(
        callback,
        state,
        db_session=object(),
    )

    assert callback.answered is True
    assert state.data["custom_request_kind"] == "new_booking"
    assert state.data["custom_request_back_target"] == "day"
    assert callback.message.edits == [
        (booking_flow_handler.texts.BOOKING_CUSTOM_TIME_NEW_BOOKING_PROMPT_TEXT, ANY)
    ]
    _, markup = callback.message.edits[-1]
    assert markup.inline_keyboard[0][0].callback_data == "booking:custom_time_back"


@pytest.mark.asyncio
async def test_request_other_time_uses_contextual_back_callback(monkeypatch) -> None:
    callback = FakeCallback(data="booking:other_time")
    state = FakeState()
    state.data["selected_day"] = "2026-04-24"
    monkeypatch.setattr(
        booking_flow_handler,
        "load_runtime_button_configs",
        AsyncMock(return_value={}),
    )

    await booking_flow_handler.request_other_time(
        callback,
        state,
        db_session=object(),
    )

    assert callback.answered is True
    assert state.data["custom_request_kind"] == "new_booking"
    assert state.data["custom_request_preferred_day"] == "2026-04-24"
    assert state.data["custom_request_back_target"] == "time"
    assert callback.message.edits == [
        (booking_flow_handler.texts.BOOKING_CUSTOM_TIME_NEW_BOOKING_PROMPT_TEXT, ANY)
    ]
    _, markup = callback.message.edits[-1]
    assert markup.inline_keyboard[0][0].callback_data == "booking:custom_time_back"


@pytest.mark.asyncio
async def test_custom_time_back_returns_to_day_picker(monkeypatch) -> None:
    callback = FakeCallback(data="booking:custom_time_back")
    state = FakeState()
    state.data["custom_request_back_target"] = "day"
    captured: dict[str, object] = {}

    async def fake_show_day_step(message, **kwargs) -> None:
        captured["message"] = message
        captured.update(kwargs)

    monkeypatch.setattr(booking_flow_handler, "show_day_step", fake_show_day_step)

    await booking_flow_handler.custom_time_back(
        callback,
        state,
        db_session=object(),
        settings=build_settings(),
    )

    assert callback.answered is True
    assert captured["message"] is callback.message
    assert captured["replace"] is True


@pytest.mark.asyncio
async def test_custom_time_back_returns_to_time_picker(monkeypatch) -> None:
    callback = FakeCallback(data="booking:custom_time_back")
    state = FakeState()
    state.data["custom_request_back_target"] = "time"
    state.data["selected_day"] = "2026-04-24"
    captured: dict[str, object] = {}

    async def fake_show_time_step(message, **kwargs) -> None:
        captured["message"] = message
        captured.update(kwargs)

    monkeypatch.setattr(booking_flow_handler, "show_time_step", fake_show_time_step)

    await booking_flow_handler.custom_time_back(
        callback,
        state,
        db_session=object(),
        settings=build_settings(),
    )

    assert callback.answered is True
    assert captured["message"] is callback.message
    assert captured["replace"] is True
    assert str(captured["local_day"]) == "2026-04-24"


@pytest.mark.asyncio
async def test_show_reschedule_days_message_uses_schedule_photo_with_page_navigation() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=4001,
            display_name="Мария",
            phone="+79990000001",
            is_admin=False,
            is_blocked=False,
        )
        service = Service(
            name="Маникюр + покрытие гель",
            price=2400,
            price_variable=False,
            duration_min=90,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        booked_slot = Slot(start_at=datetime.now(UTC) + timedelta(days=3), status=SlotStatus.BOOKED)
        free_slots = [
            Slot(
                start_at=datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
                + timedelta(days=day_offset + 1, hours=10),
                status=SlotStatus.FREE,
            )
            for day_offset in range(24)
        ]
        session.add_all([user, service, booked_slot, *free_slots])
        await session.flush()
        booking = Booking(
            client_id=user.id,
            slot_id=booked_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.commit()

        class BotStub:
            async def send_chat_action(self, *, chat_id: int, action: str) -> None:
                del chat_id, action

        class ChatStub:
            id = 101

        message = FakeMessage()
        message.bot = BotStub()
        message.chat = ChatStub()
        state = FakeState()

        await my_bookings_handler.show_reschedule_days_message(
            message,
            booking_id=booking.id,
            db_session=session,
            user=user,
            settings=settings,
            state=state,
        )

        assert state.data["reschedule_schedule_page"] == 0
        assert len(message.media_edits) == 1
        markup = message.media_edits[0]["reply_markup"]
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        assert f"my_bookings:reschedule_page:{booking.id}:1" in callbacks
        day_callbacks = [
            value
            for value in callbacks
            if value and value.startswith(f"my_bookings:reschedule_day:{booking.id}:")
        ]
        assert 0 < len(day_callbacks) < 24

    await engine.dispose()


@pytest.mark.asyncio
async def test_reschedule_schedule_page_handler_keeps_photo_navigation() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=4002,
            display_name="Мария",
            phone="+79990000002",
            is_admin=False,
            is_blocked=False,
        )
        service = Service(
            name="Маникюр + покрытие гель",
            price=2400,
            price_variable=False,
            duration_min=90,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        booked_slot = Slot(start_at=datetime.now(UTC) + timedelta(days=3), status=SlotStatus.BOOKED)
        free_slots = [
            Slot(
                start_at=datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
                + timedelta(days=day_offset + 1, hours=10),
                status=SlotStatus.FREE,
            )
            for day_offset in range(24)
        ]
        session.add_all([user, service, booked_slot, *free_slots])
        await session.flush()
        booking = Booking(
            client_id=user.id,
            slot_id=booked_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.commit()

        class BotStub:
            async def send_chat_action(self, *, chat_id: int, action: str) -> None:
                del chat_id, action

        class ChatStub:
            id = 102

        message = FakeMessage()
        message.bot = BotStub()
        message.chat = ChatStub()
        callback = FakeCallback(
            message=message,
            data=f"my_bookings:reschedule_page:{booking.id}:1",
        )
        state = FakeState()

        await my_bookings_handler.change_reschedule_schedule_page(
            callback,
            state,
            db_session=session,
            user=user,
            settings=settings,
        )

        assert callback.answered is True
        assert state.data["reschedule_schedule_page"] == 1
        assert len(message.media_edits) == 1
        markup = message.media_edits[0]["reply_markup"]
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        assert "my_bookings:reschedule_noop" in callbacks
        assert f"my_bookings:reschedule_page:{booking.id}:0" in callbacks

    await engine.dispose()


@pytest.mark.asyncio
async def test_show_day_step_uses_single_schedule_photo_with_page_navigation() -> None:
    settings = build_settings()
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

        class BotStub:
            async def send_chat_action(self, *, chat_id: int, action: str) -> None:
                del chat_id, action

        class ChatStub:
            id = 101

        message = FakeMessage()
        message.bot = BotStub()
        message.chat = ChatStub()
        state = FakeState()

        await booking_flow_handler.show_day_step(
            message,
            db_session=session,
            state=state,
            settings=settings,
        )

        assert state.state == BookingStates.choose_day
        assert len(message.photos) == 1
        markup = message.photos[0]["reply_markup"]
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        assert "booking:schedule_page:1" in callbacks
        day_callbacks = [value for value in callbacks if value and value.startswith("booking:day:")]
        assert 0 < len(day_callbacks) < 24

    await engine.dispose()
