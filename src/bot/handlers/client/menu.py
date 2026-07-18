from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.fsm_utils import clear_state_preserving_admin_mode
from src.bot.handlers.client.brand import send_template_message
from src.bot.keyboards.client import build_client_main_menu
from src.db.models import User
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.button_configs import (
    load_client_main_menu_button_configs,
    load_master_contact_url,
)
from src.services.template_sanitizer import normalize_template_content

_LAPSED_DAYS = 60

router = Router(name="client_menu")


def normalize_menu_header_text(header_text: str) -> str:
    """Return the canonical main-menu copy for both live UI and admin previews."""
    return normalize_template_content("greeting_header", header_text, texts.MENU_HEADER)


async def _build_greeting(
    user: User,
    *,
    booking_repository: BookingRepository,
    base_header: str,
) -> str:
    """Prepend a lapsed-client greeting addon when the user hasn't visited in 60+ days."""
    last_slot_at = await booking_repository.get_last_completed_slot_at(user.id)
    if last_slot_at is not None:
        if last_slot_at.tzinfo is None:
            last_slot_at = last_slot_at.replace(tzinfo=UTC)
        days_ago = (datetime.now(UTC) - last_slot_at).days
        if days_ago >= _LAPSED_DAYS:
            addon = texts.GREETING_LAPSED_ADDON.format(display_name=user.display_name)
            return addon + base_header
    return base_header


async def show_client_menu(
    message: Message,
    *,
    db_session: AsyncSession,
    user: User,
    replace_current: bool = False,
) -> None:
    """Show the main client menu."""
    booking_repository = BookingRepository(db_session)
    settings_repository = SettingRepository(db_session)
    template_repository = TemplateRepository(db_session)

    base_header = await template_repository.get_content_or_default(
        "greeting_header",
        texts.MENU_HEADER,
    )
    base_header = normalize_menu_header_text(base_header)
    header_text = await _build_greeting(
        user, booking_repository=booking_repository, base_header=base_header
    )
    button_configs = await load_client_main_menu_button_configs(settings_repository)
    contact_url = await load_master_contact_url(settings_repository)
    reply_markup = build_client_main_menu(
        show_my_bookings=await booking_repository.has_visible_bookings(user.id),
        button_configs=button_configs,
        contact_url=contact_url,
    )

    await send_template_message(
        message,
        template_key="greeting_header",
        caption=header_text,
        reply_markup=reply_markup,
        replace_current=replace_current,
    )


@router.callback_query(F.data == "client_menu:back")
async def back_to_menu(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
) -> None:
    """Return the client to the main menu."""
    await callback.answer()
    await clear_state_preserving_admin_mode(state)
    if callback.message is not None:
        await show_client_menu(
            callback.message,
            db_session=db_session,
            user=user,
            replace_current=True,
        )
