from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject


class ThrottleMiddleware(BaseMiddleware):
    """Very small in-memory anti-spam middleware."""

    def __init__(self, min_interval_seconds: float = 0.35) -> None:
        self.min_interval_seconds = min_interval_seconds
        self._last_seen: dict[tuple[int, str], float] = {}
        self._events_since_cleanup = 0

    def _prune_stale_entries(self, now: float) -> None:
        """Bound memory while retaining every entry that can still be throttled."""
        self._events_since_cleanup += 1
        if self._events_since_cleanup < 1000:
            return

        cutoff = now - max(1.0, self.min_interval_seconds * 4)
        self._last_seen = {
            key: seen_at
            for key, seen_at in self._last_seen.items()
            if seen_at >= cutoff
        }
        self._events_since_cleanup = 0

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = data.get("event_from_user")
        if from_user is None:
            return await handler(event, data)

        event_key = (from_user.id, type(event).__name__)
        now = monotonic()
        self._prune_stale_entries(now)
        last_seen = self._last_seen.get(event_key)
        self._last_seen[event_key] = now

        if last_seen is not None and now - last_seen < self.min_interval_seconds:
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("Секунду ✨", cache_time=1)
                except Exception:
                    pass
            return None

        return await handler(event, data)
