"""Database repositories."""

from src.db.repositories.approvals import ApprovalRequestRepository
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.services import ServiceRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.slots import SlotRepository
from src.db.repositories.templates import TemplateRepository
from src.db.repositories.users import UserRepository

__all__ = [
    "ApprovalRequestRepository",
    "BookingRepository",
    "ServiceRepository",
    "SettingRepository",
    "SlotRepository",
    "TemplateRepository",
    "UserRepository",
]
