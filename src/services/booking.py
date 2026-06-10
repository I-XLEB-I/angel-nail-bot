from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.db.models import (
    Booking,
    BookingCreatedVia,
    BookingStatus,
    Service,
    ServiceKind,
    Slot,
    SlotStatus,
    User,
)

PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{7,}$")
MONTH_NAMES_GENITIVE = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]
WEEKDAY_NAMES_NOMINATIVE = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
]
BOOKING_STATUS_LABELS = {
    BookingStatus.PENDING_MASTER: "Ждёт ответа Ангелы",
    BookingStatus.CONFIRMED: "Подтверждена",
    BookingStatus.CANCELLED_BY_CLIENT: "Отменена",
    BookingStatus.CANCELLED_BY_MASTER: "Отменена Ангелой",
    BookingStatus.COMPLETED: "Завершена",
    BookingStatus.NO_SHOW: "Не состоялась",
}
CANCEL_REASON_LABELS = {
    "sick": "Плохо себя чувствую",
    "busy": "Не успеваю по времени",
    "force_majeure": "Форс-мажор",
    "later": "Запишусь позже",
    "not_planning": "Не планирую больше",
    "other": "Другое",
}
PAYMENT_METHOD_CASH = "cash"
PAYMENT_METHOD_TRANSFER = "transfer"
BOOKING_STATUS_INLINE_LABELS = {
    BookingStatus.PENDING_MASTER: "ожидает подтверждения",
    BookingStatus.CONFIRMED: "подтверждена",
    BookingStatus.CANCELLED_BY_CLIENT: "отменена",
    BookingStatus.CANCELLED_BY_MASTER: "отменена Ангелой",
    BookingStatus.COMPLETED: "завершена",
    BookingStatus.NO_SHOW: "не состоялась",
}
PAYMENT_METHOD_LABELS = {
    PAYMENT_METHOD_CASH: "Наличными",
    PAYMENT_METHOD_TRANSFER: "Переводом",
}


@dataclass(slots=True)
class DayOption:
    """A bookable day rendered in the client's timezone."""

    local_date: date
    label: str


@dataclass(slots=True)
class ConfirmBookingResult:
    """Result of trying to confirm a booking."""

    ok: bool
    reason: str | None
    booking: Booking | None
    slot: Slot | None
    base_service: Service
    addons: list[Service]
    fixed_price: int
    has_variable_price: bool


@dataclass(slots=True)
class RescheduleBookingResult:
    """Result of trying to move a booking to another slot."""

    ok: bool
    reason: str | None
    booking: Booking
    old_slot: Slot | None
    new_slot: Slot | None


def needs_onboarding(user: User) -> bool:
    """Return whether the client still needs onboarding."""
    return not bool((user.display_name or "").strip())


def should_confirm_name(user: User, telegram_first_name: str | None) -> bool:
    """Return whether the flow should explicitly confirm the client's name."""
    saved_name = (user.display_name or "").strip()
    first_name = (telegram_first_name or "").strip()
    if not saved_name:
        return True
    return not user.phone and saved_name in {first_name, "Клиент"}


def normalize_phone(raw_phone: str) -> str | None:
    """Normalize a manually entered phone number into +7XXXXXXXXXX format."""
    if not PHONE_RE.match(raw_phone.strip()):
        return None

    digits = re.sub(r"\D", "", raw_phone)
    if len(digits) == 10:
        digits = f"7{digits}"
    elif len(digits) == 11 and digits.startswith("8"):
        digits = f"7{digits[1:]}"

    if len(digits) != 11 or not digits.startswith("7"):
        return None

    return f"+{digits}"


