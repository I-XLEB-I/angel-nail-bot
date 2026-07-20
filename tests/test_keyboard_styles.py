from __future__ import annotations

from datetime import UTC, datetime

from aiogram.enums import ButtonStyle

from src.bot.keyboards.admin import (
    build_admin_approval_actions_keyboard,
    build_admin_emoji_id_keyboard,
    build_admin_schedule_image_keyboard,
    build_admin_schedule_menu,
    build_admin_settings_edit_keyboard,
    build_admin_settings_keyboard,
    build_admin_stats_period_keyboard,
    build_admin_template_categories_keyboard,
    build_admin_template_category_keyboard,
    build_admin_template_detail_keyboard,
    build_admin_template_group_keyboard,
    build_force_majeure_day_keyboard,
    build_schedule_preview_keyboard,
    build_week_slot_keyboard,
)
from src.bot.keyboards.client import (
    ANGELA_CHAT_URL,
    PORTFOLIO_CUSTOM_EMOJI_ID,
    build_addons_keyboard,
    build_base_services_keyboard,
    build_booking_card_keyboard,
    build_client_card_keyboard,
    build_client_fallback_keyboard,
    build_client_main_menu,
    build_confirm_keyboard,
    build_payment_method_keyboard,
    build_portfolio_keyboard,
    build_proxy_reply_keyboard,
    build_reference_actions_keyboard,
    build_reminder_2h_keyboard,
    build_reminder_24h_keyboard,
    build_reminder_confirmed_keyboard,
    build_repair_description_keyboard,
    build_repair_photos_keyboard,
    build_repeat_prompt_keyboard,
    build_reschedule_times_keyboard,
    build_schedule_days_keyboard,
    build_services_actions_keyboard,
    build_times_keyboard,
    build_vitrine_actions_keyboard,
)
from src.db.models import ApprovalRequestKind, Service, ServiceKind, Slot, SlotStatus
from src.services.admin_defaults import list_template_categories, list_template_definitions
from src.services.booking import DayOption
from src.services.button_configs import (
    DEFAULT_PORTFOLIO_CHANNEL_URL,
    NAVIGATION_CUSTOM_EMOJI_ID,
    ClientMenuButtonConfig,
)


def test_client_main_menu_marks_booking_cta_as_success() -> None:
    keyboard = build_client_main_menu(show_my_bookings=True)
    buttons = {
        button.callback_data or button.url: button
        for row in keyboard.inline_keyboard
        for button in row
    }

    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.SUCCESS
    assert keyboard.inline_keyboard[0][0].callback_data == "client_menu:book"
    assert keyboard.inline_keyboard[0][1].style == ButtonStyle.PRIMARY
    assert keyboard.inline_keyboard[1][0].style == ButtonStyle.PRIMARY
    assert buttons[DEFAULT_PORTFOLIO_CHANNEL_URL].icon_custom_emoji_id == (
        PORTFOLIO_CUSTOM_EMOJI_ID
    )
    assert buttons[DEFAULT_PORTFOLIO_CHANNEL_URL].callback_data is None
    assert "client_menu:about" not in buttons
    assert buttons[ANGELA_CHAT_URL].url == ANGELA_CHAT_URL


def test_client_main_menu_accepts_runtime_button_overrides() -> None:
    keyboard = build_client_main_menu(
        show_my_bookings=True,
        button_configs={
            "book": ClientMenuButtonConfig(text="✨ Хочу записаться", style_name="primary"),
            "portfolio": ClientMenuButtonConfig(
                text="🌸 О мастере и работах",
                style_name="danger",
                icon_custom_emoji_id="123456",
            ),
        },
    )
    portfolio_button = next(
        button
        for row in keyboard.inline_keyboard
        for button in row
        if button.url == DEFAULT_PORTFOLIO_CHANNEL_URL
    )

    assert keyboard.inline_keyboard[0][0].text == "✨ Хочу записаться"
    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.PRIMARY
    assert portfolio_button.text == "🌸 О мастере и работах"
    assert portfolio_button.style == ButtonStyle.DANGER
    assert portfolio_button.icon_custom_emoji_id == "123456"


