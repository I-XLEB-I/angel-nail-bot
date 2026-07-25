from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.config import Settings
from src.db.models import (
    ApprovalRequest,
    ApprovalRequestKind,
    ApprovalRequestStatus,
    Booking,
    BookingCreatedVia,
    Service,
    User,
    utcnow,
)
from src.db.repositories.services import ServiceRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.slots import SlotRepository
from src.db.repositories.templates import TemplateRepository
from src.services.aftercare import (
    REPAIR_NOT_WARRANTY_SENTINEL,
    REPAIR_PAID_SERVICE_NAME,
    REPAIR_WARRANTY_SERVICE_NAME,
    ensure_paid_repair_service,
    ensure_warranty_service,
    is_repair_paid_marked,
    is_repair_warranty_marked,
)
from src.services.approvals import (
    build_client_approval_declined_text,
    extract_requested_slot_start_at,
)
from src.services.booking import (
    confirm_booking,
    format_local_datetime,
    reschedule_booking,
)
from src.services.booking_completion import (
    BookingClientConfirmationPayload,
    build_booking_client_confirmation_payload,
    finalize_confirmed_booking,
)
from src.services.calendar_sync import (
    CalendarBookingInfo,
    CalendarClientInfo,
    update_booking_event,
)
from src.services.runtime_settings import get_int_setting
from src.services.schedule_parser import parse_schedule
from src.services.template_texts import render_named_template

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApprovalSlotResolutionResult:
    """Domain result of resolving one approval against a concrete slot."""

    ok: bool
    reason: str | None = None
    start_at: datetime | None = None
    base_service_name: str | None = None
    client_confirmation: BookingClientConfirmationPayload | None = None


@dataclass(slots=True)
class _ApprovalResolutionClaim:
    """Original approval fields restored when slot resolution cannot finish."""

    status: ApprovalRequestStatus
    offered_slot_id: int | None
    offered_start_at: datetime | None
    resolved_at: datetime | None


async def _claim_approval_resolution(
    db_session: AsyncSession,
    approval: ApprovalRequest,
) -> _ApprovalResolutionClaim | None:
    """Atomically claim one still-actionable approval for slot resolution."""
    if approval.status not in {
        ApprovalRequestStatus.PENDING,
        ApprovalRequestStatus.OFFERED,
    }:
        return None

    original = _ApprovalResolutionClaim(
        status=approval.status,
        offered_slot_id=approval.offered_slot_id,
        offered_start_at=approval.offered_start_at,
        resolved_at=approval.resolved_at,
    )
    claimed_at = utcnow()
    transition = await db_session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval.id,
            ApprovalRequest.status == original.status,
            ApprovalRequest.offered_slot_id == original.offered_slot_id,
            ApprovalRequest.offered_start_at == original.offered_start_at,
        )
        .values(
            status=ApprovalRequestStatus.APPROVED,
            offered_slot_id=None,
            offered_start_at=None,
            resolved_at=claimed_at,
        )
        .execution_options(synchronize_session=False)
    )
    if transition.rowcount != 1:
        return None

    approval.status = ApprovalRequestStatus.APPROVED
    approval.offered_slot_id = None
    approval.offered_start_at = None
    approval.resolved_at = claimed_at
    return original


async def _restore_approval_resolution(
    db_session: AsyncSession,
    approval: ApprovalRequest,
    original: _ApprovalResolutionClaim,
) -> None:
    """Restore a claim when the selected slot could not be resolved."""
    await db_session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval.id,
            ApprovalRequest.status == ApprovalRequestStatus.APPROVED,
        )
        .values(
            status=original.status,
            offered_slot_id=original.offered_slot_id,
            offered_start_at=original.offered_start_at,
            resolved_at=original.resolved_at,
        )
        .execution_options(synchronize_session=False)
    )
    approval.status = original.status
    approval.offered_slot_id = original.offered_slot_id
    approval.offered_start_at = original.offered_start_at
    approval.resolved_at = original.resolved_at
    await db_session.commit()


