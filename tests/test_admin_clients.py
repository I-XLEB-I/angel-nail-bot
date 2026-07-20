from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import clients as clients_handler
from src.config import Settings
from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, User


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.state = None
        self.cleared = False

    async def set_state(self, state) -> None:
        self.state = state

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def clear(self) -> None:
        self.cleared = True
        self.data.clear()
        self.state = None


class FakeChat:
    def __init__(self, chat_id: int = 500) -> None:
        self.id = chat_id


class FakeBot:
    def __init__(self) -> None:
        self.edits: list[dict[str, object | None]] = []
        self.sent_messages: list[dict[str, object | None]] = []
        self.copied_messages: list[dict[str, int]] = []

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

    async def copy_message(self, *, chat_id: int, from_chat_id: int, message_id: int) -> None:
        self.copied_messages.append(
            {
                "chat_id": chat_id,
                "from_chat_id": from_chat_id,
                "message_id": message_id,
            }
        )


class FakeMessage:
    def __init__(
        self,
        text: str | None = None,
        *,
        bot: FakeBot | None = None,
        message_id: int = 42,
    ) -> None:
        self.text = text
        self.bot = bot or FakeBot()
        self.chat = FakeChat()
        self.message_id = message_id
        self.answers: list[tuple[str, object | None]] = []
        self.edits: list[tuple[str, object | None]] = []
        self.deleted = False

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))

    async def delete(self) -> None:
        self.deleted = True


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage | None = None) -> None:
        self.data = data
        self.message = message or FakeMessage()
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
async def test_open_clients_section_shows_home_screen() -> None:
    message = FakeMessage()
    state = FakeState()

    await clients_handler.open_clients_section(
        message,
        state,
        is_admin=True,
    )

    assert state.cleared is True
    assert message.answers
    assert message.answers[0][0] == clients_handler.texts.ADMIN_CLIENTS_HOME_TEXT
    assert message.answers[0][1] is not None


