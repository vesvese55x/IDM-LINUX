"""Off-camera fresh-runner preparation and reject-on-console footage guard."""
from pathlib import Path
import os,sys,time,json,subprocess,shutil,threading,re,ctypes
import requests
ISWIN=sys.platform=='win32'
FLAGS=subprocess.CREATE_NO_WINDOW if ISWIN else 0

def call(cmd,**kw):return subprocess.run(cmd,creationflags=FLAGS,check=True,**kw)
def safe_env():return {k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ['TOKEN','SECRET','PASSWORD']) and not k.startswith(('ACTIONS_','GITHUB_'))}
def brave_path():
 if not ISWIN:return shutil.which('brave-browser') or shutil.which('brave')
 for key in ['PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA']:
  p=Path(os.getenv(key,'C:/missing'))/'BraveSoftware/Brave-Browser/Application/brave.exe'
  if p.exists():return str(p)
 raise RuntimeError('Installed Brave executable not found')
def profile_root():
 return Path(os.environ['LOCALAPPDATA'])/'BraveSoftware/Brave-Browser/User Data' if ISWIN else Path.home()/'.config/BraveSoftware/Brave-Browser'

def read_default():
 if not ISWIN:
  return {s:subprocess.run(['xdg-mime','query','default','x-scheme-handler/'+s],capture_output=True,text=True).stdout.strip() for s in ['http','https']}
 import winreg
 result={}
 for scheme in ['http','https']:
  try:
   with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations'+'\\'+scheme+r'\UserChoice') as k:result[scheme]=winreg.QueryValueEx(k,'ProgId')[0]
  except OSError:result[scheme]=None
 return result

