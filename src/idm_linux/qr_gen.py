from __future__ import annotations

import base64
import struct
import zlib
from typing import Dict, List, Optional, Tuple

# ISO/IEC 18004 — EC Level L (01) tabloları (Versiyon 1..10, 271 bayta kadar tüm URL'ler)
# Format: version -> (toplam_veri_kod_kelimesi, blok_basi_ec, [(blok_sayisi, blok_veri_uzunlugu), ...], hizalama_merkezleri)
_QR_V_TABLE_L: Dict[int, Tuple[int, int, List[Tuple[int, int]], List[int]]] = {
    1: (19, 7, [(1, 19)], []),
    2: (34, 10, [(1, 34)], [6, 18]),
    3: (55, 15, [(1, 55)], [6, 22]),
    4: (80, 20, [(1, 80)], [6, 26]),
    5: (108, 26, [(1, 108)], [6, 30]),
    6: (136, 18, [(2, 68)], [6, 34]),
    7: (156, 20, [(2, 78)], [6, 22, 38]),
    8: (194, 24, [(2, 97)], [6, 24, 42]),
    9: (232, 30, [(2, 116)], [6, 26, 46]),
    10: (274, 18, [(2, 68), (2, 69)], [6, 28, 50]),
}

# GF(256) log / exp tabloları (polinom 0x11D)
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator_poly(nsym: int) -> List[int]:
    g = [1]
    for i in range(nsym):
        nxt = [0] * (len(g) + 1)
        root = _GF_EXP[i]
        for j, coef in enumerate(g):
            nxt[j] ^= coef
            nxt[j + 1] ^= _gf_mul(coef, root)
        g = nxt
    return g


def _rs_encode(data: List[int], nsym: int) -> List[int]:
    gen = _rs_generator_poly(nsym)
    res = list(data) + [0] * nsym
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            for j in range(1, len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data) :]


def _bch_format_bits(ec_indicator: int, mask_pattern: int) -> int:
    data = (ec_indicator << 3) | mask_pattern
    rem = data << 10
    for i in range(4, -1, -1):
        if rem & (1 << (i + 10)):
            rem ^= 0x537 << i
    return ((data << 10) | rem) ^ 0x5412


def _bch_version_bits(version: int) -> int:
    rem = version << 12
    for i in range(5, -1, -1):
        if rem & (1 << (i + 12)):
            rem ^= 0x1F25 << i
    return (version << 12) | rem


def _choose_version(payload_len: int) -> int:
    for ver in range(1, 11):
        total_data_cw = _QR_V_TABLE_L[ver][0]
        len_bits = 8 if ver <= 9 else 16
        cap = (total_data_cw * 8 - 4 - len_bits) // 8
        if payload_len <= cap:
            return ver
    raise ValueError(f"QR verisi çok uzun ({payload_len} bayt; maksimum 271 bayt).")


def _encode_codewords(payload: bytes, ver: int) -> List[int]:
    total_data_cw, ec_per_blk, blk_spec, _ = _QR_V_TABLE_L[ver]
    bits: List[int] = []

    def _push(val: int, count: int) -> None:
        for shift in range(count - 1, -1, -1):
            bits.append((val >> shift) & 1)

    # Byte mode = 0100
    _push(0b0100, 4)
    _push(len(payload), 8 if ver <= 9 else 16)
    for b in payload:
        _push(b, 8)

    max_bits = total_data_cw * 8
    term = min(4, max_bits - len(bits))
    _push(0, term)
    while len(bits) % 8 != 0:
        bits.append(0)

    data_cws = []
    for i in range(0, len(bits), 8):
        byte_val = 0
        for b in bits[i : i + 8]:
            byte_val = (byte_val << 1) | b
        data_cws.append(byte_val)

    pad_seq = (0xEC, 0x11)
    pad_idx = 0
    while len(data_cws) < total_data_cw:
        data_cws.append(pad_seq[pad_idx % 2])
        pad_idx += 1

    # Bloklara ayır ve Reed-Solomon EC üret
    data_blocks: List[List[int]] = []
    ec_blocks: List[List[int]] = []
    pos = 0
    for count, blk_len in blk_spec:
        for _ in range(count):
            blk = data_cws[pos : pos + blk_len]
            pos += blk_len
            data_blocks.append(blk)
            ec_blocks.append(_rs_encode(blk, ec_per_blk))

    # Interleave
    final_cws: List[int] = []
    max_dlen = max(len(b) for b in data_blocks)
    for col in range(max_dlen):
        for blk in data_blocks:
            if col < len(blk):
                final_cws.append(blk[col])
    for col in range(ec_per_blk):
        for eblk in ec_blocks:
            final_cws.append(eblk[col])
    return final_cws


