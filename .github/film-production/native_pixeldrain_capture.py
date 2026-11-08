"""Authorized public Pixeldrain: actual Brave page/download, manual URL Add in original IDM.
No automatic interception claim; no CAPTCHA/quota/authentication bypass, no renamed output.
Source URL is workflow input, never committed. The downloaded source media is NOT an artifact.
"""
import os,json,time,subprocess,signal,hashlib,re,sys,traceback,base64
import numpy as np
from pathlib import Path
from urllib.parse import urlsplit
import requests,websocket,cv2
from idm_linux.config import IdmLinuxConfig
from idm_linux.wine_sender import build_wine_env
from turkish_quality_gate import assert_clean
O=Path('out/film14-native-turkish/pixeldrain');O.mkdir(parents=True,exist_ok=True)
source=os.environ.get('FILM_SOURCE_PAGE_URL','');parts=urlsplit(source)
assert parts.scheme=='https' and parts.hostname in ['pixeldrain.net','pixeldrain.com'] and re.fullmatch(r'/u/[A-Za-z0-9]{8}',parts.path) and not parts.query and not parts.fragment,'Only an authorized ordinary public file-page URL; no credentials/query tokens'
file_id=parts.path.split('/')[-1]
cfg=IdmLinuxConfig.load();assert cfg.find_idm_exe() and (Path(cfg.wine_prefix)/'system.reg').is_file()
os.environ.update(build_wine_env(cfg));probe=Path('out/film14-native-turkish/native-turkish-probe.exe').resolve()
epoch=time.monotonic();events=[];recorder=None;browser=None
paced=os.environ.get('FILM_PACED_CAPTURE','false')=='true';recording_epoch=None
def wait_recording(seconds):
 if paced:
  remaining=recording_epoch+seconds-time.monotonic()
  if remaining>0:time.sleep(remaining)
result={'scope':'actual Pixeldrain public source; manual native URL Add, NOT automatic browser interception','finished_lesson':False,'final_film_export_allowed':False,'all_native_fonts_certified':False,'all_error_dialogues_verified':False,'source_video_included_in_artifact':False}
def save(name,value): (O/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))
def event(kind,**kw):
 events.append({'seconds':round(time.monotonic()-epoch,4),'event':kind,**kw});save('physical-actions.json',events)
def shot(tag):subprocess.run(['import','-window','root',str(O/(tag+'.png'))],check=True)
def physical(rect,kind):
 x1,y1,x2,y2=rect;assert 0<=x1<x2<=1920 and 0<=y1<y2<=1080,rect
 point=[int((x1+x2)/2),int((y1+y2)/2)];event(kind,rect=rect,physical_click=point)
 subprocess.run(['xdotool','mousemove',*map(str,point),'click','1'],check=True)
def keys(value):subprocess.run(['xdotool','key','--clearmodifiers',value],check=True)
def type_ascii(value):
 assert value.isascii();subprocess.run(['xdotool','type','--clearmodifiers','--delay','2',value],check=True)
def activate(needle):
 rows=[l for l in subprocess.check_output(['wmctrl','-lx'],text=True).splitlines() if needle.lower() in l.lower()]
 assert rows,('Actual window not found',needle)
 subprocess.run(['wmctrl','-ia',rows[0].split()[0]],check=True);time.sleep(.5)
class CDP:
 def __init__(self,target):self.ws=websocket.create_connection(target['webSocketDebuggerUrl'],origin='http://127.0.0.1:9222',timeout=20);self.n=0;self.events=[]
 def command(self,method,params=None):
  self.n+=1;seq=self.n;self.ws.send(json.dumps({'id':seq,'method':method,'params':params or {}}))
  while True:
   m=json.loads(self.ws.recv())
   if m.get('method','').startswith('Browser.download'):self.events.append(m)
   if m.get('id')==seq:
    assert 'error' not in m,m.get('error');return m.get('result',{})
 def read(self,expression):
  r=self.command('Runtime.evaluate',{'expression':expression,'returnByValue':True})
  assert 'exceptionDetails' not in r,r.get('exceptionDetails');return r['result'].get('value')
def targets():return requests.get('http://127.0.0.1:9222/json/list',timeout=5).json()
def connect_url(prefix):
 deadline=time.monotonic()+35
 while time.monotonic()<deadline:
  ts=[t for t in targets() if t.get('type')=='page' and t.get('url','').startswith(prefix)]
  if ts:return CDP(ts[0])
  time.sleep(.4)
 raise AssertionError('Actual browser target did not appear; stop, never paint a substitute page')
