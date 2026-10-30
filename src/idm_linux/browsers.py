from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import __version__
from .config import (
    COMPANION_CHROME_EXT_ID,
    COMPANION_FIREFOX_EXT_ID,
    COMPANION_HOST_NAME,
    LEGACY_COMPANION_CHROME_EXT_ID,
    NATIVE_HOST_NAME,
    OFFICIAL_CHROME_EXT_ID,
    OFFICIAL_EDGE_EXT_ID,
    OFFICIAL_FIREFOX_EXT_ID,
    OFFICIAL_OPERA_EXT_ID,
    get_data_dir,
)
from .sandbox import (
    looks_like_sandbox_error,
    needs_no_sandbox,
    remember_no_sandbox,
    sandbox_launch_args,
)

_IDM_DESKTOP_MARKER = "# X-IDM-Linux-Managed=1"
_CHROMIUM_UNLOCK_FEATURES = "DisableLoadExtensionCommandLineSwitch,ExtensionDisableUnsupportedDeveloper"

# v3.2.2: YENİDEN BAŞLATMASIZ EKLENTİ KURULUMU — Chromium ailesinin KURUMSAL (policy)
# force-install mekanizması. Linux'ta Chromium türevleri policy dizinini CANLI izler;
# ExtensionInstallForcelist değişince çalışan tarayıcı eklentiyi saniyeler içinde
# KENDİ kurar — tarayıcı yeniden başlatma GEREKMEZ. (Kurumsal dağıtımın resmi yolu.)
_CHROMIUM_POLICY_DIRS: List[str] = [
    "/etc/opt/chrome/policies/managed",          # Google Chrome
    "/etc/chromium/policies/managed",            # Chromium
    "/etc/chromium-browser/policies/managed",    # Debian/Ubuntu Chromium
    "/etc/brave/policies/managed",               # Brave
    "/etc/opt/edge/policies/managed",            # Microsoft Edge
    "/etc/vivaldi/policies/managed",             # Vivaldi
    "/etc/opera/policies/managed",               # Opera
    "/etc/opt/opera/policies/managed",           # Opera (alternatif)
]

# v3.2.2: Gecko ailesi kurumsal policy (Firefox açılışında otomatik kurar; canlı kapı
# zaten welcome sayfasındaki .xpi doorhanger'ıdır — restart gerektirmez)
_GECKO_POLICY_FILES: List[str] = [
    "/etc/firefox/policies/policies.json",
    "/etc/librewolf/policies/policies.json",
    "/etc/waterfox/policies/policies.json",
    "/etc/zen-browser/policies/policies.json",
]


def _root_write_file(target: Path, content: str) -> Tuple[bool, str]:
    """Root gerektiren policy dosyasını **SESSİZCE** yazmayı dener.

    v3.10.0 (kullanıcı kararı — ekran görüntüsü: "Kimlik doğrulaması gerekli"):
    Eskiden ``sudo -n`` başarısız olunca ``pkexec tee`` çağrılıyordu; bu, her
    kurulum/daemon başlangıcında KDE/GNOME polkit parola penceresi açıyordu
    (üstelik birden çok policy dizini için üst üste). Artık bu fonksiyon
    **hiçbir koşulda yetki penceresi açmaz**:
      1) dosya zaten yazılabiliyorsa doğrudan yazılır (root çalıştırma/sudoers),
      2) parolasız sudo (``sudo -n``) denenir — parola SORULMAZ, istek yoksa anında döner.
    Başarısız olursa sessizce vazgeçilir; eklenti kurulumu kullanıcı düzeyindeki
    yollarla (--load-extension bayrakları, native messaging, karşılama sayfası)
    zaten tamamlanır. Yetki isteyen yol :func:`write_policies_with_consent`
    içinde ve YALNIZ kullanıcı düğmeye bastığında çalışır.

    Döner: (ok, yöntem)
    """
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if os.access(target.parent, os.W_OK):
            target.write_text(content, encoding="utf-8")
            return True, "doğrudan"
    except OSError:
        pass
    if shutil.which("sudo"):
        try:
            res = subprocess.run(
                ["sudo", "-n", "tee", str(target)],
                input=content.encode("utf-8"),
                capture_output=True,
                timeout=6,
                check=False,
            )
            if res.returncode == 0:
                return True, "sudo"
        except (OSError, subprocess.SubprocessError):
            pass
    return False, ""


def _sudo_write_file(target: Path, content: str) -> bool:
    """Geriye dönük uyumluluk sarmalayıcısı — SESSİZ yazar (yetki sormaz)."""
    ok, _method = _root_write_file(target, content)
    return ok


