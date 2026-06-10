from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Slot, SlotStatus
from src.db.repositories.slots import SlotRepository
from src.services.schedule_parser import ParsedSlot, parse_schedule


@dataclass(slots=True)
class SchedulePeriodDeleteResult:
    """Outcome of deleting free/blocked slots in one schedule period."""

    deleted_count: int
    period_label: str


@dataclass(slots=True)
class ScheduleSlotMutationResult:
    """Generic result for one schedule-slot mutation."""

    ok: bool
    reason: str | None = None
    slot: Slot | None = None


def format_schedule_period_label(start_local_date: date, end_local_date: date) -> str:
    """Return a compact local-date period label for schedule bulk actions."""
    return f"{start_local_date:%d.%m} – {end_local_date:%d.%m}"


def parsed_slot_to_utc(parsed_slot: ParsedSlot, *, tz_name: str) -> datetime:
    """Convert a parsed local slot into a UTC start datetime."""
    local_dt = datetime.combine(parsed_slot.date, parsed_slot.time, tzinfo=ZoneInfo(tz_name))
    return local_dt.astimezone(UTC)


async def get_schedule_delete_period_payload(
    db_session: AsyncSession,
    *,
    tz_name: str,
    period_kind: str,
) -> tuple[list[Slot], str]:
    """Return deletable slots and the display label for one bulk-delete period."""
    repository = SlotRepository(db_session)
    days = 30 if period_kind == "month" else 7
    slots = await repository.list_for_next_days(tz_name=tz_name, days=days)
    now_local = datetime.now(ZoneInfo(tz_name)).date()
    period_label = format_schedule_period_label(
        now_local,
        now_local + timedelta(days=days - 1),
    )
    deletable_slots = [slot for slot in slots if slot.status != SlotStatus.BOOKED]
    return deletable_slots, period_label


async def delete_schedule_period(
    db_session: AsyncSession,
    *,
    tz_name: str,
    period_kind: str,
) -> SchedulePeriodDeleteResult:
    """Delete every free/blocked slot in the selected schedule period."""
    repository = SlotRepository(db_session)
    deletable_slots, period_label = await get_schedule_delete_period_payload(
        db_session,
        tz_name=tz_name,
        period_kind=period_kind,
    )
    for slot in deletable_slots:
        await repository.delete_slot(slot)
    await db_session.commit()
    return SchedulePeriodDeleteResult(
        deleted_count=len(deletable_slots),
        period_label=period_label,
    )


async def move_schedule_slot(
    db_session: AsyncSession,
    *,
    slot_id: int,
    raw_text: str,
    tz_name: str,
) -> ScheduleSlotMutationResult:
    """Move one free/blocked slot to a newly parsed date and time."""
    repository = SlotRepository(db_session)
    slot = await repository.get_by_id(slot_id)
    if slot is None:
        return ScheduleSlotMutationResult(ok=False, reason="missing")
    if slot.status == SlotStatus.BOOKED:
        return ScheduleSlotMutationResult(ok=False, reason="booked", slot=slot)

    local_today = datetime.now(ZoneInfo(tz_name)).date()
    parsed_slots, errors = parse_schedule(raw_text, tz_name, local_today)
    if errors or len(parsed_slots) != 1:
        return ScheduleSlotMutationResult(ok=False, reason="invalid", slot=slot)

    new_start_at = parsed_slot_to_utc(parsed_slots[0], tz_name=tz_name)
    existing_slot = await repository.get_by_start_at(new_start_at)
    if existing_slot is not None and existing_slot.id != slot.id:
        return ScheduleSlotMutationResult(ok=False, reason="collision", slot=slot)

    await repository.update_start_at(slot, new_start_at)
    await db_session.commit()
    return ScheduleSlotMutationResult(ok=True, slot=slot)


async def delete_schedule_slot(
    db_session: AsyncSession,
    *,
    slot_id: int,
) -> ScheduleSlotMutationResult:
    """Delete one free or blocked schedule slot."""
    repository = SlotRepository(db_session)
    slot = await repository.get_by_id(slot_id)
    if slot is None:
        return ScheduleSlotMutationResult(ok=False, reason="missing")
    if slot.status == SlotStatus.BOOKED:
        return ScheduleSlotMutationResult(ok=False, reason="booked", slot=slot)

    await repository.delete_slot(slot)
    await db_session.commit()
    return ScheduleSlotMutationResult(ok=True)


async def block_schedule_slot(
    db_session: AsyncSession,
    *,
    slot_id: int,
) -> ScheduleSlotMutationResult:
    """Block one free or already blocked slot."""
    repository = SlotRepository(db_session)
    slot = await repository.get_by_id(slot_id)
    if slot is None:
        return ScheduleSlotMutationResult(ok=False, reason="missing")
    if slot.status == SlotStatus.BOOKED:
        return ScheduleSlotMutationResult(ok=False, reason="booked", slot=slot)

    await repository.update_status(slot, SlotStatus.BLOCKED)
    await db_session.commit()
    return ScheduleSlotMutationResult(ok=True, slot=slot)


async def unblock_schedule_slot(
    db_session: AsyncSession,
    *,
    slot_id: int,
) -> ScheduleSlotMutationResult:
    """Unblock one slot back into FREE status."""
    repository = SlotRepository(db_session)
    slot = await repository.get_by_id(slot_id)
    if slot is None:
        return ScheduleSlotMutationResult(ok=False, reason="missing")

    await repository.update_status(slot, SlotStatus.FREE)
    await db_session.commit()
    return ScheduleSlotMutationResult(ok=True, slot=slot)
