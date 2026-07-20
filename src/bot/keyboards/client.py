from __future__ import annotations

from datetime import date

from aiogram.enums import ButtonStyle
from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from src.bot import texts
from src.db.models import Service, Slot
from src.services.booking import (
    PAYMENT_METHOD_CASH,
    PAYMENT_METHOD_TRANSFER,
    DayOption,
    format_local_datetime,
)
from src.services.button_configs import (
    ANGELA_CHAT_URL,
    DEFAULT_ADDRESS_MAP_URL,
    NAVIGATION_CUSTOM_EMOJI_ID,
    PORTFOLIO_CUSTOM_EMOJI_ID,
    ClientMenuButtonConfig,
    EditableButtonDefinition,
    get_client_main_menu_button_definition,
    resolve_button_style,
)


def _build_copy_text_button(label: str, value: str) -> InlineKeyboardButton:
    """Build a Telegram copy-text button with a safe payload length."""
    copy_value = value.strip()
    if len(copy_value) > 256:
        copy_value = copy_value[:253].rstrip() + "..."
    return InlineKeyboardButton(
        text=label,
        copy_text=CopyTextButton(text=copy_value or "—"),
    )


def _build_client_menu_button(
    definition: EditableButtonDefinition,
    config: ClientMenuButtonConfig,
    *,
    runtime_url: str | None = None,
) -> InlineKeyboardButton:
    """Build one client-menu button from a stored config and a fixed action."""
    kwargs: dict[str, object] = {
        "text": config.text,
        "icon_custom_emoji_id": config.icon_custom_emoji_id,
    }
    style = resolve_button_style(config.style_name)
    if style is not None:
        kwargs["style"] = style
    if definition.callback_data is not None:
        kwargs["callback_data"] = definition.callback_data
    elif definition.url is not None:
        kwargs["url"] = config.url or runtime_url or definition.url
    return InlineKeyboardButton(**kwargs)


def _build_reused_main_menu_button(
    *,
    key: str,
    fallback_text: str,
    fallback_style_name: str,
    callback_data: str | None = None,
    url: str | None = None,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
    icon_custom_emoji_id: str | None = None,
) -> InlineKeyboardButton:
    """Build a button that reuses the editable main-menu config in other screens."""
    definition = get_client_main_menu_button_definition(key)
    config = _lookup_button_config(
        button_configs,
        category_key="client_main_menu",
        key=key,
        fallback=ClientMenuButtonConfig(
            text=fallback_text,
            style_name=fallback_style_name,
            icon_custom_emoji_id=icon_custom_emoji_id,
        ),
    )
    kwargs: dict[str, object] = {
        "text": config.text,
        "icon_custom_emoji_id": config.icon_custom_emoji_id,
    }
    style = resolve_button_style(config.style_name)
    if style is not None:
        kwargs["style"] = style
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    elif config.url is not None:
        kwargs["url"] = config.url
    elif url is not None:
        kwargs["url"] = url
    elif definition.callback_data is not None:
        kwargs["callback_data"] = definition.callback_data
    elif definition.url is not None:
        kwargs["url"] = definition.url
    return InlineKeyboardButton(**kwargs)


def _lookup_button_config(
    button_configs: dict[str, ClientMenuButtonConfig] | None,
    *,
    category_key: str,
    key: str,
    fallback: ClientMenuButtonConfig,
) -> ClientMenuButtonConfig:
    """Lookup a runtime button config by local key or unique editor id."""
    if not button_configs:
        return fallback
    return button_configs.get(key) or button_configs.get(f"{category_key}.{key}") or fallback


def _prepare_runtime_override_text(
    text: str,
    *,
    icon_custom_emoji_id: str | None,
) -> str:
    """Avoid doubling a Unicode arrow when a premium icon is already configured."""
    if not icon_custom_emoji_id:
        return text
    parts = text.split(" ", 1)
    if len(parts) == 2 and not any(char.isalnum() for char in parts[0]):
        return parts[1]
    return text


