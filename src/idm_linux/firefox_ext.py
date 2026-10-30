"""
v2.8.0 — Firefox / Gecko XPI Kurulum Çözümü ("This add-on could not be installed
because it has not been verified" hatasının kökten giderilmesi).

Firefox RELEASE sürümleri imzasız XPI'yi about:config ile BİLE kabul etmez (Mozilla
tarafından kilitlenmiştir). Bu modül üç katmanlı kesin çözüm uygular:

  1) RESMİ İMZALI IDM XPI'si (idmmzcc3.xpi — AMO imzalı, mozilla_cc3@internetdownloadmanager.com):
     IDM kurulum paketinden çıkarılıp profil `extensions/` dizinine sideload edilir.
     İMZALI olduğu için RELEASE Firefox dahil HER Gecko sürümünde doğrulamadan geçer ve
     indirme yakalamayı köprü WebSocket'imize (17801) bağlar.
  2) İMZASIZ COMPANION XPI: yalnızca imza kontrolünün kapatılabildiği derlemelerde
     (ESR / Nightly / Developer / unbranded / pref'i sayan bazı Linux release derlemeleri)
     `user.js` pref'leri + `extensions.autoDisableScopes=0` ile profil sideload yapılır.
  3) Sistem/distro eklenti dizini (`/usr/share/mozilla/extensions/{app-id}`) yazılabilirse
     companion oraya da bırakılır (sistem eklentileri imza muafiyeti alabilir).
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import COMPANION_FIREFOX_EXT_ID, OFFICIAL_FIREFOX_EXT_ID, get_data_dir, setup_logger

logger = setup_logger("firefox_ext", "installer.log")

GECKO_APP_ID = "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}"

# İmza zorunluluğunun pref ile kapatılabildiği Gecko derlemeleri (anahtar alt kümesi)
SIGNING_TOGGLE_FLAVORS = ("esr", "nightly", "devedition", "developer", "librewolf", "waterfox", "tor", "unbranded", "pcxfirefox")


def official_xpi_cache_path() -> Path:
    return get_data_dir(create=True) / "ext" / "idmmzcc3.xpi"


def cache_official_firefox_xpi(unpacked_installer_dir: Path) -> Optional[Path]:
    """IDM SFX paketinden çıkan AMO imzalı idmmzcc3.xpi'yi kalıcı önbelleğe kopyalar."""
    dest = official_xpi_cache_path()
    for cand in sorted(unpacked_installer_dir.glob("idmmzcc*.xpi")):
        try:
            with zipfile.ZipFile(cand) as zf:
                names = zf.namelist()
            if "META-INF/mozilla.rsa" not in names or "manifest.json" not in names:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cand, dest)
            logger.info("Resmi imzalı Firefox XPI önbelleğe alındı: %s", dest)
            return dest
        except (OSError, zipfile.BadZipFile):
            continue
    return dest if dest.exists() else None


def firefox_allows_unsigned(binary_name: str) -> bool:
    bn = (binary_name or "").lower()
    return any(k in bn for k in SIGNING_TOGGLE_FLAVORS)


def find_gecko_profile_dirs(home_root: Path) -> List[Path]:
    """profiles.ini'ye bakmaksızın tüm Gecko profil dizinlerini bulur (*.default*)."""
    found: List[Path] = []
    if not home_root.is_dir():
        return found

    def _is_profile(d: Path) -> bool:
        try:
            return d.is_dir() and (
                ".default" in d.name
                or d.name.startswith(("default", "dev-edition", "nightly"))
                or (d / "prefs.js").is_file()
            )
        except OSError:
            return False

    try:
        for entry in home_root.iterdir():
            if not entry.is_dir():
                continue
            if _is_profile(entry):
                found.append(entry)
                continue
            # ~/.mozilla/firefox/*.default* gibi ikinci seviye profil klasörleri
            try:
                for sub in entry.iterdir():
                    if _is_profile(sub):
                        found.append(sub)
            except OSError:
                continue
    except OSError:
        pass
    return found


