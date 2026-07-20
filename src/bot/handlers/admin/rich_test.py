from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import (
    clear_state_preserving_admin_panel,
    remember_admin_aux_message,
    send_admin_panel,
)
from src.bot.keyboards.admin import (
    build_admin_rich_comparison_keyboard,
    build_admin_rich_test_input_keyboard,
    build_admin_rich_test_keyboard,
    build_admin_rich_test_preview_keyboard,
)
from src.bot.states import AdminRichTest
from src.config import Settings
from src.services.rich_messages import (
    get_rich_preview_definition,
    is_rich_messages_test_enabled,
    validate_rich_test_source_message,
)

router = Router(name="admin_rich_test")


def _test_target_ids(settings: Settings) -> list[int]:
    """Return deduplicated admin ids used for rich sandbox broadcasts."""
    return list(dict.fromkeys(settings.admin_tg_ids))


def _render_home_text(settings: Settings) -> str:
    """Render the home text for the admin-only rich sandbox."""
    return texts.ADMIN_RICH_TEST_HOME_TEXT.format(count=len(_test_target_ids(settings)))


def _aux_message_ref(chat_id: int, message_id: int):
    """Build a lightweight message-like object for remembered aux previews."""
    return type(
        "AuxMessageRef",
        (),
        {
            "chat": type("ChatRef", (), {"id": chat_id})(),
            "message_id": message_id,
        },
    )()


async def _show_rich_test_home(
    message: Message,
    state: FSMContext,
    *,
    settings: Settings,
    notice_text: str | None = None,
) -> None:
    """Show the rich sandbox home panel and clear any active state."""
    text = _render_home_text(settings)
    if notice_text:
        text = f"{text}\n\n{notice_text}"
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await state.update_data(admin_as_client=False)
    await send_admin_panel(
        message,
        state,
        text=text,
        reply_markup=build_admin_rich_test_keyboard(),
    )


async def _ensure_rich_test_access(
    *,
    db_session: AsyncSession,
    is_admin: bool,
    callback: CallbackQuery | None = None,
    message: Message | None = None,
) -> bool:
    """Return whether the caller may use the rich sandbox right now."""
    if not is_admin:
        if callback is not None:
            await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return False
    if await is_rich_messages_test_enabled(db_session):
        return True
    if callback is not None:
        await callback.answer(texts.ADMIN_RICH_TEST_DISABLED_TEXT, show_alert=True)
    elif message is not None:
        await message.answer(texts.ADMIN_RICH_TEST_DISABLED_TEXT)
    return False


