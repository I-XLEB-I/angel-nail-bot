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
from src.bot.keyboards.admin import (
    build_admin_service_create_confirm_keyboard,
    build_admin_service_detail_keyboard,
    build_admin_service_edit_fields_keyboard,
    build_admin_service_kind_keyboard,
    build_admin_service_prompt_cancel_keyboard,
    build_admin_service_variable_keyboard,
    build_admin_services_list_keyboard,
    render_service_admin_text,
)
from src.bot.states import AdminServiceCreate, AdminServiceEdit
from src.bot.ui_utils import replace_inline_message_text, upsert_inline_panel
from src.db.models import Service, ServiceKind
from src.db.repositories.services import ServiceRepository

router = Router(name="admin_services_crud")


def humanize_bool(value: bool) -> str:
    """Return a human-readable yes/no value."""
    return "да" if value else "нет"


async def render_services_list_text(
    db_session: AsyncSession,
    *,
    notice_text: str | None = None,
) -> str:
    """Render the compact services home text."""
    repository = ServiceRepository(db_session)
    services = await repository.list_all()
    if not services:
        base = texts.ADMIN_SERVICES_EMPTY_TEXT
    else:
        visible_count = sum(1 for service in services if service.is_active)
        hidden_count = len(services) - visible_count
        service_lines = [
            f"• {service.name} — {'показывается' if service.is_active else 'скрыта'}"
            for service in services[:8]
        ]
        more_suffix = f"\n• … и ещё {len(services) - 8}" if len(services) > 8 else ""
        base = (
            "\n".join(
                [
                    texts.ADMIN_SERVICES_HEADER_TEXT,
                    "",
                    f"Всего услуг: {len(services)}",
                    f"Активных: {visible_count}",
                    f"Скрытых: {hidden_count}",
                    "",
                    "Текущий список:",
                    *service_lines,
                ]
            )
            + more_suffix
        )
    if notice_text:
        return f"{notice_text}\n\n{base}"
    return base


