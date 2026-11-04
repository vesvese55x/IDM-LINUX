"""Regression tests for bounded blobs, passthrough and file-host routing."""
import base64
import hashlib
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler

from idm_linux.blob_transfer import BlobTransferStore
from idm_linux.mediafire_resolver import is_mediafire_url, is_mediafire_direct, parse_mediafire_download
from idm_linux.daemon import make_http_handler, ReusableThreadingHTTPServer
from idm_linux.auth_proxy import AuthenticatedProxyManager, AuthContextVault
from idm_linux import stream_engine as se

class BlobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = BlobTransferStore(Path(self.tmp.name) / 'uploads')

    def test_more_than_old_json_limit_byte_exact(self):
        data = (bytes(range(256)) * 40000) + b'end'
        key = self.store.begin('../sample.zip', 'application/zip', len(data))['transferId']
        for offset in range(0, len(data), self.store.CHUNK_BYTES):
            part = data[offset:offset+self.store.CHUNK_BYTES]
            reply = self.store.chunk(key, offset, base64.b64encode(part).decode())
            self.assertEqual(reply['received'], offset+len(part))
        result = self.store.finish(key)
        self.assertEqual(result['path'].read_bytes(), data)
        self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
        self.assertNotIn('/', result['filename'])

    def test_size_bounds_and_active_limit(self):
        for size in [-1, 0, True, 1.5, self.store.MAX_BYTES+1]:
            with self.assertRaises(ValueError): self.store.begin('x', '', size)
        for _ in range(self.store.MAX_ACTIVE): self.store.begin('x', '', 1)
        with self.assertRaises(ValueError): self.store.begin('x', '', 1)
        for key in list(self.store._jobs): self.store.cancel(key)

    def test_order_incomplete_and_malformed_chunk(self):
        key = self.store.begin('x', '', 2)['transferId']
        with self.assertRaises(ValueError): self.store.chunk(key, 1, 'YQ==')
        with self.assertRaises(ValueError): self.store.chunk(key, 0, '%%%')
        with self.assertRaises(ValueError): self.store.chunk(key, 0, 'a'* (self.store.CHUNK_BYTES*2))
        with self.assertRaises(ValueError): self.store.finish(key)
        self.store.chunk(key, 0, 'YQ==')
        with self.assertRaises(ValueError): self.store.chunk(key, 0, 'YQ==')
        self.store.cancel(key)
        self.assertEqual(list(self.store.directory.glob('*.part')), [])

    def test_expiry_removes_partial_file(self):
        key = self.store.begin('x', '', 1)['transferId']
        self.store._jobs[key]['touched'] -= self.store.TTL+1
        with self.assertRaises(ValueError): self.store.chunk(key, 0, 'YQ==')
        self.assertEqual(list(self.store.directory.glob('*.part')), [])

class HttpBlobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sent = []
        self.state = SimpleNamespace(cfg=SimpleNamespace(http_port=0,capture_downloads=True), ext_disabled=False,
            blob_transfers=BlobTransferStore(Path(self.tmp.name)/'uploads'),
            sender=SimpleNamespace(send_download=lambda req: (self.sent.append(req) is None, 'accepted')),
            auth_proxy=AuthenticatedProxyManager(AuthContextVault()), lock=threading.Lock(), downloads_dispatched=0)
        self.server = ReusableThreadingHTTPServer(('127.0.0.1',0), make_http_handler(self.state))
        self.state.cfg.http_port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.cache_patch = patch('idm_linux.auth_proxy.get_cache_dir', lambda **kw: Path(self.tmp.name))
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def post(self, action, payload, origin='chrome-extension://test'):
        conn = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=4)
        body=json.dumps(payload)
        conn.request('POST','/api/blob-transfer/'+action,body,{'Content-Type':'application/json','Origin':origin})
        res=conn.getresponse(); status=res.status; data=json.loads(res.read());conn.close()
        return status,data

    def test_upload_commit_native_proxy_byte_exact(self):
        data=bytes(range(256))*40000
        _, result=self.post('begin',{'filename':'Türkçe.zip','size':len(data)})
        key=result['transferId']
        for offset in range(0,len(data),BlobTransferStore.CHUNK_BYTES):
            _,reply=self.post('chunk',{'transferId':key,'offset':offset,'dataBase64':base64.b64encode(data[offset:offset+BlobTransferStore.CHUNK_BYTES]).decode()})
            self.assertTrue(reply['ok'])
            self.assertEqual(len(self.sent),0)
        _,result=self.post('finish',{'transferId':key})
        self.assertTrue(result['ok']);self.assertTrue(result['takeover'])
        self.assertEqual(len(self.sent),1)
        tid=self.sent[0].url.split('/proxy/',1)[1].split('/',1)[0]
        self.assertEqual(self.state.auth_proxy.get_ticket(tid).blob_file.read_bytes(),data)
        self.assertEqual(list((Path(self.tmp.name)/'uploads').glob('*.part')),[])

    def test_disabled_mid_upload_never_dispatches(self):
        _,r=self.post('begin',{'filename':'x.zip','size':1});key=r['transferId']
        self.state.ext_disabled=True
        _,r=self.post('finish',{'transferId':key})
        self.assertFalse(r['takeover']);self.assertEqual(self.sent,[])
        self.assertEqual(list((Path(self.tmp.name)/'uploads').glob('*.part')),[])

    def test_untrusted_site_is_rejected(self):
        status,_=self.post('begin',{'filename':'x','size':1},'https://example.com')
        self.assertEqual(status,403)
        self.assertEqual(self.sent,[])

    def test_incomplete_upload_cannot_dispatch(self):
        _,r=self.post('begin',{'filename':'x','size':1})
        status,r=self.post('finish',{'transferId':r['transferId']})
        self.assertEqual(status,400);self.assertFalse(r['takeover']);self.assertEqual(self.sent,[])
        for key in list(self.state.blob_transfers._jobs): self.state.blob_transfers.cancel(key)

