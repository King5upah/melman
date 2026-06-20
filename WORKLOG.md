# WORKLOG — melman

## 2026-06-20

- Bootstrap del proyecto: Python Typer+rich, backend IMAP/SMTP + App Password, keyring. Repo público.
- Comandos base: `setup inbox read search send accounts version`. Todos con `--json` para uso por agente.
- Backend Gmail API + OAuth (`melman auth`), deps opcionales `[gmail]`, dispatch por `acc.backend`. Token con refresh en config dir.
- Skill Claude Code en repo aparte (King5upah/melman-skill) + referencia cruzada en README.
- Login OAuth real (cuenta raindeerdeveloper@gmail.com). App publicada a Production para evitar tope de test users.
- Primitives de triage en `gmail_api`: `search_ids` (paginado), `fetch_meta`, `get_or_create_label`, `batch_modify` (batchModify 1000/call).
- Triage masivo: 23,146 no leídos → 0. 1,410 → label `Revisado-Importante`, 1,502 → label `Invoices`, 20,246 → solo leído. Clasificación por reglas sender/keyword server-side.
- Comando `melman unsubscribe`: dedup por remitente, `--exclude` keep-list, `--auto` (one-click RFC-8058 + mailto), `--trash`. 27 promos desuscritas one-click.
- Scope `gmail.settings.basic` + `create_filter`/`list_filters` + comando `melman filters`. 2 filtros permanentes auto-clasifican correo entrante a `Revisado-Importante` / `Invoices` (solo etiqueta, no borra).

### Pendiente
- 3 unsubscribe one-click fallaron (Medium, BPR, Shockbyte) — endpoint rechazó POST; requieren link manual.
- 7 sin header List-Unsubscribe (Steam, Xsolla, etc.) — transaccionales, dejar.
- Roadmap: attachments, `melman watch` (notifica mail nuevo), vista threaded.
