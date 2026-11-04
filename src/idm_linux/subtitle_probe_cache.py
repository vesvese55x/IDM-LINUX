"""Bounded, non-blocking subtitle checks. No media or browser/VPN transport.

Workers are daemon threads: a broken DNS lookup must not hold up bridge shutdown.
Signed URL and frame/header context are part of identity, but never logged.
"""
from collections import OrderedDict
import hashlib
import json
import queue
import threading
import time


class SubtitleProbeCache:
    def __init__(self, probe=None, workers=4, capacity=300):
        self.probe = probe
        self.workers = max(1, min(8, workers))
        self.capacity = max(self.workers, capacity)
        self.entries = OrderedDict()
        self.queue = queue.Queue(maxsize=self.capacity)
        self.lock = threading.Lock()
        self.started = False
        self.live_workers = 0

    def get(self, url, headers):
        identity = json.dumps([url, sorted((str(k).lower(), str(v)) for k, v in headers.items())])
        key = hashlib.sha256(identity.encode()).digest()
        now = time.monotonic()
        with self.lock:
            prev = self.entries.get(key)
            if prev and (prev[0] == 'checking' or now < prev[3]):
                self.entries.move_to_end(key)
                return prev[:3]
            # Never evict an in-flight request: repeated UI polls must not enqueue duplicates.
            if len(self.entries) >= self.capacity and key not in self.entries:
                victim = next((k for k, v in self.entries.items() if v[0] != 'checking'), None)
                if victim is None:
                    return ('deferred', 0, '')
                self.entries.pop(victim)
            self.entries[key] = ('checking', 0, '', now + 120)
            try:
                self.queue.put_nowait((key, url, dict(headers)))
            except queue.Full:
                self.entries.pop(key, None)
                return ('deferred', 0, '')
            if not self.started:
                self.started = True
                self.live_workers = self.workers
                for i in range(self.workers):
                    threading.Thread(target=self._work, name=f'subtitle-probe-{i}', daemon=True).start()
            return ('checking', 0, '')

    def _work(self):
        while True:
            try:
                key, url, headers = self.queue.get(timeout=15)
            except queue.Empty:
                with self.lock:
                    if not self.queue.empty():
                        continue
                    self.live_workers -= 1
                    if not self.live_workers:
                        self.started = False
                return
            try:
                if self.probe is None:
                    from .hls_streamer import fetch_subtitle_probe
                    result = fetch_subtitle_probe(url, headers, 3.0)
                else:
                    result = self.probe(url, headers, 3.0)
                if result[0] not in ('ok', 'bad', 'unknown'):
                    result = ('unknown', 0, '')
            except Exception:
                result = ('unknown', 0, '')
            with self.lock:
                self.entries[key] = (*result, time.monotonic() + (120 if result[0] == 'ok' else 20))
            self.queue.task_done()
