from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import __idm_official_download_page__
from .browsers import (
    auto_install_and_open_default_browser,
    create_native_host_wrapper,
    gecko_home_roots,
    open_folder_native,
    register_all_browsers,
    unregister_all_browsers,
    wine_path_to_unix,
)
from .config import (
    DEFAULT_HTTP_PORT,
    DEFAULT_WS_PORT,
    IdmLinuxConfig,
    close_and_suppress_all_loggers,
    get_cache_dir,
    get_config_dir,
    get_data_dir,
)
from .crx_builder import (
    build_chromium_zip_package,
    build_crx3_package,
    validate_extension_directory,
    verify_crx3_package,
)
from .daemon import is_daemon_running
from .distro import detect_system, install_system_dependencies
from .firefox_ext import (
    cache_official_firefox_xpi,
    install_firefox_extensions_robust,
    official_xpi_cache_path,
)
from .i18n import get_idm_registry_language_pair
from .pe_icon_extractor import extract_idman_official_icons, extract_pe_version_label
from .sfx_unpacker import unpack_idm_installer
from .wine_sender import WineIdmSender, build_wine_env, linux_to_wine_path

IDM_SVG_ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="globe" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#38bdf8"/>
      <stop offset="55%" stop-color="#0284c7"/>
      <stop offset="100%" stop-color="#1e3a8a"/>
    </linearGradient>
    <linearGradient id="arrow" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#4ade80"/>
      <stop offset="50%" stop-color="#16a34a"/>
      <stop offset="100%" stop-color="#14532d"/>
    </linearGradient>
  </defs>
  <circle cx="58" cy="58" r="46" fill="url(#globe)" stroke="#e0f2fe" stroke-width="3"/>
  <ellipse cx="58" cy="58" rx="22" ry="45" fill="none" stroke="#bae6fd" stroke-width="2.2" opacity="0.7"/>
  <path d="M14 58 H102 M20 38 H96 M20 78 H96" stroke="#bae6fd" stroke-width="2.2" opacity="0.7" fill="none"/>
  <path d="M76 48 H98 V80 H114 L87 114 L60 80 H76 Z" fill="url(#arrow)" stroke="#f0fdf4" stroke-width="3" stroke-linejoin="round"/>
