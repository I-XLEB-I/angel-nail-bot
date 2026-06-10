from __future__ import annotations

import re
from datetime import UTC, date, datetime, time
from html import escape
from zoneinfo import ZoneInfo

from src.db.models import ApprovalRequest, ApprovalRequestKind, Service, User
from src.services.aftercare import build_repair_requested_text
from src.services.booking import (
    build_booking_service_label,
    format_local_datetime,
    format_local_day_label,
    format_payment_method_label,
)

APPROVAL_KIND_LABELS = {
    ApprovalRequestKind.NEW_BOOKING: "Новая запись на нестандартное время",
    ApprovalRequestKind.RESCHEDULE: "Перенос на нестандартное время",
    ApprovalRequestKind.QUESTION: "Свободный вопрос",
    ApprovalRequestKind.FREQUENT_BOOKING: "Частая запись",
    ApprovalRequestKind.LATE_RESCHEDULE: "Поздний перенос",
    ApprovalRequestKind.MANUAL_APPROVAL_REQUIRED: "Требует ручного подтверждения",
    ApprovalRequestKind.REPAIR_REQUEST: "Ремонт / гарантия",
}
DATE_TIME_RE = re.compile(
    r"(?P<day>\d{1,2})[.\-/](?P<month>\d{1,2})(?:[.\-/](?P<year>\d{2,4}))?"
    r"(?:\D+)(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2}))?"
)
TIME_ONLY_RE = re.compile(r"\b(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2}))?\b")


def get_approval_kind_label(kind: ApprovalRequestKind) -> str:
    """Return a human-readable approval-request kind."""
    return APPROVAL_KIND_LABELS.get(kind, kind.value)


def format_relative_approval_age(
    created_at: datetime,
    *,
    now_utc: datetime | None = None,
) -> str:
    """Return a short relative age label for an approval request."""
    current_utc = now_utc or datetime.now(UTC)
    if current_utc.tzinfo is None:
        current_utc = current_utc.replace(tzinfo=UTC)
    normalized_created = (
        created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    )
    delta_seconds = max(int((current_utc - normalized_created).total_seconds()), 0)

    if delta_seconds < 60:
        return "только что"
    if delta_seconds < 3600:
        return f"{delta_seconds // 60} мин назад"
    if delta_seconds < 86400:
        return f"{delta_seconds // 3600} ч назад"
    return f"{delta_seconds // 86400} д назад"


def build_admin_approval_card_text(
    *,
    approval: ApprovalRequest,
    client: User,
    base_service: Service | None,
    addons: list[Service],
    tz_name: str,
    now_utc: datetime | None = None,
    warranty_days: int = 14,
    warranty_nails_limit: int = 2,
) -> str:
    """Render an admin card for any pending approval request."""
    if approval.kind == ApprovalRequestKind.REPAIR_REQUEST and approval.related_booking is not None:
        return build_repair_requested_text(
            approval=approval,
            source_booking=approval.related_booking,
            tz_name=tz_name,
            warranty_days=warranty_days,
            warranty_nails_limit=warranty_nails_limit,
            now_utc=now_utc,
        )

    username = f"@{client.tg_username}" if client.tg_username else "—"
    lines = [
        "💬 ЗАПРОС НА ПОДТВЕРЖДЕНИЕ",
        "────────────",
        f"👤 Клиентка: {client.display_name} ({username})",
        f"🗂 Тип: {get_approval_kind_label(approval.kind)}",
    ]

    if base_service is not None:
        lines.append(f"💅 Услуга: {build_booking_service_label(base_service, addons)}")

    if approval.payment_method:
        lines.append(f"💳 Оплата: {format_payment_method_label(approval.payment_method)}")

    if approval.preferred_day is not None:
        lines.append(f"📆 Предпочтительный день: {format_local_day_label(approval.preferred_day)}")

    if approval.related_booking is not None and approval.related_booking.slot is not None:
        current_local_dt = format_local_datetime(approval.related_booking.slot.start_at, tz_name)
        lines.extend(
            [
                "────────────",
                "🔁 Текущая запись:",
                (
                    f"📍 {format_local_day_label(current_local_dt.date())}, "
                    f"{current_local_dt.strftime('%H:%M')}"
                ),
            ]
        )

    lines.extend(
        [
            "────────────",
            f"🕰 Хочет: «{approval.requested_text}»",
        ]
    )

    if approval.design_photos:
        lines.append(f"🖼 Референсы: {len(approval.design_photos)} фото")

    if approval.requested_text == "(голосовое)":
        lines.append("🎤 Голосовое сообщение")

    lines.extend(
        [
            "────────────",
            f"⏳ Создано: {format_relative_approval_age(approval.created_at, now_utc=now_utc)}",
        ]
    )
    return "\n".join(lines)


