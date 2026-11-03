"""Actual official external download, verified publisher digest and visible native teaching marks."""
from pathlib import Path
import os,sys,time,json,subprocess,hashlib,re,shutil
import requests
from desktop_ready import safe_env,cdp,brave_path
from feature_cases import norm
ROOT=Path.cwd();HOME=Path.home()
def prepare(report,out,asset):
 import engine_chapter
 engine_chapter.prepare(report,out,asset)
 from idm_linux.config import IdmLinuxConfig
 from idm_linux.installer import execute_install_pipeline
 cfg=IdmLinuxConfig.load(create_if_missing=False);target=HOME/'Downloads/IDM-LINUX';target.mkdir(parents=True,exist_ok=True)
 with (Path(out)/'external-motor-prerequisite-offcamera.log').open('w') as log:
  result=execute_install_pipeline(project_root=Path(report['released_config_module_path']).parent,chosen_prefix=Path(cfg.wine_prefix),download_dir=target,skip_system_pkgs=True,language='tr',keep_wine_warm=True,create_desktop_icons=False,auto_open_browser=False,log_fn=lambda s:(log.write(s+'\n'),log.flush()))
 assert result.ok and result.idm_exe.exists(),'Actual motor prerequisite failed'
 # The original vendor can open its own welcome browser independently of
 # companion auto_open_browser. Close only this disposable runner's real
 # Brave windows before preparing the browser debug/profile session.
 time.sleep(2)
 vendor=[]
 for line in subprocess.check_output(['wmctrl','-lx'],text=True).splitlines():
  if 'brave' in line.casefold():
   wid=line.split()[0];vendor.append(line);subprocess.run(['wmctrl','-ic',wid],check=True)
 time.sleep(2)
 if vendor:
  subprocess.run(['pkill','-TERM','-x','brave'],check=False);time.sleep(1)
 report['vendor_welcome_closed_offcamera']={'actual_windows':vendor,'method':'Normal WM close; terminate remaining disposable Brave processes before normal warmup'}
 report['motor_prepared_offcamera']={'method':'Unmodified released installation pipeline, as already taught in preceding lesson','actual_executable':str(result.idm_exe),'sha256':hashlib.sha256(result.idm_exe.read_bytes()).hexdigest()};report['installation_scope']='Actual external official 7-Zip release download through released panel and native IDM, publisher bytes/SHA256 verification. Not a browser-extension, hoster matrix, install or speed test.'
 source=json.loads((ROOT/'capture/external-download-source.json').read_text());live=requests.get('https://api.github.com/repos/ip7z/7zip/releases/tags/26.05',timeout=30);live.raise_for_status();actual=next(a for a in live.json()['assets'] if a['name']==source['asset']['name']);assert all(actual[k]==source['asset'][k] for k in ['name','size','digest','browser_download_url']);report['external_source']=source