def test_client_main_menu_accepts_runtime_contact_url() -> None:
    keyboard = build_client_main_menu(
        show_my_bookings=True,
        contact_url="tg://resolve?domain=angels_new_username&text=Hi",
    )
    buttons = {
        button.callback_data or button.url: button
        for row in keyboard.inline_keyboard
        for button in row
    }

    assert "tg://resolve?domain=angels_new_username&text=Hi" in buttons


def test_client_main_menu_prefers_contact_url_override_from_button_config() -> None:
    keyboard = build_client_main_menu(
        show_my_bookings=True,
        contact_url="tg://resolve?domain=angels_default&text=Hi",
        button_configs={
            "contact": ClientMenuButtonConfig(
                text="💌 Написать Ангеле",
                style_name="success",
                url="https://t.me/angels_custom",
            )
        },
    )
    contact_button = keyboard.inline_keyboard[-1][0]

    assert contact_button.text == "💌 Написать Ангеле"
    assert contact_button.url == "https://t.me/angels_custom"
    assert contact_button.style == ButtonStyle.SUCCESS


def test_services_and_fallback_reuse_main_menu_button_overrides() -> None:
    configs = {
        "client_main_menu.book": ClientMenuButtonConfig(
            text="🪄 Хочу записаться",
            style_name="primary",
        ),
        "client_main_menu.browse": ClientMenuButtonConfig(
            text="🪟 Свободные окна",
            style_name="danger",
            icon_custom_emoji_id="654321",
        ),
        "client_main_menu.contact": ClientMenuButtonConfig(
            text="💌 Написать Ангеле",
            style_name="success",
        ),
        "common.back": ClientMenuButtonConfig(
            text="↩︎ Назад",
            style_name="danger",
        ),
    }

    services_keyboard = build_services_actions_keyboard(button_configs=configs)
    fallback_keyboard = build_client_fallback_keyboard(button_configs=configs)

    assert services_keyboard.inline_keyboard[0][0].text == "🪄 Хочу записаться"
    assert services_keyboard.inline_keyboard[0][0].callback_data == "client_menu:book"
    assert services_keyboard.inline_keyboard[0][0].style == ButtonStyle.PRIMARY
    assert services_keyboard.inline_keyboard[1][0].text == "🪟 Свободные окна"
    assert services_keyboard.inline_keyboard[1][0].callback_data == "client_menu:browse"
    assert services_keyboard.inline_keyboard[1][0].style == ButtonStyle.DANGER
    assert services_keyboard.inline_keyboard[1][0].icon_custom_emoji_id == "654321"
    assert fallback_keyboard.inline_keyboard[0][0].text == "🪄 Хочу записаться"
    assert fallback_keyboard.inline_keyboard[1][0].text == "💌 Написать Ангеле"
    assert fallback_keyboard.inline_keyboard[1][0].style == ButtonStyle.SUCCESS
    assert fallback_keyboard.inline_keyboard[2][0].text == "Главное меню"
    assert fallback_keyboard.inline_keyboard[2][0].icon_custom_emoji_id is not None


def test_client_card_reuses_main_menu_button_overrides() -> None:
    keyboard = build_client_card_keyboard(
        show_my_bookings=True,
        button_configs={
            "client_main_menu.book": ClientMenuButtonConfig(
                text="✨ Записаться сейчас",
                style_name="success",
            ),
            "client_main_menu.my_bookings": ClientMenuButtonConfig(
                text="📚 Мои визиты",
                style_name="danger",
            ),
        },
    )

    assert keyboard.inline_keyboard[0][0].text == "✨ Записаться сейчас"
    assert keyboard.inline_keyboard[1][0].text == "📚 Мои визиты"
    assert keyboard.inline_keyboard[1][0].style == ButtonStyle.DANGER