</svg>
"""

PROBLEMATIC_WIN_STUB_TARGETS = (
    # (dosya_adı, is_64bit, is_dll)
    # IDMan.exe başlangıçta (sub_45F3B0 / Timer #7) bu dosyaların varlığını GetFileAttributesW ile denetler!
    # Silinmeleri veya .disabled yapılmaları "IDM, tarayıcı ve sistem ilişkilendirmesi için gerekli olan
    # 5 dosyayı bulamıyor" uyarısına yol açar. Orijinal Windows hook ikilileri ise Wine'da çöker.
    # Bu yüzden her biri kendi orijinal adıyla 1536 baytlık güvenli no-op PE32/PE32+ stub ile değiştirilir!
    ("IDMIntegrator64.exe", True, False),
    ("IDMIntegratorAA.exe", True, False),
    ("IEMonitor.exe", False, False),
    ("IDMGrHlp.exe", False, False),
    ("MediumILStart.exe", False, False),
    ("IDMNetMon.dll", False, True),
    ("IDMNetMon64.dll", True, True),
    ("IDMNetMonAA.dll", True, True),
    ("idmbrbtn.dll", False, True),
    ("idmbrbtn64.dll", True, True),
    ("idmbrbtnAA.dll", True, True),
)

PROBLEMATIC_WIN_DRIVERS = (
    "idmwfp32.sys",
    "idmwfp64.sys",
    "idmwfpAA.sys",
    "idmtdi32.sys",
    "idmtdi64.sys",
)

PROBLEMATIC_WIN_BINARIES = tuple(x[0] for x in PROBLEMATIC_WIN_STUB_TARGETS) + PROBLEMATIC_WIN_DRIVERS
_PE_STUB_MAGIC = b"IDMLINUXSTUB"


@dataclass
class ExistingInstallation:
    kind: str       # "idm-linux" veya "wine-idm"
    label: str
    path: Path
    prefix: Optional[Path] = None


@dataclass
class InstallResult:
    ok: bool
    wine_prefix: Path
    idm_exe: Path
    crx_path: Path
    chrom_ext_dir: Path
    ff_xpi_path: Path
    cli_bin: Path
    service_alive: bool


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_choice(prompt_text: str, default: str, valid: List[str]) -> str:
    if not _is_interactive():
        return default
    while True:
        try:
            ans = input(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if not ans:
            return default
        if ans in valid:
            return ans
        print(f"  [!] Lütfen geçerli bir seçenek girin ({'/'.join(valid)}).")


def discover_wine_prefixes() -> List[Path]:
    """Sistemdeki tüm mevcut Wine prefix dizinlerini keşfeder."""
    home = Path.home()
    candidates: List[Path] = []

    env_pfx = os.environ.get("WINEPREFIX", "").strip()
    if env_pfx:
        candidates.append(Path(env_pfx).expanduser())

    candidates.append(home / ".wine")
    candidates.append(get_data_dir() / "prefix")

    for parent in (
        home / ".local" / "share" / "wineprefixes",
        home / ".PlayOnLinux" / "wineprefix",
        home / ".local" / "share" / "bottles" / "bottles",
    ):
        if parent.is_dir():
            for child in sorted(parent.iterdir()):
                if child.is_dir():
                    candidates.append(child)

    found: List[Path] = []
    seen = set()
    for c in candidates:
        try:
            rp = c.resolve()
        except OSError:
            continue
        if rp in seen:
            continue
        if (rp / "drive_c").is_dir() or (rp / "system.reg").is_file():
            seen.add(rp)
            found.append(rp)
    return found


def get_wine_prefix_choices() -> List[Tuple[str, Path]]:
    """GUI ve CLI için önceliklendirilmiş Wine ortamı seçeneklerini döndürür (~/.wine varsa 1. sırada!)."""
    home_wine = Path.home() / ".wine"
    isolated_wine = get_data_dir() / "prefix"
    existing_prefixes = discover_wine_prefixes()

    options: List[Tuple[str, Path]] = []
    seen = set()

    if (home_wine / "drive_c").exists() or (home_wine / "system.reg").exists():
        rp = home_wine.resolve()
        options.append((f"Mevcut Varsayılan Wine Ortamı ({rp}) [Önerilen]", rp))
        seen.add(rp)

    for pfx in existing_prefixes:
        if pfx not in seen and pfx != isolated_wine.resolve():
            options.append((f"Mevcut Wine Ortamı ({pfx})", pfx))
            seen.add(pfx)

    iso_label = f"IDM'ye Özel İzole Wine Ortamı ({isolated_wine})"
    if not options:
        options.append((f"{iso_label} [Varsayılan]", isolated_wine))
        options.append((f"Standart Ev Dizini Wine Ortamı Oluştur ({home_wine})", home_wine))
    else:
        options.append((iso_label, isolated_wine))

    return options


def scan_existing_idm_installations() -> List[ExistingInstallation]:
    """Sistemdeki mevcut IDM-Linux veya Wine IDM kurulumlarını dinamik olarak tespit eder."""
    results: List[ExistingInstallation] = []
    seen_paths = set()

    data_dir = get_data_dir()
    cfg_file = get_config_dir() / "config.json"
    cli_bin = Path.home() / ".local" / "bin" / "idm-linux"
    if (data_dir / "app").exists() or (data_dir / "extensions").exists() or cfg_file.exists() or cli_bin.exists():
        results.append(
            ExistingInstallation(
                kind="idm-linux",
                label="IDM-Linux Entegrasyon Paketi",
                path=data_dir,
            )
        )
        seen_paths.add(data_dir.resolve())

    for pfx in discover_wine_prefixes():
        for prog_sub in ("Program Files (x86)", "Program Files"):
            idm_dir = pfx / "drive_c" / prog_sub / "Internet Download Manager"
            if (idm_dir / "IDMan.exe").exists():
                rp = idm_dir.resolve()
                if rp not in seen_paths:
                    seen_paths.add(rp)
                    results.append(
                        ExistingInstallation(
                            kind="wine-idm",
                            label=f"Wine IDM Kurulumu (Prefix: {pfx})",
                            path=idm_dir,
                            prefix=pfx,
                        )
                    )

    return results


def _safe_run_quiet(
    cmd: List[str],
    env: Optional[dict] = None,
    timeout: float = 4.0,
) -> None:
    """Hiçbir koşulda TimeoutExpired veya OSError fırlatmadan sessizce komut çalıştırır."""
    try:
        subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _refresh_desktop_and_icon_caches() -> None:
    """KDE Plasma 6/5 (kbuildsycoca), GTK ve XDG masaüstü/simge önbelleklerini sessizce günceller."""
    apps_dir = Path.home() / ".local" / "share" / "applications"
    hicolor_root = Path.home() / ".local" / "share" / "icons" / "hicolor"
    if shutil.which("update-desktop-database") and apps_dir.is_dir():
        _safe_run_quiet(["update-desktop-database", str(apps_dir)], timeout=4.0)
    if shutil.which("gtk-update-icon-cache") and hicolor_root.is_dir():
        _safe_run_quiet(["gtk-update-icon-cache", "-f", "-t", str(hicolor_root)], timeout=4.0)
    for ksycoca in ("kbuildsycoca6", "kbuildsycoca5"):
        if shutil.which(ksycoca):
            _safe_run_quiet([ksycoca, "--noincremental"], timeout=5.0)
            break


def stop_all_idm_processes(wine_prefixes: Optional[List[Path]] = None) -> None:
    _safe_run_quiet(["systemctl", "--user", "stop", "idm-linux-daemon.service"], timeout=4.0)
    _safe_run_quiet(["pkill", "-f", "idm_linux.cli daemon-run"], timeout=2.5)
    for exe_pat in ("IDMan.exe", "IDMIntegrator", "IEMonitor.exe", "IDMGrHlp.exe", "idmBroker.exe"):
        _safe_run_quiet(["pkill", "-fi", exe_pat], timeout=2.5)

    wineserver = shutil.which("wineserver")
    if wineserver and wine_prefixes:
        for pfx in wine_prefixes:
            if pfx.exists():
                env = os.environ.copy()
                env["WINEPREFIX"] = str(pfx)
                _safe_run_quiet([wineserver, "-k"], env=env, timeout=3.5)
    time.sleep(0.25)


def clean_existing_installations(
    found: List[ExistingInstallation],
    remove_isolated_prefix: bool = True,
    log_fn: Callable[[str], None] = print,
) -> None:
    """
    Kullanıcının paylaşımlı Wine prefix'ine (~/.wine içindeki diğer programlara) zarar vermeden
    yalnızca eski IDM klasörlerini, izole prefix'i ve eski servis dosyalarını temizler.
    """
    prefixes = [item.prefix for item in found if item.prefix is not None]
    stop_all_idm_processes(prefixes)

    for item in found:
        if item.kind == "wine-idm" and item.path.exists():
            log_fn(f"  [*] Eski IDM dizini kaldırılıyor: {item.path}")
            shutil.rmtree(item.path, ignore_errors=True)

    isolated_pfx = get_data_dir() / "prefix"
    if remove_isolated_prefix and isolated_pfx.exists():
        log_fn(f"  [*] Eski izole Wine prefix temizleniyor: {isolated_pfx}")
        shutil.rmtree(isolated_pfx, ignore_errors=True)

    # bin/yt-dlp dosyasını koruyarak diğer alt dizinleri temizle
    for sub in ("app", "extensions", "service"):
        p = get_data_dir() / sub
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    native_wrapper = get_data_dir() / "bin" / "idm-native-host"
    native_wrapper.unlink(missing_ok=True)

    wine_menu = Path.home() / ".local" / "share" / "applications" / "wine" / "Programs" / "Internet Download Manager"
    if wine_menu.exists():
        shutil.rmtree(wine_menu, ignore_errors=True)


def prompt_existing_installation_action(
    found: List[ExistingInstallation],
    auto_mode: Optional[str] = None,
) -> str:
    if not found:
        return "fresh"

    print("  [!] Sistemde halihazırda kurulu IDM / IDM-Linux bileşenleri algılandı:")
    for item in found:
        print(f"      • {item.label}: {item.path}")
    print()

    if auto_mode in ("clean", "update", "uninstall"):
        return auto_mode
    if not _is_interactive():
        return "update"

    print("  Nasıl devam etmek istersiniz?")
    print("    1) Kaldır ve Sıfırdan Temiz Kur (Eski IDM dosyalarını temizler, sıfırdan kurar) [Varsayılan]")
    print("    2) Mevcut Kurulumu Güncelle / Onar (İndirme listesini koruyarak köprü ve dosyaları yeniler)")
    print("    3) Yalnızca Mevcut Kurulumu Kaldır ve Çık")
    print("    4) İptal Et")
    choice = _prompt_choice("  Seçiminiz [1]: ", default="1", valid=["1", "2", "3", "4"])
    return {"1": "clean", "2": "update", "3": "uninstall", "4": "abort"}[choice]


def choose_wine_prefix(
    explicit_prefix: Optional[Path] = None,
    assume_yes: bool = False,
) -> Path:
    if explicit_prefix is not None:
        return explicit_prefix.expanduser().resolve()

    options = get_wine_prefix_choices()
    if assume_yes or not _is_interactive():
        chosen = options[0][1]
        print(f"  [✓] Seçilen Wine Ortamı (WINEPREFIX): {chosen}")
        return chosen

    print("\n  [?] Hangi Wine ortamını (WINEPREFIX) kullanmak istersiniz?")
    for idx, (label, _p) in enumerate(options, start=1):
        print(f"    {idx}) {label}")
    custom_idx = str(len(options) + 1)
    print(f"    {custom_idx}) Özel bir Wine prefix dizin yolu gir")

    valid_choices = [str(i) for i in range(1, len(options) + 2)]
    ans = _prompt_choice("  Seçiminiz [1]: ", default="1", valid=valid_choices)
    if ans == custom_idx:
        raw_custom = input("  Özel WINEPREFIX dizin yolunu girin: ").strip()
        if raw_custom:
            return Path(raw_custom).expanduser().resolve()
    chosen_path = options[int(ans) - 1][1]
    print(f"  [✓] Seçilen Wine Ortamı: {chosen_path}")
    return chosen_path


def detect_screen_dpi() -> int:
    scale = os.environ.get("GDK_SCALE") or os.environ.get("QT_SCALE_FACTOR")
    if scale:
        try:
            val = float(scale)
            if val >= 1.2:
                return max(96, min(288, int(round(96 * val))))
        except ValueError:
            pass

    if shutil.which("xrdb"):
        try:
            res = subprocess.run(["xrdb", "-query"], capture_output=True, text=True, timeout=2, check=False)
            m = re.search(r"Xft\.dpi:\s*(\d+)", res.stdout)
            if m:
                dpi = int(m.group(1))
                if 96 <= dpi <= 288:
                    return dpi
        except (OSError, subprocess.SubprocessError):
            pass
    return 96


_OFFICIAL_IDM_EXE_RE = re.compile(
    r"(https?://(?:download|mirror2?)\.internetdownloadmanager\.com/(idman(\d+)build(\d+[a-z]?)\.exe))",
    re.IGNORECASE,
)


def _format_idm_ver_code(ver_digits: str, build_str: str) -> str:
    if len(ver_digits) >= 3:
        return f"{ver_digits[0]}.{ver_digits[1:]} Build {build_str.upper()}"
    return f"{ver_digits} Build {build_str.upper()}"


def resolve_latest_official_idm_release(
    fallback_url: str,
    log_fn: Callable[[str], None] = print,
) -> Tuple[str, str, str]:
    """
    Resmi internetdownloadmanager.com indirme sayfasını sorgulayarak her zaman
    EN GÜNCEL resmi IDM kurulum bağlantısını, dosya adını ve sürüm etiketini döndürür.
    Çevrimdışıysa önbellekteki en güncel pakete veya fallback_url adresine döner.
    """
    try:
        req = urllib.request.Request(
            __idm_official_download_page__,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
            },
        )
        with urllib.request.urlopen(req, timeout=7) as resp:
            page_html = resp.read().decode("utf-8", errors="ignore")
        matches = _OFFICIAL_IDM_EXE_RE.findall(page_html)
        if matches:
            # En yüksek sürüm/build numarasına sahip resmi bağlantıyı seç
            def _rank(m: Tuple[str, str, str, str]) -> Tuple[int, int]:
                v_num = int(m[2]) if m[2].isdigit() else 0
                b_digits = re.sub(r"\D", "", m[3])
                b_num = int(b_digits) if b_digits else 0
                return (v_num, b_num)

            best_url, best_fname, v_dig, b_str = max(matches, key=_rank)
            # download.internetdownloadmanager.com birincil CDN tercih edilir
            for u, fn, vd, bs in matches:
                if fn.lower() == best_fname.lower() and "download.internetdownloadmanager.com" in u.lower():
                    best_url, best_fname, v_dig, b_str = u, fn, vd, bs
                    break
            ver_label = _format_idm_ver_code(v_dig, b_str)
            log_fn(f"  [✓] Resmi siteden en güncel IDM sürümü algılandı: v{ver_label} ({best_fname})")
            return best_url, best_fname, ver_label
    except Exception:
        pass

    # Çevrimdışı yedek: Önbellekte daha önce indirilmiş idman*build*.exe var mı?
    cache_dir = get_cache_dir(create=False)
    if cache_dir.is_dir():
        cached_candidates = sorted(cache_dir.glob("idman*build*.exe"))
        if cached_candidates:
            latest_cached = cached_candidates[-1]
            m = re.match(r"idman(\d+)build(\d+[a-z]?)\.exe", latest_cached.name, re.IGNORECASE)
            ver_lbl = _format_idm_ver_code(m.group(1), m.group(2)) if m else "Official"
            return fallback_url, latest_cached.name, ver_lbl

    m_fb = _OFFICIAL_IDM_EXE_RE.search(fallback_url)
    if m_fb:
        return fallback_url, m_fb.group(2), _format_idm_ver_code(m_fb.group(3), m_fb.group(4))
    return fallback_url, "idman_latest.exe", "Latest"


def download_idm_installer(
    url: str,
    dest_path: Path,
    log_fn: Callable[[str], None] = print,
    dl_progress_cb: Optional[Callable[[int], None]] = None,
) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists() and dest_path.stat().st_size > 5_000_000:
        if dest_path.read_bytes()[:2] == b"MZ":
            log_fn(f"  [✓] Kurulum paketi önbellekte hazır: {dest_path.name}")
            if dl_progress_cb:
                dl_progress_cb(100)
            return dest_path

    log_fn(f"  [*] Resmi IDM paketi indiriliyor: {url}")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
        },
    )
    last_reported_pct = -1
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or "0")
        downloaded = 0
        chunks = []
        while True:
            blk = resp.read(131_072)
            if not blk:
                break
            chunks.append(blk)
            downloaded += len(blk)
            if total > 0:
                pct = int(downloaded * 100 / total)
                if dl_progress_cb and pct != last_reported_pct:
                    dl_progress_cb(pct)
                if log_fn is print:
                    sys.stdout.write(f"\r      İndiriliyor: %{pct:3d} ({downloaded // 1024} / {total // 1024} KB)")
                    sys.stdout.flush()
                elif pct // 25 != last_reported_pct // 25:
                    log_fn(f"      İndiriliyor: %{pct} ({downloaded // 1024} / {total // 1024} KB)")
                last_reported_pct = pct
    if total > 0 and log_fn is print:
        sys.stdout.write("\n")

    raw = b"".join(chunks)
    if len(raw) < 1_000_000 or raw[:2] != b"MZ":
        raise RuntimeError("İndirilen dosya geçerli bir IDM Windows kurulum paketi değil.")
    dest_path.write_bytes(raw)
    log_fn(f"  [✓] İndirme tamamlandı ({len(raw) / (1024 * 1024):.1f} MB).")
    return dest_path


def initialize_wine_prefix(cfg: IdmLinuxConfig, log_fn: Callable[[str], None] = print) -> None:
    prefix_path = Path(cfg.wine_prefix)
    if (prefix_path / "system.reg").exists() and (prefix_path / "drive_c").exists():
        log_fn(f"  [✓] Mevcut Wine ortamı hazır: {prefix_path}")
        return

    prefix_path.mkdir(parents=True, exist_ok=True)
    env = build_wine_env(cfg)
    log_fn(f"  [*] Wine ortamı ilk kez yapılandırılıyor: {prefix_path}")
    subprocess.run(
        ["wineboot", "-u"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=90,
        check=False,
    )
    wineserver = shutil.which("wineserver")
    if wineserver:
        subprocess.run([wineserver, "-w"], env=env, timeout=30, check=False)


def build_minimal_pe_stub(is_64bit: bool = False, is_dll: bool = False) -> bytes:
    """
    1536 baytlık %100 standartlara uygun, ASLR (.reloc) destekli, penceresiz (SUBSYSTEM_WINDOWS_GUI=2)
    sessiz Windows PE32 (i386) / PE32+ (x86_64) stub ikilisi üretir:
      - EXE: EntryPoint -> xor eax, eax; ret  (0 koduyla anında sessizce çıkar, Wine çökmesi olmaz)
      - DLL: DllMain    -> mov eax, 1; ret 12 / ret (hiçbir Windows hook yüklemeden TRUE döner)
    """
    dos_hdr = bytearray(0x80)
    dos_hdr[0:2] = b"MZ"
    dos_hdr[0x40 : 0x40 + len(_PE_STUB_MAGIC)] = _PE_STUB_MAGIC
    struct.pack_into("<I", dos_hdr, 0x3C, 0x80)

    machine = 0x8664 if is_64bit else 0x014C
    chars = (0x0002 | 0x0020) if is_64bit else (0x0002 | 0x0100)
    if is_dll:
        chars |= 0x2000

    opt_size = 0xF0 if is_64bit else 0xE0
    coff_hdr = struct.pack("<HHIIIHH", machine, 2, 0, 0, 0, opt_size, chars)

    opt = bytearray(opt_size)
    if is_64bit:
        hdr_part = struct.pack(
            "<HBBIIIIIQIIHHHHHHIIIIHHQQQQII",
            0x20B, 14, 0, 0x200, 0x200, 0, 0x1000, 0x1000,
            0x187A40000 if is_dll else 0x140000000,
            0x1000, 0x200,
            6, 0, 0, 0, 6, 0, 0,
            0x3000, 0x200, 0,
            2, 0x0160,
            0x100000, 0x1000, 0x100000, 0x1000,
            0, 16,
        )
        opt[:112] = hdr_part
        struct.pack_into("<II", opt, 112 + 5 * 8, 0x2000, 12)
        code_bytes = b"\xb8\x01\x00\x00\x00\xc3" if is_dll else b"\x31\xc0\xc3"
    else:
        hdr_part = struct.pack(
            "<HBBIIIIIIIIIHHHHHHIIIIHHIIIIII",
            0x10B, 14, 0, 0x200, 0x200, 0, 0x1000, 0x1000, 0x2000,
            0x67A40000 if is_dll else 0x00400000,
            0x1000, 0x200,
            6, 0, 0, 0, 6, 0, 0,
            0x3000, 0x200, 0,
            2, 0x0140,
            0x100000, 0x1000, 0x100000, 0x1000,
            0, 16,
        )
        opt[:96] = hdr_part
        struct.pack_into("<II", opt, 96 + 5 * 8, 0x2000, 12)
        code_bytes = b"\xb8\x01\x00\x00\x00\xc2\x0c\x00" if is_dll else b"\x31\xc0\xc3"

    sec_text = struct.pack(
        "<8sIIIIIIHHI",
        b".text\x00\x00\x00",
        len(code_bytes), 0x1000, 0x200, 0x200,
        0, 0, 0, 0,
        0x60000020,
    )
    reloc_bytes = struct.pack("<IIHH", 0x1000, 12, 0, 0)
    sec_reloc = struct.pack(
        "<8sIIIIIIHHI",
        b".reloc\x00\x00",
        len(reloc_bytes), 0x2000, 0x200, 0x400,
        0, 0, 0, 0,
        0x42000040,
    )

    headers = (bytes(dos_hdr) + b"PE\x00\x00" + coff_hdr + bytes(opt) + sec_text + sec_reloc).ljust(0x200, b"\x00")
    return headers + code_bytes.ljust(0x200, b"\x00") + reloc_bytes.ljust(0x200, b"\x00")


def neutralize_windows_hook_binaries(idm_dir: Path) -> int:
    """
    1) Eski sürümlerden kalmış '*.disabled' dosyalarını temizler,
    2) Windows kernel (.sys) sürücülerini kaldırır,
    3) Sorunlu Windows tarayıcı hook ikililerini (.exe / .dll) silmek yerine KENDİ ORİJİNAL ADIYLA
       1536 baytlık güvenli sessiz PE32/PE32+ stub ile değiştirir (eksikse oluşturur).
    Böylece hem Wine çökmeleri %100 engellenir, hem de IDMan.exe'nin başlangıçtaki dosya bütünlük
    taraması (sub_45F3B0 -> '5 dosyayı bulamıyor' uyarısı) %100 memnun edilir (missing = 0)!
    """
    if not idm_dir.is_dir():
        return 0

    neutralized = 0

    # Önce eski kurulumlardan kalan .disabled kalıntılarını temizle
    for old_dis in list(idm_dir.glob("*.disabled")):
        try:
            old_dis.unlink(missing_ok=True)
        except OSError:
            pass

    # Mevcut klasördeki büyük/küçük harf eşleşmelerini bul
    existing_by_lower = {p.name.lower(): p for p in idm_dir.iterdir() if p.is_file()}

    # Kernel .sys sürücülerini kaldır (sub_45F3B0 tarafından aranmazlar)
    for drv_name in PROBLEMATIC_WIN_DRIVERS:
        p_drv = existing_by_lower.get(drv_name.lower())
        if p_drv and p_drv.is_file():
            try:
                p_drv.unlink(missing_ok=True)
                neutralized += 1
            except OSError:
                pass

    # Hook .exe ve .dll dosyalarını güvenli PE stub ile değiştir / eksikse oluştur
    for target_name, is_64, is_dll in PROBLEMATIC_WIN_STUB_TARGETS:
        target_path = existing_by_lower.get(target_name.lower(), idm_dir / target_name)
        already_stub = False
        if target_path.is_file():
            try:
                head = target_path.read_bytes()[:0x60]
                if _PE_STUB_MAGIC in head:
                    already_stub = True
            except OSError:
                pass
        if not already_stub:
            try:
                target_path.write_bytes(build_minimal_pe_stub(is_64bit=is_64, is_dll=is_dll))
                neutralized += 1
            except OSError:
                pass

    # IDMan.exe sub_45F3B0 bütünlük kontrolünün aradığı yardımcı veri dosyaları silinmişse koru
    for aux_name, aux_payload in (
        ("IDMMsgHost.json", b'{"name":"com.tonec.idm","type":"stdio"}\n'),
        ("IDMGCExt.crx", b"Cr24\x03\x00\x00\x00\x00\x00\x00\x00"),
    ):
        if aux_name.lower() not in existing_by_lower:
            try:
                (idm_dir / aux_name).write_bytes(aux_payload)
            except OSError:
                pass

    return neutralized


def resolve_effective_idm_language(cfg: IdmLinuxConfig) -> Tuple[int, str]:
    """
    Seçilen arayüz dilini IDM destekliyorsa o dilin (LanguageID, idm_*.lng) çiftini,
    IDM desteklemiyorsa veya .lng dosyası mevcut değilse İngilizce (0x09, "") çiftini döndürür.
    """
    lang_id, lang_file = get_idm_registry_language_pair(cfg.language)
    if lang_file:
        idm_exe = cfg.find_idm_exe()
        if idm_exe is not None:
            lng_path = idm_exe.parent / "Languages" / lang_file
            if not lng_path.is_file():
                return (0x09, "")
    return (lang_id, lang_file)


def sync_idm_language_live(cfg: IdmLinuxConfig) -> Tuple[int, str]:
    """
    GUI üzerinden dil değiştirildiğinde Wine içindeki IDM arayüz dilini anında senkronize eder.
    Kaldırılmış / henüz kurulmamış sistemlerde hiçbir dosya veya klasör oluşturmaz!
    """
    lang_id, lang_file = resolve_effective_idm_language(cfg)
    if not shutil.which("wine") or cfg.find_idm_exe() is None:
        return (lang_id, lang_file)

    env = build_wine_env(cfg)
    reg_content = f"""Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\\Software\\DownloadManager]
