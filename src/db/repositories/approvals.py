from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import ApprovalRequest, ApprovalRequestKind, ApprovalRequestStatus, Booking


class ApprovalRequestRepository:
    """Repository for approval requests."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count_pending(self) -> int:
        """Return the number of pending approval requests."""
        result = await self.session.execute(
            select(func.count(ApprovalRequest.id)).where(
                ApprovalRequest.status == ApprovalRequestStatus.PENDING,
            )
        )
        return int(result.scalar_one())

    async def count_pending_for_client(self, client_id: int) -> int:
        """Return the number of pending approval requests for one client."""
        result = await self.session.execute(
            select(func.count(ApprovalRequest.id)).where(
                ApprovalRequest.client_id == client_id,
                ApprovalRequest.status == ApprovalRequestStatus.PENDING,
            )
        )
        return int(result.scalar_one() or 0)

    async def get_by_id(self, approval_id: int) -> ApprovalRequest | None:
        """Return an approval request with its related entities preloaded."""
        result = await self.session.execute(
            select(ApprovalRequest)
            .options(
                selectinload(ApprovalRequest.client),
                selectinload(ApprovalRequest.base_service),
                selectinload(ApprovalRequest.related_booking).selectinload(Booking.slot),
                selectinload(ApprovalRequest.related_booking).selectinload(Booking.base_service),
                selectinload(ApprovalRequest.offered_slot),
            )
            .where(ApprovalRequest.id == approval_id)
        )
        return result.scalar_one_or_none()

    async def list_pending(self) -> list[ApprovalRequest]:
        """Return pending approval requests ordered from oldest to newest."""
        result = await self.session.execute(
            select(ApprovalRequest)
            .options(
                selectinload(ApprovalRequest.client),
                selectinload(ApprovalRequest.base_service),
                selectinload(ApprovalRequest.related_booking).selectinload(Booking.slot),
                selectinload(ApprovalRequest.related_booking).selectinload(Booking.base_service),
                selectinload(ApprovalRequest.offered_slot),
            )
            .where(ApprovalRequest.status == ApprovalRequestStatus.PENDING)
            .order_by(ApprovalRequest.created_at.asc(), ApprovalRequest.id.asc())
        )
        return list(result.scalars().unique().all())

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        """Treat blank text values as missing when comparing duplicates."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    async def find_equivalent_pending(
        self,
        *,
        client_id: int,
        requested_text: str,
        kind: ApprovalRequestKind,
        base_service_id: int | None = None,
        addons: list[int] | None = None,
        design_photos: list[str] | None = None,
        design_comment: str | None = None,
        preferred_day: date | None = None,
        payment_method: str | None = None,
        related_booking_id: int | None = None,
        repair_nails_count: int | None = None,
        repair_issue_code: str | None = None,
        offered_start_at: datetime | None = None,
    ) -> ApprovalRequest | None:
        """Return an already pending approval with the exact same business payload."""
        normalized_addons = list(addons or [])
        normalized_photos = list(design_photos or [])
        normalized_comment = self._normalize_optional_text(design_comment)

        result = await self.session.execute(
            select(ApprovalRequest)
            .options(
                selectinload(ApprovalRequest.client),
                selectinload(ApprovalRequest.base_service),
                selectinload(ApprovalRequest.related_booking).selectinload(Booking.slot),
                selectinload(ApprovalRequest.related_booking).selectinload(Booking.base_service),
                selectinload(ApprovalRequest.offered_slot),
            )
            .where(
                ApprovalRequest.client_id == client_id,
                ApprovalRequest.status == ApprovalRequestStatus.PENDING,
                ApprovalRequest.kind == kind,
            )
            .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
        )
        candidates = list(result.scalars().unique().all())
        for approval in candidates:
            if approval.base_service_id != base_service_id:
                continue
            if list(approval.addons or []) != normalized_addons:
                continue
            if list(approval.design_photos or []) != normalized_photos:
                continue
            if self._normalize_optional_text(approval.design_comment) != normalized_comment:
                continue
            if approval.requested_text != requested_text:
                continue
            if approval.preferred_day != preferred_day:
                continue
            if approval.payment_method != payment_method:
                continue
            if approval.related_booking_id != related_booking_id:
                continue
            if approval.repair_nails_count != repair_nails_count:
                continue
            if approval.repair_issue_code != repair_issue_code:
                continue
            if approval.offered_start_at != offered_start_at:
                continue
            return approval
        return None

    async def create_or_reuse_pending(
        self,
        *,
        client_id: int,
        requested_text: str,
        kind: ApprovalRequestKind,
        base_service_id: int | None = None,
        addons: list[int] | None = None,
        design_photos: list[str] | None = None,
        design_comment: str | None = None,
        preferred_day: date | None = None,
        payment_method: str | None = None,
        related_booking_id: int | None = None,
        repair_nails_count: int | None = None,
        repair_issue_code: str | None = None,
        offered_start_at: datetime | None = None,
        status: ApprovalRequestStatus = ApprovalRequestStatus.PENDING,
    ) -> tuple[ApprovalRequest, bool]:
        """Create a new approval request or reuse an equivalent pending one."""
        if status == ApprovalRequestStatus.PENDING:
            existing = await self.find_equivalent_pending(
                client_id=client_id,
                requested_text=requested_text,
                kind=kind,
                base_service_id=base_service_id,
                addons=addons,
                design_photos=design_photos,
                design_comment=design_comment,
                preferred_day=preferred_day,
                payment_method=payment_method,
                related_booking_id=related_booking_id,
                repair_nails_count=repair_nails_count,
                repair_issue_code=repair_issue_code,
                offered_start_at=offered_start_at,
            )
            if existing is not None:
                return existing, False

        approval = ApprovalRequest(
            client_id=client_id,
            base_service_id=base_service_id,
            addons=addons or [],
            design_photos=design_photos or [],
            design_comment=design_comment,
            requested_text=requested_text,
            preferred_day=preferred_day,
            payment_method=payment_method,
            kind=kind,
            related_booking_id=related_booking_id,
            repair_nails_count=repair_nails_count,
            repair_issue_code=repair_issue_code,
            offered_start_at=offered_start_at,
            status=status,
        )
        self.session.add(approval)
        await self.session.flush()
        return approval, True

    async def create(
        self,
        *,
        client_id: int,
        requested_text: str,
        kind: ApprovalRequestKind,
        base_service_id: int | None = None,
        addons: list[int] | None = None,
        design_photos: list[str] | None = None,
        design_comment: str | None = None,
        preferred_day: date | None = None,
        payment_method: str | None = None,
        related_booking_id: int | None = None,
        repair_nails_count: int | None = None,
        repair_issue_code: str | None = None,
        offered_start_at: datetime | None = None,
        status: ApprovalRequestStatus = ApprovalRequestStatus.PENDING,
    ) -> ApprovalRequest:
        """Backward-compatible wrapper that returns the approval only."""
        approval, _created = await self.create_or_reuse_pending(
            client_id=client_id,
            requested_text=requested_text,
            kind=kind,
            base_service_id=base_service_id,
            addons=addons,
            design_photos=design_photos,
            design_comment=design_comment,
            preferred_day=preferred_day,
            payment_method=payment_method,
            related_booking_id=related_booking_id,
            repair_nails_count=repair_nails_count,
            repair_issue_code=repair_issue_code,
            offered_start_at=offered_start_at,
            status=status,
        )
        return approval

    async def update(self, approval: ApprovalRequest, **fields: object) -> ApprovalRequest:
        """Update editable approval-request fields."""
        for field_name, value in fields.items():
            setattr(approval, field_name, value)
        await self.session.flush()
        return approval
