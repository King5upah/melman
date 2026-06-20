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


def search_ids(acc: Account, query: str, max_results: int = 2000) -> list[str]:
    """Return message IDs matching a Gmail query, paging until max_results."""
    svc = _service(acc)
    ids: list[str] = []
    page = None
    while len(ids) < max_results:
        resp = (
            svc.users()
            .messages()
            .list(userId="me", q=query, maxResults=500, pageToken=page)
            .execute()
        )
        ids.extend(m["id"] for m in resp.get("messages", []))
        page = resp.get("nextPageToken")
        if not page:
            break
    return ids[:max_results]


def fetch_meta(acc: Account, uid: str) -> Summary:
    """One message's header summary (From/Subject/Date + unread flag)."""
    svc = _service(acc)
    meta = (
        svc.users()
        .messages()
        .get(
            userId="me",
            id=uid,
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        )
        .execute()
    )
    return _summary_from_meta(meta)


def get_or_create_label(acc: Account, name: str) -> str:
    """Return the label ID for `name`, creating it if missing."""
    svc = _service(acc)
    existing = svc.users().labels().list(userId="me").execute().get("labels", [])
    for lab in existing:
        if lab["name"].lower() == name.lower():
            return lab["id"]
    created = (
        svc.users()
        .labels()
        .create(
            userId="me",
            body={
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        .execute()
    )
    return created["id"]


def batch_modify(
    acc: Account,
    ids: list[str],
    add: list[str] | None = None,
    remove: list[str] | None = None,
) -> int:
    """Bulk add/remove labels on up to thousands of messages (1000 per API call)."""
    if not ids:
        return 0
    svc = _service(acc)
    body = {}
    if add:
        body["addLabelIds"] = add
    if remove:
        body["removeLabelIds"] = remove
    done = 0
    for i in range(0, len(ids), 1000):
        chunk = ids[i : i + 1000]
        svc.users().messages().batchModify(userId="me", body={"ids": chunk, **body}).execute()
        done += len(chunk)
    return done


def unsubscribe_info(acc: Account, uid: str) -> dict:
    """Read RFC-2369 List-Unsubscribe headers for one message. Returns the sender,
    any https/mailto unsubscribe targets, and whether RFC-8058 one-click is offered."""
    import re

    svc = _service(acc)
    meta = (
        svc.users()
        .messages()
        .get(
            userId="me",
            id=uid,
            format="metadata",
            metadataHeaders=["From", "List-Unsubscribe", "List-Unsubscribe-Post"],
        )
        .execute()
    )
    headers = meta.get("payload", {}).get("headers", [])
    raw = _header(headers, "List-Unsubscribe")
    post = _header(headers, "List-Unsubscribe-Post")
    targets = re.findall(r"<([^>]+)>", raw)
    https = [t for t in targets if t.lower().startswith("http")]
    mailto = [t for t in targets if t.lower().startswith("mailto:")]
    return {
        "uid": uid,
        "from": _header(headers, "From"),
        "https": https,
        "mailto": mailto,
        "one_click": "one-click" in post.lower() and bool(https),
        "has_target": bool(https or mailto),
    }


def unsubscribe_one_click(url: str) -> int:
    """RFC-8058 one-click: POST the unsubscribe body to the https target. Returns
    the HTTP status code. No auth/cookies — these endpoints are token-keyed."""
    import urllib.request

    data = b"List-Unsubscribe=One-Click"
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status


def trash_message(acc: Account, uid: str) -> None:
    """Move a message to Trash (recoverable for 30 days)."""
    svc = _service(acc)
    svc.users().messages().trash(userId="me", id=uid).execute()


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
