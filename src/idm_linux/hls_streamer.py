from __future__ import annotations

import concurrent.futures
import gzip
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .config import setup_logger

logger = setup_logger("hls_streamer", "daemon.log")


def build_stream_headers(
    referer: str = "",
    origin: str = "",
    cookies: str = "",
    user_agent: str = "",
) -> Dict[str, str]:
    hdrs: Dict[str, str] = {
        "User-Agent": user_agent
        or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
    }
    if referer:
        hdrs["Referer"] = referer
    if origin:
        hdrs["Origin"] = origin
    elif referer:
        rp = urllib.parse.urlparse(referer)
        if rp.scheme and rp.netloc:
            hdrs["Origin"] = f"{rp.scheme}://{rp.netloc}"
    if cookies:
        hdrs["Cookie"] = cookies
    return hdrs


def _decompress_http_body(data: bytes, content_encoding: str = "") -> bytes:
    if not data:
        return data
    enc = (content_encoding or "").lower()
    if "gzip" in enc or data[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(data)
        except Exception:
            pass
    if "deflate" in enc:
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                return zlib.decompress(data, wbits)
            except Exception:
                pass
    return data


def fetch_url_bytes(url: str, headers: Dict[str, str], timeout: float = 12.0, retries: int = 3) -> bytes:
    last_err: Optional[Exception] = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                enc = resp.headers.get("Content-Encoding") or ""
                raw = resp.read()
                return _decompress_http_body(raw, enc)
        except Exception as exc:
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            last_err = exc
    raise RuntimeError(f"HLS kaynağı indirilemedi ({url[:80]}): {last_err}")


def is_hls_playlist_text(text: str) -> bool:
    s = (text or "").lstrip("\ufeff \t\r\n")
    return s.startswith("#EXTM3U") or ("#EXTINF:" in s and "#EXT" in s)


# ─── v3.9.0: ALTYAZI AKILLI GETİRİCİ (header varyantlı + içerik doğrulamalı) ────
# Kullanıcı raporu (fullhdfilmizlesene.now / subs.rapidvid.org): altyazılar bar'da
# görünüyordu AMA inmiyordu (0 bayt). Kök neden: CDN'in sıkı hotlink koruması —
# tek başlık kombinasyonu (Referer+Origin) her CDN'e uymuyor. Artık 4 farklı başlık
# varyantı sırayla denenir ve yanıtın GERÇEKTEN bir altyazı olduğu doğrulanır;
# doğrulama probe aşamasında sahte/ölü altyazı girdilerini de KÖKTEN temizler.

_SUB_SNIFF_CAP = 262144  # doğrulama için 256 KB yeter (ilk 4 cursor)


def looks_like_subtitle_bytes(data: bytes) -> bool:
    """Baytların gerçek bir altyazı (WebVTT/SRT/ASS/TTML/SAMI) olup olmadığını anlar.
    HTML hata sayfaları, boş yanıtlar ve JSON hata gövdeleri REDDEDİLİR."""
    if not data or len(data) < 12:
        return False
    try:
        head = data[:4096].decode("utf-8", errors="replace").lstrip("\ufeff")
    except Exception:
        return False
    low = head.lower()
    if low.startswith("webvtt") or low.startswith("itel") or low.startswith("[script info]"):
        return True
    if low.startswith(("<?xml", "<tt", "<ttml")) and ("tt" in low[:200]):
        return True
    if "<sami" in low[:200] or "<srt" in low[:200]:
        return True
    # SRT: sıra numarası + '-->' zaman damgası (HH:MM:SS,mmm VEYA MM:SS.mmm)
    if "-->" in head and re.search(r"\d{1,2}(?::\d{2}){1,2}[,.]\d{1,3}\s*-->\s*\d{1,2}(?::\d{2}){1,2}[,.]\d{1,3}", head):
        return True
    # WebVTT: 'WEBVTT' erken satırlarda (BOM/whitespace sonrası)
    if re.search(r"^\s*webvtt\b", low, re.M):
        return True
    # ASS/SSA bölüm başlığı
    if re.search(r"^\s*\[(events|styles|v4\+? styles)\]", low, re.M | re.I):
        return True
    # MPL2 / sub formatları
    if re.match(r"^\s*\[\d+\]\[\d+\]", head):
        return True
    return False


def _subtitle_header_variants(headers: Dict[str, str]) -> List[Dict[str, str]]:
    """Altyazı CDN'lerine karşı 4 aşamalı başlık stratejisi:
    1) Tam tarayıcı taklidi (UA+Accept+Referer+Origin+Cookie)
    2) Origin'siz (bazı CDN'ler yanlış Origin'de 403 verir)
    3) Sadece UA+Accept (hotlink kontrolü yalnız Referer'sız geçirir)
    4) Nötr istemci (Referer olmayan doğrudan CDN erişimi)"""
    full = dict(headers or {})
    if not full.get("User-Agent"):
        full["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    full.setdefault("Accept", "*/*")
    v_no_origin = {k: v for k, v in full.items() if k.lower() != "origin"}
    v_bare = {k: v for k, v in v_no_origin.items() if k.lower() not in ("referer", "cookie")}
    v_neutral = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "Accept": "*/*"}
    out = []
    for cand in (full, v_no_origin, v_bare, v_neutral):
        if cand and cand not in out:
            out.append(cand)
    return out


def fetch_subtitle_probe(
    sub_url: str, headers: Dict[str, str], timeout: float = 6.0
) -> Tuple[str, int, str]:
    """Altyazı URL'ini DOĞRULAR. Döner: (durum, bayt_boyutu, alt_tür)
    - ("ok", boyut, "vtt|srt|ass|ttml")  -> gerçek altyazı doğrulandı
    - ("bad", 0, "")                     -> CDN yanıt verdi AMA içerik altyazı değil (sahte!)
    - ("unknown", 0, "")                 -> ağ/timeout (karar verilemedi — girdi tutulur)
    Yanıt tam metin olarak toplanmaz — ilk _SUB_SNIFF_CAP bayt okunup bağlantı kapanır."""
    got_any_response = False
    for hdrs in _subtitle_header_variants(headers):
        try:
            req = urllib.request.Request(sub_url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = int(getattr(resp, "status", 200) or 200)
                if code >= 400:
                    # v3.10.0: HTTP hatası "içerik altyazı değil" DEMEK DEĞİLDİR —
                    # CDN bize 403/404 verip tarayıcıya içerik sunuyor olabilir
                    # (YouTube timedtext, token'lı altyazı CDN'leri). Eskiden bu
                    # durum 'bad' sayılıp girdi bar'dan SİLİNİYORDU; kullanıcı
                    # raporu: "altyazı hiç görünmüyor". Artık yalnız 2xx alıp
                    # içerik altyazı DEĞİLSE elenir.
                    got_any_response = True
                    continue
                enc = resp.headers.get("Content-Encoding") or ""
                clen = resp.headers.get("Content-Length") or ""
                raw = resp.read(_SUB_SNIFF_CAP)
                data = _decompress_http_body(raw, enc)
                if not looks_like_subtitle_bytes(data):
                    got_any_response = True
                    continue
                size = int(clen) if clen.isdigit() and int(clen) > 0 else len(data)
                sub_kind = "vtt"
                head = data[:512].decode("utf-8", errors="replace").lstrip().lower()
                if head.startswith("[script info]") or head.startswith("kelvin"):
                    sub_kind = "ass"
                elif head.startswith(("<?xml", "<tt")) or "<sami" in head:
                    sub_kind = "ttml"
                elif "-->" in head and not head.startswith("webvtt"):
                    sub_kind = "srt"
                return "ok", size, sub_kind
        except Exception:
            continue
    if got_any_response:
        return "bad", 0, ""
    return "unknown", 0, ""


def fetch_subtitle_bytes_smart(
    sub_url: str, headers: Dict[str, str], timeout: float = 12.0
) -> bytes:
    """Altyazı gövdesini 4 başlık varyantıyla getirir; ilki başarısız olursa sıradaki
    varyant denenir (rapidvid/fullhdfilmizlesene '0 bayt' düzeltmesi)."""
    last_exc: Optional[Exception] = None
    for hdrs in _subtitle_header_variants(headers):
        try:
            raw = fetch_url_bytes(sub_url, hdrs, timeout=timeout, retries=2)
        except Exception as exc:
            last_exc = exc
            continue
        # v3.10.0: yalnız "bir şey indi" demek yetmez — gövde GERÇEKTEN altyazı
        # olmalı. Önceki sürüm 404/403 HTML hata sayfasını altyazı sanıp
        # 'Video [Altyazı].srt' içine HTML yazıyordu (kullanıcı: "fake srt").
        if looks_like_subtitle_bytes(raw):
            return raw
        if is_hls_playlist_text(raw.decode("utf-8", errors="ignore")):
            return raw  # segmentli altyazı: assemble_subtitle_text işleyecek
        last_exc = RuntimeError("indirilen içerik altyazı değil (HTML/hata sayfası)")
    raise RuntimeError(f"Altyazı kaynağı hiçbir başlık varyantıyla okunamadı: {last_exc}")


def looks_like_hls_url(url: str) -> bool:
    u = (url or "").lower()
    if ".m3u8" in u:
        return True
    # Film sitelerindeki gizli HLS manifest kalıpları (master.txt, index.txt, /hls/, /manifests/ vb.)
    if re.search(r"/(master|index|playlist|chunklist|manifests?|hls)[^/?]*\.(txt|json|m3u)(\?|$)", u):
        return True
    if "/hls/" in u and not re.search(r"\.(mp4|webm|mkv|mp3|m4a)(\?|$)", u):
        return True
    return False


def probe_url_is_hls(url: str, headers: Dict[str, str]) -> Optional[str]:
    """URL uzantısı .txt veya belirsiz olduğunda ilk KB'ı kontrol edip #EXTM3U ise metni döndürür."""
    try:
        req_hdrs = dict(headers)
        req = urllib.request.Request(url, headers=req_hdrs)
        with urllib.request.urlopen(req, timeout=6.0) as resp:
            enc = resp.headers.get("Content-Encoding") or ""
            ctype = (resp.headers.get("Content-Type") or "").lower()
            sample = resp.read(262_144)
            decoded_bytes = _decompress_http_body(sample, enc)
            txt = decoded_bytes.decode("utf-8", errors="ignore")
            if is_hls_playlist_text(txt):
                rest = resp.read()
                if rest:
                    full_bytes = _decompress_http_body(sample + rest, enc)
                    txt = full_bytes.decode("utf-8", errors="ignore")
                return txt
            if "mpegurl" in ctype and txt:
                return txt
    except Exception:
        pass
    return None


def strip_disguised_image_header(data: bytes) -> bytes:
    """
    Film/dizi oynatıcılarının (Atom, Vidmoly, FirePlayer, Moly, CloseLoad vb.) HLS segmentlerinin
    ilk baytlarına eklediği sahte PNG / JPEG / GIF / BMP / rastgele çöp başlığını
    188-bayt periyotlu MPEG-TS senkron baytını (0x47) veya fMP4 kutusunu bularak anında soyar!
    """
    n = len(data)
    if n < 380:
        return data

    if data[0] == 0x47 and data[188] == 0x47:
        return data
    if data[4:8] in (b"ftyp", b"styp", b"moof", b"mdat", b"sidx"):
        return data

    # Bazı player'lar ilk 64 KB'a kadar sahte PNG resmi koyup arkasına gerçek MPEG-TS ekler!
    scan_limit = min(65536, n - 377)
    idx = 0
    while idx < scan_limit:
        pos = data.find(b"\x47", idx, scan_limit)
        if pos == -1:
            break
        if data[pos + 188] == 0x47 and data[pos + 376] == 0x47:
            return data[pos:]
        idx = pos + 1

    # fMP4 segmentinin önüne sahte başlık konmuşsa ('ftyp' veya 'moof' kutusu ara)
    for box_sig in (b"ftyp", b"styp", b"moof"):
        bpos = data.find(box_sig, 4, min(16384, n))
        if bpos >= 4:
            return data[bpos - 4 :]

    return data


def _decrypt_aes128_cbc(cipher_bytes: bytes, key: bytes, iv: bytes) -> bytes:
    openssl_bin = shutil.which("openssl")
    if not openssl_bin:
        return cipher_bytes
    res = subprocess.run(
        [
            openssl_bin,
            "enc",
            "-d",
            "-aes-128-cbc",
            "-K",
            key.hex(),
            "-iv",
            iv.hex(),
        ],
        input=cipher_bytes,
        capture_output=True,
        check=False,
    )
    if res.returncode == 0 and res.stdout:
        return res.stdout
    return cipher_bytes


def resolve_media_playlists(
    m3u8_url: str,
    headers: Dict[str, str],
    initial_manifest_text: str = "",
) -> Tuple[str, str, Optional[str], Optional[str]]:
    """
    Master Playlist veya doğrudan Media Playlist'i çözümler.
    Dönüş: (video_playlist_url, video_playlist_text, audio_playlist_url, audio_playlist_text)
    """
    if initial_manifest_text and is_hls_playlist_text(initial_manifest_text):
        text = initial_manifest_text
    else:
        raw = fetch_url_bytes(m3u8_url, headers, timeout=10.0)
        text = raw.decode("utf-8", errors="ignore")

    if not is_hls_playlist_text(text):
        raise RuntimeError("Kaynak geçerli bir HLS (#EXTM3U) listesi değil.")

    if "#EXT-X-STREAM-INF" not in text:
        return m3u8_url, text, None, None

    # Master Playlist: #EXT-X-MEDIA:TYPE=AUDIO gruplarını da topla (Türkçe Dublaj / Çift sesli filmler!)
    audio_groups: Dict[str, List[Tuple[bool, str, str]]] = {}
    for raw_line in text.splitlines():
        ln = raw_line.strip()
        if ln.startswith("#EXT-X-MEDIA:") and "TYPE=AUDIO" in ln:
            gm = re.search(r'GROUP-ID="([^"]+)"', ln)
            um = re.search(r'URI="([^"]+)"', ln)
            nm = re.search(r'NAME="([^"]+)"', ln)
            lang_m = re.search(r'LANGUAGE="([^"]+)"', ln)
            if gm and um:
                gid = gm.group(1)
                a_uri = urllib.parse.urljoin(m3u8_url, um.group(1))
                label_str = f"{nm.group(1) if nm else ''} {lang_m.group(1) if lang_m else ''}".lower()
                is_preferred = ("tr" in label_str or "türk" in label_str or "turk" in label_str or "DEFAULT=YES" in ln)
                audio_groups.setdefault(gid, []).append((is_preferred, label_str, a_uri))

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    best_score = (-1, -1)
    best_uri = ""
    best_audio_gid = ""

    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:") and i + 1 < len(lines):
            nxt = lines[i + 1]
            if nxt.startswith("#"):
                continue
            res_m = re.search(r"RESOLUTION=(\d+)x(\d+)", line)
            height = int(res_m.group(2)) if res_m else 0
            bw_m = re.search(r"BANDWIDTH=(\d+)", line)
            bw = int(bw_m.group(1)) if bw_m else 0
            aud_m = re.search(r'AUDIO="([^"]+)"', line)
            score = (height, bw)
            if score >= best_score:
                best_score = score
                best_uri = urllib.parse.urljoin(m3u8_url, nxt)
                best_audio_gid = aud_m.group(1) if aud_m else ""

    if not best_uri:
        return m3u8_url, text, None, None

    v_raw = fetch_url_bytes(best_uri, headers, timeout=10.0)
    v_text = v_raw.decode("utf-8", errors="ignore")

    audio_url: Optional[str] = None
    audio_text: Optional[str] = None
    if best_audio_gid and best_audio_gid in audio_groups:
        cands = audio_groups[best_audio_gid]
        cands.sort(key=lambda x: (1 if x[0] else 0), reverse=True)
        audio_url = cands[0][2]
        try:
            a_raw = fetch_url_bytes(audio_url, headers, timeout=10.0)
            a_txt = a_raw.decode("utf-8", errors="ignore")
            if is_hls_playlist_text(a_txt):
                audio_text = a_txt
            else:
                audio_url = None
        except Exception:
            audio_url = None

    return best_uri, v_text, audio_url, audio_text


def _iter_playlist_segments_parallel(
    playlist_url: str,
    playlist_body: str,
    headers: Dict[str, str],
    concurrency: int = 16,
    stop_event: Optional[threading.Event] = None,
) -> Iterator[bytes]:
    """Tek bir HLS medya listesinin segmentlerini 16 paralel iş parçacığıyla sırasını bozmadan akıtır."""
    media_seq = 0
    seq_m = re.search(r"#EXT-X-MEDIA-SEQUENCE:(\d+)", playlist_body)
    if seq_m:
        media_seq = int(seq_m.group(1))

    init_map_url: Optional[str] = None
    current_key_uri: Optional[str] = None
    current_key_iv: Optional[bytes] = None
    pending_byterange: Optional[Tuple[int, int]] = None
    last_range_end = 0
    key_cache: Dict[str, bytes] = {}
    key_lock = threading.Lock()

    segments: List[Tuple[int, str, Optional[str], Optional[bytes], Optional[Tuple[int, int]]]] = []
    seg_idx = 0

    for raw_line in playlist_body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MAP:"):
            um = re.search(r'URI="([^"]+)"', line)
            if um:
                init_map_url = urllib.parse.urljoin(playlist_url, um.group(1))
        elif line.startswith("#EXT-X-BYTERANGE:"):
            bm = re.search(r"#EXT-X-BYTERANGE:(\d+)(?:@(\d+))?", line)
            if bm:
                length = int(bm.group(1))
                start = int(bm.group(2)) if bm.group(2) is not None else last_range_end
                pending_byterange = (start, start + length - 1)
                last_range_end = start + length
        elif line.startswith("#EXT-X-KEY:"):
            if "METHOD=AES-128" in line:
                km = re.search(r'URI="([^"]+)"', line)
                ivm = re.search(r"IV=0x([0-9a-fA-F]+)", line)
                current_key_uri = urllib.parse.urljoin(playlist_url, km.group(1)) if km else None
                current_key_iv = bytes.fromhex(ivm.group(1).zfill(32)[-32:]) if ivm else None
            else:
                current_key_uri = None
                current_key_iv = None
        elif not line.startswith("#"):
            seg_url = urllib.parse.urljoin(playlist_url, line)
            segments.append((media_seq + seg_idx, seg_url, current_key_uri, current_key_iv, pending_byterange))
            pending_byterange = None
            seg_idx += 1

    if not segments:
        raise RuntimeError("HLS çalma listesinde indirilebilir segment bulunamadı.")

    if init_map_url:
        yield strip_disguised_image_header(fetch_url_bytes(init_map_url, headers, timeout=10.0))

    def _download_one(
        item: Tuple[int, str, Optional[str], Optional[bytes], Optional[Tuple[int, int]]]
    ) -> bytes:
        if stop_event and stop_event.is_set():
            return b""
        seq_num, s_url, k_uri, k_iv, byte_rng = item
        seg_hdrs = dict(headers)
        if byte_rng is not None:
            seg_hdrs["Range"] = f"bytes={byte_rng[0]}-{byte_rng[1]}"
        data = fetch_url_bytes(s_url, seg_hdrs, timeout=15.0, retries=3)
        if k_uri:
            with key_lock:
                if k_uri not in key_cache:
                    key_cache[k_uri] = fetch_url_bytes(k_uri, headers, timeout=10.0)
                key_bytes = key_cache[k_uri]
            if len(key_bytes) == 16:
                iv_bytes = k_iv if k_iv is not None else seq_num.to_bytes(16, byteorder="big")
                data = _decrypt_aes128_cbc(data, key_bytes, iv_bytes)
        data = strip_disguised_image_header(data)
        if not data or data.lstrip().lower().startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
            raise RuntimeError("HLS segmenti boş veya medya yerine HTML hata sayfası döndü.")
        return data

    window_size = max(concurrency * 2, 24)
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures: List[Tuple[int, concurrent.futures.Future[bytes]]] = []
        next_to_submit = 0
        total = len(segments)

        while next_to_submit < min(window_size, total):
            futures.append((next_to_submit, pool.submit(_download_one, segments[next_to_submit])))
            next_to_submit += 1

        while futures:
            if stop_event and stop_event.is_set():
                for _, rest_f in futures:
                    rest_f.cancel()
                break
            idx, fut = futures.pop(0)
            tries = 0
            while True:
                try:
                    chunk = fut.result()
                    break
                except Exception as exc:
                    # v2.9.11: TEK ölü segment tüm kaydı öldüremez -> sırayı bozmadan yerinde 5 deneme
                    tries += 1
                    if tries >= 5 or (stop_event and stop_event.is_set()):
                        raise
                    logger.info(
                        "Segment %s/%s koptu (%s) -> yerinde deneme %s/5", idx + 1, total, exc, tries
                    )
                    time.sleep(min(1.5 * tries, 8))
                    fut = pool.submit(_download_one, segments[idx])
            if next_to_submit < total and not (stop_event and stop_event.is_set()):
                futures.append((next_to_submit, pool.submit(_download_one, segments[next_to_submit])))
                next_to_submit += 1
            if chunk:
                yield chunk


def iter_raw_hls_segments(
    m3u8_url: str,
    referer: str = "",
    origin: str = "",
    cookies: str = "",
    user_agent: str = "",
    concurrency: int = 16,
    initial_manifest_text: str = "",
) -> Iterator[bytes]:
    headers = build_stream_headers(referer=referer, origin=origin, cookies=cookies, user_agent=user_agent)
    v_url, v_body, _, _ = resolve_media_playlists(
        m3u8_url, headers, initial_manifest_text=initial_manifest_text
    )
    yield from _iter_playlist_segments_parallel(v_url, v_body, headers, concurrency=concurrency)


def _needs_aac_adtstoasc(ffmpeg_bin: str, sample: bytes) -> bool:
    """
    MPEG-TS veya ADTS ses segmentinin içinde ham ADTS AAC akışı olup olmadığını
    bellek içi hızlı probe (~40ms) ile tespit eder.
    - AAC ise True döner -> FFmpeg 7 MP4 muxer için '-bsf:a aac_adtstoasc' zorunludur!
    - MP3 / AC3 / EAC3 / Opus / fMP4 ise False döner -> MP3'te çökme olmaz!
    """
    if not sample or sample[4:8] in (b"ftyp", b"styp", b"moof"):
        return False
    try:
        res = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-i", "pipe:0"],
            input=sample[:131072],
            capture_output=True,
            timeout=2.5,
            check=False,
        )
        info = res.stderr.decode("utf-8", errors="ignore")
        return "Audio: aac" in info
    except Exception:
        return True


def stream_hls_as_mp4(
    m3u8_url: str,
    referer: str = "",
    origin: str = "",
    cookies: str = "",
    user_agent: str = "",
    initial_manifest_text: str = "",
    concurrency: int = 16,
    hls_mode: str = "vod",
    resume_after: int = -1,
    seq_tracker: Optional[Dict[str, int]] = None,
    emit_init: bool = True,
) -> Iterator[bytes]:
    """
    16x paralel indirilen temiz HLS segmentlerini (varsa ayrık Türkçe ses akışıyla birlikte!)
    0.15 sn gecikmeli anlık flush (-frag_duration 250000 -flush_packets 1) ile
    kesintisiz MP4 olarak IDM'ye canlı akıtır!
    v3.2.0: resume_after/seq_tracker -> canlı kayıt yeniden bağlanınca AYNI segmenti iki
    kez yazmaz (kopya kareler yok); emit_init=False -> ikinci turda init segmenti tekrarlanmaz.
    """
    headers = build_stream_headers(referer=referer, origin=origin, cookies=cookies, user_agent=user_agent)
    v_url, v_body, a_url, a_body = resolve_media_playlists(
        m3u8_url, headers, initial_manifest_text=initial_manifest_text
    )

    stop_ev = threading.Event()
    v_iter = iter_playlist_segments_smart(
        v_url, v_body, headers, concurrency=concurrency, stop_event=stop_ev, hls_mode=hls_mode,
        resume_after=resume_after, seq_tracker=seq_tracker,
    )

    first_v = next(v_iter, b"")
    if not first_v:
        return

    # Tekil fMP4 segment akışıysa ve ayrı ses yoksa doğrudan sıfır kopyayla akıt!
    if a_url is None and first_v[4:8] in (b"ftyp", b"styp", b"moof"):
        if emit_init:
            yield first_v
        for seg in v_iter:
            yield seg
        return

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        yield first_v
        for seg in v_iter:
            yield seg
        return

    a_iter: Optional[Iterator[bytes]] = None
    first_a = b""
    if a_url and a_body:
        a_iter = iter_playlist_segments_smart(
            a_url, a_body, headers, concurrency=8, stop_event=stop_ev,
            hls_mode=(hls_mode if hls_mode in ("dvr", "live") else "vod"),
            resume_after=resume_after, seq_tracker=seq_tracker,
        )
        first_a = next(a_iter, b"")

    audio_sample = first_a if first_a else first_v
    use_aac_bsf = _needs_aac_adtstoasc(ffmpeg_bin, audio_sample)

    fifo_dir: Optional[str] = None
    audio_fifo_path: Optional[str] = None

    try:
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-probesize",
            "262144",
            "-analyzeduration",
            "500000",
            "-fflags",
            "+genpts+igndts+discardcorrupt",
            "-err_detect",
            "ignore_err",
            "-i",
            "pipe:0",
        ]

        if a_iter is not None and first_a:
            fifo_dir = tempfile.mkdtemp(prefix="idm_hls_fifo_")
            audio_fifo_path = os.path.join(fifo_dir, "audio.pipe")
            os.mkfifo(audio_fifo_path)
            cmd.extend(["-i", audio_fifo_path, "-map", "0:v:0", "-map", "1:a:0"])

        cmd.extend(["-c", "copy"])
        if use_aac_bsf:
            cmd.extend(["-bsf:a", "aac_adtstoasc"])

        cmd.extend(
            [
                "-frag_duration",
                "250000",
                "-min_frag_duration",
                "100000",
                "-flush_packets",
                "1",
                "-movflags",
                "frag_keyframe+empty_moov+default_base_moof",
                "-f",
                "mp4",
                "pipe:1",
            ]
        )

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

        feeder_errors: List[Exception] = []
        video_done = threading.Event()
        audio_done = threading.Event()

        def _feed_video() -> None:
            assert proc.stdin is not None
            try:
                proc.stdin.write(first_v)
                proc.stdin.flush()
                for seg in v_iter:
                    if stop_ev.is_set():
                        break
                    proc.stdin.write(seg)
                    proc.stdin.flush()
            except Exception as exc:
                feeder_errors.append(exc)
            finally:
                video_done.set()
                try:
                    proc.stdin.close()
                except OSError:
                    pass

        def _feed_audio(fifo_p: str, first_aud: bytes, aud_stream: Iterator[bytes]) -> None:
            try:
                with open(fifo_p, "wb", buffering=0) as afh:
                    afh.write(first_aud)
                    for aseg in aud_stream:
                        if stop_ev.is_set():
                            break
                        afh.write(aseg)
            except Exception as exc:
                feeder_errors.append(exc)
            finally:
                audio_done.set()

        video_thread = threading.Thread(target=_feed_video, name="hls-video-feeder", daemon=True)
        video_thread.start()
        audio_thread = None
        if audio_fifo_path and a_iter is not None and first_a:
            audio_thread = threading.Thread(
                target=_feed_audio,
                args=(audio_fifo_path, first_a, a_iter),
                name="hls-audio-feeder",
                daemon=True,
            )
            audio_thread.start()

        try:
            assert proc.stdout is not None
            out_fd = proc.stdout.fileno()
            while True:
                out_chunk = os.read(out_fd, 65536)
                if not out_chunk:
                    break
                yield out_chunk
            # stdout EOF alone proves nothing: FFmpeg can exit successfully after
            # an upstream feeder exception and leave a playable but truncated file.
            video_thread.join(timeout=2)
            if audio_thread:
                audio_thread.join(timeout=2)
            if feeder_errors:
                raise RuntimeError("HLS ses/video segment aktarımı yarıda kesildi.") from feeder_errors[0]
            if not video_done.is_set() or (audio_thread and not audio_done.is_set()):
                raise RuntimeError("HLS dönüştürücü bütün segmentler tüketilmeden kapandı.")
            if proc.wait(timeout=5) != 0:
                raise RuntimeError("HLS dönüştürücü hata ile kapandı; dosya tamamlanmadı.")
        finally:
            stop_ev.set()
            if proc.stdout is not None:
                try:
                    proc.stdout.close()
                except OSError:
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            else:
                proc.wait()
    finally:
        stop_ev.set()
        if fifo_dir and os.path.isdir(fifo_dir):
            shutil.rmtree(fifo_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# v2.8.0 — CANLI (LIVE-EDGE) & DVR (--hls-live-restart) TAKİPLİ HLS MOTORU
# streamlink semantiği:  dvr  = playlist'in BAŞINDAN başla, yayın bitene dek takip et
#                        live = CANLI kenardan (son segment) başla, yayın bitene dek takip et
#                        vod  = statik playlist (eski davranış)
# ---------------------------------------------------------------------------

def parse_media_playlist_body(playlist_url: str, body: str) -> Dict[str, Any]:
    """Bir HLS medya listesini ayrıştırır: seq -> segment eşlemi + hedef süre + ENDLIST."""
    import json as _json  # noqa: F401  (ileriye dönük)
    media_seq = 0
    m = re.search(r"#EXT-X-MEDIA-SEQUENCE:(\d+)", body or "")
    if m:
        media_seq = int(m.group(1))
    target = 4.0
    mt = re.search(r"#EXT-X-TARGETDURATION:([\d.]+)", body or "")
    if mt:
        target = max(1.0, float(mt.group(1)))
    endlist = "#EXT-X-ENDLIST" in (body or "")

    items: List[Tuple[int, str, Optional[str], Optional[bytes], Optional[Tuple[int, int]]]] = []
    map_url: Optional[str] = None
    key_uri: Optional[str] = None
    key_iv: Optional[bytes] = None
    pending_range: Optional[Tuple[int, int]] = None
    last_end = 0
    idx = 0
    for raw_line in (body or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MAP:"):
            um = re.search(r'URI="([^"]+)"', line)
            if um:
                map_url = urllib.parse.urljoin(playlist_url, um.group(1))
        elif line.startswith("#EXT-X-BYTERANGE:"):
            bm = re.search(r"#EXT-X-BYTERANGE:(\d+)(?:@(\d+))?", line)
            if bm:
                ln = int(bm.group(1))
                st = int(bm.group(2)) if bm.group(2) is not None else last_end
                pending_range = (st, st + ln - 1)
                last_end = st + ln
        elif line.startswith("#EXT-X-KEY:"):
            if "METHOD=AES-128" in line:
                km = re.search(r'URI="([^"]+)"', line)
                ivm = re.search(r"IV=0x([0-9a-fA-F]+)", line)
                key_uri = urllib.parse.urljoin(playlist_url, km.group(1)) if km else None
                key_iv = bytes.fromhex(ivm.group(1).zfill(32)[-32:]) if ivm else None
            else:
                key_uri = None
                key_iv = None
        elif not line.startswith("#"):
            items.append((media_seq + idx, urllib.parse.urljoin(playlist_url, line), key_uri, key_iv, pending_range))
            pending_range = None
            idx += 1
    return {"media_seq": media_seq, "target": target, "endlist": endlist, "items": items, "map_url": map_url}


def iter_playlist_segments_smart(
    playlist_url: str,
    playlist_body: str,
    headers: Dict[str, str],
    concurrency: int = 16,
    stop_event: Optional[threading.Event] = None,
    hls_mode: str = "vod",
    max_refetch_fail: int = 20,
    resume_after: int = -1,
    seq_tracker: Optional[Dict[str, int]] = None,
) -> Iterator[bytes]:
    """
    vod  : statik listeyi 16x paralel indirir (eski davranış, VOD/DVR kayıtları).
    dvr  : playlist'in İLK segmentinden başlar, yeni segmentler geldikçe CANLI takip eder,
           #EXT-X-ENDLIST gelene veya stop_event kurulana dek sürer (streamlink --hls-live-restart).
    live : CANLI kenardan (o anki son segment) başlar, aynı şekilde yayın sonuna dek takip eder
           (streamlink varsayılan canlı kayıt davranışı).
    v3.2.0: resume_after -> yeniden bağlanmada bu seq'den SONRASI indirilir (kopya yok);
    seq_tracker -> indirilen en yüksek seq dışarı taşınır (sonraki tur için).
    """
    parsed = parse_media_playlist_body(playlist_url, playlist_body)
    if not parsed["items"]:
        raise RuntimeError("HLS çalma listesinde indirilebilir segment bulunamadı.")

    if parsed["endlist"] or hls_mode not in ("dvr", "live"):
        yield from _iter_playlist_segments_parallel(
            playlist_url, playlist_body, headers, concurrency=concurrency, stop_event=stop_event
        )
        return

    init_map_url = parsed["map_url"]
    if init_map_url and resume_after < 0:
        yield strip_disguised_image_header(fetch_url_bytes(init_map_url, headers, timeout=10.0))

    key_cache: Dict[str, bytes] = {}
    key_lock = threading.Lock()

    def _download_one(item: Tuple[int, str, Optional[str], Optional[bytes], Optional[Tuple[int, int]]]) -> bytes:
        if stop_event and stop_event.is_set():
            return b""
        seq_num, s_url, k_uri, k_iv, byte_rng = item
        if seq_tracker is not None and seq_num > seq_tracker.get("last", -1):
            seq_tracker["last"] = seq_num
        seg_hdrs = dict(headers)
        if byte_rng is not None:
            seg_hdrs["Range"] = f"bytes={byte_rng[0]}-{byte_rng[1]}"
        try:
            data = fetch_url_bytes(s_url, seg_hdrs, timeout=15.0, retries=4)
            if k_uri:
                with key_lock:
                    if k_uri not in key_cache:
                        key_cache[k_uri] = fetch_url_bytes(k_uri, headers, timeout=10.0)
                    kb = key_cache[k_uri]
                if len(kb) == 16:
                    ivb = k_iv if k_iv is not None else seq_num.to_bytes(16, byteorder="big")
                    data = _decrypt_aes128_cbc(data, kb, ivb)
            return strip_disguised_image_header(data)
        except Exception as exc:
            # v2.9.11: CANLI/DVR kaydında tek ölü segment kaydı öldürmez (yayın devam eder)
            logger.info("Canlı segment atlandı (%s): %s", s_url[:60], exc)
            return b""

    cursor = parsed["items"][0][0] if hls_mode == "dvr" else parsed["items"][-1][0]
    if resume_after >= 0:
        # v3.2.0: yeniden bağlanma — zaten indirilen segmentlerin üzerine çıkma
        cursor = max(cursor, resume_after + 1)
    fails = 0
    body_now = playlist_body

    while not (stop_event and stop_event.is_set()):
        cur = parse_media_playlist_body(playlist_url, body_now)
        fresh = [it for it in cur["items"] if it[0] >= cursor]
        if fresh:
            fails = 0
            if len(fresh) == 1:
                chunk = _download_one(fresh[0])
                if chunk:
                    yield chunk
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(concurrency, len(fresh))) as pool:
                    for chunk in pool.map(_download_one, fresh):
                        if stop_event and stop_event.is_set():
                            break
                        if chunk:
                            yield chunk
            cursor = fresh[-1][0] + 1
        if cur["endlist"]:
            break
        # Yeni segment beklerken playlist'i hedef süre kadar uyuyup yeniden çek
        time_sleep = min(max(cur["target"] * 0.85, 1.2), 6.0)
        if stop_event is not None:
            if stop_event.wait(time_sleep):
                break
        else:
            import time as _t
            _t.sleep(time_sleep)
        try:
            raw = fetch_url_bytes(playlist_url, headers, timeout=10.0, retries=2)
            body_now = raw.decode("utf-8", errors="ignore")
            fails = 0
        except Exception:
            fails += 1
            # v3.2.0: üstel geri çekilme — token ölümünde hızlıca pes etme (20 deneme ≈ 2-3 dk)
            time.sleep(min(1.5 * fails, 8.0))
            if fails >= max_refetch_fail:
                logger.warning("Canlı HLS playlist yeniden çekilemedi (%s) — kayıt eksik.", playlist_url[:80])
                raise RuntimeError("Canlı HLS listesi tekrar denemelerden sonra okunamadı; yayın sonu doğrulanmadı.")


# ---------------------------------------------------------------------------
# v3.2.2 — FİLM SİTELERİ ALTYAZI MOTORU
# HLS TYPE=SUBTITLES grupları segmentli .vtt oynatma listeleridir; bunları sıralı
# indirip TEK dosyada birleştirir ve her oynatıcının tanıdığı SRT'ye çevirir.
# ---------------------------------------------------------------------------

_VTT_TIME_RE = re.compile(
    r"^(\d{1,2}:)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*(\d{1,2}:)?(\d{1,2}):(\d{2})[.,](\d{1,3})(.*)$"
)


_VTT_INLINE_TAG_RE = re.compile(r"</?(?:c|v|ruby|rt|lang|font)(?:\.[^>]*)?(?:\s[^>]*)?>", re.I)
_HTML_ENTITY_MAP = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'",
    "&apos;": "'", "&nbsp;": " ", "&lrm;": "", "&rlm;": "", "&hellip;": "…",
}


def _unescape_subtitle_text(text: str) -> str:
    """HTML varlıklarını çözer (``&amp;`` → ``&``, ``&#x27;`` → ``'``)."""
    if not text or "&" not in text:
        return text
    out = text
    for src, dst in _HTML_ENTITY_MAP.items():
        out = out.replace(src, dst)
    out = re.sub(r"&#x([0-9a-fA-F]{2,6});", lambda m: chr(int(m.group(1), 16)), out)
    out = re.sub(r"&#(\d{2,6});", lambda m: chr(int(m.group(1))), out)
    return out


def _clean_cue_text(text: str) -> str:
    """VTT/SSA cue gövdesindeki biçimlendirme etiketlerini SRT dostu hale getirir."""
    out = text
    out = re.sub(r"\{\\[^}]*\}", "", out)          # ASS/SSA stilleri {\an8}
    out = re.sub(r"\{[^}]*\}", "", out)             # ASS konum/renk blokları
    out = _VTT_INLINE_TAG_RE.sub("", out)            # <c.yellow>, <v Ad>, <ruby>
    out = re.sub(r"<(?!/?(?:i|b|u|s)>)[^>]{1,40}>", "", out)  # bilinmeyen etiketler
    return _unescape_subtitle_text(out).rstrip()


def detect_subtitle_kind(text_or_bytes) -> str:
    """Altyazı türünü İÇERİKTEN tespit eder: vtt|srt|ass|ttml|sami|sbv|mpl2|"" (bilinmiyor).

    Uzantıya DEĞİL içeriğe bakılır: kullanıcı raporundaki "1.vtt adlı dosya srt
    olarak gösteriliyor / sahte srt iniyor" hatasının kökü uzantı tahminidir.
    """
    if isinstance(text_or_bytes, (bytes, bytearray)):
        raw = bytes(text_or_bytes)
        if raw[:2] in (b"\x1f\x8b", b"PK"):
            try:
                raw = _decompress_http_body(raw, "gzip")
            except Exception:
                pass
        head = raw[:8192].decode("utf-8", errors="replace")
    else:
        head = str(text_or_bytes or "")[:8192]
    low = head.lstrip("\ufeff \t\r\n").lower()
    if not low.strip():
        return ""
    if low.startswith("webvtt"):
        return "vtt"
    if low.startswith(("[script info]", "dialogue:", "v4+ styles", "v4 styles")):
        return "ass"
    if low.startswith(("<?xml", "<tt", "<ttml")) or "<tt " in low[:400]:
        return "ttml"
    if "<sami" in low[:200]:
        return "sami"
    if re.search(r"^\s*\d+:\d{2}:\d{2}[.,]\d{1,3}\s*,\s*\d+:\d{2}:\d{2}[.,]\d{1,3}", low, re.M):
        return "sbv"
    if re.match(r"^\s*\[\d+\]\[\d+\]", low):
        return "mpl2"
    if "-->" in low and re.search(r"\d{1,2}(?::\d{2}){1,2}[,.]\d{1,3}\s*-->\s*\d{1,2}(?::\d{2}){1,2}[,.]\d{1,3}", low):
        return "srt"
    # WebVTT bazen başlıksız gelir (segment birleştirme) — NOTE/X-TIMESTAMP-MAP varsa vtt
    if re.search(r"^\s*(note|x-timestamp-map)\b", low, re.M):
        return "vtt"
    return ""


def vtt_to_srt(vtt_text: str) -> str:
    """WebVTT → SubRip (SRT) dönüşümü — oynatıcıların %100 kabul ettiği biçim.

    v3.10.0 düzeltmeleri (kullanıcı: "srt sahte/bozuk"):
      * Zaman damgasından SONRAKİ cue ayarları (``align:start position:10%``)
        SRT zaman satırına YAZILMAZ — eski sürüm bunları yazdığı için dosya
        geçersiz SRT oluyordu.
      * ``<c.class>``, ``<v Ad>``, ``<ruby>`` gibi VTT'ye özel satır içi
        etiketler temizlenir; ``&amp;``/``&#39;`` varlıkları çözülür.
      * NOTE / STYLE / REGION / X-TIMESTAMP-MAP blokları gövdesiyle birlikte atılır.
    """
    blocks: List[str] = []
    idx = 0
    text = (vtt_text or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw_block in re.split(r"\n{2,}", text):
        block = raw_block.strip("\n")
        if not block.strip():
            continue
        lines = block.split("\n")
        stripped0 = lines[0].strip()
        if stripped0.startswith(("WEBVTT", "NOTE", "STYLE", "REGION", "X-TIMESTAMP-MAP")):
            continue
        # zaman satırını bul (ilk iki satırdan biri; üstünde cue id olabilir)
        time_line_pos = -1
        match = None
        for pos in (0, 1):
            if pos >= len(lines):
                break
            m = _VTT_TIME_RE.match(lines[pos].strip())
            if m:
                time_line_pos = pos
                match = m
                break
        if match is None or time_line_pos < 0:
            continue

        def _norm(h: str, mm: str, ss: str, ms: str) -> str:
            hours = int(h[:-1]) if h else 0
            return f"{hours:02d}:{int(mm):02d}:{int(ss):02d},{int(ms.ljust(3, '0')):03d}"

        start = _norm(match.group(1) or "", match.group(2), match.group(3), match.group(4))
        end = _norm(match.group(5) or "", match.group(6), match.group(7), match.group(8))
        body = [_clean_cue_text(ln) for ln in lines[time_line_pos + 1:]]
        body = [ln for ln in body if ln.strip()]
        if not body:
            continue
        idx += 1
        blocks.append(f"{idx}\n{start} --> {end}\n" + "\n".join(body))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def normalize_srt_text(srt_text: str) -> str:
    """SRT gövdesini normalize eder (noktalı virgül/nokta ondalık, sıra numarası)."""
    text = (srt_text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    blocks: List[str] = []
    idx = 0
    for raw_block in re.split(r"\n{2,}", text):
        block = raw_block.strip("\n")
        if not block.strip():
            continue
        lines = block.split("\n")
        time_pos = -1
        match = None
        for pos in range(min(3, len(lines))):
            m = _VTT_TIME_RE.match(lines[pos].strip())
            if m:
                time_pos = pos
                match = m
                break
        if match is None:
            continue

        def _norm(h: str, mm: str, ss: str, ms: str) -> str:
            hours = int(h[:-1]) if h else 0
            return f"{hours:02d}:{int(mm):02d}:{int(ss):02d},{int(ms.ljust(3, '0')):03d}"

        start = _norm(match.group(1) or "", match.group(2), match.group(3), match.group(4))
        end = _norm(match.group(5) or "", match.group(6), match.group(7), match.group(8))
        body = [_clean_cue_text(ln) for ln in lines[time_pos + 1:]]
        body = [ln for ln in body if ln.strip()]
        if not body:
            continue
        idx += 1
        blocks.append(f"{idx}\n{start} --> {end}\n" + "\n".join(body))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def normalize_vtt_text(vtt_text: str) -> str:
    """WebVTT gövdesini geçerli tek bir WebVTT belgesine dönüştürür."""
    text = (vtt_text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if text.lstrip().lower().startswith("webvtt"):
        return text if text.endswith("\n") else text + "\n"
    body = text
    blocks: List[str] = []
    for raw_block in re.split(r"\n{2,}", body):
        block = raw_block.strip("\n")
        if not block.strip():
            continue
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines or lines[0].strip().startswith(("NOTE", "STYLE", "REGION")):
            continue
        if any(_VTT_TIME_RE.match(ln.strip()) for ln in lines[:2]):
            blocks.append("\n".join(lines))
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"


def _concat_hls_vtt_segments(part_texts: List[str]) -> str:
    """Segment VTT'lerini tek WebVTT gövdesinde birleştirir (başlıklar bir kez)."""
    header = "WEBVTT"
    body_chunks: List[str] = []
    for idx, txt in enumerate(part_texts):
        seg_lines = (txt or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        skipped_header = False
        for ln in seg_lines:
            s = ln.strip()
            if not skipped_header:
                if s.startswith("WEBVTT"):
                    skipped_header = True
                    continue
                if s.startswith("X-TIMESTAMP-MAP") or s.startswith("NOTE") or s.startswith("STYLE") or s.startswith("REGION"):
                    continue
                if not s:
                    continue
            if s.startswith("X-TIMESTAMP-MAP") or (s.startswith(("NOTE", "STYLE", "REGION")) and idx > 0):
                continue
            body_chunks.append(ln.rstrip())
        body_chunks.append("")
    return header + "\n\n" + "\n".join(body_chunks).strip() + "\n"


def assemble_subtitle_text(
    sub_url: str,
    headers: Dict[str, str],
    initial_text: str = "",
    concurrency: int = 8,
    smart_fetch=None,
) -> str:
    """Altyazı kaynağını TEK metne indirir:
    - Tek .vtt/.srt dosyası -> olduğu gibi döner
    - HLS medya oynatma listesi (#EXTINF'li) -> segmentler SIRALI indirilip birleştirilir
    - HLS master (#EXT-X-STREAM-INF) -> ilk alt grup takip edilir
    AES-128 şifreli segmentler de desteklenir.
    v3.9.0: smart_fetch verildiğinde TEK dosyalık altyazı 4 başlık varyantıyla
    getirilir (rapidvid gibi hotlink korumalı CDN'lerin '0 bayt' vakası biter)."""
    text = (initial_text or "").strip()
    if not is_hls_playlist_text(text):
        try:
            if smart_fetch is not None:
                raw = smart_fetch(sub_url, headers, timeout=12.0)
            else:
                raw = fetch_url_bytes(sub_url, headers, timeout=12.0, retries=3)
            text = raw.decode("utf-8", errors="ignore").strip()
        except Exception as exc:
            raise RuntimeError(f"Altyazı kaynağı okunamadı: {exc}")

    if not is_hls_playlist_text(text):
        # düz vtt/srt dosyası — GERÇEKTEN altyazı mı? (HTML hata sayfası değil)
        if not looks_like_subtitle_bytes(text.encode("utf-8", errors="ignore")):
            raise RuntimeError(
                "İndirilen içerik altyazı değil (sunucu HTML/hata sayfası döndürdü). "
                "Altyazı bağlantısı ölmüş olabilir."
            )
        return text

    # Master listeyse: TYPE=SUBTITLES grubunun ilk URI'sini takip et; yoksa ilk varyant
    if "#EXT-X-STREAM-INF" in text:
        sub_uri = ""
        for m in re.finditer(r"#EXT-X-MEDIA:([^\n]*)", text):
            attrs = m.group(1)
            if "TYPE=SUBTITLES" in attrs:
                um = re.search(r'URI="([^"]+)"', attrs)
                if um:
                    sub_uri = urllib.parse.urljoin(sub_url, um.group(1))
                    break
        if not sub_uri:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            for i, ln in enumerate(lines):
                if ln.startswith("#EXT-X-STREAM-INF:") and i + 1 < len(lines) and not lines[i + 1].startswith("#"):
                    sub_uri = urllib.parse.urljoin(sub_url, lines[i + 1])
                    break
        if not sub_uri:
            raise RuntimeError("Master listede altyazı grubu bulunamadı.")
        return assemble_subtitle_text(sub_uri, headers, initial_text="", concurrency=concurrency, smart_fetch=smart_fetch)

    parsed = parse_media_playlist_body(sub_url, text)
    items = parsed["items"]
    if not items:
        raise RuntimeError("Altyazı oynatma listesinde segment yok.")

    key_cache: Dict[str, bytes] = {}
    key_lock = threading.Lock()

    def _fetch_one(item: Tuple[int, str, Optional[str], Optional[bytes], Optional[Tuple[int, int]]]) -> str:
        _seq, s_url, k_uri, k_iv, byte_rng = item
        seg_hdrs = dict(headers)
        if byte_rng is not None:
            seg_hdrs["Range"] = f"bytes={byte_rng[0]}-{byte_rng[1]}"
        data = fetch_url_bytes(s_url, seg_hdrs, timeout=15.0, retries=3)
        if k_uri:
            with key_lock:
                if k_uri not in key_cache:
                    key_cache[k_uri] = fetch_url_bytes(k_uri, headers, timeout=10.0)
                kb = key_cache[k_uri]
            if len(kb) == 16:
                ivb = k_iv if k_iv is not None else _seq.to_bytes(16, byteorder="big")
                data = _decrypt_aes128_cbc(data, kb, ivb)
        return data.decode("utf-8", errors="ignore")

    # Sıra korunur: pencere paralel (8x), sonuç seq sırasına göre dizilir
    results: List[Optional[str]] = [None] * len(items)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(2, concurrency)) as pool:
        fut_map = {pool.submit(_fetch_one, it): pos for pos, it in enumerate(items)}
        for fut in concurrent.futures.as_completed(fut_map):
            pos = fut_map[fut]
            try:
                results[pos] = fut.result()
            except Exception as exc:
                logger.info("Altyazı segmenti atlandı (%s/%s): %s", pos + 1, len(items), exc)
    parts = [r for r in results if r and (r or "").strip()]
    if not parts:
        raise RuntimeError("Altyazı segmentlerinin hiçbiri indirilemedi.")
    merged = _concat_hls_vtt_segments(parts)
    if not looks_like_subtitle_bytes(merged.encode("utf-8", errors="ignore")):
        raise RuntimeError("Birleştirilen altyazı segmentleri geçerli bir altyazı üretmedi.")
    return merged
