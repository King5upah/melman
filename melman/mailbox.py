"""IMAP read + SMTP send. Thin functional layer over stdlib so both the human
CLI and the agent JSON interface call the same code."""

from __future__ import annotations

import email
import imaplib
import smtplib
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr

from .config import Account


@dataclass
class Summary:
    uid: str
    from_: str
    subject: str
    date: str
    seen: bool

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "from": self.from_,
            "subject": self.subject,
            "date": self.date,
            "seen": self.seen,
        }


@dataclass
class Message:
    uid: str
    from_: str
    to: str
    subject: str
    date: str
    body: str

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "from": self.from_,
            "to": self.to,
            "subject": self.subject,
            "date": self.date,
            "body": self.body,
        }


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


class _IMAP:
    """Context manager that logs in, selects a mailbox, logs out."""

    def __init__(self, acc: Account, mailbox: str = "INBOX", readonly: bool = True):
        self.acc = acc
        self.mailbox = mailbox
        self.readonly = readonly
        self.conn: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> imaplib.IMAP4_SSL:
        pw = self.acc.password()
        if not pw:
            raise RuntimeError(f"No password in keyring for {self.acc.email}. Run `melman setup`.")
        self.conn = imaplib.IMAP4_SSL(self.acc.imap_host, self.acc.imap_port)
        self.conn.login(self.acc.email, pw)
        self.conn.select(self.mailbox, readonly=self.readonly)
        return self.conn

    def __exit__(self, *exc) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn.logout()


def list_inbox(acc: Account, limit: int = 20, mailbox: str = "INBOX") -> list[Summary]:
    with _IMAP(acc, mailbox) as conn:
        typ, data = conn.uid("search", None, "ALL")
        uids = data[0].split()
        uids = uids[-limit:][::-1]  # newest first
        return [_summary(conn, uid) for uid in uids]


def search(acc: Account, query: str, limit: int = 20, mailbox: str = "INBOX") -> list[Summary]:
    with _IMAP(acc, mailbox) as conn:
        # IMAP TEXT search across whole message.
        typ, data = conn.uid("search", None, "TEXT", f'"{query}"')
        uids = data[0].split()
        uids = uids[-limit:][::-1]
        return [_summary(conn, uid) for uid in uids]


def _summary(conn: imaplib.IMAP4_SSL, uid: bytes) -> Summary:
    typ, data = conn.uid("fetch", uid, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
    flags = b""
    header = b""
    for part in data:
        if isinstance(part, tuple):
            header = part[1]
        elif isinstance(part, bytes):
            flags += part
    msg = email.message_from_bytes(header)
    return Summary(
        uid=uid.decode(),
        from_=_decode(msg.get("From")),
        subject=_decode(msg.get("Subject")),
        date=_decode(msg.get("Date")),
        seen=b"\\Seen" in flags,
    )


def read_message(acc: Account, uid: str, mailbox: str = "INBOX", mark_seen: bool = False) -> Message:
    with _IMAP(acc, mailbox, readonly=not mark_seen) as conn:
        typ, data = conn.uid("fetch", uid.encode(), "(RFC822)")
        raw = data[0][1]
        msg = email.message_from_bytes(raw)
        return Message(
            uid=uid,
            from_=_decode(msg.get("From")),
            to=_decode(msg.get("To")),
            subject=_decode(msg.get("Subject")),
            date=_decode(msg.get("Date")),
            body=_extract_body(msg),
        )


def _extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        # Prefer text/plain; fall back to first text part.
        plain = None
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                continue
            if ctype == "text/plain" and plain is None:
                plain = part
        target = plain
        if target is None:
            for part in msg.walk():
                if part.get_content_type().startswith("text/"):
                    target = part
                    break
        if target is None:
            return ""
        return _payload_text(target)
    return _payload_text(msg)


def _payload_text(part: email.message.Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return str(part.get_payload())
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def send_message(acc: Account, to: str, subject: str, body: str, cc: str | None = None) -> None:
    pw = acc.password()
    if not pw:
        raise RuntimeError(f"No password in keyring for {acc.email}. Run `melman setup`.")
    msg = EmailMessage()
    msg["From"] = acc.email
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL(acc.smtp_host, acc.smtp_port) as smtp:
        smtp.login(acc.email, pw)
        smtp.send_message(msg)
