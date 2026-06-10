from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.client import booking_flow
from src.bot.states import Booking as BookingStates
from src.config import Settings
from src.db.base import Base
from src.db.models import Service, ServiceKind
from src.db.repositories.templates import TemplateRepository


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.state = None

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def set_state(self, state) -> None:
        self.state = state

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)


class FakeChat:
    id = 1001


class FakeBot:
    def __init__(self) -> None:
        self.chat_actions: list[tuple[int, str]] = []

    async def send_chat_action(self, *, chat_id: int, action: str) -> None:
        self.chat_actions.append((chat_id, action))


class FakeMessage:
    def __init__(self) -> None:
        self.bot = FakeBot()
        self.chat = FakeChat()
        self.message_id = 40
        self.photos: list[dict[str, object | None]] = []
        self.answers: list[tuple[str, object | None]] = []
        self.deleted = 0

    async def answer_photo(self, photo, caption: str | None = None, reply_markup=None):
        self.photos.append({"photo": photo, "caption": caption, "reply_markup": reply_markup})

    async def answer(self, text: str, reply_markup=None):
        self.answers.append((text, reply_markup))

    async def delete(self) -> None:
        self.deleted += 1


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_booking_flow_sends_price_template_before_service_picker() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(
            Service(
                name="Покрытие гель-лак",
                price=2400,
                price_variable=False,
                duration_min=120,
                kind=ServiceKind.BASE,
                is_active=True,
                display_order=10,
            )
        )
        await session.commit()
        await TemplateRepository(session).upsert(
            key="price",
            content="Прайс шаблоном",
        )
        await session.commit()

        message = FakeMessage()
        state = FakeState()

        await booking_flow.show_base_service_step(
            message,
            db_session=session,
            state=state,
        )

        assert state.state == BookingStates.choose_base_service
        if message.photos:
            assert len(message.photos) == 1
            assert message.photos[0]["caption"] == "Прайс шаблоном"
            assert message.photos[0]["reply_markup"] is not None
            assert message.answers == []
        else:
            assert len(message.answers) == 1
            assert message.answers[0][0] == "Прайс шаблоном"
            assert message.answers[0][1] is not None

    await engine.dispose()
