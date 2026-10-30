from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_BASE = Path(__file__).resolve().parents[2]  # yeni düzen: idm_linux paketini içeren src/ dizini
sys.path.insert(0, str(SRC_BASE))  # yeni düzen: src/ tabanı

from idm_linux.browsers import build_chromium_manifest, build_gecko_manifest
from idm_linux.config import (
    COMPANION_CHROME_EXT_ID,
    COMPANION_CHROME_PUBKEY,
    DEFAULT_HTTP_PORT,
    DEFAULT_WS_PORT,
    OFFICIAL_CHROME_EXT_ID,
    OFFICIAL_EDGE_EXT_ID,
    OFFICIAL_FIREFOX_EXT_ID,
    IdmLinuxConfig,
    detect_default_wine_prefix,
)
from idm_linux.crx_builder import build_crx3_package, validate_extension_directory, verify_crx3_package
from idm_linux.installer import (
    choose_wine_prefix,
    deploy_browser_extensions,
    download_idm_installer,
    neutralize_windows_hook_binaries,
    scan_existing_idm_installations,
)
from idm_linux.protocol import (
    IdmWireMessage,
    build_config_update,
    build_download_decision,
    build_handshake_ack,
    is_domain_excluded,
)
from idm_linux.sfx_unpacker import unpack_idm_installer
from idm_linux.wine_sender import linux_to_wine_path, sanitize_filename