def test_booking_card_marks_cancellation_as_danger() -> None:
    keyboard = build_booking_card_keyboard(
        42,
        can_reschedule=True,
        can_cancel=True,
        cancel_label="❌ Отменить",
    )

    assert keyboard.inline_keyboard[0][1].style == ButtonStyle.DANGER
    assert keyboard.inline_keyboard[0][1].callback_data == "my_bookings:cancel:42"


def test_booking_card_marks_reschedule_as_primary() -> None:
    keyboard = build_booking_card_keyboard(
        42,
        can_reschedule=True,
        can_cancel=False,
        cancel_label="❌ Отменить",
    )

    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.PRIMARY
    assert keyboard.inline_keyboard[0][0].callback_data == "my_bookings:reschedule:42"


def test_booking_card_can_show_aftercare_buttons() -> None:
    keyboard = build_booking_card_keyboard(
        42,
        can_reschedule=True,
        can_cancel=False,
        cancel_label="❌ Отменить",
        show_late_button=True,
        show_repair_button=True,
    )

    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "⏰ Опаздываю" in labels
    assert "🛠 Ремонт / гарантия" in labels


def test_booking_card_accepts_runtime_my_bookings_overrides() -> None:
    keyboard = build_booking_card_keyboard(
        42,
        can_reschedule=True,
        can_cancel=False,
        cancel_label="❌ Отменить",
        show_late_button=True,
        show_repair_button=True,
        button_configs={
            "client_my_bookings.reschedule": ClientMenuButtonConfig(
                text="🧷 Сдвинуть",
                style_name="success",
            ),
            "client_my_bookings.late": ClientMenuButtonConfig(
                text="🚕 Задерживаюсь",
                style_name="danger",
            ),
            "client_my_bookings.repair": ClientMenuButtonConfig(
                text="🩹 Починка",
                style_name="primary",
            ),
        },
    )

    assert keyboard.inline_keyboard[0][0].text == "🧷 Сдвинуть"
    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.SUCCESS
    assert keyboard.inline_keyboard[1][0].text == "🚕 Задерживаюсь"
    assert keyboard.inline_keyboard[1][0].style == ButtonStyle.DANGER
    assert keyboard.inline_keyboard[2][0].text == "🩹 Починка"


def test_booking_card_back_like_button_reuses_common_back_icon() -> None:
    keyboard = build_booking_card_keyboard(
        42,
        can_reschedule=False,
        can_cancel=False,
        cancel_label="❌ Отменить",
        button_configs={
            "common.back": ClientMenuButtonConfig(
                text="⬅️ Назад",
                style_name="danger",
                icon_custom_emoji_id="777888",
            )
        },
    )

    back_like_button = keyboard.inline_keyboard[-2][0]
    assert back_like_button.text == "К моим записям"
    assert back_like_button.icon_custom_emoji_id == "777888"
    assert back_like_button.callback_data == "my_bookings:overview"
    home_button = keyboard.inline_keyboard[-1][0]
    assert home_button.text == "Главное меню"
    assert home_button.icon_custom_emoji_id == "777888"
    assert home_button.callback_data == "client_menu:back"


def test_reschedule_time_keyboard_accepts_back_button_overrides() -> None:
    slot = Slot(
        id=7,
        start_at=datetime.now(UTC),
        status=SlotStatus.FREE,
    )
    keyboard = build_reschedule_times_keyboard(
        42,
        [slot],
        "Europe/Moscow",
        local_day=datetime.now(UTC).date(),
        button_configs={
            "common.back": ClientMenuButtonConfig(
                text="⬅️ Назад",
                style_name="danger",
                icon_custom_emoji_id="777888",
            )
        },
    )

    back_like_button = keyboard.inline_keyboard[-2][0]
    assert back_like_button.text == "К дням"
    assert back_like_button.icon_custom_emoji_id == "777888"
    assert keyboard.inline_keyboard[-1][0].text == "Главное меню"
    assert keyboard.inline_keyboard[-1][0].icon_custom_emoji_id == "777888"


