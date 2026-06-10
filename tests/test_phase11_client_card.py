from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.client import menu as client_menu_handler
from src.config import Settings
from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, SlotStatus, User
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.templates import TemplateRepository


class FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class FakeBot:
    def __init__(self) -> None:
        self.chat_actions: list[tuple[int, str]] = []

    async def send_chat_action(self, *, chat_id: int, action: str) -> None:
        self.chat_actions.append((chat_id, action))


class FakeMessage:
    def __init__(self, *, bot: FakeBot | None = None, chat_id: int = 1001) -> None:
        self.bot = bot or FakeBot()
        self.chat = FakeChat(chat_id)
        self.photos: list[dict[str, object | None]] = []
        self.answers: list[tuple[str, object | None]] = []

    async def answer_photo(self, photo, caption: str | None = None, reply_markup=None) -> None:
        self.photos.append(
            {
                "photo": photo,
                "caption": caption,
                "reply_markup": reply_markup,
            }
        )

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_client_card_stats_include_total_spent_and_favorite_service() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=1001,
            display_name="Дарина",
            is_admin=False,
            is_blocked=False,
        )
        manicure = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        pedicure = Service(
            name="Педикюр",
            price=3200,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=20,
        )
        slots = [
            Slot(start_at=datetime.now(UTC) - timedelta(days=20), status=SlotStatus.BOOKED),
            Slot(start_at=datetime.now(UTC) - timedelta(days=10), status=SlotStatus.BOOKED),
            Slot(start_at=datetime.now(UTC) - timedelta(days=5), status=SlotStatus.BOOKED),
        ]
        session.add_all([user, manicure, pedicure, *slots])
        await session.flush()
        session.add_all(
            [
                Booking(
                    client_id=user.id,
                    slot_id=slots[0].id,
                    base_service_id=manicure.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
                Booking(
                    client_id=user.id,
                    slot_id=slots[1].id,
                    base_service_id=manicure.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
                Booking(
                    client_id=user.id,
                    slot_id=slots[2].id,
                    base_service_id=pedicure.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=3200,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
            ]
        )
        await session.commit()

        stats = await BookingRepository(session).get_client_card_stats(user.id)

        assert stats.total_visits == 3
        assert stats.total_spent == 8000
        assert stats.favorite_service_name == "Маникюр"

    await engine.dispose()


@pytest.mark.asyncio
async def test_show_client_menu_uses_brand_photo_panel() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=1001,
            display_name="Матвей",
            is_admin=False,
            is_blocked=False,
        )
        session.add(user)
        await session.flush()
        await TemplateRepository(session).upsert(
            key="greeting_header", content="Привет из карточки"
        )
        await session.commit()

        message = FakeMessage()
        await client_menu_handler.show_client_menu(
            message,
            db_session=session,
            user=user,
        )

        assert len(message.photos) == 1
        assert message.photos[0]["caption"] == "Привет из карточки"
        assert message.photos[0]["reply_markup"] is not None
        assert message.answers == []

    await engine.dispose()
