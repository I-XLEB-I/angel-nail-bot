from __future__ import annotations

import pytest
from aiogram.fsm.storage.base import StorageKey

from src.bot.fsm_storage import JsonFsmStorage
from src.bot.states import AdminTemplateEdit


@pytest.mark.asyncio
async def test_json_fsm_storage_persists_plain_state_value(tmp_path) -> None:
    storage = JsonFsmStorage(path=tmp_path / "fsm.json")
    key = StorageKey(bot_id=1, chat_id=2, user_id=2)

    await storage.set_state(key, AdminTemplateEdit.await_image)

    assert await storage.get_state(key) == "AdminTemplateEdit:await_image"


@pytest.mark.asyncio
async def test_json_fsm_storage_reads_legacy_state_format(tmp_path) -> None:
    path = tmp_path / "fsm.json"
    path.write_text(
        '{"1:2:2:default":{"state":"<State \\"AdminTemplateEdit:await_image\\">"}}'
    )
    storage = JsonFsmStorage(path=path)
    key = StorageKey(bot_id=1, chat_id=2, user_id=2)

    assert await storage.get_state(key) == "AdminTemplateEdit:await_image"
