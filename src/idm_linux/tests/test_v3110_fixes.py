#!/usr/bin/env python3
"""v3.11.0 düzeltmelerinin test paketi.

Kapsam (kullanıcı şikâyetleri → düzeltmeler):
  1) YouTube kaynakları anında: googlevideo yakalama (background.js) + streamingData
     madenciliği (page_hook.js) + bot-check'te hızlı yt-dlp yükseltmesi
  2) YouTube altyazı 0 bayt: downsub-yaklaşımı sayfa-içi fetch + timedtext yt-dlp yedeği
  3) ok.ru indirmeleri: okcdn.ru/mycdn.me/vkuser.net proxy-needy + auth_proxy 400 kuralı
  4) gofile anında algılama + gerçek URL + "Dosya (ZIP)" dürüst etiketi
  5) Torrent: tracker zenginleştirme + ut_pex + DHT paralel + tar zaman aşımı
  6) eD2K paralel kaynak taraması
  7) Bellek sızıntıları: active_timers, probe executor, inflight clear
"""
from __future__ import annotations

import json
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_BASE = Path(__file__).resolve().parents[2]  # yeni düzen: idm_linux paketini içeren src/ dizini
import sys

sys.path.insert(0, str(SRC_BASE))  # yeni düzen: src/ tabanı


def _read(rel: str) -> str:
    # Yeni düzende kaynak dosyalar PROJECT_ROOT (src/idm_linux) içindedir;
    # eski "src/idm_linux/..." göreceli yolları da uyumlulukla kabul edilir.
    if rel.startswith("src/idm_linux/"):
        rel = rel[len("src/idm_linux/"):]
    for cand in (PROJECT_ROOT / rel, SRC_BASE / rel, PROJECT_ROOT.parents[1] / rel):
        try:
            if cand.exists():
                return cand.read_text(encoding="utf-8")
        except OSError:
            continue
    raise FileNotFoundError(rel)


class TestV3110YouTubeInstantSources(unittest.TestCase):
    def test_01_background_no_longer_skips_googlevideo(self) -> None:
        src = _read("extension/chromium/background.js")
        # eski blanket-skip satırı kaldırılmalıydı
        self.assertNotIn('if (url.includes("googlevideo.com/videoplayback")) return;', src)
        self.assertIn("videoplayback", src)
        self.assertIn("ytSeriesCount", src)
        # segment-vari parametreler soyulmalı (tam dosya URL'i kalmalı)
        for param in ("range", "rn", "rbuf", "cmsg", "keepalive"):
            self.assertIn(f'"{param}"', src)
        # clen parametresinden gerçek boyut okunmalı
        self.assertIn("clen", src)
        # sekme temizliğinde sayaç da düşülmeli (bellek)
        self.assertIn("ytSeriesCount.delete(tabId)", src)

    def test_02_page_hook_mines_streaming_data(self) -> None:
        src = _read("extension/chromium/page_hook.js")
        self.assertIn("mineStreamingData", src)
        self.assertIn("streamingData", src)
        self.assertIn("signatureCipher", src)  # şifreli formatlar atlanır
        # muxed itag seti (IDM tek dosya indirir)
        for itag in ("18", "22", "59", "78"):
            self.assertIn(f'"{itag}"', src)

    def test_03_extension_parity_after_edits(self) -> None:
        for name in ("background.js", "content.js", "page_hook.js"):
            chrom = _read(f"extension/chromium/{name}")
            firef = _read(f"extension/firefox/{name}")
            self.assertEqual(chrom, firef, f"{name} chromium/firefox senkronu bozulmuş")

    def test_04_botcheck_forces_fast_ytdlp_upgrade(self) -> None:
        src = _read("src/idm_linux/stream_engine.py")
        self.assertIn("_ytdlp_upgrade_window_open", src)
        self.assertIn("sign in to confirm", src)
        self.assertIn("10800", src)  # 3 saatlik acil pencere

    def test_05_upgrade_window_functional(self) -> None:
        from idm_linux.stream_engine import _ytdlp_upgrade_window_open, mark_ytdlp_update

        mark_ytdlp_update()
        # taze marker: 3 saat penceresi KAPALI, ama 24 saatlik günlük pencere de kapalı
        self.assertFalse(_ytdlp_upgrade_window_open())


