from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.fsm_utils import clear_state_preserving_admin_mode
from src.bot.handlers.admin.approvals import send_approval_card_to_admins
from src.bot.handlers.client.brand import send_brand_message
from src.bot.keyboards.admin import build_admin_proxy_reply_keyboard
from src.bot.keyboards.client import build_back_to_menu_keyboard
from src.bot.states import AskingMaster
from src.config import Settings
from src.db.models import ApprovalRequestKind, User, utcnow
from src.db.repositories.approvals import ApprovalRequestRepository
from src.db.repositories.rate_limit_events import RateLimitEventRepository
from src.db.repositories.settings import SettingRepository
from src.services.anti_abuse import get_anti_abuse_settings, record_rate_event
from src.services.approvals import build_admin_client_reply_prefix
from src.services.button_configs import load_all_button_configs
from src.services.notifications import (
    send_photo_to_admins,
    send_text_to_admins,
    send_voice_to_admins,
)

router = Router(name="client_ask_master")


@router.callback_query(F.data == "client_menu:ask_master")
async def ask_master_entry(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Open the free-form question flow to the master."""
    await callback.answer()
    if callback.message is None:
        return

    await clear_state_preserving_admin_mode(state)
    await state.set_state(AskingMaster.input_message)
    button_configs = await load_all_button_configs(SettingRepository(db_session))
    await send_brand_message(
        callback.message,
        caption=texts.ASK_MASTER_PROMPT_TEXT,
        reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
        replace_current=True,
        fallback_title="ВОПРОС",
        fallback_subtitle="Можно отправить текст, фото или голосовое",
    )


@router.message(StateFilter(AskingMaster.input_message), F.text)
@router.message(StateFilter(AskingMaster.input_message), F.photo)
@router.message(StateFilter(AskingMaster.input_message), F.voice)
async def submit_question_to_master(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Create a question approval request and notify admins."""
    state_data = await state.get_data()
    followup_approval_id = state_data.get("postvisit_feedback_approval_id")
    if followup_approval_id is not None:
        approval = await ApprovalRequestRepository(db_session).get_by_id(int(followup_approval_id))
        if approval is not None:
            prefix = f"{build_admin_client_reply_prefix(user)}\n\n💬 Комментарий к оценке"
            reply_markup = build_admin_proxy_reply_keyboard(approval.id)
            if message.photo:
                caption = prefix
                if message.caption:
                    caption = f"{caption}\n\n{message.caption}"
                await send_photo_to_admins(
                    message.bot,
                    admin_tg_ids=settings.admin_tg_id_set,
                    photo=message.photo[-1].file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                )
            elif message.voice:
                caption = prefix
                if message.caption:
                    caption = f"{caption}\n\n{message.caption}"
                await send_voice_to_admins(
                    message.bot,
                    admin_tg_ids=settings.admin_tg_id_set,
                    voice=message.voice.file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                )
            else:
                body = f"{prefix}\n\n{message.text or ''}".strip()
                await send_text_to_admins(
                    message.bot,
                    admin_tg_ids=settings.admin_tg_id_set,
                    text=body,
                    reply_markup=reply_markup,
                )

            await clear_state_preserving_admin_mode(state)
            button_configs = await load_all_button_configs(SettingRepository(db_session))
            await message.answer(
                texts.POSTVISIT_FEEDBACK_THANK_YOU_TEXT,
                reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
            )
            return

    anti_abuse_settings = await get_anti_abuse_settings(db_session)
    requested_text = (message.text or "").strip()
    design_photos: list[str] = []

    if message.photo:
        requested_text = (message.caption or "").strip() or "(фото)"
        design_photos = [message.photo[-1].file_id]
    elif message.voice:
        requested_text = (message.caption or "").strip()
        if requested_text:
            requested_text = f"{requested_text} (голосовое)"
        else:
            requested_text = "(голосовое)"

    current_time = utcnow()
    events = RateLimitEventRepository(db_session)
    is_blocked = (
        await events.count_since(
            user_id=user.id,
            kind="ask_master",
            since=current_time - timedelta(days=1),
        )
        >= anti_abuse_settings["ask_master_per_day"]
    )

    approval = None
    approval_created = False
    if not is_blocked:
        repository = ApprovalRequestRepository(db_session)
        approval, approval_created = await repository.create_or_reuse_pending(
            client_id=user.id,
            requested_text=requested_text,
            kind=ApprovalRequestKind.QUESTION,
            design_photos=design_photos,
        )

    await record_rate_event(
        db_session,
        user_id=user.id,
        kind="ask_master",
        metadata={
            "blocked": is_blocked,
            "approval_id": approval.id if approval is not None else None,
        },
        created_at=current_time,
    )
    await db_session.commit()

    if approval is not None and approval_created:
        loaded_approval = await ApprovalRequestRepository(db_session).get_by_id(approval.id)
        if loaded_approval is not None:
            await send_approval_card_to_admins(
                bot=message.bot,
                settings=settings,
                db_session=db_session,
                approval=loaded_approval,
            )

        if message.voice:
            await send_voice_to_admins(
                message.bot,
                admin_tg_ids=settings.admin_tg_id_set,
                voice=message.voice.file_id,
            )

    await clear_state_preserving_admin_mode(state)
    button_configs = await load_all_button_configs(SettingRepository(db_session))
    await message.answer(
        texts.ASK_MASTER_LIMIT_TEXT if is_blocked else texts.ASK_MASTER_SENT_TEXT,
        reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
    )
