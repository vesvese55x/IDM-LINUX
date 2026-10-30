from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse


@dataclass
class DownloadRequest:
    url: str
    referer: str = ""
    origin: str = ""
    cookies: str = ""
    user_agent: str = ""
    post_data: str = ""
    filename: str = ""
    save_dir: str = ""
    silent: Optional[bool] = None
    source: str = "browser"  # official-ext, companion-ext, video-bar, cli, clipboard
    extra_headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class IdmWireMessage:
    seq: int
    msg_type: int
    action: int
    flags: int
    positional_args: List[str] = field(default_factory=list)
    key_values: Dict[int, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: str) -> Optional["IdmWireMessage"]:
        """
        Resmi IDM tel protokolünü (MSG#seq#type#action#flags[:p1:p2][,k=len:val][,k=val];)
        uzunluk ön-ekli (length-prefixed) akış kurallarına göre hatasız ayrıştırır.
        """
        text = raw.strip()
        if text.endswith(";"):
            text = text[:-1]
        if not text.startswith("MSG#"):
            return None

        parts = text.split("#", 4)
        if len(parts) < 5:
            return None

        try:
            seq = int(parts[1])
            msg_type = int(parts[2])
            action = int(parts[3])
        except ValueError:
            return None

        rest = parts[4]
        split_idx = -1
        for i, ch in enumerate(rest):
            if ch in (":", ","):
                split_idx = i
                break

        if split_idx == -1:
            flags_str, remainder = rest, ""
        else:
            flags_str, remainder = rest[:split_idx], rest[split_idx:]

        try:
            flags = int(flags_str) if flags_str else 0
        except ValueError:
            flags = 0

        positional_args: List[str] = []
        key_values: Dict[int, str] = {}

        cursor = remainder
        if cursor.startswith(":"):
            cursor = cursor[1:]
            comma_idx = cursor.find(",")
            if comma_idx != -1:
                pos_part = cursor[:comma_idx]
                cursor = cursor[comma_idx:]
            else:
                pos_part = cursor
                cursor = ""
            if pos_part:
                positional_args = pos_part.split(":")

        # Anahtar-değer çiftlerini akış olarak oku: ,<key>=<len>:<val> veya ,<key>=<val>
        idx = 0
        n = len(cursor)
        while idx < n:
            if cursor[idx] == ",":
                idx += 1
                continue

            eq_pos = cursor.find("=", idx)
            if eq_pos == -1:
                break

            key_str = cursor[idx:eq_pos].strip()
            if not key_str.isdigit():
                break
            key_id = int(key_str)
            idx = eq_pos + 1

            # Uzunluk ön-eki kontrolü: rakamlar + ':'
            colon_pos = cursor.find(":", idx)
            comma_pos = cursor.find(",", idx)
            used_length_prefix = False

            if colon_pos != -1 and (comma_pos == -1 or colon_pos < comma_pos):
                len_candidate = cursor[idx:colon_pos]
                if len_candidate.isdigit():
                    val_len = int(len_candidate)
                    val_start = colon_pos + 1
                    if val_start + val_len <= n:
                        raw_val = cursor[val_start : val_start + val_len]
                        key_values[key_id] = _clean_idm_value(raw_val)
                        idx = val_start + val_len
                        used_length_prefix = True

            if not used_length_prefix:
                next_comma = cursor.find(",", idx)
                if next_comma == -1:
                    raw_val = cursor[idx:]
                    idx = n
                else:
                    raw_val = cursor[idx:next_comma]
                    idx = next_comma
                key_values[key_id] = _clean_idm_value(raw_val)

        return cls(
            seq=seq,
            msg_type=msg_type,
            action=action,
            flags=flags,
            positional_args=positional_args,
            key_values=key_values,
        )

    def to_download_request(self, source: str = "official-ext") -> Optional[DownloadRequest]:
        kv = self.key_values
        url = kv.get(6) or kv.get(17) or ""
        if not url or not url.startswith(("http://", "https://", "ftp://", "ftps://")):
            return None
        filename = kv.get(100) or kv.get(4) or ""
        return DownloadRequest(
            url=url,
            referer=kv.get(50, ""),
            origin=kv.get(7, ""),
            cookies=kv.get(51, ""),
            user_agent=kv.get(54, ""),
            post_data=kv.get(52, "") or kv.get(9, ""),
            filename=filename,
            source=source,
        )


def _clean_idm_value(val: str) -> str:
    if val.startswith("idmfc"):
        return val[5:]
    return val


def build_handshake_ack(seq: int, dpi: int = 96) -> str:
    """Type 3: Resmi eklentiye protokol sürümü (113), DPI ve Zoom onayı döner."""
    return f"MSG#{seq}#3#0#0:113:0:0:0:{dpi}:0:0:0:100;"


def build_config_update(seq: int, ext_regex: str, enabled: bool = True) -> str:
    """
    Type 4: Resmi eklentideki downloads.onCreated / onDeterminingFilename kancalarını
    etkinleştiren dosya uzantısı regex yapılandırmasını gönderir.
    """
    pattern = ext_regex if enabled else "(?!)"
    return f"MSG#{seq}#4#0#0:0:0:0:0,1={len(pattern)}:{pattern};"


def build_ping_ack(seq: int) -> str:
    return f"MSG#{seq}#1#1#0:1;"


def build_download_decision(seq: int, download_id: str, takeover: bool = True) -> str:
    """
    Type 13 yanıtı:
      3 = Tarayıcının indirmesini iptal et, IDM devraldı!
      0 = Tarayıcının kendi indirmesine izin ver.
    """
    code = 3 if takeover else 0
    return f"MSG#{seq}#13#1#0:{download_id}:{code};"


def is_domain_excluded(url: str, referer: str, excluded_domains: List[str]) -> bool:
    # Kendi yerel eklenti paketi uç noktalarımızı (/extension/*) her koşulda tarayıcıya bırak
    try:
        pu = urlparse(url)
        if (pu.hostname or "").lower() in ("127.0.0.1", "localhost", "::1") and pu.path.startswith("/extension/"):
            return True
    except ValueError:
        pass

    if not excluded_domains:
        return False
    hosts = set()
    for candidate in (url, referer):
        if candidate:
            try:
                h = (urlparse(candidate).hostname or "").lower()
                if h:
                    hosts.add(h)
            except ValueError:
                pass
    for ex in excluded_domains:
        ex_clean = ex.strip().lower().lstrip("*.")
        if not ex_clean:
            continue
        for h in hosts:
            if h == ex_clean or h.endswith("." + ex_clean):
                return True
    return False
