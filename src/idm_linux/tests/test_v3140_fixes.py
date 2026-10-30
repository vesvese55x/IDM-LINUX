#!/usr/bin/env python3
"""v3.14.0 düzeltmelerinin test paketi.

Kapsam (kullanıcı şikâyeti -> kök-neden -> düzeltme):
  1) "Torrent aşırı yavaş, anlık inip bekliyor" -> GLOBAL BLOK KOORDİNASYONU:
     blok sahipliği oturumda tek yerde; frontier parçası TÜM eşlere şeritlenir;
     8 sn sessiz kalan sahiplik ana döngüde serbest kalır (zombi parça imkânsız).
  2) Tampon sınırı artık yalnız ileri-dolguyu durdurur — frontier her koşulda
     talep edilir (kalıcı kilitlenme vakası kökten bitti).
  3) Magnet/TPB: ut_metadata vs ut_pex ayrımı İÇERİKLE yapılır (id çakışmasında
     meta parçaları PEX dalında yutuluyordu — magnet asla açılmıyordu).
  4) Bütünlük: hizasız/yanlış boyutlu bloklar reddedilir; aynı parçada iki kez
     bozuk veri gönderen eş BANLANIR.
  5) Tit-for-tat: request mesajlarına doğrulanmış parçalarla CEVAP veriyoruz
     (küçük sürülerde unchoke edilmek için hayati).
  6) WebSeed havuzu: paralel, frontier-öncelikli, tekrar denemeli.
  7) Akış-takılma dedektörü + taze keşif.
  8) Gofile 401: token tazeleme + wt JS kazıma + accountToken cookie.
  9) yt-dlp gofile'a dokunmaz; COM köprüsü arıza önbelleği.
 10) Sürüm: 3.14.0
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_BASE = Path(__file__).resolve().parents[2]  # yeni düzen: idm_linux paketini içeren src/ dizini
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


def _make_session(total_size: int = 4 * 16384, piece_len: int = 16384):
    """Ağsız test oturumu: sahte meta ile (tüm bağlamlar init'li)."""
    from collections import deque

    from idm_linux.p2p.bt_native import TorrentFile, TorrentMeta

    meta = TorrentMeta(
        info_hash=bytes(range(20)),
        name="test",
        piece_length=piece_len,
        pieces=[bytes(20)] * max(1, total_size // piece_len),
        files=[TorrentFile(path="test.bin", length=total_size, offset=0)],
        total_size=total_size,
        is_multi_file=False,
    )
    from idm_linux.p2p.bt_native import NativeTorrentSession

    sess = NativeTorrentSession.__new__(NativeTorrentSession)
    sess.meta = meta
    sess._meta = meta
    sess.info_hash = meta.info_hash
    sess.stopping = False
    sess.paused = False
    sess.stream_cursor = 0
    sess.error_message = ""
    sess._log = lambda m: None  # sessiz test günlüğü
    sess.max_peers = 10
    sess.lock = threading.RLock()
    sess._blk_lock = threading.RLock()
    sess._blk_owner = {}
    sess._blk_buf = {}
    sess._blk_buffered = 0
    sess._blk_src = {}
    sess._peer_fail_pieces = {}
    sess._banned = set()
    sess._peers = {}
    sess._known = deque()
    sess._known_set = set()
    sess._ws_pool = None
    sess.uploaded_bytes = 0
    sess._meta_total = 0
    sess._meta_buf = {}
    sess._meta_requested = set()
    sess._meta_requested_ts = {}
    sess._meta_lock = threading.Lock()
    sess.storage = None
    from idm_linux.p2p.bt_native import PieceManager

    sess.pieces = PieceManager(meta)
    return sess


def _make_peer(sess, ip="1.2.3.4", port=5, bf=None):
    from idm_linux.p2p.bt_native import PeerConn

    p = PeerConn.__new__(PeerConn)
    p.session = sess
    p.ip = ip
    p.port = port
    p.alive = True
    p.choked = False
    p.interested = True
    p.peer_id = b"X" * 20
    p.peer_bf = bf
    p.ut_metadata_id = 0
    p.ut_pex_id = 0
    p.requested = set()
    p.requested_times = {}
    p.last_block_ts = time.time()
    p.downloaded = 0
    p._upload_outstanding = 0
    return p


class TestGlobalBlockCoordination(unittest.TestCase):
    """v3.14.0 çekirdek düzeltmesi: parça = TÜM eşlerin ortak işi."""

    def test_two_peers_complete_one_piece(self) -> None:
        """İki eş farklı blokları getirir — parça yine tamamlanır (eski tasarımda imkânsızdı)."""
        from idm_linux.p2p.bt_native import BLOCK_SIZE

        sess = _make_session(total_size=32768, piece_len=32768)  # 1 parça, 2 blok
        bf = bytearray(1)
        bf[0] = 0b11000000
        pa = _make_peer(sess, ip="10.0.0.1", bf=bf)
        pb = _make_peer(sess, ip="10.0.0.2", bf=bf)
        blocks = sess._pick_blocks(pa, 48)
        self.assertEqual(len(blocks), 2)  # 32KB parça = 2 x 16KB blok
        (i0, b0, l0), (i1, b1, l1) = blocks
        self.assertEqual((i0, b0, l0), (0, 0, BLOCK_SIZE))
        self.assertEqual((i1, b1, l1), (0, BLOCK_SIZE, BLOCK_SIZE))
        # eş A yalnız ilk bloğu getirdi, eş B ikincisi — global şeritleme sayesinde
        sess._on_block(pa, 0, b0, b"A" * l0)
        self.assertFalse(sess.pieces.have[0])  # henüz eksik
        delivered = {}

        def fake_download(index, data):
            delivered["ok"] = True
            sess.pieces.mark_have(index)  # gerçek akıştaki gibi işaretle

        sess._on_piece_downloaded = fake_download
        sess._on_block(pb, 0, b1, b"B" * l1)
        self.assertTrue(delivered.get("ok"))  # parça tamamlandı!
        self.assertTrue(sess.pieces.have[0])

    def test_expired_claim_is_reclaimable(self) -> None:
        """8 sn yanıt gelmeyen sahiplik otomatik serbest kalır (zombi blok imkânsız)."""
        from idm_linux.p2p.bt_native import REQUEST_BLOCK_TIMEOUT

        sess = _make_session(total_size=16384)
        bf = bytearray(1)
        bf[0] = 0b11000000
        pa = _make_peer(sess, ip="10.0.0.1", bf=bf)
        pb = _make_peer(sess, ip="10.0.0.2", bf=bf)
        got = sess._pick_blocks(pa, 48)
        self.assertEqual(len(got), 1)
        # süreyi elle eskilt
        for k in list(sess._blk_owner):
            ts, owner = sess._blk_owner[k]
            sess._blk_owner[k] = (ts - REQUEST_BLOCK_TIMEOUT - 0.1, owner)
        got2 = sess._pick_blocks(pb, 48)
        self.assertEqual(len(got2), 1)  # süre dolan blok B'ye geçti

    def test_fresh_claim_not_duplicated(self) -> None:
        """Taze sahiplik çift talep edilmez (mükerrer trafik yok)."""
        sess = _make_session(total_size=4 * 16384)
        bf = bytearray(1)
        bf[0] = 0b11110000
        pa = _make_peer(sess, bf=bf)
        pb = _make_peer(sess, bf=bf)
        a_blocks = {(i, b) for i, b, _l in sess._pick_blocks(pa, 48)}
        b_blocks = {(i, b) for i, b, _l in sess._pick_blocks(pb, 48)}
        self.assertTrue(a_blocks)
        self.assertFalse(a_blocks & b_blocks)  # kesişim boş — temiz iş bölümü

    def test_frontier_priority(self) -> None:
        """Frontier bölgesindeki bloklar ÖNCE dağıtılır (IDM akışı için)."""
        sess = _make_session(total_size=8 * 32768, piece_len=32768)
        bf = bytearray(1)
        bf[0] = 0b11111111
        pa = _make_peer(sess, bf=bf)
        blocks = sess._pick_blocks(pa, 2)
        self.assertEqual([i for i, _b, _l in blocks], [0, 0])  # frontier parçasının iki bloğu

    def test_buffer_cap_spares_frontier(self) -> None:
        """Tampon dolu olsa bile frontier bölgesi talep edilmeye devam eder."""
        from idm_linux.p2p.bt_native import MAX_BUFFERED_BYTES

        sess = _make_session(total_size=8 * 32768, piece_len=32768)
        bf = bytearray(1)
        bf[0] = 0b11111111
        sess._blk_buffered = MAX_BUFFERED_BYTES  # tavan
        pa = _make_peer(sess, bf=bf)
        blocks = sess._pick_blocks(pa, 48)
        self.assertTrue(blocks)  # frontier bölgesi kilitlenmez
        self.assertTrue(all(i < 32 for i, _b, _l in blocks))  # yalnız frontier bölgesi


class TestIntegrityDefense(unittest.TestCase):
    def test_bad_blocks_rejected(self) -> None:
        """Hizasız / yanlış boyutlu blok parçayı KİRLETMEDEN reddedilir."""
        sess = _make_session(total_size=32768, piece_len=32768)  # 1 parça, 2 blok
        pa = _make_peer(sess)
        sess._on_block(pa, 0, 100, b"X" * 16384)  # hizasız begin
        self.assertEqual(sess._blk_buf.get(0, {}), {})
        sess._on_block(pa, 0, 0, b"X" * 100)  # yanlış boyut
        self.assertEqual(sess._blk_buf.get(0, {}), {})
        sess._on_block(pa, 0, 0, b"X" * 16384)  # doğru
        self.assertEqual(len(sess._blk_buf[0]), 1)  # tamponda bekliyor (2. blok eksik)

    def test_repeat_bad_peer_banned(self) -> None:
        """Aynı parçada İKİ denemede de katkısı olan eş banlanır (libtorrent tarzı).

        Yalnız bir denemede katkısı olan eş korunur — masum eşi banlamaz."""
        sess = _make_session(total_size=32768, piece_len=32768)  # 2 blok
        pa = _make_peer(sess, ip="9.9.9.9")   # şüpheli (her iki denemede var)
        pb = _make_peer(sess, ip="8.8.8.8")   # yalnız 1. denemede
        pc = _make_peer(sess, ip="7.7.7.7")   # yalnız 2. denemede
        closed = []
        pa.close = lambda: closed.append(1)  # type: ignore[method-assign]
        sess._peers[("9.9.9.9", 5)] = pa  # ban yolu bağlantıyı keser
        # 1. deneme: pa + pb katkı -> SHA1 düşer
        sess._on_block(pa, 0, 0, b"A" * 16384)
        sess._on_block(pb, 0, 16384, b"B" * 16384)
        sess._on_piece_downloaded(0, b"BOZUK" * 6554)
        self.assertFalse(sess.pieces.have[0])
        self.assertIn(("9.9.9.9", 5), sess._peer_fail_pieces)
        self.assertIn(("8.8.8.8", 5), sess._peer_fail_pieces)
        # 2. deneme: pa + pc katkı -> SHA1 yine düşer -> SADECE pa banlanır
        sess._on_block(pa, 0, 0, b"A" * 16384)
        sess._on_block(pc, 0, 16384, b"C" * 16384)
        sess._on_piece_downloaded(0, b"BOZUK" * 6554)
        self.assertIn(("9.9.9.9", 5), sess._banned)
        self.assertNotIn(("8.8.8.8", 5), sess._banned)
        self.assertNotIn(("7.7.7.7", 5), sess._banned)
        self.assertTrue(closed)

    def test_banned_peer_never_reconnected(self) -> None:
        from collections import deque

        sess = _make_session()
        sess._banned.add(("6.6.6.6", 1))
        sess._known = deque([("6.6.6.6", 1), ("7.7.7.7", 2)])
        sess.max_peers = 10
        sess._connect_more()
        self.assertNotIn(("6.6.6.6", 1), sess._peers)


class TestMagnetExtensionDispatch(unittest.TestCase):
    """TPB vakası: eşin ut_pex id'si bizim ut_metadata id'mizle çakışıyordu."""

    def _peer_with_ext(self, ut_metadata_id: int, ut_pex_id: int):
        from idm_linux.p2p.bt_native import PeerConn

        sess = _make_session(total_size=16384)
        sess.meta = None  # magnet senaryosu: meta henüz yok
        p = PeerConn.__new__(PeerConn)
        p.session = sess
        p.ip = "8.8.8.8"
        p.port = 1
        p.ut_metadata_id = ut_metadata_id
        p.ut_pex_id = ut_pex_id
        p.alive = True
        return sess, p

    def test_metadata_data_survives_pex_id_collision(self) -> None:
        from idm_linux.p2p.bencode import bencode

        sess, p = self._peer_with_ext(ut_metadata_id=2, ut_pex_id=1)
        # gelen mesaj ext_id=1 ile (çakışma!) ama gövde ut_metadata DATA
        body = bencode({b"msg_type": 1, b"piece": 0, b"total_size": 3 * 16384}) + b"M" * 16384
        p._on_extended(bytes([1]) + body)
        self.assertIn(0, sess._meta_buf)
        self.assertEqual(sess._meta_buf[0], b"M" * 16384)

    def test_pex_still_parsed(self) -> None:
        from idm_linux.p2p.bencode import bencode

        sess, p = self._peer_with_ext(ut_metadata_id=2, ut_pex_id=1)
        added = bytes([10, 0, 0, 1]) + (6060).to_bytes(2, "big")
        body = bencode({b"added": added})
        called = []
        sess._add_known = lambda peers, front=False: called.append(list(peers))  # type: ignore[method-assign]
        p._on_extended(bytes([1]) + body)
        self.assertEqual(called, [[("10.0.0.1", 6060)]])

    def test_metadata_request_lock_expires(self) -> None:
        from idm_linux.p2p.bencode import bencode

        sess, p = self._peer_with_ext(ut_metadata_id=7, ut_pex_id=0)
        sent = []
        p._send_extended = lambda eid, payload: sent.append(payload)  # type: ignore[method-assign]
        sess._meta_total = 4 * 16384
        sess._request_metadata_from(p)
        self.assertEqual(len(sent), 4)
        # 16 sn sonra kilitleme süresi dolduğunda yeniden istenir
        for k in list(sess._meta_requested_ts):
            sess._meta_requested_ts[k] -= 16.0
        sess._request_metadata_from(p)
        self.assertEqual(len(sent), 8)


class TestUploadTitForTat(unittest.TestCase):
    def test_upload_serves_owned_pieces_only(self) -> None:
        from idm_linux.p2p.bencode import bencode
        from idm_linux.p2p.bt_native import Storage

        sess = _make_session(total_size=16384)
        tmp = Path(__import__("tempfile").mkdtemp())
        sess.storage = Storage(tmp, sess.meta)
        sess.storage.write(0, b"U" * 16384)
        sess.pieces.mark_have(0)
        pa = _make_peer(sess)
        sent = []
        pa._send_msg = lambda mid, payload=b"": sent.append((mid, payload)) or True  # type: ignore[method-assign]
        # sahip olunan parça için istek -> cevap gelir (payload = index+begin+data)
        pa._serve_upload(((0).to_bytes(4, "big") + (0).to_bytes(4, "big") + (16384).to_bytes(4, "big")))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], 7)
        self.assertEqual(sent[0][1][8:], b"U" * 16384)
        # sahip olunmayan parça için istek -> sessiz
        sent.clear()
        pa._serve_upload(((3).to_bytes(4, "big") + (0).to_bytes(4, "big") + (16384).to_bytes(4, "big")))
        self.assertEqual(sent, [])
        sess.storage.close_all()