class TestV3110YouTubeSubtitles(unittest.TestCase):
    def test_01_page_side_fetch_downsub_style(self) -> None:
        src = _read("extension/chromium/page_hook.js")
        # altyazı sayfa bağlamında indirilir (çerez+POT dahil)
        self.assertIn('credentials: "include"', src)
        self.assertIn("__idmLinuxSubtitleText", src)
        self.assertIn("WEBVTT", src)
        # başarısızlıkta eski URL girişi bırakılır (dürüst yedek)
        self.assertIn("__idmLinuxSubtitle", src)

    def test_02_timedtext_ytdlp_fallback(self) -> None:
        src = _read("src/idm_linux/stream_engine.py")
        self.assertIn("timedtext", src)
        self.assertIn("YouTube timedtext yedeği", src)
        # yedek yt-dlp kaydını çağırır
        self.assertIn("_run_ytdlp_record_resilient", src)
        # lang parametresi URL'den çıkarılır
        self.assertIn('_q.get("lang")', src)


class TestV3110OkRu(unittest.TestCase):
    def test_01_okcdn_and_vk_cdns_are_proxy_needy(self) -> None:
        from idm_linux.stream_engine import _needs_proxy_host

        self.assertTrue(_needs_proxy_host("https://vd335.okcdn.ru/?expires=1&type=video"))
        self.assertTrue(_needs_proxy_host("https://vd220.mycdn.me/?expires=1"))
        self.assertTrue(_needs_proxy_host("https://cs1-49v4.vkuser.net/url.mp4"))
        self.assertTrue(_needs_proxy_host("https://ok.ru/video/123"))
        # googlevideo hâlâ doğrudan kalmalı
        self.assertFalse(_needs_proxy_host("https://rr3---sn-x.googlevideo.com/videoplayback?itag=22"))

    def test_02_auth_proxy_treats_400_as_referer_lock(self) -> None:
        src = _read("src/idm_linux/auth_proxy.py")
        self.assertIn("e.code in (400, 401, 403, 405)", src)
        self.assertIn("vd*.okcdn.ru", src)  # canlı doğrulama notu

    def test_03_gofile_removed_from_always_proxy(self) -> None:
        src = _read("src/idm_linux/auth_proxy.py")
        seg = src.split("_ALWAYS_PROXY_AUTH_DOMAINS = (")[1].split(")")[0]
        self.assertNotIn('"gofile.io"', seg)
        # dinamik yoklama güvenlik ağı hâlâ mevcut olmalı
        self.assertIn("binary_watch", src)


class TestV3110Gofile(unittest.TestCase):
    def test_01_page_hook_json_inspector(self) -> None:
        src = _read("extension/chromium/page_hook.js")
        self.assertIn("GOFILE ANINDA", src)
        self.assertIn("dumpGofile", src)
        self.assertIn("fileSize", src)
        self.assertIn("fileName", src)

    def test_02_content_registers_bar_entry_without_confirm(self) -> None:
        src = _read("extension/chromium/content.js")
        self.assertIn("Gofile: ", src)
        self.assertIn('sub_label: "Gofile: " + d.fileName', src)
        self.assertIn("gofileAsked", src)  # onay akışı korunur (fileName'siz wt linkleri)

    def test_03_plain_files_labeled_honestly(self) -> None:
        src = _read("src/idm_linux/stream_engine.py")
        self.assertIn("_FILE_ONLY_EXTS", src)
        self.assertIn("Dosya ({ext.upper()})", src)