def test_vitrine_actions_keyboard_can_include_map_cta() -> None:
    keyboard = build_vitrine_actions_keyboard(
        address_map_url="https://yandex.ru/maps/test",
    )

    map_button = keyboard.inline_keyboard[0][0]
    assert map_button.text == "🗺 Открыть в Яндекс Картах"
    assert map_button.url == "https://yandex.ru/maps/test"
    assert map_button.style == ButtonStyle.PRIMARY


def test_repeated_client_ctas_accept_runtime_overrides() -> None:
    configs = {
        "client_repeated.payment_cash": ClientMenuButtonConfig(
            text="💸 Наличными",
            style_name="danger",
        ),
        "client_repeated.payment_transfer": ClientMenuButtonConfig(
            text="🏦 Перевести",
            style_name="success",
        ),
        "client_repeated.other_day": ClientMenuButtonConfig(
            text="🗓 Хочу другую дату",
            style_name="primary",
        ),
        "client_repeated.other_time": ClientMenuButtonConfig(
            text="🕰 Другое время",
            style_name="success",
        ),
        "client_repeated.open_map": ClientMenuButtonConfig(
            text="📍 Построить маршрут",
            style_name="danger",
            url="https://maps.example/route",
        ),
    }
    payment_keyboard = build_payment_method_keyboard(button_configs=configs)
    day_keyboard = build_schedule_days_keyboard(
        [
            DayOption(local_date=datetime.now(UTC).date(), label="Сегодня"),
        ],
        current_page=0,
        total_pages=1,
        button_configs=configs,
    )
    time_keyboard = build_times_keyboard(
        [Slot(start_at=datetime.now(UTC), status=SlotStatus.FREE)],
        "Europe/Moscow",
        button_configs=configs,
    )
    map_keyboard = build_vitrine_actions_keyboard(
        address_map_url="https://yandex.ru/maps/test",
        button_configs=configs,
    )
    reminder_keyboard = build_reminder_24h_keyboard(
        99,
        address_map_url="https://yandex.ru/maps/test",
        button_configs=configs,
    )

    assert payment_keyboard.inline_keyboard[0][0].text == "💸 Наличными"
    assert payment_keyboard.inline_keyboard[0][0].style == ButtonStyle.DANGER
    assert payment_keyboard.inline_keyboard[1][0].text == "🏦 Перевести"
    assert payment_keyboard.inline_keyboard[1][0].style == ButtonStyle.SUCCESS
    assert day_keyboard.inline_keyboard[-3][0].text == "🗓 Хочу другую дату"
    assert day_keyboard.inline_keyboard[-3][0].style == ButtonStyle.PRIMARY
    assert time_keyboard.inline_keyboard[-3][0].text == "🕰 Другое время"
    assert time_keyboard.inline_keyboard[-3][0].style == ButtonStyle.SUCCESS
    assert map_keyboard.inline_keyboard[0][0].text == "📍 Построить маршрут"
    assert map_keyboard.inline_keyboard[0][0].url == "https://maps.example/route"
    assert map_keyboard.inline_keyboard[0][0].style == ButtonStyle.DANGER
    assert reminder_keyboard.inline_keyboard[1][0].text == "📍 Построить маршрут"
    assert reminder_keyboard.inline_keyboard[1][0].url == "https://maps.example/route"


def test_confirm_keyboard_accepts_common_button_overrides() -> None:
    keyboard = build_confirm_keyboard(
        button_configs={
            "common.back": ClientMenuButtonConfig(text="◀︎ Назад", style_name="primary"),
        }
    )

    assert keyboard.inline_keyboard[1][0].text == "Назад"
    assert keyboard.inline_keyboard[1][0].style == ButtonStyle.PRIMARY
    assert keyboard.inline_keyboard[2][0].text == "Главное меню"
    assert keyboard.inline_keyboard[2][0].callback_data == "booking:cancel"
    assert (
        keyboard.inline_keyboard[1][0].icon_custom_emoji_id
        == keyboard.inline_keyboard[2][0].icon_custom_emoji_id
    )


