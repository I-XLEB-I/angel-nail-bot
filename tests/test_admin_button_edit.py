from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import button_edit as button_edit_handler
from src.bot.states import AdminButtonEdit
from src.db.base import Base
from src.db.repositories.settings import SettingRepository
from src.services.button_configs import build_angela_chat_url, load_button_config, load_master_contact_url


class FakeState:
    def __init__(self) -> None:
        self.state = None
        self.data: dict[str, object] = {}
        self.cleared = False

    async def set_state(self, state) -> None:
        self.state = state

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def clear(self) -> None:
        self.cleared = True
        self.data.clear()


class FakeMessage:
    def __init__(self, text: str | None = None, *, entities=None) -> None:
        self.text = text
        self.entities = entities
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:
        del kwargs
        self.answers.append(text)


class FakeEntity:
    def __init__(self, *, type: str, custom_emoji_id: str | None = None) -> None:
        self.type = type
        self.custom_emoji_id = custom_emoji_id


class FakeCallback:
    def __init__(self, data: str, *, message: FakeMessage | None = None) -> None:
        self.data = data
        self.message = message or FakeMessage()
        self.answers: list[str | None] = []

    async def answer(self, text: str | None = None, **kwargs) -> None:
        del kwargs
        self.answers.append(text)


@pytest.mark.asyncio
async def test_open_button_editor_shows_categories(monkeypatch) -> None:
    state = FakeState()
    message = FakeMessage()
    captured: dict[str, object] = {}

    async def fake_clear_state(state_obj, *, admin_as_client=None) -> None:
        del admin_as_client
        await state_obj.clear()

    async def fake_show_categories(message_obj, state_obj) -> None:
        captured["message"] = message_obj
        captured["state"] = state_obj

    monkeypatch.setattr(
        button_edit_handler,
        "clear_state_preserving_admin_panel",
        fake_clear_state,
    )
    monkeypatch.setattr(button_edit_handler, "_show_button_categories", fake_show_categories)

    await button_edit_handler.open_button_editor(
        message,
        state,
        db_session=object(),
        is_admin=True,
    )

    assert state.cleared is True
    assert captured["message"] is message
    assert captured["state"] is state


@pytest.mark.asyncio
async def test_open_button_category_routes_to_category_list(monkeypatch) -> None:
    state = FakeState()
    callback = FakeCallback("admin_buttons:category:common")
    captured: dict[str, object] = {}

    async def fake_clear_state(state_obj, *, admin_as_client=None) -> None:
        del admin_as_client
        await state_obj.clear()

    async def fake_show_list(message_obj, state_obj, *, repository, category_key) -> None:
        del repository
        captured["message"] = message_obj
        captured["state"] = state_obj
        captured["category_key"] = category_key

    monkeypatch.setattr(
        button_edit_handler,
        "clear_state_preserving_admin_panel",
        fake_clear_state,
    )
    monkeypatch.setattr(button_edit_handler, "_show_button_list", fake_show_list)

    await button_edit_handler.open_button_category(
        callback,
        state,
        db_session=object(),
        is_admin=True,
    )

    assert captured["message"] is callback.message
    assert captured["state"] is state
    assert captured["category_key"] == "common"


@pytest.mark.asyncio
async def test_prompt_button_text_edit_sets_state() -> None:
    state = FakeState()
    callback = FakeCallback(
        "admin_buttons:text:client_main_menu.portfolio",
        message=FakeMessage(),
    )

    await button_edit_handler.prompt_button_text_edit(
        callback,
        state,
        is_admin=True,
    )

    assert state.state == AdminButtonEdit.input_text
    assert state.data[button_edit_handler.BUTTON_EDITOR_ID_STATE] == "client_main_menu.portfolio"


