from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.config import Settings
from src.db.models import Slot, SlotStatus, User
from src.db.repositories.settings import SettingRepository
from src.db.repositories.users import UserRepository
from src.services.booking import format_local_datetime
from src.services.runtime_settings import get_int_setting

RESCUE_SLOT_CANDIDATE_LIMIT = 6


def slot_is_rescuable(slot: Slot) -> bool:
    """Return whether a free future slot can be offered to loyal clients."""
    start_at = slot.start_at if slot.start_at.tzinfo is not None else slot.start_at.replace(tzinfo=UTC)
    return slot.status == SlotStatus.FREE and start_at > datetime.now(UTC)


def build_admin_rescue_slot_prompt_text(slot: Slot, *, settings: Settings) -> str:
    """Render the admin-side prompt for rescuing a newly freed slot."""
    local_dt = format_local_datetime(slot.start_at, settings.tz)
    return texts.ADMIN_RESCUE_SLOT_PROMPT_TEXT.format(
        date=local_dt.strftime("%d.%m.%Y"),
        time=local_dt.strftime("%H:%M"),
    )


def build_admin_rescue_slot_sent_text(
    slot: Slot,
    *,
    settings: Settings,
    sent_count: int,
) -> str:
    """Render the admin-side confirmation after the rescue offer is sent."""
    local_dt = format_local_datetime(slot.start_at, settings.tz)
    return texts.ADMIN_RESCUE_SLOT_SENT_TEXT.format(
        date=local_dt.strftime("%d.%m.%Y"),
        time=local_dt.strftime("%H:%M"),
        count=sent_count,
    )


def build_client_rescue_offer_text(slot: Slot, *, settings: Settings) -> str:
    """Render the client-facing last-minute free-slot offer."""
    local_dt = format_local_datetime(slot.start_at, settings.tz)
    return texts.CLIENT_RESCUE_SLOT_TEXT.format(
        date=local_dt.strftime("%d.%m.%Y"),
        time=local_dt.strftime("%H:%M"),
    )


async def load_rescue_offer_candidates(
    db_session: AsyncSession,
    *,
    settings: Settings,
    exclude_user_ids: set[int] | None = None,
) -> list[User]:
    """Return loyal clients eligible for a last-minute rescue offer."""
    min_completed_visits = await get_int_setting(
        SettingRepository(db_session),
        key="frequent_booking_bypass_visits",
        default=5,
    )
    return await UserRepository(db_session).list_rescue_offer_candidates(
        min_completed_visits=min_completed_visits,
        limit=RESCUE_SLOT_CANDIDATE_LIMIT,
        exclude_user_ids=exclude_user_ids,
    )
