from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.fsm_utils import clear_state_preserving_admin_mode
from src.bot.handlers.admin.approvals import send_approval_card_to_admins
from src.bot.handlers.client.booking_flow import show_base_service_step
from src.bot.keyboards.client import (
    build_back_to_menu_keyboard,
    build_design_photo_actions_keyboard,
)
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.models import ApprovalRequestKind, User
from src.db.repositories.approvals import ApprovalRequestRepository
from src.db.repositories.settings import SettingRepository
from src.services.button_configs import load_all_button_configs

router = Router(name="client_design_photo")


@router.message(StateFilter(None), F.photo)
async def outside_flow_design_photo(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Handle a design photo sent outside the booking flow."""
    state_data = await state.get_data()
    if is_admin and not state_data.get("admin_as_client"):
        return
    if message.media_group_id and not message.caption:
        # DECISION: for media groups we react only once on the first/captioned item
        # to avoid sending multiple identical prompts in Telegram.
        return

    button_configs = await load_all_button_configs(SettingRepository(db_session))
    await state.update_data(
        design_photos=[message.photo[-1].file_id],
        design_comment=(message.caption or "").strip() or None,
    )
    await message.answer(
        texts.DESIGN_PHOTO_OUTSIDE_FLOW_TEXT,
        reply_markup=build_design_photo_actions_keyboard(button_configs=button_configs),
    )


@router.callback_query(F.data == "design_photo:book")
async def book_with_outside_photo(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Start the booking flow with the outside photo prefilled."""
    await callback.answer()
    if callback.message is None:
        return

    await show_base_service_step(
        callback.message,
        db_session=db_session,
        state=state,
        replace=True,
    )


@router.callback_query(F.data == "design_photo:send")
async def send_outside_photo_to_master(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Create a question approval request from a photo sent outside the flow."""
    await callback.answer()
    if callback.message is None:
        return

    data = await state.get_data()
    design_photos = list(data.get("design_photos", []))
    requested_text = data.get("design_comment") or "(фото)"

    repository = ApprovalRequestRepository(db_session)
    approval, approval_created = await repository.create_or_reuse_pending(
        client_id=user.id,
        requested_text=requested_text,
        kind=ApprovalRequestKind.QUESTION,
        design_photos=design_photos,
    )
    await db_session.commit()
    loaded_approval = await repository.get_by_id(approval.id)
    if loaded_approval is not None and approval_created:
        await send_approval_card_to_admins(
            bot=callback.bot,
            settings=settings,
            db_session=db_session,
            approval=loaded_approval,
        )

    await clear_state_preserving_admin_mode(state)
    button_configs = await load_all_button_configs(SettingRepository(db_session))
    await replace_inline_message_text(
        callback.message,
        texts.ASK_MASTER_SENT_TEXT,
        reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
    )


@router.callback_query(F.data == "design_photo:cancel")
async def cancel_outside_photo(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Dismiss the outside-photo prompt."""
    await callback.answer()
    if callback.message is None:
        return

    await clear_state_preserving_admin_mode(state)
    button_configs = await load_all_button_configs(SettingRepository(db_session))
    await replace_inline_message_text(
        callback.message,
        texts.DESIGN_PHOTO_CANCELLED_TEXT,
        reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
    )
