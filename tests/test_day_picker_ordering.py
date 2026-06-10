"""Regression tests for the client day-picker.

Locks down the invariants that a screenshot once suggested were broken:
- days come out chronologically sorted,
- the month label follows the local date (so month flips to «мая» when the
  local date crosses into May even if storage is UTC).
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.db.models import Slot, SlotStatus
from src.services.booking import (
    format_local_day_label,
    group_slots_by_local_day,
)


def _slot(start_at_utc: datetime) -> Slot:
    return Slot(start_at=start_at_utc, status=SlotStatus.FREE)


def test_group_slots_produces_chronological_days_across_month_boundary() -> None:
    """Slots from late April and mid-May render in chronological order with
    correct month names."""
    # UTC start times that span late April and mid-May 2026.
    # Europe/Moscow is UTC+3, so 06:00 UTC == 09:00 Moscow — all on the same
    # local day as the UTC date.
    slots = [
        _slot(datetime(2026, 4, 22, 6, 0, tzinfo=UTC)),
        _slot(datetime(2026, 4, 22, 9, 0, tzinfo=UTC)),  # same day, extra time
        _slot(datetime(2026, 4, 25, 6, 0, tzinfo=UTC)),
        _slot(datetime(2026, 4, 30, 6, 0, tzinfo=UTC)),
        _slot(datetime(2026, 5, 1, 6, 0, tzinfo=UTC)),
        _slot(datetime(2026, 5, 16, 6, 0, tzinfo=UTC)),
        _slot(datetime(2026, 5, 21, 6, 0, tzinfo=UTC)),
    ]

    options = group_slots_by_local_day(slots, "Europe/Moscow")

    labels = [option.label for option in options]
    assert labels == [
        "22 апреля",
        "25 апреля",
        "30 апреля",
        "1 мая",
        "16 мая",
        "21 мая",
    ]
    # The `seen` dedup set should collapse the duplicate April 22 entry.
    assert len(options) == len({option.local_date for option in options})


def test_group_slots_applies_timezone_to_local_date() -> None:
    """A UTC slot just before midnight must roll into the next local day."""
    # 22:30 UTC on April 30, 2026 == 01:30 Moscow time on May 1, 2026.
    slots = [
        _slot(datetime(2026, 4, 30, 6, 0, tzinfo=UTC)),
        _slot(datetime(2026, 4, 30, 22, 30, tzinfo=UTC)),
    ]

    options = group_slots_by_local_day(slots, "Europe/Moscow")
    assert [option.label for option in options] == ["30 апреля", "1 мая"]


def test_format_local_day_label_for_each_month() -> None:
    """Genitive month names must cover the full calendar."""
    expected = [
        "1 января",
        "1 февраля",
        "1 марта",
        "1 апреля",
        "1 мая",
        "1 июня",
        "1 июля",
        "1 августа",
        "1 сентября",
        "1 октября",
        "1 ноября",
        "1 декабря",
    ]
    for month, label in enumerate(expected, start=1):
        assert format_local_day_label(datetime(2026, month, 1).date()) == label
