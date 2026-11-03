"""Selected real GUI functional cases. Only explicitly proven outcomes are PASS."""
import time,os,json,threading,hashlib,unicodedata
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

def norm(t):
 return ''.join(c for c in unicodedata.normalize('NFKD',t.replace('ı','i')) if not unicodedata.combining(c)).lower()
def windows(main,nav,report,out,screenshot):
 from pywinauto import Desktop
 cases=report.setdefault('functional_cases',[])
 def checkpoint():
  (out/'probe-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 def buttons():
  found=[]
  for c in main.descendants():
   try:
    if c.is_visible() and 'BUTTON' in c.class_name().upper():found.append(c)
   except Exception:pass
  return found
 def click_text(part):
  candidate=next((x for x in buttons() if norm(part) in norm(x.window_text())),None)
  if candidate is None:raise RuntimeError('Actual button unavailable: '+part)
  candidate.click_input();return candidate
 def real_idm():
  import winreg
  try:
   with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\DownloadManager') as key:
    p=Path(winreg.QueryValueEx(key,'ExePath')[0])
    if p.is_file():return p
  except OSError:pass
  for pf in ['ProgramFiles','ProgramFiles(x86)']:
   p=Path(os.getenv(pf,'C:/nonexistent'))/'Internet Download Manager/IDMan.exe'
   if p.is_file():return p
  return None
 # Actual language tiles, actual native mouse clicks; then restore Turkish.
 try:
  nav[7].click_input();time.sleep(1.5);click_text('English');time.sleep(2)
  en=main.window_text();screenshot('functional-language-en');assert 'Control Center' in en,en
  nav[7].click_input();time.sleep(1);click_text('Türkçe');time.sleep(2)
  tr=main.window_text();screenshot('functional-language-tr');assert 'Kontrol Merkezi' in tr,tr
  cases.append({'id':'gui-language-tr-en-tr','status':'PASS','english_title':en,'turkish_title':tr})
 except Exception as e:cases.append({'id':'gui-language-tr-en-tr','status':'FAIL','reason':str(e)})
 checkpoint()
 # Follow the intentional interactive installation path, with real mouse input.
 # A visible installer is not by itself a product failure. No external reinstallation.
 try:
  import psutil,requests,re
  nav[0].click_input();time.sleep(1.5)
  for c in buttons():
   if ('tarayici' in norm(c.window_text()) or 'browser' in norm(c.window_text())):
    try:
     if c.get_check_state():c.click_input()
    except Exception:pass
  start=time.time();click_text('İşlemi Şimdi Başlat');deadline=time.monotonic()+240
  actions=report.setdefault('vendor_gui_actions',[]);verified=False;stable_since=None;last_action=time.monotonic()
  def record_action(w,c,kind):
   nonlocal last_action
   last_action=time.monotonic()
   actions.append({'window_title':w.window_text(),'control_text':c.window_text(),'kind':kind,'video_offset_seconds':time.time()-report['record_wallclock_start']});checkpoint()
  def vendor_windows():
   result=[]
   try:descendant_ids={p.pid for p in psutil.Process(main.process_id()).children(recursive=True)}
   except Exception:descendant_ids=set()
   for w in Desktop(backend='win32').windows():
    try:
     title=norm(w.window_text());name=psutil.Process(w.process_id()).name().lower()
     if not w.is_visible():continue
     if w.process_id() in descendant_ids or name=='semo_idm_setup.exe' or title in ['please read idm license','choose destination location','start installation','installation complete','select program folder'] or (('idm' in title or 'internet download manager' in title) and 'semo' not in title) or name=='idman.exe' or name.startswith(('idmiecc','idmintegr','iemonitor')) or title in ['internet download manager installation wizard','idm browser integration','idm installation']:
      result.append(w)
    except Exception:pass
   return result
  def clear_vendor_information():
   count=0
   for w in Desktop(backend='win32').windows(class_name='#32770'):
    try:
     if w.process_id()!=main.process_id():continue
     text=' '.join(c.window_text() for c in w.descendants())
     if not any(x in norm(text) for x in ['klasor','folder']):continue
     for c in w.descendants():
      if norm(c.window_text()).replace('&','').strip() in ['ok','tamam']:
       report.setdefault('postinstall_folder_notices',[]).append(text);record_action(w,c,'acknowledge_app_folder_notice');c.click_input();count+=1;time.sleep(.8);break
    except Exception:pass
   for w in vendor_windows():
    title=norm(w.window_text())
    if not any(x in title for x in ['browser integration','integration module','tip','registration','kayit','ipucu']):continue
    for c in w.descendants():
     try:
      label=norm(c.window_text()).replace('&','').strip()
      if c.is_visible() and c.is_enabled() and label in ['ok','tamam','close','kapat','cancel','iptal']:
       w.set_focus();record_action(w,c,'acknowledge_information_or_close_reminder');c.click_input();time.sleep(.8);count+=1;break
     except Exception:pass
   return count
  while time.monotonic()<deadline:
   installer=Path(os.environ['TEMP'])/'semo_idm_setup.exe'
   if installer.exists() and not verified and any('installation wizard' in norm(w.window_text()) for w in vendor_windows()):
    digest=hashlib.sha256(installer.read_bytes()).hexdigest()
    manifest_url='https://raw.githubusercontent.com/microsoft/winget-pkgs/master/manifests/t/Tonec/InternetDownloadManager/6.43.16/Tonec.InternetDownloadManager.installer.yaml'
    response=requests.get(manifest_url,timeout=30);response.raise_for_status();expected_installer=re.search(r'InstallerSha256:\s*([A-Fa-f0-9]{64})(?=\s|$)',response.text).group(1).lower()
    assert len(expected_installer)==64
    report['official_installer_digest_check']={'actual_sha256':digest,'expected_sha256':expected_installer,'match':digest==expected_installer};checkpoint();assert digest==expected_installer,'Official installer hash mismatch';verified=True
   if not verified:time.sleep(1);continue
   clear_vendor_information();wizard_visible=False
   report['desktop_window_titles_during_install']=[w.window_text() for w in Desktop(backend='win32').windows() if w.window_text()]
   if verified and actions and time.monotonic()-last_action>35:break
   for w in vendor_windows():
    title=norm(w.window_text())
    if not any(x in title for x in ['installation','setup','license','destination','program folder','program group','ready to install','select folder']):continue
    wizard_visible=True
    texts=[];controls=[]
    for c in w.descendants():
     try:
      if c.is_visible():texts.append(c.window_text());controls.append(c)
     except Exception:pass
    report['last_vendor_wizard']={'title':w.window_text(),'visible_text':texts}
    # Accept only the installation licence; never activate/reset a paid licence.
    for c in controls:
     label=norm(c.window_text()).replace('&','').strip()
     if ('i accept' in label or 'kabul ediyorum' in label or 'i agree' in label) and len(label)<180:
      try:
       if not c.get_check_state():w.set_focus();record_action(w,c,'accept_installation_licence');c.click_input();time.sleep(.6)
      except Exception:pass
    for c in controls:
     label=norm(c.window_text()).replace('&','').replace('>','').replace('<','').strip()
     if label in ['next','ileri','install','yukle','finish','bitir','complete','done'] and c.is_enabled():
      w.set_focus();screenshot('functional-wizard-step-'+str(len(actions)));record_action(w,c,'installation_next_or_finish');c.click_input();time.sleep(1.2);break
   if real_idm() and not wizard_visible:
    if stable_since is None:stable_since=time.monotonic()
    if time.monotonic()-stable_since>=3:break
   else:stable_since=None
   time.sleep(.6)
  idm=real_idm();clear_vendor_information();screenshot('functional-original-idm-install')
  cases.append({'id':'official-idm-install-through-semo-user-gui','status':'PASS' if idm and stable_since is not None else 'BLOCKED','mode':'intentional interactive user-assisted GUI','external_installer_relaunch':False,'actual_idm_path':str(idm) if idm else None,'gui_actions':len(actions),'elapsed_seconds':time.time()-start,'reason':None if idm and stable_since is not None else 'Interactive installation did not reach an installed executable and closed wizard.'})
  if not idm:checkpoint();return
  report['actual_original_idm_path']=str(idm);time.sleep(4)
  from browser_consent import approve_windows
  approve_windows(report,out,screenshot);checkpoint()
  for _ in range(5):
   if not clear_vendor_information():break
  main.set_focus()
 except Exception as e:
  cases.append({'id':'official-idm-install-through-semo-user-gui','status':'FAIL','reason':str(e)});checkpoint();return
 checkpoint()
 # Deterministic own HTTP payload; no third-party media or private files.
 payload=(bytes(range(251))*((8*1024*1024)//251+1))[:8*1024*1024];expected=hashlib.sha256(payload).hexdigest();stats={'bytes_sent':0,'requests':[]};lock=threading.Lock();slot=[time.monotonic()]
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def respond(self,body):
   start,end=0,len(payload)-1;header=self.headers.get('Range','')
   if header.startswith('bytes='):
    a,b=header[6:].split('-',1);start=int(a or 0);end=min(end,int(b) if b else end)
   with lock:stats['requests'].append({'time':time.time(),'method':self.command,'range':header,'user_agent':self.headers.get('User-Agent','')})
   if start>=len(payload):self.send_response(416);self.send_header('Content-Range','bytes */'+str(len(payload)));self.end_headers();return
   self.send_response(206 if header else 200);self.send_header('Accept-Ranges','bytes');self.send_header('Last-Modified','Tue, 03 Nov 2026 00:00:00 GMT');self.send_header('ETag','\"film-proof-v1\"');self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(end-start+1));self.send_header('Content-Disposition','attachment; filename="film-proof.bin"')
   if header:self.send_header('Content-Range',f'bytes {start}-{end}/{len(payload)}')
   self.end_headers()
   if not body:return
   try:
    for offset in range(start,end+1,16384):
     chunk=payload[offset:min(offset+16384,end+1)]
     with lock:due=slot[0];slot[0]=max(slot[0],time.monotonic())+len(chunk)/(512*1024)
     time.sleep(max(0,due-time.monotonic()));self.wfile.write(chunk);self.wfile.flush()
     with lock:stats['bytes_sent']+=len(chunk)
   except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError,OSError):pass
  def do_HEAD(self):self.respond(False)
  def do_GET(self):self.respond(True)
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;threading.Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_address[1]}/film-proof.bin'
 try:
  nav[1].click_input();time.sleep(2)
  edits=[]
  for c in main.descendants():
   try:
    r=c.rectangle()
    if c.is_visible() and ('EDIT' in c.class_name().upper()) and r.width()>400 and 18<r.height()<45:edits.append(c)
   except Exception:pass
  edits.sort(key=lambda c:c.rectangle().top);assert len(edits)>=3,'Actual quick-link inputs not found'
  target=edits[2];target.click_input();target.set_edit_text(url);time.sleep(1);click_text('IDM ile İndir');start=time.time();time.sleep(4)
  # Observe real progress controls; never treat an app label alone as pause proof.
  pause=None;progress=None
  for w in Desktop(backend='win32').windows():
   if 'film-proof' not in w.window_text().lower():continue
   for b in w.descendants():
    try:
     if b.is_visible() and norm(b.window_text()).strip('& ') in ['pause','duraklat']:pause=b;progress=w;break
    except Exception:pass
   if pause:break
  if pause:
   clear_vendor_information();progress.set_focus();time.sleep(.5);pause.click_input();time.sleep(2);a=stats['bytes_sent'];time.sleep(3);b=stats['bytes_sent'];screenshot('functional-download-paused');resume=None
   for c in progress.descendants():
    try:
     if c.is_visible() and norm(c.window_text()).strip('& ') in ['resume','start','devam et','devam','baslat']:resume=c;break
    except Exception:pass
   if resume:
    progress.set_focus();resumed=time.time();resume.click_input();cases.append({'id':'actual-idm-pause-resume','status':'PASS' if b-a<=32768 else 'FAIL','bytes_sent_during_paused_3_seconds':b-a,'pause_observed_seconds':3,'resume_action_wallclock':resumed})
   else:cases.append({'id':'actual-idm-pause-resume','status':'BLOCKED','reason':'Pause was clicked but the real resume control could not be identified.'})
  else:cases.append({'id':'actual-idm-pause-resume','status':'BLOCKED','reason':'No real progress-dialog pause button found; no pause success claimed.'})
  download_root=Path(os.environ['USERPROFILE'])/'Downloads/IDM-SEMO';deadline=time.monotonic()+110;completed=None
  while time.monotonic()<deadline:
   for p in download_root.rglob('film-proof*') if download_root.exists() else []:
    try:
     if p.is_file() and p.stat().st_size==len(payload) and hashlib.sha256(p.read_bytes()).hexdigest()==expected:completed=p;break
    except (OSError,PermissionError):pass
   if completed:break
   time.sleep(1)
  screenshot('functional-download-result');cases.append({'id':'semo-gui-to-real-idm-http-download','status':'PASS' if completed else 'FAIL','expected_sha256':expected,'expected_bytes':len(payload),'saved_file':str(completed) if completed else None,'http_request_count':len(stats['requests']),'elapsed_seconds':time.time()-start,'managed_target_root':str(download_root)})
  for case in cases:
   if case['id']=='actual-idm-pause-resume' and case['status']=='PASS':
    ranged=any(q['time']>=case['resume_action_wallclock'] and q['method']=='GET' and q['range'].startswith('bytes=') and int(q['range'][6:].split('-')[0] or 0)>0 for q in stats['requests']);case['ranged_request_after_resume']=ranged
    if not completed or not ranged:case['status']='FAIL';case['reason']='Paused transfer must resume with a nonzero Range and finish with the exact expected SHA256.'
 finally:
  server.shutdown();server.server_close();(out/'controlled-http-evidence.json').write_text(json.dumps(stats,indent=2));checkpoint()

