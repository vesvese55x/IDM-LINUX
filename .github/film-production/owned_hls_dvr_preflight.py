"""Real unmodified StreamEngine against our own finite VOD and advancing live/DVR HLS.
Backend evidence only, never a fabricated GUI or external-site/DRM compatibility claim.
"""
import os,sys,time,json,threading,subprocess,functools,hashlib
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
O=Path('out/film15-owned-streaming').resolve();O.mkdir(parents=True,exist_ok=True)
for key,leaf in [('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache')]:os.environ[key]=str(O/leaf)
os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH']
from idm_linux.config import IdmLinuxConfig
from idm_linux.stream_engine import StreamEngine
cfg=IdmLinuxConfig(download_dir=str(O/'actual-downloads'),wine_prefix=str(O/'no-native-installed'),keep_wine_warm=False);assert cfg.find_idm_exe() is None
source=O/'own-source';source.mkdir(exist_ok=True)
def run(args):return subprocess.run(args,check=True,capture_output=True,text=True)
master=source/'our-original-20seconds.mp4'
run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','20','-c:v','libx264','-preset','ultrafast','-g','48','-keyint_min','48','-sc_threshold','0','-pix_fmt','yuv420p','-c:a','aac',str(master)])
requests=[]
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):requests.append({'seconds':round(time.monotonic()-epoch,3),'path':self.path});super().do_GET()
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(source)));epoch=time.monotonic();threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
engine=StreamEngine(cfg);live=None
report={'scope':'Actual original backend own HLS VOD and genuinely advancing live/DVR source; not finished GUI lesson','own_generated_media_only':True,'DRM_or_authentication_bypass':False,'mocked_jobs_or_progress':False,'vendor_helpers_called':False,'finished_lesson':False,'final_film_export_allowed':False,'cases':[]}
def save():
 (O/'actual-owned-hls-dvr-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));(O/'actual-http-requests.json').write_text(json.dumps(requests,indent=2))
def frames(path):
 text=run(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-an','-f','framemd5','-']).stdout
 return [line.split(',')[-1].strip() for line in text.splitlines() if line and not line.startswith('#')]
reference=frames(master);assert len(reference)==480
hls=['-c','copy','-f','hls','-hls_time','2','-hls_list_size','0','-hls_flags','independent_segments']
run(['ffmpeg','-nostdin','-v','error','-y','-i',str(master),*hls,str(source/'vod.m3u8')])
try:
 for mode in ['vod','dvr']:
  if mode=='dvr':
   live=subprocess.Popen(['ffmpeg','-nostdin','-v','error','-y','-re','-i',str(master),*hls,'-hls_playlist_type','event',str(source/'live.m3u8')],stdout=subprocess.DEVNULL,stderr=open(O/'actual-live-publisher.log','w'))
   deadline=time.monotonic()+40
   while time.monotonic()<deadline:
    text=(source/'live.m3u8').read_text() if (source/'live.m3u8').exists() else ''
    if text.count('#EXTINF')>=6 and '#EXT-X-ENDLIST' not in text:break
    time.sleep(.2)
   assert text.count('#EXTINF')>=6 and '#EXT-X-ENDLIST' not in text,'DVR must start while own publisher is really live and history exists'
   history=text.count('#EXTINF')
  else:history=0
  url=origin+('/vod.m3u8' if mode=='vod' else '/live.m3u8')
  ticket=engine.create_ticket(url,'Gerçek izinli '+mode+'.mp4','hls_native',is_hls=True,hls_mode=mode)
  job=engine.get_job(ticket.ticket_id);output=O/('actual-'+mode+Path(ticket.filename).suffix)
  errors=[]
  def consume():
   try:
    with output.open('wb') as f:
     for chunk in job.iter_bytes_from():f.write(chunk)
   except Exception as exc:errors.append(type(exc).__name__+': '+str(exc))
  worker=threading.Thread(target=consume,daemon=True);worker.start();deadline=time.monotonic()+180;states=[]
  while worker.is_alive() and time.monotonic()<deadline:states.append(engine.list_jobs());worker.join(.25)
  assert not worker.is_alive(),'Real engine bounded wait expired'
  assert not errors and job.completed and not job.failed,('Actual engine failure',errors,job.error_msg)
  decode=run(['ffmpeg','-v','error','-i',str(output),'-f','null','-']);assert not decode.stderr
  hashes=frames(output);assert hashes==reference,'Actual output must decode to all original 480 video frames in order'
  probe=json.loads(run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,codec_name','-of','json',str(output)]).stdout)
  assert {'video','audio'}<={s['codec_type'] for s in probe['streams']}
  report['cases'].append({'mode':mode,'backend':ticket.backend,'history_segments_when_started':history,'output':output.name,'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'decoded_video_frames_identical_to_own_source':len(hashes),'actual_states':states,'probe':probe,'full_decode_pass':True});save()
 report['actual_hls_vod_and_dvr_backend_verified']=True;save()
finally:
 for item in engine.list_jobs():
  if not item['completed'] and not item['failed']:engine.stop_job(item['ticket'])
 if live and live.poll() is None:live.terminate();live.wait(timeout=10)
 server.shutdown();server.server_close();save()
