from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(default="", alias="BOT_TOKEN")
    admin_tg_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list,
        alias="ADMIN_TG_IDS",
    )
    tz: str = Field(default="Europe/Moscow", alias="TZ")

    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/bot.db",
        alias="DATABASE_URL",
    )

    gcal_enabled: bool = Field(default=False, alias="GCAL_ENABLED")
    gcal_calendar_id: str = Field(default="", alias="GCAL_CALENDAR_ID")
    gcal_credentials_path: Path = Field(
        default=Path("./secrets/gcal_service_account.json"),
        alias="GCAL_CREDENTIALS_PATH",
    )
    google_service_account_path: Path = Field(
        default=Path("./secrets/google_service_account.json"),
        alias="GOOGLE_SERVICE_ACCOUNT_PATH",
    )
    google_oauth_client_path: Path = Field(
        default=Path("./secrets/google_oauth_client.json"),
        alias="GOOGLE_OAUTH_CLIENT_PATH",
    )
    google_oauth_token_path: Path = Field(
        default=Path("./secrets/google_oauth_token.json"),
        alias="GOOGLE_OAUTH_TOKEN_PATH",
    )
    gsheets_spreadsheet_id: str = Field(default="", alias="GSHEETS_SPREADSHEET_ID")
    gdrive_folder_id: str = Field(default="", alias="GDRIVE_FOLDER_ID")

    portfolio_channel_url: str = Field(
        default="https://t.me/angelsnailspace",
        alias="PORTFOLIO_CHANNEL_URL",
    )

    feature_repeat_prompt: bool = Field(default=True, alias="FEATURE_REPEAT_PROMPT")
    feature_postvisit_feedback: bool = Field(
        default=True,
        alias="FEATURE_POSTVISIT_FEEDBACK",
    )
    feature_reminder_2h: bool = Field(default=True, alias="FEATURE_REMINDER_2H")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    debug_commands: bool = Field(default=False, alias="DEBUG_COMMANDS")

    @field_validator("admin_tg_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: str | list[int] | None) -> list[int]:
        """Parse Telegram user ids from comma-separated or JSON-list env values."""
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return value
        stripped_value = value.strip()
        if stripped_value.startswith("["):
            return [int(item) for item in json.loads(stripped_value)]
        return [int(item.strip()) for item in stripped_value.split(",") if item.strip()]

    @property
    def admin_tg_id_set(self) -> set[int]:
        """Return admin ids as a set for fast membership checks."""
        return set(self.admin_tg_ids)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
