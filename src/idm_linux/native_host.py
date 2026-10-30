from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional

from .config import IdmLinuxConfig, setup_logger
from .daemon import is_daemon_running
from .protocol import (
    IdmWireMessage,
    build_config_update,
    build_download_decision,
    build_handshake_ack,
    build_ping_ack,
    is_domain_excluded,
)
from .wine_sender import WineIdmSender

logger = setup_logger("native_host", "native_host.log")


def _read_native_frame() -> Optional[bytes]:
    raw_len = sys.stdin.buffer.read(4)
    if not raw_len or len(raw_len) < 4:
        return None
    msg_len = struct.unpack("<I", raw_len)[0]
    if msg_len == 0 or msg_len > 16 * 1024 * 1024:
        return None
    data = sys.stdin.buffer.read(msg_len)
    if len(data) < msg_len:
        return None
    return data


def _write_native_json(obj: Any) -> None:
    encoded = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def _ensure_daemon_alive(cfg: IdmLinuxConfig) -> bool:
    if is_daemon_running(cfg):
        return True
    # Daemon çalışmıyorsa arka planda sessizce uyandır
    try:
        subprocess.Popen(
            [sys.executable, "-m", "idm_linux.cli", "daemon-run"],
            env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(12):
            time.sleep(0.15)
            if is_daemon_running(cfg):
                return True
    except OSError as exc:
        logger.warning("Daemon otomatik başlatılamadı: %s", exc)
    return False


def _post_daemon(cfg: IdmLinuxConfig, endpoint: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = f"http://127.0.0.1:{cfg.http_port}{endpoint}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("Daemon POST %s başarısız: %s", endpoint, exc)
        return None


def _get_daemon(cfg: IdmLinuxConfig, endpoint: str) -> Optional[Dict[str, Any]]:
    url = f"http://127.0.0.1:{cfg.http_port}{endpoint}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _handle_wire_string_locally(
    raw_msg: str,
    cfg: IdmLinuxConfig,
    sender: WineIdmSender,
) -> List[str]:
    """Daemon'a ulaşılamazsa bile resmi eklenti el sıkışmasını ve indirmeyi doğrudan karşılar."""
    parsed = IdmWireMessage.parse(raw_msg)
    if not parsed:
        return []

    if parsed.msg_type == 2:
        dpi = cfg.dpi_scale if cfg.dpi_scale > 0 else 96
        return [
            build_handshake_ack(parsed.seq, dpi=dpi),
            build_config_update(parsed.seq + 1, cfg.extension_regex(), enabled=cfg.capture_downloads),
        ]
    if parsed.msg_type == 0:
        return [build_ping_ack(parsed.seq)]
    if parsed.msg_type == 13:
        dl_id = parsed.positional_args[0] if parsed.positional_args else "0"
        req = parsed.to_download_request(source="official-stdio")
        if not req or not cfg.capture_downloads or is_domain_excluded(req.url, req.referer, cfg.excluded_domains):
            return [build_download_decision(parsed.seq, dl_id, takeover=False)]
        sender.send_download(req)
        return [build_download_decision(parsed.seq, dl_id, takeover=True)]
    if parsed.msg_type == 14:
        req = parsed.to_download_request(source="official-menu-stdio")
        if req:
            sender.send_download(req)
        return [build_ping_ack(parsed.seq)]
    return [build_ping_ack(parsed.seq)]


def run_native_messaging_loop() -> int:
    """
    Tarayıcıların başlattığı com.tonec.idm & com.idmlinux.companion stdio köprüsü.
    DİKKAT: stdout'a yalnızca 4-bayt uzunluk ön-ekli JSON çerçeveleri yazılır!
    """
    cfg = IdmLinuxConfig.load()
    sender = WineIdmSender(cfg)
    _ensure_daemon_alive(cfg)

    while True:
        frame = _read_native_frame()
        if frame is None:
            break

        try:
            decoded = json.loads(frame.decode("utf-8"))
        except json.JSONDecodeError:
            # Bazı eski eklenti derlemeleri düz MSG# dizgisi gönderebilir
            raw_txt = frame.decode("utf-8", errors="ignore").strip()
            if raw_txt.startswith("MSG#"):
                decoded = raw_txt
            else:
                continue

        # 1. Durum: Resmi IDM Integration Module eklentisi JSON string ("MSG#...") gönderir
        if isinstance(decoded, str):
            cfg = IdmLinuxConfig.load()
            daemon_res = _post_daemon(cfg, "/api/wire", {"raw": decoded, "ping_official": True})
            if daemon_res and daemon_res.get("ok"):
                replies = daemon_res.get("replies") or []
            else:
                replies = _handle_wire_string_locally(decoded, cfg, sender)
            for rep in replies:
                _write_native_json(rep)
            continue

        # 2. Durum: Hibrit IDM Linux Companion eklentisi yapılandırılmış JSON nesnesi gönderir
        if isinstance(decoded, dict):
            action = decoded.get("action") or "download"
            cfg = IdmLinuxConfig.load()
            _ensure_daemon_alive(cfg)

            if action in ("status", "ensure_daemon", "probe_video", "ping"):
                # v2.9.7: her durum sorgusu daemon'u hayatta tutar/uyandırır
                st = _get_daemon(cfg, "/api/status") or {"ok": True, "idm_installed": cfg.find_idm_exe() is not None}
                _write_native_json(st)
            elif action == "open_idm":
                res = _post_daemon(cfg, "/api/open-idm", {})
                if not res:
                    ok, msg = sender.open_idm_window()
                    res = {"ok": ok, "message": msg}
                _write_native_json(res)
            elif action == "probe_video":
                res = _post_daemon(cfg, "/api/video/probe", decoded) or {"ok": False, "formats": []}
                _write_native_json(res)
            elif action == "download_video":
                res = _post_daemon(cfg, "/api/video/download", decoded) or {"ok": False}
                _write_native_json(res)
            elif action == "update_config":
                res = _post_daemon(cfg, "/api/config", decoded.get("config") or {}) or {"ok": False}
                _write_native_json(res)
            elif action == "download_batch":
                res = _post_daemon(cfg, "/api/download-batch", decoded) or {"ok": False}
                _write_native_json(res)
            elif action == "torrent_download":
                # v3.6.0: torrent/magnet popup'u için yedek yol — HTTP köprüsü ölüyken bile
                # daemon uyandırılıp /api/torrent/download'a iletilebilir.
                res = _post_daemon(cfg, "/api/torrent/download", decoded) or {"ok": False}
                _write_native_json(res)
            else:
                res = _post_daemon(cfg, "/api/download", decoded)
                if not res:
                    from .protocol import DownloadRequest
                    req = DownloadRequest(
                        url=decoded.get("url", ""),
                        referer=decoded.get("referer", ""),
                        cookies=decoded.get("cookies", ""),
                        user_agent=decoded.get("userAgent", ""),
                        filename=decoded.get("filename", ""),
                    )
                    ok, msg = sender.send_download(req)
                    res = {"ok": ok, "takeover": ok, "message": msg}
                _write_native_json(res)

    return 0


if __name__ == "__main__":
    raise SystemExit(run_native_messaging_loop())
