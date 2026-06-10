from __future__ import annotations

from html import escape

from aiogram.enums import ParseMode
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.handlers.client.address import (
    build_address_copy_text,
    build_address_map_url,
    build_address_text,
)
from src.bot.handlers.client.brand import send_brand_bot_message, send_brand_message
from src.bot.keyboards.client import build_post_booking_cta_keyboard
from src.config import Settings
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.admin_defaults import required_template_defaults
from src.services.booking import format_local_datetime, format_local_day_label, format_payment_method_label
from src.services.booking_completion import BookingClientConfirmationPayload
from src.services.button_configs import load_all_button_configs, load_master_contact_url
from src.services.template_texts import ensure_late_policy_notice, render_template_text
from src.services.template_media import has_template_media

_LEGACY_BOOKING_CONFIRM_TEMPLATE = """<b>✅ Записала тебя 🌸</b>

<b>👤 {name}</b>
<b>📅 {date}</b>
<b>⏰ {time}</b>
💅 {service}
💳 {payment}

<b>📍 Адрес</b>
{address}

✨ Напомню за сутки и за пару часов.

Если что-то изменится — жми «Мои записи» в меню.

До встречи 🌸"""


async def _build_booking_confirmation_text(
    db_session: AsyncSession,
    *,
    payload: BookingClientConfirmationPayload,
    settings: Settings,
) -> str:
    """Render the shared booking confirmation text from the standard template."""
    local_dt = format_local_datetime(payload.start_at, settings.tz)
    address_text = (await build_address_text(db_session)).strip() or "—"
    has_booking_confirm_media = has_template_media("booking_confirm")
    address_inline = "на картинке выше." if has_booking_confirm_media else address_text
    address_block = (
        "📍 Адрес — на картинке выше."
        if has_booking_confirm_media
        else f"<b>📍 Адрес</b>\n{address_text}"
    )
    template_repository = TemplateRepository(db_session)
    defaults = required_template_defaults()
    template_source = await template_repository.get_content_or_default(
        "booking_confirm",
        defaults["booking_confirm"],
    )
    if template_source.strip() == _LEGACY_BOOKING_CONFIRM_TEMPLATE.strip():
        template_source = defaults["booking_confirm"]
    text = render_template_text(
        template_source,
        {
            "name": escape(payload.display_name),
            "date": escape(format_local_day_label(local_dt.date())),
            "time": escape(local_dt.strftime("%H:%M")),
            "service": escape(payload.base_service_name),
            "payment": escape(format_payment_method_label(payload.payment_method)),
            "address": address_inline,
            "address_block": address_block,
        },
    )
    if payload.payment_method and "{payment}" not in template_source:
        text += (
            f"\n\n💳 Оплата: <b>{escape(format_payment_method_label(payload.payment_method))}</b>"
        )
    return ensure_late_policy_notice(text)


async def _build_booking_confirmation_keyboard(
    db_session: AsyncSession,
    *,
    booking_id: int,
) -> object:
    """Build the shared CTA keyboard for a confirmed booking."""
    settings_repository = SettingRepository(db_session)
    button_configs = await load_all_button_configs(settings_repository)
    contact_url = await load_master_contact_url(settings_repository)
    return build_post_booking_cta_keyboard(
        booking_id,
        address_map_url=build_address_map_url(),
        address_copy_text=build_address_copy_text(),
        button_configs=button_configs,
        contact_url=contact_url,
    )


async def send_booking_confirmation_message(
    message: Message,
    *,
    db_session: AsyncSession,
    settings: Settings,
    payload: BookingClientConfirmationPayload,
    replace_current: bool = False,
) -> None:
    """Send the shared booking confirmation into the current client thread."""
    text = await _build_booking_confirmation_text(
        db_session,
        payload=payload,
        settings=settings,
    )
    keyboard = await _build_booking_confirmation_keyboard(
        db_session,
        booking_id=payload.booking_id,
    )
    await send_brand_message(
        message,
        caption=text,
        reply_markup=keyboard,
        replace_current=replace_current,
        template_key="booking_confirm",
        parse_mode=ParseMode.HTML,
    )


async def send_booking_confirmation_bot_message(
    bot,
    *,
    db_session: AsyncSession,
    settings: Settings,
    payload: BookingClientConfirmationPayload,
) -> None:
    """Send the shared booking confirmation as a proactive bot message."""
    text = await _build_booking_confirmation_text(
        db_session,
        payload=payload,
        settings=settings,
    )
    keyboard = await _build_booking_confirmation_keyboard(
        db_session,
        booking_id=payload.booking_id,
    )
    await send_brand_bot_message(
        bot,
        chat_id=payload.chat_id,
        caption=text,
        reply_markup=keyboard,
        template_key="booking_confirm",
        parse_mode=ParseMode.HTML,
    )
