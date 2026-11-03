"""Fresh-runner real package installation lessons. No mocked package managers."""
from pathlib import Path
import os,time,json,subprocess,hashlib,re,shutil,uuid
import requests
from desktop_ready import safe_env
ROOT=Path.cwd();MODE=os.environ.get('FILM_INSTALL_MODE','one');HOME=Path.home();DOWNLOADS=HOME/'Downloads'
NAMES={'one':'Linux tek satır','app':'AppImage','apt':'DEB / apt','gdebi':'DEB / GDebi'}

def package_status():
 r=subprocess.run(['dpkg-query','-W','-f=${Status} ${Version}','idm-linux'],capture_output=True,text=True)
 return {'installed':r.returncode==0 and 'install ok installed' in r.stdout,'detail':r.stdout.strip(),'returncode':r.returncode}
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def prepare(report,out,appimage):
 DOWNLOADS.mkdir(exist_ok=True);DOWNLOADS.chmod(0o755);HOME.chmod(HOME.stat().st_mode | 0o001);assert not package_status()['installed'],'Not a clean installation runner'
 report['installation_initial_package_status']=package_status();report['installation_mode']=MODE
 if MODE=='app':
  subprocess.run(['gsettings','set','org.gnome.desktop.interface','toolkit-accessibility','true'],env=safe_env(),check=True)
  path=DOWNLOADS/Path(appimage).name;shutil.copyfile(appimage,path);path.chmod(0o644)
  report['installation_asset']={**report['release'],'local_path':str(path)}
 else:
  r=requests.get('https://api.github.com/repos/vesvese55x/IDM-LINUX/releases/latest',timeout=30);r.raise_for_status();rel=r.json();asset=next(a for a in rel['assets'] if a['name']=='idm-linux_1.0.0_all.deb');path=DOWNLOADS/asset['name']
  with requests.get(asset['browser_download_url'],stream=True,timeout=(30,180)) as r:
   r.raise_for_status()
   with path.open('wb') as f:
    for chunk in r.iter_content(65536):f.write(chunk)
  assert path.stat().st_size==asset['size'];digest=sha(path)
  if asset.get('digest'):assert asset['digest']=='sha256:'+digest
  report['installation_asset']={'name':asset['name'],'id':asset['id'],'bytes':asset['size'],'sha256':digest,'publisher_digest':asset.get('digest'),'url':asset['browser_download_url'],'local_path':str(path),'downloaded_before_recording':True}
 report['installation_scope']='Package/control-panel installation only. Wine/IDM engine and actual browser transfers NOT_RUN.'