async def load_approval_service_context(
    db_session: AsyncSession,
    approval: ApprovalRequest,
) -> tuple[Service | None, list[Service]]:
    """Load the base service and add-ons used in an approval card."""
    repository = ServiceRepository(db_session)
    base_service = approval.base_service
    if base_service is None and approval.related_booking is not None:
        base_service = approval.related_booking.base_service

    addon_ids = list(approval.addons)
    if not addon_ids and approval.related_booking is not None:
        addon_ids = list(approval.related_booking.addons)
    addons = await repository.list_by_ids(addon_ids)
    return base_service, addons


def extract_direct_confirmation_start_at(
    approval: ApprovalRequest,
    *,
    tz_name: str,
) -> datetime | None:
    """Return the exact requested datetime when it can be confirmed directly."""
    today_local = datetime.now(ZoneInfo(tz_name)).date()
    return extract_requested_slot_start_at(
        requested_text=approval.requested_text,
        preferred_day=approval.preferred_day,
        tz_name=tz_name,
        today=today_local,
    )


async def resolve_decline_reason_text(
    *,
    db_session: AsyncSession,
    reason_code: str,
) -> str:
    """Resolve a canned decline code into the final client-facing reason."""
    if reason_code == "repeat_booking":
        template_repository = TemplateRepository(db_session)
        reason = await template_repository.get_content_or_default(
            "decline_repeat_booking_reason",
            texts.DEFAULT_REPEAT_BOOKING_DECLINE_REASON,
        )
        return reason.strip() or texts.DEFAULT_REPEAT_BOOKING_DECLINE_REASON
    return {
        "busy": "Уже занято",
        "physical": "Не успею физически",
        "offday": "Это нерабочий день",
    }.get(reason_code, reason_code)


async def commit_decline_request(
    *,
    approval: ApprovalRequest,
    reason: str,
    db_session: AsyncSession,
    bot,
) -> bool:
    """Atomically persist one standard decline and notify the client."""
    if approval.status not in {
        ApprovalRequestStatus.PENDING,
        ApprovalRequestStatus.OFFERED,
    }:
        return False
    transition = await db_session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval.id,
            ApprovalRequest.status == approval.status,
            ApprovalRequest.offered_slot_id == approval.offered_slot_id,
            ApprovalRequest.offered_start_at == approval.offered_start_at,
        )
        .values(
            status=ApprovalRequestStatus.DECLINED,
            admin_response_text=reason,
            offered_slot_id=None,
            offered_start_at=None,
            resolved_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if transition.rowcount != 1:
        return False

    approval.status = ApprovalRequestStatus.DECLINED
    approval.admin_response_text = reason
    approval.offered_slot_id = None
    approval.offered_start_at = None
    approval.resolved_at = utcnow()
    await db_session.commit()

    await bot.send_message(
        chat_id=approval.client.tg_id,
        text=build_client_approval_declined_text(reason),
    )
    return True


async def commit_repair_decline_request(
    *,
    approval: ApprovalRequest,
    db_session: AsyncSession,
    bot,
) -> bool:
    """Atomically persist a repair decline and notify the client."""
    if approval.status not in {
        ApprovalRequestStatus.PENDING,
        ApprovalRequestStatus.OFFERED,
    }:
        return False
    resolved_at = utcnow()
    transition = await db_session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval.id,
            ApprovalRequest.status == approval.status,
            ApprovalRequest.offered_slot_id == approval.offered_slot_id,
            ApprovalRequest.offered_start_at == approval.offered_start_at,
        )
        .values(
            status=ApprovalRequestStatus.DECLINED,
            admin_response_text=REPAIR_NOT_WARRANTY_SENTINEL,
            offered_slot_id=None,
            offered_start_at=None,
            resolved_at=resolved_at,
        )
        .execution_options(synchronize_session=False)
    )
    if transition.rowcount != 1:
        return False

    approval.status = ApprovalRequestStatus.DECLINED
    approval.admin_response_text = REPAIR_NOT_WARRANTY_SENTINEL
    approval.offered_slot_id = None
    approval.offered_start_at = None
    approval.resolved_at = utcnow()
    await db_session.commit()

    await bot.send_message(
        chat_id=approval.client.tg_id,
        text=await render_named_template(
            TemplateRepository(db_session),
            key="repair_not_warranty",
            values={},
        ),
    )
    return True


