"""Own local fixture -> genuine native File Information dialog, then Cancel.
No native transfer start; not a Pixeldrain/playlist lesson or completion proof.
"""
import json,time,threading,subprocess,hashlib
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import quote,unquote,urlsplit
import cv2
from turkish_quality_gate import assert_clean
O=Path('out/film14-native-turkish/fileinfo');O.mkdir(parents=True,exist_ok=True)
name='Türkçe_ÇĞİÖŞÜ_çğıöşü.txt';body=('Bu dosya yalnızca Türkçe dosya adı ve arayüz kontrolü için oluşturulmuştur.\n'*512).encode('utf8');requests=[]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def respond(self,send):
  assert unquote(urlsplit(self.path).path)=='/'+name,'Unexpected fixture path'
  self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(len(body)));self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(name));self.end_headers()
  requests.append({'method':self.command,'path':self.path})
  if send:
   try:self.wfile.write(body)
   except (BrokenPipeError,ConnectionResetError):pass
 def do_GET(self):self.respond(True)
 def do_HEAD(self):self.respond(False)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
probe=Path('out/film14-native-turkish/native-turkish-probe.exe').resolve()
def snapshot(tag):
 subprocess.run(['import','-window','root',str(O/(tag+'-before-probe.png'))],check=True)
 # Use regular files: an inherited Wine background-process pipe must not look like a hung UI.
 with (O/(tag+'-raw.txt')).open('wb') as stdout,(O/(tag+'-stderr.txt')).open('wb') as stderr:
  subprocess.run(['wine',str(probe)],stdout=stdout,stderr=stderr,check=True,timeout=30)
 raw=(O/(tag+'-raw.txt')).read_bytes().decode('utf8',errors='strict')
 controls=[];texts=[];titles=[]
 for line in raw.splitlines():
  a=line.split('\t')
  if a[0] in ['TEXT','WINDOW','MENU']:
   text=bytes.fromhex(a[1]).decode('utf8');assert_clean(text);texts.append(text)
   if a[0]=='WINDOW':titles.append(text)
  if a[0]=='CONTROL' and len(a)>7:
   controls.append({'class':bytes.fromhex(a[2]).decode(),'style':int(a[3],16),'rect':[int(v) for v in a[5].split(',')],'visible':a[6]=='1','text':bytes.fromhex(a[7]).decode('utf8')})
 subprocess.run(['import','-window','root',str(O/(tag+'.png'))],check=True)
 return controls,texts,titles
def click(control):
 x1,y1,x2,y2=control['rect'];assert 0<=x1<x2<=1920 and 0<=y1<y2<=1080
 subprocess.run(['xdotool','mousemove',str((x1+x2)//2),str((y1+y2)//2),'click','1'],check=True)
def button(controls,label):
 matches=[c for c in controls if c['visible'] and c['class']=='Button' and c['text'].replace('&','')==label]
 assert len(matches)==1,{'stop':'Unambiguous actual native button required','label':label,'matches':matches}
 click(matches[0])
try:
 # Dismiss only the known first-run Tip window before touching the underlying toolbar.
 for line in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
  if 'günün ipucu' in line.lower():
   subprocess.run(['wmctrl','-ia',line.split()[0]],check=True);subprocess.run(['xdotool','key','Escape'],check=True);time.sleep(.5)
 assert not any('günün ipucu' in line.lower() for line in subprocess.check_output(['wmctrl','-l'],text=True).splitlines()),'Known Tip dialog is still open; do not click through it'
 for line in subprocess.check_output(['wmctrl','-lx'],text=True).splitlines():
  if 'Internet Download Manager' in line and 'brave' not in line.lower():subprocess.run(['wmctrl','-ia',line.split()[0]],check=True)
 time.sleep(.7);subprocess.run(['import','-window','root',str(O/'before.png')],check=True)
 im=cv2.imread(str(O/'before.png'));icon=cv2.imread('.github/film-production/actual-native-url-icon.png');_,score,_,pos=cv2.minMaxLoc(cv2.matchTemplate(im,icon,cv2.TM_CCOEFF_NORMED));assert score>.985,'Do not click an unverified native icon'
 subprocess.run(['xdotool','mousemove',str(pos[0]+icon.shape[1]//2),str(pos[1]+icon.shape[0]//2),'click','1'],check=True);time.sleep(.5)
 controls,texts,titles=snapshot('01-url-dialog');assert 'İndirilecek yeni adresi girin' in titles
 edits=[c for c in controls if c['visible'] and c['class']=='Edit' and not c['style']&0x08000000]
 assert len(edits)==1,{'stop':'Expected one enabled address input','edits':edits}
 click(edits[0]);url='http://127.0.0.1:'+str(server.server_port)+'/'+quote(name)
 subprocess.run(['xdotool','key','--clearmodifiers','ctrl+a'],check=True);subprocess.run(['xdotool','type','--clearmodifiers','--delay','1',url],check=True);button(controls,'Tamam');time.sleep(2)
 controls,texts,titles=snapshot('02-actual-file-information')
 (O/'fileinfo-review.json').write_text(json.dumps({'scope':'own local fixture, native File Information only; not a transfer lesson','original_fixture_filename':name,'fixture_bytes':len(body),'fixture_sha256':hashlib.sha256(body).hexdigest(),'native_window_titles':titles,'native_texts':texts,'http_metadata_requests':requests,'native_transfer_start_clicked':False,'actual_transfer_or_completion_verified':False,'all_native_fonts_verified':False,'final_film_export_allowed':False},ensure_ascii=False,indent=2))
 assert any('Dosya İndirme Bilgisi' in title for title in titles),'Actual native File Information dialog was not found'
 assert any(name in text for text in texts),'Native filename did not retain the original Unicode fixture name; do not rename it to pass'
 button(controls,'İptal');time.sleep(.3);snapshot('03-after-cancel')
finally:
 server.shutdown();server.server_close()
