from datetime import UTC

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import clear_state_preserving_admin_panel
from src.bot.fsm_utils import clear_state_preserving_admin_mode
from src.bot.handlers.admin.approvals import show_pending_approvals
from src.bot.handlers.admin.clients import open_clients_section
from src.bot.handlers.admin.menu import show_admin_menu
from src.bot.handlers.admin.schedule import show_schedule_menu
from src.bot.handlers.admin.settings_edit import render_settings_diagnostics_text
from src.bot.handlers.client.booking_flow import start_booking_entry
from src.bot.handlers.client.menu import show_client_menu
from src.bot.handlers.client.my_bookings import show_my_bookings_entry
from src.config import Settings
from src.db.models import User
from src.services.calendar_sync import CalendarClientInfo, create_smoke_test_event
from src.services.design_photos import upload_design_photo
from src.services.google_smoke import run_google_smoke_test
from src.services.morning_summary import send_live_morning_summary_to_admin

router = Router(name="common")


async def force_client_mode(state: FSMContext, *, is_admin: bool) -> None:
    """Reset FSM and switch an admin into client mode for client commands."""
    await state.clear()
    if is_admin:
        await state.update_data(admin_as_client=True)


async def force_admin_mode(state: FSMContext) -> None:
    """Reset FSM and switch back into the admin mode."""
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await state.update_data(admin_as_client=False)