"LanguageID"=dword:{lang_id:08x}
"fulllngfile"="{lang_file}"
"""
    reg_file = get_cache_dir(create=True) / "idm_lang_sync.reg"
    reg_file.write_bytes(b"\xff\xfe" + reg_content.replace("\n", "\r\n").encode("utf-16-le"))
    try:
        subprocess.run(
            ["wine", "regedit", "/S", str(reg_file)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    return (lang_id, lang_file)


def apply_idm_registry_tweaks(cfg: IdmLinuxConfig, log_fn: Callable[[str], None] = print) -> None:
    if not shutil.which("wine"):
        return

    env = build_wine_env(cfg)
    dl_dir = Path(cfg.download_dir).expanduser().resolve()
    dl_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = get_cache_dir(create=True) / "DwnlData"
    temp_dir.mkdir(parents=True, exist_ok=True)

    win_dl = linux_to_wine_path(dl_dir).replace("\\", "\\\\")
    win_tmp = linux_to_wine_path(temp_dir).replace("\\", "\\\\")
    dpi = cfg.dpi_scale if cfg.dpi_scale > 0 else detect_screen_dpi()
    lang_id, lang_file = resolve_effective_idm_language(cfg)

    reg_content = f"""Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\\Software\\DownloadManager]
"EnableDriver"=dword:00000000
"LaunchOnStart"=dword:00000001
"MonitorClipboard"=dword:00000000
"MaxConnectionsNumber"=dword:{cfg.max_connections:08x}
"ConnectionSpeed"=dword:000f4240
"LanguageID"=dword:{lang_id:08x}
"fulllngfile"="{lang_file}"
"LocalPathW"="{win_dl}"
"LocalPath"="{win_dl}"
"TempPath"="{win_tmp}"
"UseHttpProxy"=dword:00000000
"FindApps"=dword:00000000
"radxcnt"=dword:00000001

