from __future__ import annotations

import json
import logging
import pathlib
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List

from . import __idm_download_url__, __version__
from .i18n import SUPPORTED_LANGUAGES, detect_system_language

# Resmi Tarayıcı Eklenti Kimlikleri
OFFICIAL_CHROME_EXT_ID = "ngpampappnmepgilojfohadhhmbhlaek"
OFFICIAL_EDGE_EXT_ID = "llbjbkhnmlidjebalopleeepgdfgcpec"
OFFICIAL_OPERA_EXT_ID = "jmolcgpienlcieaajfkkdamlngancncm"
OFFICIAL_FIREFOX_EXT_ID = "mozilla_cc3@internetdownloadmanager.com"

# CRX3 RSA-2048 Anahtar Çifti ile İmzalanmış Sabit Hibrit Chromium Eklenti Kimliği
COMPANION_CHROME_EXT_ID = "hdhillpmjhoiinmcdfleihbeghnnlkob"
LEGACY_COMPANION_CHROME_EXT_ID = "ajnikimlnoclnfehoheaegmkinlkfbpg"
COMPANION_CHROME_PUBKEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtN1RWXPjuZnlI6AAeBHEK/TnhdtD"
    "Oxrsczc/IXAYxNH1aSiAxZpvQdjlmll7YLbdSTreImslKsaK2oADKCarIqXtsHTAIFJmafTU"
    "cIgeDl4IYg+DimQQcUsg1Rq6ITjHZVZYUNquCqh2BxKeHjspZGqqoJoy/LY3q8X4ycNTgpGs"
    "0nY7dfn4k+ytenlkKuihNb2fF5z7CCEleuYTiov4xaOoauFx8o+KVCQWI+67gUvprrwwyuBC"
    "hhpoejm5g7qygmSWd1EZ5+/sHhXo6P95e+RIVFfV1sHES6MyVbzcblPLUSKJuwPXLv9i2IJX"
    "El1toniKDjMbwGEGVHW2W9F6SwIDAQAB"
)
COMPANION_FIREFOX_EXT_ID = "idm-linux-companion@idmlinux.local"

NATIVE_HOST_NAME = "com.tonec.idm"
COMPANION_HOST_NAME = "com.idmlinux.companion"

DEFAULT_WS_PORT = 17801
DEFAULT_HTTP_PORT = 17802
LEGACY_IDM_WS_PORT = 1001

DEFAULT_EXTENSIONS: List[str] = [
    "3GP", "7Z", "AAC", "ACE", "AIF", "APK", "APPIMAGE", "ARJ", "ASF", "AVI",
    "BIN", "BZ2", "DEB", "DMG", "DOC", "DOCX", "EXE", "F4V", "FLAC", "FLV",
    "GZ", "IMG", "ISO", "LZH", "M4A", "M4V", "MKV", "MOV", "MP3", "MP4",
    "MPA", "MPE", "MPEG", "MPG", "MSI", "MSU", "OGG", "OGV", "OPUS", "PDF",
    "PLJ", "PPS", "PPT", "PPTX", "QT", "RAR", "RM", "RMVB", "RPM", "SEA",
    "SIT", "SITX", "TAR", "TBZ2", "TGZ", "TIF", "TIFF", "TORRENT", "TS",
    "VOB", "WAV", "WEBM", "WEBM", "WMA", "WMV", "XLS", "XLSX", "XZ", "Z", "ZIP", "ZST",
]
# Yinelenen varsa temizle
DEFAULT_EXTENSIONS = sorted(set(DEFAULT_EXTENSIONS))

_REGISTERED_LOGGERS: List[logging.Logger] = []
_LOGGING_SUPPRESSED: bool = False


