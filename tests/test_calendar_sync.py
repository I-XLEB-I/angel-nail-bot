from __future__ import annotations

from datetime import datetime

from src.config import Settings
from src.services.calendar_sync import (
    CalendarBookingInfo,
    CalendarClientInfo,
    build_booking_event_body,
    build_smoke_test_event_body,
)


def test_build_smoke_test_event_body_has_expected_shape() -> None:
    settings = Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        GCAL_ENABLED="true",
        GCAL_CALENDAR_ID="calendar-id",
        GCAL_CREDENTIALS_PATH="./secrets/google_service_account.json",
    )

    event = build_smoke_test_event_body(settings)

    assert event["summary"] == "Angel Nail Bot smoke test"
    assert event["start"]["timeZone"] == "Europe/Moscow"
    assert event["end"]["timeZone"] == "Europe/Moscow"

    start_at = datetime.fromisoformat(event["start"]["dateTime"])
    end_at = datetime.fromisoformat(event["end"]["dateTime"])
    assert end_at > start_at


def test_build_smoke_test_event_body_includes_telegram_identity() -> None:
    settings = Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        GCAL_ENABLED="true",
        GCAL_CALENDAR_ID="calendar-id",
        GCAL_CREDENTIALS_PATH="./secrets/google_service_account.json",
    )
    client = CalendarClientInfo(
        display_name="Аня",
        tg_id=1395822345,
        tg_username="angel_client",
        phone="+79991234567",
        note="Любит нюдовые оттенки",
    )

    event = build_smoke_test_event_body(settings, client=client)

    assert event["summary"] == "Smoke test — Аня (@angel_client)"
    assert "Telegram: @angel_client" in event["description"]
    assert "Telegram ID: 1395822345" in event["description"]
    assert "Телефон: +79991234567" in event["description"]


def test_build_booking_event_body_uses_short_calendar_summary() -> None:
    settings = Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        GCAL_ENABLED="true",
        GCAL_CALENDAR_ID="calendar-id",
        GCAL_CREDENTIALS_PATH="./secrets/google_service_account.json",
    )
    booking = CalendarBookingInfo(
        booking_id=42,
        start_at=datetime(2026, 4, 22, 10, 0),
        duration_min=120,
        base_service_name="Покрытие гель-лак",
        addon_names=["Дизайн"],
        client=CalendarClientInfo(
            display_name="Дарина",
            tg_id=100500,
            tg_username="daridts",
        ),
    )

    event = build_booking_event_body(settings, booking)

    assert event["summary"] == "Ногти @daridts"
    assert "Услуга: Покрытие гель-лак + Дизайн" in event["description"]
