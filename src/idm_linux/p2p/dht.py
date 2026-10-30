"""BEP 5 Kademlia DHT istemcisi (magnet bağlantılarında eş bulmak için).

Sıfırdan, saf Python ve tek UDP soketi ile çalışır:
  * ``bootstrap()``  — yönlendirici düğümlerden kademeli olarak düğüm tablosunu doldurur
  * ``get_peers()``  — info-hash için yinelemeli (iterative) arama, eş adresleri döner
  * ``announce_peer()`` — isteğe bağlı: kendimizi bildirir (yalnız seed olursak)
  * gelen ``ping`` / ``find_node`` / ``get_peers`` sorgularına da yanıt verir
    (karşı tarafın tablosuna girebilmek için gerekir)

Tasarım notu: eşzamanlı (thread'li) ağ işi nedeniyle tek soket üzerinden gelen
yanıtlar işlem kimliğine (transaction id) göre bekleyen çağrılara dağıtılır.
"""
from __future__ import annotations

import logging
import os
import random
import socket
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .bencode import bdecode, bencode

log = logging.getLogger("idm_linux.p2p.dht")

DEFAULT_BOOTSTRAP_NODES: List[Tuple[str, int]] = [
    ("router.bittorrent.com", 6881),
    ("dht.transmissionbt.com", 6881),
    ("router.utorrent.com", 6881),
    ("dht.libtorrent.org", 25401),
    ("dht.aelitis.com", 6881),
]

MAX_NODES = 400


def _xor_distance(a: bytes, b: bytes) -> int:
    return int.from_bytes(bytes(x ^ y for x, y in zip(a, b)), "big")


def _encode_nodes(nodes: Sequence[Tuple[bytes, str, int]]) -> bytes:
    out = bytearray()
    for nid, ip, port in nodes[:8]:
        try:
            out += nid[:20].ljust(20, b"\x00")
            out += socket.inet_aton(ip)
            out += struct.pack(">H", int(port) & 0xFFFF)
        except OSError:
            continue
    return bytes(out)


def _decode_nodes(blob: bytes) -> List[Tuple[bytes, str, int]]:
    nodes: List[Tuple[bytes, str, int]] = []
    if not isinstance(blob, (bytes, bytearray)):
        return nodes
    for off in range(0, len(blob) - 25, 26):
        chunk = blob[off: off + 26]
        try:
            ip = socket.inet_ntoa(chunk[20:24])
            port = struct.unpack(">H", chunk[24:26])[0]
        except OSError:
            continue
        if port:
            nodes.append((chunk[:20], ip, port))
    return nodes


