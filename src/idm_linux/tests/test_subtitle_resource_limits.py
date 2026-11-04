"""Offline resource/cancellation regressions; no live-platform claims."""
import gzip
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from idm_linux import hls_streamer as hs
from idm_linux.daemon import _prepare_subtitle_job
from idm_linux.stream_engine import ActiveStreamJob, StreamTicket

VTT = b'WEBVTT\n\n00:00:00.123 --> 00:00:02.456\nReal caption\n'


def playlist(count):
    return '#EXTM3U\n#EXT-X-TARGETDURATION:2\n'+''.join(f'#EXTINF:2,\nseg{i}.vtt\n' for i in range(count))+'#EXT-X-ENDLIST\n'


class SubtitleResourceLimitTests(unittest.TestCase):
    def test_gzip_and_both_deflate_encodings(self):
        for encoded, kind in [(gzip.compress(VTT),'gzip'),(zlib.compress(VTT),'deflate'),(zlib.compress(VTT)[2:-4],'deflate')]:
            with self.subTest(kind=kind):
                self.assertEqual(hs._decode_subtitle_http_body(encoded,kind),VTT)

    def test_concatenated_gzip_members_preserve_all_data(self):
        self.assertEqual(hs._decode_subtitle_http_body(gzip.compress(VTT[:20])+gzip.compress(VTT[20:]),'gzip'),VTT)

    def test_compressed_expansion_is_capped_before_full_allocation(self):
        for encoded, kind in [(gzip.compress(b'A'*1000000),'gzip'),(zlib.compress(b'A'*1000000),'deflate')]:
            with self.subTest(kind=kind), self.assertRaises(hs.SubtitleBodyLimitError):
                hs._decode_subtitle_http_body(encoded,kind,limit=1024)

    def test_truncated_gzip_is_probe_prefix_only_not_download_success(self):
        prefix=gzip.compress(VTT)[:-8]
        self.assertEqual(hs._decode_subtitle_http_body(prefix,'gzip',allow_prefix=True),VTT)
        with self.assertRaises(ValueError):hs._decode_subtitle_http_body(prefix,'gzip')

    def test_invalid_gzip_is_not_fallback_plain_caption(self):
        with self.assertRaises(ValueError):hs._decode_subtitle_http_body(VTT,'gzip')

    def test_real_http_compression_and_truncated_content_length(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                body=gzip.compress(VTT) if self.path=='/gzip' else VTT
                self.send_response(200)
                self.send_header('Content-Length',str(len(body)+(50 if self.path=='/truncated' else 0)))
                if self.path=='/gzip':self.send_header('Content-Encoding','gzip')
                self.end_headers();self.wfile.write(body);self.close_connection=True
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            self.assertEqual(hs.fetch_subtitle_bytes_smart(base+'/gzip',{}),VTT)
            self.assertEqual(hs.fetch_subtitle_probe(base+'/gzip',{}),('ok',0,'vtt'))
            with self.assertRaisesRegex(ValueError,'eksik'):hs._fetch_subtitle_http_bytes(base+'/truncated',{})
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_timed_out_real_job_is_failed_and_not_left_active(self):
        with tempfile.TemporaryDirectory() as folder:
            job=ActiveStreamJob(StreamTicket(ticket_id='preflight-timeout',source_url='https://example.test/sub',filename='qa.vtt',mode='subs'),Path(folder))
            with patch.object(job,'wait_complete',return_value=False):self.assertFalse(_prepare_subtitle_job(job))
            self.assertTrue(job.stop_event.is_set());self.assertTrue(job.failed);self.assertFalse(job.completed)

    def test_encoded_body_limit(self):
        with self.assertRaises(hs.SubtitleBodyLimitError):hs._decode_subtitle_http_body(VTT,limit=10)

    def test_cancelled_http_does_not_open_connection(self):
        stop=threading.Event();stop.set()
        with patch.object(hs.urllib.request,'urlopen') as opener,self.assertRaisesRegex(RuntimeError,'iptal'):
            hs._fetch_subtitle_http_bytes('https://example.test/en.vtt',{},stop_event=stop)
        opener.assert_not_called()

    def test_trickle_response_cannot_reset_total_deadline(self):
        class Response:
            headers={}
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self,n):raise AssertionError('read1 must be used')
            def read1(self,n):time.sleep(.02);return b'x'
        start=time.monotonic()
        with patch.object(hs.urllib.request,'urlopen',return_value=Response()),self.assertRaises(TimeoutError):
            hs._fetch_subtitle_http_bytes('https://example.test/en.vtt',{},timeout=.055)
        self.assertLess(time.monotonic()-start,.3)

    def test_hls_stalled_worker_does_not_hold_caller_past_budget(self):
        release=threading.Event()
        def stalled(*args,**kwargs):release.wait(2);return VTT
        start=time.monotonic()
        try:
            with patch.object(hs,'_fetch_subtitle_http_bytes',side_effect=stalled),self.assertRaises(TimeoutError):
                hs.assemble_subtitle_text('https://example.test/master',{},initial_text=playlist(100),timeout=.06,concurrency=2)
            self.assertLess(time.monotonic()-start,.4)
        finally:release.set()

    def test_failed_hls_does_not_schedule_all_remaining_segments(self):
        release=threading.Event();calls=[]
        def fetch(url,*args,**kwargs):
            calls.append(url)
            if url.endswith('seg0.vtt'):raise RuntimeError('missing')
            release.wait(2);return VTT
        try:
            with patch.object(hs,'_fetch_subtitle_http_bytes',side_effect=fetch),self.assertRaisesRegex(RuntimeError,'eksik'):
                hs.assemble_subtitle_text('https://example.test/master',{},initial_text=playlist(500),concurrency=2)
            self.assertLessEqual(len(calls),2)
        finally:release.set()

    def test_hls_parallel_fetch_preserves_playlist_order(self):
        def fetch(url,*args,**kwargs):
            pos=int(url.rsplit('seg',1)[1].split('.')[0])
            if pos==0:time.sleep(.02)
            return VTT.replace(b'Real caption',f'Caption {pos}'.encode())
        with patch.object(hs,'_fetch_subtitle_http_bytes',side_effect=fetch):
            text=hs.assemble_subtitle_text('https://example.test/master',{},initial_text=playlist(3),concurrency=2)
        self.assertLess(text.index('Caption 0'),text.index('Caption 1'));self.assertLess(text.index('Caption 1'),text.index('Caption 2'))

    def test_hls_aggregate_bytes_are_capped(self):
        with patch.object(hs,'_SUB_BODY_CAP',len(playlist(3).encode())+1),patch.object(hs,'_fetch_subtitle_http_bytes',return_value=VTT),self.assertRaises(hs.SubtitleBodyLimitError):
            hs.assemble_subtitle_text('https://example.test/master',{},initial_text=playlist(3))

    def test_cancelled_hls_never_starts_segment_requests(self):
        stop=threading.Event();stop.set()
        with patch.object(hs,'_fetch_subtitle_http_bytes') as fetch,self.assertRaisesRegex(RuntimeError,'iptal'):
            hs.assemble_subtitle_text('https://example.test/master',{},initial_text=playlist(3),stop_event=stop)
        fetch.assert_not_called()

    def test_preflight_timeout_or_empty_or_failed_stops_abandoned_job(self):
        for complete,failed,size in [(False,False,0),(True,True,100),(True,False,0)]:
            job=SimpleNamespace(wait_complete=Mock(return_value=complete),failed=failed,final_size=size,stop=Mock())
            self.assertFalse(_prepare_subtitle_job(job,timeout=.1));job.stop.assert_called_once_with()

    def test_ready_preflight_does_not_stop_successful_job(self):
        job=SimpleNamespace(wait_complete=Mock(return_value=True),failed=False,final_size=100,stop=Mock())
        self.assertTrue(_prepare_subtitle_job(job));job.stop.assert_not_called();self.assertFalse(_prepare_subtitle_job(None))

    def test_cancel_during_preflight_exception_stops_job(self):
        job=SimpleNamespace(wait_complete=Mock(side_effect=RuntimeError('broken')),stop=Mock())
        with self.assertRaises(RuntimeError):_prepare_subtitle_job(job)
        job.stop.assert_called_once_with()

    def test_late_subtitle_result_cannot_publish_after_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            job=ActiveStreamJob(StreamTicket(ticket_id='cancelled',source_url='https://example.test/sub',filename='qa.vtt',mode='subs'),Path(folder))
            def finish(*args,**kwargs):job.stop_event.set();return VTT.decode()
            with patch.object(hs,'assemble_subtitle_text',side_effect=finish):
                self.assertFalse(job._run_subtitle_record())
            self.assertIn('iptal',job.error_msg)
            self.assertFalse(job.completed);self.assertFalse(job.output_file.exists())


if __name__=='__main__':unittest.main()