def write_policies_with_consent(http_port: int) -> Dict[str, str]:
    """KULLANICI ONAYIYLA (pkexec) sistem geneli politikaları yazar.

    Yalnızca Kontrol Paneli'ndeki açık bir düğme bu fonksiyonu çağırır: kurulum
    ve daemon başlangıcı ASLA parola sormaz (kullanıcı kararı). Polkit penceresi
    burada tek seferde açılır; tüm policy dosyaları TEK yetkilendirme oturumunda
    yazılır (eskiden her dizin için ayrı ayrı pencere açılıyordu).
    """
    pkexec = shutil.which("pkexec")
    results: Dict[str, str] = {}
    if not pkexec:
        return {d: "skip (pkexec yok)" for d in _CHROMIUM_POLICY_DIRS}
    payloads: List[Tuple[Path, str]] = []
    try:
        results.update({d: "ok (mevcut)" for d, v in register_chromium_force_install_policy(http_port).items() if v.startswith("ok")})
        results.update({d: "ok (mevcut)" for d, v in register_gecko_force_install_policy(http_port).items() if v.startswith("ok")})
        update_url = f"http://127.0.0.1:{int(http_port)}/crx-update.xml?v={__version__}&port={int(http_port)}"
        chrome_body = json.dumps(
            {"ExtensionInstallForcelist": {"1": f"{COMPANION_CHROME_EXT_ID};{update_url}"}}, indent=2
        )
        gecko_body = json.dumps(
            {
                "policies": {},
                "ExtensionSettings": {
                    COMPANION_FIREFOX_EXT_ID: {
                        "installation_mode": "force_installed",
                        "install_url": (
                            f"http://127.0.0.1:{int(http_port)}/extension/idm-linux-companion-firefox.xpi"
                            f"?v={__version__}"
                        ),
                    }
                },
            },
            indent=2,
        )
        for raw_dir in _CHROMIUM_POLICY_DIRS:
            payloads.append((Path(raw_dir) / "idm-linux.json", chrome_body))
        for raw_file in _GECKO_POLICY_FILES:
            payloads.append((Path(raw_file), gecko_body))
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}
    script = "; ".join(
        f"mkdir -p {shlex.quote(str(target.parent))} && cat > {shlex.quote(str(target))} <<'IDM_EOF'\n{body}\nIDM_EOF"
        for target, body in payloads
    )
    try:
        res = subprocess.run(
            [pkexec, "sh", "-c", script],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        ok = res.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": str(exc)}
    for target, _body in payloads:
        results[str(target.parent if target.name == "idm-linux.json" else target)] = (
            "ok (yetkili)" if ok else "skip (kullanıcı iptal etti)"
        )
    return results


def register_chromium_force_install_policy(http_port: int) -> Dict[str, str]:
    """v3.2.2: Chromium ailesine kurumsal force-install policy'si yazar.
    v3.9.0 GÜNCELLEME ANINDA AKTİFLEŞME (kullanıcı kararı): update URL'ine sürüm
    damgası (?v=) eklenir — IDM güncellendiğinde policy İÇERİĞİ değişir, ÇALIŞAN
    Chromium bunu CANLI algılar, güncelleme manifestini yeniden çeker ve yeni CRX'i
    TARAYICIYI YENİDEN BAŞLATMADAN üzerine kurar. Aynı sürümde policy değeri sabit
    kalır (gereksiz yeniden denetim tetiklenmez).
    Dönen değer: {policy_dizini: "ok" | "ok (sudo)" | "skip"}"""
    update_url = (
        f"http://127.0.0.1:{int(http_port)}/crx-update.xml"
        f"?v={__version__}&port={int(http_port)}"
    )
    payload = {"ExtensionInstallForcelist": {"1": f"{COMPANION_CHROME_EXT_ID};{update_url}"}}
    body = json.dumps(payload, indent=2)
    results: Dict[str, str] = {}
    for raw_dir in _CHROMIUM_POLICY_DIRS:
        pdir = Path(raw_dir)
        target = pdir / "idm-linux.json"
        try:
            if target.exists():
                try:
                    existing = json.loads(target.read_text(encoding="utf-8"))
                    if existing.get("ExtensionInstallForcelist", {}).get("1") == payload["ExtensionInstallForcelist"]["1"]:
                        results[raw_dir] = "ok (mevcut)"
                        continue
                    # Var olan policy'yi EZME — anahtarımızı ekleyerek birleştir
                    existing.setdefault("ExtensionInstallForcelist", {})["1"] = payload["ExtensionInstallForcelist"]["1"]
                    body = json.dumps(existing, indent=2)
                except Exception:
                    pass
            pdir.mkdir(parents=True, exist_ok=True)
            if os.access(pdir, os.W_OK):
                target.write_text(body + "\n", encoding="utf-8")
                results[raw_dir] = "ok"
            else:
                results[raw_dir] = "ok (sudo)" if _sudo_write_file(target, body + "\n") else "skip (yetki istenmedi)"
        except (OSError, PermissionError):
            results[raw_dir] = "ok (sudo)" if _sudo_write_file(target, body + "\n") else "skip (yetki istenmedi)"
    return results


def register_gecko_force_install_policy(http_port: int) -> Dict[str, str]:
    """v3.2.2: Firefox ailesi policies.json'una ExtensionSettings force-install ekler.
    v3.9.0: install_url sürüm damgalı — yeni IDM sürümünde policy değişir, Firefox
    bir sonraki açılışında eklentiyi GÜNCELLER (üstüne kurar)."""
    install_url = (
        f"http://127.0.0.1:{int(http_port)}/extension/idm-linux-companion-firefox.xpi"
        f"?v={__version__}"
    )
    ext_block = {
        "installation_mode": "force_installed",
        "install_url": install_url,
    }
    results: Dict[str, str] = {}
    for raw_file in _GECKO_POLICY_FILES:
        pfile = Path(raw_file)
        try:
            data: Dict = {}
            if pfile.exists():
                try:
                    data = json.loads(pfile.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            if data.get("ExtensionSettings", {}).get(COMPANION_FIREFOX_EXT_ID) == ext_block:
                results[raw_file] = "ok (mevcut)"
                continue
            data.setdefault("ExtensionSettings", {})[COMPANION_FIREFOX_EXT_ID] = ext_block
            body = json.dumps(data, indent=2, ensure_ascii=False)
            pfile.parent.mkdir(parents=True, exist_ok=True)
            if os.access(pfile.parent, os.W_OK):
                pfile.write_text(body + "\n", encoding="utf-8")
                results[raw_file] = "ok"
            else:
                results[raw_file] = "ok (sudo)" if _sudo_write_file(pfile, body + "\n") else "skip (yetki istenmedi)"
        except (OSError, PermissionError):
            results[raw_file] = "ok (sudo)" if _sudo_write_file(pfile, body + "\n") else "skip (yetki istenmedi)"
    return results


def unregister_force_install_policies() -> None:
    """Kaldırmada (uninstall) policy'leri temizler."""
    for raw_dir in _CHROMIUM_POLICY_DIRS:
        target = Path(raw_dir) / "idm-linux.json"
        try:
            if target.exists():
                data = json.loads(target.read_text(encoding="utf-8"))
                fl = data.get("ExtensionInstallForcelist", {})
                if COMPANION_CHROME_EXT_ID in str(fl):
                    fl.pop("1", None)
                    if fl:
                        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                    else:
                        target.unlink(missing_ok=True)
        except Exception:
            pass
    for raw_file in _GECKO_POLICY_FILES:
        pfile = Path(raw_file)
        try:
            if pfile.exists():
                data = json.loads(pfile.read_text(encoding="utf-8"))
                es = data.get("ExtensionSettings", {})
                if COMPANION_FIREFOX_EXT_ID in es:
                    es.pop(COMPANION_FIREFOX_EXT_ID, None)
                    if es:
                        pfile.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                    else:
                        pfile.unlink(missing_ok=True)
        except Exception:
            pass


@dataclass
class BrowserTarget:
    name: str
    family: str             # "chromium" veya "gecko"
    binaries: List[str]
    desktop_ids: List[str]
    native_host_dir: Path
    external_ext_dirs: List[Path]
    flags_conf: Optional[Path] = None
    installed: bool = False
    registered: bool = False


@dataclass
class DetectedDefaultBrowser:
    name: str
    family: str             # "chromium" veya "gecko"
    binary: str
    desktop_id: str


def _discover_dynamic_chromium_profile_dirs(cfg_root: Path) -> List[Tuple[str, Path]]:
    """
    ~/.config altındaki sabit listede olmayan tüm Chromium/Brave/Chrome/Thorium/Vivaldi
    türevlerini (örn. BraveSoftware/Brave-Origin-Nightly, Brave-Browser-Nightly,
    ungoogled-chromium, thorium vb.) Local State / Default klasörlerinden dinamik keşfeder!
    """
    discovered: List[Tuple[str, Path]] = []
    if not cfg_root.is_dir():
        return discovered

    vendor_parents = (
        "BraveSoftware",
        "Google",
        "Thorium",
        "Microsoft",
        "Vivaldi",
        "Yandex",
        "Helium",
    )

    try:
        for entry in cfg_root.iterdir():
            if not entry.is_dir():
                continue
            if entry.name in vendor_parents:
                for sub in entry.iterdir():
                    if sub.is_dir() and (
                        (sub / "Local State").is_file()
                        or (sub / "Default").is_dir()
                        or (sub / "NativeMessagingHosts").is_dir()
                    ):
                        discovered.append((sub.name, sub))
            elif (entry / "Local State").is_file() and (entry / "Default").is_dir():
                discovered.append((entry.name, entry))
    except OSError:
        pass

    return discovered


def get_browser_targets() -> List[BrowserTarget]:
    home = Path.home()
    cfg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))

    raw_targets: List[BrowserTarget] = [
        BrowserTarget(
            name="Chromium",
            family="chromium",
            binaries=["chromium", "chromium-browser", "ungoogled-chromium"],
            desktop_ids=["chromium.desktop", "chromium-browser.desktop", "ungoogled-chromium.desktop"],
            native_host_dir=cfg / "chromium" / "NativeMessagingHosts",
            external_ext_dirs=[
                cfg / "chromium" / "External Extensions",
                Path("/usr/share/chromium/extensions"),
            ],
            flags_conf=cfg / "chromium-flags.conf",
        ),
        BrowserTarget(
            name="Google Chrome",
            family="chromium",
            binaries=["google-chrome-stable", "google-chrome", "google-chrome-beta", "google-chrome-unstable"],
            desktop_ids=[
                "google-chrome.desktop",
                "google-chrome-stable.desktop",
                "google-chrome-beta.desktop",
                "google-chrome-unstable.desktop",
            ],
            native_host_dir=cfg / "google-chrome" / "NativeMessagingHosts",
            external_ext_dirs=[
                cfg / "google-chrome" / "External Extensions",
                Path("/opt/google/chrome/extensions"),
                Path("/usr/share/google-chrome/extensions"),
            ],
            flags_conf=cfg / "chrome-flags.conf",
        ),
        BrowserTarget(
            name="Brave Browser",
            family="chromium",
            binaries=["brave-browser", "brave", "brave-bin", "brave-browser-stable"],
            desktop_ids=["brave-browser.desktop", "brave.desktop", "com.brave.Browser.desktop"],
            native_host_dir=cfg / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts",
            external_ext_dirs=[
                cfg / "BraveSoftware" / "Brave-Browser" / "External Extensions",
                Path("/opt/brave.com/brave/extensions"),
                Path("/usr/share/brave/extensions"),
            ],
            flags_conf=cfg / "brave-flags.conf",
        ),
        BrowserTarget(
            name="Brave Origin Nightly",
            family="chromium",
            binaries=["brave-origin-nightly", "brave-browser-origin-nightly"],
            desktop_ids=["brave-origin-nightly.desktop", "brave-browser-origin-nightly.desktop"],
            native_host_dir=cfg / "BraveSoftware" / "Brave-Origin-Nightly" / "NativeMessagingHosts",
            external_ext_dirs=[
                cfg / "BraveSoftware" / "Brave-Origin-Nightly" / "External Extensions",
                Path("/opt/brave.com/brave-origin-nightly/extensions"),
            ],
            flags_conf=cfg / "brave-origin-nightly-flags.conf",
        ),
        BrowserTarget(
            name="Brave Nightly",
            family="chromium",
            binaries=["brave-browser-nightly", "brave-nightly"],
            desktop_ids=["brave-browser-nightly.desktop", "brave-nightly.desktop"],
            native_host_dir=cfg / "BraveSoftware" / "Brave-Browser-Nightly" / "NativeMessagingHosts",
            external_ext_dirs=[
                cfg / "BraveSoftware" / "Brave-Browser-Nightly" / "External Extensions",
                Path("/opt/brave.com/brave-nightly/extensions"),
            ],
            flags_conf=cfg / "brave-nightly-flags.conf",
        ),
        BrowserTarget(
            name="Brave Beta",
            family="chromium",
            binaries=["brave-browser-beta", "brave-beta"],
            desktop_ids=["brave-browser-beta.desktop", "brave-beta.desktop"],
            native_host_dir=cfg / "BraveSoftware" / "Brave-Browser-Beta" / "NativeMessagingHosts",
            external_ext_dirs=[
                cfg / "BraveSoftware" / "Brave-Browser-Beta" / "External Extensions",
            ],
            flags_conf=cfg / "brave-beta-flags.conf",
        ),
        BrowserTarget(
            name="Microsoft Edge",
            family="chromium",
            binaries=["microsoft-edge-stable", "microsoft-edge", "microsoft-edge-beta", "microsoft-edge-dev"],
            desktop_ids=["microsoft-edge.desktop", "microsoft-edge-stable.desktop", "microsoft-edge-dev.desktop"],
            native_host_dir=cfg / "microsoft-edge" / "NativeMessagingHosts",
            external_ext_dirs=[
                cfg / "microsoft-edge" / "External Extensions",
                Path("/usr/share/microsoft-edge/extensions"),
            ],
            flags_conf=cfg / "microsoft-edge-stable-flags.conf",
        ),
        BrowserTarget(
            name="Vivaldi",
            family="chromium",
            binaries=["vivaldi-stable", "vivaldi", "vivaldi-snapshot"],
            desktop_ids=["vivaldi-stable.desktop", "vivaldi.desktop", "vivaldi-snapshot.desktop"],
            native_host_dir=cfg / "vivaldi" / "NativeMessagingHosts",
            external_ext_dirs=[cfg / "vivaldi" / "External Extensions"],
            flags_conf=cfg / "vivaldi-stable.conf",
        ),
        BrowserTarget(
            name="Opera",
            family="chromium",
            binaries=["opera", "opera-beta", "opera-developer"],
            desktop_ids=["opera.desktop", "opera-beta.desktop"],
            native_host_dir=cfg / "opera" / "NativeMessagingHosts",
            external_ext_dirs=[cfg / "opera" / "External Extensions"],
        ),
        BrowserTarget(
            name="Thorium Browser",
            family="chromium",
            binaries=["thorium-browser", "thorium"],
            desktop_ids=["thorium-browser.desktop"],
            native_host_dir=cfg / "thorium" / "NativeMessagingHosts",
            external_ext_dirs=[cfg / "thorium" / "External Extensions"],
            flags_conf=cfg / "thorium-flags.conf",
        ),
        BrowserTarget(
            name="Mozilla Firefox",
            family="gecko",
            binaries=["firefox", "firefox-bin", "firefox-esr", "firefox-developer-edition", "firefox-nightly"],
            desktop_ids=["firefox.desktop", "org.mozilla.firefox.desktop", "firefox-esr.desktop", "firefox-nightly.desktop"],
            native_host_dir=home / ".mozilla" / "native-messaging-hosts",
            external_ext_dirs=[],
        ),
        BrowserTarget(
            name="LibreWolf",
            family="gecko",
            binaries=["librewolf"],
            desktop_ids=["librewolf.desktop", "io.gitlab.librewolf-community.desktop"],
            native_host_dir=home / ".librewolf" / "native-messaging-hosts",
            external_ext_dirs=[],
        ),
        BrowserTarget(
            name="Waterfox",
            family="gecko",
            binaries=["waterfox", "waterfox-g"],
            desktop_ids=["waterfox.desktop"],
            native_host_dir=home / ".waterfox" / "native-messaging-hosts",
            external_ext_dirs=[],
        ),
        BrowserTarget(
            name="Zen Browser",
            family="gecko",
            binaries=["zen-browser", "zen"],
            desktop_ids=["zen.desktop", "zen-browser.desktop"],
            native_host_dir=home / ".zen" / "native-messaging-hosts",
            external_ext_dirs=[],
        ),
    ]

    known_nh_dirs = {t.native_host_dir.resolve() for t in raw_targets}
    for prof_label, prof_root in _discover_extra_chromium_dirs_safe(cfg, known_nh_dirs):
        slug = prof_label.lower().replace(" ", "-")
        raw_targets.append(
            BrowserTarget(
                name=prof_label.replace("-", " ").title(),
                family="chromium",
                binaries=[slug],
                desktop_ids=[f"{slug}.desktop"],
                native_host_dir=prof_root / "NativeMessagingHosts",
                external_ext_dirs=[prof_root / "External Extensions"],
                flags_conf=cfg / f"{slug}-flags.conf",
            )
        )

    for t in raw_targets:
        has_bin = any(shutil.which(b) is not None for b in t.binaries)
        has_profile_parent = t.native_host_dir.parent.exists()
        t.installed = has_bin or has_profile_parent
        t.registered = (t.native_host_dir / f"{NATIVE_HOST_NAME}.json").exists()

    return raw_targets


