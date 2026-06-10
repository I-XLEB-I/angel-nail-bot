from __future__ import annotations

from aiogram.enums import ButtonStyle

from src.bot import texts
from src.bot.handlers.client import menu as menu_handler
from src.bot.handlers.client import portfolio as portfolio_handler
from src.bot.keyboards.admin import (
    build_admin_backgrounds_home_keyboard,
    build_admin_settings_edit_keyboard,
)
from src.bot.keyboards.client import build_back_to_menu_keyboard


def test_phase11_texts_keep_runtime_placeholders_normalized() -> None:
    assert "{first_name}" in texts.ONBOARDING_NAME_CONFIRM_TEXT
    assert r"{first\_name}" not in texts.ONBOARDING_NAME_CONFIRM_TEXT
    assert "+7" in texts.ONBOARDING_PHONE_MANUAL_INPUT_TEXT
    assert r"\+7" not in texts.ONBOARDING_PHONE_MANUAL_INPUT_TEXT
    assert "Ангела" in texts.DEFAULT_ADDRESS_POST_CONFIRM
    assert "загляни, там все последние дизайны." in texts.PORTFOLIO_INTRO
    assert "АКТУАЛЬНЫЙ ПРАЙС" in texts.DEFAULT_PRICE_TEMPLATE


def test_literal_template_key_is_not_used_as_menu_header() -> None:
    assert menu_handler.normalize_menu_header_text("greeting_header") == texts.MENU_HEADER


def test_prefixed_template_export_is_not_used_as_menu_header() -> None:
    raw = "greeting_header\n\nСтарый текст"
    assert menu_handler.normalize_menu_header_text(raw) == "Старый текст"


def test_legacy_menu_header_is_normalized_to_current_copy() -> None:
    raw = """🤍 ANGELS NAIL SPACE

Маникюрная студия Ангелы — уютное место, где делают красиво и без спешки.

✨ Что можно здесь:

┣ 📅 Посмотреть окошки и записаться
┣ 💰 Открыть актуальный прайс
┣ 📍 Узнать адрес и как дойти
┣ 📸 Заглянуть в портфолио
┗ 💬 Написать Ангеле напрямую

Выбирай раздел ниже 👇"""
    assert menu_handler.normalize_menu_header_text(raw) == texts.MENU_HEADER


def test_literal_template_key_is_not_used_as_portfolio_intro() -> None:
    assert (
        portfolio_handler.normalize_portfolio_intro_text("portfolio_intro") == texts.PORTFOLIO_INTRO
    )


def test_literal_template_key_is_not_used_as_about_master() -> None:
    assert (
        portfolio_handler.normalize_about_text("about_master")
        == texts.DEFAULT_ABOUT_MASTER_TEMPLATE
    )


def test_phase11_navigation_buttons_use_danger_style() -> None:
    client_keyboard = build_back_to_menu_keyboard()
    admin_settings_keyboard = build_admin_settings_edit_keyboard()
    admin_backgrounds_keyboard = build_admin_backgrounds_home_keyboard()

    assert client_keyboard.inline_keyboard[0][0].style == ButtonStyle.DANGER
    assert admin_settings_keyboard.inline_keyboard[0][0].style == ButtonStyle.DANGER
    assert admin_backgrounds_keyboard.inline_keyboard[-1][0].style == ButtonStyle.DANGER