def _mask_cond(mask: int, r: int, c: int) -> bool:
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return ((r // 2) + (c // 3)) % 2 == 0
    if mask == 5:
        return ((r * c) % 2 + (r * c) % 3) == 0
    if mask == 6:
        return (((r * c) % 2 + (r * c) % 3) % 2) == 0
    return (((r + c) % 2 + (r * c) % 3) % 2) == 0


def _penalty_score(mat: List[List[int]]) -> int:
    n = len(mat)
    score = 0
    # Kural 1: Ardışık 5+ aynı renk
    for r in range(n):
        run_len = 1
        for c in range(1, n):
            if mat[r][c] == mat[r][c - 1]:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                run_len = 1
        if run_len >= 5:
            score += 3 + (run_len - 5)

    for c in range(n):
        run_len = 1
        for r in range(1, n):
            if mat[r][c] == mat[r - 1][c]:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                run_len = 1
        if run_len >= 5:
            score += 3 + (run_len - 5)

    # Kural 2: 2x2 bloklar
    for r in range(n - 1):
        for c in range(n - 1):
            v = mat[r][c]
            if mat[r][c + 1] == v and mat[r + 1][c] == v and mat[r + 1][c + 1] == v:
                score += 3

    # Kural 3: Finder-benzeri desenler
    pat1 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pat2 = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for r in range(n):
        row = mat[r]
        for c in range(n - 10):
            seg = row[c : c + 11]
            if seg == pat1 or seg == pat2:
                score += 40
    for c in range(n):
        col = [mat[r][c] for r in range(n)]
        for r in range(n - 10):
            seg = col[r : r + 11]
            if seg == pat1 or seg == pat2:
                score += 40

    # Kural 4: Koyu modül oranı
    dark = sum(sum(row) for row in mat)
    total = n * n
    k = abs(dark * 20 - total * 10) // total
    score += k * 10
    return score


def build_qr_matrix(text: str) -> List[List[int]]:
    """Verilen metin/URL için %100 standart ISO/IEC 18004 QR matrisi (0=açık, 1=koyu) döndürür."""
    payload = text.encode("utf-8")
    ver = _choose_version(len(payload))
    size = 17 + 4 * ver
    _, _, _, align_centers = _QR_V_TABLE_L[ver]

    mat: List[List[Optional[int]]] = [[None] * size for _ in range(size)]
    is_func = [[False] * size for _ in range(size)]

    def _set_func(r: int, c: int, val: int) -> None:
        if 0 <= r < size and 0 <= c < size:
            mat[r][c] = val
            is_func[r][c] = True

    def _place_finder(top: int, left: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                rr, cc = top + dr, left + dc
                if 0 <= rr < size and 0 <= cc < size:
                    if 0 <= dr <= 6 and 0 <= dc <= 6:
                        on = (
                            dr in (0, 6)
                            or dc in (0, 6)
                            or (2 <= dr <= 4 and 2 <= dc <= 4)
                        )
                        _set_func(rr, cc, 1 if on else 0)
                    else:
                        _set_func(rr, cc, 0)

    _place_finder(0, 0)
    _place_finder(0, size - 7)
    _place_finder(size - 7, 0)

    # Timing desenleri
    for i in range(8, size - 8):
        _set_func(6, i, 1 if i % 2 == 0 else 0)
        _set_func(i, 6, 1 if i % 2 == 0 else 0)

    # Alignment desenleri
    for ar in align_centers:
        for ac in align_centers:
            if (ar == 6 and ac == 6) or (ar == 6 and ac == size - 7) or (ar == size - 7 and ac == 6):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    on = max(abs(dr), abs(dc)) in (0, 2)
                    _set_func(ar + dr, ac + dc, 1 if on else 0)

    # Dark module + Format rezerv alanları
    _set_func(4 * ver + 9, 8, 1)
    for i in range(9):
        if not is_func[8][i]:
            _set_func(8, i, 0)
        if not is_func[i][8]:
            _set_func(i, 8, 0)
    for i in range(8):
        _set_func(8, size - 1 - i, 0)
        _set_func(size - 1 - i, 8, 0)

    # Versiyon >= 7 için 18-bit versiyon blokları
    if ver >= 7:
        vbits = _bch_version_bits(ver)
        for i in range(18):
            bit = (vbits >> i) & 1
            a = size - 11 + (i % 3)
            b = i // 3
            _set_func(b, a, bit)
            _set_func(a, b, bit)

    # Veri bitlerini zig-zag yerleştir
    cws = _encode_codewords(payload, ver)
    data_bits: List[int] = []
    for cw in cws:
        for shift in range(7, -1, -1):
            data_bits.append((cw >> shift) & 1)

    bit_idx = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        row_iter = range(size - 1, -1, -1) if upward else range(size)
        for r in row_iter:
            for dc in (0, -1):
                c = col + dc
                if not is_func[r][c]:
                    bval = data_bits[bit_idx] if bit_idx < len(data_bits) else 0
                    mat[r][c] = bval
                    bit_idx += 1
        upward = not upward
        col -= 2

    def _apply_format(target: List[List[int]], mask_id: int) -> None:
        fbits = _bch_format_bits(0b01, mask_id)  # 01 = Level L
        # Sol-üst çevresi
        coords_tl = [
            (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5),
            (8, 7), (8, 8), (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),
        ]
        for idx, (rr, cc) in enumerate(coords_tl):
            target[rr][cc] = (fbits >> (14 - idx)) & 1
        # Sağ-üst ve sol-alt
        for idx in range(7):
            target[size - 1 - idx][8] = (fbits >> (14 - idx)) & 1
        for idx in range(7, 15):
            target[8][size - 15 + idx] = (fbits >> (14 - idx)) & 1

    best_mat: Optional[List[List[int]]] = None
    best_score = 1 << 30
    for m in range(8):
        cand = [[int(mat[r][c] or 0) for c in range(size)] for r in range(size)]
        for r in range(size):
            for c in range(size):
                if not is_func[r][c] and _mask_cond(m, r, c):
                    cand[r][c] ^= 1
        _apply_format(cand, m)
        sc = _penalty_score(cand)
        if sc < best_score:
            best_score = sc
            best_mat = cand

    assert best_mat is not None
    return best_mat


def render_qr_png_bytes(
    text: str,
    scale: int = 5,
    border: int = 3,
    dark_rgb: Tuple[int, int, int] = (15, 23, 42),
    light_rgb: Tuple[int, int, int] = (255, 255, 255),
) -> bytes:
    """
    Saf Python (zlib + struct) ile verilen metnin QR kodunu standart 8-bit RGB PNG baytlarına çevirir.
    Pillow veya harici hiçbir kütüphane gerektirmez!
    """
    mat = build_qr_matrix(text)
    n = len(mat)
    total_modules = n + border * 2
    px_size = total_modules * scale

    dark_px = bytes(dark_rgb)
    light_px = bytes(light_rgb)
    border_row = b"\x00" + (light_px * px_size)

    raw_rows: List[bytes] = []
    for _ in range(border * scale):
        raw_rows.append(border_row)

    for r in range(n):
        row_chunks = [light_px * (border * scale)]
        for c in range(n):
            row_chunks.append((dark_px if mat[r][c] else light_px) * scale)
        row_chunks.append(light_px * (border * scale))
        one_scanline = b"\x00" + b"".join(row_chunks)
        for _ in range(scale):
            raw_rows.append(one_scanline)

    for _ in range(border * scale):
        raw_rows.append(border_row)

    raw_data = b"".join(raw_rows)

    def _png_chunk(tag: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(tag + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", px_size, px_size, 8, 2, 0, 0, 0)  # 8-bit Truecolor RGB
    idat = zlib.compress(raw_data, level=6)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def render_qr_base64(
    text: str,
    scale: int = 5,
    border: int = 3,
    dark_rgb: Tuple[int, int, int] = (15, 23, 42),
    light_rgb: Tuple[int, int, int] = (255, 255, 255),
) -> str:
    """tk.PhotoImage(data=...) ve HTML data:image/png;base64,... ile doğrudan uyumlu base64 PNG döndürür.

    v3.8.0 PERFORMANS: LRU önbellek — 'Diğer Projeler' ve 'Teşekkür Et & Destekle'
    sayfaları her açılışta aynı URL'ler için ~20 QR üretiyordu (saf Python bencode +
    zlib-9 ≈ 9 ms/QR). Önbellek sayesinde tekrar açılışlar anında; ilk açılışta da
    zlib sıkıştırma düzeyi 9→6 çekilerek üretime ~%35 hız kazandırıldı (PNG boyutu
    etkisi ihmal edilebilir)."""
    key = (text, scale, border, dark_rgb, light_rgb)
    cached = _QR_B64_CACHE.get(key)
    if cached is not None:
        return cached
    b64 = base64.b64encode(
        render_qr_png_bytes(
            text, scale=scale, border=border, dark_rgb=dark_rgb, light_rgb=light_rgb
        )
    ).decode("ascii")
    if len(_QR_B64_CACHE) >= _QR_B64_CACHE_MAX:
        _QR_B64_CACHE.clear()  # basit temizlik: URL kümesi sınırlı, taşma nadir
    _QR_B64_CACHE[key] = b64
    return b64


_QR_B64_CACHE: Dict[Tuple[str, int, int, Tuple[int, int, int], Tuple[int, int, int]], str] = {}
_QR_B64_CACHE_MAX = 64
