#!/usr/bin/env python3
"""v3.13.0 düzeltmelerinin test paketi.

Kapsam (kullanıcı şikâyetleri -> düzeltmeler):
  1) Trial Reset: doğrulama tabanlı akış (wine reg sahte dönüş kodlarına dayanmaz)
  2) Gofile: çözücü ayrıştırma + daemon doğru-yakalama akışı + eklenti otomasyonu
  3) ok.ru: okcdn.ru yt-dlp zincirinde + kırık ekstrakt hızlı yükseltmesi
  4) Torrent/TPB: tüm magnet URİ'leri yakalanır + UDP yeniden deneme + endgame
  5) Motor hızı/istikrarı: blok zaman aşımı, çoklu-parça, artımlı sayaç, LRU tutamak
  6) IDM İPTAL: köprü istemci izleyicisi -> motor 60 sn sonra duraklatılır
  7) GUI: canlı/DVR kartı kaldırıldı (işlev daemon'da duruyor)
  8) Sürüm: 3.13.0
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


class TestTrialReset(unittest.TestCase):
    def test_verify_based_flow(self) -> None:
        src = _read("src/idm_linux/wine_sender.py")
        self.assertIn("_reg_key_exists", src)
        self.assertIn("_reg_value_exists", src)
        self.assertIn("_prewarm_wineserver", src)
        self.assertIn("_wait_idm_exited", src)
        # eski kırılgan tek-dönüş-kodu mantığı kalmadı
        self.assertNotIn('res.returncode == 0:\n                    deleted_any = True', src)
        self.assertNotIn("wine reg dönmedi). Wine ortamını kontrol edin.\"", src.replace(
            "DMCACount anahtarı silinemiyor", "X"))

    def test_success_criterion_is_hkcu_counter(self) -> None:
        src = _read("src/idm_linux/wine_sender.py")
        self.assertIn('hkcu_path = r"HKCU\\Software\\DMCACount"', src)
        self.assertIn("counter_ok = hkcu_path not in counter_paths_alive", src)


class TestGofile(unittest.TestCase):
    def test_resolver_parsing(self) -> None:
        from idm_linux.gofile_resolver import (
            extract_content_id,
            extract_file_id_from_store_link,
            is_gofile_store_link,
            is_gofile_url,
        )
        self.assertTrue(is_gofile_url("https://gofile.io/d/AbCdEf"))
        self.assertTrue(is_gofile_url("https://store1.gofile.io/download/web/x/f.zip"))
        self.assertFalse(is_gofile_url("https://example.com/d/x"))
        self.assertEqual(extract_content_id("https://gofile.io/d/AbCdEf?x=1"), "AbCdEf")
        self.assertTrue(is_gofile_store_link("https://store9.gofile.io/download/web/FILEID1/arşiv.zip"))
        self.assertEqual(extract_file_id_from_store_link("https://store9.gofile.io/download/web/FILEID1/a.zip"), "FILEID1")

    def test_daemon_gofile_flow(self) -> None:
        src = _read("src/idm_linux/daemon.py")
        for needle in (
            "dispatch_gofile(",
            "_gofile_direct_ok(",
            "from .gofile_resolver import",
            'text/html" in ct',
        ):
            self.assertIn(needle, src)
        # HTML hata gövdesi asla doğrudan geçmez (yoklama bütçeli, köprüye düşer)
        self.assertIn('box["ok"] = False  # hata sayfası', src)
        self.assertIn("_pt.join(timeout=6.0)", src)

    def test_extension_gofile_automatic(self) -> None:
        src = _read("extension/chromium/content.js")
        # onay pencereleri gofile'dan kalktı
        self.assertNotIn("Gofile dosyası IDM-Linux ile indirilsin mi", src)
        src_bg = _read("extension/chromium/background.js")
        self.assertIn("/gofile\\.io\\//i.test(url)", src_bg)
        self.assertIn("intercept: true, url, referer, forced: true", src_bg)
        src_ph = _read("extension/chromium/page_hook.js")
        self.assertIn("Location.prototype.assign", src_ph)
        self.assertIn("Location.prototype.replace", src_ph)

    def test_extension_parity(self) -> None:
        for name in ("background.js", "content.js", "page_hook.js"):
            self.assertEqual(
                _read(f"extension/chromium/{name}"),
                _read(f"extension/firefox/{name}"),
                f"{name} chromium/firefox senkronu bozulmuş",
            )


class TestOkRu(unittest.TestCase):
    def test_okcdn_in_ytdlp_chain(self) -> None:
        src = _read("src/idm_linux/stream_engine.py")
        self.assertIn('"okcdn.ru",', src)

    def test_okru_fast_upgrade_window(self) -> None:
        src = _read("src/idm_linux/stream_engine.py")
        self.assertIn("okru_broken", src)
        self.assertIn("odnoklassniki", src)


class TestTorrentTpb(unittest.TestCase):
    def test_all_magnet_links_captured(self) -> None:
        src = _read("extension/chromium/content.js")
        self.assertIn('low.startsWith("magnet:")', src)
        self.assertNotIn('low.startsWith("magnet:?xt=")', src)
        self.assertIn("composedPath", src)

    def test_udp_retry_and_wider_announce(self) -> None:
        src = _read("src/idm_linux/p2p/tracker.py")
        self.assertIn("announce zaman aşımı (3 deneme)", src)
        self.assertIn("connect zaman aşımı (3 deneme)", src)
        self.assertIn("normalize_trackers(trackers)[:24]", src)


class TestEnginePerformance(unittest.TestCase):
    def test_block_timeout_rerequest(self) -> None:
        src = _read("src/idm_linux/p2p/bt_native.py")
        self.assertIn("REQUEST_BLOCK_TIMEOUT", src)
        self.assertIn("_expire_stale_requests", src)

    # v3.14.0 NOT: "eş başına parça hattı" (ACTIVE_PIECES_PER_PEER / _endgame_request)
    # GLOBAL BLOK KOORDİNASYONU ile değiştirildi — blok sahipliği oturumda tek
    # yerde tutulur, frontier parçası tüm eşlere şeritlenir, süresi dolan
    # sahiplikler ana döngüde serbest kalır. Aşağıdaki doğrulamalar yeni tasarımı
    # kapsar (ayrıntılı davranış testleri: test_v3140_fixes.py).
    def test_multi_piece_pipeline(self) -> None:
        src = _read("src/idm_linux/p2p/bt_native.py")
        self.assertIn("_blk_owner", src)
        self.assertIn("_pick_blocks", src)
        self.assertIn("_on_block", src)
        self.assertIn("GLOBAL BLOK KOORDİNASYONU", src)

    def test_incremental_state(self) -> None:
        src = _read("src/idm_linux/p2p/bt_native.py")
        self.assertIn("self.have_bytes += self.meta.piece_size(index)", src)
        self.assertIn("self._bf_dirty", src)
        self.assertIn("MAX_OPEN_HANDLES", src)

    def test_native_pause_resume(self) -> None:
        src = _read("src/idm_linux/p2p/bt_native.py")
        self.assertIn("def pause(self) -> None:", src)
        self.assertIn("def resume(self) -> None:", src)
        self.assertIn("motor DURAKLATILDI", src)


class TestCancelNeverBackground(unittest.TestCase):
    def test_bridge_client_watchdog(self) -> None:
        src = _read("src/idm_linux/torrent_engine.py")
        self.assertIn("note_client_connect", src)
        self.assertIn("note_client_disconnect", src)
        self.assertIn("CLIENT_GONE_GRACE_SEC", src)
        self.assertIn("aria2.forcePause", src)
        self.assertIn("serve_torrent_over_http", src)
        self.assertIn("_serve_torrent_over_http_impl", src)
        self.assertIn("BrokenPipeError", src)

    def test_ed2k_client_watchdog(self) -> None:
        src = _read("src/idm_linux/p2p/ed2k_native.py")
        self.assertIn("note_client_connect", src)
        self.assertIn("note_client_disconnect", src)
        self.assertIn("CLIENT_GONE_GRACE_SEC", src)
        self.assertIn("oturum DURAKLATILDI", src)


class TestGuiSimplification(unittest.TestCase):
    def test_stream_card_removed_but_function_intact(self) -> None:
        gui = _read("src/idm_linux/gui.py")
        self.assertNotIn("AKTİF CANLI / DVR KAYIT İZLEYİCİ", gui)
        self.assertNotIn("streams_box", gui)
        # daemon tarafındaki işlev (API uçları) aynen duruyor
        daemon = _read("src/idm_linux/daemon.py")
        self.assertIn('"/api/streams/clear"', daemon)
        self.assertIn('"/api/stream/stop"', daemon)


class TestVersion(unittest.TestCase):
    def test_version_bumped(self) -> None:
        import idm_linux

        self.assertEqual(idm_linux.__version__, "1.0.0")
        self.assertIn('"version": "1.0.0"', _read("extension/chromium/manifest.json"))
        self.assertIn('"version": "1.0.0"', _read("extension/firefox/manifest.json"))


class TestEngineFunctional(unittest.TestCase):
    """Motor davranışsal doğrulama (ağ yok)."""

    def _make_meta(self):
        from idm_linux.p2p.bt_native import TorrentFile, TorrentMeta

        meta = TorrentMeta(
            info_hash=bytes(range(20)),
            name="test",
            piece_length=32768,
            pieces=[bytes(20)] * 4,
            files=[TorrentFile(path="test.bin", length=100_000, offset=0)],
            total_size=100_000,
            is_multi_file=False,
        )
        return meta

    def test_piece_manager_incremental(self) -> None:
        from idm_linux.p2p.bt_native import PieceManager

        meta = self._make_meta()
        pm = PieceManager(meta)
        self.assertEqual(pm.completed_bytes(), 0)
        self.assertTrue(pm.mark_have(0))
        self.assertEqual(pm.completed_bytes(), 32768)
        self.assertFalse(pm.mark_have(0))
        self.assertEqual(pm.completed_bytes(), 32768)
        self.assertEqual(pm.contiguous(), 1)
        self.assertFalse(pm.all_done)
        for i in range(4):
            pm.mark_have(i)
        self.assertTrue(pm.all_done)
        self.assertEqual(pm.completed_bytes(), meta.total_size)
        bf = pm.bitfield_bytes()
        self.assertEqual(len(bf), 1)
        self.assertEqual(bf[0], 0b11110000)

    def test_storage_roundtrip_and_lru(self) -> None:
        import tempfile

        from idm_linux.p2p.bt_native import Storage

        meta = self._make_meta()
        with tempfile.TemporaryDirectory() as td:
            st = Storage(Path(td), meta)
            st.write(0, b"ABCDE")
            self.assertEqual(st.read(0, 5), b"ABCDE")
            st.close_all()
            self.assertEqual(st.read(0, 5), b"ABCDE")  # tutamak kapandıysa yeniden açılır

    def test_metadata_multi_request(self) -> None:
        from idm_linux.p2p.bt_native import METADATA_PIECE, NativeTorrentSession

        # yalnız meta isteği mantığını doğrular (ağ yok)
        sent: list = []

        class FakePeer:
            ut_metadata_id = 7

            def _send_extended(self, ext_id, payload):
                sent.append(payload)

        import threading

        # vaka 1: toplam boyut BİLİNMİYOR -> yalnız 0. parça istenir (spam yok)
        sess = NativeTorrentSession.__new__(NativeTorrentSession)
        sess.meta = None
        sess._meta_total = 0
        sess._meta_buf = {}
        sess._meta_requested = set()
        sess._meta_requested_ts = {}  # v3.14.0: istek kilidi süre aşımı haritası
        sess._meta_lock = threading.Lock()
        sess._request_metadata_from(FakePeer())
        self.assertEqual(len(sent), 1)
        sess._request_metadata_from(FakePeer())
        self.assertEqual(len(sent), 1)  # zaten istendi

        # vaka 2: toplam boyut BİLİNİYOR -> eşzamanlı 4 parça
        sent.clear()
        sess2 = NativeTorrentSession.__new__(NativeTorrentSession)
        sess2.meta = None
        sess2._meta_total = 5 * METADATA_PIECE  # 5 parça
        sess2._meta_buf = {}
        sess2._meta_requested = set()
        sess2._meta_requested_ts = {}
        sess2._meta_lock = threading.Lock()
        sess2._request_metadata_from(FakePeer())
        self.assertEqual(len(sent), 4)
        sess2._request_metadata_from(FakePeer())
        self.assertEqual(len(sent), 5)  # kalan 1 parça
        self.assertEqual(METADATA_PIECE, 16384)


if __name__ == "__main__":
    unittest.main(verbosity=2)
