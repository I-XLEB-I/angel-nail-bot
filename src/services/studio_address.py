from __future__ import annotations

from src.db.repositories.settings import SettingRepository

STUDIO_ADDRESS_COPY_SETTING_KEY = "studio_address_copy_text"
DEFAULT_STUDIO_ADDRESS_COPY_TEXT = "Очаковское шоссе, 5к3, подъезд 2"


async def load_studio_address_copy_text(repository: SettingRepository) -> str:
    """Return the short address shared by all copy-address buttons."""
    return await repository.get_value_or_default(
        STUDIO_ADDRESS_COPY_SETTING_KEY,
        DEFAULT_STUDIO_ADDRESS_COPY_TEXT,
    )
