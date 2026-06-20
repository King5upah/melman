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

## Setup (Gmail API + OAuth, browser login)

Alternative to App Password — browser consent, granular scopes, no plaintext
secret. More one-time setup.

```bash
pip install -e .[gmail]
```

One-time in [Google Cloud Console](https://console.cloud.google.com/):

1. Create a project.
2. Enable the **Gmail API**.
3. OAuth consent screen → External → add yourself as a **test user**.
4. Credentials → Create → **OAuth client ID** → **Desktop app** → download JSON,
   save as `credentials.json`.

Then:

```bash
melman auth --email you@gmail.com -c path/to/credentials.json
```

Opens the browser, you consent, the token (with refresh) is stored in your
config dir — never in the repo. Scopes: `gmail.modify` + `gmail.send`.

After this, all commands below work against the Gmail API. `search` accepts
native Gmail syntax (`from:`, `subject:`, `has:attachment`, …).

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

- [x] Gmail API backend (OAuth browser login) as alternative to IMAP
- [ ] Attachments (download / send)
- [ ] Threaded conversation view
- [ ] `melman watch` — poll + notify on new mail
