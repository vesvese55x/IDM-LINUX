"""IDM-Linux Native P2P — sıfırdan yazılmış saf Python eD2K/eMule indirme motoru.

Neden var?
----------
Önceki sürüm eD2K bağlantılarını **aMule** (amuled + amulecmd + telnet EC) gibi
üçüncü sınıf bir araca devrediyordu; indirme IDM'ye hiç uğramıyor, dosya aMule'un
"Incoming" klasörüne düşüyordu. Kullanıcı kararı: "kendi entegrasyonunu sıfırdan
yap … ed2k algılama-indirme-IDM'ye sorunsuz aktarma". Bu modül tam olarak bunu
yapar.

Kapsam (tamamı saf Python, standart kütüphane + yerleşik MD4):
  * ``ed2k://|file|ad|boyut|hash|/`` bağlantı çözümleme
  * Sunucu listesi (server.met, zlib'li ve düz) indirme + yerleşik yedek listeler
  * eD2K sunucu girişi (0xE3 el sıkışması, OP_LOGINREQUEST / OP_IDCHANGE)
  * Kaynak sorgusu: OP_GETSOURCES + OP_GETSOURCES_OBFU
  * Eş protokolü: HELLO/HELLOANSWER, FILEREQUEST/FILEREQANSWER, QUEUEFULL,
    STARTUPLOADREQ / ACCEPTUPLOADREQ, REQUESTPARTS / SENDINGPART,
    HASHSETREQUEST / HASHSETANSWER, END_OF_DOWNLOAD
  * Parça (9.728.000 bayt) ve 180 KB blok düzeyinde indirme, MD4 parça
    doğrulaması, dosya bütünlüğü doğrulaması, dinamik kaynak yenileme
  * IDM köprüsü için ``query_status()`` (aria2 alan adlarıyla uyumlu) — mevcut
    ``/ed2k/<ticket>/<dosya>`` akışı IDM'ye canlı bayt aktarır

Bilinen sınır: Kad ağı ve eMule "obfuscation" (şifreli eş bağlantısı) bu sürümde
yoktur; düz eD2K sunucu + eş protokolü kullanılır (çoğu dosya için yeterlidir).
aMule yolu yalnızca native motor hiç başlatılamazsa yedek olarak korunur.
"""
from __future__ import annotations

import os
import random
import re
import socket
import struct
import threading
import time
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..config import get_cache_dir, setup_logger
from .md4 import md4

log = setup_logger("p2p.ed2k", "daemon.log")

__all__ = [
    "ED2K_PART_SIZE",
    "ED2K_BLOCK_SIZE",
    "NativeED2KSession",
    "parse_ed2k_link",
    "is_ed2k_link",
    "fetch_server_list",
    "BUILTIN_ED2K_SERVERS",
]

# ── protokol sabitleri ───────────────────────────────────────────────────────
PROTO_EDONKEY = 0xE3
PROTO_EMULE = 0xC5
PROTO_PACKED = 0xD4

OP_LOGINREQUEST = 0x01
OP_REJECT = 0x05
OP_GETSOURCES = 0x19
OP_GETSOURCES_OBFU = 0x23
# UDP sunucu sorguları (eMule "global" opcode'ları) — TCP girişi engelliyse
# kaynak bulmanın ikinci yolu; çok daha hızlıdır (tek paket, ~1-2 sn).
OP_GLOBGETSOURCES = 0x9A
OP_GLOBFOUNDSOURCES = 0x9B
OP_IDCHANGE = 0x40
OP_FOUNDSOURCES = 0x42
OP_FOUNDSOURCES_OBFU = 0x44
OP_SERVERLIST = 0x32
OP_GETSERVERLIST = 0x14
OP_QUERY = 0x21
OP_SERVERSTATUS = 0x34
OP_SERVERMESSAGE = 0x38

OP_HELLO = 0x01
OP_HELLOANSWER = 0x4C
OP_FILEREQUEST = 0x58
OP_FILEREQANSWER = 0x59
OP_FILEREQANSNOFIL = 0x48
OP_QUEUEFULL = 0x93
OP_FILESTATUS = 0x50
OP_STARTUPLOADREQ = 0x54
OP_ACCEPTUPLOADREQ = 0x55
OP_REQUESTPARTS = 0x47
OP_SENDINGPART = 0x46
OP_COMPRESSEDPART = 0x40
OP_HASHSETREQUEST = 0x51
OP_HASHSETANSWER = 0x52
OP_END_OF_DOWNLOAD = 0x49
OP_PING = 0x96
OP_PONG = 0x97
OP_OUTOFPARTREQS = 0x95

ED2K_PART_SIZE = 9_728_000
ED2K_BLOCK_SIZE = 180 * 1024  # eMule varsayılan blok boyutu (180 KB)
MAX_PART_REQUESTS = 3          # REQUESTPARTS paketi başına blok sayısı
MAX_OUTSTANDING_BLOCKS = 9

# Tag kimlikleri (eMule)
TAG_NAME = 0x01
TAG_VERSION = 0x11
TAG_PORT = 0x0F
TAG_SOFTWARE = 0x27

# Yerleşik sunucu listesi (server.met erişilemezse kullanılır)
BUILTIN_ED2K_SERVERS: List[Tuple[str, int]] = [
    # 2026-10-29 canlı doğrulama: aşağıdaki altı sunucu OP_LOGINREQUEST'e
    # OP_IDCHANGE ile yanıt verdi (bkz. tests/test_ed2k_framing.py).
    ("91.208.162.182", 4232),
    ("57.131.35.107", 4232),
    ("77.42.68.79", 4232),
    ("143.246.192.192", 4232),
    ("85.17.116.222", 6082),
    ("57.128.161.24", 6666),
    ("45.82.80.155", 4232),
    ("176.123.5.89", 4232),
    ("185.87.186.147", 4232),
    ("91.208.162.10", 4232),
    ("83.97.112.185", 4232),
    ("193.200.155.171", 8583),
    ("185.107.88.112", 4232),
    ("109.123.118.190", 4232),
]

_SERVER_MET_URLS = (
    "https://upd.emule-security.org/server.met",
    "http://upd.emule-security.org/server.met",
    "https://emuling.gitlab.io/server.met",
    "https://raw.githubusercontent.com/Thenuman/ed2k-server-list/main/server.met",
)


def is_ed2k_link(link: str) -> bool:
    return (link or "").strip().lower().startswith("ed2k://|file|")


