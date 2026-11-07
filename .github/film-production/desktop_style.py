"""Shared genuine XFCE configuration; no imitation panels or product changes."""
import json,subprocess
from pathlib import Path
from PIL import Image
def apply_desktop_style(output):
 O=Path(output);O.mkdir(parents=True,exist_ok=True)
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
