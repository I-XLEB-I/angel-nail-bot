from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import (
    ADMIN_PANEL_CHAT_ID_KEY,
    ADMIN_PANEL_MESSAGE_ID_KEY,
    clear_state_preserving_admin_panel,
    remember_admin_panel,
    send_admin_panel,
)
from src.bot.handlers.admin.booking_cards import build_booking_card_panel
from src.bot.handlers.admin.manual_booking import start_manual_booking_for_client
from src.bot.keyboards.admin import (
    build_admin_client_bookings_keyboard,
    build_admin_client_confirm_action_keyboard,
    build_admin_client_info_keyboard,
    build_admin_client_main_keyboard,
    build_admin_client_moderation_keyboard,
    build_admin_client_search_results_keyboard,
    build_admin_clients_back_keyboard,
    build_admin_clients_home_keyboard,
    build_admin_clients_page_keyboard,
)
from src.bot.states import AdminClientMessage, AdminClients
from src.bot.ui_utils import replace_inline_message_text, upsert_inline_panel
from src.config import Settings
from src.db.models import Booking, User
from src.db.repositories.bookings import BookingRepository, ClientBookingStats
from src.db.repositories.settings import SettingRepository
from src.db.repositories.users import UserRepository
from src.services.booking import format_local_datetime, get_booking_status_label
from src.services.runtime_settings import get_int_setting, get_runtime_tz

router = Router(name="admin_clients")

CLIENTS_PAGE_SIZE = 8
CLIENT_CARD_MAIN_VIEW = "main"
CLIENT_CARD_INFO_VIEW = "info"
CLIENT_CARD_MODERATION_VIEW = "moderation"
CLIENT_CARD_BOOKINGS_VIEW = "bookings"


def render_client_search_label(user: User) -> str:
    """Return one compact label for client search results."""
    username = f"@{user.tg_username}" if user.tg_username else "без username"
    block_suffix = " [block]" if user.is_blocked else ""
    return f"{user.display_name} ({username}){block_suffix}"


def format_confirm_rate_text(confirmed_count: int, total_count: int) -> str:
    """Render a compact reminder-confirmation score for the client card."""
    if total_count <= 0:
        return "—"
    percentage = round((confirmed_count / total_count) * 100)
    return f"{percentage}% ({confirmed_count}/{total_count})"


def resolve_client_level_label(total_visits: int) -> str:
    """Return a simple loyalty label for the admin client card."""
    if total_visits >= 10:
        return "VIP"
    if total_visits >= 4:
        return "Постоянная"
    if total_visits >= 1:
        return "Знакомая"
    return "Новая"


def format_booking_brief(booking: Booking | None, *, tz_name: str, empty_text: str) -> str:
    """Render one compact booking line for the admin client card."""
    if booking is None or booking.slot is None:
        return empty_text
    local_dt = format_local_datetime(booking.slot.start_at, tz_name)
    return (
        f"{local_dt.strftime('%d.%m.%Y %H:%M')} · "
        f"{booking.base_service.name} · "
        f"{get_booking_status_label(booking.status)}"
    )


def render_client_main_card(
    user: User,
    *,
    next_booking: Booking | None,
    tz_name: str,
    strikes_limit: int,
) -> str:
    """Render the compact operational client card."""
    username = f"@{user.tg_username}" if user.tg_username else "без username"
    phone = user.phone or "не указан"
    status_bits: list[str] = []
    if user.is_blocked:
        status_bits.append("🔴 Заблокирована")
    else:
        status_bits.append("🟢 Активна")
    risk_bits: list[str] = []
    if user.strikes > 0:
        risk_bits.append(f"Strikes: {user.strikes}/{strikes_limit}")
    if user.requires_manual_approval:
        risk_bits.append("Ручное подтверждение: да")
    if user.is_shadow_banned:
        risk_bits.append("Shadow-ban: вкл")
    if user.duplicate_phone_flag:
        risk_bits.append("Дубль телефона: да")

    lines = [
        f"👤 {user.display_name}",
        f"{username} · {phone}",
    ]
    if user.is_admin:
        lines.append("👑 Админ в режиме клиента")
    lines.extend(
        [
            "",
            f"{' · '.join(status_bits)}",
            "",
            "📅 Ближайшая запись",
            format_booking_brief(
                next_booking,
                tz_name=tz_name,
                empty_text="Сейчас активных записей нет",
            ),
        ]
    )
    if risk_bits:
        lines.extend(["", "🛡 На контроле", *risk_bits])
    return "\n".join(lines)


