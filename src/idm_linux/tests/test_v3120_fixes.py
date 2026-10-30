#!/usr/bin/env python3
"""v3.12.0 fix tests: gofile restore, ok.ru fast-proxy, trial-reset plumbing."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from idm_linux.auth_proxy import (  # noqa: E402
    _ALWAYS_PROXY_AUTH_DOMAINS,
    _FAST_PROXY_HOSTS,
    AuthenticatedProxyManager,
)
from idm_linux.protocol import DownloadRequest  # noqa: E402
from idm_linux.wine_sender import WineIdmSender  # noqa: E402


def _make_manager() -> AuthenticatedProxyManager:
    mgr = AuthenticatedProxyManager.__new__(AuthenticatedProxyManager)
    mgr._tickets = {}
    mgr._lock = __import__("threading").Lock()
    mgr._ssl_ctx = None
    mgr.vault = MagicMock()
    mgr.vault.enrich_request = lambda req: None
    return mgr


class TestGofileRestore(unittest.TestCase):
    def test_gofile_in_always_proxy_domains(self):
        self.assertIn("gofile.io", _ALWAYS_PROXY_AUTH_DOMAINS)

    def _wrap(self, url: str, cookies: str = "") -> DownloadRequest:
        mgr = _make_manager()
        req = DownloadRequest(url=url, filename="video.zip", cookies=cookies, source="gofile-capture")
        with patch.object(mgr, "_probe_upstream", return_value=(False, "video.zip", url)) as pr:
            out = mgr.maybe_wrap_authenticated_download(req, 17801)
        return out, pr

    def test_gofile_public_anon_ok_gets_real_url(self):
        """Anonim yoklama TEMİZse gofile GERÇEK store URL'sini alır (anında, bozulmadan)."""
        out, pr = self._wrap("https://store4.gofile.io/download/web/abc123/file.zip")
        self.assertEqual(out.url, "https://store4.gofile.io/download/web/abc123/file.zip")
        self.assertTrue(pr.called)
        self.assertTrue(pr.call_args.kwargs.get("fail_safe") is True)

    def test_gofile_probe_html_goes_proxy(self):
        """Yoklama HTML/403 derse köprüye alınır — 3.27KB bozuk dosya imkânsız."""
        mgr = _make_manager()
        req = DownloadRequest(url="https://gofile.io/download/web/abc123/file.zip", filename="file.zip", source="gofile-capture")
        with patch.object(mgr, "_probe_upstream", return_value=(True, "", req.url)):
            out = mgr.maybe_wrap_authenticated_download(req, 17801)
        self.assertTrue(out.url.startswith("http://127.0.0.1:17801/proxy/"))

    def test_gofile_probe_timeout_fail_safe_proxy(self):
        """Yoklama ZAMAN AŞIMINA düşerse köprü seçilir (v3.11.0 bozuk dosya vakasının kökü)."""
        mgr = _make_manager()
        req = DownloadRequest(url="https://gofile.io/download/web/abc123/file.zip", filename="file.zip", source="gofile-capture")

        class _BoomOpener:
            def open(self, *a, **k):
                raise RuntimeError("timeout")

        with patch("urllib.request.build_opener", return_value=_BoomOpener()):
            with patch("idm_linux.auth_proxy.extract_browser_cookies_for_url", return_value=""):
                out = mgr.maybe_wrap_authenticated_download(req, 17801)
        self.assertTrue(out.url.startswith("http://127.0.0.1:17801/proxy/"))


class TestOkruFastProxy(unittest.TestCase):
    def _wrap(self, url: str) -> DownloadRequest:
        mgr = _make_manager()
        req = DownloadRequest(url=url, filename="clip.mp4", referer="https://ok.ru/video/123", source="video-bar-direct")
        with patch.object(mgr, "_probe_upstream") as pr:
            out = mgr.maybe_wrap_authenticated_download(req, 17801)
        return out, pr

    def test_okcdn_skips_probe_and_proxies(self):
        """ok.ru CDN'si YOKLAMA ATLANARAK anında köprüye alınır (IDM <1sn başlar)."""
        out, pr = self._wrap("https://vd335.okcdn.ru/file-get/abc?type=33&sig=x")
        self.assertFalse(pr.called, "fast-proxy host için yoklama çağrılmamalı")
        self.assertTrue(out.url.startswith("http://127.0.0.1:17801/proxy/"))

    def test_mycdn_and_vkuser_fast_hosts(self):
        for u in ("https://vd1.mycdn.me/getVideo?id=1", "https://vk-user.vkuser.net/f.mp4"):
            out, pr = self._wrap(u)
            self.assertFalse(pr.called)
            self.assertTrue(out.url.startswith("http://127.0.0.1:17801/proxy/"), u)

    def test_youtube_googlevideo_still_direct(self):
        """YouTube googlevideo RAW kalır (anında + gerçek URL davranışı korunur)."""
        mgr = _make_manager()
        req = DownloadRequest(url="https://rr4---sn-abc.googlevideo.com/videoplayback?id=o-x&itag=18", filename="v.mp4", source="video-bar-direct")
        with patch.object(mgr, "_probe_upstream", return_value=(False, "", req.url)):
            out = mgr.maybe_wrap_authenticated_download(req, 17801)
        self.assertTrue(out.url.startswith("https://rr4---sn-abc.googlevideo.com"))

    def test_fast_proxy_hosts_content(self):
        for h in ("ok.ru", "okcdn.ru", "mycdn.me", "vkuser.net", "userapi.com", "vk.com"):
            self.assertIn(h, _FAST_PROXY_HOSTS)


class TestTrialResetPlumbing(unittest.TestCase):
    def test_trial_reset_no_wine(self):
        import idm_linux.wine_sender as ws

        cfg = MagicMock()
        cfg.find_idm_exe.return_value = None
        sender = WineIdmSender(cfg)
        ok, msg = sender.trial_reset_idm()
        self.assertFalse(ok)
        self.assertIn("bulunamadı", msg)

    def test_registry_constants(self):
        sender = WineIdmSender(MagicMock())
        self.assertIn(r"HKCU\Software\DMCACount", sender._TRIAL_REG_PATHS)
        self.assertIn("fSn", sender._TRIAL_NAG_VALUES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
