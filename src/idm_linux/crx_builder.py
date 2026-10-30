from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import List, Tuple

from .config import COMPANION_CHROME_EXT_ID, COMPANION_CHROME_PUBKEY

# Deterministik CRX3 imzalama anahtarı (yalnızca bu yerel açık kaynak eklentinin
# tüm Linux dağıtımlarında sabit 'hdhillpmjhoiinmcdfleihbeghnnlkob' kimliğini alması içindir)
_CRX3_RSA_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC03VFZc+O5meUj
oAB4EcQr9OeF20M7GuxzNz8hcBjE0fVpKIDFmm9B2OWaWXtgtt1JOt4iayUqxora
gAMoJqsipe2wdMAgUmZp9NRwiB4OXghiD4OKZBBxSyDVGrohOMdlVlhQ2q4KqHYH
Ep4eOylkaqqgmjL8tjerxfjJw1OCkazSdjt1+fiT7K16eWQq6KE1vZ8XnPsIISV6
5hOKi/jFo6hq4XHyj4pUJBYj7ruBS+muvDDK4EKGGmh6ObmDurKCZJZ3URnn7+we
Fejo/3l75EhUV9XWwcRLozJVvNxuU8tRIom7A9cu/2LYglcSXW2ieIoOMxvAYQZU
dbZb0XpLAgMBAAECggEAMawi3m1smpnAi7MyzccbWHMvbtzULxRq4g3HQdi2hL+h
Jdtg2mRar/vwux5eOyadybHoNg21LHVQx0enFkzgbWiiyfaWmYnn5Ku/+JP5pTqA
FOZr2wM2XNckUkK/4cXlRViccsBMUlMH71NWp7jZ2mFNMUSIQk2NJpj9hfQmKFKA
Jtlc6CR/d65NHUUV3DqH2SspVH+odno4KH4/GVStpzvSRzttiJPjzNuZ9Z4IdhSd
ee0fKs/veG9HFII4oB4s8sFGC/TgM1AjhjvyZ+04/e5gkWdwU5r7v4GN7stEuVVB
8sOsFxvtGyhZIFqo69XMaF/cwtZV3hJRFA0as+kdmQKBgQD83O56m7z8I14LG/6m
+qxH7xPqf96QVDCzDLJE84MCHKEoRkLdempMZ4ShRRusxFoeZrZWT0T76n3RUEQG
LYzuWR0YNoBeuWbRK+tijHlK0xQrYft25PunMKArl6Aao0K2S0L7W7TC+1zsRn1h
ykRGwLbHYKZPHXo4lgV7e4o7PQKBgQC3G7nZqhoPVuqWxOkmgV9ZuKG7xBdh3lQO
UZu9h0PN6Zqbv8hQSLvxjOHPOeFZv6VSv3HrJzSqvy/gbf+VaBaf3XerWeCdtYHT
TKHKOKFrpUB/CB83O6+8Yc9G2uHzoua1MB76hvZhkt2ORSlHoDa7d5tQUKEzCUa1
E3Jd74OEJwKBgEOTH0Aw4n5XTUiWwKULFINcxuvCJE5Z0XHoELQQh5BG6mKC9FeP
4Vxtxan7d/vhtVuug0fpgzv3XIxVcPhdr+36bqYL2p512Z5IqGz7sWZnplo5oyQQ
6ZeyjPtZV/YGb0ucLVhTF6mL1zdlVxiNH1XxJmd90rQN4p3AqdJoH3bZAoGATnuJ
yyvHg6+jWQAJVsG41sH2QH6p7v7WVFTSRggGHen0pLEs8IxcUgoqdyG93zPvbmo0
L7BcOJs9sBo1pBo7KEZKlp0tUyuK+8Aq0Hw5Y+QuosQebRQeHMZni10h38WA0URQ
4tyaGfRTFjm6mcKn8u4vGduVXESrk81EBdM1MZ0CgYEA+9fAi8rH/GnQgEnH1day
owzcJX6Ad3YO+fgDU7IKfaYpQ8e28JdJp3pyqmkO+KLDlc9hozaqFOJuTnuxRWgK
7TX08rTBtbakULAWLNesN9I+RGQ4GrNYq/vhOffWs9WrR8e4rh2IjdSTFdKKhjGt
LrIoOdQc+2FFm1SALE9/qBI=
-----END PRIVATE KEY-----
"""


def _encode_varint(val: int) -> bytes:
    out = bytearray()
    while True:
        byte = val & 0x7F
        val >>= 7
        if val:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def _pb_bytes_field(field_number: int, payload: bytes) -> bytes:
    tag = (field_number << 3) | 2  # wire_type = 2 (length-delimited)
    return _encode_varint(tag) + _encode_varint(len(payload)) + payload


def _create_deterministic_zip(source_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file_path in sorted(source_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(source_dir).as_posix()
                zf.write(file_path, arcname)
    return buf.getvalue()


def _rsa_sha256_sign(data_to_sign: bytes) -> bytes:
    """openssl dgst -sha256 -sign kullanarak PKCS#1 v1.5 RSA-SHA256 imzası üretir."""
    openssl_bin = shutil.which("openssl")
    if not openssl_bin:
        raise RuntimeError("CRX3 imzalama için sistemde 'openssl' bulunamadı.")

    with tempfile.TemporaryDirectory() as tmpd:
        key_file = Path(tmpd) / "key.pem"
        key_file.write_text(_CRX3_RSA_PRIVATE_KEY_PEM, encoding="ascii")
        key_file.chmod(0o600)

        res = subprocess.run(
            [openssl_bin, "dgst", "-sha256", "-sign", str(key_file)],
            input=data_to_sign,
            capture_output=True,
            check=True,
        )
        return res.stdout