def run(report,out,screenshot,guard):
 import pyautogui
 from idm_linux.config import IdmLinuxConfig
 from idm_linux.wine_sender import build_wine_env
 out=Path(out);epoch=report['record_wallclock_start'];treepath=out/'engine-tk.json';events=[];cues=[];cases=[];app=None;observer=None;browser=None;stop=out/'wine-observer.stop';dump=out/'wine-native.json';target=HOME/'Downloads/IDM-LINUX'
 report.update({'phase':'official-external-download-illustrated-lesson','installation_mode':'external','installation_events':events,'tutorial_browser_events':events,'tutorial_audio_cues':cues,'runtime_marks':[],'functional_cases':cases,'full_functional_suite':'PARTIAL — one genuine external download, not all sources'})
 manifest={a['file']:a for a in json.loads((ROOT/'capture/external-audio-manifest.json').read_text())}
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
  start=time.time();duration=manifest[name]['duration'];cues.append({'audio_file':name,'video_offset_seconds':start-epoch,'duration_seconds':duration,'playback_rate':1.0,'chapter_title':'RESMÎ KAYNAKTAN GERÇEK İNDİRME','presentation_notes':[(3,7,title,body)]});screenshot(name[:-4]);save()
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
 def mark(w,kind,seconds=7,color='D29A12'):
  rect=w['rect'];x,y,ww,hh=rect;assert 8<=x and 94<=y and x+ww<1552 and y+hh<1032,('Measured teaching mark outside safe area',w)
  at=time.time()-epoch;report['runtime_marks'].append({'rect':rect,'kind':kind,'start':at,'end':at+seconds,'color':color,'source':w.get('geometry_source','Actual measured native control geometry'),'target':w.get('text','Measured teaching target')});save()
 def browser_source():
  nonlocal browser
  browser=subprocess.Popen([brave_path(),'--remote-debugging-port=19333','--remote-debugging-address=127.0.0.1','--no-first-run','--window-size=1380,870','--window-position=70,100','--app=https://www.7-zip.org/download.html'],env=safe_env(),stdout=(out/'external-source-browser.log').open('wb'),stderr=subprocess.STDOUT)
  deadline=time.monotonic()+80;page=None
  while time.monotonic()<deadline:
   try:
    pages=requests.get('http://127.0.0.1:19333/json/list',timeout=3).json();page=next((p for p in pages if p.get('type')=='page' and '7-zip.org/download.html' in p.get('url','')),None)
    if page:break
   except Exception:pass
   time.sleep(.5)
  assert page,'Actual official source page unavailable'
  def ev(js):
   r=cdp(page['webSocketDebuggerUrl'],'Runtime.evaluate',{'expression':js,'returnByValue':True});assert not r.get('error') and not r.get('result',{}).get('exceptionDetails');return r['result']['result'].get('value')
  while time.monotonic()<deadline:
   if ev('document.readyState')=='complete':break
   time.sleep(.3)
  lines=subprocess.check_output(['wmctrl','-lx'],text=True).splitlines();clients=[l.split(None,4)[0] for l in lines if 'brave' in l.casefold() and 'download' in l.casefold()];assert len(clients)==1,lines;client=clients[0];subprocess.run(['wmctrl','-ir',client,'-b','remove,maximized_vert,maximized_horz'],check=True);subprocess.run(['wmctrl','-ir',client,'-e','0,70,100,1380,870'],check=True);subprocess.run(['wmctrl','-ia',client],check=True);time.sleep(1)
  # Passive observation of real mouse events gives a measured CSS->screen map.
  ev("window.__filmReadOnlyPointer=null;document.addEventListener('pointermove',e=>{window.__filmReadOnlyPointer={x:e.clientX,y:e.clientY}},{capture:true,passive:true})")
  pyautogui.moveTo(700,400,duration=.3);time.sleep(.2);a=ev('window.__filmReadOnlyPointer');pyautogui.moveTo(1000,650,duration=.3);time.sleep(.2);b=ev('window.__filmReadOnlyPointer');assert a and b;sx=300/(b['x']-a['x']);sy=250/(b['y']-a['y']);assert abs(sx-sy)<.03;ox=700-a['x']*sx;oy=400-a['y']*sy
  js='''(()=>{const a=[...document.querySelectorAll('a')].find(e=>e.href===URL);if(!a)return null;const row=a.closest('tr'),v=[...document.querySelectorAll('strong,b')].find(e=>e.textContent.includes('Download 7-Zip 26.05'));function box(e){const r=e.getBoundingClientRect();return {text:e.textContent,href:e.href||null,rect:[r.x,r.y,r.width,r.height]}}return {link:box(a),architecture:box(row.children[2]),version:box(v)}})()'''.replace('URL',json.dumps(report['external_source']['asset']['browser_download_url']))
  data=ev(js);assert data and data['link']['href']==report['external_source']['asset']['browser_download_url'];assert '64-bit' in data['architecture']['text'];report['official_page_verified_link']=data['link']['href'];report['source_browser_client']=client
  for w in data.values():
   x,y,ww,hh=w['rect'];w['rect']=[ox+x*sx,oy+y*sy,ww*sx,hh*sy];w['geometry_source']='Actual official page DOM rectangle and passively measured real mouse transform'
  pyautogui.moveTo(1500,960,duration=.2);return data
 try:
  data=browser_source();screenshot('external-official-page')
  speak('ext-01.mp3','GERÇEK DIŞ KAYNAK',['Resmî sayfa ve gerçek dosya','Kurulum değil, indirme testi'],actions=[(5,lambda:mark(data['version'],'highlight',8)),(9,lambda:mark(data['architecture'],'ellipse',8))])
  speak('ext-02.mp3','DOĞRUDAN BAĞLANTI',['Resmî sayfa → yayın dosyası','Sürüm ≠ ondalık büyüklük'],actions=[(.2,lambda:mark(data['link'],'rectangle',10)),(14,lambda:mark(data['architecture'],'rounded_rectangle',7))])
  subprocess.run(['wmctrl','-ia',report['source_browser_client']],check=True);pyautogui.hotkey('alt','f4');time.sleep(1)
  cfg=IdmLinuxConfig.load(create_if_missing=False);assert cfg.find_idm_exe() and cfg.silent_mode is False
  env={**safe_env(),'FILM_WIDGET_DUMP':str(treepath),'FILM_CAPTURE_GEOMETRY':'1380x870+70+100','PYTHONPATH':str(ROOT/'capture/probe_site')};app=subprocess.Popen(['idm-linux','gui'],env=env,stdout=(out/'external-panel.log').open('wb'),stderr=subprocess.STDOUT);tree();choose('Genel Bakış')
  wine_env={k:v for k,v in build_wine_env(cfg).items() if not any(s in k.upper() for s in ['TOKEN','SECRET','PASSWORD']) and not k.startswith(('GITHUB_','ACTIONS_'))};to_win=lambda p:'Z:'+str(Path(p).resolve()).replace('/','\\');observer=subprocess.Popen(['wine',str(ROOT/'capture/wine_window_observer.exe'),to_win(dump),to_win(stop)],env=wine_env,stdout=(out/'native-observer.log').open('wb'),stderr=subprocess.STDOUT)
  source=report['external_source']['asset'];url=source['browser_download_url'];subprocess.run(['xclip','-selection','clipboard'],input=url,text=True,check=True)
  def paste_actual():
   choose('Panodan');entry=next(w for w in tree()['widgets'] if w.get('value')==url);report['actual_pasted_direct_url']=entry['value'];mark(entry,'highlight',8);screenshot('external-url-pasted')
  entry=next(w for w in tree()['widgets'] if w['class'] in ['Entry','TEntry'] and w['rect'][2]>500);mark(entry,'rounded_rectangle',9)
  speak('ext-03.mp3','ADRESİ KONTROL ET',['Sayfa başlığı değil dosya URL’si','Yapıştırmak ≠ indirmek'],actions=[(13,paste_actual)])
  entry=next(w for w in tree()['widgets'] if w.get('value')==url);button=next(w for w in tree()['widgets'] if w['class']=='TButton' and 'idm' in norm(w['text']) and abs(w['rect'][1]-entry['rect'][1])<16)
  speak('ext-04.mp3','MOTORA GÖNDER',['Gerçek IDM ile dış bağlantı','Küçük dosya hızlı tamamlanabilir'],actions=[(.2,lambda:mark(button,'freehand_loop',8))])
  click(button,'Actual external official direct link to native IDM');deadline=time.monotonic()+180;completed=None
  while time.monotonic()<deadline:
   dismiss_information();start=native_button(['indirmeyi baslat','start download','hemen indir','download now'])
   if start:click(start,'Actual native external Start Download',True)
   for f in target.rglob(source['name']):
    if f.is_file() and f.stat().st_size==source['size'] and hashlib.sha256(f.read_bytes()).hexdigest()==source['digest'].removeprefix('sha256:'):completed=f;break
   if completed:break
   time.sleep(.6)
  assert completed,'External download did not match publisher size/SHA256; do not play success audio';cases.append({'id':'official-external-native-idm-download','status':'PASS','requested_url':url,'local_path':str(completed),'bytes':completed.stat().st_size,'sha256':hashlib.sha256(completed.read_bytes()).hexdigest(),'publisher_digest':source['digest'],'localhost_fixture_used':False});report['verified_output']=cases[-1];screenshot('external-real-completed')
  roots=[w for w in native_rows() if w['handle']==w['root'] and any(t in norm(w['text']) for t in ['tamamlan','complete'])]
  actions=[(2,lambda:mark(roots[0],'rounded_rectangle',8))] if roots else []
  speak('ext-05.mp3','YAYIN BİLGİSİYLE EŞLEŞTİ',['1.663.506 bayt','SHA-256 birebir eşleşti'],actions=actions)
  subprocess.run(['gdbus','call','--session','--dest','org.freedesktop.FileManager1','--object-path','/org/freedesktop/FileManager1','--method','org.freedesktop.FileManager1.ShowItems',"['"+completed.as_uri()+"']",''],check=True,capture_output=True);time.sleep(2)
  windows=[l.split(None,3) for l in subprocess.check_output(['wmctrl','-l'],text=True).splitlines()];thunar=[p for p in windows if len(p)==4 and 'thunar' in p[3].casefold()];assert len(thunar)==1;wid=thunar[0][0];subprocess.run(['wmctrl','-ir',wid,'-b','remove,maximized_vert,maximized_horz'],check=True);subprocess.run(['wmctrl','-ir',wid,'-e','0,70,100,1380,870'],check=True);subprocess.run(['wmctrl','-ia',wid],check=True);time.sleep(1);pyautogui.hotkey('ctrl','2');time.sleep(1);pyautogui.moveTo(1500,960,duration=.2);screenshot('external-real-file-manager');report['actual_output_file_manager_opened']=True
  # WM client rectangle is measured, not a guessed file icon position.
  geo=subprocess.check_output(['xdotool','getwindowgeometry','--shell',wid],text=True);g=dict(l.split('=',1) for l in geo.splitlines() if '=' in l);frame={'rect':[int(g['X']),int(g['Y']),int(g['WIDTH']),int(g['HEIGHT'])],'text':'Actual Thunar file location window','geometry_source':'Actual X11 client geometry for real file manager'}
  speak('ext-06.mp3','DOSYANIN GERÇEK KONUMU',['Gerçek klasör ve seçili dosya','İndirmek ≠ kurmak'],actions=[(3,lambda:mark(frame,'rounded_rectangle',8))])
  subprocess.run(['wmctrl','-ia',wid],check=True);pyautogui.hotkey('alt','f4');time.sleep(.5);choose('Genel Bakış')
  speak('ext-07.mp3','DOĞRULANAN KAPSAM',['Resmî dış dosya indirildi','Diğer kaynaklar ayrı test'])
  kinds={m.get('kind') for m in report['runtime_marks']};assert {'ellipse','rectangle','rounded_rectangle','freehand_loop','highlight'}<=kinds,'Required native drawing variety missing';report['native_illustration_acceptance']={'status':'PASS','required_kinds':sorted(k for k in kinds if k),'coordinate_source':'Actual official DOM, native controls and OS window geometry; time-bounded and speech-aligned'};report['installed_gui']={'title':tree()['root_title'],'rect':tree()['root_rect']};save()
 finally:
  stop.touch()
  if observer:
   try:observer.wait(8)
   except subprocess.TimeoutExpired:observer.terminate()
  if app:app.terminate()
  save()

