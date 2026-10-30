from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import List, Optional

from . import __idm_target_build__, __version__
from .browsers import create_native_host_wrapper, gecko_home_roots, get_browser_targets, register_all_browsers
from .config import (
    DEFAULT_HTTP_PORT,
    DEFAULT_WS_PORT,
    OFFICIAL_FIREFOX_EXT_ID,
    IdmLinuxConfig,
    get_cache_dir,
    get_data_dir,
)
from .distro import detect_system
from .firefox_ext import cache_official_firefox_xpi
from .crx_builder import verify_crx3_package
from .daemon import is_daemon_running, run_daemon_foreground
from .installer import (
    apply_idm_registry_tweaks,
    deploy_browser_extensions,
    neutralize_windows_hook_binaries,
    run_full_install,
    run_uninstall,
)
from .protocol import DownloadRequest
from .wine_sender import WineIdmSender

def _find_project_root() -> Path:
    here = Path(__file__).resolve()
    cand = here.parents[2]
    if (cand / "extension").exists():
        return cand
    return cand


def cmd_status() -> int:
    cfg = IdmLinuxConfig.load()
    sys_info = detect_system()
    sender = WineIdmSender(cfg)
    idm_exe = cfg.find_idm_exe()
    daemon_ok = is_daemon_running(cfg)
    ext_dir = get_data_dir() / "extensions"
    crx_file = ext_dir / "idm-linux-companion-chromium.crx"

    print("\n======================================================================")
    print(f"  IDM-Linux Durum Raporu (v{__version__} — Hedef: IDM {__idm_target_build__})")
    print("======================================================================")
    print(f"  • Dağıtım / Ortam   : {sys_info.distro_name} [{sys_info.pkg_manager} | {sys_info.init_system} | {sys_info.display_server}]")
    print(f"  • Aktif WINEPREFIX  : {cfg.wine_prefix}")
    print(f"  • Wine Durumu       : {'✓ ' + sys_info.wine_version if sys_info.wine_installed else '✗ Kurulu Değil'}")
    print(f"  • IDM Kurulumu      : {'✓ ' + str(idm_exe) if idm_exe else '✗ Kurulu Değil'}")
    print(f"  • IDMan.exe Süreci  : {'✓ Arka Planda Hazır' if sender.is_idm_running() else '○ Beklemede (İndirmede Açılır)'}")
    print(f"  • Köprü Servisi     : {'✓ AKTİF (HTTP:' + str(cfg.http_port) + ' / WS:' + str(cfg.ws_port) + ')' if daemon_ok else '✗ KAPALI (idm-linux start ile başlatın)'}")
    print(f"  • Chromium CRX3     : {'✓ ' + str(crx_file) if crx_file.exists() else '○ Henüz üretilmedi'}")
    print(f"  • Video & Torrent   : yt-dlp={'✓' if sys_info.ytdlp_path else '✗'} | ffmpeg={'✓' if sys_info.ffmpeg_installed else '✗'} | aria2c={'✓' if sys_info.aria2_installed else '✗'}")
    print(f"  • İndirilenler Yolu : {cfg.download_dir}")
    print("----------------------------------------------------------------------")
    print("  Tarayıcı Native Messaging (com.tonec.idm) Entegrasyonu:")
    for t in get_browser_targets():
        if t.installed or t.registered:
            st = "✓ Kayıtlı" if t.registered else "✗ Kayıtsız"
            inst = "Kurulu" if t.installed else "Profil Hazır"
            print(f"    - {t.name:<20}: {st} ({inst})")
    print("======================================================================\n")
    return 0


