from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Booking, BookingStatus, Slot, User


class UserRepository:
    """Repository for user records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        """Return a user by its primary key."""
        return await self.session.get(User, user_id)

    async def get_by_tg_id(self, tg_id: int) -> User | None:
        """Return a user by Telegram id."""
        result = await self.session.execute(select(User).where(User.tg_id == tg_id))
        return result.scalar_one_or_none()

    async def find_by_phone(
        self,
        phone: str,
        *,
        exclude_user_id: int | None = None,
    ) -> User | None:
        """Return another user with the same phone number."""
        query = select(User).where(User.phone == phone)
        if exclude_user_id is not None:
            query = query.where(User.id != exclude_user_id)
        result = await self.session.execute(query.order_by(User.id))
        return result.scalar_one_or_none()

    async def upsert_from_telegram(
        self,
        *,
        tg_id: int,
        username: str | None,
        first_name: str | None,
        is_admin: bool,
    ) -> User:
        """Create or update a user from Telegram metadata.

        Concurrent updates from the same Telegram user can race: aiogram dispatches
        events in parallel, and a sibling middleware-session may have opened its
        read snapshot before the first one committed the new row. The first call
        sees ``get_by_tg_id == None`` and inserts; the second call also sees None
        (stale snapshot) and then fails the INSERT with UNIQUE constraint on tg_id.

        We treat that exact race as "someone else just inserted us" — rollback
        and re-fetch on the now-fresh transaction.
        """
        user = await self.get_by_tg_id(tg_id)
        if user is None:
            # DECISION: `display_name` is non-null in the schema, so before onboarding
            # confirms it we keep Telegram `first_name` as a temporary placeholder.
            user = User(
                tg_id=tg_id,
                tg_username=username,
                display_name=(first_name or "Клиент").strip()[:255] or "Клиент",
                is_admin=is_admin,
            )
            self.session.add(user)
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                user = await self.get_by_tg_id(tg_id)
                if user is None:
                    raise  # truly unexpected — re-raise original error
                # fall through to the "existing user" update path below
            else:
                return user

        if username is not None:
            user.tg_username = username
        user.is_admin = is_admin
        await self.session.flush()
        return user

    async def update_profile(
        self,
        user: User,
        *,
        display_name: str | None = None,
        phone: str | None = None,
        note: str | None = None,
        repeat_prompt_snoozed_until=None,
        preferred_days_note: str | None = None,
        preferred_time_note: str | None = None,
        preferred_length_note: str | None = None,
        preferred_shape_note: str | None = None,
        preferred_design_note: str | None = None,
    ) -> User:
        """Update editable user profile fields."""
        if display_name is not None:
            user.display_name = display_name
        if phone is not None:
            user.phone = phone
        if note is not None:
            user.note = note
        if repeat_prompt_snoozed_until is not None:
            user.repeat_prompt_snoozed_until = repeat_prompt_snoozed_until
        if preferred_days_note is not None:
            user.preferred_days_note = preferred_days_note
        if preferred_time_note is not None:
            user.preferred_time_note = preferred_time_note
        if preferred_length_note is not None:
            user.preferred_length_note = preferred_length_note
        if preferred_shape_note is not None:
            user.preferred_shape_note = preferred_shape_note
        if preferred_design_note is not None:
            user.preferred_design_note = preferred_design_note
        await self.session.flush()
        return user

    async def search_clients(self, query: str, *, limit: int = 10) -> list[User]:
        """Search non-admin users by display name or Telegram username."""
        normalized = query.strip().lstrip("@").casefold()
        if not normalized:
            return []

        result = await self.session.execute(
            select(User).where(User.is_admin.is_(False)).order_by(User.display_name, User.id)
        )
        matches = [
            user
            for user in result.scalars().all()
            if normalized in (user.display_name or "").casefold()
            or normalized in (user.tg_username or "").casefold()
        ]
        return matches[:limit]

    async def count_clients(self) -> int:
        """Return the total number of non-admin users."""
        result = await self.session.execute(
            select(func.count(User.id)).where(User.is_admin.is_(False))
        )
        return int(result.scalar_one() or 0)

    async def list_clients(
        self,
        *,
        limit: int = 8,
        offset: int = 0,
    ) -> list[User]:
        """Return one page of non-admin users ordered alphabetically."""
        result = await self.session.execute(
            select(User)
            .where(User.is_admin.is_(False))
            .order_by(func.lower(User.display_name), User.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_broadcast_recipients(self) -> list[User]:
        """Return active clients with at least one real booking for broadcasts."""
        result = await self.session.execute(
            select(User)
            .join(Booking, Booking.client_id == User.id)
            .where(
                User.is_admin.is_(False),
                User.is_blocked.is_(False),
                Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.COMPLETED]),
            )
            .group_by(User.id)
            .order_by(User.id)
        )
        return list(result.scalars().all())

    async def list_rescue_offer_candidates(
        self,
        *,
        min_completed_visits: int,
        limit: int = 6,
        exclude_user_ids: set[int] | None = None,
    ) -> list[User]:
        """Return loyal clients who can receive a last-minute free-slot offer."""
        excluded_ids = exclude_user_ids or set()
        completed_result = await self.session.execute(
            select(User.id, func.max(Slot.start_at))
            .join(Booking, Booking.client_id == User.id)
            .join(Slot, Slot.id == Booking.slot_id)
            .where(
                User.is_admin.is_(False),
                User.is_blocked.is_(False),
                User.is_shadow_banned.is_(False),
                Booking.status == BookingStatus.COMPLETED,
            )
            .group_by(User.id)
            .having(func.count(Booking.id) >= min_completed_visits)
            .order_by(func.max(Slot.start_at).desc(), User.id)
        )
        candidate_ids = [
            int(user_id)
            for user_id, _last_completed_at in completed_result.all()
            if int(user_id) not in excluded_ids
        ]
        if not candidate_ids:
            return []

        active_result = await self.session.execute(
            select(Booking.client_id)
            .where(
                Booking.client_id.in_(candidate_ids),
                Booking.status.in_([BookingStatus.PENDING_MASTER, BookingStatus.CONFIRMED]),
            )
            .group_by(Booking.client_id)
        )
        active_client_ids = {int(user_id) for user_id in active_result.scalars().all()}
        final_ids = [user_id for user_id in candidate_ids if user_id not in active_client_ids][:limit]
        if not final_ids:
            return []

        users_result = await self.session.execute(select(User).where(User.id.in_(final_ids)))
        users_by_id = {user.id: user for user in users_result.scalars().all()}
        return [users_by_id[user_id] for user_id in final_ids if user_id in users_by_id]