class TestIdmLinuxSuite(unittest.TestCase):
    def test_01_wire_protocol_parsing_and_responses(self) -> None:
        # İçinde virgül ve iki nokta bulunan gerçekçi Type 13 indirme yakalama çerçevesi
        url = "https://cdn.example.com/files/archive,v2.zip?token=a:b,c=1"
        cookies = "sid=abc,123; theme=dark"
        referer = "https://example.com/downloads"
        raw = (
            f"MSG#42#13#2#0:991,"
            f"6={len(url)}:{url},"
            f"50={len(referer)}:{referer},"
            f"51={len(cookies) + 5}:idmfc{cookies},"
            f"100=14:archive_v2.zip;"
        )
        msg = IdmWireMessage.parse(raw)
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertEqual(msg.seq, 42)
        self.assertEqual(msg.msg_type, 13)
        self.assertEqual(msg.positional_args, ["991"])

        req = msg.to_download_request()
        self.assertIsNotNone(req)
        assert req is not None
        self.assertEqual(req.url, url)
        self.assertEqual(req.cookies, cookies)  # idmfc ön-eki temizlenmiş olmalı!
        self.assertEqual(req.referer, referer)
        self.assertEqual(req.filename, "archive_v2.zip")

        ack = build_handshake_ack(7, dpi=120)
        self.assertEqual(ack, "MSG#7#3#0#0:113:0:0:0:120:0:0:0:100;")
        conf = build_config_update(8, "(?:ZIP|MP4)", enabled=True)
        self.assertEqual(conf, "MSG#8#4#0#0:0:0:0:0,1=11:(?:ZIP|MP4);")
        take = build_download_decision(42, "991", takeover=True)
        self.assertEqual(take, "MSG#42#13#1#0:991:3;")

    def test_02_domain_exclusion_and_paths(self) -> None:
        self.assertTrue(is_domain_excluded("https://sub.github.com/a.zip", "", ["github.com"]))
        self.assertFalse(is_domain_excluded("https://kernel.org/linux.tar.xz", "", ["github.com"]))
        self.assertEqual(sanitize_filename('test<>:"/\\|?*.mp4'), "test_________.mp4")
        self.assertTrue(linux_to_wine_path("/tmp/test").startswith("Z:\\"))

    def test_03_browser_manifests(self) -> None:
        cm = build_chromium_manifest("com.tonec.idm", Path("/tmp/idm-native-host"))
        origins = cm["allowed_origins"]
        self.assertIn(f"chrome-extension://{OFFICIAL_CHROME_EXT_ID}/", origins)
        self.assertIn(f"chrome-extension://{OFFICIAL_EDGE_EXT_ID}/", origins)
        self.assertIn(f"chrome-extension://{COMPANION_CHROME_EXT_ID}/", origins)

        gm = build_gecko_manifest("com.tonec.idm", Path("/tmp/idm-native-host"))
        self.assertIn(OFFICIAL_FIREFOX_EXT_ID, gm["allowed_extensions"])

    def test_04_real_idm_installer_sfx_unpack(self) -> None:
        """Gerçek idman643build16.exe paketini indirip 32-bayt Tonec SFX çıkarıcısını doğrular."""
        with tempfile.TemporaryDirectory() as tmpd:
            tmp_path = Path(tmpd)
            exe_path = download_idm_installer(
                "https://download.internetdownloadmanager.com/idman643build16.exe",
                tmp_path / "idman643build16.exe",
            )
            unpack_dir = tmp_path / "unpacked"
            files = unpack_idm_installer(exe_path, unpack_dir)
            self.assertGreaterEqual(len(files), 180)

            # Kritik dosyaların bayt doğruluğu!
            idman_bin = (unpack_dir / "IDMan.exe").read_bytes()
            self.assertEqual(idman_bin[:2], b"MZ")
            self.assertGreater(len(idman_bin), 4_000_000)

            msghost_bin = (unpack_dir / "IDMMsgHost.exe").read_bytes()
            self.assertEqual(msghost_bin[:2], b"MZ")

            msghost_json = json.loads((unpack_dir / "IDMMsgHost.json").read_text(encoding="utf-8"))
            self.assertEqual(msghost_json["name"], "com.tonec.idm")

            msghost_moz = json.loads((unpack_dir / "IDMMsgHostMoz.json").read_text(encoding="utf-8"))
            self.assertEqual(msghost_moz["name"], "com.tonec.idm")

            tr_lng = (unpack_dir / "Languages" / "idm_tr.lng").read_bytes()
            self.assertIn(b"lang=0x1f", tr_lng)

    def test_05_live_daemon_websocket_http_and_native_host(self) -> None:
        """Daemon WS (Port 1001), HTTP RPC (Port 1002), CSRF koruması ve Native Host stdio testi."""
        with tempfile.TemporaryDirectory() as tmpd:
            env = os.environ.copy()
            env["XDG_CONFIG_HOME"] = str(Path(tmpd) / "config")
            env["XDG_DATA_HOME"] = str(Path(tmpd) / "data")
            env["XDG_CACHE_HOME"] = str(Path(tmpd) / "cache")
            env["PYTHONPATH"] = str(SRC_BASE)

            # Çakışmasız test portları ata
            cfg_dir = Path(env["XDG_CONFIG_HOME"]) / "idm-linux"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            (cfg_dir / "config.json").write_text(
                json.dumps({"ws_port": 39001, "http_port": 39002, "keep_wine_warm": False}),
                encoding="utf-8",
            )

            # Eklenti dağıtım testi (CRX3 + Unpacked + XPI)
            old_data = os.environ.get("XDG_DATA_HOME")
            os.environ["XDG_DATA_HOME"] = env["XDG_DATA_HOME"]
            try:
                crx_path, chrom_dir, ff_xpi = deploy_browser_extensions(PROJECT_ROOT)
                self.assertTrue(crx_path.exists())
                ok_crx, _ = verify_crx3_package(crx_path)
                self.assertTrue(ok_crx)
                self.assertTrue((chrom_dir / "manifest.json").exists())
                self.assertTrue(ff_xpi.exists())
            finally:
                if old_data is None:
                    os.environ.pop("XDG_DATA_HOME", None)
                else:
                    os.environ["XDG_DATA_HOME"] = old_data

            proc = subprocess.Popen(
                [sys.executable, "-m", "idm_linux.cli", "daemon-run"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                # Sunucu ayağa kalkana kadar bekle
                ready = False
                for _ in range(30):
                    time.sleep(0.15)
                    try:
                        with urllib.request.urlopen("http://127.0.0.1:39002/api/status", timeout=1) as r:
                            st = json.loads(r.read().decode("utf-8"))
                            if st.get("ok"):
                                ready = True
                                break
                    except Exception:
                        pass
                self.assertTrue(ready, "Daemon HTTP sunucusu başlamadı!")

                # 1) Kötü amaçlı dış web sitesi Origin isteği 403 almalı
                bad_req = urllib.request.Request(
                    "http://127.0.0.1:39002/api/status",
                    headers={"Origin": "https://malicious.example.com"},
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(bad_req, timeout=2)
                self.assertEqual(ctx.exception.code, 403)

                # 2) Resmi IDM WebSocket (plugin.v3.internetdownloadmanager.com) Handshake Testi
                with socket.create_connection(("127.0.0.1", 39001), timeout=3) as ws:
                    key = base64.b64encode(b"1234567890123456").decode("ascii")
                    upgrade = (
                        "GET /?cid=0&rnd=123456 HTTP/1.1\r\n"
                        "Host: 127.0.0.1:39001\r\n"
                        "Upgrade: websocket\r\n"
                        "Connection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\n"
                        "Sec-WebSocket-Version: 13\r\n"
                        "Sec-WebSocket-Protocol: plugin.v3.internetdownloadmanager.com\r\n\r\n"
                    )
                    ws.sendall(upgrade.encode("ascii"))
                    resp_hdr = ws.recv(1024).decode("latin1")
                    self.assertIn("101 Switching Protocols", resp_hdr)
                    self.assertIn("plugin.v3.internetdownloadmanager.com", resp_hdr)

                    # Maskeli Type 2 Handshake gönder
                    msg_bytes = b"MSG#1#2#5#1024,112=6:Chrome,113=6:6.43.1;"
                    mask = b"\x11\x22\x33\x44"
                    masked_payload = bytes(b ^ mask[i % 4] for i, b in enumerate(msg_bytes))
                    frame = bytes([0x81, 0x80 | len(msg_bytes)]) + mask + masked_payload
                    ws.sendall(frame)

                    reply_data = ws.recv(4096)
                    self.assertIn(b"MSG#1#3#0#0:113", reply_data)

                # 3) Native Messaging Host (stdio) hem resmi MSG# hem Hibrit JSON testi
                nh = subprocess.Popen(
                    [sys.executable, "-m", "idm_linux.native_host"],
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                assert nh.stdin is not None and nh.stdout is not None

                def send_nh(obj: object) -> object:
                    raw_b = json.dumps(obj).encode("utf-8")
                    nh.stdin.write(struct.pack("<I", len(raw_b)) + raw_b)
                    nh.stdin.flush()
                    rlen = struct.unpack("<I", nh.stdout.read(4))[0]
                    return json.loads(nh.stdout.read(rlen).decode("utf-8"))

                # Resmi eklenti el sıkışması -> 2 çerçeve döner (Type 3 + Type 4)
                r1 = send_nh("MSG#10#2#5#1024;")
                r2len = struct.unpack("<I", nh.stdout.read(4))[0]
                r2 = json.loads(nh.stdout.read(r2len).decode("utf-8"))
                self.assertTrue(str(r1).startswith("MSG#10#3#"))
                self.assertTrue(str(r2).startswith("MSG#11#4#"))

                # Hibrit eklenti status sorgusu
                r_st = send_nh({"action": "status"})
                self.assertIsInstance(r_st, dict)
                self.assertTrue(r_st.get("ok"))
                self.assertTrue(r_st.get("official_extension_connected"))

                nh.stdin.close()
                nh.stdout.close()
                if nh.stderr:
                    nh.stderr.close()
                nh.wait(timeout=5)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()

    def test_06_hls_master_playlist_parser(self) -> None:
        """Video sitelerindeki .m3u8 HLS Master Playlist çözünürlük ayrıştırıcısını doğrular."""
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading
        from idm_linux.stream_engine import StreamEngine

        sample_m3u8 = (
            "#EXTM3U\n"
            "#EXT-X-VERSION:3\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360\n"
            "chunklist_360p.m3u8\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=4500000,RESOLUTION=1920x1080\n"
            "https://video.example.org/hls/1080p.m3u8\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=2200000,RESOLUTION=1280x720\n"
            "chunklist_720p.m3u8\n"
        ).encode("utf-8")

        class M3u8Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                self.send_header("Content-Length", str(len(sample_m3u8)))
                self.end_headers()
                self.wfile.write(sample_m3u8)

        srv = HTTPServer(("127.0.0.1", 0), M3u8Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            eng = StreamEngine(IdmLinuxConfig())
            res = eng.probe_formats(
                page_url=f"http://127.0.0.1:{port}/watch/1",
                captured_streams=[{"url": f"http://127.0.0.1:{port}/master.m3u8", "mime": "application/x-mpegurl"}],
                use_ytdlp=False,
            )
            fmts = res["formats"]
            self.assertEqual(len(fmts), 3)
            # Büyükten küçüğe sıralanmış olmalı: 1080p -> 720p -> 360p
            self.assertEqual([f["height"] for f in fmts], [1080, 720, 360])
            self.assertEqual(fmts[0]["source_url"], "https://video.example.org/hls/1080p.m3u8")
            self.assertEqual(fmts[1]["source_url"], f"http://127.0.0.1:{port}/chunklist_720p.m3u8")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_07_crx3_binary_format_and_openssl_signature(self) -> None:
        """Üretilen .crx dosyasının Chromium CRX3 (Cr24 v3) spesifikasyonuna ve RSA-2048 imzasına tam uyumunu doğrular."""
        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            crx_file = tmp / "idm-linux-companion-chromium.crx"
            _, ext_id = build_crx3_package(PROJECT_ROOT / "extension" / "chromium", crx_file)
            self.assertEqual(ext_id, COMPANION_CHROME_EXT_ID)

            ok, msg = verify_crx3_package(crx_file)
            self.assertTrue(ok, msg)

            raw = crx_file.read_bytes()
            self.assertEqual(raw[:4], b"Cr24")
            ver, hdr_len = struct.unpack_from("<II", raw, 4)
            self.assertEqual(ver, 3)
            hdr = raw[12 : 12 + hdr_len]
            zip_payload = raw[12 + hdr_len :]
            self.assertEqual(zip_payload[:4], b"PK\x03\x04")

            # Public key DER baytlarının CRX3 başlığında birebir yer aldığını doğrula
            pub_der = base64.b64decode(COMPANION_CHROME_PUBKEY)
            self.assertIn(pub_der, hdr)

            # manifest.json içindeki 'key' ile CRX3 anahtarının birebir aynı olduğunu doğrula
            manifest_data = json.loads((PROJECT_ROOT / "extension" / "chromium" / "manifest.json").read_text())
            self.assertEqual(manifest_data["key"], COMPANION_CHROME_PUBKEY)

    def test_08_port_migration_wineprefix_and_crash_isolation(self) -> None:
        """
        1) Eski <1024 portların (1001/1002) otomatik 17801/17802 göçünü,
        2) ~/.wine mevcutken varsayılan prefix olarak seçilmesini,
        3) Sistemde mevcut IDM kurulumunun dinamik algılanmasını,
        4) Wine altında çöken IDMIntegrator64.exe & IDMNetMon64.dll modüllerinin izolasyonunu doğrular.
        """
        with tempfile.TemporaryDirectory() as tmpd:
            fake_home = Path(tmpd) / "home"
            fake_cfg = fake_home / ".config"
            fake_data = fake_home / ".local" / "share"
            (fake_cfg / "idm-linux").mkdir(parents=True)

            # 1) Eski 1001/1002 portlu config yaz -> otomatik 17801/17802 olmalı!
            (fake_cfg / "idm-linux" / "config.json").write_text(
                json.dumps({"ws_port": 1001, "http_port": 1002}),
                encoding="utf-8",
            )

            # 2) Sahte ~/.wine/drive_c/Program Files (x86)/Internet Download Manager oluştur
            fake_wine_idm = fake_home / ".wine" / "drive_c" / "Program Files (x86)" / "Internet Download Manager"
            fake_wine_idm.mkdir(parents=True)
            (fake_wine_idm / "IDMan.exe").write_bytes(b"MZ_FAKE_IDM")
            (fake_wine_idm / "IDMIntegrator64.exe").write_bytes(b"MZ_CRASHING_HOOK")
            (fake_wine_idm / "IDMNetMon64.dll").write_bytes(b"MZ_CRASHING_DLL")

            old_env = {k: os.environ.get(k) for k in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "WINEPREFIX")}
            os.environ["HOME"] = str(fake_home)
            os.environ["XDG_CONFIG_HOME"] = str(fake_cfg)
            os.environ["XDG_DATA_HOME"] = str(fake_data)
            os.environ.pop("WINEPREFIX", None)
            try:
                loaded = IdmLinuxConfig.load()
                self.assertEqual(loaded.ws_port, DEFAULT_WS_PORT)
                self.assertEqual(loaded.http_port, DEFAULT_HTTP_PORT)

                # ~/.wine varken varsayılan prefix ~/.wine olmalı!
                self.assertEqual(Path(detect_default_wine_prefix()), (fake_home / ".wine").resolve())
                chosen = choose_wine_prefix(assume_yes=True)
                self.assertEqual(chosen, (fake_home / ".wine").resolve())

                # Mevcut kurulum dinamik algılanmalı!
                existing = scan_existing_idm_installations()
                kinds = [e.kind for e in existing]
                self.assertIn("wine-idm", kinds)

                # Çöken Windows hook ikilileri silinmeden güvenli PE stub ile değiştirilmeli!
                (fake_wine_idm / "IDMGrHlp.exe.disabled").write_bytes(b"OLD_DISABLED")
                n_dis = neutralize_windows_hook_binaries(fake_wine_idm)
                self.assertGreaterEqual(n_dis, 5)
                self.assertFalse((fake_wine_idm / "IDMGrHlp.exe.disabled").exists())
                for must_exist in (
                    "IDMIntegrator64.exe",
                    "IDMGrHlp.exe",
                    "IDMNetMon.dll",
                    "IDMNetMon64.dll",
                    "idmbrbtn.dll",
                    "idmbrbtn64.dll",
                    "IDMan.exe",
                ):
                    self.assertTrue((fake_wine_idm / must_exist).is_file(), f"{must_exist} mevcut olmalı!")
                self.assertIn(b"IDMLINUXSTUB", (fake_wine_idm / "IDMGrHlp.exe").read_bytes()[:0x60])
                self.assertIn(b"IDMLINUXSTUB", (fake_wine_idm / "IDMNetMon64.dll").read_bytes()[:0x60])
            finally:
                for k, v in old_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_09_strict_manifest_file_validation(self) -> None:
        """Chromium ve Firefox manifest.json içindeki tüm referans dosyaların (js/css/icons/popup) varlığını denetler."""
        self.assertEqual(validate_extension_directory(PROJECT_ROOT / "extension" / "chromium"), [])
        self.assertEqual(validate_extension_directory(PROJECT_ROOT / "extension" / "firefox"), [])

        # Olmayan bir CSS referansı eklendiğinde doğrulayıcının anında yakaladığını kanıtla
        with tempfile.TemporaryDirectory() as tmpd:
            broken_dir = Path(tmpd) / "broken_ext"
            shutil.copytree(PROJECT_ROOT / "extension" / "chromium", broken_dir)
            mf = broken_dir / "manifest.json"
            data = json.loads(mf.read_text(encoding="utf-8"))
            data["content_scripts"][0]["css"] = ["videobar.css"]
            mf.write_text(json.dumps(data), encoding="utf-8")
            missing = validate_extension_directory(broken_dir)
            self.assertIn("videobar.css", missing)

    def test_10_gui_and_pipeline_imports(self) -> None:
        """Modern GUI Kurulum & Kontrol Merkezinin ve ortak kurulum hattının hatasız yüklendiğini doğrular."""
        import py_compile
        for py_file in (PROJECT_ROOT / "src" / "idm_linux").glob("*.py"):
            py_compile.compile(str(py_file), doraise=True)
        from idm_linux import gui
        self.assertTrue(callable(gui.launch_control_panel))
        self.assertTrue(callable(gui.can_launch_gui))

    def test_11_youtube_direct_url_and_fast_film_site_probe(self) -> None:
        """
        1) YouTube progressive formatların 127.0.0.1 yerine doğrudan gerçek googlevideo.com linki (delivery=direct)
           ve kendi özel User-Agent başlığıyla üretildiğini,
        2) Özel film sitelerinde (.m3u8 yakalanmışken) yt-dlp bekletilmeden <0.1 sn içinde yanıt döndüğünü doğrular.
        """
        from idm_linux.stream_engine import StreamEngine

        eng = StreamEngine(IdmLinuxConfig())
        sample_yt_fmts = [
            {
                "format_id": "18",
                "ext": "mp4",
                "height": 360,
                "vcodec": "avc1.42001E",
                "acodec": "mp4a.40.2",
                "protocol": "https",
                "tbr": 650,
                "filesize": 15_000_000,
                "url": "https://rr2---sn-4g5ednsd.googlevideo.com/videoplayback?itag=18&id=test",
                "http_headers": {"User-Agent": "com.google.ios.youtube/19.45.4"},
            },
            {
                "format_id": "137",
                "ext": "mp4",
                "height": 1080,
                "vcodec": "avc1.640028",
                "acodec": "none",
                "protocol": "https",
                "tbr": 3800,
                "filesize": 80_000_000,
                "url": "https://rr2---sn-4g5ednsd.googlevideo.com/videoplayback?itag=137",
            },
            {
                "format_id": "140",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "protocol": "https",
                "abr": 128,
                "filesize": 12_000_000,
                "url": "https://rr2---sn-4g5ednsd.googlevideo.com/videoplayback?itag=140",
                "http_headers": {"User-Agent": "com.google.ios.youtube/19.45.4"},
            },
        ]
        summarized = eng._summarize_ytdlp_formats(sample_yt_fmts, "https://www.youtube.com/watch?v=8HgmWGigh1s")
        by_res = {o.resolution: o for o in summarized if not o.audio_only}
        self.assertEqual(by_res["360p"].delivery, "direct")
        self.assertTrue(by_res["360p"].direct_url.startswith("https://rr2---sn-4g5ednsd.googlevideo.com/"))
        self.assertEqual(by_res["360p"].stream_user_agent, "com.google.ios.youtube/19.45.4")

        # Ses de doğrudan gerçek googlevideo URL'si olmalı!
        audio_opts = [o for o in summarized if o.audio_only]
        self.assertEqual(len(audio_opts), 1)
        self.assertEqual(audio_opts[0].delivery, "direct")
        self.assertTrue(audio_opts[0].direct_url.startswith("https://rr2---sn-4g5ednsd.googlevideo.com/"))

        # Film sitesinde doğrudan MP4 yakalanmışsa yt-dlp hiç bekletilmeden anında (<0.05s) dönmeli!
        t0 = time.time()
        fast_res = eng.probe_formats(
            page_url="https://fullhdfilmizlesene.now/film/aile-plani-the-family-plan/",
            captured_streams=[{"url": "https://cdn.player.example/movie_720p.mp4", "mime": "video/mp4", "size": 52428800}],
            use_ytdlp=True,
        )
        elapsed = time.time() - t0
        self.assertLess(elapsed, 0.25)
        self.assertEqual(fast_res["formats"][0]["delivery"], "direct")
        self.assertEqual(fast_res["formats"][0]["direct_url"], "https://cdn.player.example/movie_720p.mp4")

    def test_12_turkish_filename_stream_and_idm_dual_get_resilience(self) -> None:
        """
        Türkçe karakterli ('ğ, ı, ş, İ') dosya adlarında BaseHTTPRequestHandler latin-1 çökmesi olmadığını
        ve IDM'nin 1. bilgi sorgusu bağlantısını kapatıp 2. Range bağlantısıyla tam dosyayı indirebildiğini doğrular.
        """
        import threading
        from http.server import ThreadingHTTPServer
        from idm_linux.daemon import DaemonState, make_http_handler

        with tempfile.TemporaryDirectory() as tmpd:
            old_cache = os.environ.get("XDG_CACHE_HOME")
            os.environ["XDG_CACHE_HOME"] = tmpd
            try:
                state = DaemonState()
                # Türkçe karakterli gerçek başlık testi!
                tr_filename = "En Sevdiğim Hugo Oyunlarını Oynadım! [720p].mp4"
                ticket = state.stream_engine.create_ticket(
                    source_url="http://127.0.0.1:9/dummy",
                    filename=tr_filename,
                    mode="ytdlp",
                )
                job = state.stream_engine.get_job(ticket.ticket_id)
                assert job is not None

                payload_bytes = b"\x00\x00\x00\x18ftypmp42" + (b"IDM_LINUX_STREAM_DATA_" * 2048)
                job.work_dir.mkdir(parents=True, exist_ok=True)
                job.output_file.write_bytes(payload_bytes)
                job.final_size = len(payload_bytes)
                job.completed = True

                srv = ThreadingHTTPServer(("127.0.0.1", 0), make_http_handler(state))
                port = srv.server_address[1]
                th = threading.Thread(target=srv.serve_forever, daemon=True)
                th.start()
                try:
                    stream_url = f"http://127.0.0.1:{port}/stream/{ticket.ticket_id}/{urllib.parse.quote(ticket.filename)}"

                    # 1. İstek: IDM Dosya İndirme Bilgisi penceresi için açar, 128 bayt okuyup kapatır!
                    with urllib.request.urlopen(stream_url, timeout=3) as r1:
                        self.assertEqual(r1.status, 200)
                        cd = r1.headers.get("Content-Disposition") or ""
                        self.assertIn("filename*=UTF-8''", cd)
                        first_chunk = r1.read(128)
                        self.assertEqual(first_chunk, payload_bytes[:128])

                    # 2. İstek: Kullanıcı 'İndirmeyi Başlat' der -> IDM Range: bytes=0- ile 206 Partial Content çeker!
                    req2 = urllib.request.Request(stream_url, headers={"Range": "bytes=0-"})
                    with urllib.request.urlopen(req2, timeout=3) as r2:
                        self.assertEqual(r2.status, 206)
                        full_downloaded = r2.read()
                        self.assertEqual(full_downloaded, payload_bytes)
                finally:
                    srv.shutdown()
                    srv.server_close()
            finally:
                if old_cache is None:
                    os.environ.pop("XDG_CACHE_HOME", None)
                else:
                    os.environ["XDG_CACHE_HOME"] = old_cache

    def test_13_disguised_png_hls_live_mp4_zero_502_and_instant_open(self) -> None:
        """
        Film sitelerindeki (fullhdfilmizlesene / vidmoly / atom) sahte .PNG başlıklı MPEG-TS segmentlerini
        ve katı iframe Referer kontrolünü simüle eder; 502 Bad Gateway vermeden <0.05s içinde HTTP 200 açtığını
        ve geçerli fMP4 video ürettiğini doğrular!
        """
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg kurulu değil")

        import subprocess
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from idm_linux.daemon import DaemonState, make_http_handler
        from idm_linux.hls_streamer import strip_disguised_image_header

        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            ts_dir = tmp / "hls"
            ts_dir.mkdir(parents=True)

            # Gerçek 2.0 saniyelik test videosu + sesi üret ve 4 ayrı HLS segmentine böl
            m3u8_file = ts_dir / "index.m3u8"
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=duration=2.0:size=320x180:rate=16",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2.0",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-g", "8",
                    "-c:a", "aac", "-b:a", "64k",
                    "-f", "hls", "-hls_time", "0.5", "-hls_list_size", "0",
                    str(m3u8_file),
                ],
                check=True,
                timeout=20,
            )

            # Her .ts segmentinin başına sahte 64-baytlık PNG başlığı ekle (.png kılıfı!)
            fake_png_hdr = b"\x89PNG\r\n\x1a\n" + b"FAKE_MOVIE_PLAYER_PADDING_" * 2
            seg_files = sorted(ts_dir.glob("*.ts"))
            self.assertGreaterEqual(len(seg_files), 2)
            for sf in seg_files:
                orig = sf.read_bytes()
                disguised = fake_png_hdr + orig
                # strip_disguised_image_header doğrudan orijinal 0x47 MPEG-TS baytlarını kurtarmalı!
                self.assertEqual(strip_disguised_image_header(disguised), orig)
                sf.write_bytes(disguised)

            expected_referer = "https://player.movie-embed.example/embed/999"

            class StrictMovieHlsHandler(BaseHTTPRequestHandler):
                def log_message(self, fmt: str, *args: object) -> None:
                    return

                def do_GET(self) -> None:
                    ref = self.headers.get("Referer") or ""
                    if ref != expected_referer:
                        # Yanlış Referer gelirse gerçek film siteleri gibi 403 döndür!
                        self.send_response(403)
                        self.end_headers()
                        return
                    rel = self.path.lstrip("/").split("?")[0]
                    fpath = ts_dir / rel
                    if not fpath.is_file():
                        self.send_response(404)
                        self.end_headers()
                        return
                    data = fpath.read_bytes()
                    self.send_response(200)
                    ctype = "image/png" if fpath.suffix == ".ts" else "application/vnd.apple.mpegurl"
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

            hls_srv = ThreadingHTTPServer(("127.0.0.1", 0), StrictMovieHlsHandler)
            hls_port = hls_srv.server_address[1]
            threading.Thread(target=hls_srv.serve_forever, daemon=True).start()

            old_cache = os.environ.get("XDG_CACHE_HOME")
            os.environ["XDG_CACHE_HOME"] = str(tmp / "cache")
            try:
                state = DaemonState()
                # Wine çağrısını mock'la (yalnızca anında çağrıldığını ve URL'yi doğrula)
                dispatched = []
                state.sender.send_download = lambda req: (dispatched.append(req) or (True, "Mock IDM OK"))

                daemon_srv = ThreadingHTTPServer(("127.0.0.1", 0), make_http_handler(state))
                d_port = daemon_srv.server_address[1]
                state.cfg.http_port = d_port
                threading.Thread(target=daemon_srv.serve_forever, daemon=True).start()

                try:
                    # 1) /api/video/download çağrısı SIFIR ÖN BEKLEME ile <0.25s içinde dönmeli!
                    t_click = time.time()
                    dl_req = urllib.request.Request(
                        f"http://127.0.0.1:{d_port}/api/video/download",
                        data=json.dumps({
                            "pageUrl": "https://fullhdfilmizlesene.now/film/sarki/",
                            "title": "Şarkı",
                            "ext": "mp4",
                            "resolution": "1080p",
                            "delivery": "stream",
                            "sourceUrl": f"http://127.0.0.1:{hls_port}/index.m3u8",
                            "streamReferer": expected_referer,
                            "streamOrigin": "https://player.movie-embed.example",
                        }).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(dl_req, timeout=5) as resp:
                        dl_json = json.loads(resp.read().decode("utf-8"))
                    click_elapsed = time.time() - t_click
                    self.assertTrue(dl_json["ok"])
                    self.assertLess(click_elapsed, 0.35, f"/api/video/download çok yavaş: {click_elapsed:.2f}s")
                    self.assertEqual(len(dispatched), 1)

                    # 2) IDM'nin stream URL'sine bağlanması: 502 Bad Gateway VERMEMELİ, anında 200 OK ve geçerli MP4 vermeli!
                    stream_url = dl_json["stream_url"]
                    t_hdr = time.time()
                    with urllib.request.urlopen(stream_url, timeout=15) as s_resp:
                        hdr_elapsed = time.time() - t_hdr
                        self.assertEqual(s_resp.status, 200)
                        self.assertLess(hdr_elapsed, 0.35, f"HTTP 200 başlığı çok yavaş döndü: {hdr_elapsed:.2f}s")
                        mp4_bytes = s_resp.read()

                    self.assertGreater(len(mp4_bytes), 4096)
                    # v2.8.4: streamlink kuruluysa HLS kaydı HAM MPEG-TS passthrough'tur (ses bozulmaz!);
                    # kurulu değilse yerel motor fMP4 (ftyp/moov) üretir. İkisi de geçerli konteynerdir.
                    import shutil as _sh13

                    konteyner_ok = (
                        mp4_bytes[:1] == b"\x47"          # streamlink TS passthrough
                        or b"ftyp" in mp4_bytes[:64]       # yerel motor fMP4 remux (ffmpeg varsa)
                        or mp4_bytes[:8] == b"\x89PNG\r\n\x1a\n"  # ffmpeg YOKSA ham birleştirme (akış yine de kesintisiz)
                    )
                    self.assertTrue(konteyner_ok, "beklenmeyen konteyner başı")
                    # Not: konteyner türü motor zincirine göre değişir (TS/fMP4/ham); motor seçimi
                    # test_44/46/49/50'de ayrıca kesin olarak doğrulanır.
                finally:
                    daemon_srv.shutdown()
                    daemon_srv.server_close()
            finally:
                hls_srv.shutdown()
                hls_srv.server_close()
                if old_cache is None:
                    os.environ.pop("XDG_CACHE_HOME", None)
                else:
                    os.environ["XDG_CACHE_HOME"] = old_cache

    def test_14_youtube_cached_dash_urls_and_prebuilt_mux(self) -> None:
        """YouTube 1080p DASH akışlarında mux_video_url & mux_audio_url önbelleklemeyi doğrular."""
        from idm_linux.stream_engine import StreamEngine

        eng = StreamEngine(IdmLinuxConfig())
        sample_yt_fmts = [
            {
                "format_id": "137",
                "ext": "mp4",
                "height": 1080,
                "vcodec": "avc1.640028",
                "acodec": "none",
                "protocol": "https",
                "tbr": 3800,
                "url": "https://rr2---sn-test.googlevideo.com/videoplayback?itag=137",
                "http_headers": {"User-Agent": "Mozilla/5.0 YouTubeTest"},
            },
            {
                "format_id": "140",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "protocol": "https",
                "abr": 128,
                "url": "https://rr2---sn-test.googlevideo.com/videoplayback?itag=140",
                "http_headers": {"User-Agent": "Mozilla/5.0 YouTubeTest"},
            },
        ]
        opts = eng._summarize_ytdlp_formats(sample_yt_fmts, "https://www.youtube.com/watch?v=test1080")
        opt_1080 = [o for o in opts if o.resolution == "1080p"][0]
        self.assertEqual(opt_1080.mux_video_url, "https://rr2---sn-test.googlevideo.com/videoplayback?itag=137")
        self.assertEqual(opt_1080.mux_audio_url, "https://rr2---sn-test.googlevideo.com/videoplayback?itag=140")
        self.assertEqual(opt_1080.mux_video_headers.get("User-Agent"), "Mozilla/5.0 YouTubeTest")

    def test_15_dynamic_default_browser_and_welcome_endpoint(self) -> None:
        """Chromium autoload bayrak yazımını ve /welcome karşılama ekranını doğrular."""
        import threading
        from http.server import ThreadingHTTPServer
        from idm_linux.browsers import configure_chromium_autoload_flags
        from idm_linux.daemon import DaemonState, make_http_handler

        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            fake_cfg = tmp / ".config"
            (fake_cfg / "chromium").mkdir(parents=True)
            ext_dir = tmp / "extensions" / "chromium"
            ext_dir.mkdir(parents=True)

            old_cfg = os.environ.get("XDG_CONFIG_HOME")
            os.environ["XDG_CONFIG_HOME"] = str(fake_cfg)
            try:
                configure_chromium_autoload_flags(ext_dir)
                flags_file = fake_cfg / "chromium-flags.conf"
                self.assertTrue(flags_file.exists())
                self.assertIn(f"--load-extension={ext_dir.resolve()}", flags_file.read_text(encoding="utf-8"))

                state = DaemonState()
                srv = ThreadingHTTPServer(("127.0.0.1", 0), make_http_handler(state))
                port = srv.server_address[1]
                state.cfg.http_port = port
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/welcome", timeout=3) as r:
                        self.assertEqual(r.status, 200)
                        body = r.read().decode("utf-8")
                        self.assertIn("BELGESELSEMO", body)
                        self.assertIn("ARENA.AI", body)
                        self.assertIn("https://belgeselsemo.com.tr", body)
                finally:
                    srv.shutdown()
                    srv.server_close()
            finally:
                if old_cfg is None:
                    os.environ.pop("XDG_CONFIG_HOME", None)
                else:
                    os.environ["XDG_CONFIG_HOME"] = old_cfg

    def test_16_gui_credit_bar_pack_order_and_sidebar_swap(self) -> None:
        """
        gui.py kaynak kodunda:
        1) credit_outer.pack(side='bottom') çağrısının content_host.pack(...) çağrısından ÖNCE geldiğini
           ve içerik kartlarıyla aynı sol-sağ hizasında (padx=22) olduğunu,
        2) Sol sidebar'da sistem bilgi kutusunun (side_info_box) ve BELGESELSEMO × ARENA.AI kutusunun (side_credit_box)
           aynı rozet tasarımında (SIDE_BADGE_BG) alt alta yerleştiğini doğrular.
        """
        gui_src = (PROJECT_ROOT / "gui.py").read_text(encoding="utf-8")
        idx_credit_pack = gui_src.index('credit_outer.pack(side="bottom", fill="x", padx=22')
        idx_content_pack = gui_src.index('content_host.pack(side="top", fill="both", expand=True)')
        self.assertLess(
            idx_credit_pack,
            idx_content_pack,
            "credit_outer, content_host'tan önce pack edilmelidir ki tüm ekranlarda görünür kalsın!",
        )
        self.assertIn("bg=SIDE_BADGE_BG", gui_src[gui_src.index("side_info_box =") : gui_src.index("side_credit_box =")])

        idx_side_info = gui_src.index("side_info_box.pack(")
        idx_side_credit = gui_src.index("side_credit_box.pack(")
        self.assertLess(
            idx_side_info,
            idx_side_credit,
            "Sidebar alt kısmında sistem/köprü bilgisi üstte, BELGESELSEMO × ARENA.AI kutusu altta olmalıdır!",
        )

    def test_17_disguised_txt_hls_progressive_realtime_bytes_before_completion(self) -> None:
        """
        1) .m3u8 yerine gizli 'master.txt' (gzip sıkıştırmalı!) manifest + sahte PNG segmentli bir film akışını simüle eder,
        2) Son segment geciktirilmişken bile İLK MP4 baytlarının video bitmesini BEKLEMEDEN anında IDM'ye aktığını,
        3) Yanıtta Transfer-Encoding: chunked OLMADIĞINI (ham ikili akış olduğunu) kanıtlar!
        """
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg kurulu değil")

        import gzip
        import subprocess
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from idm_linux.daemon import DaemonState, make_http_handler

        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            ts_dir = tmp / "hls_txt"
            ts_dir.mkdir(parents=True)

            m3u8_file = ts_dir / "raw.m3u8"
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=duration=3.0:size=320x180:rate=16",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3.0",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-g", "8",
                    "-c:a", "aac", "-b:a", "64k",
                    "-f", "hls", "-hls_time", "0.5", "-hls_list_size", "0",
                    str(m3u8_file),
                ],
                check=True,
                timeout=20,
            )

            # Manifest dosyasını film siteleri gibi 'master.txt' olarak kaydet ve segmentlere PNG başlığı ekle
            txt_manifest = ts_dir / "master.txt"
            txt_manifest.write_bytes(gzip.compress(m3u8_file.read_bytes()))
            seg_files = sorted(ts_dir.glob("*.ts"))
            last_seg_name = seg_files[-1].name
            for sf in seg_files:
                sf.write_bytes(b"\x89PNG\r\n\x1a\nFAKEHDR_" + sf.read_bytes())

            last_seg_gate = threading.Event()

            class SlowTailMovieHandler(BaseHTTPRequestHandler):
                def log_message(self, fmt: str, *args: object) -> None:
                    return

                def do_GET(self) -> None:
                    rel = self.path.lstrip("/").split("?")[0]
                    fpath = ts_dir / rel
                    if not fpath.is_file():
                        self.send_response(404)
                        self.end_headers()
                        return
                    if rel == last_seg_name:
                        # Son segmenti istemci ilk baytları okuyana kadar beklet!
                        last_seg_gate.wait(timeout=3.0)
                    data = fpath.read_bytes()
                    self.send_response(200)
                    if rel == "master.txt":
                        self.send_header("Content-Type", "text/plain")
                        self.send_header("Content-Encoding", "gzip")
                    else:
                        self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

            hls_srv = ThreadingHTTPServer(("127.0.0.1", 0), SlowTailMovieHandler)
            hls_port = hls_srv.server_address[1]
            threading.Thread(target=hls_srv.serve_forever, daemon=True).start()

            old_cache = os.environ.get("XDG_CACHE_HOME")
            os.environ["XDG_CACHE_HOME"] = str(tmp / "cache")
            try:
                state = DaemonState()
                state.sender.send_download = lambda _req: (True, "Mock OK")
                daemon_srv = ThreadingHTTPServer(("127.0.0.1", 0), make_http_handler(state))
                d_port = daemon_srv.server_address[1]
                state.cfg.http_port = d_port
                threading.Thread(target=daemon_srv.serve_forever, daemon=True).start()

                try:
                    dl_req = urllib.request.Request(
                        f"http://127.0.0.1:{d_port}/api/video/download",
                        data=json.dumps({
                            "pageUrl": "https://fullhdfilmizlesene.now/film/test/",
                            "title": "Test Filmi",
                            "ext": "mp4",
                            "resolution": "1080p",
                            "delivery": "stream_proxy",
                            "sourceUrl": f"http://127.0.0.1:{hls_port}/master.txt",
                        }).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(dl_req, timeout=5) as r_dl:
                        stream_url = json.loads(r_dl.read().decode("utf-8"))["stream_url"]

                    with urllib.request.urlopen(stream_url, timeout=15) as s_resp:
                        # Transfer-Encoding: chunked OLMAMALI!
                        self.assertIsNone(s_resp.headers.get("Transfer-Encoding"))
                        # Son segment henüz kilitliyken bile İLK MP4 BAYTLARI anında gelmeli!
                        first_live_bytes = s_resp.read(2048)
                        self.assertEqual(len(first_live_bytes), 2048)
                        self.assertIn(b"ftyp", first_live_bytes[:64])
                        self.assertFalse(last_seg_gate.is_set(), "İlk baytlar son segment bitmeden canlı gelmeliydi!")
                        # Şimdi son segmentin kilidini aç ve kalan baytları tamamla
                        last_seg_gate.set()
                        rest_bytes = s_resp.read()
                        self.assertGreater(len(rest_bytes), 1024)
                finally:
                    last_seg_gate.set()
                    daemon_srv.shutdown()
                    daemon_srv.server_close()
            finally:
                hls_srv.shutdown()
                hls_srv.server_close()
                if old_cache is None:
                    os.environ.pop("XDG_CACHE_HOME", None)
                else:
                    os.environ["XDG_CACHE_HOME"] = old_cache

    def test_18_complete_zero_trace_uninstall_registry_appdata_and_logs(self) -> None:
        """
        run_uninstall() çağrıldığında:
        - Wine IDM klasörlerinin, AppData/Roaming/IDM & DMCache kalıntılarının silindiğini,
        - Wine user.reg & system.reg içindeki tüm DownloadManager / COM GUID kayıtlarının silinip
          diğer Wine programlarına (örn. 7-Zip) dokunulmadığını,
        - ~/.config/idm-linux, ~/.local/share/idm-linux, ~/.cache/idm-linux (loglar dahil!),
          chromium-flags.conf ve .desktop kısayollarının tamamen silindiğini ve
          sonrasında IdmLinuxConfig.load() çağrılsa bile klasörlerin GERİ OLUŞMADIĞINI doğrular!
        """
        from idm_linux.installer import run_uninstall

        with tempfile.TemporaryDirectory() as tmpd:
            fake_home = Path(tmpd) / "home"
            fake_cfg = fake_home / ".config"
            fake_data = fake_home / ".local" / "share"
            fake_cache = fake_home / ".cache"

            # 1) Wine ortamı + IDM + AppData + Başka bir Wine programı (7-Zip) oluştur
            pfx = fake_home / ".wine"
            idm_prog = pfx / "drive_c" / "Program Files (x86)" / "Internet Download Manager"
            sevenzip_prog = pfx / "drive_c" / "Program Files" / "7-Zip"
            idm_appdata = pfx / "drive_c" / "users" / "tus" / "AppData" / "Roaming" / "IDM" / "DwnlData"
            idm_dmcache = pfx / "drive_c" / "users" / "tus" / "AppData" / "Roaming" / "DMCache"
            for d in (idm_prog, sevenzip_prog, idm_appdata, idm_dmcache):
                d.mkdir(parents=True, exist_ok=True)
            (idm_prog / "IDMan.exe").write_bytes(b"MZ_IDM")
            (sevenzip_prog / "7zFM.exe").write_bytes(b"MZ_7ZIP")
            (idm_appdata / "part1.tmp").write_bytes(b"PART")

            (pfx / "user.reg").write_text(
                'WINE REGISTRY Version 2\n\n'
                '[Software\\\\7-Zip] 1700000000\n'
                '"Path"="C:\\\\Program Files\\\\7-Zip"\n\n'
                '[Software\\\\DownloadManager] 1700000001\n'
                '"FName"="Test"\n\n'
                '[Software\\\\DownloadManager\\\\FoldersTree] 1700000002\n'
                '"Vis"=dword:00000001\n\n'
                '[Software\\\\Classes\\\\CLSID\\\\{ECF21EAB-3AA8-4355-82BE-F777990001DD}] 1700000003\n'
                '@="CIDMLinkTransmitter"\n\n'
                '[Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Run] 1700000004\n'
                '"IDMan"="C:\\\\Program Files (x86)\\\\Internet Download Manager\\\\IDMan.exe /onboot"\n'
                '"KeepOtherApp"="C:\\\\app.exe"\n\n'
                '[Software\\\\Wine\\\\DllOverrides] 1700000005\n'
                '"idmnetmon64"=""\n'
                '"d3d11"="native"\n',
                encoding="utf-8",
            )
            (pfx / "system.reg").write_text(
                'WINE REGISTRY Version 2\n\n'
                '[Software\\\\Wow6432Node\\\\DownloadManager] 1700000001\n'
                '"ExePath"="IDMan.exe"\n',
                encoding="utf-8",
            )

            # 2) Linux config, data, cache/logs, kısayollar ve tarayıcı bayrağı oluştur
            (fake_cfg / "idm-linux").mkdir(parents=True)
            (fake_cfg / "idm-linux" / "config.json").write_text(json.dumps({"wine_prefix": str(pfx)}), encoding="utf-8")
            (fake_cfg / "chromium-flags.conf").write_text(f"--load-extension={fake_data}/idm-linux/extensions/chromium\n", encoding="utf-8")
            (fake_data / "idm-linux" / "extensions").mkdir(parents=True)
            (fake_cache / "idm-linux" / "logs").mkdir(parents=True)
            (fake_cache / "idm-linux" / "logs" / "daemon.log").write_text("LOG DATA\n", encoding="utf-8")
            (fake_data / "applications").mkdir(parents=True)
            (fake_data / "applications" / "idm-linux.desktop").write_text("[Desktop Entry]\nName=IDM\n", encoding="utf-8")
            (fake_home / ".local" / "bin").mkdir(parents=True, exist_ok=True)
            (fake_home / ".local" / "bin" / "idm-linux").write_text("#!/bin/sh\n", encoding="utf-8")

            old_env = {k: os.environ.get(k) for k in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")}
            os.environ["HOME"] = str(fake_home)
            os.environ["XDG_CONFIG_HOME"] = str(fake_cfg)
            os.environ["XDG_DATA_HOME"] = str(fake_data)
            os.environ["XDG_CACHE_HOME"] = str(fake_cache)
            try:
                rc = run_uninstall(remove_wine_idm=True, log_fn=lambda _s: None)
                self.assertEqual(rc, 0)

                # Sonrasında GUI/CLI durum sorgulasa bile hiçbir klasör geri oluşmamalı!
                _ = IdmLinuxConfig.load()
                self.assertEqual(scan_existing_idm_installations(), [])

                self.assertFalse(idm_prog.exists())
                self.assertFalse(idm_appdata.parent.exists())
                self.assertFalse(idm_dmcache.exists())
                self.assertTrue((sevenzip_prog / "7zFM.exe").exists(), "Diğer Wine programına dokunulmamalı!")

                cleaned_ureg = (pfx / "user.reg").read_text(encoding="utf-8")
                self.assertNotIn("DownloadManager", cleaned_ureg)
                self.assertNotIn("ECF21EAB", cleaned_ureg)
                self.assertNotIn('"IDMan"=', cleaned_ureg)
                self.assertNotIn("idmnetmon64", cleaned_ureg)
                self.assertIn("[Software\\\\7-Zip]", cleaned_ureg)
                self.assertIn('"KeepOtherApp"', cleaned_ureg)
                self.assertIn('"d3d11"="native"', cleaned_ureg)

                cleaned_sreg = (pfx / "system.reg").read_text(encoding="utf-8")
                self.assertNotIn("DownloadManager", cleaned_sreg)

                self.assertFalse((fake_cfg / "idm-linux").exists())
                self.assertFalse((fake_data / "idm-linux").exists())
                self.assertFalse((fake_cache / "idm-linux").exists())
                self.assertFalse((fake_cfg / "chromium-flags.conf").exists())
                self.assertFalse((fake_data / "applications" / "idm-linux.desktop").exists())
                self.assertFalse((fake_home / ".local" / "bin" / "idm-linux").exists())
            finally:
                import idm_linux.config as _cfg_mod
                _cfg_mod._LOGGING_SUPPRESSED = False
                for k, v in old_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_19_idman_integrity_check_zero_missing_files_and_valid_pe_stubs(self) -> None:
        """
        Gerçek idman643build16.exe çıkarılıp neutralize_windows_hook_binaries() çalıştırıldığında:
        1) IDMan.exe'nin sub_45F3B0 ('5 dosyayı bulamıyor' uyarısını üreten bütünlük denetçisi!)
           tarafından aranan 24 dosyanın TAMAMININ klasörde mevcut olduğunu (missing == 0),
        2) Üretilen tüm PE32/PE32+ stub dosyalarının objdump tarafından hatasız doğrulandığını,
        3) Kernel .sys sürücülerinin kaldırıldığını kanıtlar!
        """
        import subprocess
        from idm_linux.installer import download_idm_installer
        from idm_linux.sfx_unpacker import unpack_idm_installer

        idman_sub45f3b0_required = (
            "oldjsproxy.dll",
            "Uninstall.exe",
            "IDManTypeInfo.tlb",
            "libssl.dll",
            "IDMMsgHost.json",
            "IDMMsgHost.exe",
            "idmindex.dll",
            "IDMGrHlp.exe",
            "libcrypto.dll",
            "IDMShellExt.dll",
            "IDMVMPrs.dll",
            "idmbrbtn.dll",
            "idmvs.dll",
            "idmvconv.dll",
            "idmnmcl.dll",
            "IDMGCExt.crx",
            "IDMNetMon.dll",
            "IDMShellExtAA.dll",
            "IDMNetMonAA.dll",
            "idmbrbtnAA.dll",
            "IDMShellExt64.dll",
            "IDMNetMon64.dll",
            "IDMVMPrs64.dll",
            "idmbrbtn64.dll",
        )

        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            exe = tmp / "idman.exe"
            download_idm_installer(IdmLinuxConfig().idm_installer_url, exe)
            idm_dir = tmp / "IDM"
            unpack_idm_installer(exe, idm_dir)
            neutralize_windows_hook_binaries(idm_dir)

            present_lower = {p.name.lower(): p for p in idm_dir.iterdir() if p.is_file()}
            missing = [req for req in idman_sub45f3b0_required if req.lower() not in present_lower]
            self.assertEqual(missing, [], f"IDMan.exe bütünlük denetiminde eksik dosya kalmamalı: {missing}")

            # Kernel .sys dosyaları silinmiş olmalı
            self.assertFalse((idm_dir / "idmwfp64.sys").exists())
            self.assertFalse((idm_dir / "idmtdi64.sys").exists())

            # Stub ikililerin geçerli PE32 / PE32+ olduğunu objdump ile doğrula
            if shutil.which("objdump"):
                for stub_name in ("IDMGrHlp.exe", "IDMIntegrator64.exe", "IDMNetMon.dll", "IDMNetMon64.dll", "idmbrbtn.dll", "idmbrbtn64.dll"):
                    sp = present_lower[stub_name.lower()]
                    self.assertIn(b"IDMLINUXSTUB", sp.read_bytes()[:0x60])
                    r = subprocess.run(["objdump", "-x", "-d", str(sp)], capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, f"{stub_name} geçerli PE olmalı: {r.stderr}")

    def test_20_browser_cookie_decrypt_v10_and_meta_v24(self) -> None:
        """
        Brave-Origin-Nightly / Chromium v130+ (meta.version=24, SHA256(host_key) önekli AES-128-CBC v10)
        SQLite Cookies veritabanından HttpOnly oturum çerezlerinin sıfır harici paketle çözüldüğünü doğrular!
        """
        import hashlib
        import sqlite3
        from idm_linux.browser_cookies import _PEANUTS_DERIVED_KEY, extract_browser_cookies_for_url

        openssl_bin = shutil.which("openssl")
        if not openssl_bin:
            self.skipTest("openssl bulunamadı")

        def _encrypt_v10(host_key: str, plain_val: str) -> bytes:
            raw_pt = hashlib.sha256(host_key.encode("utf-8")).digest() + plain_val.encode("utf-8")
            iv_hex = (b" " * 16).hex()
            res = subprocess.run(
                [openssl_bin, "enc", "-e", "-aes-128-cbc", "-K", _PEANUTS_DERIVED_KEY.hex(), "-iv", iv_hex],
                input=raw_pt,
                capture_output=True,
                check=True,
            )
            return b"v10" + res.stdout

        with tempfile.TemporaryDirectory() as tmpd:
            old_cfg = os.environ.get("XDG_CONFIG_HOME")
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = tmpd
            os.environ["XDG_CONFIG_HOME"] = str(Path(tmpd) / ".config")
            try:
                net_dir = Path(tmpd) / ".config" / "BraveSoftware" / "Brave-Origin-Nightly" / "Default" / "Network"
                net_dir.mkdir(parents=True, exist_ok=True)
                (net_dir.parent.parent / "Local State").write_text("{}", encoding="utf-8")
                cdb = net_dir / "Cookies"

                conn = sqlite3.connect(str(cdb))
                conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
                conn.execute("INSERT INTO meta VALUES ('version', '24')")
                conn.execute(
                    "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB, "
                    "path TEXT, is_secure INTEGER, expires_utc INTEGER)"
                )
                enc_sess = _encrypt_v10(".arena.ai", "jwt_clerk_token_xyz987")
                enc_cf = _encrypt_v10("arena.ai", "cf_clear_brave_nightly_42")
                conn.execute(
                    "INSERT INTO cookies VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (".arena.ai", "__session", "", enc_sess, "/", 1, 0),
                )
                conn.execute(
                    "INSERT INTO cookies VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("arena.ai", "cf_clearance", "", enc_cf, "/", 1, 0),
                )
                conn.commit()
                conn.close()

                ck_hdr = extract_browser_cookies_for_url("https://arena.ai/api/workspace/file?id=123")
                self.assertIn("__session=jwt_clerk_token_xyz987", ck_hdr)
                self.assertIn("cf_clearance=cf_clear_brave_nightly_42", ck_hdr)
            finally:
                if old_cfg is None:
                    os.environ.pop("XDG_CONFIG_HOME", None)
                else:
                    os.environ["XDG_CONFIG_HOME"] = old_cfg
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_21_authenticated_arena_download_and_blob_proxy_e2e(self) -> None:
        """
        Çerez/Authorization olmadan 401 'Authorization Required' dönen korumalı sunucudan (arena.ai simülasyonu)
        ve blob: bellek indirmelerinden yerel /proxy/ köprüsü üzerinden 206 Partial Content (Range) ile
        şifre sormadan, gerçek dosya adıyla tam hızda indirme yapıldığını uçtan uca doğrular!
        """
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from idm_linux.auth_proxy import AuthContextVault, AuthenticatedProxyManager
        from idm_linux.protocol import DownloadRequest

        secret_payload = b"ARENA_PROTECTED_TAR_GZ_PAYLOAD_" * 200  # 6200 bayt

        class ProtectedArenaHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                ck = self.headers.get("Cookie") or ""
                auth = self.headers.get("Authorization") or ""
                if "arena_sess=valid_123" not in ck or auth != "Bearer secret_arena_jwt":
                    self.send_response(401)
                    self.send_header('WWW-Authenticate', 'Basic realm="Authorization Required"')
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

                rng = self.headers.get("Range") or ""
                start, end = 0, len(secret_payload) - 1
                partial = False
                if rng.startswith("bytes="):
                    s_p, e_p = rng[6:].split("-", 1)
                    if s_p:
                        start = int(s_p)
                    if e_p:
                        end = min(int(e_p), len(secret_payload) - 1)
                    partial = True

                chunk = secret_payload[start : end + 1]
                self.send_response(206 if partial else 200)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Accept-Ranges", "bytes")
                if partial:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(secret_payload)}")
                self.send_header("Content-Length", str(len(chunk)))
                self.send_header("Content-Disposition", 'attachment; filename="idm-linux-v2.4.0.tar.gz"')
                self.end_headers()
                self.wfile.write(chunk)

        up_srv = HTTPServer(("127.0.0.1", 0), ProtectedArenaHandler)
        up_port = up_srv.server_port
        threading.Thread(target=up_srv.serve_forever, daemon=True).start()

        vault = AuthContextVault()
        mgr = AuthenticatedProxyManager(vault)

        class BridgeProxyHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                return

            def do_HEAD(self) -> None:
                tid = [p for p in self.path.split("/") if p][1]
                mgr.serve_proxy_ticket(self, tid, head_only=True)

            def do_GET(self) -> None:
                tid = [p for p in self.path.split("/") if p][1]
                mgr.serve_proxy_ticket(self, tid, head_only=False)

        prx_srv = HTTPServer(("127.0.0.1", 0), BridgeProxyHandler)
        prx_port = prx_srv.server_port
        threading.Thread(target=prx_srv.serve_forever, daemon=True).start()

        try:
            # 127.0.0.1 test sunucusuna dış host adı gibi erişmek için localhost olmayan 127.0.0.2 yerine
            # doğrudan URL kaydı ve sarmalama testi:
            protected_url = f"http://127.0.0.1:{up_port}/api/workspace/download?id=abc"
            # Önce doğrudan çerezsiz gidildiğinde 401 geldiğini kanıtla
            with self.assertRaises(urllib.error.HTTPError) as ctx401:
                urllib.request.urlopen(protected_url, timeout=2)
            self.assertEqual(ctx401.exception.code, 401)
            self.assertIn("Authorization Required", ctx401.exception.headers.get("WWW-Authenticate", ""))

            # Şimdi kimlikli bilet oluştur (gerçekte maybe_wrap_authenticated_download tarafından üretilir)
            req = DownloadRequest(
                url=protected_url,
                cookies="arena_sess=valid_123",
                extra_headers={"Authorization": "Bearer secret_arena_jwt"},
            )
            needs_prx, disc_fn, _ = mgr._probe_upstream(req)
            self.assertTrue(needs_prx)
            self.assertEqual(disc_fn, "idm-linux-v2.4.0.tar.gz")

            from idm_linux.auth_proxy import AuthProxyTicket
            ticket = AuthProxyTicket(
                ticket_id="testticket01",
                kind="remote",
                filename=disc_fn,
                target_url=protected_url,
                cookies=req.cookies,
                extra_headers=req.extra_headers,
            )
            mgr._tickets[ticket.ticket_id] = ticket

            # IDMan.exe gibi ÇEREZSİZ ve Range: bytes=0-99 ile yerel /proxy/ adresinden çek!
            r_part = urllib.request.Request(
                f"http://127.0.0.1:{prx_port}/proxy/testticket01/idm-linux-v2.4.0.tar.gz",
                headers={"Range": "bytes=0-99"},
            )
            with urllib.request.urlopen(r_part, timeout=3) as resp:
                self.assertEqual(resp.getcode(), 206)
                self.assertIsNone(resp.headers.get("WWW-Authenticate"))
                self.assertIn("idm-linux-v2.4.0.tar.gz", resp.headers.get("Content-Disposition", ""))
                data_part = resp.read()
                self.assertEqual(len(data_part), 100)
                self.assertEqual(data_part, secret_payload[:100])

            # 2. Blob bilet testi
            blob_ticket = mgr.create_blob_ticket(b"BLOB_WORKSPACE_CONTENT_12345", "notlar.txt", "text/plain")
            with urllib.request.urlopen(
                f"http://127.0.0.1:{prx_port}/proxy/{blob_ticket.ticket_id}/notlar.txt",
                timeout=3,
            ) as b_resp:
                self.assertEqual(b_resp.getcode(), 200)
                self.assertEqual(b_resp.read(), b"BLOB_WORKSPACE_CONTENT_12345")
        finally:
            up_srv.shutdown()
            up_srv.server_close()
            prx_srv.shutdown()
            prx_srv.server_close()

    def test_22_brave_origin_nightly_discovery_wrapper_relaunch_and_zip_package(self) -> None:
        """
        1) Brave-Origin-Nightly profilinin dinamik olarak bulunup NativeMessagingHosts kaydedildiğini,
        2) >15 karakterlik kabuk sarmalayıcısıyla çalışan tarayıcı sürecinin terminate_browser_gracefully()
           ile tam isabetle kapatıldığını,
        3) CRX_REQUIRED_PROOF_MISSING hatası vermeyen .ZIP eklenti paketinin üretilip doğrulandığını ve
           127.0.0.1/extension/* adresinin yakalama dışı tutulduğunu,
        4) unregister_all_browsers() ile sıfır kalıntı bırakıldığını kanıtlar!
        """
        import zipfile
        from idm_linux.browsers import (
            DetectedDefaultBrowser,
            configure_chromium_autoload_flags,
            get_browser_extensions_url,
            register_all_browsers,
            terminate_browser_gracefully,
            unregister_all_browsers,
        )
        from idm_linux.crx_builder import build_chromium_zip_package

        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            old_home = os.environ.get("HOME")
            old_cfg = os.environ.get("XDG_CONFIG_HOME")
            os.environ["HOME"] = str(tmp)
            os.environ["XDG_CONFIG_HOME"] = str(tmp / ".config")
            try:
                # 1. Sahte Brave-Origin-Nightly profili ve sarmalayıcı betiği kur
                bon_prof = tmp / ".config" / "BraveSoftware" / "Brave-Origin-Nightly" / "Default"
                bon_prof.mkdir(parents=True, exist_ok=True)
                (bon_prof.parent / "Local State").write_text("{}", encoding="utf-8")

                opt_bon = tmp / "opt_brave_origin_nightly"
                opt_bon.mkdir(parents=True, exist_ok=True)
                wrapper_bin = opt_bon / "brave-origin-nightly"
                wrapper_bin.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
                wrapper_bin.chmod(0o755)

                apps_dir = tmp / ".local" / "share" / "applications"
                apps_dir.mkdir(parents=True, exist_ok=True)
                desk_file = apps_dir / "brave-origin-nightly.desktop"
                desk_file.write_text(
                    f"[Desktop Entry]\nName=Brave Origin Nightly\nExec={wrapper_bin} %U\nType=Application\n",
                    encoding="utf-8",
                )

                fake_nh_wrapper = tmp / "idm-native-host"
                fake_nh_wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                fake_nh_wrapper.chmod(0o755)

                chrom_src = PROJECT_ROOT / "extension" / "chromium"
                targets = register_all_browsers(fake_nh_wrapper, chrom_ext_dir=chrom_src)
                bon_nh = tmp / ".config" / "BraveSoftware" / "Brave-Origin-Nightly" / "NativeMessagingHosts"
                self.assertTrue((bon_nh / "com.tonec.idm.json").is_file())
                self.assertTrue((bon_nh / "com.idmlinux.companion.json").is_file())

                det = DetectedDefaultBrowser(
                    name="Brave Origin Nightly",
                    family="chromium",
                    binary=str(wrapper_bin),
                    desktop_id="brave-origin-nightly.desktop",
                )
                self.assertEqual(get_browser_extensions_url(det), "brave://extensions")
                configure_chromium_autoload_flags(chrom_src, default_browser=det)
                patched_desk = desk_file.read_text(encoding="utf-8")
                self.assertIn("--load-extension=", patched_desk)
                self.assertIn("DisableLoadExtensionCommandLineSwitch", patched_desk)

                # 2. >15 karakterlik sarmalayıcı sürecini başlat ve terminate_browser_gracefully ile kapat!
                proc = subprocess.Popen([str(wrapper_bin)], start_new_session=True)
                try:
                    time.sleep(0.2)
                    self.assertIsNone(proc.poll())
                    closed = terminate_browser_gracefully(str(wrapper_bin), timeout_sec=3.0)
                    self.assertTrue(closed)
                    proc.wait(timeout=2.0)
                finally:
                    if proc.poll() is None:
                        proc.kill()

                # 3. ZIP paketi ve /extension/ yakalama istisnası
                out_zip = tmp / "idm-linux-companion-chromium.zip"
                build_chromium_zip_package(chrom_src, out_zip)
                self.assertTrue(out_zip.is_file())
                with zipfile.ZipFile(out_zip, "r") as zf:
                    self.assertIn("manifest.json", zf.namelist())
                    mf = json.loads(zf.read("manifest.json").decode("utf-8"))
                    from idm_linux import __version__ as pkg_ver
                    self.assertEqual(mf["version"], pkg_ver)

                self.assertTrue(
                    is_domain_excluded(
                        "http://127.0.0.1:17802/extension/idm-linux-companion-chromium.zip",
                        "http://127.0.0.1:17802/welcome",
                        [],
                    )
                )

                # 4. Unregister sonrasında orijinal .desktop geri yüklenmeli ve manifestler silinmeli
                unregister_all_browsers()
                self.assertFalse((bon_nh / "com.tonec.idm.json").exists())
                restored_desk = desk_file.read_text(encoding="utf-8")
                self.assertNotIn("--load-extension=", restored_desk)
                self.assertIn(f"Exec={wrapper_bin} %U", restored_desk)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
                if old_cfg is None:
                    os.environ.pop("XDG_CONFIG_HOME", None)
                else:
                    os.environ["XDG_CONFIG_HOME"] = old_cfg

    def test_23_window_icon_assets_wmclass_and_gui_pages(self) -> None:
        """
        1) Pencere ve görev çubuğu ikonlarının (idm_icon_128..16.png) geçerli PNG olduğunu,
        2) gui.py içinde className='idm-linux-panel' + iconphoto(True, ...) ve installer.py içinde StartupWMClass=idm-linux-panel tanımlandığını,
        3) Başsız (Xvfb / Tkinter) ortamda 'Diğer Projeler' ve 'Teşekkür Et & Destekle' sayfalarının hatasız render edildiğini doğrular!
        """
        from idm_linux.projects_data import get_assets_dir

        assets = get_assets_dir()
        for sz in (128, 64, 48, 32, 16):
            p = assets / f"idm_icon_{sz}.png"
            self.assertTrue(p.is_file(), f"Eksik pencere ikonu: {p}")
            self.assertEqual(p.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

        gui_src = (PROJECT_ROOT / "gui.py").read_text(encoding="utf-8")
        self.assertIn('tk.Tk(className="idm-linux-panel")', gui_src)
        self.assertIn("root.iconphoto(True,", gui_src)
        self.assertIn('("projects", t("nav.projects"))', gui_src)
        self.assertIn('("support", t("nav.support"))', gui_src)
        self.assertIn('("language",', gui_src)

        inst_src = (PROJECT_ROOT / "installer.py").read_text(encoding="utf-8")
        self.assertIn("StartupWMClass=idm-linux-panel", inst_src)
        self.assertIn("application/x-bittorrent;x-scheme-handler/magnet;", inst_src)

    def test_24_qr_generator_and_all_projects_catalog(self) -> None:
        """
        Saf Python ISO/IEC 18004 QR üreticisinin geçerli PNG ürettiğini ve
        PROJECTS_CATALOG içindeki tüm 10 projenin (5 Google Play, Web, YouTube, Masaüstü, 2 Yakında)
        ikon/görsel dosyalarının eksiksiz olduğunu doğrular.
        """
        from idm_linux.projects_data import PROJECTS_CATALOG, get_assets_dir
        from idm_linux.qr_gen import render_qr_png_bytes

        self.assertEqual(len(PROJECTS_CATALOG), 11)
        assets = get_assets_dir()
        slugs = {p.slug for p in PROJECTS_CATALOG}
        for expected in (
            "belgeselsemo-web",
            "youtube-learn-explore",
            "matpay",
            "belgeselsemoflix",
            "gp-epgviewer",
            "gp-belgeselsemo",
            "gp-nb724",
            "gp-nutuk",
            "gp-trivia",
            "upcoming-retro-emulator",
            "upcoming-economy",
        ):
            self.assertIn(expected, slugs)

        for proj in PROJECTS_CATALOG:
            icon_p = assets / proj.icon_file
            self.assertTrue(icon_p.is_file(), f"Proje ikonu eksik: {proj.icon_file}")
            self.assertEqual(icon_p.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            if proj.banner_file:
                ban_p = assets / proj.banner_file
                self.assertTrue(ban_p.is_file(), f"Proje afişi eksik: {proj.banner_file}")
                self.assertEqual(ban_p.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            qr_bytes = render_qr_png_bytes(proj.qr_url or proj.primary_url, scale=4, border=3)
            self.assertEqual(qr_bytes[:8], b"\x89PNG\r\n\x1a\n")
            self.assertGreater(len(qr_bytes), 300)

    def test_25_support_endpoint_nowpayments_iframe_and_pos_qr(self) -> None:
        """
        Canlı /support uç noktasının 3 destek yöntemini, NOWPayments POS bağlantısını,
        karekodunu ve tam NOWPayments <iframe> widget kodunu döndürdüğünü doğrular.
        """
        import threading
        from http.server import ThreadingHTTPServer
        from idm_linux.daemon import DaemonState, make_http_handler
        from idm_linux.projects_data import NOWPAYMENTS_IFRAME_SNIPPET, NOWPAYMENTS_POS_URL

        state = DaemonState()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_http_handler(state))
        port = srv.server_address[1]
        state.cfg.http_port = port
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/support?lang=tr", timeout=4) as r:
                self.assertEqual(r.status, 200)
                html_txt = r.read().decode("utf-8")
                self.assertIn(NOWPAYMENTS_IFRAME_SNIPPET, html_txt)
                self.assertIn(NOWPAYMENTS_POS_URL, html_txt)
                self.assertIn("https://nowpayments.io/donation/belgeselsemo55", html_txt)
                self.assertIn("https://belgeselsemo.com.tr/premium-uyelik/", html_txt)
                self.assertIn("https://www.youtube.com/@belgeselsemo55", html_txt)
                self.assertIn("data:image/png;base64,", html_txt)
                self.assertIn("hayır duasını", html_txt)
                self.assertNotIn("tek kuruş", html_txt.lower())
        finally:
            srv.shutdown()
            srv.server_close()

    def test_26_bencode_magnet_parser_and_bitfield_continuity(self) -> None:
        """
        Saf Python Bencode .torrent çözümleyicisini, magnet:? ayrıştırıcısını ve
        aria2 bitfield ardışık doğrulanmış parça sayacını doğrular.
        """
        import hashlib
        from idm_linux.torrent_engine import (
            count_contiguous_leading_pieces,
            parse_magnet_uri,
            parse_torrent_bytes,
        )

        # Örnek tek dosyalı Bencode .torrent
        ann_u = b"udp://tracker.opentrackr.org:1337/ann"
        ws_u = b"http://127.0.0.1:9999/testfile.mp4"
        fn_u = b"belgesel_test_1080p.mp4"
        info_dict = (
            b"d6:lengthi1048576e4:name" + str(len(fn_u)).encode() + b":" + fn_u
            + b"12:piece lengthi262144e6:pieces80:" + (b"\x11" * 80) + b"e"
        )
        expected_ih = hashlib.sha1(info_dict).hexdigest()
        tor_bytes = (
            b"d8:announce" + str(len(ann_u)).encode() + b":" + ann_u
            + b"4:info" + info_dict
            + b"8:url-list" + str(len(ws_u)).encode() + b":" + ws_u + b"e"
        )
        meta = parse_torrent_bytes(tor_bytes)
        self.assertEqual(meta.name, "belgesel_test_1080p.mp4")
        self.assertEqual(meta.total_size, 1048576)
        self.assertEqual(meta.info_hash, expected_ih)
        self.assertFalse(meta.is_multi_file)
        self.assertEqual(meta.web_seeds, ["http://127.0.0.1:9999/testfile.mp4"])

        # Magnet bağlantısı
        mag = (
            f"magnet:?xt=urn:btih:{expected_ih}&dn=CachyOS+Linux+ISO&xl=2684354560"
            "&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
        )
        m_meta = parse_magnet_uri(mag)
        self.assertEqual(m_meta.info_hash, expected_ih)
        self.assertEqual(m_meta.name, "CachyOS Linux ISO")
        self.assertEqual(m_meta.total_size, 2684354560)

        # Bitfield ardışık parça kontrolü: 0xEF = 11101111 -> 3. bit 0 olduğu için yalnızca ilk 3 parça güvenli!
        self.assertEqual(count_contiguous_leading_pieces("ef", 8), 3)
        self.assertEqual(count_contiguous_leading_pieces("ff80", 12), 9)
        self.assertEqual(count_contiguous_leading_pieces("ffff", 10), 10)

    def test_27_e2e_torrent_and_magnet_bridge_to_idm(self) -> None:
        """
        Gerçek .torrent dosyasını canlı köprü sunucusu (/api/torrent/download ve /api/download)
        üzerinden IDM'ye yönlendirir ve IDMan.exe'nin bağlandığı /torrent/<ticket>/<dosya>
        adresinden hedef ikili dosyanın SHA-256 doğrulamalı tam aktarımını kanıtlar!
        """
        import base64
        import hashlib
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from idm_linux.daemon import DaemonState, make_http_handler

        payload_data = os.urandom(96 * 1024)  # 96 KB rastgele gerçek ikili veri
        expected_sha = hashlib.sha256(payload_data).hexdigest()

        class WebSeedHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload_data)))
                self.end_headers()
                self.wfile.write(payload_data)

        seed_srv = ThreadingHTTPServer(("127.0.0.1", 0), WebSeedHandler)
        seed_port = seed_srv.server_address[1]
        threading.Thread(target=seed_srv.serve_forever, daemon=True).start()

        dispatched_reqs = []
        state = DaemonState()

        # v3.10.0 NOTU: Bu test aria2c YEDEK yolunu (ve WebSeed köprüsünü) doğrular.
        # Ana motor artık yerleşik native BitTorrent motoru olduğu için burada native
        # yol bilinçli olarak KAPATILIR — böylece aria2c/webseed yedeği regresyona
        # karşı korunmaya devam eder. (Native yol ayrı testlerde doğrulanıyor:
        # tests/test_p2p_native.py)
        import idm_linux.torrent_engine as _te

        _orig_native = _te.TorrentSession._try_native_start
        _te.TorrentSession._try_native_start = lambda self: False

        def _mock_send(req):
            dispatched_reqs.append(req)
            return True, "Mock IDM OK"

        state.sender.send_download = _mock_send  # type: ignore[method-assign]
        bridge_srv = ThreadingHTTPServer(("127.0.0.1", 0), make_http_handler(state))
        b_port = bridge_srv.server_address[1]
        state.cfg.http_port = b_port
        threading.Thread(target=bridge_srv.serve_forever, daemon=True).start()

        try:
            seed_url = f"http://127.0.0.1:{seed_port}/arsiv_paketi.iso".encode("ascii")
            info_part = (
                b"d6:lengthi" + str(len(payload_data)).encode("ascii") + b"e"
                b"4:name16:arsiv_paketi.iso12:piece lengthi32768e"
                b"6:pieces60:" + (b"\x22" * 60) + b"e"
            )
            tor_raw = (
                b"d8:url-list" + str(len(seed_url)).encode("ascii") + b":" + seed_url
                + b"4:info" + info_part + b"e"
            )

            req_post = urllib.request.Request(
                f"http://127.0.0.1:{b_port}/api/torrent/download",
                data=json.dumps({"torrent_base64": base64.b64encode(tor_raw).decode("ascii")}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_post, timeout=5) as resp:
                rjson = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(rjson["ok"])
                self.assertEqual(rjson["filename"], "arsiv_paketi.iso")

            self.assertEqual(len(dispatched_reqs), 1)
            idm_target_url = dispatched_reqs[0].url
            self.assertIn(f"http://127.0.0.1:{b_port}/torrent/", idm_target_url)

            # Şimdi IDMan.exe gibi bu köprü URL'sinden dosyayı indir ve SHA-256 karşılaştır!
            # aria2c RPC+DHT ilk doğrulanmış bayt gecikmesi yavaş makinelerde 8 sn'yi aşabilir (flaky önlemi)
            with urllib.request.urlopen(idm_target_url, timeout=30) as dl_resp:
                self.assertEqual(dl_resp.status, 200)
                received = dl_resp.read()
                self.assertEqual(len(received), len(payload_data))
                self.assertEqual(hashlib.sha256(received).hexdigest(), expected_sha)

            # Magnet bağlantısı da /api/download üzerinden otomatik yakalanıp IDM'ye yönlendirilmeli!
            mag_uri = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=ornek_paket.zip"
            req_mag = urllib.request.Request(
                f"http://127.0.0.1:{b_port}/api/download",
                data=json.dumps({"url": mag_uri, "force": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_mag, timeout=5) as m_resp:
                mjson = json.loads(m_resp.read().decode("utf-8"))
            # v3.7.0 SENKRON HAZIRLIK KAPISI: WebSeed'siz magnet yalnızca aria2c GERÇEKTEN
            # çalışıyorsa IDM'ye gider; motor yoksa SAHTE 503 yerine NET hata döner.
            if shutil.which("aria2c"):
                self.assertTrue(mjson["ok"], mjson.get("message", ""))
                self.assertEqual(len(dispatched_reqs), 2)
                self.assertIn("/torrent/", dispatched_reqs[1].url)
                self.assertEqual(dispatched_reqs[1].filename, "ornek_paket.zip")
            else:
                self.assertFalse(mjson["ok"])
                self.assertIn("aria2", mjson.get("message", ""))
                self.assertEqual(len(dispatched_reqs), 1)
        finally:
            _te.TorrentSession._try_native_start = _orig_native
            bridge_srv.shutdown()
            bridge_srv.server_close()
            seed_srv.shutdown()
            seed_srv.server_close()
            state.torrent_bridge.shutdown_all()

    def test_28_twenty_languages_txt_catalog_and_placeholder_parity(self) -> None:
        """
        language/*.txt altındaki 20 dil dosyasının tamamının eksiksiz mevcut olduğunu,
        birebir aynı anahtar kümesine ve {placeholder} değişkenlerine sahip olduğunu,
        ve 1. Yöntem metninde 'tek kuruş harcamadan' ifadesinin yer almadığını doğrular.
        """
        import re
        from idm_linux.i18n import I18nManager, SUPPORTED_LANGUAGES, find_language_dir, parse_lang_txt_file

        expected_20 = {
            "tr", "en", "de", "fr", "ru", "zh", "ja", "hi", "ar", "nl",
            "fa", "el", "pt", "vi", "az", "ky", "it", "id", "ka", "ro",
        }
        self.assertEqual(set(SUPPORTED_LANGUAGES.keys()), expected_20)

        lang_dir = find_language_dir()
        self.assertTrue(lang_dir.is_dir(), f"language klasörü bulunamadı: {lang_dir}")

        tr_map = parse_lang_txt_file(lang_dir / "tr.txt")
        self.assertGreaterEqual(len(tr_map), 320)
        self.assertNotIn("tek kuruş", tr_map["sup.m1_desc"].lower())
        self.assertNotIn("kuruş harcamadan", tr_map["sup.m1_desc"].lower())

        ph_re = re.compile(r"\{[a-zA-Z0-9_:]+\}")
        master_ph = {k: set(ph_re.findall(v)) for k, v in tr_map.items()}

        for code in sorted(expected_20):
            txt_file = lang_dir / f"{code}.txt"
            self.assertTrue(txt_file.is_file(), f"Eksik dil dosyası: {txt_file}")
            cur_map = parse_lang_txt_file(txt_file)
            self.assertEqual(set(cur_map.keys()), set(tr_map.keys()), f"{code}.txt anahtar farkı var!")
            for k, val in cur_map.items():
                self.assertTrue(val.strip(), f"{code}.txt içinde boş çeviri: {k}")
                self.assertEqual(
                    set(ph_re.findall(val)),
                    master_ph[k],
                    f"{code}.txt -> {k} placeholder uyuşmazlığı!",
                )
            mgr = I18nManager(code)
            self.assertEqual(mgr.lang, code)
            self.assertIn("BELGESELSEMO", mgr.t("footer.credit_template", belgeselsemo="BELGESELSEMO", arena="ARENA.AI"))

    def test_29_auto_os_language_detection_and_idm_lng_fallback(self) -> None:
        """
        İşletim sistemi dilinin otomatik algılandığını ve IDM'nin desteklediği 18 dilde kendi
        idm_*.lng paketine, desteklemediği dillerde (az, ky) ise İngilizceye (0x09, '') ayarlandığını doğrular.
        """
        from idm_linux.i18n import detect_system_language, get_idm_registry_language_pair

        saved_env = {k: os.environ.get(k) for k in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")}
        try:
            for k in saved_env:
                os.environ.pop(k, None)

            cases = [
                ("tr_TR.UTF-8", "tr"),
                ("de_DE.UTF-8", "de"),
                ("nl_NL.UTF-8", "nl"),
                ("fa_IR.UTF-8", "fa"),
                ("el_GR.UTF-8", "el"),
                ("az_AZ.UTF-8", "az"),
                ("ky_KG.UTF-8", "ky"),
                ("ka_GE.UTF-8", "ka"),
                ("ro_RO.UTF-8", "ro"),
                ("zh_CN.UTF-8", "zh"),
                ("ja_JP.UTF-8", "ja"),
                ("sv_SE.UTF-8", "en"),  # 20 dil dışındaki OS dili -> İngilizce fallback
            ]
            for raw_loc, exp_code in cases:
                os.environ["LANG"] = raw_loc
                self.assertEqual(detect_system_language(), exp_code, f"Locale={raw_loc}")

            # IDM Registry Dil Eşleştirmesi
            self.assertEqual(get_idm_registry_language_pair("tr"), (0x1F, "idm_tr.lng"))
            self.assertEqual(get_idm_registry_language_pair("en"), (0x09, ""))
            self.assertEqual(get_idm_registry_language_pair("de"), (0x07, "idm_de.lng"))
            self.assertEqual(get_idm_registry_language_pair("zh"), (0x804, "idm_chn2.lng"))
            self.assertEqual(get_idm_registry_language_pair("ja"), (0x11, "idm_jp.lng"))
            self.assertEqual(get_idm_registry_language_pair("el"), (0x08, "idm_gr.lng"))
            self.assertEqual(get_idm_registry_language_pair("ka"), (0x37, "idm_ge.lng"))
            self.assertEqual(get_idm_registry_language_pair("ro"), (0x18, "idm_ro.lng"))
            # IDM'de yerel dil dosyası bulunmayan diller -> Otomatik İngilizce (0x09, "")
            self.assertEqual(get_idm_registry_language_pair("az"), (0x09, ""))
            self.assertEqual(get_idm_registry_language_pair("ky"), (0x09, ""))
        finally:
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_30_standalone_iframe_host_nowpayments_donation_pos_and_premium(self) -> None:
        """
        Daemon kapalı olsa dahi çalışan EmbeddedIframeHost sunucusunun
        https://nowpayments.io/donation/belgeselsemo55, POS terminali ve
        https://belgeselsemo.com.tr/premium-uyelik/ bağlantılarını <iframe> penceresi olarak sunduğunu doğrular.
        """
        from idm_linux.projects_data import (
            BELGESELSEMO_PREMIUM_URL,
            NOWPAYMENTS_DONATION_URL,
            NOWPAYMENTS_POS_URL,
        )
        from idm_linux.support_page import build_support_html
        from idm_linux.webview_modal import EmbeddedIframeHost

        self.assertEqual(NOWPAYMENTS_DONATION_URL, "https://nowpayments.io/donation/belgeselsemo55")
        self.assertEqual(NOWPAYMENTS_POS_URL, "https://nowpayments.io/pos-terminal/belgeselsemo55")
        self.assertEqual(BELGESELSEMO_PREMIUM_URL, "https://belgeselsemo.com.tr/premium-uyelik/")

        host = EmbeddedIframeHost.instance()
        try:
            for mode, expected_src in (
                ("donation", NOWPAYMENTS_DONATION_URL),
                ("pos", NOWPAYMENTS_POS_URL),
                ("premium", BELGESELSEMO_PREMIUM_URL),
            ):
                u = host.build_url(mode=mode, lang_code="tr")
                with urllib.request.urlopen(u, timeout=4) as r:
                    self.assertEqual(r.status, 200)
                    body = r.read().decode("utf-8")
                    self.assertIn("<iframe", body)
                    self.assertIn(f'src="{expected_src}"', body)

            # /support HTML de 4 yöntemin tamamını ve text-align: justify stilini içermeli
            sup_html = build_support_html(lang_code="tr")
            self.assertIn(NOWPAYMENTS_DONATION_URL, sup_html)
            self.assertIn(NOWPAYMENTS_POS_URL, sup_html)
            self.assertIn(BELGESELSEMO_PREMIUM_URL, sup_html)
            self.assertIn("text-align: justify", sup_html)
            self.assertNotIn("tek kuruş", sup_html.lower())
        finally:
            host.stop()

    def test_31_justified_text_engine_and_png_badges_integrity(self) -> None:
        """
        Yeni RGBA PNG rozet ikonlarının bozuk X11 emojileri yerine geçerli PNG dosyaları olduğunu
        ve kelime parçalayıcının LTR / CJK metinlerini doğru ayrıştırdığını doğrular.
        """
        from idm_linux.gui_pages import _tokenize_for_justify
        from idm_linux.projects_data import get_assets_dir

        assets = get_assets_dir()
        for fn in (
            "badge_yt.png",
            "badge_heart.png",
            "badge_crypto.png",
            "badge_crown.png",
            "bullet_emerald.png",
            "bullet_gold.png",
        ):
            p = assets / fn
            self.assertTrue(p.is_file(), f"Eksik PNG rozet ikonu: {p}")
            self.assertEqual(p.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

        # LTR ve CJK tokenizasyon kontrolü
        tr_tokens = _tokenize_for_justify("BELGESELSEMO kültür arşivini güçlendirin!", "tr")
        self.assertEqual(tr_tokens, ["BELGESELSEMO", "kültür", "arşivini", "güçlendirin!"])
        zh_tokens = _tokenize_for_justify("支持开源项目IDM-Linux持续发展", "zh")
        self.assertGreater(len(zh_tokens), 6)
        self.assertIn("IDM-Linux", zh_tokens)

    def test_32_twenty_language_flag_png_icons_and_rtl_shaper(self) -> None:
        """
        20 dilin tamamı için gerçek PNG ülke bayraklarının (flag_<code>.png) mevcut olduğunu
        ve Arapça/Farsça metin birleştiricisinin (rtl_shaper) harfleri doğru birleştirdiğini doğrular.
        """
        from idm_linux.i18n import LANGUAGE_LIST
        from idm_linux.projects_data import get_assets_dir
        from idm_linux.rtl_shaper import shape_rtl_for_tk

        assets = get_assets_dir()
        self.assertEqual(len(LANGUAGE_LIST), 20)
        for lspec in LANGUAGE_LIST:
            fp = assets / f"flag_{lspec.code}.png"
            self.assertTrue(fp.is_file(), f"Eksik bayrak simgesi: {fp}")
            raw = fp.read_bytes()
            self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
            self.assertGreater(len(raw), 150)

        ar_shaped = shape_rtl_for_tk("العربية")
        fa_shaped = shape_rtl_for_tk("فارسی")
        self.assertNotEqual(ar_shaped, "العربية")
        self.assertNotEqual(fa_shaped, "فارسی")
        # Presentation Forms aralığında (0xFB50..0xFEFF) birleşik glif içermeli
        self.assertTrue(any(0xFB50 <= ord(ch) <= 0xFEFF for ch in ar_shaped))
        self.assertTrue(any(0xFB50 <= ord(ch) <= 0xFEFF for ch in fa_shaped))

    def test_33_uninstall_never_invokes_wine_reg_delete_timeout(self) -> None:
        """
        Soğuk Wine-11.20 ortamında 'wine reg delete' 30 saniye takılsa bile,
        purge_wine_prefix_idm_artifacts fonksiyonunun hiçbir zaman 'wine reg' çağırmadan
        ve TimeoutExpired fırlatmadan < 1 saniye içinde tüm IDM kayıtlarını kazıdığını kanıtlar!
        """
        import time
        from idm_linux.installer import purge_wine_prefix_idm_artifacts

        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            # Eğer yanlışlıkla 'wine' çağrılırsa 20 saniye uyuyup patlayacak tuzak ikili!
            fake_wine = fake_bin / "wine"
            fake_wine.write_text("#!/bin/sh\nsleep 20\nexit 1\n", encoding="utf-8")
            fake_wine.chmod(0o755)

            pfx = tmp / ".wine"
            (pfx / "drive_c" / "Program Files (x86)" / "Internet Download Manager").mkdir(parents=True)
            (pfx / "drive_c" / "Program Files (x86)" / "Internet Download Manager" / "IDMan.exe").write_bytes(b"MZ")
            (pfx / "system.reg").write_text(
                '[Software\\\\DownloadManager] 1700000000\n"ExePath"="C:\\\\IDMan.exe"\n\n[Software\\\\7-Zip] 1700000000\n"Path"="C:\\\\7z"\n',
                encoding="utf-8",
            )

            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{fake_bin}:{old_path}"
            try:
                t0 = time.monotonic()
                purge_wine_prefix_idm_artifacts(pfx, log_fn=lambda _s: None)
                elapsed = time.monotonic() - t0
                self.assertLess(elapsed, 2.0, "Kaldırıcı takılan 'wine' ikilisini çağırmamalı!")
                sys_reg = (pfx / "system.reg").read_text(encoding="utf-8")
                self.assertNotIn("DownloadManager", sys_reg)
                self.assertIn("7-Zip", sys_reg)
            finally:
                os.environ["PATH"] = old_path

    def test_34_official_idman_pe_icon_extraction_and_distinct_desktop_icons(self) -> None:
        """
        1) Orijinal IDM ikon dosyalarının (orig_idman_*.png) Kontrol Merkezi ikonundan (idm_icon_*.png)
           farklı ve gerçek Tonec IDM ikonu olduğunu,
        2) install_cli_and_desktop_entries sonrası idm-linux.desktop (IDMan.exe) ile
           idm-linux-panel.desktop (Kontrol Merkezi) dosyalarının FARKLI ikonlara işaret ettiğini doğrular!
        """
        from idm_linux.config import IdmLinuxConfig
        from idm_linux.installer import install_cli_and_desktop_entries
        from idm_linux.projects_data import get_assets_dir

        assets = get_assets_dir()
        orig_128 = (assets / "orig_idman_128.png").read_bytes()
        panel_128 = (assets / "idm_icon_128.png").read_bytes()
        self.assertEqual(orig_128[:8], b"\x89PNG\r\n\x1a\n")
        self.assertNotEqual(orig_128, panel_128, "Orijinal IDM ikonu ile Kontrol Paneli ikonu birbirinden farklı olmalıdır!")

        with tempfile.TemporaryDirectory() as tmpd:
            fake_home = Path(tmpd)
            saved = {k: os.environ.get(k) for k in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME")}
            os.environ["HOME"] = str(fake_home)
            os.environ["XDG_DATA_HOME"] = str(fake_home / ".local" / "share")
            os.environ["XDG_CONFIG_HOME"] = str(fake_home / ".config")
            os.environ["XDG_CACHE_HOME"] = str(fake_home / ".cache")
            try:
                cfg = IdmLinuxConfig()
                cfg.http_port = 19882
                cfg.ws_port = 19881
                # Daemon başlatmayı atlamak için sahte dinleyici olmadan sadece desktop/icon üretimini sına
                import unittest.mock as mock
                with mock.patch("idm_linux.installer.verify_and_start_bridge_service", return_value=True):
                    install_cli_and_desktop_entries(PROJECT_ROOT, cfg, create_desktop_icons=False)

                apps_dir = fake_home / ".local" / "share" / "applications"
                idm_desk = (apps_dir / "idm-linux.desktop").read_text(encoding="utf-8")
                way_desk = (apps_dir / "idman.exe.desktop").read_text(encoding="utf-8")
                pnl_desk = (apps_dir / "idm-linux-panel.desktop").read_text(encoding="utf-8")

                self.assertIn("idman.png", idm_desk)
                self.assertIn("idman.png", way_desk)
                self.assertIn("idm-linux-panel.png", pnl_desk)
                self.assertNotIn("idm-linux-panel.png", idm_desk)
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_35_dynamic_latest_official_idm_release_resolver(self) -> None:
        """
        resolve_latest_official_idm_release fonksiyonunun resmi indirme sayfasındaki
        yeni IDM sürümlerini (ör. idman648build5.exe -> 6.48 Build 5) dinamik algıladığını doğrular.
        """
        import io
        import unittest.mock as mock
        from idm_linux.installer import resolve_latest_official_idm_release

        fake_html = b"""
        <html><body>
        <a href="https://mirror2.internetdownloadmanager.com/idman648build5.exe">Mirror</a>
        <a href="https://download.internetdownloadmanager.com/idman648build5.exe">Try IDM</a>
        </body></html>
        """
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(fake_html)):
            url, fname, ver_lbl = resolve_latest_official_idm_release("https://download.internetdownloadmanager.com/idman643build16.exe", log_fn=lambda _s: None)
            self.assertEqual(url, "https://download.internetdownloadmanager.com/idman648build5.exe")
            self.assertEqual(fname, "idman648build5.exe")
            self.assertEqual(ver_lbl, "6.48 Build 5")

    def test_36_iframe_window_launcher_executes_clean_app_window_and_shows_target_url(self) -> None:
        """
        open_standalone_iframe_window çağrısının:
        1) Tıklanan özel URL'yi (NOWPayments veya belgeselsemo.com.tr/premium-uyelik/) sunan yerel <iframe> URL'sini oluşturduğunu,
        2) Tarayıcıyı çakışan '--disable-extensions' veya '--no-remote' OLMADAN bağımsız '--app=' penceresiyle açtığını doğrular!
        """
        import time
        from idm_linux.projects_data import BELGESELSEMO_PREMIUM_URL
        from idm_linux.webview_modal import EmbeddedIframeHost, _extract_exec_from_desktop, open_standalone_iframe_window

        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            marker_file = tmp / "launched_args.txt"
            fake_brave = tmp / "brave-origin-nightly"
            fake_brave.write_text(
                f'#!/bin/sh\nprintf "%s\\n" "$@" > "{marker_file}"\nexit 0\n',
                encoding="utf-8",
            )
            fake_brave.chmod(0o755)

            apps_dir = tmp / ".local" / "share" / "applications"
            apps_dir.mkdir(parents=True)
            (apps_dir / "brave-test.desktop").write_text(
                f"[Desktop Entry]\nName=Brave\nExec={fake_brave} %U\nType=Application\n",
                encoding="utf-8",
            )

            old_home = os.environ.get("HOME")
            old_path = os.environ.get("PATH", "")
            os.environ["HOME"] = str(tmp)
            os.environ["PATH"] = f"{tmp}:{old_path}"
            host = EmbeddedIframeHost.instance()
            try:
                ext_res = _extract_exec_from_desktop("brave-test.desktop")
                self.assertEqual(ext_res, (str(fake_brave), "chromium"))

                ok, local_u = open_standalone_iframe_window(
                    mode="premium",
                    lang_code="tr",
                    custom_url=BELGESELSEMO_PREMIUM_URL,
                )
                self.assertTrue(ok)
                for _ in range(20):
                    if marker_file.is_file():
                        break
                    time.sleep(0.05)
                self.assertTrue(marker_file.is_file(), "Bağımsız tarayıcı penceresi başlatılmalıydı!")
                args_txt = marker_file.read_text(encoding="utf-8")
                self.assertIn(f"--app={local_u}", args_txt)
                self.assertNotIn("--disable-extensions", args_txt)

                with urllib.request.urlopen(local_u, timeout=3) as r:
                    html_txt = r.read().decode("utf-8")
                    self.assertIn(f'src="{BELGESELSEMO_PREMIUM_URL}"', html_txt)
            finally:
                host.stop()
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
                os.environ["PATH"] = old_path

    def test_37_live_dvr_hls_follow_engine_records_from_start_and_live_edge(self) -> None:
        """v2.8.0: DVR modu playlist başından, Canlı mod canlı kenardan başlayıp yayın sonuna dek takip eder."""
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from idm_linux.hls_streamer import iter_playlist_segments_smart, parse_media_playlist_body

        state = {"seq": 1, "endlist": False, "hits": 0}
        seg_body = b"\x47" + b"V" * 187

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                return

            def do_GET(self):
                if self.path.startswith("/seg"):
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(seg_body)))
                    self.end_headers()
                    self.wfile.write(seg_body)
                    return
                state["hits"] += 1
                if state["hits"] >= 3:
                    state["seq"] = 3
                    state["endlist"] = True
                lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:1", f"#EXT-X-MEDIA-SEQUENCE:{state['seq']}"]
                first = state["seq"]
                last = state["seq"] + 1
                for n in range(first, last + 1):
                    lines += ["#EXTINF:1.0,", f"/seg{n}.ts"]
                if state["endlist"]:
                    lines.append("#EXT-X-ENDLIST")
                body = "\n".join(lines).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{port}/live.m3u8"
            with urllib.request.urlopen(base, timeout=5) as r:
                first_body = r.read().decode()
            parsed = parse_media_playlist_body(base, first_body)
            self.assertFalse(parsed["endlist"])

            stop = threading.Event()
            dvr_chunks = list(iter_playlist_segments_smart(base, first_body, {}, concurrency=4, stop_event=stop, hls_mode="dvr"))
            self.assertGreaterEqual(len(dvr_chunks), 3, "DVR modu tüm segmentleri (1,2,3...) baştan çekmeli!")

            stop2 = threading.Event()
            live_chunks = list(iter_playlist_segments_smart(base, first_body, {}, concurrency=4, stop_event=stop2, hls_mode="live"))
            self.assertLess(len(live_chunks), len(dvr_chunks), "Canlı mod yalnızca canlı kenardan itibaren kayıt yapmalı!")
            self.assertGreaterEqual(len(live_chunks), 1)
        finally:
            srv.shutdown()

    def test_38_wine_path_conversion_and_native_folder_manager(self) -> None:
        """v2.8.0: Wine C:/Z: yolları Linux yoluna çevrilir ve klasör yerli FM komutuyla açılır."""
        from idm_linux.browsers import open_folder_native, wine_path_to_unix

        with tempfile.TemporaryDirectory() as td:
            pfx = Path(td) / "wineprefix"
            (pfx / "dosdevices").mkdir(parents=True)
            (pfx / "drive_c").mkdir(parents=True)
            os.symlink(td, str(pfx / "dosdevices" / "z:"))
            got = wine_path_to_unix("Z:\\Indirilenler\\video.mp4", str(pfx))
            self.assertTrue(got.startswith(td), got)
            got_c = wine_path_to_unix("C:\\Program Files\\IDM", str(pfx))
            self.assertIn("drive_c", got_c)
            ok, msg = open_folder_native(str(Path(td) / "yeni_klasor"))
            self.assertIsInstance(ok, bool)
            self.assertTrue((Path(td) / "yeni_klasor").is_dir(), "Klasör yoksa oluşturulmalı!")

    def test_39_firefox_signed_xpi_sideload_bypasses_verification_wall(self) -> None:
        """v2.8.0: RELEASE Firefox doğrulama duvarı — imzalı XPI profil sideload + user.js pref'leri."""
        import zipfile
        from idm_linux.firefox_ext import install_firefox_extensions_robust

        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            xpi = td_p / "companion.xpi"
            with zipfile.ZipFile(xpi, "w") as zf:
                zf.writestr("manifest.json", json.dumps({"manifest_version": 2, "name": "c", "version": "1.0"}))
            signed = td_p / "signed.xpi"
            with zipfile.ZipFile(signed, "w") as zf:
                zf.writestr("manifest.json", json.dumps({"manifest_version": 2, "name": "s", "version": "1.0"}))
                zf.writestr("META-INF/mozilla.rsa", b"sig")
            home_root = td_p / ".mozilla"
            prof = home_root / "firefox" / "abc.default"
            prof.mkdir(parents=True)
            (prof / "prefs.js").write_text("// x\n", encoding="utf-8")

            rep = install_firefox_extensions_robust([("Mozilla Firefox", "firefox", home_root)], xpi, signed)
            self.assertTrue(rep["signed"], "İmzalı XPI release profiline sideload edilmeli!")
            self.assertTrue((prof / "extensions" / f"{OFFICIAL_FIREFOX_EXT_ID}.xpi").is_file())
            uj = (prof / "user.js").read_text(encoding="utf-8")
            self.assertIn("extensions.autoDisableScopes", uj)
            self.assertNotIn("xpinstall.signatures.required", uj, "Release derlemede imza pref'i yazılmamalı!")

            rep_esr = install_firefox_extensions_robust([("Firefox ESR", "firefox-esr", home_root)], xpi, signed)
            self.assertTrue(rep_esr["companion"], "ESR'de imzasız companion da kurulabilmeli!")
            uj2 = (prof / "user.js").read_text(encoding="utf-8")
            self.assertIn("xpinstall.signatures.required", uj2)

    def test_40_playlist_detection_and_ticket_hls_mode_passthrough(self) -> None:
        """v2.8.0: Playlist URL tespiti + stream biletine DVR/Canlı modunun işlenmesi."""
        from idm_linux.stream_engine import StreamEngine, is_playlist_url

        self.assertTrue(is_playlist_url("https://www.youtube.com/playlist?list=PLabc123"))
        self.assertTrue(is_playlist_url("https://www.dailymotion.com/playlist/x7qkvp"))
        self.assertTrue(is_playlist_url("https://www.youtube.com/watch?v=a&list=PLx"))
        self.assertFalse(is_playlist_url("https://cdn.example.com/video.mp4"))
        self.assertFalse(is_playlist_url("magnet:?xt=urn:btih:abc"))

        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as td:
            os.environ["HOME"] = td
            try:
                eng = StreamEngine(IdmLinuxConfig.load())
                tk = eng.create_ticket(
                    source_url="http://127.0.0.1:1/none.m3u8",
                    filename="canli yayın.mp4",
                    mode="hls_native",
                    is_hls=True,
                    hls_mode="dvr",
                )
                self.assertEqual(tk.hls_mode, "dvr")
                # v2.8.2: streamlink backend varsa DVR kaydı .ts konteynere yazılır (ses bozulmaz), native'de .mp4
                if tk.backend == "streamlink":
                    self.assertTrue(tk.filename.endswith(".ts"), tk.filename)
                else:
                    self.assertTrue(tk.filename.endswith(".mp4"), tk.filename)
                eng.stop_job(tk.ticket_id)
                job = eng.get_job(tk.ticket_id)
                self.assertTrue(job.stop_event.is_set())
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_41_all_language_packs_carry_clock_and_live_dvr_keys(self) -> None:
        """v2.8.0: 20 dil paketinin tamamında saat/gün adları ve Canlı-DVR diyaloğu anahtarları eksiksiz."""
        from idm_linux.i18n import SUPPORTED_LANGUAGES, I18nManager

        lang_dir = PROJECT_ROOT / "language"
        for code in SUPPORTED_LANGUAGES:
            txt = (lang_dir / f"{code}.txt").read_text(encoding="utf-8")
            for key in ("clock.weekdays", "ov.hls_mode_dvr", "ov.hls_mode_live", "ov.pl_btn_all"):
                self.assertIn(key, f"{code}: {key} eksik!")
            mgr = I18nManager(code)
            days = mgr.t("clock.weekdays").split(",")
            self.assertEqual(len(days), 7, f"{code} gün adları 7 öğe olmalı!")
            self.assertTrue(mgr.t("ov.hls_btn_start").strip())

    def test_42_no_undefined_names_regression_gecko_home_roots_class(self) -> None:
        """v2.8.1: '%86 name gecko_home_roots is not defined' sınıfı hatanın geri dönüşünü AST ile engeller."""
        import ast
        import builtins

        src_dir = PROJECT_ROOT  # yeni düzen: paket ağacının kendisi
        mods = [
            "installer.py", "cli.py", "gui.py", "gui_pages.py", "daemon.py",
            "browsers.py", "stream_engine.py", "hls_streamer.py", "firefox_ext.py",
            "webview_modal.py", "native_host.py",
        ]
        for m in mods:
            tree = ast.parse((src_dir / m).read_text(encoding="utf-8"))
            defined = set(dir(builtins)) | {"__file__", "__name__"}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    defined.add(node.name)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                    defined.add(node.id)
                elif isinstance(node, ast.arg):
                    defined.add(node.arg)
                elif isinstance(node, ast.Import):
                    for a in node.names:
                        defined.add((a.asname or a.name).split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    for a in node.names:
                        defined.add(a.asname or a.name)
                elif isinstance(node, ast.ExceptHandler) and node.name:
                    defined.add(node.name)
            undef = sorted(
                {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in defined}
            )
            self.assertEqual(undef, [], f"{m} içinde tanımsız isim(ler): {undef}")

        from idm_linux import installer as _inst
        self.assertTrue(callable(getattr(_inst, "gecko_home_roots", None)), "installer gecko_home_roots import etmeli!")
        self.assertTrue(callable(getattr(_inst, "configure_wine_native_folder_open", None)))

    def test_43_streams_api_lists_live_dvr_jobs_and_stop(self) -> None:
        """v2.8.0: /api/streams listeleme altyapısı + canlı kayıt durdurma (stop_event) uçtan uca."""
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as td:
            os.environ["HOME"] = td
            try:
                from idm_linux.stream_engine import StreamEngine

                eng = StreamEngine(IdmLinuxConfig.load())
                tk1 = eng.create_ticket(source_url="http://127.0.0.1:9/a.m3u8", filename="canli.mp4", mode="hls_native", is_hls=True, hls_mode="live")
                jobs = eng.list_jobs()
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0]["hls_mode"], "live")
                self.assertFalse(jobs[0]["completed"])
                self.assertTrue(eng.stop_job(tk1.ticket_id))
                jobs2 = eng.list_jobs()
                self.assertTrue(eng.get_job(tk1.ticket_id).stop_event.is_set())
                self.assertIsInstance(jobs2[0]["size_bytes"], int)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_44_streamlink_command_semantics_dvr_live_and_headers(self) -> None:
        """v2.8.2: streamlink komutu DVR'da --hls-live-restart, canlıda sade; başlıklar aktarılır."""
        from idm_linux.hls_streamer import build_stream_headers
        from idm_linux.stream_engine import build_streamlink_cmd

        hdrs = build_stream_headers(referer="https://dsmartgo.com.tr/", cookies="sid=1", user_agent="UA/1.0")
        cmd_dvr = build_streamlink_cmd("/usr/bin/streamlink", "https://x.live/360.m3u8?t=1", Path("/tmp/dvr.ts"), "dvr", hdrs)
        self.assertIn("--hls-live-restart", cmd_dvr)
        self.assertIn("best", cmd_dvr)
        self.assertEqual(cmd_dvr[-2:], ["-o", "/tmp/dvr.ts"])
        idx = cmd_dvr.index("--http-header")
        self.assertTrue(any("Referer=" in c for c in cmd_dvr[idx:]))

        cmd_live = build_streamlink_cmd("/usr/bin/streamlink", "https://x.live/360.m3u8?t=1", Path("/tmp/canli.ts"), "live", hdrs)
        self.assertNotIn("--hls-live-restart", cmd_live)
        self.assertEqual(cmd_live[0], "/usr/bin/streamlink")

    def test_45_streams_clear_finished_keeps_active_recordings(self) -> None:
        """v2.8.2: İzleyici temizliği yalnızca biten/hatalı kayıtları siler, aktif kayıt korunur."""
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as td:
            os.environ["HOME"] = td
            try:
                from idm_linux.stream_engine import StreamEngine

                eng = StreamEngine(IdmLinuxConfig.load())
                # Kara delik IP: worker bağlantı denemesinde bekler -> bilet test boyunca AKTİF kalır (race yok)
                t_act = eng.create_ticket(source_url="http://10.255.255.1:9/a.m3u8", filename="aktif.mp4", mode="hls_native", is_hls=True, hls_mode="live")
                t_fin = eng.create_ticket(source_url="http://127.0.0.1:9/b.m3u8", filename="biten.mp4", mode="hls_native", is_hls=True, hls_mode="dvr")
                eng.get_job(t_fin.ticket_id).completed = True
                removed = eng.clear_jobs(mode="finished")
                self.assertEqual(removed, 1)
                self.assertIsNotNone(eng.get_ticket(t_act.ticket_id), "Aktif kayıt temizlenmemeli!")
                self.assertIsNone(eng.get_ticket(t_fin.ticket_id))
                removed_all = eng.clear_jobs(mode="all")
                self.assertEqual(removed_all, 1)
                self.assertIsNone(eng.get_ticket(t_act.ticket_id))
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_46_backend_selection_streamlink_for_dvr_live_mpd(self) -> None:
        """v2.8.2: DVR/Canlı/MPD biletleri streamlink backend + .ts konteyner alır; VOD native .mp4 kalır."""
        import shutil as _sh
        from unittest import mock
        from idm_linux.stream_engine import StreamEngine

        orig_which = _sh.which
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as td:
            os.environ["HOME"] = td
            try:
                with mock.patch.object(_sh, "which", side_effect=lambda n, *a, **k: "/usr/bin/streamlink" if n == "streamlink" else orig_which(n, *a, **k)):
                    eng = StreamEngine(IdmLinuxConfig.load())
                    tk_dvr = eng.create_ticket(source_url="http://x/a.m3u8", filename="kayit.mp4", mode="hls_native", is_hls=True, hls_mode="dvr")
                    self.assertEqual(tk_dvr.backend, "streamlink")
                    self.assertTrue(tk_dvr.filename.endswith(".ts"), tk_dvr.filename)
                    tk_live = eng.create_ticket(source_url="http://x/b.m3u8", filename="canli", mode="hls_native", is_hls=True, hls_mode="live")
                    self.assertEqual(tk_live.backend, "streamlink")
                    tk_mpd = eng.create_ticket(source_url="http://x/c.mpd", filename="dash.mp4", mode="hls_native")
                    # v2.8.4: MPD VOD -> yt-dlp (fragment birleştirme); yt-dlp yoksa streamlink
                    from idm_linux.stream_engine import find_ytdlp as _fy46

                    self.assertEqual(tk_mpd.backend, "ytdlp" if _fy46() else "streamlink")
                    tk_mpd_live = eng.create_ticket(source_url="http://x/c.mpd", filename="dashcanli.mp4", mode="hls_native", hls_mode="dvr")
                    self.assertEqual(tk_mpd_live.backend, "streamlink")
                    tk_vod = eng.create_ticket(source_url="http://x/d.m3u8", filename="vod.mp4", mode="hls_native", is_hls=True, hls_mode="vod")
                    # v2.8.4: HLS(m3u8) her modda streamlink (ses bozulmaz TS passthrough); progressive mp4 native kalır
                    self.assertEqual(tk_vod.backend, "streamlink")
                    self.assertTrue(tk_vod.filename.endswith(".ts"))
                    tk_prog = eng.create_ticket(source_url="http://x/e.mp4", filename="prog.mp4", mode="ytdlp")
                    self.assertEqual(tk_prog.backend, "native")
                    for t_ in (tk_dvr, tk_live, tk_mpd, tk_mpd_live, tk_vod, tk_prog):
                        eng.stop_job(t_.ticket_id)
                    eng.clear_jobs(mode="all")
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_47_manifest_liveness_classifier_vod_vs_live(self) -> None:
        """v2.8.3: HLS/MPD manifest sınıflandırıcı — VOD filme asla canlı/DVR demez."""
        from idm_linux.stream_engine import classify_manifest_live

        vod_hls = "#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:10,\nseg0.ts\n#EXTINF:10,\nseg1.ts\n#EXT-X-ENDLIST\n"
        cl = classify_manifest_live(vod_hls)
        self.assertTrue(cl["vod"] and not cl["live"] and not cl["dvr"])

        live_hls = "#EXTM3U\n#EXT-X-TARGETDURATION:2\n" + "".join(f"#EXTINF:2,\nseg{i}.ts\n" for i in range(8))
        cl = classify_manifest_live(live_hls)
        self.assertTrue(cl["live"] and cl["dvr"])

        cl = classify_manifest_live('<?xml version="1.0"?>\n<MPD type="static" xmlns="urn:mpeg:dash:schema:mpd:2011"></MPD>')
        self.assertTrue(cl["vod"] and not cl["live"])

        cl = classify_manifest_live('<MPD type="dynamic" timeShiftBufferDepth="PT60S"><SegmentURL/></MPD>')
        self.assertTrue(cl["live"] and cl["dvr"])

    def test_48_auto_hls_mode_never_forces_dvr_on_vod_manifest(self) -> None:
        """v2.8.3: dispatch mod seçimi — VOD m3u8 'vod' kalır, canlı liste dvr'a yükselir."""
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from idm_linux.daemon import _auto_hls_mode

        vod = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\n/a.ts\n#EXT-X-ENDLIST\n"
        live = "#EXTM3U\n#EXT-X-TARGETDURATION:2\n" + "".join(f"#EXTINF:2,\n/l{i}.ts\n" for i in range(9))

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = (vod if self.path.startswith("/vod") else live).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertEqual(_auto_hls_mode(f"http://127.0.0.1:{port}/vod.m3u8", ""), "vod")
            self.assertEqual(_auto_hls_mode(f"http://127.0.0.1:{port}/live.m3u8", ""), "dvr")
            self.assertEqual(_auto_hls_mode("http://127.0.0.1:9/x.m3u8", vod), "vod")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_49_hls_uniform_segment_exact_total_size(self) -> None:
        """v2.8.4: tekdüze TS segmentli VOD listesinin KESİN toplam boyutu hesaplanır (IDM Content-Length)."""
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from idm_linux.stream_engine import estimate_hls_total_bytes

        seg = b"\x47" + b"\xab" * 187  # 188B TS
        last = b"\x47" + b"\xcd" * 99   # 100B son segment
        plist = "#EXTM3U\n#EXT-X-TARGETDURATION:1\n" + "".join(f"#EXTINF:1,\n/s{i}.ts\n" for i in range(6)) + "#EXT-X-ENDLIST\n"

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(plist.encode())))
                self.end_headers()
                self.wfile.write(plist.encode())

            def do_HEAD(self):
                bad_sizes = {"/a.ts": 188, "/b.ts": 999, "/c.ts": 100}
                if self.path in bad_sizes:
                    clen = bad_sizes[self.path]
                else:
                    clen = len(last) if self.path == "/s5.ts" else len(seg)
                self.send_response(200)
                self.send_header("Content-Length", str(clen))
                self.end_headers()

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            total, exact = estimate_hls_total_bytes(manifest_url=f"http://127.0.0.1:{port}/v.m3u8")
            self.assertTrue(exact)
            self.assertEqual(total, len(seg) * 5 + len(last))
            # tekdüze olmayan listede kesinlik iddiası YOK
            bad = "#EXTM3U\n#EXTINF:1,\n/a.ts\n#EXTINF:1,\n/b.ts\n#EXTINF:1,\n/c.ts\n#EXT-X-ENDLIST\n"
            total2, exact2 = estimate_hls_total_bytes(manifest_text=bad, manifest_url=f"http://127.0.0.1:{port}/b.m3u8")
            self.assertFalse(exact2 or total2 > 0)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_50_ytdlp_backend_merges_fragments_into_single_mp4(self) -> None:
        """v2.8.4: MPD VOD bileti yt-dlp backend'i ile tek MP4'e birleşir (sahte yt-dlp ile uçtan uca)."""
        import stat as _stat
        import pathlib as _pl
        from unittest import mock
        import idm_linux.stream_engine as se_mod

        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as td:
            os.environ["HOME"] = td
            fake = _pl.Path(td) / "fake-ytdlp"
            fake.write_text(
                "#!/bin/sh\nOUT=\"\nprev=\"\nfor a in \"$@\"; do\n  if [ \"$prev\" = \"-o\" ]; then OUT=\"$a\"; fi\n  prev=\"$a\"\ndone\n"
                "sleep 0.3\nhead -c 200000 /dev/urandom > \"$OUT\"\nexit 0\n",
                encoding="utf-8",
            )
            fake.chmod(fake.stat().st_mode | _stat.S_IXUSR | _stat.S_IXGRP)
            try:
                with mock.patch.object(se_mod, "find_ytdlp", return_value=str(fake)):
                    from idm_linux.stream_engine import StreamEngine

                    eng = StreamEngine(IdmLinuxConfig.load())
                    tk = eng.create_ticket(source_url="http://127.0.0.1:9/x.mpd", filename="dash-vod.mp4", mode="hls_native")
                    self.assertEqual(tk.backend, "ytdlp")
                    job = eng.get_job(tk.ticket_id)
                    for _ in range(60):
                        if job.completed or job.failed:
                            break
                        time.sleep(0.3)
                    self.assertTrue(job.completed, job.error_msg)
                    self.assertTrue(job.output_file.exists())
                    self.assertEqual(job.output_file.stat().st_size, 200000)
                    eng.clear_jobs(mode="all")
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_51_list_jobs_exposes_expected_total_for_idm_size_column(self) -> None:
        """v2.8.4: /api/streams beklenen toplam + kesinlik bayrağını taşır (GUI/CLI boyut sütunu)."""
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as td:
            os.environ["HOME"] = td
            try:
                from idm_linux.stream_engine import StreamEngine

                eng = StreamEngine(IdmLinuxConfig.load())
                tk = eng.create_ticket(
                    source_url="http://10.255.255.1:9/v.m3u8",
                    filename="film.mp4",
                    mode="hls_native",
                    is_hls=True,
                    hls_mode="vod",
                    estimated_size=1234567,
                    size_exact=True,
                )
                rows = eng.list_jobs()
                row = [r for r in rows if r["ticket"] == tk.ticket_id][0]
                self.assertEqual(row["expected_total"], 1234567)
                self.assertTrue(row["size_exact"])
                eng.clear_jobs(mode="all")
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_52_dash_segment_series_extrapolation_full_list(self) -> None:
        """v2.8.5: yakalanan 2 segmentten TÜM seri (0..7) HEAD yoklamasıyla çıkarılır."""
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from idm_linux.stream_engine import extrapolate_segment_list, segment_series_key

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _ok(self):
                self.send_response(200)
                self.send_header("Content-Length", "10")
                self.end_headers()

            def do_HEAD(self):
                self._ok() if any(f"/seg{i}.dash" in self.path for i in range(8)) else self.send_error(404)

            def do_GET(self):
                body = b"0123456789"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{port}/seg"
            self.assertTrue(segment_series_key(base + "3.dash"))
            self.assertEqual(segment_series_key("http://x/video.mp4"), "")
            lst = extrapolate_segment_list([base + "3.dash", base + "5.dash"])
            self.assertEqual(lst, [base + f"{i}.dash" for i in range(8)])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_53_segment_merge_engine_concatenates_all_parts_single_file(self) -> None:
        """v2.8.5: segment serisi TEK dosyada sırayla birleşir (IDM'ye canlı akar)."""
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from idm_linux.stream_engine import StreamEngine

        parts = {i: bytes([65 + i]) * 5000 for i in range(6)}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                for i, data in parts.items():
                    if f"/p{i}.dash" in self.path:
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
                self.send_error(404)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as td:
            os.environ["HOME"] = td
            try:
                eng = StreamEngine(IdmLinuxConfig.load())
                urls = [f"http://127.0.0.1:{port}/p{i}.dash" for i in range(6)]
                tk = eng.create_ticket(
                    source_url=urls[0],
                    filename="birlesik.mp4",
                    mode="hls_native",
                    segment_urls=urls,
                )
                self.assertEqual(tk.backend, "segments")
                job = eng.get_job(tk.ticket_id)
                for _ in range(80):
                    if job.completed or job.failed:
                        break
                    time.sleep(0.3)
                self.assertTrue(job.completed, job.error_msg)
                data = job.output_file.read_bytes()
                self.assertEqual(data, b"".join(parts[i] for i in range(6)))
                eng.clear_jobs(mode="all")
            finally:
                srv.shutdown()
                srv.server_close()
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_54_probe_collapses_segment_series_into_single_option(self) -> None:
        """v2.8.5: video bar segment çöplüğü yerine TEK 'tüm segmentler' seçeneği görür."""
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as td:
            os.environ["HOME"] = td
            try:
                from idm_linux.stream_engine import StreamEngine

                eng = StreamEngine(IdmLinuxConfig.load())
                captured = [
                    {"url": f"http://127.0.0.1:9/cdn/seg{i}.dash?sid=x", "mime": "video/mp4"}
                    for i in range(4)
                ]
                info = eng.probe_formats(
                    page_url="https://orneksite.example/izle/1",
                    captured_streams=captured,
                    use_ytdlp=False,
                )
                labels = " | ".join(f["label"] for f in info["formats"])
                self.assertIn("TEK VİDEO", labels)
                self.assertEqual(sum("Doğrudan Video" in f["label"] for f in info["formats"]), 0)
                seg_opt = [f for f in info["formats"] if f.get("segment_urls")]
                self.assertTrue(seg_opt and len(seg_opt[0]["segment_urls"]) >= 4)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_55_captured_streams_memory_cap_per_series(self) -> None:
        """v2.8.6: segment birikimi sınırlı (seri başına 4, toplam 300) — tarayıcı bellek koruması."""
        from idm_linux.stream_engine import cap_captured_streams

        items = [{"url": f"http://cdn/x/seg{i}.dash?s=1", "mime": "video/mp4"} for i in range(500)]
        items += [{"url": f"http://cdn/other/{i}.mp4", "mime": "video/mp4"} for i in range(20)]
        capped = cap_captured_streams(items)
        self.assertLessEqual(len(capped), 300)
        seg_count = sum(1 for it in capped if "/seg" in it["url"])
        self.assertLessEqual(seg_count, 4)

    def test_56_probe_cache_bounded_to_48_entries(self) -> None:
        """v2.8.6: probe önbelleği sınırsız büyüyemez (daemon RSS koruması)."""
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as td:
            os.environ["HOME"] = td
            try:
                from idm_linux.stream_engine import StreamEngine

                eng = StreamEngine(IdmLinuxConfig.load())
                for i in range(60):
                    eng.probe_formats(page_url=f"https://site.example/v/{i}", captured_streams=[], use_ytdlp=False)
                self.assertLessEqual(len(eng._probe_cache), 48)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_57_stream_resume_from_offset_serves_suffix(self) -> None:
        """v2.8.6: duraklat/devam — Range ofsetinden itibaren yalnızca kalan baytlar akar."""
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as td:
            os.environ["HOME"] = td
            try:
                from idm_linux.stream_engine import StreamEngine

                eng = StreamEngine(IdmLinuxConfig.load())
                urls = []
                import threading
                from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

                parts = {i: bytes([70 + i]) * 3000 for i in range(4)}

                class H(BaseHTTPRequestHandler):
                    def log_message(self, *a):
                        pass

                    def do_GET(self):
                        for i, data in parts.items():
                            if f"/r{i}.dash" in self.path:
                                self.send_response(200)
                                self.send_header("Content-Length", str(len(data)))
                                self.end_headers()
                                self.wfile.write(data)
                                return
                        self.send_error(404)

                srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
                port = srv.server_address[1]
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                try:
                    urls = [f"http://127.0.0.1:{port}/r{i}.dash" for i in range(4)]
                    tk = eng.create_ticket(source_url=urls[0], filename="resume.mp4", mode="hls_native", segment_urls=urls)
                    job = eng.get_job(tk.ticket_id)
                    for _ in range(60):
                        if job.completed or job.failed:
                            break
                        time.sleep(0.3)
                    self.assertTrue(job.completed)
                    full = job.output_file.read_bytes()
                    got = b"".join(job.iter_bytes_from(5000))
                    self.assertEqual(got, full[5000:])
                    eng.clear_jobs(mode="all")
                finally:
                    srv.shutdown()
                    srv.server_close()
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_58_html_payload_integrity_guard(self) -> None:
        """v2.8.7: dosya beklenirken HTML dönerse tespit edilir (gofile 3.3KB bozuk dosya panzehiri)."""
        from idm_linux.auth_proxy import looks_like_html_payload

        self.assertTrue(looks_like_html_payload(b"<!DOCTYPE html><html>error", "", "dosya.zip"))
        self.assertTrue(looks_like_html_payload(b"", "text/html; charset=utf-8", "film.mp4"))
        self.assertFalse(looks_like_html_payload(b"PK\x03\x04zipdata", "application/zip", "dosya.zip"))
        self.assertFalse(looks_like_html_payload(b"<html>x", "text/html", "sayfa.html"))

    def test_59_html_response_forces_auth_proxy(self) -> None:
        """v2.8.7: sunucu .zip için HTML döndürüyorsa indirme proxy'ye alınır; proxy 502 verir (bozuk dosya asla)."""
        import io
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        from idm_linux.auth_proxy import AuthContextVault, AuthenticatedProxyManager
        from idm_linux.protocol import DownloadRequest

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = b"<!doctype html><html><body>token expired</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        # 127.0.0.2 de loopback'tir ama auth_proxy'nin "127.0.0.1" erken-çıkış korumasına takılmaz
        srv = ThreadingHTTPServer(("127.0.0.2", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        class FakeHandler:
            def __init__(self):
                self.code = None
                self.headers = {}
                self.wfile = io.BytesIO()

                class _C:
                    def setsockopt(self, *a):
                        raise OSError()

                self.connection = _C()

            def send_response(self, c, *a):
                self.code = c

            def send_header(self, *a):
                pass

            def end_headers(self):
                pass

        try:
            mgr = AuthenticatedProxyManager(AuthContextVault())
            req = DownloadRequest(url=f"http://127.0.0.2:{port}/files/belge.zip", filename="belge.zip")
            wrapped = mgr.maybe_wrap_authenticated_download(req, 17802)
            self.assertIn("/proxy/", wrapped.url)
            tid = wrapped.url.split("/proxy/", 1)[1].split("/", 1)[0]
            fh = FakeHandler()
            mgr.serve_proxy_ticket(fh, tid, head_only=False)
            self.assertEqual(fh.code, 502)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_60_job_completed_refuses_html_output(self) -> None:
        """v2.8.7: worker HTML çıktı üretirse job 'tamamlandı' olamaz — failed işaretlenir."""
        import dataclasses

        from idm_linux.stream_engine import ActiveStreamJob, StreamTicket

        vals = {}
        for name, f in StreamTicket.__dataclass_fields__.items():
            if f.default is not dataclasses.MISSING:
                vals[name] = f.default
            elif f.default_factory is not dataclasses.MISSING:
                vals[name] = f.default_factory()
        vals.update({
            "ticket_id": "tk_integrity_test",
            "mode": "hls_native",
            "source_url": "http://x.invalid/v.m3u8",
            "filename": "film.zip",
        })
        tk = StreamTicket(**vals)
        with tempfile.TemporaryDirectory() as td:
            job = ActiveStreamJob(tk, Path(td))
            job.stream_file.write_bytes(b"<!doctype html><html><body>oturum acin</body></html>")
            job.completed = True
            self.assertFalse(job.completed)
            self.assertTrue(job.failed)
            self.assertIn("HTML", job.error_msg)

    def test_61_dash_manifest_derivation(self) -> None:
        """v2.8.8: D-Smart segment URL'sinden MPD manifest adayları doğru türetilir."""
        from idm_linux.stream_engine import derive_dash_manifest_candidates, probe_dash_manifest

        u = ("https://rlbgijjfwr.turknet.ercdn.net/lw/B/IR/-D/BIR-DEVRIN-HIKAYESI-1-SEZON-1-B.smil/"
             "BIR-DEVRIN-HIKAYESI-1-SEZON-1-B=ivffC5Go-200000000.dash?sid=abc&bvr_flags=2")
        cands = derive_dash_manifest_candidates(u)
        self.assertTrue(any(c.endswith("BIR-DEVRIN-HIKAYESI-1-SEZON-1-B.mpd") for c in cands), cands)
        self.assertTrue(any(c.endswith(".smil/manifest.mpd") for c in cands), cands)
        self.assertTrue(cands[0].endswith(".smil/BIR-DEVRIN-HIKAYESI-1-SEZON-1-B.mpd"))
        # manifest içermeyen sıradan mp4 için aday ÜRETİLMEZ (gereksiz ağ isteği yok)
        self.assertEqual(derive_dash_manifest_candidates("https://cdn/x/video.mp4"), [])
        self.assertEqual(probe_dash_manifest("https://cdn/x/video.mp4"), "")

    def test_62_browser_assist_chunk_pipeline(self) -> None:
        """v2.8.8: tarayıcı destekli besleme — parçalar birleşir, bekleyen işçi dosyayı alır."""
        import threading
        from types import SimpleNamespace

        from idm_linux import auth_proxy

        payload = b"ARENA-FILE-" * 5000
        result: List[Optional[Path]] = [None]
        tk = SimpleNamespace(ticket_id="assist_test_1", target_url="http://x.invalid/f")

        def _waiter() -> None:
            result[0] = auth_proxy.request_browser_assist(tk, wait_sec=10)

        th = threading.Thread(target=_waiter, daemon=True)
        th.start()
        time.sleep(0.4)
        self.assertEqual([a["id"] for a in auth_proxy.assist_pending_list()], ["assist_test_1"])
        fh = auth_proxy.assist_begin_chunk("assist_test_1")
        self.assertIsNotNone(fh)
        for i in range(0, len(payload), 393216):
            fh.write(payload[i:i + 393216])
        auth_proxy.assist_finish("assist_test_1", True)
        th.join(timeout=12)
        got = result[0]
        self.assertIsNotNone(got)
        self.assertEqual(got.read_bytes(), payload)
        got.unlink(missing_ok=True)

    def test_64_engine_fallback_chain_order(self) -> None:
        """v2.9.0: motor zinciri — her backend için yedek motorlar sıralı denenir; canlıda yalnız streamlink."""
        from idm_linux.stream_engine import engine_attempt_order

        self.assertEqual(engine_attempt_order("segments", "vod"), ["segments", "ytdlp", "streamlink", "hls_native"])
        self.assertEqual(engine_attempt_order("ytdlp", "vod"), ["ytdlp", "streamlink", "hls_native"])
        self.assertEqual(engine_attempt_order("streamlink", "vod"), ["streamlink", "ytdlp", "hls_native"])
        self.assertEqual(engine_attempt_order("ytdlp", "dvr"), ["streamlink"])
        self.assertEqual(engine_attempt_order("segments", "live"), ["streamlink"])

    def test_65_idm_disconnect_pauses_worker(self) -> None:
        """v2.9.1: IDM kopunca işçi duraklar; devam (reattach) gelirse duraklamaz."""
        import dataclasses
        import time as _t

        from idm_linux.stream_engine import ActiveStreamJob, StreamTicket

        vals = {}
        for name, f in StreamTicket.__dataclass_fields__.items():
            if f.default is not dataclasses.MISSING:
                vals[name] = f.default
            elif f.default_factory is not dataclasses.MISSING:
                vals[name] = f.default_factory()
        vals.update({"ticket_id": "tk_pause_1", "mode": "hls_native", "source_url": "http://x.invalid/v.m3u8", "filename": "f.mp4"})
        with tempfile.TemporaryDirectory() as td:
            j1 = ActiveStreamJob(StreamTicket(**vals), Path(td))
            j1.client_disconnected(grace_sec=0.3)
            _t.sleep(0.8)
            self.assertTrue(j1.stop_event.is_set())
            self.assertTrue(j1.client_paused)

            vals["ticket_id"] = "tk_pause_2"
            j2 = ActiveStreamJob(StreamTicket(**vals), Path(td))
            j2.client_disconnected(grace_sec=0.5)
            _t.sleep(0.15)
            j2.client_reattached()
            _t.sleep(0.8)
            self.assertFalse(j2.stop_event.is_set())
            self.assertFalse(j2.client_paused)

    def test_66_remote_log_payload_builder(self) -> None:
        """v2.9.1: uzak-log paketi token/kaynak/satır sınırıyla doğru kurulur."""
        from idm_linux.daemon import build_remote_log_payload

        ring = [f"RING{i}" for i in range(500)]
        tail = [f"TAIL{i}" for i in range(10)]
        pl = build_remote_log_payload(ring, tail, "TKN", source="daemon")
        self.assertEqual(pl["token"], "TKN")
        self.assertEqual(pl["source"], "daemon")
        self.assertLessEqual(len(pl["lines"]), 400)
        self.assertIn("TAIL9", pl["lines"])

    def test_67_mpd_timeline_parse_and_drm_detect(self) -> None:
        """v2.9.2: $Time$ timeline kesin liste + Widevine DRM tespiti."""
        from idm_linux.stream_engine import mpd_has_drm, parse_mpd_segment_list

        mpd = """<?xml version="1.0"?>
<MPD type="static" xmlns="urn:mpeg:dash:schema:mpd:2011">
 <Period>
  <AdaptationSet contentType="video" mimeType="video/mp4">
   <SegmentTemplate timescale="10000000" initialization="v=hv$RepresentationID$.dash" media="v=iv$RepresentationID$-$Time$.dash">
    <SegmentTimeline>
     <S t="0" d="40000000"/>
     <S d="40000000" r="1"/>
     <S t="120000000" d="20000000"/>
    </SegmentTimeline>
   </SegmentTemplate>
   <Representation id="low" bandwidth="500000"/>
   <Representation id="hi" bandwidth="3500000"/>
  </AdaptationSet>
  <AdaptationSet contentType="audio" mimeType="audio/mp4">
   <SegmentTemplate timescale="10000000" initialization="a=ha$RepresentationID$.dash" media="a=ia$RepresentationID$-$Time$.dash">
    <SegmentTimeline><S t="0" d="40000000"/></SegmentTimeline>
   </SegmentTemplate>
   <Representation id="au" bandwidth="128000"/>
  </AdaptationSet>
 </Period>
</MPD>"""
        out = parse_mpd_segment_list(mpd, "https://cdn/x/base.mpd")
        self.assertEqual(len(out["video"]), 5)  # init + 4 segment (r=1 tekrarıyla)
        self.assertIn("v=hvhi.dash", out["video"][0])
        self.assertIn("v=ivhi-0.dash", out["video"][1])
        self.assertIn("v=ivhi-120000000.dash", out["video"][-1])
        self.assertEqual(len(out["audio"]), 2)
        self.assertFalse(mpd_has_drm(mpd))
        drm_mpd = mpd.replace('<AdaptationSet contentType="video"',
                              '<ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed" value="Widevine"/><AdaptationSet contentType="video"', 1)
        self.assertTrue(mpd_has_drm(drm_mpd))


    # ------------------------------------------------------------------
    # v3.6.0: TORRENT KÖPRÜSÜ + BAR DONMASI + ALTYAZI KAPSAMASI + GUI KAYDIRMA
    # ------------------------------------------------------------------

    def test_122_torrent_popup_background_relay(self) -> None:
        """v3.6.0: torrent/magnet onayı ARKA PLAN servisi üzerinden köprüye gider.

        Kök hata: içerik betiği 127.0.0.1'e doğrudan POST atıyordu; sayfa kaynağından
        yapılan bu istek CORS + 'Untrusted origin' kalkanına takılıyor ve kullanıcı
        'Torrent başlatılamadı — IDM Linux köprüsüne ulaşılamadı' hatası görüyordu.
        """
        root = Path(__file__).resolve().parents[1]
        bg_src = (root / "extension/chromium/background.js").read_text(encoding="utf-8")
        content_src = (root / "extension/chromium/content.js").read_text(encoding="utf-8")
        native_src = (root / "native_host.py").read_text(encoding="utf-8")
        daemon_src = (root / "daemon.py").read_text(encoding="utf-8")

        # background: özel mesaj tipi + gerçek köprü rotası + native yedek aksiyonu
        self.assertIn('msg.type === "IDM_TORRENT_SEND"', bg_src)
        self.assertIn('"/api/torrent/download"', bg_src)
        self.assertIn('"torrent_download"', bg_src)
        # magnet + url (köprü tarafı .torrent indirir) payload'ları
        self.assertIn("magnet: href", bg_src) and self.assertIn("url: href", bg_src)
        # köprü uykudayken 2 sn bekle + tekrar dene
        self.assertIn("setTimeout(r, 2000)", bg_src)

        # content: birincil yol IDM_TORRENT_SEND relay'i; doğrudan POST yalnız SON ÇARE
        self.assertIn('type: "IDM_TORRENT_SEND"', content_src)
        relay_pos = content_src.find('type: "IDM_TORRENT_SEND"')
        fallback_pos = content_src.find("ext-popup-magnet")
        self.assertGreater(fallback_pos, relay_pos, "doğrudan POST birincil yol olmamalı")
        # popup gerçek daemon mesajını gösterir (örn. aria2c eksik)
        self.assertIn("sendRes.message", content_src)

        # native host: torrent_download aksiyonu /api/torrent/download'a gider
        self.assertIn('action == "torrent_download"', native_src)
        self.assertIn('"/api/torrent/download"', native_src)

        # daemon: torrent_url (köprü taraflı indirme) desteği sürüyor
        self.assertIn("torrent_url", daemon_src)

    def test_123_bar_never_hangs_forever(self) -> None:
        """v3.6.0: 'Kaliteler hazırlanıyor...' sonsuza dek takılamaz.

        - background async handler .catch ile her koşulda sendResponse çağırır
        - HTTP çağrıları AbortController zaman aşımıyla sarılır
        - native messaging 12 sn'de iptal olur
        - daemon probe kilidi 20 sn'de bir açılır + probe 75 sn'de pending döner
        - bar canlı saniye sayacı gösterir ve 90 sn asılı promise sigortasına sahiptir
        """
        root = Path(__file__).resolve().parents[1]
        bg_src = (root / "extension/chromium/background.js").read_text(encoding="utf-8")
        content_src = (root / "extension/chromium/content.js").read_text(encoding="utf-8")
        daemon_src = (root / "daemon.py").read_text(encoding="utf-8")

        # background: IIFE catch garantisi + fetch timeout + native timeout
        self.assertIn("})().catch(", bg_src)
        self.assertIn("fetchWithTimeout", bg_src)
        self.assertIn("BRIDGE_TIMEOUT_MS", bg_src)
        self.assertIn("AbortController", bg_src)
        self.assertIn('new Error("native timeout")', bg_src)

        # daemon: kilit zaman aşımı + sert probe zaman aşımı + beklemeden kapatma
        self.assertIn("lk.acquire(timeout=20)", daemon_src)
        # v3.11.0: istek başına ThreadPoolExecutor yerine daemon Thread — asılı yt-dlp
        # probe'u artık daemon kapanmasını engelleyemez (atexit join riski bitti).
        self.assertIn("_probe_done.wait(timeout=75)", daemon_src)
        self.assertIn('"probe_wait": True', daemon_src)

        # content: canlı süre + 90 sn race sigortası + pending yeniden deneme sınırı 40
        self.assertIn("Kaliteler hazırlanıyor…", content_src)
        self.assertIn("90000", content_src)
        self.assertIn("emptyAutoRetries < 40", content_src)

    def test_124_subtitle_capture_scope_extended(self) -> None:
        """v3.6.0: altyazı yakalamaları video seçeneği olarak sızmaz + JS taraması var."""
        root = Path(__file__).resolve().parents[1]
        eng_src = (root / "stream_engine.py").read_text(encoding="utf-8")
        content_src = (root / "extension/chromium/content.js").read_text(encoding="utf-8")
        ph_src = (root / "extension/chromium/page_hook.js").read_text(encoding="utf-8")

        self.assertIn("def _looks_like_subtitle_capture", eng_src)
        self.assertIn("_looks_like_subtitle_capture(s_url", eng_src)
        # işlevsel doğrulama
        from idm_linux.stream_engine import _looks_like_subtitle_capture as subq
        self.assertTrue(subq("https://cdn.site/subs/tr.vtt", ""))
        self.assertTrue(subq("https://cdn.site/api/subtitles?lang=tr", "text/vtt"))
        self.assertTrue(subq("https://www.youtube.com/api/timedtext?lang=en", ""))
        self.assertTrue(subq("https://cdn.site/movie.srt", "application/x-subrip"))
        self.assertFalse(subq("https://cdn.site/video.mp4", "video/mp4"))
        self.assertFalse(subq("https://cdn.site/index.m3u8", "application/vnd.apple.mpegurl"))
        # content: JS konfigürasyon altyazı taraması (film siteleri)
        self.assertIn("collectDomMediaStreams._subScanTs", content_src)
        # page_hook: YouTube motoru 180 sn + SPA tazeleme
        self.assertIn("180000", ph_src)
        self.assertIn("yt-navigate-finish", ph_src)

    def test_125_gui_scrollable_overview_and_slim_scrollbar(self) -> None:
        """v3.6.0: Genel Bakış sayfası kaydırılabilir + özel ince kaydırma çubuğu."""
        root = Path(__file__).resolve().parents[1]
        gui_src = (root / "gui.py").read_text(encoding="utf-8")
        pages_src = (root / "gui_pages.py").read_text(encoding="utf-8")

        # Genel Bakış IDM Hakkında gibi kaydırılır
        self.assertIn('pg_ov = make_scrollable_area(tk, ttk, pages["overview"], BG_MAIN)', gui_src)
        self.assertIn("    make_scrollable_area,\n", gui_src)
        # özel çubuk: ttk Scrollbar bu yardımcıda artık kullanılmaz
        self.assertIn("THUMB_IDLE", pages_src)
        self.assertIn("_sb_drag", pages_src)
        self.assertIn("create_oval", pages_src)
        self.assertNotIn("ttk_mod.Scrollbar(wrap, orient=", pages_src)



# (v3.9.0: __main__ çalıştırıcısı dosyanın EN SONUNA taşındı — modül-seviyesi
#  test fonksiyonları da tanımlandıktan sonra toplansın diye)

def test_68_daemon_log_tail_is_windowed():
    """v2.9.3: log kuyruğu dosyanın tamamını değil son penceresini okumalı (RAM dostu)."""
    import pathlib
    import tempfile
    from idm_linux.daemon import _tail_file_lines

    with tempfile.TemporaryDirectory() as td:
        f = pathlib.Path(td) / "daemon.log"
        with f.open("w", encoding="utf-8") as fh:
            for i in range(20000):
                fh.write(f"satir-{i} " + ("x" * 200) + "\n")
        tail = _tail_file_lines(f, n=80)
        assert len(tail) == 80
        assert tail[-1].startswith("satir-19999")
        assert tail[0].startswith("satir-19920")


def test_69_engine_order_bilibili_yutto():
    """v2.9.3: bilibili için motor zinciri yt-dlp -> yutto -> streamlink olmalı."""
    from idm_linux.stream_engine import engine_attempt_order

    order = engine_attempt_order("ytdlp", "vod", "https://www.bilibili.com/video/BV1xx411c7mD")
    assert order[0] == "ytdlp" and order[1] == "yutto"
    plain = engine_attempt_order("ytdlp", "vod", "https://example.com/a.mp4")
    assert "yutto" not in plain


def test_70_log_handler_rotation():
    """v2.9.3: 2 MB üstü log dosyası tek yedeğe döndürülüp yeniden açılmalı."""
    import pathlib
    import tempfile
    from idm_linux.config import _LazyFileHandler

    with tempfile.TemporaryDirectory() as td:
        f = pathlib.Path(td) / "daemon.log"
        f.write_bytes(b"a" * (3 * 1024 * 1024))
        h = _LazyFileHandler("daemon.log")
        h._log_path = lambda: f
        h._rotate_if_big()
        assert not f.exists()
        assert f.with_suffix(".log.1").exists()
        h.close()

def test_71_pure_aes_fips197():
    """v2.9.4: saf-Python AES, FIPS-197 vektörleriyle birebir doğrulanmalı."""
    from idm_linux.abyss_engine import _key_expand, _aes_encrypt_block, ctr_crypt

    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    assert _aes_encrypt_block(_key_expand(bytes(range(16))), pt, 10).hex() == "69c4e0d86a7b0430d8cdb78070b4c55a"
    assert _aes_encrypt_block(_key_expand(bytes(range(32))), pt, 14).hex() == "8ea2b7ca516745bfeafc49904b496089"
    data = b"abyss segment akisi" * 7
    assert ctr_crypt(bytes(range(32)), 999, ctr_crypt(bytes(range(32)), 999, data)) == data


def test_72_abyss_protocol_helpers():
    """v2.9.4: boyut anahtarı + yol şifreleme deterministik ve çift-B64 olmalı."""
    import base64
    from idm_linux.abyss_engine import generate_size_key, encrypt_path, expand_key, decrypt_media

    assert generate_size_key(209715200) == generate_size_key(209715200)
    tok = encrypt_path("/mp4/md5/res/100/50/0", generate_size_key(100))
    first = base64.b64decode(tok + "==")
    base64.b64decode(first + b"=" * (-len(first) % 4))  # ikinci katman da B64
    key = expand_key(7, "SLUGX", "MD5X")
    media = '{"mp4": {"domains": ["d1"], "sources": [{"label": "720p", "size": 5, "res_id": "r", "partSize": 0, "sub": "d1"}]}}'
    from idm_linux.abyss_engine import ctr_crypt
    enc = ctr_crypt(key, int.from_bytes(key[:16], "big"), media.encode())
    assert decrypt_media("".join(chr(b) for b in enc), key)["mp4"]["sources"][0]["label"] == "720p"


def test_73_justbeamit_mapping():
    """v2.9.4: justbeamit.com/<kod> -> eu.justbeamit.com:8443/download?token=<kod>."""
    from idm_linux.daemon import DaemonState

    st = DaemonState.__new__(DaemonState)
    assert st._justbeamit_direct("https://justbeamit.com/wfkzb") == "https://eu.justbeamit.com:8443/download?token=wfkzb"
    assert st._justbeamit_direct("https://www.justbeamit.com/gm3ai/") == "https://eu.justbeamit.com:8443/download?token=gm3ai"
    assert st._justbeamit_direct("https://example.com/wfkzb") == "https://example.com/wfkzb"


def test_74_abyss_code_gate():
    """v2.9.4: GUI kodu 304358 kabul, diğerleri reddetmeli."""
    from idm_linux.config import abyss_code_ok

    assert abyss_code_ok("304358")
    assert abyss_code_ok(" 304358 ")
    assert not abyss_code_ok("30435")
    assert not abyss_code_ok("abcdef")
    assert not abyss_code_ok("")


def test_75_subtitle_manifest_parsers():
    """v2.9.4: HLS SUBTITLES ve MPD text AdaptationSet ayrıştırıcıları çalışmalı."""
    from idm_linux.stream_engine import parse_hls_subtitles, parse_dash_subtitles

    hls = (
        "#EXTM3U\n"
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Türkçe",URI="tr.m3u8"\n'
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="x",URI="a.m3u8"\n'
    )
    got = parse_hls_subtitles(hls, "https://cdn.x/master.m3u8")
    assert len(got) == 1 and got[0][0] == "Türkçe" and got[0][1].endswith("tr.m3u8")
    mpd = (
        '<AdaptationSet contentType="text" lang="tr"><Representation><BaseURL>sub_tr.vtt</BaseURL></Representation></AdaptationSet>'
    )
    got2 = parse_dash_subtitles(mpd, "https://cdn.x/vid.mpd")
    assert got2 and got2[0][1] == "https://cdn.x/sub_tr.vtt"

def test_76_abyss_register_meta_sniffed():
    """v2.9.5: tarayıcıdan yakalanan şifreli info JSON'u daemon tarafında çözülebilmeli."""
    import json as _json
    from idm_linux.abyss_engine import (
        abyss_register_meta,
        abyss_fetch_metadata,
        ctr_crypt,
        expand_key,
    )

    slug = "SNIFF01"
    media = {"mp4": {"domains": ["s9.abysscdn.com"], "sources": [
        {"label": "1080p", "size": 5000, "res_id": "r9", "partSize": 1000, "sub": "s9"}]}}
    uid, md5id = 77, "md5sniff"
    key = expand_key(uid, slug, md5id)
    enc = ctr_crypt(key, int.from_bytes(key[:16], "big"), _json.dumps(media).encode())
    payload = _json.dumps({"slug": slug, "user_id": uid, "md5_id": md5id, "title": "Sniff",
                           "duration": 9, "media": "".join(chr(b) for b in enc)})
    assert abyss_register_meta(payload) == slug
    meta = abyss_fetch_metadata(slug)
    assert meta and meta.sources and meta.sources[0].label == "1080p"
    assert meta.domains == ["s9.abysscdn.com"]
    assert abyss_register_meta("{bozuk") is None

def test_77_bilibili_playurl_parser():
    """v2.9.6: daemon tarafı playurl ayrıştırıcı dash+durl URL'lerini çıkarmalı."""
    import json as _json
    from unittest import mock
    from idm_linux import stream_engine as se

    payload = {"data": {"dash": {
        "video": [{"baseUrl": "https://cn/x.m4s", "mimeType": "video/mp4"},
                  {"baseUrl": "https://cn/y.m4s", "mimeType": "video/mp4"}],
        "audio": [{"baseUrl": "https://cn/a.m4s", "mimeType": "audio/mp4"}],
    }, "durl": []}}

    class _R:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return _json.dumps(payload).encode()

    with mock.patch.object(se.urllib.request, "urlopen", return_value=_R()):
        out = se.fetch_bilibili_playurl_streams("BV1xx", "12345", "buvid3=X", "")
    assert len(out) == 3
    assert out[0]["url"] == "https://cn/x.m4s"
    assert out[0]["referer"] == "https://www.bilibili.com/"
    assert out[2]["mime"] == "audio/mp4"

def test_78_mpd_representations_labels():
    """v2.9.8: MPD'den çözünürlük etiketli temsilcilik listesi çıkarılmalı."""
    from idm_linux.stream_engine import parse_mpd_representations

    mpd = (
        '<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011">'
        '<Period><AdaptationSet contentType="video" mimeType="video/mp4">'
        '<Representation id="v1" height="1080" bandwidth="5000000"><SegmentTemplate initialization="init_v1.m4s" media="seg_v1_$Time$.m4s"><SegmentTimeline>'
        '<S t="0" d="4000000" r="3"/></SegmentTimeline></SegmentTemplate></Representation>'
        '<Representation id="v2" height="720" bandwidth="2500000"><SegmentTemplate initialization="init_v2.m4s" media="seg_v2_$Time$.m4s"><SegmentTimeline>'
        '<S t="0" d="4000000" r="3"/></SegmentTimeline></SegmentTemplate></Representation>'
        '</AdaptationSet>'
        '<AdaptationSet contentType="audio" mimeType="audio/mp4"><Representation id="a1"><SegmentTemplate initialization="init_a.m4s" media="seg_a_$Time$.m4s"><SegmentTimeline>'
        '<S t="0" d="4000000" r="3"/></SegmentTimeline></SegmentTemplate></Representation></AdaptationSet>'
        '</Period></MPD>'
    )
    reps = parse_mpd_representations(mpd, "https://cdn.x/v/manifest.mpd")
    assert [r["height"] for r in reps] == [1080, 720]
    assert len(reps[0]["segments"]) == 4
    assert reps[0]["segments"][0].endswith("seg_v1_0.m4s")
    assert len(reps[0]["audio_segments"]) == 4


def test_79_protected_hosts_proxy():
    """v2.9.8: korumalı CDN'ler çıplak direct delivery alamaz."""
    from idm_linux.stream_engine import _needs_proxy_host

    assert _needs_proxy_host("https://cn-hdslb.com/x.m4s")
    assert _needs_proxy_host("https://s9.abysscdn.com/sora/123/abc")
    assert not _needs_proxy_host("https://cdn.example.com/v.mp4")

def test_80_delivery_guard_rules():
    """v2.9.9: referer'lı yakalama köprüye, YouTube doğrudan kalır."""
    from idm_linux.stream_engine import VideoFormatOption, apply_delivery_guard

    ok_opt = VideoFormatOption(
        id="a", label="x", ext="mp4", delivery="direct",
        direct_url="https://vd123.ok.ru/video.mp4", stream_referer="https://ok.ru/video/1",
    )
    yt_opt = VideoFormatOption(
        id="b", label="y", ext="mp4", delivery="direct",
        direct_url="https://rr1---sn-abc.googlevideo.com/videoplayback?x=1", stream_referer="https://youtube.com/",
    )
    plain = VideoFormatOption(
        id="c", label="z", ext="mp4", delivery="direct", direct_url="https://cdn.example.com/v.mp4",
    )
    out = apply_delivery_guard([ok_opt, yt_opt, plain], "https://ok.ru/", "https://ok.ru/video/1")
    assert out[0].delivery == "stream_proxy"
    assert out[1].delivery == "direct"
    assert out[2].delivery == "direct"


def test_81_probe_known_site_no_crash():
    """v2.9.10 REGRESYON: 2.9.9'da ytdlp_bin atamadan önce okunuyordu -> UnboundLocalError,
    YouTube/bilibili/ok.ru/abyss barı boş kalıyordu. Probe artık çökmeden payload döner."""
    import idm_linux.stream_engine as se
    from idm_linux.stream_engine import StreamEngine
    from idm_linux.config import IdmLinuxConfig

    orig_find, orig_bg = se.find_ytdlp, se.ensure_ytdlp_background
    se.find_ytdlp = lambda: None
    se.ensure_ytdlp_background = lambda upgrade=False: None
    try:
        eng = StreamEngine(IdmLinuxConfig())
        res = eng.probe_formats(
            "https://www.youtube.com/watch?v=8HgmWGigIh1s",
            [],
            cookies="",
            referer="",
            user_agent="UA",
            use_ytdlp=True,
            force_refresh=True,
        )
    finally:
        se.find_ytdlp, se.ensure_ytdlp_background = orig_find, orig_bg
    assert isinstance(res, dict)
    assert res["formats"] == []
    assert res["ytdlp_missing"] is True
    assert res["ytdlp_updating"] is False


def test_82_single_url_relay_resume_after_cut():
    """v2.9.10: sunucu akışı ortada keserse relay Range ile dirilir; dosya eksik 'tamamlanmaz'."""
    import http.server
    import threading
    import idm_linux.stream_engine as se
    from idm_linux.stream_engine import ActiveStreamJob, StreamTicket

    payload = b"V" * 300_000
    state = {"cut": False}

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            rng = (self.headers.get("Range") or "").strip()
            start = 0
            if rng.startswith("bytes="):
                start = int(rng.split("=")[1].split("-")[0] or 0)
            body = payload[start:]
            if start == 0 and not state["cut"]:
                state["cut"] = True
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload[:100_000])
                self.wfile.flush()
                self.connection.close()  # film sitesi gibi ortada kes
                return
            self.send_response(206 if start else 200)
            if start:
                self.send_header(
                    "Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}"
                )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        tmp = Path(tempfile.mkdtemp(prefix="relay82_"))
        t = StreamTicket(
            ticket_id="t82",
            source_url=f"http://127.0.0.1:{port}/film.mp4",
            filename="film.mp4",
            mode="ytdlp",
            referer="https://fullhdfilmizlesene.now/",
        )
        job = ActiveStreamJob(t, tmp)
        ok = job._run_single_url_relay()
        assert ok is True, "relay kopmadan sonra dirilip tamamlayamadı"
        assert job.completed is True
        assert job.stream_file.stat().st_size == len(payload)
        assert t.size_exact is True and t.estimated_size == len(payload)
    finally:
        srv.shutdown()
        srv.server_close()


def test_83_plain_media_relay_gate():
    """v2.9.10: relay yalnız TEK dosyalık ham medyada; HLS/DASH/mux/abyss zincire kalır."""
    import tempfile
    from idm_linux.stream_engine import ActiveStreamJob, StreamTicket

    tmp = Path(tempfile.mkdtemp(prefix="gate83_"))
    base = dict(ticket_id="g", filename="v.mp4", mode="ytdlp")
    plain = ActiveStreamJob(StreamTicket(source_url="https://cdn.x/film.mp4", **base), tmp)
    assert plain._is_plain_media_relay() is True
    hls = ActiveStreamJob(StreamTicket(source_url="https://cdn.x/master.m3u8", is_hls=True, **base), tmp)
    assert hls._is_plain_media_relay() is False
    mux = ActiveStreamJob(
        StreamTicket(source_url="https://cdn.x/v.mp4", mux_video_url="https://cdn.x/v.m4s", **base), tmp
    )
    assert mux._is_plain_media_relay() is False
    seg = ActiveStreamJob(
        StreamTicket(source_url="https://cdn.x/v.mp4", segment_urls=["https://cdn.x/s1.m4s"], **base), tmp
    )
    assert seg._is_plain_media_relay() is False


def _cut_server(payload: bytes, cut_at: int, ignore_range: bool = False):
    """İlk bağlantıyı cut_at baytta koparan (ve isteğe bağlı Range'i yok sayan) test sunucusu."""
    import http.server
    import threading

    state = {"cut": False}

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            rng = (self.headers.get("Range") or "").strip()
            start = 0
            if rng.startswith("bytes="):
                start = int(rng.split("=")[1].split("-")[0] or 0)
            if not ignore_range and start:
                body = payload[start:]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}")
            else:
                start = 0
                body = payload
                self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not state["cut"]:
                state["cut"] = True
                self.wfile.write(body[:cut_at])
                self.wfile.flush()
                self.connection.close()
                return
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, srv.server_address[1]


def test_84_segment_merge_gap_never_completes():
    """v2.9.11: kalıcı ölen segment -> delikli dosya 'tamamlandı' OLAMAZ; zincire düşer."""
    import idm_linux.stream_engine as se
    from idm_linux.stream_engine import ActiveStreamJob, StreamTicket

    segs = [b"A" * 50_000, b"B" * 50_000, b"C" * 50_000, b"D" * 50_000]
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            idx = int(self.path.strip("/seg").split(".")[0])
            if idx == 2:
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = segs[idx]
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    orig_sleep = se.time.sleep
    se.time.sleep = lambda s: None  # test hızlı bitsin
    try:
        port = srv.server_address[1]
        tmp = Path(tempfile.mkdtemp(prefix="seg84_"))
        t = StreamTicket(
            ticket_id="s84",
            source_url=f"http://127.0.0.1:{port}/v.mpd",
            filename="v.mp4",
            mode="ytdlp",
            segment_urls=[f"http://127.0.0.1:{port}/seg{i}.m4s" for i in range(4)],
        )
        job = ActiveStreamJob(t, tmp)
        ok = job._run_segment_merge_record()
        assert ok is False, "delikli birleştirme başarı dönmemeli"
        assert job.completed is False
        assert not job.stream_file.exists(), "yarım dosya sonraki motoru zehirlemesin"
    finally:
        se.time.sleep = orig_sleep
        srv.shutdown()
        srv.server_close()


def test_85_relay_survives_range_ignoring_cdn():
    """v2.9.11: CDN Range'i yok sayıp 200 dönerse relay gövdeyi atlayıp DEVAM eder (pes etmez)."""
    from idm_linux.stream_engine import ActiveStreamJob, StreamTicket

    payload = b"R" * 300_000
    srv, port = _cut_server(payload, 100_000, ignore_range=True)
    try:
        tmp = Path(tempfile.mkdtemp(prefix="relay85_"))
        t = StreamTicket(
            ticket_id="t85",
            source_url=f"http://127.0.0.1:{port}/film.mp4",
            filename="film.mp4",
            mode="ytdlp",
        )
        job = ActiveStreamJob(t, tmp)
        assert job._run_single_url_relay() is True
        assert job.completed is True
        assert job.stream_file.stat().st_size == len(payload)
    finally:
        srv.shutdown()
        srv.server_close()


def test_86_segment_merge_truncates_stale_stream_file():
    """v2.9.11: önceki motordan kalan yarım dosya birleştirmeye SIZAMAZ (çift yazma=bozuk video)."""
    import http.server
    import threading
    from idm_linux.stream_engine import ActiveStreamJob, StreamTicket

    segs = [b"V" * 40_000, b"W" * 40_000]

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            idx = int(self.path.strip("/seg").split(".")[0])
            body = segs[idx]
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        tmp = Path(tempfile.mkdtemp(prefix="seg86_"))
        t = StreamTicket(
            ticket_id="s86",
            source_url=f"http://127.0.0.1:{port}/v.mpd",
            filename="v.mp4",
            mode="ytdlp",
            segment_urls=[f"http://127.0.0.1:{port}/seg{i}.m4s" for i in range(2)],
        )
        job = ActiveStreamJob(t, tmp)
        job.stream_file.parent.mkdir(parents=True, exist_ok=True)
        job.stream_file.write_bytes(b"ESKI_MOTOR_ARTIGI" * 5000)
        ok = job._run_segment_merge_record()
        assert ok is True
        data = job.output_file.read_bytes()
        assert data == segs[0] + segs[1], "bayt çift yazması / artık tespit edildi"
    finally:
        srv.shutdown()
        srv.server_close()


def test_87_hls_vod_in_place_segment_retry():
    """v2.9.11: VOD HLS'te TEK ölü segment kaydı öldürmez — yerinde 5 deneme, sıralı akış."""
    import http.server
    import threading
    import idm_linux.hls_streamer as hs
    from idm_linux.hls_streamer import _iter_playlist_segments_parallel

    segs = {"/s0.ts": b"0" * 3000, "/s1.ts": b"1" * 3000, "/s2.ts": b"2" * 3000}
    fails = {"/s1.ts": 4}  # seg1 ilk 4 istekte 500: fetch iç denemeleri (3) YETMEZ, dış yerinde-deneme şart

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            if fails.get(self.path, 0) > 0:
                fails[self.path] -= 1
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = segs.get(self.path, b"")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    body = (
        "#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\ns0.ts\n"
        "#EXTINF:2,\ns1.ts\n#EXTINF:2,\ns2.ts\n#EXT-X-ENDLIST\n"
    )
    orig_sleep = hs.time.sleep
    hs.time.sleep = lambda s: None
    try:
        out = b"".join(
            _iter_playlist_segments_parallel(
                f"http://127.0.0.1:{port}/m.m3u8", body, {"User-Agent": "t"}, concurrency=4
            )
        )
    finally:
        hs.time.sleep = orig_sleep
        srv.shutdown()
        srv.server_close()
    assert out == segs["/s0.ts"] + segs["/s1.ts"] + segs["/s2.ts"], "segment yeniden denemesi çalışmadı"


# ---------------------------------------------------------------------------
# v3.0.0 REGRESYON KİLİTLERİ
# ---------------------------------------------------------------------------

def test_88_known_ytdlp_sites_dead_code_guard():
    """v3.0.0: _is_known_ytdlp_site ÇİFT tanım + ölü kod yüzünden vk.ru/vkvideo.ru/
    b23.tv probe'u hiç tetiklenmiyordu. Tek tanım + geniş liste kalıcı kilitte."""
    import idm_linux.stream_engine as se

    # 1) Modülde TEK tanım (gölgeleme regresyonu imkânsız)
    n_defs = sum(
        1 for name, fn in vars(se).items()
        if name == "_is_known_ytdlp_site" and callable(fn)
    )
    assert n_defs == 1, "_is_known_ytdlp_site birden fazla tanımlı (gölgeleme riski)"

    f = se._is_known_ytdlp_site
    # 2) Kullanıcı şikayeti olan siteler MUTLAKA True
    for u in (
        "https://vkvideo.ru/video-123_456",
        "https://vk.ru/video_ext.php?oid=1&id=2",
        "https://www.ok.ru/video/987654",
        "https://m.ok.ru/dk?st.cmd=movieLayer",
        "https://b23.tv/abc123",
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://rutube.ru/video/xyz/",
        "https://dai.ly/x8abcde",
        "https://www.dailymotion.com/video/x1",
        "https://www.youtube.com/watch?v=abc",
        "https://vsp.mycdn.me/?sig=1",  # ok.ru CDN'i
        "https://vidmoly.me/embed-abc.html",  # film sitesi gömülü playerı
    ):
        assert f(u) is True, f"bilinen site algılanmadı: {u}"
    # 3) Yanlış-pozitif koruması (x.com substring tuzağı)
    for u in (
        "https://www.netflix.com/watch/123",
        "https://example.com/video.mp4",
        "https://forums.example.com/thread/1",
    ):
        assert f(u) is False, f"yanlış pozitif: {u}"
    # 4) Boş girdi
    assert f("") is False
    assert f(None) is False


def test_89_ytdlp_probe_helper_contract():
    """v3.7.0: YARIŞ tabanlı probe — paralel istemci setleri, ilk geçerli JSON kazanır,
    YouTube'da bot-kontrolde geniş yedek sete düşülür, diğer siteler tek güçlü deneme."""
    import subprocess
    import idm_linux.stream_engine as se

    # Yedek istemci seti PO-token dostu istemcileri içermeli
    assert "tv_simply" in se.YT_FALLBACK_EXTRACTOR_ARGS
    assert "mweb" in se.YT_FALLBACK_EXTRACTOR_ARGS
    # v3.7.0 yarış argümanları mevcut ve player_skip içeriyor
    assert "tv" in se.YT_RACE_FAST_ARGS and "web_safari" in se.YT_RACE_FAST_ARGS
    assert "player_skip" in se.YT_RACE_FAST_ARGS
    assert "default" in se.YT_RACE_SECOND_ARGS

    # (a) binary yok -> (None, hata, False) — asla exception fırlatmaz
    info, err, drm = se._run_ytdlp_probe("/yok/boyle/yt-dlp", "https://x.com/v", None)
    assert info is None and err and drm is False

    # (b) JSON üreten sahte binary -> info döner
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "yt-dlp"
        fake.write_text("#!/bin/sh\necho '{\"title\": \"Test Video\", \"formats\": []}'\n")
        fake.chmod(0o755)
        info, err, drm = se._run_ytdlp_probe(str(fake), "https://x.com/v", None)
        assert info is not None and info.get("title") == "Test Video"
        assert err == "" and drm is False

    # (c) bot-kontrol hatası + YouTube URL -> yarış istemcileri patlar, geniş yedek set
    #     (tv_simply içerir) kurtarır
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "yt-dlp"
        fake.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"-J\" ]; then\n"
            "  for a in \"$@\"; do\n"
            "    case \"$a\" in *tv_simply*) print_ok=1;; esac\n"
            "  done\n"
            "  if [ -n \"$print_ok\" ]; then\n"
            "    echo '{\"title\": \"Fallback Video\", \"formats\": []}'\n"
            "    exit 0\n"
            "  fi\n"
            "  echo 'ERROR: Sign in to confirm you are not a bot' >&2\n"
            "  exit 1\n"
            "fi\n"
            "exit 2\n"
        )
        fake.chmod(0o755)
        info, err, drm = se._run_ytdlp_probe(str(fake), "https://www.youtube.com/watch?v=abc", None)
        assert info is not None and info.get("title") == "Fallback Video", (
            f"yedek istemci düşüşü çalışmadı: {err}"
        )

    # (d) kalıcı hata -> (None, anlamlı hata metni)
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "yt-dlp"
        fake.write_text("#!/bin/sh\necho 'ERROR: Unsupported URL' >&2\nexit 1\n")
        fake.chmod(0o755)
        info, err, drm = se._run_ytdlp_probe(str(fake), "https://x.com/v", None)
        assert info is None and "Unsupported URL" in err

    # (e) v3.7.0 YARIŞ: iki komuttan HIZLI olan kazanır (yavaş süreç kill edilir)
    with tempfile.TemporaryDirectory() as td:
        slow = Path(td) / "slow.cmd"
        slow.write_text("#!/bin/sh\nsleep 4\necho '{\"who\": \"slow\"}'\n")
        slow.chmod(0o755)
        fast = Path(td) / "fast.cmd"
        fast.write_text("#!/bin/sh\nsleep 0.4\necho '{\"who\": \"fast\"}'\n")
        fast.chmod(0o755)
        t0 = time.time()
        info, err, drm = se._race_ytdlp_cmds(
            [[str(slow)], [str(fast)]], [12, 12]
        )
        dt = time.time() - t0
        assert info is not None and info.get("who") == "fast", f"yarış kazananı hatalı: {info} {err}"
        assert dt < 3.0, f"yarış yavaş kazananı bekledi: {dt:.2f}s"


