from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.handlers.client.brand import send_brand_message
from src.bot.keyboards.client import build_portfolio_keyboard
from src.config import Settings
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.button_configs import load_all_button_configs
from src.services.template_sanitizer import normalize_template_content

router = Router(name="client_portfolio")


def normalize_portfolio_intro_text(intro_text: str) -> str:
    """Return the canonical portfolio intro for both client and admin surfaces."""
    return normalize_template_content("portfolio_intro", intro_text, texts.PORTFOLIO_INTRO)


def normalize_about_text(about_text: str) -> str:
    """Return the canonical about-master text for both client and admin surfaces."""
    return normalize_template_content(
        "about_master",
        about_text,
        texts.DEFAULT_ABOUT_MASTER_TEMPLATE,
    )


async def build_master_profile_caption(db_session: AsyncSession) -> str:
    """Build the combined «О Ангеле + работы» screen text."""
    template_repository = TemplateRepository(db_session)
    about_text = normalize_about_text(
        await template_repository.get_content_or_default(
            "about_master",
            texts.DEFAULT_ABOUT_MASTER_TEMPLATE,
        )
    ).strip()
    portfolio_intro = normalize_portfolio_intro_text(
        await template_repository.get_content_or_default(
            "portfolio_intro",
            texts.PORTFOLIO_INTRO,
        )
    ).strip()
    return f"{about_text}\n\n{portfolio_intro}".strip()


@router.callback_query(F.data == "client_menu:portfolio")
async def show_portfolio(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Show the portfolio intro and a URL button."""
    await callback.answer()
    if callback.message is None:
        return

    settings_repository = SettingRepository(db_session)
    button_configs = await load_all_button_configs(settings_repository)
    channel_url = await settings_repository.get_value_or_default(
        "portfolio_channel_url",
        settings.portfolio_channel_url,
    )
    caption = await build_master_profile_caption(db_session)

    await send_brand_message(
        callback.message,
        caption=caption,
        reply_markup=build_portfolio_keyboard(
            channel_url,
            button_configs=button_configs,
        ),
        replace_current=True,
        template_key="about_master",
        fallback_title="О АНГЕЛЕ И РАБОТЫ",
        fallback_subtitle="Знакомство с мастером и свежие работы",
    )
