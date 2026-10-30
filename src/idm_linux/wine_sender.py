from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

from .config import IdmLinuxConfig, setup_logger
from .protocol import DownloadRequest

logger = setup_logger("wine_sender", "daemon.log")

VBS_COM_SCRIPT = r"""Option Explicit
On Error Resume Next

Dim fso, args, jobPath, stream, content, lines
Set args = WScript.Arguments
If args.Count < 1 Then WScript.Quit 2
jobPath = args(0)

Set fso = CreateObject("Scripting.FileSystemObject")
If Not fso.FileExists(jobPath) Then WScript.Quit 3

' UTF-16LE (-1 = TristateTrue) olarak oku (Türkçe ve Unicode dosya adları için tam destek)
Set stream = fso.OpenTextFile(jobPath, 1, False, -1)
content = stream.ReadAll()
stream.Close()

lines = Split(content, vbCrLf)
Dim url, referer, cookies, postData, localPath, fileName, userAgent, flags
url = ""
referer = ""
cookies = ""
postData = ""
localPath = ""
fileName = ""
userAgent = ""
flags = 0

If UBound(lines) >= 0 Then url = lines(0)
If UBound(lines) >= 1 Then referer = lines(1)
If UBound(lines) >= 2 Then cookies = lines(2)
If UBound(lines) >= 3 Then postData = lines(3)
If UBound(lines) >= 4 Then localPath = lines(4)
If UBound(lines) >= 5 Then fileName = lines(5)
If UBound(lines) >= 6 Then userAgent = lines(6)
If UBound(lines) >= 7 Then flags = CLng(lines(7))

Err.Clear
Dim tx
Set tx = CreateObject("IDMan.CIDMLinkTransmitter")
If Err.Number <> 0 Then
    WScript.Quit 10
End If

' Önce ICIDMLinkTransmitter2::SendLinkToIDM2 (User-Agent destekli) dene
tx.SendLinkToIDM2 url, referer, cookies, postData, "", "", localPath, fileName, flags, userAgent, Empty
If Err.Number <> 0 Then
    Err.Clear
    tx.SendLinkToIDM url, referer, cookies, postData, "", "", localPath, fileName, flags
    If Err.Number <> 0 Then
        WScript.Quit 11
    End If
End If

fso.DeleteFile jobPath, True
WScript.Quit 0
"""


def build_wine_env(cfg: IdmLinuxConfig) -> Dict[str, str]:
    env = os.environ.copy()
    env["WINEPREFIX"] = cfg.wine_prefix
    env["WINEDEBUG"] = "-all"
    # backtrace.txt analizinde görülen Windows-only DLL enjektörlerini (idmnetmon64, idmbrbtn64, wfp)
    # Wine seviyesinde tamamen devre dışı bırakıyoruz ki çalışma zamanında ASLA crash oluşmasın!
    existing_overrides = env.get("WINEDLLOVERRIDES", "")
    block_list = "mscoree,mshtml=;idmnetmon,idmnetmon64,idmbrbtn,idmbrbtn64,idmwfp32,idmwfp64,idmtdi32,idmtdi64=d"
    env["WINEDLLOVERRIDES"] = f"{block_list};{existing_overrides}" if existing_overrides else block_list

    # Eğer daemon systemd üzerinden başladıysa ve DISPLAY/WAYLAND_DISPLAY eksikse keşfet
    uid = os.getuid()
    runtime_dir = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    if Path(runtime_dir).exists():
        env["XDG_RUNTIME_DIR"] = runtime_dir
        if not env.get("WAYLAND_DISPLAY"):
            for wl in Path(runtime_dir).glob("wayland-*"):
                if not wl.name.endswith(".lock"):
                    env["WAYLAND_DISPLAY"] = wl.name
                    break
    if not env.get("DISPLAY"):
        for xsock in sorted(Path("/tmp/.X11-unix").glob("X*")) if Path("/tmp/.X11-unix").exists() else []:
            disp_num = xsock.name[1:]
            if disp_num.isdigit():
                env["DISPLAY"] = f":{disp_num}"
                break
    return env


