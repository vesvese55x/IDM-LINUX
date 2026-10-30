"""
IDM-Linux v3.5.0 — Oynatma Listesi (Playlist) Seri İndirme Motoru.
================================================================================
GUI'deki 'Oynatma Listesi İndir' kartının arkasındaki motor:

 • YouTube / Dailymotion / OK.ru / VK.ru / VK.com ve yt-dlp'nin desteklediği
   TÜM sitelerdeki oynatma listeleri — site, URL'den DİNAMİK algılanır.
 • Videolar SIRALI (tek aktif iş) ve MAKSİMUM hızda indirilir:
   -N 8 paralel parça + doğrudan yt-dlp motoru (IDM köprüsüne bayt kopyalamak
   yerine kaynağından çeker — ekstra kopya maliyeti sıfır).
 • Her video için: Duraklat (SIGSTOP — anında, bağlantı korunur),
   Devam Et (SIGCONT), İptal (sonlandır + .part temizliği).
 • Canlı ilerleme: yüzde, indirilen/toplam MB, hız, ETA — GUI 1 sn'de bir
   /api/playlist/batch/status ile okur.
 • Yarıda kalan indirme (.part) yt-dlp -c ile kendiliğinden DEVAM eder; daemon
   yeniden başlasa bile liste /api/playlist/batch/list ile GUI'ye geri gelir.
================================================================================
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import setup_logger
from .stream_engine import cookies_header_to_netscape_file, find_ytdlp, sanitize_filename

log = setup_logger("playlist-batch", "daemon.log")

# Bir listede en fazla kaç video indirilebilir (IDM barı/ RAM koruması)
MAX_BATCH_ENTRIES = 200
# YouTube TV/ders listeleri çok uzun olabilir — probe tarafı 60'ta kesiyor; burada geniş
_STATUS_NAMES = {
    "queued": "bekliyor",
    "downloading": "indiriliyor",
    "paused": "duraklatıldı",
    "completed": "tamamlandı",
    "failed": "hata",
    "cancelled": "iptal",
}


def detect_playlist_site(url: str) -> str:
    """v3.5.0: Oynatma listesi URL'sinden siteyi dinamik algıla (GUI rozeti için)."""
    u = (url or "").lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    if "dailymotion.com" in u or "dai.ly" in u:
        return "Dailymotion"
    if "ok.ru" in u:
        return "OK.ru"
    if "vk.com" in u or "vk.ru" in u or "vkvideo.ru" in u:
        return "VK"
    if "bilibili.com" in u or "b23.tv" in u:
        return "Bilibili"
    if "rutube.ru" in u:
        return "Rutube"
    if "soundcloud.com" in u:
        return "SoundCloud"
    if "vimeo.com" in u:
        return "Vimeo"
    if "twitch.tv" in u:
        return "Twitch"
    if "izlesene.com" in u:
        return "İzlesene"
    m = re.search(r"(?:^|//|\.)([a-z0-9-]+\.[a-z.]{2,8})(?:/|$)", u)
    return m.group(1) if m else "Web"


@dataclass
class PlaylistEntry:
    index: int
    url: str
    title: str
    duration: int = 0
    status: str = "queued"          # queued|downloading|paused|completed|failed|cancelled
    downloaded: int = 0             # bayt
    total: int = 0                  # toplam bayt (0 = bilinmiyor)
    speed: float = 0.0              # bayt/sn
    eta: int = 0                    # sn
    error: str = ""
    final_file: str = ""
    _proc: Optional[subprocess.Popen] = field(default=None, repr=False)
    _paused: bool = field(default=False, repr=False)
    _cancel: bool = field(default=False, repr=False)
    _in_worker: bool = field(default=False, repr=False)  # v3.5.1: işçi şu an bu girdiyi işliyor

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "url": self.url,
            "title": self.title,
            "duration": self.duration,
            "status": self.status,
            "status_tr": _STATUS_NAMES.get(self.status, self.status),
            "downloaded": self.downloaded,
            "total": self.total,
            "speed": int(self.speed),
            "eta": self.eta,
            "error": self.error[:180],
            "final_file": self.final_file,
        }