def build_client_approval_confirmed_text(
    *,
    start_at: datetime,
    base_service_name: str,
    tz_name: str,
    address_text: str,
    payment_method: str | None = None,
) -> str:
    """Render the client notification after admin approval."""
    local_dt = format_local_datetime(start_at, tz_name)
    address_block = address_text.strip() or "—"
    return (
        "<b>✅ ЗАПИСЬ ПОДТВЕРЖДЕНА</b>\n\n"
        f"<b>📅 {escape(format_local_day_label(local_dt.date()))}</b>\n"
        f"<b>⏰ {escape(local_dt.strftime('%H:%M'))}</b>\n"
        f"💅 {escape(base_service_name)}\n"
        f"💳 {escape(format_payment_method_label(payment_method))}\n\n"
        "<b>📍 Адрес</b>\n"
        f"{address_block}\n\n"
        "✨ Ангела ждёт тебя в это время."
    )


def build_client_approval_declined_text(reason: str) -> str:
    """Render the client notification after a declined request."""
    return (
        "😔 Ангела посмотрела запрос и пока не может подтвердить это время.\n\n"
        f"Причина: {reason}"
    )


def build_client_admin_reply_text(text: str) -> str:
    """Render a text reply from the admin to the client."""
    return f"✉️ Ангела пишет:\n\n{text}"


def build_admin_client_reply_prefix(client: User) -> str:
    """Render the prefix for a client reply in the admin chat."""
    username = f"@{client.tg_username}" if client.tg_username else "—"
    return f"↩️ Ответ от {client.display_name} ({username})"


def normalize_request_year(raw_year: str | None, *, today: date) -> int:
    """Return the inferred request year."""
    if raw_year is None:
        return today.year
    if len(raw_year) == 2:
        return 2000 + int(raw_year)
    return int(raw_year)


def extract_requested_slot_start_at(
    *,
    requested_text: str,
    preferred_day: date | None,
    tz_name: str,
    today: date,
) -> datetime | None:
    """Extract a concrete requested datetime from free-form request text when possible."""
    local_day = preferred_day
    hour: int | None = None
    minute = 0

    datetime_match = DATE_TIME_RE.search(requested_text)
    if datetime_match is not None:
        day_raw = int(datetime_match.group("day"))
        month_raw = int(datetime_match.group("month"))
        year_raw = datetime_match.group("year")
        year = normalize_request_year(year_raw, today=today)
        try:
            local_day = date(year, month_raw, day_raw)
        except ValueError:
            return None

        if year_raw is None and local_day < today:
            try:
                local_day = date(today.year + 1, month_raw, day_raw)
            except ValueError:
                return None

        hour = int(datetime_match.group("hour"))
        minute = int(datetime_match.group("minute") or "00")
    elif preferred_day is not None:
        time_matches = list(TIME_ONLY_RE.finditer(requested_text))
        if not time_matches:
            return None
        selected_match = next(
            (match for match in reversed(time_matches) if match.group("minute") is not None),
            time_matches[-1],
        )
        hour = int(selected_match.group("hour"))
        minute = int(selected_match.group("minute") or "00")

    if local_day is None or hour is None:
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None

    local_dt = datetime.combine(local_day, time(hour, minute), tzinfo=ZoneInfo(tz_name))
    return local_dt.astimezone(UTC)
