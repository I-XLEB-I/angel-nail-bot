from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

logger = logging.getLogger(__name__)
LEGACY_STATE_RE = re.compile(r'^<State ["\']([^"\']+)["\']>$')


class JsonFsmStorage(BaseStorage):
    """Persistent FSM storage backed by a JSON file.

    Suitable for low-concurrency deployments (single-process bot on SQLite).
    All writes are protected by an asyncio lock so concurrent coroutines
    don't corrupt the file.
    """

    def __init__(self, path: Path | str = "data/fsm_states.json") -> None:
        self._path = Path(path)
        self._lock = asyncio.Lock()
        self._cache: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def _make_key(self, key: StorageKey) -> str:
        return f"{key.bot_id}:{key.chat_id}:{key.user_id}:{key.destiny}"

    def _load(self) -> None:
        if self._path.exists():
            try:
                with self._path.open() as fh:
                    self._cache = json.load(fh)
            except Exception as exc:
                logger.warning("Could not read FSM storage file, starting fresh: %s", exc)
                self._cache = {}
        self._loaded = True

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w") as fh:
            json.dump(self._cache, fh)

    @staticmethod
    def _normalize_state_value(state: StateType) -> str | None:
        """Persist aiogram states as plain `Group:state` strings.

        Older builds wrote `str(State)` values like `<State 'Group:state'>`.
        This helper keeps backward compatibility for values already present
        in `data/fsm_states.json`.
        """
        if state is None:
            return None
        raw_value = getattr(state, "state", None)
        if isinstance(raw_value, str) and raw_value:
            return raw_value
        rendered = str(state)
        match = LEGACY_STATE_RE.match(rendered)
        if match is not None:
            return match.group(1)
        return rendered

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        async with self._lock:
            if not self._loaded:
                self._load()
            k = self._make_key(key)
            entry = self._cache.setdefault(k, {})
            normalized_state = self._normalize_state_value(state)
            if normalized_state is None:
                entry.pop("state", None)
            else:
                entry["state"] = normalized_state
            self._save()

    async def get_state(self, key: StorageKey) -> str | None:
        async with self._lock:
            if not self._loaded:
                self._load()
            state = self._cache.get(self._make_key(key), {}).get("state")
            return self._normalize_state_value(state)

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        async with self._lock:
            if not self._loaded:
                self._load()
            k = self._make_key(key)
            entry = self._cache.setdefault(k, {})
            if data:
                entry["data"] = data
            else:
                entry.pop("data", None)
            self._save()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with self._lock:
            if not self._loaded:
                self._load()
            return dict(self._cache.get(self._make_key(key), {}).get("data", {}))

    async def close(self) -> None:
        pass
