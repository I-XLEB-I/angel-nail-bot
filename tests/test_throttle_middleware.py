from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.bot.middlewares import throttle as throttle_module
from src.bot.middlewares.throttle import ThrottleMiddleware


@pytest.mark.asyncio
async def test_throttle_periodically_prunes_stale_users(monkeypatch) -> None:
    middleware = ThrottleMiddleware(min_interval_seconds=0.35)
    middleware._last_seen[(1, "OldEvent")] = 10.0
    middleware._events_since_cleanup = 999
    monkeypatch.setattr(throttle_module, "monotonic", lambda: 100.0)

    handled: list[object] = []

    async def handler(event, data):
        del data
        handled.append(event)
        return "ok"

    event = SimpleNamespace()
    result = await middleware(
        handler,
        event,
        {"event_from_user": SimpleNamespace(id=2)},
    )

    assert result == "ok"
    assert handled == [event]
    assert (1, "OldEvent") not in middleware._last_seen
    assert (2, "SimpleNamespace") in middleware._last_seen
    assert middleware._events_since_cleanup == 0
