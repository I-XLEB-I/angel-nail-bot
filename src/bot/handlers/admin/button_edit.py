from __future__ import annotations

from html import escape
import re
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import clear_state_preserving_admin_panel, send_admin_panel
from src.bot.handlers.admin.menu import show_admin_menu
from src.bot.keyboards.admin import (
    build_admin_button_categories_keyboard,
    build_admin_button_detail_keyboard,
    build_admin_button_list_keyboard,
    build_admin_button_prompt_keyboard,
)
from src.bot.states import AdminButtonEdit
from src.config import Settings
from src.db.repositories.settings import SettingRepository
from src.services.button_configs import (
    BUTTON_STYLE_LABELS,
    ClientMenuButtonConfig,
    build_angela_chat_url,
    default_button_config,
    get_button_editor_category,
    get_editable_button_definition,
    list_button_editor_categories,
    list_editable_button_definitions_for_category,
    load_button_config,
    load_button_configs_for_category,
    load_master_contact_url,
    save_button_config,
)

router = Router(name="admin_button_edit")

BUTTON_EDITOR_ID_STATE = "admin_button_editor_id"
BUTTON_TEXT_MAX_LENGTH = 40
BUTTON_URL_MAX_LENGTH = 512
_TELEGRAM_USERNAME_RE = re.compile(r"^@?[A-Za-z0-9_]{5,32}$")


def _describe_button_destination(editor_id: str) -> str:
    """Explain one editable button in human-facing product language."""
    descriptions = {
        "client_main_menu.book": "открывает запись на услугу",
        "client_main_menu.my_bookings": "открывает раздел «Мои записи»",
        "client_main_menu.browse": "открывает свободные окошки",
        "client_main_menu.services": "открывает прайс и услуги",
        "client_main_menu.portfolio": "открывает экран «О Ангеле и работы»",
        "client_main_menu.address": "открывает адрес и навигацию",
        "client_main_menu.contact": "открывает чат с Ангелой",
        "common.back": "возвращает на шаг назад",
        "common.done": "подтверждает выбор на текущем шаге",
        "common.cancel_back": "отменяет текущий шаг и возвращает назад",
        "common.cancel_action": "отменяет текущее действие",
        "client_my_bookings.reschedule": "открывает перенос записи",
        "client_my_bookings.late": "открывает предупреждение об опоздании",
        "client_my_bookings.repair": "открывает заявку на ремонт / гарантию",
        "client_repeated.payment_cash": "выбирает оплату наличными",
        "client_repeated.payment_transfer": "выбирает оплату переводом",
        "client_repeated.other_day": "открывает выбор другой даты",
        "client_repeated.other_time": "открывает выбор другого времени в этот день",
        "client_repeated.open_map": "открывает маршрут в Яндекс Картах",
    }
    return descriptions.get(editor_id, "выполняет действие этой кнопки")


async def _resolve_current_button_url(
    *,
    editor_id: str,
    config: ClientMenuButtonConfig,
    repository: SettingRepository,
) -> str | None:
    """Resolve the active link for URL-backed buttons."""
    definition = get_editable_button_definition(editor_id)
    if definition.url is None:
        return None
    if config.url is not None:
        return config.url
    if editor_id == "client_main_menu.contact":
        return await load_master_contact_url(repository)
    return definition.url


def _normalize_button_url_input(editor_id: str, raw_value: str) -> str | None:
    """Validate and normalize one URL value typed in the admin editor."""
    candidate = raw_value.strip()
    if not candidate:
        return None
    if editor_id == "client_main_menu.contact" and _TELEGRAM_USERNAME_RE.fullmatch(candidate):
        return build_angela_chat_url(candidate)
    if candidate.startswith(("t.me/", "telegram.me/")):
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https", "tg"}:
        return None
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        return None
    if parsed.scheme == "tg" and not parsed.netloc:
        return None
    return candidate