def _discover_extra_chromium_dirs_safe(
    cfg_root: Path,
    known_nh_dirs: Set[Path],
) -> List[Tuple[str, Path]]:
    extras: List[Tuple[str, Path]] = []
    for label, prof_root in _discover_dynamic_chromium_profile_dirs(cfg_root):
        nh = (prof_root / "NativeMessagingHosts").resolve()
        if nh not in known_nh_dirs:
            known_nh_dirs.add(nh)
            extras.append((label, prof_root))
    return extras


def get_browser_extensions_url(det: Optional[DetectedDefaultBrowser]) -> str:
    """Algılanan tarayıcıya özel dahili uzantı yönetimi adresini döndürür (örn. brave://extensions)."""
    if not det:
        return "chrome://extensions"
    low = f"{det.name} {det.desktop_id} {det.binary}".lower()
    if "brave" in low:
        return "brave://extensions"
    if "edge" in low:
        return "edge://extensions"
    if "vivaldi" in low:
        return "vivaldi://extensions"
    if "opera" in low:
        return "opera://extensions"
    if det.family == "gecko":
        return "about:addons"
    return "chrome://extensions"


def _extract_exec_binary_from_desktop(desktop_file: Path) -> str:
    try:
        txt = desktop_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    for line in txt.splitlines():
        if line.startswith("Exec="):
            raw_cmd = line[5:].strip()
            # env VAR=VAL öneklerini atla
            tokens = re.findall(r'"[^"]+"|\'[^\']+\'|\S+', raw_cmd)
            for idx, tok in enumerate(tokens):
                clean = tok.strip("\"'")
                if idx == 0 and Path(clean).name == "env":
                    continue
                if "=" in clean and not clean.startswith("/"):
                    continue
                if clean.startswith("%") or clean.startswith("-"):
                    continue
                resolved = shutil.which(clean) or (clean if Path(clean).exists() else "")
                if resolved:
                    return resolved
            break
    return ""


