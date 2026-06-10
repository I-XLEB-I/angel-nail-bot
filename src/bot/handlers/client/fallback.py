"""Catch-all handler for unrecognised client messages.

Registered LAST in the dispatcher chain so all proper FSM/command/callback
handlers get the first crack at every message. Fires only when the user is
NOT in any FSM state and is in client mode — a tame «I didn't catch that»
reply with menu / proxy / book buttons, instead of the bot staying silent.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.keyboards.client import build_client_fallback_keyboard
from src.db.repositories.settings import SettingRepository
from src.services.button_configs import ANGELA_CHAT_URL, load_all_button_configs, load_master_contact_url

router = Router(name="client_fallback")


@router.message(StateFilter(None), F.text)
async def fallback_text(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Respond warmly when a client types something the bot doesn't recognise.

    Skips:
    - admins in admin mode (they have their own menu / flows; admin in client
      mode via /menu still gets the fallback so they can test the path),
    - empty / non-text messages (other handlers cover photos, voice, etc.),
    - users currently inside an FSM state (handled by `StateFilter(None)`).
    """
    state_data = await state.get_data()
    if is_admin and not state_data.get("admin_as_client"):
        return
    settings_repository = SettingRepository(db_session)
    button_configs = await load_all_button_configs(settings_repository)
    contact_url = (
        await load_master_contact_url(settings_repository)
        if db_session is not None
        else ANGELA_CHAT_URL
    )

    await message.answer(
        texts.CLIENT_FALLBACK_TEXT,
        reply_markup=build_client_fallback_keyboard(
            button_configs=button_configs,
            contact_url=contact_url,
        ),
    )