[HKEY_CURRENT_USER\\Software\\Wine\\WineDbg]
"ShowCrashDialog"=dword:00000000

[HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides]
"idmnetmon"=""
"idmnetmon64"=""
"idmbrbtn"=""
"idmbrbtn64"=""
"idmwfp32"=""
"idmwfp64"=""
"idmtdi32"=""
"idmtdi64"=""

[HKEY_CURRENT_USER\\Control Panel\\Desktop]
"FontSmoothing"="2"
"FontSmoothingType"=dword:00000002
"FontSmoothingGamma"=dword:00000578
"FontSmoothingOrientation"=dword:00000001
"LogPixels"=dword:{dpi:08x}

[HKEY_CURRENT_USER\\Software\\Wine\\X11 Driver]
"Managed"="Y"
"Decorated"="Y"
"UseTakeFocus"="Y"

[HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize]
"AppsUseLightTheme"=dword:00000001
"SystemUsesLightTheme"=dword:00000001
"ColorPrevalence"=dword:00000000
"""
    reg_file = get_cache_dir(create=True) / "idm_linux_tweaks.reg"
    reg_file.write_bytes(b"\xff\xfe" + reg_content.replace("\n", "\r\n").encode("utf-16-le"))

    idm_lang_desc = lang_file if lang_file else "English (0x09)"
    log_fn(f"  [*] Wine & IDM Registry optimizasyonları uygulanıyor (Sıfır Crash, IDM Dili={idm_lang_desc}, ClearType, HiDPI, Açık Tema)...")
    subprocess.run(
        ["wine", "regedit", "/S", str(reg_file)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=25,
        check=False,
    )
    WineIdmSender(cfg).ensure_bridge_scripts()


def ensure_idm_light_theme_registry(cfg: IdmLinuxConfig) -> bool:
    """v3.4.0 SİYAH İNDİRME PENCERESİ KÖK-DÜZELTMESİ.

    Kullanıcı raporu: IDM indirme penceresi (OK.ru vb. görsel) SİYAHLAŞIYOR. Kök-neden:
    Wine 8.13+ Linux sistem koyu temasını (GTK color-scheme=prefer-dark) Windows
    'dark mode' bayrağına çevirir; IDM 6.4x'in koyu-tema duyarlı diyalogları Wine'ın
    GDI katmanında boş/kayıp fırçalarla çizilince pencere SİYAH'a boyanır.

    Çözüm: Wine prefix kayıt defterinde Windows'un AÇIK tema bayraklarını dayat
    (AppsUseLightTheme=1 / SystemUsesLightTheme=1). Daemon her başlangıçta VE her
    IDM çalıştırmasında bu fonksiyonu çağırır — kullanıcı ne yaparsa yapsın
    (sistem temasını değiştirsin vb.) IDM pencereleri daima AÇIK temada çizilir.
    Dönüş: kayıt defteri yazımı başarılıysa True."""
    if not shutil.which("wine"):
        return False
    try:
        env = build_wine_env(cfg)
        # Açık tema bayrakları: .reg dosyası (UTF-16 BOM'lu) + sessiz regedit
        reg_content = """Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize]
"AppsUseLightTheme"=dword:00000001
"SystemUsesLightTheme"=dword:00000001
"ColorPrevalence"=dword:00000000
"""
        reg_file = get_cache_dir(create=True) / "idm_light_theme.reg"
        reg_file.write_bytes(b"\xff\xfe" + reg_content.replace("\n", "\r\n").encode("utf-16-le"))
        subprocess.run(
            ["wine", "regedit", "/S", str(reg_file)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        return True
    except Exception:
        return False


def install_idm_binary(
    cfg: IdmLinuxConfig,
    installer_exe: Path,
    log_fn: Callable[[str], None] = print,
) -> Path:
    c_drive = Path(cfg.wine_prefix) / "drive_c"
    prog_base = c_drive / "Program Files (x86)"
    if not prog_base.exists():
        prog_base = c_drive / "Program Files"
    target_dir = prog_base / "Internet Download Manager"

    log_fn(f"  [*] Orijinal IDM bileşenleri doğrudan Wine ortamına kuruluyor: {target_dir}")
    written = unpack_idm_installer(installer_exe, target_dir)
    disabled_n = neutralize_windows_hook_binaries(target_dir)
    # v2.8.0: Paketin içinden çıkan AMO İMZALI idmmzcc3.xpi'yi kalıcı önbelleğe al
    # (Firefox RELEASE doğrulamasından geçen tek yol resmi imzalı XPI'dir!)
    cached_xpi = cache_official_firefox_xpi(target_dir)
    if cached_xpi:
        log_fn(f"  [✓] Resmi imzalı Firefox XPI önbelleğe alındı: {cached_xpi.name}")
    log_fn(
        f"  [✓] {len(written)} orijinal bileşen çıkarıldı "
        f"({disabled_n} adet Wine-uyumsuz Windows kernel/hook modülü izole edildi)."
    )

    idm_exe = target_dir / "IDMan.exe"
    apply_idm_registry_tweaks(cfg, log_fn=log_fn)

    if shutil.which("wine") and idm_exe.exists():
        env = build_wine_env(cfg)
        log_fn("  [*] IDM COM Otomasyon Sunucusu (IDMan.CIDMLinkTransmitter) kaydediliyor...")
        try:
            subprocess.run(
                ["wine", str(idm_exe), "/RegServer"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=False,
            )
            for dll_name in ("downlWithIDM.dll", "IDMIECC.dll"):
                dll_path = target_dir / dll_name
                if dll_path.exists():
                    subprocess.run(
                        ["wine", "regsvr32", "/s", str(dll_path)],
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=15,
                        check=False,
                    )
        except subprocess.SubprocessError:
            pass

    return idm_exe


def deploy_browser_extensions(project_root: Path) -> Tuple[Path, Path, Path]:
    """
    Hibrit Tarayıcı Eklentisini katı manifest doğrulamasından geçirerek 3 formatta hazırlar:
      1) İmzalı Chromium CRX3 paketi : idm-linux-companion-chromium.crx
      2) Paketlenmemiş Chromium dizini: chromium/
      3) Firefox WebExtension paketi : idm-linux-companion-firefox.xpi
    """
    ext_dest = get_data_dir() / "extensions"
    ext_dest.mkdir(parents=True, exist_ok=True)

    chrom_src = project_root / "extension" / "chromium"
    ff_src = project_root / "extension" / "firefox"
    if not chrom_src.exists():
        # Kurulu kopyadan çalışıyorsa yedek kontrol
        alt_ext = get_data_dir() / "app" / "extension"
        if (alt_ext / "chromium").exists():
            chrom_src = alt_ext / "chromium"
            ff_src = alt_ext / "firefox"

    missing_chrom = validate_extension_directory(chrom_src)
    if missing_chrom:
        raise RuntimeError(f"Chromium eklenti dosyaları eksik: {missing_chrom}")
    missing_ff = validate_extension_directory(ff_src)
    if missing_ff:
        raise RuntimeError(f"Firefox eklenti dosyaları eksik: {missing_ff}")

    chrom_dest = ext_dest / "chromium"
    if chrom_dest.resolve() != chrom_src.resolve():
        if chrom_dest.exists():
            shutil.rmtree(chrom_dest)
        shutil.copytree(chrom_src, chrom_dest)

    crx_path = ext_dest / "idm-linux-companion-chromium.crx"
    build_crx3_package(chrom_src, crx_path)
    ok_crx, crx_msg = verify_crx3_package(crx_path)
    if not ok_crx:
        raise RuntimeError(f"CRX3 paket doğrulaması başarısız: {crx_msg}")

    # Tarayıcıların CRX engeline ve CRX_REQUIRED_PROOF_MISSING hatasına takılmayan ZIP paketi
    zip_path = ext_dest / "idm-linux-companion-chromium.zip"
    build_chromium_zip_package(chrom_src, zip_path)

    ff_xpi = ext_dest / "idm-linux-companion-firefox.xpi"
    with zipfile.ZipFile(ff_xpi, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file_path in sorted(ff_src.rglob("*")):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(ff_src).as_posix())

    return crx_path, chrom_dest, ff_xpi


def verify_and_start_bridge_service(cli_bin: Path, cfg: IdmLinuxConfig) -> bool:
    sys_info = detect_system()

    subprocess.run(
        ["systemctl", "--user", "stop", "idm-linux-daemon.service"],
        capture_output=True,
        check=False,
    )
    subprocess.run(["pkill", "-f", "idm_linux.cli daemon-run"], capture_output=True, check=False)
    time.sleep(0.3)

    if sys_info.init_system == "systemd":
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, capture_output=True)
        subprocess.run(["systemctl", "--user", "reset-failed", "idm-linux-daemon.service"], check=False, capture_output=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "idm-linux-daemon.service"],
            check=False,
            capture_output=True,
        )

    for attempt in range(2):
        for _ in range(12):
            time.sleep(0.2)
            if is_daemon_running(cfg):
                return True
        if attempt == 0:
            subprocess.Popen(
                [str(cli_bin), "daemon-run"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    return is_daemon_running(cfg)


def _find_desktop_dir() -> Optional[Path]:
    home = Path.home()
    for cand in (home / "Masaüstü", home / "Desktop"):
        if cand.is_dir():
            return cand
    return None


def resolve_src_base(project_root: Path) -> Path:
    """PYTHONPATH tabanı: idm_linux paketini içeren dizini döndürür.

    - Yeni depo düzeni: proje kökü = src/idm_linux paket ağacının kendisi
      (extension/, bin/, language/ bu dizinde) → taban = bir üst dizin (…/src).
    - Eski düzen / kurulu app kopyası: <kök>/src (veya app/src) klasik düzen.
    """
    for cand in (project_root / "src", project_root.parent, project_root):
        try:
            if (cand / "idm_linux" / "__init__.py").exists():
                return cand.resolve()
        except OSError:
            continue
    return (project_root / "src").resolve()


def install_cli_and_desktop_entries(
    project_root: Path,
    cfg: IdmLinuxConfig,
    crx_path: Optional[Path] = None,
    chrom_ext_dir: Optional[Path] = None,
    create_desktop_icons: bool = False,
) -> Tuple[Path, bool]:
    # Yeni depo düzeninde project_root = src/idm_linux paket ağacıdır; taban esnek çözülür.
    src_dir = resolve_src_base(project_root)
    py_exe = sys.executable

    installed_src = get_data_dir() / "app" / "src"
    if installed_src.resolve() != src_dir:
        if installed_src.exists():
            shutil.rmtree(installed_src)
        installed_src.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_dir, installed_src)
        runtime_src = installed_src
    else:
        runtime_src = src_dir

    # Eklenti kaynaklarını da ~/.local/share/idm-linux/app/extension altına yedekle (panelden onarım için!)
    ext_src = project_root / "extension"
    installed_ext = get_data_dir(create=True) / "app" / "extension"
    if ext_src.exists() and installed_ext.resolve() != ext_src.resolve():
        if installed_ext.exists():
            shutil.rmtree(installed_ext)
        shutil.copytree(ext_src, installed_ext)

    # 20 dilli language/*.txt klasörünü de ~/.local/share/idm-linux/app/language altına kopyala
    lang_src = project_root / "language"
    installed_lang = get_data_dir(create=True) / "app" / "language"
    if lang_src.exists() and installed_lang.resolve() != lang_src.resolve():
        if installed_lang.exists():
            shutil.rmtree(installed_lang)
        shutil.copytree(lang_src, installed_lang)

    local_bin = Path.home() / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    cli_bin = local_bin / "idm-linux"
    cli_script = f"""#!/bin/sh
