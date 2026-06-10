from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.handlers.client.brand import send_brand_bot_message
from src.bot.keyboards.admin import build_admin_rescue_slot_keyboard
from src.bot.keyboards.client import build_rescue_offer_keyboard
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.repositories.slots import SlotRepository
from src.services.notifications import send_text_to_admins
from src.services.rescue_slots import (
    build_admin_rescue_slot_prompt_text,
    build_admin_rescue_slot_sent_text,
    build_client_rescue_offer_text,
    load_rescue_offer_candidates,
    slot_is_rescuable,
)

router = Router(name="admin_rescue_slots")
logger = logging.getLogger(__name__)


async def send_rescue_slot_prompt_to_admins(
    bot,
    *,
    db_session: AsyncSession,
    settings: Settings,
    slot_id: int,
    exclude_user_id: int | None = None,
    client_id: int | None = None,
) -> None:
    """Notify admins that a freshly freed slot can be offered to loyal clients."""
    slot = await SlotRepository(db_session).get_by_id(slot_id)
    if slot is None or not slot_is_rescuable(slot):
        return
    await send_text_to_admins(
        bot,
        admin_tg_ids=settings.admin_tg_id_set,
        text=build_admin_rescue_slot_prompt_text(slot, settings=settings),
        reply_markup=build_admin_rescue_slot_keyboard(
            slot.id,
            exclude_user_id=exclude_user_id,
            user_id=client_id,
        ),
    )


@router.callback_query(F.data.startswith("rescue_slot:send:"))
async def send_rescue_slot_offer(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Send a quick free-slot offer to a small set of loyal clients."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.data is None or callback.message is None:
        return

    _, _, slot_id_str, exclude_user_id_str = callback.data.split(":", 3)
    slot = await SlotRepository(db_session).get_by_id(int(slot_id_str))
    if slot is None or not slot_is_rescuable(slot):
        await replace_inline_message_text(callback.message, texts.ADMIN_RESCUE_SLOT_UNAVAILABLE_TEXT)
        return

    exclude_user_id = int(exclude_user_id_str)
    exclude_ids = {exclude_user_id} if exclude_user_id > 0 else set()
    candidates = await load_rescue_offer_candidates(
        db_session,
        settings=settings,
        exclude_user_ids=exclude_ids,
    )
    if not candidates:
        await replace_inline_message_text(callback.message, texts.ADMIN_RESCUE_SLOT_NONE_TEXT)
        return

    sent_count = 0
    offer_text = build_client_rescue_offer_text(slot, settings=settings)
    for user in candidates:
        try:
            await send_brand_bot_message(
                callback.bot,
                chat_id=user.tg_id,
                caption=offer_text,
                reply_markup=build_rescue_offer_keyboard(slot.id),
            )
            sent_count += 1
        except Exception:
            logger.exception("Failed to send rescue-slot offer to user %s", user.id)

    if sent_count <= 0:
        await replace_inline_message_text(callback.message, texts.ADMIN_RESCUE_SLOT_NONE_TEXT)
        return

    await replace_inline_message_text(
        callback.message,
        build_admin_rescue_slot_sent_text(slot, settings=settings, sent_count=sent_count),
    )
