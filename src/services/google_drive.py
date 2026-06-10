from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from googleapiclient.http import MediaIoBaseUpload

from src.config import Settings
from src.services.google_workspace import build_drive_service

DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


def sanitize_drive_name(value: str) -> str:
    """Return a Drive-safe file or folder name."""
    sanitized = (
        value.replace("/", "_").replace("\\", "_").replace("\n", " ").replace("\r", " ").strip()
    )
    return sanitized or "untitled"


def build_design_photo_folder_segments(
    settings: Settings,
    *,
    uploaded_at: datetime,
    tg_id: int,
) -> list[str]:
    """Return nested folder segments for design photos."""
    local_dt = uploaded_at.astimezone(ZoneInfo(settings.tz))
    return [
        "design-photos",
        local_dt.strftime("%Y"),
        local_dt.strftime("%m"),
        str(tg_id),
    ]


def _escape_drive_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def ensure_drive_folder_path(
    settings: Settings,
    *,
    folder_segments: list[str],
) -> str:
    """Ensure a nested folder path exists under the configured root folder."""
    service = build_drive_service(settings)
    parent_id = settings.gdrive_folder_id

    for segment in folder_segments:
        folder_name = sanitize_drive_name(segment)
        query = (
            f"'{parent_id}' in parents and "
            f"name = '{_escape_drive_query_value(folder_name)}' and "
            f"mimeType = '{DRIVE_FOLDER_MIME_TYPE}' and trashed = false"
        )
        response = (
            service.files()
            .list(
                q=query,
                fields="files(id,name)",
                pageSize=1,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            )
            .execute()
        )
        files = response.get("files", [])
        if files:
            parent_id = files[0]["id"]
            continue

        created_folder = (
            service.files()
            .create(
                body={
                    "name": folder_name,
                    "mimeType": DRIVE_FOLDER_MIME_TYPE,
                    "parents": [parent_id],
                },
                fields="id,name",
                supportsAllDrives=True,
            )
            .execute()
        )
        parent_id = created_folder["id"]

    return parent_id


def upload_bytes_file(
    settings: Settings,
    *,
    file_name: str,
    content: bytes,
    mime_type: str,
    folder_segments: list[str] | None = None,
) -> dict[str, Any]:
    """Upload an in-memory file to the configured Google Drive folder."""
    service = build_drive_service(settings)
    media = MediaIoBaseUpload(BytesIO(content), mimetype=mime_type, resumable=False)
    parent_folder_id = settings.gdrive_folder_id
    if folder_segments:
        parent_folder_id = ensure_drive_folder_path(
            settings,
            folder_segments=folder_segments,
        )

    return (
        service.files()
        .create(
            body={
                "name": sanitize_drive_name(file_name),
                "parents": [parent_folder_id],
            },
            media_body=media,
            fields="id,name,mimeType,webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )
