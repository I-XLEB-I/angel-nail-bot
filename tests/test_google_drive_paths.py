from __future__ import annotations

from datetime import UTC, datetime

from src.config import Settings
from src.services.google_drive import (
    build_design_photo_folder_segments,
    sanitize_drive_name,
)


def test_sanitize_drive_name_replaces_separators() -> None:
    assert sanitize_drive_name("designs/one\\two") == "designs_one_two"


def test_build_design_photo_folder_segments_uses_local_timezone() -> None:
    settings = Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
    )

    uploaded_at = datetime(2026, 4, 30, 22, 30, tzinfo=UTC)

    assert build_design_photo_folder_segments(
        settings,
        uploaded_at=uploaded_at,
        tg_id=1395822345,
    ) == ["design-photos", "2026", "05", "1395822345"]
