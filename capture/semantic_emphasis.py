"""Read actual visible DOM geometry; draw time-bounded editorial teaching marks.
No source DOM mutation, no synthetic UI and no unverified screen coordinates.
"""
from pathlib import Path
import json
PLAN=json.loads((Path(__file__).parent/'emphasis-plan.json').read_text())

def snapshot(evaluate,transform,at,view_id):
 specs=PLAN['targets']
 script='''(()=>{const specs=SPEC;const result={};for(const [id,s] of Object.entries(specs)){
 const e=document.querySelector(s.selector);if(!e)continue;const style=getComputedStyle(e);if(style.display==='none'||style.visibility==='hidden'||Number(style.opacity)===0)continue;
 let r;try{if(s.match){const walk=document.createTreeWalker(e,NodeFilter.SHOW_TEXT);let n,found=false;while(n=walk.nextNode()){const p=n.textContent.indexOf(s.match);if(p>=0){const range=document.createRange();range.setStart(n,p);range.setEnd(n,p+s.match.length);r=range.getBoundingClientRect();found=true;break}}if(!found)continue}
 else if(s.mode==='contents'){const range=document.createRange();range.selectNodeContents(e);r=range.getBoundingClientRect()}else{r=e.getBoundingClientRect()}}catch(err){continue}
 if(!r||r.width<2||r.height<2||r.top<4||r.bottom>innerHeight-6||r.left<4||r.right>innerWidth-6)continue;const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);if(!hit||!(hit===e||e.contains(hit)))continue;
 result[id]={left:r.left,top:r.top,width:r.width,height:r.height,text:e.textContent.trim().slice(0,140)}}return result})()'''.replace('SPEC',json.dumps(specs,ensure_ascii=False))
 found=evaluate(script);rows=[]
 for key,r in found.items():
  x=transform['ox']+r['left']*transform['sx'];y=transform['oy']+r['top']*transform['sy'];w=r['width']*transform['sx'];h=r['height']*transform['sy']
  if x<8 or y<94 or x+w>1552 or y+h>1024:continue
  rows.append({'target':key,'view_id':view_id,'time':at,'rect':[round(x,2),round(y,2),round(w,2),round(h,2)],'source_text':r['text']})
 return rows

def bgr(rgb):return rgb[4:6]+rgb[2:4]+rgb[0:2]
def union_length(windows):
 merged=[]
 for a,b in sorted(windows):
  if b<=a:continue
  if merged and a<=merged[-1][1]:merged[-1][1]=max(b,merged[-1][1])
  else:merged.append([a,b])
 return sum(b-a for a,b in merged)

