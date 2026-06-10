from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot import texts
from src.bot.handlers.client import booking_flow
from src.bot.keyboards.admin import build_admin_schedule_menu
from src.bot.states import Booking as BookingStates
from src.config import Settings
from src.db.base import Base
from src.db.models import Slot, SlotStatus
from src.db.repositories.settings import SettingRepository
from src.services.schedule_image import ScheduleImageEntry, ScheduleImagePage


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = dict(data or {})
        self.state = None
        self.cleared = False

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def set_state(self, state) -> None:
        self.state = state

    async def clear(self) -> None:
        self.data.clear()
        self.cleared = True

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)


class FakeBot:
    def __init__(self) -> None:
        self.edited_messages: list[dict[str, object | None]] = []
        self.chat_actions: list[tuple[int, str]] = []

    async def send_chat_action(self, *, chat_id: int, action: str) -> None:
        self.chat_actions.append((chat_id, action))

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup=None,
        parse_mode=None,
    ) -> None:
        self.edited_messages.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )


class FakeChat:
    def __init__(self, chat_id: int = 1001) -> None:
        self.id = chat_id


class FakeMessage:
    def __init__(self, *, bot: FakeBot | None = None) -> None:
        self.bot = bot or FakeBot()
        self.chat = FakeChat()
        self.answers: list[tuple[str, object | None]] = []
        self.photos: list[dict[str, object | None]] = []
        self.edits: list[tuple[str, object | None]] = []
        self.deleted = 0
        self.message_id = 40

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))
        self.message_id += 1

    async def answer_photo(self, photo, caption: str | None = None, reply_markup=None) -> None:
        self.photos.append(
            {
                "photo": photo,
                "caption": caption,
                "reply_markup": reply_markup,
            }
        )
        self.message_id += 1

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))

    async def delete(self) -> None:
        self.deleted += 1


class FakeCallback:
    def __init__(self, data: str, *, message: FakeMessage | None = None) -> None:
        self.data = data
        self.bot = FakeBot()
        self.message = message or FakeMessage(bot=self.bot)
        self.answered = False
        self.answer_payload: tuple[tuple[object, ...], dict[str, object]] | None = None

    async def answer(self, *args, **kwargs) -> None:
        self.answered = True
        self.answer_payload = (args, kwargs)


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_show_day_step_sends_schedule_photo_when_enabled(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await SettingRepository(session).upsert(key="schedule_image_enabled", value="true")
        session.add(
            Slot(
                start_at=datetime.now(UTC) + timedelta(days=1),
                status=SlotStatus.FREE,
            )
        )
        await session.commit()

        async def fake_build_schedule_image_pages_data(*args, **kwargs) -> list[ScheduleImagePage]:
            del args, kwargs
            local_date = datetime.now(UTC).date() + timedelta(days=1)
            return [
                ScheduleImagePage(
                    entries=[
                        ScheduleImageEntry(
                            local_date=local_date,
                            day_label="завтра",
                            times=["12:00"],
                        )
                    ],
                    period="завтра",
                    caption="",
                    page_number=1,
                    total_pages=1,
                )
            ]

        def fake_render_schedule_image_bytes(*args, **kwargs) -> bytes:
            del args, kwargs
            return b"fake-image"

        monkeypatch.setattr(
            booking_flow,
            "build_schedule_image_pages_data",
            fake_build_schedule_image_pages_data,
        )
        monkeypatch.setattr(
            booking_flow,
            "render_schedule_image_bytes",
            fake_render_schedule_image_bytes,
        )

        message = FakeMessage()
        state = FakeState()

        await booking_flow.show_day_step(
            message,
            db_session=session,
            state=state,
            settings=settings,
        )

        assert state.state == BookingStates.choose_day
        assert message.answers == []
        assert len(message.photos) == 1
        assert message.photos[0]["caption"] == texts.BOOKING_SCHEDULE_IMAGE_CAPTION_TEXT
        assert message.photos[0]["reply_markup"] is not None

    await engine.dispose()


def test_admin_schedule_menu_has_no_separate_image_button() -> None:
    callbacks = [
        button.callback_data
        for row in build_admin_schedule_menu().inline_keyboard
        for button in row
    ]

    assert "admin_schedule:image" not in callbacks


@pytest.mark.asyncio
async def test_choose_base_service_replaces_previous_screen(monkeypatch) -> None:
    replace_values: list[bool] = []

    async def fake_show_addons_step(message, *, db_session, state, replace=False) -> None:
        del db_session, state
        replace_values.append(replace)
        await message.answer("addons-step")

    monkeypatch.setattr(booking_flow, "show_addons_step", fake_show_addons_step)

    callback = FakeCallback("booking:base:42")
    state = FakeState()

    await booking_flow.choose_base_service(
        callback,
        state,
        db_session=None,
    )

    assert callback.answered is True
    assert callback.message.deleted == 0
    assert state.data["base_service_id"] == 42
    assert replace_values == [True]
    assert callback.message.answers == [("addons-step", None)]


@pytest.mark.asyncio
async def test_cancel_booking_flow_reuses_menu_screen(monkeypatch) -> None:
    menu_calls: list[int] = []

    async def fake_show_client_menu(message, *, db_session, user, replace_current=False) -> None:
        del db_session
        menu_calls.append(user.id)
        menu_calls.append(int(replace_current))
        await message.answer("menu")

    async def fake_clear_state(state) -> None:
        await state.clear()

    monkeypatch.setattr(booking_flow, "show_client_menu", fake_show_client_menu)
    monkeypatch.setattr(booking_flow, "clear_state_preserving_admin_mode", fake_clear_state)

    callback = FakeCallback("booking:cancel")
    state = FakeState({"slot_id": 1})
    user = type("UserStub", (), {"id": 77})()

    await booking_flow.cancel_booking_flow(
        callback,
        state,
        db_session=None,
        user=user,
    )

    assert callback.answered is True
    assert callback.answer_payload == ((texts.BOOKING_CANCELLED_TEXT,), {})
    assert callback.message.deleted == 0
    assert state.cleared is True
    assert menu_calls == [77, 1]
    assert callback.message.answers == [("menu", None)]
