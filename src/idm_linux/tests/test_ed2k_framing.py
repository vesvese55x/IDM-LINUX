"""eD2K paket çerçevesi + sunucu girişi/kaynak sorgusu testleri.

Gerçek ağa çıkmaz: yerel bir "sahte sunucu" OP_IDCHANGE ve OP_FOUNDSOURCES
yanıtlarını üretir. Bu testler, girişin neden sessizce başarısız olduğunu
açıklayan 0xE3 çerçeve hatasını kilitler:

    doğru:  [0xE3] [uzunluk:4 LE = opcode+gövde] [opcode] [gövde]
    yanlış: [0xE3] [opcode] [uzunluk:4 LE]   ← eski sürüm (sunucu RST/yanıtsız)
"""
from __future__ import annotations

import socket
import struct
import sys
import threading
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from idm_linux.p2p import ed2k_native as E  # noqa: E402


def _socketpair():
    a, b = socket.socketpair()
    a.settimeout(5.0)
    b.settimeout(5.0)
    return a, b


def test_send_packet_header_is_e3_length_opcode():
    a, b = _socketpair()
    try:
        assert E._send_packet(a, E.OP_LOGINREQUEST, b"payload")
        raw = b.recv(64)
        assert raw[0] == 0xE3, "protokol baytı 0xE3 olmalı"
        assert struct.unpack("<I", raw[1:5])[0] == len(b"payload") + 1
        assert raw[5] == E.OP_LOGINREQUEST
        assert raw[6:] == b"payload"
    finally:
        a.close()
        b.close()


def test_recv_packet_plain_and_compressed():
    a, b = _socketpair()
    try:
        body = b"merhaba"
        E._send_packet(a, 0x40, body)
        assert E._recv_packet(b) == (0x40, body)

        packed = zlib.compress(body)
        a.sendall(
            bytes([0xD4]) + struct.pack("<I", len(packed) + 1) + bytes([0x38]) + packed
        )
        assert E._recv_packet(b) == (0x38, body)
    finally:
        a.close()
        b.close()


class FakeServer(threading.Thread):
    """OP_IDCHANGE + OP_FOUNDSOURCES üreten asgari eD2K sunucusu."""

    def __init__(self, file_hash: bytes, sources):
        super().__init__(daemon=True)
        self.file_hash = file_hash
        self.sources = list(sources)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.login_ok = False
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass

    def run(self) -> None:  # pragma: no cover - thread
        self.sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        conn.settimeout(10.0)
        try:
            pkt = E._recv_packet(conn)
            if pkt is None:
                return
            opcode, payload = pkt
            if opcode != E.OP_LOGINREQUEST:
                return
            self.login_ok = len(payload) >= 22
            # OP_IDCHANGE: client id(4) + tcp flags(4) + prim. ip(4) + sec. ip(4)
            E._send_packet(
                conn,
                E.OP_IDCHANGE,
                struct.pack("<I", 0x00D5F6) + b"\x00" * 16,
            )
            while True:
                pkt = E._recv_packet(conn)
                if pkt is None:
                    return
                opcode, payload = pkt
                if opcode in (E.OP_GETSOURCES, E.OP_GETSOURCES_OBFU):
                    body = self.file_hash + bytes([len(self.sources)])
                    for ip, port in self.sources:
                        body += struct.pack("<I", struct.unpack("<I", socket.inet_aton(ip))[0])
                        body += struct.pack("<H", port)
                    E._send_packet(conn, E.OP_FOUNDSOURCES, body)
        except (socket.timeout, OSError):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass


def test_server_login_and_source_query():
    fh = bytes(range(16))
    node = FakeServer(fh, [("1.2.3.4", 4662), ("5.6.7.8", 4662)])
    node.start()
    try:
        client = E.ED2KServerClient("127.0.0.1", node.port)
        assert client.connect(timeout=5.0) is True, client.message
        assert client.client_id == 0x00D5F6
        peers = client.get_sources(fh, 1024, timeout=5.0)
        client.close()
        assert peers == [("1.2.3.4", 4662), ("5.6.7.8", 4662)]
        assert node.login_ok, "giriş paketi beklenen asgari uzunlukta değil"
    finally:
        node.stop()


def test_empty_source_answer_returns_immediately():
    fh = b"\x42" * 16
    node = FakeServer(fh, [])
    node.start()
    try:
        client = E.ED2KServerClient("127.0.0.1", node.port)
        assert client.connect(timeout=5.0)
        t0 = time.time()
        peers = client.get_sources(fh, 1024, timeout=8.0)
        elapsed = time.time() - t0
        client.close()
        assert peers == []
        assert elapsed < 2.5, f"boş yanıtta zaman aşımı beklenmemeli ({elapsed:.1f}s)"
    finally:
        node.stop()


def test_udp_source_query_parses_reply():
    """UDP (OP_GLOBGETSOURCES) yedeği: cevabı doğru ayrıştırmalı."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(5.0)
    port = srv.getsockname()[1]
    fh = b"\x5a" * 16

    def _serve():
        try:
            data, addr = srv.recvfrom(2048)
        except OSError:
            return
        assert data[0] == 0xE3 and data[1] == E.OP_GLOBGETSOURCES
        assert data[2:18] == fh
        body = bytes([0xE3, E.OP_GLOBFOUNDSOURCES]) + fh + bytes([2])
        for ip, prt in (("1.2.3.4", 4662), ("5.6.7.8", 4662)):
            body += socket.inet_aton(ip) + struct.pack("<H", prt)
        srv.sendto(body, addr)

    threading.Thread(target=_serve, daemon=True).start()
    try:
        peers = E.udp_get_sources("127.0.0.1", port, fh, 1024, timeout=3.0)
        assert peers == [("1.2.3.4", 4662), ("5.6.7.8", 4662)]
    finally:
        srv.close()
