# Melman 🦒

Terminal Gmail client over IMAP/SMTP. Long neck — reaches your mail from the
command line. Usable **by a human** (rich TUI tables) and **by an agent**
(every command takes `--json`).

> Named after the giraffe. He delivers.

## Why

- No Google Cloud project, no OAuth dance. Just an **App Password**.
- App Password stored in the **OS keyring** (Windows Credential Manager / macOS
  Keychain / Secret Service) — never in plaintext, never in git.
- One code path serves both the human CLI and the agent JSON interface.

## Install

```bash
cd melman
pip install -e .
```

Requires Python ≥ 3.10.

## Setup (Gmail)

1. Enable 2-Factor Auth on your Google account.
2. Create an App Password: https://myaccount.google.com/apppasswords
3. Run:

```bash
melman setup
# prompts for your Gmail address and the App Password (hidden input)
```

It logs in once to verify. Other IMAP/SMTP providers: pass `--imap-host`,
`--smtp-host`, etc. at setup.

## Human usage

```bash
melman inbox -n 20            # recent messages, newest first
melman read <UID>            # open one
melman read <UID> --mark-seen
melman search "invoice"      # full-text search
melman send --to a@b.com --subject "Hi" --body "text"
echo "long body" | melman send --to a@b.com --subject "Hi"   # body from stdin
melman accounts              # list configured accounts
```

## Agent usage

Add `--json` to any read/list command for machine-parsable output. `send` also
takes `--json` (and skips the interactive confirm).

```bash
melman inbox -n 10 --json
melman read 4821 --json
melman search "from:bank" --json
melman send --to a@b.com --subject "Re" --body "ok" --json
```

### Wiring as agent tools

Expose these as shell tools to an LLM. Suggested split:

| Task            | Model        | Command                          |
|-----------------|--------------|----------------------------------|
| triage / label  | Ollama local | `melman inbox --json` + classify |
| summarize thread| Ollama local | `melman read <uid> --json`       |
| draft reply     | Claude       | compose, then `melman send`      |

Multi-account: set `MAILCLI_ACCOUNT=you@gmail.com` env var, or it uses the first
configured account.

## Security

- App Password lives only in the OS keyring.
- `accounts.json` (config dir) holds **non-secret** host/port/email only.
- Nothing sensitive is written to the repo. See `.gitignore`.

## Roadmap

- [ ] Gmail API backend (labels, threads, push) as alternative to IMAP
- [ ] Attachments (download / send)
- [ ] Threaded conversation view
- [ ] `melman watch` — poll + notify on new mail
