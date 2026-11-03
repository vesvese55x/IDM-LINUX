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
 # Install original IDM through the released SEMO UI, not a mocked backend.
 try:
  nav[0].click_input();time.sleep(1.5)
  for c in buttons():
   if ('tarayici' in norm(c.window_text()) or 'browser' in norm(c.window_text())):
    try:
     if c.get_check_state():c.click_input()
    except Exception:pass
  start=time.time();click_text('İşlemi Şimdi Başlat');deadline=time.monotonic()+420
  while time.monotonic()<deadline and not real_idm():time.sleep(2)
  idm=real_idm();screenshot('functional-original-idm-install')
  if idm:
   time.sleep(10)
   cases.append({'id':'official-idm-install-through-semo-gui','status':'PASS','installed_path':str(idm),'elapsed_seconds':time.time()-start,'license_note':'Official installation only; no trial reset or license bypass.'})
  else:
   texts=[]
   for x in main.descendants():
    try:
     if x.is_visible() and x.window_text():texts.append(x.window_text()[-4000:])
    except Exception:pass
   (out/'official-idm-install-visible-text.json').write_text(json.dumps(texts,ensure_ascii=False),encoding='utf-8')
   cases.append({'id':'official-idm-install-through-semo-gui','status':'FAIL','reason':'No actual IDMan.exe after420seconds; see visible installation log, not marked successful.'})
   checkpoint();return
 except Exception as e:
  cases.append({'id':'official-idm-install-through-semo-gui','status':'FAIL','reason':str(e)});checkpoint();return
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
   self.send_response(206 if header else 200);self.send_header('Accept-Ranges','bytes');self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(end-start+1));self.send_header('Content-Disposition','attachment; filename="film-proof.bin"')
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
   pause.click_input();time.sleep(2);a=stats['bytes_sent'];time.sleep(2);b=stats['bytes_sent'];screenshot('functional-download-paused');resume=None
   for c in progress.descendants():
    try:
     if c.is_visible() and norm(c.window_text()).strip('& ') in ['resume','devam et','devam','baslat']:resume=c;break
    except Exception:pass
   if resume:
    resumed=time.time();resume.click_input();cases.append({'id':'actual-idm-pause-resume','status':'PASS' if b-a<=32768 else 'FAIL','bytes_sent_during_paused_2_seconds':b-a,'resume_action_wallclock':resumed})
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
 cases.append({'id':'wine-idm-download-browser-p2p-functional-tests','status':'NOT_RUN','reason':'This stage only adds real language switching; Wine/IDM and network engine scenarios require the next dedicated batch.'})
