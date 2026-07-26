from __future__ import annotations

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

router = Router(name="client_menu")


def normalize_menu_header_text(header_text: str) -> str:
    """Return the canonical main-menu copy for both live UI and admin previews."""
    return normalize_template_content("greeting_header", header_text, texts.MENU_HEADER)


def personalize_menu_header_text(header_text: str, user: User) -> str:
    """Render the optional client name without inferring anything from visit history."""
    return header_text.replace("{display_name}", user.display_name)


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
    header_text = personalize_menu_header_text(base_header, user)
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
