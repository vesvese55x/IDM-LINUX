"""Real Linux GUI motor installation and controlled HTTP pause/resume lesson."""
from pathlib import Path
import os,sys,time,json,subprocess,hashlib,threading,re,shutil
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from desktop_ready import safe_env
from feature_cases import norm
ROOT=Path.cwd();HOME=Path.home()
def prepare(report,out,asset):
 import installation_chapters
 installation_chapters.prepare(report,out,asset)
 package=report['installation_asset']['local_path']
 with (Path(out)/'panel-prerequisite-offcamera.log').open('wb') as f:subprocess.run(['sudo','-n','apt-get','install','-y',package],env=safe_env(),stdout=f,stderr=f,check=True)
 module=next(Path('/opt/idm-linux').rglob('idm_linux/config.py'));report['released_config_module_path']=str(module);sys.path.insert(0,str(module.parent.parent))
 from idm_linux.config import IdmLinuxConfig
 cfg=IdmLinuxConfig.load(create_if_missing=False);assert cfg.find_idm_exe() is None,'Motor is not fresh'
 # Off-camera observer self-test in an isolated throwaway Wine prefix. This
 # is harness validation only and is never presented as an IDM functional test.
 smoke=Path(os.environ['RUNNER_TEMP'])/'observer-smoke';smoke.mkdir(exist_ok=True);state=smoke/'state.json';stopfile=smoke/'stop';smokeenv={**safe_env(),'WINEPREFIX':str(smoke/'prefix'),'WINEDEBUG':'-all','WINEDLLOVERRIDES':'mscoree,mshtml='}
 winpath=lambda p:'Z:'+str(p.resolve()).replace('/','\\')
 with (Path(out)/'observer-selftest.log').open('wb') as log:
  proc=subprocess.Popen(['wine',str(ROOT/'capture/wine_window_observer.exe'),winpath(state),winpath(stopfile),'selftest'],env=smokeenv,stdout=log,stderr=log);deadline=time.monotonic()+90;observed=None
  while time.monotonic()<deadline:
   if state.exists():
    try:
     observed=json.loads(state.read_text())
     if any(w['class'].casefold()=='button' and w['text']=='Native button' and w['rect'][2]>10 for w in observed['widgets']):break
    except Exception:pass
   if proc.poll() is not None:break
   time.sleep(.5)
  stopfile.touch();proc.wait(15);assert observed and any(w['text']=='Native button' for w in observed['widgets']),'Readonly observer native self-test failed before recording'
 report['native_observer_offcamera_selftest']={'status':'PASS','method':'Actual diagnostic Win32 test window/button in isolated prefix, not an IDM outcome','subsystem':'GUI/no console'}
 report['engine_initially_absent']=True;report['engine_prerequisites']='Control-panel DEB, Wine binaries and system tools prepared off camera; actual motor/prefix installation is performed by released GUI on camera.'
 report['installation_scope']='Real released GUI installs Wine/IDM motor; controlled owned local HTTP download/pause/resume/hash only. External hosters/browser/YouTube/P2P NOT_RUN.'

