"""v2.9.4: abyss.to / abyssplayer.com video motoru.

İki açık kaynak implementasyonun (github.com/abdlhay/AbyssVideoDownloader [Kotlin]
ve github.com/JonasCaetanoSz/AbyssVideoDownloader [Python]) didik didik analiziyle
çıkarılmış protokol:

  1) META : GET https://abysscdn.com/info/{slug}
            başlıklar: x-client-screen, Referer, User-Agent, x-referer
            yanıt: {user_id, slug, md5_id, title, duration, media:<şifreli metin>}
  2) ANAHTAR: md5(f"{user_id}:{slug}:{md5_id}") hex dizgesi (32 ascii bayt)
            AES-256-CTR, sayaç = anahtarın ilk 16 baytı (big-endian), nonce yok
            -> media metni çözülünce {mp4: {domains:[...], sources:[...]}} JSON'u
  3) SEGMENT: boyut anahtarı = md5(boyutun rakam baytları)
            yol = /mp4/{md5_id}/{res_id}/{size}/{fragment}/{index}
            token = B64(B64(AES-CTR-encrypt(yol)))  (padding '=' yok)
            url  = https://{domain}/sora/{size}/{token}
            başlıklar: Referer https://abysscdn.com/

Bu modül harici kripto paketi gerektirmez: AES-256 saf Python'da implemente
edilmiştir (FIPS-197 test vektörü test_suite ile doğrulanır).
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_FRAG = 2097152
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
_INFO_HEADERS = {
    "x-client-screen": "1366x768",
    "x-referer": "https://embedplayabyss.top/",
    "User-Agent": _UA,
}
_SEG_HEADERS = {
    "Referer": "https://abysscdn.com/",
    "x-referer": "https://embedplayabyss.top/",
    "Origin": "https://abysscdn.com",
    "User-Agent": _UA,
}

# v3.1.0: Android AbyssVideoPort.java'dan birebir uyarlanan HTML desenleri
_RE_DATAS = re.compile(r'const\s+datas\s*=\s*"([^"]*)"')
_RE_DATAS_FB = re.compile(r'datas\s*=\s*"([^"]*)"')
_RE_PLAYER_ATOB = re.compile(r'PLAYER\(atob\("([^"]+)"\)\)')

_ABYSS_EMBED_HOSTS = ("abyssplayer.com", "abysscdn.com", "embedplayabyss.top", "abyss.to", "short.icu")


# ---------------------------------------------------------------------------
# Saf Python AES-256 (yalnızca şifreleme yönü; CTR modu simetriktir)
# ---------------------------------------------------------------------------
def _gf_tables() -> Tuple[List[int], List[int]]:
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        # x *= 3 (GF(2^8), AES polinomu 0x11B) — 3 tam ilkel köktür
        y = x << 1
        if y & 0x100:
            y ^= 0x11B
        x = y ^ x
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_EXP, _LOG = _gf_tables()


def _gmul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _sbox() -> List[int]:
    sb = [0] * 256
    for i in range(256):
        inv = 0 if i == 0 else _EXP[255 - _LOG[i]]
        v = inv
        s = inv
        for _ in range(4):
            s = ((s << 1) | (s >> 7)) & 0xFF
            v ^= s
        sb[i] = v ^ 0x63
    return sb


_SBOX = _sbox()


def _key_expand(key: bytes) -> List[int]:
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i : 4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = ((rcon << 1) ^ (0x11B if rcon & 0x80 else 0)) & 0xFF
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return [b for row in w for b in row]


def _aes_encrypt_block(sched: List[int], block: bytes, nr: int) -> bytes:
    s = list(block)
    # round 0
    for i in range(16):
        s[i] ^= sched[i]
    for rnd in range(1, nr + 1):
        # SubBytes
        s = [_SBOX[b] for b in s]
        # ShiftRows
        s = [
            s[0], s[5], s[10], s[15],
            s[4], s[9], s[14], s[3],
            s[8], s[13], s[2], s[7],
            s[12], s[1], s[6], s[11],
        ]
        # MixColumns (son turda yok)
        if rnd != nr:
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c], s[4 * c + 1], s[4 * c + 2], s[4 * c + 3]
                s[4 * c] = _gmul(a0, 2) ^ _gmul(a1, 3) ^ a2 ^ a3
                s[4 * c + 1] = a0 ^ _gmul(a1, 2) ^ _gmul(a2, 3) ^ a3
                s[4 * c + 2] = a0 ^ a1 ^ _gmul(a2, 2) ^ _gmul(a3, 3)
                s[4 * c + 3] = _gmul(a0, 3) ^ a1 ^ a2 ^ _gmul(a3, 2)
        # AddRoundKey
        for i in range(16):
            s[i] ^= sched[rnd * 16 + i]
    return bytes(s)


def ctr_crypt(key: bytes, initial_counter: int, data: bytes) -> bytes:
    """AES-CTR: şifreleme == çözme (XOR akışı)."""
    nr = {16: 10, 24: 12, 32: 14}[len(key)]
    sched = _key_expand(key)
    out = bytearray()
    ctr = initial_counter & ((1 << 128) - 1)
    for off in range(0, len(data), 16):
        stream = _aes_encrypt_block(sched, ctr.to_bytes(16, "big"), nr)
        chunk = data[off : off + 16]
        out += bytes(c ^ stream[i] for i, c in enumerate(chunk))
        ctr = (ctr + 1) & ((1 << 128) - 1)
    return bytes(out)


# ---------------------------------------------------------------------------
# Abyss protokol yardımcıları
# ---------------------------------------------------------------------------
def expand_key(user_id: Any, slug: str, md5_id: str) -> bytes:
    value = f"{user_id}:{slug}:{md5_id}"
    return hashlib.md5(value.encode("utf-8")).hexdigest().encode("utf-8")


def decrypt_media(media_text: str, key: bytes) -> Dict[str, Any]:
    raw = bytes(ord(c) for c in media_text)
    counter = int.from_bytes(key[:16], byteorder="big")
    plain = ctr_crypt(key, counter, raw)
    return json.loads(plain.decode("utf-8"))


def generate_size_key(size: int) -> str:
    s = str(size)
    data = bytearray()
    for ch in s:
        data.append(int(ch) if ch.isdigit() else ord(ch))
    return hashlib.md5(bytes(data)).hexdigest()


def encrypt_path(path_str: str, key_hex: str) -> str:
    key_bytes = key_hex.encode()
    iv = int.from_bytes(key_bytes[:16], "big")
    enc = ctr_crypt(key_bytes, iv, path_str.encode())
    first = base64.b64encode(enc).decode().rstrip("=")
    second = base64.b64encode(first.encode()).decode().rstrip("=")
    return second


@dataclass
class AbyssSource:
    label: str
    size: int
    res_id: str
    part_size: int
    sub: str
    status: Optional[bool] = None  # v3.1.0: Java'daki optBoolean("status") karşılığı


@dataclass
class AbyssMeta:
    slug: str
    title: str
    duration: int
    md5_id: str
    domains: List[str] = field(default_factory=list)
    sources: List[AbyssSource] = field(default_factory=list)


_META_CACHE: Dict[str, Tuple[float, AbyssMeta]] = {}
_META_LOCK = threading.Lock()


def _cache_meta(meta: AbyssMeta) -> None:
    with _META_LOCK:
        _META_CACHE[meta.slug] = (_now(), meta)
        while len(_META_CACHE) > 40:
            _META_CACHE.pop(next(iter(_META_CACHE)))


def _abyss_fetch_html(url: str, referer: str = "") -> str:
    """v3.1.0: abyss oynatıcı/short.icu HTML'sini Android uygulamasındaki gibi çeker.
    Referer yoksa belgeselsemo varsayılanı kullanılır (Cloudflare koşulsuz geçit için)."""
    ref = referer or "https://belgeselsemo.com.tr/"
    pr = urllib.parse.urlparse(ref)
    headers = {
        "User-Agent": _UA,
        "Referer": ref,
        "Origin": f"{pr.scheme}://{pr.netloc}" if pr.scheme and pr.netloc else "https://belgeselsemo.com.tr",
        "Accept-Language": "tr,en;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _b64_tolerant_decode(blob: str) -> bytes:
    """v3.1.0: Base64.COMMON | URL_SAFE | NO_WRAP karışımlarını tolere eden çözücü."""
    cleaned = re.sub(r"\s+", "", blob or "").replace("-", "+").replace("_", "/")
    pad = (-len(cleaned)) % 4
    return base64.b64decode(cleaned + "=" * pad)


def _parse_outer_blob(blob: str) -> Optional[Dict[str, Any]]:
    """v3.1.0: 'const datas=...' / PLAYER(atob(...)) blob'unu JSON'a çözer.
    Java ile birebir: ISO-8859-1 (latin-1) String dönüşümü — her bayt 1:1 karakter olur;
    media alanındaki ham baytlar bozulmadan kalır. strict=False: JSON string içindeki
    kontrol karakterlerini org.json gibi tolere eder."""
    if not blob:
        return None
    try:
        decoded = _b64_tolerant_decode(blob)
        text = decoded.decode("latin-1")
        obj = json.loads(text, strict=False)
        if isinstance(obj, dict) and (obj.get("slug") or obj.get("media")):
            return obj
    except Exception:
        pass
    return None


def _meta_from_outer(slug_hint: str, data: Dict[str, Any]) -> Optional[AbyssMeta]:
    """v3.1.0: dış datas JSON'u (user_id/slug/md5_id/media) -> çözülmüş AbyssMeta.
    Java'daki akış: media AES-256-CTR (anahtar = md5(user_id:slug:md5_id) hex ascii)."""
    slug = str(data.get("slug") or slug_hint or "").strip()
    md5id = str(data.get("md5_id") or data.get("md5Id") or "")
    media_text = data.get("media") or ""
    uid = data.get("user_id", data.get("userId", 0))
    if not slug or not md5id or not media_text:
        return None
    try:
        key = expand_key(uid, slug, md5id)
        media = decrypt_media(media_text, key)
    except Exception:
        return None
    fmt = media.get("mp4") or next(iter(media.values()), {})
    meta = _build_meta(slug, data, fmt)
    # v3.1.0 Java filtresi: status açıkça false ise AT (Java: optBoolean("status", false));
    # alan hiç yoksa (klasik info ucu) kaynağı koru; ayrıca size>0, res_id>0, sub dolu şart
    meta.sources = [
        s for s in meta.sources
        if s.status is not False
        and s.size > 0 and str(s.res_id) not in ("", "0") and s.sub and s.label and s.label != "?"
    ]
    if not meta.sources:
        return None
    return meta