class DHTNode:
    """Küçük ama işlevsel bir DHT düğümü."""

    def __init__(
        self,
        listen_port: int = 0,
        bootstrap_nodes: Optional[Sequence[Tuple[str, int]]] = None,
    ) -> None:
        self.node_id = os.urandom(20)
        self.bootstrap_nodes = list(bootstrap_nodes or DEFAULT_BOOTSTRAP_NODES)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", int(listen_port or 0)))
        self.sock.settimeout(0.5)
        self.listen_port = self.sock.getsockname()[1]
        self.nodes: Dict[bytes, Tuple[str, int]] = {}
        self.tokens: Dict[str, bytes] = {}
        self._pending: Dict[bytes, List[Any]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._bootstrapped = False

    # ── yaşam döngüsü ───────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._serve, name="dht-serve", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass

    # ── sunucu döngüsü ──────────────────────────────────────────────────────
    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = bdecode(data)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            try:
                if b"y" in msg and msg[b"y"] == b"r":
                    tid = msg.get(b"t") or b""
                    with self._lock:
                        waiter = self._pending.get(tid)
                    if waiter:
                        waiter[1] = msg
                        waiter[0].set()
                elif msg.get(b"y") == b"q":
                    self._handle_query(msg, addr)
            except Exception:  # pragma: no cover - savunma
                continue

    def _handle_query(self, msg: Dict[bytes, Any], addr: Tuple[str, int]) -> None:
        args = msg.get(b"a") or {}
        method = msg.get(b"q") or b""
        tid = msg.get(b"t") or b""
        reply: Dict[bytes, Any] = {b"t": tid, b"y": b"r", b"r": {b"id": self.node_id}}
        if method == b"ping":
            pass
        elif method == b"find_node":
            reply[b"r"][b"nodes"] = _encode_nodes(
                [(nid, ip, port) for nid, (ip, port) in list(self.nodes.items())[:8]]
            )
        elif method == b"get_peers":
            token = os.urandom(4).hex().encode()
            self.tokens[addr[0]] = token
            reply[b"r"][b"token"] = token
            reply[b"r"][b"nodes"] = _encode_nodes(
                [(nid, ip, port) for nid, (ip, port) in list(self.nodes.items())[:8]]
            )
        elif method == b"announce_peer":
            pass
        else:
            return
        try:
            self.sock.sendto(bencode(reply), addr)
        except OSError:
            pass

    # ── istemci tarafı ──────────────────────────────────────────────────────
    def _query(
        self,
        addr: Tuple[str, int],
        method: bytes,
        args: Dict[bytes, Any],
        timeout: float = 4.0,
    ) -> Optional[Dict[bytes, Any]]:
        tid = struct.pack(">H", random.randint(0, 0xFFFF)) + os.urandom(2)
        payload = {b"t": tid, b"y": b"q", b"q": method, b"a": dict(args, id=self.node_id)}
        waiter = [threading.Event(), None]
        with self._lock:
            self._pending[tid] = waiter
        try:
            try:
                self.sock.sendto(bencode(payload), addr)
            except OSError:
                return None
            if not waiter[0].wait(timeout):
                return None
            reply = waiter[1]
        finally:
            with self._lock:
                self._pending.pop(tid, None)
        if isinstance(reply, dict):
            result = reply.get(b"r") or {}
            nodes = _decode_nodes(result.get(b"nodes") or b"")
            if nodes:
                self._remember(nodes)
            return result
        return None

    def _remember(self, nodes: Sequence[Tuple[bytes, str, int]]) -> None:
        with self._lock:
            for nid, ip, port in nodes:
                if nid == self.node_id or ip.startswith("0."):
                    continue
                self.nodes.setdefault(nid, (ip, port))
            if len(self.nodes) > MAX_NODES:
                # en "uzak" düğümleri at (basit kırpma)
                excess = len(self.nodes) - MAX_NODES
                for nid in list(self.nodes.keys())[:excess]:
                    self.nodes.pop(nid, None)

    def bootstrap(self, timeout: float = 8.0) -> int:
        """Yönlendirici düğümlerden tabloyu doldurur; bulunan düğüm sayısını döner.
        v3.11.0: SIRALI döngü PARALEL havuza çevrildi — eski yöntemde 5 router ×
        (bloklayan gethostbyname + 1.5 sn sorgu) onlarca saniye uzayabiliyordu
        (slow DNS tek başına 10 sn'lik bütçeyi yutuyordu). Artık tüm router sorguları
        AYNI ANDA fırlatılır; DNS de havuzda zaman sınırlı çözülür."""
        import concurrent.futures as _cf

        started = time.time()
        deadline = started + max(3.0, timeout)

        def _resolve(host: str, port: int) -> Optional[Tuple[str, int]]:
            box: list = []

            def _job() -> None:
                try:
                    box.append((socket.gethostbyname(host), port))
                except OSError:
                    pass

            th = threading.Thread(target=_job, daemon=True)
            th.start()
            th.join(timeout=min(2.5, max(0.5, timeout / 3)))
            return box[0] if box else None

        # 1) Tüm yönlendiricilere find_node (PARALEL)
        addrs: List[Tuple[str, int]] = []
        with _cf.ThreadPoolExecutor(max_workers=len(self.bootstrap_nodes) or 1) as ex:
            futs = [ex.submit(_resolve, h, p) for h, p in self.bootstrap_nodes]
            for fu in futs:
                try:
                    a = fu.result(timeout=3.0)
                except Exception:
                    a = None
                if a:
                    addrs.append(a)
        if addrs and time.time() < deadline:
            with _cf.ThreadPoolExecutor(max_workers=min(8, len(addrs))) as ex:
                for _ in ex.map(
                    lambda a: self._query(a, b"find_node", {b"target": self.node_id}, timeout=1.5),
                    addrs,
                ):
                    pass
        # 2) Tabloyu kademeli genişlet (PARALEL 10'lu gruplar)
        for _round in range(3):
            if time.time() > deadline:
                break
            with self._lock:
                batch = list(self.nodes.items())[:10]
            if not batch:
                break
            before = len(self.nodes)
            with _cf.ThreadPoolExecutor(max_workers=min(10, len(batch))) as ex:
                for _ in ex.map(
                    lambda kv: self._query(kv[1], b"find_node", {b"target": self.node_id}, timeout=1.5),
                    batch,
                ):
                    pass
            if len(self.nodes) == before:
                break
        self._bootstrapped = bool(self.nodes)
        return len(self.nodes)

    def get_peers(self, info_hash: bytes, timeout: float = 15.0) -> List[Tuple[str, int]]:
        """Info-hash için yinelemeli arama; bulunan (ip, port) eşlerini döner.
        v3.11.0: her turdaki 8 sorgu PARALEL fırlatılır (eski sıralı akışta 8 × 3 sn
        timeout = tur başına 24 sn kayıp; paralel akışta tur süresi tek sorgu süresidir)."""
        import concurrent.futures as _cf

        if not self.nodes:
            self.bootstrap(timeout=min(6.0, timeout / 2))
        if not self.nodes:
            return []
        deadline = time.time() + max(4.0, timeout)
        peers: List[Tuple[str, int]] = []
        seen = set()
        queried = set()
        for _round in range(4):
            if time.time() > deadline:
                break
            cand = sorted(self.nodes.items(), key=lambda kv: _xor_distance(kv[0], info_hash))
            batch = [(nid, addr) for nid, addr in cand if nid not in queried][:8]
            if not batch:
                break
            for nid, _a in batch:
                queried.add(nid)

            def _ask(addr: Tuple[str, int]) -> Optional[Dict[bytes, Any]]:
                return self._query(addr, b"get_peers", {b"info_hash": info_hash}, timeout=3.0)

            results: List[Tuple[Tuple[str, int], Optional[Dict[bytes, Any]]]] = []
            with _cf.ThreadPoolExecutor(max_workers=min(8, len(batch))) as ex:
                futs = {ex.submit(_ask, a): a for _n, a in batch}
                for fu in _cf.as_completed(futs):
                    try:
                        results.append((futs[fu], fu.result(timeout=3.5)))
                    except Exception:
                        results.append((futs[fu], None))
            for addr, res in results:
                if not res:
                    continue
                token = res.get(b"token")
                if token:
                    self.tokens[addr[0]] = token if isinstance(token, bytes) else b""
                values = res.get(b"values")
                if isinstance(values, list):
                    for item in values:
                        if isinstance(item, bytes) and len(item) >= 6:
                            try:
                                ip = socket.inet_ntoa(item[:4])
                                port = struct.unpack(">H", item[4:6])[0]
                            except OSError:
                                continue
                            key = (ip, port)
                            if port and key not in seen:
                                seen.add(key)
                                peers.append(key)
                if len(peers) >= 60:
                    return peers
        return peers

    def announce_peer(self, info_hash: bytes, port: int, timeout: float = 6.0) -> None:
        """Kendimizi en yakın 8 düğüme bildirir (isteğe bağlı, seed için)."""
        if not self.nodes:
            return
        cand = sorted(self.nodes.items(), key=lambda kv: _xor_distance(kv[0], info_hash))[:8]
        for _nid, addr in cand:
            token = self.tokens.get(addr[0])
            if not token:
                continue
            self._query(
                addr,
                b"announce_peer",
                {
                    b"info_hash": info_hash,
                    b"port": int(port),
                    b"token": token,
                    b"implied_port": 1,
                },
                timeout=min(3.0, timeout),
            )