def detect_xdg_downloads_dir() -> Path:
    """Kullanıcının gerçek XDG İndirilenler klasörünü (ör. ~/İndirilenler veya ~/Downloads) bulur."""
    home = Path.home()
    env_dir = os.environ.get("XDG_DOWNLOAD_DIR")
    if env_dir:
        p = Path(os.path.expandvars(env_dir)).expanduser()
        if p.exists():
            return p

    user_dirs = home / ".config" / "user-dirs.dirs"
    if user_dirs.exists():
        try:
            content = user_dirs.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'^XDG_DOWNLOAD_DIR="([^"]+)"', content, re.MULTILINE)
            if m:
                raw = m.group(1).replace("$HOME", str(home))
                p = Path(raw).expanduser()
                if p.exists():
                    return p
        except OSError:
            pass

    try:
        res = subprocess.run(
            ["xdg-user-dir", "DOWNLOAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            p = Path(res.stdout.strip())
            if p.exists():
                return p
    except (OSError, subprocess.SubprocessError):
        pass

    for candidate in (home / "İndirilenler", home / "Downloads"):
        if candidate.exists():
            return candidate

    return home / "Downloads"


def get_data_dir(create: bool = False) -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "idm-linux"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def get_config_dir(create: bool = False) -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "idm-linux"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def get_cache_dir(create: bool = False) -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    d = base / "idm-linux"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def detect_default_wine_prefix() -> str:
    """
    Sistemde halihazırda ~/.wine (veya $WINEPREFIX) mevcutsa onu varsayılan olarak seçer;
    yoksa ~/.local/share/idm-linux/prefix döndürür (salt-okuma sırasında klasör oluşturmaz!).
    """
    env_pfx = os.environ.get("WINEPREFIX", "").strip()
    if env_pfx:
        p = Path(env_pfx).expanduser()
        if (p / "drive_c").exists() or (p / "system.reg").exists():
            return str(p.resolve())

    default_home_wine = Path.home() / ".wine"
    if (default_home_wine / "drive_c").exists() or (default_home_wine / "system.reg").exists():
        return str(default_home_wine.resolve())

    return str(get_data_dir(create=False) / "prefix")


@dataclass
class IdmLinuxConfig:
    version: str = __version__
    idm_installer_url: str = __idm_download_url__
    installed_idm_version: str = ""
    wine_prefix: str = field(default_factory=detect_default_wine_prefix)
    download_dir: str = field(default_factory=lambda: str(detect_xdg_downloads_dir()))
    ws_port: int = DEFAULT_WS_PORT
    http_port: int = DEFAULT_HTTP_PORT
    capture_downloads: bool = True
    video_bar_enabled: bool = True
    # v3.2.0: abyss.to desteği varsayılan KAPALI (kullanıcı isteği — GUI'de 'ABYSS PASİF'
    # görünür; kod + EVET ile anında canlı açılır, ayrıca Kaydet'e basmak gerekmez)
    abyss_enabled: bool = False
    clipboard_monitor: bool = False
    silent_mode: bool = False
    language: str = field(default_factory=detect_system_language)
    dpi_scale: int = 0
    max_connections: int = 24
    keep_wine_warm: bool = True
    stream_via_idm: bool = True
    # v3.10.1: IDM'de localhost köprüsü yerine dosyanın GERÇEK bağlantısı gösterilsin
    # (kullanıcı isteği). Tarayıcı barından gelen düz dosya linkleri doğrudan IDM'ye
    # verilir; başarısız olursa kopma-diriltme relay'i otomatik devreye girer.
    prefer_real_urls: bool = True
    excluded_domains: List[str] = field(default_factory=list)
    file_extensions: List[str] = field(default_factory=lambda: list(DEFAULT_EXTENSIONS))

    @property
    def config_path(self) -> Path:
        return get_config_dir(create=False) / "config.json"

    @classmethod
    def load(cls, create_if_missing: bool = False) -> "IdmLinuxConfig":
        cfg_file = get_config_dir(create=False) / "config.json"
        if cfg_file.exists():
            try:
                raw: Dict = json.loads(cfg_file.read_text(encoding="utf-8"))
                valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
                filtered = {k: v for k, v in raw.items() if k in valid_keys}
                inst = cls(**filtered)
                migrated = False
                if inst.ws_port < 1024:
                    inst.ws_port = DEFAULT_WS_PORT
                    migrated = True
                if inst.http_port < 1024:
                    inst.http_port = DEFAULT_HTTP_PORT
                    migrated = True
                if inst.language not in SUPPORTED_LANGUAGES:
                    inst.language = detect_system_language()
                    migrated = True
                if inst.version != __version__:
                    inst.version = __version__
                    migrated = True
                if migrated:
                    inst.save()
                return inst
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        cfg = cls()
        if create_if_missing:
            cfg.save()
        return cfg

    def save(self) -> None:
        global _LOGGING_SUPPRESSED
        _LOGGING_SUPPRESSED = False
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def extension_regex(self) -> str:
        exts = [re.escape(e.strip().upper()) for e in self.file_extensions if e.strip()]
        if not exts:
            exts = DEFAULT_EXTENSIONS
        return "(?:" + "|".join(exts) + ")"

    def idm_exe_candidates(self) -> List[Path]:
        pfx = Path(self.wine_prefix) / "drive_c"
        return [
            pfx / "Program Files (x86)" / "Internet Download Manager" / "IDMan.exe",
            pfx / "Program Files" / "Internet Download Manager" / "IDMan.exe",
        ]

    def find_idm_exe(self) -> Path | None:
        for c in self.idm_exe_candidates():
            if c.exists():
                return c
        return None

    def detect_installed_idm_version(self) -> str:
        """Kurulu IDMan.exe dosyasının PE başlığından gerçek sürümünü (ör. '6.43 Build 16') okur."""
        exe = self.find_idm_exe()
        if exe is not None:
            try:
                from .pe_icon_extractor import extract_pe_version_label
                ver = extract_pe_version_label(exe)
                if ver:
                    return ver
            except Exception:
                pass
        return self.installed_idm_version or ""


class _LazyFileHandler(logging.Handler):
    # v2.9.3 KATI LOG ROTASYONU: sınırsız büyüyen daemon.log = RAM/disk patlaması
    MAX_BYTES = 2 * 1024 * 1024

    def _rotate_if_big(self) -> None:
        try:
            path = self._log_path()
            if path.is_file() and path.stat().st_size > self.MAX_BYTES:
                if self._inner is not None:
                    try:
                        self._inner.close()
                    except Exception:
                        pass
                    self._inner = None
                bak = path.with_suffix(path.suffix + ".1")
                try:
                    bak.unlink(missing_ok=True)
                    path.rename(bak)
                except OSError:
                    pass
        except Exception:
            pass

    """
    Modül import edildiğinde (ör. uninstall veya GUI açılışı) boş yere ~/.cache/idm-linux/logs
    klasörü oluşturmaz; yalnızca gerçekten bir log satırı yazıldığında ve sistem kaldırılmamışsa yazar!
    """

    def __init__(self, log_filename: str) -> None:
        super().__init__()
        self.log_filename = log_filename
        self._inner: logging.FileHandler | None = None

    def _log_path(self) -> pathlib.Path:
        return get_cache_dir(create=False) / "logs" / self.log_filename

    def emit(self, record: logging.LogRecord) -> None:
        if _LOGGING_SUPPRESSED:
            return
        try:
            self._rotate_if_big()
            if self._inner is None:
                log_dir = get_cache_dir(create=True) / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                fh = logging.FileHandler(log_dir / self.log_filename, encoding="utf-8")
                # v2.9.3: dosya boyutunu sınırla (OOM-kill panzehiri)
                if self.formatter:
                    fh.setFormatter(self.formatter)
                self._inner = fh
            self._inner.emit(record)
        except Exception:
            pass

    def close(self) -> None:
        if self._inner is not None:
            try:
                self._inner.close()
            except Exception:
                pass
            self._inner = None
        super().close()


def close_and_suppress_all_loggers() -> None:
    """Kaldırma (uninstall) sırasında açık tüm log dosyalarını kapatır ve yeniden oluşturulmasını engeller."""
    global _LOGGING_SUPPRESSED
    _LOGGING_SUPPRESSED = True
    for lg in _REGISTERED_LOGGERS:
        for h in list(lg.handlers):
            try:
                h.close()
            except Exception:
                pass
            lg.removeHandler(h)
        lg.addHandler(logging.NullHandler())


def setup_logger(name: str, log_filename: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    lh = _LazyFileHandler(log_filename)
    lh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(lh)
    _REGISTERED_LOGGERS.append(logger)
    return logger


# ---------------------------------------------------------------------------
# v2.9.4: ABYSS.TO etkinleştirme kodu — kaynakta düz metin YOK (6 katmanlı kodlama)
# ---------------------------------------------------------------------------
_AB_TARGET = "e1c2c6e7c194f7f4f294eff7c6ced594"


def _ab_transform(code: str) -> str:
    import base64 as _b64

    raw = (code or "").strip().encode("utf-8")
    a = _b64.b64encode(raw)
    b = bytes(c ^ 0x5A for c in a)
    c = _b64.b64encode(b)[::-1]
    d = bytes(c ^ 0x33 for c in c)
    e = _b64.b64encode(d)
    f = bytes(c ^ 0xA5 for c in e)
    return f.hex()


def abyss_code_ok(code: str) -> bool:
    try:
        return _ab_transform(code) == _AB_TARGET
    except Exception:
        return False
