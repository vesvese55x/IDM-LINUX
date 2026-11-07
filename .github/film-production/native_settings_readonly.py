"""Actual native settings UI inspection: physical clicks, tab navigation, Escape only.
No credentials, transfers, registration, modified settings or rendered replacement UI.
"""
import json,subprocess,time,hashlib
from pathlib import Path
import cv2
from turkish_quality_gate import assert_clean
O=Path('out/film14-native-turkish/settings');O.mkdir(parents=True,exist_ok=True)
probe=Path('out/film14-native-turkish/native-turkish-probe.exe').resolve()
def windows():return subprocess.check_output(['wmctrl','-l'],text=True).splitlines()
def shot(name):
 p=O/(name+'.png');subprocess.run(['import','-window','root',str(p)],check=True);return p
for line in windows():
 if 'günün ipucu' in line.lower():
  subprocess.run(['wmctrl','-ia',line.split()[0]],check=True);subprocess.run(['xdotool','key','Escape'],check=True);time.sleep(.5)
main=[line for line in windows() if 'Internet Download Manager' in line]
assert main,'No actual native main window to inspect'
subprocess.run(['wmctrl','-ia',main[-1].split()[0]],check=True);time.sleep(.7)
source=shot('00-before-options');image=cv2.imread(str(source));template=cv2.imread('.github/film-production/actual-native-options-icon.png')
_,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(image,template,cv2.TM_CCOEFF_NORMED))
assert score>.985,{'stop':'Actual native Options icon not confidently matched; no click','score':score}
x=point[0]+template.shape[1]//2;y=point[1]+template.shape[0]//2
subprocess.run(['xdotool','mousemove',str(x),str(y),'click','1'],check=True);time.sleep(1)
receipts=[]
def inspect(index):
 result=subprocess.run(['wine',str(probe)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=30)
 raw=result.stdout.decode('utf8',errors='strict');(O/f'{index:02}-native-raw.txt').write_text(raw)
 texts=[];resources=[];fonts=[];counts=[];selected=[];failures=[]
 for line in raw.splitlines():
  a=line.split('\t')
  if a[0] in ['TEXT','WINDOW','MENU','RESOURCE'] and len(a)>1:
   text=bytes.fromhex(a[1]).decode('utf8',errors='strict')
   if a[0]=='RESOURCE':resources.append(text);continue
   texts.append({'kind':a[0],'text':text})
   try:assert_clean(text)
   except AssertionError as e:failures.append(str(e))
  elif a[0]=='TABCOUNT':counts.append(int(a[1]))
  elif a[0]=='TABSELECT':selected.append(int(a[1]))
  elif a[0] in ['FONT_UI','FONT_TEST']:fonts.append({'origin':a[0],'family':bytes.fromhex(a[1]).decode('utf8'),'missing_tr_glyphs':int(a[2])})
 image=shot(f'{index:02}-actual-native-settings')
 r={'index':index,'raw_ui_texts':texts,'non_text_static_resources':resources,'sampled_fonts':fonts,'tab_counts':counts,'selected_tab_indices':selected,'mojibake_failures':failures,'screenshot_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'all_fonts_certified':False}
 receipts.append(r);(O/'settings-review.json').write_text(json.dumps({'scope':'actual native settings tabs, not all download dialogs','matched_actual_icon_score':score,'physical_click':[x,y],'settings_saved':False,'final_export_allowed':False,'stages':receipts},ensure_ascii=False,indent=2))
 assert not failures,{'actual_ui_text_failure':failures}
 assert all(f['missing_tr_glyphs']==0 for f in fonts),'A sampled font lacks Turkish glyphs'
 return counts
counts=inspect(1);assert counts and 1<=max(counts)<=20,'Actual native tab control was not found; stop rather than fabricate settings coverage'
for index in range(2,max(counts)+1):
 subprocess.run(['xdotool','key','ctrl+Tab'],check=True);time.sleep(.4);inspect(index)
assert {r['selected_tab_indices'][0] for r in receipts if r['selected_tab_indices']}==set(range(max(counts))),'All real native settings tabs must be observed, not merely nine screenshots'
# Escape cancels this genuine settings dialog; no Apply/OK or data field editing.
subprocess.run(['xdotool','key','Escape'],check=True);shot('99-after-cancel')
print('ACTUAL_NATIVE_SETTINGS_TABS_INSPECTED_NOT_ALL_DIALOGUES',len(receipts),flush=True)

# Inspect two further native dialogs without submitting a URL, starting a queue or saving changes.
for index,name in [(100,'url'),(110,'scheduler')]:
 screen=cv2.imread(str(shot(f'{index}-before-{name}')))
 icon=cv2.imread(f'.github/film-production/actual-native-{name}-icon.png')
 _,confidence,_,pos=cv2.minMaxLoc(cv2.matchTemplate(screen,icon,cv2.TM_CCOEFF_NORMED))
 assert confidence>.985,{'stop':'Native icon not confidently measured; no click','name':name,'score':confidence}
 tx=pos[0]+icon.shape[1]//2;ty=pos[1]+icon.shape[0]//2
 subprocess.run(['xdotool','mousemove',str(tx),str(ty),'click','1'],check=True);time.sleep(.7)
 inspect(index)
 subprocess.run(['xdotool','key','Escape'],check=True);time.sleep(.3)
 shot(f'{index}-after-cancel-{name}')