async def commit_approval_offer(
    *,
    approval: ApprovalRequest,
    db_session: AsyncSession,
    offered_slot_id: int | None,
    offered_start_at: datetime | None,
) -> bool:
    """Atomically replace the current pending/offered time proposal."""
    if approval.status not in {
        ApprovalRequestStatus.PENDING,
        ApprovalRequestStatus.OFFERED,
    }:
        return False
    if (offered_slot_id is None) == (offered_start_at is None):
        raise ValueError("Exactly one offered time source is required")

    original_status = approval.status
    original_slot_id = approval.offered_slot_id
    original_start_at = approval.offered_start_at
    transition = await db_session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval.id,
            ApprovalRequest.status == original_status,
            ApprovalRequest.offered_slot_id == original_slot_id,
            ApprovalRequest.offered_start_at == original_start_at,
        )
        .values(
            status=ApprovalRequestStatus.OFFERED,
            offered_slot_id=offered_slot_id,
            offered_start_at=offered_start_at,
            resolved_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    if transition.rowcount != 1:
        return False

    approval.status = ApprovalRequestStatus.OFFERED
    approval.offered_slot_id = offered_slot_id
    approval.offered_start_at = offered_start_at
    approval.resolved_at = None
    await db_session.commit()
    return True


async def reset_approval_offer_to_pending(
    *,
    approval: ApprovalRequest,
    db_session: AsyncSession,
) -> bool:
    """Atomically return the current undelivered offer to the pending queue."""
    transition = await db_session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval.id,
            ApprovalRequest.status == ApprovalRequestStatus.OFFERED,
            ApprovalRequest.offered_slot_id == approval.offered_slot_id,
            ApprovalRequest.offered_start_at == approval.offered_start_at,
        )
        .values(
            status=ApprovalRequestStatus.PENDING,
            offered_slot_id=None,
            offered_start_at=None,
            resolved_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    if transition.rowcount != 1:
        return False

    approval.status = ApprovalRequestStatus.PENDING
    approval.offered_slot_id = None
    approval.offered_start_at = None
    approval.resolved_at = None
    await db_session.commit()
    return True


async def commit_quiet_approval_resolution(
    *,
    approval: ApprovalRequest,
    db_session: AsyncSession,
    allowed_statuses: tuple[ApprovalRequestStatus, ...],
    response_text: str,
) -> bool:
    """Atomically close an approval without sending a client notification."""
    resolved_at = utcnow()
    transition = await db_session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval.id,
            ApprovalRequest.status.in_(allowed_statuses),
        )
        .values(
            status=ApprovalRequestStatus.RESPONDED,
            admin_response_text=response_text,
            offered_slot_id=None,
            offered_start_at=None,
            resolved_at=resolved_at,
        )
        .execution_options(synchronize_session=False)
    )
    if transition.rowcount != 1:
        return False

    approval.status = ApprovalRequestStatus.RESPONDED
    approval.admin_response_text = response_text
    approval.offered_slot_id = None
    approval.offered_start_at = None
    approval.resolved_at = resolved_at
    await db_session.commit()
    return True


async def create_or_get_exact_slot_id(
    *,
    approval: ApprovalRequest,
    db_session: AsyncSession,
    tz_name: str,
) -> int | None:
    """Create or reuse the exact requested slot and return its id."""
    direct_start_at = extract_direct_confirmation_start_at(approval, tz_name=tz_name)
    if direct_start_at is None:
        return None

    slot_repository = SlotRepository(db_session)
    slot, _ = await slot_repository.create_if_missing(direct_start_at)
    await db_session.commit()
    return slot.id