export PYTHONPATH="{runtime_src}${{PYTHONPATH:+:$PYTHONPATH}}"
exec "{py_exe}" -m idm_linux.cli "$@"
"""
    cli_bin.write_text(cli_script, encoding="utf-8")
    cli_bin.chmod(0o755)

    hicolor_root = Path.home() / ".local" / "share" / "icons" / "hicolor"
    icon_dir = hicolor_root / "scalable" / "apps"
    icon_dir.mkdir(parents=True, exist_ok=True)
    panel_svg = icon_dir / "idm-linux-panel.svg"
    panel_svg.write_text(IDM_SVG_ICON, encoding="utf-8")
    # Eski idm-linux.svg varsa sil ki masaüstü ortamları gerçek PNG IDM ikonunu ezmesin
    (icon_dir / "idm-linux.svg").unlink(missing_ok=True)

    assets_dir = runtime_src / "idm_linux" / "assets"
    panel_icon_ref = str(panel_svg)
    for sz in (128, 64, 48, 32, 16):
        src_png = assets_dir / f"idm_icon_{sz}.png"
        if src_png.is_file():
            sz_dir = hicolor_root / f"{sz}x{sz}" / "apps"
            sz_dir.mkdir(parents=True, exist_ok=True)
            dst_panel = sz_dir / "idm-linux-panel.png"
            shutil.copy2(src_png, dst_panel)
            if sz == 128:
                panel_icon_ref = str(dst_panel)

    # Gerçek kurulan IDMan.exe dosyasından (veya orig_idman_*.png yedeğinden) %100 ORİJİNAL IDM ikonunu çıkar ve kur!
    idm_exe_now = cfg.find_idm_exe()
    extracted_pe_icons = extract_idman_official_icons(idm_exe_now) if idm_exe_now else {}
    orig_idm_icon_ref = panel_icon_ref
    for sz in (256, 128, 64, 48, 32, 16):
        sz_dir = hicolor_root / f"{sz}x{sz}" / "apps"
        sz_dir.mkdir(parents=True, exist_ok=True)
        png_bytes = extracted_pe_icons.get(sz)
        if not png_bytes:
            fallback_orig = assets_dir / f"orig_idman_{sz}.png"
            if fallback_orig.is_file():
                png_bytes = fallback_orig.read_bytes()
        if png_bytes:
            for icon_name in ("idman.png", "internet-download-manager.png", "idm-linux.png"):
                (sz_dir / icon_name).write_bytes(png_bytes)
            if sz in (256, 128):
                orig_idm_icon_ref = str(sz_dir / "idman.png")

    apps_dir = Path.home() / ".local" / "share" / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)

    # Wine'ın otomatik ürettiği çakışan .desktop kısayollarını temizle ki görev çubuğu doğrudan bizim orijinal ikonlu kaydı eşleştirsin
    wine_menu_dir = apps_dir / "wine" / "Programs" / "Internet Download Manager"
    if wine_menu_dir.exists():
        shutil.rmtree(wine_menu_dir, ignore_errors=True)

    idm_desktop_txt = f"""[Desktop Entry]
Type=Application
Name=Internet Download Manager
Comment=IDM (Wine + Linux Tarayıcı, Video & Torrent/Magnet Entegrasyonu)
Exec={cli_bin} open %u
Icon={orig_idm_icon_ref}
Terminal=false
Categories=Network;FileTransfer;
MimeType=application/x-bittorrent;x-scheme-handler/magnet;x-scheme-handler/ed2k;
StartupWMClass=idman.exe
"""
    # Wayland (kwin_wayland / mutter) app_id="idman.exe" birebir dosya adı eşleşmesi için gizli yardımcı kayıt
    wayland_idman_desktop_txt = f"""[Desktop Entry]
Type=Application
Name=Internet Download Manager
Exec={cli_bin} open %u
Icon={orig_idm_icon_ref}
Terminal=false
NoDisplay=true
StartupWMClass=idman.exe
"""
    panel_desktop_txt = f"""[Desktop Entry]
Type=Application
Name=IDM Linux Kontrol Paneli
GenericName=İndirme Yöneticisi Kontrol Merkezi
Comment=IDM Linux Köprüsü, Tarayıcı Entegrasyonu, Torrent/Magnet ve Video Bar Ayarları
Exec={cli_bin} panel
Icon={panel_icon_ref}
Terminal=false
Categories=Network;Settings;Utility;
StartupWMClass=idm-linux-panel
"""
    (apps_dir / "idm-linux.desktop").write_text(idm_desktop_txt, encoding="utf-8")
    (apps_dir / "idman.exe.desktop").write_text(wayland_idman_desktop_txt, encoding="utf-8")
    (apps_dir / "idm-linux-panel.desktop").write_text(panel_desktop_txt, encoding="utf-8")
    _refresh_desktop_and_icon_caches()

    if create_desktop_icons:
        desk = _find_desktop_dir()
        if desk:
            for fname, txt in (("idm-linux.desktop", idm_desktop_txt), ("idm-linux-panel.desktop", panel_desktop_txt)):
                df = desk / fname
                df.write_text(txt, encoding="utf-8")
                df.chmod(0o755)

    autostart_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    (autostart_dir / "idm-linux-daemon.desktop").write_text(
        f"""[Desktop Entry]
Type=Application
Name=IDM Linux Arka Plan Köprüsü
Comment=IDM Native Messaging, WebSocket ve Video Akış Servisi
Exec={cli_bin} daemon-run
Icon={panel_icon_ref}
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
""",
        encoding="utf-8",
    )

    systemd_user_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user"
    systemd_user_dir.mkdir(parents=True, exist_ok=True)
    service_file = systemd_user_dir / "idm-linux-daemon.service"
    service_file.write_text(
        f"""[Unit]
Description=IDM Linux Hybrid Integration & Video Stream Daemon
After=graphical-session.target network.target

[Service]
Type=simple
ExecStart={cli_bin} daemon-run
Restart=always
RestartSec=2
# v3.2.2 SON BELLEK KALKANI: daemon süreci fiziksel olarak 700MB'u asla aşamaz.
# Aşılsa bile yalnızca daemon yeniden başlatılır (Restart=always) — sistem genelinde
# 'Bellek Sıkıntısı' OOM katliamı İMKANSIZ hale gelir.
MemoryMax=700M
MemoryHigh=450M

