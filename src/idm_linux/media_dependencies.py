"""Installer-owned media dependency detection and idempotent yt-dlp setup.

No browser sandbox flag, account data or shell startup files are changed here.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

from .config import get_data_dir, get_cache_dir


@dataclass(frozen=True)
class JsRuntime:
    name: str
    path: str
    version: str

    @property
    def label(self) -> str:
        return f"{self.name} {self.version}"


# Match the minimums of the shipped/current yt-dlp JS challenge providers.
_MINIMUMS = {'deno': (2, 3, 0), 'node': (22, 0, 0), 'bun': (1, 2, 11)}
_START = '# BEGIN IDM-LINUX MANAGED JS RUNTIME'
_END = '# END IDM-LINUX MANAGED JS RUNTIME'


@lru_cache(maxsize=24)
def _probe_runtime(name: str, path: str, mtime_ns: int, size: int) -> Optional[JsRuntime]:
    try:
        result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=3, check=False)
        if result.returncode:
            return None
        first = (result.stdout or '').splitlines()[0]
        match = re.search(r'\b(?:v)?(\d+)\.(\d+)\.(\d+)', first)
        if not match or tuple(map(int, match.groups())) < _MINIMUMS[name]:
            return None
        return JsRuntime(name, path, '.'.join(match.groups()))
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def find_js_runtime() -> Optional[JsRuntime]:
    candidates = [('deno', str(get_data_dir() / 'bin' / 'deno'))]
    candidates += [(name, shutil.which(binary)) for name, binary in [('deno', 'deno'), ('node', 'node'), ('node', 'nodejs'), ('bun', 'bun')]]
    seen = set()
    for name, value in candidates:
        if not value or value in seen:
            continue
        seen.add(value)
        path = Path(value)
        try:
            if not path.is_file() or not os.access(path, os.X_OK):
                continue
            stat = path.stat()
            runtime = _probe_runtime(name, str(path), stat.st_mtime_ns, stat.st_size)
            if runtime:
                return runtime
        except OSError:
            continue
    return None


@lru_cache(maxsize=8)
def _probe_ffmpeg(path: str, mtime_ns: int, size: int) -> bool:
    try:
        result = subprocess.run([path, '-version'], capture_output=True, text=True, timeout=3, check=False)
        return result.returncode == 0 and (result.stdout or '').startswith('ffmpeg version')
    except (OSError, subprocess.SubprocessError):
        return False


def working_ffmpeg() -> Optional[str]:
    value = shutil.which('ffmpeg')
    if value:
        try:
            stat = Path(value).stat()
            if _probe_ffmpeg(value, stat.st_mtime_ns, stat.st_size):
                return value
        except OSError:
            pass
    return None


def runtime_config_path() -> Path:
    # yt-dlp loads a portable config beside its standalone binary first. Keep
    # the normal app setup private instead of changing a user's global options.
    private = get_data_dir() / 'bin' / 'yt-dlp'
    if private.is_file() and os.access(private, os.X_OK):
        return private.parent / 'yt-dlp.conf'
    # A system/pip binary needs user configuration, never /usr/bin/yt-dlp.conf.
    xdg = Path(os.environ.get('XDG_CONFIG_HOME') or (Path.home() / '.config'))
    choices = [xdg / 'yt-dlp.conf', xdg / 'yt-dlp' / 'config', xdg / 'yt-dlp' / 'config.txt', Path.home() / 'yt-dlp.conf', Path.home() / 'yt-dlp.conf.txt', Path.home() / '.yt-dlp' / 'config', Path.home() / '.yt-dlp' / 'config.txt']
    return next((p for p in choices if p.is_file()), choices[1])


def runtime_is_configured(runtime: Optional[JsRuntime]) -> bool:
    if not runtime:
        return False
    try:
        text = runtime_config_path().read_text(encoding='utf-8')
        block = f"{_START}\n--js-runtimes {shlex.quote(runtime.name + ':' + runtime.path)}\n{_END}"
        return block in text
    except (OSError, UnicodeError):
        return False


def configure_ytdlp_runtime(runtime: JsRuntime, log_fn: Callable[[str], None] = print) -> bool:
    """Replace only our block; retain all unrelated config and one private backup."""
    path = runtime_config_path()
    temp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError('Sembolik bağlantılı ayar dosyası otomatik değiştirilmedi.')
        old = path.read_text(encoding='utf-8') if path.exists() else ''
        block = f"{_START}\n--js-runtimes {shlex.quote(runtime.name + ':' + runtime.path)}\n{_END}"
        if runtime_is_configured(runtime):
            log_fn(f'  [✓] yt-dlp JavaScript ayarı hazır: {runtime.label}')
            return True
        if _START in old and _END not in old:
            raise ValueError('Eksik/bozuk yönetilen JS bloğu; mevcut dosya korunuyor.')
        pattern = re.compile(re.escape(_START) + r'.*?' + re.escape(_END), re.S)
        clean = pattern.sub('', old).rstrip('\n')
        new = (clean + '\n\n' if clean else '') + block + '\n'
        backup = path.with_name(path.name + '.idm-linux.before')
        if path.exists() and not backup.exists():
            with backup.open('x', encoding='utf-8') as f:
                f.write(old)
            backup.chmod(0o600)
        with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.idm-js-', delete=False, encoding='utf-8') as f:
            f.write(new)
            temp_name = f.name
        Path(temp_name).chmod(0o600)
        os.replace(temp_name, path)
        log_fn(f'  [✓] yt-dlp JavaScript ortamı otomatik yapılandırıldı: {runtime.label}')
        return runtime_is_configured(runtime)
    except (OSError, UnicodeError, ValueError) as exc:
        log_fn(f'  [!] yt-dlp JavaScript ayarı yazılamadı: {exc}')
        return False
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def install_private_deno(log_fn: Callable[[str], None] = print) -> Optional[JsRuntime]:
    """Fallback for distributions shipping an obsolete Node: verified official ZIP.

    Do not run curl|sh, edit PATH, or install unverified downloaded executables.
    """
    machine = platform.machine().lower()
    arch = {'x86_64': 'x86_64', 'amd64': 'x86_64', 'aarch64': 'aarch64', 'arm64': 'aarch64'}.get(machine)
    if not arch or platform.system() != 'Linux' or platform.libc_ver()[0] == 'musl':
        log_fn('  [!] Bu mimari/libc için otomatik özel Deno kurulumu desteklenmiyor.')
        return None
    tmp_zip = tmp_binary = None
    try:
        asset_name = f'deno-{arch}-unknown-linux-gnu.zip'
        request = urllib.request.Request('https://api.github.com/repos/denoland/deno/releases/latest', headers={'User-Agent': 'IDM-Linux-media-setup', 'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(request, timeout=25) as response:
            release = json.loads(response.read(4 * 1024 * 1024))
        asset = next(a for a in release.get('assets', []) if a.get('name') == asset_name)
        digest = asset.get('digest') or ''
        if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
            raise ValueError('Deno dağıtımının SHA-256 doğrulama bilgisi yok.')
        url = asset['browser_download_url']
        if not url.startswith('https://github.com/denoland/deno/releases/download/'):
            raise ValueError('Beklenmeyen Deno dağıtım adresi.')
        cache = get_cache_dir(create=True)
        hasher = hashlib.sha256()
        deadline = time.monotonic() + 180
        with tempfile.NamedTemporaryFile(dir=cache, suffix='.zip', delete=False) as target:
            tmp_zip = target.name
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'IDM-Linux-media-setup'}), timeout=60) as response:
                size = 0
                while True:
                    if time.monotonic() > deadline:
                        raise ValueError('Deno indirme zaman sınırı aşıldı.')
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 128 * 1024 * 1024:
                        raise ValueError('Deno arşiv boyutu güvenlik sınırını aştı.')
                    hasher.update(chunk)
                    target.write(chunk)
        if hasher.hexdigest().lower() != digest.split(':', 1)[1].lower():
            raise ValueError('Deno SHA-256 eşleşmedi; dosya çalıştırılmadı.')
        folder = get_data_dir() / 'bin'
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp_zip) as archive:
            info = archive.getinfo('deno')
            if not 0 < info.file_size <= 256 * 1024 * 1024:
                raise ValueError('Deno çalıştırılabilir dosya boyutu geçersiz.')
            with tempfile.NamedTemporaryFile(dir=folder, prefix='.deno-', delete=False) as target:
                tmp_binary = target.name
                with archive.open(info) as source:
                    shutil.copyfileobj(source, target, 1024 * 1024)
        path = Path(tmp_binary)
        path.chmod(0o755)
        stat = path.stat()
        if not _probe_runtime('deno', str(path), stat.st_mtime_ns, stat.st_size):
            raise ValueError('İndirilen Deno desteklenen sürümde çalışmadı.')
        os.replace(path, folder / 'deno')
        _probe_runtime.cache_clear()
        log_fn('  [✓] Resmi Deno SHA-256 ile doğrulanıp uygulamaya özel kuruldu.')
        return find_js_runtime()
    except (OSError, ValueError, StopIteration, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        log_fn(f'  [!] JavaScript ortamı otomatik tamamlanamadı: {exc}')
        return None
    finally:
        for path in (tmp_zip, tmp_binary):
            if path:
                Path(path).unlink(missing_ok=True)


def ensure_media_dependencies(*, allow_install: bool = True, prefer_gui_auth: bool = False, log_fn: Callable[[str], None] = print, refresh_apt_index: bool = True) -> dict:
    from .distro import detect_pkg_manager, read_os_release, _run_priv, find_ytdlp, install_standalone_ytdlp
    runtime = find_js_runtime()
    ffmpeg = working_ffmpeg()
    missing = []
    if not ffmpeg:
        missing.append('ffmpeg')
    if not runtime:
        missing.append('nodejs')
    pm = detect_pkg_manager(read_os_release())
    if missing and allow_install:
        packages = [('ffmpeg-free' if pm == 'dnf' else 'media-video/ffmpeg' if pm == 'emerge' else 'ffmpeg') if p == 'ffmpeg' else ('net-libs/nodejs' if pm == 'emerge' else 'nodejs') for p in missing]
        commands = {'apt': ['apt-get', 'install', '-y'], 'pacman': ['pacman', '-S', '--needed', '--noconfirm'], 'dnf': ['dnf', 'install', '-y'], 'emerge': ['emerge', '--noreplace', '--ask=n'], 'zypper': ['zypper', '--non-interactive', 'install'], 'xbps': ['xbps-install', '-Sy'], 'apk': ['apk', 'add']}
        if pm in commands:
            log_fn('  [*] Eksik video bağımlılıkları otomatik tamamlanıyor: ' + ', '.join(missing))
            if pm == 'apt' and refresh_apt_index:
                _run_priv(['apt-get', 'update'], log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)
            _run_priv(commands[pm] + packages, log_fn=log_fn, prefer_gui_auth=prefer_gui_auth)
            _probe_runtime.cache_clear()
            _probe_ffmpeg.cache_clear()
        runtime = find_js_runtime()
        if not runtime:
            log_fn('  [*] Depodaki JS ortamı yok/eski; doğrulanmış uygulamaya özel Deno deneniyor...')
            runtime = install_private_deno(log_fn=log_fn)
        ffmpeg = working_ffmpeg()
    ytdlp = find_ytdlp()
    if not ytdlp and allow_install:
        install_standalone_ytdlp(log_fn=log_fn)
        ytdlp = find_ytdlp()
    configured = bool(runtime and ytdlp and configure_ytdlp_runtime(runtime, log_fn=log_fn))
    missing = ([] if ffmpeg else ['FFmpeg']) + ([] if ytdlp else ['yt-dlp']) + ([] if runtime else ['Deno ≥2.3 / Node ≥22 / Bun ≥1.2.11']) + ([] if configured or not runtime else ['yt-dlp JS yapılandırması'])
    ready = not missing
    log_fn('  [✓] Video bağımlılıkları doğrulandı: FFmpeg + yt-dlp + JavaScript.' if ready else '  [!] Video desteği hazır değil: ' + ', '.join(missing))
    return {'ready': ready, 'ffmpeg': ffmpeg, 'ytdlp': ytdlp, 'runtime': runtime, 'configured': configured, 'missing': missing}