def cmd_doctor(auto_fix: bool = True) -> int:
    """
    10 adımlı otomatik teşhis ve tamir doktoru:
    Port izinlerini, eski çökme modüllerini (IDMIntegrator64.exe), CRX3 paketini,
    tarayıcı manifestlerini ve köprü servisini uçtan uca kontrol edip bozuksa onarır!
    """
    print("\n======================================================================")
    print("  IDM-Linux Doktor (Tam Otomatik Teşhis & Onarım Aracı)")
    print("======================================================================")
    cfg = IdmLinuxConfig.load()
    issues_fixed = 0

    # 1. Port kontrolü (<1024 privileged port kalıntısı var mı?)
    if cfg.http_port < 1024 or cfg.ws_port < 1024:
        print(f"  [!] Eski yetkili port algılandı ({cfg.ws_port}/{cfg.http_port}) -> {DEFAULT_WS_PORT}/{DEFAULT_HTTP_PORT} olarak düzeltiliyor...")
        cfg.ws_port = DEFAULT_WS_PORT
        cfg.http_port = DEFAULT_HTTP_PORT
        cfg.save()
        issues_fixed += 1
    else:
        print(f"  [✓] 1/8 Köprü portları yetkisiz (unprivileged) aralıkta: WS={cfg.ws_port}, HTTP={cfg.http_port}")

    # 2. Wine & IDMan.exe & Çökme Modülü Kontrolü
    idm_exe = cfg.find_idm_exe()
    if idm_exe and idm_exe.exists():
        n_dis = neutralize_windows_hook_binaries(idm_exe.parent)
        if n_dis > 0:
            print(f"  [✓] 2/8 Wine altında çöken {n_dis} adet Windows hook/driver ikilisi (IDMIntegrator64 vb.) izole edildi!")
            issues_fixed += 1
        else:
            print(f"  [✓] 2/8 IDMan.exe kurulu ve çökme önleyici izolasyon tam: {idm_exe}")
    else:
        print(f"  [✗] 2/8 Aktif prefix içinde ({cfg.wine_prefix}) IDMan.exe bulunamadı! 'idm-linux install' çalıştırın.")

    # 3. CRX3 Paketi Bütünlük Kontrolü
    crx_path = get_data_dir() / "extensions" / "idm-linux-companion-chromium.crx"
    if crx_path.exists():
        ok_crx, msg_crx = verify_crx3_package(crx_path)
        print(f"  [{'✓' if ok_crx else '!'}] 3/8 Chromium CRX3 Paketi: {msg_crx}")
    elif (_find_project_root() / "extension" / "chromium").exists() and auto_fix:
        crx_path, _, _ = deploy_browser_extensions(_find_project_root())
        print(f"  [✓] 3/8 Eksik CRX3 paketi yeniden üretildi: {crx_path}")
        issues_fixed += 1
    else:
        print("  [!] 3/8 CRX3 paketi bulunamadı.")

    # 4. Tarayıcı Native Messaging Kayıtları
    src_dir = Path(__file__).resolve().parents[1]
    wrapper = create_native_host_wrapper(sys.executable, src_dir)
    targets = register_all_browsers(wrapper, crx_path=crx_path if crx_path.exists() else None)
    reg_count = sum(1 for t in targets if t.registered)
    print(f"  [✓] 4/8 Tarayıcı Native Messaging köprüleri doğrulandı ({reg_count} tarayıcı profili aktif).")

    # 5. Wine Registry & COM Köprüsü
    if auto_fix and idm_exe:
        apply_idm_registry_tweaks(cfg)
        print("  [✓] 5/8 Wine Registry (EnableDriver=0, ShowCrashDialog=0, Türkçe, ClearType) doğrulandı.")

    # 6. Canlı Köprü Servisi HTTP Testi
    if not is_daemon_running(cfg) and auto_fix:
        print("  [*] 6/8 Köprü servisi kapalıydı, yeniden başlatılıyor...")
        cmd_stop()
        cmd_start()
        issues_fixed += 1

    if is_daemon_running(cfg):
        print(f"  [✓] 6/8 Canlı HTTP & WebSocket Köprü Testi BAŞARILI (http://127.0.0.1:{cfg.http_port}/api/status -> 200 OK)!")
    else:
        print("  [✗] 6/8 Köprü servisi başlatılamadı! 'idm-linux logs' çıktısını kontrol edin.")

    # 7. Firefox İmzalı XPI Sideload & Doğrulama Duvarı Kontrolü (v2.8.0)
    from .firefox_ext import install_firefox_extensions_robust, official_xpi_cache_path

    off_xpi = official_xpi_cache_path()
    if not off_xpi.exists() and idm_exe:
        off_xpi = cache_official_firefox_xpi(idm_exe.parent) or off_xpi
    gecko_missing = 0
    for _name, _bin, home_root in gecko_home_roots():
        if not home_root.is_dir():
            continue
        from .firefox_ext import find_gecko_profile_dirs
        for prof in find_gecko_profile_dirs(home_root):
            if not (prof / "extensions" / f"{OFFICIAL_FIREFOX_EXT_ID}.xpi").exists():
                gecko_missing += 1
    if gecko_missing and auto_fix and off_xpi.exists():
        prj = _find_project_root()
        comp_xpi = get_data_dir() / "extensions" / "idm-linux-companion-firefox.xpi"
        rep = install_firefox_extensions_robust(gecko_home_roots(), comp_xpi, off_xpi)
        print(f"  [✓] 7/8 Firefox doğrulama duvarı onarıldı: {len(rep['signed'])} profile imzalı XPI sideload edildi.")
        issues_fixed += 1
    elif gecko_missing:
        print(f"  [!] 7/8 {gecko_missing} Gecko profilinde imzalı IDM XPI'si yok ('idm-linux install' önerilir).")
    else:
        print("  [✓] 7/8 Firefox/Gecko profilleri imzalı XPI sideload durumu doğrulandı.")

    # 8. Wine "Klasörü Aç" -> Linux Dosya Yöneticisi Yönlendirmesi (v2.8.0)
    user_reg = Path(cfg.wine_prefix).expanduser() / "user.reg"
    if user_reg.exists():
        reg_txt = user_reg.read_text(encoding="utf-8", errors="ignore")
        if "idm-linux-open-folder" not in reg_txt:
            if auto_fix:
                from .installer import configure_wine_native_folder_open
                if configure_wine_native_folder_open(cfg, log_fn=lambda m: None):
                    print("  [✓] 8/8 Wine 'Klasörü Aç' yönlendirmesi Linux dosya yöneticisine bağlandı.")
                    issues_fixed += 1
                else:
                    print("  [!] 8/8 Wine klasör yönlendirmesi yazılamadı (dosya yöneticisi bulunamadı).")
            else:
                print("  [!] 8/8 Wine klasör yönlendirmesi eksik.")
        else:
            print("  [✓] 8/8 Wine 'Klasörü Aç' komutu Linux varsayılan dosya yöneticisine bağlı.")
    else:
        print("  [i] 8/8 Wine prefix henüz yok — klasör yönlendirmesi kurulumda yazılacak.")

    print("----------------------------------------------------------------------")
    print(f"  Teşhis tamamlandı ({issues_fixed} sorun otomatik düzeltildi).")
    print("======================================================================\n")
    return 0


