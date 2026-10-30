from __future__ import annotations

import base64
import hashlib
import http.server
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .config import get_cache_dir, setup_logger

log = setup_logger("torrent", "daemon.log")

# Hızlı eş (peer) keşfi için güvenilir açık BitTorrent tracker listesi
# v3.5.0: ngosang/trackerslist'in en sağlam üyeleriyle genişletildi (daha çok eş, daha hızlı)
DEFAULT_PUBLIC_TRACKERS: List[str] = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://opentracker.i2p.rocks:6969/announce",
    "udp://tracker.internetwarriors.net:1337/announce",
    "udp://tracker.leechers-paradise.org:6969/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
    "http://tracker.opentrackr.org:1337/announce",
    "http://open.acgnxtracker.com:80/announce",
    "https://tracker.tamersunion.org:443/announce",
    "udp://tracker.tiny-vps.com:6969/announce",
]

# v3.5.0: DHT önyükleme düğümleri — magnet meta keşfi saniyeler içinde hızlanır
# v3.7.1 NOT: '--dht-entry-point' TEK HOST:PORT alır (liste DEĞİL) — DHT_ENTRY_POINTS[0] kullanılır.
DHT_ENTRY_POINTS: List[str] = [
    "router.bittorrent.com:6881",
    "dht.transmissionbt.com:6881",
    "router.utorrent.com:6881",
    "dht.libtorrent.org:25401",
]

# ─── v3.9.0: CANLI TRACKER LİSTESİ (ngosang/trackerslist — 12 saat önbellekli) ──
# Kullanıcı raporu: TPB torrenti 0 B/s + 'Bağlantı kesildi'. Statik listedeki
# trackerların bir kısmı ÖLMÜŞ (coppersurfer.tk, leechers-paradise vb.); eş keşfi
# yavaşlıyordu. Artık her 12 saatte bir canlı 'best' listesi çekilir, diskte saklanır
# ve statik listeyle birleştirilerek kullanılır. Ağ yoksa statik liste devamedar.

_TRACKER_CACHE_TTL = 12 * 3600.0
_tracker_cache: Dict[str, Any] = {"ts": 0.0, "trackers": []}
_tracker_cache_lock = threading.Lock()


def _load_tracker_cache_disk() -> List[str]:
    try:
        p = get_cache_dir(create=False) / "trackers_best.json"
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            ts = float(data.get("ts") or 0)
            trs = data.get("trackers") or []
            if trs and (time.time() - ts) < _TRACKER_CACHE_TTL:
                return [str(t) for t in trs if t]
    except Exception:
        pass
    return []


def _save_tracker_cache_disk(trackers: List[str]) -> None:
    try:
        p = get_cache_dir(create=True) / "trackers_best.json"
        p.write_text(json.dumps({"ts": time.time(), "trackers": trackers[:80]}), encoding="utf-8")
    except Exception:
        pass


def fetch_fresh_trackers(timeout: float = 8.0) -> List[str]:
    """ngosang/trackerslist'in canlı 'best' listesini indirir (12 saat önbellek).
    Başarısızlıkta disk önbelleği, o da yoksa boş liste döner — statik liste her zaman eklenir."""
    with _tracker_cache_lock:
        now = time.time()
        if _tracker_cache["trackers"] and (now - float(_tracker_cache["ts"])) < _TRACKER_CACHE_TTL:
            return list(_tracker_cache["trackers"])
        disk = _load_tracker_cache_disk()
        if disk:
            _tracker_cache.update({"ts": now, "trackers": disk})
            return list(disk)
        urls = (
            "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt",
            "https://cdn.jsdelivr.net/gh/ngosang/trackerslist@master/trackers_best.txt",
        )
        found: List[str] = []
        for u in urls:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "IDM-Linux"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    txt = resp.read(262144).decode("utf-8", errors="replace")
                for ln in txt.splitlines():
                    ln = ln.strip()
                    if ln.startswith(("udp://", "http://", "https://", "wss://")) and "/" in ln:
                        if ln not in found:
                            found.append(ln)
                if found:
                    break
            except Exception:
                continue
        if found:
            _tracker_cache.update({"ts": now, "trackers": found[:80]})
            _save_tracker_cache_disk(found[:80])
            log.info("Canlı tracker listesi güncellendi (%d adet).", len(found[:80]))
            return list(_tracker_cache["trackers"])
        return []


def cached_tracker_list(max_count: int = 30) -> List[str]:
    """AĞA ÇIKMADAN kullanılabilir tracker listesi (önbellek + statik).

    v3.10.0: Torrent tıklamasında dispatch yolu asla ağ beklemez — canlı liste
    arka planda (daemon ön-ısıtma iş parçacığı) tazelenir, burada yalnızca hazır
    önbellek + statik liste döner.
    """
    out: List[str] = []
    with _tracker_cache_lock:
        cached = list(_tracker_cache.get("trackers") or [])
    for t in cached + DEFAULT_PUBLIC_TRACKERS:
        if t and t not in out:
            out.append(t)
        if len(out) >= max_count:
            break
    return out


def merged_tracker_list(max_count: int = 60) -> List[str]:
    """Statik + canlı tracker listesini birleştirir (canlı ÖNCE gelir — daha taze)."""
    out: List[str] = []
    for t in fetch_fresh_trackers() + DEFAULT_PUBLIC_TRACKERS:
        if t and t not in out:
            out.append(t)
        if len(out) >= max_count:
            break
    return out


# ─── v3.9.0: ARIA2 OTOMATİK KURULUM (pkexec + statik ikili yedeği) ────────

_ARIA2_INSTALL_LOCK = threading.Lock()