[Install]
WantedBy=default.target
""",
        encoding="utf-8",
    )

    openrc_dir = get_data_dir() / "service"
    openrc_dir.mkdir(parents=True, exist_ok=True)
    openrc_script = openrc_dir / "idm-linux-openrc"
    openrc_script.write_text(
        f"""#!/sbin/openrc-run
name="idm-linux-daemon"
description="IDM Linux Hybrid Browser & Video Integration Daemon"
command="{cli_bin}"
command_args="daemon-run"
command_user="${{IDM_LINUX_USER:-{os.environ.get('USER', 'root')}}}"
command_background="yes"
pidfile="/tmp/idm-linux-openrc.pid"
""",
        encoding="utf-8",
    )
    openrc_script.chmod(0o755)

    wrapper = create_native_host_wrapper(py_exe, runtime_src)
    register_all_browsers(wrapper, crx_path=crx_path, chrom_ext_dir=chrom_ext_dir)

    # v3.2.2: YENİDEN BAŞLATMASIZ eklenti kurulumu — kurumsal policy force-install.
    # Linux Chromium ailesi policy dizinini CANLI izler: kurulum sırasında tarayıcı açık
    # olsa bile eklenti saniyeler içinde kendiliğinden yüklenir (restart YOK).
    try:
        from .browsers import register_gecko_force_install_policy, register_chromium_force_install_policy

        pol_res = register_chromium_force_install_policy(cfg.http_port)
        pol_g = register_gecko_force_install_policy(cfg.http_port)
        _pol_ok = [k for k, v in {**pol_res, **pol_g}.items() if str(v).startswith("ok")]
        print(f"[idm-linux] Policy force-install kaydı: {len(_pol_ok)} hedef (yeniden başlatmasız eklenti kurulumu).")
    except Exception as pol_exc:
        print(f"[idm-linux] Policy kaydı atlandı: {pol_exc}")

    service_alive = verify_and_start_bridge_service(cli_bin, cfg)
    return cli_bin, service_alive


def execute_install_pipeline(
    project_root: Path,
    chosen_prefix: Path,
    download_dir: Optional[Path] = None,
    existing_action: str = "fresh",
    existing_items: Optional[List[ExistingInstallation]] = None,
    custom_installer: Optional[Path] = None,
    skip_system_pkgs: bool = False,
    language: str = "tr",
    keep_wine_warm: bool = True,
    create_desktop_icons: bool = False,
    auto_open_browser: bool = True,
    prefer_gui_auth: bool = False,
    log_fn: Callable[[str], None] = print,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> InstallResult:
    """
    Hem Modern GUI Kurulum Sihirbazı hem de CLI tarafından kullanılan ortak,
    canlı ilerleme ve anlık log bildirimli kurulum hattı.
    """
    def _step(pct: int, title: str) -> None:
        if progress_cb:
            progress_cb(pct, title)

    _step(5, "Mevcut kurulum ve süreç kontrolleri yapılıyor...")
    items = existing_items if existing_items is not None else scan_existing_idm_installations()
    if items and existing_action == "clean":
        clean_existing_installations(items, remove_isolated_prefix=True, log_fn=log_fn)
        log_fn("  [✓] Eski kurulum kalıntıları temizlendi, sıfırdan kuruluma geçiliyor...")
    elif items and existing_action == "update":
        stop_all_idm_processes([e.prefix for e in items if e.prefix])
        log_fn("  [*] Mevcut kurulum korunarak güncelleme/onarım modunda devam ediliyor...")

    cfg = IdmLinuxConfig.load()
    cfg.ws_port = max(1024, cfg.ws_port) if cfg.ws_port >= 1024 else DEFAULT_WS_PORT
    cfg.http_port = max(1024, cfg.http_port) if cfg.http_port >= 1024 else DEFAULT_HTTP_PORT
    cfg.wine_prefix = str(chosen_prefix.expanduser().resolve())
    if download_dir is not None:
        cfg.download_dir = str(download_dir.expanduser().resolve())
    cfg.language = language
    cfg.keep_wine_warm = keep_wine_warm
    cfg.save()

    sys_info = detect_system()
    log_fn(f"  [*] Algılanan Dağıtım   : {sys_info.distro_name} (paket yöneticisi: {sys_info.pkg_manager})")
    log_fn(f"  [*] Init & Görüntü      : {sys_info.init_system} / {sys_info.display_server}")
    log_fn(f"  [*] Seçilen WINEPREFIX  : {cfg.wine_prefix}")
    log_fn(f"  [*] İndirilenler Dizini : {cfg.download_dir}")

    _step(15, "Sistem bağımlılıkları (Wine, FFmpeg, yt-dlp) kontrol ediliyor...")
    if not skip_system_pkgs:
        sys_info = install_system_dependencies(
            sys_info,
            install_optional_media=True,
            log_fn=log_fn,
            prefer_gui_auth=prefer_gui_auth,
        )

    _step(28, "Resmi IDM sitesinden en güncel kurulum paketi sorgulanıyor...")
    resolved_ver_label = "Latest"
    if custom_installer and custom_installer.exists():
        installer_exe = custom_installer.resolve()
        log_fn(f"  [✓] Yerel kurulum dosyası kullanılıyor: {installer_exe}")
    else:
        latest_url, latest_fname, resolved_ver_label = resolve_latest_official_idm_release(
            cfg.idm_installer_url,
            log_fn=log_fn,
        )
        cfg.idm_installer_url = latest_url
        installer_exe = download_idm_installer(
            latest_url,
            get_cache_dir(create=True) / latest_fname,
            log_fn=log_fn,
            dl_progress_cb=lambda p: _step(30 + int(p * 0.2), f"Resmi IDM {resolved_ver_label} indiriliyor (%{p})..."),
        )

    _step(55, "Wine ortamı (WINEPREFIX) doğrulanıyor...")
    if sys_info.wine_installed:
        initialize_wine_prefix(cfg, log_fn=log_fn)
    else:
        log_fn("  [!] Uyarı: Sistemde Wine bulunamadı, dosyalar yine de deterministik olarak çıkarılacak.")

    _step(68, f"IDM ({resolved_ver_label}) bileşenleri çıkarılıyor ve çökme korumaları uygulanıyor...")
    idm_exe = install_idm_binary(cfg, installer_exe, log_fn=log_fn)
    pe_ver = extract_pe_version_label(idm_exe)
    cfg.installed_idm_version = pe_ver or resolved_ver_label
    cfg.save()
    if pe_ver:
        log_fn(f"  [✓] Kurulan Orijinal IDM Sürümü doğrulandı: v{pe_ver}")

    _step(82, "Tarayıcı eklenti paketleri (CRX3, Unpacked ve XPI) derlenip doğrulanıyor...")
    crx_path, chrom_ext_dir, ff_xpi_path = deploy_browser_extensions(project_root)

    # v2.8.9: fontconfig listesini ÖNCEDEN ısıt -> GUI açılışında tkfont.families() beklemesi YOK
    try:
        import json as _json

        fc = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=20)
        if fc.returncode == 0:
            names = sorted({ln.strip() for ln in fc.stdout.splitlines() if ln.strip()})
            if names:
                from .config import get_cache_dir as _gcd

                cd = _gcd(create=True)
                cd.mkdir(parents=True, exist_ok=True)
                (cd / "font_families.json").write_text(_json.dumps(names), encoding="utf-8")
    except Exception:
        pass

    # v2.8.8: bayt-kodu ÖNDEN derle -> GUI ilk açılışta bile anında
    try:
        subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(resolve_src_base(project_root))],
            capture_output=True,
            timeout=180,
        )
    except Exception:
        pass

    log_fn(f"  [✓] Chromium eklentisi doğrulandı: {chrom_ext_dir}")
    log_fn(f"  [✓] İmzalı CRX3 paketi üretildi : {crx_path}")
    log_fn(f"  [✓] Firefox XPI paketi üretildi : {ff_xpi_path}")

    _step(86, "Firefox doğrulama duvarı çözülüyor (imzalı XPI sideload) & Wine klasör açma Linux FM'ye bağlanıyor...")
    ff_report = install_firefox_extensions_robust(
        gecko_home_roots(), ff_xpi_path, official_xpi_cache_path()
    )
    if ff_report["signed"]:
        log_fn(f"  [✓] İMZALI resmi IDM XPI'si {len(ff_report['signed'])} Gecko profiline sideload edildi (doğrulama hatası kökten çözüldü).")
    if ff_report["companion"]:
        log_fn(f"  [✓] Companion XPI (imzasız mod destekli derlemeler) {len(ff_report['companion'])} profile kuruldu.")
    configure_wine_native_folder_open(cfg, log_fn=log_fn)

    _step(90, "Masaüstü menü kısayolları, tarayıcı köprüleri ve arka plan servisi başlatılıyor...")
    cli_bin, service_alive = install_cli_and_desktop_entries(
        project_root,
        cfg,
        crx_path=crx_path,
        chrom_ext_dir=chrom_ext_dir,
        create_desktop_icons=create_desktop_icons,
    )
    cfg.save()

    if sys_info.wine_installed and cfg.keep_wine_warm:
        WineIdmSender(cfg).warm_up_idm()

    if service_alive:
        log_fn(f"  [✓] Canlı Köprü Öz-Testi BAŞARILI: HTTP 127.0.0.1:{cfg.http_port} & WS 127.0.0.1:{cfg.ws_port} AKTİF!")
    else:
        log_fn("  [!] Köprü servisi arka planda yanıt vermedi, 'idm-linux doctor' ile kontrol edebilirsiniz.")

    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    no_launch_env = os.environ.get("IDM_LINUX_NO_BROWSER_LAUNCH") == "1"
    if auto_open_browser and has_display and not no_launch_env:
        _step(96, "Varsayılan web tarayıcısı algılanıyor ve IDM eklentisi otomatik kuruluyor...")
        b_ok, b_msg = auto_install_and_open_default_browser(
            http_port=cfg.http_port,
            chrom_ext_dir=chrom_ext_dir,
            ff_xpi_path=ff_xpi_path,
            restart_if_running=False,
        )
        log_fn(f"  [{'✓' if b_ok else 'i'}] {b_msg}")

    _step(100, "Kurulum ve canlı doğrulama başarıyla tamamlandı!")
    return InstallResult(
        ok=True,
        wine_prefix=Path(cfg.wine_prefix),
        idm_exe=idm_exe,
        crx_path=crx_path,
        chrom_ext_dir=chrom_ext_dir,
        ff_xpi_path=ff_xpi_path,
        cli_bin=cli_bin,
        service_alive=service_alive,
    )


def run_full_install(
    project_root: Path,
    custom_installer: Optional[Path] = None,
    skip_system_pkgs: bool = False,
    explicit_prefix: Optional[Path] = None,
    assume_yes: bool = False,
    existing_mode: Optional[str] = None,
) -> int:
    print("\n======================================================================")
    print("  IDM-Linux v2.0 Evrensel Kurulum & Tarayıcı/Video Entegrasyon Aracı")
    print("======================================================================\n")

    existing = scan_existing_idm_installations()
    action = "fresh"
    if existing:
        action = prompt_existing_installation_action(
            existing,
            auto_mode=existing_mode or ("clean" if assume_yes and existing_mode is None else None),
        )
        if action == "abort":
            print("  [i] İşlem kullanıcı tarafından iptal edildi.")
            return 0
        if action == "uninstall":
            return run_uninstall(remove_wine_idm=True)

    chosen_pfx = choose_wine_prefix(explicit_prefix=explicit_prefix, assume_yes=assume_yes)

    res = execute_install_pipeline(
        project_root=project_root,
        chosen_prefix=chosen_pfx,
        existing_action=action,
        existing_items=existing,
        custom_installer=custom_installer,
        skip_system_pkgs=skip_system_pkgs,
        log_fn=print,
    )

    print("\n======================================================================")
    print("  [✓] KURULUM VE CANLI DOĞRULAMA BAŞARIYLA TAMAMLANDI!")
    print("======================================================================")
    print(f"  • Aktif Wine Ortamı    : {res.wine_prefix}")
    print(f"  • IDM Çalıştırılabilir : {res.idm_exe}")
    print(
        f"  • Köprü Servisi Durumu : "
        f"{'✓ AKTİF' if res.service_alive else '⚠ Manuel başlatın: idm-linux start'}"
    )
    print(f"  • Kontrol Paneli & CLI : {res.cli_bin} panel | {res.cli_bin} doctor | {res.cli_bin} status")
    print("----------------------------------------------------------------------")
    print("  Tarayıcı Eklenti Paketleriniz Hazır:")
    print(f"  • Chromium Klasör Modu : {res.chrom_ext_dir}")
    print(f"  • Chromium İmzalı CRX3 : {res.crx_path}")
    print(f"  • Firefox / LibreWolf  : {res.ff_xpi_path}")
    print("======================================================================\n")
    return 0


_IDM_REG_SECTION_MARKERS = (
    "software\\\\downloadmanager",
    "wow6432node\\\\downloadmanager",
    "internet download manager",
    "classes\\\\idman.",
    "classes\\\\cidmlinktransmitter",
    "ecf21eab-3aa8-4355-82be-f777990001dd",
    "ecf21ead-3aa8-4355-82be-f777990001dd",
    "4bd46aae-c51f-4bf7-8bc0-2e86e33d1873",
    "ac746233-e9d3-49cd-862f-068f7b7ccca4",
    "94d09862-1875-4fc9-b434-91cf25c840a1",
)

_IDM_REG_VALUE_PREFIXES = (
    '"idman"=',
    '"idmnetmon"=',
    '"idmnetmon64"=',
    '"idmnetmonaa"=',
    '"idmbrbtn"=',
    '"idmbrbtn64"=',
    '"idmbrbtnaa"=',
    '"idmwfp32"=',
    '"idmwfp64"=',
    '"idmtdi32"=',
    '"idmtdi64"=',
)


def scrub_wine_registry_file(reg_path: Path) -> int:
    """
    Wine'ın user.reg / system.reg metin dosyalarından IDM'ye ait tüm kayıt defteri
    bölümlerini ve otomatik başlatma / DLL override satırlarını cerrahi olarak temizler.
    Diğer hiçbir Wine programına dokunmaz!
    """
    if not reg_path.is_file():
        return 0
    try:
        raw = reg_path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError:
        return 0

    lines = raw.splitlines(keepends=True)
    out_lines: List[str] = []
    skip_section = False
    removed_count = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and "]" in stripped:
            hdr_low = stripped.lower()
            if any(m in hdr_low for m in _IDM_REG_SECTION_MARKERS):
                skip_section = True
                removed_count += 1
                continue
            else:
                skip_section = False

        if skip_section:
            continue

        low_line = stripped.lower()
        if any(low_line.startswith(vp) for vp in _IDM_REG_VALUE_PREFIXES) or (
            "internet download manager\\\\idman.exe" in low_line and low_line.startswith('"')
        ):
            removed_count += 1
            continue

        out_lines.append(line)

    if removed_count > 0:
        try:
            reg_path.write_text("".join(out_lines), encoding="utf-8", errors="surrogateescape")
        except OSError:
            pass
    return removed_count


def purge_wine_prefix_idm_artifacts(prefix: Path, log_fn: Callable[[str], None] = print) -> None:
    """Bir Wine prefix'i içindeki tüm IDM klasörlerini, AppData/Temp kalıntılarını ve Kayıt Defteri izlerini kazır."""
    if not prefix.is_dir():
        return

    # 1) Açık bir wineserver varsa bellekteki .reg önbelleğini diske yazıp kapatması için güvenli durdur
    # (Asla yeni bir 'wine reg delete' alt süreci başlatma: soğuk wineboot Wine-11.x üzerinde zaman aşımına uğrar!)
    ws = shutil.which("wineserver")
    if ws:
        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix)
        env["WINEDEBUG"] = "-all"
        _safe_run_quiet([ws, "-k"], env=env, timeout=3.5)

    # 2) Doğrudan .reg dosyalarını (ve .old yedeklerini) saf Python ile milisaniyede temizle (%100 garanti, %0 timeout!)
    total_reg_removed = 0
    for reg_name in ("user.reg", "user.reg.old", "system.reg", "system.reg.old", "userdef.reg"):
        total_reg_removed += scrub_wine_registry_file(prefix / reg_name)
    if total_reg_removed > 0:
        log_fn(f"  [✓] Wine Kayıt Defteri temizlendi ({prefix.name}: {total_reg_removed} IDM kaydı silindi).")

    # 3) drive_c altındaki tüm IDM uygulama, AppData, DMCache, DwnlData, Başlat Menüsü ve Temp klasörlerini sil
    drive_c = prefix / "drive_c"
    if not drive_c.is_dir():
        return

    fixed_dirs = [
        drive_c / "Program Files (x86)" / "Internet Download Manager",
        drive_c / "Program Files" / "Internet Download Manager",
        drive_c / "idm_bridge",
        drive_c / "ProgramData" / "IDM",
        drive_c / "ProgramData" / "DMCache",
        drive_c / "ProgramData" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Internet Download Manager",
    ]
    for d in fixed_dirs:
        if d.exists():
            log_fn(f"  [✓] Wine IDM klasörü kaldırıldı: {d}")
            shutil.rmtree(d, ignore_errors=True)

    users_root = drive_c / "users"
    if users_root.is_dir():
        for user_dir in users_root.iterdir():
            if not user_dir.is_dir():
                continue
            user_idm_targets = [
                user_dir / "AppData" / "Roaming" / "IDM",
                user_dir / "AppData" / "Roaming" / "DMCache",
                user_dir / "AppData" / "Local" / "IDM",
                user_dir / "AppData" / "LocalLow" / "IDM",
                user_dir / "Application Data" / "IDM",
                user_dir / "Application Data" / "DMCache",
                user_dir / "Local Settings" / "Application Data" / "IDM",
                user_dir / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Internet Download Manager",
                user_dir / "Start Menu" / "Programs" / "Internet Download Manager",
            ]
            for ut in user_idm_targets:
                if ut.exists():
                    log_fn(f"  [✓] Kullanıcı verisi kaldırıldı: {ut}")
                    shutil.rmtree(ut, ignore_errors=True)

            for pattern_parent, pat in (
                (user_dir / "Desktop", "*Internet Download Manager*"),
                (user_dir / "Temp", "IDM*"),
                (user_dir / "Temp", "idman_*"),
                (user_dir / "AppData" / "Local" / "Temp", "IDM*"),
                (user_dir / "AppData" / "Local" / "Temp", "idman_*"),
            ):
                if pattern_parent.is_dir():
                    for match in pattern_parent.glob(pat):
                        if match.is_dir():
                            shutil.rmtree(match, ignore_errors=True)
                        else:
                            match.unlink(missing_ok=True)

    win_temp = drive_c / "windows" / "temp"
    if win_temp.is_dir():
        for pat in ("IDM*", "idman_*"):
            for match in win_temp.glob(pat):
                if match.is_dir():
                    shutil.rmtree(match, ignore_errors=True)
                else:
                    match.unlink(missing_ok=True)


