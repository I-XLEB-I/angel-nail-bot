from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum, StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import BIGINT_PK, Base


def utcnow() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)


def enum_values(enum_class: type[Enum]) -> list[str]:
    """Return enum values for SQLAlchemy string-backed enums."""
    return [member.value for member in enum_class]  # type: ignore[return-value]


class ServiceKind(StrEnum):
    BASE = "base"
    ADDON = "addon"


class SlotStatus(StrEnum):
    FREE = "free"
    BOOKED = "booked"
    BLOCKED = "blocked"


class BookingStatus(StrEnum):
    PENDING_MASTER = "pending_master"
    CONFIRMED = "confirmed"
    CANCELLED_BY_CLIENT = "cancelled_by_client"
    CANCELLED_BY_MASTER = "cancelled_by_master"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class BookingCreatedVia(StrEnum):
    BOT = "bot"
    ADMIN_MANUAL = "admin_manual"
    UNKNOWN = "unknown"


class ApprovalRequestKind(StrEnum):
    NEW_BOOKING = "new_booking"
    RESCHEDULE = "reschedule"
    QUESTION = "question"
    FREQUENT_BOOKING = "frequent_booking"
    LATE_RESCHEDULE = "late_reschedule"
    MANUAL_APPROVAL_REQUIRED = "manual_approval_required"
    REPAIR_REQUEST = "repair_request"


class ApprovalRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    RESPONDED = "responded"
    OFFERED = "offered"  # admin offered a time slot; waiting for client confirmation