def render_client_info_card(
    user: User,
    *,
    stats: ClientBookingStats,
    next_booking: Booking | None,
    last_completed_booking: Booking | None,
    tz_name: str,
    confirmed_reminders: int,
    total_reminders: int,
    duplicate_user: User | None = None,
) -> str:
    """Render the secondary information card for one client."""
    username = f"@{user.tg_username}" if user.tg_username else "без username"
    phone = user.phone or "не указан"
    lines = [
        f"ℹ️ Инфо · {user.display_name}",
        f"{username} · {phone}",
        "",
        "📊 Сводка",
        f"Уровень: {resolve_client_level_label(stats.total_visits)}",
        f"Визитов: {stats.total_visits}",
        f"Выручка: {stats.total_spent}₽",
        f"Любимая услуга: {stats.favorite_service_name or '—'}",
        f"Confirm-rate: {format_confirm_rate_text(confirmed_reminders, total_reminders)}",
        "",
        "📅 Ближайшая запись",
        format_booking_brief(
            next_booking,
            tz_name=tz_name,
            empty_text="Сейчас активных записей нет",
        ),
        "",
        "🕘 Последний визит",
        format_booking_brief(
            last_completed_booking,
            tz_name=tz_name,
            empty_text="Завершённых визитов ещё не было",
        ),
        "",
        "🛡 Служебно",
        f"Дубль телефона: {'да' if user.duplicate_phone_flag else 'нет'}",
        (
            f"Совпадает с @{duplicate_user.tg_username}"
            if duplicate_user is not None and duplicate_user.tg_username
            else (
                f"Совпадает с {duplicate_user.display_name}"
                if duplicate_user is not None
                else "Совпадений не найдено"
            )
        ),
    ]
    if stats.total_cancels or stats.no_shows:
        lines.extend(
            [
                "",
                "⚠️ Риски",
                f"Отмен: {stats.total_cancels} · No-show: {stats.no_shows}",
            ]
        )

    soft_hint_lines = [
        value
        for value in [
            f"Дни: {user.preferred_days_note}" if user.preferred_days_note else "",
            f"Время: {user.preferred_time_note}" if user.preferred_time_note else "",
            f"Длина: {user.preferred_length_note}" if user.preferred_length_note else "",
            f"Форма: {user.preferred_shape_note}" if user.preferred_shape_note else "",
            f"Дизайн: {user.preferred_design_note}" if user.preferred_design_note else "",
        ]
        if value
    ]
    if soft_hint_lines:
        lines.extend(["", "🌸 Подсказки по клиентке", *soft_hint_lines])

    lines.extend(["", "📝 Заметка", user.note or "—"])
    return "\n".join(lines)


def render_client_moderation_card(
    user: User,
    *,
    strikes_limit: int,
) -> str:
    """Render the dedicated moderation screen for one client."""
    return "\n".join(
        [
            f"🛡 Модерация · {user.display_name}",
            "",
            f"Ручное подтверждение: {'да' if user.requires_manual_approval else 'нет'}",
            f"Shadow-ban: {'вкл' if user.is_shadow_banned else 'выкл'}",
            f"Strikes: {user.strikes}/{strikes_limit}",
            f"Блокировка: {'да' if user.is_blocked else 'нет'}",
            "",
            "Выбери действие ниже.",
        ]
    )


def _render_client_bookings_line(booking: Booking, *, tz_name: str) -> str:
    """Render one compact line for the per-client bookings screen."""
    if booking.slot is None or booking.base_service is None:
        return "—"
    local_dt = format_local_datetime(booking.slot.start_at, tz_name)
    return f"{local_dt:%d.%m · %H:%M} · {booking.base_service.name} · {get_booking_status_label(booking.status)}"


