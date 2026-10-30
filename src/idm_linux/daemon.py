from __future__ import annotations

import base64
import concurrent.futures
import tempfile
from collections import deque
from typing import Deque
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import threading
import uuid
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .auth_proxy import assist_begin_chunk, assist_finish, assist_pending_list, _ASSIST, _ASSIST_LOCK, AuthProxyTicket, AuthContextVault, AuthenticatedProxyManager
from .browsers import auto_install_and_open_default_browser, detect_default_browser, register_chromium_force_install_policy
from .config import COMPANION_CHROME_EXT_ID, LEGACY_IDM_WS_PORT, IdmLinuxConfig, get_cache_dir, get_data_dir, setup_logger
from .crx_builder import build_chromium_zip_package
from .distro import detect_system
from .ed2k_bridge import (
    detect_ed2k_backend,
    ed2k_add_link,
    ed2k_get_session,
    ed2k_install_backend_safe,
    ed2k_list_sessions,
    ed2k_register_native,
    ed2k_shutdown_all,
    native_ed2k_available,
    incoming_dir as ed2k_incoming_dir,
    is_ed2k_link,
    parse_ed2k_link,
)
from .gofile_resolver import (
    extract_content_id,
    get_gofile_resolver,
    is_gofile_store_link,
    is_gofile_url,
)
from .hls_streamer import looks_like_hls_url
from .i18n import I18nManager
from .protocol import (
    DownloadRequest,
    IdmWireMessage,
    build_config_update,
    build_download_decision,
    build_handshake_ack,
    build_ping_ack,
    is_domain_excluded,
)
from .browsers import open_folder_native, wine_path_to_unix
from .stream_engine import (
    is_dash_segment_url,
    probe_dash_manifest,
    fetch_mpd_full,
    mpd_has_drm,
    set_probe_done_notifier,
    StreamEngine,
    _is_known_ytdlp_site,
    is_playlist_url,
    probe_playlist_entries,
)
from .support_page import build_support_html
from .torrent_engine import TorrentBridgeManager, is_magnet_or_torrent_url, serve_torrent_over_http
from .webview_modal import build_iframe_shell_html
from .welcome_page import render_welcome_html
from .wine_sender import WineIdmSender, guess_category_subdir, sanitize_filename

logger = setup_logger("daemon", "daemon.log")

# v3.7.1: eD2K motor kurulum işinin tek örnek çalışmasını garanti eden kilit
_ED2K_INSTALL_LOCK = threading.Lock()

# v3.14.2: İÇERİK-TİPİ TORRENT KOKLAMA — filmix.gg/download/<id> gibi dinamik .torrent
# üreticilerinde URL '.torrent' ile bitmez; sunucu 'application/x-bittorrent' mime'i veya
# '*.torrent' Content-Disposition dosya adı döndürür. Bilinen büyük-dosya uzantılarında
# sorgu hiç yapılmaz (sıfır ek yük); diğerlerinde tek bir kısa HEAD isteği yeterlidir.
_KNOWN_NON_TORRENT_EXT = {
    "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "zst", "iso", "bin", "mdf", "nrg",
    "exe", "msi", "dmg", "deb", "rpm", "apk", "appimage", "pkg",
    "mp4", "mkv", "avi", "mov", "flv", "webm", "wmv", "mpg", "mpeg", "m4v", "ts",
    "mp3", "flac", "m4a", "wav", "ogg", "opus", "aac", "wma",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "epub", "mobi",
    "jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "psd",
    "ttf", "otf", "jar", "csv", "json", "xml", "vpk", "wad", "rom",
}


def _sniff_is_torrent_url(
    url: str,
    *,
    cookies: str = "",
    referer: str = "",
    user_agent: str = "",
    timeout: float = 3.0,
) -> bool:
    """URL '.torrent' ile bitmese bile sunucunun döndürdüğü içerik-tipine bakar.

    Yalnızca NET torrent işaretlerinde True döner; HEAD desteklenmiyorsa/hata varsa
    False döner (normal indirme akışı aynen sürer — asla yavaşlatmaz)."""
    try:
        low = url.lower()
        if "127.0.0.1" in low or "//localhost" in low:
            return False
        path = urllib.parse.urlparse(url).path.lower()
        last_seg = path.rsplit("/", 1)[-1]
        ext = last_seg.rsplit(".", 1)[-1] if "." in last_seg else ""
        if ext and ext in _KNOWN_NON_TORRENT_EXT:
            return False
        headers = {"User-Agent": user_agent or "Mozilla/5.0 (X11; Linux x86_64)", "Accept": "*/*"}
        if cookies:
            headers["Cookie"] = cookies
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            disp = (resp.headers.get("Content-Disposition") or "").lower()
        if ctype == "application/x-bittorrent":
            return True
        if ".torrent" in disp:
            return True
        return False
    except Exception:
        return False


def _categorized_final_dir(filename: str, base_dir: Path) -> Path:
    """v3.7.0: dosya adına göre IDM kategori klasörünü döndürür ve oluşturur.
    IDM'in Windows'taki davranışı birebir: Video -> Downloads/Video, müzik ->
    Downloads/Music, arşivler -> Downloads/Compressed ... Motor (yt-dlp/HLS)
    doğrudan bu klasöre yazar; Downloads köküne artık karışık dosya düşmez."""
    try:
        return guess_category_subdir(filename or "", Path(base_dir).expanduser())
    except Exception:
        try:
            p = Path(base_dir).expanduser()
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            return Path(base_dir).expanduser()

# v3.4.0: daemon tarafı i18n — köprü/bar notları kullanıcının GUI dilinde üretilir.
_DAEMON_I18N: Optional[I18nManager] = None
_DAEMON_I18N_LOCK = threading.Lock()


