from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, User
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.users import UserRepository


@pytest.mark.asyncio
async def test_user_repository_search_and_broadcast_filters() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        anna = User(
            tg_id=1001,
            tg_username="nail_anna",
            display_name="Анна",
            is_admin=False,
            is_blocked=False,
        )
        lena = User(
            tg_id=1002,
            tg_username="blocked_user",
            display_name="Лена",
            is_admin=False,
            is_blocked=True,
        )
        owner = User(
            tg_id=9001,
            tg_username="owner",
            display_name="Ангела",
            is_admin=True,
            is_blocked=False,
        )
        service = Service(
            name="Маникюр",
            price=2000,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status="booked",
        )
        session.add_all([anna, lena, owner, service, slot])
        await session.flush()
        session.add(
            Booking(
                client_id=anna.id,
                slot_id=slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=2000,
                has_variable_price=False,
                status=BookingStatus.CONFIRMED,
            )
        )
        await session.commit()

        repository = UserRepository(session)
        by_name = await repository.search_clients("анн")
        by_username = await repository.search_clients("@nail_anna")
        broadcast = await repository.list_broadcast_recipients()

        assert [user.display_name for user in by_name] == ["Анна"]
        assert [user.display_name for user in by_username] == ["Анна"]
        assert [user.tg_id for user in broadcast] == [1001]

    await engine.dispose()


@pytest.mark.asyncio
async def test_booking_repository_builds_client_card_stats() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=2001,
            display_name="Марина",
            is_admin=False,
            is_blocked=False,
        )
        service = Service(
            name="Маникюр",
            price=2100,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        now = datetime.now(UTC)
        slots = [
            Slot(start_at=now - timedelta(days=20), status="booked"),
            Slot(start_at=now - timedelta(days=10), status="booked"),
            Slot(start_at=now - timedelta(days=5), status="booked"),
            Slot(start_at=now - timedelta(days=1), status="booked"),
        ]
        session.add_all([user, service, *slots])
        await session.flush()
        session.add_all(
            [
                Booking(
                    client_id=user.id,
                    slot_id=slots[0].id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2100,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
                Booking(
                    client_id=user.id,
                    slot_id=slots[1].id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2100,
                    has_variable_price=False,
                    status=BookingStatus.CANCELLED_BY_CLIENT,
                ),
                Booking(
                    client_id=user.id,
                    slot_id=slots[2].id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2100,
                    has_variable_price=False,
                    status=BookingStatus.CANCELLED_BY_MASTER,
                ),
                Booking(
                    client_id=user.id,
                    slot_id=slots[3].id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2100,
                    has_variable_price=False,
                    status=BookingStatus.NO_SHOW,
                ),
            ]
        )
        await session.commit()

        repository = BookingRepository(session)
        stats = await repository.get_client_card_stats(user.id)

        assert stats.total_visits == 1
        assert stats.total_cancels == 2
        assert stats.no_shows == 1
        assert stats.average_check == 2100

    await engine.dispose()


@pytest.mark.asyncio
async def test_booking_repository_builds_period_stats() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        first_client = User(
            tg_id=3001,
            display_name="Саша",
            is_admin=False,
            is_blocked=False,
        )
        second_client = User(
            tg_id=3002,
            display_name="Оля",
            is_admin=False,
            is_blocked=False,
        )
        service_a = Service(
            name="Маникюр",
            price=2200,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        service_b = Service(
            name="Педикюр",
            price=3200,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=20,
        )
        start_utc = datetime.now(UTC) - timedelta(days=31)
        slots = [
            Slot(start_at=start_utc + timedelta(days=2), status="booked"),
            Slot(start_at=start_utc + timedelta(days=4), status="booked"),
            Slot(start_at=start_utc + timedelta(days=6), status="booked"),
            Slot(start_at=start_utc + timedelta(days=8), status="booked"),
        ]
        session.add_all([first_client, second_client, service_a, service_b, *slots])
        await session.flush()
        session.add_all(
            [
                Booking(
                    client_id=first_client.id,
                    slot_id=slots[0].id,
                    base_service_id=service_a.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2200,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
                Booking(
                    client_id=first_client.id,
                    slot_id=slots[1].id,
                    base_service_id=service_a.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2200,
                    has_variable_price=False,
                    status=BookingStatus.CANCELLED_BY_CLIENT,
                    cancel_reason_code="busy",
                ),
                Booking(
                    client_id=second_client.id,
                    slot_id=slots[2].id,
                    base_service_id=service_b.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=3200,
                    has_variable_price=False,
                    status=BookingStatus.CANCELLED_BY_MASTER,
                ),
                Booking(
                    client_id=second_client.id,
                    slot_id=slots[3].id,
                    base_service_id=service_a.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2200,
                    has_variable_price=False,
                    status=BookingStatus.NO_SHOW,
                ),
            ]
        )
        await session.commit()

        repository = BookingRepository(session)
        stats = await repository.get_period_stats(
            start_utc=start_utc,
            end_utc=start_utc + timedelta(days=30),
        )

        assert stats.total_bookings == 4
        assert stats.completed_count == 1
        assert stats.cancelled_by_client_count == 1
        assert stats.cancelled_by_master_count == 1
        assert stats.no_show_count == 1
        assert stats.revenue == 2200
        assert stats.cancel_reason_counts["busy"] == 1
        assert stats.top_services[0] == ("Маникюр", 3)

    await engine.dispose()