def format_local_datetime(value: datetime, tz_name: str) -> datetime:
    """Convert a UTC datetime into the configured local timezone."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo(tz_name))


def format_local_day_label(local_day: date) -> str:
    """Return a short Russian day label like `22 апреля`."""
    month_name = MONTH_NAMES_GENITIVE[local_day.month - 1]
    return f"{local_day.day} {month_name}"


def infer_shape_preference(design_comment: str | None) -> str | None:
    """Extract a likely nail-shape preference from a free-form design note."""
    if not design_comment:
        return None
    comment = design_comment.casefold()
    shape_aliases = (
        ("мягкий квадрат", "мягкий квадрат"),
        ("квадрат", "квадрат"),
        ("миндаль", "миндаль"),
        ("овал", "овал"),
        ("балерина", "балерина"),
        ("стилет", "стилет"),
    )
    for needle, label in shape_aliases:
        if needle in comment:
            return label
    return None


def infer_length_preference(design_comment: str | None) -> str | None:
    """Extract a likely length preference from a free-form design note."""
    if not design_comment:
        return None
    comment = design_comment.casefold()
    if "коротк" in comment:
        return "короткая"
    if "средн" in comment:
        return "средняя"
    if "длин" in comment:
        return "длинная"
    return None


def remember_client_preference_hints(
    user: User,
    *,
    preferred_day: date | None = None,
    preferred_time_text: str | None = None,
    design_comment: str | None = None,
) -> None:
    """Persist soft preference hints gathered from booking-related interactions."""
    if preferred_day is not None:
        weekday_label = WEEKDAY_NAMES_NOMINATIVE[preferred_day.weekday()]
        user.preferred_days_note = f"{weekday_label}, {format_local_day_label(preferred_day)}"
    if preferred_time_text:
        user.preferred_time_note = preferred_time_text.strip()[:240]
    if design_comment:
        user.preferred_design_note = design_comment.strip()[:500]
    inferred_shape = infer_shape_preference(design_comment)
    if inferred_shape:
        user.preferred_shape_note = inferred_shape
    inferred_length = infer_length_preference(design_comment)
    if inferred_length:
        user.preferred_length_note = inferred_length


def group_slots_by_local_day(slots: list[Slot], tz_name: str) -> list[DayOption]:
    """Return distinct bookable local days for a list of slots."""
    seen: set[date] = set()
    options: list[DayOption] = []
    for slot in slots:
        local_dt = format_local_datetime(slot.start_at, tz_name)
        local_day = local_dt.date()
        if local_day in seen:
            continue
        seen.add(local_day)
        options.append(DayOption(local_date=local_day, label=format_local_day_label(local_day)))
    return options


def format_service_price(service: Service) -> str:
    """Return a human-readable service price for the client UI."""
    if service.price_variable:
        if service.price > 0:
            return f"от {service.price}₽"
        return "обговаривается на месте"
    return f"{service.price}₽"


def normalize_payment_method(value: str | None) -> str:
    """Return a supported payment method, defaulting to transfer."""
    if value == PAYMENT_METHOD_CASH:
        return PAYMENT_METHOD_CASH
    return PAYMENT_METHOD_TRANSFER


def format_payment_method_label(value: str | None) -> str:
    """Return a user-facing payment-method label."""
    return PAYMENT_METHOD_LABELS.get(normalize_payment_method(value), "Переводом")


def payment_method_hint(value: str | None) -> str:
    """Return a short hint for the selected payment method."""
    if normalize_payment_method(value) == PAYMENT_METHOD_CASH:
        return "наличными Ангеле удобнее"
    return "можно переводом по договорённости"


def render_services_catalog_text(
    base_services: list[Service], addon_services: list[Service]
) -> str:
    """Render the client-facing services and prices text."""
    lines = ["💅 Услуги и цены", ""]
    for service in base_services:
        lines.append(f"{service.name} — {format_service_price(service)}")

    if addon_services:
        lines.extend(["", "Дополнительно:"])
        for service in addon_services:
            lines.append(f"• {service.name} — {format_service_price(service)}")

    return "\n".join(lines)


def build_services_caption_text() -> str:
    """Return the short caption shown under the price-list image."""
    from src.bot import texts

    return texts.SERVICES_CAPTION_TEXT


def build_addons_prompt_text(addons: list[Service], selected_ids: list[int]) -> str:
    """Render the add-on selection prompt."""
    selected_addons = [service.name for service in addons if service.id in selected_ids]
    lines = ["💅 ДОПОЛНИТЕЛЬНЫЕ ОПЦИИ", "", "Ориентир по ценам — на картинке выше."]
    if selected_addons:
        lines.append(f"Сейчас выбрано: {', '.join(selected_addons)}")
    else:
        lines.append("Сейчас выбрано: ничего")
    lines.extend(["", "Можно выбрать несколько или сразу нажать «Готово»."])
    return "\n".join(lines)


def build_reference_progress_text(photo_count: int, design_comment: str | None) -> str:
    """Render the reference-photo progress text."""
    lines = [f"Приняла, {photo_count}/5. Ещё или готово?"]
    if design_comment:
        lines.append("")
        lines.append(f"Комментарий: «{design_comment}»")
    return "\n".join(lines)


def build_booking_summary_text(
    *,
    base_service: Service,
    addons: list[Service],
    slot: Slot,
    tz_name: str,
    design_photo_count: int,
    design_comment: str | None,
    payment_method: str | None,
) -> str:
    """Render the booking confirmation summary."""
    fixed_price = base_service.price + sum(
        service.price for service in addons if not service.price_variable
    )
    has_variable_price = any(service.price_variable for service in addons)
    local_dt = format_local_datetime(slot.start_at, tz_name)
    service_line = f"{base_service.name} — {base_service.price}₽"

    lines = [
        "✨ Проверим запись",
        "",
        "Остался последний шаг перед подтверждением.",
        "",
        "┣ 💅 Услуга",
        f"┗ {service_line}",
    ]

    if addons:
        addon_label = ", ".join(service.name for service in addons)
        addon_suffix = " — обговариваются на месте" if has_variable_price else ""
        lines.extend(["", "┣ ✨ Дополнительно", f"┗ {addon_label}{addon_suffix}"])

    lines.extend(
        [
            "",
            "┣ 📅 Дата и время",
            f"┗ {format_local_day_label(local_dt.date())}, {local_dt.strftime('%H:%M')}",
        ]
    )

    if design_photo_count:
        lines.extend(["", "┣ 📸 Референсы", f"┗ {design_photo_count} фото"])

    if design_comment:
        lines.extend(["", "┣ 💬 Пожелания", f"┗ {design_comment}"])

    total_suffix = " + доп." if has_variable_price else ""
    lines.extend(["", "┣ 💳 Оплата", f"┗ {format_payment_method_label(payment_method)}"])
    if payment_method:
        hint = payment_method_hint(payment_method)
        lines.append(f"  {hint[:1].upper()}{hint[1:]}.")

    lines.extend(["", "┣ 💵 Итого", f"┗ {fixed_price}₽{total_suffix}"])
    if has_variable_price or design_photo_count or design_comment:
        lines.append(
            ""
        )
        lines.append(
            "Если дизайн или детали окажутся нестандартными, Ангела уточнит стоимость на месте."
        )

    lines.extend(["", "Если всё верно — жми «Подтвердить» 🤍"])
    return "\n".join(lines)


def build_receipt_text(*, base_service: Service, slot: Slot, tz_name: str) -> str:
    """Render the client receipt after a successful booking."""
    local_dt = format_local_datetime(slot.start_at, tz_name)
    return (
        "Записала тебя 💅\n\n"
        f"{format_local_day_label(local_dt.date())}, {local_dt.strftime('%H:%M')}\n\n"
        f"{base_service.name}\n\n"
        "Буду напоминать за сутки. Если что-то изменится — жми «Мои записи» в меню.\n\n"
        "До встречи 🤍"
    )


def build_admin_booking_text(
    *,
    client: User,
    base_service: Service,
    addons: list[Service],
    slot: Slot,
    tz_name: str,
    design_photo_count: int,
    design_comment: str | None,
    fixed_price: int,
    has_variable_price: bool,
    payment_method: str | None,
) -> str:
    """Render the admin notification about a new booking."""
    local_dt = format_local_datetime(slot.start_at, tz_name)
    addon_suffix = f" + {', '.join(service.name for service in addons)}" if addons else ""
    username = f"@{client.tg_username}" if client.tg_username else "—"
    lines = [
        "🆕 Новая запись",
        "",
        f"{client.display_name} ({username})",
        "",
        f"{base_service.name}{addon_suffix}",
        "",
        f"{format_local_day_label(local_dt.date())}, {local_dt.strftime('%H:%M')}",
        "",
        (
            "Цена: уточняется"
            if has_variable_price and fixed_price <= 0
            else f"Цена: {fixed_price}₽{' + доп.' if has_variable_price else ''}"
        ),
        f"Оплата: {format_payment_method_label(payment_method)}",
    ]

    if design_photo_count:
        lines.extend(["", f"📸 {design_photo_count} референса(ов)"])
    if design_comment:
        lines.extend(["", f"«{design_comment}»"])

    return "\n".join(lines)


def get_booking_status_label(status: BookingStatus) -> str:
    """Return a friendly booking status label for the client UI."""
    return BOOKING_STATUS_LABELS.get(status, status.value)


def get_cancel_reason_label(reason_code: str, reason_text: str | None = None) -> str:
    """Return a friendly cancellation reason label."""
    if reason_code == "other" and reason_text:
        return reason_text
    return CANCEL_REASON_LABELS.get(reason_code, reason_text or reason_code)


def format_booking_price(booking: Booking) -> str:
    """Return the booking price as a compact string."""
    if booking.has_variable_price and booking.fixed_price <= 0:
        return "уточняется"
    suffix = " + доп." if booking.has_variable_price else ""
    return f"{booking.fixed_price}₽{suffix}"


def build_booking_service_label(base_service: Service, addons: list[Service]) -> str:
    """Return a one-line service label for booking cards and admin notifications."""
    if not addons:
        return base_service.name
    return f"{base_service.name} + {', '.join(service.name for service in addons)}"


def format_time_until_visit(start_at: datetime, *, now_utc: datetime | None = None) -> str:
    """Return a short human-readable delta until the visit."""
    current_utc = now_utc or datetime.now(UTC)
    if current_utc.tzinfo is None:
        current_utc = current_utc.replace(tzinfo=UTC)

    normalized_start = start_at if start_at.tzinfo is not None else start_at.replace(tzinfo=UTC)
    remaining = max(normalized_start - current_utc, timedelta())
    total_seconds = int(remaining.total_seconds())
    days, remainder = divmod(total_seconds, 24 * 60 * 60)
    hours, remainder = divmod(remainder, 60 * 60)
    minutes = remainder // 60

    parts: list[str] = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    if not days and minutes:
        parts.append(f"{minutes} мин")
    return " ".join(parts[:2]) if parts else "0 мин"


def booking_needs_manual_resolution(
    booking: Booking,
    *,
    now_utc: datetime | None = None,
) -> bool:
    """Return whether the booking must stay open for a manual post-visit decision."""
    if booking.status != BookingStatus.CONFIRMED or booking.slot is None:
        return False
    if booking.reminder_2h_unconfirmed_alert_sent_at is None:
        return False
    if booking.reminder_2h_confirmed_at is not None:
        return False

    current_utc = now_utc or datetime.now(UTC)
    start_at = (
        booking.slot.start_at
        if booking.slot.start_at.tzinfo is not None
        else booking.slot.start_at.replace(tzinfo=UTC)
    )
    return start_at <= current_utc


def get_booking_display_status_label(
    booking: Booking,
    *,
    now_utc: datetime | None = None,
) -> str:
    """Return a richer status label for booking cards and lists."""
    if booking_needs_manual_resolution(booking, now_utc=now_utc):
        return "Требует решения Ангелы"
    return get_booking_status_label(booking.status)


def get_booking_display_status_inline_label(
    booking: Booking,
    *,
    now_utc: datetime | None = None,
) -> str:
    """Return a compact status label for short client-facing summaries."""
    if booking_needs_manual_resolution(booking, now_utc=now_utc):
        return "требует решения Ангелы"
    return get_booking_status_inline_label(booking.status)


def can_reschedule_booking(booking: Booking, *, now_utc: datetime | None = None) -> bool:
    """Return whether the client can reschedule the booking right now."""
    if booking.status != BookingStatus.CONFIRMED or booking.slot is None:
        return False
    current_utc = now_utc or datetime.now(UTC)
    normalized_start = (
        booking.slot.start_at
        if booking.slot.start_at.tzinfo is not None
        else booking.slot.start_at.replace(tzinfo=UTC)
    )
    return normalized_start > current_utc


def can_cancel_booking(booking: Booking, *, now_utc: datetime | None = None) -> bool:
    """Return whether the client can cancel the booking right now."""
    if booking.status == BookingStatus.PENDING_MASTER:
        return True
    return can_reschedule_booking(booking, now_utc=now_utc)


def needs_late_cancellation_notice(booking: Booking, *, now_utc: datetime | None = None) -> bool:
    """Return whether the client should see the under-24-hours note."""
    if booking.slot is None:
        return False
    current_utc = now_utc or datetime.now(UTC)
    normalized_start = (
        booking.slot.start_at
        if booking.slot.start_at.tzinfo is not None
        else booking.slot.start_at.replace(tzinfo=UTC)
    )
    delta = normalized_start - current_utc
    return timedelta() < delta < timedelta(hours=24)


def build_booking_list_item_label(booking: Booking, *, tz_name: str) -> str:
    """Return a concise label for the `Мои записи` list."""
    status_label = get_booking_display_status_label(booking)
    if booking.slot is None:
        return f"Без времени • {status_label}"

    local_dt = format_local_datetime(booking.slot.start_at, tz_name)
    return (
        f"{format_local_day_label(local_dt.date())}, {local_dt.strftime('%H:%M')} • {status_label}"
    )


def build_my_bookings_list_text(
    *,
    active_bookings: list[Booking],
    completed_bookings: list[Booking],
    tz_name: str,
) -> str:
    """Render the overview text for the `Мои записи` section."""
    lines = ["🙋‍♀️ МОИ ЗАПИСИ", ""]

    if active_bookings:
        nearest, *other_active = active_bookings
        lines.append("✨ Ближайшая")
        lines.append(f"┗ {build_booking_list_item_label(nearest, tz_name=tz_name)}")
        if nearest.base_service is not None:
            lines.append(f"  💅 {nearest.base_service.name}")
        lines.append(f"  💳 {format_payment_method_label(nearest.payment_method)}")
        lines.append(f"  ✨ статус: {get_booking_display_status_inline_label(nearest)}")

        if other_active:
            lines.extend(["", "📌 Ещё активные"])
            for booking in other_active:
                lines.append(f"• {build_booking_list_item_label(booking, tz_name=tz_name)}")

    if completed_bookings:
        if active_bookings:
            lines.append("")
        lines.append("🕊 История")
        for booking in completed_bookings:
            lines.append(f"• {build_booking_list_item_label(booking, tz_name=tz_name)}")

    lines.extend(["", "Открой запись ниже, чтобы посмотреть детали или действия 👇"])
    return "\n".join(lines)


def format_duration_approx(total_minutes: int) -> str:
    """Return a compact Russian approximation like `≈ 1ч 30м`."""
    if total_minutes <= 0:
        return ""
    hours, minutes = divmod(total_minutes, 60)
    parts = ["≈"]
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    return " ".join(parts)


def format_history_visits_summary(total_visits: int) -> str:
    """Return a friendly Russian label for completed-visit counts."""
    mod10 = total_visits % 10
    mod100 = total_visits % 100
    if mod10 == 1 and mod100 != 11:
        suffix = "раз"
    elif mod10 in {2, 3, 4} and mod100 not in {12, 13, 14}:
        suffix = "раза"
    else:
        suffix = "раз"
    return f"С нами уже {total_visits} {suffix}"


def get_booking_status_inline_label(status: BookingStatus) -> str:
    """Return a lowercase status label for compact client summaries."""
    return BOOKING_STATUS_INLINE_LABELS.get(status, status.value)


def build_my_bookings_overview_text(
    *,
    user: User,
    active_bookings: list[Booking],
    service_labels: dict[int, str],
    completed_visits: int,
    last_completed_at: datetime | None,
    tz_name: str,
    address_text: str | None = None,
) -> str:
    """Render a warm summary-first overview for the `Мои записи` section."""
    lines = [f"Привет, {user.display_name} 🌸", ""]

    if active_bookings:
        lines.extend(["Вот что у нас с тобой запланировано:", ""])
        nearest = active_bookings[0]
        nearest_service = service_labels.get(nearest.id, nearest.base_service.name)
        if nearest.slot is not None:
            nearest_local = format_local_datetime(nearest.slot.start_at, tz_name)
            nearest_duration = format_duration_approx(
                nearest.base_service.duration_min
            )
            nearest_day = format_local_day_label(nearest_local.date())
            nearest_weekday = WEEKDAY_NAMES_NOMINATIVE[nearest_local.weekday()]
            lines.extend(
                [
                    "🌷 Ближайшая встреча",
                    "─────────────────",
                    f"💅 {nearest_service}",
                    f"📅 {nearest_weekday}, {nearest_day}",
                    (
                        f"🕑 {nearest_local.strftime('%H:%M')} ({nearest_duration})"
                        if nearest_duration
                        else f"🕑 {nearest_local.strftime('%H:%M')}"
                    ),
                ]
            )
        else:
            lines.extend(
                [
                    "🌷 Ближайшая встреча",
                    "─────────────────",
                    f"💅 {nearest_service}",
                    "📅 Дата уточняется",
                ]
            )
        if address_text:
            lines.append(f"📍 {address_text}")
        lines.append(f"✨ статус: {get_booking_status_inline_label(nearest.status)}")

        if len(active_bookings) > 1:
            next_booking = active_bookings[1]
            next_service = service_labels.get(next_booking.id, next_booking.base_service.name)
            lines.extend(["", "🌸 Следующая", "─────────────────", f"💅 {next_service}"])
            if next_booking.slot is not None:
                next_local = format_local_datetime(next_booking.slot.start_at, tz_name)
                next_day = format_local_day_label(next_local.date())
                next_weekday = WEEKDAY_NAMES_NOMINATIVE[next_local.weekday()]
                lines.append(f"📅 {next_weekday}, {next_day}")
                lines.append(f"🕑 {next_local.strftime('%H:%M')}")
            else:
                lines.append("📅 Дата уточняется")
            lines.append(f"✨ статус: {get_booking_status_inline_label(next_booking.status)}")

        lines.extend(["", "До встречи! 💕"])
    else:
        lines.extend(
            [
                "Сейчас активных записей нет, но я рядом, когда захочешь выбрать новое окошко ✨",
            ]
        )

    lines.append("")
    if completed_visits > 0:
        summary = f"📜 {format_history_visits_summary(completed_visits)}"
        if last_completed_at is not None:
            summary += f" · последний визит {format_local_day_label(last_completed_at.date())}"
        lines.append(summary)
    else:
        lines.append("📜 Это будет наша первая встреча ✨")
    return "\n".join(lines)


def build_client_booking_card_text(
    *,
    booking: Booking,
    addons: list[Service],
    tz_name: str,
) -> str:
    """Render the client's booking card."""
    if booking.slot is None:
        title = "📌 Запись"
        datetime_line = "Дата и время уточняются"
    else:
        local_dt = format_local_datetime(booking.slot.start_at, tz_name)
        title = f"📌 Запись {format_local_day_label(local_dt.date())}, {local_dt.strftime('%H:%M')}"
        datetime_line = None

    lines = [title, ""]
    if datetime_line:
        lines.extend([datetime_line, ""])

    lines.append(build_booking_service_label(booking.base_service, addons))
    lines.extend(
        [
            "",
            f"Цена: {format_booking_price(booking)}",
            f"Оплата: {format_payment_method_label(booking.payment_method)}",
            f"Статус: {get_booking_display_status_label(booking)}",
        ]
    )
    if booking_needs_manual_resolution(booking):
        lines.extend(
            [
                "",
                "⚠️ Клиентка не подтвердила визит после 2ч-напоминания.",
                "Ангела вручную уточняет, состоялся ли визит.",
            ]
        )
    return "\n".join(lines)


