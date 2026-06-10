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
from src.bot.keyboards.admin import build_admin_proxy_reply_keyboard
from src.bot.keyboards.client import build_back_to_menu_keyboard
from src.bot.states import AskingMaster, PostvisitFeedback
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.models import ApprovalRequestKind, User, utcnow
from src.db.repositories.approvals import ApprovalRequestRepository
from src.db.repositories.rate_limit_events import RateLimitEventRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.anti_abuse import get_anti_abuse_settings, record_rate_event
from src.services.approvals import build_admin_client_reply_prefix
from src.services.button_configs import load_all_button_configs
from src.services.notifications import (
    send_photo_to_admins,
    send_text_to_admins,
    send_voice_to_admins,
)

router = Router(name="client_postvisit")


def _normalize_template_blob(content: str, *, key: str, default: str) -> str:
    stripped = content.strip()
    if stripped == key:
        return default
    if stripped.startswith(key):
        cleaned = stripped.removeprefix(key).strip()
        return cleaned or default
    return content


async def _load_template(db_session: AsyncSession, *, key: str, default: str) -> str:
    repository = TemplateRepository(db_session)
    content = await repository.get_content_or_default(key, default)
    return _normalize_template_blob(content, key=key, default=default)


def _build_postvisit_initial_request_text(score: int) -> str:
    """Render the first admin-facing post-visit signal created on rating click."""
    if score in (1, 2):
        return f"Низкая оценка: {score}⭐ (без комментария)"
    return f"Обратная связь после визита: {score}⭐ (без комментария)"


def _build_postvisit_followup_prefix(score: int | None) -> str:
    """Render the label used for follow-up comments after the initial rating."""
    if isinstance(score, int):
        return f"💬 Комментарий к оценке {score}⭐"
    return "💬 Комментарий к отзыву"


async def _create_postvisit_approval(
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    score: int,
    booking_id: int | None,
    bot,
) -> int:
    """Create and immediately fan out the first post-visit approval request."""
    repository = ApprovalRequestRepository(db_session)
    approval, approval_created = await repository.create_or_reuse_pending(
        client_id=user.id,
        requested_text=_build_postvisit_initial_request_text(score),
        kind=ApprovalRequestKind.QUESTION,
        related_booking_id=booking_id,
    )
    await db_session.commit()

    loaded_approval = await repository.get_by_id(approval.id)
    if loaded_approval is not None and approval_created:
        await send_approval_card_to_admins(
            bot=bot,
            settings=settings,
            db_session=db_session,
            approval=loaded_approval,
        )
    return approval.id


async def _forward_postvisit_followup_to_admins(
    *,
    message: Message,
    user: User,
    settings: Settings,
    approval_id: int,
    score: int | None,
) -> None:
    """Append a follow-up comment to an already created post-visit approval thread."""
    prefix = f"{build_admin_client_reply_prefix(user)}\n\n{_build_postvisit_followup_prefix(score)}"
    reply_markup = build_admin_proxy_reply_keyboard(approval_id)

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
        return

    if message.voice:
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
        return

    body = f"{prefix}\n\n{message.text or ''}".strip()
    await send_text_to_admins(
        message.bot,
        admin_tg_ids=settings.admin_tg_id_set,
        text=body,
        reply_markup=reply_markup,
    )


