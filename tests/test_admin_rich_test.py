from __future__ import annotations

import io

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot import texts
from src.bot.handlers.admin import rich_test as rich_test_handler
from src.config import Settings
from src.db.base import Base
from src.db.models import Service, ServiceKind
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services import rich_messages as rich_messages_service


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = dict(data or {})
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
        self.state = None


class FakeChat:
    def __init__(self, chat_id: int = 500) -> None:
        self.id = chat_id


class FakeBot:
    def __init__(self) -> None:
        self.edits: list[dict[str, object | None]] = []
        self.sent_messages: list[dict[str, object | None]] = []
        self.sent_photos: list[dict[str, object | None]] = []
        self.copied_messages: list[dict[str, object | None]] = []
        self.deleted_messages: list[dict[str, int]] = []
        self.sent_rich_messages: list[dict[str, object]] = []
        self.download_bytes = b"test-image"

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup=None,
        parse_mode=None,
    ) -> None:
        self.edits.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup=None,
        parse_mode=None,
    ):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.sent_messages.append(payload)
        return type(
            "SentMessage",
            (),
            {
                "chat": FakeChat(chat_id),
                "message_id": len(self.sent_messages) + 100,
            },
        )()

    async def copy_message(
        self,
        *,
        chat_id: int,
        from_chat_id: int,
        message_id: int,
        reply_markup=None,
    ):
        payload = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
            "reply_markup": reply_markup,
        }
        self.copied_messages.append(payload)
        return type("MessageId", (), {"message_id": len(self.copied_messages) + 700})()

    async def delete_message(self, *, chat_id: int, message_id: int) -> None:
        self.deleted_messages.append({"chat_id": chat_id, "message_id": message_id})

    async def download(self, _file_object):
        return io.BytesIO(self.download_bytes)

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo,
        caption: str,
        reply_markup=None,
        parse_mode=None,
    ):
        payload = {
            "chat_id": chat_id,
            "photo": photo,
            "caption": caption,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.sent_photos.append(payload)
        return type(
            "PhotoMessageRef",
            (),
            {
                "chat": FakeChat(chat_id),
                "message_id": len(self.sent_photos) + 500,
            },
        )()

    async def send_rich_message(self, *, chat_id: int, rich_message, reply_markup=None):
        payload = {
            "chat_id": chat_id,
            "rich_message": rich_message,
            "reply_markup": reply_markup,
        }
        self.sent_rich_messages.append(payload)
        return type(
            "RichMessageRef",
            (),
            {
                "chat": FakeChat(chat_id),
                "message_id": len(self.sent_rich_messages) + 900,
            },
        )()


class FakeMessage:
    def __init__(
        self,
        text: str | None = None,
        *,
        bot: FakeBot | None = None,
        message_id: int = 42,
        caption: str | None = None,
        content_type: str = "text",
        rich_message=None,
        media_group_id: str | None = None,
        photo=None,
        document=None,
    ) -> None:
        self.text = text
        self.caption = caption
        self.content_type = content_type
        self.rich_message = rich_message
        self.media_group_id = media_group_id
        self.photo = photo
        self.document = document
        self.bot = bot or FakeBot()
        self.chat = FakeChat()
        self.message_id = message_id
        self.answers: list[tuple[str, object | None]] = []
        self.edits: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None, parse_mode=None):
        del parse_mode
        self.answers.append((text, reply_markup))
        return type(
            "AnsweredMessage",
            (),
            {
                "chat": self.chat,
                "message_id": self.message_id + len(self.answers),
            },
        )()

    async def edit_text(self, text: str, reply_markup=None, parse_mode=None) -> None:
        del parse_mode
        self.edits.append((text, reply_markup))


class FakeCallback:
    def __init__(
        self,
        data: str,
        *,
        message: FakeMessage | None = None,
        bot: FakeBot | None = None,
    ) -> None:
        self.data = data
        self.bot = bot or FakeBot()
        self.message = message or FakeMessage(bot=self.bot)
        self.answered = False

    async def answer(self, *args, **kwargs) -> None:
        del args, kwargs
        self.answered = True