def _daemon_i18n(lang: str = "") -> I18nManager:
    global _DAEMON_I18N
    with _DAEMON_I18N_LOCK:
        if _DAEMON_I18N is None:
            _DAEMON_I18N = I18nManager(initial_lang=lang or None)
        elif lang and _DAEMON_I18N.lang != lang:
            _DAEMON_I18N.set_language(lang)
        return _DAEMON_I18N

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class DaemonState:
    def __init__(self) -> None:
        self.cfg = IdmLinuxConfig.load()
        # v3.4.0: motor/bar etiketleri kullanıcının GUI dilini izler (global i18n eşzamanlama)
        try:
            from .i18n import get_i18n as _get_i18n

            _get_i18n(self.cfg.language)
        except Exception:
            pass
        self.sender = WineIdmSender(self.cfg)
        self.stream_engine = StreamEngine(self.cfg)
        self.auth_vault = AuthContextVault()
        self.diag: Deque[str] = deque(maxlen=400)  # v2.9.1 uzak-log halkası
        self.ext_disabled = False  # v2.9.3: eklenti pasifse IDM HİÇ devreye girmez
        self.auth_proxy = AuthenticatedProxyManager(self.auth_vault)
        self.torrent_bridge = TorrentBridgeManager()
        # v3.9.0: canlı tracker listesini AÇILIŞTA arka planda ön-ısıt — ilk torrent
        # tıklamasında ağ gecikmesi yaşanmasın (0 B/s karşıtı önlem)
        try:
            from .torrent_engine import fetch_fresh_trackers as _fft

            threading.Thread(target=_fft, name="tracker-prewarm", daemon=True).start()
        except Exception:
            pass
        # v3.5.0: Oynatma Listesi seri indirme motoru (GUI kartının arkası)
        from .playlist_batch import PlaylistBatchManager

        self.playlist_manager = PlaylistBatchManager()
        self.started_at = time.time()
        self.downloads_dispatched = 0
        self.last_official_ext_ping = 0.0
        self.active_ws_ports: List[int] = []
        self.recent_urls: Dict[str, float] = {}
        # v3.2.2 DÜZELTME: v3.2.1'de hiç başlatılmamıştı -> dispatch'te AttributeError
        # (sessiz yakalama hataları). Artık düzgün liste; _strict_memory_purge kırpıyor.
        self.recent_dispatches: List[Tuple[float, str]] = []
        self.welcome_token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.running = True
        # v3.8.0: eD2K TAM OTOMATİK — motor yoksa kurulum kendiliğinden başlar,
        # bağlantı beklemeye alınır ve kurulum bitince DAEMON kendisi yeniden gönderir.
        self.ed2k_install_started = False
        self.ed2k_install_result: Optional[Dict[str, Any]] = None
        self.ed2k_pending_link: str = ""
        self.ed2k_pending_src: str = ""

        # Başlangıçta mevcut Wine IDM kurulumundaki eski .disabled / eksik hook dosyalarını sessizce onar
        try:
            idm_exe = self.cfg.find_idm_exe()
            if idm_exe is not None:
                self.sender._ensure_idm_dir_healed(idm_exe.parent)
        except Exception as exc:
            logger.debug("Başlangıç IDM dizin onarım kontrolü: %s", exc)

        # v3.4.0 SİYAH PENCERE DÜZELTMESİ: Wine koyu tema bayrağı her başlangıçta AÇIK
        # temaya döndürülür (arka planda — arayüz/servis açılışını asla bekletmez)
        threading.Thread(target=self._heal_light_theme, name="lighttheme-heal", daemon=True).start()

    def _heal_light_theme(self) -> None:
        try:
            from .installer import ensure_idm_light_theme_registry

            if self.cfg.find_idm_exe() is not None:
                ensure_idm_light_theme_registry(self.cfg)
        except Exception as exc:
            logger.debug("Açık tema (siyah pencere) düzeltmesi atlandı: %s", exc)

    # v3.8.0: eD2K TAM OTOMATİK kurulum işi — motoru kurar, çekirdeği başlatır ve
    # bekleyen bağlantıyı OTOMATİK motora iletir. pkexec yetki penceresi kullanıcı
    # onayıdır; elle kurulum komutu kullanıcıya ASLA gösterilmez.
    def _ed2k_auto_install_job(self) -> None:
        try:
            ok_i, msg_i = ed2k_install_backend_safe()
        except Exception as exc:
            ok_i, msg_i = False, f"Kurulum sırasında beklenmeyen hata: {exc}"
        logger.info("eD2K motor kurulumu tamamlandı: ok=%s (%s)", ok_i, msg_i[:160])
        pending_link = ""
        pending_src = ""
        with _ED2K_INSTALL_LOCK:
            self.ed2k_install_result = {"ok": ok_i, "message": msg_i, "ts": time.time()}
            pending_link = self.ed2k_pending_link
            pending_src = self.ed2k_pending_src
            self.ed2k_pending_link = ""
            self.ed2k_pending_src = ""
        if ok_i and pending_link.lower().startswith("ed2k://"):
            try:
                ok_e, msg_e, backend_e = ed2k_add_link(pending_link)
                logger.info("eD2K bekleyen bağlantı otomatik iletildi: ok=%s backend=%s (%s)", ok_e, backend_e, msg_e[:120])
            except Exception as exc:
                logger.warning("eD2K bekleyen bağlantı iletilemedi: %s", exc)

    def reload_config(self) -> None:
        with self.lock:
            self.cfg = IdmLinuxConfig.load()
            self.sender.cfg = self.cfg
            self.stream_engine.cfg = self.cfg
            # v3.4.0: canlı dil eşzamanlama — GUI'den dil değişince bar notları da yeni dilde
            try:
                from .i18n import get_i18n as _get_i18n

                _get_i18n(self.cfg.language)
            except Exception:
                pass

    def is_duplicate_burst(self, url: str, window_sec: float = 2.0) -> bool:
        """Hem resmi eklenti hem hibrit eklenti aynı tıklamayı yakalarsa çift pencere açılmasını önler."""
        now = time.time()
        with self.lock:
            expired = [u for u, ts in self.recent_urls.items() if now - ts > 15.0]
            for u in expired:
                self.recent_urls.pop(u, None)
            last_ts = self.recent_urls.get(url)
            if last_ts is not None and (now - last_ts) < window_sec:
                return True
            self.recent_urls[url] = now
            return False

    def dispatch_torrent_or_magnet(
        self,
        *,
        magnet_uri: str = "",
        torrent_url: str = "",
        local_path: str = "",
        raw_bytes: Optional[bytes] = None,
        cookies: str = "",
        referer: str = "",
        user_agent: str = "",
        silent: Optional[bool] = None,
        source: str = "torrent-bridge",
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            if raw_bytes is not None:
                sess = self.torrent_bridge.register_torrent_bytes(raw_bytes)
            elif local_path:
                lp = Path(local_path).expanduser().resolve()
                if not lp.is_file():
                    return False, f".torrent dosyası bulunamadı: {local_path}", None
                sess = self.torrent_bridge.register_torrent_bytes(lp.read_bytes())
            elif magnet_uri:
                sess = self.torrent_bridge.register_magnet(magnet_uri)
            elif torrent_url:
                hdrs: Dict[str, str] = {}
                if cookies:
                    hdrs["Cookie"] = cookies
                if referer:
                    hdrs["Referer"] = referer
                if user_agent:
                    hdrs["User-Agent"] = user_agent
                sess = self.torrent_bridge.register_torrent_url(torrent_url, headers=hdrs)
            else:
                return False, "Torrent veya Magnet kaynağı belirtilmedi.", None
        except Exception as exc:
            logger.error("Torrent/Magnet kayıt hatası: %s", exc)
            return False, f"Torrent ayrıştırılamadı: {exc}", None

        # v3.7.0 SENKRON HAZIRLIK KAPISI: kayıt arka planda motoru başlatır; burada
        # hazır olmasını NETLEŞTİRİP bekliyoruz (en fazla 15 sn). Motor gerçekten
        # çalışmadan (veya hatayı netleştirmeden) IDM'ye KÖPRÜ ADRESİ GİTMEZ —
        # IDM'nin yarım motora bağlanıp 'aria2c RPC servisi başlatılamadı' 503
        # sayfası görmesi kökten engellenir.
        try:
            sess.ensure_started()
        except Exception:
            pass
        if not sess.ready.wait(timeout=15.0):
            # v3.7.1: aria2c otomatik kurulumu (pkexec onayı / statik ikili indirmesi)
            # uzun sürebilir — hata YOKSA bekleme penceresini 180 sn'ye genişlet.
            # Böylece 'Torrent motoru zamanında hazır olmadı' sahte hatası yaşanmaz.
            extended_deadline = time.time() + 180.0
            while not sess.ready.wait(timeout=2.0):
                if sess.error_message:
                    break
                if time.time() >= extended_deadline:
                    break
                logger.info("Torrent motoru hâlâ hazırlanıyor (otomatik kurulum/DHT)...")
        if not sess.ready.is_set():
            logger.error("Torrent motoru zaman aşımında hazır olmadı (ticket=%s)", sess.ticket_id)
            return False, "Torrent motoru zamanında hazır olmadı — lütfen tekrar deneyin.", None
        if sess.error_message and not sess.meta.web_seeds:
            return False, sess.error_message, None
        if not sess.rpc_port and not sess.meta.web_seeds:
            return False, (
                "BitTorrent motoru (aria2c) kullanılamıyor. Kontrol Paneli -> "
                "'Eksik Araçları Kur' ile kurun veya 'sudo pacman -S aria2' / "
                "'sudo apt install aria2' komutunu çalıştırın."
            ), None

        # v3.10.1 KÖK NEDEN (kullanıcı: "torrent inmiyor, boyutu bile göstermedi"):
        # Magnet bağlantısında meta veri (dosya adı + BOYUT) DHT/tracker'dan henüz
        # gelmemişken IDM'ye adres veriliyordu; IDM boyutu 0 görüp indirmeyi
        # başlatamıyordu. Artık meta veri gelene kadar (en fazla 25 sn) beklenir;
        # IDM'ye GERÇEK dosya adı ve GERÇEK boyutla gidilir.
        if sess.meta.total_size <= 0:
            meta_deadline = time.time() + 25.0
            while time.time() < meta_deadline and not sess.meta.total_size:
                if sess.error_message:
                    break
                try:
                    st_wait = sess.query_status() or {}
                    if int(st_wait.get("totalLength") or 0) > 0:
                        break
                except Exception:
                    pass
                time.sleep(0.25)
            if sess.meta.total_size:
                logger.info(
                    "Torrent meta verisi hazır: %s (%s bayt) — IDM'ye boyutla iletiliyor",
                    sess.meta.name, sess.meta.total_size,
                )
            else:
                logger.warning(
                    "Torrent meta verisi 25 sn içinde gelmedi (magnet) — indirme yine de IDM'ye aktarılır"
                )

        out_fn = sanitize_filename(sess.meta.output_filename)
        quoted_fn = urllib.parse.quote(out_fn)
        bridge_url = f"http://127.0.0.1:{self.cfg.http_port}/torrent/{sess.ticket_id}/{quoted_fn}"
        dl_req = DownloadRequest(
            url=bridge_url,
            filename=out_fn,
            silent=silent,
            source=source,
            # IDM'nin "Kaynak/Referer" alanında GERÇEK torrent/magnet bağlantısı
            # görünür (kullanıcı isteği: "localhost linki değil gerçek link").
            referer=(magnet_uri or torrent_url or "")[:2000],
        )
        ok, msg = self.sender.send_download(dl_req)
        if ok:
            with self.lock:
                self.downloads_dispatched += 1
        info = {
            "ticket": sess.ticket_id,
            "filename": out_fn,
            "name": sess.meta.name,
            "total_size": sess.meta.total_size,
            "is_multi_file": sess.meta.is_multi_file,
            "bridge_url": bridge_url,
        }
        return ok, msg, info

    _JB_RE = re.compile(r"^https?://(?:[a-z0-9-]+\.)?justbeamit\.com/([a-z0-9]{3,12})/?$", re.I)

    def _justbeamit_direct(self, url: str) -> str:
        """v2.9.4: justbeamit.com/<kod> -> gerçek indirme ucu (P2P blob yedeği durur)."""
        m = self._JB_RE.match(url or "")
        if m:
            return f"https://eu.justbeamit.com:8443/download?token={m.group(1)}"
        return url

    # ------------------------------------------------------------------
    # v3.13.0: GOFILE DOĞRU-YAKALAMA AKIŞI
    # Kullanıcı kuralı: "idm en doğru şekilde yakalasın ve en doğru şekilde
    # indirsin, asla bozuk dosya olmasın."
    # ------------------------------------------------------------------
    @staticmethod
    def _gofile_direct_ok(store_url: str, expected_size: int, user_agent: str, account_token: str = "") -> bool:
        """Taze store linkini 1 baytlık yoklamayla doğrular (HTML/ölü link ENGELLENİR).

        Dönüş True ise IDM linki DOĞRUDAN, çok bağlantılı (tam IDM hızı) indirir.
        False ise güvenli /proxy/ köprüsüne düşer — bozuk dosya ihtimali sıfırlanır.
        v3.13.0: yoklama 6 sn bütçeli iş parçacığında çalışır (DNS takılması asla
        dispatch'i bloklamaz; şüphede köprüye düşülür).
        v3.14.0: gofile artık store indirmelerinde misafir hesap cookie'si istiyor;
        yoksa 401 dünüyor ve iyi link bile köprüye düşüyordu. Cookie ile yoklama
        web uygulamasının davranışının birebir aynısıdır.
        """
        box: Dict[str, bool] = {}

        def _probe_job() -> None:
            hdrs = {
                "User-Agent": user_agent or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/134.0.0.0 Safari/537.36",
                "Range": "bytes=0-0",
                "Accept": "*/*",
            }
            if account_token:
                hdrs["Cookie"] = f"accountToken={account_token}"
            probe = urllib.request.Request(store_url, method="GET", headers=hdrs)
            try:
                with urllib.request.urlopen(probe, timeout=5.0) as resp:
                    code = resp.getcode() or 0
                    ct = (resp.headers.get("Content-Type") or "").lower()
                    cr = resp.headers.get("Content-Range") or ""
                    total = 0
                    if "/" in cr:
                        try:
                            total = int(cr.rsplit("/", 1)[-1])
                        except ValueError:
                            total = 0
                    if code not in (200, 206):
                        box["ok"] = False
                        return
                    if "text/html" in ct or "application/json" in ct or "text/plain" in ct:
                        box["ok"] = False  # hata sayfası → asla IDM'ye verme
                        return
                    if expected_size and total and total != expected_size:
                        box["ok"] = False  # boyut uyuşmadı → eski/yanlış dosya
                        return
                    box["ok"] = True
            except Exception:
                box["ok"] = False

        _pt = threading.Thread(target=_probe_job, name="gofile-probe", daemon=True)
        _pt.start()
        _pt.join(timeout=6.0)
        return bool(box.get("ok"))

    def dispatch_gofile(
        self,
        url: str,
        referer: str = "",
        cookies: str = "",
        user_agent: str = "",
        silent: Optional[bool] = None,
        source: str = "gofile",
    ) -> Tuple[bool, str]:
        """Gofile sayfa/store bağlantısını TAZE gerçek dosya linklerine çözer ve IDM'ye verir.

        - Sayfa linki (gofile.io/d/<id>): API'den tüm çocuk dosyalar çözülür (klasör desteği).
        - Store linki: referer'daki içerik kimliğinden YENİDEN taze link üretilir
          (yakalanan eski link süresi dolmuş olsa bile indirme BOZULMAZ).
        - Her dosya 1 baytlık yoklamayla doğrulanır: doğrudan IDM hızı, şüphede köprü.
        """
        if not is_gofile_url(url):
            return False, "gofile bağlantısı değil"
        # v3.14.0: token/wt ARKA PLANDA ön-ısıtılır (dispatch bütçesini harcamaz);
        # ilk çağrı hazır değilse çözümleme yine de kendi içinde taze token alır.
        try:
            get_gofile_resolver().prewarm()
        except Exception:
            pass
        # v3.13.0: ÇÖZÜMLEME BÜTÇESİ (12 sn) — DNS/ağ takılırsa /api/download bloklanmaz;
        # süre aşılırsa eski (kanıtlanmış /proxy/) akışa düşülür, kullanıcı asla bekletilmez.
        go_res: Dict[str, Any] = {}

        def _resolve_job() -> None:
            try:
                go_res["res"] = get_gofile_resolver().resolve(url, referer=referer or "")
            except Exception as exc:  # savunma: çözücü hatası = çözülemedi
                from .gofile_resolver import GofileResult

                go_res["res"] = GofileResult(ok=False, error=str(exc))

        _rt = threading.Thread(target=_resolve_job, name="gofile-resolve", daemon=True)
        _rt.start()
        _rt.join(timeout=12.0)
        if _rt.is_alive() or "res" not in go_res:
            logger.warning("Gofile çözümleme bütçesi aşıldı (%s) — köprü akışına düşülüyor.", url[:90])
            return False, "Gofile çözümleme zaman aşımı"
        res = go_res["res"]
        if not res.ok or not res.files:
            logger.warning("Gofile çözümlenemedi (%s): %s", url[:90], res.error)
            return False, (res.error or "Gofile içeriği çözülemedi")

        page_ref = referer or (url if extract_content_id(url) else "")
        multi = len(res.files) > 1
        # v3.14.0: gofile store indirmeleri misafir hesap cookie'si ister (401 duvarı)
        try:
            gofile_token = get_gofile_resolver().account_token()
        except Exception:
            gofile_token = ""
        sent = 0
        last_msg = ""
        for gf in res.files:
            clean_name = sanitize_filename(gf.name)
            use_direct = self._gofile_direct_ok(gf.url, gf.size, user_agent, account_token=gofile_token)
            if use_direct:
                dl_req = DownloadRequest(
                    url=gf.url,
                    referer=page_ref,
                    cookies=(f"accountToken={gofile_token}" if gofile_token else ""),
                    user_agent=user_agent,
                    filename=clean_name,
                    silent=(True if (silent is None and multi) else silent),
                    source=f"{source}-direct",
                )
            else:
                extra = {"Cookie": f"accountToken={gofile_token}"} if gofile_token else {}
                wrapped = self.auth_proxy.maybe_wrap_authenticated_download(
                    DownloadRequest(
                        url=gf.url,
                        referer=page_ref,
                        cookies=cookies,
                        user_agent=user_agent,
                        filename=clean_name,
                        source=f"{source}-proxy",
                        extra_headers=extra,
                    ),
                    self.cfg.http_port,
                )
                dl_req = DownloadRequest(
                    url=wrapped.url,
                    filename=wrapped.filename or clean_name,
                    save_dir=wrapped.save_dir,
                    silent=(True if (silent is None and multi) else silent),
                    source=source,
                )
            ok, msg = self.sender.send_download(dl_req)
            last_msg = msg
            if ok:
                sent += 1
                with self.lock:
                    self.downloads_dispatched += 1
        if sent:
            if multi:
                return True, f"Gofile: {sent}/{len(res.files)} dosya IDM'ye taze linkle iletildi."
            return True, "Gofile dosyası IDM'ye taze gerçek linkle iletildi."
        return False, (last_msg or "Gofile dosyaları IDM'ye iletilemedi.")

    def dispatch_download(
        self, req: DownloadRequest, dedup: bool = True, hls_mode: str = "vod"
    ) -> Tuple[bool, str]:
        self.diag.append(f"DISPATCH {req.source} {req.url[:140]}")
        if self.ext_disabled and req.source in (
            "browser", "official-ext", "companion-ext", "clipboard", "gofile-capture", "video-bar",
        ):
            return False, "Eklenti pasif modda — indirme tarayıcının kendisinde."
        if dedup and self.is_duplicate_burst(req.url, window_sec=2.5):
            logger.info("Çift yakalama koruması: %s zaten az önce IDM'ye gönderildi.", req.url[:80])
            return True, "Zaten IDM'ye iletildi (çift pencere engellendi)."

        # v2.8.0: YouTube / Dailymotion / Twitch vb. ana akım siteler veya oynatma listesi
        # URL'leri HAM halde IDM'ye GİDEMEZ -> otomatik video/stream motoru bileti açılır.
        if (
            not req.url.strip().lower().startswith("magnet:?")
            and not req.url.strip().lower().endswith(".torrent")
            and (
                _is_known_ytdlp_site(req.url)
                or is_playlist_url(req.url)
                or looks_like_hls_url(req.url)
                or ".mpd" in req.url.lower()
                or is_dash_segment_url(req.url)
            )
            and "/stream/" not in req.url
        ):
            title = req.filename or urllib.parse.unquote(
                urllib.parse.urlparse(req.url).path.rsplit("/", 1)[-1] or "video"
            )
            title = Path(title).stem or "video"
            is_hls_src = looks_like_hls_url(req.url) or ".mpd" in req.url.lower()
            is_seg = is_dash_segment_url(req.url)
            # v2.8.8: D-Smart GO VOD segmentine tiklandiysa önce MPD manifestini kesfet
            seg_manifest = ""
            if is_seg:
                try:
                    seg_manifest = probe_dash_manifest(
                        req.url,
                        {"Referer": req.referer, "User-Agent": req.user_agent},
                        timeout=3.0,
                    )
                except Exception:
                    seg_manifest = ""
            if is_seg and seg_manifest:
                # v2.9.2: DRM'li içerikte BİLET AÇMA — 0 bayt yerine NET mesaj
                _mpd_head = fetch_mpd_full(seg_manifest, {"Referer": req.referer, "User-Agent": req.user_agent}, limit=65536)
                if mpd_has_drm(_mpd_head):
                    logger.info("DRM korumalı DASH içeriği reddedildi (Widevine/PlayReady): %s", req.url[:90])
                    return True, (
                        "🔒 Bu içerik Widevine/PlayReady DRM ile korumalıdır. "
                        "DRM şifreli yayınlar yasal ve teknik olarak indirilemez (Windows IDM dahil hiçbir araç indiremez). "
                        "DRM'siz DASH/HLS içerikler tam desteklenir."
                    )
                title0 = req.filename or urllib.parse.unquote(
                    urllib.parse.urlparse(req.url).path.rsplit("/", 1)[-1] or "video"
                )
                title0 = Path(title0).stem or "video"
                ticket0 = self.stream_engine.create_ticket(
                    source_url=seg_manifest,
                    filename=f"{title0}.mp4",
                    mode="ytdlp",
                    cookies_header=req.cookies,
                    referer=req.referer,
                    user_agent=req.user_agent,
                    final_dir=_categorized_final_dir(f"{title0}.mp4", Path(self.cfg.download_dir)),
                )
                quoted0 = urllib.parse.quote(ticket0.filename)
                stream_url0 = f"http://127.0.0.1:{self.cfg.http_port}/stream/{ticket0.ticket_id}/{quoted0}"
                ok0, msg0 = self.sender.send_download(
                    DownloadRequest(url=stream_url0, filename=ticket0.filename, silent=req.silent, source="auto-video-mpd")
                )
                if ok0:
                    with self.lock:
                        self.recent_dispatches.append((time.time(), req.url))
                    return True, msg0
            if is_hls_src and hls_mode == "vod" and not is_seg:
                # v2.8.3: VOD film listesine ASLA sebepsiz DVR/canlı deme — manifest'i sınıflandır
                hls_mode = _auto_hls_mode(req.url, "", req.referer, req.user_agent)
            ticket = self.stream_engine.create_ticket(
                source_url=req.url,
                filename=f"{title}.mp4",
                segment_urls=([req.url] if is_seg else []),
                mode=("hls_native" if (is_hls_src or is_seg) else "ytdlp"),
                cookies_header=req.cookies,
                referer=req.referer,
                user_agent=req.user_agent,
                hls_mode=(hls_mode if hls_mode != "vod" or is_hls_src else "vod"),
                is_hls=is_hls_src,
                final_dir=_categorized_final_dir(f"{title}.mp4", Path(self.cfg.download_dir)),
            )
            quoted_fn = urllib.parse.quote(ticket.filename)
            stream_url = f"http://127.0.0.1:{self.cfg.http_port}/stream/{ticket.ticket_id}/{quoted_fn}"
            wrapped = DownloadRequest(url=stream_url, filename=ticket.filename, silent=req.silent, source="auto-video")
            ok_v, msg_v = self.sender.send_download(wrapped)
            if ok_v:
                with self.lock:
                    self.downloads_dispatched += 1
            return ok_v, msg_v

        if is_magnet_or_torrent_url(req.url):
            if req.url.strip().lower().startswith("magnet:?"):
                ok_t, msg_t, _ = self.dispatch_torrent_or_magnet(
                    magnet_uri=req.url.strip(),
                    silent=req.silent,
                    source=f"{req.source}-magnet",
                )
            else:
                # Tarayıcı çerezleri ile .torrent dosyasını çekip içindeki hedefi IDM'ye bağla
                wrapped = self.auth_proxy.maybe_wrap_authenticated_download(req, self.cfg.http_port)
                ok_t, msg_t, _ = self.dispatch_torrent_or_magnet(
                    torrent_url=wrapped.url,
                    cookies=req.cookies,
                    referer=req.referer,
                    user_agent=req.user_agent,
                    silent=req.silent,
                    source=f"{req.source}-torrent",
                )
            return ok_t, msg_t

        # v3.7.0: eD2K bağlantıları IDM'ye HAM GİDEMEZ — doğrudan eMule motoruna köprülenir
        if req.url.strip().lower().startswith("ed2k://"):
            ok_e, msg_e, _backend_e = ed2k_add_link(req.url.strip())
            return ok_e, msg_e

        # v3.13.0: GOFILE — IDM'ye ASLA ham gofile linki gitmez.
        #  a) Sayfa linki (gofile.io/d/<id>): HTML sayfa iner -> API'den taze dosya linkleri.
        #  b) Store linki: yakalanan link ESKİ olabileceğinden referer'daki içeriden
        #     taze link üretilir; çözülemezse eski (proxy köprüsü) akışı korur.
        if is_gofile_url(req.url) and "/proxy/" not in req.url and "/stream/" not in req.url:
            ok_g, msg_g = self.dispatch_gofile(
                req.url,
                referer=req.referer or req.origin or "",
                cookies=req.cookies,
                user_agent=req.user_agent,
                silent=req.silent,
                source=req.source or "gofile",
            )
            if ok_g:
                return ok_g, msg_g
            logger.info("Gofile taze-çözüm başarısız, eski köprü akışına düşülüyor: %s", msg_g[:120])

        # v3.14.2: İÇERİK-TİPİ TORRENT KOKLAMA — URL '.torrent' ile bitmese bile sunucu
        # 'application/x-bittorrent' döndürüyorsa (filmix.gg/download/<id> gibi) indirme
        # DOSYA olarak değil torrent motoruyla başlar. HEAD 3 sn'yi aşarsa/hata olursa
        # normal akışa devam — hız kaybı yok, yanlış pozitif yok.
        if (
            not req.url.strip().lower().startswith("magnet:")
            and "127.0.0.1" not in req.url
            and "/proxy/" not in req.url
            and "/stream/" not in req.url
            and _sniff_is_torrent_url(
                req.url,
                cookies=req.cookies,
                referer=req.referer or req.origin or "",
                user_agent=req.user_agent,
            )
        ):
            wrapped_t = self.auth_proxy.maybe_wrap_authenticated_download(req, self.cfg.http_port)
            ok_t, msg_t, _ = self.dispatch_torrent_or_magnet(
                torrent_url=wrapped_t.url,
                cookies=req.cookies,
                referer=req.referer,
                user_agent=req.user_agent,
                silent=req.silent,
                source=f"{req.source}-torrent-sniff",
            )
            return ok_t, msg_t

        final_req = self.auth_proxy.maybe_wrap_authenticated_download(req, self.cfg.http_port)
        ok, msg = self.sender.send_download(final_req)
        if ok:
            with self.lock:
                self.downloads_dispatched += 1
        return ok, msg

    def handle_idm_wire_frame(self, raw_msg: str, via: str = "ws") -> List[str]:
        """Resmi IDM eklentisinden gelen MSG# tel protokol çerçevesini işler ve yanıt listesi üretir."""
        parsed = IdmWireMessage.parse(raw_msg)
        if not parsed:
            return []

        self.last_official_ext_ping = time.time()
        cfg = self.cfg

        if parsed.msg_type == 2:
            dpi = cfg.dpi_scale if cfg.dpi_scale > 0 else 96
            ack = build_handshake_ack(parsed.seq, dpi=dpi)
            conf = build_config_update(
                parsed.seq + 1,
                cfg.extension_regex(),
                enabled=cfg.capture_downloads,
            )
            logger.info("Resmi IDM eklentisi bağlandı (%s) -> Handshake tamamlandı.", via)
            return [ack, conf]

        if parsed.msg_type == 0:
            return [build_ping_ack(parsed.seq)]

        if parsed.msg_type == 13:
            dl_id = parsed.positional_args[0] if parsed.positional_args else "0"
            req = parsed.to_download_request(source=f"official-{via}")
            if not req or not cfg.capture_downloads or is_domain_excluded(req.url, req.referer, cfg.excluded_domains):
                return [build_download_decision(parsed.seq, dl_id, takeover=False)]

            threading.Thread(target=self.dispatch_download, args=(req, True), daemon=True).start()
            return [build_download_decision(parsed.seq, dl_id, takeover=True)]

        if parsed.msg_type == 14:
            req = parsed.to_download_request(source=f"official-menu-{via}")
            if req:
                threading.Thread(target=self.dispatch_download, args=(req, False), daemon=True).start()
            return [build_ping_ack(parsed.seq)]

        return [build_ping_ack(parsed.seq)]


# ---------------------------------------------------------------------------
# Saf Python RFC 6455 WebSocket Sunucusu (Birincil: 17801 + İsteğe Bağlı: 1001)
# ---------------------------------------------------------------------------

def _auto_hls_mode(url: str, manifest_text: str, referer: str = "", user_agent: str = "") -> str:
    """v2.8.3: manifest CANLI ise dvr/live, VOD ise vod döndürür (sebepsiz DVR yok!)."""
    from .stream_engine import classify_manifest_live

    txt = manifest_text or ""
    if not txt:
        try:
            rq = urllib.request.Request(
                url,
                headers={"User-Agent": user_agent or "IDM-Linux/2.8", "Referer": referer or ""},
            )
            with urllib.request.urlopen(rq, timeout=6) as rr:
                txt = rr.read(400000).decode("utf-8", "ignore")
        except Exception:
            return "dvr"
    cl = classify_manifest_live(txt)
    if cl["live"]:
        return "dvr" if cl["dvr"] else "live"
    return "vod"


def _ws_recv_frame(conn: socket.socket) -> Optional[Tuple[int, bytes]]:
    hdr = _recv_exact(conn, 2)
    if not hdr:
        return None
    b1, b2 = hdr[0], hdr[1]
    opcode = b1 & 0x0F
    masked = (b2 & 0x80) != 0
    length = b2 & 0x7F

    if length == 126:
        ext = _recv_exact(conn, 2)
        if not ext:
            return None
        length = struct.unpack("!H", ext)[0]
    elif length == 127:
        ext = _recv_exact(conn, 8)
        if not ext:
            return None
        length = struct.unpack("!Q", ext)[0]

    if length > 16 * 1024 * 1024:
        return None

    mask_key = _recv_exact(conn, 4) if masked else b""
    payload = _recv_exact(conn, length) if length > 0 else b""
    if payload is None:
        return None

    if masked and mask_key:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def _ws_send_frame(conn: socket.socket, payload: bytes, opcode: int = 0x1) -> None:
    header = bytearray([0x80 | (opcode & 0x0F)])
    n = len(payload)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header.extend(struct.pack("!H", n))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", n))
    conn.sendall(bytes(header) + payload)


def _recv_exact(conn: socket.socket, size: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < size:
        chunk = conn.recv(size - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


_WS_CLIENT_CONNS: set = set()
_WS_CLIENT_LOCK = threading.Lock()


def _ws_broadcast(payload: Dict[str, Any]) -> int:
    """v2.8.6: bağlı companion uzantılarına JSON çerçeve yayınlar (onay istekleri vb.)."""
    data = json.dumps(payload).encode("utf-8")
    sent = 0
    with _WS_CLIENT_LOCK:
        conns = list(_WS_CLIENT_CONNS)
    for cn in conns:
        try:
            _ws_send_frame(cn, data)
            sent += 1
        except Exception:
            with _WS_CLIENT_LOCK:
                _WS_CLIENT_CONNS.discard(cn)
    return sent


def _handle_ws_client(conn: socket.socket, state: DaemonState) -> None:
    with _WS_CLIENT_LOCK:
        _WS_CLIENT_CONNS.add(conn)
    try:
        return _handle_ws_client_inner(conn, state)
    finally:
        with _WS_CLIENT_LOCK:
            _WS_CLIENT_CONNS.discard(conn)


def _handle_ws_client_inner(conn: socket.socket, state: DaemonState) -> None:
    conn.settimeout(120)
    try:
        raw_req = b""
        while b"\r\n\r\n" not in raw_req and len(raw_req) < 16384:
            chunk = conn.recv(4096)
            if not chunk:
                return
            raw_req += chunk

        header_text = raw_req.decode("latin1", errors="ignore")
        headers: Dict[str, str] = {}
        for line in header_text.split("\r\n")[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        ws_key = headers.get("sec-websocket-key")
        if not ws_key:
            return

        accept_val = base64.b64encode(
            hashlib.sha1((ws_key + WS_GUID).encode("ascii")).digest()
        ).decode("ascii")

        subproto = headers.get("sec-websocket-protocol", "")
        chosen_proto = ""
        if "plugin.v3.internetdownloadmanager.com" in subproto:
            chosen_proto = "plugin.v3.internetdownloadmanager.com"
        elif subproto:
            chosen_proto = subproto.split(",")[0].strip()

        resp_lines = [
            "HTTP/1.1 101 Switching Protocols",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Accept: {accept_val}",
        ]
        if chosen_proto:
            resp_lines.append(f"Sec-WebSocket-Protocol: {chosen_proto}")
        resp_lines.append("")
        resp_lines.append("")
        conn.sendall("\r\n".join(resp_lines).encode("ascii"))

        while state.running:
            frame = _ws_recv_frame(conn)
            if frame is None:
                break
            opcode, payload = frame
            if opcode == 0x8:
                break
            if opcode == 0x9:
                _ws_send_frame(conn, payload, opcode=0xA)
                continue
            if opcode in (0x1, 0x2):
                msg_str = payload.decode("utf-8", errors="ignore")
                replies = state.handle_idm_wire_frame(msg_str, via="ws")
                for rep in replies:
                    _ws_send_frame(conn, rep.encode("utf-8"), opcode=0x1)
    except (OSError, socket.timeout):
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _bind_ws_listener(port: int, state: DaemonState, quiet_permission_error: bool = False) -> Optional[socket.socket]:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("127.0.0.1", port))
        srv.listen(16)
    except PermissionError:
        srv.close()
        if not quiet_permission_error:
            logger.warning("WebSocket portu (127.0.0.1:%s) yetki hatası verdi.", port)
        return None
    except OSError as exc:
        srv.close()
        if not quiet_permission_error:
            logger.warning("WebSocket portu (127.0.0.1:%s) bağlanamadı: %s", port, exc)
        return None

    def _accept_loop() -> None:
        while state.running:
            try:
                client, _ = srv.accept()
                threading.Thread(
                    target=_handle_ws_client,
                    args=(client, state),
                    daemon=True,
                ).start()
            except OSError:
                break

    threading.Thread(target=_accept_loop, name=f"idm-ws-{port}", daemon=True).start()
    state.active_ws_ports.append(port)
    logger.info("IDM WebSocket sunucusu aktif: ws://127.0.0.1:%s", port)
    return srv


def start_websocket_servers(state: DaemonState) -> List[socket.socket]:
    socks: List[socket.socket] = []
    primary = _bind_ws_listener(state.cfg.ws_port, state, quiet_permission_error=False)
    if primary:
        socks.append(primary)

    if state.cfg.ws_port != LEGACY_IDM_WS_PORT:
        legacy = _bind_ws_listener(LEGACY_IDM_WS_PORT, state, quiet_permission_error=True)
        if legacy:
            socks.append(legacy)
    return socks


# ---------------------------------------------------------------------------
# Port 17802: Hibrit Eklenti RPC API + Canlı HLS/DASH/YouTube Stream Sunucusu
# ---------------------------------------------------------------------------

def _is_trusted_origin(headers: Any, http_port: int) -> bool:
    origin = (headers.get("Origin") or "").strip().lower()
    if not origin:
        return True
    if origin.startswith(("chrome-extension://", "moz-extension://", "safari-web-extension://")):
        return True
    if origin in (f"http://127.0.0.1:{http_port}", f"http://localhost:{http_port}"):
        return True
    return False


def _find_installed_ext_paths() -> Tuple[Path, Path, Path, Path]:
    ext_root = get_data_dir() / "extensions"
    chrom_dir = ext_root / "chromium"
    crx_file = ext_root / "idm-linux-companion-chromium.crx"
    zip_file = ext_root / "idm-linux-companion-chromium.zip"
    xpi_file = ext_root / "idm-linux-companion-firefox.xpi"

    # Geliştirme / kaynak dizini yedek kontrolü
    # Yeni düzen: repo kökü = src/idm_linux (daemon.py'nin bir üst dizini DEĞİL, kendisi)
    repo_ext = Path(__file__).resolve().parents[0] / "extension"
    if not chrom_dir.exists() and (repo_ext / "chromium").exists():
        chrom_dir = repo_ext / "chromium"
    if not crx_file.exists() and (repo_ext / "idm-linux-companion-chromium.crx").exists():
        crx_file = repo_ext / "idm-linux-companion-chromium.crx"
    if not zip_file.exists() and (repo_ext / "idm-linux-companion-chromium.zip").exists():
        zip_file = repo_ext / "idm-linux-companion-chromium.zip"
    if not xpi_file.exists() and (repo_ext / "idm-linux-companion-firefox.xpi").exists():
        xpi_file = repo_ext / "idm-linux-companion-firefox.xpi"

    # ZIP paketi henüz üretilmemişse ama unpacked dizin mevcutsa anında üret
    if not zip_file.exists() and chrom_dir.is_dir():
        try:
            target_zip = (get_cache_dir(create=True) / "idm-linux-companion-chromium.zip")
            build_chromium_zip_package(chrom_dir, target_zip)
            zip_file = target_zip
        except Exception as exc:
            logger.debug("Anlık Chromium ZIP üretim hatası: %s", exc)

    return chrom_dir, crx_file, zip_file, xpi_file


# ─────────────────────────────────────────────────────────────────────────────
# v3.10.0 ALTYAZI KASASI
# Oyuncuların <track>/textTracks ile BELLEKTE tuttuğu (blob:, MSE) altyazıların
# URL'si yoktur; tarayıcı eklentisi cue'ları WebVTT metnine çevirip buraya
# gönderir, daemon diske yazar ve IDM'nin indirebileceği YEREL bir adres üretir.
# Böylece "oynatıcıya gömülü altyazı" da IDM'ye iner.
# ─────────────────────────────────────────────────────────────────────────────
_SUB_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}\.(vtt|srt|ass|ttml)$")


def _subtitle_store_dir() -> Path:
    path = get_cache_dir(create=True) / "subtitles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_subtitle_text(text: str, label: str = "") -> Optional[Dict[str, Any]]:
    """Altyazı metnini kasaya yazar → {name, url_path, size, ext} döner."""
    from .hls_streamer import detect_subtitle_kind, looks_like_subtitle_bytes

    body = (text or "").strip()
    if not body:
        return None
    raw = body.encode("utf-8", errors="ignore")
    if not looks_like_subtitle_bytes(raw):
        return None
    kind = detect_subtitle_kind(body) or "vtt"
    ext = {"vtt": "vtt", "srt": "srt", "ass": "ass", "ttml": "ttml"}.get(kind, "vtt")
    if kind not in ("vtt", "srt"):
        # SRT/VTT dışı biçimleri oynatıcılar için SRT'ye çevir
        try:
            from .hls_streamer import normalize_srt_text

            converted = normalize_srt_text(body)
            if converted.strip():
                body = converted
                ext = "srt"
        except Exception:
            pass
    if ext == "vtt":
        try:
            from .hls_streamer import normalize_vtt_text

            body = normalize_vtt_text(body)
        except Exception:
            pass
    name = hashlib.sha1(body.encode("utf-8", errors="replace")).hexdigest()[:16] + f".{ext}"
    target = _subtitle_store_dir() / name
    try:
        if not target.is_file():
            target.write_text(body, encoding="utf-8")
    except OSError:
        return None
    return {
        "name": name,
        "size": len(body.encode("utf-8", errors="replace")),
        "ext": ext,
        "label": (label or "").strip()[:80],
    }


def make_http_handler(state: DaemonState):
    class IdmBridgeHTTPHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        # v2.9.3 OOM PANZEHİRİ: IDM'nin açık tuttuğu keep-alive soketleri thread yığını
        # yapamasın — 45 sn hareketsiz bağlantıyı kes (thread ölür, RSS şişmez).
        timeout = 45

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _send_cors(self) -> None:
            origin = self.headers.get("Origin") or "*"
            if (
                origin.startswith(("chrome-extension://", "moz-extension://"))
                or origin in (f"http://127.0.0.1:{state.cfg.http_port}", f"http://localhost:{state.cfg.http_port}", "*")
            ):
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-IDM-Linux, X-Filename, X-Mime-Type")

        def _send_json(self, data: Dict[str, Any], status: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._send_cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html_text: str, status: int = 200) -> None:
            body = html_text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _send_binary_file(self, file_path: Path, content_type: str, download_name: str) -> None:
            if not file_path.exists():
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0 or length > 5 * 1024 * 1024:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._send_cors()
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()

        def do_HEAD(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path.startswith("/stream/"):
                self._handle_stream(head_only=True)
                return
            if parsed.path.startswith("/torrent/"):
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 2:
                    sess = state.torrent_bridge.get_session(parts[1])
                    if sess:
                        serve_torrent_over_http(self, sess, head_only=True)
                        return
            if parsed.path.startswith("/ed2k/"):
                # v3.10.0: native eD2K oturumunun baytları IDM'ye akar
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 2:
                    sess_e = ed2k_get_session(parts[1])
                    if sess_e is not None:
                        serve_torrent_over_http(self, sess_e, head_only=True)
                        return
            if parsed.path.startswith("/subtitle/"):
                name = urllib.parse.unquote(parsed.path[len("/subtitle/"):]).strip("/")
                self._serve_subtitle(name, head_only=True)
                return
            if parsed.path.startswith("/proxy/"):
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 2:
                    state.auth_proxy.serve_proxy_ticket(self, parts[1], head_only=True)
                    return
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _serve_subtitle(self, name: str, head_only: bool = False) -> None:
            """Kasaya kaydedilmiş altyazıyı IDM'ye sunar (/subtitle/<ad>)."""
            if not _SUB_NAME_RE.match(name or ""):
                self.send_response(400)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            fpath = _subtitle_store_dir() / name
            if not fpath.is_file():
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                body = fpath.read_bytes()
            except OSError:
                body = b""
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/vtt; charset=utf-8" if name.endswith(".vtt") else "text/plain; charset=utf-8",
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not head_only:
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        def _serve_blobstream(self, tid: str) -> None:
            """v2.9.6: büyüyen blob dosyasını IDM'ye AKIT (feeder beklenir, idle 120 sn)."""
            with _ASSIST_LOCK:
                e = _ASSIST.get(tid)
                path = e["path"] if e else None
            if not path:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            sent = 0
            idle_deadline = time.time() + 120
            try:
                while True:
                    try:
                        size = path.stat().st_size
                    except OSError:
                        size = 0
                    if size > sent:
                        with path.open("rb") as fh:
                            fh.seek(sent)
                            while sent < size:
                                blk = fh.read(262144)
                                if not blk:
                                    break
                                self.wfile.write(blk)
                                sent += len(blk)
                        idle_deadline = time.time() + 120
                        continue
                    with _ASSIST_LOCK:
                        en = _ASSIST.get(tid)
                        done = bool(en and en["event"].is_set())
                        if en:
                            en["last_feed"] = en.get("last_feed", time.time())
                    if done:
                        break
                    if time.time() > idle_deadline:
                        break
                    time.sleep(0.25)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path.startswith("/stream/"):
                self._handle_stream(head_only=False)
                return
            if parsed.path.startswith("/torrent/"):
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 2:
                    sess = state.torrent_bridge.get_session(parts[1])
                    if sess:
                        serve_torrent_over_http(self, sess, head_only=False)
                        return
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if parsed.path.startswith("/ed2k/"):
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 2:
                    sess_e = ed2k_get_session(parts[1])
                    if sess_e is not None:
                        serve_torrent_over_http(self, sess_e, head_only=False)
                        return
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if parsed.path.startswith("/subtitle/"):
                name = urllib.parse.unquote(parsed.path[len("/subtitle/"):]).strip("/")
                self._serve_subtitle(name, head_only=False)
                return
            if parsed.path.startswith("/proxy/"):
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 2:
                    state.auth_proxy.serve_proxy_ticket(self, parts[1], head_only=False)
                    return

            if parsed.path.startswith("/blobstream/"):
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 2:
                    self._serve_blobstream(parts[1])
                    return
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            if parsed.path == "/support":
                qs = urllib.parse.parse_qs(parsed.query)
                lang = (qs.get("lang", [state.cfg.language])[0] or state.cfg.language).strip().lower()
                self._send_html(build_support_html(http_port=state.cfg.http_port, lang_code=lang))
                return

            if parsed.path == "/iframe":
                qs = urllib.parse.parse_qs(parsed.query)
                mode = (qs.get("mode", ["donation"])[0] or "donation").strip().lower()
                lang = (qs.get("lang", [state.cfg.language])[0] or state.cfg.language).strip().lower()
                custom_url = (qs.get("url", [""])[0] or "").strip() or None
                if custom_url and not (custom_url.startswith("https://") or custom_url.startswith("http://")):
                    custom_url = None
                self._send_html(build_iframe_shell_html(mode=mode, lang_code=lang, custom_url=custom_url))
                return

            if parsed.path == "/welcome":
                chrom_dir, _, _, _ = _find_installed_ext_paths()
                det_browser = detect_default_browser()
                html_doc = render_welcome_html(
                    http_port=state.cfg.http_port,
                    welcome_token=state.welcome_token,
                    default_browser=det_browser,
                    chrom_ext_dir=chrom_dir,
                )
                self._send_html(html_doc)
                return

            if parsed.path == "/extension/idm-linux-companion-firefox.xpi":
                _, _, _, xpi_file = _find_installed_ext_paths()
                self._send_binary_file(xpi_file, "application/x-xpinstall", "idm-linux-companion-firefox.xpi")
                return

            if parsed.path == "/extension/idm-linux-companion-chromium.zip":
                _, _, zip_file, _ = _find_installed_ext_paths()
                self._send_binary_file(zip_file, "application/zip", "idm-linux-companion-chromium.zip")
                return

            if parsed.path == "/extension/idm-linux-companion-chromium.crx":
                # Modern Chromium/Brave CRX dosyalarını hem indirmede engeller hem de
                # CRX_REQUIRED_PROOF_MISSING hatası verir; doğrudan engellenmeyen ZIP paketine yönlendir!
                self.send_response(302)
                self.send_header("Location", "/extension/idm-linux-companion-chromium.zip")
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                return

            if parsed.path == "/extension/companion-policy.crx":
                # v3.2.2: Policy force-install için ÇIPLAK CRX — Chrome'un kendi güncelleyicisi
                # (kullanıcı indirmesi DEĞİL) buradan indirir; tarayıcı engellemez.
                _, crx_src, _, _ = _find_installed_ext_paths()
                self._send_binary_file(
                    crx_src if (crx_src and crx_src.exists()) else (Path(__file__).resolve().parents[0] / "extension" / "idm-linux-companion-chromium.crx"),
                    "application/octet-stream",
                    "idm-linux-companion-chromium.crx",
                )
                return

            if parsed.path == "/crx-update.xml":
                # v3.2.2: Chromium kurumsal force-install update manifest (gupdate 2.0).
                # Policy dizini canlı izlenir -> ÇALIŞAN tarayıcıya eklenti RESTARTSIZ kurulur.
                crx_url = f"http://127.0.0.1:{state.cfg.http_port}/extension/companion-policy.crx"
                xml = (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<gupdate xmlns="http://www.google.com/update2/response" protocol="2.0">\n'
                    f'  <app appid="{COMPANION_CHROME_EXT_ID}">\n'
                    f'    <updatecheck codebase="{crx_url}" version="{__version__}" />\n'
                    "  </app>\n"
                    "</gupdate>\n"
                )
                body = xml.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == "/api/assist/pending":
                self._send_json({"ok": True, "pending": assist_pending_list()})
                return

            if parsed.path == "/api/confirm/pending":
                global _LAST_EXT_POLL
                _LAST_EXT_POLL = time.time()
                with _CONFIRM_LOCK:
                    pend = [
                        {"id": k, "kind": v["kind"], "uri": v["uri"], "message": v.get("message", "")}
                        for k, v in _PENDING_CONFIRMS.items()
                    ]
                self._send_json({"ok": True, "pending": pend})
                return

            if parsed.path == "/api/streams":
                self._send_json({"ok": True, "streams": state.stream_engine.list_jobs()})
                return

            # v3.5.0: Oynatma Listesi seri indirme — iş durumu (GUI 1 sn'de bir okur)
            if parsed.path == "/api/playlist/batch/status":
                q = urllib.parse.parse_qs(parsed.query)
                bid = (q.get("batch_id") or [""])[0]
                info = state.playlist_manager.status(bid)
                self._send_json({"ok": info is not None, "batch": info})
                return

            if parsed.path == "/api/playlist/batch/list":
                self._send_json({"ok": True, "batches": state.playlist_manager.list_batches()})
                return

            if not _is_trusted_origin(self.headers, state.cfg.http_port):
                self._send_json({"ok": False, "error": "Untrusted origin"}, status=403)
                return

            if parsed.path == "/api/status":
                sys_info = detect_system()
                idm_exe = state.cfg.find_idm_exe()
                official_active = (time.time() - state.last_official_ext_ping) < 120.0
                det_browser = detect_default_browser()
                self._send_json(
                    {
                        "ok": True,
                        "version": __version__,
                        "daemon_uptime": int(time.time() - state.started_at),
                        "rss_mb": _rss_mb(),
                        "active_stream_jobs": state.stream_engine.active_job_count(),
                        "wine_prefix": state.cfg.wine_prefix,
                        "idm_installed": idm_exe is not None,
                        "idm_exe": str(idm_exe) if idm_exe else None,
                        "idm_running": state.sender.is_idm_running(),
                        "wine_installed": sys_info.wine_installed,
                        "wine_version": sys_info.wine_version,
                        "ffmpeg_installed": sys_info.ffmpeg_installed,
                        "ytdlp_installed": sys_info.ytdlp_path is not None,
                        "aria2_installed": sys_info.aria2_installed,
                        # v3.10.0: kendi BitTorrent motorumuz her zaman kullanılabilir
                        "native_torrent": True,
                        "streamlink_installed": shutil.which("streamlink") is not None,
                        "live_dvr_engine": True,
                        "official_extension_connected": official_active,
                        "downloads_dispatched": state.downloads_dispatched,
                        "capture_downloads": state.cfg.capture_downloads,
                        "video_bar_enabled": state.cfg.video_bar_enabled,
                        "clipboard_monitor": state.cfg.clipboard_monitor,
                        "silent_mode": state.cfg.silent_mode,
                        "excluded_domains": state.cfg.excluded_domains,
                        "file_extensions": state.cfg.file_extensions,
                        "ws_port": state.cfg.ws_port,
                        "active_ws_ports": state.active_ws_ports,
                        "http_port": state.cfg.http_port,
                        "default_browser": (
                            {
                                "name": det_browser.name,
                                "family": det_browser.family,
                                "binary": det_browser.binary,
                            }
                            if det_browser
                            else None
                        ),
                    }
                )
                return

            if parsed.path == "/api/config":
                state.reload_config()
                self._send_json({"ok": True, "config": state.cfg.__dict__})
                return

            if parsed.path == "/api/torrent/list":
                self._send_json({"ok": True, "torrents": state.torrent_bridge.list_active_summary()})
                return

            # v3.7.0: torrent popup'u açılırken aria2c motorunu ÖNCEDEN sorgular —
            # motor yoksa kullanıcıya kurulum komutu EN BAŞTA gösterilir (kör deneme yok)
            if parsed.path == "/api/torrent/preflight":
                aria2_bin = shutil.which("aria2c")
                version = ""
                if aria2_bin:
                    try:
                        vres = subprocess.run(
                            [aria2_bin, "--version"], capture_output=True, text=True, timeout=5, check=False
                        )
                        first = (vres.stdout or "").splitlines()
                        version = first[0].strip()[:60] if first else "aria2c"
                    except Exception:
                        version = "aria2c"
                self._send_json(
                    {
                        "ok": True,
                        "installed": bool(aria2_bin),
                        "version": version,
                        "hint": (
                            ""
                            if aria2_bin
                            else "sudo pacman -S aria2  |  sudo apt install aria2  |  sudo dnf install aria2"
                        ),
                    }
                )
                return

            # v3.7.0: eD2K motor durumu (popup ön-bilgi + GUI Genel Bakış satırı)
            if parsed.path == "/api/ed2k/status":
                info = detect_ed2k_backend()
                with _ED2K_INSTALL_LOCK:
                    inst_res = state.ed2k_install_result
                    inst_going = state.ed2k_install_started and inst_res is None
                self._send_json(
                    {
                        "ok": True,
                        "backend": info.get("backend") or "none",
                        "running": bool(info.get("running")),
                        "native": native_ed2k_available(),
                        "sessions": ed2k_list_sessions(),
                        "install_hint": info.get("install_hint") or "",
                        "installing": bool(inst_going),
                        "install_result": inst_res,
                        "incoming_dir": ed2k_incoming_dir(),
                    }
                )
                return

            self._send_json({"ok": False, "error": "Not found"}, status=404)

        def do_POST(self) -> None:
            # v3.0.0 GLOBAL POST KALKANI: beklenmeyen çökmede bağlantı ölmez,
            # eklenti/gGUI daima JSON yanıtı alır ('köprü yok' yanılgısı biter)
            if not _is_trusted_origin(self.headers, state.cfg.http_port):
                self._send_json({"ok": False, "error": "Untrusted origin"}, status=403)
                return
            try:
                self._do_post_inner()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as post_exc:
                logger.error("POST %s çökmesi: %s", self.path[:80], post_exc)
                try:
                    self._send_json({"ok": False, "error": str(post_exc)}, status=500)
                except Exception:
                    pass

        def _do_post_inner(self) -> None:
            parsed = urllib.parse.urlparse(self.path)

            if parsed.path == "/api/blob-upload":
                ctype = (self.headers.get("Content-Type") or "").lower()
                length = int(self.headers.get("Content-Length") or "0")
                if length <= 0 or length > 1024 * 1024 * 1024:
                    self._send_json({"ok": False, "error": "Geçersiz blob boyutu."}, status=400)
                    return

                filename = urllib.parse.unquote(self.headers.get("X-Filename") or "")
                mime_type = self.headers.get("X-Mime-Type") or "application/octet-stream"

                if "application/json" in ctype:
                    # v3.2.2: JSON/base64 yolu yalnızca KÜÇÜK gövdeler için (<= 8MB);
                    # büyük gövde RAM'de 2-3x şişiriyordu.
                    if length > 8 * 1024 * 1024:
                        self._send_json({"ok": False, "error": "JSON blob çok büyük — ikili (binary) yol kullanın."}, status=413)
                        return
                    payload_b = self._read_json()
                    b64_str = payload_b.get("dataBase64") or ""
                    filename = payload_b.get("filename") or filename
                    mime_type = payload_b.get("mimeType") or mime_type
                    try:
                        raw_bytes = base64.b64decode(b64_str)
                    except Exception:
                        self._send_json({"ok": False, "error": "Geçersiz base64 verisi."}, status=400)
                        return
                    ticket = state.auth_proxy.create_blob_ticket(
                        raw_bytes=raw_bytes,
                        filename=filename or "download.bin",
                        mime_type=mime_type,
                    )
                    del raw_bytes
                else:
                    # v3.2.2 BELLEK KALKANI: gövde DOĞRUDAN diske akıtılır (0x RAM birikimi)
                    ticket, blob_err = state.auth_proxy.create_blob_ticket_streamed(
                        reader=self.rfile,
                        length=length,
                        filename=filename or "download.bin",
                        mime_type=mime_type,
                    )
                    if ticket is None:
                        self._send_json({"ok": False, "error": blob_err or "Blob alınamadı."}, status=500)
                        return

                if not state.cfg.capture_downloads:
                    self._send_json({"ok": False, "takeover": False, "reason": "disabled"})
                    return

                quoted_fn = urllib.parse.quote(ticket.filename)
                local_url = f"http://127.0.0.1:{state.cfg.http_port}/proxy/{ticket.ticket_id}/{quoted_fn}"
                req = DownloadRequest(
                    url=local_url,
                    filename=ticket.filename,
                    source="companion-blob",
                )
                ok, msg = state.sender.send_download(req)
                if ok:
                    with state.lock:
                        state.downloads_dispatched += 1
                self._send_json({"ok": ok, "takeover": ok, "filename": ticket.filename, "message": msg})
                return

            payload = self._read_json()

            if parsed.path == "/api/auth-context":
                ctx_url = (payload.get("url") or "").strip()
                if ctx_url:
                    extra_hdrs = payload.get("extraHeaders")
                    state.auth_vault.record(
                        url=ctx_url,
                        cookies=payload.get("cookies") or "",
                        referer=payload.get("referer") or "",
                        origin=payload.get("origin") or "",
                        user_agent=payload.get("userAgent") or "",
                        extra_headers=extra_hdrs if isinstance(extra_hdrs, dict) else {},
                    )
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/browser/activate-extension":
                tok = payload.get("token") or ""
                if not secrets.compare_digest(tok, state.welcome_token):
                    self._send_json({"ok": False, "error": "Invalid token"}, status=403)
                    return

                chrom_dir, _, _, xpi_file = _find_installed_ext_paths()

                def _delayed_relaunch() -> None:
                    time.sleep(0.35)
                    auto_install_and_open_default_browser(
                        http_port=state.cfg.http_port,
                        chrom_ext_dir=chrom_dir,
                        ff_xpi_path=xpi_file,
                        restart_if_running=True,
                    )

                threading.Thread(target=_delayed_relaunch, daemon=True).start()
                self._send_json({"ok": True, "message": "Tarayıcı eklentiyle yeniden başlatılıyor..."})
                return

            if parsed.path == "/api/open-idm":
                ok, msg = state.sender.open_idm_window()
                self._send_json({"ok": ok, "message": msg})
                return

            if parsed.path == "/api/config":
                state.reload_config()
                for key in (
                    "capture_downloads",
                    "video_bar_enabled",
                    "clipboard_monitor",
                    "silent_mode",
                    "language",
                    "dpi_scale",
                    "max_connections",
                    "keep_wine_warm",
                    "stream_via_idm",
                    "excluded_domains",
                    "file_extensions",
                    "download_dir",
                    "wine_prefix",
                ):
                    if key in payload:
                        setattr(state.cfg, key, payload[key])
                state.cfg.save()
                state.reload_config()
                self._send_json({"ok": True, "config": state.cfg.__dict__})
                return

            if parsed.path == "/api/wire":
                raw_msg = payload.get("raw", "")
                if payload.get("ping_official"):
                    state.last_official_ext_ping = time.time()
                replies = state.handle_idm_wire_frame(raw_msg, via="native-host") if raw_msg else []
                self._send_json({"ok": True, "replies": replies})
                return

            # ── v3.10.0 ALTYAZI KASASI: oynatıcıya GÖMÜLÜ altyazı ────────────
            # Oyuncular altyazıyı <track>/textTracks ile bellekte tutuyorsa (blob:/
            # MSE) indirilebilir bir URL YOKTUR. Eklenti cue'ları WebVTT'ye çevirip
            # buraya gönderir; daemon diske yazar ve IDM'nin indirebileceği yerel
            # adresi döndürür. Kullanıcı raporu: "oynatıcıdaki altyazıyı bar
            # göstermiyor" — bu uç nokta o boşluğu kapatır.
            if parsed.path == "/api/subtitle/register":
                vtt = payload.get("vtt") or payload.get("text") or ""
                label = (payload.get("label") or payload.get("name") or "altyazı")[:80]
                url_hint = (payload.get("url") or "")[:400]
                info = store_subtitle_text(vtt, label=label)
                if not info:
                    self._send_json(
                        {"ok": False, "error": "Altyazı metni boş ya da geçersiz (altyazı değil)."},
                        status=400,
                    )
                    return
                local_url = f"http://127.0.0.1:{state.cfg.http_port}/subtitle/{info['name']}"
                logger.info(
                    "Altyazı kasaya alındı: %s (%s bayt, biçim=%s)", label or "?", info["size"], info["ext"]
                )
                self._send_json(
                    {
                        "ok": True,
                        "url": local_url,
                        "filename": f"{sanitize_filename(label or 'altyazı')}.{info['ext']}",
                        "ext": info["ext"],
                        "size": info["size"],
                        "label": label,
                        "source_url": url_hint,
                    }
                )
                return

            # v3.7.0: eD2K bağlantısını motoruna (mldonkey/aMule) iletir
            if parsed.path == "/api/ed2k/download":
                link = (payload.get("link") or payload.get("url") or "").strip()
                if not link.lower().startswith("ed2k://"):
                    self._send_json({"ok": False, "error": "Geçersiz ed2k bağlantısı."}, status=400)
                    return
                meta = parse_ed2k_link(link) or {}
                logger.info("eD2K bağlantısı alındı [%s]: %s (%s)", payload.get("source") or "api", meta.get("name") or "?", meta.get("size") or "?")

                # ── v3.10.0 NATIVE YOL: bağlantı IDM köprüsüne aktarılır ────
                # Dosya aMule'un "Incoming" klasörüne DEĞİL, IDM'nin indirme
                # listesine düşer; baytlar /ed2k/<ticket>/<dosya> üzerinden akar.
                if native_ed2k_available():
                    ok_n, msg_n, meta_n = ed2k_register_native(link)
                    if ok_n and meta_n:
                        out_fn = sanitize_filename(meta_n.get("filename") or meta.get("name") or "ed2k_dosya")
                        quoted = urllib.parse.quote(out_fn)
                        bridge_url = f"http://127.0.0.1:{state.cfg.http_port}/ed2k/{meta_n['ticket']}/{quoted}"
                        try:
                            ok_send, msg_send = state.sender.send_download(
                                DownloadRequest(
                                    url=bridge_url,
                                    filename=out_fn,
                                    silent=None,
                                    source="ed2k-native",
                                    # IDM özelliklerinde GERÇEK ed2k:// bağlantısı görünür
                                    referer=link[:2000],
                                )
                            )
                        except Exception as send_exc:
                            ok_send, msg_send = False, f"IDM'ye iletilemedi: {send_exc}"
                        if ok_send:
                            with state.lock:
                                state.downloads_dispatched += 1
                            self._send_json(
                                {
                                    "ok": True,
                                    "takeover": True,
                                    "installing": False,
                                    "message": (
                                        f"eD2K indirmesi IDM'ye aktarıldı ({meta_n.get('size') or 0} bayt). "
                                        "Kaynaklar aranıyor; baytlar hazır oldukça IDM'e akacak."
                                    ),
                                    "backend": "native-ed2k",
                                    "filename": out_fn,
                                    "size": meta_n.get("size") or 0,
                                    "ticket": meta_n.get("ticket"),
                                    "bridge_url": bridge_url,
                                    "incoming_dir": str(Path(state.cfg.download_dir).expanduser()),
                                }
                            )
                            return
                        logger.warning("eD2K native köprü IDM'ye iletilemedi: %s", msg_send)
                    else:
                        logger.info("eD2K native oturum açılamadı, yedek yola geçiliyor: %s", msg_n)

                ok_e, msg_e, backend_e = ed2k_add_link(link)

                # v3.8.0 TAM OTOMATİK KURULUM: motor yoksa kurulum KENDİLİĞİNDEN başlar
                # (pkexec yetki penceresi = kullanıcı onayı). Bağlantı beklemeye alınır;
                # kurulum bitince daemon bağlantıyı OTOMATİK motora iletir. Eklenti/GUI
                # /api/ed2k/status'ı yoklayarak ilerlemeyi görür — elle kurulum YOKTUR.
                installing = False
                if not ok_e and backend_e == "none":
                    with _ED2K_INSTALL_LOCK:
                        already = state.ed2k_install_started
                        if not already:
                            state.ed2k_install_started = True
                            state.ed2k_install_result = None
                            state.ed2k_pending_link = link
                            state.ed2k_pending_src = str(payload.get("source") or "api")
                    if not already:
                        logger.info("eD2K motoru yok — kurulum OTOMATİK başlatılıyor (bağlantı beklemeye alındı: %s)", (meta.get("name") or "?")[:80])
                        threading.Thread(target=state._ed2k_auto_install_job, daemon=True).start()
                        installing = True
                        msg_e = (
                            "eD2K motoru (aMule) kurulu değil — kurulum otomatik başlatıldı. "
                            "Açılan yetkilendirme penceresini onaylayın; bağlantınız kurulum "
                            "tamamlanınca kendiliğinden motoruna iletilecek."
                        )
                    else:
                        # kurulum zaten sürüyor — bu bağlantıyı bekleyen bağlantı olarak güncelle
                        with _ED2K_INSTALL_LOCK:
                            state.ed2k_pending_link = link
                            state.ed2k_pending_src = str(payload.get("source") or "api")
                        installing = True
                        msg_e = (
                            "eD2K motoru şu anda arka planda kuruluyor — bağlantınız kuyruğa "
                            "alındı ve kurulum tamamlanınca kendiliğinden gönderilecek."
                        )

                self._send_json(
                    {
                        "ok": ok_e,
                        "takeover": ok_e,
                        "installing": installing,
                        "message": msg_e,
                        "backend": backend_e,
                        "filename": meta.get("name") or "",
                        "size": meta.get("size") or 0,
                        "incoming_dir": ed2k_incoming_dir(),
                    }
                )
                return

            # v3.7.0: eD2K motorunu TEK TIKLA kur (pkexec) — arka planda çalışır,
            # eklenti/GUI /api/ed2k/status'ı yoklayarak ilerlemeyi görür
            if parsed.path == "/api/ed2k/install":
                # v3.10.0: yerleşik (native) motor hazırsa HARİCİ kurulum ve
                # yetkilendirme penceresi YOK — istek anında başarıyla döner.
                if native_ed2k_available():
                    with _ED2K_INSTALL_LOCK:
                        state.ed2k_install_started = True
                        state.ed2k_install_result = {
                            "ok": True,
                            "message": (
                                "Yerleşik eD2K motoru hazır — harici program kurulumu ve "
                                "yetkilendirme gerekmez."
                            ),
                            "ts": time.time(),
                            "native": True,
                        }
                    self._send_json(
                        {
                            "ok": True,
                            "started": False,
                            "native": True,
                            "message": "Yerleşik eD2K motoru hazır; kurulum gerekmedi.",
                        }
                    )
                    return
                with _ED2K_INSTALL_LOCK:
                    if not state.ed2k_install_started:
                        state.ed2k_install_started = True
                        state.ed2k_install_result = None
                        need_start = True
                    else:
                        need_start = False
                if need_start:
                    threading.Thread(target=state._ed2k_auto_install_job, daemon=True).start()
                self._send_json({"ok": True, "started": True, "message": "Kurulum arka planda başlatıldı."})
                return

            if parsed.path == "/api/torrent/download":
                magnet_uri = (payload.get("magnet") or "").strip()
                tor_url = (payload.get("url") or "").strip()
                local_path = (payload.get("local_path") or payload.get("localPath") or "").strip()
                b64_data = (payload.get("torrent_base64") or payload.get("torrentBase64") or "").strip()
                raw_tor: Optional[bytes] = None
                if b64_data:
                    try:
                        raw_tor = base64.b64decode(b64_data)
                    except Exception:
                        self._send_json({"ok": False, "error": "Geçersiz Base64 .torrent verisi."}, status=400)
                        return

                ok_t, msg_t, info_t = state.dispatch_torrent_or_magnet(
                    magnet_uri=magnet_uri,
                    torrent_url=tor_url,
                    local_path=local_path,
                    raw_bytes=raw_tor,
                    cookies=payload.get("cookies") or "",
                    referer=payload.get("referer") or "",
                    user_agent=payload.get("userAgent") or "",
                    silent=payload.get("silent"),
                    source=payload.get("source") or "api-torrent",
                )
                resp_body: Dict[str, Any] = {"ok": ok_t, "takeover": ok_t, "message": msg_t}
                if info_t:
                    resp_body.update(info_t)
                self._send_json(resp_body, status=200 if ok_t else 400)
                return

            if parsed.path == "/api/download":
                if state.ext_disabled:
                    self._send_json({"ok": False, "takeover": False, "reason": "ext_disabled"})
                    return
                url = (payload.get("url") or "").strip()
                if not url:
                    self._send_json({"ok": False, "error": "URL eksik."}, status=400)
                    return

                force = bool(payload.get("force", False))
                referer = payload.get("referer") or ""
                if not force:
                    if not state.cfg.capture_downloads:
                        self._send_json({"ok": False, "takeover": False, "reason": "disabled"})
                        return
                    if is_domain_excluded(url, referer, state.cfg.excluded_domains):
                        self._send_json({"ok": False, "takeover": False, "reason": "excluded"})
                        return

                extra_hdrs = payload.get("extraHeaders")
                clean_extra = extra_hdrs if isinstance(extra_hdrs, dict) else {}
                state.auth_vault.record(
                    url=url,
                    cookies=payload.get("cookies") or "",
                    referer=referer,
                    origin=payload.get("origin") or "",
                    user_agent=payload.get("userAgent") or payload.get("user_agent") or "",
                    extra_headers=clean_extra,
                )

                req = DownloadRequest(
                    url=url,
                    referer=referer,
                    origin=payload.get("origin") or "",
                    cookies=payload.get("cookies") or "",
                    user_agent=payload.get("userAgent") or payload.get("user_agent") or "",
                    post_data=payload.get("postData") or payload.get("post_data") or "",
                    filename=payload.get("filename") or "",
                    save_dir=payload.get("saveDir") or "",
                    silent=payload.get("silent"),
                    source=payload.get("source") or "companion-ext",
                    extra_headers=clean_extra,
                )
                ok, msg = state.dispatch_download(req, dedup=not force)
                self._send_json({"ok": ok, "takeover": ok, "message": msg})
                return

            if parsed.path == "/api/download-batch":
                links = payload.get("links") or []
                count = 0
                for item in links[:100]:
                    u = (item.get("url") or "").strip()
                    if not u:
                        continue
                    req = DownloadRequest(
                        url=u,
                        referer=item.get("referer") or payload.get("referer") or "",
                        cookies=payload.get("cookies") or "",
                        user_agent=payload.get("userAgent") or "",
                        filename=item.get("filename") or "",
                        silent=True if len(links) > 3 else None,
                        source="batch",
                    )
                    ok, _ = state.dispatch_download(req, dedup=False)
                    if ok:
                        count += 1
                self._send_json({"ok": True, "queued": count})
                return

            if parsed.path == "/api/playlist/probe":
                page_url = (payload.get("url") or "").strip()
                if not page_url:
                    self._send_json({"ok": False, "error": "url yok"})
                    return
                info = probe_playlist_entries(
                    page_url,
                    cookies=payload.get("cookies") or "",
                    user_agent=payload.get("userAgent") or "",
                    max_items=int(payload.get("maxItems") or 60),
                )
                # v3.5.0: GUI rozeti için siteyi dinamik algıla
                from .playlist_batch import detect_playlist_site

                info["site"] = detect_playlist_site(page_url)
                self._send_json(info)
                return

            # v3.5.0: Oynatma listesi SERİ indirme (GUI kartı) — seçilen videolar sırayla,
            # maksimum hızda; her video için duraklat/devam/iptal desteği
            if parsed.path == "/api/playlist/batch/start":
                page_url = (payload.get("playlist_url") or payload.get("url") or "").strip()
                entries = payload.get("entries") or []
                res = state.playlist_manager.start_batch(
                    playlist_url=page_url,
                    entries=entries,
                    # v3.7.0: oynatma listeleri IDM 'Video' kategori klasörüne akar
                    download_dir=str(_categorized_final_dir("playlist.mp4", Path(state.cfg.download_dir))),
                    cookies=payload.get("cookies") or "",
                    user_agent=payload.get("userAgent") or "",
                )
                state.diag.append(f"PLBATCH-START {res.get('batch_id', res.get('error', ''))}")
                self._send_json(res)
                return

            if parsed.path == "/api/playlist/batch/control":
                bid = (payload.get("batch_id") or "").strip()
                action = (payload.get("action") or "").strip()
                try:
                    idx = int(payload.get("index") or 0)
                except Exception:
                    idx = 0
                res = state.playlist_manager.control(bid, action, idx)
                state.diag.append(f"PLBATCH-{action.upper()} {bid} idx={idx}")
                self._send_json(res)
                return


            if parsed.path == "/api/playlist/download":
                entries = payload.get("entries") or []
                hls_mode = (payload.get("hlsMode") or "vod").strip().lower()
                if hls_mode not in ("vod", "dvr", "live"):
                    hls_mode = "vod"
                queued = 0
                for item in entries[:100]:
                    e_url = (item.get("url") or "").strip()
                    if not e_url:
                        continue
                    e_title = sanitize_filename((item.get("title") or f"video_{item.get('index', queued + 1)}").strip())
                    ticket = state.stream_engine.create_ticket(
                        source_url=e_url,
                        filename=f"{e_title}.mp4",
                        mode="ytdlp",
                        cookies_header=payload.get("cookies") or "",
                        referer=payload.get("referer") or "",
                        user_agent=payload.get("userAgent") or "",
                        hls_mode=hls_mode,
                        final_dir=_categorized_final_dir(f"{e_title}.mp4", Path(state.cfg.download_dir)),
                    )
                    quoted_fn = urllib.parse.quote(ticket.filename)
                    stream_url = f"http://127.0.0.1:{state.cfg.http_port}/stream/{ticket.ticket_id}/{quoted_fn}"
                    ok_p, _ = state.sender.send_download(
                        DownloadRequest(url=stream_url, filename=ticket.filename, silent=True, source="playlist-batch")
                    )
                    if ok_p:
                        queued += 1
                        with state.lock:
                            state.downloads_dispatched += 1
                self._send_json({"ok": True, "queued": queued})
                return

            if parsed.path == "/api/streams":
                self._send_json({"ok": True, "streams": state.stream_engine.list_jobs()})
                return

            if parsed.path == "/api/ext-state":
                state.ext_disabled = bool(payload.get("disabled"))
                state.diag.append(f"EXT-STATE disabled={state.ext_disabled}")
                logger.info("Companion eklenti durumu: %s", "PASİF" if state.ext_disabled else "AKTİF")
                self._send_json({"ok": True, "disabled": state.ext_disabled})
                return

            if parsed.path == "/api/remote-log/flush":
                n = flush_remote_log(state)
                self._send_json({"ok": True, "sent": n, "configured": bool((state.cfg.remote_log_url or "").strip())})
                return

            if parsed.path == "/api/abyss/meta":
                # v2.9.5: companion'ın yakaladığı şifreli abyss info JSON'u
                from .abyss_engine import abyss_register_meta

                slug = abyss_register_meta(payload.get("payload") or "")
                state.diag.append(f"ABYSS-META slug={slug}")
                self._send_json({"ok": bool(slug), "slug": slug or ""})
                return

            if parsed.path == "/api/blobfeed/init":
                # v2.9.3: BÜYÜK blob (justbeamit vb.) parça beslemesi başlat
                import secrets as _sec

                tid = _sec.token_hex(12)
                fn = sanitize_filename(payload.get("filename") or f"blob-{tid[:6]}.bin")
                path = Path(tempfile.gettempdir()) / f"idm_blobfeed_{tid}.part"
                streaming = bool(payload.get("streaming"))
                with _ASSIST_LOCK:
                    _ASSIST[tid] = {
                        "url": "",
                        "event": threading.Event(),
                        "path": path,
                        "fh": None,
                        "ok": False,
                        "born": time.time(),
                        "streaming": streaming,
                        "dispatched": False,
                        "fed_bytes": 0,
                        "last_feed": time.time(),
                        "blobfeed": {"filename": fn, "mime": payload.get("mimeType") or "application/octet-stream"},
                    }
                # v2.9.8: dispatch İLK 64 KB'dan sonra (0-bayt indirme panzehiri)
                self._send_json({"ok": True, "id": tid})
                return

            if parsed.path == "/api/blobfeed/done":
                tid = (payload.get("id") or "").strip()
                with _ASSIST_LOCK:
                    e = _ASSIST.get(tid)
                    streaming = bool(e and e.get("streaming"))
                    if e and e.get("fh"):
                        try:
                            e["fh"].close()
                        except Exception:
                            pass
                        e["fh"] = None
                    if e:
                        e["ok"] = True
                        e["event"].set()
                    if streaming:
                        if e and not e.get("dispatched") and e["path"].exists() and e["path"].stat().st_size > 0:
                            e["dispatched"] = True
                            meta0 = e.get("blobfeed") or {}
                            fn0 = meta0.get("filename") or "p2p-dosya"
                            purl = f"http://127.0.0.1:{state.cfg.http_port}/blobstream/{tid}/{urllib.parse.quote(fn0)}"
                            threading.Thread(
                                target=state.dispatch_download,
                                args=(DownloadRequest(url=purl, filename=fn0, source="blobstream"),),
                                daemon=True,
                            ).start()
                        threading.Timer(600.0, lambda: _ASSIST.pop(tid, None)).start()
                    else:
                        _ASSIST.pop(tid, None)
                if streaming:
                    self._send_json({"ok": True})
                    return
                if e and e["path"].exists() and e["path"].stat().st_size > 0:
                    meta = e.get("blobfeed") or {}
                    tk = AuthProxyTicket(
                        ticket_id=tid,
                        kind="blob",
                        filename=meta.get("filename") or "download.bin",
                        mime_type=meta.get("mime") or "application/octet-stream",
                        blob_file=e["path"],
                    )
                    with state.auth_proxy._lock:
                        state.auth_proxy._tickets[tid] = tk
                    proxy_url = f"http://127.0.0.1:{state.cfg.http_port}/proxy/{tid}/{urllib.parse.quote(tk.filename)}"
                    threading.Thread(
                        target=state.dispatch_download,
                        args=(DownloadRequest(url=proxy_url, filename=tk.filename, source="blobfeed"),),
                        daemon=True,
                    ).start()
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/assist/chunk":
                # v2.9.8: streaming blobfeed ise sayaç + eşik dispatch
                _tid0 = (payload.get("id") or "").strip()
                with _ASSIST_LOCK:
                    _e0 = _ASSIST.get(_tid0)
                    _is_stream = bool(_e0 and _e0.get("streaming"))
                if _is_stream:
                    import base64 as _b64s

                    _nb = len(_b64s.b64decode(payload.get("b64") or "")) if payload.get("b64") else 0
                    _do_dispatch = False
                    with _ASSIST_LOCK:
                        _e0 = _ASSIST.get(_tid0)
                        if _e0:
                            _e0["fed_bytes"] = _e0.get("fed_bytes", 0) + _nb
                            _e0["last_feed"] = time.time()
                            if not _e0.get("dispatched") and _e0["fed_bytes"] >= 65536:
                                _e0["dispatched"] = True
                                _do_dispatch = True
                    if _do_dispatch:
                        _meta0 = (_e0 or {}).get("blobfeed") or {}
                        _fn0 = _meta0.get("filename") or "p2p-dosya"
                        _purl = f"http://127.0.0.1:{state.cfg.http_port}/blobstream/{_tid0}/{urllib.parse.quote(_fn0)}"
                        threading.Thread(
                            target=state.dispatch_download,
                            args=(DownloadRequest(url=_purl, filename=_fn0, source="blobstream"),),
                            daemon=True,
                        ).start()
                tid = (payload.get("id") or "").strip()
                b64 = payload.get("b64") or ""
                fh = assist_begin_chunk(tid)
                if fh is not None and b64:
                    try:
                        fh.write(base64.b64decode(b64))
                    except Exception:
                        pass
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/assist/done":
                _aid = (payload.get("id") or "").strip()
                _aok = bool(payload.get("ok"))
                state.diag.append(f"ASSIST {_aid} ok={_aok}")
                assist_finish(_aid, _aok)
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/confirm-result":
                cid = (payload.get("id") or "").strip()
                ok = bool(payload.get("ok"))
                with _CONFIRM_LOCK:
                    pend = _PENDING_CONFIRMS.pop(cid, None)
                if ok and pend:
                    threading.Thread(
                        target=_finalize_confirmation,
                        args=(state, pend["kind"], pend["uri"]),
                        daemon=True,
                    ).start()
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/streams/clear":
                mode = (payload.get("mode") or "finished").strip().lower()
                tid = (payload.get("ticket") or "").strip()
                n = state.stream_engine.clear_jobs(mode=mode, ticket_id=tid)
                self._send_json({"ok": True, "cleared": n})
                return

            if parsed.path == "/api/stream/stop":
                tid = (payload.get("ticket") or "").strip()
                ok_s = state.stream_engine.stop_job(tid) if tid else False
                self._send_json({"ok": ok_s})
                return

            if parsed.path == "/api/open-folder":
                raw_path = (payload.get("path") or "").strip()
                unix_path = wine_path_to_unix(raw_path, state.cfg.wine_prefix) if ":" in raw_path[:2] else raw_path
                ok_f, msg_f = open_folder_native(unix_path or state.cfg.download_dir)
                self._send_json({"ok": ok_f, "message": msg_f})
                return

            if parsed.path == "/api/video/probe":
                page_url = (payload.get("pageUrl") or "").strip()
                streams = payload.get("streams") or []
                cookies = payload.get("cookies") or ""
                referer = payload.get("referer") or page_url
                ua = payload.get("userAgent") or ""
                use_ytdlp = bool(payload.get("useYtdlp", True))
                force_refresh = bool(payload.get("forceRefresh", False))

                state.diag.append(f"PROBE {page_url[:120]} streams={len(streams)}")
                # v2.8.7: aynı sayfa için eşzamanlı probe'ları TEK'e indir (yt-dlp selini önle)
                inflight_key = page_url or "|".join((st.get("url") or "")[:80] for st in streams[:4])
                # v3.2.2 STAMPEDE KALKANI: force_refresh (↻ Yenile) 8 sn'de birden çok kez
                # gelirse (bar + önizleme + kullanıcı) yt-dlp/manifest fırtınasını kes.
                if force_refresh and inflight_key:
                    last_f = _LAST_FORCE_PROBE.get(inflight_key, 0.0)
                    if (time.time() - last_f) < 8.0 and not _probe_has_options(state, inflight_key):
                        force_refresh = False
                if force_refresh and inflight_key:
                    _LAST_FORCE_PROBE[inflight_key] = time.time()
                    if len(_LAST_FORCE_PROBE) > 300:
                        _LAST_FORCE_PROBE.clear()
                # v3.11.0 SIZINTI/KİLİT DÜZELTMESİ: eski akış 64 kaydı aşınca TÜM inflight
                # haritasını .clear() ediyordu — bu, BAŞKA BİR İSTEĞİN ELİNDEKİ canlı
                # Lock nesnesini haritadan koparıyor, ikinci istek yeni bir kilit alıp
                # aynı sayfayı AYNI ANDA probe ediyordu (tekilleştirme sessizce bozuluyordu).
                # Artık toplu temizlik YOK: eski kayıtlar 30 dakikada bir bakım döngüsünde
                # (zaman damgasına göre) seçici biçimde düşürülür.
                if len(_PROBE_INFLIGHT) > 256:
                    _cutoff = time.time() - 1800.0
                    for _k in [k for k, ts in _PROBE_INFLIGHT_TS.items() if ts < _cutoff]:
                        _PROBE_INFLIGHT.pop(_k, None)
                        _PROBE_INFLIGHT_TS.pop(_k, None)
                _PROBE_INFLIGHT_TS[inflight_key] = time.time()
                lk = _PROBE_INFLIGHT.setdefault(inflight_key, threading.Lock())
                # v3.0.0: probe çökerse bağlantı ÖLMEZ — eklentiye JSON hata gider
                # (eski davranışta traceback + kopan bağlantı, bar 'köprü yok' sanırdı)
                # v3.6.0 KİLİT ÇÖZÜMÜ: 'with lk:' SONSUZ dek bekliyordu — aynı sayfa için
                # süren bir probe (yavaş site / takılan yt-dlp) ikinci isteği DE kilitler,
                # bar 'Kaliteler hazırlanıyor...' da ASLA dolmazdı (kullanıcı raporu).
                # Artık kilit 20 sn'de bir açılır; alınamazsa HEMEN 'pending' yanıtı döner
                # (bar 3 sn sonra yeniden dener, askıda kalmaz).
                info: Optional[Dict[str, Any]] = None
                try:
                    if not lk.acquire(timeout=20):
                        self._send_json(
                            {
                                "ok": True,
                                "title": "",
                                "formats": [],
                                "ytdlp_pending": True,
                                "probe_wait": True,
                                "is_live": False,
                                "is_dvr": False,
                                "drm": False,
                            }
                        )
                        return
                    try:
                        # v3.6.0 SERT ZAMAN ASIMI: probe_formats yavaş sitelerde 2-3 dk
                        # sürebiliyordu (HLS tahmini + yt-dlp + manifest yoklama zinciri).
                        # Probe yardımcı is parçacığında kosar; 75 sn'de sonuç gelmezse HTTP
                        # yanıtı 'pending' olarak HEMEN döner — gerçek sonuç arkada bitince
                        # probe_formats kendi içinde önbelleğe yazar ve IDM_MEDIA_UPDATED ile
                        # bara duyurulur.
                        # v3.11.0 SIZINTI DÜZELTMESİ: istek başına ThreadPoolExecutor yerine
                        # düz daemon Thread kullanılır. ThreadPoolExecutor işçileri py3.9+
                        # içinde daemon DEĞİLDİR ve atexit'e kayıtlıdır — asılı bir yt-dlp
                        # probe'u daemon sürecinin KAPANMASINI engelleyebiliyordu.
                        _probe_box: Dict[str, Any] = {"info": None}
                        _probe_done = threading.Event()

                        def _probe_job() -> None:
                            try:
                                _probe_box["info"] = state.stream_engine.probe_formats(
                                    page_url=page_url,
                                    captured_streams=streams,
                                    cookies=cookies,
                                    referer=referer,
                                    user_agent=ua,
                                    use_ytdlp=use_ytdlp,
                                    force_refresh=force_refresh,
                                    abyss_enabled=bool(state.cfg.abyss_enabled),
                                    bili_cid=(payload.get("biliCid") or "").strip(),
                                )
                            except Exception as pj_exc:
                                logger.error("probe iş parçacığı hatası (%s): %s", page_url[:80], pj_exc)
                                _probe_box["info"] = None
                            finally:
                                _probe_done.set()

                        threading.Thread(target=_probe_job, name=f"probe-{uuid.uuid4().hex[:6]}", daemon=True).start()
                        if not _probe_done.wait(timeout=75):
                            logger.info("video/probe 75 sn zaman asimi (%s) — pending dönüldü", page_url[:100])
                            info = {
                                "title": "",
                                "formats": [],
                                "ytdlp_pending": True,
                                "probe_wait": True,
                                "is_live": False,
                                "is_dvr": False,
                                "drm": False,
                            }
                        else:
                            info = _probe_box["info"]
                    finally:
                        try:
                            lk.release()
                        except Exception:
                            pass
                except Exception as probe_exc:
                    logger.error("video/probe çökmesi (%s): %s", page_url[:100], probe_exc)
                    self._send_json(
                        {"ok": False, "error": f"Probe hatası: {probe_exc}", "formats": []},
                        status=500,
                    )
                    return
                # v3.4.0 ABYSS PASİF NOTU: sayfada abyss kaynakları algılandıysa ama abyss
                # KAPALIysa bar linkleri GİZLENİR ve kullanıcıya dili ne olursa olsun yerelleştirilmiş
                # aktivasyon notu gösterilir ('Yakalama & Wine Ayarları'ndan açma yönlendirmesi).
                try:
                    if isinstance(info, dict) and info.get("abyss_detected") and not state.cfg.abyss_enabled:
                        info["abyss_note"] = _daemon_i18n(state.cfg.language).t("bar.abyss_note")
                except Exception:
                    pass
                self._send_json({"ok": True, **info})
                return

            if parsed.path == "/api/video/download":
                delivery = payload.get("delivery") or "direct"
                title = (payload.get("title") or "video").strip()
                ext = (payload.get("ext") or "mp4").strip().lstrip(".")
                res_label = (payload.get("resolution") or "").strip()
                suffix_tag = f" [{res_label}]" if res_label and f"[{res_label}]" not in title else ""
                filename = sanitize_filename(f"{title}{suffix_tag}.{ext}")

                cookies = payload.get("cookies") or ""
                # ÖNEMLİ: Film sitelerindeki gömülü player iframe Referer/Origin bilgisini koru!
                referer = payload.get("streamReferer") or payload.get("referer") or payload.get("pageUrl") or ""
                origin = payload.get("streamOrigin") or payload.get("origin") or ""
                ua = payload.get("streamUserAgent") or payload.get("userAgent") or ""
                # v3.2.2: özel ad (örn. 'Video [Türkçe Altyazı].srt') EN BAŞTA uygulanır —
                # subs/direct/HLS tüm kollar doğru dosya adını kullanır.
                _early_custom = (payload.get("customName") or payload.get("custom_name") or "").strip()
                if _early_custom:
                    filename = sanitize_filename(_early_custom if "." in _early_custom else f"{_early_custom}.{ext}")

                # v3.4.0 KRİTİK DÜZELTME: direct_url YUKARI alındı — v3.2.2'de bu satır 1551'deki
                # atamadan ÖNCE kullanılıyordu (UnboundLocalError) ve FİLM SİTESİ ALTYAZILARI
                # (subs teslimi) bar'dan tıklanınca 500 çöküyordu! Kök-neden biter.
                direct_url = (payload.get("directUrl") or "").strip()

                # v3.2.2 FİLM SİTELERİ ALTYAZILARI: 'subs' teslimi — HLS segmentli/tek dosyalık
                # altyazı motorda birleştirilir + SRT'ye çevrilir; IDM NATİVE indirir.
                if delivery == "subs" and direct_url:
                    try:
                        # v3.10.0: altyazı HANGİ biçimdeyse O uzantıyla iner (kullanıcı:
                        # "1.vtt altyazısı srt diye sahte gösteriliyor"). SRT'ye çeviri
                        # yalnız .srt hedeflendiğinde motorda GERÇEKTEN yapılır.
                        _SUB_EXTS = ("srt", "vtt", "ass", "ssa", "ttml", "sbv", "sami")
                        _want_ext = (ext or "").lower()
                        if _want_ext not in _SUB_EXTS:
                            _want_ext = "vtt"
                        _base_name = re.sub(r"\.(srt|vtt|ass|ssa|ttml|sbv|sami)$", "", filename, flags=re.I)
                        tk = state.stream_engine.create_ticket(
                            source_url=direct_url,
                            filename=sanitize_filename(f"{_base_name}.{_want_ext}"),
                            mode="subs",
                            cookies_header=cookies,
                            referer=referer,
                            origin=origin,
                            user_agent=ua,
                            manifest_text=payload.get("manifestText") or "",
                            final_dir=_categorized_final_dir(filename, Path(state.cfg.download_dir)),
                        )
                        quoted_tk = urllib.parse.quote(tk.filename)
                        relay_stream = f"http://127.0.0.1:{state.cfg.http_port}/stream/{tk.ticket_id}/{quoted_tk}"
                        ok, msg = state.sender.send_download(
                            DownloadRequest(
                                url=relay_stream,
                                filename=tk.filename,
                                silent=None,
                                source="video-bar-subs",
                                referer=direct_url[:2000],
                            )
                        )
                        if ok:
                            with state.lock:
                                state.downloads_dispatched += 1
                        self._send_json({"ok": ok, "message": msg, "filename": tk.filename})
                        return
                    except Exception as subs_exc:
                        logger.warning("Altyazı biletı açılamadı: %s", subs_exc)

                # 1) Doğrudan gerçek CDN / MP4 / WebM / M4A linki mevcutsa -> v3.2.0: KOPMA-DİRİLTME
                #    RELAY biletı üzerinden IDM'ye AKITILIR. Baytlar yine IDM'den NATİVE geçer
                #    (gerçek ilerleme/hız), AMA film CDN'leri (static3027 vb.) bağlantıyı 20-40
                #    MB'ta kestiğinde relay Range + header rotasyonu + kaynak tazelemeyle
                #    KENDİLİĞİNDEN dirilir — IDM'nin bağlantısı kopmaz, indirme yarıda bitmez!
                if delivery == "direct" and direct_url:
                    # v3.10.1 (kullanıcı isteği): IDM'de LOCALHOST köprüsü değil
                    # DOSYANIN GERÇEK BAĞLANTISI görünsün. Önce gerçek CDN adresi
                    # referer/çerez/UA ile doğrudan IDM'ye verilir; IDM'ye iletilemezse
                    # kopma-diriltme relay köprüsüne düşülür (işlevsellik korunur).
                    if getattr(state.cfg, "prefer_real_urls", True):
                        try:
                            ok_d, msg_d = state.dispatch_download(
                                DownloadRequest(
                                    url=direct_url,
                                    referer=referer,
                                    origin=origin,
                                    cookies=cookies,
                                    user_agent=ua,
                                    filename=filename,
                                    source="video-bar-direct",
                                ),
                                dedup=False,
                            )
                        except Exception as direct_exc:
                            ok_d, msg_d = False, f"Gerçek URL iletilemedi: {direct_exc}"
                        if ok_d:
                            self._send_json(
                                {
                                    "ok": True,
                                    "message": msg_d,
                                    "filename": filename,
                                    "direct": True,
                                    "real_url": True,
                                }
                            )
                            return
                        logger.info("Gerçek URL ile IDM'ye iletilemedi (%s) — relay'e düşülüyor", msg_d)
                    try:
                        tk = state.stream_engine.create_ticket(
                            source_url=direct_url,
                            filename=filename,
                            mode="relay",
                            cookies_header=cookies,
                            referer=referer,
                            origin=origin,
                            user_agent=ua,
                            final_dir=_categorized_final_dir(filename, Path(state.cfg.download_dir)),
                        )
                        quoted_tk = urllib.parse.quote(tk.filename)
                        relay_stream = f"http://127.0.0.1:{state.cfg.http_port}/stream/{tk.ticket_id}/{quoted_tk}"
                        ok, msg = state.sender.send_download(
                            DownloadRequest(
                                url=relay_stream,
                                filename=tk.filename,
                                silent=None,
                                source="video-bar-relay",
                                # IDM özelliklerinde videonun GERÇEK kaynak adresi
                                referer=(direct_url or "")[:2000],
                            )
                        )
                        if ok:
                            with state.lock:
                                state.downloads_dispatched += 1
                        self._send_json({"ok": ok, "message": msg, "filename": tk.filename, "direct": True, "relay": True})
                        return
                    except Exception as relay_exc:
                        logger.warning("Relay biletı açılamadı, doğrudan IDM'ye düşülüyor: %s", relay_exc)
                    req = DownloadRequest(
                        url=direct_url,
                        referer=referer,
                        origin=origin,
                        cookies=cookies,
                        user_agent=ua,
                        filename=filename,
                        source="video-bar-direct",
                    )
                    ok, msg = state.dispatch_download(req, dedup=False)
                    self._send_json({"ok": ok, "message": msg, "filename": filename, "direct": True})
                    return

                # 2) HLS (.m3u8 / .txt / #EXTM3U) veya YouTube DASH Ayrı Ses+Video -> SIFIR ÖN BEKLEME!
                #    Bilet mikrosaniyede oluşturulur ve IDM penceresi ANINDA (<0.3 sn) açılır!
                source_url = (payload.get("sourceUrl") or payload.get("pageUrl") or "").strip()
                fmt_sel = (payload.get("formatSelector") or "").strip()
                # v2.8.0: streamlink semantiği — dvr = baştan canlı takip, live = canlı kenardan
                hls_mode = (payload.get("hlsMode") or payload.get("hls_mode") or "").strip().lower()
                if hls_mode not in ("vod", "dvr", "live"):
                    hls_mode = "vod"
                if hls_mode == "vod" and (bool(payload.get("isHls")) or looks_like_hls_url(source_url) or ".mpd" in source_url.lower()):
                    hls_mode = _auto_hls_mode(source_url, payload.get("manifestText") or "", referer, ua)
                custom_name = (payload.get("customName") or payload.get("custom_name") or "").strip()
                if custom_name:
                    filename = sanitize_filename(
                        custom_name if "." in custom_name else f"{custom_name}.{ext}"
                    )
                mux_v_url = (payload.get("muxVideoUrl") or "").strip()
                mux_a_url = (payload.get("muxAudioUrl") or "").strip()
                mux_v_hdrs = payload.get("muxVideoHeaders") or {}
                mux_a_hdrs = payload.get("muxAudioHeaders") or {}
                manifest_txt = payload.get("manifestText") or ""
                is_hls_flag = bool(payload.get("isHls")) or bool(manifest_txt) or looks_like_hls_url(source_url)

                seg_urls = [u for u in (payload.get("segmentUrls") or []) if isinstance(u, str) and u]
                seg_audio = [u for u in (payload.get("audioSegmentUrls") or []) if isinstance(u, str) and u]
                if (payload.get("delivery") or "") == "drm_blocked":
                    self._send_json(
                        {
                            "ok": False,
                            "error": "🔒 DRM korumalı içerik: Widevine/PlayReady şifreli yayınlar indirilemez "
                            "(yasal+teknik). DRM'siz içerikler tam destekli.",
                        },
                        status=451,
                    )
                    return
                abyss_slug = (payload.get("abyssSlug") or payload.get("abyss_slug") or "").strip()
                abyss_label = (payload.get("abyssLabel") or payload.get("abyss_label") or "").strip()
                sub_lang = (payload.get("subLang") or payload.get("sub_lang") or "").strip()
                if abyss_slug and not state.cfg.abyss_enabled:
                    self._send_json({"ok": False, "error": "ABYSS.TO desteği kapalı (GUI > Yakalama sayfasından kod ile açın)."}, status=403)
                    return
                if delivery == "yt_subs" and sub_lang:
                    ticket = state.stream_engine.create_ticket(
                        source_url=source_url or (payload.get("pageUrl") or ""),
                        filename=filename if filename.lower().endswith((".srt", ".vtt", ".ass")) else sanitize_filename(f"{title} [{sub_lang}].srt"),
                        mode="ytdlp",
                        format_selector="",
                        cookies_header=cookies,
                        referer=referer,
                        origin=origin,
                        user_agent=ua,
                        sub_lang=sub_lang,
                        final_dir=_categorized_final_dir(filename, Path(state.cfg.download_dir)),
                    )
                    quoted_fn = urllib.parse.quote(ticket.filename)
                    local_stream_url = f"http://127.0.0.1:{state.cfg.http_port}/stream/{ticket.ticket_id}/{quoted_fn}"
                    ok, msg = state.dispatch_download(DownloadRequest(url=local_stream_url, filename=ticket.filename, source="video-bar-subs"), dedup=False)
                    self._send_json({"ok": ok, "message": msg, "filename": ticket.filename})
                    return
                manifest_url = (payload.get("manifestUrl") or payload.get("manifest_url") or "").strip()
                if manifest_url:
                    # v2.8.8: MPD manifesti varsa VOD'u yt-dlp ile kökten çözer (ses+görüntü, 0 bayt riski yok)
                    source_url = manifest_url
                    seg_urls = []
                    seg_audio = []
                    is_hls_flag = False
                    mode = "ytdlp"
                elif seg_urls:
                    is_hls_flag = True
                    mode = "hls_native"
                else:
                    mode = "hls_native" if (is_hls_flag and not fmt_sel and not mux_v_url) else "ytdlp"
                ticket = state.stream_engine.create_ticket(
                    source_url=source_url,
                    filename=filename,
                    mode=mode,
                    format_selector=fmt_sel,
                    cookies_header=cookies,
                    referer=referer,
                    origin=origin,
                    user_agent=ua,
                    estimated_size=payload.get("filesize"),
                    mux_video_url=mux_v_url,
                    mux_audio_url=mux_a_url,
                    mux_video_headers=mux_v_hdrs if isinstance(mux_v_hdrs, dict) else {},
                    mux_audio_headers=mux_a_hdrs if isinstance(mux_a_hdrs, dict) else {},
                    manifest_text=manifest_txt,
                    is_hls=is_hls_flag,
                    hls_mode=hls_mode,
                    segment_urls=seg_urls,
                    audio_segment_urls=seg_audio,
                    size_exact=bool(payload.get("filesizeExact")),
                    final_dir=_categorized_final_dir(filename, Path(state.cfg.download_dir)),
                    abyss_slug=abyss_slug,
                    abyss_label=abyss_label,
                    sub_lang=sub_lang,
                )

                quoted_fn = urllib.parse.quote(ticket.filename)
                local_stream_url = (
                    f"http://127.0.0.1:{state.cfg.http_port}/stream/{ticket.ticket_id}/{quoted_fn}"
                )
                req = DownloadRequest(
                    url=local_stream_url,
                    filename=ticket.filename,
                    source="video-bar-mux",
                )
                ok, msg = state.dispatch_download(req, dedup=False)
                self._send_json(
                    {
                        "ok": ok,
                        "message": msg,
                        "filename": ticket.filename,
                        "stream_url": local_stream_url,
                    }
                )
                return

            self._send_json({"ok": False, "error": "Unknown endpoint"}, status=404)

        def _handle_stream(self, head_only: bool = False) -> None:
            parts = [p for p in urllib.parse.urlparse(self.path).path.split("/") if p]
            if len(parts) < 2:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            ticket_id = parts[1]
            ticket = state.stream_engine.get_ticket(ticket_id)
            job = state.stream_engine.get_job(ticket_id)
            if not ticket or not job:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            _low_fn = ticket.filename.lower()
            if _low_fn.endswith(".m4a"):
                mime = "audio/mp4"
            elif _low_fn.endswith(".vtt"):
                mime = "text/vtt; charset=utf-8"
            elif _low_fn.endswith(".srt"):
                mime = "application/x-subrip; charset=utf-8"
            elif _low_fn.endswith((".ass", ".ssa")):
                mime = "text/plain; charset=utf-8"
            elif _low_fn.endswith(".ttml"):
                mime = "application/ttml+xml; charset=utf-8"
            else:
                mime = "video/mp4"
            # KRİTİK: Python BaseHTTPRequestHandler send_header latin-1 kullanır!
            # Türkçe karakterler (ğ, ş, ı, İ) latin-1'de UnicodeEncodeError fırlatmasın diye ASCII yedek + RFC 5987 UTF-8 başlık!
            ascii_fn = ticket.filename.encode("ascii", errors="ignore").decode("ascii").strip() or "video.mp4"
            ascii_fn = ascii_fn.replace('"', "_")
            disp_fn = urllib.parse.quote(ticket.filename)
            content_disp = f"attachment; filename=\"{ascii_fn}\"; filename*=UTF-8''{disp_fn}"

            # DURUM 1: Akış dosyası tamamen birleştirilip hazırlandıysa -> Tam Content-Length ve 206 Range Desteği!
            if job.completed and job.output_file.exists() and job.output_file.stat().st_size > 0:
                total_size = job.output_file.stat().st_size
                range_hdr = (self.headers.get("Range") or "").strip()
                start_byte = 0
                end_byte = total_size - 1
                is_partial = False

                if range_hdr.startswith("bytes="):
                    m = re.match(r"bytes=(\d*)-(\d*)", range_hdr)
                    if m:
                        s_str, e_str = m.group(1), m.group(2)
                        if s_str:
                            start_byte = min(int(s_str), total_size - 1)
                        if e_str:
                            end_byte = min(int(e_str), total_size - 1)
                        if start_byte <= end_byte:
                            is_partial = True

                length = (end_byte - start_byte) + 1
                self.send_response(206 if is_partial else 200)
                self.send_header("Content-Type", mime)
                self.send_header("Accept-Ranges", "bytes")
                if is_partial:
                    self.send_header("Content-Range", f"bytes {start_byte}-{end_byte}/{total_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Disposition", content_disp)
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.flush()

                if head_only:
                    return

                try:
                    with job.output_file.open("rb") as fh:
                        fh.seek(start_byte)
                        remaining = length
                        while remaining > 0:
                            blk = fh.read(min(262_144, remaining))
                            if not blk:
                                break
                            self.wfile.write(blk)
                            remaining -= len(blk)
                        self.wfile.flush()
                        job.add_served(length)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                return

            # v2.8.5: ses+video mux bekleyen segment biletlerinde IDM'ye ancak DOĞRU dosya akar
            if ticket.wait_mux and not job.completed:
                job.wait_complete(timeout=900)

            # DURUM 2: Canlı başlayan / devam eden HLS veya YouTube DASH akışı ->
            #          SIFIR ÖN BEKLEME + HAM İKİLİ AKIŞ (Transfer-Encoding: chunked OLMADAN!):
            #          Windows IDM chunked yanıtlarda son 0\r\n\r\n gelene kadar %0'da bekletebildiği için
            #          doğrudan TCP_NODELAY + Connection: close ile ham MP4 baytlarını anında akıtıyoruz!
            # v3.2.0: boyut kesin biliniyorsa Range/206 RESUME tam desteklenir — IDM kendi
            #         bağlantısı koptuğunda (ya da kullanıcının onayıyla) KALDIĞI YERDEN
            #         kaldığı ofsetten devam edebilir (yarıda kesilme hissi biter).
            try:
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass

            # v2.8.6 RESUME: IDM duraklatıp Range ile dönerse kaldığı ofsetten akıt!
            start_off = 0
            range_hdr = (self.headers.get("Range") or "").strip()
            if range_hdr.startswith("bytes="):
                m2 = re.match(r"bytes=(\d+)-", range_hdr)
                if m2:
                    start_off = int(m2.group(1))

            total_known = bool(ticket.size_exact and ticket.estimated_size)
            total_size2 = int(ticket.estimated_size or 0)

            job.client_connected()  # v3.2.0: bağlantı sayacı (çoklu bağlantı yarışı fix)
            try:
                if 0 < start_off < total_size2 and total_known:
                    # v3.2.0 GERÇEK 206 RESUME: IDM kaldığı bayttan devam eder
                    self.send_response(206)
                    self.send_header("Content-Type", mime)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header(
                        "Content-Range", f"bytes {start_off}-{total_size2 - 1}/{total_size2}"
                    )
                    self.send_header("Content-Length", str(total_size2 - start_off))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Accel-Buffering", "no")
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Accept-Ranges", "bytes" if total_known else "none")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Accel-Buffering", "no")
                    # v2.8.4: boyut KESİN biliniyorsa (tekdüze HLS segmentleri / yt-dlp filesize) Content-Length
                    # declare et -> IDM Boyut + Kalan süre + yüzdesini GERÇEK zamanlı gösterir!
                    if total_known:
                        self.send_header("Content-Length", str(total_size2))
                self.send_header("Content-Disposition", content_disp)
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.flush()

                if head_only:
                    return

                # v3.2.0: işçi duraklatılmışsa (IDM uzun süre ayrı kaldıysa) yeniden başlat
                try:
                    job.restart_for_resume()
                except Exception:
                    pass
                try:
                    _pending = 0
                    for chunk in job.iter_bytes_from(start_off):
                        if not chunk:
                            continue
                        self.wfile.write(chunk)
                        _pending += len(chunk)
                        # v3.10.1: her 1 MB'ta bir flush (her parçada flush = kasma)
                        if _pending >= 1_048_576:
                            self.wfile.flush()
                            _pending = 0
                    try:
                        self.wfile.flush()
                    except OSError:
                        pass
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass  # v3.2.0: sayaç düşürme finally bloğunda tek yerden yapılır
                except Exception as exc:
                    logger.error("Stream aktarım hatası (%s): %s", ticket_id, exc)
                else:
                    # v2.9.11 DÜRÜSTLÜK: baytlar bitti ama job TAMAMLANMADI (motor zinciri tükendi) ->
                    # IDM'nin eksik dosyaya "İndirme tamamlandı" demesini ENGELLE: temiz kapanış
                    # yerine RST gönder, IDM bunu bağlantı hatası sayar ve doğru raporlar.
                    if not job.completed:
                        job.wait_complete(timeout=5)
                    if not job.completed:
                        logger.warning(
                            "Akış eksik bitti (%s, %s bayt) -> sahte 'tamamlandı' yerine RST",
                            ticket_id, job.served_bytes,
                        )
                        try:
                            self.connection.setsockopt(
                                socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                            )
                            self.connection.close()
                        except OSError:
                            pass
            finally:
                # v3.2.0: bağlantı her durumda sayactan düşer — kapanış normal akış sonunda da
                # olsa (IDM bağlantı çevirirken) işçi ASLA haksız yere durdurulmaz
                job.client_disconnected()

    return IdmBridgeHTTPHandler


def _read_clipboard() -> str:
    for cmd in (
        ["wl-paste", "--no-newline"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
    ):
        if shutil.which(cmd[0]):
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=1.5, check=False)
                if res.returncode == 0:
                    return res.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
    return ""


_PENDING_CONFIRMS: Dict[str, Dict[str, Any]] = {}
_PROBE_INFLIGHT: Dict[str, threading.Lock] = {}
_PROBE_INFLIGHT_TS: Dict[str, float] = {}
_LAST_FORCE_PROBE: Dict[str, float] = {}  # v3.2.2: force-refresh stampede kalkanı


def _probe_has_options(state: "DaemonState", page_url: str) -> bool:
    """v3.2.2: aynı sayfanın taze (<=600 sn) probe sonucu bar dolu seçenekler içeriyor mu?"""
    try:
        eng = state.stream_engine
        with eng._lock:
            for k, (ts, payload) in eng._probe_cache.items():
                if k.startswith(page_url + "|") and (time.time() - ts) < 600:
                    return bool(payload.get("formats"))
    except Exception:
        pass
    return False


_CONFIRM_LOCK = threading.Lock()
_LAST_EXT_POLL = 0.0


def _dialog_confirm(title: str, msg: str) -> bool:
    """v2.8.6: masaüstü onay kutusu (zenity/yad/kdialog); hiçbiri yoksa False."""
    for cmd in (
        ["zenity", "--question", "--title=" + title, "--text=" + msg],
        ["yad", "--question", "--title=" + title, "--text=" + msg],
        ["kdialog", "--title", title, "--yesno", msg],
    ):
        if shutil.which(cmd[0]):
            try:
                res = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
                return res.returncode == 0
            except (OSError, subprocess.SubprocessError):
                continue
    return False


def _finalize_confirmation(state: DaemonState, kind: str, uri: str) -> None:
    try:
        if kind == "magnet":
            state.dispatch_torrent_or_magnet(magnet_uri=uri, source="confirmed-magnet")
        else:
            state.dispatch_download(DownloadRequest(url=uri, source="confirmed-clipboard"))
    except Exception as exc:
        logger.error("Onaylı indirme başlatılamadı: %s", exc)


def request_user_confirmation(state: DaemonState, kind: str, uri: str, label: str) -> None:
    """v2.8.6: magnet/torrent otomatik yakalamada KULLANICI ONAYI:
    önce companion uzantıya (tarayıcıda confirm), yoksa masaüstü dialoguna sorulur."""
    cid = uuid.uuid4().hex[:12]
    msg = label + "\n" + uri[:160]
    with _CONFIRM_LOCK:
        _PENDING_CONFIRMS[cid] = {"kind": kind, "uri": uri, "message": msg, "born": time.time()}
    _ws_broadcast({"type": "IDM_CONFIRM", "id": cid, "kind": kind, "uri": uri, "message": msg})

    def _ask() -> None:
        # Uzantı 12 sn içinde poll yapmadıysa (tarayıcı kapalı vb.) masaüstü dialoguna düş
        time.sleep(12.0)
        with _CONFIRM_LOCK:
            still = cid in _PENDING_CONFIRMS
        if not still or time.time() - _LAST_EXT_POLL < 12.0:
            return
        if _dialog_confirm("IDM-Linux Onay", msg):
            with _CONFIRM_LOCK:
                _PENDING_CONFIRMS.pop(cid, None)
            _finalize_confirmation(state, kind, uri)
        else:
            with _CONFIRM_LOCK:
                _PENDING_CONFIRMS.pop(cid, None)

    threading.Thread(target=_ask, daemon=True).start()


def _rss_kb() -> int:
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except Exception:
        pass
    return 0


def _tail_file_lines(path: Path, n: int = 80, window: int = 131072) -> List[str]:
    """v2.9.3: dosyanın TAMAMINI değil son penceresini okur (RAM dostu log kuyruğu)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - window))
            data = fh.read()
        lines = data.decode("utf-8", errors="ignore").splitlines()
        return lines[-n:]
    except Exception:
        return []


def build_remote_log_payload(ring: List[str], log_tail: List[str], token: str, source: str = "daemon") -> Dict[str, Any]:
    """v2.9.1: PHP uzak-log sunucusuna gidecek JSON paketi."""
    return {
        "token": token,
        "source": source,
        "ts": time.time(),
        "version": __version__,
        "lines": (list(ring) + list(log_tail))[-400:],
    }


def _read_daemon_log_tail(n: int = 80) -> List[str]:
    try:
        from .config import get_cache_dir

        p = get_cache_dir(create=False) / "logs" / "daemon.log"
        if p.is_file():
            return _tail_file_lines(p, n)
    except Exception:
        pass
    return []


def flush_remote_log(state: DaemonState) -> int:
    """v2.9.1: halka + daemon.log kuyruğunu kullanıcının PHP sunucusuna POST'lar."""
    url = (state.cfg.remote_log_url or "").strip()
    token = (state.cfg.remote_log_token or "").strip()
    if not url or not token:
        return 0
    with state.lock:
        ring = list(state.diag)
        state.diag.clear()
    payload = build_remote_log_payload(ring, _read_daemon_log_tail(), token)
    if not payload["lines"]:
        return 0
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        return len(payload["lines"])
    except Exception as exc:
        logger.debug("Uzak log gönderimi başarısız: %s", exc)
        return 0


def _remote_log_loop(state: DaemonState) -> None:
    while state.running:
        time.sleep(20.0)
        try:
            if (state.cfg.remote_log_url or "").strip():
                flush_remote_log(state)
        except Exception:
            pass


def _strict_memory_purge(state: DaemonState) -> None:
    """v2.9.2 KATI BELLEK TEMİZLİĞİ: 10 dk'da bir TÜM büyüyen yapıları süpürür.
    Hangi koşul olursa olsun daemon RSS'i şişemez."""
    import gc as _gc

    now = time.time()
    try:
        with _CONFIRM_LOCK:
            for k in [k for k, v in _PENDING_CONFIRMS.items() if now - v.get("born", now) > 600]:
                _PENDING_CONFIRMS.pop(k, None)
    except Exception:
        pass
    try:
        for k in [k for k, ts in list(_PROBE_INFLIGHT_TS.items()) if now - ts > 1800]:
            _PROBE_INFLIGHT.pop(k, None)
            _PROBE_INFLIGHT_TS.pop(k, None)
    except Exception:
        pass
    try:
        from .auth_proxy import _ASSIST, _ASSIST_LOCK

        with _ASSIST_LOCK:
            for k in [k for k, v in _ASSIST.items() if (now - v.get("born", now)) > 300]:
                e = _ASSIST.pop(k, None)
                if e:
                    if e.get("fh"):
                        try:
                            e["fh"].close()
                        except Exception:
                            pass
                    try:
                        Path(e.get("path", "/dev/null")).unlink(missing_ok=True)
                    except OSError:
                        pass
    except Exception:
        pass
    try:
        state.auth_proxy.purge_old_tickets(max_age_sec=1800)
    except Exception:
        pass
    try:
        state.stream_engine.cleanup_expired_tickets(max_age_sec=1800)
        state.stream_engine.purge_caches(completed_max_age_sec=900)
    except Exception:
        pass
    try:
        with state.lock:
            if hasattr(state, "recent_urls") and state.recent_urls is not None:
                state.recent_urls.clear()
            disp = getattr(state, "recent_dispatches", None)
            if isinstance(disp, list) and len(disp) > 200:
                del disp[: len(disp) - 200]
    except Exception:
        pass
    _gc.collect()


def _rss_mb() -> int:
    try:
        return _rss_kb() // 1024
    except Exception:
        return 0


def _self_restart_daemon(state: "DaemonState") -> None:
    """v3.2.2 Bellek KALKANI: zarif self-exit -> systemd (Restart=always) saniyeler içinde
    SIFIR bellekle yeniden başlatır. Kernel OOM katliamı ve 'Bellek Sıkıntısı' bildirimi ASLA."""
    try:
        threading.Thread(target=state.torrent_bridge.shutdown_all, daemon=True).start()
        threading.Thread(target=ed2k_shutdown_all, daemon=True).start()
    except Exception:
        pass
    try:
        # v3.5.0: oynatma listesi işleri zarifçe kapatılır (yt-dlp süreçleri sonsuz kalmaz)
        threading.Thread(target=state.playlist_manager.shutdown_all, daemon=True).start()
    except Exception:
        pass
    state.running = False
    try:
        pid_file = get_cache_dir(create=False) / "daemon.pid"
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass
    logger.warning("Daemon bellek kalkanı: zarif yeniden başlatma (os._exit(0)).")
    try:
        for h in logger.handlers:
            try:
                h.flush()
            except Exception:
                pass
    except Exception:
        pass
    os._exit(0)


def _background_maintenance_loop(state: DaemonState) -> None:
    last_clip = _read_clipboard()
    last_warm_check = 0.0
    last_purge = time.time()
    over_soft_since = 0.0

    while state.running:
        now = time.time()
        # v3.2.2: 10 dk yerine 3 dk'da bir KATI süpürme (koşulsuz) — sızıntı penceresi küçüldü
        if now - last_purge >= 180.0:
            last_purge = now
            try:
                _strict_memory_purge(state)
            except Exception as exc:
                logger.debug("katı süpürme hatası: %s", exc)

        # v3.2.2 BELLEK NÖBETÇİSİ (yeniden yapıldı):
        #   RSS > 250MB -> tüm önbellekleri boşalt (GC dahil)
        #   RSS > 450MB -> 60 sn'de inmiyor VE aktif indirme yoksa -> ZARİF SELF-RESTART
        #   (systemd Restart=always saniyeler içinde sıfır bellekle kaldırır; aktif indirme
        #    varken ASLA restart etmez — indirme yarıda kesilmez.)
        rss_now = _rss_mb()
        if rss_now > 250:
            try:
                state.stream_engine.purge_caches()
                _strict_memory_purge(state)
            except Exception:
                pass
        if rss_now > 450:
            if over_soft_since == 0.0:
                over_soft_since = now
            idle = state.stream_engine.active_job_count() == 0
            if idle and (now - over_soft_since) > 60.0:
                logger.warning(
                    "Daemon RSS %sMB (limit 450MB) 60 sn'de inmedi, aktif indirme yok — bellek kalkanı devrede.",
                    rss_now,
                )
                _self_restart_daemon(state)
        else:
            over_soft_since = 0.0

        if state.cfg.keep_wine_warm and (now - last_warm_check) > 60.0:
            last_warm_check = now
            try:
                state.sender.warm_up_idm()
            except Exception as exc:
                logger.debug("Wine warm-up kontrol hatası: %s", exc)

        if state.cfg.clipboard_monitor:
            clip = _read_clipboard()
            if clip and clip != last_clip:
                last_clip = clip
                if clip.lower().startswith("magnet:?xt=urn:btih:"):
                    logger.info("Panodan Magnet yakalandı (kullanıcı onayı bekleniyor): %s", clip[:80])
                    request_user_confirmation(state, "magnet", clip, "Magnet bağlantısı indirilsin mi?")
                elif re.match(r"^https?://[^\s<>\"']+$", clip):
                    path_part = urllib.parse.urlparse(clip).path
                    ext = Path(path_part).suffix.upper().lstrip(".")
                    if ext and (ext in set(state.cfg.file_extensions) or ext == "TORRENT"):
                        logger.info("Panodan torrent/bağlantı yakalandı (onay bekleniyor): %s", clip[:80])
                        request_user_confirmation(state, "torrent_url", clip, "Panodaki bağlantı indirilsin mi?")

        time.sleep(2.0)


def is_daemon_running(cfg: Optional[IdmLinuxConfig] = None) -> bool:
    c = cfg or IdmLinuxConfig.load()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{c.http_port}/api/status", timeout=1.2) as r:
            data = json.loads(r.read().decode("utf-8"))
            return bool(data.get("ok"))
    except Exception:
        return False


def run_daemon_foreground() -> int:
    logger.info("IDM-Linux daemon başlatılıyor (v%s)...", __version__)
    try:
        return _run_daemon_foreground_inner()
    except Exception:
        # v2.9.7: çökme nedeni logs/daemon_crash.log'a düşer (teşhis için)
        import traceback

        try:
            crash = get_cache_dir(create=True) / "logs" / "daemon_crash.log"
            crash.parent.mkdir(parents=True, exist_ok=True)
            with crash.open("a", encoding="utf-8") as fh:
                fh.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                fh.write(traceback.format_exc())
        except Exception:
            pass
        logger.exception("Daemon beklenmedik şekilde çöktü")
        raise


def _run_daemon_foreground_inner() -> int:
    state = DaemonState()
    if is_daemon_running(state.cfg):
        logger.info("idm-linux-daemon zaten çalışıyor (127.0.0.1:%s).", state.cfg.http_port)
        return 0

    pid_file = get_cache_dir(create=True) / "daemon.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    try:
        http_server = ReusableThreadingHTTPServer(
            ("127.0.0.1", state.cfg.http_port),
            make_http_handler(state),
        )
    except OSError as exc:
        logger.error("HTTP Köprü portu (127.0.0.1:%s) açılamadı: %s", state.cfg.http_port, exc)
        pid_file.unlink(missing_ok=True)
        return 1

    ws_socks = start_websocket_servers(state)
    # v3.1.0: arka plan probe'u bitince tarayıcıya IDM_MEDIA_UPDATED haberi gitsin
    set_probe_done_notifier(lambda payload: _ws_broadcast(payload))
    logger.info("Hibrit Köprü HTTP/Stream API aktif: http://127.0.0.1:%s", state.cfg.http_port)

    # v3.14.1 YOUTUBE İYİLEŞTİRMESİ: yt-dlp kurulum/güncelleme işini İLK probe'a değil
    # köprü açılışına taşı. Kullanıcı lab ortamında 'yt-dlp=✗' idi ve YouTube barı
    # 'kaynak bulunamadı' diyordu — kök neden buydu. Artık köprü kalkar kalkmaz motor
    # arka planda kurulur/güncellenir; kullanıcı video açtığında hazırdır.
    try:
        from .stream_engine import ensure_ytdlp_background, find_ytdlp, ytdlp_update_due

        ensure_ytdlp_background(upgrade=bool(find_ytdlp() and ytdlp_update_due()))
    except Exception:
        pass

    # v3.2.2: policy force-install portunu her açılışta tazele (port değişse bile canlı kurulum çalışır)
    try:
        threading.Thread(
            target=register_chromium_force_install_policy,
            args=(state.cfg.http_port,),
            daemon=True,
        ).start()
    except Exception:
        pass

    threading.Thread(target=_background_maintenance_loop, args=(state,), daemon=True).start()
    threading.Thread(target=_remote_log_loop, args=(state,), daemon=True).start()

    def _shutdown(_signum: int, _frame: Any) -> None:
        state.running = False
        threading.Thread(target=state.torrent_bridge.shutdown_all, daemon=True).start()
        # v3.5.0: oynatma listesi yt-dlp süreçleri de zarifçe sonlanır
        threading.Thread(target=state.playlist_manager.shutdown_all, daemon=True).start()
        threading.Thread(target=http_server.shutdown, daemon=True).start()
        for s in ws_socks:
            try:
                s.close()
            except OSError:
                pass

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        http_server.serve_forever()
    finally:
        pid_file.unlink(missing_ok=True)
    return 0
