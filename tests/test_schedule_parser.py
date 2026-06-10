from datetime import date

from src.services.schedule_parser import parse_schedule


def test_basic() -> None:
    text = "07.04 17:00 19:00 21:00\n08.04 17 19 21"
    slots, errs = parse_schedule(text, "Europe/Moscow", date(2026, 4, 1))

    assert len(slots) == 6
    assert not errs


def test_mixed_separators() -> None:
    text = "09.04 18:00, 20:00\n10.04 14/16"
    slots, errs = parse_schedule(text, "Europe/Moscow", date(2026, 4, 1))

    assert len(slots) == 4
    assert not errs


def test_bad_line() -> None:
    text = "хрень\n12.04 10:00"
    slots, errs = parse_schedule(text, "Europe/Moscow", date(2026, 4, 1))

    assert len(slots) == 1
    assert len(errs) == 1
    assert errs[0].reason == "нет даты в начале"


def test_past_date_rolls_to_next_year() -> None:
    slots, _ = parse_schedule("01.03 10:00", "Europe/Moscow", date(2026, 6, 1))

    assert slots[0].date.year == 2027


def test_deduplicates_inside_input() -> None:
    text = "07.04 17:00 17:00\n07.04 17"
    slots, errs = parse_schedule(text, "Europe/Moscow", date(2026, 4, 1))

    assert len(slots) == 1
    assert not errs