class LateArrivalNoticeStatus(StrEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    CLOSED = "closed"


service_kind_enum = SqlEnum(
    ServiceKind,
    name="service_kind",
    native_enum=False,
    values_callable=enum_values,
)

slot_status_enum = SqlEnum(
    SlotStatus,
    name="slot_status",
    native_enum=False,
    values_callable=enum_values,
)

booking_status_enum = SqlEnum(
    BookingStatus,
    name="booking_status",
    native_enum=False,
    values_callable=enum_values,
)

booking_created_via_enum = SqlEnum(
    BookingCreatedVia,
    name="booking_created_via",
    native_enum=False,
    values_callable=enum_values,
)

approval_kind_enum = SqlEnum(
    ApprovalRequestKind,
    name="approval_request_kind",
    native_enum=False,
    values_callable=enum_values,
)

approval_status_enum = SqlEnum(
    ApprovalRequestStatus,
    name="approval_request_status",
    native_enum=False,
    values_callable=enum_values,
)

late_arrival_notice_status_enum = SqlEnum(
    LateArrivalNoticeStatus,
    name="late_arrival_notice_status",
    native_enum=False,
    values_callable=enum_values,
)


class TimestampMixin:
    """Shared created/updated timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class User(TimestampMixin, Base):
    """Telegram user."""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BIGINT_PK, unique=True, nullable=False)
    tg_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_shadow_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    strikes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    requires_manual_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duplicate_phone_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    winback_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    repeat_prompt_snoozed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    preferred_days_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_time_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_length_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_shape_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_design_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    bookings: Mapped[list[Booking]] = relationship(back_populates="client")
    approval_requests: Mapped[list[ApprovalRequest]] = relationship(back_populates="client")
    late_arrival_notices: Mapped[list[LateArrivalNotice]] = relationship(
        back_populates="client"
    )
    rate_limit_events: Mapped[list[RateLimitEvent]] = relationship(back_populates="user")


class Service(Base):
    """Bookable service."""

    __tablename__ = "service"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    price_variable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[ServiceKind] = mapped_column(service_kind_enum, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)

    bookings: Mapped[list[Booking]] = relationship(back_populates="base_service")
    approval_requests: Mapped[list[ApprovalRequest]] = relationship(back_populates="base_service")


class Slot(Base):
    """Published booking slot."""

    __tablename__ = "slot"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        unique=True,
    )
    status: Mapped[SlotStatus] = mapped_column(
        slot_status_enum, nullable=False, default=SlotStatus.FREE
    )
    blocked_by_gcal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    bookings: Mapped[list[Booking]] = relationship(back_populates="slot")


class Booking(TimestampMixin, Base):
    """Client booking."""

    __tablename__ = "booking"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    slot_id: Mapped[int | None] = mapped_column(ForeignKey("slot.id"), nullable=True, index=True)
    base_service_id: Mapped[int] = mapped_column(ForeignKey("service.id"), nullable=False)
    addons: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    design_photos: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    design_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    fixed_price: Mapped[int] = mapped_column(Integer, nullable=False)
    has_variable_price: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_method: Mapped[str] = mapped_column(
        String(20), default="transfer", nullable=False
    )
    reschedules_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        booking_status_enum,
        nullable=False,
        default=BookingStatus.PENDING_MASTER,
        index=True,
    )
    created_via: Mapped[BookingCreatedVia] = mapped_column(
        booking_created_via_enum,
        nullable=False,
        default=BookingCreatedVia.UNKNOWN,
    )
    cancel_reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cancel_reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    gcal_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reminder_24h_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_24h_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_24h_unconfirmed_alert_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_2h_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_2h_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_2h_unconfirmed_alert_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    postvisit_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    repeat_prompt_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    force_majeure_notice_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    client: Mapped[User] = relationship(back_populates="bookings")
    slot: Mapped[Slot | None] = relationship(back_populates="bookings")
    base_service: Mapped[Service] = relationship(back_populates="bookings")
    approval_requests: Mapped[list[ApprovalRequest]] = relationship(
        back_populates="related_booking"
    )
    late_arrival_notices: Mapped[list[LateArrivalNotice]] = relationship(
        back_populates="booking"
    )


class ApprovalRequest(Base):
    """Request that requires manual admin approval."""

    __tablename__ = "approval_request"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    base_service_id: Mapped[int | None] = mapped_column(ForeignKey("service.id"), nullable=True)
    addons: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    design_photos: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    design_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_text: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    kind: Mapped[ApprovalRequestKind] = mapped_column(approval_kind_enum, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    related_booking_id: Mapped[int | None] = mapped_column(ForeignKey("booking.id"), nullable=True)
    repair_nails_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repair_issue_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[ApprovalRequestStatus] = mapped_column(
        approval_status_enum,
        nullable=False,
        default=ApprovalRequestStatus.PENDING,
        index=True,
    )
    admin_response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_tg_msg_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    offered_slot_id: Mapped[int | None] = mapped_column(
        ForeignKey("slot.id"), nullable=True
    )
    offered_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client: Mapped[User] = relationship(back_populates="approval_requests")
    base_service: Mapped[Service | None] = relationship(back_populates="approval_requests")
    related_booking: Mapped[Booking | None] = relationship(back_populates="approval_requests")
    offered_slot: Mapped[Slot | None] = relationship(foreign_keys=[offered_slot_id])


class LateArrivalNotice(Base):
    """Client-reported delay bound to one concrete booking."""

    __tablename__ = "late_arrival_notice"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("booking.id"), nullable=False, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[LateArrivalNoticeStatus] = mapped_column(
        late_arrival_notice_status_enum,
        nullable=False,
        default=LateArrivalNoticeStatus.ACTIVE,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    booking: Mapped[Booking] = relationship(back_populates="late_arrival_notices")
    client: Mapped[User] = relationship(back_populates="late_arrival_notices")


class RateLimitEvent(Base):
    """Low-level anti-abuse and throttling audit events."""

    __tablename__ = "rate_limit_events"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
        index=True,
    )

    user: Mapped[User] = relationship(back_populates="rate_limit_events")


class Template(Base):
    """Editable text template."""

    __tablename__ = "template"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class Setting(Base):
    """Key-value application setting."""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class SystemAlertEvent(Base):
    """Persisted deduplicated system alerts for critical operational failures."""

    __tablename__ = "system_alert_event"
    __table_args__ = (
        UniqueConstraint(
            "kind",
            "signature",
            name="uq_system_alert_event_kind_signature",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    signature: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    repeat_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class SystemJobStatus(Base):
    """Operational health snapshot for one recurring background job."""

    __tablename__ = "system_job_status"

    job_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_succeeded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class ReminderAdminAlertDelivery(Base):
    """One admin-side reminder alert message that can later be updated in place."""

    __tablename__ = "reminder_admin_alert_delivery"
    __table_args__ = (
        UniqueConstraint(
            "booking_id",
            "admin_tg_id",
            "reminder_kind",
            name="uq_reminder_admin_alert_delivery_booking_admin_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("booking.id"), nullable=False, index=True)
    admin_tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    reminder_kind: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class MorningSummaryDelivery(Base):
    """One admin-side morning summary message that can be updated live."""

    __tablename__ = "morning_summary_delivery"
    __table_args__ = (
        UniqueConstraint(
            "admin_tg_id",
            name="uq_morning_summary_delivery_admin_tg_id",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    admin_tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    summary_local_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


JsonList = list[int] | list[str] | list[Any]

__all__ = [
    "ApprovalRequest",
    "ApprovalRequestKind",
    "ApprovalRequestStatus",
    "Booking",
    "BookingStatus",
    "LateArrivalNotice",
    "LateArrivalNoticeStatus",
    "MorningSummaryDelivery",
    "Service",
    "ServiceKind",
    "Setting",
    "Slot",
    "SlotStatus",
    "ReminderAdminAlertDelivery",
    "SystemAlertEvent",
    "SystemJobStatus",
    "Template",
    "User",
]
