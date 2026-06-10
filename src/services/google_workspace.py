from __future__ import annotations

from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config import Settings

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"


def build_service_account_credentials(
    credentials_path: Path,
    *,
    scopes: list[str],
) -> Credentials:
    """Create service-account credentials for the requested Google scopes."""
    resolved_path = credentials_path.expanduser().resolve()
    return Credentials.from_service_account_file(str(resolved_path), scopes=scopes)


def build_sheets_service(settings: Settings) -> Any:
    """Return an authenticated Google Sheets API client."""
    credentials = build_service_account_credentials(
        settings.google_service_account_path,
        scopes=[SHEETS_SCOPE],
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def build_calendar_service(settings: Settings) -> Any:
    """Return an authenticated Google Calendar API client."""
    credentials = build_service_account_credentials(
        settings.gcal_credentials_path,
        scopes=[CALENDAR_SCOPE],
    )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def build_drive_oauth_credentials(settings: Settings) -> UserCredentials:
    """Return OAuth credentials for Google Drive, refreshing or creating them as needed."""
    token_path = settings.google_oauth_token_path.expanduser().resolve()
    client_path = settings.google_oauth_client_path.expanduser().resolve()

    credentials: UserCredentials | None = None
    if token_path.exists():
        credentials = UserCredentials.from_authorized_user_file(
            str(token_path),
            scopes=[DRIVE_SCOPE],
        )

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_path.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    if not client_path.exists():
        raise RuntimeError(
            "Google Drive OAuth client JSON not found. "
            "Place it at GOOGLE_OAUTH_CLIENT_PATH and run scripts/init_drive_oauth.py."
        )

    raise RuntimeError(
        "Google Drive OAuth token not found or expired without refresh token. "
        "Run scripts/init_drive_oauth.py to authorize Drive access."
    )


def run_drive_oauth_flow(settings: Settings) -> Path:
    """Run the interactive OAuth flow for Drive and save the resulting token."""
    client_path = settings.google_oauth_client_path.expanduser().resolve()
    token_path = settings.google_oauth_token_path.expanduser().resolve()

    if not client_path.exists():
        raise RuntimeError(
            "Google OAuth client JSON not found. "
            "Place it at GOOGLE_OAUTH_CLIENT_PATH before authorizing."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_path),
        scopes=[DRIVE_SCOPE],
    )
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        open_browser=True,
    )
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return token_path


def build_drive_service(settings: Settings) -> Any:
    """Return an authenticated Google Drive API client."""
    credentials = build_drive_oauth_credentials(settings)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)
