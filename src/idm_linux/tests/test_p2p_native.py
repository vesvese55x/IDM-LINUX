"""Native P2P motoru testleri — tamamı YEREL ve BELİRSİZLİK İÇERMEZ.

Kapsanan davranışlar:
  1) Saf Python BitTorrent motoru, sahte (mock) bir tracker + eş ile gerçek bir
     parça alışverişi yapıp dosyayı BİREBİR doğru indiriyor mu? (aria2c YOK)
  2) ``status()`` çıktısı aria2 alan adlarıyla uyumlu mu (mevcut IDM köprüsü
     tek satır değişmeden çalışsın)?
  3) Magnet + ut_metadata (BEP 9) meta veri takası çalışıyor mu?
  4) eD2K (eMule) protokolü: sunucu girişi, kaynak sorgusu, eş el sıkışması,
     parça indirme ve MD4 bütünlük doğrulaması uçtan uca çalışıyor mu?
"""
from __future__ import annotations

import hashlib
import os
import socket
import struct
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from idm_linux.p2p.bencode import bdecode, bencode  # noqa: E402
from idm_linux.p2p.bt_native import (  # noqa: E402
    BLOCK_SIZE,
    NativeTorrentSession,
    parse_magnet_uri,
    parse_torrent_bytes,
)

PROTOCOL = b"BitTorrent protocol"


# ─────────────────────────────────────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────────────────────────────────────
def _make_payload(size: int) -> bytes:
    return bytes((i * 37 + 11) % 251 for i in range(size))


def _build_torrent(payload: bytes, piece_len: int, tracker_url: str, name: str = "ornek.bin"):
    pieces = b"".join(
        hashlib.sha1(payload[i : i + piece_len]).digest() for i in range(0, len(payload), piece_len)
    )
    info = {b"name": name.encode(), b"piece length": piece_len, b"pieces": pieces, b"length": len(payload)}
    info_bytes = bencode(info)
    return bencode({b"announce": tracker_url.encode(), b"info": info}), info_bytes


class _MockTracker(BaseHTTPRequestHandler):
    peer_port = 0

    def do_GET(self):  # noqa: N802
        ip = "127.0.0.1"
        peer = socket.inet_aton(ip) + struct.pack(">H", self.peer_port)
        body = bencode({b"interval": 60, b"peers": peer, b"complete": 1, b"incomplete": 0})
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):  # sessiz
        return


def _bencode_dict_len(data: bytes) -> int:
    """Test yardımcısı: bir bencode sözlüğünün bayt uzunluğunu bulur."""
    depth = 0
    idx = 0
    while idx < len(data):
        ch = data[idx : idx + 1]
        if ch in (b"d", b"l"):
            depth += 1
            idx += 1
        elif ch == b"e":
            depth -= 1
            idx += 1
            if depth == 0:
                return idx
        elif ch.isdigit():
            sep = data.index(b":", idx)
            idx = sep + 1 + int(data[idx:sep])
        elif ch == b"i":
            idx = data.index(b"e", idx) + 1
        else:
            raise ValueError("bozuk bencode")
    raise ValueError("kapanmadı")