def build_admin_cancellation_text(
    *,
    booking: Booking,
    client: User,
    addons: list[Service],
    tz_name: str,
    now_utc: datetime | None = None,
) -> str:
    """Render the admin notification after a client cancellation."""
    username = f"@{client.tg_username}" if client.tg_username else "—"
    service_label = build_booking_service_label(booking.base_service, addons)
    reason_label = get_cancel_reason_label(
        booking.cancel_reason_code or "", booking.cancel_reason_text
    )

    if booking.slot is None:
        booking_line = f"Была запись: {service_label}"
        time_until_line = "Отменила за: —"
    else:
        local_dt = format_local_datetime(booking.slot.start_at, tz_name)
        booking_line = (
            f"Была на {format_local_day_label(local_dt.date())}, "
            f"{local_dt.strftime('%H:%M')}: {service_label}"
        )
        time_until_line = (
            "Отменила за: "
            f"{format_time_until_visit(booking.slot.start_at, now_utc=now_utc)} до визита"
        )

    return (
        "❌ Отмена записи\n\n"
        f"{client.display_name} ({username})\n\n"
        f"{booking_line}\n\n"
        f"Причина: {reason_label}\n\n"
        f"{time_until_line}"
    )


def build_admin_reschedule_text(
    *,
    booking: Booking,
    client: User,
    addons: list[Service],
    old_slot: Slot | None,
    new_slot: Slot | None,
    tz_name: str,
) -> str:
    """Render the admin notification after a client reschedule."""
    username = f"@{client.tg_username}" if client.tg_username else "—"
    service_label = build_booking_service_label(booking.base_service, addons)

    old_local_dt = (
        format_local_datetime(old_slot.start_at, tz_name)
        if old_slot is not None
        else None
    )
    new_local_dt = (
        format_local_datetime(new_slot.start_at, tz_name)
        if new_slot is not None
        else None
    )

    return texts.ADMIN_CLIENT_RESCHEDULED_TEXT.format(
        name=client.display_name,
        username=username,
        old_date=(
            format_local_day_label(old_local_dt.date())
            if old_local_dt is not None
            else "—"
        ),
        old_time=old_local_dt.strftime("%H:%M") if old_local_dt is not None else "—",
        new_date=(
            format_local_day_label(new_local_dt.date())
            if new_local_dt is not None
            else "—"
        ),
        new_time=new_local_dt.strftime("%H:%M") if new_local_dt is not None else "—",
        service=service_label,
    )