def run(report,out,screenshot,guard):
 import pyautogui
 from idm_linux.config import IdmLinuxConfig
 from idm_linux.wine_sender import build_wine_env
 out=Path(out);epoch=report['record_wallclock_start'];treepath=out/'engine-tk.json';events=[];cues=[];cases=[];app=None;observer=None;server=None;stop=out/'wine-observer.stop';dump=out/'wine-native.json'
 report.update({'phase':'real-gui-engine-transfer-lesson','installation_mode':'engine','installation_events':events,'tutorial_browser_events':events,'tutorial_audio_cues':cues,'runtime_marks':[],'functional_cases':cases,'full_functional_suite':'PARTIAL — selected motor and owned HTTP fixture only'})
 manifest={a['file']:a for a in json.loads((ROOT/'capture/engine-audio-manifest.json').read_text())}
 def save():(out/'probe-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 def tree(timeout=30):
  deadline=time.monotonic()+timeout
  while time.monotonic()<deadline:
   try:
    d=json.loads(treepath.read_text());r=d['root_rect']
    if d['root_viewable'] and r[2:]==[1380,870] and 30<r[0]<150 and 70<r[1]<145 and time.time()-d['time']<3:return d
   except Exception:pass
   time.sleep(.4)
  raise RuntimeError('Stable real Tk control panel unavailable')
 def click(w,label,native=False,park=True):
  x,y,ww,hh=w['rect'];cx=x+ww/2;cy=y+hh/2;assert 0<cx<1920 and 0<cy<1032
  if not native:
   d=tree();clients=[]
   for line in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
    parts=line.split(None,3)
    if len(parts)==4 and parts[3]==d['root_title']:clients.append(parts[0])
   assert len(clients)==1,'Actual managed Tk client window is ambiguous';subprocess.run(['wmctrl','-ia',clients[0]],check=True);time.sleep(.3)
  pyautogui.moveTo(cx,cy,duration=.45);at=time.time()-epoch;events.append({'action':'real_mouse_click','target':label,'x':cx,'y':cy,'video_offset_seconds':at,'source':w.get('geometry_source','Read-only native Win32 geometry') if native else 'Actual released Tk widget tree'});pyautogui.click();
  if x>=8 and y>=80 and x+ww<1544 and y+hh<1024:report['runtime_marks'].append({'rect':w['rect'],'start':at-.2,'end':at+1.6,'color':'D29A12' if native else '68DAD1','source':events[-1]['source'],'target':label})
  time.sleep(.8)
  if park:pyautogui.moveTo(1500,960,duration=.2)
 def set_entry(w,value,label):
  click(w,label,park=False);d=tree();report.setdefault('real_entry_focus_checks',[]).append({'target':w['path'],'actual_focus':d.get('focus_path'),'before':next((n.get('value') for n in d['widgets'] if n['path']==w['path']),None)})
  assert d.get('focus_path')==w['path'],'Actual Tk entry never received keyboard focus'
  pyautogui.press('home');pyautogui.keyDown('shift');pyautogui.press('end');pyautogui.keyUp('shift');pyautogui.press('backspace');pyautogui.write(value,interval=.02);time.sleep(.6)
  actual=next(n.get('value') for n in tree()['widgets'] if n['path']==w['path']);assert actual==value,'Actual keyboard input did not set the intended field: '+str(actual)
  pyautogui.moveTo(1500,960,duration=.2)
 def choose(part,classes=('Button','TButton')):
  candidates=[w for w in tree()['widgets'] if norm(part) in norm(w.get('text','')) and w['class'] in classes and w.get('state')!='disabled'];assert candidates,'Actual GUI control missing: '+part;click(candidates[0],part);return candidates[0]
 def speak(name,title,body,actions=None):
  start=time.time();duration=manifest[name]['duration'];cues.append({'audio_file':name,'video_offset_seconds':start-epoch,'duration_seconds':duration,'playback_rate':1.0,'chapter_title':'MOTOR VE GERÇEK AKTARIM','presentation_notes':[(3,7,title,body)]});screenshot(name[:-4]);save()
  for at,fn in actions or []:time.sleep(max(0,start+at-time.time()));fn()
  time.sleep(max(0,start+duration+.8-time.time()))
 def native_rows():
  try:
   if time.time()-dump.stat().st_mtime>4:return []
   return json.loads(dump.read_text(encoding='utf-8'))['widgets']
  except Exception:return []
 def native_button(labels):
  for w in native_rows():
   if w['enabled'] and w['class'].casefold()=='button' and norm(w['text']).replace('&','').strip(' .') in labels:return w
  return None
 def resume_from_actual_toolbar():
  # Some IDM builds leave the progress Pause disabled and expose Resume in
  # their main toolbar. Minimize the real paused dialog; do not cancel/relaunch.
  rows=native_rows();main=next(w for w in rows if w['handle']==w['root'] and w['text'].startswith('Internet Download Manager'));managed=[]
  for line in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
   parts=line.split(None,3)
   if len(parts)==4:managed.append(parts)
  for parts in managed:
   if 'BELGESELSEMO-ORNEK-DOSYA' in parts[3]:subprocess.run(['xdotool','windowminimize',parts[0]],check=True)
  client=next(parts[0] for parts in managed if parts[3]==main['text']);subprocess.run(['wmctrl','-ia',client],check=True);time.sleep(1)
  listing=next(w for w in native_rows() if w['root']==main['handle'] and w['class']=='SysListView32');assert listing.get('item_count')==1,'Resume toolbar requires the one owned fixture item';click(listing,'Focus actual one-item IDM download list',True);pyautogui.press('home');time.sleep(1)
  listing=next(w for w in native_rows() if w['handle']==listing['handle']);assert listing.get('selected_count')==1,'Actual file row not selected'
  toolbar=next(w for w in native_rows() if w['root']==main['handle'] and w['class']=='ToolbarWindow32');x,y,ww,hh=toolbar['rect'];image=pyautogui.screenshot().crop((x,y,x+ww,y+hh)).resize((ww*3,hh*3));path=out/'actual-toolbar-ocr.png';image.save(path)
  result=subprocess.run(['tesseract',str(path),'stdout','-l','tur+eng','--psm','6','tsv'],capture_output=True,text=True,check=True)
  import csv,io
  (out/'actual-toolbar-ocr.tsv').write_text(result.stdout);words=list(csv.DictReader(io.StringIO(result.stdout),delimiter='\t'));hit=next((w for w in words if norm(w.get('text','')).replace('&','').replace(' ','').strip() in ['devam','devamet','resume'] and float(w['conf'])>45),None);assert hit,'Actual visible Resume toolbar label not recognized';rect=[x+int(hit['left'])/3,y+int(hit['top'])/3,int(hit['width'])/3,int(hit['height'])/3];report['resume_alternative_ui']={'method':'Actual main toolbar; one file selected; measured OCR label bounds','label':hit['text'],'confidence':float(hit['conf']),'rect':rect};return {'rect':rect,'geometry_source':'Actual toolbar screenshot OCR bounds, corroborated by native toolbar rectangle and single selected fixture item'}
 def dismiss_information():
  rows=native_rows();roots={w['handle']:w for w in rows if w['handle']==w['root']}
  for w in rows:
   parent=roots.get(w['root'],{});text=norm(parent.get('text',''))
   allowed=any(t in text for t in ['ipucu','tip of the day','trial','deneme'])
   if allowed and w['class'].casefold()=='button' and norm(w['text']).replace('&','').strip(' .') in ['kapat','close','tamam','ok']:
    click(w,'Read/close ordinary trial or tip information',True);return
 def wait_native_button(labels,timeout=90,confirm_download=False):
  deadline=time.monotonic()+timeout
  while time.monotonic()<deadline:
   w=native_button(labels)
   if w:return w
   dismiss_information()
   if confirm_download:
    button=native_button(['indirmeyi baslat','start download','hemen indir','download now'])
    if button:click(button,'Actual IDM Start Download',True)
   time.sleep(.4)
  (out/'native-last-state.json').write_text(json.dumps(native_rows(),ensure_ascii=False,indent=2));raise RuntimeError('Actual native IDM control unavailable: '+str(labels))
 try:
  env={**safe_env(),'FILM_WIDGET_DUMP':str(treepath),'FILM_CAPTURE_GEOMETRY':'1380x870+70+100','PYTHONPATH':str(ROOT/'capture/probe_site')}
  app=subprocess.Popen(['idm-linux','gui'],env=env,stdout=(out/'engine-panel.log').open('wb'),stderr=subprocess.STDOUT);tree();time.sleep(1);choose('Kurulum')
  widgets=tree()['widgets'];entries=[w for w in widgets if w['class'] in ['Entry','TEntry'] and w['rect'][2]>300];assert entries
  target=HOME/'Downloads/IDM-LINUX';target.mkdir(parents=True,exist_ok=True);entry=min(entries,key=lambda w:w['rect'][1]);set_entry(entry,str(target),'Actual installation download-folder input')
  speak('engine-01.mp3','PANEL ≠ MOTOR',['Wine araçları önceden hazır','Motor kurulumu şimdi yapılır'])
  for w in tree()['widgets']:
   if w['class']=='TCheckbutton' and w.get('checked') and any(k in norm(w['text']) for k in ['tarayici','browser']):click(w,'Disable automatic browser opening for this lesson')
  speak('engine-02.mp3','İKİ AYRI YOL',['Wine ortamı ≠ dosya hedefi','Tarayıcı onayı ayrı ders'])
  choose('İşlemi Şimdi Başlat');begin=time.time();deadline=time.monotonic()+600;complete=False
  while time.monotonic()<deadline:
   cfg=IdmLinuxConfig.load(create_if_missing=False);idm=cfg.find_idm_exe();d=tree();log='\n'.join(w.get('value','') for w in d['widgets'] if w['class']=='Text');(out/'engine-real-installation.log').write_text(log)
   if idm and any(w.get('text','').strip()=='100%' for w in d['widgets']):complete=True;break
   if any('kurulum sirasinda hata' in norm(w.get('text','')) for w in d['widgets']):break
   time.sleep(1.5)
  assert complete,'Actual motor GUI installation failed';report['actual_download_directory_after_install']=cfg.download_dir;assert Path(cfg.download_dir).resolve()==target.resolve(),'GUI target folder not applied'
  # The original vendor may open its own welcome page independently of the
  # companion checkbox. Close that real visible page with normal keyboard input.
  for line in subprocess.check_output(['wmctrl','-lx'],text=True).splitlines():
   if 'brave' in line.casefold() and 'internet download manager' in line.casefold():
    wid=line.split()[0];subprocess.run(['wmctrl','-ia',wid],check=True);time.sleep(.4);events.append({'action':'real_keyboard_close_vendor_welcome','video_offset_seconds':time.time()-epoch});pyautogui.hotkey('alt','f4');time.sleep(1)
  cases.append({'id':'real-released-gui-motor-installation','status':'PASS','actual_idm_path':str(idm),'wine_prefix':cfg.wine_prefix,'download_dir':cfg.download_dir,'elapsed_seconds':time.time()-begin,'actual_idm_sha256':hashlib.sha256(idm.read_bytes()).hexdigest()});report['linux_wine_config']={'wine_prefix':cfg.wine_prefix,'download_dir':cfg.download_dir,'actual_idm_path':str(idm)};screenshot('engine-verified-installed')
  wine_env={**build_wine_env(cfg)};wine_env={k:v for k,v in wine_env.items() if not any(s in k.upper() for s in ['TOKEN','SECRET','PASSWORD']) and not k.startswith(('GITHUB_','ACTIONS_'))}
  to_win=lambda p:'Z:'+str(Path(p).resolve()).replace('/','\\')
  observer=subprocess.Popen(['wine',str(ROOT/'capture/wine_window_observer.exe'),to_win(dump),to_win(stop)],env=wine_env,stdout=(out/'native-observer.log').open('wb'),stderr=subprocess.STDOUT)
  # Read the actual prefix registry store without spawning a competing Wine
  # reg.exe. A not-yet-flushed snapshot is BLOCKED, not a claimed locale pass.
  regfile=Path(cfg.wine_prefix)/'system.reg';regtext=regfile.read_text(errors='replace') if regfile.exists() else '';key=r'[System\\CurrentControlSet\\Control\\Nls\\CodePage]';section=regtext.split(key,1)[1].split('\n[',1)[0] if key in regtext else '';matched=re.search(r'^"ACP"="(\d+)"',section,re.M);codepage=matched.group(1) if matched else None
  report['wine_turkish_acp']={'method':'Read-only actual Wine registry store','path':str(regfile),'value':codepage};cases.append({'id':'wine-turkish-codepage','status':'PASS' if codepage=='1254' else 'BLOCKED','codepage':codepage,'reason':None if codepage=='1254' else 'No conclusive flushed ACP snapshot; live GUI Turkish glyphs require visual review'})
  speak('engine-03.mp3','KURULUM DOĞRULANDI',['Gerçek uygulama dosyası var','İndirme henüz kanıtlanmadı'])
  choose('Yakalama')
  def configure_silent():
   # All pages are built at startup; re-enter the actual destination in this
   # settings form instead of allowing its older value to overwrite the new one.
   paths=sorted([w for w in tree()['widgets'] if w['class'] in ['Entry','TEntry'] and str(w.get('value','')).startswith(str(HOME))],key=lambda w:w['rect'][1]);assert len(paths)>=2,'Actual settings path fields missing';set_entry(paths[1],str(target),'Verify and retain actual settings download directory')
   for w in tree()['widgets']:
    if w['class']=='TCheckbutton' and any(s in norm(w['text']) for s in ['sessiz','silent']) and w.get('checked'):click(w,'Disable silent transfer to show actual progress')
   choose('Kaydet');time.sleep(.5)
   for w in tree()['widgets']:
    if w['class'] in ['Button','TButton'] and norm(w['text']).strip() in ['ok','tamam'] and w.get('toplevel')!='.':click(w,'Acknowledge actual settings saved dialog');break
   saved=IdmLinuxConfig.load(create_if_missing=False);assert saved.silent_mode is False;assert Path(saved.download_dir).resolve()==target.resolve(),'Saved target folder differs from shown destination'
  speak('engine-04.mp3','GÖRÜNÜR AKTARIM',['Sessiz gönderim kapalı','Ayarları kaydet'],actions=[(10,configure_silent)])
  choose('Genel Bakış');choose('Ana Penceresini');time.sleep(5);dismiss_information();screenshot('engine-original-idm-visible');assert native_rows(),'Read-only observer did not find actual IDMan.exe windows'
  # Own deterministic bytes. Global rate is deliberately limited, not an ISP benchmark.
  payload=(bytes(range(251))*((64*1024*1024)//251+1))[:64*1024*1024];expected=hashlib.sha256(payload).hexdigest();stats={'bytes_sent':0,'requests':[],'rate_bytes_per_second':262144};lock=threading.Lock();slot=[time.monotonic()]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def respond(self,body):
    start,end=0,len(payload)-1;header=self.headers.get('Range','')
    if header.startswith('bytes='):
     a,b=header[6:].split('-',1);start=int(a or 0);end=min(end,int(b) if b else end)
    with lock:stats['requests'].append({'time':time.time(),'method':self.command,'range':header,'user_agent':self.headers.get('User-Agent','')})
    if start>=len(payload):self.send_response(416);self.end_headers();return
    self.send_response(206 if header else 200);self.send_header('Accept-Ranges','bytes');self.send_header('Last-Modified','Tue, 03 Nov 2026 00:00:00 GMT');self.send_header('ETag','"owned-film-proof-64MiB-v1"');self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(end-start+1));self.send_header('Content-Disposition','attachment; filename="BELGESELSEMO-ORNEK-DOSYA.bin"')
    if header:self.send_header('Content-Range',f'bytes {start}-{end}/{len(payload)}')
    self.end_headers()
    if not body:return
    try:
     for offset in range(start,end+1,16384):
      chunk=payload[offset:min(end+1,offset+16384)]
      with lock:due=slot[0];slot[0]=max(slot[0],time.monotonic())+len(chunk)/stats['rate_bytes_per_second']
      time.sleep(max(0,due-time.monotonic()));self.wfile.write(chunk);self.wfile.flush()
      with lock:stats['bytes_sent']+=len(chunk)
    except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError,OSError):pass
   def do_HEAD(self):self.respond(False)
   def do_GET(self):self.respond(True)
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;threading.Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_address[1]}/BELGESELSEMO-ORNEK-DOSYA.bin'
  choose('Genel Bakış');subprocess.run(['xclip','-selection','clipboard'],input=url,text=True,check=True);choose('Panodan');assert any(w.get('value')==url for w in tree()['widgets']),'Actual clipboard URL differs';report['controlled_source']={'url':url,'ownership':'Locally generated deterministic fixture, not a hoster/browser test','bytes':len(payload),'expected_sha256':expected,'artificial_rate_limit':262144}
  speak('transfer-01.mp3','KONTROLLÜ ÖRNEK',['Kendi yerel test sunucumuz','İnternet hız testi değil'])
  entry=next(w for w in tree()['widgets'] if w.get('value')==url);button=next(w for w in tree()['widgets'] if w['class']=='TButton' and 'idm' in norm(w['text']) and abs(w['rect'][1]-entry['rect'][1])<16);click(button,'Send actual fixture URL to IDM')
  pause=wait_native_button(['duraklat','pause'],90,True);assert stats['bytes_sent']>0,'No actual bytes transferred';screenshot('transfer-real-progress')
  speak('transfer-02.mp3','GERÇEK İLERLEME',['Motor veri alıyor','Tamamlandı ≠ dosya sağlam'])
  pause=wait_native_button(['duraklat','pause'],10);click(pause,'Actual native IDM Pause',True);pause_clicked=time.time();time.sleep(3)
  with lock:a=stats['bytes_sent']
  time.sleep(3)
  with lock:b=stats['bytes_sent']
  assert b-a==0,'Bytes still advanced during settled 3-second pause';cases.append({'id':'real-linux-idm-pause','status':'PASS','bytes_in_settled_3_seconds':b-a,'pause_action_time':pause_clicked});screenshot('transfer-real-paused')
  speak('transfer-03.mp3','DURAKLATMA KANITI',['En az 3 saniye ölçüldü','Gönderilen bayt artmadı'])
  resume=native_button(['devam et','devam','baslat','resume','start'])
  if resume is None:resume=resume_from_actual_toolbar()
  resume_clicked=time.time();click(resume,'Actual native IDM Resume',True)
  with lock:stats['rate_bytes_per_second']=2*1024*1024
  deadline=time.monotonic()+180;completed=None
  while time.monotonic()<deadline:
   for f in target.rglob('BELGESELSEMO-ORNEK-DOSYA*'):
    if f.is_file() and f.stat().st_size==len(payload) and hashlib.sha256(f.read_bytes()).hexdigest()==expected:completed=f;break
   if completed:break
   dismiss_information();time.sleep(1)
  assert completed,'Actual output did not match expected size and SHA256';after=[r for r in stats['requests'] if r['time']>=resume_clicked and r['method']=='GET' and r['range'].startswith('bytes=') and int(r['range'][6:].split('-')[0] or 0)>0];assert after,'No nonzero actual resume Range request';report['verified_output']={'path':str(completed),'bytes':completed.stat().st_size,'sha256':hashlib.sha256(completed.read_bytes()).hexdigest(),'expected_sha256':expected};cases.append({'id':'real-linux-idm-resume-and-output-hash','status':'PASS','nonzero_range_requests_after_resume':len(after),**report['verified_output']});screenshot('transfer-real-completed')
  speak('transfer-04.mp3','DOSYA DOĞRULANDI',['Boyut ve SHA-256 eşleşti','Gerçek Range isteği var'])
  uri=completed.as_uri();subprocess.run(['gdbus','call','--session','--dest','org.freedesktop.FileManager1','--object-path','/org/freedesktop/FileManager1','--method','org.freedesktop.FileManager1.ShowItems',"['"+uri+"']",''],check=True,capture_output=True);time.sleep(2);report['actual_output_file_manager_opened']=True;screenshot('transfer-output-in-real-file-manager')
  speak('transfer-05.mp3','GERÇEK HEDEF DOSYA',['Adı, yolu ve boyutu kontrol et','Özet doğrulaması raporda'])
  choose('Genel Bakış');speak('engine-wrap.mp3','KANITLARI AYIR',['Bu örnek aktarım doğrulandı','Diğer kaynaklar ayrı test'])
  report['installed_gui']={'title':tree()['root_title'],'rect':tree()['root_rect'],'visible_widgets':len(tree()['widgets']),'overview_navigation_verified':True};save()
 finally:
  stop.touch()
  if observer:
   try:observer.wait(8)
   except Exception:observer.terminate()
  if server:server.shutdown();server.server_close()
  if 'stats' in locals():(out/'engine-http-evidence.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2))
  if app and app.poll() is None:app.terminate()

def finish(report,out):
 import installation_chapters as shared
 shared.finish(report,out,lesson_mode='engine',audio_subdir='engine_audio',target_filename='BELGESELSEMO-EGITIM-BOLUM-03-MOTOR-VE-AKTARIM-TR.mp4',review_labels=['engine-verified-installed','engine-original-idm-visible','transfer-real-progress','transfer-real-paused','transfer-real-completed','transfer-output-in-real-file-manager'])