def _build_runtime_callback_button(
    *,
    category_key: str,
    key: str,
    fallback_text: str,
    fallback_style_name: str,
    callback_data: str,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
    icon_custom_emoji_id: str | None = None,
    icon_override: str | None = None,
    text_override: str | None = None,
) -> InlineKeyboardButton:
    """Build a runtime-configured callback button with a dynamic destination."""
    config = _lookup_button_config(
        button_configs,
        category_key=category_key,
        key=key,
        fallback=ClientMenuButtonConfig(
            text=fallback_text,
            style_name=fallback_style_name,
            icon_custom_emoji_id=icon_custom_emoji_id,
        ),
    )
    effective_icon = icon_override or config.icon_custom_emoji_id
    button_text = _prepare_runtime_override_text(
        text_override if text_override is not None else config.text,
        icon_custom_emoji_id=effective_icon,
    )
    kwargs: dict[str, object] = {
        "text": button_text,
        "callback_data": callback_data,
        "icon_custom_emoji_id": effective_icon,
    }
    style = resolve_button_style(config.style_name)
    if style is not None:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def _build_book_cta_button(
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardButton:
    """Build the shared client CTA for starting a normal booking flow."""
    return _build_reused_main_menu_button(
        key="book",
        fallback_text="📅 Записаться",
        fallback_style_name="success",
        callback_data="client_menu:book",
        button_configs=button_configs,
    )


def _build_browse_cta_button(
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardButton:
    """Build the shared client CTA for browsing free slots."""
    return _build_reused_main_menu_button(
        key="browse",
        fallback_text="🗓 Свободные окошки",
        fallback_style_name="primary",
        callback_data="client_menu:browse",
        button_configs=button_configs,
    )


def _build_contact_cta_button(
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
    contact_url: str | None = None,
) -> InlineKeyboardButton:
    """Build the shared client CTA that opens a direct chat with the master."""
    return _build_reused_main_menu_button(
        key="contact",
        fallback_text="✉️ Написать Ангеле напрямую",
        fallback_style_name="default",
        url=contact_url or ANGELA_CHAT_URL,
        button_configs=button_configs,
    )


def _build_client_my_bookings_action_button(
    *,
    key: str,
    fallback_text: str,
    fallback_style_name: str,
    callback_data: str,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardButton:
    """Build a shared runtime-configured `Мои записи` action button."""
    return _build_runtime_callback_button(
        category_key="client_my_bookings",
        key=key,
        fallback_text=fallback_text,
        fallback_style_name=fallback_style_name,
        callback_data=callback_data,
        button_configs=button_configs,
    )


def _build_client_repeated_action_button(
    *,
    key: str,
    fallback_text: str,
    fallback_style_name: str,
    callback_data: str,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardButton:
    """Build a shared runtime-configured button for repeated client-booking CTAs."""
    return _build_runtime_callback_button(
        category_key="client_repeated",
        key=key,
        fallback_text=fallback_text,
        fallback_style_name=fallback_style_name,
        callback_data=callback_data,
        button_configs=button_configs,
    )


def _build_client_repeated_url_button(
    *,
    key: str,
    fallback_text: str,
    fallback_style_name: str,
    url: str | None = None,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardButton:
    """Build a shared runtime-configured URL button for repeated client CTAs."""
    config = _lookup_button_config(
        button_configs,
        category_key="client_repeated",
        key=key,
        fallback=ClientMenuButtonConfig(
            text=fallback_text,
            style_name=fallback_style_name,
        ),
    )
    kwargs: dict[str, object] = {
        "text": config.text,
        "url": config.url or url or DEFAULT_ADDRESS_MAP_URL,
        "icon_custom_emoji_id": config.icon_custom_emoji_id,
    }
    style = resolve_button_style(config.style_name)
    if style is not None:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def back_button(
    callback_data: str,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
    text_override: str | None = None,
) -> InlineKeyboardButton:
    """Build the shared editable `Назад` button."""
    return _build_runtime_callback_button(
        category_key="common",
        key="back",
        fallback_text="⬅️ Назад",
        fallback_style_name="danger",
        callback_data=callback_data,
        button_configs=button_configs,
        icon_override=_navigation_icon_custom_emoji_id(button_configs),
        text_override=text_override,
    )


def cancel_back_button(
    callback_data: str,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardButton:
    """Build the shared editable back-like cancel button."""
    return _build_runtime_callback_button(
        category_key="common",
        key="cancel_back",
        fallback_text="⬅️ Отмена",
        fallback_style_name="danger",
        callback_data=callback_data,
        button_configs=button_configs,
        icon_override=_navigation_icon_custom_emoji_id(button_configs),
    )


def _navigation_icon_custom_emoji_id(
    button_configs: dict[str, ClientMenuButtonConfig] | None,
) -> str:
    """Resolve one premium icon shared by back, home and navigation-cancel buttons."""
    for key in ("common.back", "back", "common.cancel_back", "cancel_back"):
        config = (button_configs or {}).get(key)
        if config is not None and config.icon_custom_emoji_id:
            return config.icon_custom_emoji_id
    return NAVIGATION_CUSTOM_EMOJI_ID


def home_button(
    callback_data: str = "client_menu:back",
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardButton:
    """Build the direct-to-main-menu action using the shared navigation appearance."""
    return _build_runtime_callback_button(
        category_key="common",
        key="back",
        fallback_text="⬅️ Назад",
        fallback_style_name="danger",
        callback_data=callback_data,
        button_configs=button_configs,
        icon_override=_navigation_icon_custom_emoji_id(button_configs),
        text_override="🏠 Главное меню",
    )


def navigation_rows(
    back_callback: str,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
    back_text: str | None = None,
    home_callback: str = "client_menu:back",
) -> list[list[InlineKeyboardButton]]:
    """Return canonical bottom navigation: back first, then direct exit."""
    return [
        [
            back_button(
                back_callback,
                button_configs=button_configs,
                text_override=back_text,
            )
        ],
        [home_button(home_callback, button_configs=button_configs)],
    ]


def cancel_action_button(
    callback_data: str,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardButton:
    """Build the shared editable destructive cancel button."""
    return _build_runtime_callback_button(
        category_key="common",
        key="cancel_action",
        fallback_text="❌ Отменить",
        fallback_style_name="danger",
        callback_data=callback_data,
        button_configs=button_configs,
        icon_override=_navigation_icon_custom_emoji_id(button_configs),
    )


def done_button(
    callback_data: str,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
    text_override: str | None = None,
) -> InlineKeyboardButton:
    """Build a positive completion action from the shared editable `Готово` config."""
    return _build_runtime_callback_button(
        category_key="common",
        key="done",
        fallback_text="✅ Готово",
        fallback_style_name="success",
        callback_data=callback_data,
        button_configs=button_configs,
        text_override=text_override,
    )


def build_client_main_menu(
    *,
    show_my_bookings: bool,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
    contact_url: str | None = None,
) -> InlineKeyboardMarkup:
    """Build the main client menu.

    Bot API 9.4 (Feb 2026) introduced the ``style`` field for KeyboardButton /
    InlineKeyboardButton with values primary/success/danger. We use
    ``ButtonStyle.PRIMARY`` on «Записаться» and «Мои записи» so that both read
    as accented actions on supporting clients; older clients fall back to the
    default gray rendering without breaking.
    """
    button_configs = button_configs or {}
    primary_row = [
        _build_client_menu_button(
            get_client_main_menu_button_definition("book"),
            button_configs.get(
                "book",
                ClientMenuButtonConfig(
                    text="📅 Записаться",
                    style_name="success",
                ),
            ),
        ),
        _build_client_menu_button(
            get_client_main_menu_button_definition("browse"),
            button_configs.get(
                "browse",
                ClientMenuButtonConfig(
                    text="🗓 Свободные окошки",
                    style_name="primary",
                ),
            ),
        ),
    ]
    rows: list[list[InlineKeyboardButton]] = [primary_row]
    if show_my_bookings:
        rows.append(
            [
                _build_client_menu_button(
                    get_client_main_menu_button_definition("my_bookings"),
                    button_configs.get(
                        "my_bookings",
                        ClientMenuButtonConfig(
                            text="🙋‍♀️ Мои записи",
                            style_name="primary",
                        ),
                    ),
                )
            ]
        )

    rows.append(
        [
            _build_client_menu_button(
                get_client_main_menu_button_definition("services"),
                button_configs.get(
                    "services",
                    ClientMenuButtonConfig(
                        text="💅 Услуги и цены",
                        style_name="primary",
                    ),
                ),
            )
        ]
    )
    rows.append(
        [
            _build_client_menu_button(
                get_client_main_menu_button_definition("portfolio"),
                button_configs.get(
                    "portfolio",
                    ClientMenuButtonConfig(
                        text="🌸 О Ангеле и работы",
                        style_name="default",
                        icon_custom_emoji_id=PORTFOLIO_CUSTOM_EMOJI_ID,
                    ),
                ),
            )
        ]
    )
    rows.append(
        [
            _build_client_menu_button(
                get_client_main_menu_button_definition("address"),
                button_configs.get(
                    "address",
                    ClientMenuButtonConfig(
                        text="📍 Адрес и как добраться",
                        style_name="default",
                    ),
                ),
            )
        ]
    )
    rows.append(
        [
            _build_contact_cta_button(
                button_configs=button_configs,
                contact_url=contact_url,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_services_actions_keyboard(
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build actions below the services list."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_build_book_cta_button(button_configs=button_configs)],
            [_build_browse_cta_button(button_configs=button_configs)],
            [home_button(button_configs=button_configs)],
        ]
    )


def build_portfolio_keyboard(
    url: str,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the combined master-profile / portfolio keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📸 Открыть канал с работами",
                    url=url,
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [_build_book_cta_button(button_configs=button_configs)],
            [_build_browse_cta_button(button_configs=button_configs)],
            [home_button(button_configs=button_configs)],
        ]
    )


def build_back_to_menu_keyboard(
    *,
    callback_data: str = "client_menu:back",
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build a direct return to the client main menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [home_button(callback_data, button_configs=button_configs)],
        ]
    )


def build_vitrine_actions_keyboard(
    *,
    address_map_url: str | None = None,
    address_copy_text: str | None = None,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build a symmetric CTA set for marketing/vitrine screens."""
    rows: list[list[InlineKeyboardButton]] = []
    if address_map_url:
        rows.append(
            [
                _build_client_repeated_url_button(
                    key="open_map",
                    fallback_text="🗺 Открыть в Яндекс Картах",
                    fallback_style_name="primary",
                    url=address_map_url,
                    button_configs=button_configs,
                )
            ]
        )
    if address_copy_text:
        rows.append([_build_copy_text_button("📋 Скопировать адрес", address_copy_text)])
    rows.extend(
        [
            [_build_book_cta_button(button_configs=button_configs)],
            [_build_browse_cta_button(button_configs=button_configs)],
            [home_button(button_configs=button_configs)],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_offered_time_keyboard(approval_id: int) -> InlineKeyboardMarkup:
    """Keyboard sent to client when admin proposes an alternative time slot."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, подходит!",
                    callback_data=f"approval:accept_offer:{approval_id}",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Нет, другое время",
                    callback_data=f"approval:decline_offer:{approval_id}",
                    style=ButtonStyle.DANGER,
                )
            ],
        ]
    )


def build_client_fallback_keyboard(
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
    contact_url: str | None = None,
) -> InlineKeyboardMarkup:
    """Build the keyboard shown under the «I didn't catch that» fallback message."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _build_reused_main_menu_button(
                    key="book",
                    fallback_text="📅 Записаться",
                    fallback_style_name="success",
                    callback_data="client_menu:book",
                    button_configs=button_configs,
                ),
            ],
            [
                _build_contact_cta_button(
                    button_configs=button_configs,
                    contact_url=contact_url,
                ),
            ],
            [
                home_button(button_configs=button_configs),
            ],
        ]
    )


def build_client_card_keyboard(
    *,
    show_my_bookings: bool,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build actions below the rendered client card."""
    rows = [
        [
            _build_reused_main_menu_button(
                key="book",
                fallback_text="📅 Записаться",
                fallback_style_name="success",
                callback_data="client_menu:book",
                button_configs=button_configs,
            )
        ]
    ]
    if show_my_bookings:
        rows.append(
            [
                _build_reused_main_menu_button(
                    key="my_bookings",
                    fallback_text="🙋‍♀️ Мои записи",
                    fallback_style_name="primary",
                    callback_data="client_menu:my_bookings",
                    button_configs=button_configs,
                )
            ]
        )
    rows.append([home_button(button_configs=button_configs)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_my_bookings_list_keyboard(
    items: list[tuple[int, str]],
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the booking-picker keyboard for the `Мои записи` section."""
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"my_bookings:open:{booking_id}")]
        for booking_id, label in items
    ]
    rows.append([home_button(button_configs=button_configs)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_my_bookings_overview_keyboard(
    *,
    nearest_booking_id: int | None,
    next_booking_id: int | None,
    repeat_booking_id: int | None,
    history_count: int,
    has_active_bookings: bool,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the summary-first keyboard for the `Мои записи` overview."""
    rows: list[list[InlineKeyboardButton]] = []
    if nearest_booking_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🌸 Ближайшая запись",
                    callback_data=f"my_bookings:open:{nearest_booking_id}",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
    if next_booking_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🌸 Следующая",
                    callback_data=f"my_bookings:open:{next_booking_id}",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
    if nearest_booking_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✏️ Перенести ближайшую",
                    callback_data=f"my_bookings:reschedule:{nearest_booking_id}",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
    if repeat_booking_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔁 Повторить прошлую запись",
                    callback_data=f"repeat_prompt:repeat_last:{repeat_booking_id}",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )
    if history_count > 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📜 История ({history_count})",
                    callback_data="my_bookings:history",
                )
            ]
        )
    if not has_active_bookings:
        rows.append(
            [
                _build_reused_main_menu_button(
                    key="book",
                    fallback_text="📅 Записаться",
                    fallback_style_name="success",
                    callback_data="client_menu:book",
                    button_configs=button_configs,
                )
            ]
        )
    rows.append([home_button(button_configs=button_configs)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_my_bookings_history_keyboard(
    items: list[tuple[int, str]],
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the detailed history/records picker for `Мои записи`."""
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"my_bookings:open:{booking_id}")]
        for booking_id, label in items
    ]
    rows.extend(
        navigation_rows(
            "my_bookings:overview",
            button_configs=button_configs,
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_my_bookings_empty_keyboard(
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build actions for an empty `Мои записи` section."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _build_reused_main_menu_button(
                    key="book",
                    fallback_text="📅 Записаться",
                    fallback_style_name="success",
                    callback_data="client_menu:book",
                    button_configs=button_configs,
                )
            ],
            [home_button(button_configs=button_configs)],
        ]
    )


def build_booking_card_keyboard(
    booking_id: int,
    *,
    can_reschedule: bool,
    can_cancel: bool,
    cancel_label: str,
    show_late_button: bool = False,
    show_repair_button: bool = False,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build actions for a single booking card."""
    rows: list[list[InlineKeyboardButton]] = []
    action_row: list[InlineKeyboardButton] = []
    if can_reschedule:
        action_row.append(
            _build_client_my_bookings_action_button(
                key="reschedule",
                fallback_text="✏️ Перенести",
                fallback_style_name="primary",
                callback_data=f"my_bookings:reschedule:{booking_id}",
                button_configs=button_configs,
            )
        )
    if can_cancel:
        action_row.append(
            InlineKeyboardButton(
                text=cancel_label,
                callback_data=f"my_bookings:cancel:{booking_id}",
                style=ButtonStyle.DANGER,
            )
        )
    if action_row:
        rows.append(action_row)

    if show_late_button:
        rows.append(
            [
                _build_client_my_bookings_action_button(
                    key="late",
                    fallback_text="⏰ Опаздываю",
                    fallback_style_name="primary",
                    callback_data=f"my_bookings:late:{booking_id}",
                    button_configs=button_configs,
                )
            ]
        )

    if show_repair_button:
        rows.append(
            [
                _build_client_my_bookings_action_button(
                    key="repair",
                    fallback_text="🛠 Ремонт / гарантия",
                    fallback_style_name="primary",
                    callback_data=f"repair:start:{booking_id}",
                    button_configs=button_configs,
                )
            ]
        )

    rows.extend(
        navigation_rows(
            "my_bookings:overview",
            button_configs=button_configs,
            back_text="⬅️ К моим записям",
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_cancel_pre_confirm_keyboard(
    booking_id: int,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Ask 'are you sure?' before opening the reason picker."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, выбрать причину",
                    callback_data=f"my_bookings:cancel_pre_confirm:{booking_id}",
                )
            ],
            *navigation_rows(
                f"my_bookings:open:{booking_id}",
                button_configs=button_configs,
            ),
        ]
    )


def build_cancel_reason_keyboard(
    booking_id: int,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the reason picker for booking cancellation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤒 Плохо себя чувствую",
                    callback_data=f"my_bookings:cancel_reason:{booking_id}:sick",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 Не успеваю по времени",
                    callback_data=f"my_bookings:cancel_reason:{booking_id}:busy",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚨 Форс-мажор",
                    callback_data=f"my_bookings:cancel_reason:{booking_id}:force_majeure",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💅 Запишусь позже",
                    callback_data=f"my_bookings:cancel_reason:{booking_id}:later",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Не планирую больше",
                    callback_data=f"my_bookings:cancel_reason:{booking_id}:not_planning",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Другое",
                    callback_data=f"my_bookings:cancel_reason:{booking_id}:other",
                )
            ],
            *navigation_rows(
                f"my_bookings:open:{booking_id}",
                button_configs=button_configs,
            ),
        ]
    )


def build_cancel_warning_keyboard(
    booking_id: int,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the confirmation step for a late cancellation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Да, отменить",
                    callback_data=f"my_bookings:cancel_confirm:{booking_id}",
                    style=ButtonStyle.DANGER,
                )
            ],
            *navigation_rows(
                f"my_bookings:open:{booking_id}",
                button_configs=button_configs,
            ),
        ]
    )


