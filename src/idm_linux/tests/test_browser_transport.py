"""Security, isolation and fail-closed browser transport regressions (no Internet)."""
import base64
import concurrent.futures
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from idm_linux.browser_transport import BrowserFetchBroker, BrowserHeaders, BrowserTransportError, public_http_url
from idm_linux import hls_streamer as hs
from idm_linux import stream_engine as se

ORIGIN = 'chrome-extension://test-extension'


class BrowserTransportTests(unittest.TestCase):
    def setUp(self):
        self.broker = BrowserFetchBroker()
        self.token = self.broker.register(ORIGIN)
        self.transport = self.broker.transport(self.token, ORIGIN)
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.addCleanup(lambda: self.pool.shutdown(wait=True))
        self.addCleanup(lambda: self.broker.revoke(self.token))

    def pending(self):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            result = self.broker.poll(self.token, ORIGIN)
            if result['pending']:
                return result['pending'][0]
            time.sleep(0.005)
        self.fail('No pending request')

    def fetch_async(self, **kwargs):
        return self.pool.submit(self.broker.fetch, self.token, 'https://media.example/segment.ts', {'Cookie': 'DO-NOT-EXPORT', 'Authorization': 'private', 'Range': 'bytes=0-3'}, **kwargs)

    def complete(self, req, data=b'test'):
        self.broker.submit(self.token, ORIGIN, req['id'], 'meta', {'status': 206, 'contentRange': 'bytes 0-3/4'})
        self.broker.submit(self.token, ORIGIN, req['id'], 'chunk', {'offset': 0, 'data': base64.b64encode(data).decode()})
        self.broker.submit(self.token, ORIGIN, req['id'], 'done', {'ok': True})

    def test_only_extension_origin_can_register(self):
        for origin in ['', 'https://evil.example', 'http://127.0.0.1:17802']:
            with self.assertRaises(BrowserTransportError):
                self.broker.register(origin)

    def test_private_local_and_non_http_sources_are_rejected(self):
        for url in ['file:///etc/passwd', 'http://127.0.0.1/a', 'http://10.1.2.3/a', 'http://[::1]/a', 'https://localhost/a', 'https://host.local/a', 'https://user:secret@example.org/a']:
            with self.subTest(url=url), self.assertRaises(BrowserTransportError):
                public_http_url(url)

    def test_public_sources_allowed(self):
        self.assertEqual(public_http_url('https://media.example/a'), 'https://media.example/a')

    def test_other_origin_cannot_take_over_client(self):
        with self.assertRaises(BrowserTransportError):
            self.broker.poll(self.token, 'chrome-extension://other')

    def test_headers_do_not_export_auth_or_cookie(self):
        future = self.fetch_async()
        req = self.pending()
        self.assertEqual(req['headers'], {'Range': 'bytes=0-3'})
        self.complete(req)
        self.assertEqual(future.result(timeout=2).data, b'test')

    def test_request_delivered_exactly_once(self):
        future = self.fetch_async()
        req = self.pending()
        self.assertFalse(self.broker.poll(self.token, ORIGIN)['pending'])
        self.complete(req)
        self.assertEqual(future.result(timeout=2).status, 206)
        self.assertFalse(self.broker._requests)

    def test_client_isolation(self):
        other = self.broker.register(ORIGIN)
        future = self.fetch_async()
        req = self.pending()
        self.assertFalse(self.broker.poll(other, ORIGIN)['pending'])
        with self.assertRaises(BrowserTransportError):
            self.broker.submit(other, ORIGIN, req['id'], 'done', {'ok': True})
        self.complete(req)
        future.result(timeout=2)

    def test_chunk_order_is_checked(self):
        future = self.fetch_async()
        req = self.pending()
        self.broker.submit(self.token, ORIGIN, req['id'], 'meta', {'status': 200})
        with self.assertRaises(BrowserTransportError):
            self.broker.submit(self.token, ORIGIN, req['id'], 'chunk', {'offset': 5, 'data': 'eA=='})
        self.broker.revoke(self.token)
        with self.assertRaises(BrowserTransportError):
            future.result(timeout=2)

    def test_malformed_base64_is_rejected(self):
        future = self.fetch_async(); req = self.pending()
        self.broker.submit(self.token, ORIGIN, req['id'], 'meta', {'status': 200})
        with self.assertRaises(BrowserTransportError):
            self.broker.submit(self.token, ORIGIN, req['id'], 'chunk', {'offset': 0, 'data': '%%%invalid'})
        self.broker.revoke(self.token)
        with self.assertRaises(BrowserTransportError): future.result(timeout=2)

    def test_size_limit_is_checked(self):
        future = self.fetch_async(limit=2); req = self.pending()
        with self.assertRaises(BrowserTransportError): self.complete(req)
        self.broker.revoke(self.token)
        with self.assertRaises(BrowserTransportError): future.result(timeout=2)

    def test_browser_failure_poison_session_not_direct_fallback(self):
        future = self.fetch_async(); req = self.pending()
        self.broker.submit(self.token, ORIGIN, req['id'], 'done', {'ok': False})
        with self.assertRaises(BrowserTransportError): future.result(timeout=2)
        with self.assertRaises(BrowserTransportError): self.transport.assert_healthy()

    def test_closed_browser_lease_fails(self):
        self.broker._clients[self.token]['seen'] -= 20
        with self.assertRaises(BrowserTransportError): self.transport.fetch('https://media.example/a', {})

    def test_ip_change_revokes_pending_request(self):
        token = self.broker.register(ORIGIN, 'a' * 64)
        future = self.pool.submit(self.broker.fetch, token, 'https://media.example/a', {})
        time.sleep(0.02)
        with self.assertRaises(BrowserTransportError): self.broker.poll(token, ORIGIN, 'b' * 64)
        with self.assertRaises(BrowserTransportError): future.result(timeout=2)

    def test_pause_cancels_wait_and_cleans_queue(self):
        stop = threading.Event(); future = self.fetch_async(stop_event=stop)
        self.pending(); stop.set()
        with self.assertRaises(BrowserTransportError): future.result(timeout=2)
        self.assertFalse(self.broker._requests)

    def test_browser_headers_survive_parallel_copies(self):
        headers = BrowserHeaders({'Accept': '*/*'}, self.transport)
        self.assertIs(headers.copy().transport, self.transport)
        with patch.object(self.transport, 'fetch', return_value=b'abc') as browser, patch.object(hs.urllib.request, 'urlopen', side_effect=AssertionError('Direct networking forbidden')):
            self.assertEqual(hs.fetch_url_bytes('https://media.example/a', headers.copy()), b'abc')
        browser.assert_called_once()

    def test_worker_never_enters_ordinary_engines_on_browser_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = se.ActiveStreamJob(se.StreamTicket('browser', 'https://media.example/a', 'a.mp4', 'hls_native', browser_transport=self.transport), Path(tmp))
            with patch.object(job, '_run_native_parallel_hls', side_effect=BrowserTransportError('offline')), patch.object(job, '_run_ytdlp_record_resilient') as fallback, patch.object(job, '_run_streamlink_record') as alternate:
                job._run_worker()
            self.assertTrue(job.failed)
            self.assertFalse(job.completed)
            fallback.assert_not_called(); alternate.assert_not_called()

    def test_revoked_transport_cannot_finalize_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = se.ActiveStreamJob(se.StreamTicket('browser', 'https://media.example/a', 'a.mp4', 'browser_mux', browser_transport=self.transport), Path(tmp))
            self.broker.revoke(self.token)
            with self.assertRaises(BrowserTransportError): job.completed = True
            self.assertFalse(job.completed)

    def test_sources_are_unguessable_and_revoked_with_client(self):
        self.transport.local_base = 'http://127.0.0.1:17802'
        url = self.transport.source_url('https://media.example/a')
        key = url.rsplit('/', 1)[-1]
        self.assertEqual(len(key), 40)
        self.assertEqual(self.broker.source(key)[0], self.token)
        self.transport.close()
        with self.assertRaises(BrowserTransportError): self.broker.source(key)

    def test_repeated_completed_sessions_do_not_exhaust_limit(self):
        for _ in range(20):
            token = self.broker.register(ORIGIN)
            self.broker.revoke(token)
        self.assertLess(len(self.broker._clients), self.broker.MAX_CLIENTS)


if __name__ == '__main__':
    unittest.main(verbosity=2)
