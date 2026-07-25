from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.base import Base
from src.db.models import (
    ApprovalRequest,
    ApprovalRequestKind,
    ApprovalRequestStatus,
    Booking,
    BookingStatus,
    Service,
    ServiceKind,
    Slot,
    SlotStatus,
    User,
)
from src.db.repositories.bookings import BookingRepository
from src.services.booking import reschedule_booking
from src.services.force_majeure import cancel_force_majeure_day


@pytest.mark.asyncio
async def test_force_majeure_does_not_cancel_booking_moved_to_another_day(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'force-race.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    first_start = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(days=2)
    second_start = first_start + timedelta(days=1)
    async with session_factory() as seed_session:
        user = User(
            tg_id=9201,
            display_name="Лена",
            phone="+79990009201",
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
        first_slot = Slot(start_at=first_start, status=SlotStatus.BOOKED)
        second_slot = Slot(start_at=second_start, status=SlotStatus.FREE)
        booking = Booking(
            client=user,
            slot=first_slot,
            base_service=service,
            addons=[],
            design_photos=[],
            fixed_price=service.price,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        approval = ApprovalRequest(
            client=user,
            related_booking=booking,
            requested_text="Перенести запись",
            kind=ApprovalRequestKind.RESCHEDULE,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        seed_session.add_all([user, service, first_slot, second_slot, booking, approval])
        await seed_session.commit()
        booking_id = booking.id
        approval_id = approval.id
        second_slot_id = second_slot.id

    async with session_factory() as session:
        booking = await BookingRepository(session).get_by_id(booking_id)
        assert booking is not None
        moved = await reschedule_booking(
            session,
            booking=booking,
            new_slot_id=second_slot_id,
        )
        assert moved.ok is True

    async with session_factory() as session:
        cancelled_ids = await cancel_force_majeure_day(
            session,
            local_day=first_start.date(),
            tz_name="UTC",
            reason="Авария",
        )
        assert cancelled_ids == []

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        approval = await session.get(ApprovalRequest, approval_id)
        assert booking is not None
        assert booking.status == BookingStatus.CONFIRMED
        assert booking.slot_id == second_slot_id
        assert approval is not None
        assert approval.status == ApprovalRequestStatus.PENDING

    await engine.dispose()