def render_client_bookings_card(
    user: User,
    *,
    active_bookings: list[Booking],
    completed_bookings: list[Booking],
    tz_name: str,
) -> str:
    """Render the lightweight bookings history for one client."""
    lines = [f"📅 Записи · {user.display_name}", ""]
    lines.append("Активные:")
    if active_bookings:
        lines.extend(_render_client_bookings_line(booking, tz_name=tz_name) for booking in active_bookings)
    else:
        lines.append("Активных записей сейчас нет")
    lines.extend(["", "История:"])
    if completed_bookings:
        lines.extend(
            _render_client_bookings_line(booking, tz_name=tz_name) for booking in completed_bookings
        )
    else:
        lines.append("Завершённых визитов ещё не было")
    return "\n".join(lines)


def parse_client_view_and_return_callback(
    parts: list[str], *, start_index: int
) -> tuple[str, str]:
    """Restore the internal client-card view plus the outer return callback."""
    view = CLIENT_CARD_MAIN_VIEW
    if len(parts) > start_index and parts[start_index] in {
        CLIENT_CARD_MAIN_VIEW,
        CLIENT_CARD_INFO_VIEW,
        CLIENT_CARD_MODERATION_VIEW,
        CLIENT_CARD_BOOKINGS_VIEW,
    }:
        view = parts[start_index]
        start_index += 1
    return view, parse_return_callback(parts, start_index=start_index)


def build_client_view_callback(
    *, client_id: int, view: str, back_callback: str
) -> str:
    """Build one internal client-card callback while preserving outer context."""
    if back_callback.startswith("admin_clients:list:"):
        context_suffix = f":list:{back_callback.rsplit(':', 1)[-1]}"
    elif back_callback.startswith("admin_approvals:open:"):
        context_suffix = f":approval:{back_callback.rsplit(':', 1)[-1]}"
    elif back_callback.startswith("admin_schedule:week:"):
        context_suffix = f":schedule:week:{back_callback.rsplit(':', 1)[-1]}"
    elif back_callback.startswith("admin_schedule:month:page:"):
        context_suffix = f":schedule:month:{back_callback.rsplit(':', 1)[-1]}"
    elif back_callback.startswith("late_notice:view:"):
        context_suffix = f":late_notice:{back_callback.rsplit(':', 1)[-1]}"
    else:
        context_suffix = ":home"
    if view == CLIENT_CARD_MAIN_VIEW:
        return f"admin_clients:open:{client_id}{context_suffix}"
    return f"admin_clients:{view}:{client_id}{context_suffix}"


def parse_return_callback(parts: list[str], *, start_index: int) -> str:
    """Restore the parent clients screen from callback segments."""
    if len(parts) > start_index and parts[start_index] == "list" and len(parts) > start_index + 1:
        return f"admin_clients:list:{parts[start_index + 1]}"
    if (
        len(parts) > start_index
        and parts[start_index] == "approval"
        and len(parts) > start_index + 1
    ):
        return f"admin_approvals:open:{parts[start_index + 1]}"
    if (
        len(parts) > start_index + 2
        and parts[start_index] == "schedule"
        and parts[start_index + 1] == "week"
    ):
        return f"admin_schedule:week:{parts[start_index + 2]}"
    if (
        len(parts) > start_index + 2
        and parts[start_index] == "schedule"
        and parts[start_index + 1] == "month"
    ):
        return f"admin_schedule:month:page:{parts[start_index + 2]}"
    if (
        len(parts) > start_index + 1
        and parts[start_index] == "late_notice"
    ):
        return f"late_notice:view:{parts[start_index + 1]}"
    return "admin_clients:home"


async def show_clients_home(
    target: Message,
    *,
    state: FSMContext | None = None,
    edit: bool = False,
) -> None:
    """Show the home screen for the clients section."""
    if edit:
        await replace_inline_message_text(
            target,
            texts.ADMIN_CLIENTS_HOME_TEXT,
            reply_markup=build_admin_clients_home_keyboard(),
        )
        if state is not None:
            await remember_admin_panel(state, target)
        return
    if state is not None:
        await send_admin_panel(
            target,
            state,
            text=texts.ADMIN_CLIENTS_HOME_TEXT,
            reply_markup=build_admin_clients_home_keyboard(),
        )
        return
    await target.answer(
        texts.ADMIN_CLIENTS_HOME_TEXT,
        reply_markup=build_admin_clients_home_keyboard(),
    )