def test_confirm_reuses_done_premium_emoji_and_style() -> None:
    keyboard = build_confirm_keyboard(
        button_configs={
            "common.done": ClientMenuButtonConfig(
                text="✅ Готово",
                style_name="primary",
                icon_custom_emoji_id="444555",
            )
        }
    )

    confirm_button = keyboard.inline_keyboard[0][0]
    assert confirm_button.text == "Подтвердить"
    assert confirm_button.style == ButtonStyle.PRIMARY
    assert confirm_button.icon_custom_emoji_id == "444555"
    assert confirm_button.callback_data == "booking:confirm"


def test_addons_keyboard_marks_toggle_buttons_as_primary() -> None:
    keyboard = build_addons_keyboard(
        [
            Service(
                id=1,
                name="Дизайн",
                price=250,
                price_variable=True,
                duration_min=30,
                kind=ServiceKind.ADDON,
                is_active=True,
                display_order=10,
            )
        ],
        selected_ids=[],
    )

    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.PRIMARY


def test_confirm_keyboard_uses_success_and_danger_styles() -> None:
    keyboard = build_confirm_keyboard()

    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.SUCCESS
    assert keyboard.inline_keyboard[1][0].style == ButtonStyle.DANGER


def test_reminder_keyboard_uses_semantic_styles() -> None:
    keyboard = build_reminder_24h_keyboard(99)

    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.SUCCESS
    assert keyboard.inline_keyboard[0][1].style == ButtonStyle.DANGER
    assert keyboard.inline_keyboard[0][0].callback_data == "reminder:ok24h:99"


def test_reminder_2h_keyboard_offers_late_notice() -> None:
    keyboard = build_reminder_2h_keyboard(99)
    labels = [button.text for row in keyboard.inline_keyboard for button in row]

    assert "⏰ Опаздываю" in labels
    assert keyboard.inline_keyboard[0][0].callback_data == "reminder:ok2h:99"


def test_reminder_keyboards_reuse_my_bookings_overrides() -> None:
    configs = {
        "client_my_bookings.late": ClientMenuButtonConfig(
            text="🚕 Задерживаюсь",
            style_name="danger",
        ),
        "client_my_bookings.reschedule": ClientMenuButtonConfig(
            text="🧷 Сдвинуть запись",
            style_name="success",
        ),
    }

    reminder_2h = build_reminder_2h_keyboard(99, button_configs=configs)
    reminder_confirmed = build_reminder_confirmed_keyboard(99, button_configs=configs)

    assert reminder_2h.inline_keyboard[1][0].text == "🚕 Задерживаюсь"
    assert reminder_2h.inline_keyboard[1][0].style == ButtonStyle.DANGER
    assert reminder_confirmed.inline_keyboard[0][1].text == "🚕 Задерживаюсь"
    assert reminder_confirmed.inline_keyboard[0][1].style == ButtonStyle.DANGER
    assert reminder_confirmed.inline_keyboard[1][0].text == "🧷 Сдвинуть запись"
    assert reminder_confirmed.inline_keyboard[1][0].style == ButtonStyle.SUCCESS


def test_repair_flow_keyboards_use_real_back_navigation() -> None:
    photo_keyboard = build_repair_photos_keyboard(
        42,
        can_finish=False,
        can_remove_last=False,
        button_configs={
            "common.back": ClientMenuButtonConfig(
                text="⬅️ Назад",
                style_name="danger",
                icon_custom_emoji_id="999111",
            )
        },
    )
    description_keyboard = build_repair_description_keyboard(
        42,
        button_configs={
            "common.back": ClientMenuButtonConfig(
                text="⬅️ Назад",
                style_name="danger",
                icon_custom_emoji_id="999111",
            )
        },
    )

    assert photo_keyboard.inline_keyboard[-2][0].callback_data == "repair:photos_back:42"
    assert photo_keyboard.inline_keyboard[-2][0].icon_custom_emoji_id == "999111"
    assert photo_keyboard.inline_keyboard[-1][0].callback_data == "client_menu:back"
    assert photo_keyboard.inline_keyboard[-1][0].icon_custom_emoji_id == "999111"
    assert description_keyboard.inline_keyboard[-2][0].callback_data == "repair:description_back:42"
    assert description_keyboard.inline_keyboard[-2][0].icon_custom_emoji_id == "999111"
    assert description_keyboard.inline_keyboard[-1][0].callback_data == "client_menu:back"


