from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.handlers.client.brand import send_template_message
from src.bot.keyboards.client import build_back_to_menu_keyboard, build_services_actions_keyboard
from src.bot.ui_utils import replace_inline_message_panel
from src.db.models import ServiceKind
from src.db.repositories.services import ServiceRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.admin_defaults import required_template_defaults
from src.services.button_configs import load_all_button_configs

router = Router(name="client_services_list")


@router.callback_query(F.data == "client_menu:services")
async def show_services(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
) -> None:
    """Show active services and prices."""
    await callback.answer()
    if callback.message is None:
        return

    repository = ServiceRepository(db_session)
    button_configs = await load_all_button_configs(SettingRepository(db_session))
    base_services = await repository.list_active(kind=ServiceKind.BASE)
    addon_services = await repository.list_active(kind=ServiceKind.ADDON)

    if not base_services and not addon_services:
        await replace_inline_message_panel(
            callback.message,
            text=texts.NO_ACTIVE_SERVICES_TEXT,
            reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
        )
        return

    defaults = required_template_defaults()
    template_repository = TemplateRepository(db_session)
    price_text = await template_repository.get_content_or_default(
        "price",
        defaults["price"],
    )
    await send_template_message(
        callback.message,
        template_key="price",
        caption=price_text.strip() or defaults["price"],
        reply_markup=build_services_actions_keyboard(button_configs=button_configs),
        replace_current=True,
    )
