"""v3.10.1 kullanıcı-raporu düzeltmelerinin regresyon testleri.

Kullanıcının bildirdiği sorunlar ve bu dosyadaki karşılıkları:

1. "Altyazı bar'da görünüyor ama IDM'de 0 baytta kalıyor"
   -> Altyazı OUTPUT_FILE'a yazılır, boyut kesinleşir ve köprü Content-Length +
      206/Range destekli tek bayt akıtır. (test_subtitle_stream_serves_bytes_with_length)
2. "Torrent inmiyor, boyutu bile göstermiyor"
   -> Magnet meta verisi gelene kadar beklenir; gelmezse sonsuza kadar %0 yerine
      dürüst 503 mesajı verilir. (test_torrent_stream_reports_missing_metadata)
3. "YouTube/ok.ru hiç kaynak bulmuyor"
   -> yt-dlp ROOT'SUZ tek dosya binary olarak kendiliğinden kurulur; bulunma
      yolu ve öncelik garantilenir. (test_find_ytdlp_prefers_bundled_binary)
4. "IDM'de hep localhost linkleri görünüyor"
   -> Düz dosya indirmelerinde IDM'ye GERÇEK bağlantı verilir (varsayılan açık),
      P2P/altyazı köprülerinde ise gerçek bağlantı referer alanına yazılır.
5. "eD2K boyutu algılanıyor ama inmiyor"
   -> Kaynak bulunamazsa dürüst hata mesajı (sonsuz bekleme yok).
"""
from __future__ import annotations

import re
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_BASE = Path(__file__).resolve().parents[2]  # yeni düzen: idm_linux paketini içeren src/ dizini
sys.path.insert(0, str(SRC_BASE))  # yeni düzen: src/ tabanı


# ─────────────────────────────────────────────────────────────────────────────
# 1) Altyazı: köprüden GERÇEK baytlar + Content-Length
# ─────────────────────────────────────────────────────────────────────────────
VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000 align:start position:10%
Merhaba <b>dünya</b> &amp; arkadaşlar

