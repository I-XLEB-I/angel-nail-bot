from __future__ import annotations

from aiogram.enums import ButtonStyle
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from src.db.models import (
    ApprovalRequestKind,
    Booking,
    BookingStatus,
    Service,
    ServiceKind,
    Slot,
    SlotStatus,
)
from src.services.admin_defaults import TemplateCategory, TemplateDefinition
from src.services.booking import format_local_datetime, format_service_price
from src.services.button_configs import (
    BUTTON_STYLE_DANGER,
    BUTTON_STYLE_DEFAULT,
    BUTTON_STYLE_PRIMARY,
    BUTTON_STYLE_SUCCESS,
    NAVIGATION_CUSTOM_EMOJI_ID,
    ButtonEditorCategory,
    ClientMenuButtonConfig,
    EditableButtonDefinition,
    resolve_button_style,
)
from src.services.rich_messages import RICH_PREVIEW_DEFINITIONS

SLOT_STATUS_ICONS = {
    SlotStatus.FREE: "🟢",
    SlotStatus.BOOKED: "🔴",
    SlotStatus.BLOCKED: "⚫️",
}


def nav_button(text: str, callback_data: str) -> InlineKeyboardButton:
    """Build a visually consistent admin back/menu/cancel button."""
    parts = text.split(" ", 1)
    normalized_text = (
        parts[1] if len(parts) == 2 and not any(char.isalnum() for char in parts[0]) else text
    )
    return InlineKeyboardButton(
        text=normalized_text,
        callback_data=callback_data,
        style=ButtonStyle.DANGER,
        icon_custom_emoji_id=NAVIGATION_CUSTOM_EMOJI_ID,
    )