def run_uninstall(
    remove_wine_idm: bool = True,
    log_fn: Callable[[str], None] = print,
) -> int:
    log_fn("  [*] IDM-Linux tam kaldırma (sıfır kalıntı) işlemi başlatılıyor...")

    # 1) Silmeden önce kayıtlı tüm Wine prefix yollarını topla
    target_prefixes: List[Path] = []
    seen_pfx = set()

    def _add_pfx(p: Optional[Path]) -> None:
        if not p:
            return
        try:
            rp = p.expanduser().resolve()
        except OSError:
            return
        if rp not in seen_pfx and rp.exists():
            seen_pfx.add(rp)
            target_prefixes.append(rp)

    cfg_file = get_config_dir(create=False) / "config.json"
    if cfg_file.exists():
        try:
            cfg_now = IdmLinuxConfig.load(create_if_missing=False)
            _add_pfx(Path(cfg_now.wine_prefix))
        except Exception:
            pass

    for p in discover_wine_prefixes():
        _add_pfx(p)
    for item in scan_existing_idm_installations():
        _add_pfx(item.prefix)

    # 2) systemd servisi devre dışı bırak ve tüm arka plan daemon / Wine IDM süreçlerini kesin sonlandır
    _safe_run_quiet(["systemctl", "--user", "disable", "--now", "idm-linux-daemon.service"], timeout=4.0)
    pid_file = get_cache_dir(create=False) / "daemon.pid"
    if pid_file.is_file():
        try:
            dpid = int(pid_file.read_text(encoding="utf-8").strip())
            if dpid != os.getpid():
                os.kill(dpid, 15)
        except Exception:
            pass

    stop_all_idm_processes(target_prefixes)
    # Kendi sürecimiz dışındaki tüm daemon süreçlerini de temizle
    _safe_run_quiet(["pkill", "-9", "-f", "idm_linux.cli daemon-run"], timeout=2.5)
    _safe_run_quiet(["pkill", "-9", "-f", "idm_linux.native_host"], timeout=2.5)
    time.sleep(0.25)

    # 3) Açık tüm log dosyası tutucularını kapat ve yeni log yazımını kilitle (klasörler geri oluşmasın!)
    close_and_suppress_all_loggers()

    # 4) Wine içindeki tüm IDM klasörlerini, AppData verilerini ve Kayıt Defteri (Registry) kayıtlarını sil
    if remove_wine_idm:
        for pfx in target_prefixes:
            purge_wine_prefix_idm_artifacts(pfx, log_fn=log_fn)

    # 5) Tüm tarayıcı NativeMessaging, External Extensions ve *-flags.conf kayıtlarını temizle
    unregister_all_browsers()
    # v3.2.2: kurumsal force-install policy'lerini de temizle
    try:
        from .browsers import unregister_force_install_policies

        unregister_force_install_policies()
    except Exception:
        pass
    log_fn("  [✓] Tarayıcı köprü kayıtları ve eklenti bayrakları temizlendi.")

    # 6) Masaüstü ve Uygulama Menüsü (.desktop) kısayollarını (Wine'ın ürettikleri dahil!) temizle
    apps_dir = Path.home() / ".local" / "share" / "applications"
    if apps_dir.is_dir():
        for wf in list(apps_dir.rglob("*.desktop")):
            try:
                low_name = wf.name.lower()
                txt = wf.read_text(encoding="utf-8", errors="ignore").lower()
                if (
                    low_name in ("idm-linux.desktop", "idm-linux-panel.desktop", "idman.exe.desktop")
                    or "internet download manager" in low_name
                    or "idman.exe" in txt
                    or "idm-linux" in txt
                ):
                    wf.unlink(missing_ok=True)
            except OSError:
                pass

    desk = _find_desktop_dir()
    extra_desk: List[Path] = []
    if desk and desk.is_dir():
        for fn in (
            "idm-linux.desktop",
            "idm-linux-panel.desktop",
            "idman.exe.desktop",
            "Internet Download Manager.desktop",
            "Internet Download Manager.lnk",
        ):
            extra_desk.append(desk / fn)

    cfg_base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    hicolor_root = Path.home() / ".local" / "share" / "icons" / "hicolor"
    hicolor_icons = [
        hicolor_root / "scalable" / "apps" / "idm-linux.svg",
        hicolor_root / "scalable" / "apps" / "idm-linux-panel.svg",
    ]
    for sz in (256, 128, 64, 48, 32, 16):
        for ic_name in ("idman.png", "internet-download-manager.png", "idm-linux.png", "idm-linux-panel.png"):
            hicolor_icons.append(hicolor_root / f"{sz}x{sz}" / "apps" / ic_name)

    paths_to_remove = [
        Path.home() / ".local" / "bin" / "idm-linux",
        Path.home() / ".local" / "bin" / "idm-native-host",
        apps_dir / "wine" / "Programs" / "Internet Download Manager",
        cfg_base / "autostart" / "idm-linux-daemon.desktop",
        cfg_base / "systemd" / "user" / "idm-linux-daemon.service",
        get_data_dir(create=False),
        get_config_dir(create=False),
        get_cache_dir(create=False),
    ] + hicolor_icons + extra_desk

    for p in paths_to_remove:
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists() or p.is_symlink():
                p.unlink(missing_ok=True)
        except OSError:
            pass

    # /tmp altındaki geçici HLS fifo / pid dosyalarını da temizle
    tmp_root = Path("/tmp")
    if tmp_root.is_dir():
        for pat in ("idm_hls_fifo_*", "idm-linux-*"):
            for mp in tmp_root.glob(pat):
                try:
                    if mp.is_dir():
                        shutil.rmtree(mp, ignore_errors=True)
                    else:
                        mp.unlink(missing_ok=True)
                except OSError:
                    pass

    # Masaüstü veritabanını, simge önbelleğini ve systemd önbelleğini yenile
    _refresh_desktop_and_icon_caches()
    _safe_run_quiet(["systemctl", "--user", "daemon-reload"], timeout=3.5)
    _safe_run_quiet(["systemctl", "--user", "reset-failed"], timeout=3.5)

    log_fn("  [✓] IDM ve IDM-Linux tüm dosyaları, klasörleri, logları ve kayıt defteri izleriyle tamamen kaldırıldı!")
    return 0