def detect_default_browser() -> Optional[DetectedDefaultBrowser]:
    """
    Sistemin varsayılan web tarayıcısını dinamik olarak sorgular ve onun
    Firefox (gecko) mu yoksa Chromium tabanlı mı olduğunu tam isabetle tespit eder.
    """
    targets = get_browser_targets()
    desktop_id = ""

    for cmd in (
        ["xdg-settings", "get", "default-web-browser"],
        ["xdg-mime", "query", "default", "x-scheme-handler/https"],
        ["xdg-mime", "query", "default", "text/html"],
    ):
        if shutil.which(cmd[0]):
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2, check=False)
                out = res.stdout.strip()
                if out and out.endswith(".desktop"):
                    desktop_id = out
                    break
            except (OSError, subprocess.SubprocessError):
                pass

    lower_desk = desktop_id.lower()
    if lower_desk:
        # 1. Önce tam .desktop kimliği eşleşmesi (brave-origin-nightly.desktop != brave-browser.desktop!)
        for t in targets:
            if any(lower_desk == d.lower() for d in t.desktop_ids):
                for b in t.binaries:
                    bp = shutil.which(b)
                    if bp:
                        return DetectedDefaultBrowser(
                            name=t.name, family=t.family, binary=bp, desktop_id=desktop_id
                        )

        # 2. Doğrudan sistem/kullanıcı .desktop dosyasının Exec= satırını oku!
        search_app_dirs = [
            Path("/usr/share/applications"),
            Path("/usr/local/share/applications"),
            Path.home() / ".local" / "share" / "applications",
        ]
        for app_dir in search_app_dirs:
            df = app_dir / desktop_id
            if df.is_file():
                bp = _extract_exec_binary_from_desktop(df)
                if bp:
                    fam = (
                        "gecko"
                        if any(
                            x in lower_desk
                            for x in ("firefox", "librewolf", "waterfox", "zen", "icecat", "floorp")
                        )
                        else "chromium"
                    )
                    pretty = desktop_id[:-8] if desktop_id.endswith(".desktop") else desktop_id
                    for t in targets:
                        if any(Path(bp).name == b for b in t.binaries):
                            pretty = t.name
                            fam = t.family
                            break
                    else:
                        pretty = pretty.replace("-", "-").title()
                    return DetectedDefaultBrowser(
                        name=pretty, family=fam, binary=bp, desktop_id=desktop_id
                    )

        # 3. Kısmi ikili adı eşleşmesi
        for t in targets:
            if any(b in lower_desk for b in t.binaries):
                for b in t.binaries:
                    bp = shutil.which(b)
                    if bp:
                        return DetectedDefaultBrowser(
                            name=t.name, family=t.family, binary=bp, desktop_id=desktop_id
                        )

    # XDG boş döndüyse kurulu ilk tarayıcıyı seç
    for t in targets:
        for b in t.binaries:
            bp = shutil.which(b)
            if bp:
                return DetectedDefaultBrowser(
                    name=t.name, family=t.family, binary=bp, desktop_id=t.desktop_ids[0]
                )
    return None


def _resolve_browser_executable_family(binary_path: str) -> Set[str]:
    """
    Linux tarayıcı başlatıcıları çoğunlukla kabuk sarmalayıcıdır (örn. /usr/bin/brave-origin-nightly ->
    /opt/brave.com/brave-origin-nightly/brave). Bu fonksiyon sarmalayıcının kendisini, sembolik bağ
    hedefini ve aynı kurulum klasöründeki gerçek ELF tarayıcı ikilisini (brave, chrome, chromium,
    msedge, vivaldi-bin, opera, thorium) tam yol olarak bulur!
    """
    paths: Set[str] = set()
    if not binary_path:
        return paths

    p = Path(binary_path)
    paths.add(str(p))
    try:
        rp = p.resolve()
        paths.add(str(rp))
    except OSError:
        rp = p

    install_dir = rp.parent
    # Eğer sarmalayıcı kabuk betiğiyse içindeki dizin ve ikili referanslarını incele
    try:
        if rp.is_file() and rp.stat().st_size < 131_072:
            head = rp.read_bytes()[:4096]
            if head.startswith(b"#!"):
                text = rp.read_text(encoding="utf-8", errors="ignore")
                for m in re.finditer(r"(/opt/[^\s\"'$]+|/usr/lib[^\s\"'$]+)", text):
                    cand = Path(m.group(1))
                    if cand.is_file():
                        paths.add(str(cand))
                        paths.add(str(cand.resolve()))
                    elif cand.is_dir():
                        install_dir = cand
    except OSError:
        pass

    # /usr/bin dışındaki özel tarayıcı klasöründeyse (örn. /opt/brave.com/brave-origin-nightly/)
    # o klasördeki asıl ELF ikilisini ekle!
    if install_dir not in (Path("/usr/bin"), Path("/bin"), Path("/usr/local/bin")):
        for elf_name in (
            "brave",
            "chrome",
            "google-chrome",
            "chromium",
            "chromium-browser",
            "msedge",
            "microsoft-edge",
            "vivaldi-bin",
            "opera",
            "thorium",
        ):
            cand_elf = install_dir / elf_name
            if cand_elf.is_file():
                paths.add(str(cand_elf))
                try:
                    paths.add(str(cand_elf.resolve()))
                except OSError:
                    pass

    return paths


