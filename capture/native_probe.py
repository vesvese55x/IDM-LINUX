"""Real released-binary startup/navigation/screen-capture probe. NOT a full feature pass."""
from pathlib import Path
import os,sys,json,time,hashlib,subprocess,platform,traceback,shutil,datetime
import requests
ROOT=Path.cwd();OUT=ROOT/'evidence';OUT.mkdir(exist_ok=True)
OS=sys.argv[1];iswin=OS=='windows';flags=subprocess.CREATE_NO_WINDOW if iswin else 0
report={'phase':'real-release-native-desktop-preflight','status':'RUNNING','platform':platform.platform(),'runner_os':os.getenv('RUNNER_OS'),'source_checkout_commit':os.getenv('GITHUB_SHA'),'run_id':os.getenv('GITHUB_RUN_ID'),'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'full_functional_suite':'NOT_RUN','pages':[],'capture_method':'ffmpeg gdigrab actual desktop' if iswin else 'ffmpeg x11grab actual Xvfb desktop','not_used':['DrawToBitmap','synthetic UI','PNG slideshow'],'application_modified':False}
rec=None;app=None;loghandles=[]
def save():
 (OUT/'probe-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
def run(cmd,**kw):return subprocess.run(cmd,check=True,creationflags=flags,**kw)
def app_env():
 return {k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ['TOKEN','SECRET','PASSWORD']) and not k.startswith(('ACTIONS_','GITHUB_'))}
def file_sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def download_asset():
 r=requests.get('https://api.github.com/repos/vesvese55x/IDM-LINUX/releases/latest',timeout=30);r.raise_for_status();rel=r.json()
 name='IDM-SEMO-1.0.0-x86_64.exe' if iswin else 'IDM-LINUX-1.0.0-x86_64.AppImage'
 asset=next(x for x in rel['assets'] if x['name']==name);dest=Path(os.getenv('RUNNER_TEMP',str(ROOT)))/name
 with requests.get(asset['browser_download_url'],stream=True,timeout=(30,180)) as resp:
  resp.raise_for_status()
  with dest.open('wb') as f:
   for b in resp.iter_content(1024*1024):f.write(b)
 digest=file_sha(dest);assert dest.stat().st_size==asset['size'],'Release size mismatch'
 if asset.get('digest'):assert asset['digest']=='sha256:'+digest,'Publisher SHA256 mismatch'
 report['release']={'tag':rel['tag_name'],'release_id':rel['id'],'asset_id':asset['id'],'asset_name':name,'bytes':dest.stat().st_size,'sha256':digest,'publisher_digest':asset.get('digest'),'download_url':asset['browser_download_url']};save();return dest

def screenshot(label):
 import pyautogui
 from PIL import ImageStat
 image=pyautogui.screenshot();stat=ImageStat.Stat(image.convert('RGB'));assert max(stat.stddev)>10 and sum(stat.mean)>10,'Desktop blank/locked/unavailable'
 image.save(OUT/(label+'.png'))
 return {'filename':label+'.png','size':list(image.size),'rgb_mean':stat.mean,'rgb_stddev':stat.stddev,'sha256':file_sha(OUT/(label+'.png'))}

def start_recorder(w,h):
 global rec
 ff=shutil.which('ffmpeg');assert ff,'ffmpeg missing'
 args=[ff,'-y','-hide_banner','-loglevel','warning','-thread_queue_size','512']
 if iswin:args+=['-f','gdigrab','-framerate','24','-draw_mouse','1','-video_size',f'{w}x{h}','-i','desktop']
 else:args+=['-f','x11grab','-framerate','24','-draw_mouse','1','-video_size',f'{w}x{h}','-i',os.environ['DISPLAY']+'.0']
 args+=['-vf','scale=out_color_matrix=bt709:out_range=tv,format=yuv420p','-c:v','libx264','-threads','2','-preset','veryfast','-crf','16','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-movflags','+faststart',str(OUT/('native-'+OS+'.mp4'))]
 log=(OUT/'recorder.log').open('wb');loghandles.append(log);rec=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=log,stderr=log,creationflags=flags);report['record_wallclock_start']=time.time();report['native_resolution']=[w,h];time.sleep(2);assert rec.poll() is None,'Desktop recorder failed to start'

def wait_tree(path,timeout=100):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  try:
   d=json.loads(path.read_text(encoding='utf-8'))
   if len(d['widgets'])>30 and d['root_rect'][2]>800:return d
  except Exception:pass
  if app and app.poll() is not None:raise RuntimeError('Released AppImage exited before usable GUI')
  time.sleep(.5)
 raise RuntimeError('Actual Tk release window not discoverable within timeout')