def measured_browser_rect(client,rect,tag):
 # Brave may intentionally report screenX/Y/outer dimensions unlike the real X11 window.
 # Match an actual read-only viewport screenshot to the actual desktop. Never move/paint DOM.
 metrics=client.command('Page.getLayoutMetrics')
 png=base64.b64decode(client.command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})['data'])
 (O/(tag+'-actual-viewport.png')).write_bytes(png)
 viewport=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
 css=metrics['cssLayoutViewport'];ratio=viewport.shape[1]/css['clientWidth']
 assert abs(ratio-1)<.01,'Non-unit real viewport scale; stop instead of guessing coordinates'
 shot(tag+'-desktop')
 screen=cv2.imread(str(O/(tag+'-desktop.png')))
 reference=viewport[:min(430,viewport.shape[0]),:min(780,viewport.shape[1])]
 _,score,_,origin=cv2.minMaxLoc(cv2.matchTemplate(screen,reference,cv2.TM_CCOEFF_NORMED))
 save(tag+'-measured-transform.json',{'css_metrics':metrics,'real_viewport_pixels':[viewport.shape[1],viewport.shape[0]],'measured_viewport_origin':origin,'actual_pixel_match':score,'DOM_target_rect':rect,'method':'unmodified actual DevTools viewport matched to actual X11 desktop, not spoofable window.screenX/Y'})
 assert score>.985,'No confidently matched actual viewport; do not click'
 return [rect[0]+origin[0],rect[1]+origin[1],rect[2]+origin[0],rect[3]+origin[1]]
def browser_controls(client,tag):
 values=client.read("""(()=>{let out=[];function walk(root){for(let e of root.querySelectorAll('*')){if(e.shadowRoot)walk(e.shadowRoot);if(e.matches('button,cr-button,cr-icon-button,[role=menuitem],[role=button]')){let r=e.getBoundingClientRect();let visible=r.width>0&&r.height>0&&(typeof e.checkVisibility!=='function'||e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}));if(visible)out.push({tag:e.tagName,id:e.id,label:e.getAttribute('aria-label')||e.getAttribute('title')||e.innerText||'',text:e.innerText||'',rect:[r.left,r.top,r.right,r.bottom]});}}}walk(document);return out;})()""")
 save(tag+'-actual-controls.json',values);return values
def find_browser_control(values,labels):
 matches=[v for v in values if v['label'].strip() in labels or v['text'].strip() in labels]
 unique={tuple(round(x,1) for x in v['rect']):v for v in matches}
 assert len(unique)==1,{'need_one_visible_control_named':labels,'actual_matches':matches}
 return next(iter(unique.values()))
def native(tag):
 shot(tag+'-before-probe')
 with (O/(tag+'-raw.txt')).open('wb') as out,(O/(tag+'-stderr.txt')).open('wb') as err:subprocess.run(['wine',str(probe)],stdout=out,stderr=err,check=True,timeout=30)
 controls=[];texts=[];titles=[]
 for line in (O/(tag+'-raw.txt')).read_text().splitlines():
  a=line.split('\t')
  if a[0] in ['TEXT','WINDOW','MENU']:
   s=bytes.fromhex(a[1]).decode('utf8');assert_clean(s);texts.append(s)
   if a[0]=='WINDOW':titles.append(s)
  if a[0]=='CONTROL' and len(a)>7:controls.append({'class':bytes.fromhex(a[2]).decode(),'style':int(a[3],16),'rect':[int(v) for v in a[5].split(',')],'visible':a[6]=='1','text':bytes.fromhex(a[7]).decode('utf8')})
 shot(tag);return controls,texts,titles
def button(cc,label):
 matches=[c for c in cc if c['visible'] and c['class']=='Button' and c['text'].replace('&','')==label]
 assert len(matches)==1,{'missing_unambiguous_actual_button':label,'matches':matches}
 physical(matches[0]['rect'],'native-button-'+label)
