from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("idm_linux.browser_cookies")

# Linux Chromium/Brave PBKDF2 sabitleri (os_crypt_linux.cc)
_CHROMIUM_SALT = b"saltysalt"
_CHROMIUM_ITERATIONS = 1
_CHROMIUM_KEY_LEN = 16
_CHROMIUM_CBC_IV = b" " * 16
_PEANUTS_DERIVED_KEY = hashlib.pbkdf2_hmac(
    "sha1", b"peanuts", _CHROMIUM_SALT, _CHROMIUM_ITERATIONS, _CHROMIUM_KEY_LEN
)

_KEY_CACHE_LOCK = threading.Lock()
_DERIVED_KEYS_CACHE: Optional[Tuple[float, List[bytes]]] = None


def _load_libcrypto() -> Optional[ctypes.CDLL]:
    """Python ssl modülünün veya sistemin zaten yüklediği libcrypto paylaşımlı kütüphanesini bulur."""
    candidates: List[str] = []
    found = ctypes.util.find_library("crypto")
    if found:
        candidates.append(found)
    candidates.extend(["libcrypto.so.3", "libcrypto.so.1.1", "libcrypto.so"])
    for name in candidates:
        try:
            lib = ctypes.CDLL(name)
            if hasattr(lib, "EVP_DecryptInit_ex") and hasattr(lib, "EVP_aes_128_cbc"):
                lib.EVP_CIPHER_CTX_new.restype = ctypes.c_void_p
                lib.EVP_CIPHER_CTX_free.argtypes = [ctypes.c_void_p]
                lib.EVP_aes_128_cbc.restype = ctypes.c_void_p
                lib.EVP_DecryptInit_ex.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_char_p,
                    ctypes.c_char_p,
                ]
                lib.EVP_DecryptInit_ex.restype = ctypes.c_int
                lib.EVP_DecryptUpdate.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_char_p,
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.c_char_p,
                    ctypes.c_int,
                ]
                lib.EVP_DecryptUpdate.restype = ctypes.c_int
                lib.EVP_DecryptFinal_ex.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_char_p,
                    ctypes.POINTER(ctypes.c_int),
                ]
                lib.EVP_DecryptFinal_ex.restype = ctypes.c_int
                return lib
        except OSError:
            continue
    return None


_LIBCRYPTO = _load_libcrypto()


