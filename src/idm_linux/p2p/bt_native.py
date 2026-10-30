"""Saf Python BitTorrent motoru — sıfırdan yazıldı.

Neden kendi motorumuz?
----------------------
IDM-Linux "hiçbir üçüncü taraf istemci kurmadan" torrent indirebilmeliydi. Bu
modül BitTorrent protokolünün tamamını (BEP 3 bencode, BEP 23 compact eşler,
BEP 6 have/have-all, BEP 9 ut_metadata, BEP 10 uzantı el sıkışması, BEP 5 DHT,
BEP 15 UDP tracker, BEP 19 web seed) doğrudan konuşur. Ne ``aria2c`` ne de
``libtorrent`` gerekir.

Tasarım
-------
* :class:`PieceManager` — parça sahipliği, uçuştaki parçalar, blok talepleri.
  Konum akışı için SIRALI (streaming) öncelik, eş yoksa en küçük indeks.
* :class:`Storage` — çok dosyalı torrentlerde sanal adres uzayını gerçek
  dosyalara eşler; ön tahsis yapar (IDM anında gerçek bayt görür).
* :class:`PeerConn` — kalıcı eş teli: el sıkışması, bitfield, interested/
  unchoke, blok talepleri, SHA1 parça doğrulaması, ut_metadata.
* :class:`NativeTorrentSession` — oturum: tracker/DHT eş keşfi, dinleme
  soketi, hız ölçümü ve **aria2 uyumlu** ``status()`` sözlüğü. Böylece
  mevcut IDM köprüsü (`serve_torrent_over_http`) tek satır değişmeden çalışır.

Doğruluk kuralları: indirilen her parça SHA1 ile doğrulanır; doğrulanmamış tek
bayt dosyaya yazılmaz. Magnet bağlantısında meta veri sha1'i info-hash ile
eşleşmezse meta yok sayılır (zehirli meta veri saldırısına karşı).
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .bencode import bdecode, bdecode_prefix, bencode, bdecode_with_spans
from .dht import DHTNode
from .tracker import announce_all, normalize_trackers

log = logging.getLogger("idm_linux.p2p.bt")

PROTOCOL = b"BitTorrent protocol"
BLOCK_SIZE = 16384            # standart blok boyu (16 KB)
# v3.14.0: GLOBAL BLOK KOORDİNASYONU — kök-neden düzeltmesi.
# Kullanıcı ölçümü: "ilk 100 sn 9.7 MB/s, sonra 0.4 MB/s'ye düşüyor, IDM saniyelerce
# bekliyor". Eski tasarımda bir parçayı TEK eş indiriyordu (bloklar eş-başına
# ayrılıyordu); o eş sessizleştiğinde parçanın blokları 90 sn kilitli kalıyor ve
# IDM akışı (kesintisiz bayt sınırı) DURUYORDU. Artık blok sahipliği GLOBALDİR:
# frontier parçasının blokları TÜM boş eşlere paylaştırılır (şeritleme/stripping),
# 8 sn yanıt gelmeyen talepler ana döngüde otomatik serbest kalır. Sonuç: parça
# hızı = eşlerin TOPLAM hızı; zombi parça = imkânsız.
MAX_PEERS_DEFAULT = 80        # eşzamanlı eş teli üst sınırı (96 -> 80: daha hafif, aynı hız)
REQUEST_PIPELINE = 48         # eş başına uçuştaki blok talebi (48 x 16KB = 768 KB/eş)
REQUEST_BLOCK_TIMEOUT = 8.0   # GLOBAL blok sahipliği zaman aşımı — sessiz eş bloğu ANINDA serbest
MAX_BUFFERED_BYTES = 96 * 1024 * 1024   # doğrulanmamış blok tamponu üst sınırı (RAM güvenliği)
STREAM_WINDOW = 32            # frontier öncelik penceresi (parça adedi)
STREAM_DEPTH = 128            # ardışık indirme derinliği (parça adedi)
FRONTIER_BLOCK_TIMEOUT = 4.0  # frontier bölgesi sahiplik zaman aşımı (seed'ler kıt — hızlı geri dönüşüm)
METADATA_PIECE = 16384        # ut_metadata parça boyu (sabit)
MAX_METADATA_SIZE = 8 * 1024 * 1024   # güvenlik sınırı (8 MB meta veri)
UT_METADATA_OUR_ID = 1        # BEP 10: bizim ut_metadata uzantı kimliğimiz
UT_PEX_OUR_ID = 2             # v3.11.0 BEP 11: bizim ut_pex (eş değişimi) uzantı kimliğimiz
MAX_METADATA_PIECES = MAX_METADATA_SIZE // METADATA_PIECE
SNAPSHOT_INTERVAL = 1.0       # durum/hız güncelleme aralığı

#: Her torrent'e eklenen genel tracker'lar (torrentin kendi listesi önce gelir).
DEFAULT_TRACKERS: List[str] = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://explodie.org:6969/announce",
    "http://tracker.openbittorrent.com:80/announce",
    # v3.11.0: UDP YASAKLI ağlar için HTTP/HTTPS açık tracker'lar — Linux Mint resmi
    # torrenti TEK udp://tracker.opentrackr.org taşıyor; kullanıcının güvenlik duvarı
    # UDP'yi kapatırsa sıfır eş = torrent asla başlamıyor ("birkaç saat bekliyor" şikâyeti).
    "https://tracker.gbitt.info:443/announce",
    "http://tracker.gbitt.info:80/announce",
    "https://tracker.lilithraws.org:443/announce",
    "http://open.acgnxtracker.com:80/announce",
    "https://opentracker.io:443/announce",
    "http://opentracker.io:6969/announce",
    "http://tracker.files.fm:6969/announce",
]


# ─────────────────────────────────────────────────────────────────────────────
# Veri modeli
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class TorrentFile:
    """Torrent içindeki tek bir dosya (offset: sanal adres uzayındaki başı)."""

    path: str
    length: int
    offset: int = 0


@dataclass
class TorrentMeta:
    """Ayrıştırılmış torrent meta verisi."""

    info_hash: bytes
    name: str
    piece_length: int
    pieces: List[bytes] = field(default_factory=list)
    files: List[TorrentFile] = field(default_factory=list)
    total_size: int = 0
    is_multi_file: bool = False
    trackers: List[str] = field(default_factory=list)
    web_seeds: List[str] = field(default_factory=list)
    private: bool = False
    info_bytes: bytes = b""

    @property
    def num_pieces(self) -> int:
        return len(self.pieces)

    def piece_size(self, index: int) -> int:
        """Parçanın gerçek bayt uzunluğu (son parça kısadır)."""
        if index < 0 or index >= len(self.pieces):
            return 0
        start = index * self.piece_length
        return max(0, min(self.piece_length, self.total_size - start))

    @property
    def output_filename(self) -> str:
        return self.name if not self.is_multi_file else f"{self.name}.tar"


def _decode_text(raw: Any, fallback: str = "") -> str:
    if isinstance(raw, bytes):
        for enc in ("utf-8", "iso-8859-9", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        return raw
    return fallback


def _safe_relpath(path: str) -> str:
    """Torrent içi yolu güvenli hale getirir ('..' ve mutlak yollar atılır)."""
    parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if not parts:
        parts = ["download.bin"]
    return "/".join(parts)


def parse_torrent_bytes(raw: bytes) -> TorrentMeta:
    """``.torrent`` baytlarını :class:`TorrentMeta`'ya çevirir."""
    if not raw:
        raise ValueError("boş torrent verisi")
    data, spans, _end = bdecode_with_spans(raw)
    if not isinstance(data, dict) or b"info" not in data:
        raise ValueError("geçersiz torrent dosyası (info sözlüğü yok)")
    istart, iend = spans[b"info"]
    info_bytes = raw[istart:iend]
    info_hash = hashlib.sha1(info_bytes).digest()
    info = data[b"info"]
    if not isinstance(info, dict):
        raise ValueError("geçersiz torrent (info sözlük değil)")

    name = _decode_text(info.get(b"name.utf-8") or info.get(b"name"), "torrent")
    piece_length = int(info.get(b"piece length") or 0)
    blob = info.get(b"pieces") or b""
    pieces = [blob[i:i + 20] for i in range(0, len(blob) - 19, 20)]

    files: List[TorrentFile] = []
    is_multi = b"files" in info
    total = 0
    if is_multi:
        for item in info.get(b"files") or []:
            if not isinstance(item, dict):
                continue
            length = int(item.get(b"length") or 0)
            path_parts = item.get(b"path.utf-8") or item.get(b"path") or []
            rel = _safe_relpath("/".join(_decode_text(p) for p in path_parts))
            files.append(TorrentFile(path=rel, length=length, offset=total))
            total += length
    else:
        length = int(info.get(b"length") or 0)
        files.append(TorrentFile(path=_safe_relpath(name), length=length, offset=0))
        total = length

    trackers: List[str] = []
    announce = _decode_text(data.get(b"announce"))
    if announce:
        trackers.append(announce)
    for tier in data.get(b"announce-list") or []:
        if isinstance(tier, list):
            for tr in tier:
                text = _decode_text(tr)
                if text:
                    trackers.append(text)
        else:
            text = _decode_text(tier)
            if text:
                trackers.append(text)

    web_seeds: List[str] = []
    url_list = data.get(b"url-list")
    if isinstance(url_list, bytes):
        web_seeds.append(_decode_text(url_list))
    elif isinstance(url_list, list):
        for item in url_list:
            text = _decode_text(item)
            if text:
                web_seeds.append(text)

    return TorrentMeta(
        info_hash=info_hash,
        name=name or "torrent",
        piece_length=piece_length,
        pieces=pieces,
        files=files,
        total_size=total,
        is_multi_file=is_multi,
        trackers=normalize_trackers(trackers),
        web_seeds=web_seeds,
        private=bool(info.get(b"private")),
        info_bytes=info_bytes,
    )