try:
 # Dismiss only the known first-run tip, never authentication/trial/unknown windows.
 for l in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
  if 'günün ipucu' in l.lower():subprocess.run(['wmctrl','-ia',l.split()[0]],check=True);keys('Escape');time.sleep(.3)
 assert 'günün ipucu' not in subprocess.check_output(['wmctrl','-l'],text=True).lower()
 activate('brave')
 wid=subprocess.check_output(['xdotool','getactivewindow'],text=True).strip()
 subprocess.run(['wmctrl','-ir',wid,'-b','remove,maximized_vert,maximized_horz'],check=True)
 subprocess.run(['wmctrl','-ir',wid,'-e','0,380,55,1480,930'],check=True);time.sleep(.5)
 keys('ctrl+l');type_ascii(source);keys('Return');event('actual-browser-navigation')
 browser=connect_url(source);time.sleep(7)
 page=browser.read("({title:document.title,text:document.body.innerText,api_endpoint:window.api_endpoint,file:window.viewer_data&&window.viewer_data.api_response,links:[...document.querySelectorAll('a')].map(a=>({text:a.innerText,href:a.href}))})")
 save('actual-browser-page.json',page);shot('01-actual-pixeldrain-page')
 assert page and page.get('file'),'No actual file page; stop for any verification/login/interstitial instead'
 meta=page['file'];save('source-public-file-metadata.json',{k:meta.get(k) for k in ['id','name','size','hash_sha256','mime_type','can_download','availability','availability_message','download_speed_limit']})
 assert meta.get('id')==file_id and meta.get('can_download') is True and not meta.get('availability'),'Source is unavailable or requires verification; never bypass'
 name=meta['name'];size=meta['size'];sha=meta['hash_sha256']
 assert Path(name).name==name and 0<size<=650*1024*1024 and re.fullmatch('[0-9a-f]{64}',sha),'Unsafe/unbounded/unchecked source'
 assert name in page['text'],'Actual source name must be visible on the real page'
 result.update(source_original_filename=name,expected_bytes=size,source_sha256=sha,actual_page_seen=True)
 save('actual-pixeldrain-review.json',result)
 # Use the real website Download button. Its genuine browser download supplies the URL.
 # Then stop this first browser transfer in the real downloads UI, before native URL Add.
 temporary=Path.home()/'film-browser-transfer';temporary.mkdir(exist_ok=True)
 browser.command('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(temporary),'eventsEnabled':True})
 candidates=browser.read("[...document.querySelectorAll('button,a')].map(e=>{let r=e.getBoundingClientRect();return {text:e.innerText.trim(),rect:[r.left,r.top,r.right,r.bottom],visible:r.width>0&&r.height>0}}).filter(x=>x.visible&&/^(download\\s*){1,2}$/i.test(x.text))")
 save('actual-download-button-dom.json',candidates);assert candidates,'Visible genuine Download button was not identified'
 # Keep only the actual source window visible over the genuine approved desktop.
 rows=subprocess.check_output(['wmctrl','-lx'],text=True).splitlines()
 save('actual-x11-windows-before-placement.json',rows)
 source_rows=[l for l in rows if 'brave' in l.lower() and name in l]
 assert len(source_rows)==1,'Require one actual source-page window'
 source_wid=source_rows[0].split()[0]
 for l in rows:
  if l.split()[0]!=source_wid and not any(x in l.lower() for x in ['xfce4-panel','xfdesktop']):subprocess.run(['xdotool','windowminimize',l.split()[0]],check=True)
 subprocess.run(['wmctrl','-ia',source_wid],check=True)
 subprocess.run(['wmctrl','-ir',source_wid,'-e','0,380,55,1480,930'],check=True);time.sleep(.7)
 log=(O/'capture.log').open('w');recorder=subprocess.Popen(['ffmpeg','-nostdin','-y','-v','warning','-f','x11grab','-draw_mouse','0','-s','1920x1080','-r','24','-i',os.environ['DISPLAY'],'-an','-c:v','libx264','-preset','veryfast','-crf','18','-threads','2',str(O/'uncut-pixeldrain-native.mp4')],stdout=log,stderr=subprocess.STDOUT)
 recording_epoch=time.monotonic()
 event('recording-started',cursor='OS cursor excluded; actual actions only');time.sleep(.8)
 if paced:
  save('paced-capture-scope.json',{'source_hold_until_seconds':25,'native_start_not_before_seconds':58.451746,'completion_hold_until_seconds':92.0,'method':'actual wall-clock dwell; no frozen frames, no speed changes, no simulated progress','voice_chunks_seconds':[28.637324,29.814422,30.963810]})
 # Re-read rects after actual window placement/reflow.
 candidates=browser.read("[...document.querySelectorAll('button,a')].map(e=>{let r=e.getBoundingClientRect();return {text:e.innerText.trim(),rect:[r.left,r.top,r.right,r.bottom],visible:r.width>0&&r.height>0}}).filter(x=>x.visible&&/^(download\\s*){1,2}$/i.test(x.text))")
 assert candidates,'Actual Download control disappeared after layout'
 wait_recording(25.0)
 physical(measured_browser_rect(browser,candidates[0]['rect'],'02-download-target'),'actual-pixeldrain-download-button')
 deadline=time.monotonic()+25;begin=None
 while time.monotonic()<deadline:
  browser.command('Runtime.evaluate',{'expression':'document.title','returnByValue':True})
  found=[e['params'] for e in browser.events if e['method']=='Browser.downloadWillBegin']
  if found:begin=found[-1];break
  time.sleep(.3)
 shot('02-browser-download-started');save('actual-browser-download-events.json',browser.events)
 assert begin,'Download did not start normally. Stop rather than bypassing a challenge or server restriction'
 actual_url=begin['url'];u=urlsplit(actual_url)
 assert u.scheme=='https' and u.hostname==parts.hostname and u.path=='/api/file/'+file_id and u.query in ['download','download='],'Unexpected download address/token; stop'
 keys('ctrl+j');time.sleep(2);downloads=connect_url('chrome://downloads')
 controls=browser_controls(downloads,'03-downloads')
 shot('03-browser-downloads-before-copy')
 copy=find_browser_control(controls,['İndirme bağlantısını kopyala','Copy download link'])
 physical(measured_browser_rect(downloads,copy['rect'],'03-copy-link-target'),'actual-browser-copy-download-link');time.sleep(.3)
 import tkinter as tk
 clipboard=tk.Tk();clipboard.withdraw()
 try:copied_url=clipboard.clipboard_get()
 finally:clipboard.destroy()
 assert copied_url==actual_url,'Only the genuine browser-copied public download URL may be pasted into native IDM'
 event('actual-browser-clipboard-url-verified')
 controls=browser_controls(downloads,'03-before-more-actions')
 more_matches=[v for v in controls if v['id']=='more-actions']
 if more_matches:
  more=find_browser_control(controls,['Diğer işlemler','Diğer eylemler','Diğer seçenekler','More actions','Other actions','More options'])
  physical(measured_browser_rect(downloads,more['rect'],'03-more-actions-target'),'actual-browser-more-actions');time.sleep(.3)
  shot('03-browser-actual-actions-menu');controls=browser_controls(downloads,'03-actual-actions-menu')
  cancel=find_browser_control(controls,['İptal','İndirmeyi iptal et','Cancel','Cancel download'])
  physical(measured_browser_rect(downloads,cancel['rect'],'03-cancel-target'),'actual-browser-download-cancel');time.sleep(.7)
  shot('04-browser-transfer-cancelled');save('actual-browser-download-events-after-cancel.json',browser.events)
 else:
  # A genuinely completed browser download has no Cancel menu. Never fabricate one.
  browser_file=temporary/name
  assert browser_file.is_file() and browser_file.stat().st_size==size,'No menu is not proof of completion'
  browser_sha=hashlib.file_digest(browser_file.open('rb'),'sha256').hexdigest()
  assert browser_sha==sha,'Completed browser copy must match public source before skipping cancellation'
  event('browser-download-already-completed-no-cancel-possible',bytes=size,sha256=browser_sha)
  save('browser-completed-before-cancel.json',{'actual_file':str(browser_file),'original_filename':name,'bytes':size,'sha256':browser_sha,'real_browser_control_ids':[c['id'] for c in controls],'physical_cancel_claimed':False})
  shot('04-browser-already-completed')
 keys('ctrl+w');time.sleep(.5)
 # Direct ordinary public URL Add is deliberately manual, not browser interception.
 activate('Internet Download Manager');shot('05-native-before-url-add')
 im=cv2.imread(str(O/'05-native-before-url-add.png'));icon=cv2.imread('.github/film-production/actual-native-url-icon.png');_,score,_,pos=cv2.minMaxLoc(cv2.matchTemplate(im,icon,cv2.TM_CCOEFF_NORMED));assert score>.985,'Unverified native icon'
 physical([pos[0],pos[1],pos[0]+icon.shape[1],pos[1]+icon.shape[0]],'native-url-add-icon');time.sleep(.5)
 cc,tt,ww=native('06-native-url-add');assert 'İndirilecek yeni adresi girin' in ww
 edits=[c for c in cc if c['visible'] and c['class']=='Edit' and not c['style']&0x08000000];assert len(edits)==1
 physical(edits[0]['rect'],'native-address-input');keys('ctrl+a');keys('ctrl+v');event('actual-native-paste-from-browser-clipboard');button(cc,'Tamam');time.sleep(3)
 cc,tt,ww=native('07-native-file-information');assert any('Dosya İndirme Bilgisi' in w for w in ww)
 paths=[c for c in cc if c['visible'] and c['class'] in ['Edit','ComboBox'] and name in c['text'] and not c['text'].startswith(('http:','https:'))];assert paths,'Original source filename must be present unchanged in a native filename/path field'
 save('native-original-filename-controls.json',paths);event('native-original-filename-read-back',name=name)
 time.sleep(2);wait_recording(58.451746);button(cc,'İndirmeyi Başlat')
 completed=False;progress=False;stages=[];deadline=time.monotonic()+720
 for n in range(180):
  time.sleep(.4 if n<10 else 3)
  cc,tt,ww=native('transfer-%03d'%n);stage={'seconds':round(time.monotonic()-epoch,3),'titles':ww,'texts':tt};stages.append(stage)
  progress=progress or any(c['visible'] and c['class']=='Button' and 'Duraklat' in c['text'] for c in cc)
  completed=any('tamamland' in w.replace('İ','i').lower() for w in ww)
  save('native-transfer-stages.json',stages)
  if completed:break
  assert any('Duraklat' in c['text'] for c in cc),'Unexpected native dialog or missing progress; stop without declaring success'
  assert time.monotonic()<deadline,'Bounded download wait elapsed; no quota/protection bypass or success claim'
 assert completed and progress,'Actual native progress and completion must both be seen'
 files=[p for root in [Path.home()/'Downloads',Path(cfg.download_dir),Path(cfg.wine_prefix)/'drive_c/users'] if root.exists() for p in root.rglob(name) if p.is_file() and p.stat().st_size==size]
 verified=[p for p in files if hashlib.file_digest(p.open('rb'),'sha256').hexdigest()==sha];assert verified,'Unchanged filename, exact bytes and source SHA256 must all match'
 ff=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration,size:stream=codec_type,codec_name,width,height','-of','json',str(verified[0])],text=True,capture_output=True,check=True)
 save('downloaded-media-probe.json',json.loads(ff.stdout))
 manifest=json.loads(Path('out/film14-native-turkish/original-vendor-payload-manifest.json').read_text())
 vendor=cfg.find_idm_exe().parent
 unchanged=all((vendor/f).is_file() and hashlib.file_digest((vendor/f).open('rb'),'sha256').hexdigest()==digest for f,digest in manifest['files'].items() if Path(f).suffix.lower() in ['.exe','.dll','.sys'])
 assert unchanged,'Vendor binary changed'
 result.update(native_completion_window_seen=completed,native_progress_pause_control_seen=progress,original_filename_on_disk=True,downloaded_files=[str(p) for p in verified],downloaded_sha256_match=True,vendor_binaries_unchanged=unchanged,browser_interception_verified=False,manual_url_add_route_verified=True,actual_native_transfer_verified=True)
 save('actual-pixeldrain-review.json',result);shot('08-native-completion-verified');wait_recording(92.0);time.sleep(3)
except Exception as e:
 if browser is not None:
  for ev in browser.events:
   if ev.get('method')=='Browser.downloadWillBegin':
    try:browser.command('Browser.cancelDownload',{'guid':ev['params']['guid']})
    except Exception:pass
 result.update(failure_type=type(e).__name__,failure=str(e),actual_native_transfer_verified=False)
 save('actual-pixeldrain-review.json',result);shot('stopped-on-real-state');raise
finally:
 if recorder is not None:recorder.send_signal(signal.SIGINT);recorder.wait(timeout=30)
 if browser is not None:browser.ws.close()
 save('physical-actions.json',events)
