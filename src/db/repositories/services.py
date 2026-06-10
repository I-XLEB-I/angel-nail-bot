from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ApprovalRequest, Booking, Service, ServiceKind


class ServiceRepository:
    """Repository for services."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, service_id: int) -> Service | None:
        """Return a service by its primary key."""
        return await self.session.get(Service, service_id)

    async def get_by_name(self, name: str) -> Service | None:
        """Return a service by its visible name."""
        result = await self.session.execute(select(Service).where(Service.name == name))
        return result.scalar_one_or_none()

    async def list_active(self, *, kind: ServiceKind | None = None) -> list[Service]:
        """Return active services, optionally filtered by kind."""
        query = (
            select(Service)
            .where(Service.is_active.is_(True))
            .order_by(Service.display_order, Service.id)
        )
        if kind is not None:
            query = query.where(Service.kind == kind)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_all(self) -> list[Service]:
        """Return all services, including hidden ones."""
        result = await self.session.execute(
            select(Service).order_by(Service.display_order, Service.id)
        )
        return list(result.scalars().all())

    async def list_by_ids(self, service_ids: list[int]) -> list[Service]:
        """Return services matching the provided ids."""
        if not service_ids:
            return []
        query = (
            select(Service)
            .where(Service.id.in_(service_ids))
            .order_by(Service.display_order, Service.id)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def upsert_seed_service(
        self,
        *,
        name: str,
        price: int,
        price_variable: bool,
        duration_min: int,
        kind: ServiceKind,
        display_order: int,
    ) -> Service:
        """Create or refresh a service used by the seed script."""
        service = await self.get_by_name(name)
        if service is None:
            service = Service(
                name=name,
                price=price,
                price_variable=price_variable,
                duration_min=duration_min,
                kind=kind,
                display_order=display_order,
                is_active=True,
            )
            self.session.add(service)
        else:
            service.price = price
            service.price_variable = price_variable
            service.duration_min = duration_min
            service.kind = kind
            service.display_order = display_order
            service.is_active = True

        await self.session.flush()
        return service

    async def next_display_order(self) -> int:
        """Return the next display order for a new service."""
        result = await self.session.execute(select(func.max(Service.display_order)))
        max_value = result.scalar_one()
        return (int(max_value) if max_value is not None else 0) + 10

    async def create(
        self,
        *,
        name: str,
        price: int,
        price_variable: bool,
        duration_min: int,
        kind: ServiceKind,
        is_active: bool = True,
    ) -> Service:
        """Create a service."""
        service = Service(
            name=name,
            price=price,
            price_variable=price_variable,
            duration_min=duration_min,
            kind=kind,
            is_active=is_active,
            display_order=await self.next_display_order(),
        )
        self.session.add(service)
        await self.session.flush()
        return service

    async def update(self, service: Service, **fields: object) -> Service:
        """Update editable service fields."""
        for field_name, value in fields.items():
            setattr(service, field_name, value)
        await self.session.flush()
        return service

    async def has_references(self, service_id: int) -> bool:
        """Return whether the service is referenced by bookings or approval requests."""
        booking_count = await self.session.scalar(
            select(func.count(Booking.id)).where(Booking.base_service_id == service_id)
        )
        approval_count = await self.session.scalar(
            select(func.count(ApprovalRequest.id)).where(
                ApprovalRequest.base_service_id == service_id
            )
        )
        return bool(booking_count or approval_count)

    async def delete_if_unused(self, service: Service) -> bool:
        """Delete a service if no records depend on it."""
        if await self.has_references(service.id):
            return False
        await self.session.delete(service)
        await self.session.flush()
        return True