def _aes_128_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes = _CHROMIUM_CBC_IV) -> Optional[bytes]:
    """Sıfır harici Python paketiyle (stdlib ctypes -> libcrypto veya openssl CLI) AES-128-CBC şifre çözme."""
    if not ciphertext or (len(ciphertext) % 16) != 0 or len(key) != 16:
        return None

    if _LIBCRYPTO is not None:
        ctx = _LIBCRYPTO.EVP_CIPHER_CTX_new()
        if not ctx:
            return None
        try:
            if _LIBCRYPTO.EVP_DecryptInit_ex(ctx, _LIBCRYPTO.EVP_aes_128_cbc(), None, key, iv) != 1:
                return None
            out_buf = ctypes.create_string_buffer(len(ciphertext) + 32)
            out_len1 = ctypes.c_int(0)
            if _LIBCRYPTO.EVP_DecryptUpdate(ctx, out_buf, ctypes.byref(out_len1), ciphertext, len(ciphertext)) != 1:
                return None
            tail_ptr = ctypes.cast(ctypes.addressof(out_buf) + out_len1.value, ctypes.c_char_p)
            out_len2 = ctypes.c_int(0)
            if _LIBCRYPTO.EVP_DecryptFinal_ex(ctx, tail_ptr, ctypes.byref(out_len2)) != 1:
                return None
            total = out_len1.value + out_len2.value
            return out_buf.raw[:total]
        finally:
            _LIBCRYPTO.EVP_CIPHER_CTX_free(ctx)

    openssl_bin = shutil.which("openssl")
    if openssl_bin:
        try:
            res = subprocess.run(
                [
                    openssl_bin,
                    "enc",
                    "-d",
                    "-aes-128-cbc",
                    "-K",
                    key.hex(),
                    "-iv",
                    iv.hex(),
                ],
                input=ciphertext,
                capture_output=True,
                timeout=1.5,
                check=False,
            )
            if res.returncode == 0:
                return res.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def _discover_keyring_derived_keys() -> List[bytes]:
    """
    Açık masaüstü oturumundaki (GNOME Keyring / Secret Service / KWallet) Chromium/Brave/Chrome
    Safe Storage parolalarından PBKDF2 AES-128 anahtarlarını türetir ve önbellekler.
    """
    global _DERIVED_KEYS_CACHE
    now = time.time()
    with _KEY_CACHE_LOCK:
        if _DERIVED_KEYS_CACHE is not None and (now - _DERIVED_KEYS_CACHE[0]) < 300.0:
            return list(_DERIVED_KEYS_CACHE[1])

    passwords: List[bytes] = []
    secret_tool = shutil.which("secret-tool")
    if secret_tool:
        for app_name in ("brave", "chrome", "chromium", "vivaldi", "opera", "microsoft-edge"):
            try:
                res = subprocess.run(
                    [secret_tool, "lookup", "application", app_name],
                    capture_output=True,
                    timeout=0.45,
                    check=False,
                )
                if res.returncode == 0 and res.stdout:
                    pw = res.stdout.rstrip(b"\r\n")
                    if pw and pw not in passwords:
                        passwords.append(pw)
            except (OSError, subprocess.SubprocessError):
                continue

        if not passwords:
            for schema_attr in (
                ["xdg:schema", "chrome_libsecret_os_crypt_password_v2"],
                ["xdg:schema", "chrome_libsecret_os_crypt_password_v1"],
            ):
                try:
                    res = subprocess.run(
                        [secret_tool, "search", "--all", *schema_attr],
                        capture_output=True,
                        text=True,
                        timeout=0.6,
                        check=False,
                    )
                    for line in (res.stdout or "").splitlines():
                        if line.startswith("secret = "):
                            pw_b = line.split("secret = ", 1)[1].strip().encode("utf-8")
                            if pw_b and pw_b not in passwords:
                                passwords.append(pw_b)
                except (OSError, subprocess.SubprocessError):
                    continue

    derived: List[bytes] = []
    for pw in passwords:
        dk = hashlib.pbkdf2_hmac("sha1", pw, _CHROMIUM_SALT, _CHROMIUM_ITERATIONS, _CHROMIUM_KEY_LEN)
        if dk not in derived:
            derived.append(dk)
    if _PEANUTS_DERIVED_KEY not in derived:
        derived.append(_PEANUTS_DERIVED_KEY)

    with _KEY_CACHE_LOCK:
        _DERIVED_KEYS_CACHE = (now, derived)
    return list(derived)


def _decode_chromium_cookie_value(
    raw_value: str,
    encrypted_value: bytes,
    host_key: str,
    meta_version: int,
    derived_keys: List[bytes],
) -> str:
    if raw_value:
        return raw_value
    if not encrypted_value:
        return ""

    if not (encrypted_value.startswith(b"v10") or encrypted_value.startswith(b"v11")):
        try:
            return encrypted_value.decode("utf-8")
        except UnicodeDecodeError:
            return ""

    payload = encrypted_value[3:]
    keys_to_try = (
        [_PEANUTS_DERIVED_KEY] + [k for k in derived_keys if k != _PEANUTS_DERIVED_KEY]
        if encrypted_value.startswith(b"v10")
        else derived_keys
    )
    host_digest = hashlib.sha256(host_key.encode("utf-8")).digest()

    for key in keys_to_try:
        pt = _aes_128_cbc_decrypt(payload, key)
        if not pt:
            continue

        # Chromium >= 130 (Cookies DB meta version >= 24) ilk 32 bayta SHA256(host_key) yazar
        candidate = pt
        if len(pt) >= 32 and (pt[:32] == host_digest or meta_version >= 24):
            candidate = pt[32:]

        try:
            decoded = candidate.decode("utf-8")
            if all(ord(ch) >= 0x20 and ch not in "\x7f;" for ch in decoded):
                return decoded
        except UnicodeDecodeError:
            continue
    return ""