class Terminal:
 def __init__(self,guard,out,mode,events,epoch):
  self.guard=guard;self.out=Path(out);self.mode=mode;self.events=events;self.epoch=epoch;self.status=self.out/'shell-status.txt';self.transcript=self.out/'installation-terminal.txt'
  self.title='IDM LINUX - Kurulum '+mode+' ['+uuid.uuid4().hex[:10]+']';chapter={'one':'linux-one-line','apt':'linux-deb-apt','app':'linux-appimage'}[mode]
  self.token=guard.allow_install_terminal(chapter,self.title)
  rc=self.out/'installation-bashrc';rc.write_text("PS1='\\u@linux:\\w\\$ '\nHISTFILE=/dev/null\n__film_count=0\nPROMPT_COMMAND='__film_rc=$?;__film_count=$((__film_count+1));printf \"%s %s\\n\" \"$__film_count\" \"$__film_rc\" > "+str(self.status)+"'\n")
  import shlex
  self.process=subprocess.Popen(['xterm','-class','FilmInstallTerminal','-title',self.title,'-fa','DejaVu Sans Mono','-fs','16','-bg','#111b27','-fg','#ecf1f6','-geometry','100x26+80+150','-e','script','-q','-f','-e','-c','bash --rcfile '+shlex.quote(str(rc))+' -i',str(self.transcript)],cwd=DOWNLOADS,env=safe_env(),stdout=(self.out/'terminal-host.log').open('wb'),stderr=subprocess.STDOUT)
  self.wait_ready()
 def state(self):
  try:return tuple(int(v) for v in self.status.read_text().strip().split())
  except Exception:return (0,-1)
 def wait_ready(self):
  deadline=time.monotonic()+20
  while time.monotonic()<deadline:
   if self.state()[0]>0:return
   if self.process.poll() is not None:raise RuntimeError('Real xterm exited before interactive prompt')
   time.sleep(.2)
  raise RuntimeError('Real installation shell did not become ready')
 def stage(self,command):
  import pyautogui
  self.events.append({'action':'real_keyboard_command_staged','command':command,'video_offset_seconds':time.time()-self.epoch})
  pyautogui.write(command,interval=.012)
 def execute(self,timeout=600):
  import pyautogui
  previous=self.state()[0];pyautogui.press('enter');deadline=time.monotonic()+timeout;answered=False
  while time.monotonic()<deadline:
   current=self.state()
   if current[0]>previous:
    self.events.append({'action':'real_command_finished','exit_code':current[1],'video_offset_seconds':time.time()-self.epoch});assert current[1]==0,'Actual installation command failed with exit '+str(current[1]);return
   text=self.transcript.read_text(errors='replace')[-5000:] if self.transcript.exists() else ''
   if not answered and (re.search(r'\[[Ee]/[Hh]\]',text) or re.search(r'\[[Yy]/[Nn]\]',text)):
    time.sleep(3);answer='e' if re.search(r'\[[Ee]/[Hh]\]',text) else 'y';pyautogui.write(answer);pyautogui.press('enter');answered=True
    self.events.append({'action':'real_package_confirmation','answer':answer,'video_offset_seconds':time.time()-self.epoch})
   time.sleep(.3)
  raise RuntimeError('Installation did not return to its real prompt before timeout')
 def close(self):
  import pyautogui
  if self.process.poll() is None:pyautogui.write('exit');pyautogui.press('enter');self.process.wait(timeout=15)
  time.sleep(.5);self.guard.end_install_terminal(self.token)

