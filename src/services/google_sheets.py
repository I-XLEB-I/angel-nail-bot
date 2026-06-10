from __future__ import annotations

from typing import Any

from src.config import Settings
from src.services.google_workspace import build_sheets_service


def get_spreadsheet_metadata(settings: Settings) -> dict[str, Any]:
    """Return spreadsheet metadata for the configured Google Sheet."""
    service = build_sheets_service(settings)
    return service.spreadsheets().get(spreadsheetId=settings.gsheets_spreadsheet_id).execute()


def ensure_sheet_tab(
    settings: Settings,
    *,
    title: str,
    headers: list[str] | None = None,
) -> str:
    """Ensure the spreadsheet contains a worksheet with the given title."""
    service = build_sheets_service(settings)
    metadata = get_spreadsheet_metadata(settings)
    existing_titles = {
        sheet["properties"]["title"]
        for sheet in metadata.get("sheets", [])
        if "properties" in sheet and "title" in sheet["properties"]
    }

    if title not in existing_titles:
        service.spreadsheets().batchUpdate(
            spreadsheetId=settings.gsheets_spreadsheet_id,
            body={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": title,
                            }
                        }
                    }
                ]
            },
        ).execute()

    if headers:
        header_range = f"'{title}'!1:1"
        existing_header_row = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=settings.gsheets_spreadsheet_id,
                range=header_range,
            )
            .execute()
        )
        if not existing_header_row.get("values"):
            service.spreadsheets().values().update(
                spreadsheetId=settings.gsheets_spreadsheet_id,
                range=f"'{title}'!A1",
                valueInputOption="RAW",
                body={"values": [headers]},
            ).execute()

    return title


def append_row(
    settings: Settings,
    *,
    sheet_title: str,
    values: list[str],
) -> dict[str, Any]:
    """Append a single row to the configured Google Sheet."""
    service = build_sheets_service(settings)
    return (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=settings.gsheets_spreadsheet_id,
            range=f"'{sheet_title}'!A:Z",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [values]},
        )
        .execute()
    )
