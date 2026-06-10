from __future__ import annotations

import pytest
from aiogram.exceptions import TelegramNetworkError

from src.bot import commands as bot_commands
from src.bot.handlers import common as common_handler
from src.config import Settings


class FakeBot:
    def __init__(self) -> None:
        self.command_calls: list[tuple[list[object], object]] = []
        self.fail_call_indexes: set[int] = set()

    async def set_my_commands(self, commands, *, scope) -> None:
        call_index = len(self.command_calls)
        self.command_calls.append((list(commands), scope))
        if call_index in self.fail_call_indexes:
            raise TelegramNetworkError(method="setMyCommands", message="timeout")


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.cleared = False

    async def clear(self) -> None:
        self.cleared = True
        self.data.clear()

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)


class FakeFromUser:
    def __init__(self, first_name: str = "Марк") -> None:
        self.first_name = first_name


class FakeMessage:
    def __init__(self, first_name: str = "Марк") -> None:
        self.from_user = FakeFromUser(first_name)
        self.answers: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1,2",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_register_bot_commands_sets_client_and_admin_scopes() -> None:
    settings = build_settings()
    bot = FakeBot()

    await bot_commands.register_bot_commands(bot, settings)

    assert len(bot.command_calls) == 3
    client_commands, client_scope = bot.command_calls[0]
    assert [command.command for command in client_commands] == [
        "start",
        "book",
        "mybookings",
        "admin",
    ]
    assert client_scope.__class__.__name__ == "BotCommandScopeAllPrivateChats"

    admin_commands, admin_scope = bot.command_calls[1]
    assert [command.command for command in admin_commands] == [
        "start",
        "schedule",
        "today",
        "requests",
        "clients",
        "diag",
        "admin",
    ]
    assert admin_scope.chat_id == 1


@pytest.mark.asyncio
async def test_register_bot_commands_continues_on_timeout() -> None:
    settings = build_settings()
    bot = FakeBot()
    bot.fail_call_indexes = {0, 2}

    await bot_commands.register_bot_commands(bot, settings)

    assert len(bot.command_calls) == 3


@pytest.mark.asyncio
async def test_command_book_forces_client_mode_and_starts_booking(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_start_booking_entry(
        message, state, *, db_session, user, first_name=None, replace_current=False
    ) -> None:
        del message, state, db_session, user
        calls.append(
            {
                "first_name": first_name,
                "replace_current": replace_current,
            }
        )

    monkeypatch.setattr(common_handler, "start_booking_entry", fake_start_booking_entry)

    message = FakeMessage("Дарина")
    state = FakeState()
    user = type("UserStub", (), {"id": 5})()

    await common_handler.command_book(
        message,
        state,
        db_session=None,
        user=user,
        is_admin=True,
    )

    assert state.cleared is True
    assert state.data["admin_as_client"] is True
    assert calls == [{"first_name": "Дарина", "replace_current": False}]


@pytest.mark.asyncio
async def test_command_my_bookings_forces_client_mode(monkeypatch) -> None:
    calls: list[int] = []

    async def fake_show_my_bookings_entry(
        message, state, *, db_session, user, settings, replace_current=False
    ) -> None:
        del message, state, db_session, settings, replace_current
        calls.append(user.id)

    monkeypatch.setattr(common_handler, "show_my_bookings_entry", fake_show_my_bookings_entry)

    message = FakeMessage()
    state = FakeState()
    user = type("UserStub", (), {"id": 7})()

    await common_handler.command_my_bookings(
        message,
        state,
        db_session=None,
        user=user,
        is_admin=False,
        settings=build_settings(),
    )

    assert state.cleared is True
    assert state.data == {}
    assert calls == [7]


@pytest.mark.asyncio
async def test_command_schedule_forces_admin_mode(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_show_schedule_menu(message, *, state=None) -> None:
        del message, state
        calls.append("schedule")

    monkeypatch.setattr(common_handler, "show_schedule_menu", fake_show_schedule_menu)

    message = FakeMessage()
    state = FakeState()
    await state.update_data(admin_as_client=True, some_flow="x")

    await common_handler.command_schedule(
        message,
        state,
        is_admin=True,
    )

    assert state.cleared is True
    assert state.data["admin_as_client"] is False
    assert calls == ["schedule"]


@pytest.mark.asyncio
async def test_command_today_status_sends_live_summary(monkeypatch) -> None:
    calls: list[int] = []

    async def fake_send_live_morning_summary_to_admin(
        bot,
        *,
        db_session,
        settings,
        admin_tg_id,
        local_today=None,
        now_utc=None,
    ) -> None:
        del bot, db_session, settings, local_today, now_utc
        calls.append(admin_tg_id)

    monkeypatch.setattr(
        common_handler,
        "send_live_morning_summary_to_admin",
        fake_send_live_morning_summary_to_admin,
    )

    message = FakeMessage()
    message.bot = object()
    message.chat = type("Chat", (), {"id": 42})()

    await common_handler.command_today_status(
        message,
        db_session=None,
        is_admin=True,
        settings=build_settings(),
    )

    assert calls == [42]


@pytest.mark.asyncio
async def test_command_requests_routes_to_pending_approvals(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_show_pending_approvals(message, *, db_session, is_admin, settings) -> None:
        del message, db_session, is_admin, settings
        calls.append("requests")

    monkeypatch.setattr(common_handler, "show_pending_approvals", fake_show_pending_approvals)

    await common_handler.command_requests(
        FakeMessage(),
        FakeState(),
        db_session=None,
        is_admin=True,
        settings=build_settings(),
    )

    assert calls == ["requests"]


@pytest.mark.asyncio
async def test_command_clients_routes_to_clients_section(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_open_clients_section(message, state, *, is_admin) -> None:
        del message, state, is_admin
        calls.append("clients")

    monkeypatch.setattr(common_handler, "open_clients_section", fake_open_clients_section)

    await common_handler.command_clients(
        FakeMessage(),
        FakeState(),
        is_admin=True,
    )

    assert calls == ["clients"]
