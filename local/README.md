# Helper scripts for this PC

These run next to the agent on this PC. `scripts/deploy-local.ps1` copies them to `%LOCALAPPDATA%\PhoneBox`, adds
their Startup shortcuts and starts them. Edit them here, never only in `%LOCALAPPDATA%`: a copy that lives only there
gets lost (and one written from a Claude Desktop session never reaches the real folder at all).

| Script | What it does | Installed |
| --- | --- | --- |
| `lock-follow.pyw` | Phone screen off when Windows locks or the monitor turns off, on again after unlock; Right Ctrl + ←/→ flips the panel's pages | yes (`PhoneBox Lock`) |
| `notes-sync.pyw` + `notes-ui.html` | Keeps the "Нотатки" page in sync with `Documents\PhoneBox\Нотатки.txt` and `Справи.txt`; editor at http://notes.localhost | yes (`PhoneBox Notes`) |
| `telegram-bridge.pyw` | Forwarded Telegram Desktop notifications to the panel | no: the agent's own Telegram notifications replaced it |

Keep the agent's *Follow the computer lock* option off while `lock-follow.pyw` runs, or both react to every lock.
