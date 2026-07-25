from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery
from aiogram.types import User as TelegramUser

from src.bot import texts
from src.bot.access import AdminOnlyFilter


def _callback(data: str) -> CallbackQuery:
    return CallbackQuery(
        id="callback-id",
        from_user=TelegramUser(id=1001, is_bot=False, first_name="Аня"),
        chat_instance="chat-instance",
        data=data,
    )


@pytest.mark.asyncio
async def test_admin_filter_allows_admin() -> None:
    allowed = await AdminOnlyFilter()(_callback("admin_schedule:add"), is_admin=True)

    assert allowed is True


@pytest.mark.asyncio
async def test_admin_filter_rejects_and_answers_admin_callback(monkeypatch) -> None:
    answer = AsyncMock()
    monkeypatch.setattr(CallbackQuery, "answer", answer)
    callback = _callback("admin_schedule:add")

    allowed = await AdminOnlyFilter()(callback, is_admin=False)

    assert allowed is False
    answer.assert_awaited_once_with(texts.ADMIN_ONLY_TEXT, show_alert=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "callback_data",
    [
        "client_menu:services",
        "approval:accept_offer:42",
        "approval:decline_offer:42",
    ],
)
async def test_admin_filter_silently_skips_client_callback(
    monkeypatch,
    callback_data: str,
) -> None:
    answer = AsyncMock()
    monkeypatch.setattr(CallbackQuery, "answer", answer)
    callback = _callback(callback_data)

    allowed = await AdminOnlyFilter()(callback, is_admin=False)

    assert allowed is False
    answer.assert_not_awaited()