def abyss_resolve_from_page(embed_url: str, referer: str = "") -> Optional[AbyssMeta]:
    """v3.1.0 ANAHTAR FONKSİYON — Android AbyssVideoPort.java'dan uyarlandı:
      1) oynatıcı/short.icu sayfasının HTML'ini çek (Referer: belgeselsemo/anlık sayfa)
      2) HTML içindeki 'const datas = "BASE64"' blob'unu bul (3 desen)
      3) base64 -> JSON {user_id, slug, md5_id, media}
      4) media'yı md5(user_id:slug:md5_id) anahtarıyla AES-CTR çöz -> mp4.sources/domains
    abysscdn info ucu öldüğünde bile kaynak listesi BÖYLE çıkar."""
    url = (embed_url or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://short.icu/" + url
    try:
        html = _abyss_fetch_html(url, referer)
    except Exception:
        return None
    blob = ""
    m = _RE_DATAS.search(html) or _RE_DATAS_FB.search(html) or _RE_PLAYER_ATOB.search(html)
    if m:
        blob = m.group(1)
    if not blob:
        return None
    outer = _parse_outer_blob(blob)
    if not outer:
        return None
    meta = _meta_from_outer("", outer)
    if meta:
        _cache_meta(meta)
    return meta


def abyss_fetch_metadata(slug: str, referer: str = "", embed_url: str = "") -> Optional[AbyssMeta]:
    """v3.1.0 ÜÇ YOLLU çözümleme:
      1) önbellek (10 dk),
      2) abysscdn.com/info/{slug} (klasik uç),
      3) SAYFA ÇÖZÜCÜ — embed_url (abyss.to/v/xxx) veya short.icu/{slug} HTML datas blob'u
    (Android projesinde kanıtlanmış yol) — belgeselsemo.com.tr abyss.to fixi."""
    slug = (slug or "").strip()
    if not slug:
        return None
    with _META_LOCK:
        hit = _META_CACHE.get(slug)
        if hit and (hit[0] > _now() - 600):
            return hit[1]
    url = f"https://abysscdn.com/info/{slug}"
    headers = dict(_INFO_HEADERS)
    headers["Referer"] = referer or "https://abysscdn.com/"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        media_text = data.get("media") or ""
        uid = data.get("user_id", data.get("userId"))
        md5id = data.get("md5_id") or data.get("md5Id") or ""
        key = expand_key(uid, slug, md5id)
        media = decrypt_media(media_text, key) if media_text else {}
        fmt = media.get("mp4") or next(iter(media.values()), {})
        meta = _build_meta(slug, data, fmt)
        if meta.sources:
            _cache_meta(meta)
            return meta
    except Exception:
        meta = None
    # v3.1.0: klasik uç başarısız -> Android protokolü (HTML datas) devreye girer
    candidates: List[str] = []
    if embed_url:
        candidates.append(embed_url)
    candidates.append(f"https://abyss.to/v/{slug}")
    candidates.append(f"https://short.icu/{slug}")
    for cand in candidates:
        if not cand:
            continue
        meta = abyss_resolve_from_page(cand, referer=referer)
        if meta and meta.sources:
            return meta
    return None


def _build_meta(slug: str, data: Dict[str, Any], fmt: Dict[str, Any]) -> AbyssMeta:
    domains = fmt.get("domains") or []
    sources = [
        AbyssSource(
            label=str(sr.get("label") or "?"),
            size=int(sr.get("size") or 0),
            res_id=str(sr.get("res_id") or sr.get("resId") or ""),
            part_size=int(sr.get("partSize") or sr.get("part_size") or 0),
            sub=str(sr.get("sub") or ""),
            status=(bool(sr["status"]) if "status" in sr else None),
        )
        for sr in (fmt.get("sources") or [])
    ]
    return AbyssMeta(
        slug=slug,
        title=str(data.get("title") or slug),
        duration=int(data.get("duration") or 0),
        md5_id=str(data.get("md5_id") or data.get("md5Id") or ""),
        domains=domains,
        sources=sorted(sources, key=lambda x: x.size, reverse=True),
    )


def abyss_register_meta(payload_text: str) -> Optional[str]:
    """v2.9.5: tarayıcının yakaladığı şifreli info JSON'unu çöz ve önbelleğe koy.

    Oynatıcı info ucunu hangi domainden çekerse çeksin (site rotasyonuna dayanıklı),
    ağ yanıtı yakalandığı sürece meta çözülür.
    """
    try:
        data = json.loads(payload_text)
    except Exception:
        return None
    slug = str(data.get("slug") or "")
    md5id = str(data.get("md5_id") or data.get("md5Id") or "")
    media_text = data.get("media") or ""
    if not slug or not media_text:
        return None
    with _META_LOCK:
        hit = _META_CACHE.get(slug)
        if hit and hit[0] > _now() - 600:
            return slug
    try:
        key = expand_key(data.get("user_id", data.get("userId")), slug, md5id)
        media = decrypt_media(media_text, key)
    except Exception:
        return None
    fmt = media.get("mp4") or next(iter(media.values()), {})
    meta = _build_meta(slug, data, fmt)
    if not meta.sources:
        return None
    with _META_LOCK:
        _META_CACHE[slug] = (_now(), meta)
        while len(_META_CACHE) > 40:
            _META_CACHE.pop(next(iter(_META_CACHE)))
    return slug


def abyss_segment_urls(meta: AbyssMeta, label: str) -> Tuple[str, List[str], int, int]:
    src = next((s for s in meta.sources if s.label == label), None)
    if not src:
        return "", [], 0, 0
    # v3.1.0 Java mantığı: domains[0]'ın ilk etiketini at -> suffix; taban = sub.suffix
    # (eski kod 'src.sub in dom' arıyordu; domain listesi oynayınca boş taban kalıyordu)
    base = ""
    suffix = ""
    for dom in meta.domains:
        dom = (dom or "").strip()
        if not dom:
            continue
        dot = dom.find(".")
        if dot > 0 and dot + 1 < len(dom):
            suffix = dom[dot + 1:]
        else:
            suffix = dom
        break
    if src.sub and suffix:
        base = f"https://{src.sub}.{suffix}"
    elif meta.domains:
        for dom in meta.domains:
            if src.sub and src.sub in dom:
                base = "https://" + dom
                break
        if not base:
            base = "https://" + meta.domains[0]
    frag = src.part_size if src.part_size > 0 else _FRAG
    total = max(1, math.ceil(src.size / frag)) if src.size else 0
    key = generate_size_key(src.size)
    urls = []
    for idx in range(total):
        path = f"/mp4/{meta.md5_id}/{src.res_id}/{src.size}/{frag}/{idx}"
        urls.append(f"{base}/sora/{src.size}/{encrypt_path(path, key)}")
    return base, urls, src.size, frag


class AbyssDownloader:
    """Segmentleri paralel indirir, sırayla birleştirir; ilerlemeyi raporlar."""

    def __init__(
        self,
        meta: AbyssMeta,
        label: str,
        output_file: Path,
        progress_cb: Callable[[int], None],
        stop_event: threading.Event,
        workers: int = 8,
    ) -> None:
        self.meta = meta
        self.label = label
        self.output_file = output_file
        self.progress_cb = progress_cb
        self.stop_event = stop_event
        self.workers = workers

    def run(self) -> bool:
        base, urls, size, frag = abyss_segment_urls(self.meta, self.label)
        if not urls:
            return False
        tmp_dir = self.output_file.parent / f".abyss_{self.meta.slug}_{self.label.replace('p', '')}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        done_bytes = [0]
        lock = threading.Lock()

        def _one(idx_url: Tuple[int, str]) -> bool:
            idx, url = idx_url
            part = tmp_dir / f"seg_{idx}"
            if part.exists() and part.stat().st_size > 0:
                return True
            paths = [url]
            # v2.9.8: 403 olursa diğer CDN domainleriyle dene (token yoldan bağımsız)
            for dom in self.meta.domains:
                alt = f"https://{dom}/sora/" + url.split("/sora/", 1)[-1] if "/sora/" in url else url
                if alt not in paths:
                    paths.append(alt)
            for attempt in range(3):
                if self.stop_event.is_set():
                    return False
                for cand in paths:
                    try:
                        req = urllib.request.Request(cand, headers=_SEG_HEADERS)
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            body = resp.read()
                        if not body:
                            continue
                        part.write_bytes(body)
                        with lock:
                            done_bytes[0] += len(body)
                            self.progress_cb(done_bytes[0])
                        return True
                    except Exception:
                        continue
            return False

        ok = True
        # v3.2.0 CANLI YAZIM: paralel indirme sürerken sıralı yazıcı AYNI ANDA çalışır —
        # seg_0 diske iner inmez IDM bayt almaya başlar (0 bayt donması tarihe karışır).
        writer_err: list = []
        writer_done = threading.Event()

        def _ordered_writer() -> int:
            written = 0
            try:
                with self.output_file.open("wb") as out:
                    for idx in range(len(urls)):
                        part = tmp_dir / f"seg_{idx}"
                        deadline = _now() + 180
                        while not (part.exists() and part.stat().st_size > 0):
                            if self.stop_event.is_set() or _now() > deadline:
                                writer_err.append(f"seg_{idx} zaman aşımı")
                                return written
                            time.sleep(0.15)
                        with part.open("rb") as fh:
                            while True:
                                blk = fh.read(1 << 20)
                                if not blk:
                                    break
                                out.write(blk)
                                out.flush()
                                written += len(blk)
                        self.progress_cb(written)
                        if self.stop_event.is_set():
                            return written
            except Exception as exc:  # pragma: no cover - disk hataları
                writer_err.append(str(exc))
            finally:
                writer_done.set()
            return written

        try:
            writer = threading.Thread(target=_ordered_writer, name="abyss-live-writer", daemon=True)
            writer.start()
            try:
                with ThreadPoolExecutor(max_workers=self.workers) as ex:
                    results = list(ex.map(_one, list(enumerate(urls))))
            except Exception:
                results = []
            writer.join(timeout=300)
            # v2.9.8 + v3.2.0: sıralı yazım paralel indirmeyle AYNI ANDA yürür —
            # /stream ucu dosya büyüdükçe IDM'ye gerçek zamanlı akar.
            ok = writer_done.is_set() and not writer_err and not self.stop_event.is_set()
            if writer_err:
                logger.info("Abyss canlı yazıcı hatası: %s", writer_err[0])
            return ok
        finally:
            import shutil as _sh

            _sh.rmtree(tmp_dir, ignore_errors=True)


def _now() -> float:
    import time as _t

    return _t.time()
