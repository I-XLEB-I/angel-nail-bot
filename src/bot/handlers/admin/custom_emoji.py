from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot import texts
from src.bot.admin_panel import clear_state_preserving_admin_panel, send_admin_panel
from src.bot.handlers.admin.menu import show_admin_menu
from src.bot.keyboards.admin import build_admin_emoji_id_keyboard
from src.bot.states import AdminCustomEmoji
from src.config import Settings

router = Router(name="admin_custom_emoji")


async def show_custom_emoji_prompt(message: Message, state: FSMContext) -> None:
    """Show the admin helper that extracts premium/custom emoji ids."""
    await send_admin_panel(
        message,
        state,
        text=texts.ADMIN_EMOJI_ID_PROMPT_TEXT,
        reply_markup=build_admin_emoji_id_keyboard(),
    )


@router.message(lambda message: message.text == "✨ Emoji ID")
async def open_custom_emoji_tool(
    message: Message,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Open the premium/custom emoji id helper for admins."""
    if not is_admin:
        return
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await state.set_state(AdminCustomEmoji.await_emoji)
    await show_custom_emoji_prompt(message, state)


@router.callback_query(F.data == "admin_emoji_id:back")
async def close_custom_emoji_tool(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Return from the emoji-id helper back to the admin menu."""
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


@router.message(StateFilter(AdminCustomEmoji.await_emoji))
async def extract_custom_emoji_id(message: Message) -> None:
    """Read one or more custom emoji ids from the admin's message."""
    entities = list(message.entities or [])
    ids = [
        entity.custom_emoji_id
        for entity in entities
        if str(entity.type) == "custom_emoji" and entity.custom_emoji_id
    ]
    if not ids:
        await message.answer(texts.ADMIN_EMOJI_ID_EMPTY_TEXT)
        return

    lines = ["✨ Нашла custom emoji id:", ""]
    for index, emoji_id in enumerate(dict.fromkeys(ids), start=1):
        lines.append(f"{index}. `{emoji_id}`")
    lines.extend(["", "Можно прислать ещё один premium emoji этим же сообщением ниже."])
    await message.answer("\n".join(lines), parse_mode="Markdown")
