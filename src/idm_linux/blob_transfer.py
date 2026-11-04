"""Bounded, ordered blob uploads. No whole-file base64/JSON allocation."""
from __future__ import annotations
import base64
import hashlib
import secrets
import re
import shutil
import threading
import time
from pathlib import Path
from .wine_sender import sanitize_filename

class BlobTransferStore:
    MAX_BYTES = 1024 ** 3
    STREAM_MAX_BYTES = 64 * 1024 ** 3
    CHUNK_BYTES = 384 * 1024
    MAX_ACTIVE = 4
    TTL = 120.0

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._jobs = {}
        self._lock = threading.RLock()

    def _cleanup(self):
        now = time.monotonic()
        if self.directory.is_dir():
            for path in self.directory.glob('*.part'):
                if re.fullmatch(r'[0-9a-f]{48}\.part', path.name) and path.stem not in self._jobs:
                    if time.time() - path.stat().st_mtime > self.TTL:
                        path.unlink(missing_ok=True)
        for key, job in list(self._jobs.items()):
            if now - job['touched'] > self.TTL:
                self.cancel(key)

    def begin(self, filename, mime, size, streaming=False):
        unknown = streaming is True and size is None
        if unknown:
            size = self.STREAM_MAX_BYTES
        limit = self.STREAM_MAX_BYTES if unknown else self.MAX_BYTES
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= limit:
            raise ValueError('Invalid blob size')
        with self._lock:
            self._cleanup()
            if len(self._jobs) >= self.MAX_ACTIVE:
                raise ValueError('Too many concurrent blob uploads')
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.directory.chmod(0o700)
            partials = [p for p in self.directory.glob('*.part') if re.fullmatch(r'[0-9a-f]{48}\.part', p.name)]
            if len(partials) >= self.MAX_ACTIVE:
                raise ValueError('Previous blob uploads are still expiring')
            reserved = sum(max(0, j['reservation'] - j['received']) for j in self._jobs.values())
            reservation = min(size, 64 * 1024 ** 2) if unknown else size
            if shutil.disk_usage(self.directory).free < reservation * 2 + reserved + 32 * 1024 ** 2:
                raise ValueError('Insufficient staging space')
            key = secrets.token_hex(24)
            path = self.directory / (key + '.part')
            fh = path.open('xb')
            self._jobs[key] = dict(path=path, fh=fh, size=size, reservation=reservation, unknown=unknown, received=0,
                filename=sanitize_filename(str(filename or 'download.bin')) or 'download.bin',
                mime=str(mime or 'application/octet-stream')[:200], touched=time.monotonic(), sha=hashlib.sha256())
            return {'ok': True, 'transferId': key, 'chunkBytes': self.CHUNK_BYTES}

    def chunk(self, key, offset, data):
        if not isinstance(data, str) or len(data) > ((self.CHUNK_BYTES + 2) // 3) * 4:
            raise ValueError('Oversized blob chunk')
        raw = base64.b64decode(data, validate=True)
        if not raw or len(raw) > self.CHUNK_BYTES:
            raise ValueError('Invalid blob chunk')
        with self._lock:
            self._cleanup()
            job = self._jobs.get(key)
            if not job or isinstance(offset, bool) or not isinstance(offset, int) or offset != job['received']:
                raise ValueError('Missing or out-of-order blob upload')
            if job['received'] + len(raw) > job['size']:
                raise ValueError('Blob length exceeded')
            if job['unknown']:
                reserved = sum(max(0, j['reservation'] - j['received']) for j in self._jobs.values())
                if shutil.disk_usage(self.directory).free < len(raw) * 2 + reserved + 32 * 1024 ** 2:
                    raise ValueError('Insufficient streaming space')
            job['fh'].write(raw)
            job['sha'].update(raw)
            job['received'] += len(raw)
            job['touched'] = time.monotonic()
            return {'ok': True, 'received': job['received']}

    def finish(self, key, final_size=None):
        with self._lock:
            self._cleanup()
            job = self._jobs.get(key)
            if not job:
                raise ValueError('Incomplete blob upload')
            expected = final_size if job['unknown'] else job['size']
            if isinstance(expected, bool) or not isinstance(expected, int) or not 0 < expected <= job['size'] or job['received'] != expected:
                raise ValueError('Incomplete blob upload')
            job['size'] = expected
            job['fh'].close()
            del self._jobs[key]
            return {k: job[k] for k in ('path', 'size', 'filename', 'mime')} | {'sha256': job['sha'].hexdigest()}

    def cancel(self, key):
        with self._lock:
            job = self._jobs.pop(key, None)
            if job:
                job['fh'].close()
                job['path'].unlink(missing_ok=True)
        return {'ok': True, 'takeover': False}