def build_back_to_booking_keyboard(
    booking_id: int,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build back and direct-main-menu actions from a nested booking screen."""
    return InlineKeyboardMarkup(
        inline_keyboard=navigation_rows(
            f"my_bookings:open:{booking_id}",
            button_configs=button_configs,
        )
    )


def build_booking_action_result_keyboard(
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build actions shown after a successful booking change."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _build_reused_main_menu_button(
                    key="my_bookings",
                    fallback_text="🙋‍♀️ Мои записи",
                    fallback_style_name="primary",
                    callback_data="my_bookings:overview",
                    button_configs=button_configs,
                )
            ],
            [home_button(button_configs=button_configs)],
        ]
    )


def build_post_booking_cta_keyboard(
    booking_id: int | None = None,
    *,
    address_map_url: str | None = None,
    address_copy_text: str | None = None,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
    contact_url: str | None = None,
) -> InlineKeyboardMarkup:
    """Build inline actions shown after a successful booking.

    When booking_id is provided a reference-upload button is added.
    """
    rows = []
    if address_map_url:
        rows.append(
            [
                _build_client_repeated_url_button(
                    key="open_map",
                    fallback_text="🗺 Открыть в Яндекс Картах",
                    fallback_style_name="primary",
                    url=address_map_url,
                    button_configs=button_configs,
                )
            ]
        )
    if address_copy_text:
        rows.append([_build_copy_text_button("📋 Скопировать адрес", address_copy_text)])
    if booking_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=texts.POST_BOOKING_REFERENCE_BUTTON_TEXT,
                    callback_data=f"client:post_reference:{booking_id}",
                )
            ]
        )
    rows.append(
        [
            _build_reused_main_menu_button(
                key="my_bookings",
                fallback_text=texts.POST_BOOKING_MY_BOOKINGS_BUTTON_TEXT,
                fallback_style_name="primary",
                callback_data="client_menu:my_bookings",
                button_configs=button_configs,
            )
        ]
    )
    rows.append(
        [
            _build_contact_cta_button(
                button_configs=button_configs,
                contact_url=contact_url,
            )
        ]
    )
    rows.append([home_button("client:to_menu", button_configs=button_configs)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_design_photo_actions_keyboard(
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build actions for a photo sent outside the booking flow."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _build_reused_main_menu_button(
                    key="book",
                    fallback_text="📅 Записаться с этим фото",
                    fallback_style_name="primary",
                    callback_data="design_photo:book",
                    button_configs=button_configs,
                )
            ],
            [
                InlineKeyboardButton(
                    text="✉️ Только передать Ангеле", callback_data="design_photo:send"
                )
            ],
            [
                cancel_back_button(
                    "design_photo:cancel",
                    button_configs=button_configs,
                )
            ],
        ]
    )


def build_proxy_reply_keyboard(approval_id: int) -> InlineKeyboardMarkup:
    """Build the reply button shown in proxy-chat messages."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Ответить",
                    callback_data=f"proxy:reply:{approval_id}",
                    style=ButtonStyle.PRIMARY,
                )
            ],
        ]
    )