def build_admin_main_menu(
    *,
    pending_approvals: int,
    rich_messages_test_enabled: bool = False,
) -> ReplyKeyboardMarkup:
    """Build the main admin reply keyboard."""
    keyboard = [
        [KeyboardButton(text="📅 Расписание"), KeyboardButton(text="📋 Все записи")],
        [KeyboardButton(text="🗓 Статусы на сегодня")],
        [
            KeyboardButton(text=f"📥 Запросы ({pending_approvals})"),
            KeyboardButton(text="💼 Услуги"),
        ],
        [
            KeyboardButton(text="👥 Клиенты"),
            KeyboardButton(text="📊 Статистика"),
        ],
        [KeyboardButton(text="✉️ Рассылка")],
    ]
    if rich_messages_test_enabled:
        keyboard.append([KeyboardButton(text="🧪 Rich тест")])
    keyboard.extend(
        [
            [
                KeyboardButton(text="📝 Шаблоны"),
                KeyboardButton(text="⚙️ Настройки"),
            ],
            [KeyboardButton(text="🎛 Кнопки"), KeyboardButton(text="✨ Emoji ID")],
            [KeyboardButton(text="➕ Ручная запись")],
            [KeyboardButton(text="🙈 Режим клиента")],
        ]
    )
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def build_admin_all_bookings_keyboard(
    bookings: list[Booking],
    *,
    offset_days: int,
    show_cancelled: bool,
    has_prev: bool,
    has_next: bool,
    tz_name: str,
) -> InlineKeyboardMarkup:
    """Build controls for the admin all-bookings screen."""
    rows: list[list[InlineKeyboardButton]] = []
    booking_buttons: list[InlineKeyboardButton] = []
    for booking in bookings:
        if booking.slot is None or booking.client is None:
            continue
        local_dt = format_local_datetime(booking.slot.start_at, tz_name)
        client_label = booking.client.display_name.strip() or "Клиентка"
        short_name = client_label.split()[0][:18]
        booking_buttons.append(
            InlineKeyboardButton(
                text=f"{local_dt:%H:%M} · {short_name}",
                callback_data=build_admin_booking_card_callback(
                    booking.id,
                    back_callback=f"admin_bookings:page:{offset_days}:{int(show_cancelled)}",
                ),
            )
        )

    for index in range(0, len(booking_buttons), 2):
        rows.append(booking_buttons[index : index + 2])

    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(
            InlineKeyboardButton(
                text="← 14 дней назад",
                callback_data=(
                    f"admin_bookings:page:{max(0, offset_days - 14)}:{int(show_cancelled)}"
                ),
            )
        )
    if has_next:
        nav_row.append(
            InlineKeyboardButton(
                text="14 дней вперёд →",
                callback_data=f"admin_bookings:page:{offset_days + 14}:{int(show_cancelled)}",
            )
        )
    if nav_row:
        rows.append(nav_row)

    toggle_text = "🙈 Скрыть отменённые" if show_cancelled else "👁 Показать отменённые"
    rows.append(
        [
            InlineKeyboardButton(
                text=toggle_text,
                callback_data=f"admin_bookings:toggle_cancelled:{offset_days}",
            )
        ]
    )
    if bookings:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📊 Сводка периода",
                    callback_data=f"admin_bookings:summary:{offset_days}:{int(show_cancelled)}",
                )
            ]
        )
    rows.append([nav_button("⬅️ Назад", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_all_bookings_delete_period_keyboard(
    *,
    offset_days: int,
    show_cancelled: bool,
) -> InlineKeyboardMarkup:
    """Build confirmation controls for removing the current bookings period."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Да, удалить",
                    callback_data=(
                        f"admin_bookings:delete_period_confirm:{offset_days}:{int(show_cancelled)}"
                    ),
                    style=ButtonStyle.DANGER,
                )
            ],
            [
                nav_button(
                    "⬅️ Не удалять",
                    f"admin_bookings:page:{offset_days}:{int(show_cancelled)}",
                )
            ],
        ]
    )


def build_admin_all_bookings_summary_keyboard(
    *,
    offset_days: int,
    show_cancelled: bool,
) -> InlineKeyboardMarkup:
    """Build the back navigation from one all-bookings summary screen."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                nav_button(
                    "⬅️ К записям",
                    f"admin_bookings:page:{offset_days}:{int(show_cancelled)}",
                )
            ],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_schedule_menu() -> InlineKeyboardMarkup:
    """Build the schedule submenu keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить окошки",
                    callback_data="admin_schedule:add",
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить окошки",
                    callback_data="admin_schedule:delete_menu",
                    style=ButtonStyle.DANGER,
                )
            ],
            [
                InlineKeyboardButton(text="📆 На неделю", callback_data="admin_schedule:week"),
                InlineKeyboardButton(text="📅 На месяц", callback_data="admin_schedule:month"),
            ],
            [nav_button("⬅️ В меню", "admin_menu:home")],
        ]
    )


def build_admin_schedule_delete_menu() -> InlineKeyboardMarkup:
    """Build the schedule bulk-delete period picker."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📆 Удалить за 7 дней",
                    callback_data="admin_schedule:delete_period:week",
                    style=ButtonStyle.DANGER,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 Удалить за 30 дней",
                    callback_data="admin_schedule:delete_period:month",
                    style=ButtonStyle.DANGER,
                )
            ],
            [nav_button("⬅️ К расписанию", "admin_schedule:back")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_schedule_delete_confirm_keyboard(
    *,
    slot_id: int,
    origin_view: str,
    origin_value: int,
) -> InlineKeyboardMarkup:
    """Build confirmation controls before deleting a schedule slot."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Да, удалить",
                    callback_data=(
                        f"admin_schedule:delete_confirm:{slot_id}:{origin_view}:{origin_value}"
                    ),
                    style=ButtonStyle.DANGER,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Не удалять",
                    callback_data=f"admin_schedule:slot:{slot_id}:{origin_view}:{origin_value}",
                )
            ],
        ]
    )


def build_admin_schedule_delete_period_confirm_keyboard(period_kind: str) -> InlineKeyboardMarkup:
    """Build confirmation controls before bulk-removing schedule slots."""
    back_callback = "admin_schedule:week" if period_kind == "week" else "admin_schedule:month"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Да, удалить",
                    callback_data=f"admin_schedule:delete_period_confirm:{period_kind}",
                    style=ButtonStyle.DANGER,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Не удалять",
                    callback_data=back_callback,
                )
            ],
        ]
    )


def build_admin_emoji_id_keyboard() -> InlineKeyboardMarkup:
    """Build controls for the premium-emoji id helper."""
    return InlineKeyboardMarkup(inline_keyboard=[[nav_button("⬅️ В меню", "admin_emoji_id:back")]])


def build_admin_button_list_keyboard(
    items: list[tuple[EditableButtonDefinition, ClientMenuButtonConfig]],
    *,
    category_key: str,
) -> InlineKeyboardMarkup:
    """Build the list of editable buttons inside one category."""
    rows: list[list[InlineKeyboardButton]] = []
    for definition, config in items:
        kwargs: dict[str, object] = {
            "text": config.text,
            "callback_data": f"admin_buttons:open:{definition.editor_id}",
            "icon_custom_emoji_id": config.icon_custom_emoji_id,
        }
        style = resolve_button_style(config.style_name)
        if style is not None:
            kwargs["style"] = style
        rows.append([InlineKeyboardButton(**kwargs)])
    rows.append([nav_button("⬅️ К разделам", "admin_buttons:categories")])
    rows.append([nav_button("⬅️ В меню", "admin_buttons:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_button_categories_keyboard(
    categories: list[ButtonEditorCategory],
) -> InlineKeyboardMarkup:
    """Build the top-level category picker for the button editor."""
    rows = [
        [
            InlineKeyboardButton(
                text=category.title,
                callback_data=f"admin_buttons:category:{category.key}",
            )
        ]
        for category in categories
    ]
    rows.append([nav_button("⬅️ В меню", "admin_buttons:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_button_detail_keyboard(
    *,
    definition: EditableButtonDefinition,
    config: ClientMenuButtonConfig,
) -> InlineKeyboardMarkup:
    """Build the editor keyboard for one selected client-menu button."""
    preview_kwargs: dict[str, object] = {
        "text": config.text,
        "callback_data": "admin_buttons:noop",
        "icon_custom_emoji_id": config.icon_custom_emoji_id,
    }
    preview_style = resolve_button_style(config.style_name)
    if preview_style is not None:
        preview_kwargs["style"] = preview_style

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(**preview_kwargs)],
        [
            InlineKeyboardButton(
                text="✏️ Изменить текст",
                callback_data=f"admin_buttons:text:{definition.editor_id}",
            ),
            InlineKeyboardButton(
                text="✨ Изменить premium emoji",
                callback_data=f"admin_buttons:emoji:{definition.editor_id}",
            ),
        ],
    ]
    if definition.url is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔗 Изменить ссылку",
                    callback_data=f"admin_buttons:url:{definition.editor_id}",
                ),
                InlineKeyboardButton(
                    text="↺ Сбросить ссылку",
                    callback_data=f"admin_buttons:url_reset:{definition.editor_id}",
                ),
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="🔵 Синий",
                    callback_data=f"admin_buttons:style:{definition.editor_id}:{BUTTON_STYLE_PRIMARY}",
                ),
                InlineKeyboardButton(
                    text="🟢 Зелёный",
                    callback_data=f"admin_buttons:style:{definition.editor_id}:{BUTTON_STYLE_SUCCESS}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔴 Красный",
                    callback_data=f"admin_buttons:style:{definition.editor_id}:{BUTTON_STYLE_DANGER}",
                ),
                InlineKeyboardButton(
                    text="⚪️ Обычный",
                    callback_data=f"admin_buttons:style:{definition.editor_id}:{BUTTON_STYLE_DEFAULT}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="♻️ Убрать premium emoji",
                    callback_data=f"admin_buttons:clear_emoji:{definition.editor_id}",
                ),
                InlineKeyboardButton(
                    text="↺ Сбросить всё",
                    callback_data=f"admin_buttons:reset:{definition.editor_id}",
                ),
            ],
            [nav_button("⬅️ К разделу", f"admin_buttons:category:{definition.category_key}")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_button_prompt_keyboard(editor_id: str) -> InlineKeyboardMarkup:
    """Build a small back keyboard while waiting for admin input."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [nav_button("⬅️ К кнопке", f"admin_buttons:open:{editor_id}")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_schedule_image_viewer_keyboard(
    *,
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Build controls under the admin schedule preview image."""
    rows: list[list[InlineKeyboardButton]] = []

    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if current_page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"admin_schedule:image_page:{current_page - 1}",
                )
            )
        nav_row.append(
            InlineKeyboardButton(
                text=f"Стр. {current_page + 1}/{total_pages}",
                callback_data="admin_schedule:noop",
            )
        )
        if current_page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"admin_schedule:image_page:{current_page + 1}",
                )
            )
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Добавить окошки",
                callback_data="admin_schedule:add",
                style=ButtonStyle.PRIMARY,
            )
        ],
    )
    rows.append(
        [
            InlineKeyboardButton(text="📆 На неделю", callback_data="admin_schedule:week"),
            InlineKeyboardButton(text="📅 На месяц", callback_data="admin_schedule:month"),
        ]
    )
    rows.append([nav_button("⬅️ В меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_schedule_preview_keyboard(*, allow_confirm: bool = True) -> InlineKeyboardMarkup:
    """Build the preview confirmation keyboard for parsed slots."""
    rows: list[list[InlineKeyboardButton]] = []
    if allow_confirm:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Добавить",
                    callback_data="admin_schedule:confirm",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="✏️ Исправить", callback_data="admin_schedule:retry")])
    rows.append([nav_button("❌ Отмена", "admin_schedule:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_schedule_input_keyboard() -> InlineKeyboardMarkup:
    """Build the keyboard while waiting for a new schedule text."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [nav_button("⬅️ Назад", "admin_schedule:cancel_input")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_schedule_back_keyboard() -> InlineKeyboardMarkup:
    """Build a compact back button to the root schedule menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [nav_button("⬅️ К расписанию", "admin_schedule:back")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_schedule_image_keyboard(
    *,
    enabled: bool,
    has_custom_background: bool,
) -> InlineKeyboardMarkup:
    """Build controls for the schedule-image settings screen."""
    toggle_label = "✅ Картинка включена" if enabled else "🚫 Картинка выключена"
    toggle_style = ButtonStyle.SUCCESS if enabled else ButtonStyle.DANGER
    rows = [
        [
            InlineKeyboardButton(
                text=toggle_label,
                callback_data="admin_schedule_image:toggle_enabled",
                style=toggle_style,
            )
        ],
        [
            InlineKeyboardButton(
                text="🖼 Загрузить картинку",
                callback_data="admin_schedule_image:upload_background",
                style=ButtonStyle.PRIMARY,
            )
        ],
    ]
    if has_custom_background:
        rows.append(
            [
                InlineKeyboardButton(
                    text="♻️ Сбросить картинку",
                    callback_data="admin_schedule_image:reset_background",
                    style=ButtonStyle.DANGER,
                )
            ]
        )
    rows.append([nav_button("⬅️ К расписанию", "admin_schedule:back")])
    rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_backgrounds_home_keyboard() -> InlineKeyboardMarkup:
    """Build a compact entry keyboard for background-related admin screens."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗓 Картинка расписания",
                    callback_data="admin_schedule:image",
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [nav_button("⬅️ Назад", "admin_menu:home")],
        ]
    )