async def show_services_list(
    message: Message,
    *,
    db_session: AsyncSession,
    state: FSMContext | None = None,
    edit: bool = False,
    notice_text: str | None = None,
) -> None:
    """Show the admin list of all services in one panel."""
    repository = ServiceRepository(db_session)
    services = await repository.list_all()
    text = await render_services_list_text(db_session, notice_text=notice_text)
    reply_markup = (
        build_admin_services_list_keyboard(services)
        if services
        else build_admin_services_list_keyboard([])
    )
    if edit:
        await replace_inline_message_text(message, text, reply_markup=reply_markup)
        if state is not None:
            await remember_admin_panel(state, message)
        return
    if state is not None:
        await send_admin_panel(message, state, text=text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


async def show_service_detail(
    message: Message,
    *,
    db_session: AsyncSession,
    service_id: int,
    state: FSMContext | None = None,
    edit: bool = False,
    notice_text: str | None = None,
) -> None:
    """Show one service detail card in the shared panel."""
    repository = ServiceRepository(db_session)
    service = await repository.get_by_id(service_id)
    if service is None:
        if edit:
            await show_services_list(
                message,
                db_session=db_session,
                state=state,
                edit=True,
                notice_text="Не нашла эту услугу.",
            )
        else:
            await message.answer("Не нашла эту услугу.")
        return

    text = render_service_admin_text(service)
    if notice_text:
        text = f"{notice_text}\n\n{text}"
    markup = build_admin_service_detail_keyboard(service)
    if edit:
        await replace_inline_message_text(message, text, reply_markup=markup)
        if state is not None:
            await remember_admin_panel(state, message)
        return
    await message.answer(text, reply_markup=markup)


async def update_service_panel(
    state: FSMContext,
    *,
    bot,
    text: str,
    reply_markup,
) -> None:
    """Update the remembered services panel by ids."""
    data = await state.get_data()
    await upsert_inline_panel(
        bot,
        chat_id=int(data[ADMIN_PANEL_CHAT_ID_KEY]),
        message_id=int(data[ADMIN_PANEL_MESSAGE_ID_KEY]),
        text=text,
        reply_markup=reply_markup,
    )


async def refresh_service_detail_panel(
    state: FSMContext,
    *,
    bot,
    service: Service,
    notice_text: str | None = None,
) -> None:
    """Render one service detail directly by stored panel ids."""
    text = render_service_admin_text(service)
    if notice_text:
        text = f"{notice_text}\n\n{text}"
    await update_service_panel(
        state,
        bot=bot,
        text=text,
        reply_markup=build_admin_service_detail_keyboard(service),
    )


@router.message(lambda message: message.text == "💼 Услуги")
async def services_menu(
    message: Message,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
) -> None:
    """Open the services admin section."""
    if not is_admin:
        return
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await show_services_list(message, db_session=db_session, state=state)


@router.callback_query(F.data == "admin_service:home")
async def open_services_home(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
) -> None:
    """Return to the services list panel."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    if callback.message is not None:
        await show_services_list(callback.message, db_session=db_session, state=state, edit=True)


@router.callback_query(F.data == "admin_service:add")
async def start_service_create(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Start the new-service flow."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return

    await callback.answer()
    await state.set_state(AdminServiceCreate.input_name)
    await state.update_data(admin_service_new={})
    if callback.message is not None:
        await remember_admin_panel(state, callback.message)
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_SERVICE_ADD_NAME_TEXT,
            reply_markup=build_admin_service_prompt_cancel_keyboard(),
        )


@router.message(StateFilter(AdminServiceCreate.input_name))
async def service_create_name(message: Message, state: FSMContext) -> None:
    """Capture the new service name."""
    name = (message.text or "").strip()
    if not name:
        await update_service_panel(
            state,
            bot=message.bot,
            text=texts.ADMIN_SERVICE_EDIT_INVALID_TEXT,
            reply_markup=build_admin_service_prompt_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    draft = dict(data.get("admin_service_new", {}))
    draft["name"] = name
    await state.update_data(admin_service_new=draft)
    await state.set_state(AdminServiceCreate.input_price)
    await update_service_panel(
        state,
        bot=message.bot,
        text=texts.ADMIN_SERVICE_ADD_PRICE_TEXT,
        reply_markup=build_admin_service_prompt_cancel_keyboard(),
    )


@router.message(StateFilter(AdminServiceCreate.input_price))
async def service_create_price(message: Message, state: FSMContext) -> None:
    """Capture the new service price."""
    try:
        price = int((message.text or "").strip())
        if price < 0:
            raise ValueError
    except ValueError:
        await update_service_panel(
            state,
            bot=message.bot,
            text=texts.ADMIN_SERVICE_EDIT_INVALID_TEXT,
            reply_markup=build_admin_service_prompt_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    draft = dict(data.get("admin_service_new", {}))
    draft["price"] = price
    await state.update_data(admin_service_new=draft)
    await state.set_state(AdminServiceCreate.input_duration)
    await update_service_panel(
        state,
        bot=message.bot,
        text=texts.ADMIN_SERVICE_ADD_DURATION_TEXT,
        reply_markup=build_admin_service_prompt_cancel_keyboard(),
    )


@router.message(StateFilter(AdminServiceCreate.input_duration))
async def service_create_duration(message: Message, state: FSMContext) -> None:
    """Capture the new service duration."""
    try:
        duration_min = int((message.text or "").strip())
        if duration_min < 0:
            raise ValueError
    except ValueError:
        await update_service_panel(
            state,
            bot=message.bot,
            text=texts.ADMIN_SERVICE_EDIT_INVALID_TEXT,
            reply_markup=build_admin_service_prompt_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    draft = dict(data.get("admin_service_new", {}))
    draft["duration_min"] = duration_min
    await state.update_data(admin_service_new=draft)
    await state.set_state(AdminServiceCreate.choose_kind)
    await update_service_panel(
        state,
        bot=message.bot,
        text=texts.ADMIN_SERVICE_ADD_KIND_TEXT,
        reply_markup=build_admin_service_kind_keyboard(
            "admin_service:create_kind",
            cancel_callback="admin_service:home",
        ),
    )


@router.callback_query(
    StateFilter(AdminServiceCreate.choose_kind),
    F.data.startswith("admin_service:create_kind:"),
)
async def service_create_kind(callback: CallbackQuery, state: FSMContext) -> None:
    """Capture the new service kind."""
    await callback.answer()
    kind_value = callback.data.rsplit(":", 1)[-1]
    kind = ServiceKind.BASE if kind_value == "base" else ServiceKind.ADDON

    data = await state.get_data()
    draft = dict(data.get("admin_service_new", {}))
    draft["kind"] = kind.value
    await state.update_data(admin_service_new=draft)
    await state.set_state(AdminServiceCreate.choose_price_variable)

    if callback.message is not None:
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_SERVICE_ADD_VARIABLE_TEXT,
            reply_markup=build_admin_service_variable_keyboard(
                "admin_service:create_variable",
                cancel_callback="admin_service:home",
            ),
        )


@router.callback_query(
    StateFilter(AdminServiceCreate.choose_price_variable),
    F.data.startswith("admin_service:create_variable:"),
)
async def service_create_price_variable(callback: CallbackQuery, state: FSMContext) -> None:
    """Capture whether the service has a variable price."""
    await callback.answer()
    value = callback.data.rsplit(":", 1)[-1] == "true"

    data = await state.get_data()
    draft = dict(data.get("admin_service_new", {}))
    draft["price_variable"] = value
    await state.update_data(admin_service_new=draft)
    await state.set_state(AdminServiceCreate.confirm)

    if callback.message is not None:
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_SERVICE_ADD_CONFIRM_TEXT.format(
                name=draft["name"],
                price=draft["price"],
                duration_min=draft["duration_min"],
                kind=draft["kind"],
                price_variable=humanize_bool(value),
            ),
            reply_markup=build_admin_service_create_confirm_keyboard(),
        )


@router.callback_query(
    StateFilter(AdminServiceCreate.confirm),
    F.data == "admin_service:create_confirm",
)
async def service_create_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Persist the new service."""
    await callback.answer()
    data = await state.get_data()
    draft = dict(data.get("admin_service_new", {}))

    repository = ServiceRepository(db_session)
    service = await repository.create(
        name=draft["name"],
        price=int(draft["price"]),
        price_variable=bool(draft["price_variable"]),
        duration_min=int(draft["duration_min"]),
        kind=ServiceKind(draft["kind"]),
    )
    await db_session.commit()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)

    if callback.message is not None:
        await show_service_detail(
            callback.message,
            db_session=db_session,
            service_id=service.id,
            state=state,
            edit=True,
            notice_text=texts.ADMIN_SERVICE_CREATED_TEXT,
        )