@dataclass
class PlaylistBatchJob:
    batch_id: str
    playlist_url: str
    site: str
    title: str
    entries: List[PlaylistEntry]
    out_dir: Path
    cookies: str = ""
    user_agent: str = ""
    created_at: float = field(default_factory=time.time)
    active_index: int = 0           # şu an indirilen video (0 = boşta)
    done: bool = False

    def summary(self) -> Dict[str, Any]:
        comp = sum(1 for e in self.entries if e.status == "completed")
        failed = sum(1 for e in self.entries if e.status == "failed")
        total_bytes = sum(e.downloaded for e in self.entries)
        return {
            "batch_id": self.batch_id,
            "playlist_url": self.playlist_url,
            "site": self.site,
            "title": self.title,
            "out_dir": str(self.out_dir),
            "entries": [e.to_dict() for e in self.entries],
            "active_index": self.active_index,
            "completed": comp,
            "failed": failed,
            "total_entries": len(self.entries),
            "total_bytes": total_bytes,
            "done": self.done,
            "created_at": self.created_at,
        }


class PlaylistBatchManager:
    """Tüm oynatma listesi işlerini yöneten tekil sınıf (daemon state içinde yaşar)."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, PlaylistBatchJob] = {}
        self._base_dir = base_dir  # None -> indirme klasörü + /Oynatma Listeleri

    # ------------------------------------------------------------------ API
    def start_batch(
        self,
        playlist_url: str,
        entries: List[Dict[str, Any]],
        download_dir: str,
        cookies: str = "",
        user_agent: str = "",
    ) -> Dict[str, Any]:
        """GUI'den gelen seçili videoları SIRALI indirme kuyruğuna alır."""
        if not entries:
            return {"ok": False, "error": "no entries"}
        ytdlp_bin = find_ytdlp()
        if not ytdlp_bin:
            return {"ok": False, "error": "yt-dlp bulunamadı (Panel → Eksik Araçları Kur)"}

        from .stream_engine import is_playlist_url
        pl_title = ""
        # Liste başlığı yoksa URL'den türet
        try:
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(playlist_url).query)
            pl_title = (q.get("list") or [""])[0] or urlparse(playlist_url).path.strip("/").rsplit("/", 1)[-1]
        except Exception:
            pl_title = "oynatma-listesi"
        site = detect_playlist_site(playlist_url)

        safe_dir_name = sanitize_filename(f"{site} - {pl_title}")[:80].strip() or "oynatma-listesi"
        out_dir = (Path(self._base_dir) if self._base_dir else Path(download_dir)) / "Oynatma Listeleri" / safe_dir_name

        ents: List[PlaylistEntry] = []
        seen_idx = set()
        for it in entries[:MAX_BATCH_ENTRIES]:
            try:
                idx = int(it.get("index") or (len(ents) + 1))
            except Exception:
                idx = len(ents) + 1
            if idx in seen_idx:
                continue
            seen_idx.add(idx)
            e_url = (it.get("url") or "").strip()
            if not e_url.startswith("http"):
                continue
            ents.append(
                PlaylistEntry(
                    index=idx,
                    url=e_url,
                    title=sanitize_filename((it.get("title") or f"Video {idx}").strip())[:110],
                    duration=int(it.get("duration") or 0),
                )
            )
        if not ents:
            return {"ok": False, "error": "geçerli video yok"}

        job = PlaylistBatchJob(
            batch_id=uuid.uuid4().hex[:12],
            playlist_url=playlist_url,
            site=site,
            title=pl_title,
            entries=ents,
            out_dir=out_dir,
            cookies=cookies or "",
            user_agent=user_agent or "",
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            # ESKİ İŞLERİ TEMİZLE: en fazla 6 kayıt canlı kalsın (bellek kalkanı)
            if len(self._jobs) >= 6:
                for k in [k for k, j in self._jobs.items() if j.done]:
                    self._jobs.pop(k, None)
            while len(self._jobs) >= 6:
                oldest = min(self._jobs, key=lambda k: self._jobs[k].created_at)
                self._jobs.pop(oldest, None)
            self._jobs[job.batch_id] = job
        threading.Thread(target=self._worker, args=(job,), name=f"plbatch-{job.batch_id}", daemon=True).start()
        log.info("Playlist batch başladı: %s (%s) — %d video → %s", site, job.batch_id, len(ents), out_dir)
        return {"ok": True, "batch_id": job.batch_id, "site": site, "out_dir": str(out_dir)}

    def control(self, batch_id: str, action: str, index: int = 0) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(batch_id)
        if not job:
            return {"ok": False, "error": "batch bulunamadı"}
        targets = [e for e in job.entries if (index == 0 or e.index == index)]
        if not targets:
            return {"ok": False, "error": "video bulunamadı"}
        for e in targets:
            if action == "pause":
                # v3.5.1: 'queued' veya proc henüz spawn olmadan 'downloading' durumunda da
                # duraklatma İşLER (_paused bayrağı _run_entry içinde proc spawn edilir
                # edilmez SIGSTOP'a çevrilir) — yarış koşulu: sessiz no-op YOK
                if e.status in ("downloading", "queued"):
                    if e._proc and e._proc.poll() is None:
                        try:
                            os.kill(e._proc.pid, signal.SIGSTOP)
                        except Exception:
                            pass
                    e.status = "paused"
                    e.speed = 0.0
                    e._paused = True
                    log.info("Playlist %s video %d DURAKLATILDI", batch_id[:6], e.index)
            elif action == "resume":
                if e.status == "paused":
                    e._paused = False
                    p = e._proc
                    if p and p.poll() is None:
                        try:
                            os.kill(p.pid, signal.SIGCONT)
                            e.status = "downloading"
                            log.info("Playlist %s video %d DEVAM", batch_id[:6], e.index)
                        except Exception:
                            e.status = "queued"  # işlem öldüyse kuyruğa geri
                            e._proc = None
                    elif getattr(e, "_in_worker", False):
                        # v3.5.1: işçi girdiyi zaten işliyor (proc spawn penceresi) —
                        # _paused temizlendi; süreç spawn edilince hiç durdurulmadan sürer
                        e.status = "downloading"
                        log.info("Playlist %s video %d DEVAM (spawn penceresi)", batch_id[:6], e.index)
                    else:
                        # işlem yok: kuyruğa geri — işçi -c ile kaldığı yerden alır
                        e.status = "queued"
                        e._proc = None
            elif action == "cancel":
                e._cancel = True
                p = e._proc
                if p and p.poll() is None:
                    try:
                        if e._paused:
                            os.kill(p.pid, signal.SIGCONT)  # durmuş süreç öldürülebilsin
                        p.terminate()
                        try:
                            p.wait(timeout=4)
                        except Exception:
                            p.kill()
                    except Exception:
                        pass
                e.status = "cancelled"
                e.speed = 0.0
                # .part dosyalarını temizle
                try:
                    for pf in job.out_dir.glob("*"):
                        if pf.is_file() and (
                            pf.name.endswith(".part")
                            or pf.name.endswith(".ytdl")
                            or ".part-Frag" in pf.name
                        ):
                            pf.unlink(missing_ok=True)
                except Exception:
                    pass
                log.info("Playlist %s video %d İPTAL", batch_id[:6], e.index)
        return {"ok": True}

    def status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(batch_id)
            return job.summary() if job else None

    def list_batches(self) -> List[Dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.summary() for j in jobs]

    def shutdown_all(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            for e in job.entries:
                p = e._proc
                if p and p.poll() is None:
                    try:
                        if e._paused:
                            os.kill(p.pid, signal.SIGCONT)
                        p.terminate()
                    except Exception:
                        pass

    # --------------------------------------------------------------- WORKER
    def _worker(self, job: PlaylistBatchJob) -> None:
        """SIRALI indirme işçisi: her seferinde TEK video, maksimum paralel parça."""
        ytdlp_bin = find_ytdlp()
        while True:
            with self._lock:
                nxt = next(
                    (e for e in job.entries if e.status == "queued" and not e._cancel and not e._paused),
                    None,
                )
                any_active = any(
                    e.status == "downloading" or (e.status == "paused" and e._proc and e._proc.poll() is None)
                    for e in job.entries
                )
            if not nxt:
                if not any_active:
                    break
                time.sleep(0.4)
                continue
            job.active_index = nxt.index
            self._run_entry(job, nxt, ytdlp_bin)
            job.active_index = 0
        job.done = True
        comp = sum(1 for e in job.entries if e.status == "completed")
        log.info("Playlist batch bitti: %s — %d/%d tamam", job.batch_id, comp, len(job.entries))

    def _run_entry(self, job: PlaylistBatchJob, e: PlaylistEntry, ytdlp_bin: str) -> None:
        e.status = "downloading"
        e.error = ""
        e._in_worker = True
        cookie_file = None
        if job.cookies:
            try:
                cookie_file = cookies_header_to_netscape_file(job.cookies, e.url)
            except Exception:
                cookie_file = None
        out_tpl = str(job.out_dir / f"{e.index:03d} - {e.title}.%(ext)s")
        cmd = [
            ytdlp_bin,
            "--no-warnings",
            "--no-color",
            "--newline",
            "--no-playlist",
            "--no-mtime",
            "--continue",
            "--retries", "6",
            "--fragment-retries", "12",
            "--socket-timeout", "25",
            "--concurrent-fragments", "8",          # v3.5.0 MAKSİMUM HIZ
            "-N", "8",
            "-f", "bv*+ba/b",
            "--merge-output-format", "mp4",
            "-o", out_tpl,
        ]
        if cookie_file:
            cmd.extend(["--cookies", str(cookie_file)])
        if job.user_agent:
            cmd.extend(["--user-agent", job.user_agent])
        if e.duration:
            pass
        cmd.append(e.url)

        try:
            e._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                start_new_session=True,   # pause için ayrı süreç grubu
            )
        except Exception as exc:
            e.status = "failed"
            e.error = f"yt-dlp başlatılamadı: {exc}"
            return

        # v3.5.1: pause, proc spawn penceresinde geldi ise HEMEN durdur (bayrak yarışı)
        if e._paused:
            try:
                os.kill(e._proc.pid, signal.SIGSTOP)
            except Exception:
                pass

        assert e._proc.stdout is not None
        try:
            for line in e._proc.stdout:
                if e._cancel:
                    break
                self._parse_progress(e, line)
            rc = 0
            try:
                rc = e._proc.wait(timeout=600)
            except Exception:
                try:
                    e._proc.kill()
                    rc = e._proc.returncode or 1
                except Exception:
                    rc = 1
        finally:
            e._in_worker = False
            if cookie_file:
                try:
                    cookie_file.unlink(missing_ok=True)
                except OSError:
                    pass

        if e._cancel:
            e.status = "cancelled"
            return
        if rc == 0:
            # çıktı dosyasını bul
            final = ""
            try:
                cands = sorted(job.out_dir.glob(f"{e.index:03d} - {e.title}.*"))
                cands = [c for c in cands if not c.name.endswith(".part")]
                if cands:
                    final = cands[-1].name
            except Exception:
                pass
            e.final_file = final
            e.status = "completed"
            if e.total and not e.downloaded:
                e.downloaded = e.total
            e.speed = 0.0
            e.eta = 0
        else:
            e.status = "failed"
            if not e.error:
                e.error = f"yt-dlp çıkış kodu: {rc}"

    @staticmethod
    def _parse_progress(e: PlaylistEntry, line: str) -> None:
        """yt-dlp --newline ilerleme satırını çöz:
        [download]  45.3% of   12.34MiB at    2.45MiB/s ETA 00:05"""
        if "[download]" not in line:
            return
        try:
            pm = re.search(r"\[download\]\s+([\d.]+)% of\s+~?\s*([\d.]+)(KiB|MiB|GiB|B)", line)
            if not pm:
                # 'of N at ...' biçimindeki %'siz satırlar (tamamlanan parça sayımı)
                am = re.search(r"\[download\]\s+([\d.]+)(KiB|MiB|GiB|B) of\s+([\d.]+)(KiB|MiB|GiB|B)", line)
                if am:
                    got = PlaylistBatchManager._to_bytes(float(am.group(1)), am.group(2))
                    tot = PlaylistBatchManager._to_bytes(float(am.group(3)), am.group(4))
                    e.downloaded = got
                    e.total = tot
                return
            pct = float(pm.group(1))
            total = PlaylistBatchManager._to_bytes(float(pm.group(2)), pm.group(3))
            e.total = total
            e.downloaded = int(total * pct / 100.0)
            sm = re.search(r"at\s+([\d.]+)(KiB|MiB|GiB|B)/s", line)
            if sm:
                e.speed = PlaylistBatchManager._to_bytes(float(sm.group(1)), sm.group(2))
            em = re.search(r"ETA\s+(\d+):(\d+)(?::(\d+))?", line)
            if em:
                e.eta = int(em.group(1)) * 60 + int(em.group(2)) + (int(em.group(3)) if em.group(3) else 0)
        except Exception:
            pass

    @staticmethod
    def _to_bytes(val: float, unit: str) -> int:
        mult = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}.get(unit, 1)
        return int(val * mult)