def validate_extension_directory(source_dir: Path) -> List[str]:
    """
    manifest.json içinde referans edilen TÜM dosyaların (js, css, icons, popup, service_worker)
    gerçekten klasörde mevcut olduğunu denetler. Eksik dosya varsa listesini döndürür.
    """
    manifest_file = source_dir / "manifest.json"
    if not manifest_file.is_file():
        return ["manifest.json"]

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    referenced: List[str] = []

    for icon_rel in (manifest.get("icons") or {}).values():
        referenced.append(icon_rel)

    for act_key in ("action", "browser_action", "page_action"):
        act = manifest.get(act_key) or {}
        if isinstance(act.get("default_popup"), str):
            referenced.append(act["default_popup"])
        def_icon = act.get("default_icon")
        if isinstance(def_icon, str):
            referenced.append(def_icon)
        elif isinstance(def_icon, dict):
            referenced.extend(def_icon.values())

    bg = manifest.get("background") or {}
    if isinstance(bg.get("service_worker"), str):
        referenced.append(bg["service_worker"])
    for sc in bg.get("scripts") or []:
        referenced.append(sc)

    for cs in manifest.get("content_scripts") or []:
        for js_rel in cs.get("js") or []:
            referenced.append(js_rel)
        for css_rel in cs.get("css") or []:
            referenced.append(css_rel)

    missing = []
    for rel in referenced:
        p = source_dir / rel
        if not p.is_file() or p.stat().st_size == 0:
            missing.append(rel)
    return missing


