from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import concurrent.futures
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .config import IdmLinuxConfig, get_cache_dir, setup_logger
from .distro import find_ytdlp
from .hls_streamer import (
    build_stream_headers,
    fetch_url_bytes,
    is_hls_playlist_text,
    looks_like_hls_url,
    probe_url_is_hls,
    stream_hls_as_mp4,
)
from .wine_sender import sanitize_filename

_UA_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

logger = setup_logger("stream_engine", "daemon.log")

# v3.0.0: yt-dlp zinciri bilinen-site listesi BÜYÜTÜLDÜ — IDM'in Windows'taki binlerce-site
# iddiasına en yakın eşik: vk.ru/vkvideo.ru (yeni VK domainleri), rutube, dzen, zen, ok.ru
# alt-domainleri, dai.ly, bilibili.tv, weibo, xiaohongshu, pinterest, cda.pl, aria, vs.
KNOWN_YTDLP_SITES = (
    "youtube.com", "youtu.be", "youtube-nocookie.com", "twitch.tv", "twitter.com", "x.com",
    "instagram.com", "tiktok.com", "vimeo.com", "dailymotion.com", "dai.ly",
    "reddit.com", "redd.it", "facebook.com", "fb.watch", "vk.com", "vk.ru", "vkvideo.ru",
    "vkontakte.ru", "userapi.com", "ok.ru", "odnoklassniki.ru", "bilibili.com", "bilibili.tv",
    # v3.13.0: ok.ru progressive MP4 CDN'i (vd*.okcdn.ru) — bar bu linkleri yakalıyor
    # ama linkler DAKİKALAR içinde süre doluyor. okcdn.ru artık yt-dlp zincirine
    # yönlendirilir: tıklama ANINDA taze URL'ler çözülür ("ok.ru videoları hâlâ
    # inmiyor" şikâyetinin kök çözümü).
    "okcdn.ru",
    "b23.tv", "kick.com", "soundcloud.com", "streamable.com", "rutube.ru", "mycdn.me",
    "dzen.ru", "zen.yandex.ru", "nicovideo.jp", "nicovideo.com", "rumble.com", "odysee.com",
    "lbry.tv", "bitchute.com", "brighteon.com", "bittube.tv", "peertube", "imgur.com",
    "flickr.com", "vid.me", "mixcloud.com", "archive.org", "ted.com", "metacafe.com",
    "vine.co", "gfycat.com", "giphy.com", "tumblr.com", "pinterest.com", "pin.it",
    "linkedin.com", "sharepoint.com", "onedrive.live.com", "drive.google.com",
    "mega.nz", "mediafire.com", "sendvid.com",
    "streamin.one", "streamin.to", "vidmoly", "molystream", "hdvid", "vidhd",
    "hdplayer", "playerx", "sibnet.ru", "video.sibnet.ru", "weibo.com", "weibo.cn",
    "xiaohongshu.com", "xhslink.com", "cda.pl", "filmweb.pl", "tviplayer.iol.pt",
    "rtp.pt", "atresplayer.com", "mitele.es", "rtve.es", "raiplay.it", "ardmediathek.de",
    "zdf.de", "daserste.de", "mediathekviewweb.de", "nos.nl", "vrt.be",
    "spreaker.com", "anchor.fm", "bandcamp.com", "hearthis.at", "looperman.com",
    "trovo.live", "veoh.com", "vkplay.ru", "live.vkplay.ru", "wasd.tv",
    "openrec.tv", "iqiyi.com", "youku.com", "v.qq.com", "douyin.com", "kuaishou.com",
    "ximalaya.com", "qingting.fm", "lizhi.fm", "acfun.cn", "weverse.io", "naver.tv",
    "tving.com", "kakaotv.com", "naver.com", "soundon.fm", "firstory.fm",
)


def _is_known_ytdlp_site(url: str) -> bool:
    """v3.0.0 KRİTİK DÜZELTME: 2.9.x'te bu fonksiyonun İLK satırı return ettiği için
    altındaki _EXTRA genişletilmiş site listesi ÖLÜ KODDU — vk.ru / vkvideo.ru /
    rutube / b23.tv gibi sitelerde sayfada yakalanan akış varken yt-dlp probe'u
    HİÇ çalışmıyordu ('video bulamama' şikayetlerinin kök-nedeni).
    Artık host-birebir VE sınır-farkındalıklı substring eşleşmesi BİRLİKTE değerlendirilir."""
    if not url:
        return False
    low_url = url.lower()
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    for d in KNOWN_YTDLP_SITES:
        d = d.strip().lower()
        if not d:
            continue
        if host == d or host.endswith("." + d):
            return True
        # v3.0.0: URL içi substring (CDN/iframe domainleri: mycdn.me, vidmoly*, hdplayer vb.)
        # Sınır-farkındalıklı: 'x.com' pattern'i 'netflix.com' ile eşleşemez.
        try:
            if re.search(r"(?<![\w-])" + re.escape(d) + r"(?![\w-])", low_url):
                return True
        except re.error:
            continue
    return False


# v3.14.0: yt-dlp ASLA denememeli — bunlar dosya barındırıcıdır, video değil.
# (Kullanıcı günlüğü: gofile linki her tıklamada yt-dlp'ye veriliyor, '[Piracy]
# This website is no longer supported' gürültüsü + 3-6 sn boşa gecikme.)
NEVER_YTDLP_PROBE = ("gofile.io", "gofile.is", "gofile")


def _never_ytdlp_probe(url: str) -> bool:
    if not url:
        return False
    low_url = url.lower()
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    for d in NEVER_YTDLP_PROBE:
        d = d.strip().lower()
        if not d:
            continue
        if host == d or host.endswith("." + d):
            return True
        try:
            if re.search(r"(?<![\w-])" + re.escape(d) + r"(?![\w-])", low_url):
                return True
        except re.error:
            continue
    return False


@dataclass
class VideoFormatOption:
    id: str
    label: str
    ext: str
    resolution: str = ""
    height: int = 0
    filesize: Optional[int] = None
    delivery: str = "direct"        # "direct" = doğrudan gerçek URL IDM'ye gider | "stream_proxy" = canlı birleştirme
    direct_url: str = ""
    format_selector: str = ""
    source_url: str = ""
    stream_referer: str = ""
    stream_origin: str = ""
    stream_user_agent: str = ""
    mux_video_url: str = ""
    manifest_url: str = ""        # v2.8.8: kesfedilen MPD manifesti (yt-dlp ile kusursuz VOD)
    mux_audio_url: str = ""
    mux_video_headers: Dict[str, str] = field(default_factory=dict)
    mux_audio_headers: Dict[str, str] = field(default_factory=dict)
    manifest_text: str = ""
    is_hls: bool = False
    audio_only: bool = False
    filesize_exact: bool = False   # v2.8.4: Content-Length olarak declare edilebilir kesin boyut
    abyss_slug: str = ""           # v2.9.4: abyss.to çözücü kimliği
    abyss_label: str = ""          # v2.9.4: çözünürlük etiketi (720p...)
    sub_lang: str = ""             # v2.9.4: yt-dlp altyazı dili
    segment_urls: List[str] = field(default_factory=list)        # v2.8.5: DASH segment serisi
    audio_segment_urls: List[str] = field(default_factory=list)  # v2.8.5: ayrık ses segment serisi


@dataclass
class StreamTicket:
    ticket_id: str
    source_url: str
    filename: str
    mode: str                       # "hls_native", "fast_mux" veya "ytdlp"
    format_selector: str = ""
    cookies_header: str = ""
    referer: str = ""
    origin: str = ""
    user_agent: str = ""
    mux_video_url: str = ""
    mux_audio_url: str = ""
    mux_video_headers: Dict[str, str] = field(default_factory=dict)
    mux_audio_headers: Dict[str, str] = field(default_factory=dict)
    manifest_text: str = ""
    is_hls: bool = False
    hls_mode: str = "vod"            # "vod" | "dvr" (baştan, canlı takip) | "live" (canlı kenardan)
    backend: str = "native"          # "streamlink" | "ytdlp" | "native"
    estimated_size: Optional[int] = None
    size_exact: bool = False         # v2.8.4: boyut KESİN ise IDM'ye Content-Length declare edilir
    segment_urls: List[str] = field(default_factory=list)        # v2.8.5
    audio_segment_urls: List[str] = field(default_factory=list)  # v2.8.5
    wait_mux: bool = False           # v2.8.5: ses+video mux bitmeden IDM'ye bayt akıtma
    abyss_slug: str = ""             # v2.9.4
    abyss_label: str = ""            # v2.9.4
    sub_lang: str = ""               # v2.9.4
    created_at: float = field(default_factory=time.time)


