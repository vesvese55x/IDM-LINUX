"""Actual GUI preparation only. Never claims unperformed native downloads or final lesson completion."""
import os,json,time,subprocess,signal,hashlib,threading
from pathlib import Path
import tkinter as tk
from PIL import Image
O=Path('out/film14-preflight');O.mkdir(parents=True,exist_ok=True);epoch=time.monotonic();events=[];rec=None;failures=[]

def event(name,**kw):
 events.append({'seconds':round(time.monotonic()-epoch,4),'event':name,**kw});(O/'events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2))
from turkish_quality_gate import catalogue_gate, visible_widget_gate, native_readiness
catalogue_gate(O)

def shot(name):
 if CURRENT_ROOT is not None:visible_widget_gate(CURRENT_ROOT,O,name)
 subprocess.run(['import','-window','root',str(O/(name+'.png'))],check=True)
CURRENT_ROOT=None
# Authentic hardware data, same original lower-left card layout.
from system_card import collect,render
info=collect();(O/'actual-system-info.json').write_text(json.dumps(info,ensure_ascii=False,indent=2));render(info,O/'system-card.png',scale=.55)
wall=Image.open('.github/film-production/wallpaper.png').convert('RGBA').resize((1920,1080));card=Image.open(O/'system-card.png');card.thumbnail((350,210));wall.alpha_composite(card,(20,1020-card.height));wall.convert('RGB').save(O/'wallpaper-with-actual-card.png')
props=subprocess.check_output(['xfconf-query','-c','xfce4-desktop','-lv'],text=True)
for line in props.splitlines():
 p=line.split()[0]
 if p.endswith('/last-image'):subprocess.run(['xfconf-query','-c','xfce4-desktop','-p',p,'-s',str((O/'wallpaper-with-actual-card.png').resolve())],check=True)
# Configure actual panel widgets, never paint a replacement taskbar.
def setpanel(prop,typ,value):
 subprocess.run(['xfconf-query','-c','xfce4-panel','-p',prop,'--create','--type',typ,'-s',str(value)],check=True,capture_output=True)
setpanel('/panels/panel-1/size','int',41)
setpanel('/panels/panel-1/position','string','p=10;x=960;y=1059')
setpanel('/panels/panel-1/icon-size','int',24)
# Default second dock is unnecessary for the approved one-panel layout.
subprocess.run(['xfconf-query','-c','xfce4-panel','-p','/panels','-a','-t','int','-s','1'],check=True,capture_output=True)
# XFCE4.18 uses separate date/time properties; the old digital-format key is obsolete.
panel_listing=subprocess.check_output(['xfconf-query','-c','xfce4-panel','-lv'],text=True)
clock_roots=[]
for line in panel_listing.splitlines():
 parts=line.split(None,1)
 if len(parts)==2 and parts[0].startswith('/plugins/plugin-') and parts[1].strip()=='clock':clock_roots.append(parts[0])
for clock in clock_roots:
 for suffix,typ,value in [('digital-layout','uint',1),('digital-time-format','string','%H:%M:%S'),('digital-date-format','string','%d.%m.%Y'),('digital-time-font','string','Noto Sans Bold 10'),('digital-date-font','string','Noto Sans 8'),('timezone','string','Europe/Istanbul')]:setpanel(clock+'/'+suffix,typ,value)
(O/'actual-clock-plugin-roots.json').write_text(json.dumps({'roots':clock_roots,'configuration':'real XFCE plugin, separate time/date labels; no painted taskbar'},ensure_ascii=False,indent=2))
subprocess.run(['xfconf-query','-c','xfce4-desktop','-p','/backdrop/screen0/monitorscreen0/workspace0/image-style','--create','--type','int','-s','3'],check=False)
subprocess.run(['xfce4-panel','--restart'],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
subprocess.run(['xfdesktop','--reload'],check=False)
original=tk.Tk.__init__
def allwidgets(w):
 out=[]
 for z in w.winfo_children():out.append(z);out.extend(allwidgets(z))
 return out

def begin(root):
 global rec,CURRENT_ROOT
 CURRENT_ROOT=root
 root.geometry('1460x900+380+40');root.update_idletasks();groups={}
 for w in allwidgets(root):
  if isinstance(w,tk.Button) and w.winfo_ismapped() and w.winfo_x()<300:
   groups.setdefault(str(w.master),[]).append(w)
 visible_widget_gate(root,O,'initial-panel')
 native_readiness(O)
 choices=[v for v in groups.values() if len(v)==9];assert len(choices)==1,'Could not identify the real 9-button navigation group';buttons=sorted(choices[0],key=lambda w:w.winfo_rooty())
 rec=subprocess.Popen(['ffmpeg','-nostdin','-y','-v','warning','-f','x11grab','-draw_mouse','0','-s','1920x1080','-r','24','-i',':99','-an','-c:v','libx264','-preset','veryfast','-crf','19','-bf','0','-threads','2',str(O/'uncut-control-panel.mp4')],stdout=open(O/'capture.log','w'),stderr=subprocess.STDOUT);event('recording_started',cursor='OS cursor excluded; actual physical click coordinates recorded')
 def step(i):
  if i>=len(buttons):root.after(1500,finish);return
  w=buttons[i];x=w.winfo_rootx()+w.winfo_width()//2;y=w.winfo_rooty()+w.winfo_height()//2;box=[w.winfo_rootx(),w.winfo_rooty(),w.winfo_width(),w.winfo_height()];label=w.cget('text');subprocess.run(['xdotool','mousemove','--sync',str(x),str(y),'click','1'],check=True);event('actual_nav_click',label=label,x=x,y=y,box=box);root.after(1100,lambda:shot(f'actual-tab-{i+1:02d}'));root.after(5000,lambda:step(i+1))
 def finish():
  global rec
  rec.send_signal(signal.SIGINT);rec.wait(timeout=30);event('recording_stopped');root.destroy()
 root.after(1500,lambda:step(0))

def observe(self,*args,**kw):
 original(self,*args,**kw)
 if kw.get('className')=='idm-linux-panel':
  def abort(exc_type,exc,tb):
   import traceback
   failures.append(str(exc));(O/'QUALITY-GATE-FAILED.txt').write_text(''.join(traceback.format_exception(exc_type,exc,tb)))
   if rec and rec.poll() is None:
    rec.send_signal(signal.SIGINT);rec.wait(timeout=30)
   self.destroy()
  self.report_callback_exception=abort
  self.after(9000,lambda:begin(self))
tk.Tk.__init__=observe
from idm_linux.gui import launch_control_panel
result=launch_control_panel(initial_page='overview',project_root=Path.cwd());assert result==0
assert not failures,failures
p=O/'uncut-control-panel.mp4';assert p.exists();subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(p),'-f','null','-'],check=True)
receipt={'status':'GENUINE_GUI_PREFLIGHT_ONLY_NOT_FINISHED_CHAPTER','native_IDM_installation_or_download_claimed':False,'product_source_modified':False,'actual_nav_clicks':sum(e['event']=='actual_nav_click' for e in events),'video_sha256':hashlib.file_digest(p.open('rb'),'sha256').hexdigest(),'cursor_trajectory_not_invented':True,'remaining_lessons':['Pixeldrain','Playlist','Installed detailed GUI','Native Windows EXE and CMD','HLS and live DVR','eD2K and troubleshooting']};(O/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));print(json.dumps(receipt,ensure_ascii=False))
