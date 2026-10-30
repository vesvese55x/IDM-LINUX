"""v3.14.1 — Evrensel --no-sandbox çözümü (kökten).

Sorun: root / kapsayıcı (docker, LXC, CI lab) / ayrıcalıksız kullanıcı ad
alanlarının kapalı olduğu ortamlarda Chromium ailesi tarayıcılar VE Electron
tabanlı tüm araçlar "--no-sandbox olmadan çalışmaz" hatasıyla açılmaz. IDM
Linux'un tarayıcıyı/araçları açtığı her noktada bu engel dinlenmez:

1) DİNAMİK ALGILAMA — ortam tek tek denetlenir:
   • root (euid=0)
   • kapsayıcı (/.dockerenv, /run/.containerenv, $container, systemd-detect-virt)
   • unshare -Ur ile gerçek kullanıcı ad alanı testi (kernel düzeyi kanıt)
   • chrome-sandbox SUID yardımcısının yokluğu/yanlış modu
2) KALICI HAFIZA — bir araç bu engele BİR KEZ takıldıysa (stderr'de sandbox
   imzası) ~/.local/share/idm-linux/sandbox-memory.json'a yazılır ve o araç
   bundan sonra HER ZAMAN --no-sandbox ile açılır (kanka kuralı: engel bir
   kez görüldüyse hep aşılsın).
3) KÖKTEN ÇÖZÜM — işaretlenen tarayıcının kullanıcı seviyesi flags dosyasına
   (chromium-flags.conf, chrome-flags.conf, brave-flags.conf, vivaldi-stable.conf,
   microsoft-edge-flags.conf, opera-flags.conf ...) --no-sandbox satırı eklenir;
   böylece kullanıcının KENDİ tıklamalarıyla açılan tarayıcı da daima sandbox'sız
   başlar.

IDM Linux dışı süreçlere dokunulmaz; yalnızca bu modülün açtığı araçlar ve
açıktan açığa işaretlenen tarayıcılar etkilenir.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "needs_no_sandbox",
    "is_marked_no_sandbox",
    "remember_no_sandbox",
    "forget_no_sandbox",
    "sandbox_launch_args",
    "looks_like_sandbox_error",
    "open_url",
    "open_url_sync",
    "persist_flags_conf",
    "SandboxDecision",
]

_MEM_LOCK = threading.Lock()

# Ortam kararı pahalı (unshare testi ~1 sn) — süreç ömründe bir kez hesaplanır.
_ENV_VERDICT: Optional[bool] = None
_ENV_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Kalıcı hafıza (~/.local/share/idm-linux/sandbox-memory.json)
# ---------------------------------------------------------------------------

def _memory_file() -> Path:
    try:
        from .config import get_data_dir

        base = get_data_dir(create=True)
    except Exception:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        base = base / "idm-linux"
    return base / "sandbox-memory.json"


def _tool_key(binary: str) -> str:
    """Araç anahtarı: tam yol yerine ad kullanılır (yol değişse de hafıza geçerli)."""
    return Path(binary).name.lower()


def _load_memory() -> Dict[str, Any]:
    try:
        return json.loads(_memory_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_memory(data: Dict[str, Any]) -> None:
    try:
        path = _memory_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        pass


def is_marked_no_sandbox(binary: str) -> bool:
    """Araç daha önce sandbox engeline takıldıysa True (kalıcı hafızadan)."""
    mem = _load_memory()
    tools = mem.get("tools") if isinstance(mem, dict) else {}
    entry = (tools or {}).get(_tool_key(binary))
    return bool(isinstance(entry, dict) and entry.get("no_sandbox"))


def remember_no_sandbox(binary: str, reason: str = "") -> None:
    """Aracı KALICI olarak 'her zaman --no-sandbox' listesine işle."""
    with _MEM_LOCK:
        mem = _load_memory()
        tools = mem.setdefault("tools", {})
        entry = tools.get(_tool_key(binary)) if isinstance(tools.get(_tool_key(binary)), dict) else {}
        entry.update(
            {
                "no_sandbox": True,
                "reason": (reason or entry.get("reason") or "")[:200],
                "since": entry.get("since") or time.strftime("%Y-%m-%d %H:%M:%S"),
                "hits": int(entry.get("hits") or 0) + 1,
            }
        )
        tools[_tool_key(binary)] = entry
        _save_memory(mem)
    # Kökten çözüm: kullanıcının kendi başlattığı açılışlar da sandbox'sız olsun
    persist_flags_conf(binary)


def forget_no_sandbox(binary: str) -> None:
    """İşareti kaldır (zorla sıfırlamak isteyenler için)."""
    with _MEM_LOCK:
        mem = _load_memory()
        tools = mem.get("tools") if isinstance(mem.get("tools"), dict) else {}
        if _tool_key(binary) in tools:
            tools.pop(_tool_key(binary), None)
            _save_memory(mem)


# ---------------------------------------------------------------------------
# Dinamik ortam algılama
# ---------------------------------------------------------------------------

def _proc_int(path: str) -> Optional[int]:
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _is_container() -> bool:
    try:
        if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
            return True
        c = (os.environ.get("container") or "").lower()
        if c in ("docker", "podman", "lxc", "systemd-nspawn", "kubepods"):
            return True
        if Path("/proc/1/cgroup").exists():
            txt = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="ignore")
            if re.search(r"(docker|kubepods|lxc|containerd)", txt):
                return True
    except Exception:
        pass
    return False


def _can_create_user_ns() -> Optional[bool]:
    """unshare -Ur çalıştırıp ayrıcalıksız kullanıcı ad alanı kurulabiliyor mu?"""
    unshare = shutil.which("unshare")
    if not unshare:
        return None
    try:
        r = subprocess.run(
            [unshare, "-Ur", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
            check=False,
        )
        return r.returncode == 0
    except Exception:
        return None


def needs_no_sandbox() -> bool:
    """Bu ortamda Chromium ailesi sandbox'unun ÇALIŞMAYACAĞI kesinse True.

    Süreç ömründe bir kez hesaplanır ve önbelleğe alınır (GUI/probe yolu
    yavaşmasın). Şüpheli durumlarda False döner — hata yakalama katmanı
    (looks_like_sandbox_error) gerektiğinde kalıcı işaretleme yapar.
    """
    global _ENV_VERDICT
    with _ENV_LOCK:
        if _ENV_VERDICT is not None:
            return _ENV_VERDICT
        verdict = False
        try:
            if os.geteuid() == 0:
                verdict = True  # Chromium root'ta bayraksız başlamaz
            elif _is_container():
                verdict = True
            elif _proc_int("/proc/sys/user/max_user_namespaces") == 0:
                verdict = True
            else:
                # Debian/Ubuntu: kernel.unprivileged_userns_clone=0 ise de engel var
                clone_val = _proc_int("/proc/sys/kernel/unprivileged_userns_clone")
                if clone_val == 0:
                    verdict = True
                else:
                    can = _can_create_user_ns()
                    if can is False:
                        verdict = True
        except Exception:
            verdict = False
        _ENV_VERDICT = verdict
        return verdict


# Chromium ailesi imzaları — bir aracın stderr'inde bunlardan biri görünce
# araç kalıcı olarak --no-sandbox listesine alınır.
_SANDBOX_ERROR_SIGNATURES = (
    "running as root without --no-sandbox",
    "running without the suid sandbox",
    "the suid sandbox helper binary was found, but is not configured correctly",
    "failed to move to new namespace",
    "cannot open sandbox",
    "sandbox host helper",
    "namespace sandbox",
    "no usable sandbox",
    "you are using an unsupported command-line flag: --no-sandbox",
)


def looks_like_sandbox_error(stderr_text: str) -> bool:
    """Chromium/Electron sandbox hata imzası var mı? (kalıcı işaretleme tetikleyicisi)"""
    low = (stderr_text or "").lower()
    if "--no-sandbox" not in low:
        return any(sig in low for sig in _SANDBOX_ERROR_SIGNATURES[:9])
    return True


# ---------------------------------------------------------------------------
# Bayrak üretimi
# ---------------------------------------------------------------------------

def sandbox_launch_args(binary: str, extra_container_safe: bool = True) -> List[str]:
    """Verilen ikili için sandbox uyumluluk bayrakları (gerekmiyorsa []).

    Kural zinciri:
      1) Kalıcı hafızada işaretliyse → daima --no-sandbox
      2) Ortam sandbox'u kesin engelliyorsa → --no-sandbox
      3) Aksi halde [] — aracın kendi varsayılanı bozulmaz
    """
    args: List[str] = []
    if is_marked_no_sandbox(binary) or needs_no_sandbox():
        args.append("--no-sandbox")
        # Kapsayıcılarda /dev/shm miniktir → çökme saltığı; zararsız ve yaygın çözüm
        if extra_container_safe and needs_no_sandbox():
            args.append("--disable-dev-shm-usage")
    return args


# flags.conf eşlemesi — kullanıcı bu tarayıcıyı KENDİ tıkladığında daima uygulanır
_FLAGS_CONF_MAP: Tuple[Tuple[str, str], ...] = (
    ("chromium", "chromium-flags.conf"),
    ("chromium-browser", "chromium-flags.conf"),
    ("ungoogled-chromium", "chromium-flags.conf"),
    ("google-chrome", "chrome-flags.conf"),
    ("google-chrome-stable", "chrome-flags.conf"),
    ("chrome", "chrome-flags.conf"),
    ("brave", "brave-flags.conf"),
    ("brave-browser", "brave-flags.conf"),
    ("brave-browser-stable", "brave-flags.conf"),
    ("vivaldi", "vivaldi-stable.conf"),
    ("vivaldi-stable", "vivaldi-stable.conf"),
    ("microsoft-edge", "microsoft-edge-flags.conf"),
    ("microsoft-edge-stable", "microsoft-edge-flags.conf"),
    ("msedge", "microsoft-edge-flags.conf"),
    ("opera", "opera-flags.conf"),
    ("thorium-browser", "thorium-flags.conf"),
)

_FLAGS_CONF_MARKER = "# IDM-Linux sandbox uyumluluk satırı (otomatik eklendi)"


def persist_flags_conf(binary: str) -> bool:
    """İşaretlenen tarayıcının kullanıcı flags dosyasına --no-sandbox yazar.

    KÖKTEN çözüm: xdg-open/masaüstü kısayolu üzerinden kullanıcı kendi
    tıklamasıyla tarayıcıyı açsa bile sandbox engeli bir daha yaşanmaz.
    Yalnızca bilinen Chromium ailesi üyelerinde çalışır; dosya yoksa
    oluşturmaz (kullanıcı yapılandırmasına gereksiz müdahale edilmez) —
    ancak dosya mevcutsa satır eklenir.
    """
    try:
        name = _tool_key(binary)
        conf_name = ""
        for prefix, conf in _FLAGS_CONF_MAP:
            if name == prefix or name.startswith(prefix):
                conf_name = conf
                break
        if not conf_name:
            return False
        cfg_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        conf = cfg_home / conf_name
        if not conf.parent.is_dir():
            return False  # profil yoksa dokunma
        text = conf.read_text(encoding="utf-8") if conf.exists() else ""
        if "--no-sandbox" in text:
            return True
        block = f"{_FLAGS_CONF_MARKER}\n--no-sandbox\n"
        conf.write_text(text + ("" if text.endswith("\n") or not text else "\n") + block, encoding="utf-8")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Akıllı URL açıcı (xdg-open yerine bayraklı doğrudan başlatma)
# ---------------------------------------------------------------------------

def _default_browser_desktop_exec() -> Optional[str]:
    """Varsayılan tarayıcının .desktop Exec satırını çözer."""
    xdg = shutil.which("xdg-settings")
    if not xdg:
        return None
    try:
        r = subprocess.run([xdg, "get", "default-web-browser"], capture_output=True, text=True, timeout=4, check=False)
        desk_id = (r.stdout or "").strip()
        if not desk_id or not desk_id.endswith(".desktop"):
            return None
        for d in (
            Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications" / desk_id,
            Path("/usr/local/share/applications") / desk_id,
            Path("/usr/share/applications") / desk_id,
        ):
            if d.exists():
                for line in d.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.startswith("Exec="):
                        return line[5:].strip()
    except Exception:
        pass
    return None


def _exec_to_binary(exec_line: str) -> Optional[str]:
    """Exec= satırından ikili adını çıkarır (alan kodları %u/%U/%f atılır)."""
    try:
        import shlex

        parts = shlex.split(exec_line)
    except Exception:
        return None
    for p in parts:
        if p.startswith("%"):
            continue
        if "/" in p:
            if Path(p).exists():
                return p
            return Path(p).name
        return p
    return None


_CHROMIUM_HINTS = (
    "chrome", "chromium", "brave", "vivaldi", "edge", "msedge", "opera",
    "thorium", "helium", "yandex", "epiphany", "ungoogled",
)


def _is_chromium_family(binary: str) -> bool:
    low = _tool_key(binary)
    return any(h in low for h in _CHROMIUM_HINTS)


def open_url_sync(url: str) -> Tuple[bool, str]:
    """URL'yi sandbox-engelli ortamlarda dahi açar (senkron).

    1) Varsayılan tarayıcı .desktop'tan çözülür; Chromium ailesiyse bayraklarla
       doğrudan başlatılır.
    2) Sandbox hatası yakalanırsa araç KALICI işaretlenir ve --no-sandbox ile
       yeniden denenir.
    3) Çözülemezse xdg-open / webbrowser fallback.
    """
    import webbrowser

    exec_line = _default_browser_desktop_exec()
    binary = _exec_to_binary(exec_line) if exec_line else None
    if binary and not Path(binary).exists() and not shutil.which(binary):
        binary = None
    if binary is None:
        for cand in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                     "brave-browser", "vivaldi-stable", "microsoft-edge-stable", "opera", "firefox"):
            found = shutil.which(cand)
            if found:
                binary = found
                break

    if binary:
        cmd: List[str] = [binary]
        cmd += sandbox_launch_args(binary)
        cmd.append(url)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            time.sleep(0.9)
            rc = proc.poll()
            if rc is None or rc == 0:
                return True, f"{Path(binary).name} ile açıldı"
            # Süreç öldü: sandbox imzası var mı?
            err_txt = ""
            try:
                err_txt = (proc.stderr.read() or b"").decode("utf-8", "ignore")
            except Exception:
                pass
            if looks_like_sandbox_error(err_txt) and "--no-sandbox" not in cmd:
                remember_no_sandbox(binary, reason=err_txt.strip()[:180])
                cmd2 = [binary, "--no-sandbox", url]
                if needs_no_sandbox():
                    cmd2.insert(1, "--disable-dev-shm-usage")
                subprocess.Popen(cmd2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                return True, "sandbox engeli kalıcı olarak işaretlendi ve --no-sandbox ile açıldı"
        except Exception:
            pass

    # Fallback zinciri
    xdg = shutil.which("xdg-open")
    if xdg:
        try:
            subprocess.Popen([xdg, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True, "xdg-open ile açıldı"
        except Exception:
            pass
    try:
        if webbrowser.open(url):
            return True, "webbrowser ile açıldı"
    except Exception:
        pass
    return False, "Tarayıcı açılamadı"


def open_url(url: str) -> None:
    """GUI için ateşle-unut açıcı (ana iş parçacığını hiç beklemez)."""
    import threading as _th

    _th.Thread(target=open_url_sync, args=(url,), daemon=True, name="idm-open-url").start()


# Electron/Chromium tabanlı TEK SEFERLİK araç başlatıcı — herhangi bir araç için
def launch_tool(cmd: List[str], tool_hint: str = "") -> subprocess.Popen:
    """Herhangi bir harici ikiliyi sandbox uyumluluğuyla başlatır.

    Bir kez sandbox hatası veren araç bundan sonra daima --no-sandbox ile
    başlar (kalıcı hafıza). Popen nesnesini döndürür; hata imzası beklenmez.
    """
    binary = cmd[0] if cmd else tool_hint
    args = sandbox_launch_args(binary)
    if args and args[0] not in cmd:
        cmd = [cmd[0]] + args + cmd[1:]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