def test_repeat_prompt_reuses_browse_override() -> None:
    keyboard = build_repeat_prompt_keyboard(
        button_configs={
            "client_main_menu.browse": ClientMenuButtonConfig(
                text="👀 Хочу посмотреть окошки",
                style_name="danger",
                icon_custom_emoji_id="333444",
            ),
        }
    )

    assert keyboard.inline_keyboard[1][0].text == "👀 Хочу посмотреть окошки"
    assert keyboard.inline_keyboard[1][0].style == ButtonStyle.DANGER
    assert keyboard.inline_keyboard[1][0].icon_custom_emoji_id == "333444"


def test_admin_schedule_preview_uses_semantic_styles() -> None:
    keyboard = build_schedule_preview_keyboard()

    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.SUCCESS
    assert keyboard.inline_keyboard[2][0].style == ButtonStyle.DANGER


def test_admin_approval_actions_use_success_and_danger_styles() -> None:
    keyboard = build_admin_approval_actions_keyboard(
        approval_id=7,
        kind=ApprovalRequestKind.NEW_BOOKING,
        can_direct_confirm=True,
    )
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    decline_button = next(button for button in buttons if button.text == "❌ Отказать")

    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.SUCCESS
    assert keyboard.inline_keyboard[1][0].style == ButtonStyle.PRIMARY
    assert decline_button.style == ButtonStyle.DANGER


def test_admin_approval_actions_without_exact_time_use_primary_picker_cta() -> None:
    keyboard = build_admin_approval_actions_keyboard(
        approval_id=7,
        kind=ApprovalRequestKind.NEW_BOOKING,
        can_direct_confirm=False,
    )
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    decline_button = next(button for button in buttons if button.text == "❌ Отказать")

    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.PRIMARY
    assert decline_button.style == ButtonStyle.DANGER


def test_admin_question_approval_reply_uses_primary_style() -> None:
    keyboard = build_admin_approval_actions_keyboard(
        approval_id=7,
        kind=ApprovalRequestKind.QUESTION,
    )

    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.PRIMARY
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "✅ Прочитано" in labels
    assert "🔕 Тихо закрыть" in labels


def test_admin_repair_approval_actions_have_warranty_controls() -> None:
    keyboard = build_admin_approval_actions_keyboard(
        approval_id=7,
        kind=ApprovalRequestKind.REPAIR_REQUEST,
        repair_warranty_marked=False,
    )

    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "🛡 По гарантии" in labels
    assert "💸 Платно" in labels
    assert "🗓 Предложить время" in labels
    assert "🕰 Своё время" in labels
    assert "🔕 Тихо закрыть" in labels


def test_admin_repair_approval_actions_highlight_paid_mode() -> None:
    keyboard = build_admin_approval_actions_keyboard(
        approval_id=7,
        kind=ApprovalRequestKind.REPAIR_REQUEST,
        repair_paid_marked=True,
    )

    assert keyboard.inline_keyboard[0][1].text == "✅ Платно"
    assert keyboard.inline_keyboard[0][1].style == ButtonStyle.PRIMARY


def test_schedule_menu_shows_implemented_month_view_only() -> None:
    keyboard = build_admin_schedule_menu()
    labels = [button.text for row in keyboard.inline_keyboard for button in row]

    assert "🚫 Заблокировать период" not in labels
    assert "📅 На месяц" in labels
    assert "🖼 Картинка" not in labels
    assert keyboard.inline_keyboard[-1][0].text == "Главное меню"