@router.callback_query(
    StateFilter(AdminServiceCreate.confirm),
    F.data == "admin_service:create_cancel",
)
async def service_create_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Cancel the create-service flow."""
    await callback.answer()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    if callback.message is not None:
        await show_services_list(callback.message, db_session=db_session, state=state, edit=True)


@router.callback_query(F.data.startswith("admin_service:open:"))
async def service_open_detail(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Open one service card inside the shared admin panel."""
    await callback.answer()
    if callback.message is None:
        return
    service_id = int(callback.data.rsplit(":", 1)[-1])
    await show_service_detail(
        callback.message,
        db_session=db_session,
        service_id=service_id,
        state=state,
        edit=True,
    )


@router.callback_query(F.data.startswith("admin_service:edit:"))
async def service_edit_menu(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
) -> None:
    """Show the field picker for a service."""
    await callback.answer()
    if callback.message is None:
        return

    service_id = int(callback.data.rsplit(":", 1)[-1])
    repository = ServiceRepository(db_session)
    service = await repository.get_by_id(service_id)
    if service is None:
        await replace_inline_message_text(callback.message, "Не нашла эту услугу.")
        return

    await replace_inline_message_text(
        callback.message,
        f"{service.name}\n\n{texts.ADMIN_SERVICE_EDIT_FIELD_TEXT}",
        reply_markup=build_admin_service_edit_fields_keyboard(service.id),
    )


