from __future__ import annotations

from src.config import Settings
from src.db.repositories.settings import SettingRepository

TRUE_VALUES = {"1", "true", "yes", "on", "y", "да"}


async def get_str_setting(
    repository: SettingRepository,
    *,
    key: str,
    default: str,
) -> str:
    """Return a string setting with a fallback."""
    value = await repository.get_value(key)
    return value if value not in {None, ""} else default


async def get_bool_setting(
    repository: SettingRepository,
    *,
    key: str,
    default: bool,
) -> bool:
    """Return a boolean setting with a tolerant parser."""
    value = await repository.get_value(key)
    if value is None:
        return default
    return value.strip().lower() in TRUE_VALUES


async def get_int_setting(
    repository: SettingRepository,
    *,
    key: str,
    default: int,
) -> int:
    """Return an integer setting with a fallback for invalid values."""
    value = await repository.get_value(key)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


async def get_runtime_tz(
    repository: SettingRepository,
    *,
    settings: Settings,
) -> str:
    """Return the currently configured timezone."""
    return await get_str_setting(repository, key="tz", default=settings.tz)