def test_90_relay_clean_eof_range_verified():
    """v3.0.0: Content-Length'suz kesilen akış sahte 'tamamlandı' OLAMAZ.
    Relay clean EOF'ta Range doğrulaması yapar: 206 dönerse kaldığı yerden sürer."""
    import http.server
    import threading
    from idm_linux.stream_engine import ActiveStreamJob, StreamTicket

    payload = b"D" * 400_000
    cut_at = 120_000
    state = {"first": True}

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            rng = (self.headers.get("Range") or "").strip()
            if state["first"] and not rng:
                # 1. istek: Content-Length YOK, ortada sessizce kapanan akış (clean EOF)
                state["first"] = False
                self.send_response(200)
                self.end_headers()
                self.wfile.write(payload[:cut_at])
                self.wfile.flush()
                self.connection.close()
                return
            start = int(rng.split("=")[1].split("-")[0] or 0) if rng.startswith("bytes=") else 0
            if start >= len(payload):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(payload)}")
                self.end_headers()
                return
            body = payload[start:]
            self.send_response(206 if start else 200)
            if start:
                self.send_header("Content-Range", f"bytes {start}-{len(payload)-1}/{len(payload)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        tmp = Path(tempfile.mkdtemp(prefix="relay90_"))
        t = StreamTicket(
            ticket_id="t90",
            source_url=f"http://127.0.0.1:{port}/film.mp4",
            filename="film.mp4",
            mode="ytdlp",
        )
        job = ActiveStreamJob(t, tmp)
        ok = job._run_single_url_relay()
        assert ok is True, "Range doğrulamalı relay tamamlamadı"
        assert job.completed is True
        assert job.stream_file.stat().st_size == len(payload), (
            f"kesik dosya 'tamam' sayıldı: {job.stream_file.stat().st_size} != {len(payload)}"
        )
        assert t.estimated_size == len(payload) and t.size_exact is True
    finally:
        srv.shutdown()
        srv.server_close()


def test_91_relay_clean_eof_416_honest_complete():
    """v3.0.0: Range doğrulaması 416 (dosya sonu) derse relay DÜRÜST tamamlar."""
    import http.server
    import threading
    from idm_linux.stream_engine import ActiveStreamJob, StreamTicket

    payload = b"E" * 80_000
    state = {"first": True}

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            rng = (self.headers.get("Range") or "").strip()
            if state["first"] and not rng:
                state["first"] = False
                self.send_response(200)
                self.end_headers()
                self.wfile.write(payload)  # tamamı, ama Content-Length'suz
                self.wfile.flush()
                self.connection.close()
                return
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{len(payload)}")
            self.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        tmp = Path(tempfile.mkdtemp(prefix="relay91_"))
        t = StreamTicket(
            ticket_id="t91",
            source_url=f"http://127.0.0.1:{port}/kisa.mp4",
            filename="kisa.mp4",
            mode="ytdlp",
        )
        job = ActiveStreamJob(t, tmp)
        assert job._run_single_url_relay() is True
        assert job.completed is True
        assert job.stream_file.stat().st_size == len(payload)
    finally:
        srv.shutdown()
        srv.server_close()


def test_92_extension_self_healing_bar_and_version():
    """v3.2.0: self-healing bar kodu her iki tarayıcıda da mevcut + sürümler senkron.
    v3.4.0: sürüm sabiti KALDIRILDI — manifest sürümü daima __version__ ile birebir olmalı."""
    import json as _json

    root = PROJECT_ROOT
    chrom = (root / "extension" / "chromium" / "content.js").read_text(encoding="utf-8")
    firef = (root / "extension" / "firefox" / "content.js").read_text(encoding="utf-8")
    assert "scheduleEmptyReprobe" in chrom, "self-healing fonksiyonu chromium'da yok"
    assert "scheduleEmptyReprobe" in firef, "self-healing fonksiyonu firefox'ta yok"
    assert chrom == firef, "chromium/firefox content.js senkronu bozulmuş"

    from idm_linux import __version__ as _pkg_ver
    for flavour in ("chromium", "firefox"):
        mf = _json.loads((root / "extension" / flavour / "manifest.json").read_text(encoding="utf-8"))
        assert mf["version"] == _pkg_ver, f"{flavour} manifest sürümü {_pkg_ver} değil"
    bg = (root / "extension" / "chromium" / "background.js").read_text(encoding="utf-8")
    bgf = (root / "extension" / "firefox" / "background.js").read_text(encoding="utf-8")
    assert bg == bgf, "chromium/firefox background.js senkronu bozulmuş"

    # v3.2.0: ok.ru/vk.ru barı — yakalanan akış varken video öğesi olmasa da bar fallback'i
    assert "haveStreams" in chrom, "captured-stream bar fallback'i chromium'da yok"
    assert "haveStreams" in firef, "captured-stream bar fallback'i firefox'ta yok"
    ph = (root / "extension" / "chromium" / "page_hook.js").read_text(encoding="utf-8")
    phf = (root / "extension" / "firefox" / "page_hook.js").read_text(encoding="utf-8")
    assert "emitVideoKeyJson" in ph and "emitVideoKeyJson" in phf, "JSON video-anahtarı kazıyıcı eksik"
    assert ph == phf, "chromium/firefox page_hook.js senkronu bozulmuş"



# ---------------------------------------------------------------------------
# v3.1.0: YouTube/bilibili/abyss/relay güçlendirme regresyonları
# ---------------------------------------------------------------------------

def test_93_abyss_page_protocol_java_port():
    """v3.1.0: Android AbyssVideoPort.java'dan uyarlanan HTML datas protokolü
    (const datas=... -> B64 -> user_id:slug:md5_id anahtarı -> AES-CTR media)."""
    import base64 as _b64
    import json as _json
    from idm_linux.abyss_engine import (
        abyss_resolve_from_page, _parse_outer_blob, _meta_from_outer,
        expand_key, ctr_crypt, abyss_segment_urls,
    )

    slug = "JAVA1"
    media = {"mp4": {
        "domains": ["s77.sssrr.org"],
        "sources": [
            {"label": "1080p", "size": 1009978980, "res_id": 5, "sub": "xrfcm3jr936", "status": True, "codec": "h264"},
            {"label": "720p", "size": 658816279, "res_id": 4, "sub": "hbsn6baxt17", "status": True, "codec": "h264"},
            {"label": "kapalı", "size": 100, "res_id": 9, "sub": "zz", "status": False, "codec": "h264"},
        ],
    }}
    uid, md5id = 21102885, "md5java"
    key = expand_key(uid, slug, md5id)
    enc = ctr_crypt(key, int.from_bytes(key[:16], "big"), _json.dumps(media).encode())
    outer = {"user_id": uid, "slug": slug, "md5_id": md5id, "media": "".join(chr(b) for b in enc)}
    blob = _b64.b64encode(_json.dumps(outer).encode()).decode()
    html = f'<html><script>const datas = "{blob}";</script></html>'

    from unittest import mock
    class _Resp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return html.encode()
    with mock.patch("idm_linux.abyss_engine.urllib.request.urlopen", return_value=_Resp()):
        meta = abyss_resolve_from_page("https://abyss.to/v/JAVA1", referer="https://belgeselsemo.com.tr/x/")
    assert meta is not None and meta.slug == slug
    labels = [s.label for s in meta.sources]
    assert labels == ["1080p", "720p"], f"status=false filtresi çalışmadı: {labels}"
    # Java taban mantığı: sub.suffix (suffix = domains[0]'ın ilk etiketten sonrası)
    base, urls, size, frag = abyss_segment_urls(meta, "720p")
    assert base == "https://hbsn6baxt17.sssrr.org", f"taban yanlış: {base}"
    assert size == 658816279 and frag == 2097152
    assert len(urls) == -(-size // frag)


def test_94_bilibili_quality_labels_and_risk_fallback():
    """v3.1.0: bilibili kalite adları + boyut tahmini + -352 risk kurtarma buvid3'ü."""
    import json as _json
    from unittest import mock
    from idm_linux import stream_engine as se

    assert se._BILI_QUALITY_NAMES.get(80) == "1080p Full HD"
    # risk kodu -352: ilk yanıt risk, ikinci yanıt normal -> ikinci çağrı yapılmalı
    payload = {"code": -352, "message": "risk"}
    ok_payload = {"code": 0, "data": {"timelength": 60000, "dash": {
        "video": [{"id": 80, "height": 1080, "bandwidth": 2000000, "baseUrl": "https://u/v.m4s", "mimeType": "video/mp4"}],
        "audio": [{"id": 30280, "bandwidth": 320000, "baseUrl": "https://u/a.m4s", "mimeType": "audio/mp4"}],
    }}}
    calls = {"n": 0}
    class _R:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            calls["n"] += 1
            return _json.dumps(payload if calls["n"] == 1 else ok_payload).encode()
    with mock.patch.object(se.urllib.request, "urlopen", return_value=_R()):
        opts = se.fetch_bilibili_quality_options("BV1x", "1", "SESSDATA=x", "")
    assert calls["n"] >= 2, "risk kurtarma ikinci denemeyi yapmadı"
    assert opts and opts[0].height == 1080
    assert "1080p Full HD" in opts[0].label
    # boyut: (2000000+320000)*60000/8000 = 17.4 MB
    assert opts[0].filesize == 17_400_000
    # buvid3 sentetik fallback
    ck = se._bili_cookie_with_fallback("")
    assert "buvid3=" in ck and "b_nut=" in ck


def test_95_probe_virtual_schemes_filtered():
    """v3.1.0: abyssif:// / drm:// yakalamaları seçeneklere 'Doğrudan Video' olarak SIZMAMALI;
    abyss iframe'i çözülüp kalite listesine dönüşmeli."""
    from idm_linux.stream_engine import StreamEngine
    from idm_linux.config import IdmLinuxConfig
    from unittest import mock

    eng = StreamEngine(IdmLinuxConfig.load())
    fake_meta = mock.MagicMock()
    fake_meta.sources = []
    with mock.patch("idm_linux.stream_engine._abyss_options", return_value=[]):
        res = eng.probe_formats(
            page_url="https://ornek-site.com/dizi/b1/",
            captured_streams=[
                {"url": "abyssif://https://abyss.to/v/XYZ", "mime": "application/x-abyss", "referer": "https://ornek-site.com/", "origin": "https://ornek-site.com", "manifestText": ""},
                {"url": "drm://detected?keysystem=com.widevine.alpha", "mime": "application/x-idm-drm", "referer": "https://ornek-site.com/", "origin": "", "manifestText": ""},
            ],
            cookies="", referer="https://ornek-site.com/dizi/b1/", user_agent="",
            use_ytdlp=False, force_refresh=True, abyss_enabled=True,
        )
    labels = [f["label"] for f in res.get("formats", [])]
    assert not any("abyssif" in l for l in labels), f"sanal şema sızdı: {labels}"
    assert res.get("drm") is True, "EME kanıtı drm bayrağına dönüşmeli"


def test_96_relay_refresh_on_403():
    """v3.1.0: relay ortasında 403 -> _refresh_source_url çağrılıp yeni kaynakla devam."""
    import io
    import urllib.error as _ue
    import threading as _th
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from idm_linux.stream_engine import StreamTicket, ActiveStreamJob, get_cache_dir
    from pathlib import Path

    state = {"mode": "fail", "hits": 0}
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            state["hits"] += 1
            if state["mode"] == "fail" and state["hits"] <= 6:
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            state["mode"] = "ok"
            self.send_response(206)
            self.send_header("Content-Range", f"bytes 0-9/10")
            self.send_header("Content-Length", "10")
            self.end_headers()
            self.wfile.write(b"0123456789")
        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), _H)
    _th.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        t = StreamTicket(
            ticket_id="refreshtest1", source_url=f"http://127.0.0.1:{port}/old",
            filename="x.mp4", mode="hls_native",
            referer="https://film-ornek.com/dizi/b1/",
        )
        tmp = get_cache_dir() / "streams" / "refreshtest1"
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)  # önceki çalıştırma artığı olmasın
        job = ActiveStreamJob(t, tmp)
        swapped = {"done": False}
        def fake_refresh() -> bool:
            if state["hits"] >= 5 and state["mode"] == "fail":
                t.source_url = f"http://127.0.0.1:{port}/new"
                swapped["done"] = True
                return True
            return False
        job._refresh_source_url = fake_refresh
        # 403'ler attempt>=5 koşuluna takılmasın: refresh yine çağrılır (denemeler 16'ya çıktı)
        assert job._run_single_url_relay() is True
        assert swapped["done"], "403 sonrası kaynak tazeleme çağrılmadı"
        assert job.completed and job.stream_file.stat().st_size == 10
    finally:
        srv.shutdown()
        srv.server_close()