class FileHostTests(unittest.TestCase):
    def test_host_boundary_and_file_classification(self):
        for url in ['https://mediafire.com/file/a','https://download123.mediafire.com/a/file.blend']:
            self.assertTrue(is_mediafire_url(url))
            self.assertFalse(se._is_known_ytdlp_site(url))
            self.assertTrue(se._never_ytdlp_probe(url))
        self.assertFalse(is_mediafire_url('https://mediafire.com.evil.test/file'))
        self.assertFalse(is_mediafire_url('https://example.com/?mediafire.com/a'))
        self.assertFalse(is_mediafire_direct('https://mediafire.com/download/1'))

    def test_only_public_download_anchor(self):
        url,name=parse_mediafire_download('<a class="x" href="https://download1.mediafire.com/x/file.blend?x=1&amp;y=2" id="downloadButton">Download</a>')
        self.assertEqual(name,'file.blend');self.assertIn('&y=2',url)
        with self.assertRaises(ValueError): parse_mediafire_download('<a id="downloadButton" href="https://evil.test/file.exe">x</a>')
        with self.assertRaises(ValueError): parse_mediafire_download('<p>CAPTCHA required</p>')

    def test_both_browser_sources_and_versions_match(self):
        root=Path(__file__).resolve().parents[1]/'extension'
        for name in ['background.js','content.js','page_hook.js','popup.js']:
            self.assertEqual((root/'chromium'/name).read_bytes(),(root/'firefox'/name).read_bytes())
        for browser in ['chromium','firefox']:
            self.assertEqual(json.loads((root/browser/'manifest.json').read_text())['version'],'1.0.0')

class MediaSourceSpeedTests(unittest.TestCase):
    def test_empty_cache_cannot_hide_first_youtube_source(self):
        from idm_linux.config import IdmLinuxConfig
        engine = se.StreamEngine(IdmLinuxConfig())
        page = 'https://www.youtube.com/watch?v=example'
        engine._probe_cache[page+'|0'] = (time.time(), {'ok': True, 'formats': []})
        result = engine.probe_formats(page, [{'url':'https://r1.googlevideo.com/videoplayback?itag=18&clen=100000&dur=30&expire=9999999999','mime':'video/mp4'}],use_ytdlp=False)
        self.assertTrue(result['formats'])
        self.assertTrue(any(f['id']=='ytq_18' for f in result['formats']))

    def test_bilibili_cookies_not_discarded(self):
        self.assertEqual(se._bili_headers('SESSDATA=authorized-user')['Cookie'],'SESSDATA=authorized-user')
        self.assertNotIn('Cookie',se._bili_headers(''))

    def test_bilibili_whole_dash_file_is_not_segment_counter(self):
        self.assertEqual(se.segment_series_key('https://up.bilivideo.com/upgcxcode/1/2/30080.m4s?deadline=999999'), '')
        self.assertEqual(se.segment_series_key('https://up.hdslb.com/upgcxcode/1/2/30280.m4s'), '')
        self.assertTrue(se.segment_series_key('https://cdn.example.test/video/15.m4s'))

class BoundedHttpTests(unittest.TestCase):
    def test_limit_returns_503_and_releases_slots(self):
        gate=threading.Event(); started=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a): pass
            def do_GET(self):
                started.set();gate.wait(3)
                self.send_response(200);self.send_header('Content-Length','0');self.end_headers()
        class Server(ReusableThreadingHTTPServer): max_request_threads=1
        server=Server(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        first=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=4)
        second=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=4)
        try:
            first.request('GET','/');self.assertTrue(started.wait(2))
            second.request('GET','/');r=second.getresponse();self.assertEqual(r.status,503);r.read()
            gate.set();r=first.getresponse();self.assertEqual(r.status,200);r.read()
            # Thread shutdown releases the semaphore even if a request raises.
            for _ in range(40):
                if server._request_slots.acquire(blocking=False): server._request_slots.release();break
                time.sleep(.01)
            else: self.fail('HTTP worker slot leaked')
        finally:
            gate.set();first.close();second.close();server.shutdown();server.server_close();thread.join(2)


class CompressedManifestModeTests(unittest.TestCase):
    def test_compressed_vod_stays_vod_and_live_stays_live(self):
        import gzip, io, zlib
        from unittest.mock import patch
        from idm_linux.daemon import _auto_hls_mode
        vod=b'#EXTM3U\n#EXTINF:2,\nfirst.ts\n#EXT-X-ENDLIST\n'
        live=b'#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\nfirst.ts\n'
        for plain,expected in ((vod,'vod'),(live,'live')):
            for enc,body in (('gzip',gzip.compress(plain)),('deflate',zlib.compress(plain)),('',gzip.compress(plain))):
                response=io.BytesIO(body);response.headers={'Content-Encoding':enc}
                with self.subTest(encoding=enc,expected=expected),patch('urllib.request.urlopen',return_value=response):
                    self.assertEqual(_auto_hls_mode('https://example.test/master.txt',''),expected)

    def test_gzip_manifest_decode_is_bounded(self):
        import gzip, io
        from unittest.mock import patch
        from idm_linux.daemon import _auto_hls_mode
        response=io.BytesIO(gzip.compress(b'A'*1000000));response.headers={'Content-Encoding':'gzip'}
        with patch('urllib.request.urlopen',return_value=response):
            self.assertEqual(_auto_hls_mode('https://example.test/master.txt',''),'dvr')

if __name__=='__main__': unittest.main(verbosity=2)