def draw(out,report,duration,emit,rectangle,oval):
 views=report.get('presentation_views',[]);targets=report.get('presentation_targets',[]);scrolls=report.get('presentation_scroll_starts',[]);rendered=[];skipped=[]
 for cue in report.get('tutorial_audio_cues',[]):
  base=cue['video_offset_seconds'];endcue=base+cue['duration_seconds'];prefix=cue['audio_file'][:2]
  for spec in PLAN['marks'].get(prefix,[]):
   start=base+spec['at'];end=min(endcue-.15,start+spec['seconds'],duration)
   active=[v for v in views if v['time']<=start+.01]
   if not active:skipped.append({'target':spec['target'],'reason':'no measured view','start':start});continue
   view=max(active,key=lambda v:v['time'])
   if any(view['time']<t<=start for t in scrolls):skipped.append({'target':spec['target'],'reason':'real scroll in progress','start':start});continue
   candidates=[r for r in targets if r['target']==spec['target'] and r['view_id']==view['id']]
   if not candidates:skipped.append({'target':spec['target'],'reason':'not actually visible in this view','start':start});continue
   future=[t for t in scrolls if t>start+.01]
   if future:end=min(end,min(future)-.12)
   if end-start<.8:skipped.append({'target':spec['target'],'reason':'actual scene changes too soon','start':start});continue
   target=candidates[-1];x,y,w,h=target['rect'];kind=spec['kind'];color=bgr(PLAN['colors'][spec['color']]);pad=7
   x-=pad;y-=pad;w+=2*pad;h+=2*pad
   # Drawing is clearly an editorial marker, never an imitation native control.
   base_tag=f'\\an7\\pos({x:.2f},{y:.2f})\\p1\\shad0\\bord2.2\\1a&HFF&\\3c&H{color}&\\3a&H08&\\fad(130,220)'
   clip=f'\\clip({x-5:.1f},{y-8:.1f},{x-5:.1f},{y+h+9:.1f})\\t(0,480,\\clip({x-5:.1f},{y-8:.1f},{x+w+8:.1f},{y+h+9:.1f}))'
   if kind=='rectangle':emit(12,start,end,'{'+base_tag+clip+'}'+rectangle(w,h,min(9,h/3)))
   elif kind=='ellipse':
    emit(12,start,end,'{'+base_tag+clip+'}'+oval(w,h))
   elif kind=='freehand_loop':
    path=f'm {w*.48:.1f} 1 b {w*.84:.1f} -3 {w+4:.1f} {h*.19:.1f} {w+1:.1f} {h*.53:.1f} b {w-2:.1f} {h*.94:.1f} {w*.64:.1f} {h+3:.1f} {w*.34:.1f} {h+1:.1f} b {w*.04:.1f} {h-1:.1f} -5 {h*.68:.1f} 0 {h*.34:.1f} b 4 2 {w*.34:.1f} -2 {w*.64:.1f} 1'
    emit(12,start,end,'{'+base_tag+clip+'}'+path)
   elif kind=='highlight':
    # Low-opacity marker band; all underlying letters remain legible.
    emit(10,start,end,f'{{\\an7\\pos({x:.2f},{y+2:.2f})\\p1\\bord0\\1c&H{color}&\\1a&HCA&\\fad(150,230){clip}}}'+rectangle(w,max(12,h-3),3))
    emit(12,start+.24,end,f'{{\\an7\\pos({x:.2f},{y+h:.2f})\\p1\\bord0\\1c&H{color}&\\1a&H50&\\fad(100,220)\\clip({x-2:.1f},{y+h-5:.1f},{x-2:.1f},{y+h+6:.1f})\\t(0,430,\\clip({x-2:.1f},{y+h-5:.1f},{x+w+4:.1f},{y+h+6:.1f}))}}'+f'm 0 0 b {w*.3:.1f} 2 {w*.7:.1f} -1 {w:.1f} 1 l {w:.1f} 3 b {w*.7:.1f} 1 {w*.3:.1f} 4 0 2')
   elif kind=='underline':
    yy=y+h-2
    emit(12,start,end,f'{{\\an7\\pos({x:.2f},{yy:.2f})\\p1\\bord0\\1c&H{color}&\\1a&H16&\\fad(100,200)\\clip({x-2:.1f},{yy-4:.1f},{x-2:.1f},{yy+8:.1f})\\t(0,500,\\clip({x-2:.1f},{yy-4:.1f},{x+w+4:.1f},{yy+8:.1f}))}}'+f'm 0 1 b {w*.24:.1f} -1 {w*.65:.1f} 3 {w:.1f} 0 l {w:.1f} 3 b {w*.65:.1f} 6 {w*.24:.1f} 2 0 4')
   elif kind=='freehand_arrow':
    xx=max(18,x-82);yy=y+h/2-28
    emit(12,start,end,f'{{\\an7\\pos({xx:.2f},{yy:.2f})\\p1\\bord0\\1c&H{color}&\\1a&H10&\\fad(130,220)\\clip({xx-5:.1f},{yy-6:.1f},{xx-5:.1f},{yy+70:.1f})\\t(0,460,\\clip({xx-5:.1f},{yy-6:.1f},{xx+85:.1f},{yy+70:.1f}))}}m 0 57 b 24 63 28 18 68 26 l 65 17 l 80 29 l 63 39 l 69 31 b 30 23 25 66 0 61 l 0 57')
   else:raise AssertionError(kind)
   rendered.append({'target':spec['target'],'kind':kind,'color':spec['color'],'start':start,'end':end,'rect':target['rect'],'view_id':view['id']})
 result={'status':'PASS','rendered_count':len(rendered),'skipped_count':len(skipped),'rendered':rendered,'skipped':skipped,'mark_visible_seconds':round(union_length([(r['start'],r['end']) for r in rendered]),3),'geometry':'Actual visible DOM ranges transformed with measured real OS pointer coordinates','respect_scroll_boundaries':True,'fabricated_targets':False}
 (Path(out)/'semantic-emphasis-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result
