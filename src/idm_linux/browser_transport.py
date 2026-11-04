"""Bounded, capability-scoped browser network transport. Never opens upstream sockets.

A selected extension/frame supplies bytes; an expired browser lease is a hard
failure, never permission to fall back to urllib/FFmpeg's normal Internet route.
"""
from __future__ import annotations

import base64
import ipaddress
import re
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional


class BrowserTransportError(RuntimeError):
    pass


def public_http_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 12000:
        raise BrowserTransportError('Geçersiz tarayıcı kaynak adresi.')
    p = urllib.parse.urlsplit(value)
    host = (p.hostname or '').lower().rstrip('.')
    if p.scheme not in ('https', 'http') or not host or p.username or p.password:
        raise BrowserTransportError('Yalnız HTTP(S) medya adresi desteklenir.')
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
        raise BrowserTransportError('Yerel/özel ağ adresleri tarayıcı aktarımına alınmaz.')
    try:
        if not ipaddress.ip_address(host).is_global:
            raise BrowserTransportError('Yerel/özel IP adresi aktarımına izin verilmedi.')
    except ValueError:
        pass
    return value


@dataclass
class BrowserResponse:
    data: bytes
    status: int
    content_range: str = ''
    content_type: str = ''


@dataclass
class _Request:
    client: str
    url: str
    headers: dict
    limit: int
    born: float
    event: threading.Event = field(default_factory=threading.Event)
    claimed: bool = False
    data: bytearray = field(default_factory=bytearray)
    status: int = 0
    content_range: str = ''
    content_type: str = ''
    error: str = ''
    metadata: bool = False