@pytest.mark.asyncio
async def test_save_button_text_persists_override(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        state = FakeState()
        await state.update_data(
            **{button_edit_handler.BUTTON_EDITOR_ID_STATE: "client_main_menu.portfolio"}
        )
        message = FakeMessage("🌸 Обо мне")
        shown: dict[str, object] = {}

        async def fake_show_detail(message_obj, state_obj, *, repository, editor_id) -> None:
            del message_obj, state_obj, repository
            shown["editor_id"] = editor_id

        monkeypatch.setattr(button_edit_handler, "_show_button_detail", fake_show_detail)

        await button_edit_handler.save_button_text(
            message,
            state,
            db_session=session,
        )

        config = await load_button_config(
            SettingRepository(session),
            editor_id="client_main_menu.portfolio",
        )
        assert config.text == "🌸 Обо мне"
        assert shown["editor_id"] == "client_main_menu.portfolio"

    await engine.dispose()


@pytest.mark.asyncio
async def test_save_button_emoji_persists_override(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        state = FakeState()
        await state.update_data(**{button_edit_handler.BUTTON_EDITOR_ID_STATE: "common.back"})
        message = FakeMessage(
            entities=[FakeEntity(type="custom_emoji", custom_emoji_id="999888")]
        )
        shown: dict[str, object] = {}

        async def fake_show_detail(message_obj, state_obj, *, repository, editor_id) -> None:
            del message_obj, state_obj, repository
            shown["editor_id"] = editor_id

        monkeypatch.setattr(button_edit_handler, "_show_button_detail", fake_show_detail)

        await button_edit_handler.save_button_emoji(
            message,
            state,
            db_session=session,
        )

        config = await load_button_config(
            SettingRepository(session),
            editor_id="common.back",
        )
        assert config.icon_custom_emoji_id == "999888"
        assert shown["editor_id"] == "common.back"

    await engine.dispose()


@pytest.mark.asyncio
async def test_save_button_url_persists_override_for_contact(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        state = FakeState()
        await state.update_data(
            **{button_edit_handler.BUTTON_EDITOR_ID_STATE: "client_main_menu.contact"}
        )
        message = FakeMessage("@angels_custom")
        shown: dict[str, object] = {}

        async def fake_show_detail(message_obj, state_obj, *, repository, editor_id) -> None:
            del message_obj, state_obj, repository
            shown["editor_id"] = editor_id

        monkeypatch.setattr(button_edit_handler, "_show_button_detail", fake_show_detail)

        await button_edit_handler.save_button_url(
            message,
            state,
            db_session=session,
        )

        config = await load_button_config(
            SettingRepository(session),
            editor_id="client_main_menu.contact",
        )
        assert config.url == build_angela_chat_url("angels_custom")
        assert shown["editor_id"] == "client_main_menu.contact"

    await engine.dispose()


@pytest.mark.asyncio
async def test_reset_button_url_clears_custom_override(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        repository = SettingRepository(session)
        await repository.upsert(
            key="button_config.client_main_menu.contact",
            value='{"text":"✉️ Написать Ангеле напрямую","style_name":"default","icon_custom_emoji_id":null,"url":"https://t.me/custom"}',
        )
        await session.commit()

        callback = FakeCallback(
            "admin_buttons:url_reset:client_main_menu.contact",
            message=FakeMessage(),
        )
        shown: dict[str, object] = {}

        async def fake_show_detail(message_obj, state_obj, *, repository, editor_id) -> None:
            del message_obj, state_obj, repository
            shown["editor_id"] = editor_id

        monkeypatch.setattr(button_edit_handler, "_show_button_detail", fake_show_detail)

        await button_edit_handler.reset_button_url(
            callback,
            FakeState(),
            db_session=session,
            is_admin=True,
        )

        config = await load_button_config(repository, editor_id="client_main_menu.contact")
        assert config.url is None
        assert shown["editor_id"] == "client_main_menu.contact"

    await engine.dispose()


@pytest.mark.asyncio
async def test_set_button_style_persists_override(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        callback = FakeCallback(
            "admin_buttons:style:client_my_bookings.repair:success",
            message=FakeMessage(),
        )
        shown: dict[str, object] = {}

        async def fake_show_detail(message_obj, state_obj, *, repository, editor_id) -> None:
            del message_obj, state_obj, repository
            shown["editor_id"] = editor_id

        monkeypatch.setattr(button_edit_handler, "_show_button_detail", fake_show_detail)

        await button_edit_handler.set_button_style(
            callback,
            FakeState(),
            db_session=session,
            is_admin=True,
        )

        config = await load_button_config(
            SettingRepository(session),
            editor_id="client_my_bookings.repair",
        )
        assert config.style_name == "success"
        assert shown["editor_id"] == "client_my_bookings.repair"

    await engine.dispose()


@pytest.mark.asyncio
async def test_reset_button_config_restores_defaults(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        repository = SettingRepository(session)
        await repository.upsert(
            key="button_config.common.done",
            value='{"text":"Сохранить","style_name":"primary","icon_custom_emoji_id":"123"}',
        )
        await session.commit()

        callback = FakeCallback("admin_buttons:reset:common.done", message=FakeMessage())
        shown: dict[str, object] = {}

        async def fake_show_detail(message_obj, state_obj, *, repository, editor_id) -> None:
            del message_obj, state_obj, repository
            shown["editor_id"] = editor_id

        monkeypatch.setattr(button_edit_handler, "_show_button_detail", fake_show_detail)

        await button_edit_handler.reset_button_config(
            callback,
            FakeState(),
            db_session=session,
            is_admin=True,
        )

        config = await load_button_config(repository, editor_id="common.done")
        assert config.text == "✅ Готово"
        assert config.style_name == "success"
        assert config.icon_custom_emoji_id is None
        assert shown["editor_id"] == "common.done"

    await engine.dispose()


@pytest.mark.asyncio
async def test_save_button_text_rejects_too_long_value() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        state = FakeState()
        await state.update_data(
            **{button_edit_handler.BUTTON_EDITOR_ID_STATE: "client_main_menu.portfolio"}
        )
        message = FakeMessage("x" * 41)

        await button_edit_handler.save_button_text(
            message,
            state,
            db_session=session,
        )

        config = await load_button_config(
            SettingRepository(session),
            editor_id="client_main_menu.portfolio",
        )
        assert config.text == "🌸 О Ангеле и работы"
        assert message.answers[-1] == "Кнопка получится слишком длинной. Оставь до 40 символов 🤍"

    await engine.dispose()


@pytest.mark.asyncio
async def test_load_master_contact_url_uses_runtime_setting() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        repository = SettingRepository(session)
        await repository.upsert(key="master_telegram_username", value="@angela_new")
        await session.commit()

        assert await load_master_contact_url(repository) == build_angela_chat_url("angela_new")

    await engine.dispose()
