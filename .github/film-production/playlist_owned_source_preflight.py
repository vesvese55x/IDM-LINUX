"""Real own RSS playlist -> unmodified probe and serial queue -> selected real media.
This is backend preflight, NOT a completed GUI/YouTube playlist lesson. No mocks/cookies/native helper calls.
"""
import json,time,threading,subprocess,hashlib,functools,os
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from idm_linux.stream_engine import probe_playlist_entries
from idm_linux.playlist_batch import PlaylistBatchManager
O=Path('out/film14-playlist-owned');O.mkdir(parents=True,exist_ok=True);source=O/'own-source';source.mkdir(exist_ok=True)
for n,color in enumerate(['blue','green','red'],1):
 subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i',f'color=c={color}:s=320x180:r=24','-f','lavfi','-i',f'sine=frequency={330*n}:sample_rate=48000','-t','8','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(source/f'own-clip-{n}.mp4')],check=True)
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(source.resolve())))
threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
items=''.join(f'<item><title>Kendi örnek videomuz {i}</title><guid>own-item-{i}</guid><enclosure url="{origin}/own-clip-{i}.mp4" type="video/mp4" length="{(source/f"own-clip-{i}.mp4").stat().st_size}"/></item>' for i in range(1,4))
(source/'playlist.rss').write_text('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Kendi izinli örnek listemiz</title><description>Three genuinely generated sample clips, not third-party content or simulated download UI.</description><link>'+origin+'</link>'+items+'</channel></rss>')
url=origin+'/playlist.rss?list=own-demo'
report={'scope':'owned real RSS list backend preflight only; not a completed GUI or YouTube lesson','source_url':url,'media_source':'three ffmpeg-generated color/tone test videos owned by this demonstration','mocked_api_or_progress':False,'native_vendor_helpers_called':False,'gui_selection_or_cancel_verified':False,'finished_lesson':False,'final_film_export_allowed':False}
def save(): (O/'actual-playlist-backend-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
save();manager=None
try:
 info=probe_playlist_entries(url,max_items=3);report['actual_probe']=info;save()
 assert info['ok'] and len(info['entries'])==3,'Actual unmodified playlist extractor must return three entries'
 assert all(e['url'].startswith(origin+'/own-clip-') for e in info['entries']),'Only real owned media URLs; no invented IDs or fallback third-party URLs'
 selected=[info['entries'][0],info['entries'][2]];report['selected_actual_entries']=selected
 manager=PlaylistBatchManager(base_dir=O/'actual-downloads');batch=manager.start_batch(url,selected,str(O/'actual-downloads'));report['actual_batch_start']=batch;save();assert batch['ok']
 stages=[];deadline=time.monotonic()+120
 while time.monotonic()<deadline:
  st=manager.status(batch['batch_id']);stages.append(st)
  if st and st.get('done'):break
  time.sleep(.4)
 report['actual_batch_stages']=stages;final=manager.status(batch['batch_id']);report['actual_batch_final']=final;save()
 assert final and final.get('done'),'Real serial queue did not finish within bounded wait'
 files=list(Path(batch['out_dir']).glob('*.mp4'));assert len(files)==2,'Only selected entries may produce outputs'
 source_hashes={hashlib.file_digest((source/f'own-clip-{i}.mp4').open('rb'),'sha256').hexdigest():i for i in range(1,4)}
 verified=[]
 for f in files:
  h=hashlib.file_digest(f.open('rb'),'sha256').hexdigest();assert h in source_hashes,'Output must equal an actual source file'
  verified.append({'file':str(f),'bytes':f.stat().st_size,'sha256':h,'source_clip':source_hashes[h]})
 assert sorted(v['source_clip'] for v in verified)==[1,3],'Selection must exactly match outputs; middle item must not download'
 report.update(selected_outputs_verified=verified,actual_backend_selection_and_files_verified=True);save()
finally:
 if manager:manager.shutdown_all()
 server.shutdown();server.server_close()