def linux(treepath,report,out,screenshot):
 import pyautogui
 cases=report.setdefault('functional_cases',[])
 def tree():return json.loads(treepath.read_text(encoding='utf-8'))
 def click(item):
  x,y,w,h=item['rect'];pyautogui.moveTo(x+w/2,y+h/2,duration=.4);pyautogui.click();time.sleep(2.5)
 def nav_language():
  d=tree();left=d['root_rect'][0]
  choices=[x for x in d['widgets'] if x['class']=='Button' and x['rect'][0]<left+40 and any(s in norm(x['text']) for s in ['language selection','dil secimi'])]
  assert choices,'Actual language navigation unavailable';click(choices[0])
 try:
  nav_language();choices=[x for x in tree()['widgets'] if x['text'].strip()=='Türkçe'];assert choices,'Actual Turkish language tile unavailable';click(choices[0]);tr=tree()['root_title'];screenshot('functional-language-tr');assert 'Kontrol Merkezi' in tr,tr
  nav_language();choices=[x for x in tree()['widgets'] if x['text'].strip()=='English'];assert choices,'Actual English language tile unavailable';click(choices[-1]);en=tree()['root_title'];screenshot('functional-language-en');assert 'Control Center' in en,en
  nav_language();choices=[x for x in tree()['widgets'] if x['text'].strip()=='Türkçe'];click(choices[0]);time.sleep(1);screenshot('functional-language-restored-tr')
  cases.append({'id':'gui-language-en-tr-en-tr','status':'PASS','turkish_title':tr,'english_title':en})
 except Exception as e:cases.append({'id':'gui-language-en-tr-en-tr','status':'FAIL','reason':str(e)})
 if os.getenv('FILM_WINE_ENGINE_TEST')=='1':
  try:linux_engine(treepath,report,out,screenshot)
  except Exception as e:cases.append({'id':'linux-real-wine-idm-engine-batch','status':'FAIL','reason':str(e)})
 else:cases.append({'id':'wine-idm-download-browser-p2p-functional-tests','status':'NOT_RUN','reason':'Dedicated Wine batch not selected.'})


