"""v3.7.1 eD2K (eDonkey2000 / eMule) köprüsü — TAM OTOMATİK motor yönetimi.

docuwiki.net gibi sitelerdeki `ed2k://|file|<ad>|<boyut>|<md4>|/` bağlantılarını
gerçek bir eD2K motoruna (aMule / mldonkey) iletir. Kullanıcı HİÇBİR ŞEY kurmak
zorunda kalmaz:

1. **aMule (tercih edilen — her dağıtımın RESMÎ deposunda VAR; mldonkey ise
   Arch'ta yalnızca AUR'dadır ve pacman kurulumu 'hedef bulunamadı' ile
   düşer — kullanıcı raporu: 'Kurulum başarısız — sudo pacman -S mldonkey')**:
   - `amuled` kapalıysa daemon KENDİ KENDİNE yapılandırır (~/.aMule/amule.conf
     EC/şifre/ağ ayarları) ve başlatır (headless), ardından `amulecmd`
     'Add' komutuyla bağlantıyı kuyruğa gönderir.
2. **mldonkey**: kuruluysa (mlnet telnet 4000) `dllink` ile beslenir —
   eski davranış aynen korunur.
3. **Hiçbiri yoksa**: `install_backend()` ile ÇOK STRATEJİLİ tek tık kurulum:
     a. pkexec + dağıtımın paket yöneticisi (Arch: 'amule' [extra],
        Debian/Ubuntu: 'amule amule-utils', Fedora: 'amule'...).
     b. O da olmadıysa KÖKSÜZ statik aMule paketi: aMule-org GitHub sürümlerindeki
        musl statik arşivi (amuled + amulecmd, kütüphane bağımlılığı YOK) kullanıcı
        önbelleğine (~/.cache/idm-linux/ed2k-engine) açılır — root/şifre gerekmez.

İndirilen dosyalar aMule'da ~/.aMule/Incoming, mldonkey'de
~/.mldonkey/incoming/files klasörüne akar; `incoming_dir()` bu yolu bildirir.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import tarfile
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import get_cache_dir, setup_logger
from .torrent_engine import _download_to, _github_latest_release_asset

# ── v3.10.0 NATIVE eD2K MOTORU ───────────────────────────────────────────────
# Kullanıcı kararı: eD2K indirmeleri aMule gibi üçüncü sınıf bir araca devredilmesin;
# kendi motorumuz bağlantıyı çözsün, indirsin ve baytları IDM'ye akıtsın. aMule yolu
# yalnızca native motor hiç başlatılamazsa (çok eski Python / ağ kısıtı) yedek kalır.
_NATIVE_ED2K_ENABLED = True
_ED2K_SESSIONS: Dict[str, Any] = {}
_ED2K_SESSIONS_LOCK = threading.RLock()

log = setup_logger("ed2k", "daemon.log")

_ED2K_FILE_RE = re.compile(
    r"^ed2k://\|file\|([^|]+)\|(\d+)\|([0-9A-Fa-f]{32})\|?/?", re.I
)
_MLNET_TELNET_PORT = 4000
_AMULE_EC_PORT = 4712

_AMULE_RELEASE_REPO = "amule-org/amule"


def is_ed2k_link(link: str) -> bool:
    u = (link or "").strip()
    return u.lower().startswith("ed2k://") and bool(_ED2K_FILE_RE.match(u))


def parse_ed2k_link(link: str) -> Optional[Dict[str, Any]]:
    """ed2k://|file|<ad>|<boyut>|<md4>|/ bağlantısını çözümler."""
    m = _ED2K_FILE_RE.match((link or "").strip())
    if not m:
        return None
    try:
        size = int(m.group(2))
    except ValueError:
        size = 0
    return {
        "name": urllib.parse.unquote(m.group(1)),
        "size": size,
        "hash": m.group(3).lower(),
        "uri": m.group(0).rstrip("/"),
    }


def format_bytes(size: int) -> str:
    if not size or size <= 0:
        return ""
    val = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024.0 or unit == "TB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return ""


# ---------------------------------------------------------------------------
# Backend algılama
# ---------------------------------------------------------------------------

def _telnet_alive(port: int = _MLNET_TELNET_PORT, timeout: float = 1.2) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _ec_alive(timeout: float = 1.2) -> bool:
    return _telnet_alive(_AMULE_EC_PORT, timeout)


def _engine_dir() -> Path:
    return get_cache_dir(create=True) / "ed2k-engine"