def finish(report,out):
 import installation_chapters
 installation_chapters.finish(report,out,audio_subdir='external_audio',target_filename='BELGESELSEMO-EGITIM-BOLUM-04-RESMI-DOSYA-CIZIMLI-TR.mp4',review_labels=['external-official-page','external-url-pasted','external-real-completed','external-real-file-manager'],lesson_mode='external')

 # Review actual rendered frames for every required drawing kind, not just
 # the final scene where annotations intentionally have already disappeared.
 from collections import Counter
 kinds={m['rendered_kind'] for m in report['presentation_audit']['native_teaching_marks']['rendered']};assert {'rectangle','rounded_rectangle','ellipse','freehand_loop','highlight'}<=kinds
 video=Path(out)/report['tutorial_delivery']['file'];proofs=Path(out)/'tutorial-receipts'
 for kind in sorted(kinds):
  m=next(m for m in report['presentation_audit']['native_teaching_marks']['rendered'] if m['rendered_kind']==kind)
  subprocess.run(['ffmpeg','-v','error','-ss',str(m['start']+min(2,(m['end']-m['start'])/2)),'-i',str(video),'-frames:v','1','-vf','scale=1280:-2','-q:v','3','-y',str(proofs/('external-mark-'+kind+'.jpg'))],check=True)
 shutil.copyfile(Path(out)/'native-teaching-marks-audit.json',proofs/'native-teaching-marks-audit.json')