def _domain_sql_patterns(hostname: str) -> List[str]:
    host = hostname.lower().strip(".")
    if not host or host in ("localhost", "127.0.0.1"):
        return []
    parts = host.split(".")
    patterns: List[str] = [host, f".{host}"]
    # Örn. sub.arena.ai -> arena.ai, .arena.ai
    if len(parts) >= 2:
        for i in range(1, len(parts) - 1):
            parent = ".".join(parts[i:])
            if "." in parent:
                if parent not in patterns:
                    patterns.append(parent)
                dot_p = f".{parent}"
                if dot_p not in patterns:
                    patterns.append(dot_p)
    return patterns


def _copy_sqlite_with_wal(db_path: Path, tmp_dir: Path) -> Path:
    dst = tmp_dir / db_path.name
    shutil.copy2(db_path, dst)
    for suffix in ("-wal", "-shm", "-journal"):
        side = Path(str(db_path) + suffix)
        if side.is_file():
            try:
                shutil.copy2(side, Path(str(dst) + suffix))
            except OSError:
                pass
    return dst


def _find_chromium_cookie_dbs() -> List[Path]:
    cfg_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    if not cfg_root.is_dir():
        return []

    found: List[Tuple[float, Path]] = []
    # Hem doğrudan ~/.config/<Browser> hem de ~/.config/<Vendor>/<Browser> (örn. BraveSoftware/Brave-Origin-Nightly)
    candidate_roots: List[Path] = []
    try:
        for d1 in cfg_root.iterdir():
            if not d1.is_dir():
                continue
            if (d1 / "Local State").is_file() or (d1 / "Default").is_dir():
                candidate_roots.append(d1)
            elif d1.name in (
                "BraveSoftware",
                "Google",
                "Thorium",
                "Microsoft",
                "Vivaldi",
                "Opera Software",
                "Yandex",
                "Helium",
            ):
                for d2 in d1.iterdir():
                    if d2.is_dir() and ((d2 / "Local State").is_file() or (d2 / "Default").is_dir()):
                        candidate_roots.append(d2)
    except OSError:
        pass

    for broot in candidate_roots:
        try:
            prof_dirs = [broot / "Default"] + [
                p for p in broot.iterdir() if p.is_dir() and (p.name.startswith("Profile ") or p.name == "Guest Profile")
            ]
            # Opera gibi doğrudan kök klasörde Cookies tutanlar
            prof_dirs.append(broot)
            for pdir in prof_dirs:
                for rel in ("Network/Cookies", "Cookies"):
                    cdb = pdir / rel
                    if cdb.is_file():
                        try:
                            found.append((cdb.stat().st_mtime, cdb))
                        except OSError:
                            pass
        except OSError:
            continue

    found.sort(key=lambda item: item[0], reverse=True)
    seen = set()
    ordered: List[Path] = []
    for _mt, p in found:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            ordered.append(p)
    return ordered


def _find_firefox_cookie_dbs() -> List[Path]:
    home = Path.home()
    roots = [
        home / ".mozilla" / "firefox",
        home / ".zen",
        home / ".librewolf",
        home / ".waterfox",
        home / ".floorp",
    ]
    found: List[Tuple[float, Path]] = []
    for r in roots:
        if not r.is_dir():
            continue
        try:
            for sub in r.iterdir():
                cdb = sub / "cookies.sqlite"
                if cdb.is_file():
                    found.append((cdb.stat().st_mtime, cdb))
        except OSError:
            continue
    found.sort(key=lambda item: item[0], reverse=True)
    return [p for _mt, p in found]


def merge_cookie_headers(*cookie_strings: str) -> str:
    """
    Birden fazla 'k1=v1; k2=v2' başlığını sırasını ve en taze değerini koruyarak tekilleştirir.
    İlk argümanlar daha yüksek önceliğe sahiptir (örn. eklentinin canlı çerezi > yerel DB çerezi).
    """
    merged: Dict[str, str] = {}
    order: List[str] = []
    for raw in cookie_strings:
        if not raw:
            continue
        for part in raw.split(";"):
            item = part.strip()
            if not item or "=" not in item:
                continue
            k, v = item.split("=", 1)
            k = k.strip()
            v = v.strip()
            if not k or not v:
                continue
            if k not in merged:
                merged[k] = v
                order.append(k)
    return "; ".join(f"{k}={merged[k]}" for k in order)