class TestWebSeedPoolAndStallDetector(unittest.TestCase):
    def test_pool_parallel_and_retry(self) -> None:
        src = _read("src/idm_linux/p2p/bt_native.py")
        self.assertIn("class WebSeedPool", src)
        self.assertNotIn("class WebSeedWorker", src)
        self.assertIn("RETRY_AFTER", src)
        # 6 işçi + frontier önceliği + P2P yarışması engeli
        self.assertIn("workers: int = 6", src)
        self.assertIn("P2P bu parçada çalışıyor", src)

    def test_stall_detector_triggers_refresh(self) -> None:
        src = _read("src/idm_linux/p2p/bt_native.py")
        self.assertIn("akış takıldı", src)
        self.assertIn("_frontier_last_advanced", src)


class TestGoFileAndMisc(unittest.TestCase):
    def test_gofile_401_recovery(self) -> None:
        src = _read("src/idm_linux/gofile_resolver.py")
        self.assertIn("force_new", src)
        self.assertIn("_invalidate_token", src)
        self.assertIn("misafir token tazeleniyor", src)
        self.assertIn("def account_token", src)
        self.assertIn("def prewarm", src)
        self.assertIn("except urllib.error.HTTPError as exc:", src)  # hata kodu döner

    def test_gofile_account_cookie_in_daemon(self) -> None:
        src = _read("src/idm_linux/daemon.py")
        self.assertIn("accountToken={gofile_token}", src)
        self.assertIn("account_token=gofile_token", src)
        self.assertIn("prewarm()", src)

    def test_never_probe_file_hosts(self) -> None:
        src = _read("src/idm_linux/stream_engine.py")
        self.assertIn("NEVER_YTDLP_PROBE", src)
        self.assertIn("_never_ytdlp_probe(page_url)", src)

    def test_com_failure_cache(self) -> None:
        src = _read("src/idm_linux/wine_sender.py")
        self.assertIn("_com_skip_until", src)
        self.assertIn("_com_fail_streak", src)
        self.assertIn("COM_SKIP_SECS", src)


class TestVersion(unittest.TestCase):
    def test_version_bumped(self) -> None:
        import idm_linux

        self.assertEqual(idm_linux.__version__, "1.0.0")
        self.assertIn('"version": "1.0.0"', _read("extension/chromium/manifest.json"))
        self.assertIn('"version": "1.0.0"', _read("extension/firefox/manifest.json"))

    def test_engine_identity_string(self) -> None:
        src = _read("src/idm_linux/p2p/bt_native.py")
        self.assertIn(b'IDM-Linux 1.0'.decode(), src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
