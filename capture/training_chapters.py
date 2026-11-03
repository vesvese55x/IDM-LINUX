"""Real Brave README->Loltek lesson. Audio is original-speed, cues measured.
No screenshots are used as a substitute for browser interaction/video capture.
"""
from pathlib import Path
import os,time,json,subprocess,requests
from desktop_ready import cdp,brave_path,safe_env
PROMO='https://rawgit.loltek.net/https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/promo/promo.html'
REPO='https://github.com/vesvese55x/IDM-LINUX/'

def run(report,out,screenshot):
 import pyautogui
 out=Path(out);events=[];cues=[];mouse_maps={};views=[];targets=[]
 report.update({'phase':'tutorial-chapter-01-real-README-Loltek-browser','tutorial_chapter':'01','full_functional_suite':'NOT_RUN','audio_playback_rate':1.0,'tutorial_audio_cues':cues,'tutorial_browser_events':events,'presentation_views':views,'presentation_targets':targets})
 manifest=json.loads((Path(__file__).parent/'promo-audio-manifest.json').read_text())
 audio={a['file']:a for a in manifest}
 events.append({'action':'real_mouse_click','target':'Open real Linux applications menu','x':22,'y':pyautogui.size().height-24,'video_offset_seconds':time.time()-report['record_wallclock_start']})
 pyautogui.click(22,pyautogui.size().height-24);time.sleep(1.5);screenshot('modern-linux-menu-open');pyautogui.press('esc');time.sleep(.8);pyautogui.moveTo(1850,850,duration=.4)
 log=(out/'tutorial-brave.log').open('wb')
 args=[brave_path(),'--remote-debugging-port=19333','--remote-debugging-address=127.0.0.1','--start-maximized',REPO]
 subprocess.Popen(args,env=safe_env(),stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0);log.close()
 def pages():
  try:return requests.get('http://127.0.0.1:19333/json/list',timeout=3).json()
  except requests.RequestException:return []
 def wait_page(fragment,timeout=65):
  deadline=time.monotonic()+timeout
  while time.monotonic()<deadline:
   found=[p for p in pages() if p.get('type')=='page' and fragment in p.get('url','')]
   if found:return found[0]
   time.sleep(.5)
  raise RuntimeError('Real browser page did not load: '+fragment)
 page=wait_page('github.com/vesvese55x/IDM-LINUX')
 # Only disposable warmup blank tabs in this fresh isolated runner profile.
 for tab in pages():
  if tab.get('type')=='page' and tab.get('url')=='about:blank':
   cdp(page['webSocketDebuggerUrl'],'Target.closeTarget',{'targetId':tab['id']})
 def ev(expression):
  r=cdp(page['webSocketDebuggerUrl'],'Runtime.evaluate',{'expression':expression,'returnByValue':True})
  assert not r.get('error') and not r.get('result',{}).get('exceptionDetails'),str(r)[:400]
  return r['result']['result'].get('value')
 def wait_selector(selector,timeout=60):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   if ev('Boolean(document.querySelector('+json.dumps(selector)+'))'):return
   time.sleep(.5)
  raise RuntimeError('Actual page element unavailable: '+selector)
 def locate(selector):
  wait_selector(selector)
  ev('document.querySelector('+json.dumps(selector)+').scrollIntoView({block:"center",behavior:"smooth"})');time.sleep(1.5)
  for attempt in range(5):
   check=ev('(()=>{const r=document.querySelector('+json.dumps(selector)+').getBoundingClientRect();return {top:r.top,bottom:r.bottom,h:innerHeight}})()')
   if check['top']>=0 and check['bottom']<=check['h']:break
   ev('document.querySelector('+json.dumps(selector)+').scrollIntoView({block:"center",behavior:"smooth"})');time.sleep(1.2)
  return ev('(()=>{const r=document.querySelector('+json.dumps(selector)+').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,width:r.width,height:r.height,sx:window.screenX,sy:window.screenY,ox:(window.outerWidth-window.innerWidth)/2,oy:window.outerHeight-window.innerHeight,dpr:window.devicePixelRatio}})()')
 def pointer_map():
  # Passive observation of REAL OS pointer events. No DOM/content replacement,
  # no JS click and no CDP input dispatch. Derive actual screen/CSS transform.
  key=(page['id'],ev('location.origin'),ev('devicePixelRatio'))
  if key not in mouse_maps:
   ev("window.__filmReadOnlyPointer=null;document.addEventListener('pointermove',e=>{window.__filmReadOnlyPointer={x:e.clientX,y:e.clientY}},{capture:true,passive:true})")
   pyautogui.moveTo(700,400,duration=.4);time.sleep(.15);a=ev('window.__filmReadOnlyPointer')
   pyautogui.moveTo(1000,650,duration=.4);time.sleep(.15);b=ev('window.__filmReadOnlyPointer')
   assert a and b and abs(b['x']-a['x'])>50 and abs(b['y']-a['y'])>50,'Native pointer observation unavailable'
   sx=300/(b['x']-a['x']);sy=250/(b['y']-a['y']);assert abs(sx-sy)<.03,(a,b,sx,sy)
   mouse_maps[key]={'sx':sx,'sy':sy,'ox':700-a['x']*sx,'oy':400-a['y']*sy,'method':'Passive actual OS pointer coordinate observation'}
  return mouse_maps[key]
 def click(selector,label):
  r=locate(selector);assert r['width']>0 and r['height']>0
  mapping=pointer_map();x=mapping['ox']+r['x']*mapping['sx'];y=mapping['oy']+r['y']*mapping['sy']
  assert 0<x<1920 and 0<y<1080,(selector,r,mapping)
  pyautogui.moveTo(x,y,duration=.6);time.sleep(.25)
  assert ev('document.querySelector('+json.dumps(selector)+').matches(":hover")'),'Real pointer is not hovering the intended clickable element'
  events.append({'action':'real_mouse_click','target':label,'x':x,'y':y,'transform':mapping,'video_offset_seconds':time.time()-report['record_wallclock_start']})
  pyautogui.click()
 def scroll(selector,label):
  report.setdefault('presentation_scroll_starts',[]).append(time.time()-report['record_wallclock_start'])
  locate(selector)
  if '.pkg-table tbody tr:first-child' in selector:
   ev('window.scrollBy({top:document.querySelector('+json.dumps(selector)+').getBoundingClientRect().top-110,behavior:"smooth"})');time.sleep(1.5)
  events.append({'action':'real_browser_scroll','target':label,'video_offset_seconds':time.time()-report['record_wallclock_start']})
  mapping=pointer_map()
  import semantic_emphasis
  at=time.time()-report['record_wallclock_start'];view={'id':len(views)+1,'time':at,'scene':label};views.append(view)
  targets.extend(semantic_emphasis.snapshot(ev,mapping,at,view['id']))
  # No parked menu tooltip or long hover URL over the lower-third captions.
  pyautogui.moveTo(1850,850,duration=.3)
 def persist():
  (out/'tutorial-cues.json').write_text(json.dumps(cues,ensure_ascii=False,indent=2),encoding='utf-8')
  (out/'probe-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 def speak(filename,selector,label,switch=None):
  scroll(selector,label);screenshot('promo-'+filename[:2]+'-ready')
  start=time.time();duration=audio[filename]['duration']
  cues.append({'audio_file':filename,'video_offset_seconds':start-report['record_wallclock_start'],'duration_seconds':duration,'playback_rate':1.0,'page_url':ev('location.href'),'visible_scene':label});persist()
  if switch:
   steps=switch if isinstance(switch,list) else [switch]
   for delay,newselector,newlabel in steps:
    time.sleep(max(0,start+delay-time.time()));scroll(newselector,newlabel)
  time.sleep(max(0,duration+.8-(time.time()-start)))
 # Real GitHub README anchor, no lookalike or local page.
 wait_selector('article')
 link_selector='article a[href="'+PROMO+'"]'
 speak('01-readme.mp3',link_selector,'Official GitHub README and actual promotion link')
 click(link_selector,'README promotion link to exact Loltek URL')
 page=wait_page('rawgit.loltek.net/https://raw.githubusercontent.com/vesvese55x/IDM-LINUX')
 wait_selector('#lang-btn');click('#lang-btn','Open actual language selector');time.sleep(.5);click('button[data-lang="tr"]','Select Turkish');time.sleep(1)
 assert ev('document.documentElement.lang')=='tr','Turkish UI not selected'
 assert ev('location.href').split('#')[0]==PROMO,'Not the requested actual Loltek page'
 report['tutorial_promo_url']=ev('location.href');report['tutorial_feature_card_count']=ev('document.querySelectorAll("#ozellikler .card").length')
 speak('02-overview.mp3','header h1','Product identity and platform choices',switch=(30.0,'.platform-grid','Platform cards before spoken platform-selection cue'))
 speak('03-browser-video.mp3','#ozellikler .card:nth-child(1)','Browser, video and supported-source limitations')
 speak('04-torrent-hosters.mp3','#ozellikler .card:nth-child(4)','Torrent, DVR and file hosters')
 speak('05-doctor-settings.mp3','#ozellikler .card:nth-child(7)','Doctor, sandbox caveat, languages and cancellation')
 # Real ASR-derived word starts: Windows at27.86s in06,32.82s in revised07.
 speak('06-gui-windows.mp3','#ekranlar .shot:first-child','All Linux gallery rows, then native Windows product',switch=[(8,'#ekranlar .shot:nth-child(3)','Linux gallery row2: browsers, doctor, projects'),(17,'#ekranlar .shot:last-child','Linux gallery row3: support and about'),(25.5,'#windows-title','Windows product at spoken Windows cue')])
 speak('10-windows-compatibility.mp3','#windows .compat-note','Real Windows compatibility limits, then all six gallery images',switch=[(23.7,'#windows .screens-grid .shot:first-child','Windows gallery: overview and browsers'),(38.3,'#windows .screens-grid .shot:nth-child(3)','Windows gallery: setup and projects'),(45.5,'#windows .screens-grid .shot:nth-child(5)','Windows gallery: settings and torrent eD2K')])
 speak('07-package-table.mp3','#kurulum .pkg-table tbody tr:first-child','Package selection table',switch=(30.4,'#kurulum .pkg-table tbody tr:last-child','Windows rows at spoken Windows cue'))
 speak('08-commands-safety.mp3','#kurulum .auto-install-options','Actual Linux/Windows commands and security caveats')
 copy_selector='#kurulum .install-command[data-platform="linux"] .copy'
 click(copy_selector,'Copy official Linux one-line installer for next chapter');time.sleep(1)
 copied=subprocess.check_output(['xclip','-selection','clipboard','-o'],text=True) if os.name!='nt' else None
 expected='curl -fsSL https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/belgeselsemo-idm-linux-installer | sh'
 assert copied==expected,'Browser copy did not produce the exact official installer command'
 report['tutorial_copied_linux_command']=copied
 speak('09-ecosystem.mp3','#ekosistem .sec-head','BELGESELSEMO ecosystem and next practical chapters',switch=(19.0,'footer','Economy soon card and actual website footer'))
 screenshot('promo-complete');persist()
 report.setdefault('functional_cases',[]).append({'id':'chapter-01-real-readme-loltek-tour','status':'PASS','scope':'Actual browser tour and exact command copy only; installation and app feature transfers NOT_RUN','narration_clips':len(cues),'natural_voice_seconds':sum(c['duration_seconds'] for c in cues),'url':PROMO,'voice':'Previously approved voice-04','asr_timed_scene_switches':{'06':27.86,'07':32.82}})
 cdp(page['webSocketDebuggerUrl'],'Browser.close')

def finish(report,out):
 """Mux source-rate narration with native footage; upload directly on runner."""
 out=Path(out);cues=report.get('tutorial_audio_cues',[])
 if not cues:return
 source=out/('native-'+('windows' if os.name=='nt' else 'linux')+'.mp4')
 audiodir=Path(__file__).parent/'tutorial_audio';target=out/'BELGESELSEMO-EGITIM-BOLUM-01-PROMO-TR-V3.mp4'
 flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
 duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(source)],text=True,creationflags=flags))
 assert max(c['video_offset_seconds']+c['duration_seconds'] for c in cues)<=duration+.3,'Recorded video is shorter than the narration timeline'
 cmd=['ffmpeg','-y','-v','warning','-i',str(source)]
 filters=[]
 for i,c in enumerate(cues,1):
  cmd+=['-i',str(audiodir/c['audio_file'])];filters.append(f'[{i}:a]adelay={round(c["video_offset_seconds"]*1000)}:all=1[a{i}]')
 labels=''.join(f'[a{i}]' for i in range(1,len(cues)+1));filters.append(labels+f'amix=inputs={len(cues)}:normalize=0,apad[voice]')
 cmd+=['-stream_loop','-1','-i',str(audiodir/'technology-bed.mp3')]
 filters.append(f'[{len(cues)+1}:a]volume=0.32,afade=t=in:d=1.5,afade=t=out:st={max(0,duration-2)}:d=2[bed]')
 filters.append('[voice][bed]amix=inputs=2:normalize=0,alimiter=limit=0.95[outa]')
 video_args=['-c:v','copy']
 if os.getenv('FILM_PRESENTATION')=='1':
  import presentation_overlay
  overlay,presentation_audit=presentation_overlay.build(out,report,duration);report['presentation_audit']=presentation_audit
  semantic=presentation_audit['semantic_emphasis'];assert semantic['rendered_count']>=18,'Too few verified on-screen annotations'
  assert {m['kind'] for m in semantic['rendered']}=={'rectangle','ellipse','underline','highlight','freehand_arrow','freehand_loop'},'Missing requested teaching-mark style'
  assert presentation_audit['cursor_duty_cycle']<.05,'Focus cursor is visible too often'
  escaped=overlay.as_posix().replace(':','\\:').replace("'","\\'")
  video_args=['-vf',"ass=filename='"+escaped+"'",'-c:v','libx264','-threads','2','-preset','veryfast','-crf','17','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-color_range','tv']
 cmd+=['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map','0:v','-map','[outa]']+video_args+['-c:a','aac','-b:a','160k','-ac','2','-ar','48000','-t',str(duration),'-movflags','+faststart',str(target)]
 with (out/'tutorial-audio-mux.log').open('wb') as log:subprocess.run(cmd,stdout=log,stderr=log,check=True,creationflags=flags)
 check=subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],capture_output=True,text=True,creationflags=flags);assert check.returncode==0 and not check.stderr,check.stderr
 import hashlib,zipfile
 def upload(path):
  digest=hashlib.md5(path.read_bytes()).hexdigest()
  with path.open('rb') as f:r=requests.post('https://upload.gofile.io/uploadfile',files={'file':(path.name,f,'application/octet-stream')},timeout=(30,300))
  r.raise_for_status();data=r.json();assert data['status']=='ok';data=data['data'];assert data['md5']==digest and data['size']==path.stat().st_size
  return {'download_page':data['downloadPage'],'filename':path.name,'bytes':path.stat().st_size,'md5':digest,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
 receipt=upload(target)
 receipt.update({'scope':'Narrated real browser chapter01 only; not the finished long training/studio film','audio_rate':1.0,'background_music':'Approved V5 technology score, quiet looping bed','resolution':'1920x1080,24fps, native screen footage','full_decode':'PASS','cue_count':len(cues),'presentation_revision':'V3 — compact selective dark amber focus, DOM-measured multi-color teaching marks and animated notes','animated_notes':report.get('presentation_audit',{}).get('animated_note_count'), 'native_arrow_recorded':os.getenv('FILM_PRESENTATION')!='1'})
 (out/'tutorial-gofile.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8');report['tutorial_delivery']=receipt
 # Small proof-only artifact for the constrained agent workspace.
 from PIL import Image
 proofs=out/'tutorial-receipts';proofs.mkdir(exist_ok=True)
 for name in ['tutorial-gofile.json','tutorial-cues.json','desktop-shell-audit.json','wallpaper-system-info.json','console-visibility-audit.json','pointer-audit.json','presentation-audit.json','semantic-emphasis-audit.json']:
  p=out/name
  if p.exists():__import__('shutil').copyfile(p,proofs/name)
 for name in ['desktop-ready-before-recording','modern-linux-menu-open','promo-01-ready','promo-02-ready','promo-07-ready','promo-complete']:
  p=out/(name+'.png')
  if p.exists():
   image=Image.open(p).convert('RGB');image.thumbnail((1280,720));image.save(proofs/(name+'.jpg'),quality=88)
 if os.getenv('FILM_PRESENTATION')=='1':
  # Proof frames are decoded from the actual final movie, not recreated scenes.
  for i in [0,1,7]:
   cue=cues[i];when=cue['video_offset_seconds']+(5 if i!=7 else 11)
   subprocess.run(['ffmpeg','-v','error','-ss',str(when),'-i',str(target),'-frames:v','1','-vf','scale=1280:-2','-q:v','2','-y',str(proofs/f'presentation-final-{i:02}.jpg')],check=True,creationflags=flags)
  for number,mark in enumerate(report.get('presentation_audit',{}).get('semantic_emphasis',{}).get('rendered',[])[:4]):
   when=mark['start']+min(1.4,(mark['end']-mark['start'])/2)
   subprocess.run(['ffmpeg','-v','error','-ss',str(when),'-i',str(target),'-frames:v','1','-vf','scale=1280:-2','-q:v','3','-y',str(proofs/f'v3-semantic-{number:02}.jpg')],check=True,creationflags=flags)
  click=next(e for e in report['tutorial_browser_events'] if e.get('target')=='README promotion link to exact Loltek URL')
  subprocess.run(['ffmpeg','-v','error','-ss',str(click['video_offset_seconds']+.18),'-i',str(target),'-frames:v','1','-vf','scale=1280:-2','-q:v','2','-y',str(proofs/'presentation-actual-click.jpg')],check=True,creationflags=flags)
 print(json.dumps({'tutorial_delivery':receipt},ensure_ascii=False),flush=True)