def extract_browser_cookies_for_url(url: str) -> str:
    """
    Açık veya kurulu tarayıcıların (Brave-Origin-Nightly, Brave, Chrome, Chromium, Edge, Firefox vb.)
    yerel SQLite veritabanlarından verilen URL ile eşleşen tüm oturum çerezlerini (HttpOnly ve
    Partitioned dahil) okur ve 'name=value; ...' biçiminde döndürür.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return ""

    hostname = (parsed.hostname or "").lower()
    req_path = parsed.path or "/"
    is_https = parsed.scheme.lower() == "https"
    hosts = _domain_sql_patterns(hostname)
    if not hosts:
        return ""

    collected_headers: List[str] = []
    placeholders = ",".join("?" for _ in hosts)

    # 1. Chromium / Brave / Chrome / Edge profilleri (en güncel profilden başlayarak)
    chrom_dbs = _find_chromium_cookie_dbs()
    if chrom_dbs:
        derived_keys = _discover_keyring_derived_keys()
        now_webkit_us = int((time.time() + 11644473600.0) * 1_000_000)

        for db_file in chrom_dbs[:5]:
            try:
                with tempfile.TemporaryDirectory(prefix="idmlinux_ck_") as tmpd:
                    copied = _copy_sqlite_with_wal(db_file, Path(tmpd))
                    conn = sqlite3.connect(f"file:{copied}?mode=ro", uri=True, timeout=1.0)
                    try:
                        cur = conn.cursor()
                        meta_ver = 0
                        try:
                            row = cur.execute("SELECT value FROM meta WHERE key='version'").fetchone()
                            if row is not None:
                                meta_ver = int(row[0])
                        except sqlite3.Error:
                            pass

                        rows = cur.execute(
                            f"SELECT host_key, name, value, encrypted_value, path, is_secure, expires_utc "
                            f"FROM cookies WHERE host_key IN ({placeholders}) "
                            f"ORDER BY LENGTH(path) DESC",
                            hosts,
                        ).fetchall()

                        pairs: List[str] = []
                        seen_names = set()
                        for host_key, name, val, enc_val, c_path, is_sec, exp_utc in rows:
                            if not name or name in seen_names:
                                continue
                            if is_sec and not is_https:
                                continue
                            if exp_utc and int(exp_utc) > 0 and int(exp_utc) < now_webkit_us:
                                continue
                            c_path_s = c_path or "/"
                            if not req_path.startswith(c_path_s):
                                continue
                            enc_bytes = bytes(enc_val) if enc_val is not None else b""
                            decoded = _decode_chromium_cookie_value(
                                val or "", enc_bytes, host_key or "", meta_ver, derived_keys
                            )
                            if decoded:
                                seen_names.add(name)
                                pairs.append(f"{name}={decoded}")
                        if pairs:
                            collected_headers.append("; ".join(pairs))
                    finally:
                        conn.close()
            except Exception as exc:
                logger.debug("Chromium çerez okuma atlandı (%s): %s", db_file, exc)

    # 2. Firefox / Zen / LibreWolf profilleri
    now_sec = int(time.time())
    for ff_db in _find_firefox_cookie_dbs()[:4]:
        try:
            with tempfile.TemporaryDirectory(prefix="idmlinux_ffck_") as tmpd:
                copied = _copy_sqlite_with_wal(ff_db, Path(tmpd))
                conn = sqlite3.connect(f"file:{copied}?mode=ro", uri=True, timeout=1.0)
                try:
                    cur = conn.cursor()
                    rows = cur.execute(
                        f"SELECT name, value, path, isSecure, expiry "
                        f"FROM moz_cookies WHERE host IN ({placeholders}) "
                        f"ORDER BY LENGTH(path) DESC",
                        hosts,
                    ).fetchall()
                    pairs = []
                    seen_names = set()
                    for name, val, c_path, is_sec, expiry in rows:
                        if not name or not val or name in seen_names:
                            continue
                        if is_sec and not is_https:
                            continue
                        if expiry and int(expiry) > 0 and int(expiry) < now_sec:
                            continue
                        if not req_path.startswith(c_path or "/"):
                            continue
                        seen_names.add(name)
                        pairs.append(f"{name}={val}")
                    if pairs:
                        collected_headers.append("; ".join(pairs))
                finally:
                    conn.close()
        except Exception as exc:
            logger.debug("Firefox çerez okuma atlandı (%s): %s", ff_db, exc)

    return merge_cookie_headers(*collected_headers)
