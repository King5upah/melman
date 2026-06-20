"""Melman CLI — terminal Gmail client. Every command takes --json so an agent can
parse output; without it, output is rendered with rich for humans."""

from __future__ import annotations

import getpass
import json as jsonlib
import sys

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__, gmail_api, mailbox
from .config import (
    GMAIL_IMAP,
    GMAIL_SMTP,
    Account,
    default_account,
    load_accounts,
    save_account,
)


def _backend(acc: Account):
    """Pick the transport module for an account. Same function signatures both ways."""
    return gmail_api if acc.backend == "gmail" else mailbox

app = typer.Typer(
    name="melman",
    help="Melman — terminal Gmail client (IMAP/SMTP). Long neck, reaches your mail.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err = Console(stderr=True)


def _emit(payload, json: bool) -> None:
    if json:
        console.print_json(jsonlib.dumps(payload))


def _account_or_die() -> Account:
    acc = default_account()
    if acc is None:
        err.print("[red]No account configured.[/] Run `melman setup`.")
        raise typer.Exit(1)
    return acc


@app.command()
def setup(
    email: str = typer.Option(..., prompt="Gmail address"),
    imap_host: str = typer.Option(GMAIL_IMAP[0]),
    imap_port: int = typer.Option(GMAIL_IMAP[1]),
    smtp_host: str = typer.Option(GMAIL_SMTP[0]),
    smtp_port: int = typer.Option(GMAIL_SMTP[1]),
):
    """Configure an account. Stores the App Password in the OS keyring.

    Gmail: enable 2FA, then create an App Password at
    https://myaccount.google.com/apppasswords and paste it here.
    """
    acc = Account(
        email=email,
        imap_host=imap_host,
        imap_port=imap_port,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
    )
    pw = getpass.getpass("App Password (hidden): ").strip().replace(" ", "")
    if not pw:
        err.print("[red]Empty password, aborting.[/]")
        raise typer.Exit(1)
    acc.set_password(pw)
    save_account(acc)
    console.print(f"[green]Saved[/] account [bold]{email}[/]. Testing login…")
    try:
        mailbox.list_inbox(acc, limit=1)
    except Exception as e:  # noqa: BLE001
        err.print(f"[red]Login failed:[/] {e}")
        raise typer.Exit(1)
    console.print("[green]✓ Login OK.[/]")


@app.command()
def auth(
    email: str = typer.Option(..., prompt="Gmail address"),
    credentials: str = typer.Option(
        "credentials.json",
        "--credentials",
        "-c",
        help="Path to the OAuth 'Desktop app' client JSON from Google Cloud Console.",
    ),
):
    """Authorize via OAuth in the browser (Gmail API backend).

    One-time prep in Google Cloud Console: create a project, enable the Gmail
    API, create an OAuth 'Desktop app' client, download its JSON, and add
    yourself as a test user. Then run this — it opens the browser for consent
    and stores the token in your config dir (never in the repo).
    """
    from . import auth as auth_mod

    acc = Account(email=email, backend="gmail")
    console.print("[cyan]Opening browser for Google consent…[/]")
    try:
        auth_mod.authorize(credentials, acc.token_path())
    except Exception as e:  # noqa: BLE001
        err.print(f"[red]Authorization failed:[/] {e}")
        raise typer.Exit(1)
    save_account(acc)
    console.print(f"[green]✓ Authorized[/] [bold]{email}[/]. Testing API…")
    try:
        gmail_api.list_inbox(acc, limit=1)
    except Exception as e:  # noqa: BLE001
        err.print(f"[red]API call failed:[/] {e}")
        raise typer.Exit(1)
    console.print("[green]✓ Gmail API OK.[/]")


@app.command()
def accounts(json: bool = typer.Option(False, "--json")):
    """List configured accounts."""
    accs = load_accounts()
    if json:
        _emit([a.email for a in accs.values()], True)
        return
    if not accs:
        console.print("No accounts. Run `melman setup`.")
        return
    for e in accs:
        console.print(f"• {e}")


@app.command()
def inbox(
    limit: int = typer.Option(20, "-n", "--limit"),
    mailbox_name: str = typer.Option("INBOX", "--mailbox"),
    json: bool = typer.Option(False, "--json"),
):
    """List recent messages, newest first."""
    acc = _account_or_die()
    msgs = _backend(acc).list_inbox(acc, limit=limit, mailbox=mailbox_name)
    if json:
        _emit([m.to_dict() for m in msgs], True)
        return
    _render_summaries(msgs, title=f"{acc.email} — {mailbox_name}")


@app.command()
def search(
    query: str = typer.Argument(...),
    limit: int = typer.Option(20, "-n", "--limit"),
    json: bool = typer.Option(False, "--json"),
):
    """Full-text search the mailbox."""
    acc = _account_or_die()
    msgs = _backend(acc).search(acc, query, limit=limit)
    if json:
        _emit([m.to_dict() for m in msgs], True)
        return
    _render_summaries(msgs, title=f"search: {query}")


@app.command()
def unsubscribe(
    query: str = typer.Option("category:promotions OR unsubscribe", "--query", "-q"),
    exclude: str = typer.Option(
        "", "--exclude", "-x", help="Comma list of substrings; senders matching any are KEPT."
    ),
    limit: int = typer.Option(60, "-n", "--limit"),
    auto: bool = typer.Option(False, "--auto", help="One-click POST + mailto unsubscribe automatically."),
    trash: bool = typer.Option(False, "--trash", help="Also move matching messages to Trash."),
    json: bool = typer.Option(False, "--json"),
):
    """Find subscription mail and unsubscribe. Dedups by sender; --exclude keeps
    senders you want. Gmail backend only. --auto does RFC-8058 one-click where
    offered and emails the mailto target otherwise. Without --auto, prints links."""
    acc = _account_or_die()
    if acc.backend != "gmail":
        err.print("[red]unsubscribe needs the Gmail backend.[/] Run `melman auth`.")
        raise typer.Exit(1)
    keep = [s.strip().lower() for s in exclude.split(",") if s.strip()]

    msgs = gmail_api.search(acc, query, limit=limit)
    # Dedup to one representative message per sender, skipping the keep-list.
    seen: dict[str, object] = {}
    for m in msgs:
        sender = m.from_.lower()
        if any(k in sender for k in keep):
            continue
        if sender not in seen:
            seen[sender] = m
    reps = list(seen.values())

    results = []
    for m in reps:
        info = gmail_api.unsubscribe_info(acc, m.uid)
        action = "none"
        detail = ""
        if auto and info["one_click"]:
            try:
                status = gmail_api.unsubscribe_one_click(info["https"][0])
                action = "one-click"
                detail = f"HTTP {status}"
            except Exception as e:  # noqa: BLE001
                action = "one-click-failed"
                detail = str(e)[:60]
        elif auto and info["mailto"]:
            try:
                _send_unsubscribe_mail(acc, info["mailto"][0])
                action = "mailto"
                detail = info["mailto"][0]
            except Exception as e:  # noqa: BLE001
                action = "mailto-failed"
                detail = str(e)[:60]
        elif info["https"]:
            action = "link"
            detail = info["https"][0]
        elif info["mailto"]:
            action = "mailto-link"
            detail = info["mailto"][0]
        if trash and info["has_target"]:
            try:
                gmail_api.trash_message(acc, m.uid)
            except Exception:  # noqa: BLE001
                pass
        results.append({"from": info["from"], "action": action, "detail": detail})

    if json:
        _emit(results, True)
        return
    table = Table(title=f"Unsubscribe — {len(results)} senders", expand=True)
    table.add_column("From", style="cyan", max_width=38)
    table.add_column("Action", no_wrap=True)
    table.add_column("Detail", max_width=60, overflow="fold")
    for r in results:
        style = "green" if r["action"] in ("one-click", "mailto") else ""
        table.add_row(r["from"], f"[{style}]{r['action']}[/]" if style else r["action"], r["detail"])
    console.print(table)
    if not auto:
        console.print("\n[dim]Re-run with --auto to one-click/mailto these, or open the links above.[/]")


def _send_unsubscribe_mail(acc: Account, mailto: str) -> None:
    """Send the unsubscribe email parsed from a mailto: List-Unsubscribe target."""
    from urllib.parse import parse_qs, unquote, urlparse

    parsed = urlparse(mailto)
    to = unquote(parsed.path)
    qs = parse_qs(parsed.query)
    subject = qs.get("subject", ["unsubscribe"])[0]
    body = qs.get("body", ["unsubscribe"])[0]
    gmail_api.send_message(acc, to=to, subject=subject, body=body)


@app.command()
def read(
    uid: str = typer.Argument(...),
    mailbox_name: str = typer.Option("INBOX", "--mailbox"),
    mark_seen: bool = typer.Option(False, "--mark-seen"),
    json: bool = typer.Option(False, "--json"),
):
    """Read a single message by UID."""
    acc = _account_or_die()
    msg = _backend(acc).read_message(acc, uid, mailbox=mailbox_name, mark_seen=mark_seen)
    if json:
        _emit(msg.to_dict(), True)
        return
    header = (
        f"[bold]From:[/] {msg.from_}\n"
        f"[bold]To:[/] {msg.to}\n"
        f"[bold]Date:[/] {msg.date}\n"
        f"[bold]Subject:[/] {msg.subject}"
    )
    console.print(Panel(header, expand=False))
    console.print(msg.body)


@app.command()
def send(
    to: str = typer.Option(..., "--to"),
    subject: str = typer.Option(..., "--subject"),
    body: str = typer.Option(None, "--body", help="Body text; omit to read from stdin."),
    cc: str = typer.Option(None, "--cc"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    json: bool = typer.Option(False, "--json"),
):
    """Send a message. Body from --body or piped stdin."""
    acc = _account_or_die()
    if body is None:
        body = sys.stdin.read()
    if not yes and not json:
        console.print(Panel(f"To: {to}\nSubject: {subject}\n\n{body}", title="Send?"))
        if not typer.confirm("Send this?"):
            raise typer.Abort()
    _backend(acc).send_message(acc, to=to, subject=subject, body=body, cc=cc)
    if json:
        _emit({"sent": True, "to": to, "subject": subject}, True)
    else:
        console.print(f"[green]✓ Sent[/] to {to}.")


@app.command()
def version():
    """Show version."""
    console.print(f"melman {__version__}")


def _render_summaries(msgs, title: str) -> None:
    table = Table(title=title, expand=True)
    table.add_column("UID", style="dim", no_wrap=True)
    table.add_column("", width=1)  # unread marker
    table.add_column("From", style="cyan", max_width=30)
    table.add_column("Subject", max_width=60)
    table.add_column("Date", style="dim", no_wrap=True)
    for m in msgs:
        table.add_row(
            m.uid,
            "" if m.seen else "●",
            m.from_,
            m.subject,
            m.date,
        )
    console.print(table)


if __name__ == "__main__":
    app()
