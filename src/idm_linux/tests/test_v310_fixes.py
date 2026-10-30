"""v3.10.0 kullanıcı-raporu düzeltmelerinin regresyon testleri.

Kapsanan başlıklar (hepsi yerel, ağ gerektirmez):
  1) YETKİ İSTEMİ: tarayıcı sistem politikası yazımı pkexec/polkit penceresi
     AÇMAZ (kurulum ve daemon başlangıcı sessizdir).
  2) ALTYAZI DÜRÜSTLÜĞÜ: WebVTT kaynağı "srt" diye etiketlenmez; SRT hedeflenirse
     GERÇEKTEN geçerli SRT üretilir (cue ayarları/temizlik) ve HTML hata sayfası
     altyazı sanılıp dosyaya yazılmaz.
  3) ALTYAZI KASASI: oynatıcıya gömülü (URL'siz) altyazılar daemon kasasına
     yazılır ve IDM'nin indirebileceği yerel adresten sunulur.
  4) eD2K sunucu listesi: düz metin listeler ve ikili server.met dosyaları
     ayrıştırılır; saçma adresler ayıklanır.
  5) KREDİ METNİ: "BELGESELSEMO tarafından ARENA.AI & Z.AI sayesinde yapılmıştır"
     20 dilde ve arayüz/rozet/eklenti metinlerinde bulunur.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_BASE = Path(__file__).resolve().parents[2]  # yeni düzen: idm_linux paketini içeren src/ dizini
sys.path.insert(0, str(SRC_BASE))  # yeni düzen: src/ tabanı


# ─────────────────────────────────────────────────────────────────────────────
# 1) Yetki istemeyen politika yazımı
# ─────────────────────────────────────────────────────────────────────────────
def test_policy_write_never_prompts_for_password() -> None:
    src = (PROJECT_ROOT / "browsers.py").read_text(encoding="utf-8")
    # _root_write_file gövdesi pkexec İÇERMEMELİ (polkit penceresi = kullanıcı şikâyeti)
    body_start = src.index("def _root_write_file(")
    body_end = src.index("def _sudo_write_file(")
    body = src[body_start:body_end]
    assert 'which("pkexec")' not in body, "kurulum sırasında yetki penceresi açan pkexec geri gelmiş!"
    assert "sudo\", \"-n\"" in body, "parolasız sudo (-n) yolu kaybolmuş"
    # Yetki isteyen yol yalnız AÇIK ONAY fonksiyonunda olabilir
    consent = src[src.index("def write_policies_with_consent(") :]
    assert 'shutil.which("pkexec")' in consent, "isteğe bağlı onaylı yazma yolu yok"
    assert '"tee"' in src, "tee tabanlı yazım kaybolmuş"


def test_policy_write_is_silent_when_not_permitted(tmp_path: Path) -> None:
    import idm_linux.browsers as br

    target = Path("/proc/idm-linux-olmayan-dizin/policy.json")
    ok, method = br._root_write_file(target, "{}")
    assert ok is False and method == "", "yazılamayan hedefte sessizce vazgeçilmeli"

    # Yazılabilir hedefte doğrudan yazar (yetki sorusu yok)
    ok2, method2 = br._root_write_file(tmp_path / "p.json", '{"a": 1}')
    assert ok2 and method2 == "doğrudan"


# ─────────────────────────────────────────────────────────────────────────────
# 2) Altyazı dürüstlüğü
# ─────────────────────────────────────────────────────────────────────────────
VTT_SAMPLE = """WEBVTT
X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000

NOTE bu bir not

1
00:00:01.000 --> 00:00:03.500 align:start position:10%
<c.yellow>Merhaba</c> dünya &amp; hoş geldin

