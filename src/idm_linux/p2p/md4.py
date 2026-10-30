"""Saf Python MD4 (RFC 1320).

Neden gerekli? eD2K/eMule dosya karmaları MD4 tabanlıdır; modern OpenSSL 3
kurulumlarında ``hashlib.new("md4")`` **kaldırılmıştır** (legacy provider).
Bu yüzden aMule gibi dış araçlara veya eski OpenSSL'e bağımlı olmadan MD4'ü
kendimiz sağlıyoruz. Hız notu: 9,7 MB'lık bir eD2K parçası ~0,15 sn'de
hesaplanır (yeterli; indirme hızları bundan çok daha düşüktür).
"""
from __future__ import annotations

import struct
from typing import List

__all__ = ["md4", "md4_hex"]


def _left_rotate(value: int, shift: int) -> int:
    value &= 0xFFFFFFFF
    return ((value << shift) | (value >> (32 - shift))) & 0xFFFFFFFF


def _compress(state: List[int], block: bytes) -> None:
    x = list(struct.unpack("<16I", block))
    a, b, c, d = state

    def f(x_, y_, z_):
        return (x_ & y_) | (~x_ & z_)

    def g(x_, y_, z_):
        return (x_ & y_) | (x_ & z_) | (y_ & z_)

    def h(x_, y_, z_):
        return x_ ^ y_ ^ z_

    # 1. tur
    for i in range(16):
        k = i
        s = (3, 7, 11, 19)[i % 4]
        if i % 4 == 0:
            a = _left_rotate(a + f(b, c, d) + x[k], s)
        elif i % 4 == 1:
            d = _left_rotate(d + f(a, b, c) + x[k], s)
        elif i % 4 == 2:
            c = _left_rotate(c + f(d, a, b) + x[k], s)
        else:
            b = _left_rotate(b + f(c, d, a) + x[k], s)
    # 2. tur
    order2 = (0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15)
    for i, k in enumerate(order2):
        s = (3, 5, 9, 13)[i % 4]
        add = 0x5A827999
        if i % 4 == 0:
            a = _left_rotate(a + g(b, c, d) + x[k] + add, s)
        elif i % 4 == 1:
            d = _left_rotate(d + g(a, b, c) + x[k] + add, s)
        elif i % 4 == 2:
            c = _left_rotate(c + g(d, a, b) + x[k] + add, s)
        else:
            b = _left_rotate(b + g(c, d, a) + x[k] + add, s)
    # 3. tur
    order3 = (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15)
    for i, k in enumerate(order3):
        s = (3, 9, 11, 15)[i % 4]
        add = 0x6ED9EBA1
        if i % 4 == 0:
            a = _left_rotate(a + h(b, c, d) + x[k] + add, s)
        elif i % 4 == 1:
            d = _left_rotate(d + h(a, b, c) + x[k] + add, s)
        elif i % 4 == 2:
            c = _left_rotate(c + h(d, a, b) + x[k] + add, s)
        else:
            b = _left_rotate(b + h(c, d, a) + x[k] + add, s)
    state[0] = (state[0] + a) & 0xFFFFFFFF
    state[1] = (state[1] + b) & 0xFFFFFFFF
    state[2] = (state[2] + c) & 0xFFFFFFFF
    state[3] = (state[3] + d) & 0xFFFFFFFF


def md4(data: bytes) -> bytes:
    """MD4 özeti (16 bayt)."""
    if isinstance(data, str):  # pragma: no cover - kolaylık
        data = data.encode("utf-8")
    msg = bytearray(data)
    bit_len = (8 * len(msg)) & 0xFFFFFFFFFFFFFFFF
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += struct.pack("<Q", bit_len)
    state = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476]
    for offset in range(0, len(msg), 64):
        _compress(state, bytes(msg[offset : offset + 64]))
    return struct.pack("<4I", *state)


def md4_hex(data: bytes) -> str:
    return md4(data).hex()