def _pkexec_install_packages(packages: List[str], timeout: float = 600.0) -> Tuple[bool, str]:
    """pkexec ile sistem paket yöneticisi üzerinden kurulum yapar (GUI onay penceresi açılır)."""
    pkexec = shutil.which("pkexec")
    if not pkexec:
        return False, "pkexec bulunamadı"
    pm = None
    for pm_name, bin_name in (("pacman", "pacman"), ("apt", "apt-get"), ("dnf", "dnf"), ("zypper", "zypper")):
        if shutil.which(bin_name):
            pm = pm_name
            break
    if not pm:
        return False, "paket yöneticisi bulunamadı"
    if pm == "pacman":
        cmd = ["pacman", "-S", "--noconfirm", "--needed"] + packages
    elif pm == "apt":
        cmd = ["apt-get", "install", "-y"] + packages
    elif pm == "dnf":
        cmd = ["dnf", "install", "-y"] + packages
    else:
        cmd = ["zypper", "--non-interactive", "install"] + packages
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    try:
        res = subprocess.run([pkexec] + cmd, capture_output=True, text=True, timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired:
        return False, "kurulum zaman aşımına uğradı"
    except Exception as exc:
        return False, str(exc)
    if res.returncode == 0:
        return True, ""
    tail = ((res.stderr or "") + (res.stdout or "")).strip().splitlines()
    return False, (tail[-1][:200] if tail else f"çıkış kodu {res.returncode}")


def _download_to(url: str, dest: Path, timeout: float = 300.0) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) IDM-Linux"})
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fp:
            while True:
                chunk = resp.read(262144)
                if not chunk:
                    break
                fp.write(chunk)
        return dest.is_file() and dest.stat().st_size > 1024
    except Exception:
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def _github_latest_release_asset(repo: str, suffix: str) -> Optional[str]:
    """GitHub API üzerinden en son sürümde <suffix> ile biten ilk varlık URL'ini döner."""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers={"User-Agent": "IDM-Linux", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for asset in data.get("assets") or []:
            name = str(asset.get("name") or "")
            if name.lower().endswith(suffix.lower()):
                url = asset.get("browser_download_url")
                if url:
                    return str(url)
    except Exception:
        pass
    return None


def ensure_aria2_installed(timeout: float = 600.0) -> Optional[str]:
    """aria2c kuruluysa yolunu döner; kurulu değilse otomatik kurmayı dener.

    1) pkexec + sistem paket yöneticisi (pacman/apt/dnf/zypper — hepsinde 'aria2'
       resmî depolarda VAR, hedef bulunamadı hatası imkânsız).
    2) Başarısızsa ROOT'SUZ statik ikili: q3aql/aria2-static-builds GitHub sürümü
       kullanıcı önbelleğine açılır (~/.cache/idm-linux/bin/aria2c).
    Hiçbiri olmazsa None döner."""
    with _ARIA2_INSTALL_LOCK:
        found = shutil.which("aria2c")
        if found:
            return found
        cache_bin = get_cache_dir(create=True) / "bin"
        static_bin = cache_bin / "aria2c"
        if static_bin.is_file() and os.access(static_bin, os.X_OK):
            return str(static_bin)

        ok, err = _pkexec_install_packages(["aria2"], timeout=timeout)
        if ok:
            found = shutil.which("aria2c")
            if found:
                log.info("aria2 paket yöneticisiyle kuruldu: %s", found)
                return found

        # ROOT'SUZ YEDEK: statik aria2c arşivi
        try:
            log.info("aria2 statik ikiliyle kurulmaya çalışılıyor (pkexec: %s)", err)
            cache_bin.mkdir(parents=True, exist_ok=True)
            asset = _github_latest_release_asset("q3aql/aria2-static-builds", "linux-gnu-64bit-build1.tar.bz2")
            if not asset:
                asset = "https://github.com/q3aql/aria2-static-builds/releases/download/v1.37.0/aria2-1.37.0-linux-gnu-64bit-build1.tar.bz2"
            tar_path = cache_bin / "aria2-static.tar.bz2"
            if not _download_to(asset, tar_path, timeout=timeout):
                return None
            extract_dir = cache_bin / "aria2-static"
            shutil.rmtree(extract_dir, ignore_errors=True)
            extract_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(tar_path, "r:bz2") as tf:
                tf.extractall(extract_dir)  # noqa: S202 — kendi önbelleğimiz
            for cand in extract_dir.rglob("aria2c"):
                if cand.is_file():
                    shutil.copy2(cand, static_bin)
                    os.chmod(static_bin, 0o755)
                    tar_path.unlink(missing_ok=True)
                    shutil.rmtree(extract_dir, ignore_errors=True)
                    log.info("aria2c statik ikili kuruldu: %s", static_bin)
                    return str(static_bin)
        except Exception as exc:
            log.warning("aria2 statik kurulumu başarısız: %s", exc)
        return None


# ─── SAF PYTHON BENCODE ÇÖZÜMLEYİCİ (BEP 0003) ───────────────────────────

def _bdecode_at(data: bytes, idx: int) -> Tuple[Any, int]:
    if idx >= len(data):
        raise ValueError("Bencode verisi beklenmedik şekilde sona erdi.")
    ch = data[idx : idx + 1]
    if ch == b"i":
        end = data.index(b"e", idx + 1)
        return int(data[idx + 1 : end].decode("ascii")), end + 1
    if ch == b"l":
        idx += 1
        items = []
        while data[idx : idx + 1] != b"e":
            val, idx = _bdecode_at(data, idx)
            items.append(val)
        return items, idx + 1
    if ch == b"d":
        idx += 1
        out: Dict[bytes, Any] = {}
        while data[idx : idx + 1] != b"e":
            k, idx = _bdecode_at(data, idx)
            if not isinstance(k, bytes):
                raise ValueError("Bencode sözlük anahtarı bytes olmalıdır.")
            val_start = idx
            v, idx = _bdecode_at(data, idx)
            out[k] = v
            if k == b"info":
                out[b"__raw_info_slice__"] = data[val_start:idx]
        return out, idx + 1
    if b"0" <= ch <= b"9":
        colon = data.index(b":", idx)
        length = int(data[idx:colon].decode("ascii"))
        start = colon + 1
        end = start + length
        if end > len(data):
            raise ValueError("Bencode bayt dizisi uzunluğu veriyi aşıyor.")
        return data[start:end], end
    raise ValueError(f"Geçersiz Bencode belirteci (konum {idx}): {ch!r}")


def bdecode(data: bytes) -> Any:
    val, _ = _bdecode_at(data, 0)
    return val


def _decode_utf8(raw: Any, fallback: str = "") -> str:
    if isinstance(raw, bytes):
        for enc in ("utf-8", "cp1254", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
    if isinstance(raw, str):
        return raw
    return fallback


@dataclass
class TorrentMetadata:
    name: str
    info_hash: str
    total_size: int
    piece_length: int
    is_multi_file: bool
    file_count: int
    trackers: List[str] = field(default_factory=list)
    web_seeds: List[str] = field(default_factory=list)

    @property
    def output_filename(self) -> str:
        safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", self.name).strip(" ._") or "torrent_indirilen"
        if self.is_multi_file and not safe.lower().endswith(".tar"):
            return f"{safe}.tar"
        return safe


def parse_torrent_bytes(raw_bytes: bytes) -> TorrentMetadata:
    if not raw_bytes or raw_bytes[:1] != b"d":
        raise ValueError("Geçerli bir .torrent (Bencode) dosyası değil.")
    root = bdecode(raw_bytes)
    if not isinstance(root, dict) or b"info" not in root:
        raise ValueError(".torrent dosyası içinde 'info' bölümü bulunamadı.")

    info = root[b"info"]
    raw_info = root.get(b"__raw_info_slice__", b"")
    info_hash = hashlib.sha1(raw_info).hexdigest() if raw_info else ""

    name = _decode_utf8(info.get(b"name.utf-8") or info.get(b"name"), fallback=f"torrent_{info_hash[:8]}")
    piece_length = int(info.get(b"piece length") or 262144)

    if b"files" in info and isinstance(info[b"files"], list):
        is_multi = True
        files_list = info[b"files"]
        file_count = len(files_list)
        total_size = sum(int(f.get(b"length") or 0) for f in files_list if isinstance(f, dict))
    else:
        is_multi = False
        file_count = 1
        total_size = int(info.get(b"length") or 0)

    trackers: List[str] = []
    if b"announce" in root:
        tr = _decode_utf8(root[b"announce"]).strip()
        if tr:
            trackers.append(tr)
    if b"announce-list" in root and isinstance(root[b"announce-list"], list):
        for tier in root[b"announce-list"]:
            if isinstance(tier, list):
                for item in tier:
                    tr = _decode_utf8(item).strip()
                    if tr and tr not in trackers:
                        trackers.append(tr)

    web_seeds: List[str] = []
    for ws_key in (b"url-list", b"httpseeds"):
        ws_val = root.get(ws_key)
        if isinstance(ws_val, bytes):
            u = _decode_utf8(ws_val).strip()
            if u.startswith(("http://", "https://")):
                web_seeds.append(u)
        elif isinstance(ws_val, list):
            for item in ws_val:
                u = _decode_utf8(item).strip()
                if u.startswith(("http://", "https://")) and u not in web_seeds:
                    web_seeds.append(u)

    return TorrentMetadata(
        name=name,
        info_hash=info_hash,
        total_size=total_size,
        piece_length=piece_length,
        is_multi_file=is_multi,
        file_count=file_count,
        trackers=trackers,
        web_seeds=web_seeds,
    )


def parse_magnet_uri(magnet_uri: str) -> TorrentMetadata:
    uri = magnet_uri.strip()
    if not uri.lower().startswith("magnet:?"):
        raise ValueError("Geçerli bir magnet:? bağlantısı değil.")
    parsed = urllib.parse.urlsplit(uri)
    qs = urllib.parse.parse_qs(parsed.query)

    info_hash = ""
    for xt in qs.get("xt", []):
        m = re.search(r"urn:btih:([A-Fa-f0-9]{40}|[A-Za-z2-7]{32})", xt)
        if m:
            raw_h = m.group(1)
            if len(raw_h) == 32 and not re.fullmatch(r"[A-Fa-f0-9]{32}", raw_h):
                try:
                    info_hash = base64.b32decode(raw_h.upper()).hex()
                except Exception:
                    info_hash = raw_h.lower()
            else:
                info_hash = raw_h.lower()
            break

    dn_list = qs.get("dn", [])
    raw_name = urllib.parse.unquote_plus(dn_list[0]).strip() if dn_list else ""
    if not raw_name:
        raw_name = f"magnet_{info_hash[:12] if info_hash else 'indirilen'}"

    xl_list = qs.get("xl", [])
    total_size = 0
    if xl_list:
        try:
            total_size = max(0, int(xl_list[0]))
        except ValueError:
            total_size = 0

    trackers: List[str] = []
    for tr in qs.get("tr", []):
        t = urllib.parse.unquote(tr).strip()
        if t and t not in trackers:
            trackers.append(t)
    for pub in DEFAULT_PUBLIC_TRACKERS:
        if pub not in trackers:
            trackers.append(pub)

    web_seeds: List[str] = []
    for ws in qs.get("ws", []) + qs.get("as", []):
        u = urllib.parse.unquote(ws).strip()
        if u.startswith(("http://", "https://")) and u not in web_seeds:
            web_seeds.append(u)

    # Magnet'ta dosya sayısı meta veri inene kadar bilinmez; uzantısı yoksa klasör olabilir ama başlangıçta tekil ad verilir
    return TorrentMetadata(
        name=raw_name,
        info_hash=info_hash,
        total_size=total_size,
        piece_length=262144,
        is_multi_file=False,
        file_count=1,
        trackers=trackers,
        web_seeds=web_seeds,
    )


def is_magnet_or_torrent_url(url: str) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    low = u.lower()
    if low.startswith("magnet:?"):
        return True
    path_only = urllib.parse.urlsplit(low).path
    return path_only.endswith(".torrent")


def count_contiguous_leading_pieces(bitfield_hex: str, total_pieces: int) -> int:
    """
    aria2 JSON-RPC 'bitfield' (onaltılık dize) içindeki 0. parçadan başlayarak
    kesintisiz (ardışık) olarak doğrulanmış parça sayısını hesaplar.
    Böylece IDM'ye yalnızca SHA-1 doğrulaması bitmiş gerçek baytlar gönderilir!
    """
    if not bitfield_hex or total_pieces <= 0:
        return 0
    try:
        raw = bytes.fromhex(bitfield_hex)
    except ValueError:
        return 0

    count = 0
    for byte_val in raw:
        if byte_val == 0xFF:
            count += 8
            if count >= total_pieces:
                return total_pieces
        else:
            for bit_pos in range(7, -1, -1):
                if byte_val & (1 << bit_pos):
                    count += 1
                    if count >= total_pieces:
                        return total_pieces
                else:
                    return count
            return count
    return min(count, total_pieces)


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class TorrentSession:
    ticket_id: str
    meta: TorrentMetadata
    work_dir: Path
    source_kind: str              # "torrent_file" | "magnet"
    torrent_file_path: Optional[Path]
    magnet_uri: Optional[str]
    rpc_port: int = 0
    rpc_secret: str = ""
    gid: str = ""
    proc: Optional[subprocess.Popen] = None
    created_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)
    started: bool = False
    error_message: str = ""
    # v3.7.0 SENKRON HAZIRLIK KAPISI: IDM'ye köprü adresi YALNIZCA aria2c RPC gerçekten
    # ayağa kalktıktan (veya net bir hata mesajı üretildikten) SONRA verilir. Böylece
    # IDM'nin /torrent/<ticket> isteği yarım başlatılmış motorla asla karşılaşmaz ve
    # kullanıcının gördüğü 'aria2c RPC servisi başlatılamadı' 503 penceresi kökten biter.
    ready: threading.Event = field(default_factory=threading.Event)
    aria2_log_path: Optional[Path] = None
    # ── v3.10.0 NATIVE MOTOR ────────────────────────────────────────────────
    # Kullanıcı kararı: BitTorrent indirmeleri KENDİ motorumuzla yapılır; aria2c
    # yalnızca native motor kurulamazsa (çok eski Python vb.) yedek olarak kalır.
    native: Any = None
    backend: str = "native"
    native_error: str = ""
    # ── v3.13.0 IDM İPTAL İZLEYİCİ ──────────────────────────────────────────
    # IDM'de iptal/duraklatılınca motorun arka planda indirmeye DEVAM ETMEMESİ
    # için köprü istemci sayacı + zarafet penceresi + otomatik duraklatma.
    bridge_clients: int = 0
    last_client_ts: float = 0.0
    engine_paused: bool = False
    cancel_watch_started: bool = False
    cancel_watch_run: bool = True
    CLIENT_GONE_GRACE_SEC: float = 60.0

    def _rpc_call(self, method: str, params: Optional[List[Any]] = None) -> Any:
        if not self.rpc_port:
            return None
        full_params: List[Any] = [f"token:{self.rpc_secret}"]
        if params:
            full_params.extend(params)
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": "idm", "method": method, "params": full_params}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.rpc_port}/jsonrpc",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        return body.get("result")

    def ensure_started(self) -> None:
        """v3.7.0: motoru senkron ve güvenli başlatır.

        - Her koşulda `ready` event'i SET edilir (hata olsa bile) — çağıran taraf
          `ready.wait(timeout)` ile net sonuç alır, yarım motorla asla IDM'ye gitmez.
        - aria2c stderr bir log dosyasına yazılır; süreç ölürse log kuyruğu hata
          mesajına eklenir (kök-neden artık kullanıcı ekranında görünür).
        """
        with self.lock:
            if self.started:
                return
            self.started = True
            try:
                self._ensure_started_impl()
            except Exception as exc:
                log.error("Torrent motoru başlatma istisnası (ticket=%s): %s", self.ticket_id, exc)
                if not self.error_message:
                    self.error_message = f"Torrent motoru başlatılamadı: {exc}"
            finally:
                self.ready.set()

    # ── v3.10.0 NATIVE MOTOR YÖNETİMİ ───────────────────────────────────────
    def _try_native_start(self) -> bool:
        """Saf Python BitTorrent motorunu başlatır. Başarılıysa ``True`` döner.

        Native motor .torrent dosyasını da magnet bağlantısını da doğrudan
        sindirir; meta veri (magnet) DHT/ut_metadata ile toplanır. Böylece
        kullanıcı hiçbir dış araç kurmadan torrent indirebilir.
        """
        try:
            from .p2p.bt_native import NativeTorrentSession
        except Exception as exc:  # pragma: no cover - kurulum bozuksa
            self.native_error = f"native motor içe aktarılamadı: {exc}"
            log.warning("Native torrent motoru yüklenemedi: %s", exc)
            return False

        raw: Optional[bytes] = None
        if self.source_kind == "torrent_file" and self.torrent_file_path and self.torrent_file_path.is_file():
            try:
                raw = self.torrent_file_path.read_bytes()
            except OSError as exc:
                self.native_error = f".torrent okunamadı: {exc}"
                return False
        magnet = self.magnet_uri or ""
        if raw is None and not magnet:
            self.native_error = "ne .torrent ne magnet verisi var"
            return False
        try:
            sess = NativeTorrentSession(
                work_dir=self.work_dir,
                torrent_bytes=raw,
                magnet=magnet,
                extra_trackers=cached_tracker_list(),
                # canlı tracker listesi ARKA PLANDA tazelenir (dispatch yolu ağ beklemez)
                tracker_refresher=merged_tracker_list,
                log_fn=lambda msg: log.info("%s", msg),
            )
            sess.start()
            sess.wait_ready(timeout=12.0)
        except Exception as exc:
            self.native_error = f"native motor başlatılamadı: {exc}"
            log.warning("Native torrent motoru başlatılamadı (ticket=%s): %s", self.ticket_id, exc)
            return False

        self.native = sess
        self.backend = "native"
        # rpc_port, "motor hazır" işareti olarak da kullanılır (dinleme portu).
        self.rpc_port = int(sess.listen_port or 1) or 1
        self.gid = "native"
        if not sess.info_hash:
            self.native_error = "info hash çözümlenemedi"
            return False
        self.meta.info_hash = sess.info_hash.hex()
        if sess.meta is not None:
            self.meta.name = sess.meta.name
            self.meta.total_size = sess.meta.total_size
            self.meta.is_multi_file = sess.meta.is_multi_file
            self.meta.file_count = len(sess.meta.files)
            self.meta.piece_length = sess.meta.piece_length
        self.meta.web_seeds = list(self.meta.web_seeds or []) + list(sess.trackers[:0])
        log.info(
            "Native BitTorrent motoru hazır (ticket=%s, eş portu=%s, %s)",
            self.ticket_id,
            self.rpc_port,
            "magnet/metadata bekleniyor" if sess.need_metadata else f"{sess.meta.num_pieces} parça",
        )
        return True

    def _sync_meta_from_native(self) -> None:
        """Magnet meta verisi indiğinde IDM köprüsünün gördüğü ad/boyut güncellenir."""
        sess = self.native
        if sess is None or sess.meta is None:
            return
        try:
            if self.meta.name != sess.meta.name:
                self.meta.name = sess.meta.name
            self.meta.total_size = sess.meta.total_size
            self.meta.is_multi_file = sess.meta.is_multi_file
            self.meta.file_count = len(sess.meta.files)
            self.meta.piece_length = sess.meta.piece_length
        except Exception:
            pass

    def _aria2_log_tail(self, limit: int = 6) -> str:
        if not self.aria2_log_path or not self.aria2_log_path.is_file():
            return ""
        try:
            lines = [
                ln.strip()
                for ln in self.aria2_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if ln.strip()
            ]
            return " | ".join(lines[-limit:])[:400]
        except Exception:
            return ""

    def _ensure_started_impl(self) -> None:
        # ── 1) NATIVE BITTORRENT MOTORU (sıfırdan, saf Python) ──────────────
        # Dış ikili, paket kurulumu, yetki penceresi YOK. Magnet bağlantıları
        # DHT + ut_metadata ile kendi kendine çözülür.
        if self._try_native_start():
            return

        # ── 2) YEDEK: aria2c köprüsü (yalnız native başlatılamazsa) ─────────
        aria2_bin = shutil.which("aria2c")
        if not aria2_bin:
            # v3.7.1: aria2 yoksa SESSİZCE otomatik kurmayı dene (pkexec onay penceresi
            # açılır; reddedilirse statik ikili arşivi kullanıcı dizinine iner). Başarılı
            # kurulumdan sonra PATH dışındaki konum da doğrudan kullanılır.
            aria2_bin = ensure_aria2_installed()
        if not aria2_bin:
            # Eğer WebSeed varsa doğrudan HTTP aktarımı kullanılabilir; yoksa net kurulum mesajı
            if not self.meta.web_seeds:
                self.error_message = (
                    "BitTorrent motoru (aria2c) kurulamadı. Kontrol Paneli -> 'Eksik Araçları Kur' "
                    "veya paket yöneticinizle 'aria2' kurup tekrar deneyin."
                )
            return

        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.rpc_port = _pick_free_port()
        self.rpc_secret = secrets.token_hex(12)
        dl_dir = self.work_dir / "data"
        dl_dir.mkdir(parents=True, exist_ok=True)

        # v3.7.0: BT/DHT dinleme portlarını da rastgele seç — aynı anda birden çok
        # torrent oturumu açıldığında 6881 çakışması 'Failed to bind' ile motoru
        # düşürüyordu (kullanıcı raporu: 'aria2c RPC servisi başlatılamadı').
        bt_port1, bt_port2 = _pick_free_port(), _pick_free_port()
        dht_port1, dht_port2 = _pick_free_port(), _pick_free_port()
        self.aria2_log_path = self.work_dir / "aria2c.log"

        # v3.7.1 KRİTİK DÜZELTME: aria2c '--dht-entry-point' seçeneği TEK bir HOST:PORT
        # kabul eder; virgüllü liste verilince '[OptionHandlerImpl.cc:469] errorCode=1
        # Unrecognized format' ile SÜREÇ ÇÖKÜYORDU (kullanıcı raporu: 'aria2c süreci
        # beklenmedik şekilde kapandı, çıkış kodu 28'). Artık tek giriş noktası +
        # ÇÖKÜŞTE otomatik 'güvenli minimal argüman' ile ikinci deneme vardır.
        # v3.9.0: canlı (ngosang) tracker listesi + 'bt-prioritize-piece=head' —
        # İLK 48 MB öncelikli iner; IDM saniyeler içinde gerçek bayt görür, '0 B/s +
        # Bağlantı kesildi' penceresi (TPB raporu) kökten biter.
        cmd = [
            aria2_bin,
            "--enable-rpc=true",
            f"--rpc-listen-port={self.rpc_port}",
            "--rpc-listen-all=false",
            f"--rpc-secret={self.rpc_secret}",
            f"--dir={dl_dir}",
            "--seed-time=0",
            "--file-allocation=none",
            "--stream-piece-selector=inorder",
            "--bt-enable-lpd=true",
            "--enable-dht=true",
            "--enable-peer-exchange=true",
            f"--listen-port={bt_port1},{bt_port2}",
            f"--dht-listen-port={dht_port1},{dht_port2}",
            "--bt-max-peers=120",
            "--bt-request-peer-speed-limit=10M",
            "--max-connection-per-server=16",
            "--split=16",
            "--min-split-size=1M",
            "--follow-torrent=mem",
            "--bt-tracker=" + ",".join(merged_tracker_list()),
            "--dht-entry-point=" + DHT_ENTRY_POINTS[0],
            "--bt-prioritize-piece=head=48M",
            "--max-overall-download-limit=0",
            "--quiet=true",
            "--summary-interval=0",
        ]
        # Basitleştirilmiş yedek komut: yalnızca EVRENSEL olarak güvenli seçenekler.
        # Herhangi bir aria2c sürümünde argüman hatası ÜRETMEZ.
        cmd_safe = [
            aria2_bin,
            "--enable-rpc=true",
            f"--rpc-listen-port={self.rpc_port}",
            "--rpc-listen-all=false",
            f"--rpc-secret={self.rpc_secret}",
            f"--dir={dl_dir}",
            "--seed-time=0",
            "--file-allocation=none",
            "--enable-dht=true",
            "--dht-entry-point=" + DHT_ENTRY_POINTS[0],
            "--quiet=true",
        ]

        log.info("aria2c BitTorrent köprüsü başlatılıyor (ticket=%s, port=%d)", self.ticket_id, self.rpc_port)

        rpc_ready = False
        for attempt, launch_cmd in enumerate((cmd, cmd_safe)):
            try:
                aria2_log_fp = open(self.aria2_log_path, "ab")  # noqa: SIM115 — süreç ömrü boyunca açık, stop'ta kapanır
                self._aria2_log_fp = aria2_log_fp
                self.proc = subprocess.Popen(
                    launch_cmd,
                    stdout=aria2_log_fp,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except Exception as exc:
                self.error_message = f"aria2c süreci başlatılamadı: {exc}"
                log.error("aria2c Popen hatası (ticket=%s): %s", self.ticket_id, exc)
                return

            # v3.7.0: RPC hazır olana kadar 12 sn'ye kadar bekle (eski 2.5 sn limiti soğuk
            # başlangıçlarda RPC yanıtını kaçırıp sahte 'başlatılamadı' hatası üretiyordu).
            for _ in range(120):
                if self.proc.poll() is not None:
                    break
                try:
                    ver = self._rpc_call("aria2.getVersion")
                    if ver:
                        rpc_ready = True
                        break
                except Exception:
                    time.sleep(0.1)

            if rpc_ready:
                break

            tail = self._aria2_log_tail()
            if self.proc.poll() is not None:
                # Süreç öldü: tam argümanlı denemeyse 'güvenli' komutla TEK daha dene;
                # o da ölürse kalıcı hata mesajı göster.
                if attempt == 0:
                    log.warning(
                        "aria2c tam argümanlarla çöktü (çıkış %s) — güvenli komutla tekrar deneniyor: %s",
                        self.proc.poll(), tail[:200],
                    )
                    self.rpc_port = _pick_free_port()
                    self.rpc_secret = secrets.token_hex(12)
                    # cmd_safe kendi rpc portunu taşır — yeniden ata
                    for _i, tok in enumerate(cmd_safe):
                        if tok.startswith("--rpc-listen-port="):
                            cmd_safe[_i] = f"--rpc-listen-port={self.rpc_port}"
                    continue
                self.error_message = (
                    f"aria2c süreci beklenmedik şekilde kapandı (çıkış kodu {self.proc.poll()})."
                    + (f" Motor günlüğü: {tail}" if tail else "")
                )
            else:
                self.error_message = (
                    "aria2c RPC servisi zamanında yanıt vermedi."
                    + (f" Motor günlüğü: {tail}" if tail else "")
                )
            log.error("aria2c RPC hazır olmadı (ticket=%s): %s", self.ticket_id, self.error_message)
            return

        if not rpc_ready:
            # döngü bir şekilde rpc_ready olmadan bitti
            tail = self._aria2_log_tail()
            self.error_message = "aria2c RPC servisi başlatılamadı." + (f" Motor günlüğü: {tail}" if tail else "")
            return

        try:
            if self.source_kind == "torrent_file" and self.torrent_file_path and self.torrent_file_path.is_file():
                b64_tor = base64.b64encode(self.torrent_file_path.read_bytes()).decode("ascii")
                self.gid = str(self._rpc_call("aria2.addTorrent", [b64_tor]) or "")
            elif self.magnet_uri:
                self.gid = str(self._rpc_call("aria2.addUri", [[self.magnet_uri]]) or "")
        except Exception as exc:
            self.error_message = f"Torrent görevi eklenemedi: {exc}"
            return

        # v3.9.0: UÇUŞTA TRACKER TAZELEME — arka planda 45 sn'de bir canlı tracker
        # listesi aria2c'ye uygulanır (aria2.changeOption). Ölmüş trackerlar devamedar;
        # eş keşfi hiç durmadan taze kaynaklarla sürer (0 B/s'ye karşı ana kalkan).
        def _tracker_refresher() -> None:
            deadline = time.time() + 6 * 3600.0
            while time.time() < deadline:
                time.sleep(45.0)
                try:
                    if not self.proc or self.proc.poll() is not None:
                        return
                    gid_now = self.gid
                    if not gid_now or not self.rpc_port:
                        continue
                    fresh = ",".join(merged_tracker_list())
                    if not fresh:
                        continue
                    self._rpc_call("aria2.changeOption", [gid_now, {"bt-tracker": fresh}])
                except Exception:
                    continue

        threading.Thread(target=_tracker_refresher, name=f"torrent-tr-{self.ticket_id[:8]}", daemon=True).start()

    # ── v3.13.0 IDM İPTAL / DEVAM YÖNETİMİ ──────────────────────────────────
    def note_client_connect(self) -> None:
        """IDM köprüye bağlandı: istemci sayacını artır, motoru DURDURULMUŞSA devam ettir."""
        with self.lock:
            self.bridge_clients += 1
            self.last_client_ts = time.time()
        if self.engine_paused:
            self.resume_engine()

    def note_client_disconnect(self) -> None:
        """IDM bağlantıyı kesti (indirme bitti / duraklatıldı / İPTAL edildi).

        Tüm istemciler gittiyse zarafet penceresi başlar: 60 sn içinde kimse
        dönmezse motor DURAKLATILIR — kullanıcı IDM'de iptal etse de arka planda
        asla indirme sürmez (kullanıcı kuralı, v3.13.0)."""
        with self.lock:
            self.bridge_clients = max(0, self.bridge_clients - 1)
            self.last_client_ts = time.time()
            no_clients = self.bridge_clients == 0
        if no_clients:
            self._ensure_cancel_watchdog()

    def _ensure_cancel_watchdog(self) -> None:
        with self.lock:
            if self.cancel_watch_started or not self.cancel_watch_run:
                return
            self.cancel_watch_started = True

        def _watch() -> None:
            while self.cancel_watch_run:
                time.sleep(5.0)
                with self.lock:
                    clients = self.bridge_clients
                    idle_for = time.time() - self.last_client_ts
                    paused = self.engine_paused
                if clients == 0 and not paused and idle_for >= self.CLIENT_GONE_GRACE_SEC:
                    self.pause_engine()

        threading.Thread(target=_watch, name=f"bt-cancel-{self.ticket_id[:8]}", daemon=True).start()

    def pause_engine(self) -> None:
        """Motoru DURAKLATIR (arka plan indirmesi tamamen durur; bilet korunur)."""
        with self.lock:
            if self.engine_paused:
                return
            self.engine_paused = True
        n = self.native
        if n is not None and hasattr(n, "pause"):
            try:
                n.pause()
                log.info("Torrent motoru DURAKLATILDI (native, ticket=%s)", self.ticket_id)
                return
            except Exception:
                pass
        if self.gid and self.rpc_port:
            try:
                self._rpc_call("aria2.forcePause", [self.gid])
                log.info("Torrent motoru DURAKLATILDI (aria2, ticket=%s)", self.ticket_id)
            except Exception:
                pass

    def resume_engine(self) -> None:
        """Duraklatılmış motoru kaldığı yerden devam ettirir."""
        with self.lock:
            if not self.engine_paused:
                return
            self.engine_paused = False
        n = self.native
        if n is not None and hasattr(n, "resume"):
            try:
                n.resume()
                log.info("Torrent motoru DEVAM EDİYOR (native, ticket=%s)", self.ticket_id)
                return
            except Exception:
                pass
        if self.gid and self.rpc_port:
            try:
                self._rpc_call("aria2.unpause", [self.gid])
                log.info("Torrent motoru DEVAM EDİYOR (aria2, ticket=%s)", self.ticket_id)
            except Exception:
                pass

    def query_status(self) -> Optional[Dict[str, Any]]:
        if self.native is not None:
            try:
                self._sync_meta_from_native()
                st = self.native.status()
                if isinstance(st, dict):
                    return st
            except Exception as exc:
                log.warning("Native durum okunamadı: %s", exc)
                return None
        if not self.gid or not self.rpc_port:
            return None
        try:
            st = self._rpc_call("aria2.tellStatus", [self.gid])
            if isinstance(st, dict):
                # Magnet meta verisi indiğinde alt görev (followedBy) oluşur -> yeni GID'ye geç!
                followed = st.get("followedBy")
                if isinstance(followed, list) and followed:
                    self.gid = str(followed[0])
                    st2 = self._rpc_call("aria2.tellStatus", [self.gid])
                    if isinstance(st2, dict):
                        return st2
                return st
        except Exception:
            pass
        return None

    def stop_and_cleanup(self) -> None:
        with self.lock:
            if self.native is not None:
                try:
                    self.native.stop()
                except Exception:
                    pass
                self.native = None
            if self.proc and self.proc.poll() is None:
                try:
                    self._rpc_call("aria2.forceShutdown")
                except Exception:
                    pass
                try:
                    self.proc.terminate()
                    self.proc.wait(timeout=2)
                except Exception:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass
            try:
                self.ready.set()
            except Exception:
                pass
            try:
                if getattr(self, "_aria2_log_fp", None):
                    self._aria2_log_fp.close()
                    self._aria2_log_fp = None
            except Exception:
                pass
            try:
                self.cancel_watch_run = False  # v3.13.0: izleyici iş parçacığını bitir
            except Exception:
                pass
            shutil.rmtree(self.work_dir, ignore_errors=True)


class TorrentBridgeManager:
    """
    .torrent dosyalarını ve magnet:? bağlantılarını canlı HTTP akışına (/torrent/<ticket>/<dosya>)
    çevirerek gerçek Windows IDM (IDMan.exe) üzerinden indirilmesini sağlayan köprü yöneticisi.
    """

    def __init__(self, base_temp_dir: Optional[Path] = None) -> None:
        self._base_dir = base_temp_dir or (Path(tempfile.gettempdir()) / "idm-linux-torrents")
        self._lock = threading.Lock()
        self._sessions: Dict[str, TorrentSession] = {}

    def _gc_locked(self) -> None:
        now = time.time()
        expired = [
            tid
            for tid, sess in self._sessions.items()
            if (now - sess.created_at) > 43200  # 12 saat
        ]
        for tid in expired:
            sess = self._sessions.pop(tid, None)
            if sess:
                threading.Thread(target=sess.stop_and_cleanup, daemon=True).start()

    def register_torrent_bytes(self, raw_bytes: bytes) -> TorrentSession:
        meta = parse_torrent_bytes(raw_bytes)
        tid = secrets.token_urlsafe(14)
        wdir = self._base_dir / tid
        wdir.mkdir(parents=True, exist_ok=True)
        tor_file = wdir / "source.torrent"
        tor_file.write_bytes(raw_bytes)

        sess = TorrentSession(
            ticket_id=tid,
            meta=meta,
            work_dir=wdir,
            source_kind="torrent_file",
            torrent_file_path=tor_file,
            magnet_uri=None,
        )
        with self._lock:
            self._gc_locked()
            self._sessions[tid] = sess
        # Arka planda hemen eş (peer) aramayı başlat ki IDM bağlandığında hazır olsun!
        threading.Thread(target=sess.ensure_started, daemon=True).start()
        return sess

    def register_torrent_url(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> TorrentSession:
        u = url.strip()
        if u.lower().startswith("magnet:?"):
            return self.register_magnet(u)

        req_hdrs = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/134.0.0.0 Safari/537.36"
        }
        if headers:
            for k, v in headers.items():
                if v:
                    req_hdrs[k] = v
        req = urllib.request.Request(u, headers=req_hdrs, method="GET")
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        return self.register_torrent_bytes(raw)

    def register_magnet(self, magnet_uri: str) -> TorrentSession:
        meta = parse_magnet_uri(magnet_uri)
        tid = secrets.token_urlsafe(14)
        wdir = self._base_dir / tid
        wdir.mkdir(parents=True, exist_ok=True)

        sess = TorrentSession(
            ticket_id=tid,
            meta=meta,
            work_dir=wdir,
            source_kind="magnet",
            torrent_file_path=None,
            magnet_uri=magnet_uri.strip(),
        )
        with self._lock:
            self._gc_locked()
            self._sessions[tid] = sess
        threading.Thread(target=sess.ensure_started, daemon=True).start()
        return sess

    def get_session(self, ticket_id: str) -> Optional[TorrentSession]:
        with self._lock:
            return self._sessions.get(ticket_id)

    def list_active_summary(self) -> List[Dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions.values())
        out: List[Dict[str, Any]] = []
        for s in sessions:
            st = s.query_status() or {}
            total = int(st.get("totalLength") or s.meta.total_size or 0)
            done = int(st.get("completedLength") or 0)
            speed = int(st.get("downloadSpeed") or 0)
            conns = int(st.get("connections") or 0)
            out.append(
                {
                    "ticket": s.ticket_id,
                    "name": s.meta.name,
                    "status": st.get("status", "preparing" if not s.error_message else "error"),
                    "total_bytes": total,
                    "completed_bytes": done,
                    "speed_bps": speed,
                    "peers": conns,
                    "error": s.error_message,
                }
            )
        return out

    def shutdown_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            s.stop_and_cleanup()


def _ascii_content_disposition(filename: str) -> str:
    safe_ascii = re.sub(r'[^\x20-\x7e]', "_", filename).replace('"', "'")
    encoded = urllib.parse.quote(filename, safe="")
    return f"attachment; filename=\"{safe_ascii}\"; filename*=UTF-8''{encoded}"



def _stream_webseed_direct(
    handler: http.server.BaseHTTPRequestHandler,
    session: "TorrentSession",
    head_only: bool,
    headers_sent: bool = False,
) -> None:
    """BEP 19 WebSeed üzerinden doğrudan köprü akışı (aria2 yoksa veya parça doğrulaması imkânsızsa)."""
    ws_url = session.meta.web_seeds[0]
    if ws_url.endswith("/"):
        ws_url = ws_url + urllib.parse.quote(session.meta.name)
    if head_only and not headers_sent:
        handler.send_response(200)
        handler.send_header("Content-Type", "application/octet-stream")
        handler.send_header("Accept-Ranges", "none")
        handler.send_header("Content-Disposition", _ascii_content_disposition(session.meta.output_filename))
        if session.meta.total_size > 0:
            handler.send_header("Content-Length", str(session.meta.total_size))
        handler.end_headers()
        return

    req = urllib.request.Request(
        ws_url,
        headers={"User-Agent": "IDM-Linux-TorrentBridge/2.5"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as upstream:
        clen = upstream.headers.get("Content-Length") or (
            str(session.meta.total_size) if session.meta.total_size > 0 else None
        )
        if not headers_sent:
            handler.send_response(200)
            handler.send_header("Content-Type", "application/octet-stream")
            handler.send_header("Accept-Ranges", "none")
            handler.send_header("Content-Disposition", _ascii_content_disposition(session.meta.output_filename))
            if clen:
                handler.send_header("Content-Length", clen)
            handler.end_headers()
        while True:
            chunk = upstream.read(65536)
            if not chunk:
                break
            handler.wfile.write(chunk)
            handler.wfile.flush()


def serve_torrent_over_http(
    handler: http.server.BaseHTTPRequestHandler,
    session: TorrentSession,
    head_only: bool = False,
) -> None:
    """v3.13.0 IDM İPTAL DENEYLEME SARMALEYİCİSİ.

    IDM'nin her köprü bağlantısı izlenir:
      - bağlantı açılır  -> motor duraklatılmışsa DEVAM ettirilir,
      - bağlantı KOPARSA (IDM'de iptal/duraklat/sunucu hatası) sessizce kapanır,
      - tüm istemciler gittikten 60 sn sonra motor DURAKLATILIR -> arka planda
        indirme ASLA sürmez (kullanıcı kuralı).
    """
    connect_fn = getattr(session, "note_client_connect", None)
    disconnect_fn = getattr(session, "note_client_disconnect", None)
    tracked = not head_only and callable(connect_fn) and callable(disconnect_fn)
    if tracked:
        try:
            connect_fn()
        except Exception:
            tracked = False
    try:
        _serve_torrent_over_http_impl(handler, session, head_only)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        # IDM koptu — normal durum (iptal/duraklat/tamamlandı). Motorun
        # duraklatması note_client_disconnect içindeki izleyiciye emanet.
        pass
    except OSError:
        pass
    finally:
        if tracked:
            try:
                disconnect_fn()
            except Exception:
                pass


def _serve_torrent_over_http_impl(
    handler: http.server.BaseHTTPRequestHandler,
    session: TorrentSession,
    head_only: bool = False,
) -> None:
    """
    IDMan.exe'nin GET/HEAD /torrent/<ticket>/<dosya> isteğini karşılar:
    - WebSeed varsa ve aria2c kurulu değilse doğrudan WebSeed HTTP akışına köprüler.
    - aria2c çalışıyorsa:
        * Tek dosyalı torrent: bitfield ile doğrulanmış ardışık baytları gerçek zamanlı olarak
          IDM'ye aktarır (%0 -> %100 canlı IDM ilerlemesi!).
        * Çok dosyalı torrent: tamamlanan paket dosyalarını tek bir canlı .tar akışı olarak
          IDM üzerinden kullanıcının İndirilenler klasörüne indirir!
    """
    session.ensure_started()

    # 1) aria2c çalışmıyorsa (rpc_port == 0) ama .torrent içinde WebSeed (BEP 19) varsa doğrudan WebSeed üzerinden aktar!
    if not session.rpc_port and session.meta.web_seeds and not session.meta.is_multi_file:
        _stream_webseed_direct(handler, session, head_only)
        return

    if session.error_message:
        err_bytes = session.error_message.encode("utf-8")
        handler.send_response(503)
        handler.send_header("Content-Type", "text/plain; charset=utf-8")
        handler.send_header("Content-Length", str(len(err_bytes)))
        handler.end_headers()
        if not head_only:
            handler.wfile.write(err_bytes)
        return

    # 2) HEAD isteğinde IDM'yi bekletmeden yanıt ver — ANCAK boyut henüz
    #    bilinmiyorsa (magnet meta verisi yolda) kısa süre bekle: IDM'nin
    #    "boyut görünmüyor" durumu kullanıcı raporunun kök nedeniydi.
    if head_only and not session.meta.is_multi_file and session.meta.total_size <= 0:
        _dl = time.time() + 12.0
        while time.time() < _dl and session.meta.total_size <= 0 and not session.error_message:
            try:
                _st = session.query_status() or {}
                if int(_st.get("totalLength") or 0) > 0:
                    break
            except Exception:
                pass
            time.sleep(0.2)
    if head_only:
        handler.send_response(200)
        handler.send_header("Content-Type", "application/octet-stream")
        handler.send_header("Accept-Ranges", "none")
        handler.send_header("Content-Disposition", _ascii_content_disposition(session.meta.output_filename))
        if not session.meta.is_multi_file and session.meta.total_size > 0:
            handler.send_header("Content-Length", str(session.meta.total_size))
        handler.end_headers()
        return

    # 3) Magnet ise meta verinin çözülmesini ve gerçek dosya bilgisinin oluşmasını bekle
    # v3.9.0: 90 sn -> 150 sn. DHT/tracker soğuk başlangıçlarında meta keşfi 1-2 dk
    # sürebiliyor; erken iptal IDM'de 'Bağlantı kesildi' gösteriyordu. Tracker
    # tazeleme iş parçacığı bu sırada eş keşfini canlı tutar.
    deadline_meta = time.time() + 90.0
    st: Optional[Dict[str, Any]] = None
    while time.time() < deadline_meta:
        st = session.query_status()
        if st:
            files = st.get("files") or []
            total_len = int(st.get("totalLength") or 0)
            st_state = st.get("status", "")
            # "[METADATA]" aşamasını geçtiyse gerçek dosya/boyut belli olmuştur
            bt_info = st.get("bittorrent") or {}
            bt_name = (bt_info.get("info") or {}).get("name")
            if bt_name:
                session.meta.name = str(bt_name)
            if len(files) > 1:
                session.meta.is_multi_file = True
                session.meta.file_count = len(files)
            if total_len > 0 and not str(files[0].get("path", "")).startswith("[METADATA]"):
                session.meta.total_size = total_len
                break
            if st_state in ("error", "removed"):
                break
        time.sleep(0.25)

    st = session.query_status() or {}
    files = st.get("files") or []
    is_multi = session.meta.is_multi_file or len(files) > 1
    out_name = session.meta.output_filename

    if not is_multi:
        total_len = int(st.get("totalLength") or session.meta.total_size or 0)
        if total_len <= 0 and not session.meta.web_seeds:
            # Dürüst hata: sonsuza kadar %0'da bekletmek yerine IDM'ye net mesaj
            body = (
                "Torrent meta verisi alınamadı: DHT/tracker üzerinden dosya bilgisi "
                "gelmedi. Kaynakta tohum (seed) olmayabilir ya da ağ erişimi kapalı. "
                "Birkaç dakika sonra yeniden deneyin."
            ).encode("utf-8")
            handler.send_response(503)
            handler.send_header("Content-Type", "text/plain; charset=utf-8")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return
        handler.send_response(200)
        handler.send_header("Content-Type", "application/octet-stream")
        handler.send_header("Accept-Ranges", "none")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Disposition", _ascii_content_disposition(out_name))
        if total_len > 0:
            handler.send_header("Content-Length", str(total_len))
        handler.end_headers()

        sent_offset = 0
        target_path: Optional[Path] = None
        if files and files[0].get("path"):
            target_path = Path(str(files[0]["path"]))

        loop_start = time.time()
        while True:
            # v2.8.2 sağlamlaştırma: parça hash'leri bozuk/eşleşmezse aria2 ASLA doğrulayamaz;
            # 4 sn grace sonrası WebSeed varsa doğrudan HTTP aktarımına düş (sonsuz beklemeyi kökten bitirir).
            if (
                sent_offset == 0
                and session.meta.web_seeds
                and time.time() - loop_start > 4.0
            ):
                log.warning("Doğrulanmış parça yok (hash uyumsuz?) — WebSeed doğrudan aktarıma geçiliyor.")
                _stream_webseed_direct(handler, session, head_only=False, headers_sent=True)
                return
            cur = session.query_status() or {}
            state = cur.get("status", "")
            cur_files = cur.get("files") or []
            if target_path is None and cur_files and cur_files[0].get("path"):
                target_path = Path(str(cur_files[0]["path"]))

            cur_total = int(cur.get("totalLength") or total_len or 0)
            piece_len = int(cur.get("pieceLength") or session.meta.piece_length or 262144)
            num_pieces = int(cur.get("numPieces") or ((cur_total + piece_len - 1) // max(1, piece_len)))
            bitfield = str(cur.get("bitfield") or "")

            if state == "complete" and cur_total > 0:
                safe_upto = cur_total
            else:
                contig_pieces = count_contiguous_leading_pieces(bitfield, num_pieces)
                safe_upto = min(cur_total, contig_pieces * piece_len)

            if target_path and target_path.is_file() and safe_upto > sent_offset:
                with target_path.open("rb") as fp:
                    fp.seek(sent_offset)
                    while sent_offset < safe_upto:
                        to_read = min(65536, safe_upto - sent_offset)
                        blk = fp.read(to_read)
                        if not blk:
                            break
                        handler.wfile.write(blk)
                        sent_offset += len(blk)
                    handler.wfile.flush()

            if cur_total > 0 and sent_offset >= cur_total:
                break
            if state in ("error", "removed"):
                break
            time.sleep(0.15)
        return

    # 4) Çok dosyalı torrent: tamamlandığında tek parça canlı .tar akışı olarak IDM'ye gönder!
    handler.send_response(200)
    handler.send_header("Content-Type", "application/x-tar")
    handler.send_header("Accept-Ranges", "none")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Disposition", _ascii_content_disposition(out_name))
    handler.end_headers()

    # v3.11.0 KRİTİK SIZINTI DÜZELTMESİ: 'while True' döngüsünün ZAMAN AŞIMI YOKTU —
    # torrent tamamlanmazsa istek NİTELİKSİZ SONSUZA kadar bekler, HTTP iş parçacığı ve
    # IDM bağlantısı kilitlenirdi (kullanıcı: "0 B/s ile saatlerce bekliyor"). Artık
    # 15 dakikalık dürüst sınır var: aşılsa 503 hatasıyla net şekilde kapanır.
    tar_deadline = time.time() + 900.0
    while True:
        cur = session.query_status() or {}
        state = cur.get("status", "")
        if state == "complete":
            break
        if state in ("error", "removed"):
            return
        if time.time() > tar_deadline:
            log.warning("Çok dosyalı torrent 15 dk içinde tamamlanamadı — tar akışı iptal.")
            return
        time.sleep(0.3)

    dl_root = session.work_dir / "data"
    with tarfile.open(mode="w|", fileobj=handler.wfile) as tf:
        if dl_root.is_dir():
            for child in sorted(dl_root.iterdir()):
                tf.add(str(child), arcname=child.name)
    handler.wfile.flush()