def test_settings_keyboard_has_back_to_admin_menu() -> None:
    keyboard = build_admin_settings_keyboard()

    assert keyboard.inline_keyboard[-1][0].callback_data == "admin_menu:home"


def test_admin_main_menu_exposes_emoji_id_tool() -> None:
    from src.bot.keyboards.admin import build_admin_main_menu

    keyboard = build_admin_main_menu(pending_approvals=0)
    labels = [button.text for row in keyboard.keyboard for button in row]

    assert "✨ Emoji ID" in labels
    assert "🎛 Кнопки" in labels
    assert "🗓 Статусы на сегодня" in labels


def test_admin_emoji_id_keyboard_has_back_action() -> None:
    keyboard = build_admin_emoji_id_keyboard()

    assert keyboard.inline_keyboard[-1][0].callback_data == "admin_emoji_id:back"
    assert keyboard.inline_keyboard[-1][0].text == "Главное меню"


def test_force_majeure_exit_is_labeled_as_main_menu() -> None:
    keyboard = build_force_majeure_day_keyboard([("Сегодня", "2026-07-20")])

    assert keyboard.inline_keyboard[-1][0].callback_data == "admin_menu:home"
    assert keyboard.inline_keyboard[-1][0].text == "Главное меню"


def test_settings_edit_keyboard_has_home_shortcut() -> None:
    keyboard = build_admin_settings_edit_keyboard()

    assert keyboard.inline_keyboard[-1][0].callback_data == "admin_menu:home"


def test_admin_navigation_uses_one_premium_icon_for_cancel_and_home() -> None:
    keyboard = build_admin_settings_edit_keyboard()
    cancel_button = keyboard.inline_keyboard[-2][0]
    home_button = keyboard.inline_keyboard[-1][0]

    assert cancel_button.text == "Отмена"
    assert home_button.text == "Главное меню"
    assert cancel_button.icon_custom_emoji_id == NAVIGATION_CUSTOM_EMOJI_ID
    assert home_button.icon_custom_emoji_id == NAVIGATION_CUSTOM_EMOJI_ID


def test_stats_keyboard_has_back_to_admin_menu() -> None:
    keyboard = build_admin_stats_period_keyboard("current")

    assert keyboard.inline_keyboard[-1][0].callback_data == "admin_menu:home"


def test_templates_keyboards_include_back_and_home_navigation() -> None:
    categories = list(list_template_categories())
    home_keyboard = build_admin_template_categories_keyboard(categories)
    category_keyboard = build_admin_template_category_keyboard(
        "clients",
        [("repair", "🛠 Ремонт и гарантия")],
    )
    group_keyboard = build_admin_template_group_keyboard(
        "clients",
        "repair",
        list_template_definitions(category_key="clients")[:1],
    )
    detail_keyboard = build_admin_template_detail_keyboard(
        "booking_confirm",
        "admin_templates:group:clients:booking",
    )
    detail_with_media_keyboard = build_admin_template_detail_keyboard(
        "booking_confirm",
        "admin_templates:group:clients:booking",
        supports_media=True,
        has_media=True,
        has_bundled_media=True,
        uses_bundled_media=False,
        has_custom_text=True,
    )

    assert home_keyboard.inline_keyboard[-1][0].callback_data == "admin_menu:home"
    assert (
        category_keyboard.inline_keyboard[0][0].callback_data
        == "admin_templates:group:clients:repair"
    )
    assert category_keyboard.inline_keyboard[-2][0].callback_data == "admin_templates:home"
    assert category_keyboard.inline_keyboard[-1][0].callback_data == "admin_menu:home"
    assert group_keyboard.inline_keyboard[-2][0].callback_data == "admin_templates:category:clients"
    assert detail_keyboard.inline_keyboard[-1][0].callback_data == "admin_menu:home"
    media_callbacks = [
        button.callback_data for row in detail_with_media_keyboard.inline_keyboard for button in row
    ]
    assert "admin_templates:preview_image:booking_confirm" not in media_callbacks
    assert "admin_templates:restore_image:booking_confirm" in media_callbacks
    assert "admin_templates:reset_text:booking_confirm" in media_callbacks