class _MockPeer:
    """Tek parçalı/çok parçalı torrenti sunan sahte eş (seeder)."""

    def __init__(self, info_hash: bytes, payload: bytes, piece_len: int,
                 info_bytes: bytes = b"", support_metadata: bool = False):
        self.info_hash = info_hash
        self.payload = payload
        self.piece_len = piece_len
        self.info_bytes = info_bytes
        self.support_metadata = support_metadata
        self.requests_served = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _recv_exact(self, conn, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return bytes(buf)

    def _handle(self, conn: socket.socket):
        try:
            conn.settimeout(30)
            hs = self._recv_exact(conn, 68)
            if not hs or hs[28:48] != self.info_hash:
                return
            reserved = bytes([0, 0, 0, 0, 0, 0x10, 0, 0])
            conn.sendall(bytes([19]) + PROTOCOL + reserved + self.info_hash + b"-MOCK00-000000000000")
            num_pieces = (len(self.payload) + self.piece_len - 1) // self.piece_len
            bitfield = bytearray((num_pieces + 7) // 8)
            for i in range(num_pieces):
                bitfield[i // 8] |= 1 << (7 - (i % 8))
            conn.sendall(struct.pack(">IB", 1 + len(bitfield), 5) + bytes(bitfield))
            conn.sendall(struct.pack(">IB", 1, 1))  # unchoke
            while not self._stop:
                head = self._recv_exact(conn, 4)
                if head is None:
                    return
                length = struct.unpack(">I", head)[0]
                if length == 0:
                    continue
                body = self._recv_exact(conn, length)
                if body is None:
                    return
                msg_id = body[0]
                payload = body[1:]
                if msg_id == 6 and len(payload) >= 12:  # request
                    index, begin, blen = struct.unpack(">III", payload[:12])
                    start = index * self.piece_len + begin
                    data = self.payload[start : start + blen]
                    conn.sendall(struct.pack(">IB", 9 + len(data), 7) + struct.pack(">II", index, begin) + data)
                    self.requests_served += 1
                elif msg_id == 2:  # interested -> unchoke (gerçek eşler gibi)
                    conn.sendall(struct.pack(">IB", 1, 1))
                elif msg_id == 20 and self.support_metadata and len(payload) >= 2:
                    ext_id = payload[0]
                    if ext_id == 0:
                        handshake_payload = bencode({b"m": {b"ut_metadata": 3}, b"v": b"MOCK"})
                        conn.sendall(
                            struct.pack(">IB", 2 + len(handshake_payload), 20)
                            + bytes([0])
                            + handshake_payload
                        )
                    elif ext_id == 3:
                        try:
                            ext_body = payload[1:]
                            head_len = _bencode_dict_len(ext_body)
                            req = bdecode(ext_body[:head_len])
                        except Exception:
                            continue
                        if int(req.get(b"msg_type") or 0) == 0:
                            idx = int(req.get(b"piece") or 0)
                            chunk = self.info_bytes[idx * 16384 : (idx + 1) * 16384]
                            reply = bencode(
                                {b"msg_type": 1, b"piece": idx, b"total_size": len(self.info_bytes)}
                            ) + chunk
                            conn.sendall(struct.pack(">IB", 2 + len(reply), 20) + bytes([3]) + reply)
        except (OSError, socket.timeout):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Testler
# ─────────────────────────────────────────────────────────────────────────────
def test_native_bittorrent_download_from_mock_swarm(tmp_path: Path) -> None:
    payload = _make_payload(400 * 1024)
    piece_len = 32 * 1024
    tracker_srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockTracker)
    tracker_port = tracker_srv.server_address[1]
    tracker_url = f"http://127.0.0.1:{tracker_port}/announce"
    torrent_bytes, info_bytes = _build_torrent(payload, piece_len, tracker_url)
    info_hash = hashlib.sha1(info_bytes).digest()

    peer = _MockPeer(info_hash, payload, piece_len)
    _MockTracker.peer_port = peer.port
    threading.Thread(target=tracker_srv.serve_forever, daemon=True).start()

    sess = NativeTorrentSession(tmp_path / "work", torrent_bytes=torrent_bytes, enable_dht=False)
    try:
        meta = parse_torrent_bytes(torrent_bytes)
        assert meta.info_hash == info_hash
        assert meta.num_pieces == (len(payload) + piece_len - 1) // piece_len
        assert meta.total_size == len(payload)

        sess.start()
        deadline = time.time() + 40
        while time.time() < deadline and not sess.all_done:
            time.sleep(0.2)
        assert sess.all_done, f"indirme tamamlanmadı: {sess.status()}"

        out_file = tmp_path / "work" / "data" / "ornek.bin"
        assert out_file.is_file(), "dosya oluşmadı"
        assert out_file.read_bytes() == payload, "indirilen baytlar bozuk!"

        st = sess.status()
        # aria2 uyumluluğu: mevcut köprü bu alanları okuyor
        assert st["status"] == "complete"
        assert int(st["totalLength"]) == len(payload)
        assert int(st["completedLength"]) == len(payload)
        assert int(st["numPieces"]) == meta.num_pieces
        assert int(st["pieceLength"]) == piece_len
        assert st["files"][0]["path"].endswith("ornek.bin")
        assert st["bittorrent"]["info"]["name"] == "ornek.bin"
        bf = st["bitfield"]
        assert bf, "bitfield boş"
        # parça sayısı 8'in katı değilse son baytın artık bitleri 0 kalır (BEP 3)
        full_bytes = meta.num_pieces // 8
        assert bf[: full_bytes * 2] == "ff" * full_bytes, "tamamlanmış parçalar bitfield'a yazılmadı"
        assert all(sess._pieces.have), "bellekte eksik parça var"
        assert peer.requests_served >= meta.num_pieces
    finally:
        sess.stop()
        peer.close()
        tracker_srv.shutdown()


def test_native_magnet_metadata_exchange(tmp_path: Path) -> None:
    payload = _make_payload(120 * 1024)
    piece_len = 32 * 1024
    torrent_bytes, info_bytes = _build_torrent(payload, piece_len, "http://127.0.0.1:1/announce")
    info_hash = hashlib.sha1(info_bytes).digest()

    peer = _MockPeer(info_hash, payload, piece_len, info_bytes=info_bytes, support_metadata=True)
    magnet = f"magnet:?xt=urn:btih:{info_hash.hex()}&dn=magnet-test"

    info = parse_magnet_uri(magnet)
    assert info["info_hash"] == info_hash

    sess = NativeTorrentSession(tmp_path / "magnet", magnet=magnet, enable_dht=False)
    sess._known_peers.append(("127.0.0.1", peer.port))  # DHT/tracker yok: eş elle verilir
    try:
        sess.start()
        deadline = time.time() + 40
        while time.time() < deadline and not sess.all_done:
            time.sleep(0.2)
        assert sess.meta is not None, "meta veri alınamadı (ut_metadata)"
        assert sess.meta.info_hash == info_hash
        assert sess.all_done, f"magnet indirmesi bitmedi: {sess.status()}"
        assert (tmp_path / "magnet" / "data" / "ornek.bin").read_bytes() == payload
    finally:
        sess.stop()
        peer.close()


def test_native_engine_prefers_no_external_binary() -> None:
    """Native motor dış ikili çağırmadan çalışmalı (aria2c yolu yalnız yedek)."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "torrent_engine.py").read_text(encoding="utf-8")
    assert "NativeTorrentSession" in src, "native motor torrent_engine'e bağlanmamış"
    impl = src[src.index("def _ensure_started_impl") :]
    assert impl.index("self._try_native_start()") < impl.index('shutil.which("aria2c")'), (
        "native motor aria2 yedeğinden ÖNCE denenmeli"
    )
    assert "self.native.stop()" in src, "native motor kapanışta durdurulmuyor"


# ─────────────────────────────────────────────────────────────────────────────
# eD2K (eMule) native motor testleri — yerel sahte sunucu + sahte eş
# ─────────────────────────────────────────────────────────────────────────────
def _read_ed2k_packet(conn, first=False):
    """eD2K TCP paketi okur: [0xE3][uzunluk:4 LE][opcode][gövde].

    ``first`` yalnızca okunacak ilk paket için anlamlıdır; çerçeve her pakette
    aynıdır (0xE3 protokol baytı + uzunluk + opcode).
    """
    head = b""
    while len(head) < 5:
        chunk = conn.recv(5 - len(head))
        if not chunk:
            return None
        head += chunk
    if head[0] != 0xE3:
        return None
    length = struct.unpack("<I", head[1:5])[0]
    if length < 1:
        return None
    body = b""
    while len(body) < length:
        chunk = conn.recv(length - len(body))
        if not chunk:
            return None
        body += chunk
    return body[0], body[1:]


def _send_ed2k_packet(conn, opcode, payload=b""):
    conn.sendall(bytes([0xE3]) + struct.pack("<I", len(payload) + 1) + bytes([opcode]) + payload)


class _MockED2KPeer:
    """eD2K eş protokolünü konuşan sahte kaynak (dosya sunar)."""

    def __init__(self, payload: bytes, file_hash: bytes, block_size: int = 180 * 1024):
        self.payload = payload
        self.file_hash = file_hash
        self.block_size = block_size
        self.requests = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        from idm_linux.p2p.md4 import md4

        try:
            conn.settimeout(20)
            pkt = _read_ed2k_packet(conn, first=True)
            if not pkt or pkt[0] != 0x01:  # HELLO
                return
            _send_ed2k_packet(conn, 0x4C, self.file_hash + struct.pack("<I", 0) + struct.pack("<H", 0))
            while True:
                pkt = _read_ed2k_packet(conn)
                if not pkt:
                    return
                opcode, payload = pkt
                if opcode == 0x58:  # FILEREQUEST
                    _send_ed2k_packet(conn, 0x59, self.file_hash + struct.pack("<H", 0))
                    _send_ed2k_packet(conn, 0x55)  # ACCEPTUPLOADREQ
                elif opcode == 0x51:  # HASHSETREQUEST
                    _send_ed2k_packet(
                        conn, 0x52, self.file_hash + struct.pack("<H", 1) + md4(self.payload)
                    )
                elif opcode == 0x47:  # REQUESTPARTS
                    start, end = struct.unpack("<II", payload[16:24])
                    data = self.payload[start:end]
                    self.requests += 1
                    _send_ed2k_packet(
                        conn, 0x46, self.file_hash + struct.pack("<II", start, end) + data
                    )
                elif opcode == 0x96:  # PING
                    _send_ed2k_packet(conn, 0x97)
        except (OSError, socket.timeout):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass


class _MockED2KServer:
    def __init__(self, peer_port: int):
        self.peer_port = peer_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            conn.settimeout(20)
            pkt = _read_ed2k_packet(conn, first=True)
            if not pkt or pkt[0] != 0x01:  # LOGINREQUEST
                return
            _send_ed2k_packet(conn, 0x40, struct.pack("<II", 0x0100007F, 0))
            while True:
                pkt = _read_ed2k_packet(conn)
                if not pkt:
                    return
                opcode, payload = pkt
                if opcode in (0x19, 0x23):  # GETSOURCES / GETSOURCES_OBFU
                    src = socket.inet_aton("127.0.0.1") + struct.pack("<H", self.peer_port)
                    _send_ed2k_packet(
                        conn, 0x42, payload[:16] + bytes([1]) + src
                    )
        except (OSError, socket.timeout):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass


def test_native_ed2k_download_and_md4_verify(tmp_path: Path) -> None:
    from idm_linux.p2p.ed2k_native import NativeED2KSession, parse_ed2k_link
    from idm_linux.p2p.md4 import md4

    payload = _make_payload(300 * 1024)
    file_hash = md4(payload)
    link = f"ed2k://|file|ed2k-ornek.bin|{len(payload)}|{file_hash.hex()}|/"

    parsed = parse_ed2k_link(link)
    assert parsed and parsed["size"] == len(payload) and parsed["hash"] == file_hash

    peer = _MockED2KPeer(payload, file_hash)
    server = _MockED2KServer(peer.port)

    import idm_linux.p2p.ed2k_native as E

    orig_fetch = E.fetch_server_list
    E.fetch_server_list = lambda timeout=8.0, force=False: [("127.0.0.1", server.port)]
    sess = NativeED2KSession(tmp_path / "ed2k", link=link, download_dir=tmp_path / "ed2k" / "out")
    try:
        sess.start()
        deadline = time.time() + 45
        while time.time() < deadline and not sess.complete:
            time.sleep(0.2)
        assert sess.complete, f"eD2K indirmesi tamamlanmadı: {sess.query_status()}"
        assert not sess.error_message, sess.error_message
        out = tmp_path / "ed2k" / "out" / "ed2k-ornek.bin"
        assert out.is_file(), "hedef dosya yok"
        assert out.read_bytes() == payload, "eD2K baytları bozuk!"
        st = sess.query_status()
        assert st["status"] == "complete"
        assert int(st["completedLength"]) == len(payload)
        assert peer.requests >= 2, "blok istekleri gönderilmedi"
    finally:
        sess.stop()
        peer.close()
        server.close()
        E.fetch_server_list = orig_fetch


def test_native_ed2k_rejects_corrupt_data(tmp_path: Path) -> None:
    """Hashset MD4 doğrulaması: bozuk parça kabul EDİLMEMELİ."""
    from idm_linux.p2p.md4 import md4

    good = _make_payload(200 * 1024)
    corrupt = bytes(b ^ 0xFF for b in good)
    file_hash = md4(good)
    link = f"ed2k://|file|bozuk.bin|{len(good)}|{file_hash.hex()}|/"

    # eş BOZUK veri gönderir, hashset doğru karmayı bildirir
    peer = _MockED2KPeer(corrupt, file_hash)
    server = _MockED2KServer(peer.port)

    import idm_linux.p2p.ed2k_native as E

    orig_fetch = E.fetch_server_list
    E.fetch_server_list = lambda timeout=8.0, force=False: [("127.0.0.1", server.port)]
    sess = E.NativeED2KSession(tmp_path / "bad", link=link, download_dir=tmp_path / "bad" / "out")
    try:
        sess.start()
        deadline = time.time() + 20
        while time.time() < deadline and sess.complete:
            time.sleep(0.2)
        time.sleep(2.5)
        assert not sess.complete, "bozuk veri kabul edildi (MD4 denetimi çalışmıyor)"
    finally:
        sess.stop()
        peer.close()
        server.close()
        E.fetch_server_list = orig_fetch


def test_native_web_seed_only_torrent(tmp_path: Path) -> None:
    """BEP 19 web seed: eş/tracker YOKKEN HTTP kaynağından parça parça indirme."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    payload = _make_payload(200 * 1024)
    piece_len = 32 * 1024
    pieces = b"".join(
        hashlib.sha1(payload[i : i + piece_len]).digest() for i in range(0, len(payload), piece_len)
    )

    class RangeHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            rng = self.headers.get("Range") or ""
            if rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                start, end = int(a), int(b)
                body = payload[start : end + 1]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
            else:
                body = payload
                self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            return

    srv = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/dosya.bin"

    info = {b"name": b"webseed.bin", b"piece length": piece_len, b"pieces": pieces, b"length": len(payload)}
    torrent = bencode({b"url-list": url.encode(), b"info": info})
    sess = NativeTorrentSession(tmp_path / "ws", torrent_bytes=torrent, enable_dht=False)
    try:
        sess.start()
        deadline = time.time() + 30
        while time.time() < deadline and not sess.all_done:
            time.sleep(0.2)
        assert sess.all_done, f"web seed indirmesi tamamlanmadı: {sess.status()}"
        assert (tmp_path / "ws" / "data" / "webseed.bin").read_bytes() == payload
    finally:
        sess.stop()
        srv.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
# Uçtan uca köprü testleri: native motor → IDM köprüsü (daemon HTTP)
# ─────────────────────────────────────────────────────────────────────────────
def _start_daemon_state():
    import threading as _th

    from idm_linux.daemon import DaemonState, make_http_handler

    state = DaemonState()
    dispatched = []

    def _mock_send(req):
        dispatched.append(req)
        return True, "Mock IDM OK"

    state.sender.send_download = _mock_send  # type: ignore[method-assign]
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_http_handler(state))
    port = srv.server_address[1]
    state.cfg.http_port = port
    _th.Thread(target=srv.serve_forever, daemon=True).start()
    return state, srv, port, dispatched


def test_e2e_native_torrent_dispatch_to_idm(tmp_path: Path) -> None:
    import base64 as _b64
    import json as _json

    payload = _make_payload(120 * 1024)
    piece_len = 32 * 1024
    tracker_srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockTracker)
    tracker_url = f"http://127.0.0.1:{tracker_srv.server_address[1]}/announce"
    torrent_bytes, info_bytes = _build_torrent(payload, piece_len, tracker_url, name="idm-e2e.bin")
    info_hash = hashlib.sha1(info_bytes).digest()
    peer = _MockPeer(info_hash, payload, piece_len)
    _MockTracker.peer_port = peer.port
    threading.Thread(target=tracker_srv.serve_forever, daemon=True).start()

    # Yalıtım: genel (internet) tracker listesi bu testte kapalı — yalnızca
    # yerel sahte tracker kullanılır (deterministik, ağ gürültüsüz).
    import idm_linux.p2p.bt_native as _btn
    import idm_linux.torrent_engine as _te

    _orig_cached = _te.cached_tracker_list
    _te.cached_tracker_list = lambda max_count=30: []
    _orig_merged = _te.merged_tracker_list
    _te.merged_tracker_list = lambda max_count=60: []
    _orig_dht_default = _btn.DHT_ENABLED_BY_DEFAULT
    _btn.DHT_ENABLED_BY_DEFAULT = False

    state, srv, port, dispatched = _start_daemon_state()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/torrent/download",
            data=_json.dumps({"torrent_base64": _b64.b64encode(torrent_bytes).decode()}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=40) as r:
            res = _json.loads(r.read().decode())
        assert res.get("ok"), res
        assert dispatched and "/torrent/" in dispatched[0].url
        with urllib.request.urlopen(dispatched[0].url, timeout=40) as dl:
            got = dl.read()
        assert got == payload, "IDM köprüsünden geçen baytlar bozuk!"
    finally:
        _te.cached_tracker_list = _orig_cached
        _te.merged_tracker_list = _orig_merged
        _btn.DHT_ENABLED_BY_DEFAULT = _orig_dht_default
        srv.shutdown()
        state.torrent_bridge.shutdown_all()
        peer.close()
        tracker_srv.shutdown()