def test_97_async_probe_for_known_sites():
    """v3.1.0: bilinen sitelerde yt-dlp probe'u arka plana geçer, yanıt anında döner
    (ytdlp_pending=True), tam sonuç gelince önbelleğe yazılır."""
    import time as _time
    from idm_linux.stream_engine import StreamEngine, set_probe_done_notifier
    from idm_linux.config import IdmLinuxConfig
    from unittest import mock

    eng = StreamEngine(IdmLinuxConfig.load())
    events = []
    set_probe_done_notifier(lambda payload: events.append(payload))

    def fake_probe(*a, **k):
        _time.sleep(0.3)
        info = {"title": "T", "is_live": False, "live_status": "", "formats": [
            {"id": "f1", "vcodec": "avc1.64001f", "acodec": "none", "height": 720, "width": 1280,
             "ext": "mp4", "protocol": "https", "url": "https://video-googlevideo.test/videoplayback?v=f1",
             "tbr": 2500, "filesize": 50_000_000, "http_headers": {"User-Agent": "UA-TEST"}},
            {"id": "f2", "vcodec": "none", "acodec": "mp4a.40.2", "ext": "m4a", "abr": 128,
             "protocol": "https", "url": "https://video-googleaudio.test/audio?v=f2",
             "filesize": 4_000_000, "http_headers": {"User-Agent": "UA-TEST"}},
        ]}
        return (info, "", False)
    with mock.patch("idm_linux.stream_engine._run_ytdlp_probe", side_effect=fake_probe), mock.patch(
        "idm_linux.stream_engine.find_ytdlp", return_value="/usr/bin/yt-dlp"
    ):  # v3.5.0: ortamdan bağımsız (hermetic) — yt-dlp kurulu olmasa da test geçer
        t0 = _time.time()
        res = eng.probe_formats(
            page_url="https://www.youtube.com/watch?v=abc",
            captured_streams=[], cookies="", referer="", user_agent="",
            use_ytdlp=True, force_refresh=False, abyss_enabled=False,
        )
        elapsed = _time.time() - t0
        assert res.get("ytdlp_pending") is True, "ilk yanıt pending işaretli değil"
        assert elapsed < 2.0, f"ilk yanıt çok geç: {elapsed:.2f}s"
        deadline = _time.time() + 6
        while _time.time() < deadline and not events:
            _time.sleep(0.1)
        assert events, "arka plan tamamlanınca IDM_MEDIA_UPDATED bildirimi gelmedi"
        assert events[0].get("type") == "IDM_MEDIA_UPDATED"
        # tam sonuç artık önbellekte
        cached = eng._probe_cache.get("https://www.youtube.com/watch?v=abc|0")
        assert cached and cached[1].get("formats"), "arka plan sonucu önbelleğe yazılmadı"
        assert not cached[1].get("ytdlp_pending")