00:00:04.000 --> 00:00:06.000
<b>İkinci</b> satır
"""

HTML_SAMPLE = "<!DOCTYPE html><html><body><h1>404 Not Found</h1></body></html>"


def test_vtt_to_srt_is_valid_subrip() -> None:
    from idm_linux.hls_streamer import detect_subtitle_kind, vtt_to_srt

    assert detect_subtitle_kind(VTT_SAMPLE) == "vtt"
    srt = vtt_to_srt(VTT_SAMPLE)
    assert srt.startswith("1\n00:00:01,000 --> 00:00:03,500\n"), srt
    assert "align:" not in srt and "position:" not in srt, "cue ayarları SRT'ye sızmış"
    assert "<c." not in srt and "</c>" not in srt, "VTT etiketleri temizlenmemiş"
    assert "Merhaba dünya & hoş geldin" in srt, "varlık çözümü/satır birleşimi bozuk"
    assert "<b>İkinci</b>" in srt, "oynatıcıların desteklediği <b> korunmalı"
    assert detect_subtitle_kind(srt) == "srt"
    assert "NOTE" not in srt and "X-TIMESTAMP-MAP" not in srt


def _serve_bodies(bodies: dict):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = bodies.get(self.path)
            if body is None:
                body = HTML_SAMPLE.encode()
                self.send_response(404)
            else:
                self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a) -> None:
            return

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_subtitle_delivery_keeps_real_format_and_rejects_html() -> None:
    from idm_linux.stream_engine import StreamEngine

    srv, base = _serve_bodies({"/1.vtt": VTT_SAMPLE.encode(), "/sayfa": HTML_SAMPLE.encode()})
    try:
        engine = StreamEngine(Path(tempfile.mkdtemp(prefix="idm_subs_v310_")))

        def run(url: str, filename: str):
            ticket = engine.create_ticket(source_url=url, filename=filename, mode="subs")
            job = engine.get_job(ticket.ticket_id)
            deadline = time.time() + 20
            while time.time() < deadline and not (job.completed or job.failed):
                time.sleep(0.05)
            return ticket, job

        # VTT hedefi → VTT olarak iner, "srt" yalanı yok
        tk_vtt, job_vtt = run(f"{base}/1.vtt", "Film [Türkçe Altyazı].vtt")
        assert tk_vtt.filename.endswith(".vtt"), tk_vtt.filename
        assert job_vtt.completed, job_vtt.error_msg
        # v3.10.1: altyazı artık OUTPUT_FILE'a yazılır (IDM 0 bayt kalma hatasının
        # kök nedeni: iter_bytes_from completed olunca output_file'ı okuyordu).
        assert job_vtt.output_file.is_file()
        vtt_out = job_vtt.output_file.read_text(encoding="utf-8")
        assert vtt_out.lstrip().startswith("WEBVTT")
        assert tk_vtt.estimated_size == len(vtt_out.encode("utf-8")) > 0
        assert tk_vtt.size_exact is True

        # SRT hedeflenirse gerçekten SRT üretilir
        tk_srt, job_srt = run(f"{base}/1.vtt", "Film [Türkçe Altyazı].srt")
        assert tk_srt.filename.endswith(".srt")
        assert job_srt.completed, job_srt.error_msg
        srt_out = job_srt.output_file.read_text(encoding="utf-8")
        assert srt_out.startswith("1\n") and "-->" in srt_out
        assert "WEBVTT" not in srt_out and "align:" not in srt_out

        # HTML/404 gövdesi ASLA altyazı olarak yazılmaz
        tk_bad, job_bad = run(f"{base}/sayfa", "Hata.srt")
        assert not job_bad.completed and job_bad.error_msg, "HTML gövdesi altyazı sanıldı!"
        assert not job_bad.output_file.exists() or job_bad.output_file.stat().st_size == 0
    finally:
        srv.shutdown()


def test_subtitle_probe_does_not_drop_locked_cdn_rows() -> None:
    """403/404 dönen CDN satırı 'sahte' sayılıp SİLİNMEZ (YouTube timedtext vakası)."""
    from idm_linux.hls_streamer import fetch_subtitle_probe

    srv, base = _serve_bodies({"/1.vtt": VTT_SAMPLE.encode(), "/sayfa": HTML_SAMPLE.encode()})
    try:
        status, size, kind = fetch_subtitle_probe(f"{base}/1.vtt", {})
        assert status == "ok" and size > 0 and kind == "vtt"
        status2, _size2, _kind2 = fetch_subtitle_probe(f"{base}/yok", {})
        assert status2 == "unknown", f"HTTP hata yanıtı 'bad' sayılmamalı: {status2}"
        status3, _s3, _k3 = fetch_subtitle_probe(f"{base}/sayfa", {})
        assert status3 == "bad", "2xx alıp altyazı olmayan içerik elenmeli"
    finally:
        srv.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
# 3) Altyazı kasası (oynatıcıya gömülü altyazı → IDM)
# ─────────────────────────────────────────────────────────────────────────────
def test_subtitle_vault_store_and_serve() -> None:
    from idm_linux.daemon import DaemonState, make_http_handler, store_subtitle_text

    info = store_subtitle_text(VTT_SAMPLE, label="Türkçe Altyazı")
    assert info and info["ext"] == "vtt" and info["size"] > 0
    assert store_subtitle_text(HTML_SAMPLE, label="sahte") is None

    state = DaemonState()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_http_handler(state))
    port = srv.server_address[1]
    state.cfg.http_port = port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/subtitle/{info['name']}", timeout=10) as resp:
            body = resp.read().decode("utf-8")
        assert resp.status == 200 and body.lstrip().startswith("WEBVTT")
        assert "Merhaba" in body

        # Kayıt uç noktası: eklentiden gelen cue metni → yerel URL
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/subtitle/register",
            data=json.dumps({"vtt": VTT_SAMPLE, "label": "Türkçe Altyazı"}).encode(),
            headers={"Content-Type": "application/json", "X-IDM-Linux": "1"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp2:
            payload = json.loads(resp2.read().decode())
        assert payload.get("ok"), payload
        assert payload["url"].endswith(".vtt") and payload["size"] > 0
        with urllib.request.urlopen(payload["url"], timeout=10) as resp3:
            assert resp3.read().lstrip().startswith(b"WEBVTT")

        # Yol kaçışı denemesi reddedilir
        bad_name = urllib.parse.quote("../../etc/passwd") if hasattr(urllib, "parse") else "%2e%2e%2fpasswd"
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/subtitle/{bad_name}", timeout=5)
            raise AssertionError("yol kaçışı isteği kabul edildi!")
        except urllib.error.HTTPError as exc:
            assert exc.code in (400, 404)
    finally:
        srv.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
# 4) eD2K sunucu listesi ayrıştırma
# ─────────────────────────────────────────────────────────────────────────────
def test_ed2k_server_list_parsing_variants() -> None:
    from idm_linux.p2p.ed2k_native import parse_server_met

    text_list = b"1.2.3.4:4232\n5.6.7.8 4242\n# yorum satiri\n10.0.0.1:4232\n"
    parsed = parse_server_met(text_list)
    assert ("1.2.3.4", 4232) in parsed and ("5.6.7.8", 4242) in parsed
    assert all(not ip.startswith("10.") for ip, _p in parsed), "özel/ayrılmış adres sızmış"

    # ikili server.met: 0xE0 + adet(4) + kayıt(ip4, port2, tagcount4)
    body = bytearray(b"\xE0")
    body += (2).to_bytes(4, "little")
    for ip_bytes, port in ((b"\x01\x02\x03\x04", 4232), (b"\x63\x64\x65\x66", 4232)):
        body += ip_bytes + port.to_bytes(2, "little") + (0).to_bytes(4, "little")
    parsed_bin = parse_server_met(bytes(body))
    assert ("1.2.3.4", 4232) in parsed_bin and ("99.100.101.102", 4232) in parsed_bin
    assert all(port in (4232, 4242) for _ip, port in parsed_bin)


# ─────────────────────────────────────────────────────────────────────────────
# 5) Kredi metni
# ─────────────────────────────────────────────────────────────────────────────
def test_credit_text_arena_and_zai_everywhere() -> None:
    seen = set()
    for lang_dir in ("language", "src/idm_linux/language"):
        for lang_file in sorted((PROJECT_ROOT / lang_dir).glob("*.txt")):
            text = lang_file.read_text(encoding="utf-8")
            m = re.search(r"^footer\.credit_template\s*=\s*(.*)$", text, re.M)
            assert m, f"{lang_file} kredi şablonu yok"
            line = m.group(1)
            assert "{arena}" in line and "{zai}" in line, f"{lang_file}: Z.AI eksik → {line}"
            seen.add(lang_file.name)
    assert len(seen) >= 20, f"20 dil beklenir, görülen {len(seen)}"

    from idm_linux.i18n import I18nManager

    tr = I18nManager("tr").t("footer.credit_template", belgeselsemo="BELGESELSEMO", arena="ARENA.AI", zai="Z.AI")
    assert tr == "Bu araç BELGESELSEMO tarafından ARENA.AI & Z.AI sayesinde yapılmıştır", tr

    gui = (PROJECT_ROOT / "gui.py").read_text(encoding="utf-8")
    assert '{zai}' in gui and 'text="Z.AI"' in gui, "GUI alt bilgisinde Z.AI etiketi yok"
    assert "BELGESELSEMO × ARENA.AI & Z.AI" in gui, "sidebar rozeti güncellenmemiş"
    assert 't("footer.credit_template", belgeselsemo="BELGESELSEMO", arena="ARENA.AI", zai="Z.AI")' in gui, (
        "sidebar rozetinde kredi cümlesi yok"
    )

    for name in ("chromium", "firefox"):
        popup = (PROJECT_ROOT / f"extension/{name}/popup.html").read_text(encoding="utf-8")
        assert "Z.AI" in popup, f"{name} popup kredi metni güncellenmemiş"
    welcome = (PROJECT_ROOT / "welcome_page.py").read_text(encoding="utf-8")
    assert "Z.AI" in welcome


def test_version_is_310_and_extension_bundles_rebuilt() -> None:
    from idm_linux import __version__

    # v3.11.0: sürüm yükseldi; test paketin canlı sürümle eşleşmesini doğrular
    assert __version__ == "1.0.0"
    import zipfile

    for bundle in ("idm-linux-companion-chromium.zip", "idm-linux-companion-firefox.xpi"):
        path = PROJECT_ROOT / "extension" / bundle
        assert path.is_file(), f"{bundle} yok"
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["version"] == __version__, f"{bundle} sürümü güncellenmemiş"
            names = zf.namelist()
            assert "background.js" in names and "page_hook.js" in names
