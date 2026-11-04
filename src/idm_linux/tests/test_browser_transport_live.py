"""Opt-in real Chromium extension + bound-frame + real FFmpeg integration.
Run: IDM_RUN_BROWSER_TESTS=1 PYTHONPATH=src python -m unittest discover ...
All external hosts are fulfilled by fixtures; no real VPN/IP service is contacted.
"""
import concurrent.futures
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from idm_linux.browser_transport import BrowserFetchBroker, BrowserTransportError
from idm_linux.daemon import make_http_handler, ReusableThreadingHTTPServer
from idm_linux import hls_streamer as hs
from idm_linux.stream_engine import ActiveStreamJob, StreamTicket


@unittest.skipUnless(os.getenv('IDM_RUN_BROWSER_TESTS') == '1', 'Opt-in installed real Chromium required')
class RealBrowserTransportTests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / 'media'; self.media.mkdir()
        r = subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','4','-c:v','libx264','-preset','ultrafast','-g','10','-sc_threshold','0','-c:a','aac','-f','hls','-hls_time','1','-hls_list_size','0','-hls_segment_filename',str(self.media/'seg%d.ts'),str(self.media/'video.m3u8')],capture_output=True,timeout=15)
        self.assertEqual(r.returncode, 0)
        self.broker = BrowserFetchBroker()
        self.cfg = SimpleNamespace(http_port=0, capture_downloads=True)
        state = SimpleNamespace(browser_fetch=self.broker, cfg=self.cfg, ext_disabled=False)
        self.server = ReusableThreadingHTTPServer(('127.0.0.1',0),make_http_handler(state));self.cfg.http_port=self.server.server_port
        threading.Thread(target=self.server.serve_forever,daemon=True).start(); self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        ext=self.root/'extension';ext.mkdir()
        packaged=Path(hs.__file__).parent/'extension'/'chromium'
        (ext/'browser_transport.js').write_bytes((packaged/'browser_transport.js').read_bytes())
        text=(packaged/'content.js').read_text(); marker='// Strict browser transport: only extension messages'
        (ext/'frame.js').write_text(text[text.index(marker):])
        (ext/'background.js').write_text('const extApi=chrome; let extensionDisabled=false; async function callBridge(path,method,body){ const r=await fetch("http://127.0.0.1:'+str(self.cfg.http_port)+'"+path,{method,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});return r.json();}\nimportScripts("browser_transport.js");')
        manifest={'manifest_version':3,'name':'Browser transport fixture','version':'1.0.0','permissions':['tabs','webNavigation'],'host_permissions':['<all_urls>'],'background':{'service_worker':'background.js'},'content_scripts':[{'matches':['https://player.test/*'],'js':['frame.js'],'all_frames':True}]}
        (ext/'manifest.json').write_text(json.dumps(manifest))
        self.pw=sync_playwright().start();self.addCleanup(self.pw.stop)
        self.context=self.pw.chromium.launch_persistent_context(str(self.root/'profile'),channel='chromium',headless=True,args=['--no-sandbox','--disable-extensions-except='+str(ext),'--load-extension='+str(ext)])
        self.addCleanup(self.context.close)
        self.ip='203.0.113.5';self.requests=[];self.block_media=False
        def route(r):
            url=r.request.url
            cors={'Access-Control-Allow-Origin':'https://player.test','Access-Control-Allow-Credentials':'true','Access-Control-Expose-Headers':'Content-Range,Content-Type','Content-Type':'application/octet-stream'}
            if url.startswith('http://127.0.0.1:'):
                r.continue_()
            elif url.startswith('https://player.test'):
                r.fulfill(status=200,content_type='text/html',body='<html><body>Authorized media fixture</body></html>')
            elif url.startswith('https://api.ipify.org/'):
                r.fulfill(status=200,headers=cors,body=json.dumps({'ip':self.ip}))
            elif url.startswith('https://media.test/'):
                self.requests.append(url)
                if self.block_media:r.abort();return
                name=urllib.parse.urlsplit(url).path.lstrip('/');file=self.media/name
                if not file.is_file():r.fulfill(status=404,headers=cors,body='missing');return
                body=file.read_bytes();range_header=r.request.headers.get('range')
                if range_header:
                    import re
                    m=re.fullmatch(r'bytes=(\d+)-(\d*)',range_header);start=int(m.group(1));end=min(int(m.group(2)),len(body)-1) if m.group(2) else len(body)-1
                    cors['Content-Range']=f'bytes {start}-{end}/{len(body)}'
                    r.fulfill(status=206,headers=cors,body=body[start:end+1])
                else:r.fulfill(status=200,headers=cors,body=body)
            else:r.abort()
        self.context.route('**/*',route)
        self.page=self.context.pages[0];self.page.goto('https://player.test/watch')
        self.worker=self.context.service_workers[0] if self.context.service_workers else self.context.wait_for_event('serviceworker')
        self.token=self.worker.evaluate('''async () => { const tabs=await chrome.tabs.query({url:"https://player.test/*"});return await IdmBrowserTransport.prepare(tabs[0].id,0,"https://player.test/watch",true); }''')
        self.addCleanup(lambda:self.broker.revoke(self.token))
        self.transport=self.broker.transport(self.token,'chrome-extension://'+self.worker.url.split('/')[2]);self.transport.local_base='http://127.0.0.1:'+str(self.cfg.http_port)
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=1);self.addCleanup(lambda:(self.broker.revoke(self.token), self.pool.shutdown(wait=True)))

    def finish(self,future,timeout=40):
        deadline=time.monotonic()+timeout
        while not future.done() and time.monotonic()<deadline:self.page.wait_for_timeout(30)
        self.assertTrue(future.done(),'Browser pipeline did not finish')
        return future.result(timeout=1)

    def test_real_bound_browser_hls_never_calls_backend_upstream(self):
        with patch.object(hs.urllib.request,'urlopen',side_effect=AssertionError('Backend upstream forbidden')):
            future=self.pool.submit(lambda:b''.join(hs.stream_hls_as_mp4('https://media.test/video.m3u8',browser_transport=self.transport)))
            data=self.finish(future)
        target=self.root/'full.mp4';target.write_bytes(data)
        r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(target)],capture_output=True,text=True,timeout=5)
        self.assertEqual(r.returncode,0);self.assertGreaterEqual(float(r.stdout),3.9)
        self.assertGreaterEqual(len(self.requests),5)
        print('REAL_BROWSER_HLS',json.dumps({'bytes':len(data),'duration':float(r.stdout),'browser_requests':len(self.requests),'backend_upstream_calls':0}))

    def test_progressive_multi_range_matches_original(self):
        import hashlib
        data = (b"BROWSER-ONLY-DATA-" + bytes(range(256))) * 17000
        (self.media/'large.bin').write_bytes(data)
        job=ActiveStreamJob(StreamTicket('progressive','https://media.test/large.bin','large.bin','browser_file',browser_transport=self.transport),self.root/'job')
        future=self.pool.submit(job._run_worker);self.finish(future)
        self.assertFalse(job.failed,job.error_msg);self.assertTrue(job.completed)
        output=job.output_file if job.output_file.exists() else job.stream_file
        self.assertEqual(hashlib.sha256(output.read_bytes()).digest(),hashlib.sha256(data).digest())
        self.assertGreaterEqual(len(self.requests),3)
        print('REAL_BROWSER_PROGRESSIVE',json.dumps({'bytes':len(data),'browser_range_requests':len(self.requests),'sha256_match':True}))

    def test_resolved_separate_video_audio_mux(self):
        for kind,flag in [('v.mp4','0:v:0'),('a.m4a','0:a:0')]:
            r=subprocess.run(['ffmpeg','-v','error','-y','-i',str(self.media/'video.m3u8'),'-map',flag,'-c','copy','-movflags','+faststart',str(self.media/kind)],capture_output=True,timeout=10)
            self.assertEqual(r.returncode,0)
        job=ActiveStreamJob(StreamTicket('mux','https://media.test/v.mp4','mux.mp4','browser_mux',mux_video_url='https://media.test/v.mp4',mux_audio_url='https://media.test/a.m4a',browser_transport=self.transport),self.root/'mux')
        self.finish(self.pool.submit(job._run_worker));self.assertFalse(job.failed,job.error_msg);self.assertTrue(job.completed)
        r=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type','-of','json',str(job.output_file)],capture_output=True,text=True,timeout=5)
        self.assertEqual(r.returncode,0);self.assertEqual({x['codec_type'] for x in json.loads(r.stdout)['streams']},{'video','audio'})
        print('REAL_BROWSER_MUX',json.dumps({'bytes':job.output_file.stat().st_size,'has_video_and_audio':True,'browser_requests':len(self.requests)}))

    def test_aes128_key_master_and_separate_audio_use_bound_browser(self):
        key=bytes(range(16));(self.media/'key.bin').write_bytes(key)
        for file in self.media.glob('seg*.ts'):
            r=subprocess.run(['openssl','enc','-aes-128-cbc','-K',key.hex(),'-iv','00'*16,'-in',str(file),'-out',str(self.media/('enc'+file.name))],capture_output=True,timeout=5)
            self.assertEqual(r.returncode,0)
        body=(self.media/'video.m3u8').read_text().replace('#EXTM3U','#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin",IV=0x'+'00'*16).replace('seg','encseg')
        (self.media/'encrypted.m3u8').write_text(body)
        (self.media/'master.m3u8').write_text('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="tr",NAME="Turkce",LANGUAGE="tr",DEFAULT=YES,AUTOSELECT=YES,URI="video.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=160x90,AUDIO="tr"\nencrypted.m3u8\n')
        with patch.object(hs.urllib.request,'urlopen',side_effect=AssertionError('Backend upstream forbidden')):
            data=self.finish(self.pool.submit(lambda:b''.join(hs.stream_hls_as_mp4('https://media.test/master.m3u8',browser_transport=self.transport))))
        (self.root/'aes.mp4').write_bytes(data)
        r=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type','-of','json',str(self.root/'aes.mp4')],capture_output=True,text=True,timeout=5)
        self.assertEqual(r.returncode,0);self.assertEqual({x['codec_type'] for x in json.loads(r.stdout)['streams']},{'video','audio'})
        self.assertTrue(any(x.endswith('/key.bin') for x in self.requests))
        print('REAL_BROWSER_AES_AND_AUDIO',json.dumps({'bytes':len(data),'browser_requests':len(self.requests),'key_requested_in_browser':True}))

    def test_nested_playlist_cannot_make_ffmpeg_open_external_url(self):
        import http.server
        attempts=[]
        segment=(self.media/'seg0.ts').read_bytes()
        class Trap(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                attempts.append(self.path);self.send_response(200);self.send_header('Content-Length',str(len(segment)));self.end_headers();self.wfile.write(segment)
        trap=http.server.ThreadingHTTPServer(('127.0.0.1',0),Trap)
        threading.Thread(target=trap.serve_forever,daemon=True).start();self.addCleanup(trap.server_close);self.addCleanup(trap.shutdown)
        (self.media/'evil.mp4').write_text('#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\nhttp://127.0.0.1:'+str(trap.server_port)+'/leak.ts\n#EXT-X-ENDLIST\n')
        job=ActiveStreamJob(StreamTicket('reject','https://media.test/evil.mp4','reject.mp4','browser_mux',mux_video_url='https://media.test/evil.mp4',mux_audio_url='https://media.test/evil.mp4',browser_transport=self.transport),self.root/'reject')
        self.finish(self.pool.submit(job._run_worker));self.assertTrue(job.failed);self.assertFalse(job.completed)
        self.assertEqual(attempts,[],'FFmpeg made an unauthorized external request')

    def test_changed_exit_stops_before_media_request(self):
        self.ip='203.0.113.6';self.page.wait_for_timeout(2400)
        with self.assertRaises(BrowserTransportError):self.transport.assert_healthy()
        self.assertEqual(self.requests,[])

    def test_cors_network_failure_cannot_fall_back_to_backend(self):
        self.block_media=True
        with patch.object(hs.urllib.request,'urlopen',side_effect=AssertionError('Backend upstream forbidden')):
            future=self.pool.submit(lambda:hs.fetch_url_bytes('https://media.test/video.m3u8',hs.BrowserHeaders({},self.transport)))
            with self.assertRaises(BrowserTransportError):self.finish(future)
        self.assertLessEqual(len(self.requests),2)

    def test_frame_close_revokes_transport(self):
        self.page.goto('https://player.test/another')
        self.page.wait_for_timeout(500)
        with self.assertRaises(BrowserTransportError):self.transport.assert_healthy()


if __name__=='__main__':unittest.main(verbosity=2)
