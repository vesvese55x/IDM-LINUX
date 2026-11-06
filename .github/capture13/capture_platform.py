import os,time,json,subprocess,signal
from pathlib import Path
from playwright.sync_api import sync_playwright
site=os.environ.get('CAPTURE_SITE','youtube')
R=Path('out')/site;R.mkdir(parents=True,exist_ok=True)
url=os.environ.get('CAPTURE_URL','https://www.youtube.com/watch?v=LXb3EKWsInQ')
min_height=int(os.environ.get('MIN_HEIGHT','144'))
events=[];epoch=time.time();rec=None

def event(name,**kw):
 events.append({'seconds':round(time.time()-epoch,3),'event':name,**kw});(R/'events.json').write_text(json.dumps(events,indent=2));print(name,flush=True)
def windows():
 return subprocess.run(['wmctrl','-lG'],capture_output=True,text=True).stdout
try:
 rec=subprocess.Popen(['ffmpeg','-nostdin','-y','-v','warning','-f','x11grab','-draw_mouse','1','-video_size','1920x1080','-framerate','24','-i',os.environ['DISPLAY'],'-an','-c:v','libx264','-preset','veryfast','-crf','20','-bf','0',str(R/'uncut.mp4')],stdout=open(R/'capture.log','w'),stderr=subprocess.STDOUT)
 with sync_playwright() as p:
  b=p.chromium.connect_over_cdp('http://127.0.0.1:9222');page=b.contexts[0].new_page();event('browser_navigation',url=url)
  page.goto(url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(7000)
  page.get_by_text('Bu videoyu indir',exact=False).first.click(timeout=45000)
  refresh=page.get_by_text('Yenile',exact=False)
  if refresh.count():refresh.first.click()
  import re
  deadline=time.time()+150;option=None;selected_label=''
  while time.time()<deadline:
   body=page.locator('body').inner_text()
   if 'Sign in to confirm' in body:raise RuntimeError('AUTHENTICATION_REQUIRED: user must complete YouTube verification; no bypass attempted')
   choices=page.get_by_text(re.compile(r'^(?:[0-9]{3,4}p|[0-9]{3,4} × [0-9]{3,4})'))
   visible=[]
   for k in range(choices.count()):
    loc=choices.nth(k)
    if loc.is_visible():
     label=loc.inner_text();m=re.search(r'(\d{3,4})p',label)
     if m:visible.append((int(m.group(1)),label,loc))
   if visible:
    h,selected_label,option=max(visible,key=lambda x:x[0])
    if h>=min_height:break
   page.wait_for_timeout(2000)
  if option is None:raise RuntimeError('No real video format option available in Brave IDM bar')
  page.screenshot(path=str(R/'real-quality-menu.png'));event('real_video_option_visible',label=selected_label)
  time.sleep(5);option.click();event('real_browser_download_selection')
  deadline=time.time()+90;found=False
  while time.time()<deadline:
   w=windows()
   if any(x.lower() in w.lower() for x in ['Download File Info','İndirilecek Dosya Bilgisi']):found=True;break
   time.sleep(1)
  (R/'windows-after-selection.txt').write_text(windows())
  if not found:raise RuntimeError('IDM file information window did not appear; do not claim a download')
  subprocess.run(['import','-window','root',str(R/'idm-file-info.png')],check=True);time.sleep(5)
  subprocess.run(['xdotool','key','Return'],check=True);event('start_pressed_in_real_idm_window')
  deadline=time.time()+600;completed=False;last_update=0
  while time.time()<deadline:
   w=windows()
   if time.time()-last_update>15:
    event('download_wait',windows=w[-1200:]);last_update=time.time()
   if any(x.lower() in w.lower() for x in ['Download complete','İndirme tamamlandı']):completed=True;break
   time.sleep(2)
  (R/'windows-end.txt').write_text(windows())
  subprocess.run(['import','-window','root',str(R/'idm-end.png')],check=True)
  if not completed:raise RuntimeError('No IDM completion dialog within 10 minutes')
  event('idm_completion_dialog_seen');time.sleep(8)
  candidates=[]
  for root in [Path.home()/'Downloads',Path.home()/'.local/share/idm-linux/prefix/drive_c/users']:
   if root.exists():
    for f in root.rglob('*'):
     if f.is_file() and f.suffix.lower() in ['.mp4','.mkv','.webm'] and f.stat().st_mtime>=epoch:
      try:
       d=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(f)],text=True,timeout=30))
       if any(s.get('height',0)>=min_height for s in d['streams']) and any(s.get('codec_type')=='audio' for s in d['streams']):candidates.append((f,d))
      except Exception:pass
  if not candidates:raise RuntimeError('Completion not accepted: no newly downloaded video with required resolution and audio verified')
  f,d=candidates[0];(R/'download-ffprobe.json').write_text(json.dumps(d,indent=2));event('VERIFIED_VIDEO_WITH_AUDIO',file=str(f),bytes=f.stat().st_size)
except Exception as e:
 event('FAIL',reason=str(e));raise
finally:
 if rec and rec.poll() is None:
  rec.send_signal(signal.SIGINT)
  try:rec.wait(timeout=45)
  except subprocess.TimeoutExpired:rec.kill();rec.wait()
