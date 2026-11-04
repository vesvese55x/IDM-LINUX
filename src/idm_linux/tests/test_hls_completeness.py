"""HLS must not turn an upstream segment failure into successful EOF."""
import io
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from idm_linux import hls_streamer as hs
from idm_linux import stream_engine as se


class HlsCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = se.ActiveStreamJob(se.StreamTicket(ticket_id='test-hls', source_url='https://media.example/video.m3u8', filename='movie.mp4', mode='hls_native'), self.root)

    @staticmethod
    def interrupted():
        yield b'x' * 4096
        raise RuntimeError('upstream segment failed')

    def test_partial_vod_is_never_completed(self):
        with patch.object(se, 'stream_hls_as_mp4', side_effect=lambda **_: self.interrupted()):
            with self.assertRaisesRegex(RuntimeError, 'eksik kaldı'):
                self.job._run_native_parallel_hls(self.job.ticket.source_url)
        self.assertFalse(self.job.completed)
        self.assertFalse(self.job.output_file.exists())
        self.assertEqual(self.job.stream_file.stat().st_size, 4096)

    def test_worker_does_not_fallback_over_partially_delivered_bytes(self):
        fallback = Mock()
        with patch.object(se, 'find_ytdlp', return_value=None), patch.object(se, 'engine_attempt_order', return_value=['hls_native', 'ytdlp']), patch.object(se, 'stream_hls_as_mp4', side_effect=lambda **_: self.interrupted()), patch.object(self.job, '_run_ytdlp_record_resilient', fallback), patch.object(self.job, '_is_plain_media_relay', return_value=False):
            self.job._run_worker()
        self.assertTrue(self.job.failed)
        self.assertFalse(self.job.completed)
        fallback.assert_not_called()

    def test_cancellation_does_not_finalize_partial_file(self):
        def interrupted(**_):
            yield b'x' * 4096
            self.job.stop_event.set()
        with patch.object(se, 'stream_hls_as_mp4', side_effect=interrupted):
            self.assertFalse(self.job._run_native_parallel_hls(self.job.ticket.source_url))
        self.assertFalse(self.job.completed)
        self.assertTrue(self.job.stream_file.exists())

    def test_failed_archive_is_named_partial_and_existing_files_survive(self):
        self.job.stream_file.write_bytes(b'x' * 131072)
        self.job.failed = True
        self.job.final_dir = self.root / 'downloads'
        self.job._safe_archive_final_file()
        self.job._safe_archive_final_file()
        self.assertFalse((self.job.final_dir / 'movie.mp4').exists())
        self.assertEqual((self.job.final_dir / 'movie.partial.mp4').stat().st_size, 131072)
        self.assertEqual((self.job.final_dir / 'movie.partial_kayit1.mp4').stat().st_size, 131072)

    def test_clean_full_stream_finalizes(self):
        with patch.object(se, 'stream_hls_as_mp4', return_value=iter([b'x' * 4096, b'y' * 4096])):
            self.assertTrue(self.job._run_native_parallel_hls(self.job.ticket.source_url))
        self.assertTrue(self.job.completed)
        self.assertEqual(self.job.final_size, 8192)

    def test_ffmpeg_success_cannot_hide_feeder_exception(self):
        def segments(*_, **__):
            yield b'G' * 4096
            raise RuntimeError('missing segment')
        rd, wr = os.pipe()
        os.write(wr, b'X' * 4096)
        os.close(wr)
        stdout = os.fdopen(rd, 'rb')
        process = SimpleNamespace(stdin=io.BytesIO(), stdout=stdout, wait=lambda **_: 0, poll=lambda: 0)
        with patch.object(hs, 'resolve_media_playlists', return_value=('https://example/a', '', None, None)), patch.object(hs, 'iter_playlist_segments_smart', side_effect=segments), patch.object(hs.shutil, 'which', return_value='/ffmpeg'), patch.object(hs, '_needs_aac_adtstoasc', return_value=False), patch.object(hs.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'yarıda kesildi'):
                list(hs.stream_hls_as_mp4('https://example/a'))

    def test_nonzero_ffmpeg_exit_is_not_success(self):
        rd, wr = os.pipe()
        os.write(wr, b'X' * 4096)
        os.close(wr)
        process = SimpleNamespace(stdin=io.BytesIO(), stdout=os.fdopen(rd, 'rb'), wait=lambda **_: 1, poll=lambda: 1)
        with patch.object(hs, 'resolve_media_playlists', return_value=('https://example/a', '', None, None)), patch.object(hs, 'iter_playlist_segments_smart', return_value=iter([b'G' * 4096])), patch.object(hs.shutil, 'which', return_value='/ffmpeg'), patch.object(hs, '_needs_aac_adtstoasc', return_value=False), patch.object(hs.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'hata ile kapandı'):
                list(hs.stream_hls_as_mp4('https://example/a'))

    def test_html_and_empty_segments_are_rejected(self):
        body = '#EXTM3U\n#EXTINF:1,\nseg.ts\n#EXT-X-ENDLIST\n'
        for payload in [b'', b'<!doctype html><html>Access denied</html>']:
            with patch.object(hs, 'fetch_url_bytes', return_value=payload), patch.object(hs.time, 'sleep'):
                with self.assertRaisesRegex(RuntimeError, 'segmenti boş'):
                    list(hs._iter_playlist_segments_parallel('https://example/video.m3u8', body, {}))

    def test_captured_8192_prefix_refetches_complete_vod(self):
        full = '#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n' + ''.join('#EXTINF:10,\n' + ('x' * 100) + str(i) + '.ts\n' for i in range(564)) + '#EXT-X-ENDLIST\n'
        prefix = full[:8192]
        self.assertNotIn('#EXT-X-ENDLIST', prefix)
        with patch.object(hs, 'fetch_url_bytes', return_value=full.encode()) as fetch:
            _, body, _, _ = hs.resolve_media_playlists('https://example/video', {}, initial_manifest_text=prefix)
        self.assertEqual(body.count('#EXTINF:'), 564)
        self.assertIn('#EXT-X-ENDLIST', body)
        fetch.assert_called_once()

    def test_complete_captured_vod_remains_usable_without_network(self):
        body = '#EXTM3U\n#EXTINF:10,\nseg.ts\n#EXT-X-ENDLIST\n'
        with patch.object(hs, 'fetch_url_bytes') as fetch:
            _, result, _, _ = hs.resolve_media_playlists('https://example/video', {}, initial_manifest_text=body)
        self.assertEqual(result, body)
        fetch.assert_not_called()

    def test_failed_refresh_never_uses_captured_partial_vod(self):
        prefix = '#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:10,\nseg.ts\n'
        with patch.object(hs, 'fetch_url_bytes', side_effect=RuntimeError('unreachable')):
            with self.assertRaisesRegex(RuntimeError, 'unreachable'):
                hs.resolve_media_playlists('https://example/video', {}, initial_manifest_text=prefix)

    def test_unfinished_vod_cannot_be_downloaded_as_complete_file(self):
        body = '#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:10,\nseg.ts\n'
        with self.assertRaisesRegex(RuntimeError, 'ENDLIST yok'):
            list(hs.iter_playlist_segments_smart('https://example/video', body, {}, hls_mode='vod'))

    def test_live_refetch_exhaustion_is_not_end_of_broadcast(self):
        body = '#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\na.ts\n'
        with patch.object(hs, 'fetch_url_bytes', side_effect=[b'G' * 4096, RuntimeError('network')]), patch.object(hs.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'yayın sonu doğrulanmadı'):
                list(hs.iter_playlist_segments_smart('https://example/live.m3u8', body, {}, hls_mode='live', max_refetch_fail=1))

    def test_http_live_and_finished_range_account_delivered_bytes(self):
        import urllib.request
        from idm_linux.daemon import make_http_handler, ReusableThreadingHTTPServer
        body = b'x' * 4096
        # Content-Length lets the client finish before the server's post-write
        # accounting. Synchronize with that operation instead of racing its thread.
        range_accounted = threading.Event()
        original_add_served = self.job.add_served
        def account(n):
            original_add_served(n)
            if self.job.served_bytes >= 4196:
                range_accounted.set()
        self.job.add_served = account
        self.job.ensure_started = Mock()
        self.job.restart_for_resume = Mock(return_value=True)
        self.job.client_disconnected = Mock()
        def chunks(offset=0):
            yield body[:2048]
            yield body[2048:]
            self.job.output_file.write_bytes(body)
            self.job.completed = True
        self.job.iter_bytes_from = chunks
        engine = SimpleNamespace(get_ticket=lambda _: self.job.ticket, get_job=lambda _: self.job)
        cfg = SimpleNamespace(http_port=0)
        state = SimpleNamespace(stream_engine=engine, cfg=cfg)
        server = ReusableThreadingHTTPServer(('127.0.0.1', 0), make_http_handler(state))
        cfg.http_port = server.server_port
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/stream/test-hls/movie.mp4'
            with urllib.request.urlopen(url, timeout=5) as response:
                self.assertEqual(response.read(), body)
            self.assertEqual(self.job.served_bytes, 4096)
            request = urllib.request.Request(url, headers={'Range': 'bytes=100-199'})
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(len(response.read()), 100)
            self.assertTrue(range_accounted.wait(2), "Range delivery accounting did not finish")
            self.assertEqual(self.job.served_bytes, 4196)
        finally:
            server.shutdown()
            server.server_close()


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Real FFmpeg/ffprobe required')
class RealHlsCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        result = subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '4', '-c:v', 'libx264', '-preset', 'ultrafast', '-g', '10', '-sc_threshold', '0', '-c:a', 'aac', '-f', 'hls', '-hls_time', '1', '-hls_list_size', '0', '-hls_segment_filename', str(self.root / 'seg%d.ts'), str(self.root / 'video.m3u8')], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0)
        self.failures_left = 0
        self.always_fail = False
        self.failed_requests = 0
        parent = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                if self.path == '/seg2.ts' and (parent.always_fail or parent.failures_left > 0):
                    parent.failures_left -= 1
                    parent.failed_requests += 1
                    self.send_response(503)
                    self.end_headers()
                    return
                path = parent.root / self.path.lstrip('/')
                if not path.is_file():
                    self.send_response(404)
                    self.end_headers()
                    return
                data = path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = 'http://127.0.0.1:%s/video.m3u8' % self.server.server_port

    def test_transient_segment_failure_recovers_and_downloads_full_duration(self):
        self.failures_left = 2
        data = b''.join(hs.stream_hls_as_mp4(self.url))
        target = self.root / 'full.mp4'
        target.write_bytes(data)
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(target)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertGreaterEqual(float(result.stdout.strip()), 3.9)
        self.assertEqual(self.failed_requests, 2)

    def test_browser_clipped_manifest_still_downloads_entire_video(self):
        full = (self.root / 'video.m3u8').read_text()
        prefix = full[:full.index('seg2.ts')]
        data = b''.join(hs.stream_hls_as_mp4(self.url, initial_manifest_text=prefix))
        target = self.root / 'refreshed-full.mp4'
        target.write_bytes(data)
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(target)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertGreaterEqual(float(result.stdout.strip()), 3.9)

    def test_permanent_segment_failure_is_reported_even_with_partial_output(self):
        self.always_fail = True
        chunks = []
        with patch.object(hs.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'yarıda kesildi'):
                for chunk in hs.stream_hls_as_mp4(self.url):
                    chunks.append(chunk)
        self.assertGreater(len(b''.join(chunks)), 1024)
        self.assertGreaterEqual(self.failed_requests, 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