@router.callback_query(F.data.startswith("admin_service:field:"))
async def service_edit_field_pick(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Pick a service field to edit."""
    await callback.answer()
    if callback.message is None:
        return

    _, _, service_id_raw, field_name = callback.data.split(":")
    service_id = int(service_id_raw)
    repository = ServiceRepository(db_session)
    service = await repository.get_by_id(service_id)
    if service is None:
        await replace_inline_message_text(callback.message, "Не нашла эту услугу.")
        return

    if field_name == "kind":
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_SERVICE_ADD_KIND_TEXT,
            reply_markup=build_admin_service_kind_keyboard(
                f"admin_service:set_kind:{service.id}",
                cancel_callback=f"admin_service:open:{service.id}",
            ),
        )
        return

    if field_name == "price_variable":
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_SERVICE_ADD_VARIABLE_TEXT,
            reply_markup=build_admin_service_variable_keyboard(
                f"admin_service:set_variable:{service.id}",
                cancel_callback=f"admin_service:open:{service.id}",
            ),
        )
        return

    prompt = {
        "name": texts.ADMIN_SERVICE_EDIT_NAME_TEXT,
        "price": texts.ADMIN_SERVICE_EDIT_PRICE_TEXT,
        "duration_min": texts.ADMIN_SERVICE_EDIT_DURATION_TEXT,
    }[field_name]
    await state.set_state(AdminServiceEdit.input_value)
    await state.update_data(admin_service_edit={"service_id": service.id, "field": field_name})
    await remember_admin_panel(state, callback.message)
    await replace_inline_message_text(
        callback.message,
        prompt,
        reply_markup=build_admin_service_prompt_cancel_keyboard(f"admin_service:open:{service.id}"),
    )


@router.callback_query(F.data.startswith("admin_service:set_kind:"))
async def service_set_kind(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Persist an updated service kind."""
    await callback.answer()
    if callback.message is None:
        return

    _, _, service_id_raw, kind_value = callback.data.split(":")
    repository = ServiceRepository(db_session)
    service = await repository.get_by_id(int(service_id_raw))
    if service is None:
        await replace_inline_message_text(callback.message, "Не нашла эту услугу.")
        return

    await repository.update(
        service,
        kind=ServiceKind.BASE if kind_value == "base" else ServiceKind.ADDON,
    )
    await db_session.commit()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await show_service_detail(
        callback.message,
        db_session=db_session,
        service_id=service.id,
        state=state,
        edit=True,
        notice_text=texts.ADMIN_SERVICE_UPDATED_TEXT,
    )


@router.callback_query(F.data.startswith("admin_service:set_variable:"))
async def service_set_price_variable(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Persist an updated price-variable flag."""
    await callback.answer()
    if callback.message is None:
        return

    _, _, service_id_raw, value_raw = callback.data.split(":")
    repository = ServiceRepository(db_session)
    service = await repository.get_by_id(int(service_id_raw))
    if service is None:
        await replace_inline_message_text(callback.message, "Не нашла эту услугу.")
        return

    await repository.update(service, price_variable=value_raw == "true")
    await db_session.commit()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await show_service_detail(
        callback.message,
        db_session=db_session,
        service_id=service.id,
        state=state,
        edit=True,
        notice_text=texts.ADMIN_SERVICE_UPDATED_TEXT,
    )


@router.message(StateFilter(AdminServiceEdit.input_value))
async def service_edit_input(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Persist a text/integer service edit."""
    data = await state.get_data()
    edit_data = dict(data.get("admin_service_edit", {}))
    service_id = int(edit_data["service_id"])
    field_name = edit_data["field"]

    repository = ServiceRepository(db_session)
    service = await repository.get_by_id(service_id)
    if service is None:
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await update_service_panel(
            state,
            bot=message.bot,
            text="Не нашла эту услугу.",
            reply_markup=build_admin_service_prompt_cancel_keyboard(),
        )
        return

    raw_value = (message.text or "").strip()
    try:
        if field_name == "name":
            if not raw_value:
                raise ValueError
            parsed_value = raw_value
        else:
            parsed_value = int(raw_value)
            if parsed_value < 0:
                raise ValueError
    except ValueError:
        await update_service_panel(
            state,
            bot=message.bot,
            text=texts.ADMIN_SERVICE_EDIT_INVALID_TEXT,
            reply_markup=build_admin_service_prompt_cancel_keyboard(
                f"admin_service:open:{service_id}"
            ),
        )
        return

    await repository.update(service, **{field_name: parsed_value})
    await db_session.commit()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await refresh_service_detail_panel(
        state,
        bot=message.bot,
        service=service,
        notice_text=texts.ADMIN_SERVICE_UPDATED_TEXT,
    )


@router.callback_query(F.data.startswith("admin_service:toggle:"))
async def service_toggle_visibility(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Toggle service visibility."""
    await callback.answer()
    if callback.message is None:
        return

    service_id = int(callback.data.rsplit(":", 1)[-1])
    repository = ServiceRepository(db_session)
    service = await repository.get_by_id(service_id)
    if service is None:
        await replace_inline_message_text(callback.message, "Не нашла эту услугу.")
        return

    await repository.update(service, is_active=not service.is_active)
    await db_session.commit()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await show_service_detail(
        callback.message,
        db_session=db_session,
        service_id=service.id,
        state=state,
        edit=True,
        notice_text=texts.ADMIN_SERVICE_VISIBILITY_TEXT,
    )


@router.callback_query(F.data.startswith("admin_service:delete:"))
async def service_delete(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Delete a service if it is not referenced elsewhere."""
    await callback.answer()
    if callback.message is None:
        return

    service_id = int(callback.data.rsplit(":", 1)[-1])
    repository = ServiceRepository(db_session)
    service = await repository.get_by_id(service_id)
    if service is None:
        await replace_inline_message_text(callback.message, "Не нашла эту услугу.")
        return

    deleted = await repository.delete_if_unused(service)
    if not deleted:
        await db_session.rollback()
        await show_service_detail(
            callback.message,
            db_session=db_session,
            service_id=service.id,
            state=state,
            edit=True,
            notice_text=texts.ADMIN_SERVICE_DELETE_FORBIDDEN_TEXT,
        )
        return

    await db_session.commit()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await show_services_list(
        callback.message,
        db_session=db_session,
        state=state,
        edit=True,
        notice_text=texts.ADMIN_SERVICE_DELETED_TEXT,
    )
