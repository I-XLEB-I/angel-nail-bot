from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.config import Settings
from src.services.google_drive import (
    build_design_photo_folder_segments,
    upload_bytes_file,
)


@dataclass(slots=True)
class UploadedDesignPhoto:
    """Metadata for a design photo uploaded to Google Drive."""

    file_name: str
    file_id: str
    web_view_link: str
    folder_segments: list[str]


def upload_design_photo(
    settings: Settings,
    *,
    tg_id: int,
    file_name: str,
    content: bytes,
    mime_type: str,
    uploaded_at: datetime,
) -> UploadedDesignPhoto:
    """Upload a design photo into a date-based Drive folder structure."""
    folder_segments = build_design_photo_folder_segments(
        settings,
        uploaded_at=uploaded_at,
        tg_id=tg_id,
    )
    drive_file = upload_bytes_file(
        settings,
        file_name=file_name,
        content=content,
        mime_type=mime_type,
        folder_segments=folder_segments,
    )
    return UploadedDesignPhoto(
        file_name=drive_file.get("name", file_name),
        file_id=drive_file.get("id", ""),
        web_view_link=drive_file.get("webViewLink", ""),
        folder_segments=folder_segments,
    )
