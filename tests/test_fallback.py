"""Tests for the catch-all client fallback handler."""

from unittest.mock import AsyncMock

import pytest

from src.bot import texts
from src.bot.handlers.client import fallback as fallback_handler


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data: dict[str, object] = dict(data or {})

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)


class FakeMessage:
    def __init__(self, text: str = "что там по записи?") -> None:
        self.text = text
        self.answers: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))


@pytest.mark.asyncio
async def test_fallback_responds_to_unrecognised_client_text(monkeypatch) -> None:
    message = FakeMessage()
    state = FakeState()
    monkeypatch.setattr(fallback_handler, "load_all_button_configs", AsyncMock(return_value={}))

    await fallback_handler.fallback_text(message, state, db_session=None, is_admin=False)

    assert len(message.answers) == 1
    text, keyboard = message.answers[0]
    assert text == texts.CLIENT_FALLBACK_TEXT
    assert keyboard is not None
    callback_datas = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]
    urls = [
        button.url
        for row in keyboard.inline_keyboard
        for button in row
    ]
    assert "client_menu:book" in callback_datas
    # «Написать Ангеле» now opens the direct chat with a prefilled draft.
    assert any(url and url.startswith("tg://resolve?domain=ny_pip&text=") for url in urls)
    assert "client_menu:back" in callback_datas


@pytest.mark.asyncio
async def test_fallback_skips_admin_in_admin_mode() -> None:
    message = FakeMessage()
    state = FakeState({"admin_as_client": False})

    await fallback_handler.fallback_text(message, state, db_session=None, is_admin=True)

    assert message.answers == []


@pytest.mark.asyncio
async def test_fallback_fires_for_admin_in_client_mode(monkeypatch) -> None:
    message = FakeMessage()
    state = FakeState({"admin_as_client": True})
    monkeypatch.setattr(fallback_handler, "load_all_button_configs", AsyncMock(return_value={}))

    await fallback_handler.fallback_text(message, state, db_session=None, is_admin=True)

    assert len(message.answers) == 1
    assert message.answers[0][0] == texts.CLIENT_FALLBACK_TEXT