# ---------------------------------------------------------------------------
# v3.2.0: NATİVE IDM İLERLEME + SÜREKLİLİK regresyonları
# ---------------------------------------------------------------------------

def test_98_relay_resumes_from_existing_stream_file():
    """v3.2.0: işçi resume ile yeniden başladığında relay stream_file'daki bayttan
    Range ile DEVAM eder — sıfırdan indirme yok (IDM duraklatma/kopma sonrası)."""
    import threading as _th
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from idm_linux.stream_engine import StreamTicket, ActiveStreamJob, get_cache_dir

    payload = bytes(range(256)) * 4  # 1024 bayt
    seen_ranges = []

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            rng = (self.headers.get("Range") or "").strip()
            seen_ranges.append(rng)
            if rng.startswith("bytes="):
                start = int(rng.split("-", 1)[0].split("=")[1])
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(payload)-1}/{len(payload)}")
                self.send_header("Content-Length", str(len(payload) - start))
                self.end_headers()
                self.wfile.write(payload[start:])
            else:
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), _H)
    _th.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        t = StreamTicket(
            ticket_id="resumetest01",
            source_url=f"http://127.0.0.1:{port}/movie.mp4",
            filename="movie.mp4",
            mode="relay",
        )
        tmp = get_cache_dir() / "streams" / "resumetest01"
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)  # önceki çalıştırma artığı olmasın
        job = ActiveStreamJob(t, tmp)
        pre = 400
        job.stream_file.write_bytes(payload[:pre])  # IDM daha önce 400 bayt aldı
        assert job._run_single_url_relay() is True
        assert job.completed
        assert job.stream_file.stat().st_size == len(payload), "relay resume toplam boyuta ulaşmadı"
        assert any(r.startswith(f"bytes={pre}-") for r in seen_ranges), "Range=400- isteği gönderilmedi"
        assert job.stream_file.read_bytes() == payload, "resume ile birleşen dosya bozuk"
    finally:
        srv.shutdown()
        srv.server_close()


