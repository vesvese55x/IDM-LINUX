"""Tracker anonsları — HTTP(S) (BEP 3) ve UDP (BEP 15).

Kendi motorumuz için yazıldı; requests/aria2 bağımlılığı yok. Tüm hatalar
istisna yerine ``error`` alanında döner: bir tracker'ın ölmesi indirmeyi durdurmaz.
"""
from __future__ import annotations

import logging
import random
import socket
import struct
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .bencode import bdecode

log = logging.getLogger("idm_linux.p2p.tracker")

_UA = "IDM-Linux/1.0 (kendi BitTorrent motoru)"
_PEER_ID = b"-ID3A00-" + bytes(random.randint(0, 255) for _ in range(12))

#: Protokolü açıkça desteklemeyen sağlayıcıların spam'ini engellemek için üst sınır
MAX_TRACKERS = 60


def normalize_trackers(items: Iterable[str]) -> List[str]:
    """Tracker listesini tekilleştirir; yalnız http(s)/udp şemaları kalır."""
    out: List[str] = []
    seen = set()
    for raw in items or []:
        url = (raw or "").strip()
        if not url:
            continue
        low = url.lower()
        if not low.startswith(("http://", "https://", "udp://")):
            continue
        if low.endswith("/announce") is False and low.startswith("udp://"):
            pass  # UDP tracker'lar port ile biter; yine de kabul
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= MAX_TRACKERS:
            break
    return out


def _quote_bytes(raw: bytes) -> str:
    """Ham baytları tracker sorgu parametresi biçimine çevirir (%XX)."""
    return "".join("%%%02X" % b for b in raw)


