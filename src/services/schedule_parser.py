from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time

DATE_RE = re.compile(r"^\s*(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\s*")
TIME_RE = re.compile(r"(\d{1,2})(?:[:.](\d{2}))?")


@dataclass(slots=True)
class ParsedSlot:
    """A successfully parsed slot from the admin schedule input."""

    date: date
    time: time
    line_no: int
    raw_line: str


@dataclass(slots=True)
class ParseError:
    """A line-level parser error."""

    line_no: int
    raw_line: str
    reason: str


def normalize_year(raw_year: str | None, *, today: date) -> tuple[int, bool]:
    """Return the parsed year and whether it was omitted in the input."""
    if raw_year is None:
        return today.year, True
    if len(raw_year) == 2:
        return 2000 + int(raw_year), False
    return int(raw_year), False


def parse_schedule(
    text: str, tz_name: str, today: date
) -> tuple[list[ParsedSlot], list[ParseError]]:
    """Parse a multiline schedule text into slots and line errors.

    Args:
        text: The raw multiline schedule text from Telegram.
        tz_name: Unused during parsing itself, kept for the service contract.
        today: The local current date used for year inference.

    Returns:
        A tuple of successfully parsed slots and line-level parse errors.
    """
    del tz_name

    parsed_slots: list[ParsedSlot] = []
    errors: list[ParseError] = []
    seen_slots: set[tuple[date, time]] = set()

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped_line = raw_line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue

        date_match = DATE_RE.match(raw_line)
        if date_match is None:
            errors.append(
                ParseError(line_no=line_no, raw_line=raw_line, reason="нет даты в начале")
            )
            continue

        day_raw, month_raw, year_raw = date_match.groups()
        year, year_was_omitted = normalize_year(year_raw, today=today)

        try:
            parsed_date = date(year, int(month_raw), int(day_raw))
        except ValueError:
            errors.append(ParseError(line_no=line_no, raw_line=raw_line, reason="невалидная дата"))
            continue

        if year_was_omitted and parsed_date < today:
            try:
                parsed_date = date(today.year + 1, int(month_raw), int(day_raw))
            except ValueError:
                errors.append(
                    ParseError(line_no=line_no, raw_line=raw_line, reason="невалидная дата")
                )
                continue

        remainder = raw_line[date_match.end() :]
        matches = list(TIME_RE.finditer(remainder))
        if not matches:
            errors.append(ParseError(line_no=line_no, raw_line=raw_line, reason="нет времён"))
            continue

        recognized_times = 0
        for match in matches:
            hour_raw, minute_raw = match.groups()
            hour = int(hour_raw)
            minute = int(minute_raw or "00")
            if not (0 <= hour < 24 and 0 <= minute < 60):
                errors.append(
                    ParseError(
                        line_no=line_no,
                        raw_line=raw_line,
                        reason=f"невалидное время «{match.group(0)}»",
                    )
                )
                continue

            recognized_times += 1
            parsed_time = time(hour, minute)
            dedupe_key = (parsed_date, parsed_time)
            if dedupe_key in seen_slots:
                continue

            seen_slots.add(dedupe_key)
            parsed_slots.append(
                ParsedSlot(
                    date=parsed_date,
                    time=parsed_time,
                    line_no=line_no,
                    raw_line=raw_line,
                )
            )

        if recognized_times == 0 and all(error.line_no != line_no for error in errors):
            errors.append(ParseError(line_no=line_no, raw_line=raw_line, reason="нет времён"))

    return parsed_slots, errors