def run(report,out,screenshot,guard):
 import pyautogui
 out=Path(out);epoch=report['record_wallclock_start'];events=[];cues=[];report.update({'phase':'real-package-installation-lesson','tutorial_audio_cues':cues,'tutorial_browser_events':events,'installation_events':events,'runtime_marks':[],'application_feature_suite':'NOT_RUN','full_functional_suite':'NOT_RUN'})
 manifest={a['file']:a for a in json.loads((ROOT/'capture/install-audio-manifest.json').read_text())}
 app=None;terminal=None;gdebi=None
 def save(): (out/'probe-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 def speak(filename,title,body,actions=None):
  start=time.time();duration=manifest[filename]['duration']
  rect=report.get('installed_gui',{}).get('overview_button_rect')
  if rect:report['runtime_marks'].append({'rect':rect,'start':start-epoch+3,'end':start-epoch+9,'color':'68DAD1','source':'Actual installed Tk widget bounds','target':'Overview navigation button'})
  cues.append({'audio_file':filename,'duration_seconds':duration,'video_offset_seconds':start-epoch,'playback_rate':1.0,'chapter_title':NAMES[MODE],'presentation_notes':[(3,7,title,body)]});screenshot('install-'+filename[:-4]);save()
  for at,fn in actions or []:time.sleep(max(0,start+at-time.time()));fn()
  time.sleep(max(0,start+duration+.8-time.time()))
 def query_gui(timeout=45):
  deadline=time.monotonic()+timeout;previous=None;stable=0
  while time.monotonic()<deadline:
   try:
    d=json.loads((out/'installed-ui.json').read_text());rect=d.get('root_rect',[])
    if d.get('root_viewable') and len(d.get('widgets',[]))>30 and time.time()-d['time']<3 and len(rect)==4 and rect[2:]==[1380,870] and 30<=rect[0]<=150 and 70<=rect[1]<=140:
     if previous==rect:stable+=1
     else:stable=0
     previous=rect
     if stable>=2:return d
   except Exception:pass
   if app and app.poll() is not None:raise RuntimeError('Actual installed application exited before a stable live GUI')
   time.sleep(.45)
  raise RuntimeError('The actually installed control panel did not produce a usable live window')
 def open_gui(argv=None):
  nonlocal app
  env=safe_env();env.update({'FILM_WIDGET_DUMP':str(out/'installed-ui.json'),'FILM_CAPTURE_GEOMETRY':'1380x870+70+100','PYTHONPATH':str(ROOT/'capture/probe_site')})
  app=subprocess.Popen(argv or ['idm-linux','gui'],env=env,stdout=(out/'installed-application.log').open('wb'),stderr=subprocess.STDOUT)
  d=query_gui();report['installed_gui']={'title':d['root_title'],'rect':d['root_rect'],'actual_launch':argv or ['idm-linux','gui'],'visible_widgets':len(d['widgets']),'application_modified':False};screenshot('installed-real-gui')
  # Actual native widget rectangle; no browser-only geometry assumptions.
  for w in d['widgets']:
   if w['class'] in ['Button','TButton'] and ('Genel Bak' in w['text'] or 'Overview' in w['text']):
    report['installed_gui']['overview_button_rect']=w['rect'];x,y,ww,hh=w['rect'];pyautogui.moveTo(x+ww/2,y+hh/2,duration=.5);events.append({'action':'real_mouse_click','target':'Installed application overview','x':x+ww/2,'y':y+hh/2,'video_offset_seconds':time.time()-epoch});pyautogui.click();time.sleep(1);verified=query_gui();assert any('Genel Bakış & Canlı' in w.get('text','') or 'Overview & Live' in w.get('text','') for w in verified['widgets']),'Actual overview click did not open the requested page';report['installed_gui']['overview_navigation_verified']=True;pyautogui.moveTo(1500,960,duration=.3);break
 def dpkg_verify():
  state=package_status();assert state['installed'],state;report['installation_final_package_status']=state
 def gtk_rows():
  try:
   d=json.loads((out/'gdebi-widgets.json').read_text());return d['widgets'] if time.time()-d['time']<4 else []
  except Exception:return []
 def wait_gtk_button(tokens,timeout=45):
  deadline=time.monotonic()+timeout
  while time.monotonic()<deadline:
   for w in gtk_rows():
    text=w['text'].replace('_','').casefold()
    if 'Button' in w['class'] and w['sensitive'] and any(t in text for t in tokens):return w
   time.sleep(.4)
  raise RuntimeError('Real GDebi button unavailable: '+str(tokens))
 def click_widget(w,label):
  x,y,ww,hh=w['rect'];assert ww>10 and hh>10 and 0<x+ww/2<1920 and 0<y+hh/2<1032
  pyautogui.moveTo(x+ww/2,y+hh/2,duration=.55);events.append({'action':'real_mouse_click','target':label,'x':x+ww/2,'y':y+hh/2,'video_offset_seconds':time.time()-epoch});pyautogui.click()
 def thunar_windows():
  rows=[]
  for line in subprocess.check_output(['wmctrl','-lGx'],text=True).splitlines():
   fields=line.split(None,8)
   if len(fields)>=9 and 'thunar' in fields[6].casefold():rows.append({'id':fields[0],'rect':[int(v) for v in fields[2:6]],'title':fields[8]})
  return rows
 def file_manager_request(method):
  uri=Path(report['installation_asset']['local_path']).as_uri()
  cmd=['gdbus','call','--session','--dest','org.freedesktop.FileManager1','--object-path','/org/freedesktop/FileManager1','--method','org.freedesktop.FileManager1.'+method,"['"+uri+"']",'']
  result=subprocess.run(cmd,capture_output=True,text=True,env=safe_env());events.append({'action':'native_file_manager_api','method':method,'actual_file_uri':uri,'returncode':result.returncode,'video_offset_seconds':time.time()-epoch});assert result.returncode==0,'Native FileManager1 '+method+' failed: '+result.stderr
 def properties():
  before={w['id'] for w in thunar_windows()};file_manager_request('ShowItemProperties');deadline=time.monotonic()+10
  while time.monotonic()<deadline:
   opened=[w for w in thunar_windows() if w['id'] not in before]
   if opened:report['appimage_real_properties_window']=opened[0];screenshot('appimage-properties');return
   time.sleep(.3)
  raise RuntimeError('Actual AppImage properties dialog did not open')
 def permissions():
  # Standard GTK notebook keyboard navigation, with actual property dialog.
  pyautogui.hotkey('ctrl','pagedown');time.sleep(.4);pyautogui.hotkey('ctrl','pagedown');time.sleep(1);screenshot('appimage-permissions-visible')
 try:
  if MODE in ['one','apt']:
   terminal=Terminal(guard,out,MODE,events,epoch)
   if MODE=='one':
    speak('one-01.mp3','KONTROL PANELİ',['Motor kurulumu ayrı','Temiz Ubuntu oturumu'])
    terminal.stage('curl -fsSL https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/belgeselsemo-idm-linux-installer | sh')
    speak('one-02.mp3','KOMUT = GÜVEN',['Resmî adresi doğrula','İndirilen betik çalışır'])
   else:
    terminal.stage('cd ~/Downloads');terminal.execute(20);terminal.stage('sudo apt install ./idm-linux_1.0.0_all.deb')
    speak('apt-01.mp3','YEREL DEB PAKETİ',['./ bu klasör demektir','Onay sorusunu oku'])
   terminal.execute(600);dpkg_verify();terminal.stage("dpkg-query -W -f='${Status} ${Version}\\n' idm-linux");terminal.execute(20);time.sleep(5);screenshot('installation-terminal-verified');terminal.close();terminal=None;open_gui()
   speak('one-03.mp3' if MODE=='one' else 'apt-02.mp3','GERÇEK PENCERE',['Paket kaydı doğrulandı','Motor/indirme testi ayrı'])
  elif MODE=='app':
   path=Path(report['installation_asset']['local_path']);thunar=subprocess.Popen(['thunar',str(DOWNLOADS)],env={**safe_env(),'GTK_MODULES':'atk-bridge','NO_AT_BRIDGE':'0','GTK_THEME':'Adwaita:dark'},stdout=(out/'thunar.log').open('wb'),stderr=subprocess.STDOUT);time.sleep(3)
   native=thunar_windows();assert native,'Real Thunar file manager did not open';file_window=max(native,key=lambda w:w['rect'][2]*w['rect'][3]);subprocess.run(['wmctrl','-ir',file_window['id'],'-e','0,70,100,1360,820'],check=True);subprocess.run(['wmctrl','-ia',file_window['id']],check=True);time.sleep(1)
   assert [p.name for p in DOWNLOADS.iterdir() if p.is_file()]==[path.name],'Fresh download directory must contain only the demonstrated AppImage'
   pyautogui.hotkey('ctrl','l');pyautogui.write(str(DOWNLOADS));pyautogui.press('enter');time.sleep(1);pyautogui.press('esc');file_manager_request('ShowItems');time.sleep(1);report['appimage_real_file_manager_window']=file_window
   speak('app-01.mp3','APPIMAGE İZNİ',['Dosya ≠ paket kaydı','chmod +x: çalıştırma izni'],actions=[(15,properties),(26,permissions)])
   pyautogui.hotkey('alt','f4');time.sleep(.5);pyautogui.hotkey('alt','f4');time.sleep(.8)
   terminal=Terminal(guard,out,MODE,events,epoch);terminal.stage('chmod +x '+path.name);time.sleep(7);terminal.execute(20);assert os.access(path,os.X_OK);screenshot('appimage-chmod-verified');terminal.close();terminal=None
   try:open_gui([str(path)]) ;report['appimage_launch_method']='Direct released AppImage with FUSE'
   except RuntimeError:
    text=(out/'installed-application.log').read_text(errors='replace').casefold()
    if not any(term in text for term in ['fuse','cannot mount appimage','operation not permitted']):raise
    if app and app.poll() is None:app.terminate();app.wait(10)
    terminal=Terminal(guard,out,MODE,events,epoch);terminal.stage('./'+path.name+' --appimage-extract');time.sleep(5);terminal.execute(180);time.sleep(3);terminal.close();terminal=None
    launch=DOWNLOADS/'squashfs-root/AppRun';assert launch.exists();open_gui([str(launch)]);report['appimage_launch_method']='Explicit real --appimage-extract then extracted AppRun; not claimed direct FUSE'
    report['appimage_fuse_fallback']=True
   speak('app-02.mp3','FUSE ALTERNATİFİ' if report.get('appimage_fuse_fallback') else 'DOĞRUDAN APPIMAGE',['Çıkarılmış AppRun açıldı','FUSE ile açılış değildir'] if report.get('appimage_fuse_fallback') else ['AppImage → gerçek GUI','Paket kaydı gerektirmez'])
   assert not package_status()['installed'],'AppImage lesson must not silently install a DEB'
  elif MODE=='gdebi':
   asset=Path(report['installation_asset']['local_path']);env=safe_env();assign={k:env[k] for k in ['DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','LANG','LC_ALL','LANGUAGE'] if k in env};assign.update({'PYTHONPATH':str(ROOT/'capture/gtk_probe'),'FILM_GTK_WIDGET_DUMP':str(out/'gdebi-widgets.json')})
   cmd=['sudo','-n','env']+[k+'='+v for k,v in assign.items()]+['/usr/bin/python3','/usr/bin/gdebi-gtk',str(asset)]
   gdebi=subprocess.Popen(cmd,stdout=(out/'gdebi.log').open('wb'),stderr=subprocess.STDOUT);button=wait_gtk_button(['paketi kur','install package']);report['gdebi_administrator_launch_disclosed']=True
   speak('gdebi-01.mp3','GRAFİK YÜKLEYİCİ',['Ayrı temiz oturum','Runner: yönetici yetkili'])
   speak('gdebi-02.mp3','KURMADAN ÖNCE',['Paket adı ve sürüm','Bağımlılık uyarılarını oku'])
   report['runtime_marks'].append({'rect':button['rect'],'start':time.time()-epoch-.3,'end':time.time()-epoch+1.5,'color':'EB6975','source':'Actual GDebi GTK widget bounds','target':'Install Package button'})
   click_widget(button,'Actual GDebi Install Package button');deadline=time.monotonic()+300
   while time.monotonic()<deadline and not package_status()['installed']:time.sleep(.5)
   dpkg_verify();time.sleep(5);screenshot('gdebi-real-install-completed');report['gdebi_real_install_button_clicked']=True
   # Close completed native dialogs, then the actual graphical loader.
   for _ in range(3):
    if gdebi.poll() is not None:break
    pyautogui.hotkey('alt','f4');time.sleep(.8)
   open_gui();speak('gdebi-03.mp3','İKİ AYRI YOL',['apt veya GDebi','Aynı kontrol paneli'])
  else:raise RuntimeError('Unknown real installation mode '+MODE)
  report['functional_cases']=[{'id':'real-package-install-'+MODE,'status':'PASS','initial':report['installation_initial_package_status'],'final':package_status(),'real_gui':report['installed_gui'],'scope':report['installation_scope']}];screenshot('installation-lesson-complete');save()
 finally:
  if terminal:
   try:terminal.close()
   except Exception:
    terminal.process.terminate();terminal.process.wait(10);time.sleep(.5);guard.end_install_terminal(terminal.token)
  if app and app.poll() is None:app.terminate()
  if gdebi and gdebi.poll() is None:gdebi.terminate()

def finish(report,out):
 from presentation_overlay import build
 out=Path(out);source=out/'native-linux.mp4';duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(source)],text=True));cues=report['tutorial_audio_cues'];assert cues
 overlay,audit=build(out,report,duration);report['presentation_audit']=audit
 target=out/('BELGESELSEMO-EGITIM-KURULUM-'+MODE.upper()+'-TR.mp4');cmd=['ffmpeg','-y','-v','warning','-i',str(source)];filters=[]
 for i,c in enumerate(cues,1):
  cmd+=['-i',str(ROOT/'capture/install_audio'/c['audio_file'])];filters.append(f'[{i}:a]adelay={round(c["video_offset_seconds"]*1000)}:all=1[a{i}]')
 labels=''.join(f'[a{i}]' for i in range(1,len(cues)+1));filters.append(labels+f'amix=inputs={len(cues)}:normalize=0,apad[voice]');cmd+=['-stream_loop','-1','-i',str(ROOT/'capture/tutorial_audio/technology-bed.mp3')];filters.append(f'[{len(cues)+1}:a]volume=0.32,afade=t=in:d=1.5,afade=t=out:st={duration-2}:d=2[bg]');filters.append('[voice][bg]amix=inputs=2:normalize=0,alimiter=limit=.95[a]')
 cmd+=['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-vf','ass='+str(overlay),'-map','0:v','-map','[a]','-c:v','libx264','-threads','2','-preset','veryfast','-crf','17','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-c:a','aac','-b:a','160k','-ar','48000','-ac','2','-t',str(duration),'-movflags','+faststart',str(target)]
 with (out/'install-mux.log').open('wb') as f:subprocess.run(cmd,stdout=f,stderr=f,check=True)
 check=subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],capture_output=True,text=True);assert check.returncode==0 and not check.stderr,check.stderr
 md5=hashlib.md5(target.read_bytes()).hexdigest()
 with target.open('rb') as f:r=requests.post('https://upload.gofile.io/uploadfile',files={'file':(target.name,f,'video/mp4')},timeout=(30,300))
 r.raise_for_status();data=r.json();assert data['status']=='ok';data=data['data'];assert data['md5']==md5 and data['size']==target.stat().st_size
 receipt={'mode':MODE,'download_page':data['downloadPage'],'file':target.name,'bytes':target.stat().st_size,'md5':md5,'sha256':sha(target),'duration':duration,'full_decode':'PASS','scope':report['installation_scope'],'voice_rate':1.0};report['tutorial_delivery']=receipt;(out/'tutorial-gofile.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
 proofs=out/'tutorial-receipts';proofs.mkdir(exist_ok=True)
 for name in ['tutorial-gofile.json','console-visibility-audit.json','pointer-audit.json','presentation-audit.json','desktop-shell-audit.json']:
  p=out/name
  if p.exists():shutil.copyfile(p,proofs/name)
 from PIL import Image
 for name in ['installed-real-gui','installation-terminal-verified','gdebi-real-install-completed','appimage-properties','appimage-permissions-visible','installation-lesson-complete']:
  p=out/(name+'.png')
  if p.exists():im=Image.open(p).convert('RGB');im.thumbnail((1280,720));im.save(proofs/(name+'.jpg'),quality=83)
 when=cues[-1]['video_offset_seconds']+5;subprocess.run(['ffmpeg','-v','error','-ss',str(when),'-i',str(target),'-frames:v','1','-vf','scale=1280:-2','-q:v','3','-y',str(proofs/'installation-final-presented.jpg')],check=True)
 print(json.dumps({'installation_delivery':receipt},ensure_ascii=False),flush=True)