def _find_matching_browser_pids(binary_path: str) -> Tuple[List[int], List[int]]:
    """
    15 karakterlik pkill sınırına TAKILMADAN doğrudan /proc/<pid> üzerinden bu kullanıcıya ait
    ve verilen tarayıcı ikilisi/sarmalayıcısıyla eşleşen (root_pids, all_pids) listesini döndürür.
    root_pids: '--type=' içermeyen ana tarayıcı süreçleri (SIGTERM gönderildiğinde sekmeleri kaydeder!).
    """
    target_paths = _resolve_browser_executable_family(binary_path)
    target_basenames = {Path(x).name for x in target_paths if Path(x).name not in ("sh", "bash", "env")}
    # Özel sarmalayıcı adı varsa (örn. brave-origin-nightly) cmdline içinde eşleştirmek için tut
    wrapper_name = Path(binary_path).name
    uid = os.getuid()
    my_pid = os.getpid()

    root_pids: List[int] = []
    all_pids: List[int] = []

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return root_pids, all_pids

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == my_pid:
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            raw_cmd = (entry / "cmdline").read_bytes()
            if not raw_cmd:
                continue
            args = [a.decode("utf-8", errors="ignore") for a in raw_cmd.split(b"\x00") if a]
            if not args:
                continue
            arg0 = args[0].split()[0]
            exe_real = ""
            try:
                exe_real = os.readlink(entry / "exe")
                if exe_real.endswith(" (deleted)"):
                    exe_real = exe_real[:-10]
            except OSError:
                pass

            matched = False
            if exe_real and exe_real in target_paths:
                matched = True
            elif arg0 in target_paths:
                matched = True
            elif Path(arg0).name == wrapper_name:
                matched = True
            elif len(wrapper_name) > 6 and wrapper_name in " ".join(args[:2]):
                matched = True
            elif exe_real and Path(exe_real).name in target_basenames and wrapper_name in exe_real:
                matched = True

            if not matched:
                continue

            # Bizim kendi python sürecimizi yanlışlıkla eşleştirme
            if exe_real and "python" in Path(exe_real).name.lower():
                continue

            all_pids.append(pid)
            is_child_helper = any(a.startswith("--type=") for a in args[1:])
            if not is_child_helper:
                root_pids.append(pid)
        except (OSError, ValueError):
            continue

    return root_pids, all_pids


def _is_browser_process_running(binary_path: str) -> bool:
    roots, all_p = _find_matching_browser_pids(binary_path)
    return bool(roots or all_p)


def terminate_browser_gracefully(binary_path: str, timeout_sec: float = 6.5) -> bool:
    """
    Açık Chromium/Brave tarayıcısının ana sürecine SIGTERM göndererek açık tüm sekmeleri
    oturum dosyasına kaydetmesini sağlar ve SingletonLock kalkana kadar bekler.
    """
    root_pids, all_pids = _find_matching_browser_pids(binary_path)
    if not all_pids:
        return True

    # 1. Önce yalnızca ana tarayıcı süreçlerine SIGTERM gönder (temiz oturum kaydı için!)
    targets_first = root_pids if root_pids else all_pids
    for pid in targets_first:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

    deadline = time.time() + timeout_sec
    sent_all_term = False
    while time.time() < deadline:
        time.sleep(0.2)
        _roots, remaining = _find_matching_browser_pids(binary_path)
        if not remaining:
            time.sleep(0.15)
            return True
        # 2.5 sn sonra hala sarmalayıcı/yardımcı süreç kaldıysa hepsine SIGTERM gönder
        if not sent_all_term and (deadline - time.time()) < (timeout_sec - 2.5):
            sent_all_term = True
            for pid in remaining:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass

    # Son çare: kilitli kalan yardımcı süreçleri temizle
    _roots, stuck = _find_matching_browser_pids(binary_path)
    for pid in stuck:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    time.sleep(0.2)
    return not _is_browser_process_running(binary_path)


def configure_chromium_autoload_flags(
    chrom_ext_dir: Path,
    default_browser: Optional[DetectedDefaultBrowser] = None,
) -> None:
    """
    1) Tüm kurulu Chromium türevlerinin ~/.config/*-flags.conf dosyalarına
       --load-extension ve --disable-features bayraklarını işler.
    2) Varsayılan Chromium tarayıcısının (örn. Brave-Origin-Nightly) uygulama başlatıcısı
       ~/.config/*-flags.conf okumasa bile her açılışta eklentiyle başlaması için
       ~/.local/share/applications/<desktop_id> kullanıcı sarmalayıcısını oluşturur
       (uninstall sırasında %100 eski haline döndürülür!).
    """
    ext_str = str(chrom_ext_dir.resolve())
    flag_lines = [
        f"--disable-features={_CHROMIUM_UNLOCK_FEATURES}",
        f"--load-extension={ext_str}",
    ]

    cfg_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    conf_files: Set[Path] = set()
    for t in get_browser_targets():
        if t.family == "chromium" and t.installed and t.flags_conf:
            conf_files.add(t.flags_conf)

    if default_browser and default_browser.family == "chromium":
        b_slug = Path(default_browser.binary).name.lower()
        conf_files.add(cfg_root / f"{b_slug}-flags.conf")

    for fc in conf_files:
        try:
            fc.parent.mkdir(parents=True, exist_ok=True)
            existing = fc.read_text(encoding="utf-8", errors="ignore") if fc.exists() else ""
            cleaned_lines = [
                ln
                for ln in existing.splitlines()
                if "idm-linux/extensions/chromium" not in ln
                and "DisableLoadExtensionCommandLineSwitch" not in ln
            ]
            cleaned_lines.extend(flag_lines)
            fc.write_text("\n".join(cleaned_lines) + "\n", encoding="utf-8")
        except OSError:
            pass

    # Varsayılan Chromium tarayıcısı için yerel .desktop başlatıcı kaydı (flags.conf okumayan paketler için!)
    det = default_browser or detect_default_browser()
    if det and det.family == "chromium" and det.desktop_id.endswith(".desktop"):
        _install_user_desktop_autoload_override(det.desktop_id, chrom_ext_dir)


