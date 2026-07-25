from __future__ import annotations

import os

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


@pytest.mark.asyncio
async def test_json_fsm_storage_keeps_previous_file_when_replace_fails(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "fsm.json"
    key = StorageKey(bot_id=1, chat_id=2, user_id=2)
    storage = JsonFsmStorage(path=path)
    await storage.set_data(key, {"step": "safe"})

    def fail_replace(source, destination) -> None:
        del source, destination
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        await storage.set_data(key, {"step": "new"})

    assert await storage.get_data(key) == {"step": "safe"}
    reloaded = JsonFsmStorage(path=path)
    assert await reloaded.get_data(key) == {"step": "safe"}
    assert list(tmp_path.glob(".*.tmp")) == []
