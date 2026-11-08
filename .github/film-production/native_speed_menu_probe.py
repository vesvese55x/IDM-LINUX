"""Read actual IDM speed-menu state; no settings changes, no speed/performance claim."""
import os,subprocess,time,json
from pathlib import Path
from idm_linux.config import IdmLinuxConfig
from idm_linux.wine_sender import build_wine_env
O=Path('out/film14-native-turkish/speed-menu');O.mkdir(parents=True,exist_ok=True)
os.environ.update(build_wine_env(IdmLinuxConfig.load()))
for l in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
 if 'günün ipucu' in l.lower():
  subprocess.run(['wmctrl','-ia',l.split()[0]],check=True);subprocess.run(['xdotool','key','Escape'],check=True);time.sleep(.3)
rows=[l for l in subprocess.check_output(['wmctrl','-l'],text=True).splitlines() if 'Internet Download Manager' in l]
assert len(rows)==1,rows
subprocess.run(['wmctrl','-ia',rows[0].split()[0]],check=True);time.sleep(.5)
p=Path('out/film14-native-turkish/native-turkish-probe.exe').resolve()
r=subprocess.run(['wine',str(p)],capture_output=True,check=True,timeout=30);(O/'actual-before-menu-raw.txt').write_bytes(r.stdout)
a=[]
for line in r.stdout.decode().splitlines():
 c=line.split('\t')
 if c[0]=='CONTROL' and len(c)>7 and bytes.fromhex(c[7]).decode().startswith('Internet Download Manager') and c[6]=='1':a.append([int(v) for v in c[5].split(',')])
assert len(a)==1,a
subprocess.run(['import','-window','root',str(O/'01-actual-before-menu.png')],check=True)
# Offset measured on genuine 1920x1080 actual-desktop source, not a guessed arbitrary target.
x,y=a[0][0]+133,a[0][1]+40
assert 0<x<1920 and 0<y<1080
(O/'actual-click-scope.json').write_text(json.dumps({'real_window_rect':a[0],'click':[x,y],'label':'İndirmeler','measurement_source':'actual 05-native-before-url-add.png in run42429760660; menu crop independently visually reviewed','settings_modified':False},ensure_ascii=False,indent=2))
subprocess.run(['xdotool','mousemove',str(x),str(y),'click','1'],check=True);time.sleep(.8)
subprocess.run(['import','-window','root',str(O/'02-actual-downloads-menu.png')],check=True)
r=subprocess.run(['wine',str(p)],capture_output=True,check=True,timeout=30);(O/'actual-menu-open-raw.txt').write_bytes(r.stdout)
subprocess.run(['xdotool','key','Escape'],check=True)