async def confirm_booking(
    session: AsyncSession,
    *,
    client_id: int,
    slot_id: int,
    base_service_id: int,
    addon_ids: list[int],
    design_photos: list[str],
    design_comment: str | None,
    payment_method: str | None = None,
    created_via: BookingCreatedVia = BookingCreatedVia.BOT,
) -> ConfirmBookingResult:
    """Atomically book a slot and create a confirmed booking."""
    base_service = await session.get(Service, base_service_id)
    if base_service is None or base_service.kind != ServiceKind.BASE:
        raise ValueError("Base service not found or invalid")

    unique_addon_ids = list(dict.fromkeys(addon_ids))
    addons: list[Service] = []
    if unique_addon_ids:
        addon_result = await session.execute(
            select(Service)
            .where(Service.id.in_(unique_addon_ids), Service.kind == ServiceKind.ADDON)
            .order_by(Service.display_order, Service.id)
        )
        addons = list(addon_result.scalars().all())
        if len(addons) != len(unique_addon_ids):
            raise ValueError("One or more add-ons were not found")

    slot = await session.get(Slot, slot_id)
    if slot is None:
        return ConfirmBookingResult(
            ok=False,
            reason="slot_missing",
            booking=None,
            slot=None,
            base_service=base_service,
            addons=addons,
            fixed_price=base_service.price,
            has_variable_price=base_service.price_variable
            or any(service.price_variable for service in addons),
        )

    fixed_price = base_service.price + sum(
        service.price for service in addons if not service.price_variable
    )
    has_variable_price = base_service.price_variable or any(
        service.price_variable for service in addons
    )

    update_result = await session.execute(
        update(Slot)
        .where(
            Slot.id == slot_id,
            Slot.status == SlotStatus.FREE,
        )
        .values(status=SlotStatus.BOOKED)
    )

    if update_result.rowcount != 1:
        await session.rollback()
        return ConfirmBookingResult(
            ok=False,
            reason="slot_unavailable",
            booking=None,
            slot=slot,
            base_service=base_service,
            addons=addons,
            fixed_price=fixed_price,
            has_variable_price=has_variable_price,
        )

    slot.status = SlotStatus.BOOKED
    booking = Booking(
        client_id=client_id,
        slot_id=slot_id,
        base_service_id=base_service_id,
        addons=unique_addon_ids,
        design_photos=design_photos,
        design_comment=(design_comment or "").strip() or None,
        fixed_price=fixed_price,
        has_variable_price=has_variable_price,
        payment_method=normalize_payment_method(payment_method),
        status=BookingStatus.CONFIRMED,
        created_via=created_via,
    )
    session.add(booking)
    await session.flush()
    await session.commit()
    await session.refresh(booking)

    return ConfirmBookingResult(
        ok=True,
        reason=None,
        booking=booking,
        slot=slot,
        base_service=base_service,
        addons=addons,
        fixed_price=fixed_price,
        has_variable_price=has_variable_price,
    )