def build_admin_schedule_week_keyboard(
    slots: list[Slot],
    *,
    page: int,
    tz_name: str,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    """Build the weekly schedule list with pagination and back navigation."""
    rows = [
        [
            InlineKeyboardButton(
                text=render_week_slot_text(slot, tz_name=tz_name),
                callback_data=f"admin_schedule:slot:{slot.id}:week:{page}",
            )
        ]
        for slot in slots
    ]

    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"admin_schedule:week:{page - 1}")
        )
    nav_row.append(
        InlineKeyboardButton(
            text=f"Стр. {page + 1}",
            callback_data="admin_schedule:noop",
        )
    )
    if has_next:
        nav_row.append(
            InlineKeyboardButton(text="➡️", callback_data=f"admin_schedule:week:{page + 1}")
        )
    if len(slots) > 1 or has_prev or has_next:
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="🗑 Удалить окошки за 7 дней",
                callback_data="admin_schedule:delete_period:week",
                style=ButtonStyle.DANGER,
            )
        ]
    )
    rows.append([nav_button("⬅️ К расписанию", "admin_schedule:back")])
    rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_schedule_slot_detail_keyboard(
    slot: Slot,
    *,
    origin_view: str,
    origin_value: int,
) -> InlineKeyboardMarkup:
    """Build the action keyboard for one slot inside the schedule views."""
    if origin_view == "month":
        back_label = "⬅️ К месяцу"
        back_callback = f"admin_schedule:month:page:{origin_value}"
    else:
        back_label = "⬅️ К неделе"
        back_callback = f"admin_schedule:week:{origin_value}"

    rows: list[list[InlineKeyboardButton]] = []
    if slot.status == SlotStatus.BOOKED:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📖 Открыть запись",
                    callback_data=(
                        f"admin_schedule:open_booking:{slot.id}:{origin_view}:{origin_value}"
                    ),
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="👤 Клиентка",
                    callback_data=f"admin_schedule:open_client:{slot.id}:{origin_view}:{origin_value}",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="⚠️ Не пришла",
                    callback_data=f"admin_schedule:no_show:{slot.id}:{origin_view}:{origin_value}",
                    style=ButtonStyle.DANGER,
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✏️ Перенести",
                    callback_data=f"admin_schedule:move:{slot.id}:{origin_view}:{origin_value}",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="❌ Удалить",
                    callback_data=f"admin_schedule:delete:{slot.id}:{origin_view}:{origin_value}",
                    style=ButtonStyle.DANGER,
                )
            ]
        )
        if slot.status == SlotStatus.BLOCKED:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="🟢 Разблокировать",
                        callback_data=(
                            f"admin_schedule:unblock:{slot.id}:{origin_view}:{origin_value}"
                        ),
                        style=ButtonStyle.SUCCESS,
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="🚫 Заблокировать",
                        callback_data=f"admin_schedule:block:{slot.id}:{origin_view}:{origin_value}",
                        style=ButtonStyle.DANGER,
                    )
                ]
            )

    rows.append([nav_button(back_label, back_callback)])
    rows.append([nav_button("🏠 К расписанию", "admin_schedule:back")])
    rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_schedule_month_keyboard(
    *,
    offset: int,
    total_days: int,
    page_size: int,
    slots_page: list[Slot] | None = None,
    tz_name: str = "UTC",
) -> InlineKeyboardMarkup:
    """Build pagination controls for the 30-day admin schedule view.

    Each slot visible on the current page gets its own clickable button so the
    admin can drill into the slot-detail card (same as the weekly view).
    """
    rows: list[list[InlineKeyboardButton]] = []

    # Per-slot buttons — one row per slot, click opens the detail card.
    if slots_page:
        for slot in slots_page:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=render_week_slot_text(slot, tz_name=tz_name),
                        callback_data=f"admin_schedule:slot:{slot.id}:month:{offset}",
                    )
                ]
            )

    nav_row: list[InlineKeyboardButton] = []
    if offset > 0:
        previous_offset = max(0, offset - page_size)
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"admin_schedule:month:page:{previous_offset}",
            )
        )
    nav_row.append(
        InlineKeyboardButton(
            text=f"Дни {offset + 1}-{min(offset + page_size, total_days)}",
            callback_data="admin_schedule:noop",
        )
    )
    if offset + page_size < total_days:
        nav_row.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"admin_schedule:month:page:{offset + page_size}",
            )
        )
    if total_days > page_size:
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="🗑 Удалить окошки за 30 дней",
                callback_data="admin_schedule:delete_period:month",
                style=ButtonStyle.DANGER,
            )
        ]
    )
    rows.append([nav_button("⬅️ К расписанию", "admin_schedule:back")])
    rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_approval_actions_keyboard(
    *,
    approval_id: int,
    kind: ApprovalRequestKind,
    can_direct_confirm: bool = False,
    include_back: bool = False,
    repair_warranty_marked: bool = False,
    repair_paid_marked: bool = False,
) -> InlineKeyboardMarkup:
    """Build actions for an approval-request card."""
    if kind == ApprovalRequestKind.QUESTION:
        rows = [
            [
                InlineKeyboardButton(
                    text="💬 Ответить",
                    callback_data=f"approval:reply:{approval_id}",
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="✅ Прочитано",
                    callback_data=f"approval:read:{approval_id}",
                    style=ButtonStyle.SUCCESS,
                ),
            ]
        ]
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔕 Тихо закрыть",
                    callback_data=f"approval:quiet_close:{approval_id}",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="👤 Клиентка",
                    callback_data=f"approval:client:{approval_id}",
                )
            ]
        )
        if include_back:
            rows.append([nav_button("⬅️ К запросам", "admin_approvals:home")])
            rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    if kind == ApprovalRequestKind.REPAIR_REQUEST:
        warranty_text = "✅ По гарантии" if repair_warranty_marked else "🛡 По гарантии"
        paid_text = "✅ Платно" if repair_paid_marked else "💸 Платно"
        rows = [
            [
                InlineKeyboardButton(
                    text=warranty_text,
                    callback_data=f"approval:repair_warranty:{approval_id}",
                    style=ButtonStyle.SUCCESS if repair_warranty_marked else None,
                ),
                InlineKeyboardButton(
                    text=paid_text,
                    callback_data=f"approval:repair_paid:{approval_id}",
                    style=ButtonStyle.PRIMARY if repair_paid_marked else None,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗓 Предложить время",
                    callback_data=f"approval:offer_time:{approval_id}",
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="🕰 Своё время",
                    callback_data=f"approval:repair_offer_custom:{approval_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💬 Уточнить",
                    callback_data=f"approval:reply:{approval_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отказать",
                    callback_data=f"approval:decline:{approval_id}",
                    style=ButtonStyle.DANGER,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔕 Тихо закрыть",
                    callback_data=f"approval:quiet_close:{approval_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Клиентка",
                    callback_data=f"approval:client:{approval_id}",
                )
            ],
        ]
        if include_back:
            rows.append([nav_button("⬅️ К запросам", "admin_approvals:home")])
            rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    rows: list[list[InlineKeyboardButton]] = []
    if can_direct_confirm:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить это время",
                    callback_data=f"approval:confirm:{approval_id}",
                    style=ButtonStyle.SUCCESS,
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗓 Предложить другое время",
                    callback_data=f"approval:offer_time:{approval_id}",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗓 Подобрать время",
                    callback_data=f"approval:confirm:{approval_id}",
                    style=ButtonStyle.PRIMARY,
                ),
            ]
        )

    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="🕖 После 19",
                    callback_data=f"approval:quick_reply:{approval_id}:after_19",
                ),
                InlineKeyboardButton(
                    text="📅 Будни заняты",
                    callback_data=f"approval:quick_reply:{approval_id}:weekdays_busy",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💡 Дам 2 варианта",
                    callback_data=f"approval:quick_reply:{approval_id}:two_variants",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 Ответить текстом",
                    callback_data=f"approval:reply:{approval_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отказать",
                    callback_data=f"approval:decline:{approval_id}",
                    style=ButtonStyle.DANGER,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔕 Тихо закрыть",
                    callback_data=f"approval:quiet_close:{approval_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Клиентка",
                    callback_data=f"approval:client:{approval_id}",
                )
            ],
        ]
    )
    if include_back:
        rows.append([nav_button("⬅️ К запросам", "admin_approvals:home")])
        rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_decline_reason_keyboard(
    approval_id: int, *, include_back: bool = False
) -> InlineKeyboardMarkup:
    """Build the inline reason picker for declining a request."""
    rows = [
        [
            InlineKeyboardButton(
                text="⏰ Уже занято", callback_data=f"approval:decline_reason:{approval_id}:busy"
            )
        ],
        [
            InlineKeyboardButton(
                text="💤 Не успею физически",
                callback_data=f"approval:decline_reason:{approval_id}:physical",
            )
        ],
        [
            InlineKeyboardButton(
                text="📴 Это нерабочий день",
                callback_data=f"approval:decline_reason:{approval_id}:offday",
            )
        ],
        [
            InlineKeyboardButton(
                text="🔁 Повторная запись",
                callback_data=f"approval:decline_reason:{approval_id}:repeat_booking",
            )
        ],
        [
            InlineKeyboardButton(
                text="✏️ Другое", callback_data=f"approval:decline_other:{approval_id}"
            )
        ],
    ]
    if include_back:
        rows.append([nav_button("⬅️ К запросу", f"admin_approvals:open:{approval_id}")])
        rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_decline_confirm_keyboard(
    approval_id: int,
    *,
    reason_code: str,
) -> InlineKeyboardMarkup:
    """Build the second confirmation step for a canned decline reason."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, отказать",
                    callback_data=f"approval:decline_commit:{approval_id}:{reason_code}",
                    style=ButtonStyle.DANGER,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ К причинам",
                    callback_data=f"approval:decline:{approval_id}",
                )
            ],
        ]
    )


def build_admin_repair_decline_confirm_keyboard(approval_id: int) -> InlineKeyboardMarkup:
    """Build the second confirmation step for declining a repair warranty request."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, отказать",
                    callback_data=f"approval:repair_decline_commit:{approval_id}",
                    style=ButtonStyle.DANGER,
                )
            ],
            [nav_button("⬅️ К запросу", f"admin_approvals:open:{approval_id}")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_repair_warranty_force_keyboard(approval_id: int) -> InlineKeyboardMarkup:
    """Build the explicit override keyboard for over-limit warranty requests."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, по гарантии",
                    callback_data=f"approval:repair_warranty_force:{approval_id}",
                    style=ButtonStyle.DANGER,
                )
            ],
            [nav_button("⬅️ К запросу", f"admin_approvals:open:{approval_id}")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_decline_custom_confirm_keyboard(approval_id: int) -> InlineKeyboardMarkup:
    """Build the second confirmation step for a free-text decline reason."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, отказать",
                    callback_data=f"approval:decline_custom_commit:{approval_id}",
                    style=ButtonStyle.DANGER,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Изменить причину",
                    callback_data=f"approval:decline_other:{approval_id}",
                )
            ],
        ]
    )


