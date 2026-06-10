from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    """Client onboarding states."""

    confirm_name = State()
    input_name = State()
    input_phone = State()


class Booking(StatesGroup):
    """Booking flow states from the specification."""

    choose_base_service = State()
    choose_addons = State()
    choose_payment = State()
    choose_day = State()
    choose_time = State()
    attach_reference = State()
    reference_input = State()
    confirm = State()


class AwaitCustomTime(StatesGroup):
    """Requesting custom date or time."""

    input_text = State()


class AskingMaster(StatesGroup):
    """Free-form question to the master."""

    input_message = State()


class ClientProxyReply(StatesGroup):
    """Client reply in an active proxy-chat thread."""

    input_message = State()


class PostBookingReference(StatesGroup):
    """Attaching reference photos after a booking is saved."""

    upload = State()


class PostvisitFeedback(StatesGroup):
    """Free-form feedback after a 3-4 star rating."""

    input_text = State()


class MyBookings(StatesGroup):
    """Managing an existing client booking."""

    input_cancel_other_reason = State()
    input_late_other_reason = State()


class RepairRequestFlow(StatesGroup):
    """Client warranty/repair request flow for a completed booking."""

    choose_issue = State()
    upload_photos = State()
    input_description = State()


class AdminReplying(StatesGroup):
    """Admin reply flow."""

    input_message = State()


class AdminSchedule(StatesGroup):
    """Admin schedule-management states."""

    input_text = State()
    preview = State()


class AdminScheduleMove(StatesGroup):
    """Admin flow for moving a free or blocked schedule slot."""

    input_text = State()


class AdminServiceCreate(StatesGroup):
    """Admin create-service flow."""

    input_name = State()
    input_price = State()
    input_duration = State()
    choose_kind = State()
    choose_price_variable = State()
    confirm = State()


class AdminServiceEdit(StatesGroup):
    """Admin edit-service flow."""

    input_value = State()


class AdminClients(StatesGroup):
    """Admin client search and note-edit flow."""

    input_query = State()
    input_note = State()


class AdminClientMessage(StatesGroup):
    """Admin direct message to a selected client."""

    input_message = State()


class AdminBookingCardReschedule(StatesGroup):
    """Admin move flow started from a booking card."""

    input_text = State()


class AdminBroadcast(StatesGroup):
    """Admin broadcast flow."""

    input_text = State()


class AdminTemplateEdit(StatesGroup):
    """Admin editable-template flow."""

    input_content = State()
    confirm_content = State()
    await_image = State()


class AdminSettingsEdit(StatesGroup):
    """Admin settings edit flow."""

    input_value = State()


class AdminCustomEmoji(StatesGroup):
    """Admin helper flow for extracting premium/custom emoji ids."""

    await_emoji = State()


class AdminButtonEdit(StatesGroup):
    """Admin flow for editing runtime button text, premium emoji and color."""

    input_text = State()
    await_emoji = State()
    input_url = State()


class AdminRepairOfferCustom(StatesGroup):
    """Admin flow for entering a custom off-schedule repair time."""

    input_text = State()


class AdminScheduleImage(StatesGroup):
    """Admin flow for the schedule-image editor (phase 10)."""

    await_background = State()


class AdminBackgroundUpload(StatesGroup):
    """Admin flow for shared image-background uploads."""

    await_photo = State()


class AdminForceMajeure(StatesGroup):
    """Admin flow for mass-cancelling bookings on a given day (force-majeure)."""

    choose_day = State()
    input_reason = State()
    confirm = State()


class AdminManualBooking(StatesGroup):
    """Admin flow for creating a booking on behalf of a client."""

    input_client = State()
    choose_service = State()
    choose_day = State()
    choose_time = State()
    confirm = State()
