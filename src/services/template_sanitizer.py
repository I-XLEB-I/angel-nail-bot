from __future__ import annotations

from src.bot import texts

PLACEHOLDER_SNIPPETS: dict[str, tuple[str, ...]] = {
    "price": ("Сюда можно добавить актуальный прайс",),
    "navigation_public": ("[Ангела", "[ангела"),
    "address_post_confirm": ("[Ангела", "[ангела"),
    "booking_confirm": ("[Ангела", "[ангела"),
    "reminder_24h": ("[Ангела", "[ангела"),
    "reminder_2h": ("[Ангела", "[ангела"),
}

LEGACY_GREETING_HEADER = """🤍 ANGELS NAIL SPACE

Маникюрная студия Ангелы — уютное место, где делают красиво и без спешки.

✨ Что можно здесь:

┣ 📅 Посмотреть окошки и записаться
┣ 💰 Открыть актуальный прайс
┣ 📍 Узнать адрес и как дойти
┣ 📸 Заглянуть в портфолио
┗ 💬 Написать Ангеле напрямую

Выбирай раздел ниже 👇"""

LEGACY_PORTFOLIO_INTRO = """📸 РАБОТЫ И НАСТРОЕНИЕ

Свежие дизайны и новые работы Ангела выкладывает в Telegram-канале.

Открой кнопку ниже — загляни, там все последние дизайны. ✨"""

LEGACY_ABOUT_MASTER = """🌸 Знакомься — это Ангела

Ангела делает аккуратный, чистый маникюр в спокойной атмосфере — без спешки и лишнего шума.

Любит мягкие формы, носибельные оттенки и чтобы тебе было по-настоящему комфортно в кресле.

Если хочешь посмотреть свежие работы — открой канал ниже.
Если удобнее сначала уточнить детали — можно сразу написать Ангеле напрямую ✨"""

LEGACY_BOOKING_CONFIRM_COMPACT = """Записала тебя 🪄

📆 {date}, {time}

💅 {service}

{address}

Буду напоминать за сутки. Если что-то изменится — жми «Мои записи» в меню.

До встречи 🤍"""

LEGACY_ADDRESS_PUBLIC_WITH_INLINE_MAP = (
    "📍 АДРЕС И КАК ДОБРАТЬСЯ\n\n"
    "Очаковское шоссе, 5к3, подъезд 2\n\n"
    '🗺 <a href="https://yandex.ru/maps/213/moscow/house/ochakovskoye_shosse_5k3/'
    'Z04YcgFhTkEFQFtvfXp4dXtqbQ==/?indoorLevel=1&amp;ll=37.461811%2C55.694677&amp;z=17.96">'
    "Открыть в Яндекс Картах</a>\n\n"
    "Если захочешь уточнить дорогу заранее — можно сразу написать Ангеле 🌸"
)

LEGACY_ADDRESS_POST_CONFIRM_WITH_INLINE_MAP = (
    "📍 АДРЕС\n\n"
    "Очаковское шоссе, 5к3, подъезд 2\n\n"
    '🗺 <a href="https://yandex.ru/maps/213/moscow/house/ochakovskoye_shosse_5k3/'
    'Z04YcgFhTkEFQFtvfXp4dXtqbQ==/?indoorLevel=1&amp;ll=37.461811%2C55.694677&amp;z=17.96">'
    "Открыть в Яндекс Картах</a>\n\n"
    "Если что-то по дороге пойдёт не так — просто напиши, Ангела поможет 🌸"
)


def _normalize_export_prefix(key: str, stripped: str, default: str) -> str | None:
    """Strip accidental `template_key ...` export prefixes for selected templates."""
    if key not in {"greeting_header", "portfolio_intro", "about_master"}:
        return None
    if stripped == key:
        return default
    if stripped.startswith(key):
        cleaned = stripped.removeprefix(key).strip()
        return cleaned or default
    return None


def _normalize_greeting_header(content: str, stripped: str) -> str | None:
    """Return the canonical main-menu greeting when a legacy variant is stored."""
    if stripped == LEGACY_GREETING_HEADER.strip():
        return texts.MENU_HEADER
    if (
        "ANGELS NAIL SPACE" in stripped
        and "Маникюрная студия Ангелы" in stripped
        and "Что можно здесь" in stripped
    ):
        return texts.MENU_HEADER
    if stripped.startswith("MENU_HEADER"):
        cleaned = stripped.removeprefix("MENU_HEADER").strip(" =")
        return cleaned.strip().strip('"') or texts.MENU_HEADER
    return None


