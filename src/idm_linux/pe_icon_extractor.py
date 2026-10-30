from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _encode_rgba_png(width: int, height: int, rgba_rows: List[bytes]) -> bytes:
    """Saf Python (yalnızca struct + zlib) ile RGBA piksel satırlarından geçerli PNG üretir."""
    def _chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw_scanlines = b"".join(b"\x00" + row for row in rgba_rows)
    idat = zlib.compress(raw_scanlines, level=9)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _dib_32bpp_to_png(dib_bytes: bytes) -> Optional[Tuple[int, int, bytes]]:
    """ICO/PE RT_ICON içindeki 32-bit BGRA BITMAPINFOHEADER verisini RGBA PNG'ye dönüştürür."""
    if len(dib_bytes) < 40:
        return None
    hdr_size, width, height_x2, _planes, bpp, compression = struct.unpack_from("<IiiHHI", dib_bytes, 0)
    if hdr_size < 40 or bpp != 32 or compression != 0 or width <= 0:
        return None
    height = abs(height_x2) // 2
    if height <= 0 or width > 512 or height > 512:
        return None

    px_off = hdr_size
    row_bytes = width * 4
    needed = px_off + row_bytes * height
    if len(dib_bytes) < needed:
        return None

    # DIB bottom-up saklanır (height_x2 > 0 ise alttan üste)
    bottom_up = height_x2 > 0
    rows_rgba: List[bytes] = []
    for y in range(height):
        src_y = (height - 1 - y) if bottom_up else y
        start = px_off + src_y * row_bytes
        line = dib_bytes[start : start + row_bytes]
        out_row = bytearray(row_bytes)
        # BGRA -> RGBA
        out_row[0::4] = line[2::4]
        out_row[1::4] = line[1::4]
        out_row[2::4] = line[0::4]
        out_row[3::4] = line[3::4]
        rows_rgba.append(bytes(out_row))

    return (width, height, _encode_rgba_png(width, height, rows_rgba))


def _parse_pe_rsrc_tree(data: bytes) -> Tuple[Optional[int], List[Tuple[int, int, int]]]:
    if len(data) < 0x100 or data[:2] != b"MZ":
        return None, []
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if e_lfanew + 24 > len(data) or data[e_lfanew : e_lfanew + 4] != b"PE\x00\x00":
        return None, []
    num_sec = struct.unpack_from("<H", data, e_lfanew + 6)[0]
    opt_size = struct.unpack_from("<H", data, e_lfanew + 20)[0]
    magic = struct.unpack_from("<H", data, e_lfanew + 24)[0]
    dd_off = e_lfanew + 24 + (96 if magic == 0x10B else 112)
    if dd_off + 24 > len(data):
        return None, []
    rsrc_rva, _rsrc_sz = struct.unpack_from("<II", data, dd_off + 2 * 8)
    if rsrc_rva == 0:
        return None, []

    secs: List[Tuple[int, int, int]] = []
    sec_base = e_lfanew + 24 + opt_size
    for i in range(num_sec):
        s = sec_base + i * 40
        if s + 40 > len(data):
            break
        vsz, vrva, rsz, rptr = struct.unpack_from("<IIII", data, s + 8)
        secs.append((vrva, max(vsz, rsz), rptr))

    for vrva, span, rptr in secs:
        if vrva <= rsrc_rva < vrva + span:
            return rptr + (rsrc_rva - vrva), secs
    return None, secs


def _rva_to_file_offset(rva: int, secs: List[Tuple[int, int, int]]) -> Optional[int]:
    for vrva, span, rptr in secs:
        if vrva <= rva < vrva + span:
            return rptr + (rva - vrva)
    return None