def tour_linux(exe):
 global app
 # Extract and run the released AppImage as allowed by its own AppRun; no source rebuild.
 exe.chmod(0o755);extract=Path(os.environ.get('RUNNER_TEMP',str(ROOT)))/'film-appimage';extract.mkdir(exist_ok=True)
 with (OUT/'appimage-extract.log').open('wb') as f:run([str(exe),'--appimage-extract'],cwd=extract,stdout=f,stderr=subprocess.STDOUT)
 launch=extract/'squashfs-root/AppRun';assert launch.exists()
 env=app_env();env['FILM_WIDGET_DUMP']=str(OUT/'visible-widgets.json');env['PYTHONPATH']=str(ROOT/'capture/probe_site');env['PYTHONUNBUFFERED']='1'
 report['ui_instrumentation']='Read-only Tk widget tree; production AppImage unchanged; external mouse clicks'
 log=(OUT/'application.log').open('wb');loghandles.append(log);app=subprocess.Popen([str(launch)],env=env,stdout=log,stderr=log)
 treepath=OUT/'visible-widgets.json';d=wait_tree(treepath)
 ids=subprocess.check_output(['xdotool','search','--onlyvisible','--class','idm-linux-panel'],text=True).split()
 if ids:
  window=ids[-1];run(['xdotool','windowactivate','--sync',window]);run(['xdotool','windowsize',window,'1880','1000']);run(['xdotool','windowmove',window,'10','10']);time.sleep(2)
 d=wait_tree(treepath);report['window_title']=d['root_title'];lx=d['root_rect'][0]
 nav=[x for x in d['widgets'] if x['class'] in ['Button','TButton'] and x['text'].strip() and x['rect'][0]<lx+30 and 130<=x['rect'][2]<=300 and x['rect'][3]>=20]
 nav=sorted(nav,key=lambda x:x['rect'][1]);report['navigation_buttons_detected']=[x['text'] for x in nav];save();assert len(nav)>=9,'Expected nine actual Linux navigation buttons'
 import pyautogui
 for i,item in enumerate(nav[:9]):
  x,y,w,h=item['rect'];pyautogui.moveTo(x+w*.5,y+h*.5,duration=.45);pyautogui.click();time.sleep(2.8)
  d=wait_tree(treepath);(OUT/f'page-{i:02d}-widgets.json').write_text(json.dumps(d,ensure_ascii=False),encoding='utf-8')
  report['pages'].append({'index':i,'navigation_label':item['text'],'video_wallclock_offset_seconds':time.time()-report['record_wallclock_start'],'evidence':screenshot(f'page-{i:02d}'),'scope':'Page navigation/display only; feature operation NOT verified'});save()
 # Return to the real overview for a clean opening/closing hold.
 x,y,w,h=nav[1]['rect'];pyautogui.moveTo(x+w*.5,y+h*.5,duration=.5);pyautogui.click();time.sleep(5)
 report['final_visible_widgets']=wait_tree(treepath);report['startup_navigation']='PASS'

def tour_windows(exe):
 global app
 import ctypes,win32api,win32con,win32gui
 from pywinauto import Desktop
 try:
  mode=win32api.EnumDisplaySettings(None,win32con.ENUM_CURRENT_SETTINGS);mode.PelsWidth=1920;mode.PelsHeight=1080;mode.Fields=win32con.DM_PELSWIDTH|win32con.DM_PELSHEIGHT
  report['display_change_return_code']=win32api.ChangeDisplaySettings(mode,0)
 except Exception as e:report['display_change_note']=type(e).__name__
 # Preseed only safe isolated test settings; later functional tests must enable capture/engines explicitly.
 settings=Path(os.environ['APPDATA'])/'IDM_SEMO/settings.ini';settings.parent.mkdir(parents=True,exist_ok=True);settings.write_text('lang=tr\nclipwatch=0\nwarm=0\n',encoding='utf-8');report['seeded_test_settings']={'lang':'tr','clipwatch':'0','warm':'0'}
 log=(OUT/'application.log').open('wb');loghandles.append(log);app=subprocess.Popen([str(exe)],env=app_env(),stdout=log,stderr=log,creationflags=flags)
 deadline=time.monotonic()+120;main=None
 while time.monotonic()<deadline:
  wins=[w for w in Desktop(backend='win32').windows() if 'IDM SEMO' in w.window_text().upper() and w.rectangle().width()>800 and w.rectangle().height()>500]
  if wins:main=max(wins,key=lambda w:w.rectangle().width()*w.rectangle().height());break
  time.sleep(.5)
 assert main is not None,'Released EXE main window unavailable on native desktop'
 main.maximize();main.set_focus();time.sleep(3);report['window_title']=main.window_text();left=main.rectangle().left
 nav=[]
 for c in main.descendants():
  try:
   r=c.rectangle()
   if c.friendly_class_name()=='Button' and c.is_visible() and c.window_text().strip() and r.right<=left+280 and r.width()>=140 and 24<=r.height()<=65:nav.append(c)
  except Exception:pass
 nav.sort(key=lambda c:c.rectangle().top);report['navigation_buttons_detected']=[c.window_text() for c in nav];save();assert len(nav)>=10,'Expected ten actual Windows navigation buttons'
 for i,c in enumerate(nav[:10]):
  label=c.window_text();c.click_input();time.sleep(2.8)
  texts=[]
  for x in main.descendants():
   try:
    if x.is_visible() and x.window_text():texts.append({'text':x.window_text()[:2000],'class':x.class_name(),'rect':[x.rectangle().left,x.rectangle().top,x.rectangle().right,x.rectangle().bottom]})
   except Exception:pass
  (OUT/f'page-{i:02d}-controls.json').write_text(json.dumps(texts,ensure_ascii=False),encoding='utf-8')
  assert not any('page failed to load' in x['text'].lower() for x in texts),'Production page construction failed'
  report['pages'].append({'index':i,'navigation_label':label,'video_wallclock_offset_seconds':time.time()-report['record_wallclock_start'],'evidence':screenshot(f'page-{i:02d}'),'scope':'Page navigation/display only; feature operation NOT verified'});save()
 nav[1].click_input();time.sleep(4)
 # Verify actual released EXE single-instance handling, not a rebuilt test executable.
 second=subprocess.Popen([str(exe)],env=app_env(),stdout=log,stderr=log,creationflags=flags);time.sleep(5)
 wins=[w for w in Desktop(backend='win32').windows() if 'IDM SEMO' in w.window_text().upper() and w.rectangle().width()>800 and w.rectangle().height()>500]
 report['single_instance']={'main_windows_after_second_launch':len(wins),'status':'PASS' if len(wins)==1 else 'FAIL'};report['startup_navigation']='PASS';screenshot('final-overview')

