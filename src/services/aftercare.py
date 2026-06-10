from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    ApprovalRequest,
    ApprovalRequestKind,
    Booking,
    BookingStatus,
    LateArrivalNotice,
    ServiceKind,
)
from src.db.repositories.services import ServiceRepository
from src.services.booking import (
    build_booking_service_label,
    format_local_datetime,
    format_local_day_label,
)

LATE_REASON_LABELS = {
    "traffic": "🚗 Пробки",
    "transport": "🚇 Транспорт",
    "address": "📍 Ищу адрес",
    "delayed": "⏳ Задержали",
    "other": "✏️ Другое",
    "skip": "Без причины",
}

REPAIR_ISSUE_LABELS = {
    "chip": "Скол",
    "crack": "Трещина",
    "lifting": "Отслойка",
    "broken": "Сломался",
    "other": "Другое",
}

REPAIR_WARRANTY_SERVICE_NAME = "Гарантийный ремонт"
REPAIR_PAID_SERVICE_NAME = "Платный ремонт"
REPAIR_WARRANTY_SENTINEL = "__repair_warranty__"
REPAIR_PAID_SENTINEL = "__repair_paid__"
REPAIR_NOT_WARRANTY_SENTINEL = "__repair_not_warranty__"


def normalize_notice_reason(reason_code: str | None) -> str:
    """Return a friendly late-arrival reason label."""
    if not reason_code:
        return LATE_REASON_LABELS["skip"]
    return LATE_REASON_LABELS.get(reason_code, reason_code)


def normalize_repair_issue(issue_code: str | None) -> str:
    """Return a friendly repair issue label."""
    if not issue_code:
        return "—"
    return REPAIR_ISSUE_LABELS.get(issue_code, issue_code)


def is_repair_warranty_marked(approval: ApprovalRequest) -> bool:
    """Return whether the repair request is marked for warranty handling."""
    return approval.kind == ApprovalRequestKind.REPAIR_REQUEST and (
        approval.admin_response_text == REPAIR_WARRANTY_SENTINEL
    )


def is_repair_paid_marked(approval: ApprovalRequest) -> bool:
    """Return whether the repair request is marked for paid handling."""
    return approval.kind == ApprovalRequestKind.REPAIR_REQUEST and (
        approval.admin_response_text == REPAIR_PAID_SENTINEL
    )


def is_repair_mode_selected(approval: ApprovalRequest) -> bool:
    """Return whether the repair request already has a chosen handling mode."""
    return is_repair_warranty_marked(approval) or is_repair_paid_marked(approval)


def can_report_late_arrival(
    booking: Booking,
    *,
    now_utc: datetime | None = None,
    hours_before_start: int = 6,
) -> bool:
    """Return whether the client should see the `Опаздываю` CTA."""
    if booking.status != BookingStatus.CONFIRMED or booking.slot is None:
        return False
    current_utc = now_utc or datetime.now(UTC)
    normalized_start = (
        booking.slot.start_at
        if booking.slot.start_at.tzinfo is not None
        else booking.slot.start_at.replace(tzinfo=UTC)
    )
    if normalized_start <= current_utc:
        return False
    return (
        normalized_start.date() == current_utc.date()
        or normalized_start - current_utc <= timedelta(hours=hours_before_start)
    )


def can_request_repair(
    booking: Booking,
    *,
    now_utc: datetime | None = None,
    request_window_days: int = 30,
) -> bool:
    """Return whether the completed booking can start a repair request."""
    if booking.status != BookingStatus.COMPLETED or booking.slot is None:
        return False
    current_utc = now_utc or datetime.now(UTC)
    normalized_start = (
        booking.slot.start_at
        if booking.slot.start_at.tzinfo is not None
        else booking.slot.start_at.replace(tzinfo=UTC)
    )
    return current_utc - normalized_start <= timedelta(days=request_window_days)


def days_since_booking(booking: Booking, *, now_utc: datetime | None = None) -> int | None:
    """Return whole days since the booking slot start."""
    if booking.slot is None:
        return None
    current_utc = now_utc or datetime.now(UTC)
    normalized_start = (
        booking.slot.start_at
        if booking.slot.start_at.tzinfo is not None
        else booking.slot.start_at.replace(tzinfo=UTC)
    )
    if current_utc <= normalized_start:
        return 0
    return max((current_utc - normalized_start).days, 0)