@router.callback_query(F.data.startswith("postvisit:rate:"))
async def rate_postvisit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Handle a post-visit star rating with a 3-tier branch.

    Callback format: ``postvisit:rate:{booking_id}:{score}`` where score is 1..5.
    Older callbacks ``postvisit:rate:{booking_id}`` (no score) fall through to the
    legacy thank-you text so existing in-flight messages keep working.
    """
    await callback.answer(texts.POSTVISIT_RATE_ACK_NOTICE_TEXT)
    if callback.data is None:
        return

    parts = callback.data.split(":")
    score: int | None = None
    booking_id: int | None = None
    if len(parts) >= 4:
        try:
            booking_id = int(parts[2])
            score = int(parts[3])
        except ValueError:
            score = None
    elif len(parts) == 3:
        try:
            booking_id = int(parts[2])
        except ValueError:
            booking_id = None

    if callback.message is None or score is None:
        if callback.message is not None:
            await replace_inline_message_text(callback.message, texts.POSTVISIT_THANK_YOU_TEXT)
        return

    if score == 5:
        text = await _load_template(
            db_session,
            key="postvisit_rating_5",
            default=texts.DEFAULT_POSTVISIT_RATING_5_TEMPLATE,
        )
        await replace_inline_message_text(callback.message, text)
        return

    if score in (3, 4):
        approval_id = await _create_postvisit_approval(
            db_session=db_session,
            user=user,
            settings=settings,
            score=score,
            booking_id=booking_id,
            bot=callback.bot,
        )
        text = await _load_template(
            db_session,
            key="postvisit_rating_mid",
            default=texts.DEFAULT_POSTVISIT_RATING_MID_TEMPLATE,
        )
        await replace_inline_message_text(callback.message, text)
        await clear_state_preserving_admin_mode(state)
        await state.set_state(PostvisitFeedback.input_text)
        await state.update_data(
            postvisit_booking_id=booking_id,
            postvisit_score=score,
            postvisit_feedback_approval_id=approval_id,
        )
        return

    # 1–2 stars: warm message + drop straight into ask-master flow.
    approval_id = await _create_postvisit_approval(
        db_session=db_session,
        user=user,
        settings=settings,
        score=score,
        booking_id=booking_id,
        bot=callback.bot,
    )
    text = await _load_template(
        db_session,
        key="postvisit_rating_low",
        default=texts.DEFAULT_POSTVISIT_RATING_LOW_TEMPLATE,
    )
    await replace_inline_message_text(callback.message, text)
    await clear_state_preserving_admin_mode(state)
    await state.set_state(AskingMaster.input_message)
    await state.update_data(
        postvisit_booking_id=booking_id,
        postvisit_score=score,
        postvisit_feedback_approval_id=approval_id,
    )


@router.message(StateFilter(PostvisitFeedback.input_text), F.text)
@router.message(StateFilter(PostvisitFeedback.input_text), F.photo)
@router.message(StateFilter(PostvisitFeedback.input_text), F.voice)
async def submit_postvisit_feedback(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Forward 3-4⭐ feedback to admins via an approval card."""
    data = await state.get_data()
    score = data.get("postvisit_score")
    followup_approval_id = data.get("postvisit_feedback_approval_id")
    if followup_approval_id is not None:
        approval = await ApprovalRequestRepository(db_session).get_by_id(int(followup_approval_id))
        if approval is not None:
            await _forward_postvisit_followup_to_admins(
                message=message,
                user=user,
                settings=settings,
                approval_id=approval.id,
                score=score if isinstance(score, int) else None,
            )
            await clear_state_preserving_admin_mode(state)
            button_configs = await load_all_button_configs(SettingRepository(db_session))
            await message.answer(
                texts.POSTVISIT_FEEDBACK_THANK_YOU_TEXT,
                reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
            )
            return

    requested_text = (message.text or message.caption or "").strip()
    prefix_parts = ["Обратная связь после визита"]
    if isinstance(score, int):
        prefix_parts.append(f"оценка {score}⭐")
    prefix = " · ".join(prefix_parts)

    if message.photo:
        body = requested_text or "(фото)"
        requested_text = f"[{prefix}] {body}"
        design_photos = [message.photo[-1].file_id]
    elif message.voice:
        body = requested_text or "(голосовое)"
        requested_text = f"[{prefix}] {body}"
        design_photos = []
    else:
        requested_text = f"[{prefix}] {requested_text or '—'}"
        design_photos = []

    current_time = utcnow()
    anti_abuse_settings = await get_anti_abuse_settings(db_session)
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
            "source": "postvisit_feedback",
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

    await clear_state_preserving_admin_mode(state)
    button_configs = await load_all_button_configs(SettingRepository(db_session))
    await message.answer(
        texts.POSTVISIT_FEEDBACK_THANK_YOU_TEXT,
        reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
    )