@pytest.mark.asyncio
async def test_open_clients_list_page_renders_first_page() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add_all(
            [
                User(
                    tg_id=1000 + index,
                    display_name=f"Клиентка {index:02d}",
                    is_admin=False,
                    is_blocked=False,
                )
                for index in range(10)
            ]
        )
        await session.commit()

        callback = FakeCallback("admin_clients:list:0")
        state = FakeState()

        await clients_handler.open_clients_list_page(
            callback,
            state,
            db_session=session,
            is_admin=True,
        )

        assert callback.answered is True
        assert state.cleared is True
        assert callback.message.edits
        text, markup = callback.message.edits[0]
        assert "Страница: 1 из 2" in text
        assert "Всего клиенток: 10" in text
        assert markup is not None
        assert markup.inline_keyboard[-2][0].callback_data == "admin_clients:home"
        assert markup.inline_keyboard[-1][0].callback_data == "admin_menu:home"

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_client_card_from_list_keeps_back_context() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=2001,
            tg_username="nails_maria",
            display_name="Мария",
            phone="+79990000000",
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
            display_order=10,
        )
        now = datetime.now(UTC)
        next_slot = Slot(start_at=now + timedelta(days=1), status="booked")
        past_slot = Slot(start_at=now - timedelta(days=7), status="booked")
        session.add_all([user, service, next_slot, past_slot])
        await session.flush()
        session.add_all(
            [
                Booking(
                    client_id=user.id,
                    slot_id=next_slot.id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.CONFIRMED,
                ),
                Booking(
                    client_id=user.id,
                    slot_id=past_slot.id,
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

        callback = FakeCallback(f"admin_clients:open:{user.id}:list:1")

        await clients_handler.open_client_card(
            callback,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        assert callback.answered is True
        assert callback.message.edits
        text, markup = callback.message.edits[0]
        assert "👤 Мария" in text
        assert "📅 Ближайшая запись" in text
        assert "ℹ️ Инфо" not in text
        assert markup is not None
        assert markup.inline_keyboard[-2][0].callback_data == "admin_clients:list:1"
        assert markup.inline_keyboard[-1][0].callback_data == "admin_menu:home"

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_card_for_admin_in_client_mode() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=3001,
            tg_username="angel_admin",
            display_name="Ангела",
            phone="+79991112233",
            is_admin=True,
            is_blocked=False,
        )
        service = Service(
            name="Покрытие гель-лак",
            price=2600,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        now = datetime.now(UTC)
        next_slot = Slot(start_at=now + timedelta(days=2), status="booked")
        session.add_all([user, service, next_slot])
        await session.flush()
        session.add(
            Booking(
                client_id=user.id,
                slot_id=next_slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=2600,
                has_variable_price=False,
                status=BookingStatus.CONFIRMED,
            )
        )
        await session.commit()

        callback = FakeCallback(f"admin_clients:open:{user.id}")

        await clients_handler.open_client_card(
            callback,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        assert callback.answered is True
        assert callback.message.edits
        text, markup = callback.message.edits[0]
        assert "👤 Ангела" in text
        assert "👑 Админ в режиме клиента" in text
        assert "Не нашла эту клиентку." not in text
        assert markup is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_client_card_from_approval_keeps_back_context() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=3011,
            tg_username="approval_client",
            display_name="Клиентка",
            phone="+79991110000",
            is_admin=False,
            is_blocked=False,
        )
        session.add(user)
        await session.commit()

        callback = FakeCallback(f"admin_clients:open:{user.id}:approval:77")

        await clients_handler.open_client_card(
            callback,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        assert callback.answered is True
        assert callback.message.edits
        _, markup = callback.message.edits[0]
        assert markup is not None
        assert markup.inline_keyboard[-2][0].callback_data == "admin_approvals:open:77"
        assert markup.inline_keyboard[-1][0].callback_data == "admin_menu:home"

    await engine.dispose()


@pytest.mark.asyncio
async def test_prompt_client_note_edits_current_message() -> None:
    callback = FakeCallback("admin_clients:note:5:home")
    state = FakeState()

    await clients_handler.prompt_client_note(
        callback,
        state,
        is_admin=True,
    )

    assert callback.answered is True
    assert state.state is not None
    assert callback.message.edits
    assert callback.message.answers == []


@pytest.mark.asyncio
async def test_save_client_note_updates_existing_panel(monkeypatch) -> None:
    updated_panels: list[str] = []

    async def fake_build_client_card_panel(
        *,
        db_session,
        settings,
        client_id,
        back_callback,
        view="main",
        notice_text=None,
    ):
        del db_session, settings, client_id, back_callback, view
        updated_panels.append(str(notice_text))
        return ("card-body", object())

    async def fake_upsert_inline_panel(
        bot,
        *,
        chat_id,
        message_id,
        text,
        reply_markup=None,
        parse_mode=None,
    ):
        del bot, chat_id, message_id, reply_markup, parse_mode
        updated_panels.append(text)
        return type("PanelRef", (), {"chat": FakeChat(500), "message_id": 77})()

    monkeypatch.setattr(clients_handler, "build_client_card_panel", fake_build_client_card_panel)
    monkeypatch.setattr(clients_handler, "upsert_inline_panel", fake_upsert_inline_panel)

    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(tg_id=4001, display_name="Наташа", is_admin=False, is_blocked=False)
        session.add(user)
        await session.commit()

        message = FakeMessage("новая заметка")
        state = FakeState()
        await state.update_data(
            admin_client_edit_id=user.id,
            admin_client_return_callback="admin_clients:home",
            admin_panel_chat_id=500,
            admin_panel_message_id=77,
        )

        await clients_handler.save_client_note(
            message,
            state,
            db_session=session,
            settings=settings,
        )

        assert updated_panels[0] == clients_handler.texts.ADMIN_CLIENT_NOTE_SAVED_TEXT
        assert updated_panels[1] == "card-body"
        assert message.answers == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_client_bookings_view_contains_booking_buttons() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=4011,
            tg_username="booking_client",
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
        now = datetime.now(UTC)
        next_slot = Slot(start_at=now + timedelta(days=3), status="booked")
        past_slot = Slot(start_at=now - timedelta(days=10), status="booked")
        session.add_all([user, service, next_slot, past_slot])
        await session.flush()
        active_booking = Booking(
            client_id=user.id,
            slot_id=next_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        completed_booking = Booking(
            client_id=user.id,
            slot_id=past_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.COMPLETED,
        )
        session.add_all([active_booking, completed_booking])
        await session.commit()

        panel = await clients_handler.build_client_card_panel(
            db_session=session,
            settings=settings,
            client_id=user.id,
            back_callback="admin_clients:list:0",
            view=clients_handler.CLIENT_CARD_BOOKINGS_VIEW,
        )

        assert panel is not None
        text, markup = panel
        assert "📅 Записи" in text
        callback_data = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        assert any(value.startswith("admin_booking_card:open:") for value in callback_data)
        assert any(value.startswith("admin_clients:open:") for value in callback_data)

    await engine.dispose()
