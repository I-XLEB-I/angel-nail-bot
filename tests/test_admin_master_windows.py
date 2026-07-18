from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import broadcast as broadcast_handler
from src.bot.handlers.admin import menu as admin_menu_handler
from src.bot.handlers.admin import settings_edit as settings_handler
from src.config import Settings
from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, User
from src.db.repositories.settings import SettingRepository


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = dict(data or {})
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
        message_id: int = 42,
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
async def test_prompt_setting_edit_reuses_current_panel() -> None:
    callback = FakeCallback("admin_settings:edit:tz")
    state = FakeState()

    await settings_handler.prompt_setting_edit(
        callback,
        state,
        is_admin=True,
    )

    assert callback.answered is True
    assert state.data["admin_settings_key"] == "tz"
    assert state.data["admin_settings_panel_message_id"] == 42
    assert callback.message.edits
    assert "Часовой пояс" in callback.message.edits[0][0]


@pytest.mark.asyncio
async def test_save_setting_value_updates_existing_panel() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await SettingRepository(session).upsert(key="tz", value="Europe/Moscow")
        await session.commit()

        bot = FakeBot()
        message = FakeMessage("Europe/Paris", bot=bot)
        state = FakeState(
            {
                "admin_settings_key": "tz",
                "admin_settings_panel_chat_id": 500,
                "admin_settings_panel_message_id": 77,
            }
        )

        await settings_handler.save_setting_value(
            message,
            state,
            db_session=session,
            settings=settings,
        )

        assert state.cleared is True
        assert bot.edits
        assert "Часовой пояс: Europe/Paris" in str(bot.edits[-1]["text"])

    await engine.dispose()


@pytest.mark.asyncio
async def test_save_address_copy_setting_updates_runtime_value() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        bot = FakeBot()
        message = FakeMessage("Новая улица, 12", bot=bot)
        state = FakeState(
            {
                "admin_settings_key": "studio_address_copy_text",
                "admin_settings_panel_chat_id": 500,
                "admin_settings_panel_message_id": 77,
            }
        )

        await settings_handler.save_setting_value(
            message,
            state,
            db_session=session,
            settings=settings,
        )

        saved = await SettingRepository(session).get_value("studio_address_copy_text")
        assert saved == "Новая улица, 12"
        assert bot.edits

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_broadcast_shows_recipient_count() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(tg_id=2001, display_name="Анна", is_admin=False, is_blocked=False)
        service = Service(
            name="Маникюр",
            price=2000,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        slot = Slot(status="booked", start_at=datetime.now(UTC) + timedelta(days=1))
        session.add_all([user, service, slot])
        await session.flush()
        session.add(
            Booking(
                client_id=user.id,
                slot_id=slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=2000,
                has_variable_price=False,
                status=BookingStatus.COMPLETED,
            )
        )
        await session.commit()

        state = FakeState()
        message = FakeMessage()

        await broadcast_handler.open_broadcast(
            message,
            state,
            db_session=session,
            is_admin=True,
        )

        assert state.state is not None
        assert message.answers
        assert "Отправим на 1 клиенток" in message.answers[0][0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_broadcast_marks_blocked_recipients(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        first = User(tg_id=2001, display_name="Анна", is_admin=False, is_blocked=False)
        second = User(tg_id=2002, display_name="Лена", is_admin=False, is_blocked=False)
        service = Service(
            name="Маникюр",
            price=2000,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        now = datetime.now(UTC)
        slot_a = Slot(status="booked", start_at=now)
        slot_b = Slot(status="booked", start_at=now + timedelta(hours=1))
        session.add_all([first, second, service, slot_a, slot_b])
        await session.flush()
        session.add_all(
            [
                Booking(
                    client_id=first.id,
                    slot_id=slot_a.id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2000,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
                Booking(
                    client_id=second.id,
                    slot_id=slot_b.id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2000,
                    has_variable_price=False,
                    status=BookingStatus.CONFIRMED,
                ),
            ]
        )
        await session.commit()

        async def fake_run_broadcast(bot, *, recipient_ids, text):
            del bot, text
            assert recipient_ids == [2001, 2002]
            return 1, 1, 0, [2002]

        monkeypatch.setattr(broadcast_handler, "run_broadcast", fake_run_broadcast)

        callback = FakeCallback("admin_broadcast:confirm", message=FakeMessage())
        state = FakeState(
            {
                "admin_broadcast_text": "Привет\\!",
                "admin_broadcast_recipient_count": 2,
            }
        )

        await broadcast_handler.confirm_broadcast(
            callback,
            state,
            db_session=session,
            is_admin=True,
        )

        refreshed_second = await session.get(User, second.id)
        assert state.cleared is True
        assert refreshed_second is not None and refreshed_second.is_blocked is True
        assert callback.message.edits[0][0] == broadcast_handler.texts.ADMIN_BROADCAST_STARTED_TEXT
        assert "Доставлено: 1" in callback.message.edits[-1][0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_menu_home_callback_routes_back_to_dashboard(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_show_admin_menu(message, *, db_session, settings, state=None) -> None:
        del message, db_session, settings, state
        calls.append("admin-menu")

    monkeypatch.setattr(admin_menu_handler, "show_admin_menu", fake_show_admin_menu)

    callback = FakeCallback("admin_menu:home", message=FakeMessage())
    state = FakeState({"admin_as_client": True, "some_flow": "x"})

    await admin_menu_handler.admin_menu_home_callback(
        callback,
        state,
        db_session=None,
        is_admin=True,
        settings=build_settings(),
    )

    assert callback.answered is True
    assert state.cleared is True
    assert state.data["admin_as_client"] is False
    assert calls == ["admin-menu"]