def parse_ed2k_link(link: str) -> Optional[Dict[str, Any]]:
    """``ed2k://|file|ad|boyut|hash|/`` çözümler."""
    raw = (link or "").strip()
    if not is_ed2k_link(raw):
        return None
    parts = raw.split("|")
    # ['ed2k://', 'file', ad, boyut, hash, '/']
    if len(parts) < 5:
        return None
    name = parts[2].strip()
    try:
        size = int(parts[3].strip())
    except ValueError:
        return None
    digest = parts[4].strip().lower()
    if len(digest) != 32:
        return None
    try:
        file_hash = bytes.fromhex(digest)
    except ValueError:
        return None
    if not name or size <= 0:
        return None
    # isteğe bağlı alanlar: |sources,1.2.3.4:4662,5.6.7.8:4662| , |p=...| , |h=...|
    sources: List[Tuple[str, int]] = []
    for chunk in parts[5:]:
        field = chunk.strip()
        if not field.startswith("sources,"):
            continue
        for item in field[len("sources,"):].split(","):
            item = item.strip()
            if not item or ":" not in item:
                continue
            host, _, port_s = item.rpartition(":")
            try:
                port = int(port_s)
            except ValueError:
                continue
            if host and 0 < port < 65536:
                sources.append((host, port))
    return {
        "name": name,
        "size": size,
        "hash": file_hash,
        "hash_hex": digest,
        "sources": sources,
        "link": raw,
    }


# ── tag yardımcıları ────────────────────────────────────────────────────────
def _tag_string(tag_id: int, value: str) -> bytes:
    raw = value.encode("utf-8", errors="replace")[:250]
    return struct.pack("<BH", 0x01, tag_id) + struct.pack("<H", len(raw)) + raw


def _tag_int(tag_id: int, value: int) -> bytes:
    return struct.pack("<BHI", 0x03, tag_id, int(value) & 0xFFFFFFFF)


def _split_tags(payload: bytes, offset: int) -> List[Tuple[int, Any]]:
    """Eş HELLO yanıtlarındaki tag bloğunu ayrıştırır (bilgi amaçlı)."""
    out: List[Tuple[int, Any]] = []
    try:
        while offset + 3 <= len(payload):
            ttype = payload[offset]
            tag_id = struct.unpack("<H", payload[offset + 1 : offset + 3])[0]
            offset += 3
            if ttype == 0x01:
                if offset + 2 > len(payload):
                    break
                ln = struct.unpack("<H", payload[offset : offset + 2])[0]
                offset += 2
                out.append((tag_id, payload[offset : offset + ln]))
                offset += ln
            elif ttype == 0x03:
                out.append((tag_id, struct.unpack("<I", payload[offset : offset + 4])[0]))
                offset += 4
            elif ttype == 0x02:  # string (eski) / int karışık — 4 bayt
                offset += 4
            else:
                break
    except Exception:
        pass
    return out


# ── sunucu listesi ──────────────────────────────────────────────────────────
#: Yaygın eD2K sunucu portları (sıralama ipucu)
_SERVER_PORT_HINTS = {4232, 4242, 4661, 4662, 5000, 5232, 5555, 6082, 6584, 80, 443, 8080, 447}

_TEXT_SERVER_RE = re.compile(
    r"(\d{1,3}(?:\.\d{1,3}){3})\s*[:\s|,]\s*(\d{1,5})"
)


def _parse_text_server_list(data: bytes) -> List[Tuple[str, int]]:
    """Düz metin sunucu listelerini (``1.2.3.4:4232`` / ``1.2.3.4 4232``) çözer.

    Bazı listeler ``server.met`` yerine düz metin yayınlıyor; eskiden bu veri
    ikili sanılıp SAÇMA adresler üretiliyordu (port 628, ip 53.51.48.49...).
    """
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        return []
    out: List[Tuple[str, int]] = []
    seen = set()
    for m in _TEXT_SERVER_RE.finditer(text):
        ip, port = m.group(1), int(m.group(2))
        if not _plausible_server(ip, port):
            continue
        key = (ip, port)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= 240:
            break
    return out


def _plausible_server(ip: str, port: int) -> bool:
    """Adres gerçekten bir eD2K sunucusu olabilir mi? (saçma ayıklama)"""
    if not (1024 <= int(port) <= 65535):
        return False
    try:
        socket.inet_aton(ip)
    except OSError:
        return False
    first = int(ip.split(".")[0])
    if first in (0, 10, 127, 255) or 224 <= first <= 239:
        return False
    return not ip.startswith(("169.254.", "0."))


def _scan_server_candidates(data: bytes, limit: int = 240) -> List[Tuple[str, int]]:
    """İkili listelerden (ip, port) adaylarını TARAYARAK çıkarır.

    Bazı sunucu listeleri farklı tag sürümleriyle yazıldığı için bayt-bayt
    ayrıştırma kayabiliyor (eski sürümde listenin ilk sunucusundan sonrası
    çöp adreslere dönüşüyordu). Bu tarayıcı, standart ayrıştırmanın kaçırdığı
    geçerli kayıtları kurtarır; her aday kullanılmadan önce bağlantı denenir.
    """
    out: List[Tuple[str, int]] = []
    seen: set = set()
    n = len(data)
    for off in range(0, max(0, n - 11)):
        try:
            ip_int, port = struct.unpack("<IH", data[off: off + 6])
        except struct.error:
            break
        ip = socket.inet_ntoa(struct.pack("<I", ip_int))
        if not _plausible_server(ip, port):
            continue
        tag_count = struct.unpack("<I", data[off + 6: off + 10])[0]
        if tag_count > 0x40:
            continue
        if tag_count:
            first_type = data[off + 10] if off + 10 < n else 0
            if first_type not in (0x01, 0x02, 0x03, 0x04, 0x06, 0x07, 0x11, 0x12):
                continue
        key = (ip, int(port))
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= limit:
            break
    return out