try:
 if iswin:
  import ctypes
  ctypes.windll.user32.SetProcessDPIAware()
  # Set screen mode before starting gdigrab, so the capture bounds remain accurate.
  import win32api,win32con
  try:
   mode=win32api.EnumDisplaySettings(None,win32con.ENUM_CURRENT_SETTINGS);mode.PelsWidth=1920;mode.PelsHeight=1080;mode.Fields=win32con.DM_PELSWIDTH|win32con.DM_PELSHEIGHT;report['initial_display_change_return_code']=win32api.ChangeDisplaySettings(mode,0)
  except Exception:pass
 else:
  # Wait only for this job's Xvfb to become usable; not an application-test shortcut.
  end=time.monotonic()+20
  while time.monotonic()<end:
   if subprocess.run(['xdotool','getdisplaygeometry'],capture_output=True).returncode==0:break
   time.sleep(.25)
 if not iswin and subprocess.run(['wmctrl','-m'],capture_output=True).returncode!=0:
  wm_log=(OUT/'window-manager.log').open('wb');loghandles.append(wm_log);subprocess.Popen(['openbox'],stdout=wm_log,stderr=wm_log,env=app_env());time.sleep(1.5)
 import pyautogui
 pyautogui.FAILSAFE=False
 w,h=pyautogui.size();assert w>=1000 and h>=700,'Desktop resolution is not usable'
 exe=download_asset();start_recorder(w,h)
 if iswin:tour_windows(exe)
 else:tour_linux(exe)
 report['status']='PASS';report['notice']='Only startup, visible page navigation, desktop recording and explicitly listed checks are validated. Download/browser/video/P2P functional tests remain NOT_RUN.'
except Exception as e:
 report['status']='FAIL';report['error_type']=type(e).__name__;report['error']=str(e);(OUT/'exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
 try:screenshot('failure-desktop')
 except Exception:pass
finally:
 if rec:
  try:
   if rec.poll() is None:rec.communicate(input=b'q\n',timeout=35)
  except Exception:
   rec.terminate()
   try:rec.wait(timeout=10)
   except Exception:rec.kill()
  report['recorder_exit_code']=rec.poll()
 if app:
  try:app.terminate()
  except Exception:pass
 for h in loghandles:
  try:h.close()
  except Exception:pass
 video=OUT/('native-'+OS+'.mp4')
 if video.exists():
  report['video']={'filename':video.name,'bytes':video.stat().st_size,'sha256':file_sha(video)}
  try:
   probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(video)],creationflags=flags));(OUT/'video-ffprobe.json').write_text(json.dumps(probe,indent=2));report['video']['duration_seconds']=float(probe['format']['duration'])
  except Exception:report['status']='FAIL';report['video']['probe']='FAIL'
 if report.get('recorder_exit_code')!=0:report['status']='FAIL'
 save();print(json.dumps({'status':report['status'],'phase':report['phase'],'pages_visited':len(report['pages']),'full_functional_suite':report['full_functional_suite'],'video':report.get('video'),'error':report.get('error')},indent=2),flush=True)
 if os.getenv('GITHUB_STEP_SUMMARY'):
  with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:f.write('## Real native release capture: '+OS+'\nStatus: '+report['status']+'\n\nFull functional suite: NOT_RUN. See original desktop MP4 and per-page evidence artifacts.\n')
sys.exit(0 if report['status']=='PASS' else 1)
