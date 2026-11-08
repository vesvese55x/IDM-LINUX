"""Actual original Tk GUI + actual original daemon; independent no-IDM media profile.
Owned real RSS, no fabricated API/status/widgets, no helper healing or vendor modifications.
"""
import os,sys,json,time,threading,subprocess,functools,signal,hashlib
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
O=Path('out/film14-playlist-gui-owned').resolve();O.mkdir(parents=True,exist_ok=True)
# A genuinely separate media-only configuration, not a hidden/reset licensed installation.
for k,s in [('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache')]:os.environ[k]=str(O/s)
from idm_linux.config import IdmLinuxConfig
cfg=IdmLinuxConfig(language='tr',wine_prefix=str(O/'no-native-installed'),download_dir=str(O/'actual-downloads'),http_port=35641,ws_port=35642,keep_wine_warm=False);cfg.save();assert cfg.find_idm_exe() is None
source=O/'own-source';source.mkdir(exist_ok=True)
for n in range(1,4):
 subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=size=640x360:rate=24','-f','lavfi','-i',f'sine=frequency={330*n}:sample_rate=48000','-t','12','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(source/f'own-clip-{n}.mp4')],check=True)
class Source(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
 def copyfile(self,src,out):
  # Real explicitly bandwidth-limited OWN source, not simulated client progress.
  try:
   while True:
    b=src.read(16384)
    if not b:break
    out.write(b);out.flush()
    if self.path.split('?')[0].endswith('.mp4'):time.sleep(.125)
  except (BrokenPipeError,ConnectionResetError):pass
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Source,directory=str(source)));threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
items=''.join(f'<item><title>İzinli örnek ders {i}</title><guid>own-item-{i}</guid><enclosure url="{origin}/own-clip-{i}.mp4" type="video/mp4" length="{(source/f"own-clip-{i}.mp4").stat().st_size}"/></item>' for i in range(1,4))
(source/'playlist.rss').write_text('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Kendi izinli örnek listemiz</title><description>Actual owned generated media. Source limited to 128 KiB/s for visible real transfers.</description><link>'+origin+'</link>'+items+'</channel></rss>');url=origin+'/playlist.rss?list=own-demo'
daemon=subprocess.Popen([sys.executable,'-m','idm_linux.cli','daemon-run'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
from idm_linux.daemon import is_daemon_running
for i in range(80):
 if is_daemon_running(cfg):break
 if daemon.poll() is not None:raise RuntimeError('Original daemon exited')
 time.sleep(.25)
assert is_daemon_running(cfg)
import tkinter as tk
from tkinter import ttk
from idm_linux.i18n import I18nManager
from desktop_style import apply_desktop_style
apply_desktop_style(O)
from turkish_quality_gate import visible_widget_gate
T=I18nManager('tr').t;original=tk.Tk.__init__;ROOT=None;events=[];failures=[];rec=None;start=time.monotonic()
def ev(k,**kw):events.append({'seconds':round(time.monotonic()-start,3),'event':k,**kw});(O/'actual-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2))
def widgets(w):
 a=[]
 for c in w.winfo_children():a.append(c);a.extend(widgets(c))
 return a
def shot(tag):
 visible_widget_gate(ROOT,O,tag);subprocess.run(['import','-window','root',str(O/(tag+'.png'))],check=True)
def click(w,tag):
 x=w.winfo_rootx()+w.winfo_width()//2;y=w.winfo_rooty()+w.winfo_height()//2
 assert w.winfo_ismapped() and 0<x<1920 and ROOT.winfo_rooty()+20<y<ROOT.winfo_rooty()+ROOT.winfo_height()-10,('Offscreen original control',str(w),x,y)
 ev(tag,widget_class=w.winfo_class(),text=str(w.cget('text')) if 'text' in w.keys() else '',point=[x,y]);subprocess.run(['xdotool','mousemove',str(x),str(y),'click','1'],check=True);ROOT.update()
def find(label):
 a=[w for w in widgets(ROOT) if isinstance(w,(tk.Button,ttk.Button)) and w.winfo_ismapped() and str(w.cget('text'))==label];assert len(a)==1,(label,len(a));return a[0]
def bottom():
 subprocess.run(['xdotool','mousemove',str(ROOT.winfo_rootx()+900),str(ROOT.winfo_rooty()+400),'click','--repeat','24','--delay','35','5'],check=True)
def begin():
 global rec,start
 ROOT.geometry('1460x900+380+40');ROOT.update_idletasks();start=time.monotonic()
 rec=subprocess.Popen(['ffmpeg','-nostdin','-y','-v','error','-f','x11grab','-draw_mouse','0','-video_size','1920x1080','-framerate','24','-i',os.environ['DISPLAY'],'-an','-c:v','libx264','-preset','veryfast','-crf','18','-threads','2',str(O/'uncut-owned-playlist-gui.mp4')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 shot('01-actual-original-overview');bottom();ROOT.after(1300,enter)
def enter():
 b=find(T('ov.pl_card_btn_list'));row=b.master;entries=[w for w in row.winfo_children() if isinstance(w,tk.Entry)];assert len(entries)==1
 click(entries[0],'actual-own-rss-address-input');subprocess.run(['xdotool','type','--clearmodifiers','--delay','2',url],check=True);click(b,'actual-list-own-playlist');ROOT.after(3000,listed)
def listed(attempt=0):
 cbs=[w for w in widgets(ROOT) if isinstance(w,tk.Checkbutton) and w.winfo_ismapped() and str(w.cget('text'))=='']
 if len(cbs)!=3:
  if attempt<30:ROOT.after(1000,lambda:listed(attempt+1));return
  raise AssertionError(('Actual own three-entry list did not appear',len(cbs)))
 bottom();shot('02-actual-three-entry-list');ev('actual-real-list-three-checkboxes',count=len(cbs))
 (O/'original-visible-widget-dump.json').write_text(json.dumps([{'class':w.winfo_class(),'text':str(w.cget('text')) if 'text' in w.keys() else '', 'rect':[w.winfo_rootx(),w.winfo_rooty(),w.winfo_width(),w.winfo_height()]} for w in widgets(ROOT) if w.winfo_ismapped()],ensure_ascii=False,indent=2))
 ROOT.after(2200,select_and_start)
def actual_batches():
 import urllib.request
 with urllib.request.urlopen('http://127.0.0.1:35641/api/playlist/batch/list',timeout=4) as r:d=json.loads(r.read())
 (O/'actual-daemon-batches.json').write_text(json.dumps(d,ensure_ascii=False,indent=2))
 return d['batches']
def row_controls():
 return sorted([w for w in widgets(ROOT) if isinstance(w,tk.Checkbutton) and w.winfo_ismapped() and str(w.cget('text'))==''],key=lambda w:w.winfo_rooty())
def select_and_start():
 cbs=row_controls();assert len(cbs)==3
 assert all(bool(ROOT.getvar(w.cget('variable'))) for w in cbs)
 click(cbs[1],'deselect-second-actual-checkbox')
 assert [bool(ROOT.getvar(w.cget('variable'))) for w in cbs]==[True,False,True]
 shot('04-actual-selection-first-third');click(find(T('ov.pl_btn_download')),'start-selected-through-original-GUI')
 ROOT.after(1300,lambda:wait_pause(0))
def wait_pause(attempt):
 a=[w for w in widgets(ROOT) if isinstance(w,ttk.Button) and w.winfo_ismapped() and str(w.cget('text'))=='⏸']
 if not a:
  assert attempt<60,'No actual downloading pause button';ROOT.after(500,lambda:wait_pause(attempt+1));return
 shot('05-actual-first-download-progress');click(a[0],'pause-real-first-transfer');ROOT.after(1800,resume_actual)
def resume_actual():
 batches=actual_batches();assert any(e['status']=='paused' for b in batches for e in b['entries'])
 shot('06-actual-paused');click(find('▶'),'resume-real-first-transfer');ROOT.after(1500,lambda:wait_complete(0))
def wait_complete(attempt):
 batches=actual_batches();assert len(batches)==1
 entries=batches[0]['entries'];assert len(entries)==2 and {int(e['index']) for e in entries}=={1,3}
 assert not any(e['status']=='failed' for e in entries),'Actual transfer failed'
 if not all(e['status']=='completed' for e in entries):
  assert attempt<180,'Actual completion timeout';ROOT.after(1000,lambda:wait_complete(attempt+1));return
 files=list((O/'actual-downloads').rglob('*.mp4'));assert len(files)==2
 hashes={hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
 assert hashes=={hashlib.sha256((source/f'own-clip-{i}.mp4').read_bytes()).hexdigest() for i in [1,3]}
 ev('actual-two-selected-files-complete-sha256-matched',files=[str(p) for p in files]);shot('07-actual-selected-downloads-complete')
 ROOT.after(2500,start_cancel_demo)
def start_cancel_demo():
 cbs=row_controls()
 for i,w in enumerate(cbs):
  wanted=(i==1)
  if bool(ROOT.getvar(w.cget('variable')))!=wanted:click(w,'actual-new-selection-for-cancel-demo')
 click(find(T('ov.pl_btn_download')),'start-own-second-clip-for-real-cancel-demo');ROOT.after(1200,lambda:wait_cancel(0))
def wait_cancel(attempt):
 a=[w for w in widgets(ROOT) if isinstance(w,ttk.Button) and w.winfo_ismapped() and str(w.cget('text'))=='⏸']
 if not a:
  assert attempt<60,'Cancel demonstration never started';ROOT.after(500,lambda:wait_cancel(attempt+1));return
 shot('08-actual-separate-cancel-demo-progress');click(find(T('ov.pl_btn_cancel_all')),'cancel-real-separate-own-batch');ROOT.after(1800,check_cancel)
def check_cancel():
 batches=actual_batches();assert len(batches)==2
 assert any(any(e['status']=='cancelled' for e in b['entries']) for b in batches)
 files=list((O/'actual-downloads').rglob('*.mp4'));assert len(files)==2,'Cancelled second source must not be called completed'
 ev('actual-cancellation-verified-original-first-third-preserved');shot('09-actual-cancelled-separate-demo');ROOT.after(3000,finish)
def finish():
 global rec
 shot('03-original-playlist-read-only-state');rec.send_signal(signal.SIGINT);rec.wait(timeout=30);rec=None;ROOT.destroy()
def init(self,*a,**kw):
 global ROOT
 original(self,*a,**kw)
 if kw.get('className')=='idm-linux-panel':
  ROOT=self
  def fail(t,e,tb):
   import traceback
   failures.append(str(e));(O/'failed-original-state.txt').write_text(''.join(traceback.format_exception(t,e,tb)))
   try:shot('stopped-on-real-state')
   except Exception:pass
   if rec and rec.poll() is None:rec.send_signal(signal.SIGINT);rec.wait(timeout=30)
   self.destroy()
  self.report_callback_exception=fail;self.after(9000,begin)
tk.Tk.__init__=init
try:
 from idm_linux.gui import launch_control_panel
 launch_control_panel(initial_page='overview',project_root=Path.cwd());assert not failures,failures
 (O/'actual-gui-probe-review.json').write_text(json.dumps({'actual_original_gui_and_original_daemon':True,'real_own_rss_list_visible':True,'native_idm_installed_in_this_separate_profile':False,'native_helper_substitution_called':False,'own_source_limited_KiB_per_second':128,'gui_download_selection_pause_resume_cancel_verified':True,'actual_selected_first_third_outputs_sha256_verified':True,'finished_lesson':False,'final_film_export_allowed':False},ensure_ascii=False,indent=2))
finally:
 daemon.terminate()
 try:daemon.wait(timeout=15)
 except subprocess.TimeoutExpired:daemon.kill()
 server.shutdown()
