from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import templates_edit as templates_handler
from src.config import Settings
from src.db.base import Base


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.state = None
        self.cleared = False

    async def set_state(self, state) -> None:
        self.state = state

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def clear(self) -> None:
        self.cleared = True
        self.data.clear()


class FakeMessage:
    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.answers: list[tuple[str, object | None]] = []
        self.edits: list[tuple[str, object | None]] = []
        self.photos: list[tuple[object, str | None, object | None]] = []

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))

    async def answer_photo(self, photo, caption: str | None = None, reply_markup=None) -> None:
        self.photos.append((photo, caption, reply_markup))


def first_rendered_text(message: FakeMessage) -> str | None:
    if message.edits:
        return message.edits[0][0]
    if message.answers:
        return message.answers[0][0]
    return None


def first_rendered_markup(message: FakeMessage):
    if message.edits:
        return message.edits[0][1]
    if message.answers:
        return message.answers[0][1]
    return None


def test_template_image_block_distinguishes_bundled_and_uploaded(monkeypatch) -> None:
    monkeypatch.setattr(
        templates_handler,
        "template_media_source",
        lambda key: "bundled" if key == "navigation_public" else "uploaded",
    )
    monkeypatch.setattr(templates_handler, "has_bundled_template_media", lambda key: True)

    assert "стандартная" in templates_handler.build_template_image_block(
        "navigation_public"
    )
    assert "загружена через админку" in templates_handler.build_template_image_block(
        "price"
    )


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage | None = None) -> None:
        self.data = data
        self.message = message or FakeMessage()
        self.answered = False
        self.answer_args: tuple[object, ...] = ()
        self.answer_kwargs: dict[str, object] = {}

    async def answer(self, *args, **kwargs) -> None:
        self.answer_args = args
        self.answer_kwargs = dict(kwargs)
        self.answered = True


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_open_templates_shows_category_picker() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        message = FakeMessage()
        state = FakeState()

        await templates_handler.open_templates(
            message,
            state,
            is_admin=True,
            db_session=session,
        )

        assert message.answers
        assert "📝 ШАБЛОНЫ" in message.answers[0][0]
        assert "💌 Клиентам" in message.answers[0][0]
        assert message.answers[0][1] is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_template_category_edits_current_message() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        callback = FakeCallback("admin_templates:category:clients")
        state = FakeState()

        await templates_handler.open_template_category_callback(
            callback,
            state,
            is_admin=True,
            db_session=session,
        )

        assert callback.answered is True
        assert first_rendered_text(callback.message) is not None
        assert "💌 Клиентам" in (first_rendered_text(callback.message) or "")
        markup = first_rendered_markup(callback.message)
        assert markup is not None
        labels = [button.text for row in markup.inline_keyboard for button in row]
        assert "💰 Прайс" in labels
        assert "🛠 Ремонт и гарантия" in labels
        assert "🛠 Ремонт / гарантия — интро" not in labels

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_template_group_shows_only_group_templates() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        callback = FakeCallback("admin_templates:group:clients:repair")
        state = FakeState()

        await templates_handler.open_template_group_callback(
            callback,
            state,
            is_admin=True,
            db_session=session,
        )

        assert callback.answered is True
        assert "🛠 Ремонт и гарантия" in (first_rendered_text(callback.message) or "")
        markup = first_rendered_markup(callback.message)
        assert markup is not None
        labels = [button.text for row in markup.inline_keyboard for button in row]
        assert "🛠 Ремонт / гарантия — интро" in labels
        assert "🔔 Напоминание за сутки" not in labels

    await engine.dispose()