def test_e2e_native_ed2k_dispatch_to_idm(tmp_path: Path) -> None:
    import json as _json

    import idm_linux.p2p.ed2k_native as E
    from idm_linux.p2p.md4 import md4

    payload = _make_payload(280 * 1024)
    file_hash = md4(payload)
    link = f"ed2k://|file|idm-e2e-ed2k.bin|{len(payload)}|{file_hash.hex()}|/"
    peer = _MockED2KPeer(payload, file_hash)
    server = _MockED2KServer(peer.port)
    orig_fetch = E.fetch_server_list
    E.fetch_server_list = lambda timeout=8.0, force=False: [("127.0.0.1", server.port)]

    state, srv, port, dispatched = _start_daemon_state()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/ed2k/download",
            data=_json.dumps({"link": link, "source": "e2e-test"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=40) as r:
            res = _json.loads(r.read().decode())
        assert res.get("ok"), res
        assert res.get("backend") == "native-ed2k", res
        assert dispatched and "/ed2k/" in dispatched[0].url
        with urllib.request.urlopen(dispatched[0].url, timeout=40) as dl:
            got = dl.read()
        assert got == payload, "IDM köprüsünden geçen eD2K baytları bozuk!"
        # köprü dosya boyutunu ve adını doğru bildirmeli
        assert dispatched[0].filename == "idm-e2e-ed2k.bin"
    finally:
        srv.shutdown()
        from idm_linux.ed2k_bridge import ed2k_shutdown_all

        ed2k_shutdown_all()
        peer.close()
        server.close()
        E.fetch_server_list = orig_fetch
