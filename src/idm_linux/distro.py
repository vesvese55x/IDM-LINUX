from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .config import get_data_dir
from .media_dependencies import find_js_runtime, runtime_is_configured, ensure_media_dependencies, working_ffmpeg


@dataclass
class SystemInfo:
    distro_id: str
    distro_name: str
    pkg_manager: str          # apt, pacman, dnf, emerge, zypper, xbps, apk, unknown
    init_system: str          # systemd, openrc, runit, xdg-only
    display_server: str       # wayland, x11, headless
    wine_installed: bool
    wine_version: str
    ffmpeg_installed: bool
    ytdlp_path: Optional[str]
    tkinter_available: bool
    aria2_installed: bool = False
    js_runtime: str = ""
    js_runtime_path: Optional[str] = None
    js_runtime_configured: bool = False


def read_os_release() -> Dict[str, str]:
    info: Dict[str, str] = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        p = Path(path)
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    info[k] = v.strip().strip('"').strip("'")
            break
    return info


def detect_pkg_manager(os_rel: Dict[str, str]) -> str:
    id_all = f"{os_rel.get('ID', '')} {os_rel.get('ID_LIKE', '')}".lower()
    checks = [
        ("apt-get", "apt"),
        ("pacman", "pacman"),
        ("dnf", "dnf"),
        ("emerge", "emerge"),
        ("zypper", "zypper"),
        ("xbps-install", "xbps"),
        ("apk", "apk"),
    ]
    # Önce ID eşleşmesine göre öncelik ver (ör. Gentoo'da başka binary varsa karışmasın)
    if "gentoo" in id_all and shutil.which("emerge"):
        return "emerge"
    if "arch" in id_all and shutil.which("pacman"):
        return "pacman"
    if ("debian" in id_all or "ubuntu" in id_all) and shutil.which("apt-get"):
        return "apt"
    if ("fedora" in id_all or "rhel" in id_all) and shutil.which("dnf"):
        return "dnf"
    if "suse" in id_all and shutil.which("zypper"):
        return "zypper"

    for binary, name in checks:
        if shutil.which(binary):
            return name
    return "unknown"


def detect_init_system() -> str:
    # systemd user session kontrolü
    if shutil.which("systemctl") and Path("/run/systemd/system").exists():
        return "systemd"
    if shutil.which("rc-status") or Path("/sbin/openrc-run").exists() or Path("/run/openrc").exists():
        return "openrc"
    if shutil.which("sv") and (Path("/run/runit").exists() or Path("/etc/runit").exists()):
        return "runit"
    return "xdg-only"


def detect_display_server() -> str:
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type in ("wayland", "x11"):
        return session_type
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "headless"


def _wine_ver_cache_file() -> Path:
    return get_data_dir() / "wine_version.cache"


def read_wine_version_cache() -> str:
    try:
        f = _wine_ver_cache_file()
        if f.exists():
            return f.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        pass
    return ""


