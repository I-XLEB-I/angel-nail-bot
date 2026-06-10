from __future__ import annotations

from datetime import UTC, date, datetime

from src.bot.handlers.client.booking_flow import (
    order_day_options_by_preference,
    order_slots_by_time_preference,
)
from src.db.models import Slot, SlotStatus
from src.services.booking import DayOption


def test_order_day_options_by_preference_moves_matching_weekday_first() -> None:
    day_options = [
        DayOption(local_date=date(2026, 5, 18), label="18 мая"),
        DayOption(local_date=date(2026, 5, 20), label="20 мая"),
        DayOption(local_date=date(2026, 5, 19), label="19 мая"),
    ]

    ordered = order_day_options_by_preference(day_options, "Люблю вторник или среду")

    assert [item.local_date for item in ordered] == [
        date(2026, 5, 19),
        date(2026, 5, 20),
        date(2026, 5, 18),
    ]


def test_order_slots_by_time_preference_prioritizes_evening_slots() -> None:
    slots = [
        Slot(start_at=datetime(2026, 5, 18, 7, 0, tzinfo=UTC), status=SlotStatus.FREE),
        Slot(start_at=datetime(2026, 5, 18, 12, 0, tzinfo=UTC), status=SlotStatus.FREE),
        Slot(start_at=datetime(2026, 5, 18, 16, 0, tzinfo=UTC), status=SlotStatus.FREE),
    ]

    ordered = order_slots_by_time_preference(
        slots,
        "после работы, после 19",
        tz_name="Europe/Moscow",
    )

    assert [slot.start_at for slot in ordered] == [
        datetime(2026, 5, 18, 16, 0, tzinfo=UTC),
        datetime(2026, 5, 18, 12, 0, tzinfo=UTC),
        datetime(2026, 5, 18, 7, 0, tzinfo=UTC),
    ]


def test_order_slots_by_time_preference_respects_morning_hint() -> None:
    slots = [
        Slot(start_at=datetime(2026, 5, 18, 16, 0, tzinfo=UTC), status=SlotStatus.FREE),
        Slot(start_at=datetime(2026, 5, 18, 6, 30, tzinfo=UTC), status=SlotStatus.FREE),
        Slot(start_at=datetime(2026, 5, 18, 9, 0, tzinfo=UTC), status=SlotStatus.FREE),
    ]

    ordered = order_slots_by_time_preference(slots, "утром", tz_name="Europe/Moscow")

    assert [slot.start_at for slot in ordered] == [
        datetime(2026, 5, 18, 6, 30, tzinfo=UTC),
        datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
        datetime(2026, 5, 18, 16, 0, tzinfo=UTC),
    ]
