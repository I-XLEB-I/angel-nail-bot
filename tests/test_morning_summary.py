from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import Settings
from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, SlotStatus, User
from src.db.repositories.morning_summary_deliveries import MorningSummaryDeliveryRepository
from src.services import morning_summary


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []
        self.deletes: list[dict[str, int]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None):
        payload = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        self.messages.append(payload)
        return type(
            "SentMessage",
            (),
            {
                "chat": type("Chat", (), {"id": chat_id})(),
                "message_id": len(self.messages) + 500,
            },
        )()

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup=None,
    ):
        self.edits.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )

    async def delete_message(self, *, chat_id: int, message_id: int):
        self.deletes.append({"chat_id": chat_id, "message_id": message_id})


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


async def seed_today_booking(
    session_factory,
    *,
    hour: int = 18,
    minute: int = 0,
) -> int:
    tz = ZoneInfo("Europe/Moscow")
    local_now = datetime.now(tz)
    local_start = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local_start.date() != local_now.date() or local_start <= local_now:
        local_start = local_now + timedelta(minutes=1)
        if local_start.date() != local_now.date():
            local_start = local_now.replace(hour=23, minute=59, second=0, microsecond=0)
    async with session_factory() as session:
        user = User(
            tg_id=12345,
            display_name="Софья",
            is_admin=False,
            is_blocked=False,
        )
        service = Service(
            name="Покрытие гель-лак",
            price=2800,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        slot = Slot(start_at=local_start.astimezone(UTC), status=SlotStatus.BOOKED)
        booking = Booking(
            client=user,
            slot=slot,
            base_service=service,
            addons=[],
            design_photos=[],
            fixed_price=2800,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add_all([user, service, slot, booking])
        await session.commit()
        return booking.id


@pytest.mark.asyncio
async def test_send_morning_summary_includes_24h_and_2h_statuses(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    await seed_today_booking(session_factory, hour=18)
    bot = FakeBot()

    @asynccontextmanager
    async def fake_session_scope(_settings):
        async with session_factory() as session:
            yield session

    monkeypatch.setattr(
        morning_summary,
        "session_scope",
        lambda _settings: fake_session_scope(_settings),
    )

    await morning_summary.send_morning_summary(bot, settings)

    assert bot.messages
    text = str(bot.messages[0]["text"])
    assert "🌸" in text
    assert "запись" in text.lower()
    assert "к концу дня" in text.lower()
    assert "24h:" in text
    assert "2h:" in text

    async with session_factory() as session:
        deliveries = await MorningSummaryDeliveryRepository(session).list_for_local_date(
            summary_local_date=datetime.now(ZoneInfo(settings.tz)).date(),
        )
        assert len(deliveries) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_refresh_live_morning_summary_updates_existing_message() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_today_booking(session_factory, hour=23, minute=59)
    bot = FakeBot()
    local_today = datetime.now(ZoneInfo(settings.tz)).date()

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.reminder_24h_sent_at = datetime.now(UTC) - timedelta(hours=20)
        booking.reminder_2h_sent_at = datetime.now(UTC) - timedelta(minutes=15)
        await MorningSummaryDeliveryRepository(session).upsert(
            admin_tg_id=1,
            chat_id=1,
            message_id=888,
            summary_local_date=local_today,
            sent_at=datetime.now(UTC),
        )
        await session.commit()

        booking.reminder_2h_confirmed_at = datetime.now(UTC)
        await session.commit()

        await morning_summary.refresh_live_morning_summary_for_today(
            bot,
            db_session=session,
            settings=settings,
            local_today=local_today,
            now_utc=datetime.now(UTC),
        )

    assert bot.edits
    assert "2h: ✅" in str(bot.edits[-1]["text"])

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_live_morning_summary_to_admin_replaces_tracked_message() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    await seed_today_booking(session_factory, hour=18)
    bot = FakeBot()
    local_today = datetime.now(ZoneInfo(settings.tz)).date()

    async with session_factory() as session:
        await MorningSummaryDeliveryRepository(session).upsert(
            admin_tg_id=1,
            chat_id=1,
            message_id=555,
            summary_local_date=local_today,
            sent_at=datetime.now(UTC),
        )
        await session.commit()

        await morning_summary.send_live_morning_summary_to_admin(
            bot,
            db_session=session,
            settings=settings,
            admin_tg_id=1,
            local_today=local_today,
            now_utc=datetime.now(UTC),
        )

        delivery = await MorningSummaryDeliveryRepository(session).get_by_admin_tg_id(admin_tg_id=1)
        assert delivery is not None
        assert delivery.message_id != 555

    assert bot.deletes == [{"chat_id": 1, "message_id": 555}]
    assert bot.messages

    await engine.dispose()