@pytest.mark.asyncio
async def test_price_group_opens_editable_text_and_image_card() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        callback = FakeCallback("admin_templates:group:clients:price")
        state = FakeState()

        await templates_handler.open_template_group_callback(
            callback,
            state,
            is_admin=True,
            db_session=session,
        )

        assert callback.answered is True
        rendered_text = first_rendered_text(callback.message)
        if rendered_text is None and callback.message.photos:
            rendered_text = callback.message.photos[0][1]
        assert "💰 Прайс" in (rendered_text or "")
        markup = first_rendered_markup(callback.message)
        if markup is None and callback.message.photos:
            markup = callback.message.photos[0][2]
        labels = [button.text for row in markup.inline_keyboard for button in row]
        assert "✏️ Изменить текст" in labels
        assert "🖼 Заменить картинку" in labels

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_single_group_category_skips_transition_screen() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        callback = FakeCallback("admin_templates:category:address")
        state = FakeState()

        await templates_handler.open_template_category_callback(
            callback,
            state,
            is_admin=True,
            db_session=session,
        )

        assert callback.answered is True
        assert "📍 Адрес и навигация" in (first_rendered_text(callback.message) or "")
        markup = first_rendered_markup(callback.message)
        assert markup is not None
        labels = [button.text for row in markup.inline_keyboard for button in row]
        assert "📍 Адрес (публичный)" in labels
        assert "🔐 Полный адрес после записи" in labels
        assert markup.inline_keyboard[-2][0].callback_data == "admin_templates:home"

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_single_template_category_skips_to_detail() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        callback = FakeCallback("admin_templates:category:schedule")
        state = FakeState()

        await templates_handler.open_template_category_callback(
            callback,
            state,
            is_admin=True,
            db_session=session,
        )

        assert callback.answered is True
        assert "Подпись картинки расписания" in (first_rendered_text(callback.message) or "")
        markup = first_rendered_markup(callback.message)
        assert markup is not None
        assert markup.inline_keyboard[-2][0].callback_data == "admin_templates:home"
        labels = [button.text for row in markup.inline_keyboard for button in row]
        assert "🗓 Витрина расписания" not in labels

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_single_template_group_skips_to_detail() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        callback = FakeCallback("admin_templates:group:other:service")
        state = FakeState()

        await templates_handler.open_template_group_callback(
            callback,
            state,
            is_admin=True,
            db_session=session,
        )

        assert callback.answered is True
        assert "Текст админ-меню" in (first_rendered_text(callback.message) or "")
        markup = first_rendered_markup(callback.message)
        assert markup is not None
        assert markup.inline_keyboard[-2][0].callback_data == "admin_templates:category:other"

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_template_category_from_photo_panel_uses_admin_panel_helper(
    monkeypatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        captured: dict[str, object] = {}

        async def fake_send_admin_panel(message, state, *, text, reply_markup=None):
            captured["message"] = message
            captured["state"] = state
            captured["text"] = text
            captured["reply_markup"] = reply_markup
            return message

        monkeypatch.setattr(templates_handler, "send_admin_panel", fake_send_admin_panel)

        callback = FakeCallback("admin_templates:category:clients")
        state = FakeState()

        await templates_handler.open_template_category_callback(
            callback,
            state,
            is_admin=True,
            db_session=session,
        )

        assert callback.answered is True
        assert "💌 Клиентам" in str(captured.get("text", ""))
        assert captured.get("reply_markup") is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_prompt_template_edit_shows_cancel_button() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        callback = FakeCallback("admin_templates:edit:booking_confirm")
        state = FakeState()

        await templates_handler.prompt_template_edit(
            callback,
            state,
            is_admin=True,
            db_session=session,
        )

        assert callback.answered is True
        assert state.data["admin_template_key"] == "booking_confirm"
        assert "✏️" in (first_rendered_text(callback.message) or "")
        assert "Подтверждение записи" in (first_rendered_text(callback.message) or "")
        assert "Текущий текст" in (first_rendered_text(callback.message) or "")
        assert first_rendered_markup(callback.message) is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_prompt_template_image_upload_sets_wait_state() -> None:
    callback = FakeCallback("admin_templates:upload_image:booking_confirm")
    state = FakeState()

    await templates_handler.prompt_template_image_upload(
        callback,
        state,
        is_admin=True,
    )

    assert callback.answered is True
    assert state.data["admin_template_key"] == "booking_confirm"
    assert state.state == templates_handler.AdminTemplateEdit.await_image
    assert "🖼" in (first_rendered_text(callback.message) or "")
    assert "Подтверждение записи" in (first_rendered_text(callback.message) or "")


@pytest.mark.asyncio
async def test_preview_template_image_callback_only_acknowledges_existing_preview(
    monkeypatch,
) -> None:
    callback = FakeCallback("admin_templates:preview_image:booking_confirm")

    monkeypatch.setattr(
        templates_handler,
        "has_template_media",
        lambda key: key == "booking_confirm",
    )

    await templates_handler.preview_template_image(
        callback,
        is_admin=True,
    )

    assert callback.answered is True
    assert callback.answer_args == (templates_handler.texts.ADMIN_TEMPLATE_IMAGE_ALREADY_VISIBLE_TEXT,)
    assert callback.message.photos == []


@pytest.mark.asyncio
async def test_show_template_detail_with_media_sends_photo_panel(tmp_path, monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        media_path = tmp_path / "booking_confirm.jpg"
        media_path.write_bytes(b"fake-image")

        monkeypatch.setattr(
            templates_handler,
            "has_template_media",
            lambda key: key == "booking_confirm",
        )
        monkeypatch.setattr(
            templates_handler,
            "template_media_path",
            lambda key: media_path,
        )

        message = FakeMessage()

        await templates_handler.show_template_detail(
            message,
            db_session=session,
            template_key="booking_confirm",
            edit=False,
            state=None,
        )

        assert message.photos
        assert "Подтверждение записи" in (message.photos[0][1] or "")
        assert message.answers == []

    await engine.dispose()


class _FakeBuffer:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._position = 0

    def seek(self, position: int) -> None:
        self._position = position

    def read(self) -> bytes:
        return self._payload


class _FakeBot:
    def __init__(self, payload: bytes = b"fake-bytes") -> None:
        self._payload = payload
        self.downloads: list[object] = []

    async def download(self, file_ref):
        self.downloads.append(file_ref)
        return _FakeBuffer(self._payload)


class _FakePhotoSize:
    def __init__(self, file_id: str = "largest") -> None:
        self.file_id = file_id


class _FakeDocument:
    def __init__(
        self,
        mime_type: str | None,
        file_id: str = "doc-1",
        file_name: str | None = None,
    ) -> None:
        self.mime_type = mime_type
        self.file_id = file_id
        self.file_name = file_name


class FakeUploadMessage(FakeMessage):
    def __init__(
        self,
        *,
        photo: list[_FakePhotoSize] | None = None,
        document: _FakeDocument | None = None,
        bot: _FakeBot | None = None,
    ) -> None:
        super().__init__()
        self.photo = photo or []
        self.document = document
        self.content_type = "photo" if photo else ("document" if document else "text")
        self.bot = bot or _FakeBot()


@pytest.mark.asyncio
async def test_save_template_image_content_accepts_photo(monkeypatch) -> None:
    saved: list[tuple[str, bytes]] = []
    upsert_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        templates_handler,
        "save_template_media",
        lambda key, content: saved.append((key, content)) or None,
    )

    async def fake_build_template_detail_text(db_session, *, template_key):
        del db_session, template_key
        return ("detail-text", object())

    async def fake_upsert_inline_panel(bot, **kwargs):
        del bot
        upsert_calls.append(kwargs)
        return FakeMessage()

    async def fake_remember(state, panel) -> None:
        del state, panel

    monkeypatch.setattr(
        templates_handler,
        "build_template_detail_text",
        fake_build_template_detail_text,
    )
    monkeypatch.setattr(
        templates_handler,
        "build_template_detail_media",
        lambda key: (b"panel-image", f"{key}.jpg"),
    )
    monkeypatch.setattr(templates_handler, "upsert_inline_panel", fake_upsert_inline_panel)
    monkeypatch.setattr(templates_handler, "remember_admin_panel", fake_remember)

    message = FakeUploadMessage(photo=[_FakePhotoSize("smallest"), _FakePhotoSize("largest")])
    state = FakeState()
    await state.update_data(
        admin_template_key="booking_confirm",
        admin_template_category="clients",
        admin_panel_chat_id=111,
        admin_panel_message_id=222,
    )

    await templates_handler.save_template_image_content(
        message,
        state,
        db_session=None,
    )

    assert saved == [("booking_confirm", b"fake-bytes")]
    assert state.cleared is True
    assert upsert_calls
    assert upsert_calls[0]["photo_bytes"] == b"panel-image"
    assert upsert_calls[0]["caption"].startswith(
        templates_handler.texts.ADMIN_TEMPLATE_IMAGE_SAVED_TEXT
    )


@pytest.mark.asyncio
async def test_save_template_image_content_accepts_image_document(monkeypatch) -> None:
    saved: list[tuple[str, bytes]] = []

    monkeypatch.setattr(
        templates_handler,
        "save_template_media",
        lambda key, content: saved.append((key, content)) or None,
    )

    async def fake_build_template_detail_text(db_session, *, template_key):
        del db_session, template_key
        return None

    calls: list[str] = []

    async def fake_show_template_group(
        message,
        *,
        db_session,
        category_key,
        group_key,
        edit,
        state=None,
    ) -> None:
        del message, db_session, edit, state
        calls.append(f"{category_key}:{group_key}")

    async def fake_show_template_category(
        message,
        *,
        db_session,
        category_key,
        edit,
        state=None,
    ) -> None:
        del message, db_session, edit, state
        calls.append(category_key)

    monkeypatch.setattr(
        templates_handler,
        "build_template_detail_text",
        fake_build_template_detail_text,
    )
    monkeypatch.setattr(
        templates_handler,
        "show_template_category",
        fake_show_template_category,
    )
    monkeypatch.setattr(
        templates_handler,
        "show_template_group",
        fake_show_template_group,
    )

    message = FakeUploadMessage(document=_FakeDocument("image/png"))
    state = FakeState()
    await state.update_data(
        admin_template_key="greeting_header",
        admin_template_category="other",
        admin_template_group="showcase",
    )

    await templates_handler.save_template_image_content(
        message,
        state,
        db_session=None,
    )

    assert saved == [("greeting_header", b"fake-bytes")]
    assert calls == ["other:showcase"]
    assert state.cleared is True


@pytest.mark.asyncio
async def test_save_template_image_content_accepts_image_document_by_extension(
    monkeypatch,
) -> None:
    saved: list[tuple[str, bytes]] = []

    monkeypatch.setattr(
        templates_handler,
        "save_template_media",
        lambda key, content: saved.append((key, content)) or None,
    )

    async def fake_build_template_detail_text(db_session, *, template_key):
        del db_session, template_key
        return None

    calls: list[str] = []

    async def fake_show_template_group(
        message,
        *,
        db_session,
        category_key,
        group_key,
        edit,
        state=None,
    ) -> None:
        del message, db_session, edit, state
        calls.append(f"{category_key}:{group_key}")

    async def fake_show_template_category(
        message,
        *,
        db_session,
        category_key,
        edit,
        state=None,
    ) -> None:
        del message, db_session, category_key, edit, state

    monkeypatch.setattr(
        templates_handler,
        "build_template_detail_text",
        fake_build_template_detail_text,
    )
    monkeypatch.setattr(
        templates_handler,
        "show_template_category",
        fake_show_template_category,
    )
    monkeypatch.setattr(
        templates_handler,
        "show_template_group",
        fake_show_template_group,
    )

    message = FakeUploadMessage(document=_FakeDocument(None, file_name="price.JPG"))
    state = FakeState()
    await state.update_data(
        admin_template_key="price",
        admin_template_category="clients",
        admin_template_group="price",
    )

    await templates_handler.save_template_image_content(
        message,
        state,
        db_session=None,
    )

    assert saved == [("price", b"fake-bytes")]
    assert calls == ["clients:price"]
    assert state.cleared is True


@pytest.mark.asyncio
async def test_save_template_image_content_rejects_text_and_keeps_state() -> None:
    message = FakeUploadMessage()
    state = FakeState()
    await state.set_state(templates_handler.AdminTemplateEdit.await_image)
    await state.update_data(
        admin_template_key="greeting_header",
        admin_template_category="other",
    )

    await templates_handler.save_template_image_content(
        message,
        state,
        db_session=None,
    )

    assert message.answers
    assert message.answers[0][0] == (
        templates_handler.texts.ADMIN_TEMPLATE_IMAGE_NOT_PHOTO_TEXT
    )
    assert state.cleared is False
    assert state.state == templates_handler.AdminTemplateEdit.await_image


@pytest.mark.asyncio
async def test_save_template_image_content_rejects_non_image_document() -> None:
    message = FakeUploadMessage(document=_FakeDocument("application/pdf"))
    state = FakeState()
    await state.set_state(templates_handler.AdminTemplateEdit.await_image)

    await templates_handler.save_template_image_content(
        message,
        state,
        db_session=None,
    )

    assert message.answers
    assert state.cleared is False


@pytest.mark.asyncio
async def test_show_template_detail_with_long_media_text_splits_into_panel_and_aux_photo(
    monkeypatch,
) -> None:
    sent_panel: dict[str, object] = {}
    sent_aux: dict[str, object] = {}

    async def fake_send_admin_panel(message, state, *, text, reply_markup=None):
        del message, state
        sent_panel["text"] = text
        sent_panel["reply_markup"] = reply_markup

    async def fake_send_admin_aux_photo(
        message,
        state,
        *,
        photo_bytes,
        filename,
        caption=None,
        parse_mode=None,
    ):
        del message, state, parse_mode
        sent_aux["photo_bytes"] = photo_bytes
        sent_aux["filename"] = filename
        sent_aux["caption"] = caption

    monkeypatch.setattr(templates_handler, "send_admin_panel", fake_send_admin_panel)
    monkeypatch.setattr(templates_handler, "send_admin_aux_photo", fake_send_admin_aux_photo)
    async def fake_ensure_required_templates(_db_session) -> None:
        return None

    monkeypatch.setattr(
        templates_handler,
        "ensure_required_templates",
        fake_ensure_required_templates,
    )
    monkeypatch.setattr(
        templates_handler,
        "build_template_detail_text",
        lambda *args, **kwargs: None,
    )

    async def fake_build_template_detail_text(db_session, *, template_key):
        del db_session, template_key
        return ("X" * (templates_handler.DETAIL_CAPTION_SAFE_LIMIT + 20), object())

    monkeypatch.setattr(
        templates_handler,
        "build_template_detail_text",
        fake_build_template_detail_text,
    )
    monkeypatch.setattr(
        templates_handler,
        "build_template_detail_media",
        lambda key: (b"preview", f"{key}.jpg"),
    )

    await templates_handler.show_template_detail(
        FakeMessage(),
        db_session=None,
        template_key="booking_confirm",
        edit=False,
        state=FakeState(),
    )

    assert sent_panel["text"]
    assert sent_aux["photo_bytes"] == b"preview"
    assert sent_aux["caption"] == "🖼 Превью картинки шаблона"


@pytest.mark.asyncio
async def test_save_template_content_rejects_short_text() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        message = FakeMessage("коротко")
        state = FakeState()
        await state.update_data(
            admin_template_key="greeting_header",
            admin_template_category="other",
        )
        user = type("UserStub", (), {"id": 1})()

        await templates_handler.save_template_content(
            message,
            state,
            db_session=session,
            settings=settings,
            user=user,
            is_admin=True,
        )

        assert message.answers[0][0] == templates_handler.texts.ADMIN_TEMPLATE_TOO_SHORT_TEXT
        assert state.cleared is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_save_template_content_warns_about_missing_and_unknown_placeholders() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        message = FakeMessage("Жду тебя {date} и {datatime} 🌸")
        state = FakeState()
        await state.update_data(
            admin_template_key="booking_confirm",
            admin_template_category="clients",
        )
        user = type("UserStub", (), {"id": 1})()

        await templates_handler.save_template_content(
            message,
            state,
            db_session=session,
            settings=settings,
            user=user,
            is_admin=True,
        )

        assert state.state == templates_handler.AdminTemplateEdit.confirm_content
        assert state.data[templates_handler.TEMPLATE_PENDING_CONTENT_KEY] == message.text
        warning_text, warning_markup = message.answers[-1]
        assert "{time}" in warning_text
        assert "{datatime}" in warning_text
        labels = [button.text for row in warning_markup.inline_keyboard for button in row]
        assert "✅ Сохранить всё равно" in labels
        assert "⬅️ Вернуться к редактированию" in labels

    await engine.dispose()


@pytest.mark.asyncio
async def test_save_template_image_content_rejects_oversized_file() -> None:
    message = FakeUploadMessage(photo=[_FakePhotoSize("largest")], bot=_FakeBot(b"x" * (6 * 1024 * 1024)))
    state = FakeState()
    await state.set_state(templates_handler.AdminTemplateEdit.await_image)
    await state.update_data(admin_template_key="booking_confirm")

    await templates_handler.save_template_image_content(
        message,
        state,
        db_session=None,
    )

    assert message.answers[0][0] == templates_handler.texts.ADMIN_TEMPLATE_IMAGE_TOO_LARGE_TEXT
    assert state.cleared is False


@pytest.mark.asyncio
async def test_cancel_template_edit_returns_to_list(monkeypatch) -> None:
    listed: list[str] = []

    async def fake_show_template_category(
        message,
        *,
        db_session,
        category_key,
        edit,
        state=None,
    ) -> None:
        del message, db_session, edit, state
        listed.append(category_key)

    monkeypatch.setattr(templates_handler, "show_template_category", fake_show_template_category)

    callback = FakeCallback("admin_templates:cancel_edit")
    state = FakeState()
    await state.update_data(admin_template_category="clients")

    await templates_handler.cancel_template_edit(
        callback,
        state,
        db_session=None,
    )

    assert callback.answered is True
    assert state.cleared is True
    assert listed == ["clients"]


@pytest.mark.asyncio
async def test_cancel_template_edit_returns_to_detail_when_template_known(monkeypatch) -> None:
    opened: list[str] = []

    async def fake_show_template_detail(
        message,
        *,
        db_session,
        template_key,
        edit,
        state=None,
    ) -> None:
        del message, db_session, edit, state
        opened.append(template_key)

    monkeypatch.setattr(templates_handler, "show_template_detail", fake_show_template_detail)

    callback = FakeCallback("admin_templates:cancel_edit")
    state = FakeState()
    await state.update_data(
        admin_template_key="repair_intro",
        admin_template_category="clients",
        admin_template_group="repair",
    )

    await templates_handler.cancel_template_edit(
        callback,
        state,
        db_session=None,
    )

    assert callback.answered is True
    assert state.cleared is True
    assert opened == ["repair_intro"]


@pytest.mark.asyncio
async def test_save_template_content_routes_admin_command_instead_of_saving(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        menu_calls: list[str] = []

        async def fake_show_admin_menu(message, *, db_session, settings, state=None) -> None:
            del message, db_session, settings, state
            menu_calls.append("admin-menu")

        monkeypatch.setattr(templates_handler, "show_admin_menu", fake_show_admin_menu)

        message = FakeMessage("/admin")
        state = FakeState()
        await state.update_data(
            admin_template_key="greeting_header",
            admin_template_category="other",
        )
        user = type("UserStub", (), {"id": 1})()

        await templates_handler.save_template_content(
            message,
            state,
            db_session=session,
            settings=settings,
            user=user,
            is_admin=True,
        )

        assert state.cleared is True
        assert menu_calls == ["admin-menu"]
        assert message.answers == []

    await engine.dispose()
