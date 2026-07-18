from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.handlers.client.brand import send_brand_message
from src.bot.keyboards.client import build_vitrine_actions_keyboard
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.button_configs import DEFAULT_ADDRESS_MAP_URL, load_all_button_configs
from src.services.studio_address import (
    DEFAULT_STUDIO_ADDRESS_COPY_TEXT,
    load_studio_address_copy_text,
)

router = Router(name="client_address")
ADDRESS_COPY_TEXT = DEFAULT_STUDIO_ADDRESS_COPY_TEXT
ADDRESS_MAP_URL = DEFAULT_ADDRESS_MAP_URL


async def build_public_address_text(db_session: AsyncSession) -> str:
    """Return the public address text used before booking is confirmed."""
    repository = TemplateRepository(db_session)
    return await repository.get_content_or_default(
        "navigation_public",
        texts.DEFAULT_ADDRESS_PUBLIC_TEMPLATE,
    )


async def build_address_text(db_session: AsyncSession) -> str:
    """Return the private post-booking address text with detailed navigation."""
    repository = TemplateRepository(db_session)
    return await repository.get_content_or_default(
        "address_post_confirm",
        texts.DEFAULT_ADDRESS_POST_CONFIRM,
    )


def build_address_copy_text() -> str:
    """Return the default short address kept for backwards compatibility."""
    return ADDRESS_COPY_TEXT


def build_address_map_url() -> str:
    """Return the canonical map URL for route buttons and address links."""
    return ADDRESS_MAP_URL


@router.callback_query(F.data == "client_menu:address")
async def show_address(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
) -> None:
    """Show the address and navigation text."""
    await callback.answer()
    if callback.message is None:
        return

    settings_repository = SettingRepository(db_session)
    button_configs = await load_all_button_configs(settings_repository)
    address_text = await build_public_address_text(db_session)
    address_copy_text = await load_studio_address_copy_text(settings_repository)
    await send_brand_message(
        callback.message,
        caption=address_text,
        reply_markup=build_vitrine_actions_keyboard(
            address_map_url=build_address_map_url(),
            address_copy_text=address_copy_text,
            button_configs=button_configs,
        ),
        replace_current=True,
        template_key="navigation_public",
        fallback_title="АДРЕС",
        fallback_subtitle="Как добраться до студии",
        parse_mode=ParseMode.HTML,
    )
