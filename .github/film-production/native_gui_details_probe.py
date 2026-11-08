"""Genuine native category and queue recording. Private footage still needs editing and listening QC."""
import os,json,time,subprocess,signal,ast,hashlib
from pathlib import Path
import cv2
from idm_linux.config import IdmLinuxConfig
from idm_linux.wine_sender import build_wine_env
from turkish_quality_gate import assert_clean
O=Path('out/film14-native-gui-details').resolve();O.mkdir(parents=True,exist_ok=True)
cfg=IdmLinuxConfig.load();assert cfg.find_idm_exe();os.environ.update(build_wine_env(cfg));probe=Path('out/film14-native-turkish/native-turkish-probe.exe').resolve();epoch=time.monotonic();events=[];recorder=None
names={'save','event','shot','physical','keys','activate','native','button','type_ascii'};tree=ast.parse(Path('.github/film-production/native_pixeldrain_capture.py').read_text());exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'existing-real-input-primitives','exec'))
r={'scope':'Real native category sidebar and scheduler/queue control inspection only','finished_lesson':False,'final_film_export_allowed':False,'widget_or_progress_injection':False}
try:
 for l in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
  if 'günün ipucu' in l.lower():subprocess.run(['wmctrl','-ia',l.split()[0]],check=True);keys('Escape')
 from desktop_style import apply_desktop_style
 apply_desktop_style(O)
 for row in subprocess.check_output(['wmctrl','-lx'],text=True).splitlines():
  if 'brave' in row.lower():subprocess.run(['xdotool','windowminimize',row.split()[0]],check=True)
 native_xids=[]
 for row in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
  parts=row.split(None,3)
  if len(parts)==4 and __import__('re').fullmatch(r'Internet Download Manager [0-9.]+',parts[3]):native_xids.append(parts[0])
 assert len(native_xids)==1,'Never activate the similarly titled Brave welcome page'
 subprocess.run(['wmctrl','-ia',native_xids[0]],check=True);time.sleep(.5)
 recorder=subprocess.Popen(['ffmpeg','-nostdin','-y','-v','warning','-f','x11grab','-draw_mouse','0','-s','1920x1080','-r','24','-i',os.environ['DISPLAY'],'-an','-c:v','libx264','-preset','veryfast','-crf','18','-threads','2',str(O/'uncut-real-native-gui-details-probe.mp4')],stdout=subprocess.DEVNULL,stderr=open(O/'actual-capture.log','w'))
 cc,tt,ww=native('01-real-native-sidebar');r['actual_main_controls']=cc;r['actual_main_titles']=ww;time.sleep(4)
 im=cv2.imread(str(O/'01-real-native-sidebar.png'));icon=cv2.imread('.github/film-production/actual-native-scheduler-icon.png');_,score,_,pos=cv2.minMaxLoc(cv2.matchTemplate(im,icon,cv2.TM_CCOEFF_NORMED));r['actual_scheduler_template_match']=score;assert score>.985,'Do not guess an unmatched actual scheduler icon'
 physical([*pos,pos[0]+icon.shape[1],pos[1]+icon.shape[0]],'actual-native-scheduler-toolbar-click');time.sleep(1)
 cc,tt,ww=native('02-real-native-scheduler-and-queue');r['actual_scheduler_controls']=cc;r['actual_scheduler_titles']=ww;r['actual_scheduler_texts']=tt;time.sleep(6)
 r['actual_scheduler_inspection_recorded']=True
 button(cc,'Yeni kuyruk');time.sleep(.5)
 cc,tt,ww=native('03-real-new-queue-dialog');r['actual_new_queue_dialog_controls']=cc;r['actual_new_queue_dialog_titles']=ww
 dialogs=[c for c in cc if c['visible'] and c['class']=='#32770' and ('yeni' in c['text'].lower() or 'kuyruk' in c['text'].lower()) and c['text']!='Programlayıcı'];assert len(dialogs)==1
 box=dialogs[0]['rect'];edits=[c for c in cc if c['visible'] and c['class']=='Edit' and box[0]<=c['rect'][0]<c['rect'][2]<=box[2] and box[1]<=c['rect'][1]<c['rect'][3]<=box[3]];assert len(edits)==1
 physical(edits[0]['rect'],'actual-new-queue-name-field');keys('ctrl+a');type_ascii('Film-Kuyrugu');button(cc,'Tamam');time.sleep(.6)
 cc,tt,ww=native('04-real-created-queue');r['actual_created_queue_texts']=tt;assert any('Film-Kuyrugu' in t for t in tt),'New actual queue name must be read back'
 r['actual_named_queue_created']=True
 tabs=[c for c in cc if c['visible'] and c['class']=='SysTabControl32'];assert len(tabs)==1
 x,y,_,_=tabs[0]['rect'];physical([x+105,y+2,x+175,y+20],'actual-queued-files-tab-independently-measured-in-run42470729360');time.sleep(.5)
 cc,tt,ww=native('05-real-queued-files-tab');r['actual_queued_files_controls']=cc;r['actual_queued_files_texts']=tt;time.sleep(4)
 button(cc,'Kapat');time.sleep(.5)
 import threading,functools
 from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
 source=O/'own-source';source.mkdir(exist_ok=True);(source/'film-dersi.lesson').write_bytes(bytes(range(256))*8192)
 class Source(SimpleHTTPRequestHandler):
  def log_message(self,*args):pass
  def copyfile(self,src,out):
   try:
    while True:
     data=src.read(8192)
     if not data:break
     out.write(data);out.flush();time.sleep(.25)
   except OSError:pass
 server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Source,directory=str(source)));threading.Thread(target=server.serve_forever,daemon=True).start()
 shot('06-real-main-before-own-url');im=cv2.imread(str(O/'06-real-main-before-own-url.png'));icon=cv2.imread('.github/film-production/actual-native-url-icon.png');_,score,_,pos=cv2.minMaxLoc(cv2.matchTemplate(im,icon,cv2.TM_CCOEFF_NORMED));assert score>.985
 physical([*pos,pos[0]+icon.shape[1],pos[1]+icon.shape[0]],'actual-own-file-url-add');time.sleep(.5)
 cc,tt,ww=native('07-real-own-url-dialog');assert 'İndirilecek yeni adresi girin' in ww
 edits=[c for c in cc if c['visible'] and c['class']=='Edit' and not c['style']&0x08000000];assert len(edits)==1
 physical(edits[0]['rect'],'actual-own-source-url-field');keys('ctrl+a');type_ascii(f'http://127.0.0.1:{server.server_port}/film-dersi.lesson');button(cc,'Tamam');time.sleep(2)
 cc,tt,ww=native('08-real-own-file-information');assert any('Dosya İndirme Bilgisi' in w for w in ww)
 button(cc,'+');time.sleep(.5)
 cc,tt,ww=native('09-real-new-category-dialog');r['actual_new_category_controls']=cc;r['actual_new_category_titles']=ww;r['actual_new_category_texts']=tt;time.sleep(5)
 # Every field is located from the actual inspected category dialog, not an invented UI.
 from pathlib import PureWindowsPath
 boxes=[c for c in cc if c['visible'] and c['class']=='#32770' and c['text']=='Bir kategoriyi IDM kategoriler listesine ekleme'];assert len(boxes)==1
 box=boxes[0]['rect'];fields={}
 for name,dy in [('name',50),('extensions',99),('folder',253)]:
  found=[c for c in cc if c['visible'] and c['class']=='Edit' and c['rect'][1]==box[1]+dy and c['rect'][0]==box[0]+17];assert len(found)==1;fields[name]=found[0]
 actual_default=PureWindowsPath(fields['folder']['text']);assert actual_default.drive.upper()=='C:'
 win_dest=str(actual_default/'Film-Dersleri')+'\\';destination=Path(cfg.wine_prefix)/'drive_c'/Path(*actual_default.parts[1:])/'Film-Dersleri'
 assert destination.resolve().is_relative_to(Path.home().resolve());destination.mkdir(parents=True,exist_ok=True);outfile=destination/'film-dersi.lesson';assert not outfile.exists(),'Do not overwrite any existing output'
 typed={'name':'Film-Dersleri','extensions':'lesson','folder':win_dest}
 for name,value in typed.items():physical(fields[name]['rect'],'actual-category-field-'+name);keys('ctrl+a');type_ascii(value)
 cc,tt,ww=native('10-real-category-fields-before-save')
 for name,value in typed.items():assert any(c['rect']==fields[name]['rect'] and c['text']==value for c in cc),'Typed native category field must read back exactly'
 button(cc,'Tamam');time.sleep(1)
 cc,tt,ww=native('11-real-category-selected-in-file-information');assert any(c['visible'] and c['class']=='ComboBox' and c['text']=='Film-Dersleri' for c in cc)
 r['actual_category_created']={'name':'Film-Dersleri','extension':'lesson','native_folder':win_dest,'fields_read_back':True}
 button(cc,'Daha Sonra İndir');time.sleep(2)
 cc,tt,ww=native('12-real-download-later-main-window');assert 'Dosya İndirme Bilgisi' not in ww
 shot('13-real-main-before-scheduler-start');im=cv2.imread(str(O/'13-real-main-before-scheduler-start.png'));icon=cv2.imread('.github/film-production/actual-native-scheduler-icon.png');_,score,_,pos=cv2.minMaxLoc(cv2.matchTemplate(im,icon,cv2.TM_CCOEFF_NORMED));assert score>.985
 physical([*pos,pos[0]+icon.shape[1],pos[1]+icon.shape[0]],'actual-scheduler-for-owned-pending-file');time.sleep(.5)
 cc,tt,ww=native('14-real-scheduler-before-main-queue-selection');scheduler=[c for c in cc if c['visible'] and c['class']=='#32770' and c['text']=='Programlayıcı'];assert len(scheduler)==1;box=scheduler[0]['rect'];trees=[c for c in cc if c['visible'] and c['class']=='SysTreeView32' and box[0]<=c['rect'][0]<c['rect'][2]<=box[2] and box[1]<=c['rect'][1]<c['rect'][3]<=box[3]];assert len(trees)==1
 x,y,_,_=trees[0]['rect'];physical([x+20,y+2,x+150,y+19],'actual-first-main-queue-row-inspected-in-run42471276559');time.sleep(.5)
 cc,tt,ww=native('15-real-selected-main-queue');assert 'Ana indirme kuyruğu' in tt
 # Read standard native checkboxes with BM_GETCHECK; no checkbox state is changed.
 raw=(O/'15-real-selected-main-queue-raw.txt').read_text();checks={};labels={}
 for line in raw.splitlines():
  a=line.split('\t')
  if a[0]=='CHECKSTATE':checks[a[1]]=int(a[2])
  if a[0]=='CONTROL' and len(a)>7:labels[a[1]]=bytes.fromhex(a[7]).decode('utf8')
 hazardous={h:labels.get(h,'') for h in checks if any(term in labels.get(h,'').lower() for term in ['bittiğinde','zorla','modemi','bilgisayarı','aşağıdaki dosyayı'])}
 assert len(hazardous)>=4 and all(checks[h]==0 for h in hazardous),'Never start a queue with automatic shutdown, forced exit, executable opening, or modem actions enabled'
 assert not any(line.startswith('QUERY_UNAVAILABLE\t'+h+'\t240\t') for h in hazardous for line in raw.splitlines())
 r['actual_dangerous_options_unchecked_before_queue_start']={hazardous[h]:checks[h] for h in hazardous}
 tabs=[c for c in cc if c['visible'] and c['class']=='SysTabControl32'];assert len(tabs)==1;x,y,_,_=tabs[0]['rect'];physical([x+105,y+2,x+175,y+20],'actual-main-queue-files-tab');time.sleep(.4)
 cc,tt,ww=native('16-real-owned-file-in-main-queue');raw=(O/'16-real-owned-file-in-main-queue-raw.txt').read_text();counts=[int(line.split('\t')[2]) for line in raw.splitlines() if line.startswith('LISTCOUNT\t')];assert 1 in counts,'Actual native queued-files list must contain the pending file'
 r['actual_main_queue_file_counts_before_start']=counts;time.sleep(4)
 button(cc,'Şimdi başlat');event('actual-main-queue-start-now');deadline=time.monotonic()+180;expected=hashlib.sha256((source/'film-dersi.lesson').read_bytes()).hexdigest();samples=[]
 while time.monotonic()<deadline:
  cc,tt,ww=native(f'17-real-queue-progress-{len(samples):02d}');samples.append({'elapsed':time.monotonic()-epoch,'titles':ww,'texts':tt})
  if outfile.is_file() and outfile.stat().st_size==2097152 and hashlib.file_digest(outfile.open('rb'),'sha256').hexdigest()==expected:break
  time.sleep(3)
 else:raise AssertionError('No verified original native queue completion in the finite recording window')
 event('actual-native-queue-output-hash-verified');time.sleep(6);cc,tt,ww=native('18-real-native-queue-after-verified-completion')
 r['actual_queue_progress_samples']=samples;r['actual_queue_output']={'path':str(outfile),'bytes':outfile.stat().st_size,'sha256':hashlib.file_digest(outfile.open('rb'),'sha256').hexdigest(),'expected_sha256':expected,'own_local_source_only':True,'original_native_downloader':True};r['category_creation_or_queue_transfer_completed']=True
 r['scope']='Genuine own-source native category creation, Download Later, main-queue list, Start Now, progress and SHA-verified completion; separately created named queue remains unpopulated'
 server.shutdown();server.server_close()
finally:
 if recorder is not None:recorder.send_signal(signal.SIGINT);recorder.wait(timeout=30)
 manifest=json.loads(Path('out/film14-native-turkish/original-vendor-payload-manifest.json').read_text());vendor=cfg.find_idm_exe().parent;r['original_vendor_binaries_unchanged']=all((vendor/f).is_file() and hashlib.file_digest((vendor/f).open('rb'),'sha256').hexdigest()==h for f,h in manifest['files'].items() if Path(f).suffix.lower() in ['.exe','.dll','.sys']);save('actual-native-gui-details-review.json',r)
assert r['original_vendor_binaries_unchanged']