def build_admin_approval_slot_keyboard(
    *,
    approval_id: int,
    slots: list[Slot],
    tz_name: str,
    exact_candidate_code: str | None = None,
    exact_candidate_label: str | None = None,
    include_back: bool = False,
    slot_callback_prefix: str = "approval:book_slot",
    custom_offer_callback: str | None = None,
) -> InlineKeyboardMarkup:
    """Build the slot picker keyboard for confirming an approval request.

    Pass ``slot_callback_prefix="approval:offer_slot"`` when the picked slot
    should trigger client-side confirmation rather than booking immediately.
    """
    rows: list[list[InlineKeyboardButton]] = []

    if exact_candidate_code and exact_candidate_label:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✨ Подтвердить {exact_candidate_label}",
                    callback_data=f"approval:book_exact:{approval_id}:{exact_candidate_code}",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )

    for slot in slots[:18]:
        local_dt = format_local_datetime(slot.start_at, tz_name)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{local_dt.strftime('%d.%m %H:%M')}",
                    callback_data=f"{slot_callback_prefix}:{approval_id}:{slot.id}",
                )
            ]
        )

    if custom_offer_callback:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🕰 Предложить своё время",
                    callback_data=custom_offer_callback,
                )
            ]
        )

    if include_back:
        rows.append([nav_button("⬅️ К запросу", f"admin_approvals:open:{approval_id}")])
        rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_proxy_reply_keyboard(approval_id: int) -> InlineKeyboardMarkup:
    """Build the keyboard for continuing a proxy-chat thread."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Ответить ещё", callback_data=f"approval:reply:{approval_id}"
                )
            ],
        ]
    )


def build_admin_proxy_reply_prompt_keyboard(approval_id: int) -> InlineKeyboardMarkup:
    """Build navigation while waiting for an admin proxy reply."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [nav_button("⬅️ К запросу", f"admin_approvals:open:{approval_id}")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_late_notice_keyboard(notice_id: int) -> InlineKeyboardMarkup:
    """Build actions for an admin late-arrival notice."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Клиентка",
                    callback_data=f"late_notice:client:{notice_id}",
                ),
                InlineKeyboardButton(
                    text="✅ Учла",
                    callback_data=f"late_notice:ack:{notice_id}",
                    style=ButtonStyle.SUCCESS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💬 Написать",
                    callback_data=f"late_notice:message:{notice_id}",
                    style=ButtonStyle.PRIMARY,
                )
            ],
        ]
    )


def build_admin_approvals_list_keyboard(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """Build the pending-approvals queue keyboard."""
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"admin_approvals:open:{approval_id}")]
        for approval_id, label in items
    ]
    rows.append([nav_button("⬅️ В меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_week_slot_keyboard(slot: Slot) -> InlineKeyboardMarkup:
    """Build actions for a slot in the weekly schedule view."""
    action_buttons = []
    if slot.status == SlotStatus.BOOKED:
        action_buttons.append(
            InlineKeyboardButton(
                text="📖 Открыть запись", callback_data=f"admin_schedule:open_booking:{slot.id}"
            )
        )
    else:
        action_buttons.append(
            InlineKeyboardButton(
                text="❌ Удалить",
                callback_data=f"admin_schedule:delete:{slot.id}",
                style=ButtonStyle.DANGER,
            )
        )

    block_button = (
        InlineKeyboardButton(
            text="🟢 Разблокировать",
            callback_data=f"admin_schedule:unblock:{slot.id}",
            style=ButtonStyle.SUCCESS,
        )
        if slot.status == SlotStatus.BLOCKED
        else InlineKeyboardButton(
            text="🚫 Заблокировать",
            callback_data=f"admin_schedule:block:{slot.id}",
            style=ButtonStyle.DANGER,
        )
    )
    action_buttons.append(block_button)
    return InlineKeyboardMarkup(inline_keyboard=[action_buttons])


def build_admin_booking_card_callback(booking_id: int, *, back_callback: str) -> str:
    """Encode one booking-card open callback while preserving its parent screen."""
    suffix = _encode_admin_booking_card_back_suffix(back_callback)
    return f"admin_booking_card:open:{booking_id}:{suffix}"


def _encode_admin_booking_card_back_suffix(back_callback: str) -> str:
    """Encode the parent screen for booking-card actions and back navigation."""
    if back_callback.startswith("admin_bookings:page:"):
        _, _, offset_days, show_cancelled = back_callback.split(":")
        return f"all:{offset_days}:{show_cancelled}"
    if back_callback.startswith("admin_clients:bookings:"):
        parts = back_callback.split(":")
        client_id = parts[2]
        suffix = ":".join(parts[3:]) if len(parts) > 3 else "home"
        return f"client:{client_id}:{suffix}"
    return "home"


def build_admin_booking_card_action_callback(
    action: str,
    *,
    booking_id: int,
    back_callback: str,
    client_id: int | None = None,
) -> str:
    """Encode one booking-card action callback while preserving parent context."""
    suffix = _encode_admin_booking_card_back_suffix(back_callback)
    if client_id is None:
        return f"admin_booking_card:{action}:{booking_id}:{suffix}"
    return f"admin_booking_card:{action}:{booking_id}:{client_id}:{suffix}"


def build_admin_service_actions_keyboard(service: Service) -> InlineKeyboardMarkup:
    """Build actions for a single service card."""
    visibility_label = "👁 Показать" if not service.is_active else "🙈 Скрыть"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить", callback_data=f"admin_service:edit:{service.id}"
                ),
                InlineKeyboardButton(
                    text=visibility_label,
                    callback_data=f"admin_service:toggle:{service.id}",
                ),
                InlineKeyboardButton(
                    text="❌ Удалить",
                    callback_data=f"admin_service:delete:{service.id}",
                    style=ButtonStyle.DANGER,
                ),
            ]
        ]
    )


def build_admin_services_list_keyboard(services: list[Service]) -> InlineKeyboardMarkup:
    """Build the single-panel services list keyboard."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{service.name} · {format_service_price(service)}",
                callback_data=f"admin_service:open:{service.id}",
            )
        ]
        for service in services
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Добавить услугу",
                callback_data="admin_service:add",
                style=ButtonStyle.PRIMARY,
            )
        ]
    )
    rows.append([nav_button("⬅️ В меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_services_footer_keyboard() -> InlineKeyboardMarkup:
    """Build the footer keyboard under the service list."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить услугу",
                    callback_data="admin_service:add",
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [nav_button("⬅️ В меню", "admin_menu:home")],
        ]
    )


def build_admin_service_edit_fields_keyboard(service_id: int) -> InlineKeyboardMarkup:
    """Build the field picker for editing a service."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Название", callback_data=f"admin_service:field:{service_id}:name"
                ),
                InlineKeyboardButton(
                    text="Цена", callback_data=f"admin_service:field:{service_id}:price"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Длительность",
                    callback_data=f"admin_service:field:{service_id}:duration_min",
                ),
                InlineKeyboardButton(
                    text="Тип", callback_data=f"admin_service:field:{service_id}:kind"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Переменная цена",
                    callback_data=f"admin_service:field:{service_id}:price_variable",
                )
            ],
            [nav_button("⬅️ К услуге", f"admin_service:open:{service_id}")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_service_kind_keyboard(
    prefix: str, *, cancel_callback: str | None = None
) -> InlineKeyboardMarkup:
    """Build a kind-selection keyboard."""
    rows = [
        [
            InlineKeyboardButton(text="base", callback_data=f"{prefix}:base"),
            InlineKeyboardButton(text="addon", callback_data=f"{prefix}:addon"),
        ]
    ]
    if cancel_callback:
        rows.append([nav_button("⬅️ Отмена", cancel_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_service_variable_keyboard(
    prefix: str,
    *,
    cancel_callback: str | None = None,
) -> InlineKeyboardMarkup:
    """Build a yes/no keyboard for price variability."""
    rows = [
        [
            InlineKeyboardButton(text="Да", callback_data=f"{prefix}:true"),
            InlineKeyboardButton(text="Нет", callback_data=f"{prefix}:false"),
        ]
    ]
    if cancel_callback:
        rows.append([nav_button("⬅️ Отмена", cancel_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_service_create_confirm_keyboard(
    *,
    cancel_callback: str = "admin_service:create_cancel",
) -> InlineKeyboardMarkup:
    """Build the final confirm keyboard for service creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Сохранить",
                    callback_data="admin_service:create_confirm",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [nav_button("❌ Отмена", cancel_callback)],
        ]
    )


def build_admin_service_prompt_cancel_keyboard(
    callback_data: str = "admin_service:home",
) -> InlineKeyboardMarkup:
    """Build a compact cancel/back button for service input steps."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [nav_button("⬅️ Отмена", callback_data)],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_service_detail_keyboard(service: Service) -> InlineKeyboardMarkup:
    """Build the service-detail action keyboard with a back button."""
    visibility_label = "👁 Показать" if not service.is_active else "🙈 Скрыть"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data=f"admin_service:edit:{service.id}",
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text=visibility_label,
                    callback_data=f"admin_service:toggle:{service.id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Удалить",
                    callback_data=f"admin_service:delete:{service.id}",
                    style=ButtonStyle.DANGER,
                )
            ],
            [nav_button("⬅️ К услугам", "admin_service:home")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def render_service_admin_text(service: Service) -> str:
    """Render one service card for the admin list."""
    kind_label = "base" if service.kind == ServiceKind.BASE else "addon"
    visible_label = "показывается" if service.is_active else "скрыта"
    return (
        f"{service.name}\n"
        f"Цена: {format_service_price(service)}\n"
        f"Тип: {kind_label}\n"
        f"Длительность: {service.duration_min} мин\n"
        f"Статус: {visible_label}"
    )


def render_week_slot_text(slot: Slot, *, tz_name: str) -> str:
    """Render one slot line for the weekly admin view."""
    local_dt = format_local_datetime(slot.start_at, tz_name)
    status_icon = SLOT_STATUS_ICONS[slot.status]
    return f"{status_icon} {local_dt.strftime('%d.%m %H:%M')} — {slot.status.value}"


def build_open_client_card_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Build a client-card button for admin notifications."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👀 Открыть карточку клиентки",
                    callback_data=f"admin_clients:open:{user_id}",
                )
            ]
        ]
    )


def build_admin_rescue_slot_keyboard(
    slot_id: int,
    *,
    exclude_user_id: int | None = None,
    user_id: int | None = None,
) -> InlineKeyboardMarkup:
    """Build the admin keyboard for sending a quick rescue offer."""
    rows = [
        [
            InlineKeyboardButton(
                text="✨ Спасти окошко",
                callback_data=f"rescue_slot:send:{slot_id}:{exclude_user_id or 0}",
                style=ButtonStyle.SUCCESS,
            )
        ]
    ]
    if user_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="👀 Открыть карточку клиентки",
                    callback_data=f"admin_clients:open:{user_id}",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_unconfirmed_alert_keyboard(
    *,
    booking_id: int,
    user_id: int,
    allow_no_show: bool = True,
) -> InlineKeyboardMarkup:
    """Build the admin keyboard for reminder-confirmation alerts.

    The phone, when known, is rendered directly in the alert text. The keyboard
    keeps only safe callback-based actions.
    """
    rows: list[list[InlineKeyboardButton]] = []
    action_row = [
        InlineKeyboardButton(
            text="💬 Написать",
            callback_data=f"admin_clients:open:{user_id}",
        )
    ]
    if allow_no_show:
        action_row.append(
            InlineKeyboardButton(
                text="✕ Считать отменой",
                callback_data=f"admin_unconfirmed:no_show:{booking_id}",
                style=ButtonStyle.DANGER,
            )
        )
    rows.append(action_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_force_majeure_day_keyboard(
    days: list[tuple[str, str]],
) -> InlineKeyboardMarkup:
    """Build a day-picker for the force-majeure flow.

    ``days`` is a list of ``(label, iso_date_str)`` tuples.
    """
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"force_majeure:day:{iso}")]
        for label, iso in days
    ]
    rows.append([nav_button("⬅️ Отмена", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_force_majeure_reason_keyboard(iso_date: str) -> InlineKeyboardMarkup:
    """Offer the editable default text before asking for a custom reason."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Использовать шаблон",
                    callback_data=f"force_majeure:use_template:{iso_date}",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [nav_button("⬅️ Отмена", "admin_menu:home")],
        ]
    )


def build_force_majeure_confirm_keyboard(iso_date: str) -> InlineKeyboardMarkup:
    """Confirm/cancel keyboard for the force-majeure action."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"force_majeure:confirm:{iso_date}",
                    style=ButtonStyle.DANGER,
                )
            ],
            [nav_button("⬅️ Отмена", "admin_menu:home")],
        ]
    )


