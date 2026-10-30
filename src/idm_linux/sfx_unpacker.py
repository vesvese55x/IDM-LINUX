from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path
from typing import Dict, List, Tuple


def _pe_overlay_offset(data: bytes) -> int:
    """PE32 başlığından bölümlerin bittiği ve Tonec SFX sıkıştırılmış verisinin başladığı ofseti bulur."""
    if len(data) < 0x100 or data[:2] != b"MZ":
        raise ValueError("Geçerli bir PE (MZ) çalıştırılabilir dosyası değil.")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew : e_lfanew + 4] != b"PE\x00\x00":
        raise ValueError("Geçerli bir PE imzası bulunamadı.")
    num_sections = struct.unpack_from("<H", data, e_lfanew + 6)[0]
    opt_hdr_size = struct.unpack_from("<H", data, e_lfanew + 20)[0]
    sec_offset = e_lfanew + 24 + opt_hdr_size

    max_end = 0
    for i in range(num_sections):
        s = sec_offset + i * 40
        rsize, rptr = struct.unpack_from("<II", data, s + 16)
        end = rptr + rsize
        if end > max_end:
            max_end = end
    return max_end


def _extract_tonec_records(data: bytes, start_offset: int) -> List[bytes]:
    """
    Tonec SFX ikili kapsayıcısını kesin 32-bayt kayıt başlığıyla okur:
      struct TonecEntryHeader {
          uint32_t attr_or_flags;
          uint32_t compressed_size;
          uint64_t creation_time;
          uint64_t last_access_time;
          uint64_t last_write_time;
      }; // toplam 32 bayt, hemen ardından zlib akışı (compressed_size bayt) gelir.
    """
    records: List[bytes] = []
    pos = start_offset
    total = len(data)

    while pos + 32 <= total:
        _flags, comp_size = struct.unpack_from("<II", data, pos)
        z_start = pos + 32
        z_end = z_start + comp_size
        if comp_size == 0 or z_end > total:
            break
        chunk = data[z_start:z_end]
        try:
            raw_file = zlib.decompress(chunk)
        except zlib.error:
            # Beklenmeyen ek imza/sertifika kuyruğuna ulaşıldıysa dur
            break
        records.append(raw_file)
        pos = z_end

    return records


def parse_dest_manifest(manifest_bytes: bytes) -> List[Tuple[int, str]]:
    """Tonec <DEST> haritasından <P1="..."> .. <PN="..."> kayıtlarını sırayla çıkarır."""
    text = manifest_bytes.decode("latin1", errors="ignore")
    entries: List[Tuple[int, str]] = []
    for m in re.finditer(r'<P(\d+)="([^"]+)"', text):
        idx = int(m.group(1))
        rel_win_path = m.group(2).replace("\\", "/").lstrip("/")
        entries.append((idx, rel_win_path))
    return entries


def unpack_idm_installer(installer_exe: Path, target_dir: Path) -> Dict[str, Path]:
    """
    idman643build16.exe dosyasını 32-bayt Tonec SFX blok tablosuyla %100 birebir
    hedef klasöre çıkartır (Wine GUI takılmalarına karşı Deterministik Kurulum & Onarım Motoru).
    """
    raw = installer_exe.read_bytes()
    overlay_off = _pe_overlay_offset(raw)
    records = _extract_tonec_records(raw, overlay_off)
    if len(records) < 10 or b"<DEST>" not in records[0][:64]:
        raise RuntimeError("Tonec IDM SFX kurulum haritası (<DEST>) çözümlenemedi.")

    manifest_entries = parse_dest_manifest(records[0])
    target_dir.mkdir(parents=True, exist_ok=True)

    written: Dict[str, Path] = {}
    for p_idx, rel_path in manifest_entries:
        clean_parts = [pt for pt in Path(rel_path).parts if pt not in ("", ".", "..")]
        if not clean_parts:
            continue
        if 1 <= p_idx < len(records):
            dest_file = target_dir.joinpath(*clean_parts)
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.write_bytes(records[p_idx])
            written[rel_path] = dest_file

    return written