def build_reminder_24h_keyboard(
    booking_id: int,
    *,
    address_map_url: str | None = None,
    address_copy_text: str | None = None,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build actions under the 24h reminder."""
    rows = [
        [
            InlineKeyboardButton(
                text="✅ Буду",
                callback_data=f"reminder:ok24h:{booking_id}",
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(
                text="❌ Не смогу — перенести/отменить",
                callback_data=f"reminder:manage:{booking_id}",
                style=ButtonStyle.DANGER,
            ),
        ]
    ]
    if address_map_url:
        rows.append(
            [
                _build_client_repeated_url_button(
                    key="open_map",
                    fallback_text="🗺 Открыть в Яндекс Картах",
                    fallback_style_name="primary",
                    url=address_map_url,
                    button_configs=button_configs,
                )
            ]
        )
    if address_copy_text:
        rows.append([_build_copy_text_button("📋 Скопировать адрес", address_copy_text)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_reminder_2h_keyboard(
    booking_id: int,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build actions under the 2h reminder."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Буду",
                    callback_data=f"reminder:ok2h:{booking_id}",
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    text="❌ Не смогу — перенести/отменить",
                    callback_data=f"reminder:manage:{booking_id}",
                    style=ButtonStyle.DANGER,
                ),
            ],
            [
                _build_client_my_bookings_action_button(
                    key="late",
                    fallback_text="⏰ Опаздываю",
                    fallback_style_name="primary",
                    callback_data=f"my_bookings:late:{booking_id}",
                    button_configs=button_configs,
                )
            ],
        ]
    )


def build_reminder_confirmed_keyboard(
    booking_id: int,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build follow-up actions shown after the client confirms the reminder."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📍 Адрес",
                    callback_data="client_menu:address",
                    style=ButtonStyle.PRIMARY,
                ),
                _build_client_my_bookings_action_button(
                    key="late",
                    fallback_text="⏰ Опаздываю",
                    fallback_style_name="primary",
                    callback_data=f"my_bookings:late:{booking_id}",
                    button_configs=button_configs,
                ),
            ],
            [
                _build_client_my_bookings_action_button(
                    key="reschedule",
                    fallback_text="✏️ Перенести",
                    fallback_style_name="primary",
                    callback_data=f"my_bookings:reschedule:{booking_id}",
                    button_configs=button_configs,
                )
            ],
        ]
    )


def build_late_notice_minutes_keyboard(
    booking_id: int,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the first-step minute picker for late-arrival reporting."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="5 мин",
                    callback_data=f"my_bookings:late_minutes:{booking_id}:5",
                ),
                InlineKeyboardButton(
                    text="10 мин",
                    callback_data=f"my_bookings:late_minutes:{booking_id}:10",
                ),
                InlineKeyboardButton(
                    text="15 мин",
                    callback_data=f"my_bookings:late_minutes:{booking_id}:15",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="20 мин",
                    callback_data=f"my_bookings:late_minutes:{booking_id}:20",
                ),
                InlineKeyboardButton(
                    text="30+ мин",
                    callback_data=f"my_bookings:late_minutes:{booking_id}:30",
                ),
            ],
            *navigation_rows(
                f"my_bookings:open:{booking_id}",
                button_configs=button_configs,
            ),
        ]
    )


def build_late_notice_reason_keyboard(
    booking_id: int,
    minutes: int,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the late-arrival reason picker."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚗 Пробки",
                    callback_data=f"my_bookings:late_reason:{booking_id}:{minutes}:traffic",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚇 Транспорт",
                    callback_data=f"my_bookings:late_reason:{booking_id}:{minutes}:transport",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📍 Ищу адрес",
                    callback_data=f"my_bookings:late_reason:{booking_id}:{minutes}:address",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏳ Задержали",
                    callback_data=f"my_bookings:late_reason:{booking_id}:{minutes}:delayed",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Другое",
                    callback_data=f"my_bookings:late_reason:{booking_id}:{minutes}:other",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏭ Пропустить",
                    callback_data=f"my_bookings:late_reason:{booking_id}:{minutes}:skip",
                )
            ],
            *navigation_rows(
                f"my_bookings:late:{booking_id}",
                button_configs=button_configs,
            ),
        ]
    )


def build_late_notice_result_keyboard(
    booking_id: int,
    *,
    allow_reschedule_request: bool,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the keyboard shown after a late-arrival notice is sent."""
    rows: list[list[InlineKeyboardButton]] = []
    if allow_reschedule_request:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗓 Лучше попросить другое время",
                    callback_data=f"my_bookings:reschedule:{booking_id}",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
    rows.extend(
        navigation_rows(
            f"my_bookings:open:{booking_id}",
            button_configs=button_configs,
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_repair_nails_keyboard(
    booking_id: int,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the nail-count picker for a repair request."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1", callback_data=f"repair:nails:{booking_id}:1"),
                InlineKeyboardButton(text="2", callback_data=f"repair:nails:{booking_id}:2"),
                InlineKeyboardButton(text="3", callback_data=f"repair:nails:{booking_id}:3"),
            ],
            [
                InlineKeyboardButton(text="4", callback_data=f"repair:nails:{booking_id}:4"),
                InlineKeyboardButton(text="5+", callback_data=f"repair:nails:{booking_id}:5"),
            ],
            *navigation_rows(
                f"my_bookings:open:{booking_id}",
                button_configs=button_configs,
            ),
        ]
    )