def build_force_majeure_final_keyboard(iso_date: str, count: int) -> InlineKeyboardMarkup:
    """Build the second safety confirmation for the force-majeure action."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ Да, отменить {count} записей",
                    callback_data=f"force_majeure:final_commit:{iso_date}",
                    style=ButtonStyle.DANGER,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Нет, передумала",
                    callback_data=f"force_majeure:review:{iso_date}",
                )
            ],
        ]
    )


def build_force_majeure_client_keyboard() -> InlineKeyboardMarkup:
    """Keyboard attached to the client's force-majeure notification."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📅 Выбрать новое время",
                    callback_data="client_menu:book",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        ]
    )


def _build_client_return_suffix(back_callback: str) -> str:
    """Convert a clients back-callback into a compact suffix for child actions."""
    if back_callback.startswith("admin_clients:list:"):
        page = back_callback.rsplit(":", 1)[-1]
        return f":list:{page}"
    if back_callback.startswith("admin_approvals:open:"):
        approval_id = back_callback.rsplit(":", 1)[-1]
        return f":approval:{approval_id}"
    if back_callback.startswith("admin_schedule:week:"):
        page = back_callback.rsplit(":", 1)[-1]
        return f":schedule:week:{page}"
    if back_callback.startswith("admin_schedule:month:page:"):
        offset = back_callback.rsplit(":", 1)[-1]
        return f":schedule:month:{offset}"
    if back_callback.startswith("late_notice:view:"):
        notice_id = back_callback.rsplit(":", 1)[-1]
        return f":late_notice:{notice_id}"
    return ":home"


def _build_client_screen_callback(view: str, user_id: int, back_callback: str) -> str:
    """Build one client-card child callback while preserving the outer return context."""
    context_suffix = _build_client_return_suffix(back_callback)
    if view == "main":
        return f"admin_clients:open:{user_id}{context_suffix}"
    return f"admin_clients:{view}:{user_id}{context_suffix}"