def build_calendar_booking_info_from_request(
    *,
    booking: Booking,
    client: User,
    addons: list[Service],
) -> CalendarBookingInfo:
    """Build the calendar payload after manual approval."""
    if booking.slot is None:
        raise ValueError("Booking slot is required for calendar sync")

    return CalendarBookingInfo(
        booking_id=booking.id,
        start_at=booking.slot.start_at,
        duration_min=booking.base_service.duration_min
        + sum(addon.duration_min for addon in addons),
        base_service_name=booking.base_service.name,
        addon_names=[addon.name for addon in addons],
        client=CalendarClientInfo(
            display_name=client.display_name,
            tg_id=client.tg_id,
            tg_username=client.tg_username,
            phone=client.phone,
            note=client.note,
        ),
        design_comment=booking.design_comment,
    )


async def finalize_approval_with_slot(
    *,
    approval: ApprovalRequest,
    slot_id: int,
    db_session: AsyncSession,
    settings: Settings,
    calendar_event_updater=update_booking_event,
) -> ApprovalSlotResolutionResult:
    """Resolve one approval against a concrete slot using the shared business path."""
    base_service, addons = await load_approval_service_context(db_session, approval)
    slot_repository = SlotRepository(db_session)
    slot = await slot_repository.get_by_id(slot_id)
    if slot is None:
        return ApprovalSlotResolutionResult(ok=False, reason="slot_unavailable")

    if (
        approval.kind == ApprovalRequestKind.REPAIR_REQUEST
        and not is_repair_warranty_marked(approval)
        and not is_repair_paid_marked(approval)
    ):
        return ApprovalSlotResolutionResult(ok=False, reason="confirm_failed")
    if (
        approval.kind != ApprovalRequestKind.REPAIR_REQUEST
        and approval.related_booking is None
        and (base_service is None or approval.base_service_id is None)
    ):
        return ApprovalSlotResolutionResult(ok=False, reason="confirm_failed")

    original_claim = await _claim_approval_resolution(db_session, approval)
    if original_claim is None:
        return ApprovalSlotResolutionResult(ok=False, reason="approval_changed")

    if approval.kind == ApprovalRequestKind.REPAIR_REQUEST:
        repair_duration = await get_int_setting(
            SettingRepository(db_session),
            key="repair_default_duration_min",
            default=30,
        )
        if is_repair_warranty_marked(approval):
            repair_service_id = await ensure_warranty_service(
                db_session,
                duration_min=repair_duration,
            )
        elif is_repair_paid_marked(approval):
            repair_service_id = await ensure_paid_repair_service(
                db_session,
                duration_min=repair_duration,
            )
        else:
            await _restore_approval_resolution(db_session, approval, original_claim)
            return ApprovalSlotResolutionResult(ok=False, reason="confirm_failed")

        result = await confirm_booking(
            db_session,
            client_id=approval.client_id,
            slot_id=slot.id,
            base_service_id=repair_service_id,
            addon_ids=[],
            design_photos=list(approval.design_photos),
            design_comment=approval.design_comment,
            payment_method=approval.payment_method,
            created_via=BookingCreatedVia.BOT,
            allow_inactive_base_service=True,
        )
        if (
            not result.ok
            or result.booking is None
            or result.slot is None
            or result.base_service is None
        ):
            await _restore_approval_resolution(db_session, approval, original_claim)
            return ApprovalSlotResolutionResult(ok=False, reason="slot_unavailable")

        completion = await finalize_confirmed_booking(
            db_session,
            booking=result.booking,
            slot=result.slot,
            base_service=result.base_service,
            addons=[],
            user=approval.client,
            settings=settings,
            origin="approval",
            notify_client=True,
            sync_calendar=True,
        )

        return ApprovalSlotResolutionResult(
            ok=True,
            start_at=result.slot.start_at,
            base_service_name=result.base_service.name,
            client_confirmation=completion.client_confirmation,
        )

    if approval.related_booking is None:
        if base_service is None or approval.base_service_id is None:
            await _restore_approval_resolution(db_session, approval, original_claim)
            return ApprovalSlotResolutionResult(ok=False, reason="confirm_failed")

        result = await confirm_booking(
            db_session,
            client_id=approval.client_id,
            slot_id=slot.id,
            base_service_id=approval.base_service_id,
            addon_ids=list(approval.addons),
            design_photos=list(approval.design_photos),
            design_comment=approval.design_comment,
            payment_method=approval.payment_method,
            created_via=BookingCreatedVia.BOT,
        )
        if (
            not result.ok
            or result.booking is None
            or result.slot is None
            or result.base_service is None
        ):
            await _restore_approval_resolution(db_session, approval, original_claim)
            return ApprovalSlotResolutionResult(ok=False, reason="slot_unavailable")

        completion = await finalize_confirmed_booking(
            db_session,
            booking=result.booking,
            slot=result.slot,
            base_service=result.base_service,
            addons=addons,
            user=approval.client,
            settings=settings,
            origin="approval",
            notify_client=True,
            sync_calendar=True,
        )

        return ApprovalSlotResolutionResult(
            ok=True,
            start_at=result.slot.start_at,
            base_service_name=result.base_service.name,
            client_confirmation=completion.client_confirmation,
        )

    result = await reschedule_booking(
        db_session,
        booking=approval.related_booking,
        new_slot_id=slot.id,
    )
    if not result.ok or result.new_slot is None:
        await _restore_approval_resolution(db_session, approval, original_claim)
        return ApprovalSlotResolutionResult(ok=False, reason="slot_unavailable")

    if approval.related_booking.gcal_event_id:
        try:
            await asyncio.to_thread(
                calendar_event_updater,
                settings,
                event_id=approval.related_booking.gcal_event_id,
                booking=build_calendar_booking_info_from_request(
                    booking=approval.related_booking,
                    client=approval.client,
                    addons=addons,
                ),
            )
        except Exception:
            logger.exception(
                "Failed to update Google Calendar event for reschedule request %s",
                approval.id,
            )

    return ApprovalSlotResolutionResult(
        ok=True,
        start_at=result.new_slot.start_at,
        base_service_name=result.booking.base_service.name,
        client_confirmation=build_booking_client_confirmation_payload(
            booking=result.booking,
            slot=result.new_slot,
            base_service=result.booking.base_service,
            user=approval.client,
            notify_client=True,
        ),
    )