def build_admin_late_notice_text(
    *,
    notice: LateArrivalNotice,
    booking: Booking,
    tz_name: str,
    is_update: bool = False,
) -> str:
    """Render one admin-facing late-arrival notification."""
    if booking.slot is None:
        when_line = "🕑 Время записи уточняется"
    else:
        local_dt = format_local_datetime(booking.slot.start_at, tz_name)
        when_line = (
            f"🕑 Запись: {format_local_day_label(local_dt.date())}, {local_dt.strftime('%H:%M')}"
        )

    title = "⏰ Клиентка опаздывает" if not is_update else "⏰ Клиентка обновила опоздание"
    lines = [
        title,
        "",
        f"👤 {notice.client.display_name}",
        when_line,
        f"💅 Услуга: {booking.base_service.name}",
        f"⌛ Опоздание: {notice.minutes} мин",
        f"📌 Причина: {normalize_notice_reason(notice.reason_code)}",
    ]
    if notice.comment:
        lines.extend(["", f"💬 Комментарий: {notice.comment}"])
    return "\n".join(lines)


def build_repair_requested_text(
    *,
    approval: ApprovalRequest,
    source_booking: Booking,
    tz_name: str,
    warranty_days: int,
    warranty_nails_limit: int,
    now_utc: datetime | None = None,
) -> str:
    """Render repair-specific details for admin approval cards."""
    days_since = days_since_booking(source_booking, now_utc=now_utc)
    in_window = days_since is not None and days_since <= warranty_days
    within_limit = (
        approval.repair_nails_count is not None
        and approval.repair_nails_count <= warranty_nails_limit
    )
    service_label = build_booking_service_label(source_booking.base_service, [])
    lines = [
        "🛠 ЗАПРОС НА РЕМОНТ",
        "────────────",
        f"👤 Клиентка: {approval.client.display_name}"
        + (f" (@{approval.client.tg_username})" if approval.client.tg_username else ""),
        f"💅 Исходная услуга: {service_label}",
    ]
    if source_booking.slot is not None:
        local_dt = format_local_datetime(source_booking.slot.start_at, tz_name)
        lines.append(
            f"📅 Визит: {format_local_day_label(local_dt.date())}, {local_dt.strftime('%H:%M')}"
        )
    if days_since is not None:
        lines.append(f"🗓 Прошло после визита: {days_since} дн")
    lines.append(f"🔢 Ногтей: {approval.repair_nails_count or '—'}")
    lines.append(f"🧩 Проблема: {normalize_repair_issue(approval.repair_issue_code)}")
    lines.append(
        "🛡 Гарантия: "
        + ("в окне" if in_window else "вне окна")
        + " · "
        + ("до лимита" if within_limit else "выше лимита")
    )
    if is_repair_warranty_marked(approval):
        lines.append("🧾 Решение: по гарантии")
    elif is_repair_paid_marked(approval):
        lines.append("🧾 Решение: платный ремонт")
    if approval.design_photos:
        lines.append(f"🖼 Фото: {len(approval.design_photos)}")
    if approval.design_comment:
        lines.extend(["", f"💬 Что случилось: {approval.design_comment}"])
    return "\n".join(lines)


async def ensure_warranty_service(
    db_session: AsyncSession,
    *,
    duration_min: int,
) -> int:
    """Return the hidden base service id used for warranty repairs."""
    return await ensure_hidden_repair_service(
        db_session,
        name=REPAIR_WARRANTY_SERVICE_NAME,
        price=0,
        price_variable=False,
        duration_min=duration_min,
    )


async def ensure_paid_repair_service(
    db_session: AsyncSession,
    *,
    duration_min: int,
) -> int:
    """Return the hidden base service id used for paid repairs."""
    return await ensure_hidden_repair_service(
        db_session,
        name=REPAIR_PAID_SERVICE_NAME,
        price=0,
        price_variable=True,
        duration_min=duration_min,
    )


async def ensure_hidden_repair_service(
    db_session: AsyncSession,
    *,
    name: str,
    price: int,
    price_variable: bool,
    duration_min: int,
) -> int:
    """Create or update one hidden service used for repair bookings."""
    repository = ServiceRepository(db_session)
    service = await repository.get_by_name(name)
    if service is None:
        service = await repository.create(
            name=name,
            price=price,
            price_variable=price_variable,
            duration_min=duration_min,
            kind=ServiceKind.BASE,
            is_active=False,
        )
    else:
        await repository.update(
            service,
            price=price,
            price_variable=price_variable,
            duration_min=duration_min,
            kind=ServiceKind.BASE,
            is_active=False,
        )
    await db_session.flush()
    return service.id