def build_settings(admin_ids: str = "1,2") -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS=admin_ids,
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_open_rich_test_respects_disabled_flag() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        message = FakeMessage("🧪 Rich тест")
        state = FakeState()

        await rich_test_handler.open_rich_test(
            message,
            state,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        assert message.answers == [(texts.ADMIN_RICH_TEST_DISABLED_TEXT, None)]

    await engine.dispose()


@pytest.mark.asyncio
async def test_build_rich_price_message_includes_media_when_available() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add_all(
            [
                Service(
                    name="Маникюр",
                    price=2400,
                    price_variable=False,
                    duration_min=120,
                    kind=ServiceKind.BASE,
                    is_active=True,
                    display_order=10,
                ),
                Service(
                    name="Дизайн",
                    price=250,
                    price_variable=True,
                    duration_min=30,
                    kind=ServiceKind.ADDON,
                    is_active=True,
                    display_order=20,
                ),
            ]
        )
        await TemplateRepository(session).upsert(
            key="price",
            content="💅 ПРАЙС\n\nАктуальные услуги ниже.",
        )
        await session.commit()

        rich_message = await rich_messages_service.build_rich_price_message(session)

        assert rich_message.blocks is not None
        assert "InputRichBlockPhoto" in str(rich_message.blocks)
        assert "Маникюр" in str(rich_message.blocks)
        assert "Дизайн" in str(rich_message.blocks)
        assert "Основные услуги" in str(rich_message.blocks)
        assert "Дополнительно" in str(rich_message.blocks)

    await engine.dispose()


@pytest.mark.asyncio
async def test_build_rich_price_message_skips_media_when_disabled(
    monkeypatch,
    tmp_path,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(
            Service(
                name="Маникюр",
                price=2400,
                price_variable=False,
                duration_min=120,
                kind=ServiceKind.BASE,
                is_active=True,
                display_order=10,
            )
        )
        await session.commit()

        monkeypatch.setattr(rich_messages_service, "has_template_media", lambda key: False)
        monkeypatch.setattr(rich_messages_service, "DEFAULT_ASSETS_DIR", tmp_path)
        rich_message = await rich_messages_service.build_rich_price_message(session)

        assert rich_message.media is None
        assert "InputRichBlockPhoto" not in str(rich_message.blocks)
        assert "Маникюр" in str(rich_message.blocks)

    await engine.dispose()


@pytest.mark.asyncio
async def test_registered_preview_sends_standard_then_rich() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await SettingRepository(session).upsert(key="rich_messages_test_enabled", value="true")
        await session.commit()
        bot = FakeBot()
        callback = FakeCallback(
            "admin_rich_test:preview:reminder_2h",
            message=FakeMessage(bot=bot, message_id=555),
            bot=bot,
        )
        state = FakeState(
            {
                "admin_panel_chat_id": 500,
                "admin_panel_message_id": 77,
            }
        )

        await rich_test_handler.send_rich_price_preview(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        assert len(bot.sent_messages) == 1
        assert "15 минут" in str(bot.sent_messages[0]["text"])
        assert len(bot.sent_rich_messages) == 1
        assert "InputRichBlockSectionHeading" in str(
            bot.sent_rich_messages[0]["rich_message"].blocks
        )
        assert bot.sent_messages[0]["reply_markup"].inline_keyboard[0][0].text == (
            "Обычный вариант"
        )
        assert bot.sent_rich_messages[0]["reply_markup"].inline_keyboard[0][0].text == (
            "Rich вариант"
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_rich_media_upload_uses_isolated_key(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    saved: dict[str, object] = {}

    def fake_save_template_media(key: str, content: bytes) -> None:
        saved["key"] = key
        saved["content"] = content

    monkeypatch.setattr(rich_test_handler, "save_template_media", fake_save_template_media)
    monkeypatch.setattr(rich_test_handler, "has_template_media", lambda _key: False)

    async with session_factory() as session:
        await SettingRepository(session).upsert(key="rich_messages_test_enabled", value="true")
        await session.commit()
        bot = FakeBot()
        state = FakeState(
            {
                "admin_panel_chat_id": 500,
                "admin_panel_message_id": 77,
                "admin_rich_media_key": "rich_price_header",
            }
        )
        message = FakeMessage(bot=bot, photo=[object()])

        await rich_test_handler.save_rich_media_upload(
            message,
            state,
            db_session=session,
            is_admin=True,
        )

        assert saved == {"key": "rich_price_header", "content": b"test-image"}
        assert "только для Rich теста" in str(bot.edits[-1]["text"])
        assert saved["key"] != "price"

    await engine.dispose()


@pytest.mark.asyncio
async def test_capture_rich_test_source_creates_preview_copy() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await SettingRepository(session).upsert(key="rich_messages_test_enabled", value="true")
        await session.commit()

        bot = FakeBot()
        state = FakeState(
            {
                "admin_panel_chat_id": 500,
                "admin_panel_message_id": 77,
            }
        )
        message = FakeMessage(
            text=None,
            caption="Тестовый rich broadcast",
            content_type="photo",
            bot=bot,
            message_id=99,
        )

        await rich_test_handler.capture_rich_test_broadcast_source(
            message,
            state,
            db_session=session,
            is_admin=True,
        )

        assert state.data["admin_rich_test_source_message_id"] == 99
        assert bot.copied_messages[0]["chat_id"] == 500
        assert bot.copied_messages[0]["from_chat_id"] == 500
        assert state.data["admin_rich_test_preview_message_id"] == 701
        assert "ПРЕВЬЮ ГОТОВО" in str(bot.edits[-1]["text"])

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_rich_test_broadcast_targets_only_admin_ids() -> None:
    settings = build_settings("9001,9002")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await SettingRepository(session).upsert(key="rich_messages_test_enabled", value="true")
        await session.commit()

        bot = FakeBot()
        callback = FakeCallback(
            "admin_rich_test:broadcast_confirm",
            message=FakeMessage(bot=bot, message_id=555),
            bot=bot,
        )
        state = FakeState(
            {
                "admin_panel_chat_id": 500,
                "admin_panel_message_id": 77,
                "admin_panel_aux_chat_id": 500,
                "admin_panel_aux_message_id": 701,
                "admin_rich_test_source_chat_id": 500,
                "admin_rich_test_source_message_id": 321,
            }
        )

        await rich_test_handler.confirm_rich_test_broadcast(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        delivered_chat_ids = [item["chat_id"] for item in bot.copied_messages]
        assert delivered_chat_ids == [9001, 9002]
        assert bot.deleted_messages[0] == {"chat_id": 500, "message_id": 701}
        assert "Получатели: только admin_tg_ids" in str(bot.edits[-1]["text"])

    await engine.dispose()


@pytest.mark.asyncio
async def test_validate_rich_test_source_rejects_albums() -> None:
    message = FakeMessage(
        caption="Альбом",
        content_type="photo",
        media_group_id="album-1",
    )

    assert (
        rich_messages_service.validate_rich_test_source_message(message)
        == texts.ADMIN_RICH_TEST_UNSUPPORTED_MESSAGE_TEXT
    )