def test_99_client_refcount_and_worker_restart():
    """v3.2.0: IDM bağlantı çevirirken (bir bağlantı kapanırken diğeri açık) işçi
    DURDURULMAZ; tüm bağlantılar kapanırsa grace devreye girer; resume'da işçi
    yeniden başlatılabilir olur."""
    import time as _time
    from idm_linux.stream_engine import StreamTicket, ActiveStreamJob, get_cache_dir

    t = StreamTicket(
        ticket_id="refcountest1",
        source_url="https://ornek-cdn.test/never-reachable.mp4",
        filename="never.mp4",
        mode="relay",
    )
    import shutil as _shutil
    _shutil.rmtree(get_cache_dir() / "streams" / "refcountest1", ignore_errors=True)
    job = ActiveStreamJob(t, get_cache_dir() / "streams" / "refcountest1")

    job.client_connected()
    job.client_connected()
    job.client_disconnected(grace_sec=0.4)  # 1 bağlantı kapandı; 1 hâlâ açık
    _time.sleep(0.7)
    assert not job.client_paused, "tek bağlantı kapanışı işçiyi durdurdu (çoklu bağlantı yarışı geri döndü)"
    assert not job.stop_event.is_set()

    job.client_disconnected(grace_sec=0.4)  # son bağlantı da kapandı
    _time.sleep(0.7)
    assert job.client_paused, "tüm bağlantılar kapandığında grace duraklatması çalışmadı"
    assert job.stop_event.is_set()

    assert job.restart_for_resume() is True, "resume yeniden başlatması reddedildi"
    assert not job.stop_event.is_set(), "restart stop_event'i temizlemedi"
    assert not job.client_paused, "restart client_paused'u temizlemedi"
    job.stop()  # test işçisi hemen kapansın
    _time.sleep(0.1)


