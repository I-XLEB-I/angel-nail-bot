from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import (
    clear_state_preserving_admin_panel,
    send_admin_panel,
    send_admin_photo_panel,
)
from src.bot.fsm_utils import clear_state_preserving_admin_mode
from src.bot.handlers.client.brand import BRAND_IMAGE_PATH, load_brand_image_bytes
from src.bot.handlers.client.menu import show_client_menu
from src.bot.keyboards.admin import build_admin_main_menu
from src.config import Settings
from src.db.models import User
from src.db.repositories.approvals import ApprovalRequestRepository
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.morning_summary import send_live_morning_summary_to_admin
from src.services.runtime_settings import get_runtime_tz
from src.services.template_texts import render_named_template

router = Router(name="admin_menu")


async def show_admin_menu(
    message: Message,
    *,
    db_session: AsyncSession,
    settings: Settings,
    state: FSMContext | None = None,
) -> None:
    """Show the main admin dashboard."""
    approval_repository = ApprovalRequestRepository(db_session)
    booking_repository = BookingRepository(db_session)
    settings_repository = SettingRepository(db_session)
    template_repository = TemplateRepository(db_session)
    tz_name = await get_runtime_tz(settings_repository, settings=settings)
    local_today = datetime.now(ZoneInfo(tz_name)).date()
    pending_approvals = await approval_repository.count_pending()
    today_bookings = await booking_repository.count_for_local_day(
        local_day=local_today,
        tz_name=tz_name,
    )

    text = await render_named_template(
        template_repository,
        key="admin_menu_text",
        values={
            "pending_approvals": str(pending_approvals),
            "today_bookings": str(today_bookings),
        },
    )
    markup = build_admin_main_menu(pending_approvals=pending_approvals)
    brand_image_bytes = load_brand_image_bytes()
    if state is not None:
        if brand_image_bytes is not None:
            await send_admin_photo_panel(
                message,
                state,
                photo_bytes=brand_image_bytes,
                filename=BRAND_IMAGE_PATH.name,
                caption=text,
                reply_markup=markup,
            )
            return
        await send_admin_panel(message, state, text=text, reply_markup=markup)
        return
    if brand_image_bytes is not None:
        await message.answer_photo(
            photo=BufferedInputFile(brand_image_bytes, filename=BRAND_IMAGE_PATH.name),
            caption=text,
            reply_markup=markup,
        )
        return
    await message.answer(text, reply_markup=markup)


@router.message(Command("admin"))
async def admin_menu_command(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the admin menu or fallback to the client menu for non-admins."""
    if not is_admin:
        await clear_state_preserving_admin_mode(state)
        await show_client_menu(message, db_session=db_session, user=user)
        return

    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await state.update_data(admin_as_client=False)
    await show_admin_menu(message, db_session=db_session, settings=settings, state=state)


@router.callback_query(F.data == "admin_menu:home")
async def admin_menu_home_callback(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Return from an inline admin subsection to the main admin menu."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await state.update_data(admin_as_client=False)
    if callback.message is not None:
        await show_admin_menu(
            callback.message,
            db_session=db_session,
            settings=settings,
            state=state,
        )


@router.message(lambda message: message.text == "🗓 Статусы на сегодня")
async def open_today_status_summary(
    message: Message,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Send a fresh live today-status summary from the admin reply keyboard."""
    if not is_admin:
        return
    await send_live_morning_summary_to_admin(
        message.bot,
        db_session=db_session,
        settings=settings,
        admin_tg_id=message.chat.id,
    )


@router.message(lambda message: message.text == "🙈 Режим клиента")
async def admin_switch_to_client_mode(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    is_admin: bool,
) -> None:
    """Switch an admin into client mode until `/admin` is called again."""
    if not is_admin:
        return

    await state.clear()
    await state.update_data(admin_as_client=True)
    await message.answer("Переключила в режим клиента ✨", reply_markup=ReplyKeyboardRemove())
    await show_client_menu(message, db_session=db_session, user=user)