def _normalize_portfolio_intro(stripped: str) -> str | None:
    """Return the canonical portfolio intro when a legacy alias is stored."""
    if stripped == LEGACY_PORTFOLIO_INTRO.strip():
        return texts.PORTFOLIO_INTRO
    if "РАБОТЫ И НАСТРОЕНИЕ" in stripped and "Свежие дизайны" in stripped:
        return texts.PORTFOLIO_INTRO
    if stripped.startswith("PORTFOLIO_INTRO"):
        cleaned = stripped.removeprefix("PORTFOLIO_INTRO").strip(" =")
        return cleaned.strip().strip('"') or texts.PORTFOLIO_INTRO
    return None


def _normalize_about_master(stripped: str) -> str | None:
    """Return the canonical about-master copy when a legacy alias is stored."""
    if stripped == LEGACY_ABOUT_MASTER.strip():
        return texts.DEFAULT_ABOUT_MASTER_TEMPLATE
    if "Знакомься — это Ангела" in stripped and "чистый маникюр" in stripped:
        return texts.DEFAULT_ABOUT_MASTER_TEMPLATE
    if stripped.startswith("DEFAULT_ABOUT_MASTER_TEMPLATE"):
        cleaned = stripped.removeprefix("DEFAULT_ABOUT_MASTER_TEMPLATE").strip(" =")
        return cleaned.strip().strip('"') or texts.DEFAULT_ABOUT_MASTER_TEMPLATE
    return None


def _normalize_booking_confirm(stripped: str) -> str | None:
    """Return the canonical booking-confirm copy when an old compact variant is stored."""
    if stripped == LEGACY_BOOKING_CONFIRM_COMPACT.strip():
        return texts.DEFAULT_BOOKING_CONFIRM_TEMPLATE
    if (
        "Записала тебя" in stripped
        and "{date}" in stripped
        and "{time}" in stripped
        and "{service}" in stripped
        and "{address}" in stripped
        and "Буду напоминать за сутки" in stripped
        and "Мои записи" in stripped
        and "{address_block}" not in stripped
        and "────────────" not in stripped
    ):
        return texts.DEFAULT_BOOKING_CONFIRM_TEMPLATE
    return None


def normalize_template_content(key: str, content: str | None, default: str) -> str:
    """Return a safe user-facing template value instead of obvious placeholder content."""
    if content is None:
        return default

    stripped = content.strip()
    if not stripped:
        return default
    normalized_export = _normalize_export_prefix(key, stripped, default)
    if normalized_export is not None:
        return normalized_export
    if key == "greeting_header":
        normalized_greeting = _normalize_greeting_header(content, stripped)
        if normalized_greeting is not None:
            return normalized_greeting
    if key == "portfolio_intro":
        normalized_portfolio = _normalize_portfolio_intro(stripped)
        if normalized_portfolio is not None:
            return normalized_portfolio
    if key == "about_master":
        normalized_about = _normalize_about_master(stripped)
        if normalized_about is not None:
            return normalized_about
    if key == "booking_confirm":
        normalized_booking_confirm = _normalize_booking_confirm(stripped)
        if normalized_booking_confirm is not None:
            return normalized_booking_confirm
    if key == "navigation_public" and stripped == LEGACY_ADDRESS_PUBLIC_WITH_INLINE_MAP.strip():
        return texts.DEFAULT_ADDRESS_PUBLIC_TEMPLATE
    if (
        key == "address_post_confirm"
        and stripped == LEGACY_ADDRESS_POST_CONFIRM_WITH_INLINE_MAP.strip()
    ):
        return texts.DEFAULT_ADDRESS_POST_CONFIRM
    if key in {"navigation_public", "address_post_confirm"}:
        return content.replace("Очаковское шоссе, 5к3", "Очаковское шоссе, 5к4")

    for snippet in PLACEHOLDER_SNIPPETS.get(key, ()):
        if snippet in content:
            return default
    return content