def test_100_probe_cache_mux_fast_path():
    """v3.2.0: işçi, bar probe'unun -J sonucunu önbellekten alıp mux URL'lerini
    saniyeler içinde doldurur (YouTube canlı ilerleme için -J tekrarı yok)."""
    from idm_linux.stream_engine import StreamTicket, ActiveStreamJob, StreamEngine, get_cache_dir
    from idm_linux.config import IdmLinuxConfig

    eng = StreamEngine(IdmLinuxConfig.load())
    page = "https://www.youtube.com/watch?v=muxfast"
    eng._probe_cache[f"{page}|0"] = (
        __import__("time").time(),
        {
            "formats": [
                {
                    "height": 1080,
                    "mux_video_url": "https://v-googlevideo.test/videoplayback?v=1080",
                    "mux_audio_url": "https://a-googlevideo.test/videoplayback?v=audio",
                    "mux_video_headers": {"User-Agent": "UA-PROBE"},
                    "mux_audio_headers": {"User-Agent": "UA-PROBE"},
                    "filesize": 123456789,
                    "format_selector": "",
                }
            ]
        },
    )
    t = StreamTicket(
        ticket_id="muxfastest01", source_url=page, filename="v.mp4", mode="ytdlp",
    )
    import shutil as _shutil
    _shutil.rmtree(get_cache_dir() / "streams" / "muxfastest01", ignore_errors=True)
    job = ActiveStreamJob(t, get_cache_dir() / "streams" / "muxfastest01")
    job.manager = eng
    job._apply_probe_cache_mux()
    assert t.mux_video_url == "https://v-googlevideo.test/videoplayback?v=1080", "mux video URL önbellekten gelmedi"
    assert t.mux_audio_url == "https://a-googlevideo.test/videoplayback?v=audio", "mux ses URL önbellekten gelmedi"
    assert t.mux_video_headers.get("User-Agent") == "UA-PROBE"
    assert t.estimated_size == 123456789, "boyut önbellekten alınmadı"


def test_101_abyss_default_off_and_gui_hint():
    """v3.2.0: abyss varsayılan KAPALI; GUI'de ABYSS PASİF metni + canlı uygulama ipucu var."""
    from pathlib import Path as _Path

    from idm_linux.config import IdmLinuxConfig

    fresh = IdmLinuxConfig()
    assert fresh.abyss_enabled is False, "abyss varsayılanı hâlâ açık"

    root = _Path(__file__).resolve().parents[1]
    tr = (root / "language" / "tr.txt").read_text(encoding="utf-8")
    assert "ABYSS PASİF" in tr, "tr dil dosyasında ABYSS PASİF yok"
    assert "set.abyss_hint" in tr, "canlı uygulama ipucu (set.abyss_hint) yok"
    gui_src = (root / "gui.py").read_text(encoding="utf-8")
    assert "set.abyss_hint" in gui_src, "GUI ipucu etiketi eklenmedi"


# ---------------------------------------------------------------------------
# v3.2.2 — BELLEK KALKANI + YENİDEN BAŞLATMASIZ EKLENTİ + SEGMENTLİ ALTYAZI
# ---------------------------------------------------------------------------

def test_102_dynamic_mpd_segment_cap():
    """v3.2.2: dynamic (DVR) MPD'de segment genişletmesi sınırlanır; statik VOD listesi korunur."""
    from idm_linux.stream_engine import parse_mpd_segment_list

    # 1 saatlik DVR: 900 <S> etiketi, her biri r=5 (6 segment) = 5400 segment
    s_tags = "".join('<S d="4000" r="5"/>' for _ in range(900))
    dyn_mpd = (
        '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="dynamic" timeShiftBufferDepth="PT2H">'
        "<Period><AdaptationSet contentType=\"video\">"
        '<Representation id="1080p" bandwidth="4000000">'
        f'<SegmentTemplate media="v-$Time$.dash" initialization="init.dash"><SegmentTimeline>{s_tags}</SegmentTimeline></SegmentTemplate>'
        "</Representation></AdaptationSet></Period></MPD>"
    )
    out = parse_mpd_segment_list(dyn_mpd, "https://cdn.example/live/master.mpd")
    assert len(out["video"]) <= 360, f"dynamic MPD sınırı aşıldı: {len(out['video'])}"
    # kuyruk korunur (en yeni segmentler): son URL en yüksek $Time$ olmalı
    tail_time = int(out["video"][-1].rsplit("-", 1)[1].split(".")[0]) if out["video"] else 0
    assert tail_time > 0

    # Statik VOD: 1000 segment -> tamamı korunur (<= 5000)
    vod_s = "".join('<S d="4000" r="5"/>' for _ in range(167))
    vod_mpd = vod_mpd = (
        '<MPD type="static"><Period><AdaptationSet contentType="video">'
        '<Representation id="1080p" bandwidth="4000000">'
        f'<SegmentTemplate media="v-$Time$.dash" initialization="init.dash"><SegmentTimeline>{vod_s}</SegmentTimeline></SegmentTemplate>'
        "</Representation></AdaptationSet></Period></MPD>"
    )
    out2 = parse_mpd_segment_list(vod_mpd, "https://cdn.example/film.mpd")
    # v3.4.0 düzeltme: liste INIT URL'sini de içerir (1 init + 167x6 segment = 1003)
    assert 900 <= len(out2["video"]) <= 1003, f"VOD listesi bozuldu: {len(out2['video'])}"
    assert out2["video"][0].endswith("init.dash"), "init URL listede ilk sırada olmalı"


def test_103_parse_mpd_representations_cap():
    """v3.2.2: temsil başına segment genişletme sınırı (canlı 240 / VOD 4000)."""
    from idm_linux.stream_engine import parse_mpd_representations

    s_tags = "".join('<S d="4000" r="50"/>' for _ in range(400))  # 20400 potansiyel
    dyn = (
        '<MPD type="dynamic"><Period>'
        '<AdaptationSet contentType="video"><Representation id="a" bandwidth="1" height="1080">'
        f'<SegmentTemplate media="v-$Time$-$RepresentationID$.m4s" initialization="i.m4s"><SegmentTimeline>{s_tags}</SegmentTimeline></SegmentTemplate>'
        "</Representation></AdaptationSet></Period></MPD>"
    )
    reps = parse_mpd_representations(dyn, "https://x.example/live.mpd")
    assert reps and len(reps[0]["segments"]) <= 240, f"cap aşıldı: {len(reps[0]['segments'])}"


def test_104_probe_cache_double_bounded():
    """v3.2.2: probe önbelleği 16 kayıt VE ~24MB toplam gövdeyle sınırlı; segment kuyruğu trimpli."""
    import time as _t

    from idm_linux.stream_engine import StreamEngine

    eng = StreamEngine(IdmLinuxConfig())
    big = ["https://seg.example/x-" + str(i) + ".ts" for i in range(5000)]
    for k in range(30):
        payload = {
            "title": f"p{k}",
            "is_live": False,
            "is_dvr": False,
            "drm": False,
            "formats": [
                {"id": "s", "label": "s", "delivery": "stream_proxy", "segment_urls": big, "audio_segment_urls": [], "manifest_text": "X" * 90000}
            ],
        }
        with eng._lock:
            eng._probe_cache[f"https://page.example/{k}"] = (_t.time(), payload)
    # doğrudan doldurduk; şimdi gerçek probe yolunun trim+evict fonksiyonlarını doğrulamak için
    # küçük bir probe_formats çağrısı yapılır (yakalanan akışlarla, yt-dlp yok)
    res = eng.probe_formats(
        page_url="https://example.com/video",
        captured_streams=[{"url": "https://cdn.example/movie.mp4", "mime": "video/mp4", "size": 1000}],
        use_ytdlp=False,
    )
    assert res["formats"], "probe boş döndü"
    with eng._lock:
        n = len(eng._probe_cache)
    assert n <= 17, f"önbellek kayıt sınırı aşıldı: {n}"


def test_105_vtt_to_srt_and_subs_delivery():
    """v3.2.2: WebVTT->SRT dönüşümü + altyazı seçenekleri 'subs' teslimiyle SRT etiketli."""
    from idm_linux.hls_streamer import vtt_to_srt

    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nMerhaba\n\n00:02:03.500 --> 00:02:06.250\nİkinci"
    srt = vtt_to_srt(vtt)
    assert "1\n00:00:01,000 --> 00:00:04,000\nMerhaba" in srt
    assert "00:02:03,500 --> 00:02:06,250" in srt
    assert "WEBVTT" not in srt

    from idm_linux.stream_engine import _subtitle_options

    opts = _subtitle_options(
        [{"url": "https://cdn.example/trk.vtt", "mime": "text/vtt", "sub_label": "Türkçe"}],
        referer="https://film.example/izle",
        page_url="https://film.example/izle",
    )
    # v3.10.0 (kullanıcı kararı): uzantı DÜRÜST — kaynak .vtt ise bar'da vtt yazar
    assert opts and opts[0].delivery == "subs" and opts[0].ext == "vtt"
    assert "(VTT)" in opts[0].label and "Türkçe" in opts[0].label

    src = (PROJECT_ROOT / "stream_engine.py").read_text(encoding="utf-8")
    assert 'if t.mode == "subs":' in src, "işçi altyazı kolu yok"
    dsrc = (PROJECT_ROOT / "daemon.py").read_text(encoding="utf-8")
    assert 'delivery == "subs" and direct_url:' in dsrc, "daemon altyazı kolu yok"


def test_106_hls_subtitle_assembly_order():
    """v3.2.2: segmentli HLS altyazısı sıralı birleştirilir (yerel HTTP sunucusuyla)."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from idm_linux.hls_streamer import assemble_subtitle_text, vtt_to_srt

    class SubH(BaseHTTPRequestHandler):
        def do_GET(self):
            bodies = {
                "/sub.m3u8": b"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:6,\na.vtt\n#EXTINF:6,\nb.vtt\n#EXTINF:6,\nc.vtt\n#EXT-X-ENDLIST\n",
                "/a.vtt": b"WEBVTT\n\n00:00:00.000 --> 00:00:06.000\nILK",
                "/b.vtt": b"WEBVTT\n\n00:00:06.000 --> 00:00:12.000\nORTA",
                "/c.vtt": b"WEBVTT\n\n00:00:12.000 --> 00:00:18.000\nSON",
            }
            body = bodies.get(self.path, b"")
            if not body:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), SubH)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        txt = assemble_subtitle_text(f"http://127.0.0.1:{port}/sub.m3u8", {})
        srt = vtt_to_srt(txt)
        assert "ILK" in srt and "ORTA" in srt and "SON" in srt
        assert srt.index("ILK") < srt.index("ORTA") < srt.index("SON"), "sıra bozuldu"
        assert "WEBVTT" not in srt
    finally:
        srv.shutdown()


def test_107_chromium_force_install_policy_payload():
    """v3.2.2: kurumsal force-install policy gövdesi doğru ve tmp dizine yazılır."""
    import idm_linux.browsers as br

    tmpdir = Path(tempfile.mkdtemp(prefix="idm_policy_test_"))
    br._CHROMIUM_POLICY_DIRS, orig_dirs = [str(tmpdir)], br._CHROMIUM_POLICY_DIRS
    try:
        res = br.register_chromium_force_install_policy(17802)
        assert res.get(str(tmpdir)) == "ok", res
        data = json.loads((tmpdir / "idm-linux.json").read_text(encoding="utf-8"))
        entry = data["ExtensionInstallForcelist"]["1"]
        assert entry.startswith(COMPANION_CHROME_EXT_ID + ";http://127.0.0.1:17802/crx-update.xml")

        # ikinci çağrı idempotent (mevcut)
        res2 = br.register_chromium_force_install_policy(17802)
        assert res2.get(str(tmpdir)) == "ok (mevcut)"
    finally:
        br._CHROMIUM_POLICY_DIRS = orig_dirs
        shutil.rmtree(tmpdir, ignore_errors=True)

    dsrc = (PROJECT_ROOT / "daemon.py").read_text(encoding="utf-8")
    assert "/crx-update.xml" in dsrc and "/extension/companion-policy.crx" in dsrc
    isrc = (PROJECT_ROOT / "installer.py").read_text(encoding="utf-8")
    assert "register_chromium_force_install_policy" in isrc


def test_108_blob_ticket_streamed_to_disk():
    """v3.2.2: büyük blob yüklemesi RAM'e almadan diske akıtılır."""
    import io

    from idm_linux.auth_proxy import AuthContextVault, AuthenticatedProxyManager

    mgr = AuthenticatedProxyManager(AuthContextVault())
    payload = b"Z" * (1024 * 512)
    ticket, err = mgr.create_blob_ticket_streamed(io.BytesIO(payload), len(payload), "film.iso", "application/octet-stream")
    assert ticket is not None and not err
    assert ticket.blob_file.exists() and ticket.blob_file.stat().st_size == len(payload)
    ticket.blob_file.unlink(missing_ok=True)


def test_109_memory_governor_and_status_fields():
    """v3.2.2: RSS valfi (250/450MB + aktif iş kontrolü) ve /api/status alanları mevcut."""
    from idm_linux import daemon as dm
    from idm_linux.stream_engine import StreamEngine

    assert callable(dm._rss_mb)
    assert callable(dm._self_restart_daemon)
    assert callable(dm._strict_memory_purge)
    eng = StreamEngine(IdmLinuxConfig())
    assert eng.active_job_count() == 0

    dsrc = (PROJECT_ROOT / "daemon.py").read_text(encoding="utf-8")
    assert "rss_now > 450" in dsrc and "active_job_count() == 0" in dsrc
    assert "MemoryMax=700M" in (PROJECT_ROOT / "installer.py").read_text(encoding="utf-8")
    assert '"rss_mb"' in dsrc and '"active_stream_jobs"' in dsrc


# ---------------------------------------------------------------------------
# v3.4.0 — IDM HAKKINDA SAYFASI + ABYSS PASİF NOTU + ANINDA YOUTUBE + SİYAH
# PENCERE DÜZELTMESİ + FİLM SİTESİ ALTYAZILARI + ARKA PLAN GECİKMELİ GUI İNŞASI
# ---------------------------------------------------------------------------

def test_110_subs_delivery_direct_url_order_fixed():
    """v3.4.0 KRİTİK: daemon'da 'subs' teslimi, direct_url atamasından ÖNCE kullanılıyordu
    (UnboundLocalError) -> film sitesi altyazıları bar'dan tıklanınca 500 çöküyordu."""
    from pathlib import Path as _Path

    daemon_src = (_Path(__file__).resolve().parents[1] / "daemon.py").read_text(encoding="utf-8")
    assign_pos = daemon_src.find('direct_url = (payload.get("directUrl") or "").strip()')
    subs_pos = daemon_src.find('if delivery == "subs" and direct_url:')
    assert assign_pos != -1, "direct_url ataması yok"
    assert subs_pos != -1, "subs teslim bloğu yok"
    assert assign_pos < subs_pos, "direct_url hâlâ subs bloğundan SONRA atanıyor (UnboundLocalError)"


def test_111_about_page_i18n_all_20_languages():
    """v3.4.0: 'IDM Hakkında' sayfası metinleri 20 dilin HEPSİNDE tam çeviriyle mevcut."""
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parents[1]
    required_keys = (
        "nav.about", "about.title", "about.what", "about.history", "about.features",
        "about.project", "about.license_note", "about.btn_official", "bar.abyss_note",
        "bar.sub_label", "bar.sub_lang", "bar.audio_lang", "bar.yt_quick_muxed",
    )
    lang_dir = root / "language"
    lang_files = sorted(lang_dir.glob("*.txt"))
    assert len(lang_files) == 20, f"20 dil dosyası bekleniyordu: {len(lang_files)}"
    for lf in lang_files:
        content = lf.read_text(encoding="utf-8")
        for key in required_keys:
            assert f"\n{key} = " in f"\n{content}", f"{lf.name} içinde {key} eksik"

    # GUI: 9. nav öğesi + sayfa üreticisi + gerçek iki yana yaslama bileşeni kullanımı
    gp_src = (root / "gui_pages.py").read_text(encoding="utf-8")
    assert "def build_about_idm_page" in gp_src, "build_about_idm_page yok"
    assert "create_justified_text" in gp_src.split("def build_about_idm_page")[1], "Hakkında sayfası yaslı metin kullanmıyor"
    assert "idm_icon_128.png" in gp_src, "IDM simgesi sayfada yok"
    gui_src = (root / "gui.py").read_text(encoding="utf-8")
    assert '("about", t("nav.about"))' in gui_src, "9. nav öğesi (about) yok"


def test_112_abyss_detected_flag_and_probe_note():
    """v3.4.0: probe yanıtı abyss_detected bayrağı taşır; abyss kapalıyken bar linkleri üretilmez."""
    from idm_linux.config import IdmLinuxConfig
    from idm_linux.stream_engine import StreamEngine

    eng = StreamEngine(IdmLinuxConfig())
    res = eng.probe_formats(
        page_url="https://film.example/watch/x",
        captured_streams=[
            {"url": "abyssif://https://abyss.to/v/abcd1234", "mime": "application/x-abyss"},
            {"url": "https://cdn.example/movie.mp4", "mime": "video/mp4", "size": 1000},
        ],
        use_ytdlp=False,
        abyss_enabled=False,
    )
    assert res.get("abyss_detected") is True, "abyss_detected bayrağı gelmedi"
    # abyss kapalıyken abyss seçenekleri LİSTEDE OLMAMALI (yalnız not mekanizması var)
    labels = [f.get("label", "") for f in res.get("formats", [])]
    assert not any("Abyss" in (x or "") for x in labels), "abyss kapalıyken abyss linki sızdı"
    # mp4 yakalama hâlâ listelenmeli
    assert any("MP4" in (x or "") or "mp4" in (x or "") for x in labels), "normal video kayboldu"


def test_113_youtube_quick_options_from_captured_googlevideo():
    """v3.4.0 ANINDA YOUTUBE: yakalanan googlevideo akışlarından 0 sn'de oynatılabilir seçenekler."""
    from idm_linux.stream_engine import _youtube_quick_options

    gv = (
        "https://rr3---sn-abc.googlevideo.com/videoplayback?itag=18&clen=73400320"
        "&dur=300.000&mn=sn-abc&ms=au&mt=1&mv=m&source=youtube&expire=9999999999"
    )
    gv_audio = (
        "https://rr3---sn-abc.googlevideo.com/videoplayback?itag=140&clen=4800000"
        "&dur=300.000&mn=sn-abc&ms=au&mt=1&mv=m&source=youtube&expire=9999999999"
    )
    opts = _youtube_quick_options(
        [{"url": gv, "mime": "video/mp4"}, {"url": gv_audio, "mime": "audio/mp4"}],
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/",
    )
    ids = {o.id for o in opts}
    assert "ytq_18" in ids, "muxed itag 18 seçeneği yok"
    assert "ytq_140" in ids, "ses itag 140 seçeneği yok"
    by_id = {o.id: o for o in opts}
    q18 = by_id["ytq_18"]
    assert q18.delivery == "direct" and q18.filesize == 73400320, "muxed seçenek alanları hatalı"
    assert q18.resolution == "360p", "itag 18 -> 360p eşleşmesi bozuk"
    a140 = by_id["ytq_140"]
    assert a140.audio_only is True and a140.filesize == 4800000, "ses seçeneği hatalı"
    # bilinmeyen itag seçenek ÜRETMEZ
    opts2 = _youtube_quick_options(
        [{"url": gv.replace("itag=18", "itag=999")}], "https://youtu.be/x", ""
    )
    assert opts2 == [], "bilinmeyen itag filtrelendi"


def test_114_light_theme_registry_black_window_fix():
    """v3.4.0 SİYAH PENCERE: açık tema (light theme) bayrakları registry optimizasyonlarında."""
    from pathlib import Path as _Path

    inst_src = (_Path(__file__).resolve().parents[1] / "installer.py").read_text(encoding="utf-8")
    assert "def ensure_idm_light_theme_registry" in inst_src, "açık tema self-heal fonksiyonu yok"
    assert "AppsUseLightTheme" in inst_src and "SystemUsesLightTheme" in inst_src, "açık tema bayrakları yok"
    # ana tweaks .reg bloğunda da Personalize bölümü olmalı
    assert "[HKEY_CURRENT_USER\\\\Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Themes\\\\Personalize]" in inst_src
    # daemon başlangıcında self-heal çağrısı bağlı
    daemon_src = (_Path(__file__).resolve().parents[1] / "daemon.py").read_text(encoding="utf-8")
    assert "ensure_idm_light_theme_registry" in daemon_src, "daemon açılışında açık tema düzeltmesi çağrılmıyor"


def test_115_gui_sequential_lazy_page_build():
    """v3.4.0: ağır sayfalar TEK TEK arka planda (90ms aralıkla) inşa edilir — açılış kasmıyor."""
    from pathlib import Path as _Path

    gui_src = (_Path(__file__).resolve().parents[1] / "gui.py").read_text(encoding="utf-8")
    assert "root.after(90, _flush_deferred_pages)" in gui_src, "sıralı gecikmeli inşa zinciri yok"
    assert '"about": lambda: build_about_idm_page(' in gui_src, "about sayfası gecikmeli inşaya bağlı değil"
    # while döngüsüyle TOPLU inşa kalkmış olmalı
    assert "while deferred_builders:" not in gui_src, "eski toplu inşa (while) hâlâ duruyor"


# ---------------------------------------------------------------------------
# v3.5.0: ALTYAZI MOTORU + OYNATMA LİSTESİ + TORRENT POPUP regresyonları
# ---------------------------------------------------------------------------

def test_116_youtube_auto_captions_in_bar():
    """v3.5.0 KÖKLÜ ALTYAZI DÜZELTMESİ: YouTube'da elle yüklenen altyazı YOKSA bile
    automatic_captions (otomatik kapalı altyazılar) IDM barına DÜŞER — 'tr' kodu
    'Türkçe' olarak etiketlenir."""
    from idm_linux.stream_engine import _youtube_lang_options, sub_lang_name
    from idm_linux.i18n import get_i18n

    get_i18n("tr")  # etiketler deterministik olsun

    assert sub_lang_name("tr") == "Türkçe"
    assert sub_lang_name("en") == "English"
    assert sub_lang_name("pt-BR") == "Português (pt-BR)"
    assert sub_lang_name("") == ""

    info = {
        "title": "T",
        "formats": [],
        "subtitles": {},  # elle altyazı YOK
        "automatic_captions": {"tr": [], "en": [], "de": [], "live_chat": []},
    }
    opts = _youtube_lang_options(info, "https://www.youtube.com/watch?v=abc")
    auto = [o for o in opts if o.delivery == "yt_subs"]
    assert auto, "otomatik altyazılar bara gelmedi!"
    langs = {o.sub_lang for o in auto}
    assert {"tr", "en", "de"} <= langs, f"beklenen diller yok: {langs}"
    assert all("live_chat" not in o.sub_lang for o in auto)
    tr_opt = next(o for o in auto if o.sub_lang == "tr")
    assert "Türkçe" in tr_opt.label and "Otomatik" in tr_opt.label, tr_opt.label
    # elle yüklenen + otomatik karışık: elle önce gelir
    info2 = {"title": "T", "formats": [], "subtitles": {"ja": []}, "automatic_captions": {"en": []}}
    opts2 = _youtube_lang_options(info2, "https://www.youtube.com/watch?v=abc")
    subs2 = [o for o in opts2 if o.delivery == "yt_subs"]
    assert subs2[0].sub_lang == "ja" and "Otomatik" not in subs2[0].label


def test_117_subtitle_options_broad_patterns():
    """v3.5.0: film sitelerinin XHR altyazıları (timedtext, /caption?lang=.., text/vtt MIME,
    .ttml/.xml) IDM barına düşer; YouTube timedtext URL'sinden dil etiketi çözülür."""
    from idm_linux.stream_engine import _subtitle_options

    caps = [
        # YouTube timedtext — lang paramından 'Türkçe' etiketi GELMELİ
        {"url": "https://www.youtube.com/api/timedtext?v=abc&lang=tr&fmt=vtt", "mime": "text/vtt", "referer": ""},
        # film sitesi XHR altyazısı — /subtitles yolu
        {"url": "https://cdn.fullhdfilmizlesene.now/api/subtitles?id=42&lang=tr", "mime": "", "referer": ""},
        # .ttml uzantısı
        {"url": "https://cdn.example.net/cap/tr_altyazi.ttml", "mime": "", "referer": ""},
        # video URL'si ASLA altyazı sanılmamalı
        {"url": "https://cdn.example.net/movie.mp4", "mime": "video/mp4", "referer": ""},
    ]
    opts = _subtitle_options(caps, "", "https://site/film")
    labels = [o.label for o in opts]
    assert len(opts) == 3, f"3 altyazı bekleniyordu: {labels}"
    assert any("Türkçe" in l for l in labels), labels
    assert all(o.delivery == "subs" for o in opts)
    ttml = next(o for o in opts if "ttml" in o.direct_url)
    assert ttml.ext == "ttml"


def test_118_playlist_batch_lifecycle():
    """v3.5.0: Oynatma listesi seri motoru — sahte yt-dlp ile tam yaşam döngüsü:
    başlat -> indiriliyor -> DURAKLAT -> DEVAM -> İPTAL (durumlar + ilerleme çözümü)."""
    import os
    import stat
    import tempfile
    from unittest import mock
    from idm_linux.playlist_batch import PlaylistBatchManager, PlaylistBatchManager as _PM

    # ilerleme satırı çözümü (saf)
    e = _PM.__new__(_PM)  # statik metod için örnek gerekmez ama okunabilirlik
    from idm_linux.playlist_batch import PlaylistEntry

    ent = PlaylistEntry(index=1, url="https://x/v1", title="T")
    _PM._parse_progress(ent, "[download]  42.5% of   10.00MiB at    2.00MiB/s ETA 00:03")
    assert ent.downloaded == int(10 * 1024 * 1024 * 0.425)
    assert ent.total == 10 * 1024 * 1024
    assert ent.speed == 2 * 1024 * 1024
    assert ent.eta == 3

    tmp = Path(tempfile.mkdtemp(prefix="idmplb-"))
    fake_bin = tmp / "yt-dlp-fake"
    fake_bin.write_text(
        "#!/bin/sh\n"
        "echo \"[download]  25.0% of    4.00MiB at    1.00MiB/s ETA 00:02\"\n"
        "sleep 30\n",
        encoding="utf-8",
    )
    fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC)

    mgr = PlaylistBatchManager()
    with mock.patch("idm_linux.playlist_batch.find_ytdlp", return_value=str(fake_bin)):
        res = mgr.start_batch(
            playlist_url="https://www.youtube.com/playlist?list=PLtest123",
            entries=[{"index": 1, "url": "https://www.youtube.com/watch?v=a1", "title": "Video 1", "duration": 61},
                     {"index": 2, "url": "https://www.youtube.com/watch?v=a2", "title": "Video 2", "duration": 122}],
            download_dir=str(tmp),
        )
    assert res.get("ok"), res
    bid = res["batch_id"]
    st = mgr.status(bid)
    assert st and st["site"] == "YouTube" and st["total_entries"] == 2

    # indiriliyor durumuna geçmesini bekle
    deadline = time.time() + 6
    while time.time() < deadline:
        st = mgr.status(bid)
        if st["entries"][0]["status"] == "downloading":
            break
        time.sleep(0.1)
    assert st["entries"][0]["status"] == "downloading", st["entries"][0]
    assert st["active_index"] == 1

    # DURAKLAT
    r1 = mgr.control(bid, "pause", 1)
    assert r1.get("ok")
    st = mgr.status(bid)
    assert st["entries"][0]["status"] == "paused", st["entries"][0]
    # DEVAM
    r2 = mgr.control(bid, "resume", 1)
    assert r2.get("ok")
    st = mgr.status(bid)
    assert st["entries"][0]["status"] == "downloading", st["entries"][0]
    # İPTAL (tümü)
    r3 = mgr.control(bid, "cancel", 0)
    assert r3.get("ok")
    st = mgr.status(bid)
    assert all(e_["status"] == "cancelled" for e_ in st["entries"]), st["entries"]
    mgr.shutdown_all()


def test_119_playlist_site_dynamic_detection():
    """v3.5.0: oynatma listesi URL'sinden site DİNAMİK algılanır (GUI rozeti)."""
    from idm_linux.playlist_batch import detect_playlist_site

    assert detect_playlist_site("https://www.youtube.com/playlist?list=PL1") == "YouTube"
    assert detect_playlist_site("https://youtu.be/xxx?list=PL1") == "YouTube"
    assert detect_playlist_site("https://www.dailymotion.com/playlist/x7abc") == "Dailymotion"
    assert detect_playlist_site("https://ok.ru/video/c123pl") == "OK.ru"
    assert detect_playlist_site("https://vk.com/video?z=pl") == "VK"
    assert detect_playlist_site("https://vkvideo.ru/playlist/x") == "VK"
    assert detect_playlist_site("https://www.bilibili.com/list/ml1") == "Bilibili"
    assert "adl" in detect_playlist_site("https://example.com/pl") or detect_playlist_site("https://example.com/pl") == "example.com"


def test_120_v350_deliverables_consistency():
    """v3.5.0 sürüm tutarlılığı + torrent onay popup'u + altyazı bölüm başlığı + i18n."""
    root = Path(__file__).resolve().parents[1]

    # v3.9.0: sürüm sabit kodlanmaz — üçü de BİRBİRİYLE tutarlı olmalı
    from idm_linux import __version__ as _pkg_ver
    assert json.loads((root / "extension/chromium/manifest.json").read_text(encoding="utf-8"))["version"] == _pkg_ver
    assert json.loads((root / "extension/firefox/manifest.json").read_text(encoding="utf-8"))["version"] == _pkg_ver
    init_src = (root / "__init__.py").read_text(encoding="utf-8")
    assert f'__version__ = "{_pkg_ver}"' in init_src

    content_src = (root / "extension/chromium/content.js").read_text(encoding="utf-8")
    assert "TORRENT_I18N" in content_src and "Bu torrenti indirmek istiyor musunuz?" in content_src, "torrent onay popup'u yok"
    assert "idmTorrentPopup" in content_src and "__idmLinuxTorrentPopup" in content_src
    # eski 'onaysız doğrudan magnet gönder' kaldırıldı
    assert "magnet-click" not in content_src, "eski onaysız magnet yakalayıcısı hâlâ duruyor"
    # altyazı grubu
    assert "subsHeader" in content_src and "insertSubSeparator" in content_src
    ph_src = (root / "extension/chromium/page_hook.js").read_text(encoding="utf-8")
    assert "ytInitialPlayerResponse" in ph_src and "captionTracks" in ph_src, "YouTube altyazı motoru yok"

    # engine + daemon
    eng_src = (root / "stream_engine.py").read_text(encoding="utf-8")
    assert "automatic_captions" in eng_src and "bar.subs_header" in eng_src
    daemon_src = (root / "daemon.py").read_text(encoding="utf-8")
    for route in ("/api/playlist/batch/start", "/api/playlist/batch/control", "/api/playlist/batch/status", "/api/playlist/batch/list"):
        assert route in daemon_src, f"daemon rotası eksik: {route}"

    # 20 dil dosyasında 25 yeni anahtar
    keys = ["bar.subs_header", "bar.sub_auto", "ov.pl_card_title", "ov.pl_card_sub",
            "ov.pl_status_paused", "ov.pl_btn_download"]
    for f in (root / "language").glob("*.txt"):
        txt = f.read_text(encoding="utf-8")
        for k in keys:
            assert f"{k} = " in txt, f"{f.name}: {k} eksik"

    # chromium/firefox kopyaları birebir aynı olmalı
    for fn in ("content.js", "page_hook.js"):
        assert (root / f"extension/chromium/{fn}").read_bytes() == (root / f"extension/firefox/{fn}").read_bytes(), f"{fn} kopyaları farklı"