def parse_magnet(uri: str) -> Dict[str, Any]:
    """Magnet bağlantısını çözer → {info_hash, name, trackers, web_seeds}."""
    import urllib.parse

    text = (uri or "").strip()
    if not text.lower().startswith("magnet:?"):
        raise ValueError("geçersiz magnet bağlantısı")
    query = urllib.parse.parse_qs(text[8:], keep_blank_values=True)
    info_hash = b""
    name = ""
    for xt in query.get("xt", []):
        low = xt.lower()
        if not low.startswith("urn:btih:"):
            continue
        value = xt[9:]
        try:
            if len(value) == 40:
                info_hash = bytes.fromhex(value)
            elif len(value) == 32:
                import base64

                info_hash = base64.b32decode(value.upper())
        except (ValueError, TypeError):
            info_hash = b""
        if info_hash:
            break
    if len(info_hash) != 20:
        raise ValueError("magnet bağlantısında geçerli info-hash yok")
    dn = query.get("dn") or []
    if dn:
        name = dn[0]
    return {
        "info_hash": info_hash,
        "name": name,
        "trackers": normalize_trackers(query.get("tr") or []),
        "web_seeds": [w for w in (query.get("ws") or []) if w.startswith("http")],
    }


def random_peer_id() -> bytes:
    return b"-ID3A00-" + bytes(random.randint(0, 255) for _ in range(12))


