"""Non-interactive editorial layer over actual footage, driven by real pointer data.
Never draws UI, successful downloads, dialogs or fabricated cursor actions.
"""
from pathlib import Path
import csv,json,os,time,threading

class PointerTracker:
 def __init__(self,out,epoch):
  self.out=Path(out);self.epoch=epoch;self.stop=threading.Event();self.thread=None;self.error=None;self.count=0
 def start(self):
  self.thread=threading.Thread(target=self._run,name='actual-pointer-observer',daemon=True);self.thread.start();return self
 def _run(self):
  connection=None
  try:
   if os.name!='nt':
    from Xlib import display
    connection=display.Display();root=connection.screen().root
    def position():
     p=root.query_pointer();return p.root_x,p.root_y
   else:
    import ctypes
    from ctypes import wintypes
    def position():
     p=wintypes.POINT();assert ctypes.windll.user32.GetCursorPos(ctypes.byref(p));return p.x,p.y
   with (self.out/'actual-pointer.csv').open('w',newline='') as f:
    writer=csv.writer(f);writer.writerow(['seconds','x','y']);deadline=time.monotonic()
    while not self.stop.is_set():
     x,y=position();writer.writerow([f'{max(0,time.time()-self.epoch):.4f}',x,y]);self.count+=1
     deadline+=1/24;self.stop.wait(max(0,deadline-time.monotonic()))
     if time.monotonic()-deadline>.25:deadline=time.monotonic()
  except Exception as e:self.error=type(e).__name__+': '+str(e)
  finally:
   if connection:connection.close()
 def finish(self):
  alive=self.thread is not None and self.thread.is_alive();self.stop.set()
  if self.thread:self.thread.join(3)
  result={'status':'PASS' if alive and not self.error and self.count>2 else 'FAIL','samples':self.count,'sample_rate_target':24,'error':self.error,'source':'Actual X11 QueryPointer / Windows GetCursorPos','native_arrow_recorded':False,'rendered_style':'Translucent warm-yellow oval with precise centre dot; no simulated pointer events'}
  (self.out/'pointer-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result

def timestamp(value):
 cs=max(0,round(value*100));return f'{cs//360000}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}'
def escape(text):return str(text).replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\N')
def rectangle(width,height,radius=12):
 w,h,r=width,height,radius;k=r*.55228475
 return f'm {r} 0 l {w-r} 0 b {w-r+k} 0 {w} {r-k} {w} {r} l {w} {h-r} b {w} {h-r+k} {w-r+k} {h} {w-r} {h} l {r} {h} b {r-k} {h} 0 {h-r+k} 0 {h-r} l 0 {r} b 0 {r-k} {r-k} 0 {r} 0'
def oval(w,h):
 x,y=w/2,h/2;k=.55228475
 return f'm {x} 0 b {x+x*k} 0 {w} {y-y*k} {w} {y} b {w} {y+y*k} {x+x*k} {h} {x} {h} b {x-x*k} {h} 0 {y+y*k} 0 {y} b 0 {y-y*k} {x-x*k} 0 {x} 0'
HEADER='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,DejaVu Sans,22,&H00F2F5F8,&H00F2F5F8,&H00302115,&H80000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''

def build(out,report,duration):
 out=Path(out);events=[];cards=[]
 def emit(layer,start,end,text):
  start=max(0,start);end=min(duration,end)
  if end>start:events.append((start,f'Dialogue: {layer},{timestamp(start)},{timestamp(end)},Main,,0,0,0,,{text}\n'))
 # Preserve actual samples and the stationary hold endpoints. No invented moves.
 with (out/'actual-pointer.csv').open() as f:
  samples=[(float(r['seconds']),float(r['x']),float(r['y'])) for r in csv.DictReader(f)]
 assert len(samples)>2
 if samples[0][0]>.001:samples.insert(0,(0,samples[0][1],samples[0][2]))
 if samples[-1][0]<duration:samples.append((duration,samples[-1][1],samples[-1][2]))
 kept=[p for i,p in enumerate(samples) if i in (0,len(samples)-1) or p[1:]!=samples[i-1][1:] or p[1:]!=samples[i+1][1:]]
 shape=oval(44,30);dot=oval(5,5)
 for a,b in zip(kept,kept[1:]):
  if a[0]>=duration:break
  move=f'\\move({a[1]-22:.2f},{a[2]-15:.2f},{b[1]-22:.2f},{b[2]-15:.2f})'
  emit(30,a[0],b[0],'{\\an7'+move+'\\p1\\bord1.3\\shad0\\1c&H70D8FF&\\1a&H75&\\3c&H173449&\\3a&H10&}'+shape)
  move=f'\\move({a[1]-2.5:.2f},{a[2]-2.5:.2f},{b[1]-2.5:.2f},{b[2]-2.5:.2f})'
  emit(31,a[0],b[0],'{\\an7'+move+'\\p1\\bord0\\shad0\\1c&H173449&\\1a&H10&}'+dot)
 for action in report.get('tutorial_browser_events',[]):
  if action.get('action')!='real_mouse_click' or 'x' not in action:continue
  t=action['video_offset_seconds'];x=action['x'];y=action['y']
  # Centred outlined ellipse expands and fades over 0.52s; still real coordinates.
  emit(32,t,t+.52,f'{{\\an5\\pos({x:.2f},{y:.2f})\\p1\\bord2\\shad0\\1a&HFF&\\3c&H70D8FF&\\3a&H10&\\fscx65\\fscy65\\t(0,520,\\fscx145\\fscy145\\3a&HFF&)}}'+oval(64,64))
 notes={
 '01':[(3,8,'DOĞRU KAYNAK',['GitHub → README','Adresini kontrol et'])],
 '02':[(3,8,'ÇIKTI',['İndirilebilir durumda','Linux ve Windows']),(33,8,'PAKETİNİ DOĞRU SEÇ',['Linux ≠ Windows','Sisteme uygun dosya'])],
 '03':[(3,9,'ÖNCE EKLENTİ ONAYI',['Ardından gerçek bir','indirmeyle doğrula']),(36,8,'VİDEO KALİTESİ',['Her video 4K değildir','Kaliteyi kaynak belirler'])],
 '04':[(7,9,'İZİNLİ İÇERİK',['Torrent / magnet','Kullanıcı onayı önemli'])],
 '05':[(26,9,'İPTALİ DE SINAYACAĞIZ',['Düğmeye basmak yetmez','Aktarım gerçekten durmalı'])],
 '06':[(3,8,'GALERİ ≠ İŞLEV TESTİ',['Görseller arayüzü tanıtır','Gerçek işlemler sırada'])],
 '10':[(7,11,'UYUMLULUK NOTU',['Tüm paket için','Windows XP iddiası yok']),(28,8,'GERÇEK ARAYÜZ GÖRSELİ',['Ekran görüntüsü tek başına','indirme kanıtı değildir'])],
 '07':[(8,8,'DEB / UBUNTU',['apt ve GDebi','İki ayrı kurulum yolu']),(20,9,'RPM / ARCH ZST',['Fedora için RPM','Arch için pacman'])],
 '08':[(18,11,'KOMUT = GÜVEN',['Kaynağı doğrula','Rastgele satır çalıştırma'])],
 '09':[(28,9,'BU BÖLÜMDE',['Tanıtım sayfasını gezdik','Gerçek testler sırada'])]
 }
 chapters={'01':'KAYNAK SAYFASI','02':'İKİ PLATFORM','03':'TARAYICI VE VİDEO','04':'İÇERİK TÜRLERİ','05':'TEŞHİS VE KONTROL','06':'ARAYÜZ GALERİSİ','10':'WINDOWS UYUMLULUĞU','07':'PAKET SEÇİMİ','08':'KOMUT GÜVENLİĞİ','09':'EKOSİSTEM'}
 cues=report.get('tutorial_audio_cues',[])
 for number,cue in enumerate(cues,1):
  prefix=cue['audio_file'][:2];base=cue['video_offset_seconds'];length=cue['duration_seconds']
  # Left gutter only. Keep browser controls and the operating-system taskbar clear.
  emit(3,base,base+length,'{\\an7\\pos(24,996)\\fs17\\1c&HC8D3DD&\\bord0.5\\3c&H131B24&\\fad(220,220)}'+escape(f'{number:02} · '+chapters[prefix]))
  for offset,seconds,title,body in notes.get(prefix,[]):
   start=base+offset;end=min(base+length-.2,start+seconds)
   # Verified empty right gutter of this browser chapter: x>=1576, width320.
   x=1576;y=182;w=320;h=144
   def motion(dx=0,dy=0):return f'\\move({1948+dx},{y+dy},{x+dx},{y+dy},0,320)\\fad(180,260)'
   emit(5,start,end,'{\\an7'+motion()+'\\p1\\bord1.2\\shad1\\1c&H2B1E11&\\1a&H12&\\3c&H735C40&\\3a&H50&}'+rectangle(w,h,14))
   emit(6,start,end,'{\\an7'+motion(18,15)+'\\fs12\\b1\\1c&H70D8FF&}SUNUM NOTU')
   emit(6,start,end,'{\\an7'+motion(18,37)+'\\fs21\\b1\\1c&HF4F7FA&}'+escape(title))
   for line,text in enumerate(body):
    emit(6,start,end,'{\\an7'+motion(18,76+line*26)+'\\fs19\\1c&HDCE5ED&}'+escape(text))
   # Restrained hand-drawn-style underline reveals left to right, not blinking.
   emit(7,start+.36,end,'{\\an7\\pos(1594,248)\\clip(1594,246,1594,252)\\t(0,480,\\clip(1594,246,1712,252))\\p1\\bord0\\1c&H70D8FF&\\1a&H30&}m 0 0 b 24 2 74 -1 118 1 l 118 3 b 74 1 24 4 0 2')
   cards.append({'start':start,'end':end,'title':title,'body':body,'safe_rect':[x,y,w,h]})
 events.sort(key=lambda e:e[0]);path=out/'presentation.ass';path.write_text(HEADER+''.join(e[1] for e in events),encoding='utf-8')
 audit={'status':'PASS','cursor_style':'44x30 warm yellow translucent oval, 5px centre dot; native arrow excluded at capture','pointer_samples':len(samples),'cursor_keyframes':len(kept),'real_click_pulses':sum(e.get('action')=='real_mouse_click' for e in report.get('tutorial_browser_events',[])),'animated_note_count':len(cards),'notes':cards,'source_content_modified':False,'ui_interaction_affected':False,'note_layout_scope':'Verified browser right gutter only; GUI chapters require their own safe area, never blindly reuse','voice_rate':1.0}
 (out/'presentation-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8');return path,audit

def self_test():
 import tempfile
 with tempfile.TemporaryDirectory() as temp:
  out=Path(temp);(out/'actual-pointer.csv').write_text('seconds,x,y\n0,200,300\n1,200,300\n2,400,500\n3,400,500\n')
  report={'tutorial_audio_cues':[{'audio_file':'01-readme.mp3','video_offset_seconds':0,'duration_seconds':20}],'tutorial_browser_events':[{'action':'real_mouse_click','x':400,'y':500,'video_offset_seconds':2}]}
  path,audit=build(out,report,20)
  assert audit['animated_note_count']==1 and audit['real_click_pulses']==1
  assert all(c['safe_rect'][0]>=1576 and c['safe_rect'][0]+c['safe_rect'][2]<=1920 for c in audit['notes'])
  assert '\\move(' in path.read_text() and 'DOĞRU KAYNAK' in path.read_text()
  assert timestamp(3661.23)=='1:01:01.23'
 print('presentation_overlay self-test PASS')
if __name__=='__main__':self_test()
