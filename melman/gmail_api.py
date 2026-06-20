"""Gmail API backend. Mirrors mailbox.py's function signatures so cli.py can
dispatch on account.backend without caring which transport is used. Reuses the
Summary/Message dataclasses from mailbox so rendering is identical.

UIDs here are Gmail message IDs (hex strings), not IMAP sequence numbers."""

from __future__ import annotations

import base64
from email.message import EmailMessage

from .auth import load_credentials
from .config import Account
from .mailbox import Message, Summary


def _service(acc: Account):
    from googleapiclient.discovery import build

    creds = load_credentials(acc.token_path())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _summary_from_meta(msg: dict) -> Summary:
    headers = msg.get("payload", {}).get("headers", [])
    labels = msg.get("labelIds", [])
    return Summary(
        uid=msg["id"],
        from_=_header(headers, "From"),
        subject=_header(headers, "Subject"),
        date=_header(headers, "Date"),
        seen="UNREAD" not in labels,
    )


def _list(acc: Account, q: str | None, limit: int, label_ids: list[str] | None) -> list[Summary]:
    svc = _service(acc)
    kwargs = {"userId": "me", "maxResults": limit}
    if q:
        kwargs["q"] = q
    if label_ids:
        kwargs["labelIds"] = label_ids
    resp = svc.users().messages().list(**kwargs).execute()
    ids = [m["id"] for m in resp.get("messages", [])]
    out = []
    for mid in ids:
        meta = (
            svc.users()
            .messages()
            .get(
                userId="me",
                id=mid,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        out.append(_summary_from_meta(meta))
    return out


def list_inbox(acc: Account, limit: int = 20, mailbox: str = "INBOX") -> list[Summary]:
    label = mailbox.upper() if mailbox else "INBOX"
    return _list(acc, q=None, limit=limit, label_ids=[label])


def search(acc: Account, query: str, limit: int = 20, mailbox: str = "INBOX") -> list[Summary]:
    # Gmail search syntax (from:, subject:, has:attachment, etc.) passes through.
    return _list(acc, q=query, limit=limit, label_ids=None)


def read_message(acc: Account, uid: str, mailbox: str = "INBOX", mark_seen: bool = False) -> Message:
    svc = _service(acc)
    full = svc.users().messages().get(userId="me", id=uid, format="full").execute()
    headers = full.get("payload", {}).get("headers", [])
    body = _extract_body(full.get("payload", {}))
    if mark_seen:
        svc.users().messages().modify(
            userId="me", id=uid, body={"removeLabelIds": ["UNREAD"]}
        ).execute()
    return Message(
        uid=uid,
        from_=_header(headers, "From"),
        to=_header(headers, "To"),
        subject=_header(headers, "Subject"),
        date=_header(headers, "Date"),
        body=body,
    )


def _extract_body(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        return _decode_part(payload)
    if mime.startswith("multipart/"):
        parts = payload.get("parts", [])
        # Prefer text/plain anywhere in the tree.
        for p in parts:
            if p.get("mimeType") == "text/plain":
                return _decode_part(p)
        for p in parts:
            if p.get("mimeType", "").startswith("multipart/"):
                nested = _extract_body(p)
                if nested:
                    return nested
        for p in parts:
            if p.get("mimeType") == "text/html":
                return _decode_part(p)
    if mime == "text/html":
        return _decode_part(payload)
    return ""


def _decode_part(part: dict) -> str:
    data = part.get("body", {}).get("data")
    if not data:
        return ""
    raw = base64.urlsafe_b64decode(data.encode("ascii"))
    return raw.decode("utf-8", errors="replace")


def send_message(acc: Account, to: str, subject: str, body: str, cc: str | None = None) -> None:
    svc = _service(acc)
    msg = EmailMessage()
    msg["From"] = acc.email
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    svc.users().messages().send(userId="me", body={"raw": raw}).execute()
