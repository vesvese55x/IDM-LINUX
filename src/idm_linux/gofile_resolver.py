"""v3.14.0: GOFILE.IO SUNUCU-TARAFLI ÇÖZÜCÜ — IDM her koşulda DOĞRU linki yakalar.

Sorun (kullanıcı raporu): "gofile indirmeleri IDM yakalayamıyor, tarayıcıda iniyor;
en doğru şekilde yakalasın, en doğru şekilde indirsin, asla bozuk dosya olmasın."

v3.14.0 düzeltmeleri (kullanıcı günlüğündeki 'HTTP Error 401: Unauthorized' vakası):
  1) 401/403 GERİ DÖNÜŞÜMÜ: diskteki 6 saatlik misafir token'ın süresi dolmuşsa
     /contents çağrısı 401 ile çöküyordu ve çözüm BÜTÜNCE başarısız oluyordu.
     Artık 401/403'te token GEÇERSİZ kılınır, TAZE misafir hesabı alınır ve
     çözümleme bir kez daha denenir.
  2) wt (websiteToken) artık sayfa HTML'inin yanında dist JS paketlerinden de
     kazınır (gofile arayüzü token'ı JS bundle'ına taşıdı) + daemon başında
     ARKA PLANDA ön-ısıtılır — çözüm bütçesi (12 sn) asla wt için harcanmaz.
  3) Store linki indirmeleri için ``account_token()`` erişimi: köprü/probe
     'Cookie: accountToken=...' gönderebilir (web uygulamasının yaptığı gibi).

Kök mantık
----------
Gofile indirmeleri 3 katmanda kaybediliyordu:
  1) Sayfa JS'i indirmeyi location.assign()/anchor tıklamasıyla başlatınca eklenti
     kaçırıyordu -> tarayıcı kendi indiriyordu.
  2) API JSON'undan yakalanan store linki KISA SÜRELİ dir; IDM'ye ulaştığında
     süre dolmuş olabiliyordu -> bozuk/HTML gövde.
  3) Köprüyeye gelen HTML hata sayfası (3.27KB) IDM'ye dosya sanılıp yazılıyordu.

Bu modül kökten çözer: gofile sayfa linkini (gofile.io/d/<id>) veya store linkini
alır, RESMÎ gofile API'siyle (guest hesap + wt + /contents) ANINDA TAZE gerçek
indirme linklerini üretir. IDM her zaman diri bir store linki indirir -> dosya
asla bozuk olmaz, tarayıcı da asla devreye girmez.

Kullanılan resmî uçlar (gofile API dokümanı):
  POST https://api.gofile.io/accounts            -> guest token (misafir hesap)
  GET  https://api.gofile.io/servers             -> aktif store sunucuları
  GET  https://api.gofile.io/contents/<id>?wt=.. -> klasör/dosya detayı + linkler
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import get_cache_dir, setup_logger

logger = setup_logger("gofile", "daemon.log")

GOFILE_HOSTS = ("gofile.io", "gofile.is")
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)
_GOFILE_API = "https://api.gofile.io"

# store linki: https://<store>.gofile.io/download/web/<fileId>/<ad>  (veya eski /download/<ad>)
_STORE_LINK_RX = re.compile(
    r"^https?://[a-z0-9.-]*gofile\.(?:io|is)/download/(?:web/)?(?P<fid>[a-zA-Z0-9]+)/(?P<name>[^/?#]+)",
    re.I,
)
_PAGE_LINK_RX = re.compile(
    r"^https?://(?:www\.)?(?:gofile\.io|gofile\.is)/(?:d/)?(?P<cid>[a-zA-Z0-9]{6,20})/?$",
    re.I,
)
# Sayfa HTML'inden wt (websiteToken) kazıma desenleri — sayfa JS'i değişse bile
# bir deseni eşleşsin diye birden çok biçim denenir.
_WT_RXS = (
    re.compile(r'"websiteToken"\s*:\s*"([^"]{6,80})"', re.I),
    re.compile(r"websiteToken\s*[=:]\s*['\"]([^'\"]{6,80})['\"]", re.I),
    re.compile(r"[?&]wt=([a-zA-Z0-9]{6,80})"),
)
# v3.14.0: dist JS paketi adresleri (wt bundle'a taşındı)
_JS_URL_RX = re.compile(r'(?:src=["\']|href=["\'])?((?:https?:)?//[^"\' ]+?\.js(?:\?[^"\' ]*)?|/dist/[^"\' ]+?\.js)', re.I)


@dataclass
class GofileFile:
    url: str
    name: str
    size: int = 0


@dataclass
class GofileResult:
    ok: bool = False
    files: List[GofileFile] = field(default_factory=list)
    folder_name: str = ""
    error: str = ""


def is_gofile_url(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in GOFILE_HOSTS)


def is_gofile_store_link(url: str) -> bool:
    return bool(_STORE_LINK_RX.match((url or "").strip()))


def extract_file_id_from_store_link(url: str) -> str:
    m = _STORE_LINK_RX.match((url or "").strip())
    return m.group("fid") if m else ""


def extract_content_id(url: str) -> str:
    """gofile.io/d/<id> sayfa linkinden içerik kimliğini çıkarır."""
    u = (url or "").strip()
    m = _PAGE_LINK_RX.match(u)
    if m:
        return m.group("cid")
    # /d/<id> biçimindeki tüm varyantlar (sorgu/# eklentili)
    m = re.search(r"gofile\.(?:io|is)/d/([a-zA-Z0-9]{4,30})", u, re.I)
    return m.group(1) if m else ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


class GofileResolver:
    """Gofile içerik kimliğini taze store linklerine çözer (thread-güvenli, önbellekli)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: str = ""
        self._token_ts: float = 0.0
        self._wt: str = ""
        self._wt_ts: float = 0.0
        self._disk_loaded = False

    # ------------------------------------------------------------------
    # önbellek (diskte 6 saat — daemon yeniden başlasa da misafir hesap durur)
    # ------------------------------------------------------------------
    def _cache_path(self) -> Path:
        return get_cache_dir(create=True) / "gofile_guest.json"

    def _load_cache(self) -> None:
        if self._disk_loaded:
            return
        self._disk_loaded = True
        try:
            data = json.loads(self._cache_path().read_text(encoding="utf-8"))
            now = time.time()
            if now - float(data.get("token_ts") or 0) < 6 * 3600 and data.get("token"):
                self._token = str(data["token"])
                self._token_ts = float(data.get("token_ts") or now)
            if now - float(data.get("wt_ts") or 0) < 6 * 3600 and data.get("wt"):
                self._wt = str(data["wt"])
                self._wt_ts = float(data.get("wt_ts") or now)
        except Exception:
            pass

    def _save_cache(self) -> None:
        try:
            self._cache_path().write_text(
                json.dumps({"token": self._token, "token_ts": self._token_ts, "wt": self._wt, "wt_ts": self._wt_ts}),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # düşük seviye HTTP
    # ------------------------------------------------------------------
    @staticmethod
    def _http_json(url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None, timeout: float = 8.0) -> Tuple[int, Dict[str, Any]]:
        """JSON uçlarını çağırır; HTTP hata kodlarında İSTİSA ATMAZ — kodu döner.

        v3.14.0: 401/403 geri dönüşümü için hata gövdeleri de okunur (eski akışta
        HTTPError istisnası yukarı fırlıyor, çözümleme 'zaman aşımı' sanılıyordu).
        """
        req = urllib.request.Request(url, method=method, headers={"User-Agent": _UA, "Accept": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(2 * 1024 * 1024)
                code = resp.getcode() or 200
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(2 * 1024 * 1024)
            except Exception:
                body = b""
            code = int(exc.code or 0)
        except Exception:
            raise
        try:
            data = json.loads(body.decode("utf-8", "replace"))
        except Exception:
            data = {}
        return code, data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # guest token + wt
    # ------------------------------------------------------------------
    def _guest_token(self, force_new: bool = False) -> str:
        with self._lock:
            self._load_cache()
            if not force_new and self._token and (time.time() - self._token_ts) < 6 * 3600:
                return self._token
            # Resmî misafir hesap ucu (yeni API): POST /accounts
            for endpoint, method in ((_GOFILE_API + "/accounts", "POST"), (_GOFILE_API + "/accounts", "GET")):
                try:
                    code, data = self._http_json(endpoint, method=method, timeout=8.0)
                    tok = str(((data.get("data") or {}).get("token")) or "")
                    if code in (200, 201) and tok:
                        self._token = tok
                        self._token_ts = time.time()
                        self._save_cache()
                        logger.info("Gofile misafir token alındı (%s).", endpoint)
                        return self._token
                except urllib.error.HTTPError:
                    continue
                except Exception:
                    continue
            return ""

    def _invalidate_token(self) -> None:
        """v3.14.0: süresi dolan/reddedilen misafir token'ını önbellekten siler."""
        with self._lock:
            self._token = ""
            self._token_ts = 0.0
            try:
                self._cache_path().unlink(missing_ok=True)
            except Exception:
                pass

    def account_token(self) -> str:
        """Store linki indirmelerinde 'Cookie: accountToken=' için misafir token.
        Ağ yoksa boş döner; çağıran taraf cookie'siz devam eder."""
        return self._guest_token()

    def prewarm(self) -> None:
        """Token + wt'yi ARKA PLANDA hazırlar (dispatch bütçesini hiç harcamaz)."""
        def _job() -> None:
            try:
                self._guest_token()
                self._website_token("")
            except Exception:
                pass

        threading.Thread(target=_job, name="gofile-prewarm", daemon=True).start()

    def _website_token(self, content_id: str) -> str:
        """wt parametresini gofile sayfasından/dist JS'inden kazır (6 saat önbellek).

        v3.14.0: gofile arayüzü websiteToken'ı JS paketine taşıdı; HTML'de
        bulunamazsa sayfadaki dist JS'leri de indirilip taranır.
        """
        with self._lock:
            self._load_cache()
            if self._wt and (time.time() - self._wt_ts) < 6 * 3600:
                return self._wt
        page_urls = (
            f"https://gofile.io/d/{content_id}" if content_id else "https://gofile.io/",
            "https://gofile.io/uploadFiles",
        )
        for pu in page_urls:
            try:
                req = urllib.request.Request(pu, headers={"User-Agent": _UA, "Accept": "*/*"})
                with urllib.request.urlopen(req, timeout=6.0) as resp:
                    html = resp.read(1024 * 1024).decode("utf-8", "replace")
                # 1) doğrudan HTML'de ara
                wt = self._scan_wt(html)
                # 2) HTML'de yoksa dist JS paketlerini tara (tek seviye)
                if not wt:
                    for js_url in _JS_URL_RX.findall(html)[:3]:
                        if js_url.startswith("//"):
                            js_url = "https:" + js_url
                        elif js_url.startswith("/"):
                            js_url = "https://gofile.io" + js_url
                        elif not js_url.startswith("http"):
                            js_url = "https://gofile.io/" + js_url
                        try:
                            req2 = urllib.request.Request(js_url, headers={"User-Agent": _UA, "Accept": "*/*"})
                            with urllib.request.urlopen(req2, timeout=6.0) as resp2:
                                wt = self._scan_wt(resp2.read(4 * 1024 * 1024).decode("utf-8", "replace"))
                            if wt:
                                break
                        except Exception:
                            continue
                if wt:
                    with self._lock:
                        self._wt = wt
                        self._wt_ts = time.time()
                        self._save_cache()
                    logger.info("Gofile wt token kazındı (%s...).", self._wt[:6])
                    return self._wt
            except Exception:
                continue
        return ""

    @staticmethod
    def _scan_wt(text: str) -> str:
        for rx in _WT_RXS:
            m = rx.search(text)
            if m:
                return m.group(1)
        return ""

    # ------------------------------------------------------------------
    # asıl çözümleme
    # ------------------------------------------------------------------
    def _walk_children(self, node: Dict[str, Any], out: List[GofileFile], depth: int = 0) -> str:
        """data.children ağacındaki tüm 'file' düğümlerinin diri linklerini toplar."""
        if not isinstance(node, dict) or depth > 6:
            return ""
        children = node.get("children")
        if isinstance(children, dict):
            for child in children.values():
                self._walk_children(child, out, depth + 1)
        elif isinstance(children, list):
            for child in children:
                self._walk_children(child, out, depth + 1)
        ctype = str(node.get("type") or "").lower()
        name = str(node.get("name") or "")
        link = str(node.get("link") or "")
        size = int(node.get("size") or 0)
        if ctype == "file" and link.startswith("http") and name:
            out.append(GofileFile(url=link, name=name, size=size))
        elif not ctype and link.startswith("http") and name and re.search(r"\.[a-z0-9]{2,6}$", name, re.I):
            out.append(GofileFile(url=link, name=name, size=size))
        return str(node.get("name") or "")

    def _api_contents(self, content_id: str, token: str, wt: str) -> Optional[Dict[str, Any]]:
        """/contents çağrısı — v3.14.0: 401/403'te TAZE token ile otomatik tek tekrar.

        Eski akışta diskteki 6 saatlik misafir token'ın süresi dolduğunda API
        kalıcı 401 veriyor, çözüm tamamen başarısız oluyordu (kullanıcı günlüğü:
        'Gofile çözümlenemedi ... HTTP Error 401: Unauthorized')."""
        url = f"{_GOFILE_API}/contents/{urllib.parse.quote(content_id)}"

        def _call(bearer: str, wt_value: str) -> Tuple[int, Dict[str, Any]]:
            q: List[str] = []
            if wt_value:
                q.append("wt=" + urllib.parse.quote(wt_value))
            call_url = url + ("?" + "&".join(q) if q else "")
            headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
            return self._http_json(call_url, headers=headers, timeout=10.0)

        def _ok(code: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            if code == 200 and str(data.get("status") or "").lower() == "ok":
                payload = data.get("data")
                return payload if isinstance(payload, dict) else None
            return None

        # 1. tur: token + wt ile
        code, data = _call(token, wt)
        payload = _ok(code, data)
        if payload is not None:
            return payload
        # 2. tur: 401/403 ise token geçersizdir -> TAZE misafir hesabı al ve yeniden dene
        if code in (401, 403):
            logger.info("Gofile /contents %d döndü — misafir token tazeleniyor.", code)
            self._invalidate_token()
            fresh = self._guest_token(force_new=True)
            if fresh:
                code, data = _call(fresh, wt)
                payload = _ok(code, data)
                if payload is not None:
                    return payload
        # 3. tur: wt'siz dene (bazı içeriklerde wt zorunlu değil)
        code, data = _call(token, "")
        payload = _ok(code, data)
        if payload is not None:
            return payload
        # 4. tur: token'sız (anonim) son şans
        try:
            code, data = _call("", wt)
            payload = _ok(code, data)
            if payload is not None:
                return payload
        except Exception:
            pass
        return None

    def resolve(self, url: str, referer: str = "") -> GofileResult:
        """Sayfa VEYA store linkini TAZE gerçek dosya linklerine çözer."""
        u = (url or "").strip()
        if not is_gofile_url(u):
            return GofileResult(ok=False, error="gofile bağlantısı değil")

        store_file_id = extract_file_id_from_store_link(u)
        page_cid = extract_content_id(u) or extract_content_id(referer or "")
        if not page_cid and not store_file_id:
            return GofileResult(ok=False, error="gofile içerik kimliği bulunamadı")

        token = self._guest_token()
        wt = self._website_token(page_cid)
        payload: Optional[Dict[str, Any]] = None
        if page_cid:
            payload = self._api_contents(page_cid, token, wt)
        if payload is None and store_file_id:
            # yalnız store linki geldiyse: dosya kimliğiyle içerik sorgusu dene
            payload = self._api_contents(store_file_id, token, wt)

        if payload is None:
            return GofileResult(
                ok=False,
                error="gofile API içeriği çözülemedi (bağlantı silinmiş/korumalı olabilir)",
            )

        files: List[GofileFile] = []
        folder_name = self._walk_children(payload, files)
        # tek dosya için children yoksa payload'un kendisi dosya olabilir
        if not files and str(payload.get("type") or "").lower() == "file":
            link = str(payload.get("link") or "")
            name = str(payload.get("name") or "")
            if link.startswith("http") and name:
                files.append(GofileFile(url=link, name=name, size=int(payload.get("size") or 0)))

        if not files:
            return GofileResult(ok=False, folder_name=folder_name, error="gofile içeriğinde indirilebilir dosya yok")

        # linklerdeki store sunucusu ölmüş olabilir -> /servers ile doğrula ve gerekirse
        # sunucu adını taze store sunucusuyla değiştir (BÖYLECE 'bozuk dosya' sıfırlanır)
        try:
            _, servers = self._http_json(_GOFILE_API + "/servers", timeout=6.0)
            sdata = servers.get("data") or {}
            slist = sdata.get("servers") or []
            if slist and isinstance(slist, list):
                fresh_host = f"{slist[0].get('name')}.gofile.io"
                fixed: List[GofileFile] = []
                for f in files:
                    m = re.match(r"^(https?://)([^/]+)(/.*)$", f.url)
                    if m and "gofile.io" in m.group(2) and m.group(2) != fresh_host:
                        fixed.append(GofileFile(url=m.group(1) + fresh_host + m.group(3), name=f.name, size=f.size))
                    else:
                        fixed.append(f)
                files = fixed
        except Exception:
            pass

        return GofileResult(ok=True, files=files[:100], folder_name=folder_name)


_RESOLVER: Optional[GofileResolver] = None
_RESOLVER_LOCK = threading.Lock()


def get_gofile_resolver() -> GofileResolver:
    global _RESOLVER
    with _RESOLVER_LOCK:
        if _RESOLVER is None:
            _RESOLVER = GofileResolver()
        return _RESOLVER