def _build_client_action_context_suffix(view: str, back_callback: str) -> str:
    """Encode the current client-card screen plus its outer return target."""
    return f":{view}{_build_client_return_suffix(back_callback)}"


def build_admin_clients_home_keyboard() -> InlineKeyboardMarkup:
    """Build the home screen for the admin clients section."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔍 Найти по имени или @username",
                    callback_data="admin_clients:search",
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Список всех клиентов",
                    callback_data="admin_clients:list:0",
                )
            ],
            [nav_button("⬅️ В меню", "admin_menu:home")],
        ]
    )


def build_admin_clients_back_keyboard(
    callback_data: str = "admin_clients:home",
) -> InlineKeyboardMarkup:
    """Build back and direct-main-menu actions for the clients section."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [nav_button("⬅️ К клиентам", callback_data)],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_client_search_results_keyboard(
    items: list[tuple[int, str]],
    *,
    back_callback: str = "admin_clients:home",
) -> InlineKeyboardMarkup:
    """Build the search-results keyboard for client cards."""
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"admin_clients:open:{user_id}")]
        for user_id, label in items
    ]
    rows.append([nav_button("⬅️ К клиентам", back_callback)])
    rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_clients_page_keyboard(
    items: list[tuple[int, str]],
    *,
    page: int,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    """Build a paginated list of all clients."""
    rows = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=f"admin_clients:open:{user_id}:list:{page}",
            )
        ]
        for user_id, label in items
    ]

    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"admin_clients:list:{page - 1}")
        )
    nav_row.append(
        InlineKeyboardButton(text=f"Стр. {page + 1}", callback_data="admin_clients:noop")
    )
    if has_next:
        nav_row.append(
            InlineKeyboardButton(text="➡️", callback_data=f"admin_clients:list:{page + 1}")
        )
    rows.append(nav_row)
    rows.append([nav_button("⬅️ К клиентам", "admin_clients:home")])
    rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_client_main_keyboard(
    *,
    user_id: int,
    back_callback: str = "admin_clients:home",
) -> InlineKeyboardMarkup:
    """Build the compact primary-action keyboard for the main client card."""
    rows = [
        [
            InlineKeyboardButton(
                text="📅 Записи",
                callback_data=_build_client_screen_callback("bookings", user_id, back_callback),
            ),
            InlineKeyboardButton(
                text="➕ Записать",
                callback_data=f"admin_clients:manual_book:{user_id}{_build_client_return_suffix(back_callback)}",
                style=ButtonStyle.PRIMARY,
            ),
        ],
        [
            InlineKeyboardButton(
                text="💬 Написать",
                callback_data=(
                    "admin_clients:message:"
                    f"{user_id}{_build_client_action_context_suffix('main', back_callback)}"
                ),
                style=ButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                text="ℹ️ Инфо",
                callback_data=_build_client_screen_callback("info", user_id, back_callback),
            ),
        ],
        [
            InlineKeyboardButton(
                text="🛡 Модерация",
                callback_data=_build_client_screen_callback("moderation", user_id, back_callback),
            )
        ],
        [nav_button("⬅️ К списку", back_callback)],
        [nav_button("🏠 Главное меню", "admin_menu:home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_client_info_keyboard(
    *,
    user_id: int,
    duplicate_user_id: int | None = None,
    back_callback: str = "admin_clients:home",
) -> InlineKeyboardMarkup:
    """Build the secondary information/actions keyboard for the client info screen."""
    rows = [
        [
            InlineKeyboardButton(
                text="📝 Заметка",
                callback_data=(
                    "admin_clients:note:"
                    f"{user_id}{_build_client_action_context_suffix('info', back_callback)}"
                ),
            ),
            InlineKeyboardButton(
                text="💬 Написать",
                callback_data=(
                    "admin_clients:message:"
                    f"{user_id}{_build_client_action_context_suffix('info', back_callback)}"
                ),
                style=ButtonStyle.PRIMARY,
            ),
        ],
        [
            InlineKeyboardButton(
                text="📅 Записи",
                callback_data=_build_client_screen_callback("bookings", user_id, back_callback),
            ),
            InlineKeyboardButton(
                text="➕ Записать",
                callback_data=f"admin_clients:manual_book:{user_id}{_build_client_return_suffix(back_callback)}",
                style=ButtonStyle.PRIMARY,
            ),
        ],
    ]
    if duplicate_user_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📞 Открыть дубликат",
                    callback_data=_build_client_screen_callback(
                        "main",
                        duplicate_user_id,
                        back_callback,
                    ),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ К клиентке",
                callback_data=_build_client_screen_callback("main", user_id, back_callback),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_client_moderation_keyboard(
    *,
    user_id: int,
    is_blocked: bool,
    is_shadow_banned: bool,
    requires_manual_approval: bool,
    back_callback: str = "admin_clients:home",
) -> InlineKeyboardMarkup:
    """Build the isolated moderation keyboard for one client."""
    block_label = "✅ Разблокировать" if is_blocked else "🚫 Заблокировать"
    block_action = "unblock" if is_blocked else "block"
    shadow_label = "☀️ Снять shadow-ban" if is_shadow_banned else "🌙 Включить shadow-ban"
    shadow_action = "shadow_unban" if is_shadow_banned else "shadow_ban"
    manual_label = (
        "✅ Снять ручное подтверждение"
        if requires_manual_approval
        else "✋ Включить ручное подтверждение"
    )
    manual_action = "clear_manual" if requires_manual_approval else "set_manual"
    context_suffix = _build_client_action_context_suffix("moderation", back_callback)
    rows = [
        [
            InlineKeyboardButton(
                text=manual_label,
                callback_data=f"admin_clients:confirm:{manual_action}:{user_id}{context_suffix}",
            )
        ],
        [
            InlineKeyboardButton(
                text=shadow_label,
                callback_data=f"admin_clients:confirm:{shadow_action}:{user_id}{context_suffix}",
            )
        ],
        [
            InlineKeyboardButton(
                text="♻️ Сбросить strikes",
                callback_data=f"admin_clients:confirm:reset_strikes:{user_id}{context_suffix}",
            )
        ],
        [
            InlineKeyboardButton(
                text=block_label,
                callback_data=f"admin_clients:confirm:{block_action}:{user_id}{context_suffix}",
                style=ButtonStyle.SUCCESS if is_blocked else ButtonStyle.DANGER,
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ К клиентке",
                callback_data=_build_client_screen_callback("main", user_id, back_callback),
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_client_bookings_keyboard(
    *,
    user_id: int,
    active_bookings: list[Booking],
    completed_bookings: list[Booking],
    tz_name: str,
    back_callback: str = "admin_clients:home",
) -> InlineKeyboardMarkup:
    """Build the lightweight bookings-history keyboard for one client."""
    rows: list[list[InlineKeyboardButton]] = []
    for booking in [*active_bookings, *completed_bookings]:
        if booking.slot is None:
            label = f"📌 Без даты · {booking.base_service.name}"
        else:
            local_dt = format_local_datetime(booking.slot.start_at, tz_name)
            status_icon = "✅"
            if booking.status.value == "pending_master":
                status_icon = "⏳"
            elif booking.status.value in {"cancelled_by_client", "cancelled_by_master"}:
                status_icon = "✖️"
            elif booking.status.value == "no_show":
                status_icon = "⚠️"
            label = f"{status_icon} {local_dt:%d.%m · %H:%M} · {booking.base_service.name}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=build_admin_booking_card_callback(
                        booking.id,
                        back_callback=_build_client_screen_callback(
                            "bookings",
                            user_id,
                            back_callback,
                        ),
                    ),
                )
            ]
        )

    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="➕ Записать",
                    callback_data=f"admin_clients:manual_book:{user_id}{_build_client_return_suffix(back_callback)}",
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ К клиентке",
                    callback_data=_build_client_screen_callback("main", user_id, back_callback),
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_booking_card_keyboard(
    *,
    booking_id: int,
    client_id: int,
    back_callback: str,
    status: BookingStatus,
    has_slot: bool,
) -> InlineKeyboardMarkup:
    """Build the admin booking-card actions."""
    rows = [
        [
            InlineKeyboardButton(
                text="👤 Клиентка",
                callback_data=_build_client_screen_callback("main", client_id, back_callback),
            ),
            InlineKeyboardButton(
                text="📅 Все её записи",
                callback_data=_build_client_screen_callback("bookings", client_id, back_callback),
            ),
        ],
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="💬 Написать",
                callback_data=build_admin_booking_card_action_callback(
                    "message",
                    booking_id=booking_id,
                    client_id=client_id,
                    back_callback=back_callback,
                ),
                style=ButtonStyle.PRIMARY,
            )
        ]
    )
    if status in {BookingStatus.PENDING_MASTER, BookingStatus.CONFIRMED}:
        action_row: list[InlineKeyboardButton] = []
        if has_slot and status == BookingStatus.CONFIRMED:
            action_row.append(
                InlineKeyboardButton(
                    text="🕐 Перенести",
                    callback_data=build_admin_booking_card_action_callback(
                        "reschedule",
                        booking_id=booking_id,
                        back_callback=back_callback,
                    ),
                    style=ButtonStyle.PRIMARY,
                )
            )
        action_row.append(
            InlineKeyboardButton(
                text="❌ Отменить",
                callback_data=build_admin_booking_card_action_callback(
                    "cancel",
                    booking_id=booking_id,
                    back_callback=back_callback,
                ),
                style=ButtonStyle.DANGER,
            )
        )
        rows.append(action_row)
        if has_slot and status == BookingStatus.CONFIRMED:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="⚠️ Отметить no-show",
                        callback_data=build_admin_booking_card_action_callback(
                            "no_show",
                            booking_id=booking_id,
                            back_callback=back_callback,
                        ),
                        style=ButtonStyle.DANGER,
                    )
                ]
            )
    if status == BookingStatus.COMPLETED:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🛠 Гарантия / ремонт",
                    callback_data=build_admin_booking_card_action_callback(
                        "repair",
                        booking_id=booking_id,
                        back_callback=back_callback,
                    ),
                )
            ]
        )
    rows.append([nav_button("⬅️ Назад", back_callback)])
    rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_client_confirm_action_keyboard(
    *,
    action: str,
    user_id: int,
    view: str,
    back_callback: str,
) -> InlineKeyboardMarkup:
    """Build confirmation controls for risky client-card actions."""
    action_context_suffix = _build_client_action_context_suffix(view, back_callback)
    labels = {
        "block": "🚫 Да, заблокировать",
        "unblock": "✅ Да, разблокировать",
        "shadow_ban": "🔕 Да, включить shadow-ban",
        "shadow_unban": "🔔 Да, снять shadow-ban",
        "reset_strikes": "♻️ Да, сбросить strikes",
        "set_manual": "✋ Да, включить ручное подтверждение",
        "clear_manual": "✅ Да, снять ручное подтверждение",
    }
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=labels.get(action, "✅ Подтвердить"),
                    callback_data=f"admin_clients:{action}:{user_id}{action_context_suffix}",
                    style=ButtonStyle.DANGER,
                )
            ],
            [
                nav_button(
                    "⬅️ Не менять",
                    _build_client_screen_callback(view, user_id, back_callback),
                )
            ],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_stats_period_keyboard(period: str) -> InlineKeyboardMarkup:
    """Build the admin stats period switcher."""
    rows: list[list[InlineKeyboardButton]] = []
    if period != "previous":
        rows.append(
            [
                InlineKeyboardButton(
                    text="📆 Прошлый месяц", callback_data="admin_stats:period:previous"
                )
            ]
        )
    if period != "all":
        rows.append(
            [InlineKeyboardButton(text="📆 За всё время", callback_data="admin_stats:period:all")]
        )
    if period != "current":
        rows.append(
            [
                InlineKeyboardButton(
                    text="📆 Текущий месяц", callback_data="admin_stats:period:current"
                )
            ]
        )
    rows.append([nav_button("⬅️ Назад", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_broadcast_input_keyboard() -> InlineKeyboardMarkup:
    """Build a cancel button while waiting for the broadcast text."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[nav_button("⬅️ Отмена", "admin_broadcast:cancel")]]
    )


def build_admin_broadcast_preview_keyboard(recipient_count: int) -> InlineKeyboardMarkup:
    """Build the preview actions for a pending broadcast."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ Отправить всем ({recipient_count})",
                    callback_data="admin_broadcast:confirm",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [nav_button("❌ Отмена", "admin_broadcast:cancel")],
        ]
    )


def build_admin_template_actions_keyboard(template_key: str) -> InlineKeyboardMarkup:
    """Build actions for a single editable template."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить", callback_data=f"admin_templates:edit:{template_key}"
                )
            ]
        ]
    )


def build_admin_template_categories_keyboard(
    categories: list[TemplateCategory],
    *,
    counts_by_key: dict[str, int] | None = None,
) -> InlineKeyboardMarkup:
    """Build the category picker for admin templates."""
    rows = [
        [
            InlineKeyboardButton(
                text=(
                    f"{category.title} · {counts_by_key[category.key]}"
                    if counts_by_key is not None and category.key in counts_by_key
                    else category.title
                ),
                callback_data=f"admin_templates:category:{category.key}",
            )
        ]
        for category in categories
    ]
    rows.append([nav_button("⬅️ Назад", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_template_category_keyboard(
    category_key: str,
    groups: list[tuple[str, str]],
) -> InlineKeyboardMarkup:
    """Build the subgroup picker inside one template category."""
    rows: list[list[InlineKeyboardButton]] = []
    for group_key, group_title in groups:
        rows.append(
            [
                InlineKeyboardButton(
                    text=group_title,
                    callback_data=f"admin_templates:group:{category_key}:{group_key}",
                )
            ]
        )
    rows.append([nav_button("⬅️ К разделам", "admin_templates:home")])
    rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_template_group_keyboard(
    category_key: str,
    group_key: str,
    templates: list[TemplateDefinition],
    *,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    """Build the template list inside one subgroup."""
    rows = [
        [
            InlineKeyboardButton(
                text=template.title,
                callback_data=f"admin_templates:open:{template.key}",
            )
        ]
        for template in templates
    ]
    rows.append(
        [
            nav_button(
                "⬅️ Назад",
                back_callback or f"admin_templates:category:{category_key}",
            )
        ]
    )
    rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_template_detail_keyboard(
    template_key: str,
    back_callback: str,
    *,
    supports_media: bool = False,
    has_media: bool = False,
    has_bundled_media: bool = False,
    uses_bundled_media: bool = False,
    has_custom_text: bool = False,
) -> InlineKeyboardMarkup:
    """Build actions below one template detail view."""
    rows = [
        [
            InlineKeyboardButton(
                text="✏️ Изменить текст",
                callback_data=f"admin_templates:edit:{template_key}",
                style=ButtonStyle.PRIMARY,
            )
        ]
    ]
    if has_custom_text:
        rows.append(
            [
                InlineKeyboardButton(
                    text="↩️ Вернуть стандартный текст",
                    callback_data=f"admin_templates:reset_text:{template_key}",
                )
            ]
        )
    if supports_media:
        media_row: list[InlineKeyboardButton] = []
        media_row.append(
            InlineKeyboardButton(
                text="🖼 Заменить картинку" if has_media else "🖼 Загрузить картинку",
                callback_data=f"admin_templates:upload_image:{template_key}",
            )
        )
        rows.append(media_row)
        if has_media:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="🗑 Удалить картинку",
                        callback_data=f"admin_templates:remove_image:{template_key}",
                        style=ButtonStyle.DANGER,
                    )
                ]
            )
        if has_bundled_media and not uses_bundled_media:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="↩️ Вернуть стандартную картинку",
                        callback_data=f"admin_templates:restore_image:{template_key}",
                    )
                ]
            )
    rows.extend(
        [
            [nav_button("⬅️ Назад", back_callback)],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_template_edit_cancel_keyboard() -> InlineKeyboardMarkup:
    """Build a cancel button for template-edit mode."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [nav_button("⬅️ Отмена", "admin_templates:cancel_edit")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_template_warning_keyboard() -> InlineKeyboardMarkup:
    """Build actions for placeholder warnings before template save."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Сохранить всё равно",
                    callback_data="admin_templates:save_anyway",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [nav_button("⬅️ Вернуться к редактированию", "admin_templates:back_to_edit")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_template_media_cancel_keyboard(template_key: str) -> InlineKeyboardMarkup:
    """Build a back button while waiting for a template image."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [nav_button("⬅️ Отмена", "admin_templates:cancel_media")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


ADMIN_SETTINGS_SECTIONS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "basic": (
        "🌐 Основное",
        (
            ("Часовой пояс", "admin_settings:edit:tz"),
            ("Telegram username Ангелы", "admin_settings:edit:master_telegram_username"),
            ("Адрес для кнопки «Скопировать»", "admin_settings:edit:studio_address_copy_text"),
            ("Режим отпуска", "admin_settings:toggle:vacation_mode"),
        ),
    ),
    "booking": (
        "🛡 Запись и безопасность",
        (
            ("Интервал между записями", "admin_settings:edit:min_days_between_bookings"),
            ("Активных записей на клиента", "admin_settings:edit:max_active_bookings_per_user"),
            (
                "Постоянная клиентка после визитов",
                "admin_settings:edit:frequent_booking_bypass_visits",
            ),
            ("Перенос минимум за часов", "admin_settings:edit:reschedule_min_hours_before"),
            ("Макс. переносов записи", "admin_settings:edit:max_reschedules_per_booking"),
            ("Пауза после отмены", "admin_settings:edit:cancel_cooldown_minutes"),
            ("Поздняя отмена от часов", "admin_settings:edit:late_cancel_hours"),
            ("Порог late-cancel", "admin_settings:edit:late_cancel_strike_limit"),
            ("Порог no-show", "admin_settings:edit:no_show_strike_limit"),
            ("Макс. pending approvals", "admin_settings:edit:max_pending_approvals_per_user"),
            ("Антиспам записи: окно", "admin_settings:edit:booking_attempt_limit_window_minutes"),
            ("Антиспам записи: попыток", "admin_settings:edit:booking_attempt_limit_count"),
            ("Антиспам записи: пауза", "admin_settings:edit:booking_attempt_pause_minutes"),
        ),
    ),
    "notifications": (
        "⏰ Уведомления",
        (
            ("24h напоминание", "admin_settings:toggle:reminder_24h_enabled"),
            ("2h напоминание", "admin_settings:toggle:reminder_2h_enabled"),
            ("Алерт мастеру без ответа", "admin_settings:toggle:unconfirmed_alert_enabled"),
            ("Алерт за сколько минут", "admin_settings:edit:unconfirmed_alert_before_minutes"),
            ("Пауза после напоминания", "admin_settings:edit:unconfirmed_alert_after_minutes"),
            ("Пост-визитный опрос", "admin_settings:toggle:postvisit_enabled"),
            ("Repeat-prompt (недели)", "admin_settings:edit:repeat_prompt_weeks"),
        ),
    ),
    "aftercare": (
        "🛠 Опоздания и гарантия",
        (
            ("Порог опоздания (мин)", "admin_settings:edit:late_notice_warning_minutes"),
            ("Гарантия: дней", "admin_settings:edit:repair_warranty_days"),
            ("Гарантия: ногтей", "admin_settings:edit:repair_warranty_nails_limit"),
            ("Окно заявки на ремонт", "admin_settings:edit:repair_request_window_days"),
            ("Длительность ремонта", "admin_settings:edit:repair_default_duration_min"),
        ),
    ),
    "appearance": (
        "🎨 Внешний вид",
        (
            ("Картинка расписания", "admin_settings:toggle:schedule_image_enabled"),
            ("Rich test sandbox", "admin_settings:toggle:rich_messages_test_enabled"),
        ),
    ),
    "limits": (
        "🔒 Интеграции и лимиты",
        (
            ("Proxy-сообщений в час", "admin_settings:edit:proxy_messages_per_hour"),
            ("Вопросов мастеру в день", "admin_settings:edit:ask_master_per_day"),
        ),
    ),
}