def _install_user_desktop_autoload_override(desktop_id: str, chrom_ext_dir: Path) -> None:
    user_apps = Path.home() / ".local" / "share" / "applications"
    user_target = user_apps / desktop_id
    backup_target = user_apps / f"{desktop_id}.idm-linux-orig"

    source_desktop: Optional[Path] = None
    if backup_target.is_file():
        source_desktop = backup_target
    elif user_target.is_file():
        existing_txt = user_target.read_text(encoding="utf-8", errors="ignore")
        if _IDM_DESKTOP_MARKER not in existing_txt:
            try:
                user_apps.mkdir(parents=True, exist_ok=True)
                backup_target.write_text(existing_txt, encoding="utf-8")
            except OSError:
                return
            source_desktop = backup_target
    if source_desktop is None:
        for sys_dir in (Path("/usr/share/applications"), Path("/usr/local/share/applications")):
            cand = sys_dir / desktop_id
            if cand.is_file():
                source_desktop = cand
                break

    if source_desktop is None or not source_desktop.is_file():
        return

    try:
        raw_txt = source_desktop.read_text(encoding="utf-8", errors="ignore")
        ext_arg = (
            f'--disable-features={_CHROMIUM_UNLOCK_FEATURES} '
            f'--load-extension="{chrom_ext_dir.resolve()}"'
        )
        out_lines = [_IDM_DESKTOP_MARKER]
        for ln in raw_txt.splitlines():
            if ln.strip() == _IDM_DESKTOP_MARKER:
                continue
            if ln.startswith("Exec=") and "idm-linux/extensions/chromium" not in ln:
                # Exec=/usr/bin/brave-origin-nightly %U -> Exec=/usr/bin/brave-origin-nightly --disable-features=... --load-extension="..." %U
                if "%" in ln:
                    idx = ln.find("%")
                    ln = f"{ln[:idx].rstrip()} {ext_arg} {ln[idx:]}"
                else:
                    ln = f"{ln.rstrip()} {ext_arg}"
            out_lines.append(ln)
        user_apps.mkdir(parents=True, exist_ok=True)
        user_target.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def remove_chromium_autoload_flags() -> None:
    cfg_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    conf_candidates: Set[Path] = set()
    for t in get_browser_targets():
        if t.flags_conf:
            conf_candidates.add(t.flags_conf)
    if cfg_root.is_dir():
        try:
            for p in cfg_root.glob("*-flags.conf"):
                conf_candidates.add(p)
        except OSError:
            pass

    for fc in conf_candidates:
        if fc.exists():
            try:
                existing = fc.read_text(encoding="utf-8", errors="ignore")
                cleaned = [
                    ln
                    for ln in existing.splitlines()
                    if "idm-linux/extensions/chromium" not in ln
                    and "DisableLoadExtensionCommandLineSwitch" not in ln
                    and ln.strip()
                ]
                if cleaned:
                    fc.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
                else:
                    fc.unlink(missing_ok=True)
            except OSError:
                pass

    # Yerel .desktop sarmalayıcılarını %100 eski haline döndür / temizle
    user_apps = Path.home() / ".local" / "share" / "applications"
    if user_apps.is_dir():
        try:
            for df in list(user_apps.glob("*.desktop")):
                orig = user_apps / f"{df.name}.idm-linux-orig"
                txt = df.read_text(encoding="utf-8", errors="ignore")
                if _IDM_DESKTOP_MARKER in txt or "idm-linux/extensions/chromium" in txt:
                    if orig.is_file():
                        df.write_text(orig.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
                        orig.unlink(missing_ok=True)
                    else:
                        df.unlink(missing_ok=True)
            for stray_orig in list(user_apps.glob("*.idm-linux-orig")):
                stray_orig.unlink(missing_ok=True)
        except OSError:
            pass


def _copy_path_to_system_clipboard(text: str) -> None:
    for cmd in (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), timeout=1.5, check=False)
                return
            except (OSError, subprocess.SubprocessError):
                pass