def announce_http(
    tracker: str,
    info_hash: bytes,
    peer_id: bytes,
    port: int,
    *,
    uploaded: int = 0,
    downloaded: int = 0,
    left: int = 0,
    event: str = "",
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """Tek HTTP(S) tracker'a anons. Döner: {peers, interval, complete, incomplete, error}"""
    params = [
        ("info_hash", _quote_bytes(info_hash)),
        ("peer_id", _quote_bytes(peer_id)),
        ("port", str(int(port))),
        ("uploaded", str(int(uploaded))),
        ("downloaded", str(int(downloaded))),
        ("left", str(int(left))),
        ("compact", "1"),
        ("numwant", "80"),
    ]
    if event:
        params.append(("event", event))
    sep = "&" if "?" in tracker else "?"
    url = tracker + sep + "&".join(f"{k}={v}" for k, v in params)
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(512 * 1024)
    except Exception as exc:
        return {"peers": [], "interval": 1800, "complete": 0, "incomplete": 0,
                "error": f"{type(exc).__name__}: {exc}"}
    try:
        data = bdecode(body)
    except Exception as exc:
        return {"peers": [], "interval": 1800, "complete": 0, "incomplete": 0,
                "error": f"geçersiz yanıt: {exc}"}
    if not isinstance(data, dict):
        return {"peers": [], "interval": 1800, "complete": 0, "incomplete": 0,
                "error": "geçersiz yanıt gövdesi"}
    if b"failure reason" in data:
        reason = data[b"failure reason"]
        text = reason.decode("utf-8", "replace") if isinstance(reason, bytes) else str(reason)
        return {"peers": [], "interval": 1800, "complete": 0, "incomplete": 0,
                "error": text[:200]}
    peers = _parse_peers(data.get(b"peers"))
    peers.extend(_parse_peers(data.get(b"peers6"), ipv6=True))
    return {
        "peers": peers,
        "interval": _as_int(data.get(b"interval"), 1800),
        "min_interval": _as_int(data.get(b"min interval"), 0),
        "complete": _as_int(data.get(b"complete"), 0),
        "incomplete": _as_int(data.get(b"incomplete"), 0),
        "error": "",
    }


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_peers(blob: Any, ipv6: bool = False) -> List[Tuple[str, int]]:
    """Compact (6/18 bayt) veya sözlük listesi biçimindeki eş listesini çözer."""
    out: List[Tuple[str, int]] = []
    if not blob:
        return out
    if isinstance(blob, bytes):
        size = 18 if ipv6 else 6
        for off in range(0, len(blob) - size + 1, size):
            chunk = blob[off: off + size]
            try:
                if ipv6:
                    addr = socket.inet_ntop(socket.AF_INET6, chunk[:16])
                    port = struct.unpack(">H", chunk[16:18])[0]
                else:
                    addr = socket.inet_ntoa(chunk[:4])
                    port = struct.unpack(">H", chunk[4:6])[0]
            except (OSError, ValueError):
                continue
            if port > 0:
                out.append((addr, port))
        return out
    if isinstance(blob, list):
        for item in blob:
            if not isinstance(item, dict):
                continue
            ip = item.get(b"ip")
            port = _as_int(item.get(b"port"), 0)
            if isinstance(ip, bytes) and port > 0:
                out.append((ip.decode("utf-8", "replace"), port))
    return out


def announce_udp(
    tracker: str,
    info_hash: bytes,
    peer_id: bytes,
    port: int,
    *,
    uploaded: int = 0,
    downloaded: int = 0,
    left: int = 0,
    event: str = "",
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """UDP tracker (BEP 15) anonsu.

    v3.13.0: BEP 15 önerisi gereği connect/announce paketleri 3'e kadar
    YENİDEN DENENİR — tek UDP paketi kaybolan trackerlar artık ölü sanılmaz;
    ilk denemede eş bulamama (TPB 0 B/s vakası) ciddi ölçüde azalır."""
    err = {"peers": [], "interval": 1800, "complete": 0, "incomplete": 0, "error": ""}
    try:
        parsed = urllib.parse.urlsplit(tracker)
        host = parsed.hostname or ""
        host_port = parsed.port or 80
        if not host:
            err["error"] = "geçersiz udp tracker adresi"
            return err
        addr = (host, host_port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            # 1) connect isteği (BEP 15: 3 deneme, 2^n * 60 sn — biz kısa tutarız)
            conn_id = 0
            got_connect = False
            for attempt in range(3):
                try:
                    tid = random.randint(0, 0xFFFFFFFF)
                    sock.sendto(struct.pack(">QII", 0x41727101980, 0, tid), addr)
                    data, _ = sock.recvfrom(2048)
                    if len(data) < 16:
                        err["error"] = "connect yanıtı kısa"
                        continue
                    action, rtid, conn_id = struct.unpack(">IIQ", data[:16])
                    if action == 0 and rtid == tid:
                        got_connect = True
                        break
                except socket.timeout:
                    continue
            if not got_connect:
                if not err["error"]:
                    err["error"] = "connect zaman aşımı (3 deneme)"
                return err
            # 2) announce isteği (aynı şekilde 3 deneme)
            announce_data = b""
            for attempt in range(3):
                try:
                    tid = random.randint(0, 0xFFFFFFFF)
                    event_id = {"": 0, "completed": 1, "started": 2, "stopped": 3}.get(event, 0)
                    packet = struct.pack(
                        ">QII20s20sQQQIIIiH",
                        conn_id, 1, tid, info_hash, peer_id,
                        downloaded, left, uploaded, event_id, 0, random.randint(0, 0xFFFF), -1, port,
                    )
                    sock.sendto(packet, addr)
                    announce_data, _ = sock.recvfrom(8192)
                    break
                except socket.timeout:
                    continue
            if not announce_data:
                err["error"] = "announce zaman aşımı (3 deneme)"
                return err
        finally:
            sock.close()
        if len(announce_data) < 20:
            err["error"] = "announce yanıtı kısa"
            return err
        action, rtid = struct.unpack(">II", announce_data[:8])
        if action == 3:
            err["error"] = announce_data[8:208].decode("utf-8", "replace")
            return err
        if action != 1:
            err["error"] = "announce yanıtı geçersiz"
            return err
        interval, _leechers, seeders = struct.unpack(">III", announce_data[8:20])
        peers = _parse_peers(announce_data[20:])
        err.update(
            {
                "peers": peers,
                "interval": max(60, interval),
                "complete": seeders,
                "incomplete": _leechers,
            }
        )
        return err
    except Exception as exc:
        err["error"] = f"{type(exc).__name__}: {exc}"
        return err


def announce_all(
    trackers: Sequence[str],
    info_hash: bytes,
    peer_id: bytes,
    port: int,
    *,
    uploaded: int = 0,
    downloaded: int = 0,
    left: int = 0,
    event: str = "",
    timeout: float = 8.0,
) -> List[Dict[str, Any]]:
    """Tüm tracker'lara SIRAYLA (ama toplam süre sınırlı) anons eder.

    Not: v3.13.0 denenen tracker sayısı 12 -> 24 çıkarıldı (TPB gibi geniş
    torrentlerde tek ölü tracker turu eş keşfini geciktirmesin); paralel havuz
    12 işçiyle çalışır ve indirmeyi bloke etmez.
    """
    import concurrent.futures

    trackers = normalize_trackers(trackers)[:24]
    if not trackers:
        return []
    results: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, len(trackers))) as pool:
        futures = []
        for tracker in trackers:
            func = announce_udp if tracker.lower().startswith("udp://") else announce_http
            futures.append(
                pool.submit(
                    func, tracker, info_hash, peer_id, port,
                    uploaded=uploaded, downloaded=downloaded, left=left,
                    event=event, timeout=timeout,
                )
            )
        for fut, tracker in zip(futures, trackers):
            try:
                res = fut.result(timeout=timeout + 5)
            except Exception as exc:
                res = {"peers": [], "error": f"{type(exc).__name__}: {exc}"}
            res["tracker"] = tracker
            results.append(res)
    return results