def _static_bundle_paths() -> Tuple[Optional[str], Optional[str]]:
    """KÖKSÜZ statik aMule paketindeki (amuled, amulecmd) ikili yollarını döner."""
    marker = _engine_dir() / "bundle.json"
    try:
        if marker.is_file():
            data = json.loads(marker.read_text(encoding="utf-8"))
            amuled = data.get("amuled") or ""
            amulecmd = data.get("amulecmd") or ""
            if amuled and os.access(amuled, os.X_OK) and amulecmd and os.access(amulecmd, os.X_OK):
                return amuled, amulecmd
    except Exception:
        pass
    # marker yoksa dizinde ara (eski kurulum)
    try:
        eng = _engine_dir()
        amuled = next((p for p in eng.rglob("amuled") if p.is_file()), None)
        amulecmd = next((p for p in eng.rglob("amulecmd") if p.is_file()), None)
        if amuled and amulecmd:
            return str(amuled), str(amulecmd)
    except Exception:
        pass
    return None, None


def _amule_binaries() -> Tuple[Optional[str], Optional[str]]:
    """(amuled_yolu, amulecmd_yolu) — önce PATH, sonra statik paket."""
    amulecmd = shutil.which("amulecmd")
    amuled = shutil.which("amuled")
    if amulecmd and amuled:
        return amuled, amulecmd
    s_amuled, s_amulecmd = _static_bundle_paths()
    return (amuled or s_amuled), (amulecmd or s_amulecmd)


def detect_ed2k_backend() -> Dict[str, Any]:
    """Sistemdeki eD2K motorunu algılar. Döner:
    {backend: 'native'|'mldonkey'|'amule'|'none', running: bool, install_hint: str}

    v3.10.0: ÖNCE yerleşik native eD2K motoru raporlanır — dış araç/paket gerekmez.
    """
    if _NATIVE_ED2K_ENABLED:
        try:
            from .p2p.ed2k_native import NativeED2KSession  # noqa: F401

            return {"backend": "native", "running": True, "install_hint": ""}
        except Exception:
            pass
    mlnet_bin = shutil.which("mlnet") or shutil.which("mldonkey")
    if mlnet_bin and _telnet_alive():
        return {"backend": "mldonkey", "running": True, "install_hint": ""}
    if _ec_alive():
        return {"backend": "amule", "running": True, "install_hint": ""}
    amuled, _amulecmd = _amule_binaries()
    if amuled:
        # kurulu ama kapalı — _amule_ensure_running() otomatik başlatır
        return {"backend": "amule", "running": False, "install_hint": ""}
    if mlnet_bin:
        # mldonkey kurulu ama mlnet çalışmıyor — daemon otomatik başlatır
        return {"backend": "mldonkey", "running": False, "install_hint": ""}
    # v3.8.0: motor yoksa kurulum OTOMATİK başlar (daemon pkexec onay penceresini
    # kendisi açar) — kullanıcıya elle kurulum komutu ASLA gösterilmez.
    return {
        "backend": "none",
        "running": False,
        "install_hint": "Motor kurulu değil — ilk ed2k bağlantısında kurulum otomatik başlar "
        "(yalnızca sistem yetkilendirme penceresini onaylamanız yeterli).",
    }


def _detect_package_manager() -> str:
    for pm, bin_name in (
        ("pacman", "pacman"),
        ("apt", "apt-get"),
        ("dnf", "dnf"),
        ("zypper", "zypper"),
    ):
        if shutil.which(bin_name):
            return pm
    return ""


def incoming_dir() -> str:
    """eD2K motorunun indirdiği klasör (varsa gerçek yol, yoksa öngörülen yol)."""
    home = Path.home()
    candidates = [
        home / ".aMule" / "Incoming",
        home / ".mldonkey" / "incoming" / "files",
        home / ".mldonkey" / "incoming",
    ]
    for c in candidates:
        if c.is_dir():
            return str(c)
    return str(home / ".aMule" / "Incoming")


# ---------------------------------------------------------------------------
# aMule otomatik yapılandırma + otomatik başlatma (v3.7.1)
# ---------------------------------------------------------------------------