class BrowserFetchBroker:
    LEASE = 15.0
    MAX_BYTES = 8 * 1024 * 1024
    MAX_CLIENTS = 8
    MAX_REQUESTS = 32

    def __init__(self):
        self._lock = threading.RLock()
        self._clients = {}
        self._requests = {}
        self._sources = {}

    def register(self, origin: str, route_hash: str = '') -> str:
        if not origin.startswith(('chrome-extension://', 'moz-extension://')):
            raise BrowserTransportError('Tarayıcı aktarımı yalnız eklenti bağlamından başlatılabilir.')
        if route_hash and not re.fullmatch(r'[a-f0-9]{64}', route_hash):
            raise BrowserTransportError('Geçersiz çıkış doğrulaması.')
        with self._lock:
            self._prune()
            if len(self._clients) >= self.MAX_CLIENTS:
                raise BrowserTransportError('Çok fazla tarayıcı aktarımı açık.')
            token = secrets.token_hex(24)
            self._clients[token] = {'origin': origin, 'seen': time.monotonic(), 'route': route_hash, 'error': ''}
            return token

    def _prune(self):
        for token, client in list(self._clients.items()):
            if time.monotonic() - client['seen'] > 90 or (client['error'] and not any(r.client == token for r in self._requests.values())):
                self.revoke(token, 'Tarayıcı bağlantısının süresi doldu.')
                self._clients.pop(token, None)

    def _client(self, token, origin=None):
        client = self._clients.get(token)
        if not client or (origin is not None and client['origin'] != origin):
            raise BrowserTransportError('Tarayıcı oturumu bulunamadı veya yetkisiz.')
        if client['error']:
            raise BrowserTransportError(client['error'])
        if time.monotonic() - client['seen'] > self.LEASE:
            self.revoke(token, 'Tarayıcı/eklenti bağlantısı kesildi; doğrudan ağa geçilmedi.')
            raise BrowserTransportError('Tarayıcı bağlantısı kesildi; indirmeyi yeniden başlatın.')
        return client

    def transport(self, token: str, origin: str):
        with self._lock:
            self._client(token, origin)
        return BrowserTransport(self, token)

    def poll(self, token, origin, route_hash=''):
        with self._lock:
            client = self._client(token, origin)
            if client['route'] and not secrets.compare_digest(client['route'], route_hash):
                self.revoke(token, 'Tarayıcı çıkışı değişti; aktarım güvenli biçimde durduruldu.')
                raise BrowserTransportError('Tarayıcı çıkışı değişti.')
            client['seen'] = time.monotonic()
            pending = []
            active = []
            for key, req in self._requests.items():
                if req.client != token or req.event.is_set():
                    continue
                active.append(key)
                if not req.claimed and len(pending) < 4:
                    req.claimed = True
                    pending.append({'id': key, 'url': req.url, 'headers': req.headers, 'limit': req.limit})
            return {'pending': pending, 'active': active}

    def revoke(self, token, reason='Tarayıcı aktarımı kapatıldı.'):
        with self._lock:
            client = self._clients.get(token)
            if client:
                client['error'] = reason
            for req in self._requests.values():
                if req.client == token and not req.event.is_set():
                    req.error = reason
                    req.event.set()
            for key, source in list(self._sources.items()):
                if source[0] == token:
                    self._sources.pop(key, None)

    def submit(self, token, origin, key, action, payload):
        with self._lock:
            self._client(token, origin)
            req = self._requests.get(key)
            if not req or req.client != token or req.event.is_set():
                raise BrowserTransportError('İstek kapandı veya başka oturuma ait.')
            if action == 'meta':
                status = int(payload.get('status', 0))
                if req.metadata or status not in (200, 206):
                    raise BrowserTransportError('Medya HTTP yanıtı kabul edilmedi.')
                req.status = status
                req.content_range = str(payload.get('contentRange', ''))[:160]
                req.content_type = str(payload.get('contentType', ''))[:160]
                req.metadata = True
            elif action == 'chunk':
                if not req.metadata:
                    raise BrowserTransportError('Medya başlıkları gelmedi.')
                encoded = payload.get('data', '')
                if not isinstance(encoded, str) or len(encoded) > 524288:
                    raise BrowserTransportError('Aktarım parçası sınırı aşıldı.')
                try:
                    data = base64.b64decode(encoded, validate=True)
                except (ValueError, TypeError) as exc:
                    raise BrowserTransportError('Geçersiz aktarım verisi.') from exc
                if payload.get('offset') != len(req.data) or len(req.data) + len(data) > req.limit:
                    raise BrowserTransportError('Aktarım sırası/boyutu geçersiz.')
                if sum(len(item.data) for item in self._requests.values()) + len(data) > 64 * 1024 * 1024:
                    raise BrowserTransportError('Tarayıcı aktarım belleği sınırı aşıldı.')
                req.data.extend(data)
            elif action == 'done':
                if not payload.get('ok') or not req.metadata:
                    req.error = 'Tarayıcı isteği başarısız/iptal edildi; doğrudan bağlantı denenmedi.'
                req.event.set()
            else:
                raise BrowserTransportError('Geçersiz aktarım işlemi.')

    def fetch(self, token, url, headers, timeout=30, limit=None, stop_event=None):
        url = public_http_url(url)
        safe = {k: str(v) for k, v in headers.items() if k.lower() in ('range', 'accept')}
        limit = min(int(limit or self.MAX_BYTES), self.MAX_BYTES)
        with self._lock:
            self._client(token)
            if len(self._requests) >= self.MAX_REQUESTS:
                raise BrowserTransportError('Tarayıcı aktarım kuyruğu dolu.')
            key = secrets.token_hex(16)
            req = _Request(token, url, safe, limit, time.monotonic())
            self._requests[key] = req
        try:
            deadline = time.monotonic() + max(5, min(timeout, 60))
            while not req.event.wait(0.2):
                if stop_event is not None and stop_event.is_set():
                    raise BrowserTransportError('Tarayıcı aktarımı duraklatıldı/iptal edildi.')
                with self._lock:
                    self._client(token)
                if time.monotonic() > deadline:
                    raise BrowserTransportError('Tarayıcı yanıt zaman sınırı aşıldı.')
            if req.error:
                raise BrowserTransportError(req.error)
            return BrowserResponse(bytes(req.data), req.status, req.content_range, req.content_type)
        except BrowserTransportError:
            self.revoke(token, 'Tarayıcı aktarımı kesildi; doğrudan bağlantıya geçilmedi.')
            raise
        finally:
            with self._lock:
                self._requests.pop(key, None)

    def add_source(self, token, url, headers):
        public_http_url(url)
        with self._lock:
            self._client(token)
            if len(self._sources) >= 32:
                raise BrowserTransportError('Tarayıcı kaynak sınırı aşıldı.')
            key = secrets.token_hex(20)
            self._sources[key] = (token, url, dict(headers))
            return key

    def source(self, key):
        with self._lock:
            source = self._sources.get(key)
            if not source:
                raise BrowserTransportError('Tarayıcı kaynağı kapatıldı.')
            self._client(source[0])
            return source