async def show_clients_page(
    target: Message,
    *,
    db_session: AsyncSession,
    page: int,
    edit: bool = False,
) -> None:
    """Show one page of the full clients list."""
    repository = UserRepository(db_session)
    total = await repository.count_clients()
    if total <= 0:
        text = texts.ADMIN_CLIENTS_LIST_EMPTY_TEXT
        markup = build_admin_clients_back_keyboard()
    else:
        max_page = max(0, (total - 1) // CLIENTS_PAGE_SIZE)
        page = min(max(page, 0), max_page)
        users = await repository.list_clients(
            limit=CLIENTS_PAGE_SIZE,
            offset=page * CLIENTS_PAGE_SIZE,
        )
        text = texts.ADMIN_CLIENTS_LIST_TEXT.format(page=page + 1, pages=max_page + 1, total=total)
        markup = build_admin_clients_page_keyboard(
            [(user.id, render_client_search_label(user)) for user in users],
            page=page,
            has_prev=page > 0,
            has_next=page < max_page,
        )

    if edit:
        await replace_inline_message_text(target, text, reply_markup=markup)
        return
    await target.answer(text, reply_markup=markup)


async def show_client_card(
    target: Message,
    *,
    db_session: AsyncSession,
    settings: Settings,
    client_id: int,
    back_callback: str = "admin_clients:home",
    view: str = CLIENT_CARD_MAIN_VIEW,
    edit: bool = False,
    notice_text: str | None = None,
) -> None:
    """Send the selected client card."""
    panel = await build_client_card_panel(
        db_session=db_session,
        settings=settings,
        client_id=client_id,
        back_callback=back_callback,
        view=view,
        notice_text=notice_text,
    )
    if panel is None:
        await target.answer("Не нашла эту клиентку.")
        return
    text, markup = panel

    if edit:
        await replace_inline_message_text(target, text, reply_markup=markup)
        return
    await target.answer(text, reply_markup=markup)


async def build_client_card_panel(
    *,
    db_session: AsyncSession,
    settings: Settings,
    client_id: int,
    back_callback: str,
    view: str = CLIENT_CARD_MAIN_VIEW,
    notice_text: str | None = None,
) -> tuple[str, object] | None:
    """Build the admin client-card text and keyboard."""
    user_repository = UserRepository(db_session)
    booking_repository = BookingRepository(db_session)
    settings_repository = SettingRepository(db_session)

    user = await user_repository.get_by_id(client_id)
    if user is None:
        return None
    duplicate_user = None
    if user.phone:
        duplicate_user = await user_repository.find_by_phone(user.phone, exclude_user_id=user.id)

    tz_name = await get_runtime_tz(settings_repository, settings=settings)
    stats = await booking_repository.get_client_card_stats(user.id)
    confirmed_reminders, total_reminders = await booking_repository.get_client_confirmation_stats(
        user.id
    )
    next_bookings = await booking_repository.list_active_for_client(user.id)
    last_completed = await booking_repository.list_recent_completed_for_client(user.id, limit=1)
    late_cancel_strike_limit = await get_int_setting(
        settings_repository,
        key="late_cancel_strike_limit",
        default=3,
    )
    no_show_strike_limit = await get_int_setting(
        settings_repository,
        key="no_show_strike_limit",
        default=3,
    )
    strikes_limit = max(1, late_cancel_strike_limit, no_show_strike_limit * 2)
    if view == CLIENT_CARD_INFO_VIEW:
        text = render_client_info_card(
            user,
            stats=stats,
            next_booking=next_bookings[0] if next_bookings else None,
            last_completed_booking=last_completed[0] if last_completed else None,
            tz_name=tz_name,
            confirmed_reminders=confirmed_reminders,
            total_reminders=total_reminders,
            duplicate_user=duplicate_user,
        )
        markup = build_admin_client_info_keyboard(
            user_id=user.id,
            duplicate_user_id=duplicate_user.id if duplicate_user is not None else None,
            back_callback=back_callback,
        )
    elif view == CLIENT_CARD_MODERATION_VIEW:
        text = render_client_moderation_card(
            user,
            strikes_limit=strikes_limit,
        )
        markup = build_admin_client_moderation_keyboard(
            user_id=user.id,
            is_blocked=user.is_blocked,
            is_shadow_banned=user.is_shadow_banned,
            requires_manual_approval=user.requires_manual_approval,
            back_callback=back_callback,
        )
    elif view == CLIENT_CARD_BOOKINGS_VIEW:
        completed_bookings = await booking_repository.list_recent_completed_for_client(
            user.id,
            limit=10,
        )
        text = render_client_bookings_card(
            user,
            active_bookings=next_bookings,
            completed_bookings=completed_bookings,
            tz_name=tz_name,
        )
        markup = build_admin_client_bookings_keyboard(
            user_id=user.id,
            active_bookings=next_bookings,
            completed_bookings=completed_bookings,
            tz_name=tz_name,
            back_callback=back_callback,
        )
    else:
        text = render_client_main_card(
            user,
            next_booking=next_bookings[0] if next_bookings else None,
            tz_name=tz_name,
            strikes_limit=strikes_limit,
        )
        markup = build_admin_client_main_keyboard(
            user_id=user.id,
            back_callback=back_callback,
        )
    if notice_text:
        text = f"{notice_text}\n\n{text}"
    return text, markup


@router.message(lambda message: message.text == "👥 Клиенты")
async def open_clients_section(
    message: Message,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Open the clients section home screen."""
    if not is_admin:
        return
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await show_clients_home(message, state=state)


@router.callback_query(F.data == "admin_clients:home")
async def open_clients_home_callback(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Return to the clients section home screen."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    if callback.message is not None:
        await show_clients_home(callback.message, edit=True, state=state)


@router.callback_query(F.data == "admin_clients:noop")
async def noop_clients_callback(
    callback: CallbackQuery,
    *,
    is_admin: bool,
) -> None:
    """Acknowledge a non-action pagination button."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data == "admin_clients:search")
async def prompt_client_search(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Switch the clients section into search mode."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminClients.input_query)
    if callback.message is not None:
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_CLIENTS_PROMPT_TEXT,
            reply_markup=build_admin_clients_back_keyboard(),
        )


@router.callback_query(F.data.startswith("admin_clients:list:"))
async def open_clients_list_page(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Open one page from the full clients list."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    await state.clear()
    page = int(callback.data.rsplit(":", 1)[-1])
    if callback.message is not None:
        await show_clients_page(callback.message, db_session=db_session, page=page, edit=True)


@router.message(StateFilter(AdminClients.input_query))
async def search_clients(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Search clients by name or username."""
    query = (message.text or "").strip()
    await state.clear()
    repository = UserRepository(db_session)
    users = await repository.search_clients(query)
    if not users:
        await message.answer(
            texts.ADMIN_CLIENTS_EMPTY_TEXT,
            reply_markup=build_admin_clients_back_keyboard(),
        )
        return

    if len(users) == 1:
        await show_client_card(
            message,
            db_session=db_session,
            settings=settings,
            client_id=users[0].id,
        )
        return

    await message.answer(
        texts.ADMIN_CLIENTS_PICK_TEXT,
        reply_markup=build_admin_client_search_results_keyboard(
            [(user.id, render_client_search_label(user)) for user in users],
        ),
    )


@router.callback_query(F.data.startswith("admin_clients:open:"))
async def open_client_card(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open a client card from a button."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(":")
    client_id = int(parts[2])
    _, back_callback = parse_client_view_and_return_callback(parts, start_index=3)
    if callback.message is not None:
        await show_client_card(
            callback.message,
            db_session=db_session,
            settings=settings,
            client_id=client_id,
            back_callback=back_callback,
            edit=True,
        )


@router.callback_query(F.data.startswith("admin_clients:info:"))
async def open_client_info_card(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the secondary info screen for one client."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(":")
    client_id = int(parts[2])
    back_callback = parse_return_callback(parts, start_index=3)
    if callback.message is not None:
        await show_client_card(
            callback.message,
            db_session=db_session,
            settings=settings,
            client_id=client_id,
            back_callback=back_callback,
            view=CLIENT_CARD_INFO_VIEW,
            edit=True,
        )


@router.callback_query(F.data.startswith("admin_clients:moderation:"))
async def open_client_moderation_card(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the dedicated moderation screen for one client."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(":")
    client_id = int(parts[2])
    back_callback = parse_return_callback(parts, start_index=3)
    if callback.message is not None:
        await show_client_card(
            callback.message,
            db_session=db_session,
            settings=settings,
            client_id=client_id,
            back_callback=back_callback,
            view=CLIENT_CARD_MODERATION_VIEW,
            edit=True,
        )


@router.callback_query(F.data.startswith("admin_clients:bookings:"))
async def open_client_bookings_card(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the lightweight bookings-history screen for one client."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(":")
    client_id = int(parts[2])
    back_callback = parse_return_callback(parts, start_index=3)
    if callback.message is not None:
        await show_client_card(
            callback.message,
            db_session=db_session,
            settings=settings,
            client_id=client_id,
            back_callback=back_callback,
            view=CLIENT_CARD_BOOKINGS_VIEW,
            edit=True,
        )


@router.callback_query(F.data.startswith("admin_clients:manual_book:"))
async def open_manual_booking_from_client_card(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Start manual booking with the selected client already chosen."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    parts = callback.data.split(":")
    client_id = int(parts[2])
    started = await start_manual_booking_for_client(
        callback.message,
        state,
        db_session=db_session,
        client_id=client_id,
    )
    if not started:
        await replace_inline_message_text(callback.message, "Не нашла эту клиентку.")


@router.callback_query(F.data.startswith("admin_clients:note:"))
async def prompt_client_note(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Prompt for a new client note."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(":")
    client_id = int(parts[2])
    view, back_callback = parse_client_view_and_return_callback(parts, start_index=3)
    await state.set_state(AdminClients.input_note)
    await state.update_data(
        admin_client_edit_id=client_id,
        admin_client_return_callback=back_callback,
        admin_client_return_view=view,
    )
    if callback.message is not None:
        await remember_admin_panel(state, callback.message)
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_CLIENT_NOTE_PROMPT_TEXT,
            reply_markup=build_admin_clients_back_keyboard(
                build_client_view_callback(
                    client_id=client_id,
                    view=view,
                    back_callback=back_callback,
                )
            ),
        )


@router.message(StateFilter(AdminClients.input_note))
async def save_client_note(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Save a new client note."""
    data = await state.get_data()
    client_id = int(data.get("admin_client_edit_id"))
    back_callback = str(data.get("admin_client_return_callback") or "admin_clients:home")
    view = str(data.get("admin_client_return_view") or CLIENT_CARD_MAIN_VIEW)
    panel_chat_id = data.get(ADMIN_PANEL_CHAT_ID_KEY)
    panel_message_id = data.get(ADMIN_PANEL_MESSAGE_ID_KEY)
    note_raw = (message.text or "").strip()
    note = None if note_raw in {"", "-", "—"} else note_raw
    repository = UserRepository(db_session)
    user = await repository.get_by_id(client_id)
    if user is None:
        await message.answer("Не нашла эту клиентку.")
        await state.clear()
        return

    await repository.update_profile(user, note=note)
    await db_session.commit()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    if panel_chat_id and panel_message_id:
        panel = await build_client_card_panel(
            db_session=db_session,
            settings=settings,
            client_id=user.id,
            back_callback=back_callback,
            view=view,
            notice_text=texts.ADMIN_CLIENT_NOTE_SAVED_TEXT,
        )
        if panel is not None:
            text, markup = panel
            panel_ref = await upsert_inline_panel(
                message.bot,
                chat_id=int(panel_chat_id),
                message_id=int(panel_message_id),
                text=text,
                reply_markup=markup,
            )
            await remember_admin_panel(state, panel_ref)
            return
    await show_client_card(
        message,
        db_session=db_session,
        settings=settings,
        client_id=user.id,
        back_callback=back_callback,
        view=view,
        notice_text=texts.ADMIN_CLIENT_NOTE_SAVED_TEXT,
    )


@router.callback_query(F.data.startswith("admin_clients:message:"))
async def prompt_client_message(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Prompt for a direct admin message to the client."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(":")
    client_id = int(parts[2])
    repository = UserRepository(db_session)
    user = await repository.get_by_id(client_id)
    if user is None:
        if callback.message is not None:
            await callback.message.answer("Не нашла эту клиентку.")
        return

    view, back_callback = parse_client_view_and_return_callback(parts, start_index=3)

    await state.set_state(AdminClientMessage.input_message)
    await state.update_data(
        admin_client_message_id=user.id,
        admin_client_message_tg_id=user.tg_id,
        admin_client_return_callback=back_callback,
        admin_client_return_view=view,
    )
    if callback.message is not None:
        await remember_admin_panel(state, callback.message)
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_CLIENT_MESSAGE_PROMPT_TEXT,
            reply_markup=build_admin_clients_back_keyboard(
                build_client_view_callback(
                    client_id=user.id,
                    view=view,
                    back_callback=back_callback,
                )
            ),
        )


@router.message(StateFilter(AdminClientMessage.input_message))
async def send_client_message(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Copy one admin message directly to the selected client."""
    data = await state.get_data()
    target_tg_id = data.get("admin_client_message_tg_id")
    client_id = data.get("admin_client_message_id")
    back_callback = str(data.get("admin_client_return_callback") or "admin_clients:home")
    view = str(data.get("admin_client_return_view") or CLIENT_CARD_MAIN_VIEW)
    panel_chat_id = data.get(ADMIN_PANEL_CHAT_ID_KEY)
    panel_message_id = data.get(ADMIN_PANEL_MESSAGE_ID_KEY)
    booking_card_id = data.get("admin_booking_card_id")
    booking_card_back_callback = str(data.get("admin_booking_card_back_callback") or "admin_menu:home")
    if not target_tg_id or not client_id:
        await state.clear()
        await message.answer("Не нашла получателя.")
        return

    try:
        await message.bot.copy_message(
            chat_id=int(target_tg_id),
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        await message.answer("Не получилось доставить сообщение.")
        return

    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    if panel_chat_id and panel_message_id:
        if booking_card_id:
            panel = await build_booking_card_panel(
                db_session=db_session,
                settings=settings,
                booking_id=int(booking_card_id),
                back_callback=booking_card_back_callback,
                notice_text=texts.ADMIN_CLIENT_MESSAGE_SENT_TEXT,
            )
            if panel is not None:
                text, markup = panel
                panel_ref = await upsert_inline_panel(
                    message.bot,
                    chat_id=int(panel_chat_id),
                    message_id=int(panel_message_id),
                    text=text,
                    reply_markup=markup,
                )
                await remember_admin_panel(state, panel_ref)
                return
        panel = await build_client_card_panel(
            db_session=db_session,
            settings=settings,
            client_id=int(client_id),
            back_callback=back_callback,
            view=view,
            notice_text=texts.ADMIN_CLIENT_MESSAGE_SENT_TEXT,
        )
        if panel is not None:
            text, markup = panel
            panel_ref = await upsert_inline_panel(
                message.bot,
                chat_id=int(panel_chat_id),
                message_id=int(panel_message_id),
                text=text,
                reply_markup=markup,
            )
            await remember_admin_panel(state, panel_ref)
            return
    await show_client_card(
        message,
        db_session=db_session,
        settings=settings,
        client_id=int(client_id),
        back_callback=back_callback,
        view=view,
        notice_text=texts.ADMIN_CLIENT_MESSAGE_SENT_TEXT,
    )


@router.callback_query(F.data.startswith("admin_clients:confirm:"))
async def confirm_client_risky_action(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Ask for explicit confirmation before risky client-card actions."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    parts = callback.data.split(":")
    action = parts[2]
    client_id = int(parts[3])
    view, back_callback = parse_client_view_and_return_callback(parts, start_index=4)
    repository = UserRepository(db_session)
    user = await repository.get_by_id(client_id)
    if user is None:
        await replace_inline_message_text(callback.message, "Не нашла эту клиентку.")
        return
    action_titles = {
        "block": "заблокировать клиентку",
        "unblock": "разблокировать клиентку",
        "shadow_ban": "включить shadow-ban",
        "shadow_unban": "снять shadow-ban",
        "reset_strikes": "сбросить strikes",
    }
    await replace_inline_message_text(
        callback.message,
        (
            "Подтверди действие\n\n"
            f"👤 {user.display_name}\n"
            f"Действие: {action_titles.get(action, action)}"
        ),
        reply_markup=build_admin_client_confirm_action_keyboard(
            action=action,
            user_id=client_id,
            view=view,
            back_callback=back_callback,
        ),
    )


@router.callback_query(F.data.startswith("admin_clients:block:"))
@router.callback_query(F.data.startswith("admin_clients:unblock:"))
async def toggle_client_block(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Toggle the blocked flag for a client."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(":")
    action = parts[1]
    client_id = int(parts[2])
    view, back_callback = parse_client_view_and_return_callback(parts, start_index=3)
    repository = UserRepository(db_session)
    user = await repository.get_by_id(client_id)
    if user is None:
        if callback.message is not None:
            await callback.message.answer("Не нашла эту клиентку.")
        return

    user.is_blocked = action == "block"
    await db_session.commit()
    if callback.message is not None:
        await show_client_card(
            callback.message,
            db_session=db_session,
            settings=settings,
            client_id=user.id,
            back_callback=back_callback,
            view=view,
            edit=True,
            notice_text=(
                texts.ADMIN_CLIENT_BLOCKED_TEXT
                if user.is_blocked
                else texts.ADMIN_CLIENT_UNBLOCKED_TEXT
            ),
        )


@router.callback_query(F.data.startswith("admin_clients:shadow_ban:"))
@router.callback_query(F.data.startswith("admin_clients:shadow_unban:"))
async def toggle_client_shadow_ban(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Toggle the client's shadow-ban flag."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(":")
    action = parts[1]
    client_id = int(parts[2])
    view, back_callback = parse_client_view_and_return_callback(parts, start_index=3)
    repository = UserRepository(db_session)
    user = await repository.get_by_id(client_id)
    if user is None:
        return
    user.is_shadow_banned = action == "shadow_ban"
    await db_session.commit()
    if callback.message is not None:
        await show_client_card(
            callback.message,
            db_session=db_session,
            settings=settings,
            client_id=user.id,
            back_callback=back_callback,
            view=view,
            edit=True,
            notice_text=(
                texts.ADMIN_CLIENT_SHADOW_BANNED_TEXT
                if user.is_shadow_banned
                else texts.ADMIN_CLIENT_SHADOW_UNBANNED_TEXT
            ),
        )


@router.callback_query(F.data.startswith("admin_clients:reset_strikes:"))
async def reset_client_strikes(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Reset the client's strike counter."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(":")
    client_id = int(parts[2])
    view, back_callback = parse_client_view_and_return_callback(parts, start_index=3)
    repository = UserRepository(db_session)
    user = await repository.get_by_id(client_id)
    if user is None:
        return
    user.strikes = 0
    await db_session.commit()
    if callback.message is not None:
        await show_client_card(
            callback.message,
            db_session=db_session,
            settings=settings,
            client_id=user.id,
            back_callback=back_callback,
            view=view,
            edit=True,
            notice_text=texts.ADMIN_CLIENT_STRIKES_RESET_TEXT,
        )


@router.callback_query(F.data.startswith("admin_clients:set_manual:"))
@router.callback_query(F.data.startswith("admin_clients:clear_manual:"))
async def toggle_client_manual_approval(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Toggle the manual-approval requirement for a client."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(":")
    action = parts[1]
    client_id = int(parts[2])
    view, back_callback = parse_client_view_and_return_callback(parts, start_index=3)
    repository = UserRepository(db_session)
    user = await repository.get_by_id(client_id)
    if user is None:
        return
    user.requires_manual_approval = action == "set_manual"
    await db_session.commit()
    if callback.message is not None:
        await show_client_card(
            callback.message,
            db_session=db_session,
            settings=settings,
            client_id=user.id,
            back_callback=back_callback,
            view=view,
            edit=True,
            notice_text=(
                texts.ADMIN_CLIENT_MANUAL_APPROVAL_SET_TEXT
                if user.requires_manual_approval
                else texts.ADMIN_CLIENT_MANUAL_APPROVAL_CLEARED_TEXT
            ),
        )
