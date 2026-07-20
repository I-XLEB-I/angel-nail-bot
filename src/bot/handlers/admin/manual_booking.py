"""Admin manual booking flow — create a booking on behalf of a client."""

from __future__ import annotations

from datetime import UTC, date, datetime

from aiogram import F, Router
from aiogram.enums import ButtonStyle
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import clear_state_preserving_admin_panel
from src.bot.handlers.client.booking_confirmation import send_booking_confirmation_bot_message
from src.bot.keyboards.admin import nav_button
from src.bot.slot_picker import (
    order_day_options_by_preference,
    order_slots_by_time_preference,
    render_day_picker,
    render_time_picker,
)
from src.bot.states import AdminManualBooking
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.models import BookingCreatedVia
from src.db.repositories.services import ServiceRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.slots import SlotRepository
from src.db.repositories.users import UserRepository
from src.services.booking import (
    ConfirmBookingResult,
    confirm_booking,
    format_local_datetime,
    group_slots_by_local_day,
)
from src.services.booking_completion import finalize_confirmed_booking
from src.services.runtime_settings import get_runtime_tz

router = Router(name="admin_manual_booking")

_CANCEL_CB = "admin_manual_booking:cancel"
_DAY_PAGE_STATE_KEY = "slot_picker_admin_manual_page"


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[nav_button("⬅️ Отмена", _CANCEL_CB)]])


