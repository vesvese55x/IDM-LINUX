"""BEP 3 bencode kodlayıcı/çözücü.

Kendi BitTorrent motorumuz için yazıldı; ``bittorrent`` gibi dış bağımlılık YOK.

Önemli ayrıntı: ``parse_torrent`` fonksiyonunun info sözlüğünün **tam baytlarını**
(ve dolayısıyla info-hash'i) hesaplayabilmesi için çözücü, her değerin metin
içindeki başlangıç/bitiş konumlarını da döndürebilir.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

__all__ = ["bencode", "bdecode", "bdecode_with_spans"]


# ─────────────────────────────────────────────────────────────────────────────
# Kodlama
# ─────────────────────────────────────────────────────────────────────────────
def bencode(obj: Any) -> bytes:
    """Python nesnesini bencode baytlarına çevirir (sözlük anahtarları sıralı)."""
    out: List[bytes] = []
    _encode_into(obj, out)
    return b"".join(out)


def _encode_into(obj: Any, out: List[bytes]) -> None:
    if isinstance(obj, bool):
        out.append(b"i1e" if obj else b"i0e")
    elif isinstance(obj, int):
        out.append(b"i%de" % obj)
    elif isinstance(obj, bytes):
        out.append(b"%d:%s" % (len(obj), obj))
    elif isinstance(obj, bytearray):
        out.append(b"%d:%s" % (len(obj), bytes(obj)))
    elif isinstance(obj, str):
        raw = obj.encode("utf-8")
        out.append(b"%d:%s" % (len(raw), raw))
    elif isinstance(obj, (list, tuple)):
        out.append(b"l")
        for item in obj:
            _encode_into(item, out)
        out.append(b"e")
    elif isinstance(obj, dict):
        out.append(b"d")
        items = []
        for key, value in obj.items():
            if isinstance(key, str):
                key = key.encode("utf-8")
            elif not isinstance(key, bytes):
                key = str(key).encode("utf-8")
            items.append((key, value))
        for key, value in sorted(items, key=lambda kv: kv[0]):
            out.append(b"%d:%s" % (len(key), key))
            _encode_into(value, out)
        out.append(b"e")
    else:  # pragma: no cover - desteklenmeyen tip
        raise TypeError(f"bencode: desteklenmeyen tip {type(obj)!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Çözme
# ─────────────────────────────────────────────────────────────────────────────
class BencodeError(ValueError):
    """Bozuk bencode verisi."""


def bdecode(data: bytes) -> Any:
    """Bencode baytlarını Python nesnesine çevirir (sözlük anahtarları ``bytes``)."""
    value, idx = _decode_at(data, 0)
    # Sondaki boşluk/çöp tolere edilir (bazı tracker'lar yanıt sonuna '\\n' ekler)
    while idx < len(data) and data[idx: idx + 1] in b" \r\n\t":
        idx += 1
    if idx != len(data):
        raise BencodeError(f"bencode: {idx}. bayttan sonra beklenmeyen veri")
    return value


def bdecode_with_spans(data: bytes) -> Tuple[Any, Dict[bytes, Tuple[int, int]], int]:
    """Üst düzey sözlüğü, her üst anahtarın **değer** bayt aralığıyla çözer.

    Döner: ``(sözlük, {anahtar: (başlangıç, bitiş)}, tüketilen_bayt)``
    """
    if data[:1] != b"d":
        value, idx = _decode_at(data, 0)
        return value, {}, idx
    idx = 1
    result: Dict[Any, Any] = {}
    spans: Dict[bytes, Tuple[int, int]] = {}
    while True:
        if idx >= len(data):
            raise BencodeError("bencode: sözlük kapanmadı")
        if data[idx: idx + 1] == b"e":
            idx += 1
            break
        key, idx = _decode_at(data, idx)
        start = idx
        value, idx = _decode_at(data, idx)
        result[key] = value
        if isinstance(key, bytes):
            spans[key] = (start, idx)
    return result, spans, idx


def _decode_at(data: bytes, idx: int) -> Tuple[Any, int]:
    if idx >= len(data):
        raise BencodeError("bencode: veri bitti")
    ch = data[idx: idx + 1]
    if ch == b"i":
        end = data.index(b"e", idx)
        raw = data[idx + 1: end]
        try:
            return int(raw), end + 1
        except ValueError as exc:  # pragma: no cover - bozuk veri
            raise BencodeError(f"bencode: geçersiz tamsayı {raw!r}") from exc
    if ch == b"l":
        idx += 1
        items: List[Any] = []
        while True:
            if data[idx: idx + 1] == b"e":
                return items, idx + 1
            value, idx = _decode_at(data, idx)
            items.append(value)
    if ch == b"d":
        idx += 1
        result: Dict[Any, Any] = {}
        while True:
            if data[idx: idx + 1] == b"e":
                return result, idx + 1
            key, idx = _decode_at(data, idx)
            value, idx = _decode_at(data, idx)
            result[key] = value
    if ch.isdigit():
        colon = data.index(b":", idx)
        length = int(data[idx:colon])
        start = colon + 1
        end = start + length
        if end > len(data):
            raise BencodeError("bencode: metin verisi kesildi")
        return data[start:end], end
    raise BencodeError(f"bencode: beklenmeyen bayt {ch!r} ({idx}. konum)")


def bdecode_prefix(data: bytes) -> Tuple[Any, int]:
    """İlk bencode değerini çözer ve kaç bayt tükettiğini de döner.

    ut_metadata (BEP 9) iletilerinde sözlüğün ARDINDAN ham parça verisi gelir;
    bu yardımcı sayesinde sınır doğru bulunur.
    """
    value, idx = _decode_at(data, 0)
    return value, idx
