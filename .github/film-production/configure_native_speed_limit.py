"""Ordinary native UI preference via physical real clicks, never injected progress.
Explicit documentary source limit; NOT a speed benchmark. No vendor/registration files edited.
"""
import os,subprocess,time,json,re
from pathlib import Path
O=Path('out/film14-native-turkish/actual-speed-limit-configuration');O.mkdir(parents=True,exist_ok=True)
P=Path('out/film14-native-turkish/native-turkish-probe.exe').resolve()
def inspect(tag):
 r=subprocess.run(['wine',str(P)],capture_output=True,check=True,timeout=30)
 (O/(tag+'.txt')).write_bytes(r.stdout)
 controls=[];states=[];titles=[]
 for line in r.stdout.decode().splitlines():
  a=line.split('\t')
  if a[0]=='WINDOW':titles.append(bytes.fromhex(a[1]).decode())
  if a[0]=='CONTROL' and len(a)>7:controls.append({'class':bytes.fromhex(a[2]).decode(),'visible':a[6]=='1','rect':list(map(int,a[5].split(','))),'text':bytes.fromhex(a[7]).decode()})
  if a[0]=='MENU_STATE':states.append({'state':int(a[1]),'text':bytes.fromhex(a[2]).decode().replace('&','')})
 return controls,states,titles
def shot(tag):subprocess.run(['import','-window','root',str(O/(tag+'.png'))],check=True)
def click(rect):
 x1,y1,x2,y2=rect;assert 0<=x1<x2<=1920 and 0<=y1<y2<=1080
 subprocess.run(['xdotool','mousemove',str((x1+x2)//2),str((y1+y2)//2),'click','1'],check=True);time.sleep(.5)
def menu(root):
 # Relative targets independently visually measured in actual runner42453287118.
 click([root[0]+123,root[1]+32,root[0]+143,root[1]+48])
 subprocess.run(['xdotool','mousemove',str(root[0]+190),str(root[1]+226)],check=True);time.sleep(.8)
def configure(kibps):
 assert kibps==10000,'Only the documented ordinary demonstration rate is supported'
 rows=[l for l in subprocess.check_output(['wmctrl','-l'],text=True).splitlines() if re.search(r'Internet Download Manager \d+\.\d+$',l)];assert len(rows)==1
 subprocess.run(['wmctrl','-ia',rows[0].split()[0]],check=True);time.sleep(.4)
 controls,_,_=inspect('01-before')
 roots=[c['rect'] for c in controls if c['visible'] and c['class']=='#32770' and re.fullmatch(r'Internet Download Manager \d+\.\d+',c['text'])];assert len(roots)==1
 root=roots[0];menu(root);click([root[0]+320,root[1]+263,root[0]+340,root[1]+277]);time.sleep(.6)
 controls,_,titles=inspect('02-actual-settings-before');assert 'Hız Sınırlayıcı ayarları' in titles
 edits=[c for c in controls if c['visible'] and c['class']=='Edit'];assert len(edits)==1
 click(edits[0]['rect']);subprocess.run(['xdotool','key','ctrl+a'],check=True);subprocess.run(['xdotool','type','--clearmodifiers',str(kibps)],check=True);time.sleep(.4)
 controls,_,_=inspect('03-value-read-back');assert any(c['class']=='Edit' and c['text']==str(kibps) for c in controls)
 ok=[c for c in controls if c['visible'] and c['class']=='Button' and c['text'].replace('&','')=='Tamam'];assert len(ok)==1
 shot('03-actual-value-before-confirm');click(ok[0]['rect']);menu(root)
 click([root[0]+320,root[1]+222,root[0]+340,root[1]+236])
 _,states,_=inspect('04-after-enable');on=[s for s in states if s['text']=='Aç'];off=[s for s in states if s['text']=='Kapalı']
 assert len(on)==1 and len(off)==1 and on[0]['state']&8 and not off[0]['state']&8,'Actual native menu checkmarks must certify enable state'
 menu(root);shot('05-actual-enabled-checkmark');subprocess.run(['xdotool','key','Escape','Escape'],check=True)
 report={'configured_by_physical_original_UI':True,'native_speed_limit_KiB_per_second':kibps,'value_read_back':True,'enabled_menu_checkmark_verified':True,'benchmark_or_maximum_speed_claim':False,'reason':'Make real progress observable in a genuine paced tutorial, not a performance test','vendor_files_or_trial_keys_modified':False}
 (O/'actual-ordinary-speed-limit-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 return report
