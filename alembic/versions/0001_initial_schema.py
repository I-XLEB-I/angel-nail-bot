"""Initial schema for phase 1."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk_type = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

    service_kind = sa.Enum("base", "addon", name="service_kind", native_enum=False)
    slot_status = sa.Enum("free", "booked", "blocked", name="slot_status", native_enum=False)
    booking_status = sa.Enum(
        "pending_master",
        "confirmed",
        "cancelled_by_client",
        "cancelled_by_master",
        "completed",
        "no_show",
        name="booking_status",
        native_enum=False,
    )
    approval_kind = sa.Enum(
        "new_booking",
        "reschedule",
        "question",
        name="approval_request_kind",
        native_enum=False,
    )
    approval_status = sa.Enum(
        "pending",
        "approved",
        "declined",
        "responded",
        name="approval_request_status",
        native_enum=False,
    )

    op.create_table(
        "user",
        sa.Column("id", pk_type, primary_key=True),
        sa.Column("tg_id", pk_type, nullable=False),
        sa.Column("tg_username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tg_id"),
    )

    op.create_table(
        "service",
        sa.Column("id", pk_type, primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("price_variable", sa.Boolean(), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("kind", service_kind, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
    )

    op.create_table(
        "slot",
        sa.Column("id", pk_type, primary_key=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", slot_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("start_at"),
    )

    op.create_table(
        "template",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "setting",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )

    op.create_table(
        "booking",
        sa.Column("id", pk_type, primary_key=True),
        sa.Column("client_id", pk_type, sa.ForeignKey("user.id"), nullable=False),
        sa.Column("slot_id", pk_type, sa.ForeignKey("slot.id"), nullable=True),
        sa.Column("base_service_id", pk_type, sa.ForeignKey("service.id"), nullable=False),
        sa.Column("addons", sa.JSON(), nullable=False),
        sa.Column("design_photos", sa.JSON(), nullable=False),
        sa.Column("design_comment", sa.Text(), nullable=True),
        sa.Column("fixed_price", sa.Integer(), nullable=False),
        sa.Column("has_variable_price", sa.Boolean(), nullable=False),
        sa.Column("status", booking_status, nullable=False),
        sa.Column("cancel_reason_code", sa.String(length=50), nullable=True),
        sa.Column("cancel_reason_text", sa.Text(), nullable=True),
        sa.Column("gcal_event_id", sa.String(length=255), nullable=True),
        sa.Column("reminder_24h_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_2h_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("postvisit_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("repeat_prompt_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_booking_client_id"), "booking", ["client_id"], unique=False)
    op.create_index(op.f("ix_booking_slot_id"), "booking", ["slot_id"], unique=False)
    op.create_index(op.f("ix_booking_status"), "booking", ["status"], unique=False)

    op.create_table(
        "approval_request",
        sa.Column("id", pk_type, primary_key=True),
        sa.Column("client_id", pk_type, sa.ForeignKey("user.id"), nullable=False),
        sa.Column("base_service_id", pk_type, sa.ForeignKey("service.id"), nullable=True),
        sa.Column("addons", sa.JSON(), nullable=False),
        sa.Column("design_photos", sa.JSON(), nullable=False),
        sa.Column("design_comment", sa.Text(), nullable=True),
        sa.Column("requested_text", sa.Text(), nullable=False),
        sa.Column("preferred_day", sa.Date(), nullable=True),
        sa.Column("kind", approval_kind, nullable=False),
        sa.Column("related_booking_id", pk_type, sa.ForeignKey("booking.id"), nullable=True),
        sa.Column("status", approval_status, nullable=False),
        sa.Column("admin_response_text", sa.Text(), nullable=True),
        sa.Column("admin_tg_msg_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_approval_request_client_id"),
        "approval_request",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_approval_request_status"),
        "approval_request",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_approval_request_status"), table_name="approval_request")
    op.drop_index(op.f("ix_approval_request_client_id"), table_name="approval_request")
    op.drop_table("approval_request")

    op.drop_index(op.f("ix_booking_status"), table_name="booking")
    op.drop_index(op.f("ix_booking_slot_id"), table_name="booking")
    op.drop_index(op.f("ix_booking_client_id"), table_name="booking")
    op.drop_table("booking")

    op.drop_table("setting")
    op.drop_table("template")

    op.drop_table("slot")

    op.drop_table("service")

    op.drop_table("user")
