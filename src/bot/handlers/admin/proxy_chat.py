from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import (
    clear_state_preserving_admin_panel,
    remember_admin_panel,
    send_admin_panel,
)
from src.bot.fsm_utils import clear_state_preserving_admin_mode
from src.bot.handlers.admin.approvals import show_pending_approvals
from src.bot.keyboards.admin import (
    build_admin_decline_custom_confirm_keyboard,
    build_admin_proxy_reply_keyboard,
    build_admin_proxy_reply_prompt_keyboard,
)
from src.bot.keyboards.client import build_back_to_menu_keyboard, build_proxy_reply_keyboard
from src.bot.states import AdminReplying, ClientProxyReply
from src.bot.ui_utils import upsert_inline_panel
from src.db.models import User, utcnow
from src.db.repositories.approvals import ApprovalRequestRepository
from src.db.repositories.rate_limit_events import RateLimitEventRepository
from src.services.anti_abuse import get_anti_abuse_settings, record_rate_event
from src.services.approvals import (
    build_admin_client_reply_prefix,
    build_client_admin_reply_text,
)
from src.services.notifications import (
    send_photo_to_admins,
    send_text_to_admins,
    send_voice_to_admins,
)

router = Router(name="admin_proxy_chat")

QUICK_APPROVAL_REPLIES = {
    "after_19": texts.ADMIN_APPROVAL_QUICK_REPLY_AFTER_19_TEXT,
    "weekdays_busy": texts.ADMIN_APPROVAL_QUICK_REPLY_WEEKDAYS_BUSY_TEXT,
    "two_variants": texts.ADMIN_APPROVAL_QUICK_REPLY_TWO_VARIANTS_TEXT,
}


