from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.handlers.admin.clients import show_client_card
from src.bot.keyboards.admin import (
    build_admin_clients_back_keyboard,
    build_admin_late_notice_keyboard,
)
from src.bot.states import AdminClientMessage
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.models import LateArrivalNoticeStatus
from src.db.repositories.late_arrival_notices import LateArrivalNoticeRepository
from src.db.repositories.users import UserRepository
from src.services.aftercare import build_admin_late_notice_text

router = Router(name="admin_late_notices")


async def show_late_notice_detail(
    target: Message,
    *,
    notice_id: int,
    db_session: AsyncSession,
    settings: Settings,
    edit: bool = False,
    notice_text: str | None = None,
) -> None:
    """Render one late-arrival notice in place."""
    repository = LateArrivalNoticeRepository(db_session)
    notice = await repository.get_by_id(notice_id)
    if notice is None:
        text = texts.LATE_NOTICE_ADMIN_NOT_FOUND_TEXT
        if edit:
            await replace_inline_message_text(target, text)
            return
        await target.answer(text)
        return

    text = build_admin_late_notice_text(
        notice=notice,
        booking=notice.booking,
        tz_name=settings.tz,
    )
    if notice.status == LateArrivalNoticeStatus.ACKNOWLEDGED:
        text = f"{text}\n\n✅ Учла"
    if notice_text:
        text = f"{notice_text}\n\n{text}"

    if edit:
        await replace_inline_message_text(
            target,
            text,
            reply_markup=build_admin_late_notice_keyboard(notice.id),
        )
        return
    await target.answer(text, reply_markup=build_admin_late_notice_keyboard(notice.id))


@router.callback_query(F.data.startswith("late_notice:view:"))
async def open_late_notice_view(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the structured late-arrival notice panel."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    notice_id = int(callback.data.rsplit(":", 1)[1])
    await show_late_notice_detail(
        callback.message,
        notice_id=notice_id,
        db_session=db_session,
        settings=settings,
        edit=True,
    )


@router.callback_query(F.data.startswith("late_notice:ack:"))
async def acknowledge_late_notice(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Mark one late-arrival notice as acknowledged."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer(texts.LATE_NOTICE_ACKNOWLEDGED_TOAST)
    if callback.message is None or callback.data is None:
        return
    notice_id = int(callback.data.rsplit(":", 1)[1])
    repository = LateArrivalNoticeRepository(db_session)
    notice = await repository.get_by_id(notice_id)
    if notice is None:
        await callback.message.answer(texts.LATE_NOTICE_ADMIN_NOT_FOUND_TEXT)
        return
    notice.status = LateArrivalNoticeStatus.ACKNOWLEDGED
    await db_session.commit()
    await show_late_notice_detail(
        callback.message,
        notice_id=notice.id,
        db_session=db_session,
        settings=settings,
        edit=True,
    )


@router.callback_query(F.data.startswith("late_notice:client:"))
async def open_late_notice_client(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the client card connected to one late-arrival notice."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    notice_id = int(callback.data.rsplit(":", 1)[1])
    repository = LateArrivalNoticeRepository(db_session)
    notice = await repository.get_by_id(notice_id)
    if notice is None:
        await callback.message.answer(texts.LATE_NOTICE_ADMIN_NOT_FOUND_TEXT)
        return
    await show_client_card(
        callback.message,
        db_session=db_session,
        settings=settings,
        client_id=notice.client_id,
        back_callback=f"late_notice:view:{notice.id}",
        edit=True,
    )


@router.callback_query(F.data.startswith("late_notice:message:"))
async def prompt_late_notice_message(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Prompt the admin for a direct reply to the client from a late notice."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    notice_id = int(callback.data.rsplit(":", 1)[1])
    repository = LateArrivalNoticeRepository(db_session)
    notice = await repository.get_by_id(notice_id)
    if notice is None:
        await callback.message.answer(texts.LATE_NOTICE_ADMIN_NOT_FOUND_TEXT)
        return

    user = await UserRepository(db_session).get_by_id(notice.client_id)
    if user is None:
        await callback.message.answer("Не нашла эту клиентку.")
        return

    await state.set_state(AdminClientMessage.input_message)
    await state.update_data(
        admin_client_message_id=user.id,
        admin_client_message_tg_id=user.tg_id,
        admin_client_return_callback=f"late_notice:view:{notice.id}",
    )
    await replace_inline_message_text(
        callback.message,
        texts.ADMIN_CLIENT_MESSAGE_PROMPT_TEXT,
        reply_markup=build_admin_clients_back_keyboard(f"late_notice:view:{notice.id}"),
    )