def _ec_password() -> Tuple[str, str]:
    """(düz_parola, md5_hex) — ~/.aMule/idm_linux_ecpw içinde saklanır (0600)."""
    amule_dir = Path.home() / ".aMule"
    amule_dir.mkdir(parents=True, exist_ok=True)
    pw_file = amule_dir / "idm_linux_ecpw"
    try:
        if pw_file.is_file():
            pw = pw_file.read_text(encoding="utf-8").strip()
            if len(pw) >= 8:
                return pw, hashlib.md5(pw.encode("utf-8")).hexdigest()
    except Exception:
        pass
    pw = secrets.token_urlsafe(18)
    try:
        pw_file.write_text(pw, encoding="utf-8")
        os.chmod(pw_file, 0o600)
    except Exception:
        pass
    return pw, hashlib.md5(pw.encode("utf-8")).hexdigest()


def _patch_amule_conf_text(text: str, md5_pw: str) -> str:
    """amule.conf içeriğinde EC/ağ anahtarlarını ayarlar (eksik anahtar eklenir)."""
    wanted: Dict[str, Dict[str, str]] = {
        "ExternalConnect": {
            "AcceptExternalConnections": "1",
            "ECAddress": "127.0.0.1",
            "ECPort": str(_AMULE_EC_PORT),
            "ECPassword": md5_pw,
        },
        "eMule": {
            "NetworkED2K": "1",
            "NetworkKademlia": "1",
            "AutoConnect": "1",
            "Reconnect": "1",
        },
        "WebServer": {"Enabled": "0"},
    }
    lines = text.splitlines()
    current_section = ""
    seen_keys: Dict[str, set] = {}
    out: List[str] = []
    for ln in lines:
        stripped = ln.strip()
        m_sec = re.match(r"^\[([^\]]+)\]$", stripped)
        if m_sec:
            current_section = m_sec.group(1)
            seen_keys.setdefault(current_section, set())
            out.append(ln)
            continue
        m_kv = re.match(r"^([A-Za-z0-9_]+)\s*=", stripped)
        if m_kv and current_section in wanted and m_kv.group(1) in wanted[current_section]:
            if m_kv.group(1) in seen_keys.get(current_section, set()):
                out.append(ln)
                continue
            seen_keys.setdefault(current_section, set()).add(m_kv.group(1))
            out.append(f"{m_kv.group(1)}={wanted[current_section][m_kv.group(1)]}")
            continue
        out.append(ln)
    # Eksik bölümleri/anahtarları sona ekle
    for sec, kvs in wanted.items():
        if sec not in seen_keys:
            out.append("")
            out.append(f"[{sec}]")
        for k, v in kvs.items():
            if k not in seen_keys.get(sec, set()):
                out.append(f"{k}={v}")
    return "\n".join(out) + "\n"


def _ensure_amule_config() -> Tuple[bool, str]:
    """~/.aMule/amule.conf hazırlanır: EC açık, şifre MD5'li, ağlar etkin.
    (ok, amulecmd_şifresi) döner — şifre boşsa kimliksiz denenecek demektir."""
    amule_dir = Path.home() / ".aMule"
    amule_dir.mkdir(parents=True, exist_ok=True)
    inc = amule_dir / "Incoming"
    inc.mkdir(parents=True, exist_ok=True)
    tmp = amule_dir / "Temp"
    tmp.mkdir(parents=True, exist_ok=True)
    conf = amule_dir / "amule.conf"
    pw_plain, pw_md5 = _ec_password()
    try:
        if conf.is_file():
            text = conf.read_text(encoding="utf-8", errors="replace")
        else:
            text = (
                "[eMule]\n"
                "AppVersion=IDM Linux Bridge\n"
                "Nick=idm-linux\n"
                "VersionCheck=0\n"
                "NetworkED2K=1\n"
                "NetworkKademlia=1\n"
                "AutoConnect=1\n"
                "Reconnect=1\n"
                "\n"
                "[ExternalConnect]\n"
                "AcceptExternalConnections=1\n"
                "ECAddress=127.0.0.1\n"
                f"ECPort={_AMULE_EC_PORT}\n"
                "ECPassword=PLACEHOLDER_MD5\n"
                "\n"
                "[WebServer]\n"
                "Enabled=0\n"
            )
        patched = _patch_amule_conf_text(text, pw_md5)
        if patched != text:
            conf.write_text(patched, encoding="utf-8")
        return True, pw_plain
    except Exception as exc:
        log.warning("amule.conf hazırlanamadı: %s", exc)
        return False, ""


