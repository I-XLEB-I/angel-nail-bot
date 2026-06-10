"""Client-side handlers for accepting or declining a time-slot offer from the master."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.handlers.admin.approvals import finalize_approval_with_slot
from src.bot.handlers.client.booking_confirmation import send_booking_confirmation_message
from src.bot.keyboards.client import build_back_to_menu_keyboard
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.models import ApprovalRequestKind, ApprovalRequestStatus, User
from src.db.repositories.approvals import ApprovalRequestRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.slots import SlotRepository
from src.services.booking import format_local_datetime
from src.services.button_configs import load_all_button_configs
from src.services.notifications import send_text_to_admins

logger = logging.getLogger(__name__)

router = Router(name="client_offer_confirm")


async def _replace_offer_result_message(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    text: str,
) -> None:
    """Replace the current offer card with a final status message."""
    if callback.message is None:
        return
    button_configs = await load_all_button_configs(SettingRepository(db_session))
    await replace_inline_message_text(
        callback.message,
        text,
        reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
    )


async def reset_offered_request_to_pending(
    *,
    db_session: AsyncSession,
    approval,
) -> None:
    """Return an offered approval back to the pending queue."""
    approval.status = ApprovalRequestStatus.PENDING
    approval.offered_slot_id = None
    approval.offered_start_at = None
    approval.resolved_at = None
    await db_session.commit()


@router.callback_query(F.data.startswith("approval:accept_offer:"))
async def accept_time_offer(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Client confirms the offered time slot — create the booking."""
    await callback.answer(texts.APPROVAL_OFFER_ACCEPT_TOAST)
    if callback.message is None or callback.data is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)

    if (
        approval is None
        or approval.status != ApprovalRequestStatus.OFFERED
        or approval.client_id != user.id
        or (
            approval.offered_slot_id is None
            and approval.offered_start_at is None
        )
    ):
        await _replace_offer_result_message(
            callback,
            db_session=db_session,
            text=texts.APPROVAL_OFFER_EXPIRED_TEXT,
        )
        return

    slot_repository = SlotRepository(db_session)
    slot = None
    if approval.offered_slot_id is not None:
        slot = await slot_repository.get_by_id(approval.offered_slot_id)
    elif approval.offered_start_at is not None:
        slot, _ = await slot_repository.create_if_missing(approval.offered_start_at)
        await db_session.commit()
    if slot is None:
        await reset_offered_request_to_pending(db_session=db_session, approval=approval)
        await _replace_offer_result_message(
            callback,
            db_session=db_session,
            text=texts.APPROVAL_OFFER_EXPIRED_TEXT,
        )
        try:
            await send_text_to_admins(
                    callback.bot,
                    admin_tg_ids=settings.admin_tg_id_set,
                    text=(
                        texts.APPROVAL_REPAIR_OFFER_DECLINED_ADMIN_TEXT
                        if approval.kind == ApprovalRequestKind.REPAIR_REQUEST
                        else texts.APPROVAL_OFFER_DECLINED_ADMIN_TEXT
                    ),
                )
        except Exception:
            logger.exception("Failed to notify admins about expired offer %s", approval_id)
        return

    result = await finalize_approval_with_slot(
        approval=approval,
        slot_id=slot.id,
        db_session=db_session,
        settings=settings,
    )
    if not result.ok:
        if result.reason == "slot_unavailable":
            await reset_offered_request_to_pending(db_session=db_session, approval=approval)
            await _replace_offer_result_message(
                callback,
                db_session=db_session,
                text=texts.APPROVAL_OFFER_EXPIRED_TEXT,
            )
            try:
                await send_text_to_admins(
                    callback.bot,
                    admin_tg_ids=settings.admin_tg_id_set,
                    text=(
                        texts.APPROVAL_REPAIR_OFFER_DECLINED_ADMIN_TEXT
                        if approval.kind == ApprovalRequestKind.REPAIR_REQUEST
                        else texts.APPROVAL_OFFER_DECLINED_ADMIN_TEXT
                    ),
                )
            except Exception:
                logger.exception("Failed to notify admins about slot conflict %s", approval_id)
            return
        await _replace_offer_result_message(
            callback,
            db_session=db_session,
            text=texts.APPROVAL_OFFER_EXPIRED_TEXT,
        )
        return

    if result.client_confirmation is not None:
        await send_booking_confirmation_message(
            callback.message,
            db_session=db_session,
            settings=settings,
            payload=result.client_confirmation,
            replace_current=True,
        )

    if result.start_at is None:
        return
    local_dt = format_local_datetime(result.start_at, settings.tz)
    try:
        await send_text_to_admins(
            callback.bot,
            admin_tg_ids=settings.admin_tg_id_set,
            text=(
                texts.APPROVAL_REPAIR_OFFER_ACCEPTED_ADMIN_TEXT
                if approval.kind == ApprovalRequestKind.REPAIR_REQUEST
                else texts.APPROVAL_OFFER_ACCEPTED_ADMIN_TEXT
            ).format(
                date=local_dt.strftime("%d.%m.%Y"),
                time=local_dt.strftime("%H:%M"),
            ),
        )
    except Exception:
        logger.exception("Failed to notify admins about accepted offer %s", approval_id)


@router.callback_query(F.data.startswith("approval:decline_offer:"))
async def decline_time_offer(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Client declines the offered time — reset approval to PENDING."""
    await callback.answer(texts.APPROVAL_OFFER_DECLINE_TOAST)
    if callback.message is None or callback.data is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)

    if (
        approval is None
        or approval.status != ApprovalRequestStatus.OFFERED
        or approval.client_id != user.id
    ):
        await _replace_offer_result_message(
            callback,
            db_session=db_session,
            text=texts.APPROVAL_OFFER_EXPIRED_TEXT,
        )
        return

    # Reset to pending so admin can offer another time.
    await reset_offered_request_to_pending(db_session=db_session, approval=approval)

    # Acknowledge to client.
    await replace_inline_message_text(
        callback.message,
        texts.APPROVAL_OFFER_DECLINE_TOAST,
        reply_markup=build_back_to_menu_keyboard(
            button_configs=await load_all_button_configs(SettingRepository(db_session))
        ),
    )

    # Notify admin(s).
    try:
        await send_text_to_admins(
            callback.bot,
            admin_tg_ids=settings.admin_tg_id_set,
            text=(
                texts.APPROVAL_REPAIR_OFFER_DECLINED_ADMIN_TEXT
                if approval.kind == ApprovalRequestKind.REPAIR_REQUEST
                else texts.APPROVAL_OFFER_DECLINED_ADMIN_TEXT
            ),
        )
    except Exception:
        logger.exception("Failed to notify admins about declined offer %s", approval_id)
