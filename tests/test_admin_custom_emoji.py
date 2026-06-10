from __future__ import annotations

import pytest

from src.bot.handlers.admin import custom_emoji as custom_emoji_handler
from src.bot.states import AdminCustomEmoji


class FakeState:
    def __init__(self) -> None:
        self.state = None
        self.data: dict[str, object] = {}
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


class FakeMessage:
    def __init__(self, *, entities=None) -> None:
        self.entities = entities
        self.answers: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None, parse_mode=None) -> None:
        self.answers.append((text, reply_markup if reply_markup is not None else parse_mode))


class FakeEntity:
    def __init__(self, *, type: str, custom_emoji_id: str | None = None) -> None:
        self.type = type
        self.custom_emoji_id = custom_emoji_id


@pytest.mark.asyncio
async def test_open_custom_emoji_tool_sets_state_and_shows_prompt(monkeypatch) -> None:
    state = FakeState()
    message = FakeMessage()
    captured: dict[str, object] = {}

    async def fake_clear_state(state_obj, *, admin_as_client=None) -> None:
        del admin_as_client
        await state_obj.clear()

    async def fake_show_prompt(message_obj, state_obj) -> None:
        del state_obj
        captured["message"] = message_obj

    monkeypatch.setattr(
        custom_emoji_handler,
        "clear_state_preserving_admin_panel",
        fake_clear_state,
    )
    monkeypatch.setattr(custom_emoji_handler, "show_custom_emoji_prompt", fake_show_prompt)

    await custom_emoji_handler.open_custom_emoji_tool(
        message,
        state,
        is_admin=True,
    )

    assert state.state == AdminCustomEmoji.await_emoji
    assert state.cleared is True
    assert captured["message"] is message


@pytest.mark.asyncio
async def test_extract_custom_emoji_id_returns_ids() -> None:
    message = FakeMessage(
        entities=[
            FakeEntity(type="custom_emoji", custom_emoji_id="111"),
            FakeEntity(type="custom_emoji", custom_emoji_id="222"),
            FakeEntity(type="custom_emoji", custom_emoji_id="111"),
        ]
    )

    await custom_emoji_handler.extract_custom_emoji_id(message)

    assert len(message.answers) == 1
    assert "`111`" in message.answers[0][0]
    assert "`222`" in message.answers[0][0]


@pytest.mark.asyncio
async def test_extract_custom_emoji_id_rejects_regular_emoji() -> None:
    message = FakeMessage(entities=[FakeEntity(type="bold")])

    await custom_emoji_handler.extract_custom_emoji_id(message)

    assert message.answers == [(custom_emoji_handler.texts.ADMIN_EMOJI_ID_EMPTY_TEXT, None)]