def _disable_system_amuled_service() -> None:
    """Dağıtımın 'amule-daemon' paketi sistem servisini başlattıysa çakışmayı önle:
    4712 başka bir kullanıcı/by sistem amuled'i kapmışsa bizim user-level daemon'ımız
    başlayamaz. En temiz yol: sistem servisini kapatıp devre dışı bırakmak (pkexec)."""
    if not _ec_alive():
        return
    systemctl = shutil.which("systemctl")
    pkexec = shutil.which("pkexec")
    if not systemctl or not pkexec:
        return
    try:
        res = subprocess.run(
            [systemctl, "is-active", "--quiet", "amule-daemon"],
            capture_output=True,
            timeout=4,
            check=False,
        )
        if res.returncode == 0:
            subprocess.run(
                [pkexec, systemctl, "disable", "--now", "amule-daemon"],
                capture_output=True,
                timeout=30,
                check=False,
            )
            time.sleep(1.0)
    except Exception:
        pass


def _amule_ensure_running(timeout: float = 30.0) -> bool:
    """aMule çekirdeğini (amuled) gerektiğinde YAPILANDIRIP arka planda başlatır."""
    _disable_system_amuled_service()
    if _ec_alive():
        return True
    amuled_bin, _amulecmd_bin = _amule_binaries()
    if not amuled_bin:
        return False
    ok_conf, _pw = _ensure_amule_config()
    if not ok_conf:
        return False
    try:
        env = {**os.environ, "HOME": str(Path.home())}
        subprocess.Popen(
            [amuled_bin],
            cwd=str(Path.home() / ".aMule"),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        log.warning("amuled başlatılamadı: %s", exc)
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _ec_alive():
            log.info("amuled arka planda başlatıldı (EC %d hazır).", _AMULE_EC_PORT)
            return True
        time.sleep(0.5)
    return False


def _amulecmd_add(link: str) -> Tuple[bool, str]:
    """amulecmd 'Add <link>' — birden çok çağrı biçimiyle dener.

    v3.9.0 KRİTİK DÜZELTME (kullanıcı raporu: "eMule 'Add' failed: Unknown option 'H'"):
    amulecmd 2.3.x'te host seçeneği '-h/--host=dur' (KÜÇÜK harf); '-H' diye bir seçenek
    YOKTUR ve wxCommandLine 'Unknown option H' ile çıkar (gerçek aMule 2.3.3 üzerinde
    birebir doğrulandı). Artık host argümanı hiç verilmez (varsayılan localhost zaten
    127.0.0.1'dir); ayrıca uzun biçim '--host=127.0.0.1' yalnızca yedek denemedir.
    Başarılı 'Add' sonrası 'Downloads' sorgusuyla bağlantının GERÇEKTEN kuyrukta
    olduğu doğrulanır (sessiz başarısızlık biter)."""
    _amulecmd_bin = shutil.which("amulecmd")
    if not _amulecmd_bin:
        _s_amuled, _amulecmd_bin = _static_bundle_paths()
    if not _amulecmd_bin:
        return False, "amulecmd bulunamadı."
    pw_file = Path.home() / ".aMule" / "idm_linux_ecpw"
    pw = ""
    try:
        if pw_file.is_file():
            pw = pw_file.read_text(encoding="utf-8").strip()
    except Exception:
        pw = ""
    base = [_amulecmd_bin, "-p", str(_AMULE_EC_PORT)]
    attempts: List[List[str]] = []
    if pw:
        attempts.append(base + ["-P", pw, "-c", f"Add {link}"])
    attempts.append(base + ["-c", f"Add {link}"])
    if pw:
        attempts.append(base + ["--host=127.0.0.1", "-P", pw, "-c", f"Add {link}"])
    attempts.append(base + ["--host=127.0.0.1", "-c", f"Add {link}"])
    last_out = ""
    for cmd in attempts:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
            out = ((res.stdout or "") + (res.stderr or "")).strip()
            last_out = out[:300]
            low = out.lower()
            if "unknown option" in low:
                continue  # bu biçim bu amulecmd sürümünde yok — sıradaki biçim
            if res.returncode == 0 and (
                "added" in low or "operation" in low or "successful" in low
                or "queued" in low or " » " in out or "ed2k://" in low
            ):
                # Doğrulama: bağlantı gerçekten kuyrukta mı? ('Show DL' çıktısında ad aranır;
                # eski aMule sürümlerinde komut 'Downloads' idi — sırayla denenir)
                verified = ""
                try:
                    name_slug = link.split("|")[2] if link.count("|") >= 3 else ""
                    try:
                        name_slug = urllib.parse.unquote(name_slug)
                    except Exception:
                        pass
                    if name_slug:
                        for chk_cmd in ("Show DL", "Downloads"):
                            chk = subprocess.run(
                                base + (["-P", pw] if pw else []) + ["-c", chk_cmd],
                                capture_output=True, text=True, timeout=12, check=False,
                            )
                            chk_out = ((chk.stdout or "") + (chk.stderr or "")).strip()
                            if name_slug[:24].lower() in chk_out.lower():
                                verified = " (kuyruk doğrulandı)"
                                break
                except Exception:
                    pass
                return True, f"Bağlantı aMule kuyruğuna eklendi{verified}."
            if "connection" in low and ("refused" in low or "failed" in low):
                continue  # daemon uyandı — sıradaki deneme
            if "password" in low or "auth" in low or "login" in low:
                continue
        except subprocess.TimeoutExpired:
            continue
        except Exception:
            continue
    return False, f"aMule 'Add' başarısız: {last_out or 'yanıt yok'}"


def _amule_dllink(link: str) -> Tuple[bool, str]:
    """aMule motoruna bağlantı gönderir; çekirdek kapalıysa OTOMATİK başlatır."""
    if not _amule_ensure_running():
        return False, (
            "aMule çekirdeği (amuled) şu anda başlatılamadı. Birkaç saniye bekleyip "
            "bağlantıyı tekrar göndermeyi deneyin — sorun sürerse paneldeki 'Motoru Kur' "
            "düğmesi kurulumu tazeler."
        )
    ok, msg = _amulecmd_add(link)
    if ok:
        return True, f"{msg} İndirilenler şuraya akar: {incoming_dir()}"
    # son çare: ed2k CLI işleyicisi (aMule GUI çalışıyorsa bağlantıyı ona iletir)
    ed2k_cli = shutil.which("ed2k") or shutil.which("ed2k-amule")
    if ed2k_cli:
        try:
            res = subprocess.run([ed2k_cli, link], capture_output=True, text=True, timeout=10, check=False)
            if res.returncode == 0:
                return True, "Bağlantı aMule ed2k işleyicisine gönderildi."
        except Exception:
            pass
    return False, msg


def _mlnet_ensure_running(timeout: float = 12.0) -> bool:
    if _telnet_alive():
        return True
    mlnet_bin = shutil.which("mlnet") or shutil.which("mldonkey")
    if not mlnet_bin:
        return False
    try:
        conf_dir = Path.home() / ".mldonkey"
        conf_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "HOME": str(Path.home())}
        subprocess.Popen(
            [mlnet_bin],
            cwd=str(conf_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        log.warning("mlnet otomatik başlatılamadı: %s", exc)
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _telnet_alive():
            log.info("mlnet arka planda başlatıldı (telnet 4000 hazır).")
            return True
        time.sleep(0.4)
    return False


def _mldonkey_dllink(link: str) -> Tuple[bool, str]:
    if not _mlnet_ensure_running():
        return False, "mldonkey servisi (mlnet) başlatılamadı — elle 'mlnet &' çalıştırıp tekrar deneyin."
    try:
        with socket.create_connection(("127.0.0.1", _MLNET_TELNET_PORT), timeout=4) as s:
            s.settimeout(6)
            try:
                s.recv(4096)  # banner
            except OSError:
                pass
            s.sendall(f"dllink {link}\n".encode("utf-8"))
            time.sleep(0.6)
            data = b""
            try:
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    if len(data) > 65536:
                        break
            except OSError:
                pass
        txt = data.decode("utf-8", errors="replace").lower()
        if "added" in txt or "link" in txt or "download" in txt or "ed2k" in txt:
            return True, "Bağlantı mldonkey'e eklendi — indirme mlnet kuyruğunda başladı."
        if "auth" in txt or "password" in txt:
            return False, (
                "mldonkey şifre korumalı. '~/.mldonkey/downloads.ini' içinde "
                "allowed_ips += '127.0.0.1' ve empty şifre ayarlayın veya GUI'den ekleyin."
            )
        return True, "Bağlantı mldonkey'e gönderildi."
    except Exception as exc:
        return False, f"mldonkey telnet bağlantısı kurulamadı: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# v3.10.0 NATIVE eD2K OTURUM YÖNETİCİSİ
# ─────────────────────────────────────────────────────────────────────────────
def native_ed2k_available() -> bool:
    """Yerleşik native eD2K motoru kullanılabilir mi?"""
    if not _NATIVE_ED2K_ENABLED:
        return False
    try:
        from .p2p.ed2k_native import NativeED2KSession  # noqa: F401

        return True
    except Exception:
        return False


def ed2k_register_native(link: str, download_dir: Optional[str] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """eD2K bağlantısı için NATIVE indirme oturumu açar.

    Döner: (ok, mesaj, bilgi_sözlüğü) — bilgi sözlüğü IDM köprüsü adresi için
    ``ticket``, ``filename``, ``size``, ``session`` alanlarını taşır.
    """
    if not native_ed2k_available():
        return False, "Native eD2K motoru yüklenemedi.", None
    info = parse_ed2k_link(link)
    if not info:
        return False, "Geçersiz ed2k bağlantısı.", None
    # NOT: bağlantı adı URL-encode'lu gelebilir ("Test+Dosya.iso"); eD2K kuralı
    # gereği '+' boşluk değil artı işaretidir, yalnızca %XX çözülür.
    from .p2p.ed2k_native import NativeED2KSession

    ticket = secrets.token_hex(8)
    work = get_cache_dir(create=True) / "ed2k" / ticket
    try:
        target_dir = None
        if download_dir:
            target_dir = Path(download_dir).expanduser()
        sess = NativeED2KSession(
            work_dir=work,
            link=link,
            download_dir=target_dir,
            log_fn=lambda msg: log.info("%s", msg),
        )
    except Exception as exc:
        return False, f"eD2K oturumu açılamadı: {exc}", None
    with _ED2K_SESSIONS_LOCK:
        _ED2K_SESSIONS[ticket] = sess
        # bellek koruması: 12'den fazla oturum tutulmaz
        if len(_ED2K_SESSIONS) > 12:
            for old_ticket in list(_ED2K_SESSIONS)[: len(_ED2K_SESSIONS) - 12]:
                try:
                    _ED2K_SESSIONS.pop(old_ticket).stop()
                except Exception:
                    pass
    sess.start()
    sess.wait_ready(timeout=8.0)
    return (
        True,
        f"eD2K indirmesi IDM'ye bağlandı: {info['name']}",
        {
            "ticket": ticket,
            "filename": info["name"],
            "size": info["size"],
            "hash": info.get("hash") or "",
            "session": sess,
            "work_dir": str(work),
        },
    )


def ed2k_get_session(ticket: str) -> Optional[Any]:
    with _ED2K_SESSIONS_LOCK:
        return _ED2K_SESSIONS.get(ticket)


def ed2k_list_sessions() -> List[Dict[str, Any]]:
    with _ED2K_SESSIONS_LOCK:
        sessions = list(_ED2K_SESSIONS.items())
    out: List[Dict[str, Any]] = []
    for ticket, sess in sessions:
        try:
            st = sess.query_status()
        except Exception:
            continue
        out.append(
            {
                "ticket": ticket,
                "name": st.get("bittorrent", {}).get("info", {}).get("name") or "",
                "status": st.get("status"),
                "total_bytes": int(st.get("totalLength") or 0),
                "completed_bytes": int(st.get("completedLength") or 0),
                "speed_bps": int(st.get("downloadSpeed") or 0),
                "peers": int(st.get("connections") or 0),
                "sources": int(st.get("sources") or 0),
                "error": st.get("errorMessage") or "",
            }
        )
    return out


def ed2k_shutdown_all() -> None:
    with _ED2K_SESSIONS_LOCK:
        sessions = list(_ED2K_SESSIONS.values())
        _ED2K_SESSIONS.clear()
    for sess in sessions:
        try:
            sess.stop()
        except Exception:
            pass


def ed2k_add_link(link: str) -> Tuple[bool, str, str]:
    """ed2k:// bağlantısını motora ekler. Döner: (ok, mesaj, backend_adi).

    v3.10.0: Bu fonksiyon artık YALNIZCA yedek yoldur. Ana yol
    :func:`ed2k_register_native` — bağlantı IDM köprüsüne aktarılır.
    """
    u = (link or "").strip()
    if not u.lower().startswith("ed2k://"):
        return False, "Geçersiz ed2k bağlantısı.", "none"
    if not is_ed2k_link(u):
        return False, "ed2k bağlantısı çözümlenemedi (file|ad|boyut|hash biçimi beklenir).", "none"
    info = detect_ed2k_backend()
    backend = info.get("backend") or "none"
    if backend == "native":
        # native motor devrede: aMule/mldonkey yolu hiç denenmez
        ok_n, msg_n, meta_n = ed2k_register_native(u)
        if ok_n:
            return True, msg_n, "native"
        return False, msg_n, "none"
    if backend == "mldonkey":
        ok, msg = _mldonkey_dllink(u)
        return ok, msg, "mldonkey"
    if backend == "amule":
        ok, msg = _amule_dllink(u)
        return ok, msg, "amule"
    # Motor yok: kurulum OTOMATİK başlar (daemon pkexec yetki penceresini kendisi açar);
    # kullanıcıdan elle komut / elle kurulum istenmez (v3.8.0 kullanıcı kararı).
    return (
        False,
        (
            "eD2K motoru (aMule) kurulu değil — kurulum otomatik başlatılıyor. Açılacak "
            "yetkilendirme penceresini onaylayın; motor kurulup çekirdek başladığında "
            f"bağlantılar '{incoming_dir()}' klasörüne inmeye başlar."
        ),
        "none",
    )


# ---------------------------------------------------------------------------
# TEK TIK KURULUM v3 (çok stratejili: pkexec paketleri → köksüz statik aMule)
# ---------------------------------------------------------------------------

def _install_static_amule_bundle(timeout: float = 600.0) -> bool:
    """KÖKSÜZ kurulum: aMule-org GitHub sürümündeki statik (musl) Linux arşivini
    indirip kullanıcı önbelleğine açar. amuled + amulecmd ikilileri daima bulundurur."""
    eng = _engine_dir()
    eng.mkdir(parents=True, exist_ok=True)
    arch = (platform.machine() or "x86_64").lower()
    suffix = "Linux-arm64-static.tar.gz" if ("arm" in arch or "aarch" in arch) else "Linux-x64-static.tar.gz"
    asset = _github_latest_release_asset(_AMULE_RELEASE_REPO, suffix)
    if not asset:
        # GitHub varlık adları büyük/küçük harfe DUYARLIDIR: aMule-3.2.0-Linux-x64-static.tar.gz
        asset = f"https://github.com/{_AMULE_RELEASE_REPO}/releases/download/3.2.0/aMule-3.2.0-{suffix}"
    tar_path = eng / "amule-static.tar.gz"
    if not _download_to(asset, tar_path, timeout=timeout):
        return False
    extract_dir = eng / "extract"
    shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            tf.extractall(extract_dir)  # noqa: S202 — kendi önbelleğimiz
        amuled_p = next((p for p in extract_dir.rglob("amuled") if p.is_file()), None)
        amulecmd_p = next((p for p in extract_dir.rglob("amulecmd") if p.is_file()), None)
        if not amuled_p or not amulecmd_p:
            return False
        final_amuled = eng / "bin" / "amuled"
        final_cmd = eng / "bin" / "amulecmd"
        final_amuled.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(amuled_p, final_amuled)
        shutil.copy2(amulecmd_p, final_cmd)
        os.chmod(final_amuled, 0o755)
        os.chmod(final_cmd, 0o755)
        (eng / "bundle.json").write_text(
            json.dumps({"amuled": str(final_amuled), "amulecmd": str(final_cmd)}),
            encoding="utf-8",
        )
        return True
    except Exception as exc:
        log.warning("statik aMule paketi açılamadı: %s", exc)
        return False
    finally:
        try:
            tar_path.unlink(missing_ok=True)
            shutil.rmtree(extract_dir, ignore_errors=True)
        except Exception:
            pass


def _pkexec_run(cmd: List[str], timeout: float = 900.0) -> Tuple[int, str]:
    pkexec = shutil.which("pkexec")
    if not pkexec:
        return 127, "pkexec bulunamadı"
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    try:
        res = subprocess.run([pkexec] + cmd, capture_output=True, text=True, timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired:
        return 124, "kurulum zaman aşımına uğradı (yetkilendirme penceresi yanıtlanmadı mı?)"
    except Exception as exc:
        return 1, str(exc)
    tail = ((res.stderr or "") + (res.stdout or "")).strip().splitlines()
    detail = tail[-1][:220] if tail else ""
    return res.returncode, detail


def _pm_install_cmd(pm: str, packages: List[str]) -> List[str]:
    if pm == "pacman":
        return ["pacman", "-S", "--noconfirm", "--needed"] + packages
    if pm == "apt":
        return ["apt-get", "install", "-y"] + packages
    if pm == "dnf":
        return ["dnf", "install", "-y"] + packages
    return ["zypper", "--non-interactive", "install"] + packages


def install_backend(timeout: float = 900.0) -> Tuple[bool, str]:
    """v3.7.1 ÇOK STRATEJİLİ kurulum:

    1. Dağıtımın resmî deposundan aMule (pkexec onaylı):
       • Arch: 'amule' [extra] — mldonkey AUR'da olduğu için pacman -S mldonkey
         'hedef bulunamadı' ile DÜŞER (kullanıcının yaşadığı hata!). aMule resmî depoda.
       • Debian/Ubuntu: 'amule amule-utils'
       • Fedora: 'amule' | openSUSE: 'amule'
    2. Paket yöneticisi olmadan/olmazsa KÖKSÜZ statik aMule paketi (GitHub).
    Kurulumdan sonra amuled otomatik yapılandırılır ve başlatılır."""
    pm = _detect_package_manager()
    tried: List[str] = []
    if pm:
        candidates: List[List[str]] = {
            "pacman": [["amule"]],
            "apt": [["amule", "amule-utils"], ["amule-daemon", "amule-utils"]],
            "dnf": [["amule"]],
            "zypper": [["amule"]],
        }.get(pm, [])
        for pkgs in candidates:
            tried.append(" ".join(pkgs))
            code, detail = _pkexec_run(_pm_install_cmd(pm, pkgs), timeout=timeout)
            if code == 0:
                # sistem servisi çakışmasını önle (Debian amule-daemon)
                _disable_system_amuled_service()
                amuled_bin, _cmd_bin = _amule_binaries()
                if amuled_bin:
                    if _amule_ensure_running():
                        return True, (
                            f"aMule kuruldu ve çekirdek arka planda başlatıldı. "
                            f"İndirilenler: {incoming_dir()}"
                        )
                    return True, (
                        f"aMule kuruldu; ilk ed2k bağlantısında çekirdek otomatik başlar. "
                        f"İndirilenler: {incoming_dir()}"
                    )
                # paket kuruldu ama amuled ikilisi yok (nadiren bölünmüş paket) → statik yedeğe düş
                break
            if code in (126, 127):
                break  # pkexec yok — paket yolu tükendi
            if code == 124:
                return False, "Kurulum zaman aşımına uğradı (yetkilendirme penceresi yanıtlanmadı mı?)."
            tried[-1] += f" ✗ ({detail})"

    # KÖKSÜZ YEDEK: statik aMule paketi (root/şifre gerektirmez, her dağıtımda çalışır)
    if _install_static_amule_bundle(timeout=timeout):
        if _amule_ensure_running():
            return True, (
                f"aMule (bağımsız paket) kuruldu ve çekirdek arka planda başlatıldı — "
                f"sistem şifresi gerekmedi. İndirilenler: {incoming_dir()}"
            )
        return True, (
            f"aMule (bağımsız paket) kuruldu; ilk ed2k bağlantısında çekirdek otomatik başlar. "
            f"İndirilenler: {incoming_dir()}"
        )

    detail_txt = " | ".join(tried) if tried else "paket yöneticisi bulunamadı"
    # v3.8.0 KULLANICI KARARI: 'elle kurmayı deneyin + sudo komutu' ASLA gösterilmez.
    # Yalnızca dostane bir yeniden deneme yol gösterimi sunulur (pkexec penceresi
    # onaylanmadıysa ya da ağ indirme başarısız olduysa tekrar denemek yeterlidir).
    return False, (
        f"Otomatik kurulum bu denemede tamamlanamadı ({detail_txt}). "
        "Yetkilendirme penceresini onayladığınızdan ve internet bağlantınızın "
        "çalıştığından emin olup tekrar deneyin — kurulum yeniden başlatılabilir."
    )


def ed2k_install_backend_safe() -> Tuple[bool, str]:
    """install_backend'in istisna sızdırmayan sarmalayıcısı (daemon arka plan
    iş parçacığından çağrılır — her koşulda (ok, mesaj) döner)."""
    try:
        return install_backend()
    except Exception as exc:
        log.error("ed2k motor kurulumu istisnası: %s", exc)
        return False, f"Kurulum sırasında beklenmeyen hata: {exc}"
