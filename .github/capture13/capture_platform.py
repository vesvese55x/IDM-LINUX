import os,time,json,subprocess,signal,sys,re
from pathlib import Path
from playwright.sync_api import sync_playwright
site,url=sys.argv[1:3]
R=Path('out')/site;R.mkdir(parents=True,exist_ok=True)
events=[];epoch=time.time();rec=None

def event(name,**kw):
 events.append({'seconds':round(time.time()-epoch,3),'event':name,**kw});(R/'events.json').write_text(json.dumps(events,indent=2));print(name,flush=True)
def windows():
 return subprocess.run(['wmctrl','-lG'],capture_output=True,text=True).stdout
try:
 rec=subprocess.Popen(['ffmpeg','-nostdin','-y','-v','warning','-f','x11grab','-draw_mouse','1','-video_size','1920x1080','-framerate','24','-i',os.environ['DISPLAY'],'-an','-c:v','libx264','-preset','veryfast','-crf','20','-bf','0',str(R/'uncut.mp4')],stdout=open(R/'capture.log','w'),stderr=subprocess.STDOUT)
 with sync_playwright() as p:
  b=p.chromium.connect_over_cdp('http://127.0.0.1:9222');page=b.contexts[0].new_page();event('browser_navigation',url=url)
  page.goto(url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(10000)
  page.screenshot(path=str(R/'source-page.png'));(R/'source-page.txt').write_text(page.locator('body').inner_text())
  if re.search(r'Sign in to confirm|CAPTCHA|Access denied',page.locator('body').inner_text(),re.I):raise RuntimeError('Access/authentication barrier; no bypass attempted')
  page.get_by_text('Bu videoyu indir',exact=False).first.click(timeout=45000)
  refresh=page.get_by_text('Yenile',exact=False)
  if refresh.count():refresh.first.click()
  option=page.get_by_text(re.compile(r'^\d{3,4}p\b')).first;option.wait_for(state='visible',timeout=150000)
  page.screenshot(path=str(R/'real-quality-menu.png'));event('real_video_option_visible',label=option.inner_text())
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
  deadline=time.time()+600;completed=False
  while time.time()<deadline:
   w=windows()
   if any(x.lower() in w.lower() for x in ['Download complete','İndirme tamamlandı']):completed=True;break
   time.sleep(2)
  (R/'windows-end.txt').write_text(windows())
  subprocess.run(['import','-window','root',str(R/'idm-end.png')],check=True)
  if not completed:raise RuntimeError('No IDM completion dialog within 10 minutes')
  event('idm_completion_dialog_seen');time.sleep(8)
  candidates=[]
  for root in [Path.home()]:
   if root.exists():
    for f in root.rglob('*'):
     if f.is_file() and f.suffix.lower() in ['.mp4','.mkv','.webm'] and f.stat().st_mtime>=epoch:
      try:
       d=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(f)],text=True,timeout=30))
       if any(s.get('height',0)>=144 for s in d['streams']) and any(s.get('codec_type')=='audio' for s in d['streams']):candidates.append((f,d))
      except Exception:pass
  if not candidates:raise RuntimeError('Completion not accepted: no newly downloaded video with audio verified')
  f,d=candidates[0];(R/'download-ffprobe.json').write_text(json.dumps(d,indent=2));event('VERIFIED_NEW_VIDEO_WITH_AUDIO',file=str(f),bytes=f.stat().st_size)
except Exception as e:
 event('FAIL',reason=str(e));raise
finally:
 if rec and rec.poll() is None:
  rec.send_signal(signal.SIGINT)
  try:rec.wait(timeout=45)
  except subprocess.TimeoutExpired:rec.kill();rec.wait()
