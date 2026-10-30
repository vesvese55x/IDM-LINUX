from __future__ import annotations

import email.message
import logging
import os
import re
import secrets
import tempfile
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .browser_cookies import extract_browser_cookies_for_url, merge_cookie_headers
from .config import get_cache_dir
from .protocol import DownloadRequest
from .wine_sender import sanitize_filename

logger = logging.getLogger("idm_linux.auth_proxy")

DEFAULT_MODERN_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

# Cloudflare JA3/TLS + HttpOnly/JWT çerezleri nedeniyle doğrudan Wine/WinInet yerine
# her zaman yerel Range-destekli TLS 1.3 köprüsünden geçirilmesi gereken oturumlu platformlar
# v2.8.8 TARAYICI DESTEKLİ BESLEME: sunucu çerezi/CF'yi urllib'e vermiyorsa (arena.ai vb.)
# dosyayı BIZZAT TARAYICI kendi kimliğiyle çeker ve parça parça daemon'a aktarır.
_ASSIST: Dict[str, Dict[str, Any]] = {}
_ASSIST_LOCK = threading.Lock()


def assist_pending_list() -> List[Dict[str, str]]:
    now = time.time()
    with _ASSIST_LOCK:
        return [
            {"id": tid, "url": e["url"]}
            for tid, e in _ASSIST.items()
            if not e["event"].is_set() and (now - e["born"]) < 150
        ]


def assist_begin_chunk(tid: str) -> Any:
    with _ASSIST_LOCK:
        e = _ASSIST.get(tid)
        if not e:
            return None
        if e["fh"] is None:
            e["fh"] = open(e["path"], "wb")
        return e["fh"]


def assist_finish(tid: str, ok: bool) -> None:
    with _ASSIST_LOCK:
        e = _ASSIST.get(tid)
        if not e:
            return
        if e["fh"] is not None:
            try:
                e["fh"].close()
            except Exception:
                pass
            e["fh"] = None
        e["ok"] = ok
        e["event"].set()


def request_browser_assist(ticket: Any, wait_sec: float = 120.0) -> Optional[Path]:
    """401/403 kesinleştiğinde tarayıcıdan besleme ister; başarırsa yerel dosyayı döndürür."""
    tid = ticket.ticket_id
    with _ASSIST_LOCK:
        old = _ASSIST.pop(tid, None)
        if old and old["fh"]:
            try:
                old["fh"].close()
            except Exception:
                pass
        path = Path(tempfile.gettempdir()) / f"idm_assist_{tid}.part"
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        _ASSIST[tid] = {"url": ticket.target_url, "event": threading.Event(), "path": path, "fh": None, "ok": False, "born": time.time()}
        if len(_ASSIST) > 16:
            for k in [k for k, v in _ASSIST.items() if v["event"].is_set()][:8]:
                _ASSIST.pop(k, None)
    done = _ASSIST[tid]["event"].wait(wait_sec)
    with _ASSIST_LOCK:
        e = _ASSIST.pop(tid, None)
    if not done or not e or not e["ok"]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    if not path.exists() or path.stat().st_size <= 0:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return path


_BINARY_WATCH_EXTS = {".zip", ".rar", ".7z", ".exe", ".msi", ".apk", ".dmg", ".iso", ".mp4",
                      ".mkv", ".avi", ".mov", ".wmv", ".flv", ".mp3", ".flac", ".wav", ".pdf",
                      ".tar", ".gz", ".bz2", ".xz", ".bin", ".deb", ".rpm", ".appimage"}

_HTML_OK_EXTS = {".html", ".htm", ".xhtml", ".svg", ".xml", ".json", ".txt", ".php", ".asp", ".aspx", ".jsp", ".m3u8", ".mpd", ""}