def _render_button_detail_text(
    *,
    editor_id: str,
    config: ClientMenuButtonConfig,
    current_url: str | None = None,
) -> str:
    """Build the detail text for one editable button."""
    definition = get_editable_button_definition(editor_id)
    category = get_button_editor_category(definition.category_key)
    emoji = (
        f"<code>{escape(config.icon_custom_emoji_id)}</code>"
        if config.icon_custom_emoji_id
        else "не задан"
    )
    hint_lines: list[str] = []
    if config.icon_custom_emoji_id and any(
        char for char in config.text if not char.isalnum() and not char.isspace()
    ):
        hint_lines.extend(
            [
                "",
                "💡 Если в тексте кнопки уже есть обычный emoji, его можно убрать —"
                " тогда не будет двойного значка рядом с premium emoji.",
            ]
        )
    lines = [
        "🎛 <b>Редактор кнопки</b>",
        "",
        f"<b>Раздел:</b> {escape(category.title)}",
        f"<b>Кнопка:</b> {escape(definition.title)}",
        "",
        f"<b>Текст:</b> <code>{escape(config.text)}</code>",
        f"<b>Premium emoji:</b> {emoji}",
        f"<b>Цвет:</b> {BUTTON_STYLE_LABELS[config.style_name]}",
        f"<b>Действие:</b> {escape(_describe_button_destination(editor_id))}",
    ]
    if current_url is not None:
        lines.extend(
            [
                f"<b>Ссылка:</b> <code>{escape(current_url)}</code>",
                f"<b>Источник ссылки:</b> {'своя ссылка' if config.url else 'по умолчанию'}",
            ]
        )
    lines.extend(
        [
            "",
            "Живой вид кнопки показан ниже. "
            + (
                "Можно менять текст, premium emoji, цвет и ссылку."
                if current_url is not None
                else "Можно менять текст, premium emoji и цвет."
            ),
            *hint_lines,
        ]
    )
    return "\n".join(lines)


async def _show_button_categories(
    message: Message,
    state: FSMContext,
) -> None:
    """Show the top-level category picker for editable buttons."""
    await send_admin_panel(
        message,
        state,
        text=(
            "🎛 Кнопки\n\n"
            "Здесь можно менять названия, premium emoji и цвет кнопок. "
            "Редактируются только ключевые клиентские CTA, а не все кнопки бота. "
            "Сначала выбери раздел."
        ),
        reply_markup=build_admin_button_categories_keyboard(
            list(list_button_editor_categories())
        ),
    )


async def _show_button_list(
    message: Message,
    state: FSMContext,
    *,
    repository: SettingRepository,
    category_key: str,
) -> None:
    """Show the list of editable buttons inside one category."""
    configs = await load_button_configs_for_category(repository, category_key=category_key)
    items = [
        (definition, configs[definition.key])
        for definition in list_editable_button_definitions_for_category(category_key)
    ]
    category = get_button_editor_category(category_key)
    await send_admin_panel(
        message,
        state,
        text=f"🎛 {category.title}\n\nВыбери кнопку, которую хочешь отредактировать.",
        reply_markup=build_admin_button_list_keyboard(items, category_key=category_key),
    )


async def _show_button_detail(
    message: Message,
    state: FSMContext,
    *,
    repository: SettingRepository,
    editor_id: str,
) -> None:
    """Show one editable button."""
    config = await load_button_config(repository, editor_id=editor_id)
    current_url = await _resolve_current_button_url(
        editor_id=editor_id,
        config=config,
        repository=repository,
    )
    await send_admin_panel(
        message,
        state,
        text=_render_button_detail_text(
            editor_id=editor_id,
            config=config,
            current_url=current_url,
        ),
        reply_markup=build_admin_button_detail_keyboard(
            definition=get_editable_button_definition(editor_id),
            config=config,
        ),
        parse_mode="HTML",
    )