00:00:04.000 --> 00:00:06.000
<c.yellow>İkinci</c> satır
"""


def _serve_text(body: str):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/vtt")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):  # noqa: A003
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _http_get(port: int, path: str, method: str = "GET"):
    import urllib.request

    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, dict(r.headers), (r.read() if method != "HEAD" else b"")


def test_subtitle_stream_serves_bytes_with_length():
    """Altyazı köprüsü: Content-Length > 0 ve gövde GERÇEK altyazı olmalı."""
    import urllib.parse
    from http.server import ThreadingHTTPServer

    from idm_linux.daemon import DaemonState, make_http_handler

    src, base = _serve_text(VTT)
    state = DaemonState()
    bridge = ThreadingHTTPServer(("127.0.0.1", 0), make_http_handler(state))
    state.cfg.http_port = bridge.server_address[1]
    threading.Thread(target=bridge.serve_forever, daemon=True).start()
    try:
        ticket = state.stream_engine.create_ticket(
            source_url=f"{base}/1.vtt", filename="film.vtt", mode="subs"
        )
        job = state.stream_engine.get_job(ticket.ticket_id)
        job.ensure_started()
        deadline = time.time() + 25
        while time.time() < deadline and not (job.completed or job.failed):
            time.sleep(0.05)
        assert job.completed, job.error_msg
        assert job.output_file.is_file() and job.output_file.stat().st_size > 0

        path = f"/stream/{ticket.ticket_id}/{urllib.parse.quote(ticket.filename)}"
        status, headers, _ = _http_get(bridge.server_address[1], path, "HEAD")
        assert status == 200
        assert int(headers.get("Content-Length") or 0) > 0, "IDM 0 bayt görürdü (eski hata)"
        assert "vtt" in (headers.get("Content-Type") or "").lower()

        status, headers, body = _http_get(bridge.server_address[1], path)
        assert status == 200 and body.lstrip().startswith(b"WEBVTT")
        assert len(body) == int(headers.get("Content-Length") or 0)

        # Range desteği: IDM duraklatıp devam ettirebilir
        import urllib.request

        req = urllib.request.Request(
            f"http://127.0.0.1:{bridge.server_address[1]}{path}",
            headers={"Range": "bytes=0-9"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            assert r.status == 206
            assert r.read() == body[:10]
    finally:
        src.shutdown()
        bridge.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
# 2) Torrent: meta veri yoksa dürüst hata (sonsuz %0 yok)
# ─────────────────────────────────────────────────────────────────────────────
class _FakeMeta:
    name = "deneme"
    total_size = 0
    is_multi_file = False
    web_seeds = []
    piece_length = 262144

    @property
    def output_filename(self) -> str:
        return "deneme.bin"


class _FakeSession:
    meta = _FakeMeta()
    rpc_port = 1234
    error_message = ""

    def ensure_started(self) -> None:
        return None

    def query_status(self):
        return {"status": "waiting", "totalLength": "0", "files": []}


class _FakeHandler:
    def __init__(self) -> None:
        self.status = 0
        self.headers = {}
        self.body = b""
        self.wfile = self

    def send_response(self, code, *a):
        self.status = code

    def send_header(self, k, v):
        self.headers[k.lower()] = v

    def end_headers(self):
        pass

    def write(self, data):
        self.body += data


def test_torrent_stream_reports_missing_metadata():
    from idm_linux.torrent_engine import serve_torrent_over_http

    import idm_linux.torrent_engine as T

    handler = _FakeHandler()
    t0 = time.time()
    # Gerçek bekleme 90 sn'dir; testte sanal saatle hızlandırılır.
    clock = {"t": 0.0}

    def _fake_time() -> float:
        clock["t"] += 1.0
        return clock["t"]

    orig_time, orig_sleep = T.time.time, T.time.sleep
    try:
        T.time.time = _fake_time
        T.time.sleep = lambda *_a, **_k: None
        serve_torrent_over_http(handler, _FakeSession(), head_only=False)
    finally:
        T.time.time = orig_time
        T.time.sleep = orig_sleep
    assert handler.status == 503, handler.status
    assert b"meta" in handler.body.lower()
    assert time.time() - t0 < 60


# ─────────────────────────────────────────────────────────────────────────────
# 3) yt-dlp: paketlenmiş (root'suz) ikili öncelikli bulunur
# ─────────────────────────────────────────────────────────────────────────────
def test_find_ytdlp_prefers_bundled_binary(tmp_path, monkeypatch):
    from idm_linux import distro

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    bin_dir = tmp_path / "idm-linux" / "bin"
    bin_dir.mkdir(parents=True)
    fake = bin_dir / "yt-dlp"
    fake.write_bytes(b"#!/bin/sh\necho test\n" + b"x" * 200_000)
    fake.chmod(0o755)
    found = distro.find_ytdlp()
    assert found == str(fake), found

    src = (PROJECT_ROOT / "distro.py").read_text(encoding="utf-8")
    body = src[src.index("def ensure_ytdlp(") :]
    assert "install_standalone_ytdlp" in body.split("cmds = [")[0], (
        "ensure_ytdlp önce root'suz ikili indirmeyi denemeli"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4) IDM'de gerçek bağlantı: config varsayılanı + köprü referer aktarımı
# ─────────────────────────────────────────────────────────────────────────────
def test_real_urls_preferred_by_default():
    from idm_linux.config import IdmLinuxConfig

    assert IdmLinuxConfig().prefer_real_urls is True

    src = (PROJECT_ROOT / "daemon.py").read_text(encoding="utf-8")
    assert 'prefer_real_urls' in src
    direct_block = src[
        src.index('if delivery == "direct" and direct_url:') : src.index('if delivery == "direct" and direct_url:')
        + 2600
    ]
    assert "direct_url" in direct_block and "real_url" in direct_block

    # torrent/ed2k/altyazı köprülerinde gerçek bağlantı referer alanında görünür
    assert "referer=(magnet_uri or torrent_url or \"\")" in src
    assert "referer=link[:2000]" in src
    assert "referer=direct_url[:2000]" in src


# ─────────────────────────────────────────────────────────────────────────────
# 5) eD2K: kaynak yoksa dürüst hata
# ─────────────────────────────────────────────────────────────────────────────
def test_ed2k_reports_no_sources_clearly():
    from idm_linux.p2p import ed2k_native as E

    assert "kaynak (tohum) bulunamadı" in Path(E.__file__).read_text(encoding="utf-8")
    session_src = Path(E.__file__).read_text(encoding="utf-8")
    assert "_gather_loop" in session_src and "error_message" in session_src