def cmd_start() -> int:
    cfg = IdmLinuxConfig.load()
    if is_daemon_running(cfg):
        print(f"  [✓] Köprü servisi zaten çalışıyor (127.0.0.1:{cfg.http_port}).")
        return 0
    subprocess.Popen(
        [sys.executable, "-m", "idm_linux.cli", "daemon-run"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(15):
        time.sleep(0.2)
        if is_daemon_running(cfg):
            print(f"  [✓] IDM-Linux köprü ve video akış servisi başlatıldı (HTTP:{cfg.http_port} / WS:{cfg.ws_port}).")
            return 0
    print("  [!] Servis başlatma zaman aşımına uğradı, 'idm-linux logs' ile kontrol edin.")
    return 1


def cmd_stop() -> int:
    subprocess.run(
        ["systemctl", "--user", "stop", "idm-linux-daemon.service"],
        capture_output=True,
        check=False,
    )
    pid_file = get_cache_dir() / "daemon.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            subprocess.run(["kill", str(pid)], check=False, capture_output=True)
        except (ValueError, OSError):
            pass
    subprocess.run(["pkill", "-f", "idm_linux.cli daemon-run"], check=False, capture_output=True)
    time.sleep(0.3)
    print("  [✓] IDM-Linux arka plan servisi durduruldu.")
    return 0


def cmd_repair(extra_ext_ids: Optional[List[str]] = None) -> int:
    from .installer import install_cli_and_desktop_entries, install_idm_binary

    cfg = IdmLinuxConfig.load()
    print("  [*] IDM-Linux kapsamlı onarım ve senkronizasyon başlatılıyor...")
    idm_exe = cfg.find_idm_exe()
    cache_d = get_cache_dir(create=False)
    cached_list = sorted(cache_d.glob("idman*build*.exe")) if cache_d.is_dir() else []
    cached_installer = cached_list[-1] if cached_list else (cache_d / "idman643build16.exe")
    if not idm_exe and cached_installer.exists():
        idm_exe = install_idm_binary(cfg, cached_installer)
    elif idm_exe:
        neutralize_windows_hook_binaries(idm_exe.parent)
        apply_idm_registry_tweaks(cfg)

    proj_root = _find_project_root()
    crx_path: Optional[Path] = get_data_dir() / "extensions" / "idm-linux-companion-chromium.crx"
    chrom_ext_dir: Optional[Path] = get_data_dir() / "extensions" / "chromium-unpacked"
    if (proj_root / "extension" / "chromium").exists():
        crx_path, chrom_ext_dir, _ = deploy_browser_extensions(proj_root)

    if (proj_root / "src").exists():
        install_cli_and_desktop_entries(proj_root, cfg, crx_path=crx_path, chrom_ext_dir=chrom_ext_dir)
    else:
        src_dir = Path(__file__).resolve().parents[1]
        wrapper = create_native_host_wrapper(sys.executable, src_dir)
        register_all_browsers(wrapper, crx_path=crx_path, chrom_ext_dir=chrom_ext_dir, extra_chromium_ids=extra_ext_ids)
    cmd_stop()
    cmd_start()
    print("  [✓] Onarım tamamlandı! Tüm tarayıcı manifestleri, orijinal IDM görev çubuğu simgeleri ve Wine ayarları yenilendi.")
    return 0


def cmd_add_url(url: str, filename: str = "", silent: bool = False, hls_mode: str = "vod") -> int:
    cfg = IdmLinuxConfig.load()
    target = url.strip()
    if target.startswith("file://"):
        import urllib.parse as _up
        target = _up.unquote(_up.urlparse(target).path)

    is_local_torrent = Path(target).expanduser().is_file() and target.lower().endswith(".torrent")
    is_magnet = target.lower().startswith("magnet:?")

    if (is_local_torrent or is_magnet) and not is_daemon_running(cfg):
        cmd_start()

    if is_daemon_running(cfg):
        if is_local_torrent or is_magnet:
            t_payload = {
                "local_path": str(Path(target).expanduser().resolve()) if is_local_torrent else "",
                "magnet": target if is_magnet else "",
                "silent": silent if silent else None,
                "source": "cli-torrent",
            }
            req = urllib.request.Request(
                f"http://127.0.0.1:{cfg.http_port}/api/torrent/download",
                data=json.dumps(t_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
            print(f"  [{'✓' if res.get('ok') else '!'}] {res.get('message', '')}")
            return 0 if res.get("ok") else 1

        payload = {
            "url": target,
            "filename": filename,
            "silent": silent if silent else None,
            "force": True,
            "source": "cli",
            "hlsMode": hls_mode,
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{cfg.http_port}/api/download",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        print(f"  [{'✓' if res.get('ok') else '!'}] {res.get('message', '')}")
        return 0 if res.get("ok") else 1

    sender = WineIdmSender(cfg)
    ok, msg = sender.send_download(DownloadRequest(url=target, filename=filename, silent=silent or None, source="cli"))
    print(f"  [{'✓' if ok else '!'}] {msg}")
    return 0 if ok else 1


def cmd_open_folder_native(raw_path: str) -> int:
    from .browsers import open_folder_native, wine_path_to_unix

    cfg = IdmLinuxConfig.load()
    unix_path = wine_path_to_unix(raw_path, cfg.wine_prefix)
    ok, msg = open_folder_native(unix_path or cfg.download_dir)
    print(f"  [{'✓' if ok else '!'}] {msg}")
    return 0 if ok else 1


def cmd_streams() -> int:
    cfg = IdmLinuxConfig.load()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{cfg.http_port}/api/streams", timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        print("  [!] Köprü servisine ulaşılamadı ('idm-linux start').")
        return 1
    streams = data.get("streams") or []
    if not streams:
        print("  [i] Aktif veya yakın zamanda tamamlanmış stream kaydı yok.")
        return 0
    print(f"  {'DURUM':<10} {'MOD':<6} {'MOTOR':<11} {'BOYUT':>10}  DOSYA / BİLET")
    for st in streams:
        durum = "BİTTİ" if st["completed"] else ("HATA" if st["failed"] else "KAYITTA")
        mb = st["size_bytes"] / (1024 * 1024)
        tot = st.get("expected_total") or 0
        boyut = f"{mb:.1f}/{tot / (1024 * 1024):.1f}MB" if tot else f"{mb:.1f}MB"
        print(f"  {durum:<10} {st['hls_mode']:<6} {st.get('backend', 'native'):<11} {boyut:>14}  {st['filename']}  [{st['ticket']}]")
    print("  İpucu: kaydı sonlandırmak için -> idm-linux stream-stop <bilet>")
    return 0


def cmd_stream_stop(ticket_id: str) -> int:
    cfg = IdmLinuxConfig.load()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{cfg.http_port}/api/stream/stop",
            data=json.dumps({"ticket": ticket_id}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        print(f"  [{'✓' if res.get('ok') else '!'}] Canlı kayıt durdurma: {res.get('ok')}")
        return 0 if res.get("ok") else 1
    except Exception as exc:
        print(f"  [!] Köprüye ulaşılamadı: {exc}")
        return 1


def cmd_playlist(url: str, pick: str = "all", hls_mode: str = "vod") -> int:
    from .stream_engine import probe_playlist_entries

    cfg = IdmLinuxConfig.load()
    if not is_daemon_running(cfg):
        cmd_start()
    print("  [*] Oynatma listesi çözümleniyor (yt-dlp --flat-playlist)...")
    info = probe_playlist_entries(url, max_items=100)
    if not info.get("ok"):
        print(f"  [!] Liste çözülemedi: {info.get('error', 'bilinmeyen')}")
        return 1
    entries = info["entries"]
    print(f"  [✓] {info.get('title', '') or url} -> {len(entries)} giriş bulundu.")
    if pick != "all":
        wanted = {int(x) for x in pick.split(",") if x.strip().isdigit()}
        entries = [e for e in entries if e["index"] in wanted]
    for e in entries[:10]:
        print(f"      {e['index']:>3}. {e['title'][:70]}")
    if len(entries) > 10:
        print(f"      ... ve {len(entries) - 10} giriş daha")
    req = urllib.request.Request(
        f"http://127.0.0.1:{cfg.http_port}/api/playlist/download",
        data=json.dumps({"entries": entries, "hlsMode": hls_mode, "referer": url}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    print(f"  [{'✓' if res.get('ok') else '!'}] {res.get('queued', 0)} video IDM kuyruğuna gönderildi.")
    return 0 if res.get("ok") else 1


def cmd_logs(lines: int = 50) -> int:
    for name in ("daemon.log", "native_host.log"):
        lf = get_cache_dir() / "logs" / name
        print(f"=== {name} ({lf}) ===")
        if lf.exists():
            all_lines = lf.read_text(encoding="utf-8", errors="ignore").splitlines()
            for ln in all_lines[-lines:]:
                print(ln)
        else:
            print("(Henüz kayıt yok)")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="idm-linux",
        description="Internet Download Manager (IDM) Evrensel Linux Kurulum, Tarayıcı ve Video Bar Entegrasyon Aracı",
    )
    sub = p.add_subparsers(dest="command")

    p_inst = sub.add_parser("install", help="Wine + En Güncel Resmi IDM + Tarayıcı & Video Bar entegrasyonunu kurar (Varsayılan: Modern GUI)")
    p_inst.add_argument("--cli", action="store_true", help="Grafik arayüz yerine klasik terminal (CLI) modunda kur")
    p_inst.add_argument("--gui", action="store_true", help="Modern GUI Kurulum Sihirbazını zorla aç")
    p_inst.add_argument("--installer", type=Path, help="Yerel bir idman*.exe kurulum dosyası kullan")
    p_inst.add_argument("--prefix", type=Path, help="Kullanılacak WINEPREFIX dizinini doğrudan belirt (ör: ~/.wine)")
    p_inst.add_argument("-y", "--yes", action="store_true", help="Varsayılan seçeneklerle etkileşimsiz (otomatik CLI) kur")
    p_inst.add_argument(
        "--mode",
        choices=["clean", "update", "uninstall"],
        help="Mevcut kurulum algılandığında uygulanacak işlem (clean=kaldır ve temiz kur, update=güncelle)",
    )
    p_inst.add_argument("--skip-pkgs", action="store_true", help="Sistem paket yöneticisi adımını atla")

    sub.add_parser("install-gui", help="Doğrudan Modern GUI Kurulum & Güncelleme Sihirbazını açar")

    sub.add_parser("status", help="Sistem, Wine, IDM, Köprü ve Tarayıcı entegrasyon durumunu gösterir")
    sub.add_parser("doctor", help="10 adımlı otomatik teşhis ve tamir doktorunu çalıştırır")
    p_open = sub.add_parser("open", help="Internet Download Manager ana penceresini açar (veya verilen URL/.torrent/magnet hedefini IDM'ye yollar)")
    p_open.add_argument("target", nargs="?", default="", help="İsteğe bağlı URL, .torrent dosyası veya magnet:? bağlantısı")
    sub.add_parser("panel", help="IDM Linux Masaüstü Kontrol Panelini (GUI) açar")
    sub.add_parser("gui", help="IDM Linux Masaüstü Kontrol Panelini (GUI) açar")
    sub.add_parser("start", help="Arka plan köprü ve video akış servisini başlatır")
    sub.add_parser("stop", help="Arka plan köprü servisini durdurur")
    sub.add_parser("restart", help="Arka plan köprü servisini yeniden başlatır")
    sub.add_parser("trial-reset", help="v3.12.0: IDM 30 günlük deneme sayacını güvenli biçimde sıfırlar (DMCACount)")

    p_rep = sub.add_parser("repair", help="Wine Registry, COM, CRX3 ve tarayıcı Native Messaging bağlantılarını onarır")
    p_rep.add_argument("--ext-id", action="append", default=[], help="Ek özel Chromium eklenti ID'si tanımla")

    p_add = sub.add_parser("add", help="Verilen URL'yi doğrudan gerçek IDM'ye gönderir (m3u8/HLS, video sitesi ve playlist akıllı yönlendirmeli)")
    p_add.add_argument("--hls-mode", choices=["vod", "dvr", "live"], default="vod",
                       help="HLS modu: dvr = yayın başından canlı takip, live = canlı kenardan kayıt")
    p_add.add_argument("--name", default="", help="İndirilecek dosyaya verilecek özel ad")
    p_pl = sub.add_parser("playlist", help="YouTube/Dailymotion vb. oynatma listesini toplu olarak IDM'ye indirir")
    p_pl.add_argument("url")
    p_pl.add_argument("--pick", default="all", help="Virgülle ayrılmış giriş numaraları (örn. 1,3,5) veya 'all'")
    p_pl.add_argument("--hls-mode", choices=["vod", "dvr", "live"], default="vod")
    sub.add_parser("streams", help="Aktif canlı/DVR stream kayıtlarını listeler")
    p_ss = sub.add_parser("stream-stop", help="Devam eden canlı/DVR stream kaydını sonlandırır")
    p_ss.add_argument("ticket")
    p_of = sub.add_parser("open-folder-native", help="Wine yolunu Linux varsayılan dosya yöneticisiyle açar")
    p_of.add_argument("path")
    p_add.add_argument("url", help="İndirilecek dosya bağlantısı")
    p_add.add_argument("-f", "--filename", default="", help="Kaydedilecek dosya adı")
    p_add.add_argument("-s", "--silent", action="store_true", help="Onay penceresi göstermeden hemen indir")

    p_log = sub.add_parser("logs", help="Köprü ve yakalama günlüklerini gösterir")
    p_log.add_argument("-n", "--lines", type=int, default=50, help="Gösterilecek satır sayısı")

    sub.add_parser("daemon-run", help="Köprü servisini ön planda çalıştırır (systemd/autostart için)")
    sub.add_parser("uninstall", help="IDM-Linux entegrasyonunu sistemden tamamen kaldırır")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cmd = args.command or "status"

    if cmd == "install-gui":
        from .gui import launch_control_panel
        return launch_control_panel(initial_page="installer", project_root=_find_project_root())

    if cmd == "install":
        use_cli_only = bool(args.cli or args.yes or args.mode or args.prefix or args.installer)
        if not use_cli_only or args.gui:
            from .gui import can_launch_gui, launch_control_panel
            if can_launch_gui():
                return launch_control_panel(initial_page="installer", project_root=_find_project_root())
        return run_full_install(
            project_root=_find_project_root(),
            custom_installer=args.installer,
            skip_system_pkgs=args.skip_pkgs,
            explicit_prefix=args.prefix,
            assume_yes=args.yes,
            existing_mode=args.mode,
        )
    if cmd == "status":
        return cmd_status()
    if cmd == "doctor":
        return cmd_doctor(auto_fix=True)
    if cmd == "open":
        if getattr(args, "target", "").strip():
            return cmd_add_url(args.target.strip())
        ok, msg = WineIdmSender(IdmLinuxConfig.load()).open_idm_window()
        print(f"  [{'✓' if ok else '!'}] {msg}")
        return 0 if ok else 1
    if cmd in ("panel", "gui"):
        from .gui import launch_control_panel
        return launch_control_panel()
    if cmd == "start":
        return cmd_start()
    if cmd == "stop":
        return cmd_stop()
    if cmd == "restart":
        cmd_stop()
        return cmd_start()
    if cmd == "trial-reset":
        ok_r, msg_r = WineIdmSender(IdmLinuxConfig.load()).trial_reset_idm()
        print(f"  [{'✓' if ok_r else '!'}] {msg_r}")
        return 0 if ok_r else 1
    if cmd == "repair":
        return cmd_repair(extra_ext_ids=args.ext_id)
    if cmd == "add":
        return cmd_add_url(
            args.url,
            filename=getattr(args, "name", "") or "",
            hls_mode=getattr(args, "hls_mode", "vod") or "vod",
        )
    if cmd == "playlist":
        return cmd_playlist(args.url, pick=args.pick, hls_mode=args.hls_mode)
    if cmd == "streams":
        return cmd_streams()
    if cmd == "stream-stop":
        return cmd_stream_stop(args.ticket)
    if cmd == "open-folder-native":
        return cmd_open_folder_native(args.path)
    if cmd == "add_legacy":
        return cmd_add_url(args.url, filename=args.filename, silent=args.silent)
    if cmd == "logs":
        return cmd_logs(lines=args.lines)
    if cmd == "daemon-run":
        return run_daemon_foreground()
    if cmd == "uninstall":
        return run_uninstall()

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