def make_windows_default(out):
 from pywinauto import Desktop
 from ctypes import wintypes
 # Use the real Windows default-app UI. Never forge a UserChoice hash.
 subprocess.Popen(['explorer.exe','ms-settings:defaultapps'],creationflags=FLAGS)
 desktop=Desktop(backend='uia');deadline=time.monotonic()+75;events=[]
 while time.monotonic()<deadline:
  current=read_default()
  if all(v and str(v).lower().startswith('brave') for v in current.values()):break
  windows=desktop.windows()
  for win in windows:
   try:
    if win.window_text() not in ['Settings','Ayarlar']:continue
    try:win.maximize()
    except Exception:pass
    nodes=win.descendants();choices=[]
    for n in nodes:
     try:
      label=n.window_text().strip();kind=n.element_info.control_type
      if n.is_visible() and n.is_enabled() and label.lower() in ['switch anyway','yine de değiştir','brave','brave browser']:
       win.set_focus();n.click_input();events.append(label);time.sleep(1.2);break
     except Exception:pass
    else:
     labels=[n for n in nodes if n.window_text().strip().lower() in ['web browser','web tarayıcısı']]
     if labels:
      r=labels[0].rectangle()
      choices=[n for n in nodes if n.element_info.control_type=='Button' and n.is_visible() and n.is_enabled() and r.top<=n.rectangle().top<r.bottom+120 and n.rectangle().width()>100]
      choices.sort(key=lambda n:abs(n.rectangle().top-r.bottom))
     if not choices:choices=[n for n in nodes if n.element_info.control_type=='Button' and n.is_visible() and any(x in n.window_text() for x in ['Microsoft Edge','Internet Explorer'])]
     if choices:win.set_focus();choices[0].click_input();events.append(choices[0].window_text());time.sleep(1)
   except Exception:pass
  time.sleep(.5)
 final=read_default()
 (out/'brave-default-ui-events.json').write_text(json.dumps({'events':events,'default':final},ensure_ascii=False,indent=2))
 if not all(v and str(v).lower().startswith('brave') for v in final.values()):
  snapshot=[]
  for win in desktop.windows():
   try:
    if win.window_text() in ['Settings','Ayarlar']:
     snapshot=[{'text':n.window_text(),'type':n.element_info.control_type} for n in win.descendants() if n.is_visible()]
   except Exception:pass
  (out/'default-app-settings-controls.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2))
  raise RuntimeError('Brave default HTTP/HTTPS associations not verified; recording not started')
 for win in desktop.windows():
  try:
   if win.window_text() in ['Settings','Ayarlar']:win.close()
  except Exception:pass
 return final

def cdp(ws,method,params=None):
 import websocket
 sock=websocket.create_connection(ws,timeout=8,suppress_origin=True)
 try:
  sock.send(json.dumps({'id':1,'method':method,'params':params or {}}))
  while True:
   data=json.loads(sock.recv())
   if data.get('id')==1:return data
 finally:sock.close()

def browser_warmup(exe,out):
 # Standard installed profile, so subsequent normal/default-browser launches and
 # the apps' native-messaging registration see exactly the same profile.
 profile=profile_root();(profile/'Default').mkdir(parents=True,exist_ok=True)
 (profile/'First Run').touch()
 prefs=profile/'Default/Preferences'
 values=json.loads(prefs.read_text()) if prefs.exists() else {}
 values.setdefault('browser',{}).update({'check_default_browser':False,'has_seen_welcome_page':True})
 values.setdefault('brave',{}).update({'has_seen_welcome_page':True})
 values.setdefault('profile',{}).update({'exit_type':'Normal','exited_cleanly':True})
 values.setdefault('session',{}).update({'restore_on_startup':5,'startup_urls':[]})
 prefs.write_text(json.dumps(values))
 # P3A belongs to Local State, not profile Preferences. Complete its first-use
 # privacy choice off-camera (opt out), so no setup notice leaks into footage.
 localfile=profile/'Local State'
 local=json.loads(localfile.read_text()) if localfile.exists() else {}
 local.setdefault('brave',{}).setdefault('p3a',{}).update({'enabled':False,'notice_acknowledged':True})
 localfile.write_text(json.dumps(local))
 args=[exe,'--no-first-run','--no-default-browser-check','--disable-session-crashed-bubble','--remote-debugging-port=19333','--remote-debugging-address=127.0.0.1','about:blank']
 log=(out/'brave-off-camera-preparation.log').open('wb')
 process=subprocess.Popen(args,env=safe_env(),stdout=log,stderr=log,creationflags=FLAGS)
 try:
  deadline=time.monotonic()+45;version=None
  while time.monotonic()<deadline:
   try:
    r=requests.get('http://127.0.0.1:19333/json/version',timeout=1)
    if r.ok:version=r.json();break
   except requests.RequestException:pass
   time.sleep(.5)
  if not version:raise RuntimeError('Off-camera Brave first-run session did not become ready')
  tabs=requests.get('http://127.0.0.1:19333/json/list',timeout=5).json()
  for tab in tabs:
   if tab.get('type')=='page':cdp(tab['webSocketDebuggerUrl'],'Page.navigate',{'url':'about:blank'})
  time.sleep(2)
  after=requests.get('http://127.0.0.1:19333/json/list',timeout=5).json()
  assert any(t.get('url')=='about:blank' for t in after),'Prepared Brave blank tab missing'
  assert not any('brave://welcome' in t.get('url','') for t in after),'Welcome page remained visible'
  try:cdp(version['webSocketDebuggerUrl'],'Browser.close')
  except Exception:pass
  time.sleep(2)
  # A second ordinary startup must remain first-run-free without the bypass
  # flags used during initial off-camera provisioning.
  normal=[a for a in args if a not in ['--no-first-run','--no-default-browser-check']]
  process=subprocess.Popen(normal,env=safe_env(),stdout=log,stderr=log,creationflags=FLAGS)
  deadline=time.monotonic()+30;version2=None
  while time.monotonic()<deadline:
   try:
    rr=requests.get('http://127.0.0.1:19333/json/version',timeout=1)
    if rr.ok:version2=rr.json();break
   except requests.RequestException:pass
   time.sleep(.5)
  assert version2,'Normal Brave restart did not become ready'
  time.sleep(3)
  normal_tabs=requests.get('http://127.0.0.1:19333/json/list',timeout=5).json()
  assert not any(any(t.get('url','').startswith(prefix) for prefix in ['brave://welcome','brave://intro','brave://onboarding']) for t in normal_tabs),'Normal Brave restart still showed first-run setup'
  try:cdp(version2['webSocketDebuggerUrl'],'Browser.close')
  except Exception:pass
  time.sleep(2)
  persisted=json.loads(localfile.read_text()).get('brave',{}).get('p3a',{})
  assert persisted.get('notice_acknowledged') is True and persisted.get('enabled') is False,'First-use privacy preparation did not persist'
  return {'privacy_first_use_prepared':'PASS','normal_restart_without_first_run_flags':'PASS','status':'PASS','profile':str(profile),'first_run_marker':True,'welcoming_tabs_remaining':False,'browser_version':version.get('Browser'),'preparation_recorded':False}
 finally:
  if process.poll() is None:
   try:process.wait(timeout=5)
   except subprocess.TimeoutExpired:process.terminate()
  log.close()

def prepare(out,report):
 out=Path(out)
 from national_wallpaper import build
 wall,wallinfo=build(out,os.environ.get('FILM_LANGUAGE','tr'));report['wallpaper_system_info']=wallinfo
 exe=brave_path();assert exe
 if ISWIN:
  import winreg
  with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Control Panel\Desktop') as k:
   winreg.SetValueEx(k,'WallpaperStyle',0,winreg.REG_SZ,'6');winreg.SetValueEx(k,'TileWallpaper',0,winreg.REG_SZ,'0')
  from PIL import Image
  bmp=Path(os.environ['TEMP'])/'film-studio-wallpaper.bmp';Image.open(wall).save(bmp)
  assert ctypes.windll.user32.SystemParametersInfoW(20,0,str(bmp),3),'Wallpaper application failed'
  # Hide host/runner console windows before any recording exists.
  callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
  def hide(hwnd,_):
   buf=ctypes.create_unicode_buffer(256);ctypes.windll.user32.GetClassNameW(hwnd,buf,256)
   if buf.value in ['ConsoleWindowClass','CASCADIA_HOSTING_WINDOW_CLASS']:ctypes.windll.user32.ShowWindow(hwnd,0)
   return True
  ctypes.windll.user32.EnumWindows(callback(hide),0)
  default=make_windows_default(out)
 else:
  assert os.environ.get('LANG','').lower().startswith('tr_tr'),'Turkish locale not active'
  call(['feh','--no-fehbg','--bg-max',str(wall)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  for mime in ['x-scheme-handler/http','x-scheme-handler/https','text/html','application/xhtml+xml']:
   call(['xdg-mime','default','brave-browser.desktop',mime],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  subprocess.run(['xdg-settings','set','default-web-browser','brave-browser.desktop'],capture_output=True)
  default=read_default();assert all('brave' in x.lower() for x in default.values()),default
  # Verify real installed font cmap coverage, not just a font filename.
  from fontTools.ttLib import TTFont
  fontpath=subprocess.check_output(['fc-match','-f','%{file}','DejaVu Sans'],text=True).strip()
  ft=TTFont(fontpath);cmap=ft.getBestCmap();chars='ÇĞİÖŞÜçğıöşü';missing=[c for c in chars if ord(c) not in cmap];assert not missing,missing
  report['turkish_desktop_preflight']={'locale':os.environ.get('LANG'),'font':fontpath,'required_characters':chars,'missing_characters':missing,'font_coverage':'PASS','wine_text_visual_verification':'PENDING'}
 browser=browser_warmup(exe,out)
 import desktop_shell
 report['desktop_shell']=desktop_shell.prepare(out,wall)
 report['desktop_preparation']={'status':'PASS','before_recording':True,'brave_executable':exe,'default_http_https':default,'browser':browser,'wallpaper':wall.name,'installer_or_first_run_recorded':False}

class ConsoleGuard:
 def __init__(self,out):self.out=Path(out);self.events=[];self.allowed_events=[];self.install_rules={};self.rule_lock=threading.RLock();self.seen_rejected=set();self.seen_allowed=set();self.stop=threading.Event();self.armed=False;self.thread=None
 def start(self):
  self.armed=True
  if ISWIN:
   self.thread=threading.Thread(target=self.windows,daemon=True)
  else:self.thread=threading.Thread(target=self.linux,daemon=True)
  self.thread.start()
 def allow_install_terminal(self,chapter,title,seconds=900):
  import uuid
  assert not ISWIN and chapter in ['linux-one-line','linux-appimage','linux-deb-apt'],'No terminal exemption for this chapter'
  assert len(title)>20 and seconds<=1200
  token=uuid.uuid4().hex
  with self.rule_lock:self.install_rules[token]={'chapter':chapter,'title':title,'parent_pid':os.getpid(),'binary':str(Path(shutil.which('xterm')).resolve()),'until':time.monotonic()+seconds,'active':True,'opened':time.time()}
  return token
 def end_install_terminal(self,token):
  with self.rule_lock:self.install_rules[token]['active']=False;self.install_rules[token]['closed']=time.time()
 def observe_linux_terminal(self,w,d,klass,source):
  title=w.get_wm_name() or '';pid=0
  try:
   prop=w.get_full_property(d.intern_atom('_NET_WM_PID'),0);pid=int(prop.value[0])
  except Exception:pass
  approved=None
  with self.rule_lock:
   for token,rule in self.install_rules.items():
    if not(rule['active'] and time.monotonic()<=rule['until'] and title==rule['title'] and 'xterm' in klass):continue
    try:
     exe=str(Path(f'/proc/{pid}/exe').resolve());stat=Path(f'/proc/{pid}/stat').read_text();parent=int(stat.rsplit(')',1)[1].split()[1])
     if exe==rule['binary'] and parent==rule['parent_pid']:approved=rule;break
    except Exception:pass
  event={'time':time.time(),'class':klass,'source':source,'window_id':w.id,'pid':pid,'title':title}
  if approved:
   key=(w.id,approved['chapter'])
   if key not in self.seen_allowed:self.seen_allowed.add(key);self.allowed_events.append({**event,'chapter':approved['chapter'],'policy':'Exact unique title, real xterm binary and direct capture-process parent; bounded live installation scope'})
  elif w.id not in self.seen_rejected:
   self.seen_rejected.add(w.id);self.events.append(event)
 def windows(self):
  import win32gui,win32con
  from ctypes import wintypes
  from ctypes.wintypes import HWND,DWORD,LONG
  # WinEvent provides event-driven coverage; polling additionally checks current
  # visibility. Any detected console event rejects footage rather than masking it.
  def check(hwnd,origin):
   try:
    klass=win32gui.GetClassName(hwnd)
    if klass in ['ConsoleWindowClass','CASCADIA_HOSTING_WINDOW_CLASS'] and win32gui.IsWindowVisible(hwnd):
     self.events.append({'time':time.time(),'class':klass,'source':origin});win32gui.ShowWindow(hwnd,win32con.SW_HIDE)
   except Exception:pass
  CB=ctypes.WINFUNCTYPE(None,ctypes.c_void_p,DWORD,HWND,LONG,LONG,DWORD,DWORD)
  def event(h,kind,hwnd,obj,child,thread,ms):
   if hwnd and obj==0:check(hwnd,'EVENT_OBJECT_SHOW')
  callback=CB(event);u=ctypes.windll.user32;u.SetWinEventHook.restype=ctypes.c_void_p
  u.SetWinEventHook.argtypes=[DWORD,DWORD,ctypes.c_void_p,CB,DWORD,DWORD,DWORD]
  hook=u.SetWinEventHook(0x8002,0x8002,None,callback,0,0,0)
  if not hook:self.events.append({'time':time.time(),'source':'monitor_initialization','error':'WinEvent hook unavailable'})
  msg=wintypes.MSG()
  try:
   while not self.stop.is_set():
    while u.PeekMessageW(ctypes.byref(msg),None,0,0,1):u.TranslateMessage(ctypes.byref(msg));u.DispatchMessageW(ctypes.byref(msg))
    win32gui.EnumWindows(lambda hwnd,_:check(hwnd,'visibility_scan'),None);self.stop.wait(.03)
  finally:
   if hook:u.UnhookWinEvent(ctypes.c_void_p(hook))
 def linux(self):
  from Xlib import display,X
  from desktop_shell import x11_windows
  d=display.Display();root=d.screen().root
  root.change_attributes(event_mask=X.SubstructureNotifyMask)
  names=['xterm','gnome-terminal','xfce4-terminal','konsole','kitty','alacritty','wineconsole','wezterm','terminator']
  seen=set()
  try:
   while not self.stop.is_set():
    while d.pending_events():
     e=d.next_event()
     if e.type==X.MapNotify:
      try:
       klass=' '.join(e.window.get_wm_class() or ()).lower()
       if any(n in klass for n in names):self.observe_linux_terminal(e.window,d,klass,'X11_MapNotify')
      except Exception:pass
    for w in x11_windows(root):
     try:
      klass=' '.join(w.get_wm_class() or ()).lower()
      if any(n in klass for n in names) and w.get_attributes().map_state==X.IsViewable:
       self.observe_linux_terminal(w,d,klass,'visibility_scan')
     except Exception:pass
    self.stop.wait(.04)
  finally:d.close()
 def finish(self):
  alive=bool(self.thread and self.thread.is_alive())
  if any(r['active'] for r in self.install_rules.values()):self.events.append({'time':time.time(),'source':'unclosed_installation_scope'})
  self.stop.set()
  if self.thread:self.thread.join(timeout=3)
  result={'status':'REJECT' if self.events or not alive else 'PASS','monitor_alive_at_end':alive,'detected_terminal_console_events':len(self.events),'events':self.events,'authorized_installation_terminal_events':self.allowed_events,'installation_scopes_all_closed':all(not r['active'] for r in self.install_rules.values()),'method':'WinEvent+visibility scan' if ISWIN else 'X11 MapNotify+visibility scan','limit':'Native window monitoring is supplemented by editorial frame review; no absolute zero-flash guarantee from sampling alone.'}
  (self.out/'console-visibility-audit.json').write_text(json.dumps(result,indent=2));return result