def test_schedule_image_reset_uses_danger_style() -> None:
    keyboard = build_admin_schedule_image_keyboard(
        enabled=True,
        has_custom_background=True,
    )

    reset_button = next(
        button
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data == "admin_schedule_image:reset_background"
    )
    assert reset_button.style == ButtonStyle.DANGER


def test_week_slot_keyboard_marks_block_actions_semantically() -> None:
    free_slot = Slot(
        id=1,
        start_at=datetime.now(UTC),
        status=SlotStatus.FREE,
    )
    blocked_slot = Slot(
        id=2,
        start_at=datetime.now(UTC),
        status=SlotStatus.BLOCKED,
    )

    free_keyboard = build_week_slot_keyboard(free_slot)
    blocked_keyboard = build_week_slot_keyboard(blocked_slot)

    assert free_keyboard.inline_keyboard[0][0].style == ButtonStyle.DANGER
    assert free_keyboard.inline_keyboard[0][1].style == ButtonStyle.DANGER
    assert blocked_keyboard.inline_keyboard[0][1].style == ButtonStyle.SUCCESS


def test_portfolio_keyboard_uses_primary_cta() -> None:
    keyboard = build_portfolio_keyboard("https://t.me/example")

    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.PRIMARY


def test_portfolio_keyboard_reuses_main_menu_cta_overrides() -> None:
    keyboard = build_portfolio_keyboard(
        "https://t.me/example",
        button_configs={
            "client_main_menu.book": ClientMenuButtonConfig(
                text="✨ Записаться сейчас",
                style_name="danger",
                icon_custom_emoji_id="111222",
            ),
            "client_main_menu.browse": ClientMenuButtonConfig(
                text="👀 Посмотреть окна",
                style_name="success",
                icon_custom_emoji_id="333444",
            ),
        },
    )

    assert keyboard.inline_keyboard[1][0].text == "✨ Записаться сейчас"
    assert keyboard.inline_keyboard[1][0].style == ButtonStyle.DANGER
    assert keyboard.inline_keyboard[1][0].icon_custom_emoji_id == "111222"
    assert keyboard.inline_keyboard[2][0].text == "👀 Посмотреть окна"
    assert keyboard.inline_keyboard[2][0].style == ButtonStyle.SUCCESS
    assert keyboard.inline_keyboard[2][0].icon_custom_emoji_id == "333444"


def test_proxy_reply_keyboard_uses_primary_cta() -> None:
    keyboard = build_proxy_reply_keyboard(12)

    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.PRIMARY


def test_reference_remove_last_uses_danger_style() -> None:
    keyboard = build_reference_actions_keyboard(
        can_finish=True,
        has_photos=True,
        can_add_more=True,
    )

    assert keyboard.inline_keyboard[1][0].style == ButtonStyle.DANGER


def test_base_services_cancel_uses_danger_style() -> None:
    keyboard = build_base_services_keyboard(
        [
            Service(
                id=1,
                name="Маникюр",
                price=2400,
                price_variable=False,
                duration_min=120,
                kind=ServiceKind.BASE,
                is_active=True,
                display_order=10,
            )
        ]
    )

    assert keyboard.inline_keyboard[-1][0].style == ButtonStyle.DANGER
    assert keyboard.inline_keyboard[-1][0].text == "Главное меню"
    assert keyboard.inline_keyboard[-1][0].callback_data == "booking:cancel"
    assert keyboard.inline_keyboard[0][0].style == ButtonStyle.PRIMARY
    assert keyboard.inline_keyboard[0][0].text == "Маникюр"
