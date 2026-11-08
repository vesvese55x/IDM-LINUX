"""Read-only genuine native category/sidebar and scheduler reconnaissance, not a completed lesson."""
import os,json,time,subprocess,signal,ast,hashlib
from pathlib import Path
import cv2
from idm_linux.config import IdmLinuxConfig
from idm_linux.wine_sender import build_wine_env
from turkish_quality_gate import assert_clean
O=Path('out/film14-native-gui-details').resolve();O.mkdir(parents=True,exist_ok=True)
cfg=IdmLinuxConfig.load();assert cfg.find_idm_exe();os.environ.update(build_wine_env(cfg));probe=Path('out/film14-native-turkish/native-turkish-probe.exe').resolve();epoch=time.monotonic();events=[];recorder=None
names={'save','event','shot','physical','keys','activate','native','button'};tree=ast.parse(Path('.github/film-production/native_pixeldrain_capture.py').read_text());exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'existing-real-input-primitives','exec'))
r={'scope':'Real native category sidebar and scheduler/queue control inspection only','finished_lesson':False,'final_film_export_allowed':False,'widget_or_progress_injection':False}
try:
 for l in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
  if 'günün ipucu' in l.lower():subprocess.run(['wmctrl','-ia',l.split()[0]],check=True);keys('Escape')
 activate('Internet Download Manager')
 recorder=subprocess.Popen(['ffmpeg','-nostdin','-y','-v','warning','-f','x11grab','-draw_mouse','0','-s','1920x1080','-r','24','-i',os.environ['DISPLAY'],'-an','-c:v','libx264','-preset','veryfast','-crf','18','-threads','2',str(O/'uncut-real-native-gui-details-probe.mp4')],stdout=subprocess.DEVNULL,stderr=open(O/'actual-capture.log','w'))
 cc,tt,ww=native('01-real-native-sidebar');r['actual_main_controls']=cc;r['actual_main_titles']=ww;time.sleep(4)
 im=cv2.imread(str(O/'01-real-native-sidebar.png'));icon=cv2.imread('.github/film-production/actual-native-scheduler-icon.png');_,score,_,pos=cv2.minMaxLoc(cv2.matchTemplate(im,icon,cv2.TM_CCOEFF_NORMED));r['actual_scheduler_template_match']=score;assert score>.985,'Do not guess an unmatched actual scheduler icon'
 physical([*pos,pos[0]+icon.shape[1],pos[1]+icon.shape[0]],'actual-native-scheduler-toolbar-click');time.sleep(1)
 cc,tt,ww=native('02-real-native-scheduler-and-queue');r['actual_scheduler_controls']=cc;r['actual_scheduler_titles']=ww;r['actual_scheduler_texts']=tt;time.sleep(6)
 r['actual_scheduler_inspection_recorded']=True
finally:
 if recorder is not None:recorder.send_signal(signal.SIGINT);recorder.wait(timeout=30)
 manifest=json.loads(Path('out/film14-native-turkish/original-vendor-payload-manifest.json').read_text());vendor=cfg.find_idm_exe().parent;r['original_vendor_binaries_unchanged']=all((vendor/f).is_file() and hashlib.file_digest((vendor/f).open('rb'),'sha256').hexdigest()==h for f,h in manifest['files'].items() if Path(f).suffix.lower() in ['.exe','.dll','.sys']);save('actual-native-gui-details-review.json',r)
assert r['original_vendor_binaries_unchanged']