class BrowserTransport:
    def __init__(self, broker, token):
        self.broker, self.token = broker, token
        self.stop_event = None
        self.local_base = ''

    def fetch_response(self, url, headers, timeout=30, limit=None):
        return self.broker.fetch(self.token, url, headers, timeout=max(30, timeout), limit=limit, stop_event=self.stop_event)

    def fetch(self, url, headers, timeout=30):
        return self.fetch_response(url, headers, timeout).data

    def source_url(self, url, headers=None):
        key = self.broker.add_source(self.token, url, headers or {})
        return self.local_base + '/browser-source/' + key

    def assert_healthy(self):
        with self.broker._lock:
            self.broker._client(self.token)
        if self.stop_event is not None and self.stop_event.is_set():
            raise BrowserTransportError('Tarayıcı aktarımı iptal edildi.')

    def close(self):
        self.broker.revoke(self.token)


class BrowserHeaders(dict):
    def __init__(self, values=(), transport: Optional[BrowserTransport] = None):
        super().__init__(values)
        self.transport = transport

    def copy(self):
        return BrowserHeaders(self, self.transport)


def serve_browser_source(handler, broker, key, head_only=False):
    """Range-capable loopback input for FFmpeg and the native progressive relay."""
    import socket
    import struct
    sent_headers = False
    try:
        token, url, original_headers = broker.source(key)
        match = re.fullmatch(r'bytes=(\d+)-(\d*)', handler.headers.get('Range', ''))
        if handler.headers.get('Range') and not match:
            handler.send_response(416)
            handler.send_header('Content-Length', '0')
            handler.end_headers()
            return
        start = int(match.group(1)) if match else 0
        wanted_end = int(match.group(2)) if match and match.group(2) else None
        block = 2 * 1024 * 1024

        def read_part(offset, end):
            headers = {'Range': f'bytes={offset}-{end}'}
            response = broker.fetch(token, url, headers, timeout=45, limit=block)
            if response.status == 206:
                parsed = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.content_range)
                if not parsed:
                    raise BrowserTransportError('Tarayıcı kaynağının Range yanıtı geçersiz.')
                first, last, total = map(int, parsed.groups())
                if first != offset or last > end or last - first + 1 != len(response.data) or total <= last:
                    raise BrowserTransportError('Tarayıcı kaynağı beklenen aralığı döndürmedi.')
                return response.data, total
            if offset != 0 or not response.data:
                raise BrowserTransportError('Sunucu kaldığı yerden aktarımı desteklemiyor.')
            return response.data, len(response.data)

        data, total = read_part(start, min(start + block - 1, wanted_end) if wanted_end is not None else start + block - 1)
        end = min(wanted_end, total - 1) if wanted_end is not None else total - 1
        if start > end:
            raise BrowserTransportError('Geçersiz medya aralığı.')
        handler.send_response(206 if match else 200)
        handler.send_header('Content-Type', 'application/octet-stream')
        handler.send_header('Content-Length', str(end - start + 1))
        handler.send_header('Accept-Ranges', 'bytes')
        if match:
            handler.send_header('Content-Range', f'bytes {start}-{end}/{total}')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('Connection', 'close')
        handler.end_headers()
        sent_headers = True
        if head_only:
            return
        offset = start
        while offset <= end:
            if not data or offset + len(data) - 1 > end:
                raise BrowserTransportError('Tarayıcı aktarım aralığı uyuşmuyor.')
            handler.wfile.write(data)
            handler.wfile.flush()
            offset += len(data)
            if offset <= end:
                data, next_total = read_part(offset, min(offset + block - 1, end))
                if next_total != total:
                    raise BrowserTransportError('Medya boyutu aktarım sırasında değişti.')
    except (BrowserTransportError, OSError, ValueError):
        if not sent_headers:
            handler.send_response(502)
            handler.send_header('Content-Length', '0')
            handler.send_header('Connection', 'close')
            handler.end_headers()
        else:
            try:
                handler.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
                handler.connection.close()
            except OSError:
                pass