class TestV3110Torrent(unittest.TestCase):
    def test_01_default_trackers_have_http_fallback(self) -> None:
        from idm_linux.p2p.bt_native import DEFAULT_TRACKERS

        https = [t for t in DEFAULT_TRACKERS if t.startswith("https://")]
        self.assertGreaterEqual(len(https), 3, "UDP yasaklı ağlar için HTTPS tracker gerekli")

    def test_02_single_tracker_torrent_is_enriched(self) -> None:
        import os

        from idm_linux.p2p.bencode import bencode
        from idm_linux.p2p.bt_native import NativeTorrentSession

        info = {
            b"name": b"single-tracker-test.bin",
            b"length": 1000,
            b"piece length": 16384,
            b"pieces": os.urandom(20),
        }
        torrent = {
            b"announce": b"udp://tracker.opentrackr.org:1337/announce",
            b"info": info,
        }
        sess = NativeTorrentSession(
            work_dir=Path("/tmp/idm-test-tracker"),
            torrent_bytes=bencode(torrent),
        )
        # meta tracker'ı yalnız 1 — v3.11.0 DEFAULT listesiyle zenginleşir
        self.assertGreaterEqual(len(sess.trackers), 5)

    def test_03_ut_pex_supported(self) -> None:
        from idm_linux.p2p.bencode import bdecode, bencode
        from idm_linux.p2p.bt_native import NativeTorrentSession, PeerConn

        import os as _os

        info = {b"name": b"pex.bin", b"length": 10, b"piece length": 16384, b"pieces": _os.urandom(20)}
        sess = NativeTorrentSession(
            work_dir=Path("/tmp/idm-test-pex"), torrent_bytes=bencode({b"info": info, b"announce": b"udp://t/announce"})
        )
        peer = PeerConn(sess, "192.0.2.55", 6881)
        peer.ut_pex_id = 2
        compact = bytes([10, 0, 0, 1]) + (6889).to_bytes(2, "big")  # 10.0.0.1:6889
        # _connect_more bağlanma denemesi yapmasın (test izolesi)
        sess._connect_more = lambda: None  # type: ignore[method-assign]
        peer._on_extended(bytes([2]) + bencode({b"added": compact}))
        self.assertIn(("10.0.0.1", 6889), list(sess._known))

        # ut_pex ilanı uzatılmış el sıkışmada bulunmalı
        hs_src = _read("src/idm_linux/p2p/bt_native.py")
        self.assertIn('"ut_pex"', hs_src.replace("'", '"'))
        self.assertIn("UT_PEX_OUR_ID", hs_src)

    def test_04_dht_lookup_runs_even_on_empty_bootstrap(self) -> None:
        src = _read("src/idm_linux/p2p/bt_native.py")
        self.assertIn("doğrudan peer sorgusu", src)
        dht_src = _read("src/idm_linux/p2p/dht.py")
        self.assertIn("PARALEL", dht_src)
        self.assertIn("ThreadPoolExecutor", dht_src)

    def test_05_multifile_tar_has_deadline(self) -> None:
        src = _read("src/idm_linux/torrent_engine.py")
        self.assertIn("tar_deadline", src)
        self.assertIn("900.0", src)

    def test_06_pipeline_widened(self) -> None:
        src = _read("src/idm_linux/p2p/bt_native.py")
        self.assertIn("REQUEST_PIPELINE = 48", src)  # v3.14.0: global blok koordinasyonu ile 48 (768KB/eş)
        self.assertIn("cursor) + 64", src)