@router.message(lambda message: message.text == "🧪 Rich тест")
async def open_rich_test(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the admin-only rich sandbox from the reply keyboard."""
    if not await _ensure_rich_test_access(
        db_session=db_session,
        is_admin=is_admin,
        message=message,
    ):
        return
    await _show_rich_test_home(message, state, settings=settings)


@router.callback_query(F.data == "admin_rich_test:home")
async def rich_test_home(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Return to the sandbox home screen."""
    if not await _ensure_rich_test_access(
        db_session=db_session,
        is_admin=is_admin,
        callback=callback,
    ):
        return
    await callback.answer()
    if callback.message is None:
        return
    await _show_rich_test_home(callback.message, state, settings=settings)


@router.callback_query(F.data.startswith("admin_rich_test:preview:"))
@router.callback_query(F.data == "admin_rich_test:price_preview")
async def send_rich_price_preview(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Send one registered standard/rich comparison as auxiliary messages."""
    if not await _ensure_rich_test_access(
        db_session=db_session,
        is_admin=is_admin,
        callback=callback,
    ):
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    preview_key = (
        "price"
        if callback.data == "admin_rich_test:price_preview"
        else callback.data.rsplit(":", 1)[-1]
    )
    definition = get_rich_preview_definition(preview_key)
    if definition is None:
        await callback.answer(texts.ADMIN_RICH_TEST_UNKNOWN_PREVIEW_TEXT, show_alert=True)
        return

    await _show_rich_test_home(
        callback.message,
        state,
        settings=settings,
        notice_text=texts.ADMIN_RICH_TEST_COMPARISON_SENT_TEXT.format(title=definition.title),
    )
    comparison = await definition.builder(db_session, settings)
    standard_keyboard = build_admin_rich_comparison_keyboard(preview_key, rich=False)
    if comparison.standard_media_path is not None:
        standard_preview = await callback.bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=BufferedInputFile(
                comparison.standard_media_path.read_bytes(),
                filename=comparison.standard_media_path.name,
            ),
            caption=comparison.standard_text,
            reply_markup=standard_keyboard,
            parse_mode="HTML",
        )
    else:
        standard_preview = await callback.bot.send_message(
            chat_id=callback.message.chat.id,
            text=comparison.standard_text,
            reply_markup=standard_keyboard,
            parse_mode="HTML",
        )
    await remember_admin_aux_message(state, standard_preview)

    rich_preview = await callback.bot.send_rich_message(
        chat_id=callback.message.chat.id,
        rich_message=comparison.rich_message,
        reply_markup=build_admin_rich_comparison_keyboard(preview_key, rich=True),
    )
    await remember_admin_aux_message(state, rich_preview)


@router.callback_query(F.data == "admin_rich_test:noop")
async def ignore_rich_preview_action(callback: CallbackQuery) -> None:
    """Acknowledge visual-only buttons without entering client flows."""
    await callback.answer(texts.ADMIN_RICH_TEST_PREVIEW_BUTTON_TEXT)


@router.callback_query(F.data == "admin_rich_test:broadcast")
async def prompt_rich_test_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Prompt the admin to send one source message for the test broadcast."""
    if not await _ensure_rich_test_access(
        db_session=db_session,
        is_admin=is_admin,
        callback=callback,
    ):
        return
    await callback.answer()
    if callback.message is None:
        return
    await state.set_state(AdminRichTest.await_broadcast_source)
    await send_admin_panel(
        callback.message,
        state,
        text=texts.ADMIN_RICH_TEST_BROADCAST_PROMPT_TEXT,
        reply_markup=build_admin_rich_test_input_keyboard(),
    )


@router.callback_query(F.data == "admin_rich_test:cancel_input")
async def cancel_rich_test_input(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Cancel waiting for a source message and return to the sandbox home."""
    if not await _ensure_rich_test_access(
        db_session=db_session,
        is_admin=is_admin,
        callback=callback,
    ):
        return
    await callback.answer()
    if callback.message is None:
        return
    await _show_rich_test_home(
        callback.message,
        state,
        settings=settings,
        notice_text=texts.ADMIN_RICH_TEST_BROADCAST_CANCELLED_TEXT,
    )


@router.message(StateFilter(AdminRichTest.await_broadcast_source))
async def capture_rich_test_broadcast_source(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Store and preview one copyable source message for the test broadcast."""
    if not await _ensure_rich_test_access(
        db_session=db_session,
        is_admin=is_admin,
        message=message,
    ):
        return

    error_text = validate_rich_test_source_message(message)
    if error_text is not None:
        await send_admin_panel(
            message,
            state,
            text=f"{texts.ADMIN_RICH_TEST_BROADCAST_PROMPT_TEXT}\n\n{error_text}",
            reply_markup=build_admin_rich_test_input_keyboard(),
        )
        return

    await state.update_data(
        admin_rich_test_source_chat_id=message.chat.id,
        admin_rich_test_source_message_id=message.message_id,
    )
    await state.set_state(AdminRichTest.confirm_broadcast)
    await send_admin_panel(
        message,
        state,
        text=texts.ADMIN_RICH_TEST_PREVIEW_READY_TEXT,
        reply_markup=build_admin_rich_test_input_keyboard(),
    )

    preview = await message.bot.copy_message(
        chat_id=message.chat.id,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
        reply_markup=build_admin_rich_test_preview_keyboard(),
    )
    preview_ref = _aux_message_ref(message.chat.id, int(preview.message_id))
    await remember_admin_aux_message(state, preview_ref)
    await state.update_data(admin_rich_test_preview_message_id=int(preview.message_id))


@router.callback_query(F.data == "admin_rich_test:broadcast_cancel")
async def cancel_rich_test_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Cancel a prepared preview broadcast and return to the sandbox home."""
    if not await _ensure_rich_test_access(
        db_session=db_session,
        is_admin=is_admin,
        callback=callback,
    ):
        return
    await callback.answer()
    if callback.message is None:
        return
    await _show_rich_test_home(
        callback.message,
        state,
        settings=settings,
        notice_text=texts.ADMIN_RICH_TEST_BROADCAST_CANCELLED_TEXT,
    )


@router.callback_query(F.data == "admin_rich_test:broadcast_confirm")
async def confirm_rich_test_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Copy the prepared message only to the configured admin ids."""
    if not await _ensure_rich_test_access(
        db_session=db_session,
        is_admin=is_admin,
        callback=callback,
    ):
        return
    await callback.answer()
    if callback.message is None:
        return

    data = await state.get_data()
    source_chat_id = data.get("admin_rich_test_source_chat_id")
    source_message_id = data.get("admin_rich_test_source_message_id")
    if not source_chat_id or not source_message_id:
        await _show_rich_test_home(
            callback.message,
            state,
            settings=settings,
            notice_text=texts.ADMIN_RICH_TEST_BROADCAST_CANCELLED_TEXT,
        )
        return

    target_ids = _test_target_ids(settings)
    if not target_ids:
        await _show_rich_test_home(
            callback.message,
            state,
            settings=settings,
            notice_text=texts.ADMIN_RICH_TEST_NO_TARGETS_TEXT,
        )
        return

    await send_admin_panel(
        callback.message,
        state,
        text=texts.ADMIN_RICH_TEST_BROADCAST_STARTED_TEXT,
        reply_markup=build_admin_rich_test_keyboard(),
    )

    delivered = 0
    blocked = 0
    failed = 0
    for tg_id in target_ids:
        try:
            await callback.bot.copy_message(
                chat_id=int(tg_id),
                from_chat_id=int(source_chat_id),
                message_id=int(source_message_id),
            )
            delivered += 1
        except TelegramForbiddenError:
            blocked += 1
        except TelegramBadRequest as exc:
            error_text = str(exc).lower()
            if (
                "chat not found" in error_text
                or "bot was blocked" in error_text
                or "user is deactivated" in error_text
            ):
                blocked += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    await _show_rich_test_home(
        callback.message,
        state,
        settings=settings,
        notice_text=texts.ADMIN_RICH_TEST_BROADCAST_REPORT_TEXT.format(
            delivered=delivered,
            blocked=blocked,
            failed=failed,
        ),
    )