def _popen_browser_with_sandbox_retry(cmd: List[str]) -> "subprocess.Popen":
    """v3.14.2: Tarayıcıyı sandbox uyumluluğuyla AÇILMAYA ZORLAYARAK başlatır.

    Kanka kuralı: kurulum sırasında/eklenti yüklerken IDM tarayıcıyı açmak
    istediğinde --no-sandbox engeline takılan ortamlarda tarayıcı AÇILMAYAZ;
    burada:
      1) Ortam/kalıcı hafıza gerektiriyorsa BAŞTAN --no-sandbox eklenir,
      2) Yine de hızla ölürse ve çıktı sandbox hata imzası taşıyorsa araç
         KALICI işaretlenir ve --no-sandbox ile TEKRAR açılır (zorla açılış).
    """
    binary = cmd[0] if cmd else ""
    sb_args = sandbox_launch_args(binary) if binary else []
    launch = [cmd[0], *sb_args, *cmd[1:]] if sb_args else list(cmd)
    try:
        proc = subprocess.Popen(
            launch,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        time.sleep(0.9)
        rc = proc.poll()
        if rc is None or rc == 0:
            return proc  # çalışıyor / sorunsuz — iş tamam
        err_txt = ""
        try:
            err_txt = (proc.stderr.read() or b"").decode("utf-8", "ignore")
        except Exception:
            pass
        if looks_like_sandbox_error(err_txt):
            # Kökten çözüm: aracı kalıcı işaretle (kullanıcının kendi açılışları da
            # flags.conf sayesinde sandbox'sız başlar) ve --no-sandbox ile ZORLA aç
            remember_no_sandbox(binary, reason=err_txt.strip()[:180])
            retry = [cmd[0], "--no-sandbox"]
            if needs_no_sandbox():
                retry.append("--disable-dev-shm-usage")
            retry.extend(cmd[1:])
            return subprocess.Popen(
                retry,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        # Sandbox hatası değil: davranış eskisi gibi sessiz (DEAD process zaten bitti)
        return proc
    except Exception:
        # Son çare: hiçbir denetim olmadan başlatmayı dene
        try:
            return subprocess.Popen(
                launch,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            raise


def _launch_chromium_with_extension(
    binary_path: str,
    chrom_ext_dir: Path,
    welcome_url: str,
) -> None:
    """
    Hem Brave / Brave-Origin-Nightly / Chromium / Edge / Vivaldi (--load-extension +
    --disable-features=DisableLoadExtensionCommandLineSwitch,ExtensionDisableUnsupportedDeveloper)
    HEM DE Google Chrome 142+ (--remote-debugging-pipe + Extensions.loadUnpacked CDP komutu)
    ile %100 uyumlu ikili başlatıcı!
    """
    ext_abs = str(chrom_ext_dir.resolve())
    bname_low = Path(binary_path).name.lower()
    is_branded_google_chrome = "google-chrome" in bname_low or bname_low == "chrome"

    base_args = [
        binary_path,
        "--restore-last-session",
        f"--disable-features={_CHROMIUM_UNLOCK_FEATURES}",
        f"--load-extension={ext_abs}",
    ]

    if not is_branded_google_chrome:
        # v3.14.2: sandbox engelli ortamlarda BAŞTAN --no-sandbox; engeline takılan
        # araç kalıcı işaretlenip --no-sandbox ile yeniden AÇILMAYA ZORLANIR
        _popen_browser_with_sandbox_retry([*base_args, welcome_url])
        return

    # Google Chrome 142+ resmi derlemeleri için bağımsız CDP Pipe (FD 3 & FD 4) yardımcı başlatıcısı:
    # Chrome başladığı saniyede borudan Extensions.loadUnpacked gönderir ve Chrome kapanana dek boruyu açık tutar.
    # v3.14.2: sandbox bayrakları yardımcıya taşınır; Chrome sandbox engeline takılırsa
    # yardımcı KENDİSİ --no-sandbox ile yeniden başlatır (açılış zorlanır).
    sb_args = sandbox_launch_args(binary_path)
    helper_code = r"""
import json, os, shlex, subprocess, sys, tempfile, time
binary, ext_dir, url, feats = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sb_flags = shlex.split(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5].strip() else []
c_read, p_write = os.pipe()
p_read, c_write = os.pipe()
def _setup_fds():
    os.dup2(c_read, 3)
    os.dup2(c_write, 4)
def _spawn(extra):
    cmd = [binary, *extra, *sb_flags,
        "--restore-last-session",
        "--remote-debugging-pipe",
        "--enable-unsafe-extension-debugging",
        f"--disable-features={feats}",
        f"--load-extension={ext_dir}",
        url,
    ]
    # v3.14.2: stderr GEÇİCİ DOSYAYA — PIPE dolarsa Chrome'nin stderr yazısı
    # TIKANIR ve tarayıcı donar; dosya sınırsızdır ve ölüm anında okunabilir
    errf = tempfile.TemporaryFile()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=errf,
        pass_fds=(3, 4),
        preexec_fn=_setup_fds,
        start_new_session=True,
    )
    return proc, errf
proc, errf = _spawn([])
os.close(c_read)
os.close(c_write)
time.sleep(1.1)
if proc.poll() not in (None, 0) and "--no-sandbox" not in sb_flags:
    # v3.14.2: sandbox engeli — --no-sandbox ile ZORLA yeniden açılış
    try:
        errf.seek(0)
        err = (errf.read() or b"").decode("utf-8", "ignore").lower()
    except Exception:
        err = ""
    sigs = ("running as root without --no-sandbox", "running without the suid sandbox",
            "the suid sandbox helper binary was found, but is not configured correctly",
            "failed to move to new namespace", "no usable sandbox", "cannot open sandbox")
    if any(s in err for s in sigs):
        # işaret, ana sürecin bir sonraki çalışmasında ortam algılama/kalıcı
        # hafızayla kalıcılaşır; burada amaç AÇILIŞI ZORLAMAK
        proc, errf = _spawn(["--no-sandbox", "--disable-dev-shm-usage"])
try:
    time.sleep(0.4)
    msg = json.dumps({"id": 1, "method": "Extensions.loadUnpacked", "params": {"path": ext_dir}}).encode("utf-8") + b"\x00"
    os.write(p_write, msg)
    while proc.poll() is None:
        buf = os.read(p_read, 4096)
        if not buf:
            break
except OSError:
    pass
"""
    subprocess.Popen(
        [sys.executable, "-c", helper_code, binary_path, ext_abs, welcome_url, _CHROMIUM_UNLOCK_FEATURES, " ".join(sb_args)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def auto_install_and_open_default_browser(
    http_port: int,
    chrom_ext_dir: Path,
    ff_xpi_path: Path,
    restart_if_running: bool = False,
) -> Tuple[bool, str]:
    """
    Sistemin varsayılan tarayıcısını dinamik olarak algılar (Firefox/Gecko vs Chromium tabanlı)
    ve tarayıcıyı açarak ilgili IDM eklentisini otomatik kurar / etkinleştirir!
    """
    det = detect_default_browser()
    if not det:
        return False, "Sistemde varsayılan bir web tarayıcısı algılanamadı."

    # 1. Durum: Firefox / LibreWolf / Waterfox / Zen (Gecko Ailesi)
    # v2.8.0: RELEASE Firefox imzasız XPI'yi REDDETTİĞİ için kurulum dialogu yerine
    # profil sideload + imzalı resmi XPI stratejisi uygulanır ("not verified" hatası biter).
    if det.family == "gecko":
        from .firefox_ext import install_firefox_extensions_robust, official_xpi_cache_path

        # v3.2.2: Gecko kurumsal policy — sonraki tüm açılışlarda eklenti otomatik (sessiz kurulum)
        try:
            register_gecko_force_install_policy(http_port)
        except Exception:
            pass

        home = Path.home()
        root_map = {
            "firefox": home / ".mozilla",
            "librewolf": home / ".librewolf",
            "waterfox": home / ".waterfox",
            "zen": home / ".zen",
        }
        home_root = next((v for k, v in root_map.items() if k in det.binary.lower()), home / ".mozilla")
        report = install_firefox_extensions_robust(
            [(det.name, Path(det.binary).name, home_root)], ff_xpi_path, official_xpi_cache_path()
        )
        welcome_url = f"http://127.0.0.1:{http_port}/welcome"
        # v3.14.2: sandbox engelli ortamda Gecko ailesi etkilenmez ama Chromium
        # türevi Gecko çatallarına karşı güvenli başlatma + zorla-açılış katmanı kullanılır
        _popen_browser_with_sandbox_retry([det.binary, welcome_url])
        if report["signed"] or report["companion"]:
            return True, (
                f"Varsayılan tarayıcı ({det.name} — Gecko) profillerine eklenti(ler) DOĞRUDAN sideload edildi "
                f"(imzalı: {len(report['signed'])}, companion: {len(report['companion'])}). Tarayıcı yeniden başlatıldığında aktiftir!"
            )
        if ff_xpi_path.exists():
            _popen_browser_with_sandbox_retry([det.binary, str(ff_xpi_path.resolve())])
        return True, f"Varsayılan tarayıcı ({det.name} — Gecko) algılandı ve .xpi eklenti kurulumu başlatıldı!"

    # 2. Durum: Chromium / Google Chrome / Brave / Brave-Origin-Nightly / Edge / Vivaldi
    configure_chromium_autoload_flags(chrom_ext_dir, default_browser=det)
    # v3.2.2: YENİDEN BAŞLATMASIZ kurulum — kurumsal policy force-install. ÇALIŞAN tarayıcı
    # bile policy değişimini canlı izler ve eklentiyi kendi kurar (restart YOK!).
    try:
        register_chromium_force_install_policy(http_port)
    except Exception:
        pass
    _copy_path_to_system_clipboard(str(chrom_ext_dir.resolve()))
    welcome_url = f"http://127.0.0.1:{http_port}/welcome"
    running = _is_browser_process_running(det.binary)

    if restart_if_running and running:
        terminate_browser_gracefully(det.binary, timeout_sec=6.5)
        running = _is_browser_process_running(det.binary)

    if not running:
        _launch_chromium_with_extension(det.binary, chrom_ext_dir, welcome_url)
        return True, f"Varsayılan tarayıcı ({det.name} — Chromium) algılandı ve eklenti otomatik yüklenerek açıldı!"

    # Tarayıcı zaten açıksa: policy force-install CANLI devreye girer (restart gerekmez);
    # /welcome sayfası da aktivasyonu anında doğrular.
    # v3.14.2: sandbox engeli olsa dahi sekme açılışı zorlanır
    _popen_browser_with_sandbox_retry([det.binary, welcome_url])
    return True, (
        f"Varsayılan tarayıcı ({det.name} — Chromium) algılandı; eklenti kurumsal policy ile "
        "CANLI yüklendi (tarayıcı yeniden başlatılmadı) ve aktivasyon sayfası açıldı!"
    )


def build_chromium_manifest(
    host_name: str,
    wrapper_path: Path,
    extra_ext_ids: Optional[List[str]] = None,
) -> Dict:
    ids = [
        OFFICIAL_CHROME_EXT_ID,
        OFFICIAL_EDGE_EXT_ID,
        OFFICIAL_OPERA_EXT_ID,
        COMPANION_CHROME_EXT_ID,
        LEGACY_COMPANION_CHROME_EXT_ID,
    ]
    if extra_ext_ids:
        for eid in extra_ext_ids:
            eid = eid.strip()
            if eid and eid not in ids:
                ids.append(eid)

    return {
        "name": host_name,
        "description": "Internet Download Manager Linux Hybrid Native Messaging Host",
        "path": str(wrapper_path.resolve()),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{eid}/" for eid in ids],
    }


def build_gecko_manifest(host_name: str, wrapper_path: Path) -> Dict:
    return {
        "name": host_name,
        "description": "Internet Download Manager Linux Hybrid Native Messaging Host",
        "path": str(wrapper_path.resolve()),
        "type": "stdio",
        "allowed_extensions": [
            OFFICIAL_FIREFOX_EXT_ID,
            COMPANION_FIREFOX_EXT_ID,
        ],
    }


def create_native_host_wrapper(python_exe: str, package_src_dir: Path) -> Path:
    bin_dir = get_data_dir() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    wrapper = bin_dir / "idm-native-host"

    script = f"""#!/bin/sh
export PYTHONPATH="{package_src_dir.resolve()}${{PYTHONPATH:+:$PYTHONPATH}}"
export PYTHONDONTWRITEBYTECODE=1
exec "{python_exe}" -m idm_linux.native_host "$@"
"""
    wrapper.write_text(script, encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def register_external_crx_descriptors(crx_path: Path, targets: List[BrowserTarget]) -> None:
    if not crx_path.exists():
        return

    descriptor = {
        "external_crx": str(crx_path.resolve()),
        "external_version": __version__,
    }
    payload = json.dumps(descriptor, indent=2) + "\n"

    for t in targets:
        if t.family != "chromium" or not t.installed:
            continue
        for ext_dir in t.external_ext_dirs:
            try:
                if str(ext_dir).startswith(str(Path.home())):
                    ext_dir.mkdir(parents=True, exist_ok=True)
                elif not ext_dir.exists() or not os.access(ext_dir, os.W_OK):
                    continue
                (ext_dir / f"{COMPANION_CHROME_EXT_ID}.json").write_text(payload, encoding="utf-8")
            except OSError:
                continue


def register_all_browsers(
    wrapper_path: Path,
    crx_path: Optional[Path] = None,
    chrom_ext_dir: Optional[Path] = None,
    extra_chromium_ids: Optional[List[str]] = None,
    register_uninstalled_common: bool = True,
) -> List[BrowserTarget]:
    targets = get_browser_targets()
    for t in targets:
        should_write = t.installed or (
            register_uninstalled_common
            and t.name in (
                "Google Chrome",
                "Chromium",
                "Microsoft Edge",
                "Brave Browser",
                "Mozilla Firefox",
            )
        )
        if not should_write:
            continue

        t.native_host_dir.mkdir(parents=True, exist_ok=True)
        for host_name in (NATIVE_HOST_NAME, COMPANION_HOST_NAME):
            if t.family == "chromium":
                manifest = build_chromium_manifest(host_name, wrapper_path, extra_chromium_ids)
            else:
                manifest = build_gecko_manifest(host_name, wrapper_path)

            out_file = t.native_host_dir / f"{host_name}.json"
            out_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        t.registered = True

    if crx_path is not None:
        register_external_crx_descriptors(crx_path, targets)
    if chrom_ext_dir is not None and chrom_ext_dir.exists():
        configure_chromium_autoload_flags(chrom_ext_dir)

    return targets


def unregister_all_browsers() -> None:
    remove_chromium_autoload_flags()
    for t in get_browser_targets():
        for host_name in (NATIVE_HOST_NAME, COMPANION_HOST_NAME):
            (t.native_host_dir / f"{host_name}.json").unlink(missing_ok=True)
        for ext_dir in t.external_ext_dirs:
            try:
                (ext_dir / f"{COMPANION_CHROME_EXT_ID}.json").unlink(missing_ok=True)
            except OSError:
                pass

    # Ekstra güvenlik: ~/.config altındaki tüm NativeMessagingHosts klasörlerinden IDM manifestlerini sil
    cfg_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    if cfg_root.is_dir():
        try:
            for nh_dir in cfg_root.rglob("NativeMessagingHosts"):
                if nh_dir.is_dir():
                    for host_name in (NATIVE_HOST_NAME, COMPANION_HOST_NAME):
                        (nh_dir / f"{host_name}.json").unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# v2.8.0 — Linux varsayılan DOSYA YÖNETİCİSİ ile klasör açma (Wine explorer DEĞİL!)
# ---------------------------------------------------------------------------

_FM_CANDIDATES = (
    "gio",
    "xdg-open",
    "dolphin",
    "nautilus",
    "thunar",
    "nemo",
    "caja",
    "pcmanfm",
    "pcmanfm-qt",
    "krusader",
    "konqueror",
)


def detect_native_file_manager() -> Optional[str]:
    for cand in _FM_CANDIDATES:
        bin_path = shutil.which(cand)
        if bin_path:
            return bin_path
    return None


def open_folder_native(folder_path: str) -> Tuple[bool, str]:
    """Verilen klasörü Wine'ın kendi dosya yöneticisi yerine Linux'un varsayılan FM'i ile açar."""
    target = Path(folder_path).expanduser()
    if not target.exists():
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, f"Klasör oluşturulamadı: {exc}"
    fm = detect_native_file_manager()
    if not fm:
        return False, "Sistemde dosya yöneticisi bulunamadı."
    name = Path(fm).name
    if name == "gio":
        cmd = [fm, "open", str(target)]
    else:
        cmd = [fm, str(target)]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True, f"{name} ile açıldı: {target}"
    except OSError as exc:
        return False, f"Dosya yöneticisi başlatılamadı: {exc}"


def wine_path_to_unix(win_path: str, wine_prefix: str) -> str:
    """C:\\... / Z:\\... biçimli Wine yollarını dosdevices eşlemesinden Linux yoluna çevirir."""
    p = (win_path or "").strip().strip('"')
    if not p:
        return ""
    if p.startswith("/") or p.startswith("~"):
        return str(Path(p).expanduser())
    dosdevices = Path(wine_prefix).expanduser() / "dosdevices"
    drive_letter = p[0].lower()
    rest = p[2:].replace("\\", "/") if len(p) > 2 and p[1] in (":",) else p.replace("\\", "/")
    link = dosdevices / f"{drive_letter}:"
    try:
        if link.is_symlink() or link.exists():
            base = str(Path(os.readlink(link)) if link.is_symlink() else link.resolve())
            return os.path.join(base, rest.lstrip("/")) if rest else base
    except OSError:
        pass
    # yedek: z: doğrudan kök, c: prefix/drive_c
    if drive_letter == "z":
        return "/" + rest.lstrip("/")
    if drive_letter == "c":
        return str(Path(wine_prefix).expanduser() / "drive_c" / rest.lstrip("/"))
    return p


def gecko_home_roots() -> List[Tuple[str, str, Path]]:
    """(hedef adı, binary adı, eklenti/profil kök HOME dizini) listesi."""
    home = Path.home()
    return [
        ("Mozilla Firefox", "firefox", home / ".mozilla"),
        ("LibreWolf", "librewolf", home / ".librewolf"),
        ("Waterfox", "waterfox", home / ".waterfox"),
        ("Zen Browser", "zen-browser", home / ".zen"),
    ]
