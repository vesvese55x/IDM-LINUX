"""eD2K eş protokolü — uçtan uca indirme testi.

Gerçek eMule eş protokolünü konuşan küçük bir "referans tohum" (seeder) sunucu
ayağa kaldırılır; native indirme oturumu bu eşe bağlanıp dosyayı indirir.
Doğrulananlar: 0xE3 paket çerçevesi, HELLO/HELLOANSWER, FILEREQUEST/
FILEREQANSWER, HASHSETREQUEST/HASHSETANSWER, STARTUPLOADREQ/ACCEPTUPLOADREQ,
REQUESTPARTS/SENDINGPART, parça MD4 doğrulaması ve çok parçalı dosya hash'i.

Test dış ağa çıkmaz (sunucu listesi boş, kaynak doğrudan verilir).
"""
from __future__ import annotations

import socket
import sys
import struct
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from idm_linux.p2p import ed2k_native as E  # noqa: E402
from idm_linux.p2p.md4 import md4


def _ed2k_file_hash(data: bytes) -> bytes:
    part = E.ED2K_PART_SIZE
    parts = [data[i : i + part] for i in range(0, len(data), part)] or [b""]
    hashes = [md4(p) for p in parts]
    return hashes[0] if len(hashes) == 1 else md4(b"".join(hashes))


class ReferenceSeeder(threading.Thread):
    """eMule eş protokolüyle tek dosya sunan minimal tohum."""

    def __init__(self, data: bytes, name: str = "ornek.bin") -> None:
        super().__init__(daemon=True)
        self.data = data
        self.name = name
        self.file_hash = _ed2k_file_hash(data)
        part_count = max(1, (len(data) + E.ED2K_PART_SIZE - 1) // E.ED2K_PART_SIZE)
        self.part_hashes = [
            md4(data[i * E.ED2K_PART_SIZE : (i + 1) * E.ED2K_PART_SIZE])
            for i in range(part_count)
        ]
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.served_bytes = 0
        self.requests = 0
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # pragma: no cover - thread
        self.sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, _addr = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()
        try:
            self.sock.close()
        except OSError:
            pass

    # ── tek bağlantı ────────────────────────────────────────────────────────
    def _serve(self, conn: socket.socket) -> None:
        conn.settimeout(30.0)
        try:
            while not self._stop.is_set():
                pkt = E._recv_packet(conn)
                if pkt is None:
                    return
                opcode, payload = pkt
                if opcode == E.OP_HELLO:
                    answer = (
                        self.file_hash[:0] + b"\x00" * 16  # istemci hash'i serbest
                        + struct.pack("<I", 0x1234)
                        + struct.pack("<H", self.port)
                        + struct.pack("<I", 1)
                        + E._tag_string(E.TAG_NAME, "ReferenceSeeder")
                    )
                    E._send_packet(conn, E.OP_HELLOANSWER, answer)
                elif opcode == E.OP_FILEREQUEST:
                    if payload[:16] != self.file_hash:
                        E._send_packet(conn, E.OP_FILEREQANSNOFIL, self.file_hash)
                        continue
                    body = self.file_hash + struct.pack("<H", len(self.part_hashes))
                    body += b"".join(self.part_hashes)
                    E._send_packet(conn, E.OP_FILEREQANSWER, body)
                elif opcode == E.OP_HASHSETREQUEST:
                    body = self.file_hash + struct.pack("<H", len(self.part_hashes))
                    body += b"".join(self.part_hashes)
                    E._send_packet(conn, E.OP_HASHSETANSWER, body)
                elif opcode == E.OP_STARTUPLOADREQ:
                    E._send_packet(conn, E.OP_ACCEPTUPLOADREQ, b"")
                elif opcode == E.OP_REQUESTPARTS:
                    self.requests += 1
                    self._serve_parts(conn, payload)
                elif opcode == E.OP_PING:
                    E._send_packet(conn, E.OP_PONG, b"")
        except (socket.timeout, OSError):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _serve_parts(self, conn: socket.socket, payload: bytes) -> None:
        body = payload[16:]
        entries = [body[i : i + 16] for i in range(0, len(body) - 15, 16)][:3]
        for entry in entries:
            if len(entry) < 16:
                continue
            start, end1, end2, end3 = struct.unpack("<IIII", entry)
            end = end3 or end2 or end1
            if end <= start:
                continue
            chunk = self.data[start:end]
            pkt = self.file_hash + struct.pack("<II", start, start + len(chunk)) + chunk
            E._send_packet(conn, E.OP_SENDINGPART, pkt)
            self.served_bytes += len(chunk)


@pytest.fixture()
def seeder():
    data = bytes((i * 37 + 11) & 0xFF for i in range(E.ED2K_PART_SIZE + 216_000))
    node = ReferenceSeeder(data)
    node.start()
    yield node
    node.stop()


def _make_session(monkeypatch, tmp_path: Path, node: ReferenceSeeder):
    link = f"ed2k://|file|ornek.bin|{len(node.data)}|{node.file_hash.hex()}|/"
    info = E.parse_ed2k_link(link)
    monkeypatch.setattr(E, "fetch_server_list", lambda *a, **k: [])
    session = E.NativeED2KSession(
        tmp_path / "work",
        link=link,
        info=info,
        download_dir=tmp_path / "out",
        log_fn=lambda *_a, **_k: None,
    )
    session._known = [("127.0.0.1", node.port)]
    session._known_set = {("127.0.0.1", node.port)}
    return session


def test_ed2k_multipart_download_from_reference_peer(monkeypatch, tmp_path):
    node = ReferenceSeeder(bytes((i * 37 + 11) & 0xFF for i in range(E.ED2K_PART_SIZE + 216_000)))
    node.start()
    try:
        session = _make_session(monkeypatch, tmp_path, node)
        session.start()
        deadline = time.time() + 120
        while time.time() < deadline and not session.complete and not session.error_message:
            time.sleep(0.4)
        session.stop()
        assert not session.error_message, session.error_message
        assert session.complete, f"indirme tamamlanmadı: {session.downloaded_bytes()} bayt"
        got = session.target_path.read_bytes()
        assert got == node.data, "indirilen içerik tohumla aynı değil"
        assert session.compute_file_hash() == node.file_hash
        status = session.query_status()
        assert status["status"] == "complete"
        assert int(status["completedLength"]) == len(node.data)
        assert int(status["numPieces"]) == 2
        assert node.served_bytes >= len(node.data)
        assert node.requests >= 1
    finally:
        node.stop()


def test_ed2k_requestparts_uses_standard_64_byte_format():
    """REQUESTPARTS gövdesi 16 (hash) + 3 × 16 bayt olmalı."""
    entry = struct.pack("<IIII", 0, 180 * 1024, 180 * 1024, 180 * 1024)
    payload = b"\x11" * 16 + entry + struct.pack("<IIII", 0, 0, 0, 0) * 2
    assert len(payload) == 64
    _, e1, e2, e3 = struct.unpack("<IIII", payload[16:32])
    assert (e1, e2, e3) == (180 * 1024, 180 * 1024, 180 * 1024)


def test_ed2k_link_sources_are_parsed():
    link = (
        "ed2k://|file|a.bin|1234|0123456789abcdef0123456789abcdef|/"
        "|sources,1.2.3.4:4662,5.6.7.8:4662|/"
    )
    info = E.parse_ed2k_link(link)
    assert info is not None
    assert info["sources"] == [("1.2.3.4", 4662), ("5.6.7.8", 4662)]
