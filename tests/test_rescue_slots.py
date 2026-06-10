from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import rescue_slots as rescue_slots_handler
from src.bot.handlers.client import booking_flow as booking_flow_handler
from src.config import Settings
from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, SlotStatus, User


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
        self.state = None


class FakeChat:
    def __init__(self, chat_id: int = 501) -> None:
        self.id = chat_id


class FakeBot:
    async def send_message(self, *args, **kwargs) -> None:  # pragma: no cover - safety fallback
        del args, kwargs
        return None


class FakeMessage:
    def __init__(self, *, bot: FakeBot | None = None) -> None:
        self.bot = bot or FakeBot()
        self.chat = FakeChat()
        self.message_id = 77
        self.edits: list[tuple[str, object | None]] = []
        self.answers: list[tuple[str, object | None]] = []
        self.deleted = False

    async def edit_text(self, text: str, reply_markup=None, parse_mode=None) -> None:
        del parse_mode
        self.edits.append((text, reply_markup))

    async def answer(self, text: str, reply_markup=None, parse_mode=None) -> None:
        del parse_mode
        self.answers.append((text, reply_markup))

    async def delete(self) -> None:
        self.deleted = True


class FakeFromUser:
    def __init__(self, first_name: str = "Аня") -> None:
        self.first_name = first_name


class FakeCallback:
    def __init__(self, data: str, *, message: FakeMessage | None = None) -> None:
        self.data = data
        self.message = message or FakeMessage()
        self.bot = self.message.bot
        self.from_user = FakeFromUser()
        self.answered = False

    async def answer(self, *args, **kwargs) -> None:
        del args, kwargs
        self.answered = True


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


async def seed_completed_visits(
    session,
    *,
    user: User,
    service: Service,
    visits: int,
) -> None:
    now = datetime.now(UTC)
    for index in range(visits):
        slot = Slot(
            start_at=now - timedelta(days=index + 2),
            status=SlotStatus.BOOKED,
        )
        session.add(slot)
        await session.flush()
        session.add(
            Booking(
                client_id=user.id,
                slot_id=slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=service.price,
                has_variable_price=False,
                status=BookingStatus.COMPLETED,
                payment_method="transfer",
            )
        )
    await session.flush()


@pytest.mark.asyncio
async def test_admin_rescue_offer_sends_only_to_loyal_available_clients(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        rescue_slot = Slot(
            start_at=datetime.now(UTC) + timedelta(hours=3),
            status=SlotStatus.FREE,
        )
        excluded_user = User(
            tg_id=2001,
            display_name="Исключённая",
            phone="+79990000001",
            is_admin=False,
            is_blocked=False,
        )
        loyal_user = User(
            tg_id=2002,
            display_name="Лояльная",
            phone="+79990000002",
            is_admin=False,
            is_blocked=False,
        )
        active_user = User(
            tg_id=2003,
            display_name="Занятая",
            phone="+79990000003",
            is_admin=False,
            is_blocked=False,
        )
        session.add_all([service, rescue_slot, excluded_user, loyal_user, active_user])
        await session.flush()

        await seed_completed_visits(session, user=excluded_user, service=service, visits=5)
        await seed_completed_visits(session, user=loyal_user, service=service, visits=5)
        await seed_completed_visits(session, user=active_user, service=service, visits=5)

        active_slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.BOOKED,
        )
        session.add(active_slot)
        await session.flush()
        session.add(
            Booking(
                client_id=active_user.id,
                slot_id=active_slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=service.price,
                has_variable_price=False,
                status=BookingStatus.CONFIRMED,
                payment_method="transfer",
            )
        )
        await session.commit()

        sent_chat_ids: list[int] = []

        async def fake_send_brand_bot_message(bot, *, chat_id, caption, reply_markup=None, **kwargs):
            del bot, caption, reply_markup, kwargs
            sent_chat_ids.append(chat_id)

        monkeypatch.setattr(
            rescue_slots_handler,
            "send_brand_bot_message",
            fake_send_brand_bot_message,
        )

        callback = FakeCallback(
            f"rescue_slot:send:{rescue_slot.id}:{excluded_user.id}",
        )

        await rescue_slots_handler.send_rescue_slot_offer(
            callback,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        assert callback.answered is True
        assert sent_chat_ids == [loyal_user.tg_id]
        assert callback.message.edits
        assert "Разослала оффер" in callback.message.edits[-1][0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_claim_rescue_offer_starts_booking_with_locked_slot(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=3001,
            display_name="Аня",
            phone="+79990000000",
            is_admin=False,
            is_blocked=False,
        )
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(hours=5),
            status=SlotStatus.FREE,
        )
        session.add_all([user, service, slot])
        await session.commit()

        template_calls: list[dict[str, object]] = []

        async def fake_send_template_message(
            message,
            *,
            template_key,
            caption,
            reply_markup=None,
            replace_current=False,
            parse_mode=None,
        ) -> None:
            del message, reply_markup, parse_mode
            template_calls.append(
                {
                    "template_key": template_key,
                    "caption": caption,
                    "replace_current": replace_current,
                }
            )

        monkeypatch.setattr(booking_flow_handler, "send_template_message", fake_send_template_message)

        callback = FakeCallback(f"rescue_offer:claim:{slot.id}")
        state = FakeState()

        await booking_flow_handler.claim_rescue_offer(
            callback,
            state,
            db_session=session,
            user=user,
            settings=settings,
        )

        assert callback.answered is True
        assert state.data["locked_slot_offer"] is True
        assert state.data["browse_mode"] is True
        assert state.data["slot_id"] == slot.id
        assert template_calls
        assert template_calls[-1]["template_key"] == "price"
        assert template_calls[-1]["replace_current"] is True

    await engine.dispose()