def parse_server_met(data: bytes) -> List[Tuple[str, int]]:
    """server.met içeriğini (ip, port) listesine çevirir (zlib + düz metin destekli)."""
    if not data:
        return []
    printable = sum(1 for b in data[:256] if 32 <= b < 127)
    looks_text = len(data[:256]) > 0 and printable / max(1, len(data[:256])) > 0.85
    if data[:1] != b"\xE0" or looks_text:
        # ikili başlık yok → düz metin liste olabilir
        text_list = _parse_text_server_list(data)
        if text_list:
            return text_list
    if data[0] != 0xE0 and len(data) > 2:
        # bazı listeler doğrudan (başlıksız) gelir; yine de deneyelim
        pass
    idx = 1 if data[0] == 0xE0 else 0
    if idx + 4 > len(data):
        return []
    count = struct.unpack("<I", data[idx : idx + 4])[0]
    idx += 4
    body = data[idx:]
    if body[:1] == b"\xcf":
        try:
            body = zlib.decompress(body[1:])
        except Exception:
            return []
    out: List[Tuple[str, int]] = []
    pos = 0
    for _ in range(min(count, 4096)):
        if pos + 6 > len(body):
            break
        ip_int, port = struct.unpack("<IH", body[pos : pos + 6])
        pos += 6
        if pos + 4 > len(body):
            break
        tag_count = struct.unpack("<I", body[pos : pos + 4])[0]
        pos += 4
        for _t in range(min(tag_count, 32)):
            if pos + 3 > len(body):
                break
            ttype = body[pos]
            pos += 3
            if ttype == 0x01:
                if pos + 2 > len(body):
                    break
                ln = struct.unpack("<H", body[pos : pos + 2])[0]
                pos += 2 + ln
            elif ttype == 0x03:
                pos += 4
            elif ttype == 0x02:
                pos += 4
            else:
                break
        ip = socket.inet_ntoa(struct.pack("<I", ip_int))
        if not _plausible_server(ip, port):
            continue
        out.append((ip, int(port)))
    # Ayrıştırma kaydıysa/az kayıt çıktıysa tarayıcı ile tamamla
    if len(out) < 8:
        known = set(out)
        for cand in _scan_server_candidates(data):
            if cand not in known:
                known.add(cand)
                out.append(cand)
    # Yaygın eD2K sunucu portları öne alınır (tarayıcı artıkları sona düşer)
    def _rank(item: Tuple[str, int]) -> int:
        return 0 if item[1] in _SERVER_PORT_HINTS else 1

    out.sort(key=_rank)
    return out[:240]


def fetch_server_list(timeout: float = 8.0, force: bool = False) -> List[Tuple[str, int]]:
    """Canlı eD2K sunucu listesini indirir (24 saat disk önbelleği + yerleşik yedek)."""
    cache = get_cache_dir(create=True) / "ed2k_servers.json"
    servers: List[Tuple[str, int]] = []
    try:
        import json

        if cache.is_file() and not force:
            blob = json.loads(cache.read_text(encoding="utf-8"))
            if (time.time() - float(blob.get("ts") or 0)) < 86400:
                servers = [(str(ip), int(port)) for ip, port in blob.get("servers") or []]
    except Exception:
        servers = []
    if servers:
        return servers
    for url in _SERVER_MET_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "IDM-Linux-Native/3.10"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read(4 * 1024 * 1024)
            parsed = parse_server_met(data)
            parsed = [(ip, port) for ip, port in parsed if _plausible_server(ip, port)]
            if parsed:
                servers = parsed[:240]
                break
        except Exception:
            continue
    if not servers:
        servers = list(BUILTIN_ED2K_SERVERS)
    try:
        import json

        cache.write_text(
            json.dumps({"ts": time.time(), "servers": servers[:240]}), encoding="utf-8"
        )
    except Exception:
        pass
    return servers


# ── düşük seviye soket yardımcıları ─────────────────────────────────────────
def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except (socket.timeout, OSError):
            return None
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def _send_packet(sock: socket.socket, opcode: int, payload: bytes = b"",
                 first: bool = False, proto: int = PROTO_EDONKEY) -> bool:
    """eD2K TCP paketi yazar.

    Doğru çerçeve (hem sunucu hem eş bağlantısı için geçerli)::

        [0xE3 protokol baytı] [uzunluk:4 LE = opcode + gövde] [opcode:1] [gövde]

    ``first`` parametresi eski imza uyumu için korunmuştur; artık hiçbir etkisi
    yoktur (her paket aynı biçimde çerçevelenir).
    """
    try:
        head = bytes([proto]) + struct.pack("<I", len(payload) + 1) + bytes([opcode])
        sock.sendall(head + payload)
        return True
    except OSError:
        return False


def _recv_packet(sock: socket.socket) -> Optional[Tuple[int, bytes]]:
    """Tek bir eD2K paketi okur (0xE3 düz veya 0xD4 sıkıştırılmış)."""
    head = _recv_exact(sock, 5)
    if head is None:
        return None
    proto = head[0]
    length = struct.unpack("<I", head[1:5])[0]
    if length < 1 or length > 8 * 1024 * 1024:
        return None
    body = _recv_exact(sock, length)
    if body is None:
        return None
    opcode, payload = body[0], body[1:]
    if proto == PROTO_PACKED:
        # eMule sıkıştırılmış paket: opcode AÇIK kalır, yalnızca gövde sıkıştırılır
        try:
            payload = zlib.decompress(payload)
        except zlib.error:
            return None
    return opcode, payload


def udp_get_sources(
    host: str, port: int, file_hash: bytes, size: int, timeout: float = 2.5
) -> List[Tuple[str, int]]:
    """Sunucuya UDP ile kaynak sorar (eMule ``OP_GLOBGETSOURCES``).

    TCP girişi reddeden/geciken sunucularda bile kaynak bulmayı sağlar; tek
    paket gidip tek paket döndüğü için neredeyse bedavadır.
    """
    peers: List[Tuple[str, int]] = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(max(0.8, timeout))
        pkt = bytes([PROTO_EDONKEY, OP_GLOBGETSOURCES]) + file_hash + struct.pack("<I", int(size))
        sock.sendto(pkt, (host, int(port)))
        deadline = time.time() + max(0.8, timeout)
        while time.time() < deadline:
            try:
                data, _addr = sock.recvfrom(8192)
            except socket.timeout:
                break
            except OSError:
                break
            if len(data) < 20 or data[0] != PROTO_EDONKEY or data[1] != OP_GLOBFOUNDSOURCES:
                continue
            if data[2:18] != file_hash:
                continue
            count = data[18]
            idx = 19
            for _ in range(min(count, 400)):
                if idx + 6 > len(data):
                    break
                ip_int, p_port = struct.unpack("<IH", data[idx : idx + 6])
                idx += 6
                ip = socket.inet_ntoa(struct.pack("<I", ip_int))
                if p_port > 0 and not ip.startswith("0.") and (ip, int(p_port)) not in peers:
                    peers.append((ip, int(p_port)))
            if peers:
                break
    except OSError:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return peers


