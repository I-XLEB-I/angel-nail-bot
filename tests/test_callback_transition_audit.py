from __future__ import annotations

from pathlib import Path

ALLOWED_CALLBACK_ANSWER_COUNTS = {
    "src/bot/handlers/admin/clients.py": 2,
    "src/bot/handlers/admin/late_notices.py": 4,
    "src/bot/handlers/admin/proxy_chat.py": 1,
    "src/bot/handlers/client/booking_flow.py": 1,
}


def test_callback_message_answer_sites_are_explicitly_allowlisted() -> None:
    """Guard callback screens from silently regressing into chat-spam transitions."""
    root = Path("src/bot/handlers")
    found: dict[str, int] = {}
    for path in root.rglob("*.py"):
        count = path.read_text(encoding="utf-8").count("callback.message.answer(")
        if count:
            found[str(path)] = count

    assert found == ALLOWED_CALLBACK_ANSWER_COUNTS