class TestV3110Ed2k(unittest.TestCase):
    def test_00_hash_string_converted_to_bytes(self) -> None:
        """KRİTİK: parse_ed2k_link 'hash' STR döndürür; NativeED2KSession bunu BYTES'e
        çevirmeliydi. Eski akışta str kaldığı için bytes+str TypeError ile TÜM kaynak
        sorguları ve eş paketleri sessizce çöküyordu (eD2K kökten ölüydü)."""
        from idm_linux.p2p.ed2k_native import NativeED2KSession

        link = (
            "ed2k://|file|Test.File.2024.720p.mkv|1068275554|"
            "1AFCD68A8B55D38F6D8B4E2D5F1B4B4C|h=PHNKTJXAFZQGBSTLJVLTK3KB7DJRLNX6|/"
        )
        sess = NativeED2KSession(work_dir=Path("/tmp/idm-test-hashfix"), link=link)
        self.assertIsInstance(sess.file_hash, (bytes, bytearray))
        self.assertEqual(bytes(sess.file_hash).hex(), "1afcd68a8b55d38f6d8b4e2d5f1b4b4c")
        self.assertEqual(len(sess.file_hash), 16)
        # info dict ile kurulumda bytes hash olduğu gibi kabul edilmeli
        sess2 = NativeED2KSession(
            work_dir=Path("/tmp/idm-test-hashfix"),
            info={"name": "x.bin", "size": 10, "hash": bytes(range(16)), "link": "ed2k://|file|x|10|00|/"},
        )
        self.assertEqual(bytes(sess2.file_hash), bytes(range(16)))

    def test_01_parallel_source_gathering(self) -> None:
        src = _read("src/idm_linux/p2p/ed2k_native.py")
        self.assertIn("AŞAMA 1", src)
        self.assertIn("AŞAMA 2", src)
        self.assertIn("ThreadPoolExecutor", src)
        # UDP aşaması TCP'den önce gelmeli (hız)
        self.assertLess(src.index("udp_get_sources, host, port"), src.index("_query_server, hp"))

    def test_02_empty_server_list_returns_quietly(self) -> None:
        from idm_linux.p2p.ed2k_native import NativeED2KSession

        sess = NativeED2KSession(
            work_dir=Path("/tmp/idm-test-ed2k"),
            link="ed2k://|file|test.bin|1000|"
            + "0" * 32
            + "|/",
        )
        # boş sunucu listesi istisna fırlatmadan dönmeli
        sess._gather_sources([], force=True)
        self.assertEqual(len(sess._known), 0)

    def test_03_add_peers_thread_safe(self) -> None:
        src = _read("src/idm_linux/p2p/ed2k_native.py")
        self.assertIn("with self._lock:", src.split("def _add_peers")[1].split("return added")[0])


class TestV3110Memory(unittest.TestCase):
    def test_01_gui_recurring_timers_not_accumulated(self) -> None:
        src = _read("src/idm_linux/gui.py")
        # _drain_ui_queue kendi döngüsünde artık id biriktirmez
        drain_seg = src.split("def _drain_ui_queue")[1].split("def _start_install_worker")[0]
        self.assertNotIn("active_timers.append", drain_seg)
        loop_seg = src.split("def _periodic_status_loop")[1].split("_reload_logs()")[0]
        self.assertNotIn("active_timers.append", loop_seg)

    def test_02_daemon_probe_uses_daemon_thread(self) -> None:
        src = _read("src/idm_linux/daemon.py")
        self.assertIn("_probe_done.wait(timeout=75)", src)
        self.assertNotIn("_px.shutdown(wait=False)", src)
        self.assertIn("name=f\"probe-{uuid.uuid4().hex[:6]}\"", src)

    def test_03_inflight_no_wholesale_clear(self) -> None:
        src = _read("src/idm_linux/daemon.py")
        self.assertNotIn("if len(_PROBE_INFLIGHT) > 64:\n                    _PROBE_INFLIGHT.clear()", src)
        self.assertIn("len(_PROBE_INFLIGHT) > 256", src)


class TestV3110VersionBundles(unittest.TestCase):
    def test_01_version_bumped_everywhere(self) -> None:
        from idm_linux import __version__

        self.assertEqual(__version__, "1.0.0")
        pyproject = _read("pyproject.toml")
        self.assertIn('version = "1.0.0"', pyproject)
        for name in ("chromium", "firefox"):
            mf = json.loads(_read(f"extension/{name}/manifest.json"))
            self.assertEqual(mf["version"], "1.0.0")

    def test_02_bundles_rebuilt_with_new_code(self) -> None:
        for bundle, member in (
            ("extension/idm-linux-companion-chromium.zip", "background.js"),
            ("extension/idm-linux-companion-firefox.xpi", "background.js"),
        ):
            path = PROJECT_ROOT / bundle
            self.assertTrue(path.is_file(), f"{bundle} yok")
            with zipfile.ZipFile(path) as zf:
                manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["version"], "1.0.0", f"{bundle} yeniden paketlenmemiş")
                bg = zf.read(member).decode("utf-8")
                self.assertIn("ytSeriesCount", bg, f"{bundle} içindeki {member} eski!")


if __name__ == "__main__":
    unittest.main(verbosity=2)