def build_repair_issue_keyboard(
    booking_id: int,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the repair issue-type picker."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Скол",
                    callback_data=f"repair:issue:{booking_id}:chip",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Трещина",
                    callback_data=f"repair:issue:{booking_id}:crack",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отслойка",
                    callback_data=f"repair:issue:{booking_id}:lifting",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Сломался",
                    callback_data=f"repair:issue:{booking_id}:broken",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Другое",
                    callback_data=f"repair:issue:{booking_id}:other",
                )
            ],
            *navigation_rows(
                f"repair:start:{booking_id}",
                button_configs=button_configs,
            ),
        ]
    )


def build_repair_photos_keyboard(
    booking_id: int,
    *,
    can_finish: bool,
    can_remove_last: bool,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build actions while the client uploads repair photos."""
    rows: list[list[InlineKeyboardButton]] = []
    if can_finish:
        rows.append(
            [
                done_button(
                    f"repair:photos_done:{booking_id}",
                    button_configs=button_configs,
                )
            ]
        )
    if can_remove_last:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Убрать последнее фото",
                    callback_data=f"repair:remove_last:{booking_id}",
                )
            ]
        )
    rows.extend(
        navigation_rows(
            f"repair:photos_back:{booking_id}",
            button_configs=button_configs,
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_repair_description_keyboard(
    booking_id: int,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the back action for the repair-description step."""
    return InlineKeyboardMarkup(
        inline_keyboard=navigation_rows(
            f"repair:description_back:{booking_id}",
            button_configs=button_configs,
        )
    )


def build_postvisit_rating_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    """Build the simple MVP post-visit rating keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐", callback_data=f"postvisit:rate:{booking_id}:1"),
                InlineKeyboardButton(text="⭐⭐", callback_data=f"postvisit:rate:{booking_id}:2"),
                InlineKeyboardButton(text="⭐⭐⭐", callback_data=f"postvisit:rate:{booking_id}:3"),
                InlineKeyboardButton(
                    text="⭐⭐⭐⭐", callback_data=f"postvisit:rate:{booking_id}:4"
                ),
                InlineKeyboardButton(
                    text="⭐⭐⭐⭐⭐", callback_data=f"postvisit:rate:{booking_id}:5"
                ),
            ]
        ]
    )


def build_repeat_prompt_keyboard(
    last_booking_id: int | None = None,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build actions under the repeat prompt."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔁 Повторить прошлую запись",
                    callback_data=(
                        f"repeat_prompt:repeat_last:{last_booking_id}"
                        if last_booking_id is not None
                        else "repeat_prompt:repeat_last"
                    ),
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [_build_browse_cta_button(button_configs=button_configs)],
            [
                InlineKeyboardButton(
                    text="⏳ Через 1 неделю",
                    callback_data="repeat_prompt:snooze:1",
                ),
                InlineKeyboardButton(
                    text="⏳ Через 2 недели",
                    callback_data="repeat_prompt:snooze:2",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🙈 Пока не напоминать",
                    callback_data="repeat_prompt:snooze:0",
                    style=ButtonStyle.DANGER,
                ),
            ],
        ]
    )


def build_rescue_offer_keyboard(slot_id: int) -> InlineKeyboardMarkup:
    """Build actions under a last-minute free-slot offer."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌸 Забрать это окошко",
                    callback_data=f"rescue_offer:claim:{slot_id}",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Не сейчас",
                    callback_data=f"rescue_offer:dismiss:{slot_id}",
                )
            ],
        ]
    )