def linux_engine(treepath,report,out,screenshot):
 import sys,subprocess,pyautogui
 cases=report.setdefault('functional_cases',[])
 def checkpoint():
  (out/'probe-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 def tree():return json.loads(treepath.read_text(encoding='utf-8'))
 def click(item):
  x,y,w,h=item['rect'];assert 0<x+w/2<1920 and 0<y+h/2<1080,'Control outside visible capture viewport';pyautogui.moveTo(x+w/2,y+h/2,duration=.35);pyautogui.click();time.sleep(1.5)
 def choose(part,kind=None):
  window=str(int(tree()['window_id'],16));subprocess.run(['xdotool','windowraise',window],check=False);subprocess.run(['xdotool','windowfocus',window],check=False);time.sleep(.3)
  candidates=[w for w in tree()['widgets'] if norm(part) in norm(w['text']) and (kind is None or w['class'] in kind)]
  assert candidates,'Released GUI control unavailable: '+part
  click(candidates[0]);return candidates[0]
 def logs():return '\n'.join(w.get('value','') for w in tree()['widgets'] if w['class']=='Text')
 sys.path.insert(0,str(Path(report['released_config_module_path']).parent.parent))
 from idm_linux.config import IdmLinuxConfig
 choose('Kurulum', ['Button','TButton'])
 # Do not unexpectedly launch a browser during the engine-only scenario.
 for w in tree()['widgets']:
  if w['class']=='TCheckbutton' and w.get('checked') and any(x in norm(w['text']) for x in ['tarayici','browser']):click(w)
 screenshot('functional-wine-install-before');choose('İşlemi Şimdi Başlat',['Button','TButton']);start=time.time();deadline=time.monotonic()+540;cfg=None;idm=None;complete=False
 while time.monotonic()<deadline:
  cfg=IdmLinuxConfig.load(create_if_missing=False);idm=cfg.find_idm_exe();log=logs()
  (out/'real-gui-install-log.txt').write_text(log,encoding='utf-8')
  if idm and any(w['text'].strip()=='100%' for w in tree()['widgets']):complete=True;break
  if any(w['class'] in ['Label','TLabel'] and any(t in norm(w['text']) for t in ['kurulum sirasinda hata','installation failed']) for w in tree()['widgets']):break
  time.sleep(2)
 screenshot('functional-wine-install-after');cases.append({'id':'linux-release-gui-installs-original-idm-in-wine','status':'PASS' if complete else 'FAIL','actual_idm_path':str(idm) if idm else None,'wine_prefix':cfg.wine_prefix if cfg else None,'elapsed_seconds':time.time()-start,'completed_to_100_percent':complete});checkpoint()
 if not complete:return
 report['linux_wine_config']={'wine_prefix':cfg.wine_prefix,'download_dir':cfg.download_dir,'actual_idm_path':str(idm)}
 from idm_linux.wine_sender import build_wine_env
 env=build_wine_env(cfg);env={k:v for k,v in env.items() if not any(x in k.upper() for x in ['TOKEN','SECRET','PASSWORD']) and not k.startswith(('ACTIONS_','GITHUB_'))}
 acp=subprocess.run(['wine','reg','query',r'HKLM\System\CurrentControlSet\Control\Nls\CodePage','/v','ACP'],env=env,capture_output=True,text=True,timeout=25)
 locale_info=subprocess.run(['wine','reg','query',r'HKCU\Control Panel\International','/v','Locale'],env=env,capture_output=True,text=True,timeout=25)
 (out/'wine-turkish-codepage.txt').write_text(acp.stdout+'\n'+acp.stderr+'\n'+locale_info.stdout+'\n'+locale_info.stderr,encoding='utf-8')
 turkish_acp=acp.returncode==0 and '1254' in acp.stdout
 report.setdefault('turkish_desktop_preflight',{})['wine_ansi_codepage_1254']='PASS' if turkish_acp else 'FAIL'
 cases.append({'id':'wine-turkish-ansi-codepage','status':'PASS' if turkish_acp else 'FAIL','expected_ansi_codepage':1254,'registry_output':acp.stdout})

 # CLI observation uses AppRun from the same released AppImage, not source checkout.
 observed=subprocess.run([report['release_apprun_path'],'status'],capture_output=True,text=True,timeout=45)
 (out/'released-cli-status.txt').write_text(observed.stdout+'\n'+observed.stderr,encoding='utf-8')
 report['released_cli_status_exit_code']=observed.returncode
 choose('Yakalama',['Button','TButton'])
 for w in tree()['widgets']:
  if w['class']=='TCheckbutton' and any(x in norm(w['text']) for x in ['sessiz','silent']) and not w.get('checked'):click(w)
 choose('Kaydet',['Button','TButton']);time.sleep(2)
 for w in tree()['widgets']:
  if w['class'] in ['Button','TButton'] and norm(w['text']).strip() in ['ok','tamam'] and any(x in norm(w.get('window_title','')) for x in ['kaydedildi','saved']):
   click(w);report['acknowledged_settings_saved_dialog']=w.get('window_title');break
 cases.append({'id':'linux-silent-mode-selected-through-real-gui','status':'PASS' if IdmLinuxConfig.load(create_if_missing=False).silent_mode else 'FAIL'})
 choose('Genel Bakış',['Button','TButton']);time.sleep(2)
 choose('Ana Penceresini',['Button','TButton']);time.sleep(8);screenshot('functional-wine-original-idm-open-request')
 window=str(int(tree()['window_id'],16));subprocess.run(['xdotool','windowraise',window],check=False);subprocess.run(['xdotool','windowfocus',window],check=False);time.sleep(.5)
 payload=(bytes(range(251))*((8*1024*1024)//251+1))[:8*1024*1024];expected=hashlib.sha256(payload).hexdigest();stats={'bytes_sent':0,'requests':[]};lock=threading.Lock();slot=[time.monotonic()]
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def respond(self,body):
   start,end=0,len(payload)-1;header=self.headers.get('Range','')
   if header.startswith('bytes='):
    a,b=header[6:].split('-',1);start=int(a or 0);end=min(end,int(b) if b else end)
   with lock:stats['requests'].append({'time':time.time(),'method':self.command,'range':header,'user_agent':self.headers.get('User-Agent','')})
   if start>=len(payload):self.send_response(416);self.send_header('Content-Range','bytes */'+str(len(payload)));self.end_headers();return
   self.send_response(206 if header else 200);self.send_header('Accept-Ranges','bytes');self.send_header('Last-Modified','Tue, 03 Nov 2026 00:00:00 GMT');self.send_header('ETag','\"film-proof-v1\"');self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(end-start+1));self.send_header('Content-Disposition','attachment; filename="film-proof.bin"')
   if header:self.send_header('Content-Range',f'bytes {start}-{end}/{len(payload)}')
   self.end_headers()
   if not body:return
   try:
    for offset in range(start,end+1,16384):
     chunk=payload[offset:min(offset+16384,end+1)]
     with lock:due=slot[0];slot[0]=max(slot[0],time.monotonic())+len(chunk)/(512*1024)
     time.sleep(max(0,due-time.monotonic()));self.wfile.write(chunk);self.wfile.flush()
     with lock:stats['bytes_sent']+=len(chunk)
   except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError,OSError):pass
  def do_HEAD(self):self.respond(False)
  def do_GET(self):self.respond(True)
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;threading.Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_address[1]}/film-proof.bin'
 try:
  entries=sorted([w for w in tree()['widgets'] if w['class'] in ['Entry','TEntry'] and w['rect'][2]>350],key=lambda w:w['rect'][1]);assert entries,'Real quick download input unavailable'
  subprocess.run(['xclip','-selection','clipboard'],input=url,text=True,check=True)
  choose('Panodan',['TButton']);time.sleep(1)
  current=next(w for w in tree()['widgets'] if w['path']==entries[0]['path']);report['verified_gui_fixture_url']=current.get('value');assert current.get('value')==url,'GUI clipboard paste did not populate the exact fixture URL'
  screenshot('functional-linux-clipboard-url-before-download')
  send=next(w for w in tree()['widgets'] if w['class']=='TButton' and 'idm' in norm(w['text']) and abs(w['rect'][1]-current['rect'][1])<15);click(send);start=time.time();deadline=time.monotonic()+160;completed=None
  while time.monotonic()<deadline:
   target=Path(cfg.download_dir).expanduser()
   for f in target.rglob('film-proof*') if target.exists() else []:
    try:
     if f.is_file() and f.stat().st_size==len(payload) and hashlib.sha256(f.read_bytes()).hexdigest()==expected:completed=f;break
    except (OSError,PermissionError):pass
   if completed:break
   time.sleep(1)
  screenshot('functional-linux-real-idm-download-result');cases.append({'id':'linux-gui-to-real-wine-idm-http-download','status':'PASS' if completed and stats['requests'] else 'FAIL','expected_sha256':expected,'actual_sha256':hashlib.sha256(completed.read_bytes()).hexdigest() if completed else None,'expected_bytes':len(payload),'saved_file':str(completed) if completed else None,'http_request_count':len(stats['requests']),'elapsed_seconds':time.time()-start,'managed_target_root':cfg.download_dir})
 finally:
  server.shutdown();server.server_close();(out/'controlled-http-evidence.json').write_text(json.dumps(stats,indent=2));checkpoint()
  # Collect the actual application's diagnostic logs without changing it.
  import shutil
  logs_root=Path.home()/'.cache/idm-linux/logs'
  if logs_root.exists():shutil.copytree(logs_root,out/'linux-runtime-logs',dirs_exist_ok=True)
  (out/'x11-window-list.txt').write_text(subprocess.run(['wmctrl','-l'],capture_output=True,text=True).stdout)
  if not completed:
   from idm_linux.wine_sender import build_wine_env
   env=build_wine_env(cfg);env={k:v for k,v in env.items() if not any(x in k.upper() for x in ['TOKEN','SECRET','PASSWORD']) and not k.startswith(('ACTIONS_','GITHUB_'))};env['WINEDEBUG']='err+all'
   with (out/'wine-startup-diagnostic.log').open('wb') as log:
    diagnostic=subprocess.Popen(['wine',str(idm),'/onboot'],env=env,stdout=log,stderr=subprocess.STDOUT);time.sleep(8);report['diagnostic_only_wine_launch']={'returncode_after_8s':diagnostic.poll(),'note':'External diagnosis after GUI test failure, not counted as GUI success.'}
   screenshot('functional-linux-wine-failure-diagnostic');checkpoint()
 cases.append({'id':'linux-browser-p2p-video-dvr-and-pause-suite','status':'NOT_RUN','reason':'This batch targets actual GUI installation and Wine/IDM HTTP transfer only.'})