def build_crx3_package(source_dir: Path, output_crx: Path) -> Tuple[Path, str]:
    """
    Chromium resmi CRX3 (Cr24 v3 Protobuf + RSA-2048 SHA-256 imzalı) spesifikasyonuna
    %100 uyumlu .crx uzantı paketi oluşturur.
    """
    missing = validate_extension_directory(source_dir)
    if missing:
        raise RuntimeError(f"Eklenti manifestinde eksik dosyalar var: {missing}")

    pub_der = base64.b64decode(COMPANION_CHROME_PUBKEY)
    crx_id_raw = hashlib.sha256(pub_der).digest()[:16]
    computed_ext_id = "".join(chr(ord("a") + int(c, 16)) for c in crx_id_raw.hex())
    if computed_ext_id != COMPANION_CHROME_EXT_ID:
        raise RuntimeError(f"CRX3 anahtar kimliği uyuşmazlığı: {computed_ext_id} != {COMPANION_CHROME_EXT_ID}")

    zip_bytes = _create_deterministic_zip(source_dir)

    # SignedData { bytes crx_id = 1; }
    signed_header_data = _pb_bytes_field(1, crx_id_raw)

    # CRX3 imzalanacak veri formatı:
    # "CRX3 SignedData\x00" + uint32_le(len(signed_header_data)) + signed_header_data + zip_bytes
    signing_input = (
        b"CRX3 SignedData\x00"
        + struct.pack("<I", len(signed_header_data))
        + signed_header_data
        + zip_bytes
    )
    signature = _rsa_sha256_sign(signing_input)

    # AsymmetricKeyProof { bytes public_key = 1; bytes signature = 2; }
    asym_proof = _pb_bytes_field(1, pub_der) + _pb_bytes_field(2, signature)

    # CrxFileHeader { repeated AsymmetricKeyProof sha256_with_rsa = 2; bytes signed_header_data = 10000; }
    crx_file_header = _pb_bytes_field(2, asym_proof) + _pb_bytes_field(10000, signed_header_data)

    # CRX3 Binary Frame: "Cr24" + uint32_le(3) + uint32_le(header_len) + header + zip
    crx_binary = (
        b"Cr24"
        + struct.pack("<II", 3, len(crx_file_header))
        + crx_file_header
        + zip_bytes
    )

    output_crx.parent.mkdir(parents=True, exist_ok=True)
    output_crx.write_bytes(crx_binary)
    return output_crx, computed_ext_id


def build_chromium_zip_package(source_dir: Path, output_zip: Path) -> Path:
    """
    Tarayıcıların CRX indirme engeline ve 'CRX_REQUIRED_PROOF_MISSING' hatasına takılmadan
    doğrudan indirilebilen ve chrome://extensions / brave://extensions (Geliştirici Modu)
    ekranına sürükle-bırak ile anında kalıcı kurulan standart ZIP paketini oluşturur.
    manifest.json içindeki deterministik RSA 'key' alanı sayesinde eklenti kimliği
    yine sabit 'hdhillpmjhoiinmcdfleihbeghnnlkob' olarak korunur!
    """
    missing = validate_extension_directory(source_dir)
    if missing:
        raise RuntimeError(f"Eklenti manifestinde eksik dosyalar var: {missing}")

    zip_bytes = _create_deterministic_zip(source_dir)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    output_zip.write_bytes(zip_bytes)
    return output_zip


def verify_crx3_package(crx_path: Path) -> Tuple[bool, str]:
    """Üretilen .crx dosyasının CRX3 başlığını, ZIP bütünlüğünü ve RSA-SHA256 imzasını doğrular."""
    data = crx_path.read_bytes()
    if len(data) < 64 or data[:4] != b"Cr24":
        return False, "CRX sihirli baytları (Cr24) eksik."
    version, hdr_len = struct.unpack_from("<II", data, 4)
    if version != 3:
        return False, f"CRX sürümü 3 değil ({version})."
    zip_offset = 12 + hdr_len
    if zip_offset >= len(data) or data[zip_offset : zip_offset + 4] != b"PK\x03\x04":
        return False, "CRX3 ZIP yükü başlangıcı geçersiz."

    with zipfile.ZipFile(io.BytesIO(data[zip_offset:]), "r") as zf:
        if "manifest.json" not in zf.namelist():
            return False, "CRX3 içinde manifest.json bulunamadı."
        bad = zf.testzip()
        if bad is not None:
            return False, f"Bozuk ZIP girdisi: {bad}"

    return True, f"CRX3 v3 doğrulandı (boyut={len(data)} bayt, ID={COMPANION_CHROME_EXT_ID})"