def build_admin_settings_keyboard() -> InlineKeyboardMarkup:
    """Build top-level runtime settings categories."""
    rows = [
        [
            InlineKeyboardButton(
                text=title,
                callback_data=f"admin_settings:section:{section_key}",
            )
        ]
        for section_key, (title, _) in ADMIN_SETTINGS_SECTIONS.items()
    ]
    rows.append(
        [InlineKeyboardButton(text="🧭 Диагностика", callback_data="admin_settings:diagnostics")]
    )
    rows.append([nav_button("⬅️ Назад", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_settings_section_keyboard(section_key: str) -> InlineKeyboardMarkup:
    """Build the edit/toggle buttons for one settings category."""
    section = ADMIN_SETTINGS_SECTIONS.get(section_key)
    if section is None:
        return build_admin_settings_keyboard()
    _, items = section
    rows = [
        [InlineKeyboardButton(text=label, callback_data=callback_data)]
        for label, callback_data in items
    ]
    rows.append([nav_button("⬅️ К разделам", "admin_settings:home")])
    rows.append([nav_button("🏠 Главное меню", "admin_menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_settings_diagnostics_keyboard() -> InlineKeyboardMarkup:
    """Build the diagnostics screen keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [nav_button("⬅️ К разделам", "admin_settings:home")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_settings_edit_keyboard() -> InlineKeyboardMarkup:
    """Build a cancel button while editing one settings value."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [nav_button("⬅️ Отмена", "admin_settings:cancel_edit")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_rich_test_keyboard() -> InlineKeyboardMarkup:
    """Build the admin-only rich sandbox actions."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"🧪 {definition.title}",
                callback_data=f"admin_rich_test:preview:{definition.key}",
                style=ButtonStyle.PRIMARY,
            )
        ]
        for definition in RICH_PREVIEW_DEFINITIONS
    ]
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="✉️ Тест-рассылка",
                    callback_data="admin_rich_test:broadcast",
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [nav_button("⬅️ В меню", "admin_menu:home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_rich_comparison_keyboard(
    preview_key: str,
    *,
    rich: bool,
) -> InlineKeyboardMarkup:
    """Build safe visual-only actions under one standard/rich preview."""
    variant_label = "Rich вариант" if rich else "Обычный вариант"
    action_labels: dict[str, tuple[tuple[str, ButtonStyle], ...]] = {
        "price": (
            ("📅 Записаться", ButtonStyle.SUCCESS),
            ("🏠 Главное меню", ButtonStyle.DANGER),
        ),
        "about": (
            ("📸 Открыть канал", ButtonStyle.PRIMARY),
            ("🏠 Главное меню", ButtonStyle.DANGER),
        ),
        "address": (
            ("🗺 Открыть карту", ButtonStyle.PRIMARY),
            ("🏠 Главное меню", ButtonStyle.DANGER),
        ),
        "reminder_24h": (
            ("✅ Буду", ButtonStyle.SUCCESS),
            ("❌ Не смогу — перенести/отменить", ButtonStyle.DANGER),
        ),
        "reminder_2h": (
            ("✅ Буду", ButtonStyle.SUCCESS),
            ("❌ Не смогу — перенести/отменить", ButtonStyle.DANGER),
            ("⏰ Опаздываю", ButtonStyle.PRIMARY),
        ),
        "booking_confirm": (
            ("🙋‍♀️ Мои записи", ButtonStyle.PRIMARY),
            ("🏠 Главное меню", ButtonStyle.DANGER),
        ),
    }
    rows = [
        [
            InlineKeyboardButton(
                text=variant_label,
                callback_data="admin_rich_test:noop",
                style=ButtonStyle.PRIMARY,
            )
        ]
    ]
    rows.extend(
        [
            InlineKeyboardButton(
                text=label,
                callback_data="admin_rich_test:noop",
                style=style,
            )
        ]
        for label, style in action_labels.get(preview_key, ())
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_rich_test_input_keyboard() -> InlineKeyboardMarkup:
    """Build controls while waiting for a test source message."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [nav_button("⬅️ Отмена", "admin_rich_test:cancel_input")],
            [nav_button("🏠 Главное меню", "admin_menu:home")],
        ]
    )


def build_admin_rich_test_preview_keyboard() -> InlineKeyboardMarkup:
    """Build confirmation controls for the copied test preview."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Отправить тест",
                    callback_data="admin_rich_test:broadcast_confirm",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [nav_button("❌ Отмена", "admin_rich_test:broadcast_cancel")],
        ]
    )
