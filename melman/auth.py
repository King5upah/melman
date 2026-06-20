"""OAuth2 for the Gmail API backend. Opens the browser for consent, captures the
token on a localhost redirect, and stores it (with its refresh_token) in the
config dir — never in the repo. google-* deps are imported lazily so the IMAP
backend works without them installed."""

from __future__ import annotations

from pathlib import Path

# Read + modify (labels, mark read) + send + manage filters/labels settings.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]


def _require_google():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError(
            "Gmail backend needs extra deps. Install with:\n"
            "    pip install -e .[gmail]"
        ) from e
    return Request, Credentials, InstalledAppFlow


def authorize(credentials_path: str, token_path: Path):
    """Run the install-app OAuth flow (or refresh an existing token) and persist
    the result. Returns valid google credentials."""
    Request, Credentials, InstalledAppFlow = _require_google()

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        cp = Path(credentials_path)
        if not cp.exists():
            raise RuntimeError(
                f"credentials.json not found at {cp}. Download an OAuth 'Desktop "
                "app' client from Google Cloud Console (Gmail API enabled)."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(cp), SCOPES)
        # Opens the browser; serves a one-shot localhost handler to catch the code.
        creds = flow.run_local_server(port=0, prompt="consent")

    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def load_credentials(token_path: Path):
    """Load + refresh stored creds for normal API calls. Raises if not authorized."""
    Request, Credentials, _ = _require_google()
    if not token_path.exists():
        raise RuntimeError("Not authorized. Run `melman auth` first.")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError("Token invalid. Re-run `melman auth`.")
    return creds