def _meta_from_info_bytes(info_bytes: bytes, info_hash: bytes, trackers: Sequence[str]) -> TorrentMeta:
    """ut_metadata ile gelen info sözlüğünden meta üretir (sha1 doğrulanmış)."""
    info = bdecode(info_bytes)
    if not isinstance(info, dict):
        raise ValueError("meta veri sözlük değil")
    name = _decode_text(info.get(b"name.utf-8") or info.get(b"name"), "torrent")
    piece_length = int(info.get(b"piece length") or 0)
    blob = info.get(b"pieces") or b""
    pieces = [blob[i:i + 20] for i in range(0, len(blob) - 19, 20)]
    files: List[TorrentFile] = []
    total = 0
    is_multi = b"files" in info
    if is_multi:
        for item in info.get(b"files") or []:
            if not isinstance(item, dict):
                continue
            length = int(item.get(b"length") or 0)
            parts = item.get(b"path.utf-8") or item.get(b"path") or []
            files.append(
                TorrentFile(
                    path=_safe_relpath("/".join(_decode_text(p) for p in parts)),
                    length=length,
                    offset=total,
                )
            )
            total += length
    else:
        length = int(info.get(b"length") or 0)
        files.append(TorrentFile(path=_safe_relpath(name), length=length, offset=0))
        total = length
    return TorrentMeta(
        info_hash=info_hash,
        name=name or "torrent",
        piece_length=piece_length,
        pieces=pieces,
        files=files,
        total_size=total,
        is_multi_file=is_multi,
        trackers=normalize_trackers(trackers),
        info_bytes=info_bytes,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Depolama
# ─────────────────────────────────────────────────────────────────────────────
class Storage:
    """Torrent dosyalarını diske yazar/okur (çok dosyalı torrent desteği).

    v3.13.0: AÇIK DOSYA TUTACAKLARI önbelleklenir — eski akışta HER parça yazımı
    için open()/close() yapılıyordu (4MB parça x 8 eş/sn = saniyede yüzlerce
    syscall). Artık tutamaklar yeniden kullanılır; LRU 96 dosya ile sınırlıdır.
    """

    MAX_OPEN_HANDLES = 96

    def __init__(self, root: Path, meta: TorrentMeta) -> None:
        self.root = Path(root)
        self.meta = meta
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.paths: List[Path] = []
        for f in meta.files:
            target = (self.root / f.path).resolve()
            if self.root.resolve() not in target.parents and target != self.root.resolve():
                target = self.root / "download.bin"  # yol kaçışı engeli
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                if not target.exists() or target.stat().st_size != f.length:
                    with open(target, "wb") as fh:
                        fh.truncate(f.length)  # ön tahsis (anında gerçek boyut)
            except OSError:
                pass
            self.paths.append(target)
        self._handles: Dict[Path, Any] = {}
        self._handle_order: List[Path] = []

    def _get_handle(self, path: Path):
        """Önbellekli 'r+b' tutamacı döner; kapalıysa yeniden açar."""
        fh = self._handles.get(path)
        if fh is not None and not fh.closed:
            return fh
        try:
            fh = open(path, "r+b")
        except OSError as exc:  # pragma: no cover - disk hatası
            log.warning("Dosya açılamadı (%s): %s", path.name, exc)
            return None
        self._handles[path] = fh
        self._handle_order.append(path)
        # LRU kırpma
        while len(self._handle_order) > self.MAX_OPEN_HANDLES:
            old = self._handle_order.pop(0)
            old_fh = self._handles.pop(old, None)
            if old_fh is not None:
                try:
                    old_fh.close()
                except OSError:
                    pass
        return fh

    def close_all(self) -> None:
        with self.lock:
            for fh in self._handles.values():
                try:
                    fh.close()
                except OSError:
                    pass
            self._handles.clear()
            self._handle_order.clear()

    def write(self, offset: int, data: bytes) -> None:
        """Sanal adresten başlayarak baytları ilgili dosyalara dağıtır."""
        pos = offset
        remaining = memoryview(data)
        with self.lock:
            for f, path in zip(self.meta.files, self.paths):
                if remaining.nbytes == 0:
                    break
                fstart = f.offset
                fend = f.offset + f.length
                if pos >= fend or pos + remaining.nbytes <= fstart:
                    continue
                local = pos - fstart
                take = min(remaining.nbytes, f.length - local)
                fh = self._get_handle(path)
                if fh is not None:
                    try:
                        fh.seek(local)
                        fh.write(remaining[:take])
                    except OSError as exc:  # pragma: no cover - disk hatası
                        log.warning("Parça yazılamadı (%s): %s", path.name, exc)
                        try:
                            fh.close()
                        except OSError:
                            pass
                        self._handles.pop(path, None)
                pos += take
                remaining = remaining[take:]

    def read(self, offset: int, length: int) -> bytes:
        out = bytearray()
        pos = offset
        with self.lock:
            for f, path in zip(self.meta.files, self.paths):
                if len(out) >= length:
                    break
                fend = f.offset + f.length
                if pos >= fend:
                    continue
                local = max(0, pos - f.offset)
                take = min(length - len(out), f.length - local)
                fh = self._get_handle(path)
                if fh is not None:
                    try:
                        fh.seek(local)
                        out += fh.read(take)
                    except OSError:
                        pass
                else:
                    try:
                        with open(path, "rb") as fh2:
                            fh2.seek(local)
                            out += fh2.read(take)
                    except OSError:
                        pass
                pos += take
        return bytes(out)


# ─────────────────────────────────────────────────────────────────────────────
# Parça yöneticisi
# ─────────────────────────────────────────────────────────────────────────────
class PieceManager:
    """Parça sahipliği + uçuştaki parçalar + blok durumu.

    v3.13.0: tamamlanan bayt sayısı ve bitfield ARTIK artımlı tutulur — IDM
    köprüsünün 150 ms'de bir okuduğu status() artık O(parça) döngü yapmaz
    (100k parçalık torrentlerde bile sıfır CPU maliyeti).
    """

    def __init__(self, meta: TorrentMeta) -> None:
        self.meta = meta
        self.lock = threading.RLock()
        self.have = bytearray(meta.num_pieces)
        self.inflight: Set[int] = set()
        self.verify_failed: Set[int] = set()
        self.have_bytes = 0            # v3.13.0: artımlı tamamlanan bayt sayacı
        self.frontier = 0              # v3.14.0: O(1) kesintisiz önek uzunluğu (IDM akışı)
        self._bitfield_cache: bytes = b""
        self._bf_dirty = True

    # ── durum ───────────────────────────────────────────────────────────────
    def count_have(self) -> int:
        return sum(self.have)

    @property
    def all_done(self) -> bool:
        # v3.13.0: tam sayaç == toplam boyut ise hepsi indi (sum() çağrısı yok)
        return self.have_bytes >= self.meta.total_size > 0 or (not self.have and self.meta.num_pieces == 0)

    def completed_bytes(self) -> int:
        return self.have_bytes

    def contiguous(self) -> int:
        """Baştan itibaren kesintisiz tamamlanmış parça sayısı (IDM akışı için).

        v3.14.0: artımlı tutulur (O(1)) — 100k parçalık torrentlerde bile
        her okuma sıfır maliyetlidir."""
        return self.frontier

    def bitfield_bytes(self) -> bytes:
        n = self.meta.num_pieces
        with self.lock:
            if not self._bf_dirty and self._bitfield_cache:
                return self._bitfield_cache
            buf = bytearray((n + 7) // 8)
            for i in range(n):
                if self.have[i]:
                    buf[i // 8] |= 0x80 >> (i % 8)
            self._bitfield_cache = bytes(buf)
            self._bf_dirty = False
            return self._bitfield_cache

    def bitfield_hex(self) -> str:
        return self.bitfield_bytes().hex()

    # ── seçim ───────────────────────────────────────────────────────────────
    def pick(self, peer_have: Optional[bytearray], cursor: int = 0) -> Optional[int]:
        """Eşin sahip olduğu, henüz indirilmeyen bir parça seçer.

        Önce akış penceresi (``cursor``..``cursor+64``) taranır: IDM'ye ardışık
        bayt aksın diye sıralı öncelik. Pencere boşsa en küçük indekse düşer.
        """
        n = self.meta.num_pieces
        with self.lock:
            if n == 0:
                return None
            # v3.11.0: akış penceresi 32 → 64 parça — yüksek gecikmeli bağlantılarda
            # ardışık indirme derinliği arttı, IDM ilk bayta daha hızlı kavuşur.
            window_end = min(n, max(0, cursor) + 64)
            for i in range(max(0, cursor), window_end):
                if self.have[i] or i in self.inflight:
                    continue
                if peer_have is not None and not peer_have[i]:
                    continue
                self.inflight.add(i)
                return i
            for i in range(n):
                if self.have[i] or i in self.inflight:
                    continue
                if peer_have is not None and not peer_have[i]:
                    continue
                self.inflight.add(i)
                return i
        return None

    def inflight_list(self) -> List[int]:
        """Uçuştaki (başka eşlerce talep edilmiş) parça listesi — endgame için."""
        with self.lock:
            return list(self.inflight)

    def release(self, index: int) -> None:
        with self.lock:
            self.inflight.discard(index)

    def mark_have(self, index: int) -> bool:
        """Parçayı tamamlandı olarak işaretler; yeni miydi bilgisini döner."""
        with self.lock:
            if index < 0 or index >= len(self.have):
                return False
            if self.have[index]:
                return False
            self.have[index] = 1
            self.inflight.discard(index)
            self.have_bytes += self.meta.piece_size(index)
            # v3.14.0: kesintisiz önek (frontier) artımlı ilerletilir
            if index == self.frontier:
                n = len(self.have)
                f = self.frontier + 1
                while f < n and self.have[f]:
                    f += 1
                self.frontier = f
            self._bf_dirty = True
            return True

    def block_count(self, index: int) -> int:
        return max(1, (self.meta.piece_size(index) + BLOCK_SIZE - 1) // BLOCK_SIZE)

    def block_len(self, index: int, block: int) -> int:
        size = self.meta.piece_size(index)
        start = block * BLOCK_SIZE
        return max(0, min(BLOCK_SIZE, size - start))



# ─────────────────────────────────────────────────────────────────────────────
# Eş teli
# ─────────────────────────────────────────────────────────────────────────────
class PeerConn:
    """Tek bir eşle BitTorrent teli (handshake → istek → parça doğrulama)."""

    def __init__(
        self,
        session: "NativeTorrentSession",
        ip: str,
        port: int,
        sock: Optional[socket.socket] = None,
        incoming: bool = False,
    ) -> None:
        self.session = session
        self.ip = ip
        self.port = int(port)
        self.incoming = incoming
        self.sock = sock
        self.alive = True
        self.choked = True
        self.interested = False
        self.peer_id = b""
        self.peer_bf: Optional[bytearray] = None
        self.peer_ext: Dict[bytes, Any] = {}
        self.ut_metadata_id = 0
        self.ut_pex_id = 0  # v3.11.0: eşin ut_pex uzantı kimliği (BEP 11)
        # v3.14.0 GLOBAL BLOK KOORDİNASYONU: blok sahipliği artık oturumda
        # (``_blk_owner``). Eş yalnızca KENDİ istek kaydını tutar — hangi bloğu
        # kime istediğimizin tek doğrusu oturumda, zombi parça imkânsız.
        self.requested: Set[Tuple[int, int]] = set()
        self.requested_times: Dict[Tuple[int, int], float] = {}
        self.last_block_ts = time.time()
        self.downloaded = 0
        self._upload_outstanding = 0      # v3.14.0: uçuştaki yükleme bloğu sayacı
        self._peer_interested = False
        self._we_unchoked_them = False
        self._msg_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    @property
    def outstanding(self) -> int:
        """Uçuştaki talep sayısı — sahipliği hâlâ bende olan istekler (oturum doğrusu)."""
        sess = self.session
        try:
            with sess._blk_lock:
                return sum(1 for k in self.requested if sess._blk_owner.get(k, (0, None))[1] == self.key)
        except AttributeError:  # oturum kapanmış olabilir
            return 0

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PeerConn {self.ip}:{self.port} choke={self.choked}>"

    @property
    def key(self) -> Tuple[str, int]:
        return (self.ip, self.port)

    # ── yaşam döngüsü ───────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name=f"bt-peer-{self.ip}:{self.port}", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.alive = False
        try:
            if self.sock is not None:
                self.sock.close()
        except OSError:
            pass
        self.sock = None
        self.session._peer_closed(self)

    def run(self) -> None:
        try:
            if self.sock is None:
                self.sock = socket.create_connection((self.ip, self.port), timeout=8.0)
            self.sock.settimeout(12.0)
            if not self._handshake():
                return
            self.sock.settimeout(90.0)
            self._send_extended_handshake()
            if self.session.meta is None:
                self.session._request_metadata_from(self)
            if self.choked:
                self._send_msg(2)  # interested
                self.interested = True
            else:
                self._fill_requests()
            self._loop()
        except (OSError, ValueError, struct.error):
            pass
        except Exception as exc:  # pragma: no cover - savunma
            log.debug("Eş teli hatası %s:%s — %s", self.ip, self.port, exc)
        finally:
            self.close()

    # ── el sıkışması ────────────────────────────────────────────────────────
    def _handshake(self) -> bool:
        assert self.sock is not None
        if self.incoming:
            head = self._recv_exact(68)
            if not head:
                return False
            if head[0] != len(PROTOCOL) or head[1:20] != PROTOCOL:
                return False
            if head[28:48] != self.session.info_hash:
                return False
            self.peer_id = head[48:68]
            reserved = head[20:28]
            self.sock.sendall(self._handshake_bytes())
        else:
            self.sock.sendall(self._handshake_bytes())
            head = self._recv_exact(68)
            if not head:
                return False
            if head[0] != len(PROTOCOL) or head[1:20] != PROTOCOL:
                return False
            if head[28:48] != self.session.info_hash:
                return False
            self.peer_id = head[48:68]
            reserved = head[20:28]
        if self.peer_id == self.session.peer_id:
            return False  # kendimize bağlandık
        self.supports_ext = bool(reserved[5] & 0x10)
        # ilk mesajımız: bitfield (varsa) veya have'ler
        self.session._send_bitfield_to(self)
        return True

    def _handshake_bytes(self) -> bytes:
        reserved = bytearray(8)
        reserved[5] |= 0x10  # BEP 10 uzantı protokolü
        return bytes([len(PROTOCOL)]) + PROTOCOL + bytes(reserved) + self.session.info_hash + self.session.peer_id

    def _recv_exact(self, size: int) -> Optional[bytes]:
        if self.sock is None:
            return None
        buf = bytearray()
        while len(buf) < size:
            try:
                chunk = self.sock.recv(size - len(buf))
            except socket.timeout:
                return None
            except OSError:
                return None
            if not chunk:
                return None
            buf += chunk
        return bytes(buf)

    # ── mesaj gönderimi ─────────────────────────────────────────────────────
    def _send(self, payload: bytes) -> bool:
        if self.sock is None or not self.alive:
            return False
        with self._msg_lock:
            try:
                self.sock.sendall(payload)
                return True
            except OSError:
                self.alive = False
                return False

    def _send_msg(self, msg_id: int, payload: bytes = b"") -> bool:
        return self._send(struct.pack(">IB", len(payload) + 1, msg_id) + payload)

    def _send_extended(self, ext_id: int, payload: bytes) -> bool:
        return self._send_msg(20, struct.pack(">B", ext_id) + payload)

    def _send_extended_handshake(self) -> None:
        info: Dict[bytes, Any] = {
            b"m": {b"ut_metadata": UT_METADATA_OUR_ID, b"ut_pex": UT_PEX_OUR_ID},
            b"v": b"IDM-Linux 1.0",
        }
        if self.session.meta is not None:
            info[b"metadata_size"] = len(self.session.meta.info_bytes)
        self._send_extended(0, bencode(info))

    def _send_bitfield(self) -> None:
        if self.session.pieces is None:
            return
        self._send_msg(5, self.session.pieces.bitfield_bytes())

    # ── mesaj döngüsü ───────────────────────────────────────────────────────
    def _loop(self) -> None:
        while self.alive and not self.session.stopping:
            header = self._recv_exact(4)
            if header is None:
                return
            length = struct.unpack(">I", header)[0]
            if length == 0:
                continue  # keep-alive
            if length > 2 * 1024 * 1024:
                return
            body = self._recv_exact(length)
            if body is None:
                return
            self._dispatch(body[0], body[1:])
            if not self.choked and not self.session.stopping:
                self._fill_requests()

    def _dispatch(self, msg_id: int, payload: bytes) -> None:
        if msg_id == 0:            # choke
            self.choked = True
        elif msg_id == 1:          # unchoke
            self.choked = False
            self._fill_requests()
        elif msg_id == 4:          # have
            if len(payload) >= 4:
                index = struct.unpack(">I", payload[:4])[0]
                self._peer_has(index)
                if not self.interested:
                    self._send_msg(2)
                    self.interested = True
        elif msg_id == 5:          # bitfield
            bf = bytearray(self.session.pieces.meta.num_pieces if self.session.pieces else len(payload) * 8)
            for i in range(len(bf)):
                byte = payload[i // 8] if i // 8 < len(payload) else 0
                bf[i] = 1 if byte & (0x80 >> (i % 8)) else 0
            self.peer_bf = bf
        elif msg_id == 7:          # piece
            self._on_piece(payload)
        elif msg_id == 6:          # request — v3.14.0: KARŞIYA YÜKLEME (tit-for-tat)
            self._serve_upload(payload)
        elif msg_id == 2:          # interested — v3.14.0: unchoke edip yükleyelim;
            # diğer leecherlar yüklendiğimiz eşleri tercih eder (küçük sürülerde
            # aç bırakmamak için hayati — Ubuntu torrenti vakası).
            self._peer_interested = True
            if not self._we_unchoked_them:
                self._we_unchoked_them = True
                self._send_msg(1)  # unchoke
        elif msg_id == 3:          # uninterested
            self._peer_interested = False
        elif msg_id == 20:         # uzantı
            self._on_extended(payload)

    # ── v3.14.0 karşıya yükleme (seeding-while-leeching) ─────────────────────
    MAX_UPLOAD_OUTSTANDING = 16     # eş başına uçuştaki yükleme bloğu
    MAX_UPLOAD_BLOCK = 32768        # protokol içi güvenli blok üst sınırı (32 KB)

    def _serve_upload(self, payload: bytes) -> None:
        """Eşin request mesajına diskten cevap verir (sadece doğrulanmış parçalar).

        Amaç hız değil, ADİLİK: tit-for-tat gereği veri yükleyen istemci
        diğer leecherlarca unchoke edilir — küçük sürülerde indirme hızını
        ciddi artırır. Upload bant genişliği uçuş bloğu sayacıyla doğal
        sınırlanır (eş başına 16 x 32 KB = 512 KB).
        """
        sess = self.session
        if len(payload) < 12 or sess.paused or sess.stopping:
            return
        pm = sess.pieces
        if pm is None or not pm.count_have():
            return
        if self._upload_outstanding >= self.MAX_UPLOAD_OUTSTANDING:
            return  # bu eşin kotası dolu — sessizce yut (istemci yeniden ister)
        try:
            index, begin, length = struct.unpack(">III", payload[:12])
        except struct.error:
            return
        if length <= 0 or length > self.MAX_UPLOAD_BLOCK:
            return
        if index < 0 or index >= pm.meta.num_pieces or not pm.have[index]:
            return  # elimizde doğrulanmış parça yok
        storage = sess.storage
        if storage is None:
            return
        try:
            data = storage.read(index * pm.meta.piece_length + begin, length)
        except Exception:
            return
        if len(data) != length:
            return
        self._upload_outstanding += 1
        if self._send_msg(7, struct.pack(">II", index, begin) + data):
            sess.uploaded_bytes += len(data)
            # uçuş sayacı: 3 sn sonra geri bırak (istemci yavaşsa da döngü tıkanmasın)
            def _rel() -> None:
                time.sleep(3.0)
                self._upload_outstanding = max(0, self._upload_outstanding - 1)

            threading.Thread(target=_rel, name="bt-upload-rel", daemon=True).start()

    def _peer_has(self, index: int) -> None:
        if self.peer_bf is None:
            return
        if 0 <= index < len(self.peer_bf):
            self.peer_bf[index] = 1

    # ── parça indirme (v3.14.0 GLOBAL BLOK KOORDİNASYONU) ───────────────────
    def _fill_requests(self) -> None:
        """Eşin pipeline'ını oturumun GLOBAL blok dağıtıcısından doldurur.

        Önemli: hangi bloğun kime ait olduğu oturumda tek yerde tutulur
        (``_blk_owner``). Frontier parçasının blokları tüm boş eşlere
        ŞERİTLENİR — parça hızı = eşlerin toplam hızı (tek eşin hızı değil!).
        8 sn yanıt gelmeyen sahiplikler ana döngüde otomatik serbest kalır;
        sessizleşen eşin blokları kilitli kalamaz (zombi parça imkânsız).
        """
        sess = self.session
        pm = sess.pieces
        if pm is None or sess.stopping or sess.paused or self.choked:
            return
        if not self.alive:
            return
        # sahipliği düşen (süre doldu / başka eşe geçti / tamamlandı) istekleri kayıtlarımdan sil
        try:
            with sess._blk_lock:
                stale = [k for k in self.requested if sess._blk_owner.get(k, (0.0, None))[1] != self.key]
            for k in stale:
                self.requested.discard(k)
                self.requested_times.pop(k, None)
        except (AttributeError, RuntimeError):
            return
        free = REQUEST_PIPELINE - self.outstanding
        if free <= 0:
            return
        picked = sess._pick_blocks(self, free)
        if not picked:
            return
        for index, begin, length in picked:
            if not self._send_msg(6, struct.pack(">III", index, begin, length)):
                return  # soket öldü — sahiplikler close() ile serbest kalır
            key = (index, begin // BLOCK_SIZE)
            self.requested.add(key)
            self.requested_times[key] = time.time()

    def _on_piece(self, payload: bytes) -> None:
        if len(payload) < 8:
            return
        index, begin = struct.unpack(">II", payload[:8])
        data = payload[8:]
        self.last_block_ts = time.time()
        self.downloaded += len(data)
        ib = (index, begin // BLOCK_SIZE)
        if ib in self.requested:
            self.requested.discard(ib)
            self.requested_times.pop(ib, None)
        # Blok oturumun GLOBAL tamponuna yazılır; parça hangi eşten gelirse gelsin
        # blokları tamamlandığında bir kez doğrulanıp diske yazılır.
        self.session._on_block(self, index, begin, data)

    # ── uzantılar (BEP 9 / BEP 10) ──────────────────────────────────────────
    def _on_extended(self, payload: bytes) -> None:
        if not payload:
            return
        ext_id = payload[0]
        body = payload[1:]
        if ext_id == 0:
            try:
                info = bdecode(body)
            except Exception:
                return
            if not isinstance(info, dict):
                return
            self.peer_ext = info
            m = info.get(b"m") or {}
            if isinstance(m, dict):
                try:
                    self.ut_metadata_id = int(m.get(b"ut_metadata") or 0)
                except (TypeError, ValueError):
                    self.ut_metadata_id = 0
                # v3.11.0 BEP 11: eşin ut_pex kimliğini öğren
                try:
                    self.ut_pex_id = int(m.get(b"ut_pex") or 0)
                except (TypeError, ValueError):
                    self.ut_pex_id = 0
            size = info.get(b"metadata_size")
            if size and self.session.meta is None:
                try:
                    self.session._metadata_begin(int(size))
                except (TypeError, ValueError):
                    pass
            if self.session.meta is None and self.ut_metadata_id:
                # eşin ut_metadata kimliği öğrenildi → meta veri parçalarını iste
                self.session._request_metadata_from(self)
            return
        # v3.14.0 KRİTİK MAGNET DÜZELTMESİ: ut_metadata / ut_pex ayrımı ARTIK
        # İÇERİKLE yapılır (mesaj gövdesindeki anahtarlara bakılır), uzantı
        # kimliğiyle DEĞİL. Eski mantık 'ext_id == eşin ut_pex id' ile PEX sanıyordu;
        # çok yaygın çakışmada (eşin ut_pex'i = 1, bizim ut_metadata'mız = 1) gelen
        # META VERİ PARÇALARI PEX dalında sessizce YUTULUYORDU ve magnet meta
        # verisi ASLA tamamlanmıyordu (TPB magnetleri hiç açılmıyordu!).
        head: Optional[Dict[bytes, Any]] = None
        consumed = 0
        try:
            head, consumed = bdecode_prefix(body)
        except Exception:
            head = None
        if isinstance(head, dict) and b"msg_type" in head:
            # ── ut_metadata (BEP 9) ──
            msg_type = head.get(b"msg_type")
            try:
                piece_idx = int(head.get(b"piece"))
            except (TypeError, ValueError):
                return
            if msg_type == 0:  # istek (bizden meta istiyor)
                self.session._serve_metadata_piece(self, piece_idx)
            elif msg_type == 1:  # veri
                total = 0
                try:
                    total = int(head.get(b"total_size") or 0)
                except (TypeError, ValueError):
                    total = 0
                self.session._metadata_piece(piece_idx, body[consumed:], total)
            elif msg_type == 2:
                self.session._metadata_rejected(piece_idx)
            return
        if isinstance(head, dict) and (b"added" in head or b"dropped" in head):
            # ── ut_pex (BEP 11): eşin bize bildirdiği eşleri keşif listesine ekle ──
            added = head.get(b"added") or b""
            peers: List[Tuple[str, int]] = []
            try:
                for i in range(0, len(added) - 5, 6):
                    ip = ".".join(str(b) for b in added[i : i + 4])
                    port = int.from_bytes(added[i + 4 : i + 6], "big")
                    if port > 0:
                        peers.append((ip, port))
            except Exception:
                peers = []
            if peers:
                self.session._add_known(peers, front=True)
                self.session._connect_more()
            return
        # bilinmeyen/çözülemeyen uzantı mesajı — yok sayılır
        return


# ─────────────────────────────────────────────────────────────────────────────
# Web seed havuzu (BEP 19) — v3.14.0
# ─────────────────────────────────────────────────────────────────────────────
class WebSeedPool:
    """BEP 19 ``url-list`` HTTP kaynaklarından PARALEL parça indiren havuz.

    Eski ``WebSeedWorker`` TEK iş parçacığıydı: parçaları sırayla, tek HTTP
    isteğinde (2-4 MB!) indirir, tek geçişliydi (hata olursa parça ASLA
    tekrar denenmezdi). Yeni havuz:
      * 6 eşzamanlı işçi — HTTP hızı x6,
      * frontier önceliği — IDM'nin beklediği parçalar ÖNCE iner,
      * P2P ile yarışmaz: blok sahipliği olan (eşlerin çalıştığı) parçaları atlar,
      * başarısız parçalar 20 sn sonra YENİDEN denenir (tek geçiş değil).
    """

    RETRY_AFTER = 20.0

    def __init__(self, session: "NativeTorrentSession", workers: int = 6) -> None:
        self.session = session
        self.workers = max(2, int(workers))
        self._active: Set[int] = set()
        self._retry_at: Dict[int, float] = {}
        self._lock = threading.Lock()
        self._url_i = 0

    def start(self) -> None:
        for i in range(self.workers):
            threading.Thread(target=self._worker, name=f"bt-webseed-{i}", daemon=True).start()

    # -- iş seçimi -----------------------------------------------------------
    def _next_piece(self) -> Optional[int]:
        sess = self.session
        meta = sess.meta
        pm = sess.pieces
        if meta is None or pm is None:
            return None
        now = time.time()
        # eşler hiç bağlı değilse web seed HERŞEYİ alır (tek kaynak senaryosu)
        with sess.lock:
            peers_alive = any(p.alive for p in sess._peers.values())
        with sess._blk_lock:
            owned = set(idx for (idx, _b) in sess._blk_owner)
        cursor = min(sess.stream_cursor, max(0, meta.num_pieces - 1))
        order = list(range(cursor, meta.num_pieces)) + list(range(0, cursor))
        for index in order:
            if pm.have[index]:
                continue
            with self._lock:
                if index in self._active:
                    continue
                if now < self._retry_at.get(index, 0.0):
                    continue
            if peers_alive and index in owned:
                continue  # P2P bu parçada çalışıyor — israf etme
            with self._lock:
                self._active.add(index)
            return index
        return None

    def _worker(self) -> None:
        sess = self.session
        while not sess.stopping:
            if sess.paused or sess.meta is None:
                time.sleep(1.0)
                continue
            index = self._next_piece()
            if index is None:
                time.sleep(0.6)
                continue
            try:
                self._fetch_piece(index)
            except Exception:  # pragma: no cover
                pass
            finally:
                with self._lock:
                    self._active.discard(index)

    def _fetch_piece(self, index: int) -> None:
        sess = self.session
        meta = sess.meta
        pm = sess.pieces
        if meta is None or pm is None or pm.have[index]:
            return
        start = index * meta.piece_length
        length = meta.piece_size(index)
        if length <= 0:
            return
        urls = list(meta.web_seeds)
        if not urls:
            return
        self._url_i = (self._url_i + 1) % len(urls)
        ordered = urls[self._url_i:] + urls[:self._url_i]
        for url in ordered:
            if sess.stopping or pm.have[index]:
                return
            target = self._resolve(url, meta)
            data = self._fetch_range(target, start, length)
            if data is not None and len(data) == length:
                sess._on_piece_downloaded(index, data)
                with self._lock:
                    self._retry_at.pop(index, None)
                return
        # tüm kaynaklar başarısız -> 20 sn sonra yeniden dene
        with self._lock:
            self._retry_at[index] = time.time() + self.RETRY_AFTER

    @staticmethod
    def _resolve(url: str, meta: TorrentMeta) -> str:
        base = url.strip()
        if not base:
            return ""
        if meta.is_multi_file:
            rel = meta.files[0].path if meta.files else ""
            if base.endswith("/"):
                return base + urllib.parse.quote(rel)
            return base
        if base.endswith("/"):
            return base + urllib.parse.quote(meta.files[0].path if meta.files else meta.name)
        return base

    @staticmethod
    def _fetch_range(url: str, start: int, length: int) -> Optional[bytes]:
        if not url:
            return None
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "IDM-Linux/1.0 (web seed)",
                "Range": f"bytes={start}-{start + length - 1}",
                "Accept": "*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=25.0) as resp:
                data = resp.read(length + 1)
        except Exception:
            return None
        if len(data) == length:
            return data
        # Sunucu Range'i yok saydıysa tam gövde gelir → dilimi ayıkla
        if len(data) > length:
            return data[start: start + length]
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Oturum
# ─────────────────────────────────────────────────────────────────────────────
class NativeTorrentSession:
    """Kendi BitTorrent oturumumuz — aria2 uyumlu ``status()`` ile."""

    def __init__(
        self,
        work_dir: Path,
        *,
        torrent_bytes: Optional[bytes] = None,
        magnet: str = "",
        extra_trackers: Optional[Sequence[str]] = None,
        max_peers: int = MAX_PEERS_DEFAULT,
        enable_dht: bool = True,
        listen_port: int = 0,
        log_fn: Any = None,
        tracker_refresher: Any = None,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.work_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.peer_id = random_peer_id()
        self.max_peers = max(8, int(max_peers))
        self.enable_dht = bool(enable_dht)
        self.listen_port = int(listen_port or 0)
        self._log = log_fn or (lambda msg: log.info("%s", msg))
        self.lock = threading.RLock()
        self.stopping = False
        self.started = False
        self.ready = threading.Event()
        self.error_message = ""
        # v3.13.0: IDM İPTAL DENEDEmi — kullanıcı IDM'de iptal/duraklatınca arka
        # planda P2P trafiği SIFIRLANIR (pause); yeniden bağlanınca devam eder.
        self.paused = False
        self.stream_cursor = 0
        self.download_speed = 0
        self.uploaded_bytes = 0   # v3.14.0: karşıya yüklenen toplam bayt (tit-for-tat)
        self._speed_samples: Deque[Tuple[float, int]] = deque(maxlen=20)
        self._meta = None  # type: Optional[TorrentMeta]
        self.meta: Optional[TorrentMeta] = None
        self.info_hash = b""
        self.name = "torrent"
        self.magnet_info: Dict[str, Any] = {}
        self.extra_trackers = normalize_trackers(list(extra_trackers or []))
        self._live_trackers: List[str] = []
        self._tracker_refresher = tracker_refresher
        self._last_refresh = 0.0
        self.pieces: Optional[PieceManager] = None
        self.storage: Optional[Storage] = None
        self._peers: Dict[Tuple[str, int], PeerConn] = {}
        self._known: Deque[Tuple[str, int]] = deque()
        # ── v3.14.0 GLOBAL BLOK KOORDİNASYONU ───────────────────────────────
        # Blok sahipliği TEK yerde: (parça, blok) -> (talep_zamanı, eş_anahtarı).
        # Frontier parçasının blokları tüm boş eşlere şeritlenir; 8 sn içinde
        # yanıt gelmeyen talepler ana döngüde serbest kalır. Parça, blokları
        # HANGİ eşten gelirse gelsin tamamlandığında bir kez doğrulanır.
        self._blk_lock = threading.RLock()
        self._blk_owner: Dict[Tuple[int, int], Tuple[float, Tuple[str, int]]] = {}
        self._blk_buf: Dict[int, Dict[int, bytes]] = {}
        self._blk_buffered = 0
        # v3.14.0 BÜTÜNLÜK: parça -> {begin: gönderen_eş} — SHA1 düşen parçada
        # iki kez ortak çıkan (yani bozuk veri gönderen) eş BANLANIR.
        self._blk_src: Dict[int, Dict[int, Tuple[str, int]]] = {}
        self._peer_fail_pieces: Dict[Tuple[str, int], Set[int]] = {}
        self._banned: Set[Tuple[str, int]] = set()
        self._ws_pool: Optional[WebSeedPool] = None
        self._known_set: Set[Tuple[str, int]] = set()
        self._listener: Optional[socket.socket] = None
        self._dht: Optional[DHTNode] = None
        self._dht_lookup_running = False
        self._announce_running = False
        self._last_announce = 0.0
        self._announce_interval = 1800.0
        self._announce_due = 0.0
        self._announce_retry = 10.0
        self._announce_failures = 0
        self._threads: List[threading.Thread] = []
        self._completed_announced = False
        self._frontier_seen = 0          # v3.14.1: akış-takılma dedektörü durumu
        self._frontier_bytes_seen = 0
        # meta veri takası (magnet)
        self._meta_total = 0
        self._meta_buf: Dict[int, bytes] = {}
        self._meta_requested: Set[int] = set()
        self._meta_requested_ts: Dict[int, float] = {}   # v3.14.0: istek kilidi süre aşımı
        self._meta_lock = threading.Lock()
        self._last_meta_try = 0.0

        if torrent_bytes:
            self.meta = parse_torrent_bytes(torrent_bytes)
            self._meta = self.meta
            self.info_hash = self.meta.info_hash
            self.name = self.meta.name
        elif magnet:
            self.magnet_info = parse_magnet(magnet)
            self.info_hash = self.magnet_info["info_hash"]
            self.name = self.magnet_info.get("name") or self.info_hash.hex()[:16]
        else:
            raise ValueError("Ne .torrent ne magnet verisi verildi")

    # ── geriye dönük iç adlar (eski testler/araçlar) ────────────────────────
    @property
    def _pieces(self) -> Optional["PieceManager"]:
        return self.pieces

    @property
    def _known_peers(self) -> Deque[Tuple[str, int]]:
        return self._known

    # ── görünüm ─────────────────────────────────────────────────────────────
    @property
    def need_metadata(self) -> bool:
        return self.meta is None

    @property
    def all_done(self) -> bool:
        return bool(self.pieces is not None and self.pieces.all_done)

    @property
    def total_size(self) -> int:
        return self.meta.total_size if self.meta else 0

    @property
    def piece_count(self) -> int:
        return self.meta.num_pieces if self.meta else 0

    @property
    def output_filename(self) -> str:
        if self.meta:
            return self.meta.output_filename
        return f"{self.name}.tar"

    @property
    def trackers(self) -> List[str]:
        out: List[str] = []
        if self.meta:
            out.extend(self.meta.trackers)
        out.extend(self.magnet_info.get("trackers") or [])
        out.extend(self.extra_trackers)
        if not out and self.enable_dht:
            # Torrentin kendi tracker'ı yoksa genel listeye düşülür. DHT kapalıyken
            # (çevrimdışı/test modu) internet tracker'larına gidilmez.
            out.extend(DEFAULT_TRACKERS[:4])
        out.extend(self._live_trackers)
        out = normalize_trackers(out)
        # v3.11.0: torrent yalnız 1-2 tracker taşıyorsa (Linux Mint resmi torrenti TEK
        # udp tracker!) genel açık tracker listesiyle ZENGİNLEŞTİR — UDP kapalı ağlarda
        # HTTP tracker'lar + DHT kurtarıcı olur, eş keşfi sağlanır.
        if 0 < len(out) < 3 and self.enable_dht:
            out.extend(DEFAULT_TRACKERS)
            out = normalize_trackers(out)
        return out

    # ── başlatma ────────────────────────────────────────────────────────────
    def start(self) -> None:
        with self.lock:
            if self.started:
                return
            self.started = True
        self._open_listener()
        if self.meta is not None:
            self._install_meta(self.meta)
        if self.enable_dht:
            try:
                self._dht = DHTNode(listen_port=0)
                self._dht.start()
            except OSError:
                self._dht = None
        thread = threading.Thread(target=self._run, name="bt-native", daemon=True)
        thread.start()
        self._threads.append(thread)

    def _open_listener(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", int(self.listen_port or 0)))
            sock.listen(16)
            sock.settimeout(1.0)
            self.listen_port = int(sock.getsockname()[1])
            self._listener = sock
            threading.Thread(target=self._accept_loop, name="bt-accept", daemon=True).start()
        except OSError as exc:  # pragma: no cover - port hatası
            log.debug("Dinleme soketi açılamadı: %s", exc)
            self.listen_port = 0

    # -- v3.13.0: IDM İPTAL / DEVAM KOMUTLARI ---------------------------------
    def pause(self) -> None:
        """IDM istemcisi koptu (iptal/duraklat): P2P trafiğini ANINDA keser.

        Eşler kapatılır, anons/eş arama durur; diskteki hazır parçalar ve
        bilet korunur. IDM yeniden bağlanınca resume() ile kaldığı yerden
        (belli ki 0 ofsetinden) saniyeler içinde devam eder. Arka planda
        NOKTA kadar bant genişliği harcanmaz (kullanıcı kuralı).
        """
        if self.stopping:
            return
        self.paused = True
        with self.lock:
            peers = list(self._peers.values())
        for peer in peers:
            peer.close()
        self._log("BitTorrent: IDM istemcisi ayrıldı -> motor DURAKLATILDI (arka plan indirmesi yok)")

    def resume(self) -> None:
        """IDM yeniden bağlandı: motoru kaldığı yerden devam ettirir."""
        if not self.paused or self.stopping:
            return
        self.paused = False
        self._announce_due = 0.0
        self._last_meta_try = 0.0
        self._announce_retry = 10.0
        self._announce_async("")
        self._connect_more()
        self._log("BitTorrent: IDM yeniden bağlandı -> motor DEVAM EDİYOR")

    def _accept_loop(self) -> None:
        while not self.stopping and self._listener is not None:
            if self.paused:
                # duraklatılmışken gelen eşleri sessizce reddet (sıfır trafik)
                try:
                    conn, _addr = self._listener.accept()
                    conn.close()
                except socket.timeout:
                    continue
                except OSError:
                    return
                continue
            try:
                conn, addr = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            peer = PeerConn(self, addr[0], addr[1], sock=conn, incoming=True)
            peer.start()

    def _install_meta(self, meta: TorrentMeta) -> None:
        self.meta = meta
        self._meta = meta
        self.info_hash = meta.info_hash
        self.name = meta.name
        self.pieces = PieceManager(meta)
        try:
            self.storage = Storage(self.data_dir, meta)
        except OSError as exc:  # pragma: no cover
            self.error_message = f"Disk hazırlığı başarısız: {exc}"
            self.storage = None
        self._log(
            f"BitTorrent: {meta.name} — {meta.num_pieces} parça, "
            f"{meta.total_size} bayt, {len(meta.files)} dosya"
        )

    # ── v3.14.0 GLOBAL BLOK DAĞITICI ────────────────────────────────────────
    def _expire_stale_requests(self, now: Optional[float] = None) -> None:
        """Süresi dolan GLOBAL blok sahipliklerini serbest bırakır.

        Eski akışta bu denetim yalnız eşten mesaj gelince çalışıyordu; sessiz
        eşin blokları 90 sn kilitli kalıyor ve IDM akışı DURUYORDU (kullanıcı
        ölçümü: frontier 80+ sn sabit). Artık ana döngü her tıkta çağırır —
        sessiz eş bloğu 8 sn içinde başka eşe geçer.
        """
        now = time.time() if now is None else now
        with self._blk_lock:
            expired = [k for k, (ts, _o) in self._blk_owner.items() if now - ts > REQUEST_BLOCK_TIMEOUT]
            for k in expired:
                self._blk_owner.pop(k, None)

    def _release_peer_claims(self, peer_key: Tuple[str, int]) -> None:
        """Eş kapandığında sahipliklerini ANINDA serbest bırakır (8 sn beklemeden)."""
        with self._blk_lock:
            dead = [k for k, (_ts, owner) in self._blk_owner.items() if owner == peer_key]
            for k in dead:
                self._blk_owner.pop(k, None)

    def _pick_blocks(self, peer: PeerConn, limit: int) -> List[Tuple[int, int, int]]:
        """Eşe göndereceği blokları seçer ve GLOBAL sahiplik alır.

        Öncelik sırası (IDM kesintisiz bayt akışı için):
          1) frontier penceresi  [cursor, cursor+32)   — IDM'nin beklediği bölge
          2) akış derinliği      [cursor+32, cursor+128) — ardışık dolgu
          3) kalan parçalar      (en küçük indeksten)   — penceredeki bloklar o eşte yoksa
        Sahipliği taze olan bloklar atlanır (mükerrer trafik YOK); süresi dolanlar
        yeniden dağıtılır (otomatik endgame).
        """
        meta = self.meta
        pm = self.pieces
        if meta is None or pm is None or limit <= 0 or self.paused or self.stopping:
            return []
        now = time.time()
        pk = peer.key
        bf = peer.peer_bf
        n = meta.num_pieces
        cursor = self.stream_cursor if 0 <= self.stream_cursor < n else 0
        out: List[Tuple[int, int, int]] = []
        with self._blk_lock:
            self._expire_stale_requests(now)
            # v3.14.1: tampon sınırı YALNIZ ileri-dolgu taleplerini durdurur.
            # Frontier bölgesi (IDM'nin beklediği parçalar) her koşulda talep
            # edilir — aksi halde kısmen dolu parçalar hiç tamamlanamaz ve
            # MOTOR KALICI KİLİTLENİR (ölçülen 60+ sn donma vakası).
            over_cap = self._blk_buffered >= MAX_BUFFERED_BYTES
            warm = self._blk_buffered >= MAX_BUFFERED_BYTES * 0.6
            # katman 1: IDM'nin beklediği frontier penceresi (SADECE bu bölgedeki
            # parçalara sahip eşler azdır — seed'ler; KISA zaman aşımıyla hızlı
            # geri dönüşüm uygulanır)
            for index in range(cursor, min(n, cursor + STREAM_WINDOW)):
                self._scan_piece(pm, bf, index, now, pk, out, limit,
                                 timeout=FRONTIER_BLOCK_TIMEOUT)
                if len(out) >= limit:
                    return out
            if over_cap:
                return out
            # katman 2: ardışık akış derinliği (tampon ısındıysa derinlik yarıya iner)
            depth = STREAM_DEPTH // 2 if warm else STREAM_DEPTH
            for index in range(min(n, cursor + STREAM_WINDOW), min(n, cursor + depth)):
                self._scan_piece(pm, bf, index, now, pk, out, limit)
                if len(out) >= limit:
                    return out
            # katman 3: kalan tüm parçalar (cursor'dan sarmalı tarama)
            start = max(0, cursor)
            for index in list(range(start, n)) + list(range(0, start)):
                self._scan_piece(pm, bf, index, now, pk, out, limit)
                if len(out) >= limit:
                    return out
        return out

    def _scan_piece(
        self,
        pm: "PieceManager",
        bf: Optional[bytearray],
        index: int,
        now: float,
        pk: Tuple[str, int],
        out: List[Tuple[int, int, int]],
        limit: int,
        timeout: float = REQUEST_BLOCK_TIMEOUT,
    ) -> None:
        """Tek parçanın eksik bloklarından sahiplik alınabilenleri ``out``'a ekler."""
        if index < 0 or index >= pm.meta.num_pieces or pm.have[index] or len(out) >= limit:
            return
        if bf is not None and index < len(bf) and not bf[index]:
            return  # bu eş bu parçaya sahip değil
        buf = self._blk_buf.get(index)
        for block in range(pm.block_count(index)):
            begin = block * BLOCK_SIZE
            if buf is not None and begin in buf:
                continue
            key = (index, block)
            own = self._blk_owner.get(key)
            if own is not None and (now - own[0]) < timeout:
                continue  # taze sahiplik — dokunma (mükerrer trafik yok)
            self._blk_owner[key] = (now, pk)
            out.append((index, begin, pm.block_len(index, block)))
            if len(out) >= limit:
                return

    def _on_block(self, peer: PeerConn, index: int, begin: int, data: bytes) -> None:
        """Gelen bloğu GLOBAL tampona yazar; parça tamamlanınca doğrular."""
        pm = self.pieces
        meta = self.meta
        if pm is None or meta is None or self.stopping:
            return
        if index < 0 or index >= meta.num_pieces or pm.have[index]:
            return
        # v3.14.0 PROTOKOL DOĞRULAMASI: hizasız/taşan/yanlış boyutlu blok kabul edilmez
        # (bozuk eş savunması — hatalı blok parçayı kirlemeden düşer)
        piece_size = meta.piece_size(index)
        if begin < 0 or begin % BLOCK_SIZE != 0 or begin >= piece_size:
            log.debug("Uyumsuz blok reddedildi: parça=%d begin=%d", index, begin)
            return
        if len(data) != pm.block_len(index, begin // BLOCK_SIZE):
            log.debug("Yanlış boyutlu blok reddedildi: parça=%d begin=%d boy=%d", index, begin, len(data))
            return
        complete = False
        buf: Dict[int, bytes] = {}
        with self._blk_lock:
            cur = self._blk_buf.get(index)
            if cur is not None and begin in cur:
                return  # çift blok
            self._blk_buf.setdefault(index, {})[begin] = data
            self._blk_owner.pop((index, begin // BLOCK_SIZE), None)
            # göndereni kaydet (SHA1 düşerse suçlu tespiti için)
            self._blk_src.setdefault(index, {})[begin] = peer.key
            self._blk_buffered += len(data)
            cur = self._blk_buf[index]
            if len(cur) >= pm.block_count(index):
                complete = True
                buf = self._blk_buf.pop(index)
                self._blk_buffered -= sum(len(v) for v in buf.values())
        if not complete:
            return
        size = meta.piece_size(index)
        assembled = bytearray(size)
        for off, chunk in buf.items():
            assembled[off: off + len(chunk)] = chunk
        self._on_piece_downloaded(index, bytes(assembled))

    def _clear_piece_state(self, index: int) -> None:
        """Tamamlanan parçanın artık blok/sahiplik kayıtlarını temizler."""
        pm = self.pieces
        with self._blk_lock:
            leftover = self._blk_buf.pop(index, None)
            if leftover:
                self._blk_buffered -= sum(len(v) for v in leftover.values())
            self._blk_src.pop(index, None)
            if pm is not None:
                for b in range(pm.block_count(index)):
                    self._blk_owner.pop((index, b), None)

    def _ban_peer(self, peer_key: Tuple[str, int], reason: str) -> None:
        """Bozuk veri gönderen eşi oturum boyunca yasaklar ve bağlantısını keser."""
        with self._blk_lock:
            if peer_key in self._banned:
                return
            self._banned.add(peer_key)
        with self.lock:
            conn = self._peers.get(peer_key)
        if conn is not None:
            conn.close()  # _peer_closed -> sahiplikler serbest, yeni eş bağlanır
        self._log(f"BitTorrent: bozuk eş yasaklandı ({peer_key[0]}) — {reason}")

    # ── ana döngü ───────────────────────────────────────────────────────────
    def _run(self) -> None:
        self.ready.set()
        if self.meta is not None and self.meta.web_seeds:
            self._ws_pool = WebSeedPool(self)
            self._ws_pool.start()
        if self._dht is not None:
            threading.Thread(target=self._dht_bootstrap, name="bt-dht-boot", daemon=True).start()
        self._announce_async("started")
        last_snapshot = 0.0
        # v3.14.1: akış-takılma dedektörü — frontier ilerlemiyor ama eşler varsa
        # (choked/az eş) YENİ eş keşfi tetiklenir (tracker + DHT).
        self._frontier_last_advanced = time.time()
        self._stall_refresh_last = 0.0
        while not self.stopping:
            # v3.13.0: DURAKLATILMIŞ -> hiçbir arama/anons/eş bağlantısı yapılmaz
            if self.paused:
                time.sleep(0.5)
                continue
            now = time.time()
            if self.all_done:
                if not self._completed_announced:
                    self._completed_announced = True
                    self._announce_async("completed")
                self._update_speed()
                self.ready.set()
                break
            # v3.14.0: süresi dolan blok sahipliklerini her tıkta serbest bırak
            # (sessiz eşin blokları artık asla kilitli kalamaz — kök-neden düzeltmesi)
            self._expire_stale_requests(now)
            # v3.14.1: frontier 12 sn ilerlemediyse yeni eş ara (az eş / choke döngüsü)
            if self.pieces is not None and not self.need_metadata:
                frontier = self.pieces.frontier
                if frontier > self._frontier_seen:
                    self._frontier_last_advanced = now
                    self._frontier_seen = frontier
                elif now - self._frontier_last_advanced > 12.0 and now - self._stall_refresh_last > 15.0:
                    self._stall_refresh_last = now
                    self._log("BitTorrent: akış takıldı — ek eş keşfi başlatılıyor (tracker+DHT)")
                    self._announce_async("")
                    if self._dht is not None and not self._dht_lookup_running:
                        threading.Thread(target=self._dht_lookup, name="bt-dht-stall", daemon=True).start()
            # boşta kalan unchoke'lu eşleri tekrar doldur (mesaj beklemeden)
            with self.lock:
                idle_peers = [p for p in self._peers.values() if p.alive and not p.choked]
            for peer in idle_peers:
                try:
                    peer._fill_requests()
                except Exception:  # pragma: no cover - savunma
                    pass
            if now >= self._announce_due and not self._announce_running:
                self._announce_async("")
            if self.need_metadata and now - self._last_meta_try > 5.0:
                self._last_meta_try = now
                self._request_metadata_from_peers()
            self._connect_more()
            self._reap_peers()
            if now - last_snapshot >= SNAPSHOT_INTERVAL:
                last_snapshot = now
                self._update_speed()
                if self.pieces is not None:
                    self.stream_cursor = min(self.pieces.contiguous(), max(0, self.pieces.meta.num_pieces - 1))
                self._refresh_trackers_bg()
                if self.stopping:
                    break
            time.sleep(0.35)
        self.ready.set()

    def _dht_bootstrap(self) -> None:
        try:
            if self._dht is not None:
                found = self._dht.bootstrap(timeout=10.0)
                if found:
                    self._log(f"BitTorrent: DHT tablosu hazır ({found} düğüm)")
                else:
                    # v3.11.0: bootstrap sıfır düğümle döndüyse bile get_peers ÇALIŞTIR —
                    # router'lar (router.bittorrent.com) doğrudan sorgulanabilir; eski
                    # davranışta lookup hiç atlanmadan bırakılıyordu ve DHT tamamen ölüyordu.
                    self._log("BitTorrent: DHT bootstrap zayıf — doğrudan peer sorgusu deneniyor")
                self._dht_lookup()
        except Exception:  # pragma: no cover
            pass

    def _dht_lookup(self) -> None:
        if self._dht_lookup_running or self._dht is None:
            return
        self._dht_lookup_running = True
        try:
            peers = self._dht.get_peers(self.info_hash, timeout=14.0) if self._dht else []
        except Exception:
            peers = []
        finally:
            self._dht_lookup_running = False
        if peers:
            self._add_known(peers, front=True)
            self._log(f"BitTorrent: DHT {len(peers)} eş buldu")
            self._connect_more()

    # ── tracker ─────────────────────────────────────────────────────────────
    def _refresh_trackers_bg(self) -> None:
        """Canlı tracker listesini ARKA PLANDA tazeler (indirmeyi bloke etmez)."""
        if self._tracker_refresher is None or time.time() - self._last_refresh < 1200:
            return
        self._last_refresh = time.time()

        def _work() -> None:
            try:
                fresh = self._tracker_refresher() or []
            except Exception:
                return
            if fresh:
                self._live_trackers = list(fresh)[:60]
                self._log(f"BitTorrent: canlı tracker listesi tazelendi ({len(self._live_trackers)})")

        threading.Thread(target=_work, name="bt-trackers", daemon=True).start()

    def _announce_async(self, event: str = "") -> None:
        if self._announce_running or self.stopping or self.paused:
            return
        self._announce_running = True
        threading.Thread(target=self._announce, args=(event,), name="bt-announce", daemon=True).start()

    def _announce(self, event: str = "") -> bool:
        """Tracker'lara anons yapar; eş yoksa hızlı yeniden deneme planlar."""
        trackers = self.trackers
        found: List[Tuple[str, int]] = []
        if trackers:
            results = announce_all(
                trackers,
                self.info_hash,
                self.peer_id,
                self.listen_port or 6881,
                left=max(0, (self.total_size - self._downloaded()) if self.meta else 0),
                event=event,
                timeout=6.0,
            )
            intervals: List[float] = []
            for res in results:
                if res.get("error"):
                    continue
                interval = res.get("interval") or 1800
                try:
                    intervals.append(float(interval))
                except (TypeError, ValueError):
                    pass
                found.extend(res.get("peers") or [])
            if intervals:
                self._announce_interval = max(120.0, min(intervals))
        if found:
            # v3.14.1: anons sonucu gelen eşler EN ÖNE eklenir — takılma
            # anlarında taze keşif (seed'ler dahil) hemen bağlanır.
            self._add_known(found, front=(event != "stopped"))
        self._last_announce = time.time()
        with self.lock:
            alive = any(p.alive for p in self._peers.values())
        if self.all_done:
            self._announce_due = time.time() + max(120.0, self._announce_interval)
        elif not alive:
            self._announce_due = time.time() + self._announce_retry
            self._announce_retry = min(60.0, max(10.0, self._announce_retry * 1.5))
            if self._dht is not None and not self._dht_lookup_running:
                threading.Thread(target=self._dht_lookup, name="bt-dht-lookup", daemon=True).start()
        else:
            self._announce_retry = 10.0
            self._announce_due = time.time() + max(30.0, self._announce_interval)
        self._announce_running = False
        if found:
            self._connect_more()
        return bool(found)

    # ── eş yönetimi ─────────────────────────────────────────────────────────
    def _add_known(self, peers: Iterable[Tuple[str, int]], front: bool = False) -> None:
        with self.lock:
            for ip, port in peers:
                key = (ip, int(port))
                if key in self._known_set or key in self._peers:
                    continue
                if port == self.listen_port or port <= 0:
                    continue
                if ip in ("0.0.0.0", "255.255.255.255"):
                    continue
                self._known_set.add(key)
                if front:
                    self._known.appendleft(key)
                else:
                    self._known.append(key)
                if len(self._known_set) > 800:
                    old = self._known.popleft()
                    self._known_set.discard(old)

    def _connect_more(self) -> None:
        if self.paused:
            return
        with self.lock:
            while self._known and len(self._peers) < self.max_peers:
                ip, port = self._known.popleft()
                self._known_set.discard((ip, port))
                if (ip, port) in self._peers:
                    continue
                # v3.14.0: banlı eşlere asla yeniden bağlanılmaz
                with self._blk_lock:
                    if (ip, port) in self._banned:
                        continue
                peer = PeerConn(self, ip, port)
                self._peers[(ip, port)] = peer
                peer.start()

    def _reap_peers(self) -> None:
        with self.lock:
            dead = [k for k, p in self._peers.items() if not p.alive]
        for key in dead:
            self._peer_closed(self._peers.get(key))

    def _peer_closed(self, peer: Optional[PeerConn]) -> None:
        if peer is None:
            return
        peer.alive = False
        # v3.14.0: eşin sahipliklerini ANINDA serbest bırak — bloklar 8 sn
        # beklemeden diğer eşlere dağıtılır (akış kopmaz).
        self._release_peer_claims(peer.key)
        with self.lock:
            self._peers.pop(peer.key, None)

    def _send_bitfield_to(self, peer: PeerConn) -> None:
        if self.pieces is not None and not self.pieces.all_done:
            peer._send_msg(5, self.pieces.bitfield_bytes())

    def _broadcast_have(self, index: int) -> None:
        with self.lock:
            peers = list(self._peers.values())
        payload = struct.pack(">I", index)
        for peer in peers:
            peer._peer_has(index)
            peer._send_msg(4, payload)

    # ── parça teslimi ───────────────────────────────────────────────────────
    def _on_piece_downloaded(self, index: int, data: bytes) -> None:
        meta = self.meta
        pm = self.pieces
        if meta is None or pm is None or index >= meta.num_pieces:
            return
        expected = meta.pieces[index]
        if hashlib.sha1(data).digest() != expected:
            pm.release(index)
            pm.verify_failed.add(index)
            # v3.14.0: parçaya veri katkısı yapan eşleri bul; AYNI parçada İKİ KEZ
            # ortak çıkan (yani iki denemede de bozuk veri gönderen) eşi banla.
            with self._blk_lock:
                contributors = set(self._blk_src.pop(index, {}).values())
                leftover = self._blk_buf.pop(index, None)
                if leftover:
                    self._blk_buffered -= sum(len(v) for v in leftover.values())
            banned_now: List[Tuple[str, int]] = []
            for key in contributors:
                fails = self._peer_fail_pieces.setdefault(key, set())
                if index in fails:
                    banned_now.append(key)
                else:
                    fails.add(index)
            self._log(f"BitTorrent: parça {index} SHA1 uyuşmadı — yeniden indirilecek "
                      f"({len(contributors)} katkıcı{', ban: ' + ','.join(k[0] for k in banned_now) if banned_now else ''})")
            for key in banned_now:
                self._ban_peer(key, f"parça {index} iki kez bozuk")
            return
        if self.storage is not None:
            try:
                self.storage.write(index * meta.piece_length, data)
            except OSError as exc:
                # v3.10.1: disk dolu/izin hatasında sonsuz "parça yazılamadı"
                # döngüsü yerine DÜRÜST hata — IDM net mesaj görür.
                msg = f"Diske yazılamadı ({exc}). Boş alan/izin sorununu giderip yeniden deneyin."
                if not self.error_message:
                    self._log(f"BitTorrent: {msg}")
                    self.error_message = msg
                    self.stopping = True
                pm.release(index)
                return
        if pm.mark_have(index):
            self._clear_piece_state(index)
            self._broadcast_have(index)

    def _downloaded(self) -> int:
        return self.pieces.completed_bytes() if self.pieces else 0

    def _update_speed(self) -> None:
        done = self._downloaded()
        now = time.time()
        self._speed_samples.append((now, done))
        if len(self._speed_samples) >= 2:
            t0, b0 = self._speed_samples[0]
            dt = max(0.2, now - t0)
            self.download_speed = int(max(0, (done - b0) / dt))
        else:
            self.download_speed = 0

    # ── magnet meta verisi (BEP 9) ──────────────────────────────────────────
    def _metadata_begin(self, total: int) -> None:
        """Eşin bildirdiği meta veri boyutunu kaydeder."""
        with self._meta_lock:
            if total <= 0 or total > MAX_METADATA_SIZE:
                return
            if self._meta_total and total != self._meta_total:
                self._meta_buf.clear()
                self._meta_requested.clear()
            self._meta_total = total

    def _request_metadata_from(self, peer: PeerConn) -> None:
        """Bir eşten eksik meta veri parçalarını ister (v3.13.0: EŞZAMANLI 4 PARÇA).

        Eski akış her çağrıda TEK parça istiyordu; 5 saniyede bir tekrarlandığı
        için meta takası yavaş tamamlanıyordu. Artık eş başına 4 parça birden
        istenir -> magnet meta verisi saniyeler içinde iner.

        Eş ``metadata_size`` bildirmediyse (bazı istemciler bildirmez) parçalar
        sırayla istenir ve son (kısa) parça geldiğinde boyut öğrenilir.
        """
        if not peer.ut_metadata_id:
            return
        now_ts = time.time()
        with self._meta_lock:
            if self.meta is not None:
                return
            # v3.14.0: 15 sn önce istenmiş ve gelmemiş parçaların kilidini aç
            # (cevapsız kalan eş isteği sonsuza dek bloklamasın)
            stale = [i for i, ts in self._meta_requested_ts.items() if now_ts - ts > 15.0]
            for i in stale:
                self._meta_requested_ts.pop(i, None)
                self._meta_requested.discard(i)
            total = self._meta_total
            picked: List[int] = []
            if total > 0:
                limit = (total + METADATA_PIECE - 1) // METADATA_PIECE
                for idx in range(limit):
                    if len(picked) >= 4:
                        break
                    if idx not in self._meta_buf and idx not in self._meta_requested:
                        picked.append(idx)
            else:
                # toplam boyut bilinmiyor: yalnız 0. parça istenir — ut_metadata
                # yanıtında total_size gelir, sonraki isteklerde 4'erli tırmanır
                # (bilinmeyen boyutta 512 parça spam'İ OLAMAZ).
                if 0 not in self._meta_buf and 0 not in self._meta_requested:
                    picked.append(0)
            if not picked:
                return
            self._meta_requested.update(picked)
            for idx in picked:
                self._meta_requested_ts[idx] = now_ts
        for idx in picked:
            peer._send_extended(peer.ut_metadata_id, bencode({b"msg_type": 0, b"piece": idx}))

    def _request_metadata_from_peers(self) -> None:
        with self.lock:
            peers = list(self._peers.values())
        for peer in peers:
            if peer.alive and peer.ut_metadata_id:
                self._request_metadata_from(peer)

    def _metadata_piece(self, index: int, data: bytes, total_size: int = 0) -> None:
        """Gelen meta veri parçasını biriktirir; tamamlanınca sha1 doğrulaması yapar."""
        blob = b""
        complete = False
        with self._meta_lock:
            if self.meta is not None:
                return  # v3.14.0: zaten kuruldu — tekrar _install_meta yapma
            if total_size > 0 and total_size <= MAX_METADATA_SIZE:
                if self._meta_total and total_size != self._meta_total:
                    self._meta_buf.clear()
                    self._meta_requested.clear()
                self._meta_total = total_size
            if not data:
                return
            self._meta_buf[index] = data[:METADATA_PIECE]
            self._meta_requested.discard(index)
            self._meta_requested_ts.pop(index, None)
            if self._meta_total <= 0 and len(data) < METADATA_PIECE:
                # son (kısa) parça: toplam boyut buradan çıkar
                self._meta_total = index * METADATA_PIECE + len(data)
            if self._meta_total > 0:
                needed = (self._meta_total + METADATA_PIECE - 1) // METADATA_PIECE
                if len(self._meta_buf) >= needed and all(i in self._meta_buf for i in range(needed)):
                    complete = True
                    blob = b"".join(self._meta_buf[i] for i in range(needed))[: self._meta_total]
                    # v3.14.0: tamponu TEMİZLE — ikinci bir "tamamlandı" tetiklenmesin
                    self._meta_buf.clear()
                    self._meta_requested.clear()
                    self._meta_requested_ts.clear()
            if not complete:
                pending = (self._meta_total + METADATA_PIECE - 1) // METADATA_PIECE
                if self._meta_total <= 0 and len(self._meta_buf) >= MAX_METADATA_PIECES:
                    complete = False
                    pending = 0
        if not complete:
            self._request_metadata_from_peers()
            return
        if hashlib.sha1(blob).digest() != self.info_hash:
            self._log("BitTorrent: magnet meta verisi doğrulanamadı (sha1 uyuşmadı)")
            with self._meta_lock:
                self._meta_buf.clear()
                self._meta_requested.clear()
            return
        try:
            meta = _meta_from_info_bytes(blob, self.info_hash, self.trackers)
        except Exception as exc:
            self._log(f"BitTorrent: meta veri çözümlenemedi: {exc}")
            return
        self._install_meta(meta)
        self._log("BitTorrent: magnet meta verisi alındı")
        if meta.web_seeds and self._ws_pool is None:
            self._ws_pool = WebSeedPool(self)
            self._ws_pool.start()
        with self.lock:
            peers = list(self._peers.values())
        for peer in peers:
            if peer.ut_metadata_id == 0:
                peer._send_extended_handshake()

    def _metadata_rejected(self, index: int) -> None:
        with self._meta_lock:
            self._meta_requested.discard(index)
            self._meta_requested_ts.pop(index, None)

    def _serve_metadata_piece(self, peer: PeerConn, index: int) -> None:
        if self.meta is None or not peer.ut_metadata_id:
            return
        blob = self.meta.info_bytes
        start = index * METADATA_PIECE
        if start >= len(blob):
            peer._send_extended(peer.ut_metadata_id, bencode({b"msg_type": 2, b"piece": index}))
            return
        chunk = blob[start: start + METADATA_PIECE]
        head = bencode({b"msg_type": 1, b"piece": index, b"total_size": len(blob)})
        peer._send_extended(peer.ut_metadata_id, head + chunk)

    # ── durum (aria2 uyumlu) ────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        meta = self.meta
        with self.lock:
            conns = len(self._peers)
        if meta is None:
            return {
                "status": "error" if self.error_message else "active",
                "totalLength": "0",
                "completedLength": "0",
                "downloadSpeed": str(self.download_speed),
                "uploadSpeed": "0",
                "connections": str(conns),
                "numPieces": "0",
                "pieceLength": "0",
                "bitfield": "",
                "files": [{"path": "[METADATA]", "length": "0", "completedLength": "0", "selected": "true"}],
                "bittorrent": {"info": {"name": self.name}},
                "errorMessage": self.error_message,
            }
        pm = self.pieces
        done = pm.completed_bytes() if pm else 0
        if self.error_message:
            state = "error"
        elif self.all_done:
            state = "complete"
        elif conns:
            state = "active"
        else:
            state = "waiting"
        files = []
        for f in meta.files[:64]:
            files.append(
                {
                    "path": str((self.data_dir / f.path).resolve()) if self.storage else f.path,
                    "length": str(f.length),
                    "completedLength": str(f.length if self.all_done else 0),
                    "selected": "true",
                }
            )
        return {
            "status": state,
            "totalLength": str(meta.total_size),
            "completedLength": str(done),
            "downloadSpeed": str(self.download_speed),
            "uploadSpeed": "0",
            "connections": str(conns),
            "numPieces": str(meta.num_pieces),
            "pieceLength": str(meta.piece_length),
            "bitfield": pm.bitfield_hex() if pm else "",
            "files": files,
            "bittorrent": {"info": {"name": meta.name}},
            "errorMessage": self.error_message,
        }

    def wait_ready(self, timeout: float = 12.0) -> bool:
        return self.ready.wait(timeout)

    def stop(self) -> None:
        self.stopping = True
        with self.lock:
            peers = list(self._peers.values())
        for peer in peers:
            peer.close()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None
        if self._dht is not None:
            self._dht.stop()
            self._dht = None
        try:
            if self.storage is not None:
                self.storage.close_all()  # v3.13.0: açık tutamakları da kapat
        except Exception:
            pass
        self.ready.set()

    # ── yardımcılar (eski API uyumu) ────────────────────────────────────────
    @property
    def info_hash_hex(self) -> str:
        return self.info_hash.hex() if self.info_hash else ""

    def piece_done_flags(self) -> List[bool]:
        if self.pieces is None:
            return []
        return [bool(x) for x in self.pieces.have]


# ─────────────────────────────────────────────────────────────────────────────
# Geriye dönük API adları (eski sürümlerden çağıran kodlar kırılmasın)
# ─────────────────────────────────────────────────────────────────────────────
parse_magnet_uri = parse_magnet
DHT_ENABLED_BY_DEFAULT = True
MAX_PENDING_CONNECTS = MAX_PEERS_DEFAULT