def check_wine(quick: bool = False) -> Tuple[bool, str]:
    """quick=True ise ALT process ÇALIŞTIRMAZ (GUI açılışı asla Wine soğuk başlatmasını beklemez)."""
    wine_bin = shutil.which("wine")
    if not wine_bin:
        return False, ""
    if quick:
        return True, read_wine_version_cache()
    try:
        res = subprocess.run(
            [wine_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        ver = res.stdout.strip() or res.stderr.strip()
        ok = res.returncode == 0 and bool(ver)
        if ok:
            try:
                _wine_ver_cache_file().parent.mkdir(parents=True, exist_ok=True)
                _wine_ver_cache_file().write_text(ver, encoding="utf-8")
            except OSError:
                pass
        return ok, ver
    except (OSError, subprocess.SubprocessError):
        return False, ""


def find_ytdlp() -> Optional[str]:
    local_bin = get_data_dir() / "bin" / "yt-dlp"
    if local_bin.exists() and os.access(local_bin, os.X_OK):
        return str(local_bin)
    for extra in (Path.home() / ".local" / "share" / "idm-linux" / "bin" / "yt-dlp",
                  Path.home() / ".local" / "bin" / "yt-dlp"):
        try:
            if extra.is_file() and os.access(extra, os.X_OK) and extra.stat().st_size > 100_000:
                return str(extra)
        except OSError:
            pass
    sys_bin = shutil.which("yt-dlp")
    if sys_bin:
        return sys_bin
    # v2.9.10: daemon kısıtlı PATH ile başlasa bile pip --user / sistem kurulumlarını gör
    for cand in (
        os.path.expanduser("~/.local/bin/yt-dlp"),
        "/usr/local/bin/yt-dlp",
        os.path.join(os.path.dirname(sys.executable), "yt-dlp"),
    ):
        if os.path.exists(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def check_tkinter() -> bool:
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def detect_system(quick: bool = False) -> SystemInfo:
    os_rel = read_os_release()
    pkg = detect_pkg_manager(os_rel)
    wine_ok, wine_ver = check_wine(quick=quick)
    js = find_js_runtime()
    return SystemInfo(
        distro_id=os_rel.get("ID", "linux"),
        distro_name=os_rel.get("PRETTY_NAME", os_rel.get("NAME", "Linux")),
        pkg_manager=pkg,
        init_system=detect_init_system(),
        display_server=detect_display_server(),
        wine_installed=wine_ok,
        wine_version=wine_ver,
        ffmpeg_installed=working_ffmpeg() is not None,
        ytdlp_path=find_ytdlp(),
        tkinter_available=check_tkinter(),
        aria2_installed=shutil.which("aria2c") is not None,
        js_runtime=js.label if js else "",
        js_runtime_path=js.path if js else None,
        js_runtime_configured=runtime_is_configured(js),
    )


def get_priv_prefix(prefer_gui_auth: bool = False) -> List[str]:
    """Root yetkisi gerektiğinde uygun komutu (pkexec / sudo / doas) seçer."""
    if os.geteuid() == 0:
        return []
    # Eğer terminal (TTY) yoksa veya grafik yetki penceresi istendiyse önce pkexec dene
    if (prefer_gui_auth or not sys.stdin.isatty()) and shutil.which("pkexec"):
        return ["pkexec"]
    for tool in ("sudo", "doas", "pkexec"):
        if shutil.which(tool):
            return [tool]
    return []


def _run_priv(
    cmd: List[str],
    log_fn: Callable[[str], None] = print,
    prefer_gui_auth: bool = False,
) -> int:
    prefix = get_priv_prefix(prefer_gui_auth=prefer_gui_auth)
    if os.geteuid() != 0 and not prefix:
        log_fn("  [!] Root yetkisi için pkexec/sudo/doas bulunamadı. Lütfen komutu root olarak çalıştırın:")
        log_fn("      " + " ".join(cmd))
        return 1
    full_cmd = prefix + cmd
    log_fn(f"  -> Çalıştırılıyor: {' '.join(full_cmd)}")
    if log_fn is print:
        res = subprocess.run(full_cmd, check=False)
        return res.returncode

    proc = subprocess.Popen(
        full_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        stripped = line.rstrip()
        if stripped:
            log_fn(f"     {stripped}")
    return proc.wait()


def ensure_arch_multilib(
    log_fn: Callable[[str], None] = print,
    prefer_gui_auth: bool = False,
) -> None:
    """Arch tabanlı dağıtımlarda Wine 32-bit için [multilib] deposunu kontrol eder."""
    conf = Path("/etc/pacman.conf")
    if not conf.exists():
        return
    txt = conf.read_text(encoding="utf-8", errors="ignore")
    if re.search(r"^\s*\[multilib\]", txt, re.MULTILINE):
        return
    log_fn("  [*] Arch Linux [multilib] deposu kapalı algılandı, Wine için etkinleştiriliyor...")
    script = (
        "sed -i '/^#\\[multilib\\]/,/^#Include = \\/etc\\/pacman.d\\/mirrorlist/ s/^#//' /etc/pacman.conf "
        "&& pacman -Sy"
    )
    _run_priv(["sh", "-c", script], log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)


def install_system_dependencies(
    sys_info: Optional[SystemInfo] = None,
    install_optional_media: bool = True,
    log_fn: Callable[[str], None] = print,
    prefer_gui_auth: bool = False,
) -> SystemInfo:
    """
    Sistemde Wine veya yardımcı araçlar eksikse dağıtımın kendi paket yöneticisiyle
    (apt, pacman, dnf, emerge, zypper, xbps, apk) otomatik olarak kurar.
    """
    info = sys_info or detect_system()
    pm = info.pkg_manager

    apt_index_ready = False
    need_wine = not info.wine_installed
    need_tk = not info.tkinter_available
    need_ffmpeg = install_optional_media and not info.ffmpeg_installed
    need_aria2 = install_optional_media and not info.aria2_installed
    need_streamlink = install_optional_media and shutil.which("streamlink") is None
    need_curl = shutil.which("curl") is None

    if not (need_wine or need_tk or need_ffmpeg or need_aria2 or need_streamlink or need_curl):
        log_fn(f"  [✓] Sistem bağımlılıkları tam (Wine: {info.wine_version}).")
    else:
        log_fn(f"  [*] Eksik sistem paketleri {info.distro_name} ({pm}) üzerinden tamamlanıyor...")
        if pm == "apt":
            if need_wine:
                _run_priv(["dpkg", "--add-architecture", "i386"], log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)
            apt_index_ready = _run_priv(["apt-get", "update"], log_fn=log_fn, prefer_gui_auth=prefer_gui_auth) == 0
            pkgs: List[str] = []
            if need_wine:
                pkgs.extend(["wine", "wine32", "wine64"])
            if need_tk:
                pkgs.append("python3-tk")
            if need_ffmpeg:
                pkgs.append("ffmpeg")
            if need_aria2:
                pkgs.append("aria2")
                if need_streamlink:
                    pkgs.append("streamlink")
            if need_curl:
                pkgs.append("curl")
            if pkgs:
                rc = _run_priv(["apt-get", "install", "-y"] + pkgs, log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)
                if rc != 0 and need_wine:
                    fallback_pkgs = [p for p in pkgs if p not in ("wine32", "wine64")]
                    _run_priv(["apt-get", "install", "-y"] + fallback_pkgs, log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)

        elif pm == "pacman":
            if need_wine:
                ensure_arch_multilib(log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)
            pkgs = []
            if need_wine:
                pkgs.extend(["wine", "lib32-gnutls"])
            if need_tk:
                pkgs.append("tk")
            if need_ffmpeg:
                pkgs.append("ffmpeg")
            if need_aria2:
                pkgs.append("aria2")
                if need_streamlink:
                    pkgs.append("streamlink")
            if need_curl:
                pkgs.append("curl")
            if install_optional_media and not info.ytdlp_path:
                pkgs.append("yt-dlp")
            if pkgs:
                _run_priv(["pacman", "-S", "--needed", "--noconfirm"] + pkgs, log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)

        elif pm == "dnf":
            pkgs = []
            if need_wine:
                pkgs.append("wine")
            if need_tk:
                pkgs.append("python3-tkinter")
            if need_ffmpeg:
                pkgs.append("ffmpeg-free")
            if need_aria2:
                pkgs.append("aria2")
                if need_streamlink:
                    pkgs.append("streamlink")
            if need_curl:
                pkgs.append("curl")
            if install_optional_media and not info.ytdlp_path:
                pkgs.append("yt-dlp")
            if pkgs:
                _run_priv(["dnf", "install", "-y"] + pkgs, log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)

        elif pm == "emerge":
            pkgs = []
            if need_wine:
                log_fn("  [i] Gentoo algılandı: virtual/wine (32-bit abi_x86_32 desteğiyle) kuruluyor...")
                pkgs.append("virtual/wine")
            if need_ffmpeg:
                pkgs.append("media-video/ffmpeg")
            if need_aria2:
                pkgs.append("net-misc/aria2")
                if need_streamlink:
                    pkgs.append("net-misc/streamlink")
            if need_curl:
                pkgs.append("net-misc/curl")
            if install_optional_media and not info.ytdlp_path:
                pkgs.append("net-misc/yt-dlp")
            if pkgs:
                _run_priv(["emerge", "--noreplace", "--ask=n"] + pkgs, log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)
            if need_tk:
                log_fn(
                    "  [i] Gentoo Notu: Masaüstü Kontrol Paneli (GUI) için dev-lang/python paketinde "
                    "USE='tk' bayrağının açık olduğundan emin olun."
                )

        elif pm == "zypper":
            pkgs = []
            if need_wine:
                pkgs.append("wine")
            if need_tk:
                pkgs.append("python3-tk")
            if need_ffmpeg:
                pkgs.append("ffmpeg")
            if need_aria2:
                pkgs.append("aria2")
                if need_streamlink:
                    pkgs.append("streamlink")
            if need_curl:
                pkgs.append("curl")
            if pkgs:
                _run_priv(["zypper", "--non-interactive", "install"] + pkgs, log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)

        elif pm == "xbps":
            if need_wine:
                _run_priv(["xbps-install", "-Sy", "void-repo-multilib"], log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)
            pkgs = []
            if need_wine:
                pkgs.extend(["wine", "wine-32bit"])
            if need_tk:
                pkgs.append("python3-tkinter")
            if need_ffmpeg:
                pkgs.append("ffmpeg")
            if need_aria2:
                pkgs.append("aria2")
                if need_streamlink:
                    pkgs.append("streamlink")
            if need_curl:
                pkgs.append("curl")
            if pkgs:
                _run_priv(["xbps-install", "-Sy"] + pkgs, log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)

        elif pm == "apk":
            pkgs = []
            if need_wine:
                pkgs.append("wine")
            if need_tk:
                pkgs.append("py3-tkinter")
            if need_ffmpeg:
                pkgs.append("ffmpeg")
            if need_aria2:
                pkgs.append("aria2")
                if need_streamlink:
                    pkgs.append("streamlink")
            if need_curl:
                pkgs.append("curl")
            if pkgs:
                _run_priv(["apk", "add"] + pkgs, log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)
        else:
            log_fn(
                "  [!] Paket yöneticisi otomatik tanınamadı. Lütfen 'wine', 'ffmpeg' ve 'python3' "
                "paketlerinin kurulu olduğundan emin olun."
            )

    if install_optional_media:
        ensure_media_dependencies(allow_install=True, prefer_gui_auth=prefer_gui_auth,
                                  log_fn=log_fn, refresh_apt_index=not apt_index_ready)

    return detect_system()


def install_standalone_ytdlp(log_fn: Callable[[str], None] = print) -> Optional[Path]:
    """Dağıtım deposunda güncel yt-dlp yoksa ~/.local/share/idm-linux/bin/yt-dlp olarak indirir."""
    bin_dir = get_data_dir() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / "yt-dlp"
    url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
    log_fn("  [*] Video siteleri (HLS/DASH/YouTube) için güncel yt-dlp motoru indiriliyor...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "idm-linux/2.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if len(data) > 100_000:
            target.write_bytes(data)
            target.chmod(0o755)
            log_fn(f"  [✓] yt-dlp kuruldu: {target}")
            return target
    except Exception as exc:
        log_fn(f"  [!] yt-dlp indirilemedi (isteğe bağlı): {exc}")
    return None


_SL_INSTALL_TRIED = False


def ensure_streamlink(log_fn: Callable[[str], None] = print) -> Optional[str]:
    """v2.8.2: DVR/Canlı kayıt motoru streamlink'i gerekiyorsa dağıtım yöneticisiyle tek paket kurar."""
    global _SL_INSTALL_TRIED
    bin_path = shutil.which("streamlink")
    if bin_path or _SL_INSTALL_TRIED:
        return bin_path
    _SL_INSTALL_TRIED = True
    pm = detect_system().pkg_manager
    cmds = {
        "apt": ["apt-get", "install", "-y", "streamlink"],
        "pacman": ["pacman", "-S", "--noconfirm", "streamlink"],
        "dnf": ["dnf", "install", "-y", "streamlink"],
        "yum": ["yum", "install", "-y", "streamlink"],
        "zypper": ["zypper", "--non-interactive", "install", "streamlink"],
        "emerge": ["emerge", "--quiet", "net-misc/streamlink"],
        "xbps": ["xbps-install", "-Sy", "streamlink"],
        "apk": ["apk", "add", "streamlink"],
    }
    cmd = cmds.get(pm)
    if not cmd:
        return None
    log_fn(f"  [*] Canlı/DVR kayıt motoru (streamlink) {pm} ile kuruluyor...")
    if pm == "apt":
        _run_priv(["apt-get", "update"], log_fn=log_fn)
    _run_priv(cmd, log_fn=log_fn)
    return shutil.which("streamlink")


def ensure_ytdlp(log_fn: Optional[Callable[[str], None]] = None, upgrade: bool = False) -> bool:
    """v2.9.6/2.9.9: yt-dlp yoksa kurar; upgrade=True ise sürümü tazeler (site ekstrakları)."""
    if find_ytdlp() and not upgrade:
        return True
    import shutil as _sh
    import subprocess as _sp

    py = _sh.which("python3") or sys.executable
    # v3.10.1: ÖNCE ROOT'SUZ TEK DOSYA BİNARY — pip/PEP-668 engellerini ve paket
    # yöneticisi yetkilerini tamamen atlar. Kullanıcı raporu: yeni sürümde YouTube
    # ve ok.ru hiç kaynak bulamıyordu; nedeni yt-dlp'nin kurulamamış olmasıydı.
    try:
        got = install_standalone_ytdlp(log_fn=lambda m: log_fn and log_fn(m))
        if got and find_ytdlp():
            return True
    except Exception:
        pass
    cmds = [
        [py, "-m", "pip", "install", "--user", "--quiet", "--upgrade", "yt-dlp"],
        # v2.9.10: PEP 668 (externally-managed) dağıtımlarında pip --user reddedilir -> kır ve kur
        [py, "-m", "pip", "install", "--user", "--quiet", "--upgrade", "--break-system-packages", "yt-dlp"],
        [py, "-m", "pip", "install", "--quiet", "--upgrade", "yt-dlp"],
    ]
    if _sh.which("pipx"):
        cmds.append([_sh.which("pipx"), "install", "--force", "yt-dlp"])
    for cmd in cmds:
        try:
            log_fn and log_fn("yt-dlp kuruluyor: " + " ".join(cmd[-2:]))
            r = _sp.run(cmd, capture_output=True, text=True, timeout=300, check=False)
            if r.returncode == 0 and find_ytdlp():
                log_fn and log_fn("yt-dlp kuruldu.")
                return True
        except Exception:
            continue
    return False
