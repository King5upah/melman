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

from . import __version__, mailbox
from .config import (
    GMAIL_IMAP,
    GMAIL_SMTP,
    Account,
    default_account,
    load_accounts,
    save_account,
)

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
    msgs = mailbox.list_inbox(acc, limit=limit, mailbox=mailbox_name)
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
    msgs = mailbox.search(acc, query, limit=limit)
    if json:
        _emit([m.to_dict() for m in msgs], True)
        return
    _render_summaries(msgs, title=f"search: {query}")


@app.command()
def read(
    uid: str = typer.Argument(...),
    mailbox_name: str = typer.Option("INBOX", "--mailbox"),
    mark_seen: bool = typer.Option(False, "--mark-seen"),
    json: bool = typer.Option(False, "--json"),
):
    """Read a single message by UID."""
    acc = _account_or_die()
    msg = mailbox.read_message(acc, uid, mailbox=mailbox_name, mark_seen=mark_seen)
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
    mailbox.send_message(acc, to=to, subject=subject, body=body, cc=cc)
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
