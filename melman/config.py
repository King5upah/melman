"""Account config. Non-secret settings live in a JSON file under the user config
dir; the App Password lives in the OS keyring (Windows Credential Manager), never
on disk in plaintext."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import keyring

KEYRING_SERVICE = "melman"

# Gmail defaults. Override per-account for other providers.
GMAIL_IMAP = ("imap.gmail.com", 993)
GMAIL_SMTP = ("smtp.gmail.com", 465)


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    d = Path(base) / "melman"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "accounts.json"


@dataclass
class Account:
    email: str
    imap_host: str = GMAIL_IMAP[0]
    imap_port: int = GMAIL_IMAP[1]
    smtp_host: str = GMAIL_SMTP[0]
    smtp_port: int = GMAIL_SMTP[1]

    def password(self) -> str | None:
        return keyring.get_password(KEYRING_SERVICE, self.email)

    def set_password(self, pw: str) -> None:
        keyring.set_password(KEYRING_SERVICE, self.email, pw)


def load_accounts() -> dict[str, Account]:
    p = config_path()
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {e: Account(**a) for e, a in raw.items()}


def save_account(acc: Account) -> None:
    accounts = load_accounts()
    accounts[acc.email] = acc
    data = {e: asdict(a) for e, a in accounts.items()}
    config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def default_account() -> Account | None:
    accounts = load_accounts()
    if not accounts:
        return None
    # MAILCLI_ACCOUNT env override, else first configured.
    want = os.environ.get("MAILCLI_ACCOUNT")
    if want and want in accounts:
        return accounts[want]
    return next(iter(accounts.values()))
