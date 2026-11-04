"""Real FFmpeg + throttled HTTP: emit media before the whole audio is fetched."""
import http.server
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from idm_linux.stream_engine import ActiveStreamJob, StreamTicket

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
class LiveMuxDeliveryTests(unittest.TestCase):
    def test_real_mux_emits_bytes_before_audio_download_finishes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for cmd in [
                ['ffmpeg','-v','error','-y','-f','lavfi','-i','color=blue:s=64x64:r=10','-t','6','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-movflags','+faststart',str(root/'v.mp4')],
                ['ffmpeg','-v','error','-y','-f','lavfi','-i','anoisesrc=color=white:sample_rate=44100','-t','60','-c:a','aac','-b:a','128k','-movflags','+faststart',str(root/'a.m4a')],
            ]:
                subprocess.run(cmd,check=True,timeout=20,capture_output=True)
            bodies={'/v.mp4':(root/'v.mp4').read_bytes(),'/a.m4a':(root/'a.m4a').read_bytes()}
            observed={'audio_eof':False,'audio_bytes':0}
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    body=bodies.get(self.path)
                    if body is None:self.send_error(404);return
                    start=0;end=len(body)-1
                    m=re.match(r'bytes=(\d+)-(\d*)',self.headers.get('Range',''))
                    if m:
                        start=int(m.group(1));end=min(int(m.group(2)),end) if m.group(2) else end
                    self.send_response(206 if m else 200)
                    self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
                    if m:self.send_header('Content-Range',f'bytes {start}-{end}/{len(body)}')
                    self.end_headers()
                    try:
                        for offset in range(start,end+1,16384):
                            part=body[offset:min(offset+16384,end+1)];self.wfile.write(part);self.wfile.flush()
                            if self.path=='/a.m4a':
                                observed['audio_bytes']+=len(part);time.sleep(0.04)
                        if self.path=='/a.m4a' and end==len(body)-1:observed['audio_eof']=True
                    except (OSError,ConnectionError):pass
                def log_message(self,*args):pass
            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
            threading.Thread(target=server.serve_forever,daemon=True).start()
            base=f'http://127.0.0.1:{server.server_port}'
            job=ActiveStreamJob(StreamTicket(ticket_id='real-live',source_url=base+'/v.mp4',filename='mux.mp4',mode='fast_mux',mux_video_url=base+'/v.mp4',mux_audio_url=base+'/a.m4a'),root/'job')
            result=[];started=time.monotonic()
            thread=threading.Thread(target=lambda:result.append(job._run_prebuilt_urls_ffmpeg_mux(shutil.which('ffmpeg'))),daemon=True)
            thread.start();snapshot=None
            try:
                deadline=started+20
                while time.monotonic()<deadline:
                    if job.stream_file.exists() and job.stream_file.stat().st_size>=16384:
                        snapshot={'first_media_seconds':round(time.monotonic()-started,3),**observed};break
                    if not thread.is_alive():break
                    time.sleep(0.02)
                self.assertIsNotNone(snapshot, 'No growing MP4 media observed')
                self.assertFalse(snapshot['audio_eof'],snapshot)
                thread.join(timeout=25);self.assertFalse(thread.is_alive())
                self.assertEqual(result,[True]);self.assertTrue(job.completed)
                data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=codec_type','-of','json',str(job.output_file)],timeout=10))
                types=[s['codec_type'] for s in data['streams']]
                self.assertEqual(types.count('video'),1);self.assertEqual(types.count('audio'),1)
                print('REAL_LIVE_MUX_EVIDENCE',json.dumps({**snapshot,'audio_total_bytes':len(bodies['/a.m4a']),'final_bytes':job.output_file.stat().st_size,'streams':types}))
            finally:
                job.stop();server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