# ---------------------------------------------------------------------------
# v2.8.0 — Wine içinde "Klasörü Aç" -> Linux VARSAYILAN DOSYA YÖNETİCİSİ
# ---------------------------------------------------------------------------

def _reg_replace_section(reg_text: str, section: str, body: str) -> str:
    """user.reg içindeki bir bölümü yoksa ekler, varsa gövdesini değiştirir."""
    header = f"[{section}]"
    if header in reg_text:
        start = reg_text.index(header)
        end = reg_text.find("\n[", start + len(header))
        end = len(reg_text) if end == -1 else end + 1
        return reg_text[:start] + header + "\n" + body.rstrip("\n") + "\n\n" + reg_text[end:]
    return reg_text.rstrip("\n") + "\n\n" + header + "\n" + body.rstrip("\n") + "\n"


def _reg_remove_section(reg_text: str, section: str) -> str:
    header = f"[{section}]"
    while header in reg_text:
        start = reg_text.index(header)
        end = reg_text.find("\n[", start + len(header))
        end = len(reg_text) if end == -1 else end + 1
        reg_text = reg_text[:start] + reg_text[end:]
    return reg_text


def configure_wine_native_folder_open(cfg: IdmLinuxConfig, log_fn: Callable[[str], None] = print) -> bool:
    """
    IDM'nin "Klasörü Aç" komutunun Wine'ın çirkin dosya yöneticisi yerine
    Linux'un varsayılan dosya yöneticisini (gio/xdg-open/dolphin/nautilus...) açmasını sağlar.
    wine reg.exe ÇALIŞTIRMAZ (timeout riski yok) — user.reg dosyasını doğrudan cerrahi olarak yamar.
    """
    from .browsers import detect_native_file_manager, get_data_dir as _gd

    fm_bin = detect_native_file_manager()
    if not fm_bin:
        return False

    bin_dir = _gd(create=True) / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    wrapper = bin_dir / "idm-linux-open-folder"
    src_dir = Path(__file__).resolve().parent.parent
    wrapper.write_text(
        f"""#!/bin/sh
# IDM-Linux v2.8.0: Wine "Klasörü Aç" -> Linux varsayılan dosya yöneticisi
export PYTHONPATH="{src_dir}${{PYTHONPATH:+:$PYTHONPATH}}"
export PYTHONDONTWRITEBYTECODE=1
exec "{sys.executable}" -m idm_linux.cli open-folder-native "$@"
""",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    win_cmd = "/bin/sh " + str(wrapper).replace("/", "\\") + ' \"%1\"'
    # Wine registry'de Z: üzerinden doğrudan unix yol da kabul edilir; en güvenlisi winepath biçimi:
    win_cmd = f'/bin/sh Z:{str(wrapper).replace("/", chr(92))} \"%1\"'

    user_reg = Path(cfg.wine_prefix).expanduser() / "user.reg"
    if not user_reg.exists():
        log_fn("  [i] Wine prefix user.reg henüz yok — klasör yönlendirmesi ilk başlatmada yazılacak.")
        return False

    text = user_reg.read_text(encoding="utf-8", errors="ignore")
    for cls in ("folder", "Directory", "Drive"):
        text = _reg_remove_section(text, f"Software\\Classes\\{cls}\\shell\\open\\ddeexec")
        text = _reg_remove_section(text, f"Software\\Classes\\{cls}\\shell\\open\\ddeexec\\topic")
        text = _reg_replace_section(
            text,
            f"Software\\Classes\\{cls}\\shell\\open\\command",
            f'@="{win_cmd}"\n',
        )
    text = _reg_replace_section(
        text,
        "Software\\Wine\\WineBrowser",
        '"Browsers"="xdg-open"\n"Mailers"="xdg-open"\n',
    )
    user_reg.write_text(text, encoding="utf-8")
    log_fn(f"  [✓] Wine 'Klasörü Aç' komutu Linux dosya yöneticisine ({Path(fm_bin).name}) bağlandı.")
    return True