@router.message(lambda message: message.text == "🎛 Кнопки")
async def open_button_editor(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Open the admin button editor."""
    if not is_admin:
        return
    del db_session
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await _show_button_categories(message, state)


@router.callback_query(F.data == "admin_buttons:categories")
async def show_button_categories_callback(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Return from a button detail back to the category picker."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    if callback.message is None:
        return
    await _show_button_categories(callback.message, state)


@router.callback_query(F.data.startswith("admin_buttons:category:"))
async def open_button_category(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Open one button category."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return
    category_key = callback.data.rsplit(":", 1)[-1]
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    repository = SettingRepository(db_session)
    await _show_button_list(
        callback.message,
        state,
        repository=repository,
        category_key=category_key,
    )


@router.callback_query(F.data == "admin_buttons:back")
async def close_button_editor(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Return from the button editor back to the admin menu."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    if callback.message is not None:
        await show_admin_menu(
            callback.message,
            db_session=db_session,
            settings=settings,
            state=state,
        )


@router.callback_query(F.data == "admin_buttons:noop")
async def noop_button_preview(
    callback: CallbackQuery,
    *,
    is_admin: bool,
) -> None:
    """Acknowledge preview button taps inside the button editor."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer("Это превью кнопки ✨")


@router.callback_query(F.data.startswith("admin_buttons:open:"))
async def open_button_detail(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Open the selected button in the admin editor."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return
    editor_id = callback.data.rsplit(":", 1)[-1]
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    repository = SettingRepository(db_session)
    await _show_button_detail(
        callback.message,
        state,
        repository=repository,
        editor_id=editor_id,
    )


@router.callback_query(F.data.startswith("admin_buttons:text:"))
async def prompt_button_text_edit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Ask the admin to send a new button label."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer("Жду новый текст")
    if callback.message is None:
        return
    editor_id = callback.data.rsplit(":", 1)[-1]
    await state.update_data(**{BUTTON_EDITOR_ID_STATE: editor_id})
    await state.set_state(AdminButtonEdit.input_text)
    await send_admin_panel(
        callback.message,
        state,
        text="✏️ Пришли новый текст для этой кнопки одним сообщением.",
        reply_markup=build_admin_button_prompt_keyboard(editor_id),
    )


@router.callback_query(F.data.startswith("admin_buttons:emoji:"))
async def prompt_button_emoji_edit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Ask the admin to send one premium/custom emoji for the selected button."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer("Жду premium emoji")
    if callback.message is None:
        return
    editor_id = callback.data.rsplit(":", 1)[-1]
    await state.update_data(**{BUTTON_EDITOR_ID_STATE: editor_id})
    await state.set_state(AdminButtonEdit.await_emoji)
    await send_admin_panel(
        callback.message,
        state,
        text=(
            "✨ Пришли одним сообщением один premium/custom emoji — я поставлю его на кнопку.\n\n"
            "Если в тексте кнопки уже есть обычный emoji, лучше убрать его заранее — "
            "так кнопка будет выглядеть чище."
        ),
        reply_markup=build_admin_button_prompt_keyboard(editor_id),
    )


@router.callback_query(F.data.startswith("admin_buttons:url:"))
async def prompt_button_url_edit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Ask the admin to send a new link for one URL-backed button."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    if callback.message is None:
        return
    editor_id = callback.data.rsplit(":", 1)[-1]
    definition = get_editable_button_definition(editor_id)
    if definition.url is None:
        await callback.answer("У этой кнопки нет ссылки", show_alert=True)
        return
    await callback.answer("Жду новую ссылку")
    await state.update_data(**{BUTTON_EDITOR_ID_STATE: editor_id})
    await state.set_state(AdminButtonEdit.input_url)
    prompt_text = (
        "🔗 Пришли новую ссылку одним сообщением.\n\n"
        "Подойдут https://, http:// или tg:// ссылки.\n"
        "Для кнопки «Написать Ангеле» можно просто прислать @username."
        if editor_id == "client_main_menu.contact"
        else "🔗 Пришли новую ссылку одним сообщением.\n\n"
        "Подойдут https://, http:// или tg:// ссылки."
    )
    await send_admin_panel(
        callback.message,
        state,
        text=prompt_text,
        reply_markup=build_admin_button_prompt_keyboard(editor_id),
    )


@router.callback_query(F.data.startswith("admin_buttons:url_reset:"))
async def reset_button_url(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Drop a custom URL override and fall back to the default link."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    if callback.message is None:
        return
    editor_id = callback.data.rsplit(":", 1)[-1]
    definition = get_editable_button_definition(editor_id)
    if definition.url is None:
        await callback.answer("У этой кнопки нет ссылки", show_alert=True)
        return
    repository = SettingRepository(db_session)
    config = await load_button_config(repository, editor_id=editor_id)
    await save_button_config(
        repository,
        editor_id=editor_id,
        config=ClientMenuButtonConfig(
            text=config.text,
            style_name=config.style_name,
            icon_custom_emoji_id=config.icon_custom_emoji_id,
            url=None,
        ),
    )
    await db_session.commit()
    await callback.answer("Ссылку вернула к умолчанию")
    await _show_button_detail(
        callback.message,
        state,
        repository=repository,
        editor_id=editor_id,
    )


@router.callback_query(F.data.startswith("admin_buttons:style:"))
async def set_button_style(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Change the stored button style."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    if callback.message is None:
        return
    _, _, editor_id, style_name = callback.data.split(":", 3)
    repository = SettingRepository(db_session)
    config = await load_button_config(repository, editor_id=editor_id)
    await save_button_config(
        repository,
        editor_id=editor_id,
        config=ClientMenuButtonConfig(
            text=config.text,
            style_name=style_name,
            icon_custom_emoji_id=config.icon_custom_emoji_id,
            url=config.url,
        ),
    )
    await db_session.commit()
    await callback.answer("Цвет кнопки обновила")
    await _show_button_detail(
        callback.message,
        state,
        repository=repository,
        editor_id=editor_id,
    )


@router.callback_query(F.data.startswith("admin_buttons:clear_emoji:"))
async def clear_button_premium_emoji(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Remove the premium emoji icon from a button."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    if callback.message is None:
        return
    editor_id = callback.data.rsplit(":", 1)[-1]
    repository = SettingRepository(db_session)
    config = await load_button_config(repository, editor_id=editor_id)
    await save_button_config(
        repository,
        editor_id=editor_id,
        config=ClientMenuButtonConfig(
            text=config.text,
            style_name=config.style_name,
            icon_custom_emoji_id=None,
            url=config.url,
        ),
    )
    await db_session.commit()
    await callback.answer("Premium emoji убрала")
    await _show_button_detail(
        callback.message,
        state,
        repository=repository,
        editor_id=editor_id,
    )


@router.callback_query(F.data.startswith("admin_buttons:reset:"))
async def reset_button_config(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Reset a button to its default text, emoji and color."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    if callback.message is None:
        return
    editor_id = callback.data.rsplit(":", 1)[-1]
    definition = get_editable_button_definition(editor_id)
    repository = SettingRepository(db_session)
    await save_button_config(
        repository,
        editor_id=editor_id,
        config=default_button_config(definition),
    )
    await db_session.commit()
    await callback.answer("Кнопку вернула к умолчанию")
    await _show_button_detail(
        callback.message,
        state,
        repository=repository,
        editor_id=editor_id,
    )


@router.message(StateFilter(AdminButtonEdit.input_text))
async def save_button_text(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Persist a new button label and return to the detail card."""
    editor_id = (await state.get_data()).get(BUTTON_EDITOR_ID_STATE)
    if not isinstance(editor_id, str):
        await message.answer("Не нашла, какую кнопку редактировать. Открой раздел ещё раз 🤍")
        return
    new_text = (message.text or "").strip()
    if not new_text:
        await message.answer("Текст не должен быть пустым.")
        return
    if len(new_text) > BUTTON_TEXT_MAX_LENGTH:
        await message.answer(
            f"Кнопка получится слишком длинной. Оставь до {BUTTON_TEXT_MAX_LENGTH} символов 🤍"
        )
        return
    repository = SettingRepository(db_session)
    config = await load_button_config(repository, editor_id=editor_id)
    await save_button_config(
        repository,
        editor_id=editor_id,
        config=ClientMenuButtonConfig(
            text=new_text,
            style_name=config.style_name,
            icon_custom_emoji_id=config.icon_custom_emoji_id,
            url=config.url,
        ),
    )
    await db_session.commit()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await _show_button_detail(
        message,
        state,
        repository=repository,
        editor_id=editor_id,
    )


@router.message(StateFilter(AdminButtonEdit.await_emoji))
async def save_button_emoji(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Persist a premium/custom emoji id for the selected button."""
    editor_id = (await state.get_data()).get(BUTTON_EDITOR_ID_STATE)
    if not isinstance(editor_id, str):
        await message.answer("Не нашла, какую кнопку редактировать. Открой раздел ещё раз 🤍")
        return
    entities = list(message.entities or [])
    custom_emoji_id = next(
        (
            entity.custom_emoji_id
            for entity in entities
            if str(entity.type) == "custom_emoji" and entity.custom_emoji_id
        ),
        None,
    )
    if not custom_emoji_id:
        await message.answer("Это не premium/custom emoji. Пришли именно такой эмодзи ✨")
        return
    repository = SettingRepository(db_session)
    config = await load_button_config(repository, editor_id=editor_id)
    await save_button_config(
        repository,
        editor_id=editor_id,
        config=ClientMenuButtonConfig(
            text=config.text,
            style_name=config.style_name,
            icon_custom_emoji_id=custom_emoji_id,
            url=config.url,
        ),
    )
    await db_session.commit()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await _show_button_detail(
        message,
        state,
        repository=repository,
        editor_id=editor_id,
    )


@router.message(StateFilter(AdminButtonEdit.input_url))
async def save_button_url(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Persist a custom link for one URL-backed button."""
    editor_id = (await state.get_data()).get(BUTTON_EDITOR_ID_STATE)
    if not isinstance(editor_id, str):
        await message.answer("Не нашла, какую кнопку редактировать. Открой раздел ещё раз 🤍")
        return
    if get_editable_button_definition(editor_id).url is None:
        await message.answer("У этой кнопки нет ссылки для редактирования.")
        return
    raw_url = (message.text or "").strip()
    if not raw_url:
        await message.answer("Ссылка не должна быть пустой.")
        return
    if len(raw_url) > BUTTON_URL_MAX_LENGTH:
        await message.answer(
            f"Ссылка получилась слишком длинной. Оставь до {BUTTON_URL_MAX_LENGTH} символов 🤍"
        )
        return
    normalized_url = _normalize_button_url_input(editor_id, raw_url)
    if normalized_url is None:
        await message.answer(
            "Не смогла распознать ссылку. Пришли https://, http:// или tg:// ссылку 🤍"
        )
        return
    repository = SettingRepository(db_session)
    config = await load_button_config(repository, editor_id=editor_id)
    await save_button_config(
        repository,
        editor_id=editor_id,
        config=ClientMenuButtonConfig(
            text=config.text,
            style_name=config.style_name,
            icon_custom_emoji_id=config.icon_custom_emoji_id,
            url=normalized_url,
        ),
    )
    await db_session.commit()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await _show_button_detail(
        message,
        state,
        repository=repository,
        editor_id=editor_id,
    )