async def cancel_booking(
    session: AsyncSession,
    *,
    booking: Booking,
    reason_code: str,
    reason_text: str | None = None,
) -> Slot | None:
    """Cancel a client booking and release its slot."""
    released_slot = booking.slot

    if booking.slot_id is not None:
        await session.execute(
            update(Slot).where(Slot.id == booking.slot_id).values(status=SlotStatus.FREE)
        )
        if released_slot is not None:
            released_slot.status = SlotStatus.FREE

    booking.status = BookingStatus.CANCELLED_BY_CLIENT
    booking.cancel_reason_code = reason_code
    booking.cancel_reason_text = (
        (reason_text or "").strip() or None if reason_code == "other" else None
    )
    await session.flush()
    await session.commit()
    return released_slot


async def cancel_booking_by_master(
    session: AsyncSession,
    *,
    booking: Booking,
    reason_text: str | None = None,
) -> Slot | None:
    """Cancel a booking from the admin side and release its slot."""
    released_slot = booking.slot

    if booking.slot_id is not None:
        await session.execute(
            update(Slot).where(Slot.id == booking.slot_id).values(status=SlotStatus.FREE)
        )
        if released_slot is not None:
            released_slot.status = SlotStatus.FREE

    booking.status = BookingStatus.CANCELLED_BY_MASTER
    booking.cancel_reason_code = "other"
    booking.cancel_reason_text = (reason_text or "").strip() or "Отменена Ангелой"
    await session.flush()
    await session.commit()
    return released_slot