def _walk_rsrc_dir(data: bytes, rsrc_root: int, dir_off: int) -> List[Tuple[int, bool, int]]:
    if dir_off < 0 or dir_off + 16 > len(data):
        return []
    named_n, id_n = struct.unpack_from("<HH", data, dir_off + 12)
    total = named_n + id_n
    if total > 4096:
        return []
    entries: List[Tuple[int, bool, int]] = []
    pos = dir_off + 16
    for _ in range(total):
        if pos + 8 > len(data):
            break
        name_or_id, off_to_data = struct.unpack_from("<II", data, pos)
        pos += 8
        is_dir = bool(off_to_data & 0x80000000)
        sub_off = rsrc_root + (off_to_data & 0x7FFFFFFF)
        entries.append((name_or_id, is_dir, sub_off))
    return entries


def extract_idman_official_icons(pe_path: Path) -> Dict[int, bytes]:
    """
    IDMan.exe dosyasının ana uygulama simge grubundan (RT_GROUP_ICON)
    boyut -> PNG baytları (ör. {256: b'\\x89PNG...', 48: ..., 32: ..., 16: ...}) çıkarır.
    """
    if not pe_path.is_file():
        return {}
    try:
        data = pe_path.read_bytes()
    except OSError:
        return {}

    rsrc_off, secs = _parse_pe_rsrc_tree(data)
    if rsrc_off is None:
        return {}

    rt_icons: Dict[int, bytes] = {}
    rt_groups: Dict[int, bytes] = {}

    for type_id, is_dir, t_off in _walk_rsrc_dir(data, rsrc_off, rsrc_off):
        if not is_dir or type_id not in (3, 14):
            continue
        for res_id, is_d2, n_off in _walk_rsrc_dir(data, rsrc_off, t_off):
            if not is_d2:
                continue
            for _lang_id, is_d3, l_off in _walk_rsrc_dir(data, rsrc_off, n_off):
                if is_d3 or l_off + 16 > len(data):
                    continue
                data_rva, sz = struct.unpack_from("<II", data, l_off)
                foff = _rva_to_file_offset(data_rva, secs)
                if foff is not None and 0 < sz <= len(data) - foff:
                    blob = data[foff : foff + sz]
                    if type_id == 3:
                        rt_icons[res_id] = blob
                    else:
                        rt_groups[res_id] = blob
                break

    if not rt_groups:
        return {}

    # İlk (en düşük ID'li) simge grubu Windows PE standartlarında ana uygulama simgesidir (IDMan.exe -> Group 128)
    main_gid = min(rt_groups.keys())
    gblob = rt_groups[main_gid]
    if len(gblob) < 6:
        return {}
    _res, _type, count = struct.unpack_from("<HHH", gblob, 0)

    out_pngs: Dict[int, bytes] = {}
    for idx in range(count):
        ent_off = 6 + idx * 14
        if ent_off + 14 > len(gblob):
            break
        b_w, b_h, _b_col, _r, _planes, bpp, _bytes_in_res, icon_id = struct.unpack_from("<BBBBHHIH", gblob, ent_off)
        w = 256 if b_w == 0 else b_w
        ib = rt_icons.get(icon_id)
        if not ib:
            continue
        if ib[:8] == b"\x89PNG\r\n\x1a\n":
            out_pngs[w] = ib
        elif bpp == 32 and w not in out_pngs:
            conv = _dib_32bpp_to_png(ib)
            if conv is not None:
                out_pngs[conv[0]] = conv[2]

    return out_pngs


def extract_pe_version_label(pe_path: Path) -> Optional[str]:
    """
    IDMan.exe dosyasının VS_FIXEDFILEINFO yapısından (0xFEEF04BD) gerçek sürümünü
    okur (ör. '6.43 Build 16').
    """
    if not pe_path.is_file():
        return None
    try:
        data = pe_path.read_bytes()
    except OSError:
        return None

    sig = struct.pack("<I", 0xFEEF04BD)
    idx = data.find(sig)
    if idx < 0 or idx + 20 > len(data):
        return None
    ms, ls = struct.unpack_from("<II", data, idx + 8)
    major = (ms >> 16) & 0xFFFF
    minor = ms & 0xFFFF
    build = (ls >> 16) & 0xFFFF
    if major == 0:
        return None
    return f"{major}.{minor} Build {build}"