class ActiveStreamJob:
    """
    HLS (.m3u8 / .txt / gizli .png segmentler) veya ayrık DASH (Video+Ses) akışlarını
    0 saniye ön-beklemeyle arka planda canlı büyüten ve her 64 KB'ta bir anında IDM'ye
    akıtan paylaşımlı işçi.
    """

    @property
    def completed(self) -> bool:
        return self._completed

    @completed.setter
    def completed(self, val: bool) -> None:
        # v2.8.7 BÜTÜNLÜK KORUMASI: job tamamlanıyor sanılırken dosya HTML hata sayfasıysa
        # (gofile vb. token/auth eksik) başarı YERİNE hata işaretle — bozuk dosya asla "indi" olmaz.
        if val and not getattr(self, "_completed", False):
            try:
                from .auth_proxy import looks_like_html_payload

                pth = self.output_file if self.output_file.exists() else self.stream_file
                if pth.exists():
                    with pth.open("rb") as fh:
                        head = fh.read(512)
                    if looks_like_html_payload(head, "", self.ticket.filename):
                        self.failed = True
                        self.error_msg = (
                            "Site dosya yerine HTML hata sayfası döndürdü (oturum/token gerekebilir). "
                            "Bozuk dosya kaydedilmedi."
                        )
                        logger.warning("Bütünlük koruması: %s için HTML çıktı tespit edildi.", self.ticket.filename)
                        self._completed = False
                        return
            except Exception:
                pass
        self._completed = bool(val)

    def __init__(self, ticket: StreamTicket, work_dir: Path) -> None:
        self.ticket = ticket
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(ticket.filename).suffix.lstrip(".") or "mp4"
        self.output_file = self.work_dir / f"ready.{ext}"
        self.stream_file = self.work_dir / f"live.{ext}"
        self.completed = False
        self.failed = False
        self.error_msg = ""
        self.final_size: Optional[int] = None
        self.served_bytes = 0
        self.stop_event = threading.Event()
        self.client_paused = False      # v2.9.1: IDM duraklattı/iptal etti
        self._client_back = True
        self._active_clients = 0        # v3.2.0: AÇIK IDM bağlantı sayısı (çoklu bağlantı yarışı fix)
        self.final_dir: Optional[Path] = None
        self._cond = threading.Condition()
        self._started = False
        self._tried_resolved_live = False  # v3.2.0: -J çözümleme bir kez denensin (tekrar 50 sn kayıp yok)

    def _apply_probe_cache_mux(self) -> None:
        """v3.2.0: bar'ın arka plan probe'u (/api/video/formats) zaten yt-dlp -J çalıştırdıysa
        sonucu önbellekte hazırır. İşçi, -J'yi TEKRAR çalıştırmadan mux video+ses URL'lerini
        buradan saniyeler içinde alır -> IDM anında canlı ilerlemeye başlar."""
        mgr = getattr(self, "manager", None)
        if not mgr or not hasattr(mgr, "_probe_cache"):
            return
        t = self.ticket
        page = (t.source_url or "").strip()
        if not page.startswith("http"):
            return
        best = None
        try:
            with mgr._lock:
                snapshot = list(mgr._probe_cache.items())
        except Exception:
            return
        for key, (ts, payload) in snapshot:
            if time.time() - ts > 600:
                continue
            key_page = str(key).rsplit("|", 1)[0]
            if key_page != page:
                continue
            for fmt in (payload or {}).get("formats") or []:
                mv = (fmt.get("mux_video_url") or "").strip()
                if not mv.startswith("http"):
                    continue
                sel = (fmt.get("format_selector") or "").strip()
                if t.format_selector and sel and sel != t.format_selector:
                    continue
                h = int(fmt.get("height") or 0)
                if best is None or h > best[0]:
                    best = (h, fmt)
            if best:
                break
        if not best:
            return
        fmt = best[1]
        t.mux_video_url = (fmt.get("mux_video_url") or "").strip()
        t.mux_audio_url = (fmt.get("mux_audio_url") or "").strip()
        vh = fmt.get("mux_video_headers") or {}
        ah = fmt.get("mux_audio_headers") or {}
        t.mux_video_headers = dict(vh) if isinstance(vh, dict) else {}
        t.mux_audio_headers = dict(ah) if isinstance(ah, dict) else {}
        if not t.estimated_size and fmt.get("filesize"):
            t.estimated_size = int(fmt["filesize"] or 0) or None
        if t.mux_video_url:
            logger.info("Probe önbelleğinden mux URL alındı (%s p) -> canlı mux hazır: %s", best[0], t.mux_video_url[:70])

    def stop(self) -> bool:
        """Canlı kaydı kullanıcı isteğiyle sonlandırır (dosya o ana kadar olan haliyle finalize edilir)."""
        self.stop_event.set()
        return True

    def add_served(self, n: int) -> None:
        if n > 0:
            self.served_bytes += n

    def ensure_started(self) -> None:
        with self._cond:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._run_worker, name=f"mux-{self.ticket.ticket_id[:8]}", daemon=True).start()

    def _notify_all(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def _idle_watchdog(self, procs: List[subprocess.Popen], idle_sec: float, name: str, progress: Dict[str, int]) -> threading.Event:
        """v3.1.0 SESSIZ DONMA AVINCİ: alt süreç `idle_sec` boyunca TEK BAYT bile üretmezse
        öldürülür (YouTube 403/PO-token döngülerinde ffmpeg/yt-dlp'nin sessizce takılıp
        IDM'i saatlerce 0 bayt'ta tutması tarihe karışır). progress = {"bytes": n} sözlüğü
        işçinin yazdığı baytı anlık taşır; monitör artışı görmezse süreci kapanatır."""
        kill_evt = threading.Event()

        def _monitor() -> None:
            last = progress.get("bytes", 0)
            idle = 0.0
            while not kill_evt.is_set():
                if self.stop_event.is_set():
                    for p in procs:
                        try:
                            p.kill()
                        except Exception:
                            pass
                    return
                now = progress.get("bytes", 0)
                if now != last:
                    last = now
                    idle = 0.0
                else:
                    idle += 1.0
                if idle >= idle_sec:
                    alive = [p for p in procs if p.poll() is None]
                    if alive:
                        logger.warning(
                            "%s: %s sn boyunca 0 bayt üretti -> süreç kapatılıyor, motor zinciri devralıyor (%s)",
                            name, int(idle_sec), self.ticket.source_url[:70],
                        )
                        for p in alive:
                            try:
                                p.kill()
                            except Exception:
                                pass
                    return
                time.sleep(1.0)

        threading.Thread(target=_monitor, name=f"wd-{name}-{self.ticket.ticket_id[:6]}", daemon=True).start()
        return kill_evt

    def client_connected(self) -> None:
        """v3.2.0: IDM bir bağlantı açtı — sayaç artar, zarafet penceresi ve duraklatma iptal olur.
        IDM bazen indirme ORTASINDA bağlantı çevirir (eski bağlantıyı kapatıp yenisini açar);
        eski kod bu kapanışı 'kullanıcı gitti' sanıp işçiyi 6 sn sonra durduruyordu -> kalan
        bağlantılar 0 bayt'ta donuyor ve indirme 20-40 MB'ta kesiliyordu. Sayaç ile yalnızca
        TÜM bağlantılar kapandığında zarafet penceresi başlar."""
        with self._cond:
            self._active_clients += 1
        self.client_reattached()

    def client_reattached(self) -> None:
        """v2.9.1: IDM yeniden bağlandı (devam) — zarafet penceresini iptal et."""
        self._client_back = True
        self.client_paused = False

    def client_disconnected(self, grace_sec: float = 20.0) -> None:
        """v2.9.1 + v3.2.0: IDM bağlantıyı kesti. Sayaç 0'a inerse (TÜM bağlantılar kapandı)
        grace_sec boyunca bekle (resume ihtimali), dönen yoksa işçiyi durdur.
        Böylece IDM'de duraklatılan indirme GUI'de de durur (kullanıcı kuralı)."""
        with self._cond:
            self._active_clients = max(0, self._active_clients - 1)
            last_client = self._active_clients == 0
        if not last_client:
            return
        self._client_back = False

        def _grace() -> None:
            time.sleep(grace_sec)
            if not self._client_back and not self.stop_event.is_set():
                self.client_paused = True
                self.stop_event.set()
                logger.info("IDM istemcisi ayrıldı — işçi duraklatıldı (ticket %s).", self.ticket.ticket_id[:8])
                self._notify_all()

        threading.Thread(target=_grace, daemon=True).start()

    def restart_for_resume(self) -> bool:
        """v3.2.0: işçi duraklatılmışsa (IDM duraklatma/uzun kopma) ve dosya hâlâ bitmediyse
        işçiyi SIFIRDAN başlatılabilir yapar. Yeniden başlayan işçi:
          - relay biletlerinde stream_file'daki mevcut bayttan Range ile DEVAM eder,
          - yt-dlp/ diğer motorlarda tam dosyayı yeniden üretir; tamamlandığında IDM
            kaldığı ofsetten (output_file üzerinden) eksiksiz akışa kavuşur."""
        with self._cond:
            if self._completed or self.failed:
                return False
            if not self.client_paused and not self.stop_event.is_set():
                return True  # işçi zaten çalışıyor
            self.stop_event.clear()
            self.client_paused = False
            self.failed = False
            self.error_msg = ""
            self._started = False
        logger.info("İşçi resume için yeniden başlatılıyor (ticket %s).", self.ticket.ticket_id[:8])
        self.ensure_started()
        return True

    def _run_worker(self) -> None:
        t = self.ticket
        cookie_file = cookies_header_to_netscape_file(t.cookies_header, t.source_url)
        ytdlp_bin = find_ytdlp()
        ffmpeg_bin = shutil.which("ffmpeg")

        try:
            # v3.2.2 ALTYAZI MOTORU: HLS segmentli / tek dosyalık altyazılar sıralı
            # indirilir, birleştirilir ve SRT'ye çevrilir -> IDM baytları NATİVE akar.
            if t.mode == "subs":
                self._run_subtitle_record()
                return

            # v2.9.10: TEK DOSYALIK medya (film sitesi MP4'ü, ok.ru/vk relay'i) ->
            # KOPMA-DİRİLTME döngülü köprü: sunucu ortada keserse Range ile devam eder.
            if self._is_plain_media_relay():
                if self._run_single_url_relay():
                    return
                logger.info("Tek-URL relay başarısız -> motor zinciri (%s)", t.source_url[:70])

            # v2.9.8: DASH video+ses CANLI mux — IDM ilerlemeyi anlık gösterir
            if shutil.which("ffmpeg") and (
                (t.segment_urls and t.audio_segment_urls) or (t.mux_video_url and t.mux_audio_url)
            ):
                if self._run_live_mux_record():
                    return
                logger.info("Canlı mux başarısız -> zincir (%s)", t.source_url[:70])

            # v2.9.4: abyss.to şifreli segment protokolü (kod kilidi açıkken)
            if t.abyss_slug:
                if self._run_abyss_record():
                    return
                # v2.9.9: abyss motoru susarsa ZİNCİRE düş (yakalanan HLS/MPD manifesti devralır)
                logger.info("abyss motoru başarısız (%s) -> zincir", t.abyss_slug[:20])

            # v3.2.0 YOUTUBE/ANA-SITE ÖNCELİĞİ (NATİVE İLERLEME):
            # Bilinen sitelerde SIRALAMA: 1) probe önbelleğindeki taze mux URL'leriyle CANLI
            # ffmpeg mux (IDM baytları ANINDA akar) -> 2) yt-dlp ile taze -J çözümü + canlı
            # HLS/ffmpeg motoru -> 3) yt-dlp'nin KENDİ indirmesi (--no-part ile stream_file'a
            # CANLI yazar; SABR/PO-token burada içeriden hallolur). Böylece 0 bayt donması
            # TÜM motorlarda tarihe karışır.
            if _is_known_ytdlp_site(t.source_url) or (t.format_selector and not t.mux_video_url):
                if not t.mux_video_url and not (t.segment_urls and t.audio_segment_urls):
                    self._apply_probe_cache_mux()  # v3.2.0: bar probe'unun -J sonucundan anında mux URL
                if t.mux_video_url and ffmpeg_bin and not t.format_selector:
                    if self._run_prebuilt_urls_ffmpeg_mux(ffmpeg_bin):
                        return
                    logger.info("Canlı ffmpeg-mux başarısız -> taze -J çözümüne geçiliyor (%s)", t.source_url[:70])
                if ytdlp_bin and self._run_ytdlp_resolved_live(ytdlp_bin, ffmpeg_bin, cookie_file):
                    return
                logger.info("Canlı çözümleme başarısız -> yt-dlp kaydı devralıyor (%s)", t.source_url[:70])
                if self._run_ytdlp_record_resilient():
                    return
                logger.info("yt-dlp esnek kayıt başarısız -> motor zinciri (%s)", t.source_url[:70])

            # v2.9.0 MOTOR ZİNCİRİ: başarısız motordan sonrakine otomatik geçer (0 bayt bitti)
            for eng in engine_attempt_order(t.backend, t.hls_mode, t.source_url):
                if self.stop_event.is_set():
                    return
                if eng == "streamlink":
                    if not shutil.which("streamlink"):
                        from .distro import ensure_streamlink

                        ensure_streamlink(log_fn=lambda m_: logger.info(m_))
                    if shutil.which("streamlink") and self._run_streamlink_record():
                        return
                    logger.info("Motor zinciri: streamlink başarısız -> sonraki motor (%s)", t.source_url[:70])
                elif eng == "segments":
                    if self._run_segment_merge_record():
                        return
                    logger.info("Motor zinciri: segment birleştirme başarısız -> sonraki motor (%s)", t.source_url[:70])
                elif eng == "ytdlp":
                    if self._run_ytdlp_record_resilient():
                        return
                    logger.info("Motor zinciri: yt-dlp başarısız -> sonraki motor (%s)", t.source_url[:70])
                elif eng == "yutto":
                    if self._run_yutto_record():
                        return
                    logger.info("Motor zinciri: yutto başarısız -> sonraki motor (%s)", t.source_url[:70])
                elif eng == "hls_native":
                    if (
                        t.mode in ("hls_native", "hls_ffmpeg")
                        or t.is_hls
                        or bool(t.manifest_text)
                        or looks_like_hls_url(t.source_url)
                    ) and self._run_native_parallel_hls(
                        target_url=t.source_url,
                        initial_manifest=t.manifest_text,
                        hls_mode=t.hls_mode,
                    ):
                        return
                    logger.info("Motor zinciri: yerel HLS başarısız (%s)", t.source_url[:70])

            # 1B) Uzantısı gizlenmiş (.txt / uzantısız) doğrudan HLS manifesti kontrolü
            if not t.mux_video_url and not t.format_selector and not _is_known_ytdlp_site(t.source_url):
                hdrs = build_stream_headers(t.referer, t.origin, t.cookies_header, t.user_agent)
                probed_m3u8 = probe_url_is_hls(t.source_url, hdrs)
                if probed_m3u8:
                    if self._run_native_parallel_hls(target_url=t.source_url, initial_manifest=probed_m3u8):
                        return

            # 2) ÖNCELİK 2 — ÖNCEDEN ÇÖZÜLMÜŞ URL (YouTube DASH veya HLS URL!)
            if t.mux_video_url:
                if looks_like_hls_url(t.mux_video_url):
                    if self._run_native_parallel_hls(target_url=t.mux_video_url):
                        return
                if ffmpeg_bin and self._run_prebuilt_urls_ffmpeg_mux(ffmpeg_bin):
                    return

            # 3) ÖNCELİK 3 — yt-dlp -J İLE URL ÇÖZÜP CANLI MOTORA (16x HLS veya Canlı FFmpeg) AKTARMA
            #    (v3.2.0: bilinen sitelerde zaten yukarıda denendi — tekrar 50 sn kaybetmeyelim)
            if ytdlp_bin and not self._tried_resolved_live:
                if self._run_ytdlp_resolved_live(ytdlp_bin, ffmpeg_bin, cookie_file):
                    return

            # 4) ÖNCELİK 4 — CANLI BORU HATTI (yt-dlp stdout -> ffmpeg canlı fMP4; ASLA bekletmez!)
            if ytdlp_bin:
                if self._run_ytdlp_live_pipe(ytdlp_bin, ffmpeg_bin, cookie_file):
                    return

            self._mark_failed("Video akışı kaynaktan alınamadı.")
        except Exception as exc:
            logger.error("ActiveStreamJob hatası (%s): %s", t.ticket_id, exc)
            self._mark_failed(str(exc))
        finally:
            if cookie_file:
                cookie_file.unlink(missing_ok=True)
            self._safe_archive_final_file()

    def _is_plain_media_relay(self) -> bool:
        """v2.9.10: Bilet tek dosyalık ham medya mı (MP4/WebM/MKV/M4A)? Manifest/segment/mux yoksa."""
        t = self.ticket
        if t.is_hls or t.manifest_text or t.segment_urls or t.audio_segment_urls:
            return False
        if t.mux_video_url or t.mux_audio_url or t.abyss_slug or t.format_selector:
            return False
        low = (t.source_url or "").lower().split("?", 1)[0]
        if low.endswith((".m3u8", ".mpd")) or ".m3u8/" in low or ".mpd/" in low:
            return False
        if looks_like_hls_url(t.source_url):
            return False
        return bool((t.source_url or "").startswith(("http://", "https://")))

    def _cdn_link_likely_stale(self) -> bool:
        """v3.13.0: kısa ömürlü CDN linki bayatlamış mı? (ok.ru/vk ailesi, 45 sn+)"""
        t = self.ticket
        host = ""
        try:
            host = (urllib.parse.urlparse(t.source_url or "").hostname or "").lower()
        except ValueError:
            return False
        short_lived = (
            "okcdn.ru" in host
            or "mycdn.me" in host
            or "vkuser.net" in host
            or "userapi.com" in host
        )
        if not short_lived:
            return False
        try:
            age = time.time() - float(getattr(t, "created_at", 0.0) or 0.0)
        except (TypeError, ValueError):
            age = 0.0
        return age > 45.0

    def _run_single_url_relay(self) -> bool:
        """v2.9.10 KOPMA-DİRİLTME RELAY'İ (v3.1.0 GÜÇLENDİRİLDİ): film siteleri/ok.ru gibi
        tek dosyalık kaynaklarda sunucu bağlantıyı ortada keserse (4 MB / 43 MB kesilmeleri)
        Range ile kaldığı bayttan yeniden bağlanır; Content-Length öğrenilince IDM'ye GERÇEK
        boyut declare edilir.
        v3.1.0 panzehirleri:
          - 16 deneme + yumuşak artan bekleme -> 'belli süre sonra yarıda kesilme' bitti
          - 403/404/410'da header ROTASYONU (Referer/Origin/UA varyantları) — token'lı
            CDN'ler (static3027 vb.) referer kilidi olabilir
          - 5. denemeden sonra kaynağı TAZELE: yeni URL bulunursa Range devamı taşınır"""
        t = self.ticket
        base_hdrs = build_stream_headers(t.referer, t.origin, t.cookies_header, t.user_agent)
        total: Optional[int] = None
        got = 0
        # v3.13.0 PROAKTİF TAZELEME: ok.ru/vk CDN linkleri (vd*.okcdn.ru / mycdn.me /
        # vkuser.net) dakikalar içinde SÜRE DOLAR. Bar yakalaması ile tıklama arası
        # 45+ sn geçtiyse İLK istekten ÖNCE kaynak tazelenir — 403 turu ve başarısız
        # indirme hiç yaşanmaz ("ok.ru videoları hâlâ inmiyor" şikâyetinin ikinci ayağı).
        if self._cdn_link_likely_stale() and self._refresh_source_url():
            logger.info("Süresi dolmuş CDN linki baştan tazelendi: %s", t.source_url[:90])
        # v3.2.0: işçi resume ile yeniden başladıysa stream_file'daki mevcut bayttan DEVAM et
        # (IDM duraklatma/kopma sonrası Range ile döner; sıfırdan indirme YOK)
        try:
            if self.stream_file.exists():
                pre = self.stream_file.stat().st_size
                if pre > 0:
                    got = pre
                    logger.info("Relay kaldığı yerden devam: %s bayt mevcut (%s)", got, t.source_url[:70])
        except OSError:
            pass
        attempt = 0
        max_attempts = 16
        refreshed_count = 0
        while attempt <= max_attempts:
            if self.stop_event.is_set():
                return False
            req_hdrs = dict(base_hdrs)
            # v3.1.0: header rotasyonu — kilitli CDN'lere karşı varyantlar
            if attempt >= 2:
                rot = attempt % 4
                if rot == 0 and t.referer:
                    req_hdrs.pop("Referer", None)
                    req_hdrs.pop("Origin", None)
                elif rot == 1 and t.origin:
                    req_hdrs["Referer"] = t.origin + "/"
                elif rot == 2:
                    req_hdrs["User-Agent"] = _UA_CHROME
            if got > 0:
                req_hdrs["Range"] = f"bytes={got}-"
            req = urllib.request.Request(t.source_url, headers=req_hdrs)
            clean_eof = False
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    status = getattr(resp, "status", 200) or 200
                    skip = 0
                    if got > 0 and status == 200:
                        # v2.9.11: CDN Range'i yok saydı -> gövdenin ilk `got` baytını ÇÖPE at,
                        # kalanı ekle (2.9.10'da bu durumda relay pes edip zincire düşüyordu).
                        skip = got
                    cl = (resp.headers.get("Content-Length") or "").strip()
                    cr = (resp.headers.get("Content-Range") or "").strip()
                    if cr and "/" in cr and cr.split("/")[-1].isdigit():
                        total = int(cr.split("/")[-1])
                    elif cl.isdigit() and status == 206:
                        total = got + int(cl)
                    elif cl.isdigit() and got == 0:
                        total = int(cl)
                    if total:
                        t.estimated_size = total
                        t.size_exact = True
                    mode = "ab" if got > 0 else "wb"
                    with self.stream_file.open(mode) as fh:
                        while skip > 0:
                            blk = resp.read(min(262_144, skip))
                            if not blk:
                                break
                            skip -= len(blk)
                        if skip > 0:
                            # gövde beklenenden kısaydı -> bu bağlantı çöp
                            raise IOError("Range yok sayan sunucu kısa gövde gönderdi")
                        while True:
                            if self.stop_event.is_set():
                                return False
                            blk = resp.read(262_144)
                            if not blk:
                                clean_eof = True
                                break
                            fh.write(blk)
                            fh.flush()
                            got += len(blk)
            except urllib.error.HTTPError as exc:
                logger.info("Relay HTTP %s (%s bayt, deneme %s): %s", exc.code, got, attempt, t.source_url[:70])
                # v3.1.0+v3.2.0: token süresi dolmuş olabilir -> kaynak URL'yi TAZELE (2 hakkı var)
                if (
                    exc.code in (403, 404, 410)
                    and attempt >= 3
                    and refreshed_count < 2
                    and self._refresh_source_url()
                ):
                    refreshed_count += 1
                    continue
            except Exception as exc:
                logger.info("Relay bağlantısı koptu (%s bayt): %s", got, exc)
                # v3.2.0: tekrarlayan taşima hatalarında da kaynağı tazele (statik CDN oturumu ölür)
                if (
                    got > 0
                    and attempt >= 6
                    and refreshed_count < 2
                    and self._refresh_source_url()
                ):
                    refreshed_count += 1
                    continue
            if total is not None and got >= total:
                self.completed = True
                return not self.failed
            if clean_eof and total is None:
                # v3.0.0 DÜRÜSTLÜK DOĞRULAMASI: uzunluğu bilinmeyen akış "temiz bitti"ydi AMA
                # bazı film CDN'leri bağlantıyı sessizce erken kapatır (43MB kesilmeleri).
                # Sunucuya Range: bytes={got}- sorusu sorulur:
                #   416  -> gerçekten dosya sonu         -> DÜRÜST tamam
                #   206  -> sunucuda DAHA FAZLA veri var -> total öğrenilir, indirmeye devam
                #   200  -> Range yok sayıldı; Content-Length ile karşılaştırılır
                verdict = self._relay_verify_end(got, base_hdrs)
                if verdict == "complete":
                    self.completed = True
                    return not self.failed and got > 0
                if verdict.startswith("more:"):
                    total = int(verdict.split(":", 1)[1])
                    t.estimated_size = total
                    t.size_exact = True
                    logger.info("Relay doğrulaması: dosya bitmemiş (gerçek=%s, alınan=%s) -> devam", total, got)
                    # akışa devam — aşağıdaki attempt artışı ile Range'li tur başlar
                elif attempt >= max_attempts:
                    # doğrulanamadı + deneme hakkı bitti -> eski davranış (temiz EOF = tamam)
                    self.completed = True
                    return not self.failed and got > 0
                else:
                    logger.info("Relay doğrulaması belirsiz -> yeniden bağlanıyor (%s bayt)", got)
            attempt += 1
            if attempt > max_attempts:
                break
            logger.info("Relay diriltme %s/%s -> Range bytes=%s-", attempt, max_attempts, got)
            time.sleep(min(2 * attempt, 10))
        if total is not None and got >= total:
            self.completed = True
            return not self.failed
        # v2.9.11: yarım kalan relay dosyasını SİL (sonraki motorun 'ab' yazımı bozulmasın)
        self.stream_file.unlink(missing_ok=True)
        return False

    def _run_subtitle_record(self) -> bool:
        """ALTYAZI KAYDI — kaynağı doğrular, biçimini KORUYARAK kaydeder.

        v3.10.0 (kullanıcı raporu: "srt olarak fake/yanlış gösteriyor"):
          * İçerik gerçekten altyazı mı? (HTML/404 gövdesi asla yazılmaz)
          * Biçim İÇERİKTEN tespit edilir; VTT ise ve hedef .srt ise GERÇEKTEN
            dönüştürülür (cue ayarları temizlenmiş, geçerli SRT üretilir).
          * VTT hedeflenmişse VTT olarak iner — "sahte SRT" iddiası biter.
          * ASS/TTML gibi SRT'ye çevrilemeyen biçimler OLDUĞU GİBİ iner ve
            dosya adı gerçek biçime göre düzeltilir.
        """
        from .hls_streamer import (
            assemble_subtitle_text,
            detect_subtitle_kind,
            fetch_subtitle_bytes_smart,
            normalize_srt_text,
            normalize_vtt_text,
            vtt_to_srt,
        )

        t = self.ticket
        headers = build_stream_headers(t.referer, t.origin, t.cookies_header, t.user_agent)
        try:
            txt = assemble_subtitle_text(
                t.source_url, headers, initial_text=t.manifest_text or "", smart_fetch=fetch_subtitle_bytes_smart
            )
            if not (txt or "").strip():
                raise RuntimeError("boş altyazı metni")
            kind = detect_subtitle_kind(txt)
            if not kind:
                raise RuntimeError(
                    "kaynak altyazı değil (HTML/hata sayfası) — altyazı bağlantısı ölmüş olabilir"
                )
            _EXT_OF_KIND = {"vtt": "vtt", "srt": "srt", "ass": "ass", "ssa": "ssa",
                            "ttml": "ttml", "sami": "sami", "sbv": "sbv", "mpl2": "srt"}
            want_ext = ""
            if "." in t.filename:
                want_ext = t.filename.rsplit(".", 1)[-1].lower()
            final_txt = txt
            delivered_ext = _EXT_OF_KIND.get(kind, "vtt")
            if kind == "vtt" and want_ext == "srt":
                # .srt İSTENMİŞ ve kaynak VTT -> GERÇEKTEN dönüştür
                converted = vtt_to_srt(txt)
                if not converted.strip():
                    raise RuntimeError("WebVTT → SRT dönüşümü boş sonuç verdi")
                final_txt = converted
                delivered_ext = "srt"
            elif kind == "vtt":
                final_txt = normalize_vtt_text(txt) or txt
                delivered_ext = "vtt"
            elif kind == "srt":
                final_txt = normalize_srt_text(txt) or txt
                delivered_ext = "srt"
            else:
                # ASS/SSA/TTML/SAMI/SBV/MPL2: dönüştürmüyoruz — OLDUĞU GİBİ iner
                final_txt = txt
            # Dosya adı/iş dosyası TESLİM EDİLEN biçimle birebir eşleşmeli
            base_name = t.filename.rsplit(".", 1)[0] if "." in t.filename else t.filename
            if want_ext != delivered_ext:
                t.filename = f"{base_name}.{delivered_ext}"
                logger.info("Altyazı biçimi: %s → .%s", (want_ext or "?"), delivered_ext)
            if self.output_file.suffix.lower().lstrip(".") != delivered_ext:
                self.output_file = self.work_dir / f"ready.{delivered_ext}"
            if self.stream_file.suffix.lower().lstrip(".") != delivered_ext:
                self.stream_file = self.work_dir / f"live.{delivered_ext}"
            target = delivered_ext
            data = final_txt.encode("utf-8")
            try:
                self.stream_file.unlink(missing_ok=True)
            except Exception:
                pass
            self.output_file.write_bytes(data)
            self.final_size = len(data)
            t.estimated_size = len(data)
            t.size_exact = True
            self.completed = True
            logger.info("Altyazı hazır: %s (%s bayt, biçim=%s)", t.filename, len(data), target)
            return not self.failed
        except Exception as exc:
            self.failed = True
            self.error_msg = f"Altyazı indirilemedi: {exc}"
            logger.warning("Altyazı kaydı başarısız (%s): %s", t.source_url[:80], exc)
            # v3.11.0 YOUTUBE TIMEDTEXT YEDEĞİ (0 bayt altyazı şikâyetinin kökten çözümü):
            # YouTube timedtext URL'leri IP/çerez/POT kilitli olabilir; sunucu tarafı fetch
            # 403/boş dönerse yt-dlp'nin KENDİ istemci zinciri (tv/web_safari...) altyazıyı
            # çözer. Böylece bar'da görünen YouTube altyazısı tıklanınca GERÇEK dosya verir.
            low_url = (t.source_url or "").lower()
            if "timedtext" in low_url and not self.stop_event.is_set():
                try:
                    _q = urllib.parse.parse_qs(urllib.parse.urlparse(t.source_url).query)
                    _lang = (_q.get("lang") or [""])[0]
                    _vid = (_q.get("v") or [""])[0]
                    if not _vid and t.referer:
                        _rm = re.search(r"(?:\?|&)v=([\w-]{6,})", t.referer or "")
                        if _rm:
                            _vid = _rm.group(1)
                    if _vid or "watch?v=" in low_url or "youtu.be/" in low_url:
                        t.sub_lang = _lang or "en"
                        t.source_url = (
                            f"https://www.youtube.com/watch?v={_vid}"
                            if _vid
                            else (t.referer or t.source_url)
                        )
                        self.failed = False
                        self.error_msg = ""
                        logger.info(
                            "YouTube timedtext yedeği devrede: yt-dlp altyazı kaydı (lang=%s, video=%s)",
                            t.sub_lang,
                            _vid[:12],
                        )
                        if self._run_ytdlp_record_resilient():
                            return True
                        self.failed = True
                        self.error_msg = f"Altyazı indirilemedi: {exc}"
                        logger.warning("timedtext yt-dlp yedeği de başarısız (%s)", t.source_url[:80])
                except Exception as fb_exc:
                    logger.debug("timedtext yedeği istisnası: %s", fb_exc)
            return False

    def _refresh_source_url(self) -> bool:
        """v3.1.0: relay ortasında token'ı ölen URL için TAZE kaynak bulur.
        1) Yöneticinin probe önbelleğinde aynı sayfaya ait daha yeni 'direct' kaynak var mı?
        2) yt-dlp'yi referer sayfasına çalıştırıp progressif doğrudan URL çıkarır.
        Bulunursa ticket.source_url GÜNCELLENİR ve Range devamı yeni URL'ye taşınır."""
        t = self.ticket
        mgr = getattr(self, "manager", None)
        if mgr is not None:
            try:
                with mgr._lock:
                    for key, (ts, payload) in list(mgr._probe_cache.items()):
                        if time.time() - ts > 900:
                            continue
                        page = key.split("|", 1)[0]
                        if not page or (t.referer and page not in t.referer and t.referer not in page):
                            continue
                        for fmt in payload.get("formats") or []:
                            cand = (fmt.get("direct_url") or "").strip()
                            if cand and cand != t.source_url and cand.startswith("http"):
                                logger.info("Relay URL tazeleme: probe önbelleğinden yeni kaynak alındı (%s)", cand[:80])
                                t.source_url = cand
                                return True
            except Exception:
                pass
        # yt-dlp ile referer sayfasını yeniden çöz
        page = (t.referer or "").strip()
        if not page.startswith(("http://", "https://")):
            return False
        yb = find_ytdlp()
        if not yb:
            return False
        cookie_file = cookies_header_to_netscape_file(t.cookies_header, page)
        cmd = [yb, "-J", "--no-playlist", "--no-warnings", "--no-check-certificates", "--socket-timeout", "10"]
        if cookie_file:
            cmd.extend(["--cookies", str(cookie_file)])
        if t.user_agent:
            cmd.extend(["--user-agent", t.user_agent])
        cmd.append(page)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=42, check=False)
            if res.returncode != 0 or not res.stdout.strip():
                return False
            info = json.loads(res.stdout)
            fmts = info.get("formats") or []
            best = ""
            best_score = -1.0
            for f in fmts:
                if f.get("vcodec") in (None, "none"):
                    continue
                u = f.get("url") or ""
                proto = (f.get("protocol") or "").lower()
                if not u.startswith("http") or "m3u8" in proto:
                    continue
                if f.get("acodec") not in (None, "none"):
                    score = 1000 + (f.get("tbr") or 0)  # progressif (sesli) tercih
                else:
                    score = f.get("tbr") or 0
                if score > best_score:
                    best_score = score
                    best = u
            if best and best != t.source_url:
                logger.info("Relay URL tazeleme: yt-dlp yeni kaynak buldu (%s)", best[:80])
                t.source_url = best
                return True
        except Exception as exc:
            logger.info("Relay URL tazeleme başarısız: %s", exc)
        finally:
            if cookie_file:
                cookie_file.unlink(missing_ok=True)
        return False

    def _relay_verify_end(self, got: int, hdrs: Dict[str, str]) -> str:
        """v3.0.0: 'clean_eof ama toplam bilinmiyor' durumunda dosyanın GERÇEKTEN bitip
        bitmediğini sunucuya Range sorusuyla doğrular.
        Döner: 'complete' | 'more:<toplam_bayt>' | 'unknown'"""
        if got <= 0:
            return "unknown"
        probe_hdrs = dict(hdrs)
        probe_hdrs["Range"] = f"bytes={got}-"
        req = urllib.request.Request(self.ticket.source_url, headers=probe_hdrs)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                status = getattr(resp, "status", 200) or 200
                if status == 206:
                    cr = (resp.headers.get("Content-Range") or "").strip()
                    if cr and "/" in cr:
                        tail = cr.split("/")[-1]
                        if tail.isdigit():
                            total = int(tail)
                            return "complete" if total <= got else f"more:{total}"
                    cl = (resp.headers.get("Content-Length") or "").strip()
                    if cl.isdigit() and int(cl) > 0:
                        return f"more:{got + int(cl)}"
                    return "unknown"
                if status == 200:
                    # Range yok sayıldı — gövdeyi KULLANMA (baştan gönderiyor olabilir);
                    # Content-Length tam boyutu verir
                    cl = (resp.headers.get("Content-Length") or "").strip()
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    if cl.isdigit():
                        full = int(cl)
                        if full <= got:
                            return "complete"
                        return f"more:{full}"
                    if "html" in ctype:
                        # doğrulama yanıtı hata sayfası -> elimizdeki dosya makul
                        return "complete"
                    return "unknown"
                if status in (416, 412):
                    return "complete"
                return "unknown"
        except urllib.error.HTTPError as exc:
            if exc.code in (416, 412):
                return "complete"  # Range dosya sonunun ötesinde -> indirdiğimiz kadarı TAMAM
            logger.info("Relay doğrulama HTTP %s (%s bayt)", exc.code, got)
            return "unknown"
        except Exception as exc:
            logger.info("Relay doğrulama yapılamadı (%s bayt): %s", got, exc)
            return "unknown"

    def _safe_archive_final_file(self) -> None:
        """
        v2.8.0: Stream kaynağı (canlı yayın / DVR) tamamlandığında, IDM bağlantısı tarayıcıyla
        birlikte kopmuş olsa bile kaydın TAMAMI kullanıcının İndirilenler klasörüne arşivlenir.
        """
        try:
            src = self.output_file if (self.completed and self.output_file.exists()) else self.stream_file
            if not src.exists() or src.stat().st_size < 65536:
                return
            if self.served_bytes >= src.stat().st_size - 65536:
                return  # IDM zaten tamamını aldı
            if not self.final_dir:
                return
            self.final_dir.mkdir(parents=True, exist_ok=True)
            dest = self.final_dir / self.ticket.filename
            if dest.exists():
                stem = dest.stem
                dest = self.final_dir / f"{stem}_kayit{dest.suffix}"
            shutil.copy2(src, dest)
            logger.info("Canlı kayıt arşivlendi: %s", dest)
        except Exception as exc:
            logger.debug("Canlı kayıt arşivleme hatası: %s", exc)

    def _run_native_parallel_hls(
        self,
        target_url: str,
        initial_manifest: str = "",
        override_referer: str = "",
        override_ua: str = "",
        hls_mode: str = "vod",
    ) -> bool:
        t = self.ticket
        # v3.2.0 CANLI/DVR SÜREKLİLİK: canlı yayında ffmpeg çökmesi / playlist token'inin
        # ölmesi / kısa ağ kesintileri kaydı 20-40 MB'ta BİTİRİYORDU. Canlı modlarda akış
        # susarsa kaynağı tazeleyip KALINDIĞI YERDEN (append) yeniden bağlanır.
        max_cycles = 10 if hls_mode in ("dvr", "live") else 1
        written_total = 0
        cur_target = target_url
        cur_manifest = initial_manifest
        append_mode = "wb"
        seq_tracker: Dict[str, int] = {"last": -1}  # v3.2.0: kopya segment önleme
        for cycle in range(max_cycles):
            if self.stop_event.is_set():
                break
            written_cycle = 0
            try:
                with self.stream_file.open(append_mode) as fh:
                    for chunk in stream_hls_as_mp4(
                        m3u8_url=cur_target,
                        referer=override_referer or t.referer,
                        origin=t.origin,
                        cookies=t.cookies_header,
                        user_agent=override_ua or t.user_agent,
                        initial_manifest_text=cur_manifest,
                        concurrency=16,
                        hls_mode=hls_mode,
                        resume_after=(-1 if cycle == 0 else seq_tracker.get("last", -1)),
                        seq_tracker=seq_tracker,
                        emit_init=(cycle == 0),
                    ):
                        if self.stop_event.is_set():
                            break
                        if not chunk:
                            continue
                        fh.write(chunk)
                        fh.flush()
                        written_cycle += len(chunk)
                        written_total += len(chunk)
                        self._notify_all()
            except Exception as exc:
                logger.warning("Native 16x HLS akış hatası (tur %s, %s): %s", cycle + 1, cur_target[:80], exc)
            if written_cycle > 1024 and self.stream_file.exists() and not self.stop_event.is_set():
                # dvr/live: akış sürerken bağlantı bitti mi yoksa yayın mı sona erdi?
                if hls_mode in ("dvr", "live") and cycle + 1 < max_cycles:
                    # v3.2.0: önce ENDLIST kontrolü — yayın GERÇEKTEN bittiyse kopya tur yok
                    try:
                        end_hdrs = build_stream_headers(
                            override_referer or t.referer, t.origin, t.cookies_header, override_ua or t.user_agent
                        )
                        head_txt = fetch_url_bytes(cur_target, end_hdrs, timeout=10.0, retries=1).decode(
                            "utf-8", errors="ignore"
                        )
                        if "#EXT-X-ENDLIST" in head_txt:
                            logger.info("Canlı HLS: yayın ENDLIST ile bitti — kayıt tamamlandı (tur %s)", cycle + 1)
                            break
                    except Exception:
                        pass
                    if t.source_url and self._refresh_source_url():
                        cur_target = t.source_url
                    cur_manifest = ""
                    append_mode = "ab"
                    logger.info(
                        "Canlı HLS tur %s bitti (%s bayt) -> 3 sn sonra seq=%s sonrasından devam",
                        cycle + 1, written_cycle, seq_tracker.get("last", -1),
                    )
                    if self.stop_event.wait(3.0):
                        break
                    continue
                break
            if written_cycle > 1024:
                break
            if written_cycle <= 1024 and cycle == 0:
                break  # ilk turda hiç veri yok -> zincirdeki diğer motorlara düş
        if written_total > 1024 and self.stream_file.exists():
            self.stream_file.replace(self.output_file)
            with self._cond:
                self.final_size = self.output_file.stat().st_size
                self.completed = True
                self._cond.notify_all()
            return True
        self.stream_file.unlink(missing_ok=True)
        return False

    def _run_prebuilt_urls_ffmpeg_mux(self, ffmpeg_bin: str) -> bool:
        """Önceden çözülmüş HTTP DASH video + ses URL'lerini 0.25 sn aralıklarla canlı fMP4 olarak akıtır!"""
        t = self.ticket
        ff_cmd = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-fflags",
            "+genpts+igndts",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
        ]

        def _append_input(u: str, hdr_dict: Dict[str, str]) -> None:
            lines = []
            for hk, hv in (hdr_dict or {}).items():
                lines.append(f"{hk}: {hv}\r\n")
            if t.cookies_header and "Cookie" not in (hdr_dict or {}):
                lines.append(f"Cookie: {t.cookies_header}\r\n")
            if t.referer and "Referer" not in (hdr_dict or {}):
                lines.append(f"Referer: {t.referer}\r\n")
            if lines:
                ff_cmd.extend(["-headers", "".join(lines)])
            ff_cmd.extend(["-i", u])

        _append_input(t.mux_video_url, t.mux_video_headers)
        if t.mux_audio_url:
            _append_input(t.mux_audio_url, t.mux_audio_headers)
            ff_cmd.extend(["-map", "0:v:0", "-map", "1:a:0"])

        # v3.2.0: ses KOPYALAMA önce (m4a/aac kaynakta yeniden kodlama YOK — CPU boşa
        # yorulmaz, kalite kaybı olmaz); opus/vorbis gibi mp4'e kopyalanamayan codec'de
        # aac yeniden kodlama yedeği devreye girer.
        copy_tail = ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy"] if t.mux_audio_url else ["-c:v", "copy"]
        ff_cmd_variants = [
            ff_cmd
            + copy_tail
            + [
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
            ],
            ff_cmd
            + ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac"]
            + [
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
            ],
        ]

        proc = None
        for variant in ff_cmd_variants:
            try:
                proc = subprocess.Popen(
                    variant,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=0,
                )
                break
            except OSError:
                continue
        if proc is None:
            logger.info("ffmpeg-mux başlatılamadı: %s", t.mux_video_url[:80])
            return False
        written = 0
        progress = {"bytes": 0}
        wd = self._idle_watchdog([proc], 30.0, "ffmpeg-mux", progress)
        logger.info("ffmpeg-mux başladı: %s", t.mux_video_url[:80])
        try:
            assert proc.stdout is not None
            out_fd = proc.stdout.fileno()
            with self.stream_file.open("wb") as fh:
                while True:
                    blk = os.read(out_fd, 65536)
                    if not blk:
                        break
                    fh.write(blk)
                    fh.flush()
                    written += len(blk)
                    progress["bytes"] = written
                    self._notify_all()
        finally:
            wd.set()
            if proc.stdout is not None:
                try:
                    proc.stdout.close()
                except OSError:
                    pass
            rc = proc.wait()

        if rc == 0 and written > 4096 and self.stream_file.exists():
            self.stream_file.replace(self.output_file)
            with self._cond:
                self.final_size = self.output_file.stat().st_size
                self.completed = True
                self._cond.notify_all()
            return True

        logger.info("ffmpeg-mux başarısız (rc=%s, %s bayt): %s", rc, written, t.mux_video_url[:80])
        self.stream_file.unlink(missing_ok=True)
        return False

    def _run_ytdlp_resolved_live(
        self,
        ytdlp_bin: str,
        ffmpeg_bin: Optional[str],
        cookie_file: Optional[Path],
    ) -> bool:
        """
        yt-dlp ile akışın gerçek kaynağını çözer:
        - HLS (m3u8 / m3u8_native / .txt #EXTM3U) ise DOĞRUDAN 16x yerel HLS canlı motorumuza verir!
        - HTTP DASH ise canlı FFmpeg mux motoruna verir!
        """
        self._tried_resolved_live = True  # v3.2.0: zincirde tekrar denenmesin
        t = self.ticket
        cmd = [
            ytdlp_bin,
            "-J",
            "--no-playlist",
            "--no-warnings",
            "--no-check-certificates",
            "--socket-timeout",
            "8",
        ]
        if t.format_selector:
            cmd.extend(["-f", t.format_selector])
        if cookie_file:
            cmd.extend(["--cookies", str(cookie_file)])
        if t.referer:
            cmd.extend(["--referer", t.referer])
        if t.user_agent:
            cmd.extend(["--user-agent", t.user_agent])
        cmd.append(t.source_url)

        # v3.2.0: YouTube -J çözümlemesi 20-90 sn sürebilir; 18 sn'de TIMEOUT'a düşüp canlı
        # motorları boşuna atlıyordu -> 50 sn (içeride ytdlp_record yedek duruyor)
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=50, check=False)
        if res.returncode != 0 or not res.stdout.strip():
            return False

        try:
            info = json.loads(res.stdout)
        except json.JSONDecodeError:
            return False

        req_fmts = info.get("requested_formats")
        if not req_fmts:
            single_url = info.get("url")
            req_fmts = [info] if single_url else []

        if not req_fmts:
            return False

        primary = req_fmts[0]
        p_url = (primary.get("url") or "").strip()
        p_proto = (primary.get("protocol") or "").lower()
        p_hdrs = primary.get("http_headers") or {}
        p_ref = p_hdrs.get("Referer") or t.referer or t.source_url
        p_ua = p_hdrs.get("User-Agent") or t.user_agent

        if not p_url.startswith("http"):
            return False

        # Eğer dönen kaynak HLS ise (veya gizli .txt HLS manifestiyse) -> 16x paralel canlı HLS motoru!
        if "m3u8" in p_proto or looks_like_hls_url(p_url):
            if self._run_native_parallel_hls(target_url=p_url, override_referer=p_ref, override_ua=p_ua):
                return True

        probed_hls = probe_url_is_hls(
            p_url,
            build_stream_headers(p_ref, t.origin, t.cookies_header, p_ua),
        )
        if probed_hls:
            if self._run_native_parallel_hls(
                target_url=p_url,
                initial_manifest=probed_hls,
                override_referer=p_ref,
                override_ua=p_ua,
            ):
                return True

        # Doğrudan HTTP DASH veya tekil akışsa -> canlı FFmpeg mux!
        if ffmpeg_bin and 1 <= len(req_fmts) <= 2:
            t.mux_video_url = p_url
            t.mux_video_headers = p_hdrs
            if len(req_fmts) == 2:
                t.mux_audio_url = (req_fmts[1].get("url") or "").strip()
                t.mux_audio_headers = req_fmts[1].get("http_headers") or {}
            return self._run_prebuilt_urls_ffmpeg_mux(ffmpeg_bin)

        return False

    def _run_ytdlp_live_pipe(
        self,
        ytdlp_bin: str,
        ffmpeg_bin: Optional[str],
        cookie_file: Optional[Path],
    ) -> bool:
        """
        Son çare yedek: yt-dlp -o - (stdout canlı akış) -> her 64 KB indikçe anında IDM'ye yansıtır!
        ASLA videonun bitmesini bekleyip %0'da tutmaz!
        """
        t = self.ticket
        cmd = [
            ytdlp_bin,
            "--no-playlist",
            "--no-warnings",
            "--no-part",
            "--hls-prefer-native",
            "-N",
            "16",
            "-o",
            "-",
        ]
        if t.format_selector:
            cmd.extend(["-f", t.format_selector])
        if cookie_file:
            cmd.extend(["--cookies", str(cookie_file)])
        if t.user_agent:
            cmd.extend(["--user-agent", t.user_agent])
        if t.referer:
            cmd.extend(["--referer", t.referer])
        if t.origin:
            cmd.extend(["--add-header", f"Origin:{t.origin}"])
        cmd.append(t.source_url)

        yt_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=65536,
        )

        written = 0
        procs = [yt_proc]
        progress = {"bytes": 0}
        wd = None
        if ffmpeg_bin and not t.filename.lower().endswith(".m4a"):
            ff_proc = subprocess.Popen(
                [
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
                    "-c",
                    "copy",
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
                ],
                stdin=yt_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            if yt_proc.stdout is not None:
                yt_proc.stdout.close()
            procs.append(ff_proc)
            wd = self._idle_watchdog(procs, 45.0, "yt-live-pipe", progress)
            logger.info("yt-dlp canlı boru hattı başladı (yt-dlp -> ffmpeg): %s", t.source_url[:80])
            try:
                assert ff_proc.stdout is not None
                out_fd = ff_proc.stdout.fileno()
                with self.stream_file.open("wb") as fh:
                    while True:
                        blk = os.read(out_fd, 65536)
                        if not blk:
                            break
                        fh.write(blk)
                        fh.flush()
                        written += len(blk)
                        progress["bytes"] = written
                        self._notify_all()
            finally:
                if ff_proc.stdout is not None:
                    try:
                        ff_proc.stdout.close()
                    except OSError:
                        pass
                ff_proc.wait()
                yt_proc.wait()
        else:
            wd = self._idle_watchdog(procs, 45.0, "yt-live-pipe", progress)
            logger.info("yt-dlp canlı boru hattı başladı (düz): %s", t.source_url[:80])
            try:
                assert yt_proc.stdout is not None
                with self.stream_file.open("wb") as fh:
                    while True:
                        blk = yt_proc.stdout.read(65536)
                        if not blk:
                            break
                        fh.write(blk)
                        fh.flush()
                        written += len(blk)
                        progress["bytes"] = written
                        self._notify_all()
            finally:
                if yt_proc.stdout is not None:
                    try:
                        yt_proc.stdout.close()
                    except OSError:
                        pass
                yt_proc.wait()
        if wd:
            wd.set()

        if written > 4096 and self.stream_file.exists():
            self.stream_file.replace(self.output_file)
            with self._cond:
                self.final_size = self.output_file.stat().st_size
                self.completed = True
                self._cond.notify_all()
            return True

        self.stream_file.unlink(missing_ok=True)
        return False

    def _run_streamlink_record(self) -> bool:
        """streamlink'i arka planda çalıştırır; büyüyen dosyayı anında IDM'ye akıtır (ses bozulmaz)."""
        t = self.ticket
        sl_bin = shutil.which("streamlink")
        if not sl_bin:
            return False
        hdrs = build_stream_headers(t.referer, t.origin, t.cookies_header, t.user_agent)
        cmd = build_streamlink_cmd(sl_bin, t.source_url, self.stream_file, t.hls_mode, hdrs)
        logger.info("streamlink kaydı başlatıldı: %s", " ".join(cmd[:3]) + " ... -o " + str(self.stream_file))
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            logger.warning("streamlink başlatılamadı: %s", exc)
            return False

        last_size = 0
        while proc.poll() is None:
            if self.stop_event.is_set():
                proc.terminate()
                break
            try:
                sz = self.stream_file.stat().st_size if self.stream_file.exists() else 0
            except OSError:
                sz = 0
            if sz > last_size:
                last_size = sz
                self._notify_all()
            if self.stop_event.wait(0.4):
                proc.terminate()
                break
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            last_size = self.stream_file.stat().st_size if self.stream_file.exists() else last_size
        except OSError:
            pass
        rc = proc.poll()
        stopped_by_user = self.stop_event.is_set()
        # Küçük VOD kaydı (rc=0) veya kullanıcı durdurmalı kısmi canlı kayıt da BAŞARILI sayılır
        ok_size = last_size > 0 and (rc == 0 or stopped_by_user or last_size > 65536)
        # v2.8.4 konteyner başı doğrulaması: sahte .PNG segmentli film siteleri gibi streamlink'in
        # çiğ geçirdiği bozuk payload'ları REDDET -> yerel motor (TS-ofset sökücü + remux) devralır
        head_ok = True
        if ok_size:
            try:
                with self.stream_file.open("rb") as fh:
                    head = fh.read(64)
                head_ok = head[:1] == b"\x47" or b"ftyp" in head
            except OSError:
                head_ok = False
        if ok_size and head_ok and self.stream_file.exists():
            self.stream_file.replace(self.output_file)
            with self._cond:
                self.final_size = self.output_file.stat().st_size
                self.completed = True
                self._cond.notify_all()
            return True
        return False

    def _run_segment_merge_record(self) -> bool:
        """v2.8.5: tarayıcının segment segment sunduğu DASH videolarını BAŞTAN SONA tek dosyada
        birleştirir (8 paralel bağlantı, sıralı yazım -> IDM canlı ilerleme görür).
        Ayrık ses serisi varsa ffmpeg ile muxlar (bu durumda mux bitince aktarır)."""
        t = self.ticket
        hdrs = build_stream_headers(t.referer, t.origin, t.cookies_header, t.user_agent)
        # v2.9.1: CDN'ler (ercdn vb.) tarayıcı benzeri başlıklar ister — 403'ü engelle
        if t.origin:
            hdrs.setdefault("Origin", t.origin)
        hdrs.setdefault("Accept", "*/*")
        hdrs.setdefault("Sec-Fetch-Dest", "empty")
        hdrs.setdefault("Sec-Fetch-Mode", "cors")
        hdrs.setdefault("Sec-Fetch-Site", "cross-site")
        urls = list(t.segment_urls)
        if len(urls) < 2:
            urls = extrapolate_segment_list(urls or [t.source_url], hdrs)
        if not urls:
            return False
        audio_urls = list(t.audio_segment_urls)
        if audio_urls and len(audio_urls) < 2:
            audio_urls = extrapolate_segment_list(audio_urls, hdrs)

        parts_dir = self.work_dir / "parts"
        parts_dir.mkdir(parents=True, exist_ok=True)
        audio_path = self.work_dir / "audio_series.mp4"
        # v2.9.11: ÖNCEKİ motordan kalmış yarım dosya OLAMAZ (çift yazma = bozuk video)
        self.stream_file.unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)

        def _fetch(idx_url: Tuple[int, str, str]) -> Tuple[int, str, str]:
            idx, url, kind = idx_url
            dest = parts_dir / f"{kind}_{idx:06d}.part"
            # v2.9.11: segment başına 5 deneme — TEK segment hatası dosyayı delik deşik edemez
            for attempt in range(1, 6):
                if self.stop_event.is_set():
                    return idx, kind, ""
                try:
                    rq = urllib.request.Request(url, headers=hdrs)
                    with urllib.request.urlopen(rq, timeout=30) as rr, dest.open("wb") as fh:
                        shutil.copyfileobj(rr, fh, 1024 * 256)
                    if dest.stat().st_size > 0:
                        return idx, kind, str(dest)
                except Exception as exc:
                    logger.info("Segment %s/%s deneme %s/5 hata: %s", kind, idx, attempt, exc)
                time.sleep(min(1.2 * attempt, 6))
            logger.warning("Segment kalıcı başarısız: %s %s", kind, idx)
            return idx, kind, ""

        tasks = [(i, u, "v") for i, u in enumerate(urls)]
        tasks += [(i, u, "a") for i, u in enumerate(audio_urls)]
        results: Dict[Tuple[str, int], str] = {}
        merged_bytes = 0
        gaps = 0  # v2.9.11: kalıcı indirilemeyen segment sayacı
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                futs = {ex.submit(_fetch, tk_): tk_ for tk_ in tasks}
                pending = set(futs)
                v_next, a_next = 0, 0
                v_done = len(urls) == 0
                a_done = len(audio_urls) == 0
                while pending or not (v_done and a_done):
                    done, pending = concurrent.futures.wait(pending, timeout=0.4)
                    for fut in done:
                        idx, kind, path = fut.result()
                        results[(kind, idx)] = path
                    # sıralı yazım: video
                    while ("v", v_next) in results:
                        path = results.pop(("v", v_next))
                        if path:
                            with open(path, "rb") as src, self.stream_file.open("ab") as dst:
                                shutil.copyfileobj(src, dst, 1024 * 256)
                            merged_bytes += os.path.getsize(path)
                            Path(path).unlink(missing_ok=True)
                            self._notify_all()
                        else:
                            gaps += 1
                        v_next += 1
                    if v_next >= len(urls):
                        v_done = True
                    # sıralı yazım: ses
                    while ("a", a_next) in results:
                        path = results.pop(("a", a_next))
                        if path:
                            with open(path, "rb") as src, audio_path.open("ab") as dst:
                                shutil.copyfileobj(src, dst, 1024 * 256)
                            Path(path).unlink(missing_ok=True)
                        else:
                            gaps += 1
                        a_next += 1
                    if a_next >= len(audio_urls):
                        a_done = True
                    if self.stop_event.is_set():
                        for f in pending:
                            f.cancel()
                        break
            if self.stop_event.is_set() and not v_done:
                return False
            if gaps and not self.stop_event.is_set():
                # v2.9.11: DELİKLİ DOSYA ASLA "TAMAMLANDI" OLMAZ -> motor zinciri devralır
                logger.warning(
                    "Segment birleştirme: %s eksik parça -> sahte tamamlanma engellendi (%s)",
                    gaps, t.source_url[:70],
                )
                self.stream_file.unlink(missing_ok=True)
                audio_path.unlink(missing_ok=True)
                return False
            if not self.stream_file.exists() or self.stream_file.stat().st_size == 0:
                return False
            if audio_urls and audio_path.exists() and shutil.which("ffmpeg"):
                cmd = [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-i", str(self.stream_file), "-i", str(audio_path),
                    "-c", "copy", "-movflags", "+faststart", str(self.output_file),
                ]
                res = subprocess.run(cmd, capture_output=True, timeout=600, check=False)
                if res.returncode != 0 or not self.output_file.exists():
                    self.stream_file.replace(self.output_file)
            else:
                self.stream_file.replace(self.output_file)
            with self._cond:
                self.final_size = self.output_file.stat().st_size
                self.completed = True
                self._cond.notify_all()
            return True
        except Exception as exc:
            logger.error("segment birleştirme hatası: %s", exc)
            return False

    def _run_live_mux_record(self) -> bool:
        """v2.9.8: DASH video+ses -> ffmpeg ile CANLI mux (pipe->pipe).

        IDM baytları mux edildikçe alır: anlık hız/ilerleme GERÇEK, dosya doğru.
        """
        t = self.ticket
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return False
        has_segs = bool(t.segment_urls) and bool(t.audio_segment_urls)
        has_mux = bool(t.mux_video_url) and bool(t.mux_audio_url)
        if not (has_segs or has_mux):
            return False

        audio_path = self.work_dir / "live_audio.m4a"
        audio_state = {"bytes": 0}

        def _dl_audio() -> bool:
            hdrs = t.mux_audio_headers or {"Referer": t.referer, "User-Agent": t.user_agent or _UA_CHROME}
            if has_mux:
                try:
                    rq = urllib.request.Request(t.mux_audio_url, headers=hdrs)
                    # v3.1.0: ses indirmesi TOP 150 sn — tröklenmiş googlevideo akışları
                    # mux motorunu sonsuza dek meşgul edemesin
                    with urllib.request.urlopen(rq, timeout=60) as rr, audio_path.open("wb") as fh:
                        deadline = time.time() + 150
                        while True:
                            if self.stop_event.is_set():
                                return False
                            blk = rr.read(1 << 20)
                            if not blk:
                                break
                            fh.write(blk)
                            audio_state["bytes"] += len(blk)
                            if time.time() > deadline:
                                logger.info("Ses indirmesi 150 sn sınırını aştı — mux motoru atlanıyor")
                                return False
                    return audio_path.exists() and audio_path.stat().st_size > 1024
                except Exception:
                    return False
            try:
                with audio_path.open("wb") as fh:
                    for u in t.audio_segment_urls:
                        rq = urllib.request.Request(u, headers=hdrs)
                        with urllib.request.urlopen(rq, timeout=30) as rr:
                            shutil.copyfileobj(rr, fh, 1 << 20)
                        if self.stop_event.is_set():
                            return False
                return audio_path.stat().st_size > 1024
            except Exception:
                return False

        if not _dl_audio():
            return False

        # v2.9.8: ffmpeg sürüm farklarına dayanıklı boru formatı zinciri
        cmd_variants = [
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", "pipe:0", "-i", str(audio_path),
                "-c", "copy", "-f", "mp4",
                "-movflags", "frag_keyframe+empty_moov",
                "pipe:1",
            ],
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", "pipe:0", "-i", str(audio_path),
                "-c", "copy", "-f", "mpegts",
                "pipe:1",
            ],
        ]
        proc = None
        for cmd in cmd_variants:
            try:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                break
            except OSError:
                continue
        if proc is None:
            return False

        stop_feed = threading.Event()

        def _feed() -> None:
            hdrs = t.mux_video_headers or {"Referer": t.referer, "User-Agent": t.user_agent or _UA_CHROME}
            try:
                if has_mux:
                    rq = urllib.request.Request(t.mux_video_url, headers=hdrs)
                    with urllib.request.urlopen(rq, timeout=60) as rr:
                        while not stop_feed.is_set():
                            blk = rr.read(262144)
                            if not blk:
                                break
                            proc.stdin.write(blk)
                else:
                    for u in t.segment_urls:
                        if stop_feed.is_set():
                            break
                        rq = urllib.request.Request(u, headers=hdrs)
                        with urllib.request.urlopen(rq, timeout=30) as rr:
                            shutil.copyfileobj(rr, proc.stdin, 262144)
            except Exception:
                pass
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

        feeder = threading.Thread(target=_feed, daemon=True)
        feeder.start()
        written = 0
        progress = {"bytes": 0}
        wd = self._idle_watchdog([proc], 30.0, "live-mux", progress)
        try:
            with self.stream_file.open("wb") as sf, self.output_file.open("wb") as of:
                while True:
                    blk = proc.stdout.read(262144)
                    if not blk:
                        if proc.poll() is not None:
                            break
                            break
                        if self.stop_event.is_set():
                            break
                        time.sleep(0.1)
                        continue
                    sf.write(blk)
                    of.write(blk)
                    written += len(blk)
                    progress["bytes"] = written
                    self._notify_all()
            rc = proc.wait(timeout=20)
            # v2.9.8: küçük dosyalar da geçerli (HTML çöp koruması completed-setter'da)
            ok = written > 1024 and (rc == 0 or self.stop_event.is_set())
            if ok:
                with self._cond:
                    self.final_size = written
                    self.completed = True
                    self._cond.notify_all()
            else:
                logger.info("Canlı mux yetersiz çıktı (rc=%s, %s bayt) -> zincir", rc, written)
            return ok
        except Exception:
            stop_feed.set()
            try:
                proc.kill()
            except Exception:
                pass
            return False
        finally:
            stop_feed.set()
            wd.set()

    def _run_abyss_record(self) -> bool:
        """v2.9.4: abyss.to şifreli segment indirmesi (saf-Python AES-CTR).
        v3.2.0: parçalar stream_file'a CANLI yazılır (IDM anlık ilerleme) + IDM'ye kesin
        boyut declare edilir (gerçek ilerleme yüzdesi + kalan süre)."""
        from .abyss_engine import AbyssDownloader, abyss_fetch_metadata, abyss_segment_urls

        t = self.ticket
        meta = abyss_fetch_metadata(t.abyss_slug, referer=t.source_url or t.referer)
        if not meta:
            return False
        try:
            _, _urls, total_size, _frag = abyss_segment_urls(meta, t.abyss_label)
            if total_size:
                t.estimated_size = total_size
                t.size_exact = True
        except Exception:
            pass
        dl = AbyssDownloader(
            meta=meta,
            label=t.abyss_label,
            output_file=self.stream_file,
            progress_cb=lambda nbytes: self._notify_all(),
            stop_event=self.stop_event,
        )
        if dl.run() and self.stream_file.exists() and self.stream_file.stat().st_size > 65536:
            self.stream_file.replace(self.output_file)
            with self._cond:
                self.final_size = self.output_file.stat().st_size
                self.completed = True
                self._cond.notify_all()
            return True
        return False

    def _run_yutto_record(self) -> bool:
        """v2.9.3: bilibili için yutto motoru (github.com/yutto-dev/yutto) — kuruluysa zincire girer."""
        binp = shutil.which("yutto")
        if not binp or not any(h in (self.ticket.source_url or "").lower() for h in ("bilibili.com", "b23.tv")):
            return False
        out_dir = self.work_dir / "yutto_out"
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [binp, self.ticket.source_url, "-d", str(out_dir), "--no-danmaku", "--video-quality", "128", "--audio-quality", "30280"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            return False
        last = 0
        try:
            while proc.poll() is None:
                if self.stop_event.is_set():
                    proc.terminate()
                    return False
                biggest = max((f for f in out_dir.iterdir() if f.is_file()), key=lambda f: f.stat().st_size, default=None)
                sz = biggest.stat().st_size if biggest else 0
                if sz > last:
                    last = sz
                    self._notify_all()
                if self.stop_event.wait(0.5):
                    proc.terminate()
                    return False
            biggest = max((f for f in out_dir.iterdir() if f.is_file()), key=lambda f: f.stat().st_size, default=None)
            if proc.returncode == 0 and biggest and biggest.stat().st_size > 65536:
                biggest.replace(self.output_file)
                with self._cond:
                    self.final_size = self.output_file.stat().st_size
                    self.completed = True
                    self._cond.notify_all()
                return True
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
        return False

    def _run_ytdlp_record_resilient(self) -> bool:
        """v3.1.0: yt-dlp kaydını 2 AŞAMALI istemci stratejisiyle dener:
          1) yerel varsayılan istemciler (en güncel davranış),
          2) youtube:player_client=tv_simply,tv,web_safari,mweb — YouTube bot/PO-token
             kontrolü devreye girdiğinde yedek istemcilerle aşılır.
        Site youtube değilse ikinci deneme yok (gereksiz 90 sn kayıp olmasın).
        Ayrıca -4 zorlaması: bazı IPv6 sonlu ağlarda googlevideo 403 üretir."""
        t = self.ticket
        is_yt = any(h in (t.source_url or "").lower() for h in ("youtube.com", "youtu.be", "youtube-nocookie"))
        attempts = [""]
        if is_yt:
            attempts.append(YT_FALLBACK_EXTRACTOR_ARGS)
            attempts.append("youtube:player_client=android,web_embedded")
        last_err = ""
        for idx, ex_args in enumerate(attempts, start=1):
            if self.stop_event.is_set():
                return False
            if self._run_ytdlp_record(extractor_args=ex_args, live_attempt=idx):
                return True
            last_err = self.error_msg or last_err
            logger.info("yt-dlp kayıt denemesi %s/%s başarısız (%s): %s", idx, len(attempts), t.source_url[:60], (last_err or "bilinmiyor")[:120])
        return False

    def _run_ytdlp_record(self, extractor_args: str = "", live_attempt: int = 1) -> bool:
        """v2.8.4: yt-dlp ile DASH/MPD (veya mux) kaydı; v3.2.0: çıktı DOĞRUDAN stream_file'a
        (--no-part) yazılır -> büyüyen dosya ANINDA IDM'ye akar (0 bayt donması YOK!).
        DASH bv+ba birleşiminde yt-dlp önce .fNNN parça dosyalarını indirir (IDM bu aşamada
        bekler), sonra birleştirmeyi yine stream_file'a yazar — birleştirme disk hızıyla akar.
        1. deneme canlı; sonraki denemeler (farklı istemciler) güvenlik için gizli dosyaya yazar.
        Kopmalara karşı 10 yeniden deneme + 8 paralel fragment."""
        t = self.ticket
        yb = find_ytdlp()
        if not yb:
            return False
        # v3.2.0: 1. deneme CANLI stream_file'a (boş/yoksa); doluysa veya sonraki
        # denemelerde gizli dosya kullan (IDM'in okuduğu baytları bozma!)
        live_out = self.stream_file
        try:
            if live_out.exists() and live_out.stat().st_size > 0:
                live_out = None
        except OSError:
            live_out = None
        if live_out is None or live_attempt > 1:
            out_path = self.work_dir / f"ytdlp_merged_{live_attempt}.mp4"
        else:
            out_path = live_out
        if t.sub_lang:  # v2.9.4: yalnızca altyazı dosyası indir
            out_path = self.work_dir / "yt_sub"
        cmd = [
            yb,
            "-f",
            t.format_selector or "bv*+ba/b",
            "--no-playlist",
            "--no-warnings",
            "--no-check-certificates",
            "--continue",
            "--no-part",
            "--concurrent-fragments",
            "8",
            "--retries",
            "10",
            "--fragment-retries",
            "10",
            "--socket-timeout",
            "15",
            "--retry-sleep",
            "linear=1:4",
            "--merge-output-format",
            "mp4",
            "-o",
            str(out_path),
        ]
        if extractor_args:
            cmd.extend(["--extractor-args", extractor_args])
        cookie_file = cookies_header_to_netscape_file(t.cookies_header, t.source_url)
        if cookie_file:
            cmd.extend(["--cookies", str(cookie_file)])
        if t.user_agent:
            cmd.extend(["--user-agent", t.user_agent])
        if t.referer:
            cmd.extend(["--referer", t.referer])
        if t.sub_lang:
            cmd.extend(["--write-subs", "--sub-langs", t.sub_lang, "--sub-format", "srt/best", "--skip-download"])
        cmd.append(t.source_url)
        logger.info("yt-dlp birleştirme kaydı başlatıldı: %s", t.source_url[:80])
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            logger.warning("yt-dlp başlatılamadı: %s", exc)
            return False
        part_path = out_path.with_suffix(out_path.suffix + ".part")
        last_size = 0
        try:
            while proc.poll() is None:
                if self.stop_event.is_set():
                    proc.terminate()
                    break
                try:
                    if out_path.exists():
                        sz = out_path.stat().st_size
                    elif part_path.exists():
                        sz = part_path.stat().st_size
                    else:
                        sz = 0
                except OSError:
                    sz = 0
                if sz > last_size:
                    last_size = sz
                    self._notify_all()
                if self.stop_event.wait(0.4):
                    proc.terminate()
                    break
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
            try:
                last_size = out_path.stat().st_size if out_path.exists() else last_size
            except OSError:
                pass
            rc = proc.poll()
            if t.sub_lang:  # v2.9.4: altyazı dosyasını bul ve teslim et
                subs = sorted(
                    (f for f in self.work_dir.glob("yt_sub.*") if f.suffix.lower() in (".srt", ".vtt", ".ass", ".ttml")),
                    key=lambda f: f.stat().st_size,
                    reverse=True,
                )
                if subs and rc == 0:
                    subs[0].replace(self.output_file)
                    with self._cond:
                        self.final_size = self.output_file.stat().st_size
                        self.completed = True
                        self._cond.notify_all()
                    return True
                return False
            ok = last_size > 0 and (rc == 0 or self.stop_event.is_set())
            if ok and out_path.exists():
                out_path.replace(self.output_file)
                with self._cond:
                    self.final_size = self.output_file.stat().st_size
                    self.completed = True
                    self._cond.notify_all()
                return True
            if last_size == 0 and rc != 0 and not out_path.exists():
                self.error_msg = f"yt-dlp rc={rc} (0 bayt)"
            return False
        finally:
            if cookie_file:
                cookie_file.unlink(missing_ok=True)

    def wait_complete(self, timeout: float = 600.0) -> bool:
        """v2.8.5: mux/birleştirme bitene dek bekler (wait_mux biletlerinde IDM'ye doğru dosya akar)."""
        deadline = time.time() + timeout
        with self._cond:
            while not self.completed and not self.failed and time.time() < deadline:
                self._cond.wait(timeout=1.0)
            return self.completed

    def _mark_failed(self, msg: str) -> None:
        with self._cond:
            self.failed = True
            self.error_msg = msg
            self._cond.notify_all()

    def iter_bytes_from(self, start_offset: int = 0) -> Iterator[bytes]:
        """Hem canlı büyüyen dosyadan hem de tamamlanmış dosyadan her 64 KB'ta bir anında bayt akıtır."""
        self.ensure_started()
        pos = start_offset
        while True:
            with self._cond:
                active_path = self.output_file if self.completed else self.stream_file
                size_now = active_path.stat().st_size if active_path.exists() else 0

                if pos < size_now:
                    pass
                elif self.completed or self.failed:
                    break
                else:
                    self._cond.wait(timeout=0.04)
                    continue

            active_path = self.output_file if self.completed else self.stream_file
            if not active_path.exists():
                continue
            with active_path.open("rb") as fh:
                fh.seek(pos)
                # v3.10.1 (kullanıcı: "vk indirirken kasma var"): 64 KB yerine 256 KB
                # oku — küçük parçalar hem syscall hem flush fırtınası yapıyordu.
                chunk = fh.read(262_144)
                if chunk:
                    pos += len(chunk)
                    yield chunk


_SL_FLAG_CACHE: Dict[str, frozenset] = {}


def streamlink_supported_flags(bin_path: str) -> frozenset:
    """streamlink sürümleri arasında değişen bayrak adlarını --help çıktısından önbellekler (v2.8.2)."""
    if bin_path in _SL_FLAG_CACHE:
        return _SL_FLAG_CACHE[bin_path]
    flags: set = set()
    try:
        res = subprocess.run([bin_path, "--help"], capture_output=True, text=True, timeout=8, check=False)
        for tok in (res.stdout or "").replace("\n", " ").split():
            if tok.startswith("--"):
                flags.add(tok.strip("="))
    except Exception:
        pass
    frozen = frozenset(flags)
    _SL_FLAG_CACHE[bin_path] = frozen
    return frozen


_DASH_SEG_RE = re.compile(
    r"^(?P<pre>.*?)(?P<idx>\d+)(?P<post>[^\d/]*\.(?:dash|m4s|m4v|m4a|cmfv|cmfa|chunk)(?:\?.*)?)$",
    re.I,
)


def segment_series_key(url: str) -> str:
    """v2.8.5: DASH segment URL'sinin seri anahtarı (index maskelenir). Seri değilse ''."""
    m = _DASH_SEG_RE.match(url or "")
    if not m:
        return ""
    return m.group("pre") + "#" + m.group("post")


def is_dash_segment_url(url: str) -> bool:
    return bool(segment_series_key(url))


def extrapolate_segment_list(
    seed_urls: List[str],
    headers: Optional[Dict[str, str]] = None,
    max_probe: int = 600,
    miss_stop: int = 3,
) -> List[str]:
    """v2.8.5: yakalanan segment URL'lerinden TÜM seriyi çıkarır:
    index'i 0'a doğru ve uçtan ileriye HEAD ile yoklar (art arda miss_stop başarısızlıkta durur)."""
    seeds = [u for u in seed_urls if segment_series_key(u)]
    if not seeds:
        return []
    m0 = _DASH_SEG_RE.match(seeds[0])
    pre, post = m0.group("pre"), m0.group("post")
    known = sorted({int(_DASH_SEG_RE.match(u).group("idx")) for u in seeds if _DASH_SEG_RE.match(u)})
    hdrs = dict(headers or {})
    hdrs.setdefault("User-Agent", "IDM-Linux/2.8")

    def _exists(idx: int) -> bool:
        try:
            rq = urllib.request.Request(f"{pre}{idx}{post}", headers=hdrs, method="HEAD")
            with urllib.request.urlopen(rq, timeout=5) as rr:
                return rr.status < 400
        except Exception:
            return False

    lo = min(known)
    while lo > 0 and _exists(lo - 1):
        lo -= 1
    good = list(range(lo, max(known) + 1))
    cur = max(known)
    miss = 0
    gap: List[int] = []
    while cur - lo < max_probe and miss < miss_stop:
        if _exists(cur + 1):
            good.extend(gap)
            good.append(cur + 1)
            gap = []
            cur += 1
            miss = 0
        else:
            miss += 1
            gap.append(cur + 1)
            cur += 1
    return [f"{pre}{i}{post}" for i in good]


def derive_dash_manifest_candidates(url: str) -> List[str]:
    """v2.8.8: segment URL'sinden olasi MPD/SMIL manifest adreslerini türetir.
    D-Smart GO/ercdn kalibi: .../BASE.smil/BASE=<id>-<idx>.dash?sid=... -> .../BASE.smil/BASE.mpd?sid=..."""
    cands: List[str] = []
    q = ""
    if "?" in url:
        url, q = url.split("?", 1)
        q = "?" + q
    m = re.match(r"^(?P<base>https?://.*?\.smil)/(?P<stem>[^/=]+)=[^/]+\.(?:dash|m4s|m4v)$", url)
    if m:
        base, stem = m.group("base"), m.group("stem")
        cands += [f"{base}/{stem}.mpd", f"{base}/manifest.mpd", base, f"{base}/{stem}.mpd{q}", f"{base}{q}"]
    else:
        m2 = re.match(r"^(?P<base>https?://.*?)[=/][^/]*=\w+-\d+\.(?:dash|m4s|m4v)$", url)
        if m2:
            b = m2.group("base")
            cands += [f"{b}.mpd", b, f"{b}.mpd{q}", f"{b}{q}"]
    out: List[str] = []
    for c in cands:
        if c not in out:
            out.append(c)
    return out[:6]


def probe_dash_manifest(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 4.0) -> str:
    """v2.8.8: türetilen adaylari dener; gercek MPD dönen ilk adresi verir (bos string = yok)."""
    hdrs = {"User-Agent": (headers or {}).get("User-Agent") or "IDM-Linux/2.8", "Range": "bytes=0-4095"}
    ref = (headers or {}).get("Referer")
    if ref:
        hdrs["Referer"] = ref
    for cand in derive_dash_manifest_candidates(url)[:3]:  # v2.9.1: canlıda probeyi yavaşlatma
        try:
            req = urllib.request.Request(cand, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ct = (resp.headers.get("Content-Type") or "").lower()
                head = resp.read(4096)
            if b"<MPD" in head or "dash" in ct:
                return cand
        except Exception:
            continue
    return ""


_DRM_UUIDS = (
    "edef8ba9-79d6-4ace-a3c8-27dcd51d21ed",  # Widevine
    "9a04f079-9840-4286-ab92-e65be0885f95",  # PlayReady
    "e2719d58-a985-b3c9-781a-b030af78d30e",  # FairPlay
)


def mpd_has_drm(mpd_text: str) -> bool:
    """v2.9.2: MPD Widevine/PlayReady/FairPlay korumalı mı? (DRM içerik indirilemez — NET mesaj ver)."""
    t = (mpd_text or "").lower()
    if any(u in t for u in _DRM_UUIDS):
        return True
    return "contentprotection" in t and "default_kid" in t


def fetch_mpd_full(url: str, headers: Optional[Dict[str, str]] = None, limit: int = 400_000) -> str:
    hdrs = {"User-Agent": (headers or {}).get("User-Agent") or "IDM-Linux/2.9"}
    ref = (headers or {}).get("Referer")
    if ref:
        hdrs["Referer"] = ref
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=6) as resp:
            return resp.read(limit).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def parse_mpd_segment_list(mpd_text: str, base_url: str) -> Dict[str, Any]:
    """v2.9.2: SegmentTimeline ($Time$/$Number$) ile KESİN video+ses segment listesi.
    D-Smart gibi $Time$ tabanlı CDN'lerde tahmin yerine manifest'in kendi doğrusu.

    v3.2.2 BELLEK KALKANI: canlı (dynamic) MPD'de DVR kayan penceresi saatlerce büyür ve
    SegmentTimeline'ın TAM genişletilmesi on binlerce URL dizisi = yüzlerce MB RAM demekti
    (dsmartgo izlerken daemon OOM yiyordu!). Artık:
      - dynamic MPD -> SADECE son 360 segment (kayan pencere kuyruğu; kayıt motoru zaten
        canlı manifesti kendisi takip eder, tam liste GEREKMEZ)
      - statik VOD  -> en çok 5000 segment (2 saatlik film = ~3600; yet ve güvenli)
    """
    out: Dict[str, Any] = {"video": [], "audio": []}
    if not mpd_text or "<MPD" not in mpd_text[:400]:
        return out
    is_dynamic = 'type="dynamic"' in (mpd_text[:2000] + mpd_text[-2000:]).lower() or "type='dynamic'" in (mpd_text[:2000] + mpd_text[-2000:]).lower()
    seg_cap = 360 if is_dynamic else 5000
    base = base_url.rsplit("/", 1)[0] + "/"
    for ad in re.finditer(r"(<AdaptationSet\b[^>]*>)(.*?)</AdaptationSet>", mpd_text, re.S):
        attrs_tag = ad.group(1)
        block = ad.group(2)
        is_audio = (
            'contentType="audio"' in attrs_tag
            or 'mimeType="audio/' in attrs_tag
            or ('mimeType="audio/' in block)
            or ("<AudioChannelConfiguration" in block and 'contentType="video"' not in attrs_tag)
        )
        tm = re.search(r"<SegmentTemplate\b[^>]*>", block)
        if not tm:
            continue
        tag = tm.group(0)
        media_m = re.search(r'media="([^"]+)"', tag)
        init_m = re.search(r'initialization="([^"]+)"', tag)
        if not media_m:
            continue
        reps = re.findall(r'<Representation\b[^>]*?id="([^"]+)"[^>]*?bandwidth="(\d+)"', block)
        if not reps:
            continue
        rep_id = max(reps, key=lambda r: int(r[1]))[0]
        urls: List[str] = []
        if init_m:
            urls.append(base + init_m.group(1).replace("$RepresentationID$", rep_id))
        tl = re.search(r"<SegmentTimeline\b[^>]*>(.*?)</SegmentTimeline>", block, re.S)
        if tl:
            t_cur: Optional[int] = None
            for s_tag in re.finditer(r"<S\b([^>]*)/?>", tl.group(1)):
                if len(urls) >= seg_cap:
                    break
                attrs = dict(re.findall(r'(\w+)="([^"]+)"', s_tag.group(1)))
                d = int(attrs.get("d", "0") or 0)
                r = int(attrs.get("r", "0") or 0)
                if "t" in attrs:
                    t_cur = int(attrs["t"])
                if t_cur is None:
                    t_cur = 0
                # v3.2.2: dinamik MPD'de pencerenin KUYRUĞU (en yeni segmentler) korunur;
                # statik VOD'da BAŞI korunur (indirme baştan yapılır).
                room = seg_cap - len(urls)
                if room <= 0:
                    break
                step = min(r, 4000) + 1
                if step > room:
                    t_cur += (step - room) * d if not is_dynamic else 0
                    step = room
                for _ in range(step):
                    urls.append(
                        base
                        + media_m.group(1)
                        .replace("$RepresentationID$", rep_id)
                        .replace("$Time$", str(t_cur))
                        .replace("$Number$", str(len(urls)))
                    )
                    t_cur += d
        if is_audio:
            out["audio"] = urls
        elif len(urls) > len(out["video"]):
            out["video"] = urls
    return out


def engine_attempt_order(backend: str, hls_mode: str, source_url: str = "") -> List[str]:
    """v2.9.0 MOTOR ZİNCİRİ: bir motor indiremezse DİĞERİ mutlaka denenir.
    Kullanıcı kuralı: streamlink deniyorsa yt-dlp, yt-dlp deniyorsa streamlink...
    Canlı/DVR istisnası korunur (yayınlar yalnız streamlink)."""
    if hls_mode in ("dvr", "live"):
        return ["streamlink"]
    if backend == "streamlink":
        return ["streamlink", "ytdlp", "hls_native"]
    if backend == "segments":
        return ["segments", "ytdlp", "streamlink", "hls_native"]
    if backend == "ytdlp":
        # v2.9.3: bilibili'de yutto (github.com/yutto-dev/yutto) ikinci motor olarak devrede
        if any(h in (source_url or "").lower() for h in ("bilibili.com", "b23.tv")):
            return ["ytdlp", "yutto", "streamlink", "hls_native"]
        return ["ytdlp", "streamlink", "hls_native"]
    return ["hls_native", "ytdlp", "streamlink"]


def cap_captured_streams(items: List[Dict[str, Any]], total_cap: int = 300, per_series_cap: int = 4) -> List[Dict[str, Any]]:
    """v2.8.6 BELLEK KORUMASI: sayfa yakalama listesini sınırlar.
    Segment sitelerinde binlerce parça URL'si birikirse tarayıcı çöker; seri başına birkaç örnek yeter.
    v3.2.2: dev manifestText gövdeleri de kırpılır (DVR MPD'leri saniyede büyür; 128KB yeter)."""
    if len(items) > total_cap:
        items = items[-total_cap:]
    counts: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for it in items:
        url = (it.get("url") or "").strip()
        key = segment_series_key(url) or url
        c = counts.get(key, 0)
        if key != url and c >= per_series_cap:
            continue
        counts[key] = c + 1
        mt = it.get("manifestText")
        if isinstance(mt, str) and len(mt) > 131072:
            it = dict(it)
            it["manifestText"] = mt[:131072]
        out.append(it)
    return out


def classify_manifest_live(manifest_text: str) -> Dict[str, bool]:
    """v2.8.3: HLS/M3U8 ve DASH/MPD manifestlerinin CANLI mı VOD mu olduğunu sınıflandırır.
    VOD film listesine sebepsiz DVR/canlı muamelesi yapılmasını kökten engeller."""
    out = {"live": False, "dvr": False, "vod": True}
    t = (manifest_text or "").strip()
    if not t:
        return out
    if "<MPD" in t[:400]:
        m = re.search(r'type\s*=\s*"(dynamic|static)"', t[:2000])
        dyn = bool(m and m.group(1) == "dynamic")
        out["live"] = dyn
        out["vod"] = not dyn
        out["dvr"] = dyn and ("timeShiftBufferDepth" in t or t.count("<SegmentURL") > 6)
        return out
    has_end = "#EXT-X-ENDLIST" in t
    mt = re.search(r"#EXT-X-PLAYLIST-TYPE:([A-Z]+)", t)
    vod = has_end or bool(mt and mt.group(1) == "VOD")
    out["vod"] = bool(vod)
    out["live"] = not vod
    out["dvr"] = out["live"] and t.count("#EXTINF") >= 6
    return out


def estimate_hls_total_bytes(
    manifest_text: str = "",
    manifest_url: str = "",
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, bool]:
    """v2.8.4: VOD HLS listesinde KESİN toplam boyut.
    TS segmentleri tekdüze üretilir: ilk==orta segment boyutu ise toplam = s*(n-1)+son (tam doğru!)."""
    txt = manifest_text or ""
    hdrs = dict(headers or {})
    hdrs.setdefault("User-Agent", "IDM-Linux/2.8")
    if not txt and manifest_url:
        try:
            rq = urllib.request.Request(manifest_url, headers=hdrs)
            with urllib.request.urlopen(rq, timeout=6) as rr:
                txt = rr.read(600000).decode("utf-8", "ignore")
        except Exception:
            return 0, False
    if not txt or "#EXTINF" not in txt:
        return 0, False
    lines = [ln.strip() for ln in txt.splitlines()]
    segs = [
        lines[i + 1]
        for i, ln in enumerate(lines[:-1])
        if ln.startswith("#EXTINF") and lines[i + 1] and not lines[i + 1].startswith("#")
    ]
    n = len(segs)
    if n < 3:
        return 0, False
    base = manifest_url or ""

    def _head(idx: int) -> Tuple[int, int]:
        try:
            url = urllib.parse.urljoin(base, segs[idx]) if base else segs[idx]
            rq = urllib.request.Request(url, headers=hdrs, method="HEAD")
            with urllib.request.urlopen(rq, timeout=6) as rr:
                return idx, int(rr.headers.get("Content-Length") or 0)
        except Exception:
            return idx, 0

    idxs = [0, n // 2, n - 1]
    sizes: Dict[int, int] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        for idx, sz in ex.map(_head, idxs):
            sizes[idx] = sz
    s0, sm, sl = sizes[0], sizes[n // 2], sizes[n - 1]
    if s0 > 0 and s0 == sm:
        return s0 * (n - 1) + sl, True
    return 0, False


def build_streamlink_cmd(
    streamlink_bin: str,
    source_url: str,
    out_file: Path,
    hls_mode: str = "vod",
    headers: Optional[Dict[str, str]] = None,
) -> List[str]:
    """
    v2.8.2 — streamlink kayıt komutu (kullanıcının doğruladığı semantik):
      DVR  : streamlink "<url>" best --hls-live-restart -o "<dosya>"
      Canlı: streamlink "<url>" best -o "<dosya>"
    Şifreli HLS/DASH'te anahtar/segment başlıkları --http-header ile aktarılır.
    """
    cmd = [streamlink_bin, "--force", "-l", "error"]
    supported = streamlink_supported_flags(streamlink_bin)
    # Sürüme göre bayrak adları (8.x: --stream-*, <=6.x: --hls-segment-*)
    for new_flag, old_flag, val in (
        ("--stream-segment-attempts", "--hls-segment-attempts", "5"),
        ("--stream-timeout", "--hls-segment-timeout", "15"),
        ("--hls-playlist-reload-attempts", None, "8"),
        ("--dash-manifest-reload-attempts", None, "8"),
    ):
        pick = new_flag if (not supported or new_flag in supported) else (old_flag if old_flag in supported else "")
        if pick:
            cmd.extend([pick, val])
    if hls_mode == "dvr":
        cmd.append("--hls-live-restart")
    for k, v in (headers or {}).items():
        if v:
            cmd.extend(["--http-header", f"{k}={v}"])
    cmd.extend([source_url, "best", "-o", str(out_file)])
    return cmd


def cookies_header_to_netscape_file(
    cookie_header: str,
    target_url: str,
) -> Optional[Path]:
    if not cookie_header.strip():
        return None
    parsed = urllib.parse.urlparse(target_url)
    host = (parsed.hostname or "").lstrip(".")
    if not host:
        return None
    parts = host.split(".")
    base_domain = "." + ".".join(parts[-2:]) if len(parts) >= 2 else "." + host
    secure = "TRUE" if parsed.scheme == "https" else "FALSE"
    expiry = str(int(time.time()) + 86400 * 7)

    lines = ["# Netscape HTTP Cookie File", "# Generated by idm-linux"]
    for pair in cookie_header.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue
        lines.append(f"{base_domain}\tTRUE\t/\t{secure}\t{expiry}\t{k}\t{v}")

    if len(lines) <= 2:
        return None

    tmp_dir = get_cache_dir() / "cookies"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    cfile = tmp_dir / f"ck_{uuid.uuid4().hex[:12]}.txt"
    cfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cfile.chmod(0o600)
    return cfile


def _probe_cookie_file(cookies: str, page_url: str) -> Optional[Path]:
    """v3.14.2 YouTube bot-kontrolü kök çözümü — tarayıcı oturumu fallback'i.

    YouTube'un "robot olmadığını doğrulamak için giriş yap" (Sign in to confirm
    you're not a bot) engeli çerezsiz/oturumsuz istemlerde IP itibarına dayalı
    tetiklenir; --no-sandbox ile ilgisi YOKTUR (o bayrak yalnızca Chromium'un
    kendi sandbox'ını etkiler). Kök neden: tarayıcıdan yakalanan çerez olmadan
    yt-dlp'nin istemcileri YouTube'a 'anonim bot' gibi görünür.

    Bu katman: uzantıdan yakalanan çerez varsa onu kullanır; YOKSA ve hedef
    YouTube ise, kullanıcının KENDİ tarayıcılarının (Brave/Chrome/Chromium/Edge/
    Firefox...) youtube.com oturum çerezlerini sistemden okuyup yt-dlp'ye
    'gerçek tarayıcı oturumu' sinyali verir (bot-engelinin bilinen en etkili
    kodsal aşımı). Çerez dosyası geçici: çağıran sonunda unlink eder.
    """
    if cookies:
        return cookies_header_to_netscape_file(cookies, page_url)
    low = (page_url or "").lower()
    if not any(h in low for h in ("youtube.com", "youtu.be", "youtube-nocookie.com")):
        return None
    try:
        from .browser_cookies import extract_browser_cookies_for_url

        header = extract_browser_cookies_for_url("https://www.youtube.com/")
        if header:
            jar = cookies_header_to_netscape_file(header, "https://www.youtube.com/")
            if jar:
                logger.info(
                    "yt-dlp probe: sistem tarayıcısından %d YouTube çerezi okundu "
                    "(bot-kontrol önlemi — tarayıcı oturumu fallback)",
                    header.count("="),
                )
            return jar
    except Exception as exc:
        logger.debug("tarayıcı çerez fallback hatası: %s", exc)
    return None


def format_bytes(size: Optional[int]) -> str:
    if not size or size <= 0:
        return ""
    units = ["B", "KB", "MB", "GB"]
    val = float(size)
    for u in units:
        if val < 1024.0 or u == "GB":
            return f"{val:.1f} {u}" if u != "B" else f"{int(val)} B"
        val /= 1024.0
    return ""


_YTDP_ENSURE_TRIED = False
_YTDP_ENSURE_LOCK = threading.Lock()
_YTDP_WARM = threading.Event()
_YTDP_PENDING_PAGES: List[str] = []


def wait_for_ytdlp(timeout: float = 25.0) -> Optional[str]:
    """v3.10.1: yt-dlp kurulumu sürüyorsa kısa süre bekler ve yolunu döner.

    Kullanıcı raporu: "YouTube/ok.ru hiç kaynak bulamıyor". Kök neden yt-dlp'nin
    kurulu olmamasıydı; ilk probe kurulum bitmeden dönüyordu. Artık ilk probe
    kurulumu bekler (köprü zaman aşımının altında kalacak şekilde).
    """
    found = find_ytdlp()
    if found:
        return found
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        if _YTDP_WARM.is_set():
            break
        time.sleep(0.4)
        found = find_ytdlp()
        if found:
            return found
    return find_ytdlp()


def ensure_ytdlp_background(upgrade: bool = False) -> None:
    global _YTDP_ENSURE_TRIED
    with _YTDP_ENSURE_LOCK:
        if _YTDP_ENSURE_TRIED and not upgrade:
            return
        _YTDP_ENSURE_TRIED = True

    def _job() -> None:
        try:
            from .distro import ensure_ytdlp

            ok = ensure_ytdlp(log_fn=lambda m: logger.info(m), upgrade=upgrade)
        except Exception as exc:
            logger.debug("yt-dlp otomatik kurulum atlandı: %s", exc)
            return
        if ok:
            _YTDP_WARM.set()
            # v3.10.1: motor kuruldu — bekleyen probe'lar önbellekten düşsün ve
            # bar kendini tazelesin (kullanıcı "kaynak yok" ekranında kalmasın).
            try:
                notify = _PROBE_DONE_NOTIFIER
                if callable(notify):
                    for url in list(_YTDP_PENDING_PAGES)[-8:]:
                        try:
                            notify({"type": "IDM_MEDIA_UPDATED", "pageUrl": url, "reason": "ytdlp-ready"})
                        except Exception:
                            pass
            except Exception:
                pass

    threading.Thread(target=_job, daemon=True).start()


def ytdlp_update_due() -> bool:
    """v2.9.9: son güncelleme denemesi 24 saatten eskiyse True."""
    try:
        marker = get_cache_dir(create=False) / "ytdlp_last_update"
        if not marker.exists():
            return True
        return (time.time() - marker.stat().st_mtime) > 86400
    except Exception:
        return True


def mark_ytdlp_update() -> None:
    try:
        pth = get_cache_dir(create=True) / "ytdlp_last_update"
        pth.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
    except Exception:
        pass


def _ytdlp_upgrade_window_open() -> bool:
    """v3.11.0: YouTube bot-check kırılması acil durumdur — günlük bekletmeye takılmadan
    3 saatte bir yükseltme penceresi açar (yt-dlp ekibi bu tip kırılmaları saatler içinde
    yamalar; 24 saat bekleyen kullanıcı 'kaynak hiç bulunamıyor' der)."""
    try:
        marker = get_cache_dir(create=False) / "ytdlp_last_update"
        if not marker.exists():
            return True
        return (time.time() - marker.stat().st_mtime) > 10800  # 3 saat
    except Exception:
        return True


# v3.0.0: YouTube PO-Token çağı — yt-dlp'nin kendi varsayılan istemcileri sürüm ile
# birlikte güncellenir; ZORLANMIŞ client listesi (default,tv,mweb) kırılgandır.
# 1. deneme: yt-dlp YEREL VARSAYILANLARI (bakımcıların güncel tuttuğu set)
# 2. deneme: PO-token gerektirmeyen yedek istemciler (tv_simply/tv/web_safari/mweb)
# v3.14.1: android_vr EKLENDİ — giriş gerektirmeyen, PO-token istemeyen VR istemcisi;
# oturum açılmamış ortamlarda (kanka labı) 1080p'ye kadar kaynak garantisi verir.
YT_FALLBACK_EXTRACTOR_ARGS = "youtube:player_client=tv_simply,tv,web_safari,mweb,android_vr"
# v3.4.0: PROBE için hız önceliği — tv + web_safari istemcileri POT (proof-of-origin)
# beklemeksizin yanıt verir; web_safari ayrıca 1080p'ye kadar sınırsız formattır.
YT_FAST_EXTRACTOR_ARGS = "youtube:player_client=tv,web_safari"
# v3.7.0 YARIŞ ARGÜMANLARI: player_skip=webpage,configs, innertube sayfa/veri
# adımlarını atlayarak tv & web_safari istemcilerini ~2-6 sn'ye indirir.
YT_RACE_FAST_ARGS = "youtube:player_client=tv,web_safari;player_skip=webpage,configs"
YT_RACE_SECOND_ARGS = "youtube:player_client=default;player_skip=webpage,configs"


def _parse_probe_output(returncode: int, out: str, err: str) -> Tuple[Any, str, bool]:
    """v3.7.0: yt-dlp süreci çıktısını JSON'a çevirir.
    Döner: (info_dict | None, hata_metni, drm_flag)."""
    drm_flag = False
    low_err = (err or "").lower()
    if "drm" in low_err or "widevine" in low_err or "fairplay" in low_err:
        drm_flag = True
    if returncode != 0 or not (out or "").strip():
        tail = (err or "").strip()[-300:] or f"rc={returncode}"
        return None, tail, drm_flag
    try:
        return json.loads(out), "", drm_flag
    except json.JSONDecodeError as jexc:
        return None, f"JSON parse hatası: {jexc}", drm_flag


def _race_ytdlp_cmds(
    cmds: List[List[str]],
    timeouts: List[int],
) -> Tuple[Optional[Dict[str, Any]], str, bool]:
    """v3.7.0 PARALEL YARIŞ PROBU — 'video kaynağı aşırı geç bulunuyor / hiç
    bulunamıyor' şikayetinin kökten çözümü.

    Eski yöntem: istemci setleri SIRALI deniyordu (40+45+50 = 135 sn'e kadar
    bekleme; YouTube bot-kontrolü ilk denemeyi yutunca bar boş kalıyordu).
    Yeni yöntem: TÜM komutlar AYNI ANDA başlatılır; GEÇERLİ JSON üreten İLK
    süreç yarışı kazanır, kalanların üzerine kill atılır. En hızlı istemci
    (tv/web_safari + player_skip) tipik olarak 2-6 sn içinde döner.
    Kazanan tam -J info_dict'i olduğu için 4K/altyazı listesi eksiksiz gelir.
    """
    procs: List[subprocess.Popen] = []
    results: List[Optional[Tuple[Any, str, bool]]] = [None] * len(cmds)
    done_flags = [False] * len(cmds)
    race_start = time.time()

    def _runner(idx: int) -> None:
        proc = None
        try:
            proc = subprocess.Popen(
                cmds[idx],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            procs.append(proc)
            try:
                # ÖNEMLİ: communicate() boru tamponunu sürekli boşaltır — büyük
                # YouTube -J çıktısında (1-2 MB) proc.wait() KİLİTLENİRDİ.
                out, err = proc.communicate(timeout=max(15, timeouts[idx]))
                results[idx] = _parse_probe_output(proc.returncode, out or "", err or "")
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.communicate(timeout=2)
                except Exception:
                    pass
                results[idx] = (None, f"TIMEOUT {timeouts[idx]}s", False)
            done_flags[idx] = True
        except Exception as exc:
            results[idx] = (None, f"{type(exc).__name__}: {exc}", False)
            done_flags[idx] = True

    for i, cmd in enumerate(cmds):
        th = threading.Thread(target=_runner, args=(i,), daemon=True)
        th.start()

    # Kazananı bekle: en uzun timeout + 4 sn pay; her 0.15 sn'de sonuç kontrolü
    deadline = time.time() + max(timeouts) + 4.0
    winner: Optional[Tuple[Any, str, bool]] = None
    last_err = ""
    while time.time() < deadline:
        for i, res in enumerate(results):
            if res is None or not done_flags[i]:
                continue
            info, err_txt, drm = res
            if info is not None:
                winner = res
                break
            # bu istemci başarısız — hatayı kaydet, diğer istemci hâlâ yarışıyor
            if err_txt:
                last_err = err_txt
            results[i] = None
        if winner is not None:
            break
        if all(done_flags):
            break
        time.sleep(0.15)

    # kalan süreçleri temizle
    for p in procs:
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass
    for p in procs:
        try:
            p.wait(timeout=1.5)
        except Exception:
            pass

    if winner is not None:
        info, _err, drm = winner
        logger.info(
            "Yarış probe kazandı: %.1f sn'de geçerli JSON (%s)",
            time.time() - race_start,
            "youtube" if "youtube" in (cmds[0][-1] or "").lower() else "site",
        )
        return info, "", drm
    return None, last_err, False


def _run_ytdlp_probe(
    ytdlp_bin: str,
    page_url: str,
    cookie_file: Optional[Path],
    user_agent: str = "",
    referer: str = "",
) -> Tuple[Optional[Dict[str, Any]], str, bool]:
    """v3.7.0 YARIŞ TABANLI yt-dlp probe'u (eski 3'lü sıralı zincirin yerini aldı).

    YouTube: İKİ istemci seti AYNI ANDA yarıştırılır —
      1) tv,web_safari + player_skip=webpage,configs   [30 sn, tipik kazanan 2-6 sn]
      2) default + player_skip=webpage,configs         [50 sn, bot-kontrolü aşan]
    Geçerli JSON üreten İLK süreç kazanır, diğerine kill atılır. Her ikisi de
    başarısızsa eski geniş yedek set (tv_simply,tv,web_safari,mweb) TEK deneme
    olarak çalışır.
    Diğer siteler: tek deneme 55 sn (extractor-args yalnız YouTube'a etki eder,
    tekrar tekrar denemenin anlamı yoktu — gereksiz 90 sn gecikme biter).
    Döner: (info_dict | None, hata_metni | "", drm_flag)
    """
    is_youtube = any(h in (page_url or "").lower() for h in ("youtube.com", "youtu.be", "youtube-nocookie.com"))
    drm_flag = False
    last_err = ""

    def _build_cmd(extractor_args: str) -> List[str]:
        cmd = [
            ytdlp_bin,
            "-J",
            "--no-playlist",
            "--lazy-playlist",
            "--no-warnings",
            "--no-check-certificates",
            "--socket-timeout",
            "12",
            "--extractor-retries",
            "2",
        ]
        if extractor_args:
            cmd.extend(["--extractor-args", extractor_args])
        if cookie_file:
            cmd.extend(["--cookies", str(cookie_file)])
        if user_agent:
            cmd.extend(["--user-agent", user_agent])
        if referer:
            cmd.extend(["--referer", referer])
        cmd.append(page_url)
        return cmd

    if is_youtube:
        # v3.7.0 PARALEL YARIŞ: iki istemci seti tek seferde fırlatılır
        info, race_err, drm_flag = _race_ytdlp_cmds(
            [_build_cmd(YT_RACE_FAST_ARGS), _build_cmd(YT_RACE_SECOND_ARGS)],
            [30, 50],
        )
        if info is not None:
            return info, "", drm_flag
        last_err = race_err or "bot-check"
        logger.info(
            "yt-dlp YouTube yarışı sonuçsuz (%s): %s — geniş yedek set deneniyor",
            page_url[:80],
            (last_err or "?")[:120],
        )
        # son şans: eski geniş yedek set (tv_simply,tv,web_safari,mweb)
        try:
            res = subprocess.run(
                _build_cmd(YT_FALLBACK_EXTRACTOR_ARGS),
                capture_output=True,
                text=True,
                timeout=50,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                try:
                    return json.loads(res.stdout), "", drm_flag
                except json.JSONDecodeError as jexc:
                    last_err = f"JSON parse hatası: {jexc}"
            else:
                err_txt = (res.stderr or "").strip()
                low_err = err_txt.lower()
                if "drm" in low_err or "widevine" in low_err or "fairplay" in low_err:
                    drm_flag = True
                last_err = err_txt[-300:] or f"rc={res.returncode}"
        except subprocess.TimeoutExpired:
            last_err = "TIMEOUT 50s (geniş yedek)"
            logger.info("yt-dlp probe zaman aşımı (%s): %s", page_url[:80], last_err)
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            logger.info("yt-dlp probe hata (%s): %s", page_url[:80], last_err)
        return None, last_err, drm_flag

    # v3.7.0: YouTube DIŞI siteler — tek güçlü deneme (extractor-args yalnız
    # YouTube ekstraktörüne etki eder; eski 3'lü döngü gereksiz ~90 sn gecikmeydi)
    try:
        res = subprocess.run(
            _build_cmd(""),
            capture_output=True,
            text=True,
            timeout=55,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            try:
                return json.loads(res.stdout), "", False
            except json.JSONDecodeError as jexc:
                return None, f"JSON parse hatası: {jexc}", False
        err_txt = (res.stderr or "").strip()
        low_err = err_txt.lower()
        if "drm" in low_err or "widevine" in low_err or "fairplay" in low_err:
            drm_flag = True
        last_err = err_txt[-300:] or f"rc={res.returncode}"
        return None, last_err, drm_flag
    except subprocess.TimeoutExpired:
        last_err = "TIMEOUT 55s"
        logger.info("yt-dlp probe zaman aşımı (%s): %s", page_url[:80], last_err)
    except Exception as exc:
        last_err = f"{type(exc).__name__}: {exc}"
        logger.info("yt-dlp probe hata (%s): %s", page_url[:80], last_err)
    return None, last_err, drm_flag


_BILI_QUALITY_NAMES = {
    127: "2160p Ust Seviye", 126: "2160p Dolby", 125: "2160p HDR", 120: "2160p 4K",
    116: "1080p60", 112: "1080p+ (Yuksek bit hiz)", 100: "1080p HIFLY", 80: "1080p Full HD",
    74: "720p60", 64: "720p HD", 32: "480p", 16: "360p", 15: "360p web",
}


def _bili_headers(cookies: str = "", user_agent: str = "") -> Dict[str, str]:
    return {
        "User-Agent": user_agent or _UA_CHROME,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
    }


def _bili_cookie_with_fallback(cookies: str) -> str:
    """v3.1.0: risk kontrolü (-352/412) panzehiri — çerezde buvid3 yoksa sentetik ekle.
    Bilibili API'si buvid3/b_nut olmayan istemcilere sık sık 'risk control' döner."""
    if "buvid3" in (cookies or ""):
        return cookies
    import random as _rnd

    hexu = "".join(_rnd.choice("0123456789ABCDEF") for _ in range(32))
    buvid = f"{hexu[:8]}-{hexu[8:12]}-{hexu[12:16]}-{hexu[16:20]}-{hexu[20:32]}infoc"
    base = cookies.strip()
    if base and not base.endswith(";"):
        base += "; "
    return f"{base}buvid3={buvid}; b_nut={int(time.time())};"


def _bili_get_json(url: str, cookies: str, user_agent: str = "", timeout: int = 15) -> Optional[Dict[str, Any]]:
    """v3.1.0: bilibili GET + risk-kontrol otomatik kurtarma (ana sayfa ısıtma + buvid3)."""
    headers = _bili_headers(cookies, user_agent)
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if not isinstance(data, dict):
                return None
            raw_code = data.get("code")
            code = int(raw_code) if isinstance(raw_code, (int, float, str)) and str(raw_code).lstrip("-").isdigit() else 0
            if code in (0, -404):
                return data
            if code in (-352, -412, -799) and attempt == 0:
                # risk kontrolü: ana sayfayı ısıt + sentetik buvid3 ile bir daha dene
                try:
                    warm = urllib.request.Request(
                        "https://www.bilibili.com/", headers={"User-Agent": headers["User-Agent"]}
                    )
                    urllib.request.urlopen(warm, timeout=8).read(65536)
                except Exception:
                    pass
                headers["Cookie"] = _bili_cookie_with_fallback(headers.get("Cookie", ""))
                continue
            return data
        except urllib.error.HTTPError as exc:
            if exc.code in (412, 352) and attempt == 0:
                headers["Cookie"] = _bili_cookie_with_fallback(headers.get("Cookie", ""))
                continue
            return None
        except Exception:
            return None
    return None


def fetch_bilibili_cid(bvid: str, cookies: str = "", user_agent: str = "") -> str:
    """v3.1.0: bvid -> cid (pagelist + view çift yol). Sayfa kancası susarsa bile cid bulunur."""
    for api in (
        f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}",
        f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
    ):
        data = _bili_get_json(api, cookies, user_agent)
        if not data:
            continue
        d = data.get("data") or {}
        if isinstance(d, list) and d:
            return str((d[0] or {}).get("cid") or "")
        if isinstance(d, dict) and d.get("cid"):
            return str(d["cid"])
        if isinstance(d, dict) and isinstance(d.get("pages"), list) and d["pages"]:
            return str((d["pages"][0] or {}).get("cid") or "")
    return ""


def _bili_dash_size_est(bandwidth: Any, timelength_ms: Any) -> Optional[int]:
    try:
        bw = int(bandwidth or 0)
        ms = int(timelength_ms or 0)
        if bw > 0 and ms > 0:
            return int(bw * ms / 8000.0)
    except Exception:
        pass
    return None


def fetch_bilibili_quality_options(
    bvid: str, cid: str, cookies: str = "", user_agent: str = ""
) -> List["VideoFormatOption"]:
    """v3.1.0 GÜÇLENDİRİLMİŞ: playurl'dan ÇÖZÜNÜRLÜK + KALİTE ADI + BOYUT etiketli DASH
    seçenekleri (video+ses mux). Risk kontrolüne (-352/412) buvid3/ısıtma panzehirli,
    en yüksek bant genişlikli ses seçilir, bilibili kalite adları (4K/HDR/1080P60...)
    bar'da gösterilir."""
    url = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=16&fnver=0&fourk=1&type=0&platform=html5_high"
    data = _bili_get_json(url, cookies, user_agent)
    if not data:
        return []
    d = (data.get("data") or {}) if isinstance(data, dict) else {}
    dash = d.get("dash") or {}
    auds = sorted(
        (dash.get("audio") or []),
        key=lambda a: (a.get("bandwidth") or a.get("id") or 0),
        reverse=True,
    )
    a_url = ""
    if auds:
        a_url = auds[0].get("baseUrl") or (auds[0].get("base_url") or "")
    hdrs = {"Referer": "https://www.bilibili.com/", "Origin": "https://www.bilibili.com", "User-Agent": user_agent or _UA_CHROME}
    tl = d.get("timelength") or 0
    opts: List["VideoFormatOption"] = []
    seen_h: set = set()
    for v in (dash.get("video") or [])[:8]:
        vu = v.get("baseUrl") or v.get("base_url") or ""
        if not vu:
            continue
        h = int(v.get("height") or 0)
        if h in seen_h:
            continue
        seen_h.add(h)
        qid = int(v.get("id") or 0)
        qname = _BILI_QUALITY_NAMES.get(qid, "")
        v_est = _bili_dash_size_est(v.get("bandwidth"), tl)
        a_est = _bili_dash_size_est(auds[0].get("bandwidth") if auds else 0, tl)
        est = (v_est + a_est) if (v_est and a_est) else (v_est or a_est)
        lbl = f"{h}p"
        # v3.1.0: kalite adı yalnızca gerçek bilgi taşıyorsa göster (480p (480p) tekrarı yok)
        if qname and qname.lower() != f"{h}p":
            lbl += f" ({qname})"
        lbl += " • DASH (video+ses) • bilibili"
        if est:
            lbl += f" — ~{format_bytes(est)}"
        opts.append(
            VideoFormatOption(
                id=f"bili_{h}_{len(opts)}",
                label=lbl,
                ext="mp4",
                resolution=f"{h}p",
                height=h,
                filesize=est,
                delivery="stream_proxy",
                source_url=f"https://www.bilibili.com/video/{bvid}",
                stream_referer="https://www.bilibili.com/",
                mux_video_url=vu,
                mux_audio_url=a_url,
                mux_video_headers=dict(hdrs),
                mux_audio_headers=dict(hdrs),
            )
        )
    opts.sort(key=lambda o: o.height, reverse=True)
    return opts


def fetch_bilibili_playurl_streams(
    bvid: str, cid: str, cookies: str = "", user_agent: str = ""
) -> List[Dict[str, Any]]:
    """v2.9.6 (v3.1.0 panzehirli): playurl API'sini daemon tarafında çerezlerle çağırır
    (CORS/yasak başlık derdi yok; -352/412 risk kontrolünde buvid3+ısıtma kurtarır)."""
    url = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=16&fnver=0&fourk=1"
    data = _bili_get_json(url, cookies, user_agent)
    if not data:
        return []
    d = data.get("data") or {}
    out: List[Dict[str, Any]] = []
    dash = d.get("dash") or {}
    for v in (dash.get("video") or [])[:6]:
        bu = v.get("baseUrl") or v.get("base_url") or ""
        if bu:
            out.append({"url": bu, "mime": v.get("mimeType") or "video/mp4", "isHls": False,
                        "referer": "https://www.bilibili.com/", "origin": "https://www.bilibili.com",
                        "manifestText": ""})
    for a in (dash.get("audio") or [])[:2]:
        bu = a.get("baseUrl") or a.get("base_url") or ""
        if bu:
            out.append({"url": bu, "mime": a.get("mimeType") or "audio/mp4", "isHls": False,
                        "referer": "https://www.bilibili.com/", "origin": "https://www.bilibili.com",
                        "manifestText": ""})
    for du in (d.get("durl") or [])[:3]:
        if du.get("url"):
            out.append({"url": du["url"], "mime": "video/mp4", "isHls": False,
                        "referer": "https://www.bilibili.com/", "origin": "https://www.bilibili.com",
                        "manifestText": ""})
    return out


def parse_hls_subtitles(manifest_text: str, base_url: str = "") -> List[Tuple[str, str]]:
    """v2.9.4: HLS master'dan SUBTITLES gruplarını çıkar (isim, mutlak URL)."""
    out: List[Tuple[str, str]] = []
    for m in re.finditer(r"#EXT-X-MEDIA:([^\n]*)", manifest_text or ""):
        attrs = m.group(1)
        if "TYPE=SUBTITLES" not in attrs:
            continue
        nm = re.search(r'NAME="([^"]*)"', attrs)
        ur = re.search(r'URI="([^"]*)"', attrs)
        if not ur:
            continue
        url = ur.group(1)
        if url.startswith("/"):
            url = urllib.parse.urljoin(base_url or "https://x.invalid/", url)
        elif not url.startswith("http"):
            url = urllib.parse.urljoin((base_url or "") + "/", url)
        out.append((nm.group(1) if nm else "altyazı", url))
    return out


def parse_dash_subtitles(manifest_text: str, base_url: str = "") -> List[Tuple[str, str]]:
    """v2.9.4: MPD'de contentType=text / text/* AdaptationSet'lerinin tek dosya BaseURL'leri."""
    out: List[Tuple[str, str]] = []
    for m in re.finditer(r"<AdaptationSet\b([^>]*)>(.*?)</AdaptationSet>", manifest_text or "", re.S):
        attrs, body = m.group(1), m.group(2)
        if 'contentType="text"' not in attrs and "text/" not in attrs:
            continue
        lang = re.search(r'lang="([^"]*)"', attrs)
        bu = re.search(r"<BaseURL>([^<]+)</BaseURL>", body)
        if not bu:
            continue
        url = bu.group(1).strip()
        if not url.startswith("http"):
            url = urllib.parse.urljoin(base_url or "https://x.invalid/", url)
        out.append((lang.group(1) if lang else "altyazı", url))
    return out


# v3.4.0 YOUTUBE ANINDA HIZLI KAYNAKLAR: kullanıcının en büyük şikayeti "YouTube kaynakları
# aşırı geç bulunuyor" idi. yt-dlp -J çözümlemesi (20-90 sn) sürerken sayfada YAKALANAN
# googlevideo akışlarından ANINDA (0 sn) oynatılabilir formatlar türetilir:
#   - i18/22 (birleşik ses+video MP4)  -> relay üzerinden IDM'de NATİVE akar
#   - 140/141/249/250/251 (yalnız ses) -> m4a/opus olarak listelenir
# Bu "⚡ Hazır" seçenekler 0 sn'de bara düşer; arka plandaki tam -J çözümü bitince
# 4K/2K/1080p gibi tüm kaliteler + altyazılar listeye EKLENİR (IDM_MEDIA_UPDATED).
_YT_ITAG_TABLE: Dict[str, Tuple[str, str, int]] = {
    # itag: (kalite etiketi, uzantı, tür)  tür: 2=muxed, 1=ses
    "18": ("360p", "mp4", 2),
    "22": ("720p", "mp4", 2),
    "59": ("480p", "mp4", 2),
    "78": ("720p", "mp4", 2),
    "139": ("48kbps", "m4a", 1),
    "140": ("128kbps", "m4a", 1),
    "141": ("256kbps", "m4a", 1),
    "249": ("~50kbps", "weba", 1),
    "250": ("~70kbps", "weba", 1),
    "251": ("160kbps", "weba", 1),
}


def _youtube_quick_options(captured_streams: List[Dict[str, Any]], page_url: str, referer: str) -> List[VideoFormatOption]:
    """v3.4.0: yakalanan googlevideo/videoplayback URL'lerinden anında oynatılabilir seçenekler.

    Yalnızca BİRLEŞİK (muxed) ve YALNIZ SES itag'ları türetilir — video-only parçalar
    ffmpeg mux gerektirdiğinden (arka plan motoru işi) atlanır; onlar tam -J sonucuyla gelir.
    Boyut URL'deki 'clen' parametresinden OKSAL olmayan şekilde okunur."""
    from .i18n import get_i18n

    opts: List[VideoFormatOption] = []
    seen_itags: set = set()
    best_audio: Optional[VideoFormatOption] = None
    for st in captured_streams[:60]:
        s_url = (st.get("url") or "").strip()
        if "googlevideo.com/videoplayback" not in s_url:
            continue
        q = urllib.parse.parse_qs(urllib.parse.urlparse(s_url).query)
        itag = (q.get("itag") or [""])[0]
        if not itag or itag in seen_itags:
            continue
        meta = _YT_ITAG_TABLE.get(itag)
        if not meta:
            continue
        seen_itags.add(itag)
        q_label, ext, kind = meta
        try:
            clen = int((q.get("clen") or ["0"])[0]) or None
        except ValueError:
            clen = None
        mime = (st.get("mime") or "").lower()
        if kind == 2:
            opts.append(
                VideoFormatOption(
                    id=f"ytq_{itag}",
                    label=get_i18n().t("bar.yt_quick_muxed", q=q_label),
                    ext=ext,
                    resolution=q_label if q_label.endswith("p") else "",
                    filesize=clen,
                    filesize_exact=bool(clen),
                    delivery="direct",
                    direct_url=s_url,
                    source_url=s_url,
                    stream_referer=st.get("referer") or referer or page_url,
                    stream_origin=st.get("origin") or "",
                    stream_user_agent=st.get("userAgent") or "",
                )
            )
        else:
            cand = VideoFormatOption(
                id=f"ytq_{itag}",
                label=get_i18n().t("bar.yt_quick_audio", q=q_label),
                ext=ext,
                resolution="",
                filesize=clen,
                filesize_exact=bool(clen),
                delivery="direct",
                direct_url=s_url,
                source_url=s_url,
                stream_referer=st.get("referer") or referer or page_url,
                stream_origin=st.get("origin") or "",
                stream_user_agent=st.get("userAgent") or "",
                audio_only=True,
            )
            # En yüksek ses kalitesi üstte kalsın (141 > 251 > 140 > ...)
            rank = {"141": 4, "251": 3, "140": 2, "250": 1, "139": 0, "249": 0}.get(itag, 0)
            if best_audio is None or rank > int(getattr(best_audio, "height", 0) or 0):
                best_audio = cand
                cand.height = rank  # type: ignore[attr-defined]
    if best_audio is not None:
        opts.append(best_audio)
    return opts


# v3.5.0: dil kodu -> ana dilde ad (IDM barında 'tr' yerine 'Türkçe' görünür)
SUB_LANG_NAMES: Dict[str, str] = {
    "tr": "Türkçe", "en": "English", "de": "Deutsch", "fr": "Français", "ru": "Русский",
    "es": "Español", "it": "Italiano", "pt": "Português", "ja": "日本語", "ko": "한국어",
    "zh": "中文", "zh-hans": "简体中文", "zh-hant": "繁體中文", "ar": "العربية", "fa": "فارسی",
    "hi": "हिन्दी", "id": "Bahasa Indonesia", "nl": "Nederlands", "el": "Ελληνικά",
    "vi": "Tiếng Việt", "az": "Azərbaycanca", "pl": "Polski", "ro": "Română", "ka": "ქართული",
    "uk": "Українська", "sv": "Svenska", "no": "Norsk", "nb": "Norsk Bokmål", "da": "Dansk",
    "fi": "Suomi", "cs": "Čeština", "sk": "Slovenčina", "hu": "Magyar", "th": "ไทย",
    "he": "עברית", "bn": "বাংলা", "ur": "اردو", "ms": "Melayu", "fil": "Filipino",
    "kk": "Қазақша", "ky": "Кыргызча", "bg": "Български", "hr": "Hrvatski", "sr": "Српски",
    "sl": "Slovenščina", "et": "Eesti", "lv": "Latviešu", "lt": "Lietuvių", "hy": "Հայերեն",
}


def sub_lang_name(code: str) -> str:
    """v3.5.0: 'tr' -> 'Türkçe', 'pt-BR' -> 'Português (pt-BR)', bilinmeyen -> kodun kendisi."""
    c = (code or "").strip()
    if not c:
        return ""
    low = c.lower().replace("_", "-")
    if low in SUB_LANG_NAMES:
        return SUB_LANG_NAMES[low]
    base = low.split("-")[0]
    if base == "zh" and low not in SUB_LANG_NAMES:
        return SUB_LANG_NAMES["zh"]
    if base in SUB_LANG_NAMES and low != base:
        return f"{SUB_LANG_NAMES[base]} ({c})"
    return c


# v3.9.0: URL'den altyazı DİLİ TAHMİNİ — kullanıcının kararı: 'altyazı dilini de yazsın,
# kullanıcı Türkçe mi başka dilde mi indirdiğini anlasın'. Film CDN'leri dili URL'de taşır:
# /1.vtt yerine tr.vtt, -tr.vtt, ?lang=tr, _turkce.vtt, turkish-eng.vtt vb.
_SUB_URL_LANG_WORDS: Dict[str, str] = {
    "turkce": "tr", "türkçe": "tr", "turkish": "tr", "turk": "tr", "tur": "tr",
    "ingilizce": "en", "english": "en", "eng": "en", "ingles": "en",
    "almanca": "de", "german": "de", "deutsch": "de", "ger": "de", "deu": "de",
    "fransizca": "fr", "french": "fr", "francais": "fr", "fra": "fr", "fre": "fr",
    "ispanyolca": "es", "spanish": "es", "espanol": "es", "spa": "es",
    "italyanca": "it", "italian": "it", "italiano": "it", "ita": "it",
    "rusca": "ru", "russian": "ru", "russian": "ru", "rus": "ru",
    "arapca": "ar", "arabic": "ar", "ara": "ar", "arab": "ar",
    "japonca": "ja", "japanese": "ja", "jpn": "ja", "jap": "ja",
    "korece": "ko", "korean": "ko", "kor": "ko",
    "cincesi": "zh", "chinese": "zh", "chi": "zh", "zho": "zh",
    "farsca": "fa", "persian": "fa", "fas": "fa", "per": "fa",
    "azerce": "az", "azeri": "az", "aze": "az",
    "yunanca": "el", "greek": "el", "gre": "el", "ell": "el",
    " portekizce": "pt", "portuguese": "pt", "por": "pt",
    "hintce": "hi", "hindi": "hi", "hin": "hi",
}


def guess_lang_from_url(url: str) -> str:
    """Altyazı URL'inden dil kodu tahmin eder ('' = belirsiz).
    ?lang=tr, /tr/, -tr.vtt, _tr., .tr., turkce, english vb. kalıpları yakalar."""
    low = (url or "").lower()
    if not low:
        return ""
    # 1) açık dil parametreleri
    m = re.search(r"[?&](?:lang|language|sub_lang|srclang|sublang)=([a-z]{2,3}(?:[-_][a-z0-9]{2,8})?)\b", low)
    if m:
        return m.group(1).replace("_", "-")
    # 2) yol segmentleri: /tr/, .tr., -tr., _tr.
    path = low.split("?")[0]
    m = re.search(r"(?:^|[/_.\-])([a-z]{2})(?:[/_.\-]|$)", path)
    if m and m.group(1) in SUB_LANG_NAMES:
        # 2 harfli kod — ama yanlış pozitif riski: dosya adı '1.vtt' gibi. Yalnız
        # bilinçli dil segmenti kalıplarında güvenilir: tr.vtt / -tr- / _tr. / /tr/
        seg = re.search(r"(?:^|/)([a-z]{2})(?:\.|-|_|/)(?:vtt|srt|ass|ssa|ttml|xml|sbv|sami|sub)\b", path)
        if seg and seg.group(1) in SUB_LANG_NAMES:
            return seg.group(1)
        m2 = re.search(r"[/_.\-]([a-z]{2})[/_.\-][^/?]*\.(?:vtt|srt|ass|ssa|ttml|xml|sbv|sami|sub)\b", path)
        if m2 and m2.group(1) in SUB_LANG_NAMES:
            return m2.group(1)
    # 3) 3 harfli ISO 639-2 kodları (tur, eng, ger...)
    m3 = re.search(r"(?:^|[/_.\-])(tur|eng|ger|deu|fre|fra|spa|ita|rus|ara|jpn|kor|zho|chi|fas|per|aze|ell|por|hin)(?:[/_.\-]|$)", path)
    if m3:
        iso2 = {"tur": "tr", "eng": "en", "ger": "de", "deu": "de", "fre": "fr", "fra": "fr",
                "spa": "es", "ita": "it", "rus": "ru", "ara": "ar", "jpn": "ja", "kor": "ko",
                "zho": "zh", "chi": "zh", "fas": "fa", "per": "fa", "aze": "az", "ell": "el",
                "por": "pt", "hin": "hi"}.get(m3.group(1), "")
        if iso2:
            return iso2
    # 4) dil ADLARI (turkce, english, ingilizce...)
    for word, code in _SUB_URL_LANG_WORDS.items():
        if re.search(rf"(?:^|[/_.\-]){re.escape(word.strip())}(?:[/_.\-]|$)", path):
            return code
    return ""


def _norm_sub_dedup_key(url: str) -> str:
    """Altyazı URL'ini tekilleştirme anahtarına indirger: şema farkları, parça (#),
    ve sorgusuz/boş sorgu varyantları aynı altyazıya işaret eder (kullanıcı raporu:
    2 altyazı varken bar 3 gösteriyordu)."""
    try:
        p = urllib.parse.urlsplit((url or "").strip())
        host = (p.netloc or "").lower()
        path = (p.path or "").rstrip("/")
        return f"{host}{path}"
    except Exception:
        return (url or "").strip().lower()


def _youtube_lang_options(info: Dict[str, Any], page_url: str) -> List[VideoFormatOption]:
    """v2.9.4: YouTube çok dilli ses rayları + altyazı dosyaları (yt-dlp -J çıktısından).
    v3.4.0: etiketler 20 dilde yerelleştirilir.
    v3.5.0 KÖKLÜ ALTYAZI DÜZELTMESİ: yalnız info['subtitles'] değil AUTOMATIC_CAPTIONS da
    listelenir (YouTube'da çoğu videonun elle altyazısı YOKTUR — otomatik kapalı altyazıları
    listelenmediği için bar hiç altyazı göstermiyordu). Etiketler artık dil adıyla gelir:
    'tr' yerine 'Türkçe'."""
    from .i18n import get_i18n

    opts: List[VideoFormatOption] = []
    seen_lang = set()
    for f in info.get("formats") or []:
        lang = (f.get("language") or "").strip()
        if not lang or f.get("vcodec") != "none" or not f.get("acodec") or f.get("acodec") == "none":
            continue
        if lang in seen_lang:
            continue
        seen_lang.add(lang)
        if len(seen_lang) > 14:
            break
        opts.append(
            VideoFormatOption(
                id=f"ytlang_{lang}",
                label=get_i18n().t("bar.audio_lang", lang=sub_lang_name(lang)),
                ext="m4a",
                resolution="",
                filesize=f.get("filesize") or f.get("filesize_approx"),
                delivery="ytdlp",
                format_selector=f"bestaudio[language={lang}]/bestaudio",
                source_url=page_url,
                audio_only=True,
            )
        )
    # v3.5.0: önce GERÇEK (elle yüklenmiş) altyazılar, sonra otomatik kapalı altyazılar;
    # toplam 20 kayıtla sınırlı (bar taşmasın). YouTube 'en-orig' gibi -orig kodları sonda.
    real_codes = [c for c in (info.get("subtitles") or {}).keys() if c and c != "live_chat"]
    auto_all = list((info.get("automatic_captions") or {}).keys())
    auto_codes = [c for c in auto_all if c and c not in real_codes and c != "live_chat"]
    auto_codes.sort(key=lambda c: (c.endswith("-orig"), c))  # -orig en sona
    n_sub = 0
    for is_auto, codes in ((False, real_codes), (True, auto_codes)):
        if n_sub >= 20:
            break
        for code in codes:
            if n_sub >= 20:
                break
            nm = sub_lang_name(code)
            opts.append(
                VideoFormatOption(
                    id=f"ytsub_{'auto' if is_auto else 'man'}_{code}",
                    label=(
                        get_i18n().t("bar.sub_auto", name=nm)
                        if is_auto
                        else get_i18n().t("bar.sub_lang", code=nm)
                    ),
                    ext="srt",
                    delivery="yt_subs",
                    sub_lang=code,
                    source_url=page_url,
                )
            )
            n_sub += 1
    return opts

def _looks_like_subtitle_capture(url: str, mime: str = "") -> bool:
    """v3.6.0: yakalanan akışın ALTYAZI kaynağı olup olmadığını anlar.

    Bu akışlar video döngüsünde 'Doğrudan Video (MP4)' seçeneği olarak SIZMAMALI —
    _subtitle_options() onları '📝 Altyazı: <dil>' olarak listeler (kullanıcı raporu:
    film sitelerinde altyazılar bar'a altyazı olarak değil bozuk video olarak düşüyordu).
    """
    m = (mime or "").lower()
    if m.startswith("text/") and not m.startswith("text/html"):
        return True
    if m in ("application/x-subrip", "application/ttml+xml", "application/xml"):
        return True
    low = (url or "").lower()
    if not low.startswith(("http://", "https://")):
        return False
    path_q = low.split("?")[0]
    if path_q.endswith((".vtt", ".srt", ".ass", ".ssa", ".ttml", ".sbv", ".sami", ".xml")):
        return True
    if (
        ".vtt?" in low
        or ".srt?" in low
        or "/timedtext" in low
        or "/caption" in low
        or "/subtitles" in low
        or "/subtitle" in low
        or "caption=" in low
        or "subtitleformat" in low
    ):
        return True
    return False


def _bar_subs_header_text() -> str:
    """v3.5.0: IDM barında altyazı grubu başlığı ('─── 📝 Altyazılar ───') — yerelleştirilmiş."""
    try:
        from .i18n import get_i18n

        return str(get_i18n().t("bar.subs_header") or "")
    except Exception:
        return "📝 Altyazılar"


def _subtitle_options(
    captured_streams: List[Dict[str, Any]], referer: str, page_url: str, validate: bool = True
) -> List[VideoFormatOption]:
    """v2.9.4: manifest/<track> altyazıları IDM barında tıklayıp indirilebilir.
    v3.2.2: TÜM altyazılar 'subs' teslimiyle SRT olarak iner — HLS segmentli
    (TYPE=SUBTITLES) altyazılar motorda sıralı indirilip birleştirilir + VTT→SRT
    dönüşümü yapılır; tek dosyalık .vtt/.srt/.ass da aynı kapıdan SRT/şeklinde geçer.
    v3.4.0: etiketler 20 dilde yerelleştirilir.
    v3.5.0 KAPSAMA ARTIŞI: film sitelerinin çoğu altyazıyı .vtt yerine XHR ile
    (api/subtitles, /caption?lang=tr, text/vtt MIME, .xml TTML) çeker — desenler
    genişletildi; YouTube timedtext URL'lerinden dil kodu okunup 'Türkçe' etiketi
    üretilir; <track lang> / sub_label varsa dil adıyla birleşir.

    v3.9.0 KULLANICI KARARLARI (fullhdfilmizlesene.now raporu):
    1) SAHTE GİRDİ YOK: her aday URL gerçekten doğrulanır (fetch_subtitle_probe —
       4 başlık varyantı, içerik imza kontrolü). CDN yanıt verdi ama içerik altyazı
       değilse girdi BAR'A HİÇ GİRMEZ (ör. oyuncunun boş 'Default (Forced)' rayı).
    2) TEKRAR YOK: normalleştirilmiş anahtar (host+yol) ile tekilleştirme — aynı
       altyazının sorgu/şema varyantları tek satıra iner.
    3) DİL YAZILIR: sub_label > URL dil kalıbı (guess_lang_from_url) > dosya adı.
    4) GERÇEK BOYUT: doğrulanan altyazının tam bayt boyutu 'filesize' olarak bar'a
       gider (kullanıcı '52 KB' görür — 0 bayt iddiası imkânsız hale gelir)."""
    from .i18n import get_i18n

    opts: List[VideoFormatOption] = []
    # normalleştirilmiş tekilleştirme: anahtar -> ( tercihlenilmiş aday )
    cand_by_key: Dict[str, Dict[str, Any]] = {}

    def _label_score(lbl: str) -> int:
        # etiket kalitesi: 'Türkçe Altyazı' > '1' > 'altyazı'
        if not lbl:
            return 0
        low = lbl.strip().lower()
        if low in ("altyazı", "altyazi", "subtitle", "caption", "default (forced)", "forced"):
            return 1
        if low.isdigit() or len(low) < 2:
            return 1
        return 3

    raw_candidates: List[Tuple[str, str]] = []  # (url, label)
    for st in captured_streams[:40]:
        url = st.get("url") or ""
        mime = (st.get("mime") or "").lower()
        mt = st.get("manifestText") or ""
        if mt:
            # HLS/DASH altyazı grupları ayrı aday olarak girer (doğrudan URL'ler)
            for nm, surl in parse_hls_subtitles(mt, url) + parse_dash_subtitles(mt, url):
                if surl and surl.startswith("http"):
                    raw_candidates.append((surl, nm))
        low = url.lower()
        path_q = low.split("?")[0]
        is_sub_url = (
            mime.startswith("text/")
            or mime in ("application/x-subrip", "application/ttml+xml", "application/xml")
            or path_q.endswith((".vtt", ".srt", ".ass", ".ssa", ".ttml", ".xml", ".sbv", ".sami"))
            or ".vtt?" in low
            or "/timedtext?" in low
            or "timedtext" in low
            or "/caption" in low
            or "/subtitles" in low
            or "/subtitle" in low
            or "caption=" in low
            or "subtitleformat" in low
        )
        if is_sub_url and url.startswith("http"):
            lbl = (st.get("sub_label") or "").strip()
            if not lbl:
                lm = re.search(r"[?&]lang=([A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?)", url)
                if lm:
                    lbl = sub_lang_name(lm.group(1))
            if not lbl and "/timedtext" in low:
                lbl = "YouTube"
            raw_candidates.append((url, lbl))

    # 1) TEKİLLEŞTİRME — aynı (host+yol) için en iyi etiketli aday kazanır
    for url, lbl in raw_candidates:
        key = _norm_sub_dedup_key(url)
        prev = cand_by_key.get(key)
        if prev is None:
            cand_by_key[key] = {"url": url, "label": lbl, "score": _label_score(lbl)}
        else:
            if _label_score(lbl) > prev["score"]:
                prev["label"] = lbl
                prev["score"] = _label_score(lbl)

    # 2) DOĞRULAMA — sahte/ölü girdiler kökten elenir; gerçek boyut alınır
    probe_results: Dict[str, Tuple[str, int, str]] = {}
    if validate and cand_by_key:
        from .hls_streamer import build_stream_headers, fetch_subtitle_probe

        rp = urllib.parse.urlsplit(referer or page_url or "")
        origin = f"{rp.scheme}://{rp.netloc}" if rp.netloc else ""
        probe_headers = build_stream_headers(referer or page_url or "", origin, "", "")
        keys = list(cand_by_key.keys())[:14]
        if keys:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(keys))) as px:
                fut_map = {
                    px.submit(fetch_subtitle_probe, cand_by_key[k]["url"], probe_headers, 6.0): k
                    for k in keys
                }
                for fut in concurrent.futures.as_completed(fut_map, timeout=30):
                    k = fut_map[fut]
                    try:
                        probe_results[k] = fut.result()
                    except Exception:
                        probe_results[k] = ("unknown", 0, "")

    seen: set = set()
    for key, cand in cand_by_key.items():
        url = cand["url"]
        status, size_bytes, sub_kind = probe_results.get(key, ("unknown", 0, ""))
        if status == "bad":
            # CDN yanıt verdi ama içerik altyazı değil -> SAHTE girdi, bar'a girmez!
            logger.info("Sahte/ölü altyazı girdisi elendi: %s", url[:110])
            continue
        lbl = (cand["label"] or "").strip()
        # v3.9.0: uzantı 'lang:tr' biçiminde dil kodu ipucu gönderebilir ->
        # yerel dil adına çevrilir ('Türkçe' / 'English' ...)
        if lbl.lower().startswith("lang:"):
            lbl = sub_lang_name(lbl[5:].strip())
        if not lbl:
            lang_code = guess_lang_from_url(url)
            if lang_code:
                lbl = sub_lang_name(lang_code)
        if not lbl and "/timedtext" in url.lower():
            lbl = "YouTube"
        if not lbl:
            tail = url.split("?")[0].rsplit("/", 1)[-1]
            stem = Path(tail).stem if tail and "." in tail else ""
            # '1', '2', '78aea874...' gibi anlamsız dosya adları dil etiketi OLAMAZ —
            # kullanıcı 'hangi dil?' sorusunu hak ediyor; nötr etiket + URL kısaltması gösterilir.
            if stem and len(stem) >= 2 and not stem.isdigit():
                lbl = stem[:28]
        if not lbl:
            lbl = "altyazı"
        seen.add(key)
        if len(seen) > 16:
            break
        # v3.10.0 UZANTI DÜRÜSTLÜĞÜ (kullanıcı kararı): altyazı HANGİ biçimdeyse
        # bar'da O biçimde görünür ve O biçimde iner. Önceki sürüm her şeyi "srt"
        # diye etiketliyordu; kullanıcı "1.vtt altyazısı srt olarak sahte
        # gösteriliyor" diye bildirdi. Artık VTT → vtt, SRT → srt, ASS → ass...
        ext = sub_kind if sub_kind in ("vtt", "srt", "ass", "ttml") else ""
        if not ext:
            for cand_ext in ("vtt", "srt", "ass", "ssa", "ttml", "sbv", "sami"):
                if f".{cand_ext}" in url.lower():
                    ext = "vtt" if cand_ext in ("vtt",) else ("srt" if cand_ext == "srt" else cand_ext)
                    break
        if not ext:
            ext = "vtt"  # içerik/URL belirsizse en yaygın biçim varsayılır (SRT iddiası yok)
        opts.append(
            VideoFormatOption(
                id=f"sub_{len(seen)}",
                label=get_i18n().t("bar.sub_label", name=lbl, fmt=ext.upper()),
                ext=ext,
                delivery="subs",
                direct_url=url,
                source_url=page_url,
                stream_referer=referer or page_url,
                filesize=(size_bytes if status == "ok" and size_bytes > 0 else None),
                filesize_exact=(status == "ok" and size_bytes > 0),
            )
        )
    return opts

def _abyss_options(captured_streams: List[Dict[str, Any]], page_url: str) -> List[VideoFormatOption]:
    """v2.9.4→v3.1.0: abyssplayer/abysscdn/abyss.to/short.icu iframe'lerinden gelen slug ve
    TAM iframe URL'lerini (abyssif://) çözünürlük+boyut listesine çevirir.

    v3.1.0: Android AbyssVideoPort.java'dan uyarlanan SAYFA ÇÖZÜCÜ devrede —
    abysscdn.com/info/{slug} ucu ölse bile abyss.to / short.icu HTML'indeki
    'const datas=...' blob'u çözülerek kaynaklar bulunur (belgeselsemo fixi)."""
    from .abyss_engine import abyss_fetch_metadata

    slugs: List[str] = []       # yalın slug'lar (abyss://slug)
    embed_urls: List[str] = []  # tam iframe URL'leri (abyssif://https://abyss.to/v/xxx)
    for st in captured_streams[:40]:
        u = st.get("url") or ""
        if u.startswith("abyss://"):
            slugs.append(u[len("abyss://"):])
        elif u.startswith("abyssif://"):
            embed_urls.append(u[len("abyssif://"):])
    low = (page_url or "").lower()
    if any(h in low for h in ("abyssplayer.com", "abysscdn.com", "embedplayabyss.top", "abyss.to", "short.icu")):
        m = re.search(r"[?&]v=([A-Za-z0-9_-]{4,})", page_url or "")
        if m:
            slugs.append(m.group(1))
        m2 = re.search(r"/([A-Za-z0-9_-]{6,})(?:[?#]|$)", page_url or "")
        if m2 and ("abyssplayer" in low or "abyss.to" in low or "short.icu" in low):
            slugs.append(m2.group(1))
    opts: List[VideoFormatOption] = []
    seen_sources: set = set()

    def _emit_for(slug: str, embed_url: str = "") -> None:
        meta = abyss_fetch_metadata(slug, referer=page_url, embed_url=embed_url)
        if not meta or not meta.sources:
            return
        for src in meta.sources[:6]:
            key = (slug, src.label)
            if key in seen_sources:
                continue
            seen_sources.add(key)
            qtag = src.label
            opts.append(
                VideoFormatOption(
                    id=f"abyss_{slug[:8]}_{src.label}",
                    label=f"ABYSS {qtag} • {format_bytes(src.size)}",
                    ext="mp4",
                    resolution=qtag,
                    filesize=src.size,
                    filesize_exact=True,
                    delivery="abyss",
                    abyss_slug=slug,
                    abyss_label=src.label,
                    source_url=embed_url or page_url,
                    stream_referer=page_url,
                )
            )

    for e_url in list(dict.fromkeys(embed_urls))[:3]:
        m = re.search(r"/([A-Za-z0-9_-]{5,})(?:[/?#]|$)", e_url)
        slug = ""
        if m:
            slug = m.group(1)
        mq = re.search(r"[?&]v=([A-Za-z0-9_-]{4,})", e_url)
        if mq:
            slug = mq.group(1)
        if slug:
            _emit_for(slug, e_url)
    for slug in list(dict.fromkeys(slugs))[:2]:
        _emit_for(slug, "")
    return opts


_DIRECT_SAFE_HOSTS = (
    "googlevideo.com", "youtube.com", "ytimg.com", "gvt1.com", "ggpht.com",
)

_PROXY_NEEDY_HOSTS = (
    "bilibili.com", "b23.tv", "hdslb.com", "abyssplayer.com", "abysscdn.com",
    "iamcdn.net", "mediastor", "embedplayabyss.top", "justbeamit.com",
    # v2.9.9: ok.ru/vk CDN'leri çerez+Referer ister (400 Bad Request panzehiri),
    # ayrıca köprü relay'i TEK bağlantıdan aktığı için anlık ilerleme de gelir.
    "ok.ru", "odnoklassniki", "mrok.ru", "vkvd", "vkvideo", "vk.com",
    # v3.11.0 KRİTİK OK.RU DÜZELTMESİ: ok.ru'nun CDN'i ARTIK okcdn.ru / mycdn.me!
    # Kullanıcı raporu: "ok.ru videolarında bar kaynakları gösteriyor ama tıklayınca inmiyor."
    # Kök neden canlı testle doğrulandı: vd335.okcdn.ru linki Referer'sız IDM'ye verildiğinde
    # 400 Bad Request dönüyordu (Referer: https://ok.ru/ ile 206 OK). CDN alan adları
    # listede yoktu -> apply_delivery_guard 'direct' bırakıyordu -> IDM çıplak istek 400.
    "okcdn.ru", "mycdn.me",
    # vk.com CDN'leri (vkuser.net / userapi.com) aynı şekilde Referer kilitli
    "vkuser.net", "userapi.com",
)


def apply_delivery_guard(
    options: List["VideoFormatOption"], referer: str = "", page_url: str = ""
) -> List["VideoFormatOption"]:
    """v2.9.8/2.9.9: çıplak 'direct' teslimat güvenlik kemeri.

    - Korumalı CDN (Referer/şifre/token şartı) -> köprü (stream_proxy)
    - Referer taşıyan site yakalamaları (ok.ru 400 / 4MB kesilme panzehiri) -> köprü
    - YouTube gibi açık CDN'ler DOĞRUDAN kalır (natif IDM ilerlemesi bozulmaz)
    """
    for o in options:
        if o.delivery != "direct":
            continue
        target = o.direct_url or o.source_url or ""
        low_t = target.lower()
        if any(h in low_t for h in _DIRECT_SAFE_HOSTS):
            continue
        if _needs_proxy_host(target):
            o.delivery = "stream_proxy"
            o.stream_referer = o.stream_referer or referer or page_url
    return options


def _needs_proxy_host(url: str) -> bool:
    """v2.9.8: Referer/çerez şartı olan CDN'ler IDM'ye çıplak verilmez (403 panzehiri)."""
    low = (url or "").lower()
    return any(h in low for h in _PROXY_NEEDY_HOSTS)


# v3.1.0: daemon, arka plan probe'u bitince tarayıcıya haber vermek için bu kancaı kurar
_PROBE_DONE_NOTIFIER = None


def set_probe_done_notifier(fn) -> None:
    global _PROBE_DONE_NOTIFIER
    _PROBE_DONE_NOTIFIER = fn


def _notify_probe_done(count: int) -> None:
    fn = _PROBE_DONE_NOTIFIER
    if not fn:
        return
    try:
        fn({"type": "IDM_MEDIA_UPDATED", "count": int(count)})
    except Exception:
        pass


def parse_mpd_representations(mpd_text: str, base_url: str) -> List[Dict[str, Any]]:
    """v2.9.8: MPD'deki HER video temsilciliğini (çözünürlük+segment listesi) çıkarır.

    Bar'da 'MPEG-DASH Video Akışı' belirsizliği biter: 1080p/720p/... etiketli seçenekler.
    """
    out: List[Dict[str, Any]] = []
    if not mpd_text or "<MPD" not in mpd_text[:400]:
        return out
    # v3.2.2 BELLEK KALKANI: dynamic (canlı DVR) MPD'de temsil başına TAM segment
    # genişletmesi yüzlerce MB RAM şişiriyordu (dsmartgo OOM kök nedeni). Kayıt motoru
    # canlı manifesti zaten kendisi takip eder — burada yalnızca ETİKET için küçük kuyruk yeter.
    rep_dynamic = 'type="dynamic"' in (mpd_text[:2000] + mpd_text[-2000:]).lower()
    rep_cap = 240 if rep_dynamic else 4000
    base = base_url.rsplit("/", 1)[0] + "/"

    def _abs(u: str) -> str:
        return u if u.startswith("http") else base + u.lstrip("/")

    audio_segs: List[str] = []
    audio_init = ""
    for am in re.finditer(r"<AdaptationSet\b([^>]*)>(.*?)</AdaptationSet>", mpd_text, re.S):
        attrs = am.group(1)
        if 'contentType="audio"' not in attrs and "audio/mp4" not in attrs and "audio/webm" not in attrs:
            continue
        body = am.group(2)
        rm = re.search(r"<Representation\b[^>]*>(.*?)</Representation>", body, re.S)
        rblock = rm.group(1) if rm else body
        im = re.search(r'initialization="([^"]+)"', rblock)
        if not im:
            im = re.search(r'<Initialization\b[^>]*sourceURL="([^"]+)"', rblock)
        tm = re.search(r"<SegmentTemplate\b([^>]*)>", rblock)
        if not tm:
            continue
        tattrs = tm.group(1)
        media = re.search(r'media="([^"]+)"', tattrs)
        if not media:
            continue
        rep_id = re.search(r'id="([^"]+)"', rm.group(0) if rm else "")
        segs: List[str] = []
        tl = re.search(r"<SegmentTimeline>(.*?)</SegmentTimeline>", rblock, re.S)
        t = 0
        if tl:
            for sm in re.finditer(r"<S\b([^>]*)/?>", tl.group(1)):
                if len(segs) >= rep_cap:
                    break
                sa = sm.group(1)
                st = re.search(r't="(\d+)"', sa)
                sd = re.search(r'd="(\d+)"', sa)
                sr = re.search(r'r="(-?\d+)"', sa)
                if st:
                    t = int(st.group(1))
                d = int(sd.group(1)) if sd else 0
                reps = int(sr.group(1)) if sr else 0
                cnt = reps + 1 if reps >= 0 else 1
                for _ in range(min(cnt, rep_cap - len(segs), 2000)):
                    segs.append(media.group(1).replace("$Time$", str(t)).replace("$RepresentationID$", rep_id.group(1) if rep_id else ""))
                    t += d
        if im:
            audio_init = _abs(im.group(1).replace("$RepresentationID$", rep_id.group(1) if rep_id else ""))
        audio_segs = [_abs(u.replace("$RepresentationID$", rep_id.group(1) if rep_id else "")) for u in segs]
        break

    for vm in re.finditer(r"<AdaptationSet\b([^>]*)>(.*?)</AdaptationSet>", mpd_text, re.S):
        attrs = vm.group(1)
        if 'contentType="video"' not in attrs and "video/mp4" not in attrs and "video/webm" not in attrs:
            continue
        for rm in re.finditer(r"<Representation\b([^>]*)>(.*?)</Representation>", vm.group(2), re.S):
            rattrs, rblock = rm.group(1), rm.group(2)
            hm = re.search(r'height="(\d+)"', rattrs)
            bm = re.search(r'bandwidth="(\d+)"', rattrs)
            rep_id = re.search(r'id="([^"]+)"', rattrs)
            tm = re.search(r"<SegmentTemplate\b([^>]*)>", rblock) or re.search(r"<SegmentTemplate\b([^>]*)>", vm.group(1) + vm.group(2)[:0])
            if not tm:
                tm = re.search(r"<SegmentTemplate\b([^>]*)/?>", vm.group(2))
            if not tm:
                continue
            tattrs = tm.group(1)
            media = re.search(r'media="([^"]+)"', tattrs)
            im = re.search(r'initialization="([^"]+)"', tattrs)
            if not media:
                continue
            segs: List[str] = []
            tl = re.search(r"<SegmentTimeline>(.*?)</SegmentTimeline>", rblock) or re.search(r"<SegmentTimeline>(.*?)</SegmentTimeline>", vm.group(2), re.S)
            rid = rep_id.group(1) if rep_id else ""
            t = 0
            if tl:
                for sm in re.finditer(r"<S\b([^>]*)/?>", tl.group(1)):
                    if len(segs) >= rep_cap:
                        break
                    sa = sm.group(1)
                    st = re.search(r't="(\d+)"', sa)
                    sd = re.search(r'd="(\d+)"', sa)
                    sr = re.search(r'r="(-?\d+)"', sa)
                    if st:
                        t = int(st.group(1))
                    d = int(sd.group(1)) if sd else 0
                    reps = int(sr.group(1)) if sr else 0
                    cnt = reps + 1 if reps >= 0 else 1
                    for _ in range(min(cnt, rep_cap - len(segs), 2000)):
                        segs.append(media.group(1).replace("$Time$", str(t)).replace("$RepresentationID$", rid).replace("$Number$", str(len(segs) + 1)))
                        t += d
            else:
                dm = re.search(r'duration="(\d+)"', tattrs)
                sm2 = re.search(r'startNumber="(\d+)"', tattrs)
                tm2 = re.search(r'timescale="(\d+)"', tattrs)
                if dm:
                    n = min(240, rep_cap)
                    st0 = int(sm2.group(1)) if sm2 else 1
                    for i in range(n):
                        segs.append(media.group(1).replace("$Number$", str(st0 + i)).replace("$RepresentationID$", rid).replace("$Time$", str(i * int(dm.group(1)))))
            if not segs:
                continue
            init = _abs(im.group(1).replace("$RepresentationID$", rid)) if im else ""
            out.append({
                "height": int(hm.group(1)) if hm else 0,
                "bandwidth": int(bm.group(1)) if bm else 0,
                "init": init,
                "segments": [_abs(u.replace("$RepresentationID$", rid)) for u in segs],
                "audio_init": audio_init,
                "audio_segments": audio_segs,
            })
    out.sort(key=lambda x: x["height"], reverse=True)
    return out


# v3.0.0 NOT: Bu dosyada ikinci bir _is_known_ytdlp_site tanımı vardı; modül sonunda
# tanımlandığı için yukarıdaki düzeltilmiş sürümü EZİYORDU (ölü kodlu 2.9.x sürümü
# fiilen geçerliydi). Ölü tanım kaldırıldı — artık tek ve doğru sürüm yukarıdadır.




class StreamEngine:
    def __init__(self, cfg: IdmLinuxConfig) -> None:
        self.cfg = cfg
        self._tickets: Dict[str, StreamTicket] = {}
        self._jobs: Dict[str, ActiveStreamJob] = {}
        self._probe_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._probe_pending: Dict[str, float] = {}  # v3.1.0: arka plan probe'u yürüyen sayfalar
        self._lock = threading.Lock()

    def clear_cache(self) -> None:
        with self._lock:
            self._probe_cache.clear()

    def purge_caches(self, completed_max_age_sec: int = 3600) -> None:
        """v2.8.6: bellek baskısında çağrılır — probe önbelleğini boşaltır, yaşlı biten job'ları atar."""
        with self._lock:
            self._probe_cache.clear()
        now = time.time()
        with self._lock:
            tids = list(self._tickets.keys())
        for tid in tids:
            job = self._jobs.get(tid)
            tk = self._tickets.get(tid)
            if job and tk and (job.completed or job.failed) and (now - tk.created_at) > completed_max_age_sec:
                self.clear_jobs(mode="ticket", ticket_id=tid)

    def cleanup_expired_tickets(self, max_age_sec: int = 5400) -> None:
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._tickets.items() if now - v.created_at > max_age_sec]
            for k in expired:
                self._tickets.pop(k, None)
                job = self._jobs.pop(k, None)
                if job and job.work_dir.exists():
                    shutil.rmtree(job.work_dir, ignore_errors=True)

    def create_ticket(
        self,
        source_url: str,
        filename: str,
        mode: str,
        format_selector: str = "",
        cookies_header: str = "",
        referer: str = "",
        origin: str = "",
        user_agent: str = "",
        mux_video_url: str = "",
        mux_audio_url: str = "",
        mux_video_headers: Optional[Dict[str, str]] = None,
        mux_audio_headers: Optional[Dict[str, str]] = None,
        manifest_text: str = "",
        is_hls: bool = False,
        hls_mode: str = "vod",
        estimated_size: Optional[int] = None,
        final_dir: Optional[Path] = None,
        size_exact: bool = False,
        segment_urls: Optional[List[str]] = None,
        audio_segment_urls: Optional[List[str]] = None,
        abyss_slug: str = "",
        abyss_label: str = "",
        sub_lang: str = "",
    ) -> StreamTicket:
        self.cleanup_expired_tickets()
        tid = uuid.uuid4().hex[:16]
        clean_fn = sanitize_filename(filename or "video.mp4")
        if not Path(clean_fn).suffix:
            clean_fn += ".mp4"
        # v2.8.4 işbölümü: HLS(m3u8) her modda streamlink | MPD VOD: yt-dlp (fragment birleştirme+mux)
        # MPD canlı/DVR: streamlink | progressive/mp4: native IDM (max hız, gerçek boyut+ETA)
        src_low = source_url.lower()
        is_mpd = ".mpd" in src_low
        is_hls_src = is_hls or looks_like_hls_url(source_url) or is_mpd
        seg_urls = [u for u in (segment_urls or []) if u]
        seg_audio = [u for u in (audio_segment_urls or []) if u]
        if seg_urls:
            backend = "segments"
        elif is_mpd and hls_mode == "vod":
            backend = "ytdlp" if find_ytdlp() else ("streamlink" if shutil.which("streamlink") else "native")
        elif is_hls_src or hls_mode in ("dvr", "live"):
            backend = "streamlink" if shutil.which("streamlink") else "native"
        else:
            backend = "native"
        if abyss_slug:
            backend = "abyss"
        if backend == "streamlink" and not is_mpd and clean_fn.lower().endswith(".mp4"):
            clean_fn = clean_fn[:-4] + ".ts"
        ticket = StreamTicket(
            ticket_id=tid,
            source_url=source_url,
            filename=clean_fn,
            mode=mode,
            format_selector=format_selector,
            cookies_header=cookies_header,
            referer=referer,
            origin=origin,
            user_agent=user_agent,
            mux_video_url=mux_video_url,
            mux_audio_url=mux_audio_url,
            mux_video_headers=dict(mux_video_headers or {}),
            mux_audio_headers=dict(mux_audio_headers or {}),
            manifest_text=manifest_text,
            is_hls=is_hls,
            hls_mode=hls_mode if hls_mode in ("vod", "dvr", "live") else "vod",
            backend=backend,
            estimated_size=estimated_size,
            size_exact=size_exact,
            segment_urls=seg_urls,
            audio_segment_urls=seg_audio,
            abyss_slug=abyss_slug,
            abyss_label=abyss_label,
            sub_lang=sub_lang,
            wait_mux=False if shutil.which("ffmpeg") else bool(seg_urls and seg_audio),  # v2.9.8 canlı mux
        )
        work_dir = get_cache_dir() / "streams" / tid
        job = ActiveStreamJob(ticket, work_dir)
        job.final_dir = final_dir
        job.manager = self  # v3.1.0: relay URL tazelemesi probe önbelleğine erişsin
        with self._lock:
            self._tickets[tid] = ticket
            self._jobs[tid] = job
        job.ensure_started()
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[StreamTicket]:
        return self._tickets.get(ticket_id)

    def get_job(self, ticket_id: str) -> Optional[ActiveStreamJob]:
        return self._jobs.get(ticket_id)

    def active_job_count(self) -> int:
        """v3.2.2: bitmemiş (çalışan) kayıt işi sayısı — RSS valfi için zorunlu.
        Aktif iş VARKEN daemon asla kendini yeniden başlatmaz (indirme yarıda kesilmez)."""
        n = 0
        for job in list(self._jobs.values()):
            if job and not job.completed and not job.failed:
                n += 1
        return n

    def list_jobs(self) -> List[Dict[str, Any]]:
        """Aktif / sonlanmış stream kayıt işlerini GUI ve CLI için listeler (v2.8.0)."""
        out: List[Dict[str, Any]] = []
        with self._lock:
            items = list(self._tickets.items())
        for tid, tk in items:
            job = self._jobs.get(tid)
            size_now = 0
            if job:
                active = job.output_file if job.completed else job.stream_file
                if active.exists():
                    size_now = active.stat().st_size
            out.append(
                {
                    "ticket": tid,
                    "filename": tk.filename,
                    "source_url": tk.source_url[:120],
                    "mode": tk.mode,
                    "hls_mode": tk.hls_mode,
                    "backend": tk.backend,
                    "expected_total": int(tk.estimated_size or 0),
                    "segment_count": len(tk.segment_urls),
                    "client_paused": bool(getattr(job, "client_paused", False)),
                    "wait_mux": bool(tk.wait_mux),
                    "size_exact": bool(tk.size_exact),
                    "completed": bool(job.completed) if job else False,
                    "failed": bool(job.failed) if job else False,
                    "served_bytes": int(job.served_bytes) if job else 0,
                    "size_bytes": size_now,
                    "age_sec": int(time.time() - tk.created_at),
                }
            )
        out.sort(key=lambda d: d["age_sec"])
        return out

    def stop_job(self, ticket_id: str) -> bool:
        job = self._jobs.get(ticket_id)
        if not job:
            return False
        job.stop()
        return True

    def clear_jobs(self, mode: str = "finished", ticket_id: str = "") -> int:
        """v2.8.2: İzleyici kartındaki kayıtları temizler (finished | all | tek bilet)."""
        with self._lock:
            if ticket_id:
                ids = [ticket_id] if ticket_id in self._tickets else []
            elif mode == "all":
                ids = list(self._tickets.keys())
            else:
                ids = [
                    tid
                    for tid, job in self._jobs.items()
                    if job.completed or job.failed
                ]
            for tid in ids:
                job = self._jobs.pop(tid, None)
                self._tickets.pop(tid, None)
                if job:
                    job.stop()
                    if job.work_dir.exists():
                        shutil.rmtree(job.work_dir, ignore_errors=True)
        return len(ids)

    def parse_hls_master(
        self,
        m3u8_url: str,
        cookies: str = "",
        referer: str = "",
        origin: str = "",
        user_agent: str = "",
        raw_manifest_text: str = "",
    ) -> List[VideoFormatOption]:
        headers = build_stream_headers(referer=referer, origin=origin, cookies=cookies, user_agent=user_agent)
        eff_origin = headers.get("Origin", "")

        body = raw_manifest_text
        if not body:
            try:
                raw_bytes = fetch_url_bytes(m3u8_url, headers, timeout=6.0, retries=2)
                body = raw_bytes.decode("utf-8", errors="ignore")
            except Exception as exc:
                logger.debug("HLS manifest okunamadı (%s): %s", m3u8_url[:80], exc)
                return [
                    VideoFormatOption(
                        id="hls_orig",
                        label="HLS Video Akışı (MP4)",
                        ext="mp4",
                        delivery="stream_proxy",
                        source_url=m3u8_url,
                        stream_referer=referer,
                        stream_origin=eff_origin,
                        is_hls=True,
                    )
                ]

        if "#EXT-X-STREAM-INF" not in body:
            return [
                VideoFormatOption(
                    id="hls_single",
                    label="HLS Video Akışı (MP4)",
                    ext="mp4",
                    delivery="stream_proxy",
                    source_url=m3u8_url,
                    stream_referer=referer,
                    stream_origin=eff_origin,
                    manifest_text=body if is_hls_playlist_text(body) else "",
                    is_hls=True,
                )
            ]

        has_separate_audio = "#EXT-X-MEDIA:" in body and "TYPE=AUDIO" in body and 'URI="' in body
        variants: List[VideoFormatOption] = []
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF:") and i + 1 < len(lines):
                uri_line = lines[i + 1]
                if uri_line.startswith("#"):
                    continue
                full_uri = urllib.parse.urljoin(m3u8_url, uri_line)
                res_m = re.search(r"RESOLUTION=(\d+)x(\d+)", line)
                bw_m = re.search(r"BANDWIDTH=(\d+)", line)
                height = int(res_m.group(2)) if res_m else 0
                res_txt = f"{height}p" if height else "HLS"
                bw_kbps = f" ({int(bw_m.group(1)) // 1000} kbps)" if bw_m else ""
                # Eğer Master Playlist içinde ayrık ses grubu varsa (#EXT-X-MEDIA:TYPE=AUDIO),
                # en yüksek kalite için master URL'yi de koru ki Türkçe ses otomatik birleşsin!
                target_src = m3u8_url if has_separate_audio else full_uri
                variants.append(
                    VideoFormatOption(
                        id=f"hls_{height}_{i}",
                        label=f"{res_txt} HD MP4{bw_kbps}",
                        ext="mp4",
                        resolution=res_txt,
                        height=height,
                        delivery="stream_proxy",
                        source_url=target_src,
                        stream_referer=referer,
                        stream_origin=eff_origin,
                        is_hls=True,
                    )
                )

        variants.sort(key=lambda x: x.height, reverse=True)
        return variants or [
            VideoFormatOption(
                id="hls_default",
                label="HLS Video (MP4)",
                ext="mp4",
                delivery="stream_proxy",
                source_url=m3u8_url,
                stream_referer=referer,
                stream_origin=eff_origin,
                is_hls=True,
            )
        ]

    def probe_formats(
        self,
        page_url: str,
        captured_streams: List[Dict[str, Any]],
        cookies: str = "",
        referer: str = "",
        user_agent: str = "",
        use_ytdlp: bool = True,
        force_refresh: bool = False,
        abyss_enabled: bool = False,
        bili_cid: str = "",
    ) -> Dict[str, Any]:
        captured_streams = cap_captured_streams(captured_streams or [])
        extra_bili: List[VideoFormatOption] = []
        # v3.1.0: tarayıcı EME/DRM yakalaması (page_hook requestMediaKeySystemAccess kancası)
        # -> bar 'bulunamadı' yerine net DRM mesajı göstersin; drm:// kaynağı seçeneklere SIZMASIN
        page_drm_flag = any((st.get("url") or "").startswith("drm://detected") for st in captured_streams)
        captured_streams = [st for st in captured_streams if not (st.get("url") or "").startswith("drm://")]
        # v3.4.0: abyss kaynak algı bayrağı — abyss kapalıyken bar'a YERELLEŞTİRİLMİŞ aktivasyon
        # notu gönderilir (linkler zaten abyss_enabled=False iken üretilmez).
        abyss_detected = any(
            (st.get("url") or "").startswith(("abyssif://", "abyss://")) for st in captured_streams
        )
        # v3.1.0: player iframe bildirimleri (text/html) seçenek listesine 'video' olarak SIZMASIN
        captured_streams = [
            st for st in captured_streams
            if not ((st.get("mime") or "").lower().startswith("text/html") and not st.get("manifestText"))
        ]
        # v2.9.6: bilibili playurl SUNUCU TARAFI (çerezlerle) — sayfa kancası sussа bile kaynak gelir
        low_page = (page_url or "").lower()
        if not abyss_detected and any(h in low_page for h in ("abyss.to", "abyssplayer.com", "abysscdn.com", "embedplayabyss.top", "short.icu")):
            abyss_detected = True
        if any(h in low_page for h in ("bilibili.com", "b23.tv")):
            bm = re.search(r"/video/(BV[0-9A-Za-z]+)", page_url or "")
            if not bm:
                # v3.1.0: b23.tv kısa linki -> gerçek /video/BV... adresine çöz
                try:
                    rq0 = urllib.request.Request(page_url, headers={"User-Agent": user_agent or _UA_CHROME})
                    with urllib.request.urlopen(rq0, timeout=8) as rr0:
                        bm = re.search(r"/video/(BV[0-9A-Za-z]+)", rr0.geturl() or "")
                except Exception:
                    bm = None
            cid = (bili_cid or "").strip()
            if not cid:
                for st in captured_streams:
                    mc = re.search(r'"cid"\s*:\s*(\d{4,})', st.get("manifestText") or "")
                    if mc:
                        cid = mc.group(1)
                        break
            # v3.1.0: sayfa kancası susarsa cid'yi SUNUCU TARAFINDA bul (pagelist/view API)
            if bm and not cid:
                cid = fetch_bilibili_cid(bm.group(1), cookies, user_agent)
            if bm and cid:
                extra_bili = fetch_bilibili_quality_options(bm.group(1), cid, cookies, user_agent)
                for item in fetch_bilibili_playurl_streams(bm.group(1), cid, cookies, user_agent):
                    if item["url"] not in [c.get("url") for c in captured_streams]:
                        captured_streams = captured_streams + [item]
        # v3.2.2: akış sayısı CANLI sayfalarda sürekli oynar -> her probe yeni anahtar =
        # önbellek çöplüğü. 8'lik kovalarla anahtar sabitlenir (aynı sayfa = aynı önbellek).
        cache_key = f"{page_url}|{len(captured_streams) // 8}"
        if not force_refresh:
            with self._lock:
                cached = self._probe_cache.get(cache_key)
                if cached and (time.time() - cached[0]) < 600:
                    return cached[1]

        options: List[VideoFormatOption] = []
        title = ""
        seen_urls = set()

        # v2.8.5: DASH segment serilerini grupla; parça parça "Doğrudan Video" çöplüğü YOK!
        series_groups: Dict[str, List[Dict[str, Any]]] = {}
        audio_groups: Dict[str, List[Dict[str, Any]]] = {}
        leftover: List[Dict[str, Any]] = []
        for item in captured_streams:
            s_url0 = (item.get("url") or "").strip()
            # v3.1.0: abyssif:// / abyss:// yakalamaları yalnızca _abyss_options'a aittir
            if s_url0.startswith(("abyssif://", "abyss://", "drm://")):
                continue
            key = segment_series_key(s_url0)
            mime0 = (item.get("mime") or "").lower()
            is_audio0 = mime0.startswith("audio") or key.lower().endswith(("#.m4a", "#.cmfa"))
            if key:
                (audio_groups if is_audio0 else series_groups).setdefault(key, []).append(item)
            else:
                leftover.append(item)
        # v2.9.3: CANLI sayfada segment tahmini/manifest yoklaması YAPMA (600 HEAD seli = donma)
        page_live = any(
            classify_manifest_live((it.get("manifestText") or "")).get("live", False)
            for it in captured_streams[:24]
        )
        series_options: List[VideoFormatOption] = []
        first_audio_key = next(iter(audio_groups), "")
        for gi, (key, members) in enumerate(series_groups.items()):
            urls_seen = []
            for m in members:
                u = (m.get("url") or "").strip()
                if u and u not in urls_seen:
                    urls_seen.append(u)
            if not page_live:
                full_list = extrapolate_segment_list(urls_seen, {"Referer": referer or page_url, "User-Agent": user_agent or "IDM-Linux/2.8"})
                if len(full_list) > len(urls_seen):
                    urls_seen = full_list
            manifest_hit = ""
            drm_here = False
            base_pre = (urls_seen[0] if urls_seen else "").split(".smil/", 1)[0]
            if base_pre:
                for it in captured_streams:
                    u2 = (it.get("url") or "").strip()
                    if not u2 or base_pre not in u2:
                        continue
                    mt2 = (it.get("manifestText") or "")[:400]
                    if ".mpd" in u2 or "<MPD" in mt2:
                        manifest_hit = u2
                        break
            if not manifest_hit and not page_live:
                manifest_hit = probe_dash_manifest(  # v2.9.1: kısa zaman aşımı
                urls_seen[0] if urls_seen else (members[0].get("url") or ""),
                {"Referer": referer or page_url, "User-Agent": user_agent or "IDM-Linux/2.8"},
                timeout=1.5,
            )
            mpd_text_full = ""
            if manifest_hit and not page_live:
                mpd_text_full = fetch_mpd_full(
                    manifest_hit, {"Referer": referer or page_url, "User-Agent": user_agent or "IDM-Linux/2.9"}
                )
                drm_here = mpd_has_drm(mpd_text_full)
                if not drm_here:
                    parsed_lists = parse_mpd_segment_list(mpd_text_full, manifest_hit)
                    if parsed_lists["video"]:
                        urls_seen = parsed_lists["video"]
                        if parsed_lists["audio"]:
                            audio_groups[first_audio_key or "auto"] = [
                                {"url": u, "referer": referer or page_url} for u in parsed_lists["audio"]
                            ]
                            first_audio_key = first_audio_key or "auto"
            n_parca = len(urls_seen)
            series_options.append(
                VideoFormatOption(
                    id=f"segseries_{gi}",
                    label=(
                        "🔒 DRM KORUMALI (Widevine) — bu içerik indirilemez"
                        if drm_here
                        else f"Tüm Segmentler → TEK VİDEO ({n_parca} parça, baştan sona sesli birleşik)"
                    ),
                    delivery=("drm_blocked" if drm_here else "stream_proxy"),
                    ext="mp4",
                    source_url=urls_seen[0] if urls_seen else (members[0].get("url") or ""),
                    stream_referer=(members[0].get("referer") or referer or page_url),
                    stream_origin=(members[0].get("origin") or ""),
                    stream_user_agent=user_agent,
                    segment_urls=urls_seen,
                    manifest_url=manifest_hit,
                    audio_segment_urls=(
                        [ (a.get("url") or "").strip() for a in audio_groups[first_audio_key] ]
                        if first_audio_key else []
                    ),
                )
            )
        if series_options:
            captured_streams = leftover

        for item in captured_streams:
            s_url = (item.get("url") or "").strip()
            if not s_url or s_url in seen_urls:
                continue
            # v3.1.0: sanal yakalama şemaları doğrudan video olarak listelenmez
            if s_url.startswith(("abyssif://", "abyss://", "drm://")):
                continue
            # v3.6.0: ALTYAZI yakalamaları video seçeneği OLMAMALI — aşağıdaki
            # _subtitle_options() bunları '📝 Altyazı: <dil>' grubu olarak listeler.
            if item.get("sub_label") or _looks_like_subtitle_capture(s_url, item.get("mime") or ""):
                continue
            seen_urls.add(s_url)

            mime = (item.get("mime") or "").lower()
            size = item.get("size")
            s_ref = item.get("referer") or referer or page_url
            s_orig = item.get("origin") or ""
            manifest_txt = item.get("manifestText") or ""
            flagged_hls = bool(item.get("isHls")) or is_hls_playlist_text(manifest_txt)
            lower_path = urllib.parse.urlparse(s_url).path.lower()

            if "googlevideo.com/videoplayback" in s_url:
                continue

            if flagged_hls or ".m3u8" in lower_path or "mpegurl" in mime or looks_like_hls_url(s_url):
                hls_opts = self.parse_hls_master(
                    s_url,
                    cookies=cookies,
                    referer=s_ref,
                    origin=s_orig,
                    user_agent=user_agent,
                    raw_manifest_text=manifest_txt,
                )
                existing_keys = {(o.source_url, o.resolution) for o in options}
                for ho in hls_opts:
                    if (ho.source_url, ho.resolution) not in existing_keys:
                        options.append(ho)
                        existing_keys.add((ho.source_url, ho.resolution))
            elif ".mpd" in lower_path or "dash+xml" in mime:
                options.append(
                    VideoFormatOption(
                        id=f"dash_{len(options)}",
                        label="MPEG-DASH Video Akışı (MP4)",
                        ext="mp4",
                        delivery="stream_proxy",
                        source_url=s_url,
                        stream_referer=s_ref,
                        stream_origin=s_orig,
                    )
                )
            else:
                ext = "mp4"
                for cand_ext in ("mp4", "webm", "mkv", "flv", "mov", "mp3", "m4a", "ogg"):
                    if lower_path.endswith(f".{cand_ext}") or cand_ext in mime:
                        ext = cand_ext
                        break
                size_str = f" — {format_bytes(size)}" if size else ""
                # v3.11.0: VİDEO OLMAYAN dosyalar (gofile zip/rar/pdf/apk/iso/exe...) artık
                # "Doğrudan Video (MP4)" diye SAHTE etiket almaz — gerçek uzantıyla "Dosya"
                # olarak listelenir (goFile anında yakalama ile birlikte doğru görüntü).
                file_ext = ""
                if lower_path:
                    cand = lower_path.rsplit("/", 1)[-1].split("?")[0].rsplit(".", 1)
                    if len(cand) == 2 and 1 <= len(cand[1]) <= 5 and cand[1].isalnum():
                        file_ext = cand[1]
                _FILE_ONLY_EXTS = (
                    "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "pdf", "exe", "msi",
                    "dmg", "apk", "iso", "deb", "rpm", "appimage", "txt", "doc", "docx",
                    "xls", "xlsx", "ppt", "pptx", "epub", "csv", "bin",
                )
                is_plain_file = file_ext in _FILE_ONLY_EXTS
                if is_plain_file:
                    ext = file_ext
                    label_txt = f"Dosya ({ext.upper()}){size_str}"
                else:
                    label_txt = f"Doğrudan Video ({ext.upper()}){size_str}"
                options.insert(
                    0,
                    VideoFormatOption(
                        id=f"direct_{len(options)}",
                        label=label_txt,
                        ext=ext,
                        filesize=size,
                        delivery=(
                            "stream_proxy"
                            if any(h in s_url.lower() for h in ("bilibili.com", "b23.tv", "hdslb.com"))
                            else "direct"
                        ),  # v2.9.3: bilibili Referer ister -> köprüden akıt
                        direct_url=s_url,
                        source_url=s_url,
                        stream_referer=s_ref,
                        stream_origin=s_orig,
                    ),
                )

        # v3.4.0 YOUTUBE ANINDA: yakalanan googlevideo akışlarından 0 sn'de oynatılabilir
        # "⚡ Hazır" seçenekler (muxed itag 18/22 + en iyi ses) — kullanıcı yt-dlp beklerken
        # bile ANINDA indirebilir. Tam -J sonucu gelince zengin listeyle değişir.
        if any(h in low_page for h in ("youtube.com", "youtu.be", "youtube-nocookie.com")):
            quick_opts = _youtube_quick_options(captured_streams, page_url, referer)
            if quick_opts:
                options = quick_opts + options

        hlsopts = [o for o in options if o.delivery == "stream_proxy" and o.is_hls and not o.filesize][:6]
        if hlsopts:
            hdrs0 = {"User-Agent": user_agent or "IDM-Linux/2.8", "Referer": referer or ""}
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                futs = {ex.submit(estimate_hls_total_bytes, "", o.source_url, hdrs0): o for o in hlsopts}
                for fut in concurrent.futures.as_completed(futs):
                    tot, exact = fut.result()
                    if exact and tot > 0:
                        futs[fut].filesize = tot
                        futs[fut].filesize_exact = True

        should_run_ytdlp = use_ytdlp and (not options or _is_known_ytdlp_site(page_url))
        # v2.9.10 KRİTİK: ytdlp_bin ÖNCE atanmalı! 2.9.9'daki ters sıralama UnboundLocalError
        # fırlatıyor, probe TÜMDEN çöküp YouTube/bilibili/ok.ru/abyss barını BOŞ bırakıyordu.
        ytdlp_bin = find_ytdlp() if should_run_ytdlp else None
        if should_run_ytdlp and not ytdlp_bin:
            # v2.9.6: yt-dlp eksikse arka planda kur (ok.ru/vk/bilibili zinciri kendiliğinden canlansın)
            ensure_ytdlp_background()
            if page_url and page_url not in _YTDP_PENDING_PAGES:
                _YTDP_PENDING_PAGES.append(page_url)
            # v3.10.1: İLK kullanımda kurulumu kısa süre BEKLE — kullanıcı boş bar
            # görmek yerine ilk denemede kaynakları görsün (köprü limiti 45 sn).
            ytdlp_bin = wait_for_ytdlp(timeout=25.0)
            if ytdlp_bin:
                logger.info("yt-dlp hazır — ilk probe bu istekte çözümleniyor")
        is_live = False
        is_dvr = False
        _live_head_cache: Dict[str, str] = {}
        for item in captured_streams:
            mt_txt = item.get("manifestText") or ""
            if not mt_txt:
                u_l = (item.get("url") or "").split("?")[0]
                if u_l.endswith((".m3u8", ".mpd")) or ".m3u8?" in (item.get("url") or "") or ".mpd?" in (item.get("url") or ""):
                    if u_l not in _live_head_cache:
                        _live_head_cache[u_l] = fetch_mpd_full(
                            item.get("url") or "", {"Referer": referer or page_url, "User-Agent": user_agent or "IDM-Linux/2.9"}, limit=8192
                        ) or "#"
                    mt_txt = _live_head_cache[u_l]
            cl_m = classify_manifest_live(mt_txt)
            if cl_m["live"]:
                is_live = True
                is_dvr = is_dvr or cl_m["dvr"]
        drm_flag = False
        ytdlp_updating = False
        ytdlp_live_status = ""
        probe_pending = False  # v3.1.0: arka plan probe işareti

        # v3.1.0 ARKA PLAN PROBE (YouTube'un ilk açılış yavaşlığına KÖKLÜ ÇÖZÜM):
        # Bilinen yt-dlp sitelerinde (YouTube/vk/ok.ru/bilibili...) -J çözümlemesi 20-90 sn
        # sürer; bar bu sürede BOŞ kalırdı. Artık yt-dlp probe'u ARKA PLANDA çalışır, bar
        # anında (yakalanan akışlarla) döner; probe bitince önbelleğe yazılır ve tarayıcıya
        # IDM_MEDIA_UPDATED haberi gider (bar kendini tazeleyip kaliteleri gösterir).
        run_probe_inline = True
        # v3.14.0: dosya barındırıcılar (gofile vb.) yt-dlp'ye ASLA verilmez —
        # '[Piracy]' gürültüsü + 3-6 sn boşa gecikme (kullanıcı günlüğü vakası).
        if _never_ytdlp_probe(page_url):
            run_probe_inline = False
        elif (
            ytdlp_bin
            and page_url.startswith(("http://", "https://"))
            and _is_known_ytdlp_site(page_url)
            and not force_refresh
        ):
            now_ts = time.time()
            with self._lock:
                pend_ts = self._probe_pending.get(page_url)
            if pend_ts and (now_ts - pend_ts) < 180:
                run_probe_inline = False  # arka plan zaten çalışıyor
                probe_pending = True
            else:
                with self._lock:
                    self._probe_pending[page_url] = now_ts
                run_probe_inline = False
                probe_pending = True

                def _bg_probe() -> None:
                    try:
                        bg_res = self.probe_formats(
                            page_url=page_url,
                            captured_streams=captured_streams,
                            cookies=cookies,
                            referer=referer,
                            user_agent=user_agent,
                            use_ytdlp=True,
                            force_refresh=True,
                            abyss_enabled=abyss_enabled,
                            bili_cid=bili_cid,
                        )
                        # v3.1.0: tam sonuç hazır -> tarayıcı barı hemen tazelesin
                        _notify_probe_done(len((bg_res or {}).get("formats") or []))
                    except Exception as bg_exc:
                        logger.info("Arka plan probe hatası (%s): %s", page_url[:80], bg_exc)
                    finally:
                        with self._lock:
                            self._probe_pending.pop(page_url, None)

                threading.Thread(target=_bg_probe, name=f"bgprobe-{uuid.uuid4().hex[:6]}", daemon=True).start()

        if (
            run_probe_inline
            and ytdlp_bin
            and page_url.startswith(("http://", "https://"))
            and not _never_ytdlp_probe(page_url)
        ):
            # v3.14.2: uzantı çerezi yoksa YouTube için sistem tarayıcısı oturum çerezleri
            # okunur (bot-kontrol 'giriş yap' engelinin kökten çözümü)
            cookie_file = _probe_cookie_file(cookies, page_url)
            try:
                info, probe_err, drm_flag = _run_ytdlp_probe(
                    ytdlp_bin, page_url, cookie_file, user_agent, referer
                )
                if info is not None:
                    title = info.get("title") or ""
                    ytdlp_live_status = str(info.get("live_status") or "")
                    if bool(info.get("is_live")) or ytdlp_live_status == "is_live":
                        is_live = True
                        is_dvr = True  # YT canlıları DVR penceresi sunar
                    fmts = info.get("formats") or []
                    extracted = self._summarize_ytdlp_formats(fmts, page_url)
                    if extracted:
                        options = extracted + options
                    # v2.9.4: çok dilli sesler + altyazı dosyaları bara listelenir
                    lang_opts = _youtube_lang_options(info, page_url)
                    if lang_opts:
                        options = options + lang_opts
                elif probe_err:
                    logger.info("yt-dlp probe başarısız (%s): %s", page_url[:80], probe_err[:200])
                    if "DRM" in probe_err.upper():
                        drm_flag = True
                    # v2.9.9/v3.0.0: site ekstraktları haftalık kırılır (YouTube/bilibili/ok.ru)
                    # returncode != 0, parse hatası VEYA zaman aşımı — HER başarısızlıkta tazele
                    # v3.11.0: "Sign in to confirm you're not a bot" = yt-dlp KIRIK demek.
                    # Günlük tek güncelleme yetmez; bot-check hâlinde 3 saatlik kısa pencereyle
                    # YÜKSELTME ZORLANIR (kullanıcı: "bazen hiç bulamıyor" — kök nedeni budur).
                    low_probe = probe_err.lower()
                    botcheck = (
                        "sign in to confirm" in low_probe
                        or "not a bot" in low_probe
                        or "unable to extract" in low_probe
                        and "youtube" in low_probe
                    )
                    # v3.13.0: ok.ru/vk ekstrakt kırılmaları da ACIL sayılır —
                    # "unable to extract" + ok.ru/vk = yt-dlp'nin ok.ru ekstraktörü
                    # eskimiş demektir; 3 saatlik hızlı yükseltme penceresi açılır.
                    okru_broken = (
                        "unable to extract" in low_probe
                        and ("ok.ru" in low_probe or "odnoklassniki" in low_probe or "vk.com" in low_probe or "vkvideo" in low_probe)
                    )
                    if ytdlp_update_due() or (botcheck and _ytdlp_upgrade_window_open()) or (okru_broken and _ytdlp_upgrade_window_open()):
                        ytdlp_updating = True
                        mark_ytdlp_update()
                        ensure_ytdlp_background(upgrade=True)
            finally:
                if cookie_file:
                    cookie_file.unlink(missing_ok=True)

        # v2.9.8: MPD yakalamalarında ÇÖZÜNÜRLÜK ETİKETLİ seçenekler (belirsizlik bitti)
        if series_options:
            reps_all: List[Dict[str, Any]] = []
            for st in captured_streams[:24]:
                mt = st.get("manifestText") or ""
                u_l = (st.get("url") or "").lower()
                if ".mpd" in u_l or "<MPD" in mt[:200]:
                    reps_all.extend(parse_mpd_representations(mt, st.get("url") or ""))
            if len(reps_all) >= 2:
                labeled: List[VideoFormatOption] = []
                for rp in reps_all[:6]:
                    vsegs = ([rp["init"]] + rp["segments"]) if rp["init"] else rp["segments"]
                    asegs = ([rp["audio_init"]] + rp["audio_segments"]) if rp["audio_init"] else rp["audio_segments"]
                    labeled.append(
                        VideoFormatOption(
                            id=f"dash_{rp['height']}_{len(labeled)}",
                            label=(
                                f"{rp['height']}p • MPEG-DASH (video+ses)"
                                if asegs
                                else f"{rp['height']}p • MPEG-DASH"
                            ),
                            ext="mp4",
                            resolution=f"{rp['height']}p",
                            height=rp["height"],
                            delivery="stream_proxy",
                            source_url=page_url,
                            stream_referer=referer or page_url,
                            segment_urls=vsegs,
                            audio_segment_urls=asegs,
                            is_hls=True,
                        )
                    )
                if labeled:
                    series_options = labeled

        options = series_options + options
        if extra_bili:
            options = extra_bili + options

        if page_drm_flag and not options:
            drm_flag = True  # v3.1.0: EME kanıtı — Widevine/FairPlay korumalı oynatıcı

        options = apply_delivery_guard(options, referer, page_url)

        # v2.9.4: altyazı parçaları (HLS SUBTITLES / MPD text / <track> yakalamaları)
        sub_opts = _subtitle_options(captured_streams, referer, page_url)
        if sub_opts:
            options = options + sub_opts
        # v2.9.4: abyss.to (v3.1.0: iframe/short.icu sayfa çözücüsüyle birlikte)
        if abyss_enabled:
            abyss_opts = _abyss_options(captured_streams, page_url)
            if abyss_opts:
                options = abyss_opts + options

        # v3.2.2 BELLEK KALKANI: YANIT tam listeyi taşır (VOD indirmesi eksik kalmasın —
        # zaten MPD/HLS ayrıştırıcıları parse_mpd_* içinde sınırlı). ANCAK ÖNBELLEĞE
        # yazılan kopya TRİMLENİR: DVR/canlı sayfada her probe farklı cache anahtarıyla
        # gelir; on binlerce segment URL'sinin 16-48 kayıt boyunca tutulması = yüzlerce
        # MB kalıcı RSS (dsmartgo izlerken daemon OOM kök nedeni).
        # v3.5.0: altyazı grubu başlığı — bar, altyazıları ayrı bölüm olarak gruplar
        _has_subs = any(o.delivery in ("subs", "yt_subs") for o in options)
        result_payload = {
            "title": title,
            "is_live": is_live,
            "is_dvr": is_dvr,
            "drm": drm_flag,
            "abyss_detected": bool(abyss_detected),  # v3.4.0: pasifken bar notu için
            "ytdlp_missing": bool(should_run_ytdlp and not ytdlp_bin),
            "ytdlp_updating": bool(ytdlp_updating),
            "ytdlp_pending": bool(probe_pending),
            "subs_header": (_bar_subs_header_text() if _has_subs else ""),
            "formats": [
                {
                    "id": o.id,
                    "label": o.label,
                    "ext": o.ext,
                    "resolution": o.resolution,
                    "height": o.height,
                    "filesize": o.filesize,
                    "filesize_exact": o.filesize_exact,
                    "filesize_human": format_bytes(o.filesize),
                    "delivery": o.delivery,
                    "direct_url": o.direct_url,
                    "format_selector": o.format_selector,
                    "source_url": o.source_url,
                    "stream_referer": o.stream_referer,
                    "stream_origin": o.stream_origin,
                    "stream_user_agent": o.stream_user_agent,
                    "mux_video_url": o.mux_video_url,
                    "mux_audio_url": o.mux_audio_url,
                    "segment_urls": o.segment_urls,
                    "manifest_url": o.manifest_url,
                    "audio_segment_urls": o.audio_segment_urls,
                    "mux_video_headers": o.mux_video_headers,
                    "mux_audio_headers": o.mux_audio_headers,
                    "manifest_text": o.manifest_text,
                    "is_hls": o.is_hls,
                    "audio_only": o.audio_only,
                    "abyss_slug": o.abyss_slug,
                    "abyss_label": o.abyss_label,
                    "sub_lang": o.sub_lang,
                }
                for o in options
            ],
        }

        # v3.1.0: KISMİ sonuç (yt-dlp arka planda) ÖNBELLEĞE YAZILMAZ — 10 dakika boyunca
        # yarım bar gösterilmesin. Tam sonuç (inline) önbelleğe girer.
        if options and not probe_pending:
            _CACHE_SEG_CAP = 400

            def _cache_fmt(f: Dict[str, Any]) -> Dict[str, Any]:
                g = dict(f)
                if len(g.get("segment_urls") or []) > _CACHE_SEG_CAP:
                    g["segment_urls"] = g["segment_urls"][-_CACHE_SEG_CAP:]
                if len(g.get("audio_segment_urls") or []) > _CACHE_SEG_CAP:
                    g["audio_segment_urls"] = g["audio_segment_urls"][-_CACHE_SEG_CAP:]
                if g.get("manifest_text") and len(g["manifest_text"]) > 65536:
                    g["manifest_text"] = g["manifest_text"][:65536]
                return g

            cache_copy = {
                "title": result_payload["title"],
                "is_live": is_live,
                "is_dvr": is_dvr,
                "drm": drm_flag,
                "abyss_detected": bool(abyss_detected),  # v3.4.0: önbellekte de kalsın
                "ytdlp_missing": bool(should_run_ytdlp and not ytdlp_bin),
                "ytdlp_updating": bool(ytdlp_updating),
                "ytdlp_pending": False,
                "subs_header": result_payload.get("subs_header", ""),
                "formats": [_cache_fmt(f) for f in result_payload["formats"]],
            }
            with self._lock:
                self._probe_cache[cache_key] = (time.time(), cache_copy)
                # v3.2.2: önbellek ARTIK ÇİFT SINUURLU — 16 kayıt VE yaklaşık 24 MB toplam
                # gövde. Aşımada EN YAŞLI kayıt atılır -> daemon RSS'i probe'la şişemez.
                def _payload_kb(p: Dict[str, Any]) -> int:
                    try:
                        return len(json.dumps(p, ensure_ascii=False, default=str)) // 1024
                    except Exception:
                        return 4096

                total_kb = sum(_payload_kb(v[1]) for v in self._probe_cache.values())
                while len(self._probe_cache) > 16 or total_kb > 24576:
                    if not self._probe_cache:
                        break
                    oldest = min(self._probe_cache, key=lambda k: self._probe_cache[k][0])
                    total_kb -= _payload_kb(self._probe_cache[oldest][1])
                    self._probe_cache.pop(oldest, None)

        return result_payload

    def _summarize_ytdlp_formats(
        self,
        fmts: List[Dict[str, Any]],
        page_url: str,
    ) -> List[VideoFormatOption]:
        best_audio_size = 0
        best_audio_size_exact = False
        best_direct_audio: Optional[Dict[str, Any]] = None
        for f in fmts:
            if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none"):
                sz = f.get("filesize") or f.get("filesize_approx") or 0
                if sz > best_audio_size:
                    best_audio_size = sz
                    best_audio_size_exact = bool(f.get("filesize"))
                proto = (f.get("protocol") or "").lower()
                u_val = f.get("url") or ""
                if (
                    proto in ("http", "https")
                    and u_val
                    and not looks_like_hls_url(u_val)
                    and "manifest" not in u_val.lower()
                ):
                    score = (1000 if f.get("ext") == "m4a" else 0) + (f.get("abr") or 0)
                    prev_score = (
                        (1000 if best_direct_audio.get("ext") == "m4a" else 0) + (best_direct_audio.get("abr") or 0)
                        if best_direct_audio
                        else -1
                    )
                    if score > prev_score:
                        best_direct_audio = f

        by_height: Dict[int, Dict[str, Any]] = {}
        progressive_by_height: Dict[int, Dict[str, Any]] = {}

        for f in fmts:
            vcodec = f.get("vcodec")
            acodec = f.get("acodec")
            height = f.get("height") or 0
            if not vcodec or vcodec == "none" or height < 144:
                continue

            proto = (f.get("protocol") or "").lower()
            url_val = f.get("url") or ""
            is_hls_fmt = "m3u8" in proto or looks_like_hls_url(url_val)
            is_direct_http = (
                proto in ("http", "https")
                and bool(url_val)
                and not is_hls_fmt
                and "manifest" not in url_val.lower()
            )
            has_audio = acodec not in (None, "none")

            if has_audio and is_direct_http:
                prev = progressive_by_height.get(height)
                if not prev or (f.get("tbr") or 0) > (prev.get("tbr") or 0):
                    progressive_by_height[height] = f

            # Hem doğrudan HTTP hem de HLS akışlarını kalite tablosuna dahil et!
            prev_v = by_height.get(height)
            cand_score = (10000 if f.get("ext") == "mp4" else 0) + (5000 if is_direct_http else 0) + (f.get("tbr") or 0)
            prev_score = (
                (10000 if prev_v.get("ext") == "mp4" else 0)
                + (5000 if (prev_v.get("protocol") in ("http", "https") and "m3u8" not in (prev_v.get("protocol") or "")) else 0)
                + (prev_v.get("tbr") or 0)
                if prev_v
                else -1
            )
            if cand_score > prev_score:
                by_height[height] = f

        results: List[VideoFormatOption] = []
        quality_names = {
            2160: "4K Ultra HD",
            1440: "2K QHD",
            1080: "Full HD",
            720: "HD",
            480: "SD",
            360: "Standart",
            240: "Düşük",
        }

        for h in sorted(by_height.keys(), reverse=True):
            qtag = quality_names.get(h, "")
            if h in progressive_by_height:
                pf = progressive_by_height[h]
                sz = pf.get("filesize") or pf.get("filesize_approx")
                sz_txt = f" — {format_bytes(sz)}" if sz else ""
                ext_val = pf.get("ext") or "mp4"
                p_hdrs = pf.get("http_headers") or {}
                results.append(
                    VideoFormatOption(
                        id=f"yt_direct_{h}",
                        label=f"{h}p {qtag} ({ext_val.upper()} • Doğrudan){sz_txt}".replace("  ", " "),
                        ext=ext_val,
                        resolution=f"{h}p",
                        height=h,
                        filesize=sz,
                        delivery="direct",
                        direct_url=pf["url"],
                        source_url=page_url,
                        stream_referer=p_hdrs.get("Referer") or page_url,
                        stream_user_agent=p_hdrs.get("User-Agent") or "",
                    )
                )
            else:
                vf = by_height[h]
                v_proto = (vf.get("protocol") or "").lower()
                v_url = vf.get("url") or ""
                v_hdrs = vf.get("http_headers") or {}
                is_hls_fmt = "m3u8" in v_proto or looks_like_hls_url(v_url)

                if is_hls_fmt and v_url.startswith("http"):
                    # yt-dlp HLS bulduysa doğrudan 16x yerel HLS motoruna bağla!
                    results.append(
                        VideoFormatOption(
                            id=f"yt_hls_{h}",
                            label=f"{h}p {qtag} (MP4 • 16x Hızlı HLS)".replace("  ", " "),
                            ext="mp4",
                            resolution=f"{h}p",
                            height=h,
                            delivery="stream_proxy",
                            source_url=v_url,
                            stream_referer=v_hdrs.get("Referer") or page_url,
                            stream_user_agent=v_hdrs.get("User-Agent") or "",
                            is_hls=True,
                        )
                    )
                else:
                    v_sz = vf.get("filesize") or vf.get("filesize_approx") or 0
                    est_total = (v_sz + best_audio_size) if v_sz else None
                    sz_txt = f" — ~{format_bytes(est_total)}" if est_total else ""
                    selector = (
                        f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
                        f"bestvideo[height<={h}]+bestaudio/best[height<={h}]"
                    )
                    a_url = (best_direct_audio.get("url") or "") if best_direct_audio else ""
                    a_hdrs = (best_direct_audio.get("http_headers") or {}) if best_direct_audio else {}

                    results.append(
                        VideoFormatOption(
                            id=f"yt_mux_{h}",
                            label=f"{h}p {qtag} (MP4 HD Birleşik){sz_txt}".replace("  ", " "),
                            ext="mp4",
                            resolution=f"{h}p",
                            height=h,
                            filesize=est_total,
                            delivery="stream_proxy",
                            format_selector=selector,
                            source_url=page_url,
                            stream_referer=v_hdrs.get("Referer") or page_url,
                            mux_video_url=v_url,
                            mux_audio_url=a_url,
                            mux_video_headers=v_hdrs,
                            mux_audio_headers=a_hdrs,
                            filesize_exact=bool(vf.get("filesize")) and (best_audio_size_exact or not a_url),
                        )
                    )

        if best_direct_audio and best_direct_audio.get("url"):
            a_sz = best_direct_audio.get("filesize") or best_direct_audio.get("filesize_approx")
            a_ext = best_direct_audio.get("ext") or "m4a"
            sz_txt = f" — {format_bytes(a_sz)}" if a_sz else ""
            a_ua = (best_direct_audio.get("http_headers") or {}).get("User-Agent") or ""
            results.append(
                VideoFormatOption(
                    id="yt_audio_direct",
                    label=f"Sadece Ses — Yüksek Kalite ({a_ext.upper()} • Doğrudan){sz_txt}",
                    ext=a_ext,
                    filesize=a_sz,
                    delivery="direct",
                    direct_url=best_direct_audio["url"],
                    source_url=page_url,
                    stream_referer=page_url,
                    stream_user_agent=a_ua,
                    audio_only=True,
                )
            )
        elif best_audio_size or by_height:
            sz_txt = f" — ~{format_bytes(best_audio_size)}" if best_audio_size else ""
            results.append(
                VideoFormatOption(
                    id="yt_audio_m4a",
                    label=f"Sadece Ses — Yüksek Kalite (M4A){sz_txt}",
                    ext="m4a",
                    filesize=best_audio_size or None,
                    delivery="stream_proxy",
                    format_selector="bestaudio[ext=m4a]/bestaudio",
                    source_url=page_url,
                    stream_referer=page_url,
                    audio_only=True,
                )
            )

        return results


# ---------------------------------------------------------------------------
# v2.8.0 — OYNATMA LİSTESİ (YouTube / Dailymotion / Twitch Koleksiyon vb.) DESTEĞİ
# ---------------------------------------------------------------------------

PLAYLIST_URL_PATTERNS = (
    r"[?&]list=",
    r"/playlist(?:s)?/",
    r"dailymotion\.com/playlist/",
    r"/sets/",
    r"/collections?/",
    r"watch\?v=.*&index=",
)


def is_playlist_url(url: str) -> bool:
    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        return False
    return any(re.search(p, u, re.I) for p in PLAYLIST_URL_PATTERNS)


def probe_playlist_entries(
    page_url: str,
    cookies: str = "",
    user_agent: str = "",
    max_items: int = 60,
) -> Dict[str, Any]:
    """
    yt-dlp --flat-playlist ile oynatma listesinin girişlerini (başlık + URL + süre) sıralar.
    Tekil video URL'si verilirse tek girişlik liste döner (böylece 'video linkiyle indirme'
    de aynı akıştan geçer).
    """
    ytdlp_bin = find_ytdlp()
    if not ytdlp_bin:
        return {"ok": False, "error": "yt-dlp bulunamadı", "entries": [], "title": ""}

    # v3.14.2: YouTube liste çözümlemesi de tarayıcı-oturum fallback'inden geçer
    cookie_file = _probe_cookie_file(cookies, page_url)
    cmd = [
        ytdlp_bin,
        "--no-warnings",
        "--flat-playlist",
        "--playlist-end",
        str(max_items),
        "--dump-single-json",
        "-J",
    ]
    if cookie_file:
        cmd.extend(["--cookies", str(cookie_file)])
    if user_agent:
        cmd.extend(["--user-agent", user_agent])
    cmd.append(page_url)
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=90, check=False)
        if res.returncode != 0 or not res.stdout.strip():
            return {"ok": False, "error": "yt-dlp liste çözemedi", "entries": [], "title": ""}
        data = json.loads(res.stdout.decode("utf-8", errors="ignore"))
    except Exception as exc:
        return {"ok": False, "error": str(exc), "entries": [], "title": ""}
    finally:
        if cookie_file:
            try:
                cookie_file.unlink(missing_ok=True)
            except OSError:
                pass

    entries: List[Dict[str, Any]] = []
    pl_title = data.get("title") or ""
    raw_entries = data.get("entries")
    if raw_entries is None:
        raw_entries = [data]
    for i, ent in enumerate(raw_entries):
        if not isinstance(ent, dict):
            continue
        e_url = ent.get("url") or ent.get("webpage_url") or ""
        if e_url and not e_url.startswith("http"):
            e_url = f"https://www.youtube.com/watch?v={e_url}"
        if not e_url:
            continue
        dur = ent.get("duration")
        entries.append(
            {
                "index": i + 1,
                "url": e_url,
                "title": ent.get("title") or f"Video {i + 1}",
                "duration": int(dur) if isinstance(dur, (int, float)) else 0,
            }
        )
        if len(entries) >= max_items:
            break
    return {"ok": bool(entries), "entries": entries, "title": pl_title, "error": ""}
