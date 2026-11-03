"""Enable real desktop icons and a real taskbar; no painted/synthetic controls."""
from pathlib import Path
import os,time,subprocess,json,shutil

def windows():
 import ctypes,win32gui,win32con,winreg
 from ctypes import wintypes
 with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced') as k:winreg.SetValueEx(k,'HideIcons',0,winreg.REG_DWORD,0)
 icons=[]
 def show(hwnd,_):
  view=win32gui.FindWindowEx(hwnd,0,'SHELLDLL_DefView',None)
  if view:
   child=win32gui.FindWindowEx(view,0,'SysListView32',None)
   if child:win32gui.ShowWindow(child,win32con.SW_SHOW);icons.append(child)
 win32gui.EnumWindows(show,None)
 taskbar=win32gui.FindWindow('Shell_TrayWnd',None)
 assert taskbar,'Windows Explorer taskbar unavailable'
 class APPBARDATA(ctypes.Structure):
  _fields_=[('cbSize',wintypes.DWORD),('hWnd',wintypes.HWND),('uCallbackMessage',wintypes.UINT),('uEdge',wintypes.UINT),('rc',wintypes.RECT),('lParam',wintypes.LPARAM)]
 data=APPBARDATA();data.cbSize=ctypes.sizeof(data);data.hWnd=taskbar;data.lParam=2
 ctypes.windll.shell32.SHAppBarMessage(10,ctypes.byref(data))
 win32gui.ShowWindow(taskbar,win32con.SW_SHOW);time.sleep(.7)
 assert icons and any(win32gui.IsWindowVisible(i) for i in icons),'Windows desktop icon view not visible'
 assert win32gui.IsWindowVisible(taskbar),'Windows taskbar not visible'
 return {'status':'PASS','implementation':'Native Windows Explorer desktop and taskbar','icons_visible':True,'taskbar_visible':True,'autohide_disabled':True}

def linux(out,wall):
 out=Path(out);home=Path.home();desktop=home/'Desktop';desktop.mkdir(exist_ok=True)
 users=home/'.config/user-dirs.dirs';users.parent.mkdir(parents=True,exist_ok=True)
 lines=users.read_text().splitlines() if users.exists() else []
 lines=[l for l in lines if not l.startswith('XDG_DESKTOP_DIR=')];lines.append('XDG_DESKTOP_DIR="$HOME/Desktop"');users.write_text('\n'.join(lines)+'\n')
 brave=Path('/usr/share/applications/brave-browser.desktop')
 if brave.exists():shutil.copyfile(brave,desktop/'Brave.desktop');(desktop/'Brave.desktop').chmod(0o755)
 for filename,name,url,icon in [('Downloads.desktop','İndirilenler',(home/'Downloads').as_uri(),'folder-download'),('BELGESELSEMO.desktop','BELGESELSEMO','https://belgeselsemo.com.tr','web-browser')]:
  p=desktop/filename;p.write_text('[Desktop Entry]\nVersion=1.0\nType=Link\nName='+name+'\nURL='+url+'\nIcon='+icon+'\n',encoding='utf-8');p.chmod(0o755)
 cfg=home/'.config/xfce4/xfconf/xfce-perchannel-xml';cfg.mkdir(parents=True,exist_ok=True)
 (cfg/'xfce4-panel.xml').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-panel" version="1.0"><property name="configver" type="int" value="2"/><property name="panels" type="array"><value type="int" value="1"/><property name="panel-1" type="empty"><property name="position" type="string" value="p=10;x=960;y=1060"/><property name="position-locked" type="bool" value="true"/><property name="size" type="uint" value="40"/><property name="length" type="uint" value="100"/><property name="length-adjust" type="bool" value="false"/><property name="mode" type="uint" value="0"/><property name="plugin-ids" type="array"><value type="int" value="1"/><value type="int" value="2"/><value type="int" value="3"/><value type="int" value="4"/><value type="int" value="5"/><value type="int" value="6"/></property></property></property><property name="plugins" type="empty"><property name="plugin-1" type="string" value="applicationsmenu"/><property name="plugin-2" type="string" value="tasklist"/><property name="plugin-3" type="string" value="separator"><property name="expand" type="bool" value="true"/></property><property name="plugin-4" type="string" value="systray"/><property name="plugin-5" type="string" value="clock"><property name="digital-format" type="string" value="%H:%M"/></property><property name="plugin-6" type="string" value="showdesktop"/></property></channel>''')
 processes=[]
 for args in [['xfdesktop'],['xfce4-panel','--disable-wm-check']]:
  log=(out/(args[0]+'-desktop.log')).open('wb');p=subprocess.Popen(args,stdout=log,stderr=log);log.close();processes.append((args[0],p))
 time.sleep(4)
 def props():return subprocess.run(['xfconf-query','-c','xfce4-desktop','-l'],capture_output=True,text=True).stdout.splitlines()
 paths=[p for p in props() if p.endswith('/last-image')]
 if not paths:paths=['/backdrop/screen0/monitor0/workspace0/last-image','/backdrop/screen0/monitorscreen/workspace0/last-image']
 for key in paths:
  parent=key.rsplit('/',1)[0]
  for prop,value,typ in [(key,str(wall),'string'),(parent+'/image-style','4','int')]:
   result=subprocess.run(['xfconf-query','-c','xfce4-desktop','-p',prop,'-s',value],capture_output=True)
   if result.returncode:subprocess.run(['xfconf-query','-c','xfce4-desktop','-p',prop,'--create','-t',typ,'-s',value],capture_output=True,check=True)
 subprocess.run(['xfconf-query','-c','xfce4-desktop','-p','/desktop-icons/style','--create','-t','int','-s','2'],capture_output=True)
 subprocess.run(['xfdesktop','--reload'],capture_output=True);time.sleep(2)
 assert all(p.poll() is None for _,p in processes),'Real Linux desktop/panel process exited'
 from Xlib import display,X
 d=display.Display();found=[]
 for w in d.screen().root.query_tree().children:
  try:
   klass=' '.join(w.get_wm_class() or ()).lower()
   if w.get_attributes().map_state==X.IsViewable and ('xfdesktop' in klass or 'xfce4-panel' in klass):found.append({'class':klass,'width':w.get_geometry().width,'height':w.get_geometry().height})
  except Exception:pass
 d.close()
 assert any('xfdesktop' in x['class'] for x in found) and any('xfce4-panel' in x['class'] for x in found),'Desktop or taskbar has no mapped real X11 window'
 return {'status':'PASS','implementation':'Real Xfdesktop file icons + Xfce panel on Openbox','icons_directory':str(desktop),'icons_visible':True,'taskbar_visible':True,'mapped_windows':found}

def prepare(out,wall):
 result=windows() if os.name=='nt' else linux(out,wall)
 (Path(out)/'desktop-shell-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 return result