def linux_to_wine_path(linux_path: str | Path) -> str:
    p = Path(linux_path).expanduser().resolve()
    raw = str(p).replace("/", "\\")
    return f"Z:{raw}"


def sanitize_filename(name: str, fallback_url: str = "") -> str:
    candidate = name.strip()
    if not candidate and fallback_url:
        try:
            parsed = urlparse(fallback_url)
            tail = Path(unquote(parsed.path)).name
            if tail and "." in tail and len(tail) < 180:
                candidate = tail
        except ValueError:
            pass
    # Windows dosya sistemi için yasaklı karakterleri temizle
    candidate = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", candidate).strip(" .")
    if len(candidate) > 200:
        stem, dot, ext = candidate.rpartition(".")
        if dot and len(ext) <= 10:
            candidate = stem[:185] + "." + ext
        else:
            candidate = candidate[:200]
    return candidate


def guess_category_subdir(filename: str, base_download_dir: Path) -> Path:
    ext = Path(filename).suffix.lower().lstrip(".")
    mapping = {
        "Compressed": {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz", "zst"},
        "Programs": {"exe", "msi", "deb", "rpm", "appimage", "apk", "dmg", "bin", "iso"},
        "Video": {"mp4", "mkv", "avi", "mov", "webm", "flv", "wmv", "m4v", "ts", "3gp"},
        "Music": {"mp3", "flac", "wav", "m4a", "aac", "ogg", "opus", "wma"},
        "Documents": {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "epub"},
    }
    for folder, exts in mapping.items():
        if ext in exts:
            target = base_download_dir / folder
            target.mkdir(parents=True, exist_ok=True)
            return target
    base_download_dir.mkdir(parents=True, exist_ok=True)
    return base_download_dir


class WineIdmSender:
    def __init__(self, cfg: IdmLinuxConfig) -> None:
        self.cfg = cfg
        self._last_user_agent: str = ""
        self._healed_dirs: set[Path] = set()
        # v3.14.0: COM köprüsü arıza önbelleği — kullanıcı günlüğünde COM HER SEFERİNDE
        # (dönüş kodu 1) düşüyor ve her gönderim gereksiz bir cscript denemesi
        # (+8 sn'ye kadar) harcıyordu. Üst üste 3 arızada COM 30 dakika atlanır;
        # süre dolduğunda tek bir deneme yapıp durumu tazeler (IDM onarımı halinde
        # kanal otomatik geri gelir). CLI kanalı her koşulda çalışır — işlev kaybı YOK.
        self._com_fail_streak: int = 0
        self._com_skip_until: float = 0.0
        self._COM_SKIP_AFTER = 3
        self._COM_SKIP_SECS = 1800.0

    def _ensure_idm_dir_healed(self, idm_dir: Path) -> None:
        """IDMan.exe açılmadan önce eksik hook dosyalarını güvenli PE stub ile tamamlar."""
        if idm_dir in self._healed_dirs:
            return
        try:
            from .installer import neutralize_windows_hook_binaries

            neutralize_windows_hook_binaries(idm_dir)
            self._healed_dirs.add(idm_dir)
        except Exception as exc:
            logger.debug("IDM dizin stub onarımı atlandı: %s", exc)

    def ensure_bridge_scripts(self) -> Path:
        bridge_dir = Path(self.cfg.wine_prefix) / "drive_c" / "idm_bridge"
        bridge_dir.mkdir(parents=True, exist_ok=True)
        vbs_file = bridge_dir / "send_link.vbs"
        if not vbs_file.exists():
            vbs_file.write_bytes(VBS_COM_SCRIPT.encode("utf-8"))
        return bridge_dir

    def is_idm_running(self) -> bool:
        try:
            res = subprocess.run(
                ["pgrep", "-fi", "IDMan.exe"],
                capture_output=True,
                timeout=3,
                check=False,
            )
            return res.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def warm_up_idm(self) -> bool:
        """Wine sunucusunu ve IDMan.exe /onboot sürecini arka planda hazır tutar."""
        idm_exe = self.cfg.find_idm_exe()
        if not idm_exe or not shutil.which("wine"):
            return False

        self._ensure_idm_dir_healed(idm_exe.parent)
        env = build_wine_env(self.cfg)
        wineserver = shutil.which("wineserver")
        if wineserver:
            subprocess.Popen(
                [wineserver, "-p300"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        if not self.is_idm_running():
            logger.info("IDMan.exe arka planda (/onboot) başlatılıyor...")
            subprocess.Popen(
                ["wine", str(idm_exe), "/onboot"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return True

    def open_idm_window(self) -> Tuple[bool, str]:
        idm_exe = self.cfg.find_idm_exe()
        if not idm_exe:
            return False, "IDMan.exe bulunamadı. Önce 'idm-linux install' çalıştırın."
        if not shutil.which("wine"):
            return False, "Sistemde Wine kurulu değil."

        self._ensure_idm_dir_healed(idm_exe.parent)
        env = build_wine_env(self.cfg)
        subprocess.Popen(
            ["wine", str(idm_exe)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True, "Internet Download Manager açılıyor."

    # ------------------------------------------------------------------
    # v3.12.0: IDM TRIAL RESET (kullanıcı isteği)
    # v3.13.0: wine reg çıkış koduna KÖRÜ KÖRÜNE güvenme — WINE 10/11'de (CachyOS
    # Wine 11.20 dâhil) 'reg delete' başarılı olduğu halde sahte kod döndürebilir
    # veya soğuk wineserver başlangıcı 20 sn zaman aşımını yutabilir. Yeni akış:
    #   sil (dönüş kodu YOK SAYILIR) -> 'wine reg query' ile VAR/YOK DOĞRULAMASI.
    # Anahtar gerçekten gittiyse BAŞARILI; hâlâ duruyorsa 3 kez yeniden denenir.
    # ------------------------------------------------------------------
    _TRIAL_REG_PATHS = (
        # 30 günlük deneme sayacının yaşadığı ANAHTAR (IDM 6.x): silinince IDM
        # kendini yeni kurulum sanır ve deneme süresi yeniden başlar.
        r"HKCU\Software\DMCACount",
        r"HKU\.DEFAULT\Software\DMCACount",
    )
    # DownloadManager altında yalnız NAG / kontrol-sayacı değerleri —
    # kullanıcının kayıtlı LİSANS/serial verisi ASLA dokunulmaz.
    _TRIAL_NAG_VALUES = ("fSn", "Checked", "LastCheck", "radxcnt")

    # -- v3.13.0: düsük seviye wine reg yardimcilari (dogrulama tabanli) ------
    def _reg_env(self, env: Dict[str, str]) -> Dict[str, str]:
        """wine reg davranışını bölgesel ayardan bağımsız sabitler."""
        reg_env = dict(env)
        reg_env.setdefault("LC_ALL", "C")
        reg_env.setdefault("LANG", "C")
        return reg_env

    def _wine_reg_run(self, args: List[str], env: Dict[str, str], timeout: float = 30.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["wine", "reg"] + args,
            env=self._reg_env(env),
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def _reg_key_exists(self, reg_path: str, env: Dict[str, str]) -> bool:
        """'wine reg query' ile anahtarın VAR olduğunu doğrular (rc=0 => var)."""
        try:
            res = self._wine_reg_run(["query", reg_path], env=env, timeout=20.0)
            return res.returncode == 0
        except (OSError, subprocess.SubprocessError):
            # Sorgu başlayamazsa muhafazakâr davran: 'var' say ki silme denensin.
            return True

    def _reg_value_exists(self, reg_path: str, value_name: str, env: Dict[str, str]) -> bool:
        try:
            res = self._wine_reg_run(["query", reg_path, "/v", value_name], env=env, timeout=20.0)
            return res.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return True

    def _prewarm_wineserver(self, env: Dict[str, str]) -> None:
        """Registry işlemlerinden ÖNCE kalıcı wineserver'ı uyandır — soğuk başlangıç
        zaman aşımı yüzünden 'wine reg dönmedi' hatalarını kökten bitirir."""
        wineserver = shutil.which("wineserver")
        if not wineserver:
            return
        try:
            subprocess.Popen(
                [wineserver, "-p300"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # wineserver RPC'nin ayağa kalkmasına kısa bir nefes ver
            time.sleep(0.4)
        except (OSError, subprocess.SubprocessError):
            pass

    def _wait_idm_exited(self, timeout: float = 12.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_idm_running():
                return True
            time.sleep(0.5)
        return not self.is_idm_running()

    def trial_reset_idm(self) -> Tuple[bool, str]:
        """IDM 30 günlük deneme sayacını güvenli biçimde sıfırlar.

        v3.13.0 AKIŞI (doğrulama tabanlı):
          1. IDM düzgünce kapatılır (çıkış DOĞRULANIR).
          2. Kalıcı wineserver önceden ısıtılır (soğuk başlangıç kilitlenmesi yok).
          3. Her hedef anahtar/değer: sil -> 'wine reg query' ile VAR/YOK doğrulaması
             (wine'in sahte dönüş kodları sonucu değiştiremez) -> gerekirse yeniden dene.
          4. ANA sayaç anahtarı (HKCU DMCACount) gerçekten gittiyse BAŞARI; hâlâ
             duruyorsa wine çıktısıyla birlikte dürüst hata raporu.
          5. IDM arka plan servisi geri ısıtılır.
        """
        idm_exe = self.cfg.find_idm_exe()
        if not idm_exe:
            return False, "IDMan.exe bulunamadı. Önce 'idm-linux install' çalıştırın."
        if not shutil.which("wine"):
            return False, "Sistemde Wine kurulu değil."

        env = build_wine_env(self.cfg)
        was_running = self.is_idm_running()

        # 1. IDM'yi kapat (registry kilitli kalmasın / eski sayaç geri yazılmasın)
        if was_running:
            try:
                subprocess.run(
                    ["wine", "taskkill", "/F", "/IM", "IDMan.exe"],
                    env=env, capture_output=True, timeout=15, check=False,
                )
            except (OSError, subprocess.SubprocessError):
                pass
            if not self._wait_idm_exited(8.0):
                try:
                    subprocess.run(
                        ["pkill", "-9", "-f", "IDMan.exe"],
                        capture_output=True, timeout=8, check=False,
                    )
                    self._wait_idm_exited(6.0)
                except (OSError, subprocess.SubprocessError):
                    pass
            time.sleep(0.8)

        # 2. Kalıcı wineserver'ı önceden ısıt (reg çağrıları asla donmasın)
        self._prewarm_wineserver(env)

        # 3. Sayaç anahtarlarını sil + DOĞRULA (en fazla 3 deneme)
        counter_paths_alive: List[str] = []
        for reg_path in self._TRIAL_REG_PATHS:
            gone = False
            for _attempt in range(3):
                try:
                    self._wine_reg_run(["delete", reg_path, "/f"], env=env, timeout=30.0)
                except (OSError, subprocess.SubprocessError):
                    pass
                if not self._reg_key_exists(reg_path, env):
                    gone = True
                    break
                time.sleep(0.6)
            if not gone:
                # HKU\.DEFAULT çoğu prefix'te hiç yoktur; ANA sayaç HKCU'dadır.
                counter_paths_alive.append(reg_path)

        # 4. Nag / kontrol sayaç değerleri (lisans verisi değil)
        for val in self._TRIAL_NAG_VALUES:
            for _attempt in range(2):
                try:
                    self._wine_reg_run(
                        ["delete", r"HKCU\Software\DownloadManager", "/v", val, "/f"],
                        env=env, timeout=25.0,
                    )
                except (OSError, subprocess.SubprocessError):
                    pass
                if not self._reg_value_exists(r"HKCU\Software\DownloadManager", val, env):
                    break
                time.sleep(0.4)

        # 5. Başarı ölçütü: ANA sayaç anahtarı (HKCU DMCACount) gitmiş olmalı.
        #    HKU\.DEFAULT varyantı veya bir nag değeri kalsa bile IDM kendini yeni
        #    kurulum sanır (30 günlük sayaç HKCU DMCACount'ta yaşar).
        hkcu_path = r"HKCU\Software\DMCACount"
        counter_ok = hkcu_path not in counter_paths_alive
        if counter_ok:
            logger.info(
                "IDM Trial Reset tamamlandı (önceki durum: %s).",
                "çalışıyordu" if was_running else "kapalıydı",
            )
            # 6. IDM daha önce açıksa arka plan servisini geri getir
            if was_running:
                try:
                    self.warm_up_idm()
                except Exception:
                    pass
            return True, (
                "✓ IDM deneme sayacı sıfırlandı."
                + (" IDM arka planda yeniden başlatıldı — 30 günlük deneme süresi yeniden aktif." if was_running else "")
            )

        # Dürüst hata: wine'in kendisi ne dediyse göster
        diag_tail = ""
        try:
            res = self._wine_reg_run(["query", hkcu_path], env=env, timeout=15.0)
            diag_tail = ((res.stderr or b"").decode("utf-8", "replace") + (res.stdout or b"").decode("utf-8", "replace")).strip()
        except Exception as exc:
            diag_tail = str(exc)
        diag_tail = diag_tail[:220]
        logger.error("Trial Reset başarısız: %s canlı kaldı. Diag: %s", hkcu_path, diag_tail)
        return False, (
            "Registry işlemi tamamlanamadı: DMCACount anahtarı silinemiyor."
            + (f" Wine çıktısı: {diag_tail}" if diag_tail else " Wine ortamını kontrol edin.")
        )

    def _sync_custom_user_agent(self, ua: str, env: Dict[str, str]) -> None:
        clean_ua = ua.strip()
        if not clean_ua or clean_ua == self._last_user_agent:
            return
        self._last_user_agent = clean_ua
        subprocess.Popen(
            [
                "wine",
                "reg",
                "add",
                r"HKCU\Software\DownloadManager",
                "/v",
                "szCustomUserAgent",
                "/t",
                "REG_SZ",
                "/d",
                clean_ua,
                "/f",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def send_download(self, req: DownloadRequest) -> Tuple[bool, str]:
        """
        Yakalanan indirmeyi (URL, Cookie, Referer, User-Agent, Dosya Adı)
        önce COM (CIDMLinkTransmitter) üzerinden, başarısız olursa doğrudan IDMan.exe CLI
        üzerinden gerçek IDM'ye iletir.
        """
        idm_exe = self.cfg.find_idm_exe()
        if not idm_exe:
            msg = "IDMan.exe kurulu değil! Lütfen 'idm-linux install' çalıştırın."
            logger.error(msg)
            return False, msg

        if not shutil.which("wine"):
            msg = "Wine bulunamadı!"
            logger.error(msg)
            return False, msg

        self._ensure_idm_dir_healed(idm_exe.parent)
        env = build_wine_env(self.cfg)
        if req.user_agent:
            self._sync_custom_user_agent(req.user_agent, env)

        clean_name = sanitize_filename(req.filename, req.url)
        base_dl = Path(req.save_dir) if req.save_dir else Path(self.cfg.download_dir)
        target_linux_dir = guess_category_subdir(clean_name, base_dl) if clean_name else base_dl
        target_linux_dir.mkdir(parents=True, exist_ok=True)
        win_save_dir = linux_to_wine_path(target_linux_dir)

        use_silent = req.silent if req.silent is not None else self.cfg.silent_mode
        lflags = 1 if use_silent else 0

        # KANAL 1: COM Otomasyonu (Cookie + Referer + POST + User-Agent tam aktarım)
        # v3.14.0: arıza önbelleği sıcakken COM denemesi tamamen atlanır (sıfır gecikme)
        com_active = time.time() >= self._com_skip_until
        if com_active:
            try:
                bridge_dir = self.ensure_bridge_scripts()
                job_name = f"job_{uuid.uuid4().hex[:12]}.txt"
                job_linux_path = bridge_dir / job_name

                def _single_line(s: str) -> str:
                    return s.replace("\r", " ").replace("\n", " ").strip()

                payload_lines = [
                    _single_line(req.url),
                    _single_line(req.referer or req.origin),
                    _single_line(req.cookies),
                    _single_line(req.post_data),
                    win_save_dir,
                    clean_name,
                    _single_line(req.user_agent),
                    str(lflags),
                ]
                # UTF-16LE BOM (\xff\xfe) ile yaz ki VBScript OpenTextFile(..., -1) tam Unicode okusun
                utf16_payload = b"\xff\xfe" + "\r\n".join(payload_lines).encode("utf-16-le")
                job_linux_path.write_bytes(utf16_payload)

                win_vbs = r"C:\idm_bridge\send_link.vbs"
                win_job = rf"C:\idm_bridge\{job_name}"

                res = subprocess.run(
                    ["wine", "cscript.exe", "//Nologo", "//T:8", win_vbs, win_job],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                )
                if res.returncode == 0:
                    self._com_fail_streak = 0
                    logger.info(
                        "COM üzerinden IDM'ye iletildi [%s]: %s (dosya=%s, çerez=%s)",
                        req.source,
                        req.url[:100],
                        clean_name or "otomatik",
                        "evet" if req.cookies else "hayır",
                    )
                    return True, "COM köprüsü üzerinden IDM'ye gönderildi."

                # Başarısız olduysa geçici dosyayı temizle ve Kanal 2'ye geç
                job_linux_path.unlink(missing_ok=True)
                self._com_fail_streak += 1
                if self._com_fail_streak >= self._COM_SKIP_AFTER and time.time() >= self._com_skip_until:
                    self._com_skip_until = time.time() + self._COM_SKIP_SECS
                    logger.info(
                        "COM köprüsü %d kez üst üste başarısız — 30 dakika atlanacak (CLI kanalı aynen çalışıyor).",
                        self._com_fail_streak,
                    )
                else:
                    logger.warning("COM köprüsü dönüş kodu %s, CLI fallback devreye giriyor.", res.returncode)
            except Exception as exc:
                self._com_fail_streak += 1
                if self._com_fail_streak >= self._COM_SKIP_AFTER and time.time() >= self._com_skip_until:
                    self._com_skip_until = time.time() + self._COM_SKIP_SECS
                    logger.info("COM köprüsü arızalı (%s) — 30 dakika atlanıyor, CLI kanalı aynen çalışıyor.", exc)
                else:
                    logger.warning("COM aktarım hatası (%s), CLI fallback kullanılıyor.", exc)

        # KANAL 2: Doğrudan IDMan.exe CLI (/d URL /p YOL /f DOSYA_ADI)
        cmd = ["wine", str(idm_exe), "/d", req.url, "/p", win_save_dir]
        if clean_name:
            cmd.extend(["/f", clean_name])
        if use_silent:
            cmd.append("/n")

        subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("CLI üzerinden IDM'ye iletildi [%s]: %s", req.source, req.url[:100])
        return True, "CLI üzerinden IDM'ye gönderildi."
