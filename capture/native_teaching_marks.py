"""Editor-only geometry-anchored marks for actual native controls and live pages."""
from pathlib import Path
import json
KINDS={'rectangle','rounded_rectangle','ellipse','freehand_loop','highlight','freehand_arrow'}
def draw(out,report,duration,emit,rectangle,oval):
 rendered=[]
 for m in report.get('runtime_marks',[]):
  kind=m.get('kind','rounded_rectangle');assert kind in KINDS,kind
  x,y,w,h=m['rect'];assert x>=0 and y>=0 and x+w<1552 and y+h<1032,'Native annotation violates measured safe area'
  x-=4;y-=4;w+=8;h+=8;color=m['color'];bgr=color[4:6]+color[2:4]+color[:2];start=max(0,m['start']);end=min(duration,m['end']);assert end>start
  # Closed paths are outline-only. Highlights stay transparent; UI stays intact.
  tag=f'\\an7\\pos({x:.2f},{y:.2f})\\p1\\bord2.6\\shad0\\1a&HFF&\\3a&H08&\\3c&H{bgr}&\\fad(160,230)'
  reveal=f'\\clip({x-6:.2f},{y-8:.2f},{x-6:.2f},{y+h+8:.2f})\\t(0,480,\\clip({x-6:.2f},{y-8:.2f},{x+w+8:.2f},{y+h+8:.2f}))'
  if kind in ['rectangle','rounded_rectangle']:
   path=rectangle(w,h,0 if kind=='rectangle' else min(12,h/3));emit(12,start,end,'{'+tag+reveal+'}'+path)
  elif kind=='ellipse':emit(12,start,end,'{'+tag+reveal+'}'+oval(w,h))
  elif kind=='freehand_loop':
   path=f'm {w*.48:.2f} 1 b {w*.85:.2f} -3 {w+4:.2f} {h*.2:.2f} {w+1:.2f} {h*.53:.2f} b {w-2:.2f} {h*.94:.2f} {w*.64:.2f} {h+3:.2f} {w*.34:.2f} {h+1:.2f} b {w*.04:.2f} {h-1:.2f} -5 {h*.68:.2f} 0 {h*.34:.2f} b 4 2 {w*.34:.2f} -2 {w*.64:.2f} 1'
   emit(12,start,end,'{'+tag+reveal+'}'+path)
  elif kind=='highlight':
   emit(10,start,end,f'{{\\an7\\pos({x:.2f},{y:.2f})\\p1\\bord0\\shad0\\1c&H{bgr}&\\1a&HD0&\\fad(160,230){reveal}}}'+rectangle(w,h,3))
   emit(12,start+.2,end,f'{{\\an7\\pos({x:.2f},{y+h:.2f})\\p1\\bord0\\1c&H{bgr}&\\1a&H18&\\fad(160,230)}}'+f'm 0 0 b {w*.3:.2f} 2 {w*.7:.2f} -1 {w:.2f} 1 l {w:.2f} 3 b {w*.7:.2f} 1 {w*.3:.2f} 4 0 2')
  else:
   emit(12,start,end,'{'+tag+reveal+'}'+f'm 0 {h*.9:.2f} b {w*.2:.2f} {h*.8:.2f} {w*.4:.2f} {h*.2:.2f} {w*.8:.2f} {h*.4:.2f} m {w*.65:.2f} {h*.17:.2f} l {w*.85:.2f} {h*.42:.2f} l {w*.6:.2f} {h*.57:.2f}')
  rendered.append({**m,'rendered_kind':kind,'start':start,'end':end})
 result={'status':'PASS','count':len(rendered),'kinds':sorted({m['rendered_kind'] for m in rendered}),'rendered':rendered,'fabricated_targets':False,'source_ui_modified':False,'timing':'Speech cue actions and actual measured geometry'}
 if report.get('installation_mode')=='external':assert {'rectangle','rounded_rectangle','ellipse','freehand_loop','highlight'}<=set(result['kinds']),'Incomplete requested illustration variety'
 (Path(out)/'native-teaching-marks-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));return result