# ── sunucu istemcisi ────────────────────────────────────────────────────────
class ED2KServerClient:
    """Tek bir eD2K sunucusuyla konuşan minimal istemci (kaynak sorgusu için)."""

    def __init__(self, host: str, port: int, listen_port: int = 0) -> None:
        self.host = host
        self.port = int(port)
        self.listen_port = int(listen_port or 0)
        self.sock: Optional[socket.socket] = None
        self.user_hash = os.urandom(16)
        self.client_id = 0
        self.ok = False
        self.message = ""

    def connect(self, timeout: float = 8.0) -> bool:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
            sock.settimeout(timeout)
        except OSError as exc:
            self.message = f"sunucuya bağlanılamadı: {exc}"
            return False
        self.sock = sock
        tags = (
            _tag_string(TAG_NAME, "IDM-Linux")
            + _tag_string(TAG_VERSION, "3.10")
            + _tag_int(TAG_PORT, self.listen_port)
            + _tag_int(TAG_SOFTWARE, 0x22)
        )
        login = self.user_hash + struct.pack("<I", 0) + struct.pack("<H", self.listen_port) + tags
        if not _send_packet(sock, OP_LOGINREQUEST, login, first=True):
            self.message = "giriş paketi gönderilemedi"
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            pkt = _recv_packet(sock)
            if pkt is None:
                break
            opcode, payload = pkt
            if opcode == OP_IDCHANGE and len(payload) >= 4:
                self.client_id = struct.unpack("<I", payload[:4])[0]
                self.ok = True
                self.message = f"sunucu girişi tamam (client id 0x{self.client_id:08X})"
                return True
            if opcode == OP_REJECT:
                self.message = "sunucu bağlantıyı reddetti"
                return False
            if opcode in (OP_SERVERMESSAGE, OP_SERVERSTATUS):
                continue
        self.message = self.message or "sunucu yanıt vermedi"
        return False

    def get_sources(self, file_hash: bytes, size: int, timeout: float = 10.0,
                    obfuscated: bool = False) -> List[Tuple[str, int]]:
        """Sunucudan kaynak listesi ister; yanıt gelir gelmez döner (boşsa da)."""
        if self.sock is None:
            return []
        opcode = OP_GETSOURCES_OBFU if obfuscated else OP_GETSOURCES
        payload = file_hash + struct.pack("<I", int(size))
        if obfuscated:
            payload += os.urandom(4)
        try:
            self.sock.settimeout(max(2.0, min(timeout, 6.0)))
        except OSError:
            pass
        if not _send_packet(self.sock, opcode, payload):
            return []
        deadline = time.time() + timeout
        while time.time() < deadline:
            pkt = _recv_packet(self.sock)
            if pkt is None:
                break
            op, body = pkt
            if op in (OP_FOUNDSOURCES, OP_FOUNDSOURCES_OBFU):
                if len(body) < 17 or body[:16] != file_hash:
                    continue
                peers = self._parse_sources(body)
                return peers
            if op == OP_REJECT:
                return []
            # sunucu mesajları / durum bildirimleri: yut ve devam et
        return []

    @staticmethod
    def _parse_sources(body: bytes) -> List[Tuple[str, int]]:
        count = body[16]
        idx = 17
        peers: List[Tuple[str, int]] = []
        for _ in range(min(count, 400)):
            if idx + 6 > len(body):
                break
            ip_int, port = struct.unpack("<IH", body[idx : idx + 6])
            idx += 6
            ip = socket.inet_ntoa(struct.pack("<I", ip_int))
            # NOT: geri döngü adresleri süzülmez (yerel test eşleri + NAT içi ağlar)
            if port > 0 and not ip.startswith("0."):
                if (ip, int(port)) not in peers:
                    peers.append((ip, int(port)))
        return peers

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