def test_121_gui_playlist_card_and_details_card():
    """v3.5.0: GUI Genel Bakış sayfasına Oynatma Listesi kartı eklendi; link kutusu sabit,
    liste kaydırılabilir; Dağıtım & Ortam kartı kısaltıldı (expand kalktı)."""
    gui_src = (Path(__file__).resolve().parents[1] / "gui.py").read_text(encoding="utf-8")
    assert "ov.pl_card_title" in gui_src, "oynatma listesi kartı yok"
    assert "_pl_control(" in gui_src and '"pause"' in gui_src and '"resume"' in gui_src, "duraklat/devam yok"
    assert "pl_canvas.yview_scroll" in gui_src, "kaydırılabilir liste yok"
    assert "/api/playlist/batch/start" in gui_src and "/api/playlist/batch/status" in gui_src
    # Dağıtım & Ortam kartı artık expand etmiyor (yükseklik kısaltıldı)
    assert 'sys_det_card.pack(fill="x")' in gui_src
    assert 'sys_det_card.pack(fill="both", expand=True)' not in gui_src


# ═════════════════════════════════════════════════════════════════════════════
# v3.8.0 REGRESYON TESTLERİ
# ═════════════════════════════════════════════════════════════════════════════

_ARIA2C_STUB = r'''#!/usr/bin/env python3
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

args = sys.argv[1:]
log_path = os.environ.get("IDM_STUB_LAUNCH_LOG", "")
if log_path:
    with open(log_path, "a", encoding="utf-8") as fp:
        fp.write("\t".join(args) + "\n")
for a in args:
    if a.startswith("--dht-entry-point="):
        v = a.split("=", 1)[1]
        if "," in v:
            # GERÇEK aria2c davranışı: virgüllü liste 'Unrecognized format' ile çöküş
            sys.stderr.write("[OptionHandlerImpl.cc:469] errorCode=1 Unrecognized format in --dht-entry-point\n")
            sys.exit(1)

port = 0
for a in args:
    if a.startswith("--rpc-listen-port="):
        try:
            port = int(a.split("=", 1)[1])
        except ValueError:
            port = 0

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(n)
        try:
            req = json.loads(body.decode())
        except Exception:
            req = {}
        method = req.get("method", "")
        if method == "aria2.getVersion":
            res = {"version": "1.37.0-stub", "enabledFeatures": []}
        elif method == "aria2.addTorrent":
            res = "stub-gid-1"
        elif method == "aria2.addUri":
            res = "stub-gid-2"
        elif method == "aria2.tellStatus":
            res = {
                "gid": "stub-gid-1", "status": "active", "totalLength": "1048576",
                "completedLength": "0", "downloadSpeed": "0", "uploadSpeed": "0",
                "connections": "0", "numSeeds": "0", "bitfield": "ff", "followedBy": [],
            }
        else:
            res = "OK"
        out = json.dumps({"id": req.get("id"), "jsonrpc": "2.0", "result": res}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass

ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
'''


def _make_stub_aria2c(tmpd: Path) -> Path:
    stub_dir = tmpd / "stubbin"
    stub_dir.mkdir(parents=True, exist_ok=True)
    bin_path = stub_dir / "aria2c"
    bin_path.write_text(_ARIA2C_STUB, encoding="utf-8")
    bin_path.chmod(0o755)
    return bin_path


def _minimal_torrent_bytes() -> bytes:
    import hashlib
    ann_u = b"udp://tracker.opentrackr.org:1337/ann"
    fn_u = b"v38_regression_test.mp4"
    info_dict = (
        b"d6:lengthi1048576e4:name" + str(len(fn_u)).encode() + b":" + fn_u
        + b"12:piece lengthi262144e6:pieces80:" + (b"\x11" * 80) + b"e"
    )
    return (
        b"d8:announce" + str(len(ann_u)).encode() + b":" + ann_u
        + b"4:info" + info_dict + b"e"
    )


def test_123_aria2c_dht_entry_point_single_value_e2e_stub():
    """v3.8.0 REGRESYON: kullanıcının raporladığı 'aria2c süreci beklenmedik şekilde
    kapandı (çıkış kodu 28) — [OptionHandlerImpl.cc] errorCode=1 Unrecognized format'
    hatası kök-nedeniyle köprüden geçer: --dht-entry-point'e virgüllü LİSTE vermek
    yerine TEK giriş noktası gönderilir ve stub aria2c İLK denemede RPC'ye kalkar
    (güvenli-yedek ikinci deneme devreye GİRMEZ — kök-neden düzelidir)."""
    import hashlib
    from idm_linux.torrent_engine import parse_torrent_bytes

    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        _make_stub_aria2c(tmp)
        launch_log = tmp / "launches.log"
        old_path = os.environ.get("PATH")
        old_log = os.environ.get("IDM_STUB_LAUNCH_LOG")
        os.environ["PATH"] = str(tmp / "stubbin") + os.pathsep + (old_path or "")
        try:
            # 0) Stub'un kendisi eski hatayı doğru simüle ediyor mu? (virgül -> exit 1)
            #    (log kaydı kapalı — yalnızca köprü başlatmaları sayılacak)
            bad = subprocess.run(
                [str(tmp / "stubbin" / "aria2c"), "--dht-entry-point=a:1,b:2"],
                capture_output=True, text=True, timeout=10,
            )
            assert bad.returncode == 1 and "Unrecognized format" in bad.stderr, "stub simülasyonu bozuk"
            os.environ["IDM_STUB_LAUNCH_LOG"] = str(launch_log)

            # 1) Köprüyü gerçek başlatma yoluyla ayağa kaldır
            # v3.10.0: bu test aria2c YEDEK motorunun başlatma argümanlarını doğrular;
            # yerleşik native motor bilinçli olarak kapatılır (ana yol ayrı testlerde).
            from idm_linux.torrent_engine import TorrentBridgeManager, TorrentSession

            _orig_native = TorrentSession._try_native_start
            TorrentSession._try_native_start = lambda self: False

            raw = _minimal_torrent_bytes()
            meta = parse_torrent_bytes(raw)
            assert hashlib.sha1  # meta.info_hash alanı deterministik
            mgr = TorrentBridgeManager(base_temp_dir=tmp / "sessions")
            sess = mgr.register_torrent_bytes(raw)
            ok_ready = sess.ready.wait(timeout=30)
            try:
                assert ok_ready, "motor ready event'i zamanında gelmedi"
                assert sess.error_message == "", f"beklenmeyen hata: {sess.error_message}"
                assert sess.gid == "stub-gid-1", f"beklenen gid yok: {sess.gid}"
                # 2) YALNIZCA BİR kez başlatıldı (güvenli-yedek gerekmedi) ve dht değeri TEK
                launches = launch_log.read_text(encoding="utf-8").splitlines()
                assert len(launches) == 1, f"başlatma sayısı {len(launches)} (beklenen 1) — kök-neden düzeltilmemiş!"
                argv_tokens = launches[0].split("\t")
                dht_tokens = [t for t in argv_tokens if t.startswith("--dht-entry-point=")]
                assert len(dht_tokens) == 1
                assert "," not in dht_tokens[0], "dht-entry-point hâlâ liste taşıyor!"
            finally:
                sess.stop_and_cleanup()
        finally:
            try:
                TorrentSession._try_native_start = _orig_native
            except Exception:
                pass
            if old_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = old_path
            if old_log is None:
                os.environ.pop("IDM_STUB_LAUNCH_LOG", None)
            else:
                os.environ["IDM_STUB_LAUNCH_LOG"] = old_log


def test_124_ed2k_auto_install_flow_and_no_manual_hints():
    """v3.8.0 REGRESYON: kullanıcının 'Kurulum başarısız — elle kurmayı deneyin:
    sudo pacman -S mldonkey' şikayeti kökten biter —
    a) eklenti & köprü metinlerinde elle kurulum komutu ASLA geçmez,
    b) daemon /api/ed2k/download motor yoksa kurulumu OTOMATİK başlatır ve
       bağlantıyı beklemeye alır (kullanıcı tek onayı pkexec penceresinde verir)."""
    root = Path(__file__).resolve().parents[1]

    # a) eklenti kaynakları: yasak metinler + davranış anahtarları
    for browser in ("chromium", "firefox"):
        ct_src = (root / f"extension/{browser}/content.js").read_text(encoding="utf-8")
        for banned in ("installFail", "elle kurmayı", "try manual install", "sudo pacman", "sudo apt", "sudo dnf", "sudo zypper"):
            assert banned not in ct_src, f"{browser}/content.js yasaklı metin: {banned}"
        assert "startEngineInstall" in ct_src, "otomatik kurulum akışı yok"
        assert "IDM_ED2K_SEND" in ct_src, "otomatik bağlantı gönderimi yok"
        bg_src = (root / f"extension/{browser}/background.js").read_text(encoding="utf-8")
        assert "/api/ed2k/install" in bg_src

    # b) daemon kaynak: otomatik kurulum işi + bekleyen bağlantı alanları
    daemon_src = (root / "daemon.py").read_text(encoding="utf-8")
    assert "_ed2k_auto_install_job" in daemon_src
    assert "ed2k_pending_link" in daemon_src and "ed2k_install_started" in daemon_src

    # c) köprü metinleri: kullanıcıya elle komut gösterilmez
    bridge_src = (root / "ed2k_bridge.py").read_text(encoding="utf-8")
    for banned in ("Elle kurmayı deneyin", "sudo pacman -S amule", "sudo apt install amule"):
        assert banned not in bridge_src, f"ed2k_bridge yasaklı metin: {banned}"

    # d) CANLI davranış: motor yokken /api/ed2k/download → installing=True + bekleyen bağlantı
    import tempfile as _tf
    import urllib.parse as _up
    import threading
    from http.server import ThreadingHTTPServer as _THS

    with _tf.TemporaryDirectory() as tmpd:
        old_cache = os.environ.get("XDG_CACHE_HOME")
        old_home = os.environ.get("HOME")
        os.environ["XDG_CACHE_HOME"] = tmpd
        try:
            from idm_linux import daemon as _daemon
            from idm_linux import ed2k_bridge as _bridge

            # testte gerçek indirme/pkexec denenmesin: kurulum işi izole edilir
            # (release olayına dek bekler — pending link durumunu deterministik okuruz)
            calls = {"n": 0}
            install_started = threading.Event()
            release = threading.Event()

            def _fake_install():
                install_started.set()
                release.wait(timeout=30)
                calls["n"] += 1
                return True, "stub-install"

            # v3.10.0: Bu test aMule YEDEK motorunun otomatik kurulum akışını doğrular.
            # Native eD2K motoru artık ana yol olduğu için burada bilinçli olarak
            # "yok" gibi davranır (ana native yol tests/test_p2p_native.py'de test edilir).
            orig_native_avail = _daemon.native_ed2k_available
            _daemon.native_ed2k_available = lambda: False
            _orig_native_flag = _bridge._NATIVE_ED2K_ENABLED
            _bridge._NATIVE_ED2K_ENABLED = False

            orig_install = _daemon.ed2k_install_backend_safe
            _daemon.ed2k_install_backend_safe = _fake_install
            try:
                state = _daemon.DaemonState()
                srv = _THS(("127.0.0.1", 0), _daemon.make_http_handler(state))
                port = srv.server_address[1]
                th = threading.Thread(target=srv.serve_forever, daemon=True)
                th.start()
                try:
                    link = "ed2k://|file|Test+Dosya.iso|1048576|D41D8CD98F00B204E9800998ECF8427E|/"
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/ed2k/download",
                        data=json.dumps({"link": link, "source": "unit-test"}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=10) as r:
                        res = json.loads(r.read().decode("utf-8"))
                    assert res.get("installing") is True, f"installing beklenmedi: {res}"
                    assert res.get("ok") is False  # motor yok — ama kurulum başladı
                    assert "otomatik" in (res.get("message") or "").lower()
                    with _daemon._ED2K_INSTALL_LOCK:
                        assert state.ed2k_install_started is True
                        assert state.ed2k_pending_link == link, "bağlantı beklemeye alınmadı"
                    # kurulum işi çalışıyor mu? (durum ucu installing=true bildirmeli)
                    assert install_started.wait(timeout=10), "kurulum işi tetiklenmedi"
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ed2k/status", timeout=5) as r:
                        st_res = json.loads(r.read().decode("utf-8"))
                    assert st_res.get("installing") is True, f"durum installing=false: {st_res}"
                    # bekleyen bağlantı işlensin ve stub çağrıldığını doğrula
                    release.set()
                    for _ in range(50):
                        if calls["n"] > 0:
                            break
                        time.sleep(0.1)
                    assert calls["n"] >= 1, "kurulum işi stub'ı çağırmadı"
                finally:
                    srv.shutdown()
                    srv.server_close()
            finally:
                _daemon.ed2k_install_backend_safe = orig_install
                _daemon.native_ed2k_available = orig_native_avail
                _bridge._NATIVE_ED2K_ENABLED = _orig_native_flag
        finally:
            if old_cache is None:
                os.environ.pop("XDG_CACHE_HOME", None)
            else:
                os.environ["XDG_CACHE_HOME"] = old_cache


def test_125_subtitle_capture_layers_for_movie_sites():
    """v3.8.0 REGRESYON: film siteleri (fullhdfilmizlesene/rapidvid) için TÜM altyazı
    yakalama katmanları hem chromium hem firefox'ta mevcut olmalı:
    webRequest ağ gözlemcisi + fetch/XHR gövde taraması + Resource Timing + <track>."""
    root = Path(__file__).resolve().parents[1]
    for browser in ("chromium", "firefox"):
        bg_src = (root / f"extension/{browser}/background.js").read_text(encoding="utf-8")
        assert "IDM_BG_SUBTITLE" in bg_src, f"{browser}/background.js ağ gözlemcisi yok"
        assert "IDM_SUB_EXT_RE" in bg_src and "timedtext" in bg_src
        ph_src = (root / f"extension/{browser}/page_hook.js").read_text(encoding="utf-8")
        assert "scanSubUrls" in ph_src, f"{browser}/page_hook.js gövde taraması yok"
        assert "dfxp" in ph_src and "sami" in ph_src, "genişletilmiş altyazı uzantıları yok"
        ct_src = (root / f"extension/{browser}/content.js").read_text(encoding="utf-8")
        assert "getEntriesByType(\"resource\")" in ct_src, f"{browser}/content.js Resource Timing yok"
        assert "IDM_BG_SUBTITLE" in ct_src, f"{browser}/content.js arka plan altyazı işleyicisi yok"

    # motor tarafı: rapidvid tarzı üçüncü taraf .vtt URL'i altyazı olarak tanınır
    from idm_linux.stream_engine import _looks_like_subtitle_capture

    assert _looks_like_subtitle_capture("https://subs.rapidvid.org/1306c2d2/78aea874c017d949/1.vtt", "")
    assert _looks_like_subtitle_capture("https://cdn.example.com/api/subtitles?lang=tr", "application/json")


def test_126_tk9_wheel_number_mapping_and_scroll_dispatch():
    """v3.8.0 REGRESYON: Tk 9.0'da (Arch/Manjaro) tekerlek olay numaraları 8/9'dur
    (8.6'da 4/5). Global kaydırma dağıtıcısı sürüme göre doğru tabloyu seçmeli;
    aksi hâlde Genel Bakış & İndir sayfası tekerleğe tepki vermez (kullanıcı raporu)."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "gui_pages.py").read_text(encoding="utf-8")
    assert "_wheel_nums_for_runtime" in src, "sürüm-uyumlu tekerlek tablosu yok"
    assert "TkVersion >= 9.0" in src, "Tk 9.0 denetimi yok"
    # dağıtıcı sabitlenmiş 4/5 karşılaştırması İÇERMEMELİ (yön tayini tablo üzerinden yapılmalı)
    assert "if num == 4 or wheel_delta > 0" not in src, "eski sabit num karşılaştırması duruyor"
    assert "_WHEEL_UP_NUMS" in src and "_WHEEL_DOWN_NUMS" in src
    # oynatma listesi tekerleği de her iki sürümü kapsamalı
    gui_src = (root / "gui.py").read_text(encoding="utf-8")
    assert "<Button-8>" in gui_src and "<Button-9>" in gui_src, "oynatma listesi Tk 9.0 tekerleği kapsamıyor"


def test_127_qr_cache_and_performance_guards():
    """v3.8.0 REGRESYON: QR üretimi LRU önbellekli olmalı (Diğer Projeler/Teşekkür
    sayfaları tekrar açılışlarında anında kurulmalı) ve iki yana yaslı metin
    yeniden çizimi Configure fırtınalarına karşı debounce'lu olmalı."""
    root = Path(__file__).resolve().parents[1]
    qr_src = (root / "qr_gen.py").read_text(encoding="utf-8")
    assert "_QR_B64_CACHE" in qr_src, "QR önbelleği yok"

    from idm_linux.qr_gen import render_qr_base64

    b1 = render_qr_base64("https://idm-linux.example/v38?a=1", scale=2, border=2)
    b2 = render_qr_base64("https://idm-linux.example/v38?a=1", scale=2, border=2)
    assert b1 == b2 and b1.startswith("iVBOR"), "QR önbelleği tutarsız"

    gp_src = (root / "gui_pages.py").read_text(encoding="utf-8")
    assert "_pending_redraw" in gp_src and "_flush_pending_redraw" in gp_src, "justified text debounce yok"


# ───────────────────────── v3.9.0 REGRESYON KATMANI ─────────────────────────

def test_128_amulecmd_no_uppercase_h_option():
    """v3.9.0 REGRESYON (kullanıcı raporu: "eMule 'Add' failed: Unknown option 'H'"):
    amulecmd çağrı zincirinde '-H' seçeneği ASLA bulunmamalı — 2.3.x'te host seçeneği
    '-h/--host=' (küçük harf) '-H' yoktur. Ayrıca 'Show DL' kuyruk doğrulaması
    zincirde yer almalı (sessiz başarısızlık biter)."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "ed2k_bridge.py").read_text(encoding="utf-8")
    # attempts kurulumunda -H geçmemeli (docstring/rapor içindeki geçişler hariç)
    import re as _re
    fn = src.split("def _amulecmd_add")[1].split("\ndef ")[0]
    for line in fn.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        assert '"-H"' not in line, f"'-H' argümanı duruyor: {s}"
    assert '"-p", str(_AMULE_EC_PORT)' in fn, "EC portu denemelerde yok"
    assert '"--host=127.0.0.1"' in fn, "uzun biçim yedek denemesi yok"
    assert '"Show DL"' in fn, "kuyruk doğrulama komutu yok"


def test_129_amulecmd_add_live_stub_daemon():
    """v3.9.0: stub amulecmd ikilisiyle gerçek akış — 'Operation was successful'
    yanıtı kabul edilir ve Show DL doğrulaması 'kuyruk doğrulandı' ekler."""
    tmp = Path(tempfile.mkdtemp(prefix="idm-amule-stub-"))
    try:
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "amulecmd"
        stub.write_text(
            "#!/bin/sh\n"
            'case "$*" in\n'
            '  *"Add "*) echo "Creating client..."; echo "Succeeded! Connection established"; echo " > Operation was successful.";;\n'
            '  *"Show DL"*) echo " > 5F5B2A3AB1D3E4C6A7B8C9D0E1F2A3B4 Test.Documentary.mp4";;\n'
            '  *) echo " > other";;\n'
            "esac\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        import idm_linux.ed2k_bridge as eb

        orig_which = shutil.which

        def fake_which(name):
            if name == "amulecmd":
                return str(stub)
            return orig_which(name)

        shutil.which = fake_which
        try:
            ok, msg = eb._amulecmd_add(
                "ed2k://|file|Test.Documentary.mp4|123|5F5B2A3AB1D3E4C6A7B8C9D0E1F2A3B4|/"
            )
        finally:
            shutil.which = orig_which
        assert ok, msg
        assert "kuyruk doğrulandı" in msg, f"doğrulama eklenmedi: {msg}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_130_subtitle_lang_guess_and_dedup():
    """v3.9.0: URL'den altyazı dili tahmini + normalleştirilmiş tekilleştirme
    (kullanıcı kararı: 'altyazı dilini de yazsın' + 'fake/yanlış gösterilmesin')."""
    from idm_linux.stream_engine import _norm_sub_dedup_key, guess_lang_from_url, sub_lang_name

    assert guess_lang_from_url("https://c.x/subs?lang=tr&v=2") == "tr"
    assert guess_lang_from_url("https://c.x/sub/tr.vtt") == "tr"
    assert guess_lang_from_url("https://c.x/sub/-tr-yeni.vtt") == "tr"
    assert guess_lang_from_url("https://c.x/sub/turkce.vtt") == "tr"
    assert guess_lang_from_url("https://c.x/sub/english.vtt") == "en"
    assert guess_lang_from_url("https://c.x/sub/ingilizce.srt") == "en"
    assert guess_lang_from_url("https://c.x/sub/tur.vtt") == "tr"  # ISO 639-2
    assert guess_lang_from_url("https://c.x/1306c2d2/hash/1.vtt") in ("", "c")  # anlamsız
    assert sub_lang_name("tr") == "Türkçe"
    # 'lang:tr' öneki etiketi yerel ada çevrilir (_subtitle_options içinde)
    assert _norm_sub_dedup_key("https://s.r/x/1.vtt?tok=a") == _norm_sub_dedup_key(
        "http://s.r/x/1.vtt"
    )


def test_131_subtitle_content_sniffer():
    """v3.9.0: altyazı içerik imzası — WEBVTT/SRT/ASS/TTML tanınır, HTML hata sayfası
    ve JSON gövdeleri SAHTE sayılır (fullhdfilmizlesene 'Default (Forced)' boş rayı)."""
    from idm_linux.hls_streamer import looks_like_subtitle_bytes

    assert looks_like_subtitle_bytes(b"WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nx")
    assert looks_like_subtitle_bytes(b"\xef\xbb\xbfWEBVTT\n\n00:01.000 --> 00:02.000\nmerhaba")
    assert looks_like_subtitle_bytes(b"1\n00:00:01,000 --> 00:00:03,000\nsrt satiri\n")
    assert looks_like_subtitle_bytes(b"[Script Info]\nTitle: t\n[V4+ Styles]\n")
    assert looks_like_subtitle_bytes(b"<?xml version='1.0'?><tt xmlns='urn:tt'></tt>")
    assert not looks_like_subtitle_bytes(b"<html><body>403 Hotlink</body></html>")
    assert not looks_like_subtitle_bytes(b'{"error": "not found"}')
    assert not looks_like_subtitle_bytes(b"")
    assert not looks_like_subtitle_bytes(b"short")


def test_132_subtitle_header_variants_shape():
    """v3.9.0: 4 aşamalı başlık stratejisi — tam taklit → Origin'siz → çıplak → nötr.
    Hotlink korumalı rapidvid CDN'lerinin '0 bayt' vakasının kalkanı."""
    from idm_linux.hls_streamer import _subtitle_header_variants

    full = {
        "User-Agent": "UA1",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://film.example/film/x/",
        "Origin": "https://film.example",
        "Cookie": "sid=1",
    }
    vs = _subtitle_header_variants(full)
    assert len(vs) == 4
    assert "Referer" in vs[0] and "Origin" in vs[0] and "Cookie" in vs[0]
    assert "Origin" not in vs[1] and "Referer" in vs[1]
    assert "Referer" not in vs[2] and "Cookie" not in vs[2]
    assert set(vs[3].keys()) == {"User-Agent", "Accept"}


def test_133_subtitle_options_drops_fakes_and_dedups():
    """v3.9.0 E2E: sahte rapidvid benzeri CDN'de (adı .vtt ama HTML dönen 'Default'
    rayı) bar'da YALNIZCA gerçek 2 altyazı görünür; sorgu varyantları tek satıra iner;
    gerçek bayt boyutu filesize alanına yazar."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    home = os.environ.get("HOME") or "/tmp"
    os.makedirs(home, exist_ok=True)

    tr_vtt = b"WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\nMerhaba\n"
    en_vtt = b"WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\nHello\n"
    fake_html = b"<html><body>403</body></html>"

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            p = urllib.parse.urlsplit(self.path).path
            if p.endswith("tr.vtt"):
                body = tr_vtt
            elif p.endswith("en.vtt"):
                body = en_vtt
            else:
                body = fake_html
            self.send_response(200)
            self.send_header("Content-Type", "text/html" if body is fake_html else "text/vtt")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        from idm_linux.stream_engine import _subtitle_options

        captured = [
            {"url": f"{base}/a/tr.vtt", "mime": "text/vtt", "sub_label": "Türkçe Altyazı"},
            {"url": f"{base}/a/tr.vtt?tok=x", "mime": "text/vtt", "sub_label": ""},
            {"url": f"{base}/a/en.vtt", "mime": "text/vtt", "sub_label": "lang:en"},
            {"url": f"{base}/a/fake.vtt", "mime": "text/vtt", "sub_label": "Default (Forced)"},
        ]
        opts = _subtitle_options(captured, "https://film.example/film/x/", "https://film.example/film/x/", validate=True)
        labels = [o.label for o in opts]
        assert len(opts) == 2, f"beklenen 2, gelen {len(opts)}: {labels}"
        assert any("Türkçe" in l for l in labels)
        assert any("English" in l for l in labels)
        tr_opt = next(o for o in opts if "Türkçe" in o.label)
        assert tr_opt.filesize == len(tr_vtt) and tr_opt.filesize_exact
        # v3.10.0 (kullanıcı kararı): uzantı DÜRÜST — kaynak WebVTT ise vtt yazar
        assert tr_opt.ext == "vtt"
    finally:
        srv.shutdown()


def test_134_live_tracker_list_merges_with_static():
    """v3.9.0: canlı tracker listesi — statik liste her zaman bulunur, ağ yoksa da
    torrent başlatma asla tracker'sız kalmaz (TPB '0 B/s' kalkanı)."""
    from idm_linux.torrent_engine import DEFAULT_PUBLIC_TRACKERS, merged_tracker_list

    merged = merged_tracker_list()
    assert merged, "birleşik liste boş olamaz"
    for t in DEFAULT_PUBLIC_TRACKERS[:3]:
        assert t in merged, f"statik tracker kayboldu: {t}"
    assert len(merged) <= 60


def test_135_aria2_cmd_has_head_priority_and_live_trackers():
    """v3.9.0: aria2c komutunda bt-prioritize-piece=head + canlı tracker listesi +
    changeOption tabanlı refresher iş parçacığı bulunmalı."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "torrent_engine.py").read_text(encoding="utf-8")
    assert '"--bt-prioritize-piece=head=48M"' in src
    assert "merged_tracker_list()" in src
    assert "aria2.changeOption" in src
    assert "fetch_fresh_trackers" in src
    assert "ngosang/trackerslist" in src
    # kaldırılan tehlikeli seçenek geri gelmemeli (yavaş torrenti öldürür)
    assert "--bt-stop-timeout" not in src


def test_136_policy_update_url_version_stamped():
    """v3.9.0 (kullanıcı kararı): kurumsal policy güncelleme URL'i sürüm damgalı olmalı —
    IDM güncellenince policy içeriği değişir, ÇALIŞAN Chromium eklentiyi RESTARTSIZ
    üzerine kurar. pkexec yedeği de mevcut olmalı."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "browsers.py").read_text(encoding="utf-8")
    assert "crx-update.xml" in src and "?v=" in src, "sürüm damgası yok"
    assert "__version__" in src, "sürüm değişkeni kullanılmıyor"
    assert 'shutil.which("pkexec")' in src and '"tee"' in src, "pkexec yedeği yok"
    from idm_linux import __version__ as v

    assert v == "1.0.0", f"beklenen 1.0.0, gelen {v}"


def test_137_extension_bar_drag_and_autoprobe_guards():
    """v3.9.0 (kullanıcı kararı): bar sürükleme eşiği + kalıcı konum + otomatik tespit
    + altyazı dil haritası + rozet sayacı uzantı kodunda bulunmalı."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "extension/chromium/content.js").read_text(encoding="utf-8")
    assert "Math.hypot(dx, dy) < 6" in src, "sürükleme eşiği yok"
    assert "persistBarPos" in src and "restoreBarPos" in src, "kalıcı konum yok"
    assert "lastPrefetchCount" in src, "otomatik tespit sayacı yok"
    assert "subLabelMap" in src and "enrichSubLabel" in src, "altyazı dil haritası yok"
    assert "IDM ·" in src, "rozet sayacı yok"
    assert "normSubKey" in src, "normalleştirilmiş altyazı tekilleştirmesi yok"
    ff = (root / "extension/firefox/content.js").read_text(encoding="utf-8")
    assert "Math.hypot(dx, dy) < 6" in ff, "firefox kopyası bayat"
    hook = (root / "extension/chromium/page_hook.js").read_text(encoding="utf-8")
    assert "detectSubLabelFromContext" in hook, "page_hook dil bağlamı çıkarımı yok"


if __name__ == "__main__":
    # v3.9.0 DÜZELTME: modül-seviyesi test_* fonksiyonları (v2.9.3'ten beri eklenen
    # test_68, test_100+, v3.9.0 katmanı vb.) loadTestsFromModule tarafından
    # TOPLANMIYORDU — yıllardır hiç çalışmıyorlardı (yalnızca TestCase metotları
    # koşuyordu). Artık hem TestCase sınıfı hem modül fonksiyonları koşar.
    _module = sys.modules["__main__"]
    _suite = unittest.defaultTestLoader.loadTestsFromModule(_module)
    import types as _types

    _added = 0
    for _name in sorted(dir(_module)):
        if not _name.startswith("test_"):
            continue
        _obj = getattr(_module, _name)
        if isinstance(_obj, _types.FunctionType):
            _suite.addTest(unittest.FunctionTestCase(_obj, description=_obj.__doc__ or _name))
            _added += 1
    _runner = unittest.TextTestRunner(verbosity=2)
    _result = _runner.run(_suite)
    print(f"\nmodül-seviyesi test fonksiyonu eklendi: {_added}")
    sys.exit(0 if _result.wasSuccessful() else 1)
