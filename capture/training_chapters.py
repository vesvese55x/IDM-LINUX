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
 out=Path(out);events=[];cues=[]
 report.update({'phase':'tutorial-chapter-01-real-README-Loltek-browser','tutorial_chapter':'01','full_functional_suite':'NOT_RUN','audio_playback_rate':1.0,'tutorial_audio_cues':cues,'tutorial_browser_events':events})
 manifest=json.loads((Path(__file__).parent/'promo-audio-manifest.json').read_text())
 audio={a['file']:a for a in manifest}
 log=(out/'tutorial-brave.log').open('wb')
 args=[brave_path(),'--remote-debugging-port=19333','--remote-debugging-address=127.0.0.1','--start-maximized','--new-window',REPO]
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
  return ev('(()=>{const r=document.querySelector('+json.dumps(selector)+').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,width:r.width,height:r.height,sx:window.screenX,sy:window.screenY,ox:(window.outerWidth-window.innerWidth)/2,oy:window.outerHeight-window.innerHeight,dpr:window.devicePixelRatio}})()')
 def click(selector,label):
  r=locate(selector);assert r['width']>0 and r['height']>0
  x=r['sx']+r['ox']+r['x'];y=r['sy']+r['oy']+r['y']
  assert 0<x<1920 and 0<y<1080,(selector,r)
  pyautogui.moveTo(x,y,duration=.6);pyautogui.click()
  events.append({'action':'real_mouse_click','target':label,'video_offset_seconds':time.time()-report['record_wallclock_start']})
 def scroll(selector,label):
  locate(selector);events.append({'action':'real_browser_scroll','target':label,'video_offset_seconds':time.time()-report['record_wallclock_start']})
 def persist():
  (out/'tutorial-cues.json').write_text(json.dumps(cues,ensure_ascii=False,indent=2),encoding='utf-8')
  (out/'probe-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 def speak(filename,selector,label,switch=None):
  scroll(selector,label);screenshot('promo-'+filename[:2]+'-ready')
  start=time.time();duration=audio[filename]['duration']
  cues.append({'audio_file':filename,'video_offset_seconds':start-report['record_wallclock_start'],'duration_seconds':duration,'playback_rate':1.0,'page_url':ev('location.href'),'visible_scene':label});persist()
  if switch:
   delay,newselector,newlabel=switch;time.sleep(delay);scroll(newselector,newlabel)
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
 speak('02-overview.mp3','header h1','Product identity and platform choices')
 scroll('.platform-grid','Linux and Windows platform cards');time.sleep(3)
 speak('03-browser-video.mp3','#ozellikler .card:nth-child(1)','Browser, video and supported-source limitations')
 speak('04-torrent-hosters.mp3','#ozellikler .card:nth-child(4)','Torrent, DVR and file hosters')
 speak('05-doctor-settings.mp3','#ozellikler .card:nth-child(7)','Doctor, sandbox caveat, languages and cancellation')
 # Real ASR-derived word starts: Windows at27.86s in06,34.34s in07.
 speak('06-gui-windows.mp3','#ekranlar .sec-head','GUI gallery, then native Windows product',switch=(26.0,'#windows-title','Windows product at spoken Windows cue'))
 speak('07-package-table.mp3','#kurulum .pkg-table tbody tr:first-child','Package selection table',switch=(32.5,'#kurulum .pkg-table tbody tr:last-child','Windows rows at spoken Windows cue'))
 speak('08-commands-safety.mp3','#kurulum .auto-install-options','Actual Linux/Windows commands and security caveats')
 copy_selector='#kurulum .install-command[data-platform="linux"] .copy'
 click(copy_selector,'Copy official Linux one-line installer for next chapter');time.sleep(1)
 copied=subprocess.check_output(['xclip','-selection','clipboard','-o'],text=True) if os.name!='nt' else None
 expected='curl -fsSL https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/belgeselsemo-idm-linux-installer | sh'
 assert copied==expected,'Browser copy did not produce the exact official installer command'
 report['tutorial_copied_linux_command']=copied
 speak('09-ecosystem.mp3','#ekosistem .sec-head','BELGESELSEMO ecosystem and next practical chapters')
 screenshot('promo-complete');persist()
 report.setdefault('functional_cases',[]).append({'id':'chapter-01-real-readme-loltek-tour','status':'PASS','scope':'Actual browser tour and exact command copy only; installation and app feature transfers NOT_RUN','narration_clips':len(cues),'natural_voice_seconds':sum(c['duration_seconds'] for c in cues),'url':PROMO,'voice':'Previously approved voice-04','asr_timed_scene_switches':{'06':27.86,'07':34.34}})
 cdp(page['webSocketDebuggerUrl'],'Browser.close')

def finish(report,out):
 """Mux source-rate narration with native footage; upload directly on runner."""
 out=Path(out);cues=report.get('tutorial_audio_cues',[])
 if not cues:return
 source=out/('native-'+('windows' if os.name=='nt' else 'linux')+'.mp4')
 audiodir=Path(__file__).parent/'tutorial_audio';target=out/'BELGESELSEMO-EGITIM-BOLUM-01-PROMO-TR.mp4'
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
 cmd+=['-filter_complex',';'.join(filters),'-map','0:v','-map','[outa]','-c:v','copy','-c:a','aac','-b:a','160k','-ac','2','-ar','48000','-t',str(duration),'-movflags','+faststart',str(target)]
 with (out/'tutorial-audio-mux.log').open('wb') as log:subprocess.run(cmd,stdout=log,stderr=log,check=True,creationflags=flags)
 check=subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],capture_output=True,text=True,creationflags=flags);assert check.returncode==0 and not check.stderr,check.stderr
 import hashlib,zipfile
 def upload(path):
  digest=hashlib.md5(path.read_bytes()).hexdigest()
  with path.open('rb') as f:r=requests.post('https://upload.gofile.io/uploadfile',files={'file':(path.name,f,'application/octet-stream')},timeout=(30,300))
  r.raise_for_status();data=r.json();assert data['status']=='ok';data=data['data'];assert data['md5']==digest and data['size']==path.stat().st_size
  return {'download_page':data['downloadPage'],'filename':path.name,'bytes':path.stat().st_size,'md5':digest,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
 receipt=upload(target)
 receipt.update({'scope':'Narrated real browser chapter01 only; not the finished long training/studio film','audio_rate':1.0,'background_music':'Approved V5 technology score, quiet looping bed','resolution':'1920x1080,24fps, native screen footage','full_decode':'PASS','cue_count':len(cues)})
 (out/'tutorial-gofile.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8');report['tutorial_delivery']=receipt
 # Small proof-only artifact for the constrained agent workspace.
 from PIL import Image
 proofs=out/'tutorial-receipts';proofs.mkdir(exist_ok=True)
 for name in ['tutorial-gofile.json','tutorial-cues.json','desktop-shell-audit.json','wallpaper-system-info.json','console-visibility-audit.json']:
  p=out/name
  if p.exists():__import__('shutil').copyfile(p,proofs/name)
 for name in ['desktop-ready-before-recording','promo-01-ready','promo-02-ready','promo-07-ready','promo-complete']:
  p=out/(name+'.png')
  if p.exists():
   image=Image.open(p).convert('RGB');image.thumbnail((1280,720));image.save(proofs/(name+'.jpg'),quality=88)
 print(json.dumps({'tutorial_delivery':receipt},ensure_ascii=False),flush=True)