def _build_manual_day_keyboard(day_options: list) -> InlineKeyboardMarkup:
    """Build the plain day keyboard for admin manual booking."""
    day_buttons = [
        InlineKeyboardButton(
            text=day_option.label,
            callback_data=f"admin_manual_booking:day:{day_option.local_date.isoformat()}",
        )
        for day_option in day_options
    ]
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(day_buttons), 2):
        rows.append(day_buttons[index : index + 2])
    rows.append([nav_button("⬅️ Отмена", _CANCEL_CB)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_manual_schedule_day_keyboard(
    day_options: list,
    *,
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Build the paginated day keyboard for admin manual booking."""
    day_buttons = [
        InlineKeyboardButton(
            text=day_option.label,
            callback_data=f"admin_manual_booking:day:{day_option.local_date.isoformat()}",
        )
        for day_option in day_options
    ]
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(day_buttons), 2):
        rows.append(day_buttons[index : index + 2])
    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if current_page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"admin_manual_booking:page:{current_page - 1}",
                )
            )
        nav_row.append(
            InlineKeyboardButton(
                text=f"Стр. {current_page + 1}/{total_pages}",
                callback_data="admin_manual_booking:page_noop",
            )
        )
        if current_page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"admin_manual_booking:page:{current_page + 1}",
                )
            )
        rows.append(nav_row)
    rows.append([nav_button("⬅️ Отмена", _CANCEL_CB)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_manual_time_keyboard(slots: list, *, tz_name: str) -> InlineKeyboardMarkup:
    """Build the time keyboard for admin manual booking."""
    time_buttons = [
        InlineKeyboardButton(
            text=format_local_datetime(slot.start_at, tz_name).strftime("%H:%M"),
            callback_data=f"admin_manual_booking:slot:{slot.id}",
        )
        for slot in slots
    ]
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(time_buttons), 3):
        rows.append(time_buttons[index : index + 3])
    rows.append([nav_button("⬅️ К дням", "admin_manual_booking:days_back")])
    rows.append([nav_button("⬅️ Отмена", _CANCEL_CB)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def start_manual_booking_for_client(
    message: Message | None,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    client_id: int,
) -> bool:
    """Jump into manual booking with one already selected client."""
    if message is None:
        return False
    user = await UserRepository(db_session).get_by_id(client_id)
    if user is None:
        return False
    await state.update_data(
        manual_booking_client_id=client_id,
        manual_booking_client_name=user.display_name,
    )
    await _show_service_picker(message, state, db_session=db_session)
    return True


@router.message(lambda message: message.text == "➕ Ручная запись")
async def manual_booking_entry(
    message: Message,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Start the manual booking flow — ask admin to search for a client."""
    if not is_admin:
        return
    await state.set_state(AdminManualBooking.input_client)
    await message.answer(
        texts.ADMIN_MANUAL_BOOKING_START_TEXT,
        reply_markup=_cancel_keyboard(),
    )


@router.callback_query(F.data == _CANCEL_CB)
async def manual_booking_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the manual booking flow."""
    await callback.answer()
    await clear_state_preserving_admin_panel(state)
    if callback.message is not None:
        await replace_inline_message_text(callback.message, "Отменено 🤍")


@router.message(StateFilter(AdminManualBooking.input_client), F.text)
async def manual_booking_client_search(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Search for existing clients; if none found, offer to create a guest booking."""
    if not is_admin:
        return
    query = (message.text or "").strip()
    if not query:
        await message.answer(texts.ADMIN_MANUAL_BOOKING_START_TEXT, reply_markup=_cancel_keyboard())
        return

    user_repository = UserRepository(db_session)
    # Also try to match by phone
    users = await user_repository.search_clients(query, limit=8)
    if not users and query.startswith("+") or any(ch.isdigit() for ch in query):
        by_phone = await user_repository.find_by_phone(query)
        if by_phone:
            users = [by_phone]

    if not users:
        # Offer to create a guest user with this name
        await state.update_data(manual_booking_guest_name=query)
        rows = [
            [
                InlineKeyboardButton(
                    text=f"✅ Создать «{query[:40]}»",
                    callback_data="admin_manual_booking:create_guest",
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [nav_button("⬅️ Отмена", _CANCEL_CB)],
        ]
        await message.answer(
            texts.ADMIN_MANUAL_BOOKING_NOT_FOUND_CREATE_TEXT.format(name=query[:40]),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        return

    rows = [
        [
            InlineKeyboardButton(
                text=f"{u.display_name} (id {u.id})",
                callback_data=f"admin_manual_booking:client:{u.id}",
            )
        ]
        for u in users
    ]
    rows.append([nav_button("⬅️ Отмена", _CANCEL_CB)])
    await message.answer(
        "Выбери клиента 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "admin_manual_booking:create_guest")
async def manual_booking_create_guest(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Create a minimal guest User with the provided name and proceed."""
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    data = await state.get_data()
    guest_name = (data.get("manual_booking_guest_name") or "Гость").strip()[:255] or "Гость"

    # Create guest with a placeholder tg_id that won't match real users.
    # We use a large negative-based stable ID collision-resistant number.
    import hashlib  # noqa: PLC0415

    fake_tg_id = -(abs(int(hashlib.md5(guest_name.encode()).hexdigest()[:8], 16)) % 10**9 + 1)
    user_repository = UserRepository(db_session)
    existing = await user_repository.get_by_tg_id(fake_tg_id)
    if existing is None:
        from src.db.models import User as UserModel  # noqa: PLC0415

        guest_user = UserModel(
            tg_id=fake_tg_id,
            display_name=guest_name,
            is_admin=False,
        )
        db_session.add(guest_user)
        await db_session.flush()
        client_id = guest_user.id
    else:
        client_id = existing.id

    await state.update_data(
        manual_booking_client_id=client_id,
        manual_booking_client_name=guest_name,
    )
    await _show_service_picker(callback.message, state, db_session=db_session)


@router.callback_query(F.data.startswith("admin_manual_booking:client:"))
async def manual_booking_client_chosen(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Store the chosen client and show the service picker."""
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    if callback.data is None:
        return
    client_id = int(callback.data.rsplit(":", 1)[-1])
    user = await UserRepository(db_session).get_by_id(client_id)
    if user is None:
        if callback.message is not None:
            await replace_inline_message_text(callback.message, "Клиент не найден 🤍")
        await clear_state_preserving_admin_panel(state)
        return
    await state.update_data(
        manual_booking_client_id=client_id,
        manual_booking_client_name=user.display_name,
    )
    await _show_service_picker(callback.message, state, db_session=db_session)


async def _show_service_picker(
    message: Message | None,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    if message is None:
        return
    from src.db.models import ServiceKind  # noqa: PLC0415

    services = await ServiceRepository(db_session).list_active(kind=ServiceKind.BASE)
    if not services:
        await replace_inline_message_text(message, "Нет активных услуг 🤍")
        await clear_state_preserving_admin_panel(state)
        return
    rows = [
        [InlineKeyboardButton(text=s.name, callback_data=f"admin_manual_booking:service:{s.id}")]
        for s in services
    ]
    rows.append([nav_button("⬅️ Отмена", _CANCEL_CB)])
    await state.set_state(AdminManualBooking.choose_service)
    await replace_inline_message_text(
        message,
        texts.ADMIN_MANUAL_BOOKING_CHOOSE_SERVICE_TEXT,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(
    StateFilter(AdminManualBooking.choose_service),
    F.data.startswith("admin_manual_booking:service:"),
)
async def manual_booking_service_chosen(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    if callback.data is None or callback.message is None:
        return
    service_id = int(callback.data.rsplit(":", 1)[-1])
    await state.update_data(manual_booking_service_id=service_id)
    await _show_day_picker(callback.message, state, db_session=db_session, settings=settings)


async def _show_day_picker(
    message: Message | None,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
    prefix_text: str | None = None,
    image_page: int | None = None,
    focus_day: date | None = None,
) -> None:
    if message is None:
        return
    settings_repository = SettingRepository(db_session)
    tz_name = await get_runtime_tz(settings_repository, settings=settings)
    now_utc = datetime.now(UTC)
    slot_repository = SlotRepository(db_session)
    free_slots = await slot_repository.list_free_future(now_utc=now_utc)

    data = await state.get_data()
    client_id = data.get("manual_booking_client_id")
    client = (
        await UserRepository(db_session).get_by_id(int(client_id))
        if isinstance(client_id, int) or (isinstance(client_id, str) and client_id.isdigit())
        else None
    )
    day_groups = order_day_options_by_preference(
        group_slots_by_local_day(free_slots, tz_name=tz_name),
        client.preferred_days_note if client is not None else None,
    )
    await state.set_state(AdminManualBooking.choose_day)
    prompt_text = texts.ADMIN_MANUAL_BOOKING_CHOOSE_DAY_TEXT
    if prefix_text:
        prompt_text = f"{prefix_text}\n\n{prompt_text}"
    await render_day_picker(
        message,
        db_session=db_session,
        settings=settings,
        slots=free_slots,
        day_options=day_groups,
        prompt_text=prompt_text,
        no_slots_text=texts.BOOKING_NO_SLOTS_TEXT,
        replace=True,
        no_slots_reply_markup=_cancel_keyboard(),
        text_reply_markup_builder=_build_manual_day_keyboard,
        image_reply_markup_builder=(
            lambda current_day_options, current_page, total_pages: (
                _build_manual_schedule_day_keyboard(
                    current_day_options,
                    current_page=current_page,
                    total_pages=total_pages,
                )
            )
        ),
        schedule_caption_text=texts.BOOKING_SCHEDULE_IMAGE_CAPTION_TEXT,
        state=state,
        page_state_key=_DAY_PAGE_STATE_KEY,
        image_page=image_page,
        focus_day=focus_day,
    )


@router.callback_query(
    StateFilter(AdminManualBooking.choose_day),
    F.data.startswith("admin_manual_booking:day:"),
)
async def manual_booking_day_chosen(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    if callback.data is None or callback.message is None:
        return
    iso_day = callback.data.removeprefix("admin_manual_booking:day:")
    local_day = date.fromisoformat(iso_day)
    settings_repository = SettingRepository(db_session)
    tz_name = await get_runtime_tz(settings_repository, settings=settings)
    slot_repository = SlotRepository(db_session)
    slots = await slot_repository.list_free_for_local_day(local_day=local_day, tz_name=tz_name)
    data = await state.get_data()
    client_id = data.get("manual_booking_client_id")
    client = (
        await UserRepository(db_session).get_by_id(int(client_id))
        if isinstance(client_id, int) or (isinstance(client_id, str) and client_id.isdigit())
        else None
    )
    slots = order_slots_by_time_preference(
        slots,
        client.preferred_time_note if client is not None else None,
        tz_name=tz_name,
    )
    if not slots:
        await _show_day_picker(
            callback.message,
            state,
            db_session=db_session,
            settings=settings,
            prefix_text="Свободных окошек на этот день нет 🤍",
            focus_day=local_day,
        )
        return
    await state.set_state(AdminManualBooking.choose_time)
    await render_time_picker(
        callback.message,
        prompt_text=texts.ADMIN_MANUAL_BOOKING_CHOOSE_TIME_TEXT,
        replace=True,
        reply_markup=_build_manual_time_keyboard(slots, tz_name=tz_name),
    )


@router.callback_query(
    StateFilter(AdminManualBooking.choose_day),
    F.data.startswith("admin_manual_booking:page:"),
)
async def manual_booking_change_day_page(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Flip one page inside the manual-booking day viewer."""
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    page = int(callback.data.rsplit(":", 1)[-1])
    await _show_day_picker(
        callback.message,
        state,
        db_session=db_session,
        settings=settings,
        image_page=page,
    )


@router.callback_query(
    StateFilter(AdminManualBooking.choose_day),
    F.data == "admin_manual_booking:page_noop",
)
async def manual_booking_day_page_noop(callback: CallbackQuery) -> None:
    """Acknowledge the inert page indicator in the manual-booking day viewer."""
    await callback.answer()


@router.callback_query(
    StateFilter(AdminManualBooking.choose_time),
    F.data == "admin_manual_booking:days_back",
)
async def manual_booking_back_to_days(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Return from time selection to the day picker."""
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    if callback.message is None:
        return
    await _show_day_picker(
        callback.message,
        state,
        db_session=db_session,
        settings=settings,
    )


@router.callback_query(
    StateFilter(AdminManualBooking.choose_time),
    F.data.startswith("admin_manual_booking:slot:"),
)
async def manual_booking_slot_chosen(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    if callback.data is None or callback.message is None:
        return
    slot_id = int(callback.data.rsplit(":", 1)[-1])
    await state.update_data(manual_booking_slot_id=slot_id)

    data = await state.get_data()
    client_name = data.get("manual_booking_client_name", "Клиент")
    service_id = data.get("manual_booking_service_id")

    settings_repository = SettingRepository(db_session)
    tz_name = await get_runtime_tz(settings_repository, settings=settings)
    slot = await SlotRepository(db_session).get_by_id(slot_id)
    service = await ServiceRepository(db_session).get_by_id(service_id) if service_id else None

    if slot is None or service is None:
        await replace_inline_message_text(callback.message, "Что-то пошло не так 🤍")
        await clear_state_preserving_admin_panel(state)
        return

    local_dt = format_local_datetime(slot.start_at, tz_name)
    confirm_text = texts.ADMIN_MANUAL_BOOKING_CONFIRM_TEXT.format(
        client_name=client_name,
        date=local_dt.strftime("%d.%m.%Y"),
        time=local_dt.strftime("%H:%M"),
        service=service.name,
    )
    rows = [
        [
            InlineKeyboardButton(
                text="✅ Создать запись",
                callback_data="admin_manual_booking:confirm",
                style=ButtonStyle.SUCCESS,
            )
        ],
        [nav_button("⬅️ Отмена", _CANCEL_CB)],
    ]
    await state.set_state(AdminManualBooking.confirm)
    await replace_inline_message_text(
        callback.message,
        confirm_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(
    StateFilter(AdminManualBooking.confirm),
    F.data == "admin_manual_booking:confirm",
)
async def manual_booking_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    if callback.message is None:
        return

    data = await state.get_data()
    client_id = data.get("manual_booking_client_id")
    service_id = data.get("manual_booking_service_id")
    slot_id = data.get("manual_booking_slot_id")

    if not all([client_id, service_id, slot_id]):
        await replace_inline_message_text(callback.message, "Данные потеряны, начни заново 🤍")
        await clear_state_preserving_admin_panel(state)
        return

    result: ConfirmBookingResult = await confirm_booking(
        db_session,
        client_id=client_id,
        slot_id=slot_id,
        base_service_id=service_id,
        addon_ids=[],
        design_photos=[],
        design_comment=None,
        created_via=BookingCreatedVia.ADMIN_MANUAL,
    )

    if not result.ok:
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_MANUAL_BOOKING_SLOT_TAKEN_TEXT,
        )
        await clear_state_preserving_admin_panel(state)
        return

    user = await UserRepository(db_session).get_by_id(int(client_id))
    if user is None or result.booking is None or result.slot is None:
        await replace_inline_message_text(callback.message, "Что-то пошло не так 🤍")
        await clear_state_preserving_admin_panel(state)
        return

    completion = await finalize_confirmed_booking(
        db_session,
        booking=result.booking,
        slot=result.slot,
        base_service=result.base_service,
        addons=result.addons,
        user=user,
        settings=settings,
        origin="admin_manual",
        notify_client=user.tg_id > 0,
        sync_calendar=True,
    )
    if completion.client_confirmation is not None:
        await send_booking_confirmation_bot_message(
            callback.bot,
            db_session=db_session,
            settings=settings,
            payload=completion.client_confirmation,
        )

    await clear_state_preserving_admin_panel(state)
    await replace_inline_message_text(
        callback.message,
        texts.ADMIN_MANUAL_BOOKING_DONE_TEXT,
    )
