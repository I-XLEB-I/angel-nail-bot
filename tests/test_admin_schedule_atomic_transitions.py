from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.base import Base
from src.db.models import (
    Booking,
    BookingStatus,
    Service,
    ServiceKind,
    Slot,
    SlotStatus,
    User,
)
from src.services import admin_schedule as admin_schedule_service
from src.services.booking import confirm_booking


async def _seed_slot_dependencies(session) -> tuple[User, Service]:
    user = User(
        tg_id=8101,
        display_name="Лена",
        phone="+79990008101",
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
    session.add_all([user, service])
    await session.flush()
    return user, service


@pytest.mark.asyncio
async def test_stale_move_cannot_change_newly_booked_slot(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'move.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    original_start = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(days=2)
    async with session_factory() as seed_session:
        user, service = await _seed_slot_dependencies(seed_session)
        slot = Slot(start_at=original_start, status=SlotStatus.FREE)
        seed_session.add(slot)
        await seed_session.commit()
        user_id = user.id
        service_id = service.id
        slot_id = slot.id

    async with session_factory() as stale_session:
        assert await stale_session.get(Slot, slot_id) is not None
        await stale_session.commit()

        async with session_factory() as current_session:
            result = await confirm_booking(
                current_session,
                client_id=user_id,
                slot_id=slot_id,
                base_service_id=service_id,
                addon_ids=[],
                design_photos=[],
                design_comment=None,
            )
            assert result.ok is True

        new_start = original_start + timedelta(days=3)
        stale_result = await admin_schedule_service.move_schedule_slot(
            stale_session,
            slot_id=slot_id,
            raw_text=new_start.strftime("%d.%m %H:%M"),
            tz_name="UTC",
        )
        assert stale_result.ok is False
        assert stale_result.reason == "booked"

    async with session_factory() as verify_session:
        slot = await verify_session.get(Slot, slot_id)
        assert slot is not None
        assert slot.status == SlotStatus.BOOKED
        assert slot.start_at.replace(tzinfo=UTC) == original_start

    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_unblock_cannot_release_newly_booked_slot(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'unblock.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as seed_session:
        user, service = await _seed_slot_dependencies(seed_session)
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=2),
            status=SlotStatus.BLOCKED,
        )
        seed_session.add(slot)
        await seed_session.commit()
        user_id = user.id
        service_id = service.id
        slot_id = slot.id

    async with session_factory() as stale_session:
        assert await stale_session.get(Slot, slot_id) is not None
        await stale_session.commit()

        async with session_factory() as current_session:
            unblocked = await admin_schedule_service.unblock_schedule_slot(
                current_session,
                slot_id=slot_id,
            )
            assert unblocked.ok is True
            booked = await confirm_booking(
                current_session,
                client_id=user_id,
                slot_id=slot_id,
                base_service_id=service_id,
                addon_ids=[],
                design_photos=[],
                design_comment=None,
            )
            assert booked.ok is True

        stale_result = await admin_schedule_service.unblock_schedule_slot(
            stale_session,
            slot_id=slot_id,
        )
        assert stale_result.ok is False
        assert stale_result.reason == "booked"

    async with session_factory() as verify_session:
        slot = await verify_session.get(Slot, slot_id)
        assert slot is not None
        assert slot.status == SlotStatus.BOOKED

    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_keeps_slot_referenced_by_booking_history(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await _seed_slot_dependencies(session)
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=2),
            status=SlotStatus.FREE,
        )
        session.add(slot)
        await session.flush()
        booking = Booking(
            client_id=user.id,
            slot_id=slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=service.price,
            has_variable_price=False,
            status=BookingStatus.CANCELLED_BY_CLIENT,
        )
        session.add(booking)
        await session.commit()
        slot_id = slot.id
        booking_id = booking.id

        result = await admin_schedule_service.delete_schedule_slot(
            session,
            slot_id=slot_id,
        )
        assert result.ok is False
        assert result.reason == "referenced"

    async with session_factory() as verify_session:
        assert await verify_session.get(Slot, slot_id) is not None
        assert await verify_session.get(Booking, booking_id) is not None

    await engine.dispose()