# ── eş bağlantısı ───────────────────────────────────────────────────────────
class _ED2KPeer(threading.Thread):
    """Tek bir eD2K eşinden parça indiren iş parçacığı."""

    def __init__(self, session: "NativeED2KSession", host: str, port: int) -> None:
        super().__init__(name=f"ed2k-peer-{host}:{port}", daemon=True)
        self.session = session
        self.host = host
        self.port = int(port)
        self.sock: Optional[socket.socket] = None
        self.part_index: Optional[int] = None
        self.buf = bytearray()
        self.received: Set[int] = set()
        self.requested: Set[int] = set()
        self.blocks_in_part = 0
        self.outstanding = 0
        self.last_data = time.time()
        self.aborted = False
        self.queue_rank = -1

    # ── parça/blok yerleşimi ────────────────────────────────────────────────
    def _part_len(self) -> int:
        return self.session.part_length(self.part_index or 0)

    def _block_span(self, block: int) -> Tuple[int, int]:
        start = block * ED2K_BLOCK_SIZE
        end = min(start + ED2K_BLOCK_SIZE, self._part_len())
        return start, end

    def _missing_block(self) -> Optional[int]:
        for b in range(self.blocks_in_part):
            if b not in self.received and b not in self.requested:
                return b
        return None

    # ── ana akış ────────────────────────────────────────────────────────────
    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:  # pragma: no cover - beklenmeyen
            log.info("eD2K eş hatası (%s): %s", self.host, exc)
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        self.session._peer_finished(self)

    def _run(self) -> None:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=8.0)
            sock.settimeout(45.0)
        except OSError:
            return
        self.sock = sock
        tags = (
            _tag_string(TAG_NAME, "IDM-Linux")
            + _tag_string(TAG_VERSION, "3.10")
            + _tag_int(TAG_PORT, self.session.listen_port)
            + _tag_int(TAG_SOFTWARE, 0x22)
        )
        hello = (
            self.session.user_hash
            + struct.pack("<I", 0)
            + struct.pack("<H", self.session.listen_port)
            + tags
        )
        if not _send_packet(sock, OP_HELLO, hello, first=True):
            return
        pkt = _recv_packet(sock)
        if not pkt:
            return
        opcode, payload = pkt
        if opcode not in (OP_HELLOANSWER, OP_HELLO):
            return
        # dosya isteği
        if not _send_packet(sock, OP_FILEREQUEST, self.session.file_hash):
            return
        while not self.session.stopping and not self.session.complete:
            pkt = _recv_packet(sock)
            if pkt is None:
                return
            opcode, payload = pkt
            if opcode in (OP_HELLOANSWER, OP_HELLO, OP_FILESTATUS):
                continue
            if opcode == OP_FILEREQANSWER:
                if not _send_packet(sock, OP_STARTUPLOADREQ, self.session.file_hash):
                    return
                self._request_hashset()
                continue
            if opcode == OP_FILEREQANSNOFIL:
                log.info("eD2K eş %s: dosya yok", self.host)
                return
            if opcode == OP_QUEUEFULL:
                self.queue_rank = 0
                # eMule davranışı: sıra dolduysa bekle ve SIRAYA yeniden gir
                time.sleep(6.0)
                if not _send_packet(sock, OP_STARTUPLOADREQ, self.session.file_hash):
                    return
                continue
            if opcode == OP_ACCEPTUPLOADREQ:
                if not self._assign_part():
                    return
                self._request_more()
                continue
            if opcode == OP_SENDINGPART:
                self._on_sending_part(payload)
                self._request_more()
                continue
            if opcode == OP_HASHSETANSWER:
                self.session._set_hashset(payload)
                continue
            if opcode in (OP_END_OF_DOWNLOAD, OP_OUTOFPARTREQS):
                if self.part_index is not None and not self._part_complete():
                    # parçayı geri ver, yeniden dene
                    self.session._release_part(self.part_index)
                    self.part_index = None
                continue
            if opcode == OP_PING:
                _send_packet(sock, OP_PONG)
                continue

    def _request_hashset(self) -> None:
        if self.sock is not None and not self.session.has_hashset:
            _send_packet(self.sock, OP_HASHSETREQUEST, self.session.file_hash)

    def _assign_part(self) -> bool:
        idx = self.session._assign_part()
        if idx is None:
            return False
        self.part_index = idx
        self.buf = bytearray(self.session.part_length(idx))
        self.received.clear()
        self.requested.clear()
        self.outstanding = 0
        self.blocks_in_part = max(1, (len(self.buf) + ED2K_BLOCK_SIZE - 1) // ED2K_BLOCK_SIZE)
        self.last_data = time.time()
        return True

    def _request_more(self) -> None:
        if self.sock is None or self.part_index is None:
            return
        while self.outstanding < MAX_OUTSTANDING_BLOCKS:
            block = self._missing_block()
            if block is None:
                break
            start, end = self._block_span(block)
            # eş protokolünde ofsetler DOSYA başına göredir (parça başına değil)
            base = (self.part_index or 0) * ED2K_PART_SIZE
            start += base
            end += base
            # REQUESTPARTS (eMule biçimi): hash(16) + 3 × (başlangıç + 3 bitiş ucu)
            # Kullanılmayan iki yuva sıfırlanır; eşler bunları yok sayar.
            entry = struct.pack("<IIII", start, end, end, end)
            payload = self.session.file_hash + entry + struct.pack("<IIII", 0, 0, 0, 0) * 2
            if not _send_packet(self.sock, OP_REQUESTPARTS, payload):
                return
            self.requested.add(block)
            self.outstanding += 1

    def _on_sending_part(self, payload: bytes) -> None:
        if len(payload) < 24:
            return
        start, end = struct.unpack("<II", payload[16:24])
        data = payload[24:]
        if self.part_index is None:
            return
        part_start = self.part_index * ED2K_PART_SIZE
        local = start - part_start
        if local < 0 or local >= len(self.buf):
            return
        if local + len(data) > len(self.buf):
            data = data[: len(self.buf) - local]
        self.buf[local : local + len(data)] = data
        block = local // ED2K_BLOCK_SIZE
        self.received.add(block)
        self.outstanding = max(0, self.outstanding - 1)
        self.last_data = time.time()
        if self._part_complete():
            self.session._complete_part(self.part_index, bytes(self.buf))
            # parça bitti: AYNI yükleme oturumunda sıradaki parçaya geç
            self.part_index = None
            if self._assign_part():
                self._request_more()

    def _part_complete(self) -> bool:
        return len(self.received) >= self.blocks_in_part


# ── oturum ──────────────────────────────────────────────────────────────────
class NativeED2KSession:
    """Saf Python eD2K indirme oturumu (IDM köprüsü uyumlu durum çıktısı)."""

    MAX_PEERS = 24
    MAX_SERVERS_TO_QUERY = 24

    def __init__(
        self,
        work_dir: Path,
        link: str = "",
        *,
        info: Optional[Dict[str, Any]] = None,
        download_dir: Optional[Path] = None,
        max_peers: int = MAX_PEERS,
        log_fn: Any = None,
    ) -> None:
        parsed = info or parse_ed2k_link(link)
        if not parsed:
            raise ValueError("Geçersiz eD2K bağlantısı")
        self.link = parsed.get("link") or link
        self.file_name = parsed["name"]
        self.total_size = int(parsed["size"])
        # v3.11.0 KRİTİK DÜZELTME: parse_ed2k_link 'hash'i STR döndürür (regex grubu) ama
        # bu alan bytes olmalı. Eski akışta str olduğu için:
        #   • udp_get_sources: bytes([PROTO]) + file_hash -> TypeError ('str to bytes')
        #     -> TÜM UDP kaynak sorguları sessizce 0 kaynak döndürüyordu!
        #   • data[2:18] != file_hash -> bytes != str -> yanıt EŞLEŞME diye çöpe gidiyordu
        #   • _ED2KPeer OP_FILEREQUEST paketi -> TypeError -> eş aktarımı hiç başlamıyordu
        # Sonuç: eD2K indirmeleri KÖKTEN ölüydü (kullanıcı: "eMule entegrasyonunda sorun").
        # Hex-string -> bytes dönüşümü tek noktadan yapılır.
        _raw_hash = parsed["hash"]
        if isinstance(_raw_hash, str):
            self.file_hash: bytes = bytes.fromhex(_raw_hash.strip())
        else:
            self.file_hash = bytes(_raw_hash)
        if len(self.file_hash) != 16:
            raise ValueError(f"eD2K hash 16 bayt olmalı, gelen {len(self.file_hash)}")
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.work_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        target_dir = Path(download_dir) if download_dir else self.data_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        self.target_path = target_dir / _safe_name(self.file_name)
        self.part_size = ED2K_PART_SIZE
        self.num_parts = max(1, (self.total_size + ED2K_PART_SIZE - 1) // ED2K_PART_SIZE)
        self.has_parts = bytearray(self.num_parts)
        self._inflight: Set[int] = set()
        self._lock = threading.RLock()
        self._peers: List[_ED2KPeer] = []
        self._peer_keys: Set[Tuple[str, int]] = set()
        self._known: List[Tuple[str, int]] = []
        self._known_set: Set[Tuple[str, int]] = set()
        self._queried_servers: Set[Tuple[str, int]] = set()
        self._last_gather = 0.0
        self._hashset: List[bytes] = []
        self.complete = False
        self.stopping = False
        self.paused = False  # v3.13.0: IDM iptal/duraklatma denetimi
        # v3.13.0: köprü istemci sayacı (IDM iptal -> arka plan SIFIR)
        self._bridge_clients = 0
        self._last_client_ts = 0.0
        self._cancel_watch_started = False
        self._cancel_watch_run = True
        self.CLIENT_GONE_GRACE_SEC = 60.0
        self.error_message = ""
        self.user_hash = os.urandom(16)
        self.listen_port = 0
        self.download_speed = 0
        self._speed_samples: List[Tuple[float, int]] = []
        self._log = log_fn or (lambda *_a, **_k: None)
        self.ready = threading.Event()
        self.started = False
        self.started_at = time.time()
        self._server: Optional[ED2KServerClient] = None
        self._threads: List[threading.Thread] = []
        self.backend = "native-ed2k"
        self._downloads_bytes = 0
        # bağlantıda doğrudan verilen kaynaklar (|sources,IP:PORT|) anında kullanılır
        for ip, port in (parsed.get("sources") or []):
            if (ip, port) not in self._known_set:
                self._known_set.add((ip, port))
                self._known.append((ip, port))
        self._prepare_file()

    # ── meta uyumluluğu (IDM köprüsü serve_torrent_over_http kullanır) ───────
    @property
    def name(self) -> str:
        return self.file_name

    @property
    def is_multi_file(self) -> bool:
        return False

    @property
    def piece_length(self) -> int:
        return self.part_size

    @property
    def web_seeds(self) -> List[str]:
        return []

    @property
    def output_filename(self) -> str:
        return self.file_name

    @property
    def meta(self) -> "_ED2KMeta":
        cached = getattr(self, "_meta_obj", None)
        if cached is None:
            cached = _ED2KMeta(self)
            self._meta_obj = cached
        return cached

    @property
    def rpc_port(self) -> int:
        return self.listen_port or 1

    @property
    def has_hashset(self) -> bool:
        return bool(self._hashset)

    # ── hazırlık ────────────────────────────────────────────────────────────
    def _prepare_file(self) -> None:
        try:
            self.target_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.target_path.exists():
                self.target_path.touch()
            if self.target_path.stat().st_size < self.total_size:
                with self.target_path.open("r+b") as fh:
                    fh.truncate(self.total_size)
        except OSError as exc:
            self.error_message = f"hedef dosya hazırlanamadı: {exc}"

    def part_length(self, index: int) -> int:
        if index >= self.num_parts:
            return 0
        if index == self.num_parts - 1:
            return self.total_size - ED2K_PART_SIZE * (self.num_parts - 1)
        return ED2K_PART_SIZE

    def downloaded_bytes(self) -> int:
        total = 0
        for i in range(self.num_parts):
            if self.has_parts[i]:
                total += self.part_length(i)
        return total

    def _contiguous_parts(self) -> int:
        n = 0
        for b in self.has_parts:
            if not b:
                break
            n += 1
        return n

    # ── başlatma / durdurma ─────────────────────────────────────────────────
    def ensure_started(self) -> None:
        self.start()

    def start(self) -> None:
        with self._lock:
            if self.started:
                return
            self.started = True
        t = threading.Thread(target=self._run, name="ed2k-native", daemon=True)
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        self.stopping = True
        self._cancel_watch_run = False  # v3.13.0: izleyiciyi bitir
        with self._lock:
            peers = list(self._peers)
        for p in peers:
            p.aborted = True
        if self._server is not None:
            self._server.close()
        self.ready.set()

    # -- v3.13.0: IDM İPTAL / DEVAM -------------------------------------------
    def pause(self) -> None:
        """IDM istemcisi koptu: eD2K kaynak/eş trafiğini ANINDA keser.

        Arka planda indirme ASLA sürmez; bilet korunur, IDM yeniden bağlanınca
        resume() ile kaldığı yerden devam eder."""
        if self.stopping:
            return
        self.paused = True
        with self._lock:
            peers = list(self._peers)
        for p in peers:
            p.aborted = True
        if self._server is not None:
            try:
                self._server.close()
            except Exception:
                pass
            self._server = None
        self._log("eD2K: IDM istemcisi ayrıldı -> oturum DURAKLATILDI (arka plan indirmesi yok)")

    def resume(self) -> None:
        """IDM yeniden bağlandı: kaynak toplama ve eş başlatma kaldığı yerden sürer."""
        if not self.paused or self.stopping:
            return
        self.paused = False
        self._last_gather = 0.0
        self._log("eD2K: IDM yeniden bağlandı -> oturum DEVAM EDİYOR")

    # -- v3.13.0: IDM İPTAL İZLEYİCİ (köprü HTTP istemci takibi) ---------------
    def note_client_connect(self) -> None:
        self._bridge_clients += 1
        self._last_client_ts = time.time()
        if self.paused:
            self.resume()

    def note_client_disconnect(self) -> None:
        self._bridge_clients = max(0, self._bridge_clients - 1)
        self._last_client_ts = time.time()
        if self._bridge_clients == 0:
            self._ensure_cancel_watch()

    def _ensure_cancel_watch(self) -> None:
        if self._cancel_watch_started or not self._cancel_watch_run:
            return
        self._cancel_watch_started = True

        def _watch() -> None:
            while self._cancel_watch_run:
                time.sleep(5.0)
                idle_for = time.time() - self._last_client_ts
                if self._bridge_clients == 0 and not self.paused and idle_for >= self.CLIENT_GONE_GRACE_SEC:
                    self.pause()
                    self._log("eD2K: IDM istemcisi %d sn diri yok -> oturum DURAKLATILDI" % int(idle_for))

        import threading as _th

        _th.Thread(target=_watch, name=f"ed2k-cancel-{id(self):x}", daemon=True).start()

    # ── parça havuzu ────────────────────────────────────────────────────────
    def _assign_part(self) -> Optional[int]:
        with self._lock:
            for idx in range(self.num_parts):
                if self.has_parts[idx] or idx in self._inflight:
                    continue
                self._inflight.add(idx)
                return idx
            return None

    def _release_part(self, index: int) -> None:
        with self._lock:
            self._inflight.discard(index)

    def _complete_part(self, index: int, data: bytes) -> None:
        with self._lock:
            self._inflight.discard(index)
        expected_len = self.part_length(index)
        if len(data) != expected_len:
            self._release_part(index)
            return
        if self._hashset:
            digest = _hashset_entry(self._hashset, index)
            if digest and md4(data) != digest:
                log.info("eD2K parça %d MD4 uyuşmadı — yeniden indirilecek", index)
                return
        try:
            with self.target_path.open("r+b") as fh:
                fh.seek(index * ED2K_PART_SIZE)
                fh.write(data)
        except OSError as exc:
            self.error_message = f"parça diske yazılamadı: {exc}"
            return
        self.has_parts[index] = 1
        self._downloads_bytes += len(data)
        self._log(f"eD2K parça {index + 1}/{self.num_parts} tamam")
        if all(self.has_parts):
            self._finish()

    def _set_hashset(self, payload: bytes) -> None:
        if len(payload) < 18:
            return
        count = struct.unpack("<H", payload[16:18])[0]
        hashes = [payload[18 + i * 16 : 18 + (i + 1) * 16] for i in range(count)]
        if hashes:
            self._hashset = hashes

    def compute_file_hash(self) -> bytes:
        """eD2K dosya hash'i: tek parçaysa parçanın MD4'ü, çok parçalıysa
        parça MD4'lerinin birleşiminin MD4'ü (eMule tanımı)."""
        try:
            with self.target_path.open("rb") as fh:
                if self.num_parts <= 1:
                    return md4(fh.read())
                part_hashes: List[bytes] = []
                for idx in range(self.num_parts):
                    want = self.part_length(idx)
                    chunk = fh.read(want)
                    if len(chunk) != want:
                        return b""
                    part_hashes.append(md4(chunk))
        except OSError:
            return b""
        return md4(b"".join(part_hashes)) if part_hashes else b""

    def _finish(self) -> None:
        # uçtan uca bütünlük: eD2K hash'i bağlantıdaki hash ile aynı olmalı
        digest = self.compute_file_hash()
        if digest and digest != self.file_hash:
            self.error_message = "Dosya bütünlüğü doğrulanamadı (MD4 uyuşmadı)."
            self._log(self.error_message)
            return
        self.complete = True
        self._log(f"eD2K indirme tamamlandı: {self.file_name}")

    def _peer_finished(self, peer: _ED2KPeer) -> None:
        with self._lock:
            if peer in self._peers:
                self._peers.remove(peer)
            self._peer_keys.discard((peer.host, peer.port))
            if peer.part_index is not None:
                self._inflight.discard(peer.part_index)
                peer.part_index = None

    # ── ana döngü ───────────────────────────────────────────────────────────
    def _run(self) -> None:
        try:
            self._log(
                f"eD2K motoru başlıyor: {self.file_name} ({self.total_size} bayt, "
                f"{self.num_parts} parça)"
            )
            servers = fetch_server_list()
            self._log(f"eD2K sunucu listesi: {len(servers)} sunucu")
            self.ready.set()
            # kaynak toplama ayrı iş parçacığında: ana döngü (ve IDM akışı) beklemez
            threading.Thread(
                target=self._gather_loop, args=(servers,), name="ed2k-sources", daemon=True
            ).start()
            while not self.stopping and not self.complete:
                # v3.13.0: DURAKLATILMIŞ -> sıfır ağ trafiği
                if self.paused:
                    time.sleep(1.0)
                    continue
                self._spawn_peers()
                self._update_speed()
                time.sleep(1.0)
        except Exception as exc:  # pragma: no cover
            self.error_message = f"eD2K motoru hatası: {exc}"
            self._log(self.error_message)
        finally:
            self.ready.set()

    def _gather_loop(self, servers: Sequence[Tuple[str, int]]) -> None:
        """Kaynakları düzenli aralıklarla tazeler (ana döngüyü bloke etmeden)."""
        current = list(servers)
        started = time.time()
        while not self.stopping and not self.complete:
            if self.paused:  # v3.13.0: duraklatılmışken kaynak tarama YOK
                for _ in range(10):
                    if self.stopping or self.complete or not self.paused:
                        break
                    time.sleep(1.0)
                continue
            self._gather_sources(current, force=True)
            if len(self._known) < 8:
                # kaynak az/ yok: sunucu listesini tazele
                try:
                    current = fetch_server_list() or current
                except Exception:
                    pass
            for _ in range(25):
                if self.stopping or self.complete:
                    return
                time.sleep(1.0)
                # v3.10.1: 2.5 dakika boyunca HİÇ kaynak bulunamadıysa dürüst hata —
                # IDM'de sonsuza kadar "%0" beklemek yerine nedenini söyle.
                if (
                    not self._known
                    and not self.downloaded_bytes()
                    and (time.time() - started) > 150.0
                    and not self.error_message
                ):
                    self.error_message = (
                        "eD2K: dosya için ağda kaynak (tohum) bulunamadı. Dosya artık "
                        "paylaşılmıyor olabilir; bağlantı geçerli ama indirilecek kaynak yok."
                    )
                    self._log(self.error_message)
                    return

    def _gather_sources(self, servers: Sequence[Tuple[str, int]], force: bool = False) -> None:
        """Sunuculardan kaynak toplar. v3.11.0 İKİ AŞAMALI PARALEL strateji:

        Eski akış 24 sunucuyu SIRALI dolaşıyordu (bağlantı 5 sn + TCP sorgu 6 sn +
        obf. 5 sn + UDP 2.5 sn = sunucu başına ~18.5 sn → TUR ~7 DAKİKA!). Artık:
          AŞAMA 1: UDP global kaynak sorgusu TÜM sunuculara PARALEL (8 işçi) —
                   bağlantı gerektirmez; 3-5 sn içinde ilk kaynaklar eld edilir.
          AŞAMA 2: TCP bağlantı + get_sources PARALEL (4 işçi) — derin sonuç + sunucu
                   mesajı; yeterli kaynak toplanınca erken durur.
        (Kullanıcı şikâyeti: docuwiki ed2k linkleri kaynak beklerken dakikalarca ölüyordu.)
        """
        now = time.time()
        if not force and (now - self._last_gather) < 20.0:
            return
        self._last_gather = now
        import concurrent.futures as _cf

        def _add_peers(peers: Sequence[Tuple[str, int]]) -> int:
            # v3.11.0: paralel TCP işçileri aynı anda çağırabilir -> kilitle
            added = 0
            with self._lock:
                for ip, p_port in peers or []:
                    if self.stopping or self.complete:
                        return added
                    if (ip, p_port) not in self._known_set:
                        self._known_set.add((ip, p_port))
                        self._known.append((ip, p_port))
                        added += 1
            return added

        target = servers[: self.MAX_SERVERS_TO_QUERY]
        found_new = 0

        # ── AŞAMA 1: PARALEL UDP (bağlantısız, hızlı) ────────────────────────
        if target and not self.stopping and not self.complete:
            with _cf.ThreadPoolExecutor(max_workers=min(8, len(target))) as ex:
                futs = {
                    ex.submit(udp_get_sources, host, port, self.file_hash, self.total_size, 2.5): (host, port)
                    for host, port in target
                }
                for fu in _cf.as_completed(futs):
                    if self.stopping or self.complete:
                        break
                    try:
                        found_new += _add_peers(fu.result(timeout=3.0))
                    except Exception:
                        pass
            if found_new:
                self._log(f"eD2K UDP taraması: +{found_new} eş (toplam {len(self._known)})")

        # ── AŞAMA 2: PARALEL TCP (derin sorgu) ───────────────────────────────
        if found_new >= 40:
            # UDP yeterince kaynak verdi; TCP turuna gerek yok (hız!)
            if found_new:
                self._log(f"eD2K kaynak bulundu: +{found_new} eş (toplam {len(self._known)})")
            return
        pending = [(h, p) for h, p in target if (h, p) not in self._queried_servers]
        if pending and not self.stopping and not self.complete:

            def _query_server(hp: Tuple[str, int]) -> int:
                host, port = hp
                if self.stopping or self.complete:
                    return 0
                client = ED2KServerClient(host, port, self.listen_port)
                try:
                    if not client.connect(timeout=5.0):
                        self._queried_servers.add(hp)
                        return 0
                    self._server = client
                    self._log(f"{host}:{port} — {client.message}")
                    peers = client.get_sources(self.file_hash, self.total_size, timeout=6.0)
                    if not peers:
                        peers = client.get_sources(
                            self.file_hash, self.total_size, timeout=5.0, obfuscated=True
                        )
                    self._queried_servers.add(hp)
                    return _add_peers(peers)
                finally:
                    client.close()

            with _cf.ThreadPoolExecutor(max_workers=4) as ex:
                futs = [ex.submit(_query_server, hp) for hp in pending[: self.MAX_SERVERS_TO_QUERY]]
                for fu in _cf.as_completed(futs):
                    if self.stopping or self.complete:
                        break
                    try:
                        found_new += fu.result(timeout=20.0)
                    except Exception:
                        pass
            # TCP turu toplamı zaten _known'a yazdı; found_new UDP+TCP birleşik
            if found_new:
                self._log(f"eD2K kaynak bulundu: +{found_new} eş (toplam {len(self._known)})")
            elif self._queried_servers and not self._known:
                self._log(
                    "eD2K: sunuculara giriş yapıldı ama bu dosya için kaynak yok "
                    "(dosya ağda paylaşılmıyor olabilir; birkaç dakikada bir yeniden denenir)"
                )

    def _spawn_peers(self) -> None:
        if self.paused:
            return
        need = min(self.MAX_PEERS, len(self._known)) - len(self._peers)
        if need <= 0:
            return
        for host, port in self._known:
            if need <= 0 or self.stopping or self.complete:
                return
            key = (host, port)
            if key in self._peer_keys:
                continue
            self._peer_keys.add(key)
            peer = _ED2KPeer(self, host, port)
            with self._lock:
                self._peers.append(peer)
            peer.start()
            need -= 1

    def _update_speed(self) -> None:
        now = time.time()
        done = self.downloaded_bytes()
        self._speed_samples.append((now, done))
        while len(self._speed_samples) > 2 and now - self._speed_samples[0][0] > 8.0:
            self._speed_samples.pop(0)
        if len(self._speed_samples) >= 2:
            t0, b0 = self._speed_samples[0]
            dt = max(0.3, now - t0)
            self.download_speed = int(max(0, (done - b0) / dt))

    # ── durum (IDM köprüsü + GUI) ───────────────────────────────────────────
    def query_status(self) -> Dict[str, Any]:
        completed = self.downloaded_bytes()
        bits = bytes(self.has_parts)
        nbytes = (len(bits) + 7) // 8
        out = bytearray(nbytes)
        for i, b in enumerate(bits):
            if b:
                out[i // 8] |= 1 << (7 - (i % 8))
        state = "complete" if self.complete else ("error" if self.error_message else "active")
        with self._lock:
            conns = len(self._peers)
        return {
            "gid": self.file_hash.hex()[:16],
            "status": state,
            "totalLength": str(self.total_size),
            "completedLength": str(completed),
            "downloadSpeed": str(self.download_speed),
            "uploadSpeed": "0",
            "connections": str(conns),
            "numPieces": str(self.num_parts),
            "pieceLength": str(self.part_size),
            "bitfield": out.hex(),
            "files": [
                {
                    "index": "1",
                    "path": str(self.target_path),
                    "length": str(self.total_size),
                    "completedLength": str(completed),
                    "selected": "true",
                }
            ],
            "dir": str(self.target_path.parent),
            "bittorrent": {"info": {"name": self.file_name}, "mode": "single"},
            "errorMessage": self.error_message,
            "sources": len(self._known),
        }

    # köprü tarafının beklediği isim
    def status(self) -> Dict[str, Any]:
        return self.query_status()

    def wait_ready(self, timeout: float = 15.0) -> bool:
        return self.ready.wait(timeout)


class _ED2KMeta:
    """``serve_torrent_over_http`` uyumu için ince meta sarmalayıcısı.

    Köprü kodu (torrent motoruyla paylaşılır) bu nesnenin alanlarını OKUR ve
    bazılarını YAZAR (ör. meta adı güncellenir). Bu yüzden property yerine
    sade, yazılabilir alanlar kullanılır.
    """

    def __init__(self, session: NativeED2KSession) -> None:
        self._s = session
        self.name = session.file_name
        self.total_size = session.total_size
        self.is_multi_file = False
        self.piece_length = session.part_size
        self.web_seeds: List[str] = []
        self.file_count = 1

    @property
    def output_filename(self) -> str:
        return self.name or self._s.file_name

    def piece_size(self, index: int) -> int:
        return self._s.part_length(index)


def _hashset_entry(hashes: List[bytes], index: int) -> bytes:
    """Hashset tek hash içeriyorsa tüm parçalar aynı karmaya sahiptir (eMule kuralı)."""
    if not hashes:
        return b""
    if len(hashes) == 1:
        return hashes[0]
    if index < len(hashes):
        return hashes[index]
    return hashes[-1]


def _safe_name(name: str) -> str:
    bad = '/\\\x00:*?"<>|'
    out = "".join("_" if ch in bad else ch for ch in (name or "ed2k_dosya")).strip()
    return out[:200] or "ed2k_dosya"