@router.message(CommandStart())
async def start_menu(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Show the start menu depending on the user's role and mode."""
    data = await state.get_data()
    if is_admin and not data.get("admin_as_client"):
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await state.update_data(admin_as_client=False)
        await show_admin_menu(message, db_session=db_session, settings=settings, state=state)
        return

    await clear_state_preserving_admin_mode(state)
    await show_client_menu(message, db_session=db_session, user=user)


@router.message(Command("menu"))
async def bot_menu(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
) -> None:
    """Show the main client menu."""
    await clear_state_preserving_admin_mode(state)
    await show_client_menu(message, db_session=db_session, user=user)


@router.message(Command("help"))
async def help_menu(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Show the admin or client menu depending on the current mode."""
    data = await state.get_data()
    if is_admin and not data.get("admin_as_client"):
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await state.update_data(admin_as_client=False)
        await show_admin_menu(message, db_session=db_session, settings=settings, state=state)
        return

    await clear_state_preserving_admin_mode(state)
    await show_client_menu(message, db_session=db_session, user=user)


@router.message(Command("book"))
async def command_book(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    is_admin: bool,
) -> None:
    """Start booking from the Telegram commands menu."""
    await force_client_mode(state, is_admin=is_admin)
    await start_booking_entry(
        message,
        state,
        db_session=db_session,
        user=user,
        first_name=(message.from_user.first_name if message.from_user else None),
    )


@router.message(Command("mybookings"))
async def command_my_bookings(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open `Мои записи` from the Telegram commands menu."""
    await force_client_mode(state, is_admin=is_admin)
    await show_my_bookings_entry(
        message,
        state,
        db_session=db_session,
        user=user,
        settings=settings,
    )


@router.message(Command("schedule"))
async def command_schedule(
    message: Message,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Open the admin schedule section from the commands menu."""
    if not is_admin:
        return
    await force_admin_mode(state)
    await show_schedule_menu(message, state=state)


@router.message(Command("requests"))
async def command_requests(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the admin requests queue from the commands menu."""
    if not is_admin:
        return
    await force_admin_mode(state)
    await show_pending_approvals(
        message,
        db_session=db_session,
        is_admin=is_admin,
        settings=settings,
    )


@router.message(Command("clients"))
async def command_clients(
    message: Message,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Open the admin clients section from the commands menu."""
    if not is_admin:
        return
    await force_admin_mode(state)
    await open_clients_section(message, state, is_admin=is_admin)


@router.message(Command("today"))
async def command_today_status(
    message: Message,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Send a fresh live today-status summary for admins."""
    if not is_admin:
        return
    await send_live_morning_summary_to_admin(
        message.bot,
        db_session=db_session,
        settings=settings,
        admin_tg_id=message.chat.id,
    )


@router.message(Command("diag"))
async def command_diag(
    message: Message,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Show a concise operational diagnostics snapshot for admins."""
    if not is_admin:
        return
    await message.answer(await render_settings_diagnostics_text(db_session, settings))


@router.message(Command("google_test"))
async def google_test(
    message: Message,
    *,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Run a Google Sheets/Drive smoke test from Telegram for admins."""
    if not is_admin or not settings.debug_commands:
        return

    await message.answer(texts.GOOGLE_TEST_LOADING_TEXT)
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        result = run_google_smoke_test(settings)
    except Exception as exc:
        await message.answer(texts.GOOGLE_TEST_FAILED_TEXT.format(error=str(exc)))
        return

    await message.answer(
        texts.GOOGLE_TEST_SUCCESS_TEXT.format(
            sheet_title=result.sheet_title,
            updated_range=result.updated_range,
            drive_file_name=result.drive_file_name,
            drive_file_id=result.drive_file_id,
        )
    )


@router.message(Command("save_photo"))
@router.message(F.photo, F.caption.startswith("/save_photo"))
async def save_photo(
    message: Message,
    *,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Upload a Telegram photo into the structured Google Drive design-photo folders."""
    if not is_admin or not settings.debug_commands:
        return

    target_message = message.reply_to_message or message
    if not target_message.photo:
        await message.answer(texts.SAVE_PHOTO_USAGE_TEXT)
        return

    photo = target_message.photo[-1]
    uploaded_at = target_message.date.replace(tzinfo=UTC)
    owner_tg_id = (
        target_message.from_user.id
        if target_message.from_user is not None
        else message.from_user.id
    )
    file_name = f"photo_{uploaded_at.strftime('%Y%m%dT%H%M%S')}_{photo.file_unique_id}.jpg"

    await message.answer(texts.SAVE_PHOTO_LOADING_TEXT)
    await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_document")
    try:
        downloaded = await message.bot.download(photo)
        if downloaded is None:
            raise RuntimeError("Telegram did not return the file bytes")
        downloaded.seek(0)
        result = upload_design_photo(
            settings,
            tg_id=owner_tg_id,
            file_name=file_name,
            content=downloaded.read(),
            mime_type="image/jpeg",
            uploaded_at=uploaded_at,
        )
    except Exception as exc:
        await message.answer(texts.SAVE_PHOTO_FAILED_TEXT.format(error=str(exc)))
        return

    await message.answer(
        texts.SAVE_PHOTO_SUCCESS_TEXT.format(
            folder_path="/".join(result.folder_segments),
            file_name=result.file_name,
            file_id=result.file_id,
        )
    )


@router.message(Command("calendar_test"))
async def calendar_test(
    message: Message,
    *,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Create a short Google Calendar smoke-test event for admins."""
    if not is_admin or not settings.debug_commands:
        return

    await message.answer(texts.CALENDAR_TEST_LOADING_TEXT)
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        from_user = message.from_user
        client = None
        if from_user is not None:
            display_name = (from_user.full_name or from_user.first_name or "Клиент").strip()
            client = CalendarClientInfo(
                display_name=display_name,
                tg_id=from_user.id,
                tg_username=from_user.username,
            )
        result = create_smoke_test_event(settings, client=client)
    except Exception as exc:
        await message.answer(texts.CALENDAR_TEST_FAILED_TEXT.format(error=str(exc)))
        return

    await message.answer(
        texts.CALENDAR_TEST_SUCCESS_TEXT.format(
            calendar_summary=result.calendar_summary,
            event_summary=result.event_summary,
            start_at=result.start_at,
            end_at=result.end_at,
            event_id=result.event_id,
        )
    )