def _write_user_js_prefs(profile_dir: Path, allow_unsigned: bool) -> None:
    prefs: List[Tuple[str, str]] = [
        ("extensions.autoDisableScopes", "0"),
        ("extensions.enabledScopes", "15"),
        ("xpinstall.enabled", "true"),
    ]
    if allow_unsigned:
        prefs.append(("xpinstall.signatures.required", "false"))
    user_js = profile_dir / "user.js"
    existing = user_js.read_text(encoding="utf-8", errors="ignore") if user_js.exists() else ""
    additions = []
    for key, val in prefs:
        marker = f'user_pref("{key}"'
        if marker not in existing:
            additions.append(f'user_pref("{key}", {val});')
    if additions:
        block = "\n// IDM-Linux v2.8.0 Gecko entegrasyonu\n" + "\n".join(additions) + "\n"
        with user_js.open("a", encoding="utf-8") as fh:
            fh.write(block)


def _sideload_xpi(profile_dir: Path, xpi_path: Path, ext_id: str, unpack: bool) -> bool:
    ext_dir = profile_dir / "extensions"
    try:
        ext_dir.mkdir(parents=True, exist_ok=True)
        if unpack:
            target = ext_dir / ext_id
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(xpi_path) as zf:
                zf.extractall(target)
        else:
            shutil.copy2(xpi_path, ext_dir / f"{ext_id}.xpi")
        # Eklenti önbelleğini zorla yenilet
        for stale in ("extensions.json",):
            sp = profile_dir / stale
            if sp.exists():
                sp.unlink(missing_ok=True)
        sc = profile_dir / "startupCache"
        if sc.is_dir():
            shutil.rmtree(sc, ignore_errors=True)
        return True
    except (OSError, zipfile.BadZipFile) as exc:
        logger.warning("XPI sideload başarısız (%s): %s", ext_id, exc)
        return False


def install_firefox_extensions_robust(
    gecko_targets: List[Tuple[str, str, Path]],
    companion_xpi: Path,
    official_xpi: Optional[Path],
) -> Dict[str, List[str]]:
    """
    gecko_targets: [(hedef_adı, binary_adı, native_host_home_kökü)] ör. ("Mozilla Firefox", "firefox", ~/.mozilla)
    Dönüş: {"signed": [...], "companion": [...], "system": [...]}
    """
    report: Dict[str, List[str]] = {"signed": [], "companion": [], "system": []}

    for target_name, binary_name, home_root in gecko_targets:
        profiles = find_gecko_profile_dirs(home_root)
        if not profiles:
            # Profil yoksa (ilk kurulum) kök dizini oluşturup default profil dizini hazırla
            app_dir = next((p for p in ("firefox", "librewolf", "waterfox", "zen") if p in str(home_root)), "firefox")
            default_prof = home_root / app_dir / "idm-linux.default"
            default_prof.mkdir(parents=True, exist_ok=True)
            profiles = [default_prof]

        allow_unsigned = firefox_allows_unsigned(binary_name)
        for prof in profiles:
            _write_user_js_prefs(prof, allow_unsigned)
            if official_xpi and official_xpi.exists():
                if _sideload_xpi(prof, official_xpi, OFFICIAL_FIREFOX_EXT_ID, unpack=False):
                    report["signed"].append(f"{target_name}:{prof.name}")
            if allow_unsigned and companion_xpi.exists():
                if _sideload_xpi(prof, companion_xpi, COMPANION_FIREFOX_EXT_ID, unpack=True):
                    report["companion"].append(f"{target_name}:{prof.name}")

    # 3) Sistem/distro eklenti dizini (yazılabilirse — imza muafiyeti alabilir)
    if companion_xpi.exists():
        for sys_dir in (
            Path("/usr/share/mozilla/extensions") / GECKO_APP_ID,
            Path("/usr/lib/mozilla/extensions") / GECKO_APP_ID,
        ):
            try:
                sys_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(companion_xpi, sys_dir / f"{COMPANION_FIREFOX_EXT_ID}.xpi")
                report["system"].append(str(sys_dir))
            except OSError:
                continue

    logger.info("Firefox eklenti kurulum raporu: %s", json.dumps(report, ensure_ascii=False))
    return report