def build_name_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Build the onboarding name confirmation keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, всё верно",
                    callback_data="onboarding:name_yes",
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(text="✏️ Другое имя", callback_data="onboarding:name_other"),
            ]
        ]
    )


def build_phone_manual_keyboard() -> InlineKeyboardMarkup:
    """Build the inline keyboard for manual phone entry."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=PHONE_MANUAL_BUTTON_TEXT,
                    callback_data="onboarding:phone_manual",
                )
            ]
        ]
    )


PHONE_MANUAL_BUTTON_TEXT = "✏️ Ввести вручную"


def build_contact_request_keyboard() -> ReplyKeyboardMarkup:
    """Build the contact-request reply keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📱 Поделиться контактом",
                    request_contact=True,
                )
            ],
            [KeyboardButton(text=PHONE_MANUAL_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def build_note_skip_keyboard() -> ReplyKeyboardMarkup:
    """Build the reply keyboard for skipping an optional note."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⏭ Пропустить")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def build_base_services_keyboard(
    services: list[Service],
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the base-service selection keyboard."""
    rows = [
        [
            InlineKeyboardButton(
                text=service.name,
                callback_data=f"booking:base:{service.id}",
                style=ButtonStyle.PRIMARY,
            )
        ]
        for service in services
    ]
    rows.append([home_button("booking:cancel", button_configs=button_configs)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_addons_keyboard(
    addons: list[Service],
    selected_ids: list[int],
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the add-on toggle keyboard."""
    rows = []
    for addon in addons:
        prefix = "✅" if addon.id in selected_ids else "⬜️"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix} {addon.name}",
                    callback_data=f"booking:addon_toggle:{addon.id}",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )

    rows.append([done_button("booking:addons_done", button_configs=button_configs)])
    rows.extend(
        navigation_rows(
            "booking:addons_back",
            button_configs=button_configs,
            home_callback="booking:cancel",
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_payment_method_keyboard(
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the payment-method choice keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _build_client_repeated_action_button(
                    key="payment_cash",
                    fallback_text="💵 Наличными (предпочтительно)",
                    fallback_style_name="success",
                    callback_data=f"booking:payment:{PAYMENT_METHOD_CASH}",
                    button_configs=button_configs,
                )
            ],
            [
                _build_client_repeated_action_button(
                    key="payment_transfer",
                    fallback_text="💳 Переводом",
                    fallback_style_name="primary",
                    callback_data=f"booking:payment:{PAYMENT_METHOD_TRANSFER}",
                    button_configs=button_configs,
                )
            ],
            *navigation_rows(
                "booking:payment_back",
                button_configs=button_configs,
                home_callback="booking:cancel",
            ),
        ]
    )


def build_days_keyboard(
    day_options: list[DayOption],
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the day selection keyboard."""
    day_buttons = [
        InlineKeyboardButton(
            text=day_option.label,
            callback_data=f"booking:day:{day_option.local_date.isoformat()}",
        )
        for day_option in day_options
    ]

    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(day_buttons), 2):
        rows.append(day_buttons[index : index + 2])

    rows.extend(
        [
            [
                _build_client_repeated_action_button(
                    key="other_day",
                    fallback_text="❓ Нужна другая дата",
                    fallback_style_name="default",
                    callback_data="booking:other_day",
                    button_configs=button_configs,
                )
            ],
            *navigation_rows(
                "booking:day_back",
                button_configs=button_configs,
                home_callback="booking:cancel",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_schedule_days_keyboard(
    day_options: list[DayOption],
    *,
    current_page: int,
    total_pages: int,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build day buttons for the current schedule-image page only."""
    day_buttons = [
        InlineKeyboardButton(
            text=day_option.label,
            callback_data=f"booking:day:{day_option.local_date.isoformat()}",
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
                    callback_data=f"booking:schedule_page:{current_page - 1}",
                )
            )
        nav_row.append(
            InlineKeyboardButton(
                text=f"Стр. {current_page + 1}/{total_pages}",
                callback_data="booking:schedule_noop",
            )
        )
        if current_page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"booking:schedule_page:{current_page + 1}",
                )
            )
        rows.append(nav_row)

    rows.extend(
        [
            [
                _build_client_repeated_action_button(
                    key="other_day",
                    fallback_text="❓ Нужна другая дата",
                    fallback_style_name="default",
                    callback_data="booking:other_day",
                    button_configs=button_configs,
                )
            ],
            *navigation_rows(
                "booking:day_back",
                button_configs=button_configs,
                home_callback="booking:cancel",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_reschedule_schedule_days_keyboard(
    booking_id: int,
    day_options: list[DayOption],
    *,
    current_page: int,
    total_pages: int,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build paginated reschedule day buttons for the current schedule-image page."""
    day_buttons = [
        InlineKeyboardButton(
            text=day_option.label,
            callback_data=(
                f"my_bookings:reschedule_day:{booking_id}:{day_option.local_date.isoformat()}"
            ),
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
                    callback_data=f"my_bookings:reschedule_page:{booking_id}:{current_page - 1}",
                )
            )
        nav_row.append(
            InlineKeyboardButton(
                text=f"Стр. {current_page + 1}/{total_pages}",
                callback_data="my_bookings:reschedule_noop",
            )
        )
        if current_page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"my_bookings:reschedule_page:{booking_id}:{current_page + 1}",
                )
            )
        rows.append(nav_row)

    rows.extend(
        [
            [
                _build_client_repeated_action_button(
                    key="other_day",
                    fallback_text="❓ Нужна другая дата",
                    fallback_style_name="default",
                    callback_data=f"my_bookings:reschedule_other_day:{booking_id}",
                    button_configs=button_configs,
                )
            ],
            *navigation_rows(
                f"my_bookings:open:{booking_id}",
                button_configs=button_configs,
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_reschedule_days_keyboard(
    booking_id: int,
    day_options: list[DayOption],
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the day selection keyboard for rescheduling."""
    day_buttons = [
        InlineKeyboardButton(
            text=day_option.label,
            callback_data=f"my_bookings:reschedule_day:{booking_id}:{day_option.local_date.isoformat()}",
        )
        for day_option in day_options
    ]

    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(day_buttons), 2):
        rows.append(day_buttons[index : index + 2])

    rows.append(
        [
            _build_client_repeated_action_button(
                key="other_day",
                fallback_text="❓ Нужна другая дата",
                fallback_style_name="default",
                callback_data=f"my_bookings:reschedule_other_day:{booking_id}",
                button_configs=button_configs,
            )
        ]
    )
    rows.extend(
        navigation_rows(
            f"my_bookings:open:{booking_id}",
            button_configs=button_configs,
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_no_slots_keyboard(
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
    contact_url: str | None = None,
) -> InlineKeyboardMarkup:
    """Build actions for the no-slots state."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _build_contact_cta_button(
                    button_configs=button_configs,
                    contact_url=contact_url,
                )
            ],
            [home_button(button_configs=button_configs)],
        ]
    )


def build_times_keyboard(
    slots: list[Slot],
    tz_name: str,
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the time selection keyboard."""
    buttons = [
        InlineKeyboardButton(
            text=format_local_datetime(slot.start_at, tz_name).strftime("%H:%M"),
            callback_data=f"booking:time:{slot.id}",
        )
        for slot in slots
    ]

    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(buttons), 3):
        rows.append(buttons[index : index + 3])

    rows.extend(
        [
            [
                _build_client_repeated_action_button(
                    key="other_time",
                    fallback_text="⏰ Хочу другое время в этот день",
                    fallback_style_name="default",
                    callback_data="booking:other_time",
                    button_configs=button_configs,
                )
            ],
            *navigation_rows(
                "booking:time_back",
                button_configs=button_configs,
                home_callback="booking:cancel",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_reschedule_times_keyboard(
    booking_id: int,
    slots: list[Slot],
    tz_name: str,
    *,
    local_day: date,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the time selection keyboard for rescheduling."""
    buttons = [
        InlineKeyboardButton(
            text=format_local_datetime(slot.start_at, tz_name).strftime("%H:%M"),
            callback_data=f"my_bookings:reschedule_slot:{booking_id}:{slot.id}",
        )
        for slot in slots
    ]

    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(buttons), 3):
        rows.append(buttons[index : index + 3])

    rows.append(
        [
            _build_client_repeated_action_button(
                key="other_time",
                fallback_text="⏰ Хочу другое время в этот день",
                fallback_style_name="default",
                callback_data=f"my_bookings:reschedule_other_time:{booking_id}:{local_day.isoformat()}",
                button_configs=button_configs,
            )
        ]
    )
    rows.extend(
        navigation_rows(
            f"my_bookings:reschedule_days_back:{booking_id}",
            button_configs=button_configs,
            back_text="⬅️ К дням",
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_reference_prompt_keyboard() -> InlineKeyboardMarkup:
    """Build the initial reference-photo prompt keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📸 Приложить фото", callback_data="booking:attach_photo"
                ),
                InlineKeyboardButton(text="⏭ Пропустить", callback_data="booking:skip_reference"),
            ]
        ]
    )


def build_reference_actions_keyboard(
    *,
    can_finish: bool,
    has_photos: bool,
    can_add_more: bool,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the keyboard shown after at least one reference action."""
    first_row = [
        InlineKeyboardButton(
            text="📝 Добавить комментарий", callback_data="booking:reference_comment"
        )
    ]
    if can_finish:
        first_row.append(done_button("booking:reference_done", button_configs=button_configs))

    rows = [first_row]
    if has_photos:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Убрать последнее",
                    callback_data="booking:reference_remove_last",
                    style=ButtonStyle.DANGER,
                )
            ]
        )
    if can_add_more:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📸 Добавить ещё фото", callback_data="booking:attach_photo"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_confirm_keyboard(
    *,
    button_configs: dict[str, ClientMenuButtonConfig] | None = None,
) -> InlineKeyboardMarkup:
    """Build the final booking confirmation keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                done_button(
                    "booking:confirm",
                    button_configs=button_configs,
                    text_override="✅ Подтвердить",
                )
            ],
            [back_button("booking:confirm_back", button_configs=button_configs)],
            [home_button("booking:cancel", button_configs=button_configs)],
        ]
    )