@router.callback_query(F.data.startswith("approval:reply:"))
async def start_admin_reply(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Switch an admin into reply mode for a specific approval thread."""
    await callback.answer()
    if not is_admin or callback.message is None or callback.data is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    approval = await ApprovalRequestRepository(db_session).get_by_id(approval_id)
    if approval is None:
        await upsert_inline_panel(
            callback.bot,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    await state.set_state(AdminReplying.input_message)
    await state.update_data(admin_action="reply", approval_id=approval_id)
    panel = await upsert_inline_panel(
        callback.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=texts.ADMIN_APPROVAL_REPLY_PROMPT_TEXT,
        reply_markup=build_admin_proxy_reply_prompt_keyboard(approval_id),
    )
    await remember_admin_panel(state, panel)


@router.callback_query(F.data.startswith("approval:quick_reply:"))
async def send_admin_quick_reply(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings,
) -> None:
    """Send one canned reply from the approval card without opening text mode."""
    await callback.answer()
    if not is_admin or callback.data is None:
        return

    _, _, approval_id_str, quick_reply_key = callback.data.split(":", 3)
    reply_text = QUICK_APPROVAL_REPLIES.get(quick_reply_key)
    if reply_text is None:
        return

    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(int(approval_id_str))
    if approval is None:
        return

    await callback.bot.send_message(
        chat_id=approval.client.tg_id,
        text=build_client_admin_reply_text(reply_text),
        reply_markup=build_proxy_reply_keyboard(approval.id),
    )
    approval.admin_response_text = reply_text
    await db_session.commit()

    if callback.message is not None:
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await show_pending_approvals(
            callback.message,
            db_session=db_session,
            is_admin=True,
            settings=settings,
            state=state,
            edit=True,
            notice_text=texts.ADMIN_APPROVAL_REPLY_SENT_TEXT,
        )


@router.callback_query(F.data.startswith("proxy:reply:"))
async def start_client_proxy_reply(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Switch a client into reply mode for an active proxy-chat thread."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    await clear_state_preserving_admin_mode(state)
    await state.set_state(ClientProxyReply.input_message)
    await state.update_data(proxy_approval_id=approval_id)
    await callback.message.answer(
        texts.PROXY_REPLY_PROMPT_TEXT,
        reply_markup=build_back_to_menu_keyboard(),
    )


@router.message(StateFilter(AdminReplying.input_message), F.text)
@router.message(StateFilter(AdminReplying.input_message), F.photo)
@router.message(StateFilter(AdminReplying.input_message), F.voice)
async def submit_admin_reply(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings,
) -> None:
    """Send an admin reply or a custom decline reason for an approval thread."""
    if not is_admin:
        return

    data = await state.get_data()
    approval_id = data.get("approval_id")
    if approval_id is None:
        await state.clear()
        return

    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(int(approval_id))
    if approval is None:
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await show_pending_approvals(
            message,
            db_session=db_session,
            is_admin=True,
            settings=settings,
            state=state,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    if data.get("admin_action") == "decline":
        reason = (message.text or "").strip()
        if not reason:
            await message.answer(texts.ADMIN_APPROVAL_DECLINE_PROMPT_TEXT)
            return

        await state.update_data(decline_pending_reason=reason)
        await send_admin_panel(
            message,
            state=state,
            text=texts.ADMIN_APPROVAL_DECLINE_CONFIRM_TEXT.format(reason=reason),
            reply_markup=build_admin_decline_custom_confirm_keyboard(approval.id),
        )
        return

    reply_markup = build_proxy_reply_keyboard(approval.id)
    response_text = (message.text or "").strip()
    if message.photo:
        response_text = (message.caption or "").strip() or "(фото)"
        caption = build_client_admin_reply_text(response_text)
        await message.bot.send_photo(
            chat_id=approval.client.tg_id,
            photo=message.photo[-1].file_id,
            caption=caption,
            reply_markup=reply_markup,
        )
    elif message.voice:
        response_text = (message.caption or "").strip() or "(голосовое)"
        caption = build_client_admin_reply_text(response_text)
        await message.bot.send_voice(
            chat_id=approval.client.tg_id,
            voice=message.voice.file_id,
            caption=caption,
            reply_markup=reply_markup,
        )
    else:
        await message.bot.send_message(
            chat_id=approval.client.tg_id,
            text=build_client_admin_reply_text(response_text),
            reply_markup=reply_markup,
        )

    approval.admin_response_text = response_text
    await db_session.commit()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await show_pending_approvals(
        message,
        db_session=db_session,
        is_admin=True,
        settings=settings,
        state=state,
        notice_text=texts.ADMIN_APPROVAL_REPLY_SENT_TEXT,
    )


@router.message(StateFilter(ClientProxyReply.input_message), F.text)
@router.message(StateFilter(ClientProxyReply.input_message), F.photo)
@router.message(StateFilter(ClientProxyReply.input_message), F.voice)
async def submit_client_proxy_reply(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings,
) -> None:
    """Forward a client reply back to admins in the proxy-chat thread."""
    data = await state.get_data()
    approval_id = data.get("proxy_approval_id")
    if approval_id is None:
        await clear_state_preserving_admin_mode(state)
        return

    approval = await ApprovalRequestRepository(db_session).get_by_id(int(approval_id))
    if approval is None:
        await clear_state_preserving_admin_mode(state)
        await message.answer(
            texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
            reply_markup=build_back_to_menu_keyboard(),
        )
        return

    anti_abuse_settings = await get_anti_abuse_settings(db_session)
    current_time = utcnow()
    events = RateLimitEventRepository(db_session)
    is_blocked = (
        await events.count_since(
            user_id=user.id,
            kind="proxy_message",
            since=current_time - timedelta(hours=1),
        )
        >= anti_abuse_settings["proxy_messages_per_hour"]
    )

    prefix = build_admin_client_reply_prefix(user)
    reply_markup = build_admin_proxy_reply_keyboard(approval.id)
    if not is_blocked:
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

    await record_rate_event(
        db_session,
        user_id=user.id,
        kind="proxy_message",
        metadata={"blocked": is_blocked, "approval_id": approval.id},
        created_at=current_time,
    )
    await db_session.commit()

    await clear_state_preserving_admin_mode(state)
    await message.answer(
        texts.PROXY_MESSAGE_LIMIT_TEXT if is_blocked else texts.PROXY_REPLY_SENT_TEXT,
        reply_markup=build_back_to_menu_keyboard(),
    )
