"""Real original daemon HTTP stream routes -> original native IDM via manual URL Add.
Own source page is explicitly a recording fixture, NOT counterfeit product UI.
Separate normal media-only daemon profile prevents vendor-helper healing/substitution.
No automatic browser interception or completed-film claim.
"""
import os,sys,json,time,subprocess,signal,hashlib,threading,functools,ast,socketserver,socket,struct
from pathlib import Path
from urllib.parse import quote
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
import cv2,requests,websocket
from idm_linux.config import IdmLinuxConfig,get_cache_dir
from idm_linux.wine_sender import build_wine_env
from turkish_quality_gate import assert_clean
O=Path('out/film15-owned-native-streams').resolve();O.mkdir(parents=True,exist_ok=True)
os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH']
native_cfg=IdmLinuxConfig.load();assert native_cfg.find_idm_exe();os.environ.update(build_wine_env(native_cfg));probe=Path('out/film14-native-turkish/native-turkish-probe.exe').resolve()
# Reuse only our existing read-only native inspector and real input/browser primitives.
helpers={'save','event','shot','physical','keys','type_ascii','activate','CDP','targets','connect_url','native','button'}
tree=ast.parse(Path('.github/film-production/native_pixeldrain_capture.py').read_text());exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in helpers],type_ignores=[]),'existing-real-input-primitives','exec'))
epoch=time.monotonic();events=[];recorder=None;publisher=None;seeder=None;discovery=None
for k,v in [('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache')]:os.environ[k]=str(O/v)
media_cfg=IdmLinuxConfig(language='tr',wine_prefix=str(O/'no-native-installed'),download_dir=str(O/'media-engine-outputs'),keep_wine_warm=False);media_cfg.save();assert media_cfg.find_idm_exe() is None
from idm_linux.daemon import DaemonState,make_http_handler,ReusableThreadingHTTPServer
state=DaemonState();assert state.cfg.find_idm_exe() is None
bridge=ReusableThreadingHTTPServer(('127.0.0.1',0),make_http_handler(state));state.cfg.http_port=bridge.server_port;threading.Thread(target=bridge.serve_forever,daemon=True).start()
engine=state.stream_engine
source=O/'own-source';source.mkdir(exist_ok=True)
def command(args):return subprocess.run(args,check=True,capture_output=True,text=True)
master=source/'own-20-seconds.mp4'
command(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','20','-c:v','libx264','-preset','ultrafast','-g','48','-keyint_min','48','-sc_threshold','0','-pix_fmt','yuv420p','-c:a','aac',str(master)])
hls=['-c','copy','-f','hls','-hls_time','2','-hls_list_size','0','-hls_flags','independent_segments']
command(['ffmpeg','-nostdin','-v','error','-y','-i',str(master),*hls,str(source/'vod.m3u8')])
source_requests=[]
class Source(SimpleHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):source_requests.append({'seconds':round(time.monotonic()-epoch,3),'path':self.path});super().do_GET()
 def copyfile(self,src,out):
  try:
   while True:
    chunk=src.read(16384)
    if not chunk:break
    out.write(chunk);out.flush()
    if self.path.split('?')[0].endswith('.ts'):time.sleep(.25)
  except (OSError,ConnectionResetError):pass
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Source,directory=str(source)));threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
report={'scope':'Actual ORIGINAL daemon HTTP routes and ORIGINAL native IDM linked by manual URL Add; own source page explicitly a fixture, not product GUI','automatic_browser_interception_verified':False,'product_code_modified':False,'vendor_helper_substitution':False,'media_only_bridge_profile':True,'native_IDM_in_separate_existing_original_prefix':True,'finished_lesson':False,'final_film_export_allowed':False,'cases':[]}
def persist():save('actual-owned-native-streams-review.json',report);save('actual-own-source-http-requests.json',source_requests)
def frames(path):return [s.split(',')[-1].strip() for s in command(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-an','-f','framemd5','-']).stdout.splitlines() if s and not s.startswith('#')]
reference=frames(master);assert len(reference)==480
from configure_native_speed_limit import configure
# ONLY ordinary real user preference; never fabricated progress/throttled client buffers.
for l in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
 if 'günün ipucu' in l.lower():subprocess.run(['wmctrl','-ia',l.split()[0]],check=True);keys('Escape')
report['actual_native_speed_limit_configuration']=configure(100)
def source_page(mode,url):
 filename=mode+'-source.html'
 (source/filename).write_text('<!doctype html><html lang="tr"><meta charset="utf-8"><title>Kendi izinli '+mode+' kaynağımız</title><style>body{background:#101820;color:#eee;font:20px sans-serif;padding:50px;max-width:1000px}h1{color:#d29a12}input{width:98%;font:17px monospace;padding:15px;margin:25px 0}p{line-height:1.6}</style><h1>Kendi izinli '+mode+' kaynağımız</h1><p>Bu sayfa film için hazırlanan gerçek kaynak sayfasıdır; IDM arayüzü değildir.</p><p>Kullanılan dosya ve yayınlar bize aittir. Aşağıdaki gerçek bağlantı, özgün yazılımın yerel medya köprüsüdür. IDM’ye elle URL Ekle yoluyla aktarılır; otomatik tarayıcı yakalaması iddia edilmez.</p><input id="bridge" autofocus readonly value="'+url+'"><p>İlerleme ve tamamlanma, özgün IDM penceresinde izlenecektir.</p>',encoding='utf8')
 activate('brave');keys('ctrl+l');type_ascii(origin+'/'+filename);keys('Return');page=connect_url(origin+'/'+filename);time.sleep(1)
 actual=page.read("({title:document.title,text:document.body.innerText,focused:document.activeElement.id,url:document.getElementById('bridge').value})");save(mode+'-actual-own-page.json',actual)
 assert actual['focused']=='bridge' and actual['url']==url
 shot(mode+'-actual-own-source-page');keys('ctrl+a');keys('ctrl+c');time.sleep(.2)
 import tkinter as tk
 clipboard=tk.Tk();clipboard.withdraw()
 try:copied=clipboard.clipboard_get()
 finally:clipboard.destroy()
 assert copied==url
 event(mode+'-actual-browser-copy-own-original-bridge-url');page.ws.close()
def native_transfer(mode,url,name):
 source_page(mode,url);time.sleep(2);activate('Internet Download Manager');shot(mode+'-before-url-add')
 im=cv2.imread(str(O/(mode+'-before-url-add.png')));icon=cv2.imread('.github/film-production/actual-native-url-icon.png');_,score,_,pos=cv2.minMaxLoc(cv2.matchTemplate(im,icon,cv2.TM_CCOEFF_NORMED));assert score>.985
 physical([*pos,pos[0]+icon.shape[1],pos[1]+icon.shape[0]],mode+'-real-native-url-add');time.sleep(.5)
 cc,tt,ww=native(mode+'-real-url-dialog');assert 'İndirilecek yeni adresi girin' in ww
 edits=[c for c in cc if c['visible'] and c['class']=='Edit' and not c['style']&0x08000000];assert len(edits)==1
 physical(edits[0]['rect'],mode+'-actual-address-field');keys('ctrl+a');keys('ctrl+v');button(cc,'Tamam');time.sleep(2)
 deadline=time.monotonic()+45
 while True:
  cc,tt,ww=native(mode+'-real-file-information')
  if any('Dosya İndirme Bilgisi' in w for w in ww):break
  assert time.monotonic()<deadline,'Actual native file-info dialog did not appear';time.sleep(.5)
 assert any(name in c['text'] for c in cc if c['visible'] and c['class'] in ['Edit','ComboBox']),'Original own filename must be present in actual native file info'
 event(mode+'-actual-native-start',filename=name);button(cc,'İndirmeyi Başlat');deadline=time.monotonic()+240;states=[];progress=False
 while time.monotonic()<deadline:
  time.sleep(1)
  # Original read-only inspector; periodic screenshots only first/progress/completion.
  r=subprocess.run(['wine',str(probe)],capture_output=True,check=True,timeout=30);texts=[];titles=[]
  for line in r.stdout.decode().splitlines():
   a=line.split('\t')
   if a[0] in ['TEXT','WINDOW']:texts.append(bytes.fromhex(a[1]).decode('utf8'))
   if a[0]=='WINDOW':titles.append(bytes.fromhex(a[1]).decode('utf8'))
  states.append({'seconds':round(time.monotonic()-epoch,3),'titles':titles,'texts':texts});save(mode+'-actual-native-states.json',states)
  if any('Duraklat' in s for s in texts):
   if not progress:shot(mode+'-real-native-progress')
   progress=True
  if any('tamamland' in w.replace('İ','i').lower() for w in titles):break
 else:raise AssertionError('Actual native completion bounded wait expired')
 assert progress,'No actual native progress/pause window was observed'
 candidates=[p for root in [Path.home()/'Downloads',Path(native_cfg.download_dir),Path(native_cfg.wine_prefix)/'drive_c/users'] if root.exists() for p in root.rglob(name) if p.is_file()]
 assert candidates,'Actual native file not found';p=candidates[0]
 event(mode+'-actual-native-completion',bytes=p.stat().st_size);shot(mode+'-native-completed');time.sleep(4)
 cc,tt,ww=native(mode+'-completed-close-control');button(cc,'Kapat');time.sleep(.5)
 return p,states
try:
 log=(O/'actual-capture.log').open('w');recorder=subprocess.Popen(['ffmpeg','-nostdin','-y','-v','warning','-f','x11grab','-draw_mouse','0','-s','1920x1080','-r','24','-i',os.environ['DISPLAY'],'-an','-c:v','libx264','-preset','veryfast','-crf','18','-threads','2',str(O/'uncut-owned-original-bridge-native.mp4')],stdout=log,stderr=subprocess.STDOUT);event('actual-recording-started')
 for mode,name in ([] if os.environ.get('FILM_OWNED_NATIVE_ED2K_ONLY')=='true' else [('vod','izinli_hls_vod.mp4'),('dvr','izinli_canli_dvr.mp4')]):
  history=0
  if mode=='dvr':
   publisher=subprocess.Popen(['ffmpeg','-nostdin','-v','error','-y','-stream_loop','2','-re','-i',str(master),*hls,'-hls_playlist_type','event',str(source/'live.m3u8')],stdout=subprocess.DEVNULL,stderr=open(O/'actual-live-publisher.log','w'));deadline=time.monotonic()+45
   while time.monotonic()<deadline:
    text=(source/'live.m3u8').read_text() if (source/'live.m3u8').exists() else ''
    if text.count('#EXTINF')>=6 and '#EXT-X-ENDLIST' not in text:break
    time.sleep(.2)
   assert text.count('#EXTINF')>=6 and '#EXT-X-ENDLIST' not in text
   history=text.count('#EXTINF');event('actual-live-dvr-history-ready',segments=history)
  ticket=engine.create_ticket(origin+('/vod.m3u8' if mode=='vod' else '/live.m3u8'),name,'hls_native',is_hls=True,hls_mode=mode)
  url=f'http://127.0.0.1:{bridge.server_port}/stream/{ticket.ticket_id}/{quote(ticket.filename)}';path,states=native_transfer(mode,url,ticket.filename)
  actual_frames=frames(path);assert actual_frames==reference*(3 if mode=='dvr' else 1),'Native downloaded all original video frames in order'
  decoded=command(['ffmpeg','-v','error','-i',str(path),'-f','null','-']);assert not decoded.stderr
  report['cases'].append({'mode':mode,'actual_native_filename':path.name,'bytes':path.stat().st_size,'sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),'all_source_video_frames_identical':len(actual_frames),'actual_original_daemon_route_used':True,'actual_native_progress_and_completion':True,'history_segments_at_live_dvr_start':history,'backend':ticket.backend,'full_decode_pass':True});persist()
 if os.environ.get('FILM_OWNED_NATIVE_ED2K_ONLY')=='true':
  from idm_linux.p2p import ed2k_native as E
  from idm_linux.tests.test_ed2k_peer_live import ReferenceSeeder
  from idm_linux.ed2k_bridge import ed2k_register_native
  payload=bytes(range(256))*(E.ED2K_PART_SIZE//256)+bytes(range(256))*844
  name='izinli_ed2k_ornegi.bin';seeder=ReferenceSeeder(payload,name);seeder.start();wire=[]
  class Discovery(socketserver.BaseRequestHandler):
   def handle(self):
    self.request.settimeout(15)
    try:
     while True:
      packet=E._recv_packet(self.request)
      if packet is None:return
      op,body=packet;wire.append({'opcode':op,'payload_bytes':len(body)})
      if op==E.OP_LOGINREQUEST:E._send_packet(self.request,E.OP_IDCHANGE,struct.pack('<I',0x1234))
      elif op in (E.OP_GETSOURCES,E.OP_GETSOURCES_OBFU):
       assert body[:16]==seeder.file_hash
       E._send_packet(self.request,E.OP_FOUNDSOURCES,seeder.file_hash+b'\x01'+socket.inet_aton('127.0.0.1')+struct.pack('<H',seeder.port))
    except OSError:return
  discovery=socketserver.ThreadingTCPServer(('127.0.0.1',0),Discovery);discovery.daemon_threads=True;threading.Thread(target=discovery.serve_forever,daemon=True).start()
  (get_cache_dir(create=True)/'ed2k_servers.json').write_text(json.dumps({'ts':time.time(),'servers':[['127.0.0.1',discovery.server_address[1]]]}))
  link=f'ed2k://|file|{name}|{len(payload)}|{seeder.file_hash.hex()}|/'
  ok,msg,meta=ed2k_register_native(link,str(O/'actual-ed2k-engine-output'));assert ok,msg
  url=f'http://127.0.0.1:{bridge.server_port}/ed2k/{meta["ticket"]}/{quote(name)}'
  path,states=native_transfer('ed2k',url,name);session=meta['session']
  assert path.read_bytes()==payload and session.complete and session.compute_file_hash()==seeder.file_hash
  assert seeder.served_bytes>=len(payload) and seeder.requests>0
  assert E.OP_LOGINREQUEST in [x['opcode'] for x in wire] and E.OP_GETSOURCES in [x['opcode'] for x in wire]
  report['cases'].append({'mode':'ed2k','actual_original_daemon_route_used':True,'actual_native_progress_and_completion':True,'native_original_filename_preserved':path.name==name,'bytes':path.stat().st_size,'sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),'ed2k_hash':session.compute_file_hash().hex(),'actual_discovery_wire_requests':wire,'actual_peer_served_bytes':seeder.served_bytes,'actual_peer_part_requests':seeder.requests,'multipart_count':session.num_parts,'scope':'Owned real private discovery/peer network, not public-network or automatic interception proof'})
  report['actual_original_bridge_native_ed2k_verified']=True;persist()
 else:report['actual_original_bridge_native_hls_and_dvr_verified']=True;persist()
except Exception as e:
 report.update(failure=type(e).__name__+': '+str(e));persist();shot('stopped-on-real-state');raise
finally:
 if recorder is not None:recorder.send_signal(signal.SIGINT);recorder.wait(timeout=30)
 if seeder is not None:
  from idm_linux.ed2k_bridge import ed2k_shutdown_all
  ed2k_shutdown_all();seeder.stop()
 if discovery is not None:discovery.shutdown();discovery.server_close()
 if publisher and publisher.poll() is None:publisher.terminate();publisher.wait(timeout=10)
 for item in engine.list_jobs():
  if not item['completed'] and not item['failed']:engine.stop_job(item['ticket'])
 bridge.shutdown();bridge.server_close();server.shutdown();server.server_close()
 manifest=json.loads(Path('out/film14-native-turkish/original-vendor-payload-manifest.json').read_text());vendor=native_cfg.find_idm_exe().parent
 report['original_vendor_binaries_unchanged']=all((vendor/f).is_file() and hashlib.file_digest((vendor/f).open('rb'),'sha256').hexdigest()==h for f,h in manifest['files'].items() if Path(f).suffix.lower() in ['.exe','.dll','.sys']);persist()

assert report['original_vendor_binaries_unchanged'],'Never certify a changed vendor payload'