def apply_booking_no_show(
    booking: Booking,
    *,
    no_show_strike_limit: int,
    now_utc: datetime | None = None,
) -> None:
    """Apply the shared no-show side effects to one confirmed booking."""
    current_utc = now_utc or datetime.now(UTC)
    booking.status = BookingStatus.NO_SHOW
    if booking.client is not None:
        booking.client.strikes += 2
        if booking.client.strikes >= no_show_strike_limit * 2:
            booking.client.requires_manual_approval = True
    if booking.slot is not None and booking.slot.start_at > current_utc:
        booking.slot.status = SlotStatus.FREE


def build_no_show_client_notice(
    *,
    strikes: int,
    strike_limit: int,
    requires_manual_approval: bool,
) -> str:
    """Render the client-facing text after an admin marks a booking as no-show."""
    manual_approval_hint = (
        "Сейчас новые записи будут идти через ручное подтверждение Ангелы."
        if requires_manual_approval
        else "Пока всё ещё можно записываться через бота."
    )
    return texts.NO_SHOW_CLIENT_NOTICE_TEXT.format(
        strikes=strikes,
        strike_limit=strike_limit,
        manual_approval_hint=manual_approval_hint,
    )


async def reschedule_booking(
    session: AsyncSession,
    *,
    booking: Booking,
    new_slot_id: int,
) -> RescheduleBookingResult:
    """Move a confirmed booking to another free slot."""
    if booking.status != BookingStatus.CONFIRMED:
        return RescheduleBookingResult(
            ok=False,
            reason="not_confirmed",
            booking=booking,
            old_slot=booking.slot,
            new_slot=None,
        )

    if booking.slot_id is None:
        return RescheduleBookingResult(
            ok=False,
            reason="slot_missing",
            booking=booking,
            old_slot=None,
            new_slot=None,
        )

    if booking.slot_id == new_slot_id:
        return RescheduleBookingResult(
            ok=False,
            reason="same_slot",
            booking=booking,
            old_slot=booking.slot,
            new_slot=booking.slot,
        )

    new_slot = await session.get(Slot, new_slot_id)
    if new_slot is None:
        return RescheduleBookingResult(
            ok=False,
            reason="slot_missing",
            booking=booking,
            old_slot=booking.slot,
            new_slot=None,
        )

    update_result = await session.execute(
        update(Slot)
        .where(
            Slot.id == new_slot_id,
            Slot.status == SlotStatus.FREE,
        )
        .values(status=SlotStatus.BOOKED)
    )
    if update_result.rowcount != 1:
        await session.rollback()
        return RescheduleBookingResult(
            ok=False,
            reason="slot_unavailable",
            booking=booking,
            old_slot=booking.slot,
            new_slot=new_slot,
        )

    old_slot = booking.slot
    await session.execute(
        update(Slot).where(Slot.id == booking.slot_id).values(status=SlotStatus.FREE)
    )
    if old_slot is not None:
        old_slot.status = SlotStatus.FREE

    booking.slot_id = new_slot_id
    booking.slot = new_slot
    new_slot.status = SlotStatus.BOOKED
    booking.reschedules_count += 1
    await session.flush()
    await session.commit()

    return RescheduleBookingResult(
        ok=True,
        reason=None,
        booking=booking,
        old_slot=old_slot,
        new_slot=new_slot,
    )