def looks_like_html_payload(head: bytes, content_type: str, filename: str) -> bool:
    """v2.8.7 BÜTÜNLÜK KORUMASI: beklenen dosya ikili (zip/mp4/exe...) olduğu halde sunucu
    HTML (hata/login sayfası) döndürüyorsa True — gofile 3.3KB bozuk dosya vakasının panzehiri."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in _HTML_OK_EXTS:
        return False
    ct = (content_type or "").lower()
    if "text/html" in ct or "application/xhtml" in ct:
        return True
    h = (head or b"")[:512].lstrip().lower()
    return h.startswith(b"<!doctype html") or h.startswith(b"<html")


_ALWAYS_PROXY_AUTH_DOMAINS = (
    "arena.ai",
    "lmarena.ai",
    "chatbotarena.ai",
    "huggingface.co",
    "hf.co",
    "github.com",
    "githubusercontent.com",
    "gitlab.com",
    "notion.so",
    "figma.com",
    "kaggle.com",
    # v3.12.0 GERİ GETİRİLDİ (kullanıcı kararı): gofile.io her zaman köprüden akıtılır.
    # v3.11.0'daki "dinamik yoklama" denemesi gofile'da 3.27KB HTML bozuk dosyası
    # üretti (anonim yoklama zaman aşımına düşünce IDM çıplak URL'yi alıyordu).
    # 3.10.x'te kanıtlanmış DOĞRU akış geri döndü: gofile (api/store/gofile.io) ASMADA
    # /proxy/ köprüsünden akar; tarayıcı çerezleri + wt oturumuyla GERÇEK dosya iner,
    # bütünlük koruması HTML sayfasını asla IDM'ye yazdırmaz. Anında yakalama
    # (page_hook contents JSON kancası) aynen korunur — algılama hızı düşmez.
    "gofile.io",
    "cloudflareaccess.com",
)

_FAST_PROXY_HOSTS = (
    # v3.12.0 OK.RU/VK ANINDA BAŞLAMA LİSTESİ: Referer/çerez kilidi CANLI TESTLE
    # kanıtlanmış CDN'ler (v3.11.0: vd*.okcdn.ru çıplak istekte 400, Referer'lı
    # istekte 206). Bu sunucularda 1.3sn anonim + 2.2sn kimlikli ÇİFT YOKLAMA
    # YAŞANMAZ — istek doğrudan /proxy/ köprü biletine alınır; IDM indirmeye
    # YouTube/vk hızında (<1 sn) başlar. Köprü zaten Referer/Cookie'yi taşır.
    "ok.ru", "odnoklassniki.ru", "mrok.ru", "okcdn.ru", "mycdn.me",
    "vk.com", "vk.ru", "vkvideo.ru", "vkontakte.ru", "vkuser.net", "userapi.com",
    "bilibili.com", "b23.tv", "hdslb.com",
)

_FORWARDED_EXTRA_HEADER_NAMES = {
    "authorization",
    "x-authorization",
    "x-api-key",
    "x-auth-token",
    "x-csrf-token",
    "x-xsrf-token",
    "x-requested-with",
    "x-goog-authuser",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
}


def _extract_base_domain(hostname: str) -> str:
    h = (hostname or "").lower().strip(".")
    parts = h.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return h


def parse_content_disposition_filename(header_val: str) -> str:
    if not header_val:
        return ""
    # 1. RFC 5987: filename*=UTF-8''...
    m_star = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)?''([^;\r\n]+)", header_val)
    if m_star:
        decoded = urllib.parse.unquote(m_star.group(1).strip().strip('"'))
        if decoded:
            return sanitize_filename(decoded)

    # 2. Standart filename="..."
    msg = email.message.Message()
    msg["content-disposition"] = header_val
    fn = msg.get_filename()
    if fn:
        try:
            # Bazı sunucular UTF-8 baytlarını latin-1 başlığa ham yazar
            fn_fixed = fn.encode("latin-1").decode("utf-8")
            fn = fn_fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return sanitize_filename(urllib.parse.unquote(fn))

    m_plain = re.search(r'filename\s*=\s*"?([^";\r\n]+)"?', header_val, flags=re.IGNORECASE)
    if m_plain:
        return sanitize_filename(urllib.parse.unquote(m_plain.group(1).strip()))
    return ""


def guess_filename_from_url(url: str, fallback: str = "") -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        # S3 / R2 / GCS imzalı URL'lerde response-content-disposition sıklıkla bulunur
        for disp_key in ("response-content-disposition", "rscd", "content-disposition"):
            if disp_key in qs and qs[disp_key]:
                fn = parse_content_disposition_filename(qs[disp_key][0])
                if fn:
                    return fn
        for q_key in ("filename", "file", "name", "download"):
            if q_key in qs and qs[q_key]:
                cand = Path(urllib.parse.unquote(qs[q_key][0])).name
                if cand and "." in cand:
                    return sanitize_filename(cand)
        tail = Path(urllib.parse.unquote(parsed.path)).name
        if tail and tail not in ("/", "download", "file", "blob", "export"):
            return sanitize_filename(tail)
    except Exception:
        pass
    return sanitize_filename(fallback) if fallback else ""


def build_safe_content_disposition(filename: str) -> str:
    clean = sanitize_filename(filename or "download.bin")
    ascii_fn = clean.encode("ascii", errors="ignore").decode("ascii").strip() or "download.bin"
    ascii_fn = ascii_fn.replace('"', "_")
    disp_fn = urllib.parse.quote(clean)
    return f"attachment; filename=\"{ascii_fn}\"; filename*=UTF-8''{disp_fn}"


@dataclass
class AuthSnapshot:
    url: str
    cookies: str = ""
    referer: str = ""
    origin: str = ""
    user_agent: str = ""
    extra_headers: Dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)  # v2.9.3: purge için zorunlu
    updated_at: float = field(default_factory=time.time)


class AuthContextVault:
    """
    Tarayıcı eklentisinin webRequest.onBeforeSendHeaders (extraHeaders) ve cookies.getAll
    üzerinden yakaladığı gerçek Cookie, Authorization, Referer, Origin ve User-Agent
    bilgilerini tutar; hem hibrit hem resmi IDM eklentisinden gelen istekleri zenginleştirir.
    """

    TTL_SECONDS = 1800.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_url: Dict[str, AuthSnapshot] = {}
        self._by_host: Dict[str, AuthSnapshot] = {}

    def record(
        self,
        url: str,
        cookies: str = "",
        referer: str = "",
        origin: str = "",
        user_agent: str = "",
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        if not url or not url.startswith(("http://", "https://")):
            return
        try:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
        except ValueError:
            return
        if not host or host in ("127.0.0.1", "localhost"):
            return

        filtered_hdrs: Dict[str, str] = {}
        for k, v in (extra_headers or {}).items():
            if not k or not v:
                continue
            kl = k.strip().lower()
            if kl in _FORWARDED_EXTRA_HEADER_NAMES:
                filtered_hdrs[k.strip()] = str(v).strip()

        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            prev_url = self._by_url.get(url)
            prev_host = self._by_host.get(host)

            merged_ck = merge_cookie_headers(
                cookies,
                prev_url.cookies if prev_url else "",
                prev_host.cookies if prev_host else "",
            )
            merged_hdrs: Dict[str, str] = {}
            if prev_host:
                merged_hdrs.update(prev_host.extra_headers)
            if prev_url:
                merged_hdrs.update(prev_url.extra_headers)
            merged_hdrs.update(filtered_hdrs)

            snap = AuthSnapshot(
                url=url,
                cookies=merged_ck,
                referer=referer or (prev_url.referer if prev_url else "") or (prev_host.referer if prev_host else ""),
                origin=origin or (prev_url.origin if prev_url else "") or (prev_host.origin if prev_host else ""),
                user_agent=user_agent
                or (prev_url.user_agent if prev_url else "")
                or (prev_host.user_agent if prev_host else ""),
                extra_headers=merged_hdrs,
                updated_at=now,
            )
            self._by_url[url] = snap
            self._by_host[host] = snap
            base_dom = _extract_base_domain(host)
            if base_dom and base_dom != host:
                prev_base = self._by_host.get(base_dom)
                if not prev_base:
                    self._by_host[base_dom] = snap
                else:
                    prev_base.cookies = merge_cookie_headers(merged_ck, prev_base.cookies)
                    prev_base.updated_at = now

    def _cleanup_locked(self, now: float) -> None:
        if len(self._by_url) > 400:
            expired_u = [u for u, s in self._by_url.items() if (now - s.updated_at) > self.TTL_SECONDS]
            for u in expired_u:
                self._by_url.pop(u, None)
        if len(self._by_host) > 200:
            expired_h = [h for h, s in self._by_host.items() if (now - s.updated_at) > self.TTL_SECONDS]
            for h in expired_h:
                self._by_host.pop(h, None)

    def enrich_request(self, req: DownloadRequest) -> DownloadRequest:
        if not req.url.startswith(("http://", "https://")):
            return req
        try:
            parsed = urllib.parse.urlparse(req.url)
            host = (parsed.hostname or "").lower()
        except ValueError:
            return req
        if not host or host in ("127.0.0.1", "localhost"):
            return req

        snap_url: Optional[AuthSnapshot] = None
        snap_host: Optional[AuthSnapshot] = None
        snap_base: Optional[AuthSnapshot] = None
        base_dom = _extract_base_domain(host)

        with self._lock:
            snap_url = self._by_url.get(req.url)
            snap_host = self._by_host.get(host)
            if base_dom and base_dom != host:
                snap_base = self._by_host.get(base_dom)

        # Açık tarayıcıların yerel SQLite çerez veritabanından da (HttpOnly + Partitioned) tamamla
        db_cookies = ""
        try:
            db_cookies = extract_browser_cookies_for_url(req.url)
        except Exception as exc:
            logger.debug("Yerel DB çerez zenginleştirme hatası: %s", exc)

        req.cookies = merge_cookie_headers(
            snap_url.cookies if snap_url else "",
            req.cookies,
            snap_host.cookies if snap_host else "",
            snap_base.cookies if snap_base else "",
            db_cookies,
        )

        if not req.referer:
            req.referer = (
                (snap_url.referer if snap_url else "")
                or (snap_host.referer if snap_host else "")
                or f"{parsed.scheme}://{host}/"
            )
        if not req.origin:
            req.origin = (snap_url.origin if snap_url else "") or (snap_host.origin if snap_host else "")
        if not req.user_agent:
            req.user_agent = (
                (snap_url.user_agent if snap_url else "")
                or (snap_host.user_agent if snap_host else "")
                or DEFAULT_MODERN_UA
            )

        merged_extra: Dict[str, str] = {}
        if snap_base:
            merged_extra.update(snap_base.extra_headers)
        if snap_host:
            merged_extra.update(snap_host.extra_headers)
        if snap_url:
            merged_extra.update(snap_url.extra_headers)
        for k, v in (req.extra_headers or {}).items():
            if k and v and k.strip().lower() in _FORWARDED_EXTRA_HEADER_NAMES:
                merged_extra[k.strip()] = str(v).strip()
        req.extra_headers = merged_extra
        return req


@dataclass
class AuthProxyTicket:
    ticket_id: str
    kind: str  # "remote" | "blob"
    filename: str
    mime_type: str = "application/octet-stream"
    target_url: str = ""
    cookies: str = ""
    referer: str = ""
    origin: str = ""
    user_agent: str = DEFAULT_MODERN_UA
    extra_headers: Dict[str, str] = field(default_factory=dict)
    blob_file: Optional[Path] = None
    created_at: float = field(default_factory=time.time)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        return None


class AuthenticatedProxyManager:
    """
    1) Kimlik doğrulamalı (Cookie / Authorization: Bearer / Cloudflare oturumu gerektiren)
       indirmeleri yerel 127.0.0.1 HTTP 206 Range köprüsü üzerinden IDM'ye sunar; böylece
       Windows IDMan.exe ASLA 'Authorization Required (Kullanıcı adı / şifre)' penceresi açmaz!
    2) Tarayıcı içi blob:https://... (örn. arena.ai / GitHub / SPA bellek indirmeleri)
       dosyalarını yerel köprüye alıp gerçek IDM penceresiyle indirtir!
    """

    TICKET_TTL = 7200.0

    def __init__(self, vault: AuthContextVault) -> None:
        self.vault = vault
        self._lock = threading.Lock()
        self._tickets: Dict[str, AuthProxyTicket] = {}
        self._ssl_ctx = ssl.create_default_context()

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired = [tid for tid, t in self._tickets.items() if (now - t.created_at) > self.TICKET_TTL]
        for tid in expired:
            t = self._tickets.pop(tid, None)
            if t and t.blob_file and t.blob_file.exists():
                try:
                    t.blob_file.unlink(missing_ok=True)
                except OSError:
                    pass

    def get_ticket(self, ticket_id: str) -> Optional[AuthProxyTicket]:
        with self._lock:
            self._cleanup_locked()
            return self._tickets.get(ticket_id)

    def create_blob_ticket(
        self,
        raw_bytes: bytes,
        filename: str = "",
        mime_type: str = "application/octet-stream",
    ) -> AuthProxyTicket:
        blob_dir = get_cache_dir(create=True) / "blob_staging"
        blob_dir.mkdir(parents=True, exist_ok=True)
        tid = secrets.token_hex(12)
        clean_fn = sanitize_filename(filename or f"download-{tid[:6]}.bin")
        blob_path = blob_dir / f"{tid}_{clean_fn}"
        blob_path.write_bytes(raw_bytes)

        ticket = AuthProxyTicket(
            ticket_id=tid,
            kind="blob",
            filename=clean_fn,
            mime_type=mime_type or "application/octet-stream",
            blob_file=blob_path,
        )
        with self._lock:
            self._cleanup_locked()
            self._tickets[tid] = ticket
        return ticket

    def create_blob_ticket_streamed(
        self,
        reader: Any,
        length: int,
        filename: str = "",
        mime_type: str = "application/octet-stream",
    ) -> Tuple[Optional[AuthProxyTicket], str]:
        """v3.2.2 BELLEK KALKANI: büyük blob yüklemesini RAM'e ALMADAN diske akıtır.
        Eski yol 256MB'lık gövdeyi `chunks[]` + `b"".join()` ile 2x RAM'de tutuyordu.
        Dönüş: (ticket | None, hata mesajı)"""
        blob_dir = get_cache_dir(create=True) / "blob_staging"
        blob_dir.mkdir(parents=True, exist_ok=True)
        tid = secrets.token_hex(12)
        clean_fn = sanitize_filename(filename or f"download-{tid[:6]}.bin")
        blob_path = blob_dir / f"{tid}_{clean_fn}"
        written = 0
        try:
            with blob_path.open("wb") as fh:
                rem = length
                while rem > 0:
                    blk = reader.read(min(262144, rem))
                    if not blk:
                        break
                    fh.write(blk)
                    written += len(blk)
                    rem -= len(blk)
        except OSError as exc:
            blob_path.unlink(missing_ok=True)
            return None, f"Blob diske yazılamadı: {exc}"
        if written <= 0:
            blob_path.unlink(missing_ok=True)
            return None, "Boş blob gövdesi."
        ticket = AuthProxyTicket(
            ticket_id=tid,
            kind="blob",
            filename=clean_fn,
            mime_type=mime_type or "application/octet-stream",
            blob_file=blob_path,
        )
        with self._lock:
            self._cleanup_locked()
            self._tickets[tid] = ticket
        return ticket, ""

    def _build_upstream_headers(self, ticket: AuthProxyTicket, range_hdr: str = "") -> Dict[str, str]:
        hdrs: Dict[str, str] = {
            "User-Agent": ticket.user_agent or DEFAULT_MODERN_UA,
            "Accept": "*/*",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        if ticket.referer:
            hdrs["Referer"] = ticket.referer
        if ticket.origin:
            hdrs["Origin"] = ticket.origin
        if ticket.cookies:
            hdrs["Cookie"] = ticket.cookies
        for k, v in ticket.extra_headers.items():
            if k and v:
                hdrs[k] = v
        if range_hdr:
            hdrs["Range"] = range_hdr
        return hdrs

    def _probe_upstream(self, req: DownloadRequest, fail_safe: bool = False) -> Tuple[bool, str, str]:
        """
        Uzak sunucunun anonim (çerezsiz/başlıksız) bağlantıda 401/403/login-redirect verip
        vermediğini ve kimlikli bağlantıda dönen gerçek dosya adını (Content-Disposition)
        1.5 saniye içinde kontrol eder.
        Dönüş: (needs_auth_proxy, discovered_filename, final_url)

        v3.12.0: fail_safe=True (gofile gibi katı-domain siteler) iken yoklama beklemediği
        şekilde sonlanırsa (zaman aşımı/ağ hatası) HASARLI SONUÇ yerine KÖPRÜ seçilir —
        IDM'ye asla bozuk HTML gitmez; köprü zaten bütünlük korumasıyla akıtır.
        """
        needs_proxy = False
        discovered_fn = ""
        final_url = req.url

        # 1. Hızlı anonim kontrol (yönlendirme izlemeden)
        no_redir_opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self._ssl_ctx),
            _NoRedirectHandler(),
        )
        anon_req = urllib.request.Request(
            req.url,
            method="GET",
            headers={
                "User-Agent": req.user_agent or DEFAULT_MODERN_UA,
                "Range": "bytes=0-0",
            },
        )
        try:
            with no_redir_opener.open(anon_req, timeout=1.3) as resp:
                code = resp.getcode() or 200
                cd = resp.headers.get("Content-Disposition") or ""
                if cd:
                    discovered_fn = parse_content_disposition_filename(cd)
                if code in (401, 403):
                    needs_proxy = True
                # v2.8.7: dosya beklenirken HTML dönüyorsa (gofile wt/token eksik vb.) proxy'ye al
                ct_anon = resp.headers.get("Content-Type") or ""
                fn_guess = req.filename or urllib.parse.urlparse(req.url).path.rsplit("/", 1)[-1]
                if code == 200 and looks_like_html_payload(b"", ct_anon, fn_guess):
                    needs_proxy = True
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = (e.headers.get("Location") or "").lower()
                if any(tok in loc for tok in ("login", "signin", "sign-in", "auth", "clerk", "account", "sso")):
                    needs_proxy = True
            elif e.code in (400, 401, 403, 405):
                # 401/403 kesin kimlik doğrulama gerektiriyor!
                if e.code in (401, 403):
                    needs_proxy = True
                # v3.11.0: 400 = Referer/UA kilidi olabilir (canlı doğrulandı: ok.ru'nun
                # CDN'i vd*.okcdn.ru çıplak istekte 400, Referer'lı istekte 206 döndü).
                # needs_proxy işaretlenir; aşağıdaki kimlikli (başlıklı) yoklama onaylar.
                elif e.code in (400, 405):
                    needs_proxy = True
        except Exception:
            # v3.12.0: katı-domain (gofile vb.) isteklerde yoklama cevap vermezse
            # "yok" varsaymak YASAK — bozuk dosya vakası tam da buradan doğuyordu.
            if fail_safe:
                needs_proxy = True

        # 2. Eğer proxy gerekiyorsa veya dosya adı henüz belirsizse, kimlikli 1-bayt yoklamayla
        #    hem kimlik doğrulamanın çalıştığını doğrula hem de gerçek Content-Disposition adını al!
        if needs_proxy or not req.filename:
            temp_ticket = AuthProxyTicket(
                ticket_id="probe",
                kind="remote",
                filename=req.filename or "download.bin",
                target_url=req.url,
                cookies=req.cookies,
                referer=req.referer,
                origin=req.origin,
                user_agent=req.user_agent or DEFAULT_MODERN_UA,
                extra_headers=dict(req.extra_headers),
            )
            auth_opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self._ssl_ctx))
            auth_req = urllib.request.Request(
                req.url,
                method="GET",
                headers=self._build_upstream_headers(temp_ticket, range_hdr="bytes=0-0"),
            )
            try:
                with auth_opener.open(auth_req, timeout=2.2) as resp:
                    final_url = resp.geturl() or req.url
                    cd = resp.headers.get("Content-Disposition") or ""
                    if cd:
                        fn = parse_content_disposition_filename(cd)
                        if fn:
                            discovered_fn = fn
                    ct = (resp.headers.get("Content-Type") or "").lower()
                    # Eğer anonim istek text/html login sayfası dönerken kimlikli istek binary dosya dönüyorsa
                    if not needs_proxy and req.cookies and "text/html" not in ct and resp.headers.get("Set-Cookie"):
                        needs_proxy = True
            except Exception as exc:
                logger.debug("Kimlikli ön yoklama bilgi notu (%s): %s", req.url[:80], exc)

        return needs_proxy, discovered_fn, final_url

    def maybe_wrap_authenticated_download(self, req: DownloadRequest, http_port: int) -> DownloadRequest:
        """
        Gelen indirme isteğini önce tüm tarayıcı çerezleri ve başlıklarla zenginleştirir.
        Eğer indirme oturum / Authorization / Cloudflare gerektiriyorsa (örn. arena.ai),
        isteği yerel yüksek hızlı HTTP 206 Range köprüsüne (/proxy/<id>/<filename>) sarar.
        """
        if not req.url.startswith(("http://", "https://")) or req.post_data:
            return req

        try:
            parsed = urllib.parse.urlparse(req.url)
            host = (parsed.hostname or "").lower()
        except ValueError:
            return req

        if not host or host in ("127.0.0.1", "localhost", "::1"):
            return req

        # 1. Tüm kaynaklardan (Eklenti webRequest kasası + Açık Tarayıcı SQLite çerezleri) zenginleştir
        self.vault.enrich_request(req)

        has_auth_hdr = any(
            k.lower() in ("authorization", "x-authorization", "x-api-key", "x-auth-token", "x-csrf-token")
            for k in req.extra_headers
        )
        domain_matches_strict = any(
            host == dom or host.endswith("." + dom) for dom in _ALWAYS_PROXY_AUTH_DOMAINS
        )
        long_cookies = len(req.cookies) > 1000

        # v3.12.0: referer-kilitli CDN'lerde YOKLAMA YOK (bilet anında açılır)
        fast_proxy_host = any(
            host == dom or host.endswith("." + dom) for dom in _FAST_PROXY_HOSTS
        )
        probed_needs_proxy = False
        discovered_fn = ""

        if fast_proxy_host:
            # Çift yoklama (1.3sn anonim + 2.2sn kimlikli) ATLANIR — bilet
            # mikrosaniyelerde hazır olur; köprü Referer/Cookie'yi taşıdığı için
            # ok.ru/vk CDN'lerinin 400/403 kilidi köprüde çözülür.
            force_proxy = True
        else:
            force_proxy = has_auth_hdr or (domain_matches_strict and bool(req.cookies or has_auth_hdr)) or long_cookies

            # v2.8.7: çerezsiz isteklerde bile ikili dosya bekleniyorsa hızlı içerik-taraması yap
            # (gofile vb. siteler HTML hata sayfasını 200 ile döndürüp 3.3KB bozuk dosya indirtiyor!)
            _url_ext = os.path.splitext(urllib.parse.urlparse(req.url).path)[1].lower()
            _fn_ext = os.path.splitext(req.filename or "")[1].lower()
            binary_watch = (_url_ext in _BINARY_WATCH_EXTS) or (_fn_ext in _BINARY_WATCH_EXTS)
            if force_proxy or req.cookies or domain_matches_strict or binary_watch:
                # v3.12.0: katı-domain sitelerde (gofile vb.) yoklama beklenmedik şekilde
                # sonlanırsa köprüye düş (fail_safe) — IDM'ye bozuk HTML gitmesin.
                probed_needs_proxy, discovered_fn, _final_u = self._probe_upstream(
                    req, fail_safe=domain_matches_strict
                )
                if not req.cookies and (probed_needs_proxy or domain_matches_strict):
                    # Çerez henüz yazılmış olabilir; bir kez daha doğrudan tarayıcı DB'sini tara
                    fresh_ck = extract_browser_cookies_for_url(req.url)
                    if fresh_ck:
                        req.cookies = fresh_ck

        if not (force_proxy or probed_needs_proxy):
            if discovered_fn and not req.filename:
                req.filename = discovered_fn
            return req

        final_fn = (
            discovered_fn
            or guess_filename_from_url(req.url, fallback=req.filename)
            or sanitize_filename(req.filename or "download.bin")
        )
        tid = secrets.token_hex(12)
        ticket = AuthProxyTicket(
            ticket_id=tid,
            kind="remote",
            filename=final_fn,
            target_url=req.url,
            cookies=req.cookies,
            referer=req.referer,
            origin=req.origin,
            user_agent=req.user_agent or DEFAULT_MODERN_UA,
            extra_headers=dict(req.extra_headers),
        )
        with self._lock:
            self._cleanup_locked()
            self._tickets[tid] = ticket

        quoted_fn = urllib.parse.quote(final_fn)
        proxy_url = f"http://127.0.0.1:{http_port}/proxy/{tid}/{quoted_fn}"
        logger.info(
            "Kimlik doğrulamalı indirme yerel TLS/Cookie köprüsüne alındı: %s -> %s",
            host,
            final_fn,
        )
        return DownloadRequest(
            url=proxy_url,
            filename=final_fn,
            save_dir=req.save_dir,
            silent=req.silent,
            source=req.source,
        )

    def purge_old_tickets(self, max_age_sec: int = 3600) -> int:
        """v2.9.2: yaşlı proxy biletlerini süpür (katı bellek koruması)."""
        now = time.time()
        dropped = 0
        with self._lock:
            for tid in list(self._tickets.keys()):
                tk = self._tickets[tid]
                born = getattr(tk, "created_at", None) or getattr(tk, "born", None)
                if born and (now - float(born)) > max_age_sec:
                    self._tickets.pop(tid, None)
                    dropped += 1
        return dropped

    def serve_proxy_ticket(self, handler: Any, ticket_id: str, head_only: bool = False) -> None:
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            handler.send_response(404)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return

        try:
            handler.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

        range_hdr = (handler.headers.get("Range") or "").strip()

        # DURUM A: Tarayıcı belleğinden (blob:https://arena.ai/...) aktarılan dosya
        if ticket.kind == "blob":
            if not ticket.blob_file or not ticket.blob_file.is_file():
                handler.send_response(404)
                handler.send_header("Content-Length", "0")
                handler.end_headers()
                return

            total_size = ticket.blob_file.stat().st_size
            start_byte = 0
            end_byte = max(0, total_size - 1)
            is_partial = False

            if total_size > 0 and range_hdr.startswith("bytes="):
                m = re.match(r"bytes=(\d*)-(\d*)", range_hdr)
                if m:
                    s_s, e_s = m.group(1), m.group(2)
                    if s_s:
                        start_byte = min(int(s_s), total_size - 1)
                    if e_s:
                        end_byte = min(int(e_s), total_size - 1)
                    if start_byte <= end_byte:
                        is_partial = True

            length = (end_byte - start_byte + 1) if total_size > 0 else 0
            handler.send_response(206 if is_partial else 200)
            handler.send_header("Content-Type", ticket.mime_type or "application/octet-stream")
            handler.send_header("Accept-Ranges", "bytes")
            if is_partial:
                handler.send_header("Content-Range", f"bytes {start_byte}-{end_byte}/{total_size}")
            handler.send_header("Content-Length", str(length))
            handler.send_header("Content-Disposition", build_safe_content_disposition(ticket.filename))
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.wfile.flush()
            if head_only or length == 0:
                return

            try:
                with ticket.blob_file.open("rb") as fh:
                    fh.seek(start_byte)
                    rem = length
                    while rem > 0:
                        chunk = fh.read(min(65536, rem))
                        if not chunk:
                            break
                        handler.wfile.write(chunk)
                        rem -= len(chunk)
                    handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            return

        # DURUM B: Uzak Kimlik Doğrulamalı HTTPS Akışı (arena.ai vb. — 200 & 206 Range Desteği!)
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self._ssl_ctx))
        method = "HEAD" if head_only else "GET"

        def _open_upstream(allow_refresh: bool = True) -> Any:
            up_headers = self._build_upstream_headers(ticket, range_hdr=range_hdr)
            up_req = urllib.request.Request(ticket.target_url, method=method, headers=up_headers)
            try:
                return opener.open(up_req, timeout=25)
            except urllib.error.HTTPError as err:
                # HEAD desteklemeyen imzalı API'ler için GET bytes=0-0 yedeği
                if head_only and err.code in (403, 405, 501):
                    get_hdrs = self._build_upstream_headers(ticket, range_hdr="bytes=0-0")
                    return opener.open(
                        urllib.request.Request(ticket.target_url, method="GET", headers=get_hdrs),
                        timeout=25,
                    )
                # 401/403 durumunda tarayıcı çerezlerini tazeleyip bir kez daha dene!
                if allow_refresh and err.code in (401, 403):
                    fresh_req = DownloadRequest(
                        url=ticket.target_url,
                        referer=ticket.referer,
                        origin=ticket.origin,
                        cookies=ticket.cookies,
                        user_agent=ticket.user_agent,
                        extra_headers=dict(ticket.extra_headers),
                    )
                    self.vault.enrich_request(fresh_req)
                    ticket.cookies = fresh_req.cookies
                    ticket.extra_headers = fresh_req.extra_headers
                    return _open_upstream(allow_refresh=False)
                raise

        try:
            resp = _open_upstream(allow_refresh=True)
        except urllib.error.HTTPError as err:
            # v2.8.8: çerez urllib'e gelmiyorsa TARAYICIDAN BESLEME iste (arena.ai workspace vb.)
            if err.code in (401, 403) and not head_only:
                fed = request_browser_assist(ticket)
                if fed is not None:
                    total = fed.stat().st_size
                    handler.send_response(200)
                    handler.send_header("Content-Type", "application/octet-stream")
                    handler.send_header("Accept-Ranges", "bytes")
                    handler.send_header("Content-Length", str(total))
                    handler.send_header("Content-Disposition", build_safe_content_disposition(ticket.filename))
                    handler.send_header("Cache-Control", "no-store")
                    handler.send_header("Connection", "close")
                    handler.end_headers()
                    handler.wfile.flush()
                    try:
                        with fed.open("rb") as fh:
                            while True:
                                blk = fh.read(65536)
                                if not blk:
                                    break
                                handler.wfile.write(blk)
                                handler.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    finally:
                        try:
                            fed.unlink(missing_ok=True)
                        except OSError:
                            pass
                    return
            # KRİTİK: WWW-Authenticate başlığını ASLA IDMan.exe'ye iletme (kullanıcı adı/şifre popup'ını önler!)
            status_out = 502 if err.code == 401 else err.code
            logger.warning("Kimlikli indirme uzak sunucu hatası (%s): HTTP %s", ticket.target_url[:80], err.code)
            handler.send_response(status_out)
            handler.send_header("Content-Type", "text/plain; charset=utf-8")
            handler.send_header("Content-Length", "0")
            handler.send_header("Connection", "close")
            handler.end_headers()
            return
        except Exception as exc:
            logger.error("Kimlikli indirme bağlantı hatası (%s): %s", ticket.target_url[:80], exc)
            handler.send_response(502)
            handler.send_header("Content-Length", "0")
            handler.send_header("Connection", "close")
            handler.end_headers()
            return

        with resp:
            up_code = resp.getcode() or 200
            up_hdrs = resp.headers

            # HEAD isteği GET bytes=0-0 ile karşılandıysa toplam boyutu Content-Range içinden çıkar
            content_len = up_hdrs.get("Content-Length")
            content_range = up_hdrs.get("Content-Range")
            if head_only and up_code == 206 and not range_hdr and content_range and "/" in content_range:
                tot_part = content_range.rsplit("/", 1)[-1].strip()
                if tot_part.isdigit():
                    content_len = tot_part
                up_code = 200
                content_range = None

            cd_upstream = up_hdrs.get("Content-Disposition") or ""
            up_fn = parse_content_disposition_filename(cd_upstream)
            if up_fn:
                ticket.filename = up_fn

            ctype = up_hdrs.get("Content-Type") or ticket.mime_type or "application/octet-stream"
            accept_ranges = up_hdrs.get("Accept-Ranges") or ("bytes" if content_len else "none")

            # v2.8.7 BÜTÜNLÜK KORUMASI: uzak HTML hata sayfası döndürdüyse IDM'ye 502 ver,
            # 3.3KB bozuk dosya ASLA diske yazılmasın.
            first_blk = b""
            if not head_only:
                try:
                    first_blk = resp.read(65536) or b""
                except Exception:
                    first_blk = b""
                if looks_like_html_payload(first_blk, ctype, ticket.filename):
                    logger.warning("Bütünlük koruması: %s HTML hata sayfası döndürdü — 502.", ticket.target_url[:90])
                    handler.send_response(502)
                    handler.send_header("Content-Type", "text/plain; charset=utf-8")
                    handler.send_header("Content-Length", "0")
                    handler.send_header("Connection", "close")
                    handler.end_headers()
                    return

            handler.send_response(206 if (up_code == 206 and range_hdr) else 200)
            handler.send_header("Content-Type", ctype)
            handler.send_header("Accept-Ranges", accept_ranges)
            if up_code == 206 and range_hdr and content_range:
                handler.send_header("Content-Range", content_range)
            if content_len and content_len.isdigit():
                handler.send_header("Content-Length", content_len)
            handler.send_header("Content-Disposition", build_safe_content_disposition(ticket.filename))
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.wfile.flush()

            if head_only:
                return

            try:
                if first_blk:
                    handler.wfile.write(first_blk)
                    handler.wfile.flush()
                while True:
                    blk = resp.read(65536)
                    if not blk:
                        break
                    handler.wfile.write(blk)
                    handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