async def render_client_offer_text(
    *,
    approval: ApprovalRequest,
    start_at: datetime,
    db_session: AsyncSession,
    settings: Settings,
) -> str:
    """Render the client-facing offer text for standard or repair requests."""
    local_dt = format_local_datetime(start_at, settings.tz)
    if approval.kind == ApprovalRequestKind.REPAIR_REQUEST:
        if is_repair_warranty_marked(approval):
            service_name = REPAIR_WARRANTY_SERVICE_NAME
        elif is_repair_paid_marked(approval):
            service_name = REPAIR_PAID_SERVICE_NAME
        else:
            service_name = "Ремонт"
        return await render_named_template(
            TemplateRepository(db_session),
            key="repair_warranty_offer",
            values={
                "date": local_dt.strftime("%d.%m.%Y"),
                "time": local_dt.strftime("%H:%M"),
                "service": service_name,
            },
        )
    base_service, _ = await load_approval_service_context(db_session, approval)
    service_name = base_service.name if base_service is not None else "услуга"
    return texts.APPROVAL_TIME_OFFER_CLIENT_TEXT.format(
        date=local_dt.strftime("%d.%m.%Y"),
        time=local_dt.strftime("%H:%M"),
        service=service_name,
    )


def parse_custom_offer_start_at(raw_text: str, *, tz_name: str) -> datetime | None:
    """Parse one custom off-schedule offer datetime from admin input."""
    local_today = datetime.now(ZoneInfo(tz_name)).date()
    parsed_slots, errors = parse_schedule(raw_text, tz_name, local_today)
    if errors or len(parsed_slots) != 1:
        return None
    parsed_slot = parsed_slots[0]
    local_dt = datetime.combine(
        parsed_slot.date,
        parsed_slot.time,
        tzinfo=ZoneInfo(tz_name),
    )
    return local_dt.astimezone(UTC)
