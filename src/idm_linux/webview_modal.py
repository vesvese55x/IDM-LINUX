from __future__ import annotations

import atexit
import html
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .i18n import I18nManager, SUPPORTED_LANGUAGES
from .projects_data import (
    BELGESELSEMO_PREMIUM_URL,
    NOWPAYMENTS_DONATION_URL,
    NOWPAYMENTS_POS_URL,
    NOWPAYMENTS_WIDGET_URL,
)


IFRAME_MODE_URLS: Dict[str, str] = {
    "donation": NOWPAYMENTS_DONATION_URL,
    "pos": NOWPAYMENTS_POS_URL,
    "widget": NOWPAYMENTS_WIDGET_URL,
    "premium": BELGESELSEMO_PREMIUM_URL,
}

_GECKO_MARKERS = (
    "firefox",
    "librewolf",
    "waterfox",
    "floorp",
    "zen",
    "firedragon",
    "cachy-browser",
    "icecat",
    "palemoon",
    "tor-browser",
)

_CHROMIUM_CANDIDATES = (
    "brave-origin-nightly",
    "brave-origin-nightly-bin",
    "brave-browser",
    "brave-browser-nightly",
    "brave-browser-beta",
    "brave",
    "brave-bin",
    "chromium",
    "chromium-browser",
    "google-chrome-stable",
    "google-chrome",
    "microsoft-edge-stable",
    "microsoft-edge",
    "vivaldi-stable",
    "vivaldi",
    "thorium-browser",
    "helium-browser",
    "helium",
    "opera",
)

_GECKO_CANDIDATES = (
    "firefox",
    "firefox-esr",
    "cachy-browser",
    "firedragon",
    "zen-browser",
    "zen-bin",
    "librewolf",
    "floorp",
    "waterfox",
)


def build_iframe_shell_html(
    mode: str = "donation",
    lang_code: str = "tr",
    custom_url: Optional[str] = None,
) -> str:
    """Hedef URL'yi bağımsız pencere içinde tam boy <iframe> olarak gösteren koyu temalı HTML kabuğu."""
    i18n = I18nManager(lang_code)
    t = i18n.t
    spec = SUPPORTED_LANGUAGES.get(i18n.lang)
    dir_attr = "rtl" if (spec and spec.rtl) else "ltr"

    mode_clean = mode if mode in IFRAME_MODE_URLS else "donation"
    initial_url = custom_url or IFRAME_MODE_URLS[mode_clean]

    win_title = (
        f"{t('sup.m4_badge')} — BELGESELSEMO"
        if mode_clean == "premium"
        else t("sup.iframe_win_title")
    )
    lbl_don = html.escape(t("sup.iframe_tab_donation"))
    lbl_pos = html.escape(t("sup.iframe_tab_pos"))
    lbl_wid = html.escape(t("sup.iframe_tab_widget"))
    lbl_copy = html.escape(t("common.copy_link"))
    lbl_copied = html.escape(t("common.copied_title"))
    lbl_direct = html.escape(t("common.open_window"))

    esc_title = html.escape(win_title)
    esc_initial = html.escape(initial_url, quote=True)
    esc_don = html.escape(NOWPAYMENTS_DONATION_URL, quote=True)
    esc_pos = html.escape(NOWPAYMENTS_POS_URL, quote=True)
    esc_wid = html.escape(NOWPAYMENTS_WIDGET_URL, quote=True)

    is_nowpayments = mode_clean in ("donation", "pos", "widget") and not custom_url
    if is_nowpayments:
        act_don = "active" if mode_clean == "donation" else ""
        act_pos = "active" if mode_clean == "pos" else ""
        act_wid = "active" if mode_clean == "widget" else ""
        tabs_html = f"""
        <div class="seg-group" role="tablist">
          <button class="seg-btn {act_don}" data-url="{esc_don}" onclick="switchFrame(this)">{lbl_don}</button>
          <button class="seg-btn {act_pos}" data-url="{esc_pos}" onclick="switchFrame(this)">{lbl_pos}</button>
          <button class="seg-btn {act_wid}" data-url="{esc_wid}" onclick="switchFrame(this)">{lbl_wid}</button>
        </div>
        """
    else:
        tabs_html = f"""
        <div class="seg-group">
          <span class="url-pill" id="url-pill">{esc_initial}</span>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="{html.escape(i18n.lang)}" dir="{dir_attr}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc_title}</title>
  <style>
    :root {{
      --bg-bar: #0b1324;
      --bg-body: #0f172a;
      --border: #26354d;
      --accent: #0284c7;
      --accent-hi: #38bdf8;
      --fg: #f8fafc;
      --fg-sub: #94a3b8;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: var(--bg-body);
      color: var(--fg);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans", "DejaVu Sans", sans-serif;
      display: flex;
      flex-direction: column;
    }}
    .topbar {{
      height: 52px;
      min-height: 52px;
      background: linear-gradient(90deg, #0b1324 0%, #132038 100%);
      border-bottom: 1px solid var(--border);
      padding: 0 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      user-select: none;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }}
    .brand-dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: linear-gradient(135deg, #38bdf8, #10b981);
      box-shadow: 0 0 10px rgba(56, 189, 248, 0.65);
      flex-shrink: 0;
    }}
    .brand-title {{
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      color: #f1f5f9;
    }}
    .seg-group {{
      display: flex;
      align-items: center;
      gap: 6px;
      background: rgba(15, 23, 42, 0.78);
      padding: 4px;
      border-radius: 10px;
      border: 1px solid #1e293b;
    }}
    .seg-btn {{
      appearance: none;
      border: 0;
      background: transparent;
      color: var(--fg-sub);
      padding: 6px 12px;
      border-radius: 7px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.15s ease;
      white-space: nowrap;
    }}
    .seg-btn:hover {{
      color: #ffffff;
      background: rgba(56, 189, 248, 0.12);
    }}
    .seg-btn.active {{
      color: #ffffff;
      background: var(--accent);
      box-shadow: 0 2px 8px rgba(2, 132, 199, 0.45);
    }}
    .url-pill {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
      color: #38bdf8;
      padding: 4px 10px;
      max-width: 440px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .actions {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }}
    .act-btn {{
      appearance: none;
      border: 1px solid #334155;
      background: #1e293b;
      color: #e2e8f0;
      padding: 6px 11px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
      text-decoration: none;
    }}
    .act-btn:hover {{
      border-color: var(--accent-hi);
      color: #ffffff;
      background: #26354d;
    }}
    .frame-wrap {{
      position: relative;
      flex: 1 1 auto;
      width: 100%;
      height: calc(100vh - 52px);
      background: #0f172a;
    }}
    .loader {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      pointer-events: none;
      transition: opacity 0.25s ease;
      z-index: 1;
    }}
    .spinner {{
      width: 34px;
      height: 34px;
      border: 3px solid rgba(56, 189, 248, 0.22);
      border-top-color: #38bdf8;
      border-radius: 50%;
      animation: spin 0.75s linear infinite;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    iframe#main-frame {{
      position: relative;
      z-index: 2;
      width: 100%;
      height: 100%;
      border: 0;
      background: #ffffff;
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand">
      <span class="brand-dot"></span>
      <span class="brand-title">{esc_title}</span>
    </div>
    {tabs_html}
    <div class="actions">
      <button class="act-btn" onclick="window.location.href=currentUrl" title="Direct View">↗ {lbl_direct}</button>
      <button class="act-btn" id="copy-btn" onclick="copyCurrentUrl()">📋 {lbl_copy}</button>
    </div>
  </header>
  <main class="frame-wrap">
    <div class="loader" id="loader"><div class="spinner"></div></div>
    <iframe
      id="main-frame"
      src="{esc_initial}"
      allow="payment *; clipboard-write *; fullscreen *"
      referrerpolicy="no-referrer-when-downgrade"
      onload="document.getElementById('loader').style.opacity='0';"
    ></iframe>
  </main>
  <script>
    var currentUrl = "{esc_initial}";
    var defaultCopyLabel = "📋 {lbl_copy}";
    var copiedLabel = "✓ {lbl_copied}";
    function switchFrame(btn) {{
      var url = btn.getAttribute("data-url");
      if (!url) return;
      currentUrl = url;
      document.getElementById("loader").style.opacity = "1";
      document.getElementById("main-frame").src = url;
      var all = document.querySelectorAll(".seg-btn");
      for (var i = 0; i < all.length; i++) all[i].classList.remove("active");
      btn.classList.add("active");
    }}
    function copyCurrentUrl() {{
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(currentUrl);
      }}
      var b = document.getElementById("copy-btn");
      b.textContent = copiedLabel;
      setTimeout(function() {{ b.textContent = defaultCopyLabel; }}, 1600);
    }}
  </script>
</body>
</html>
"""


class _IframeRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        mode = (qs.get("mode", ["donation"])[0] or "donation").strip().lower()
        lang = (qs.get("lang", ["tr"])[0] or "tr").strip().lower()
        custom_url = (qs.get("url", [""])[0] or "").strip() or None
        if custom_url and not (custom_url.startswith("https://") or custom_url.startswith("http://")):
            custom_url = None

        body = build_iframe_shell_html(mode=mode, lang_code=lang, custom_url=custom_url).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class EmbeddedIframeHost:
    """Köprü servisi (daemon) kapalı olsa dahi bağımsız <iframe> sayfalarını sunan yerel HTTP sunucusu."""

    _instance: Optional["EmbeddedIframeHost"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.port: int = 0

    @classmethod
    def instance(cls) -> "EmbeddedIframeHost":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            cls._instance.ensure_running()
            return cls._instance

    def ensure_running(self) -> int:
        if self._server is not None and self.port > 0:
            return self.port
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _IframeRequestHandler)
        srv.daemon_threads = True
        self.port = int(srv.server_address[1])
        self._server = srv
        t = threading.Thread(target=srv.serve_forever, name="idm-linux-iframe-host", daemon=True)
        t.start()
        self._thread = t
        atexit.register(self.stop)
        return self.port

    def stop(self) -> None:
        srv = self._server
        self._server = None
        self.port = 0
        if srv is not None:
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass

    def build_url(self, mode: str = "donation", lang_code: str = "tr", custom_url: Optional[str] = None) -> str:
        port = self.ensure_running()
        params = {"mode": mode, "lang": lang_code}
        if custom_url:
            params["url"] = custom_url
        return f"http://127.0.0.1:{port}/iframe?{urllib.parse.urlencode(params)}"


def _temp_profile_base() -> Path:
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    return Path(tempfile.gettempdir()) / f"idm-linux-iframe-{uid}"


def cleanup_iframe_temp_profiles() -> None:
    base = _temp_profile_base()
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)


atexit.register(cleanup_iframe_temp_profiles)


def _extract_exec_from_desktop(desktop_name: str) -> Optional[Tuple[str, str]]:
    """Verilen .desktop dosyasından yürütülebilir tarayıcı yolunu ve ailesini ('chromium'|'gecko') bulur."""
    if not desktop_name:
        return None
    if not desktop_name.endswith(".desktop"):
        desktop_name += ".desktop"

    search_dirs = [
        Path.home() / ".local" / "share" / "applications",
        Path("/usr/local/share/applications"),
        Path("/usr/share/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
        Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
    ]
    for d in search_dirs:
        fp = d / desktop_name
        if not fp.is_file():
            continue
        try:
            for line in fp.read_text(encoding="utf-8", errors="ignore").splitlines():
                s = line.strip()
                if s.startswith("Exec="):
                    raw_cmd = s[5:].strip()
                    parts = [p for p in shlex.split(raw_cmd) if not p.startswith("%")]
                    if not parts:
                        break
                    # 'env VAR=1 /usr/bin/brave ...' sarmalayıcılarını soy
                    idx = 0
                    if os.path.basename(parts[0]) == "env":
                        idx = 1
                        while idx < len(parts) and "=" in parts[idx]:
                            idx += 1
                    if idx >= len(parts):
                        break
                    exe_cand = parts[idx]
                    resolved = exe_cand if os.path.isfile(exe_cand) else shutil.which(exe_cand)
                    if resolved:
                        low = (desktop_name + " " + os.path.basename(resolved)).lower()
                        fam = "gecko" if any(g in low for g in _GECKO_MARKERS) else "chromium"
                        return (resolved, fam)
                    break
        except Exception:
            continue
    return None


def _discover_window_browsers() -> List[Tuple[str, str]]:
    """
    Sistemdeki tarayıcıları (önce kullanıcının varsayılan tarayıcısı, sonra diğer kurulu tarayıcılar)
    [(binary_path, 'chromium'|'gecko'), ...] sırasıyla döndürür.
    """
    found: List[Tuple[str, str]] = []
    seen: set[str] = set()

    def _add(path: Optional[str], fam: str) -> None:
        if path and path not in seen and os.path.isfile(path) and os.access(path, os.X_OK):
            seen.add(path)
            found.append((path, fam))

    # 1. Kullanıcının XDG varsayılan tarayıcısını bul (.desktop üzerinden gerçek ikili yoluyla!)
    for cmd in (
        ["xdg-settings", "get", "default-web-browser"],
        ["xdg-mime", "query", "default", "x-scheme-handler/https"],
    ):
        if not shutil.which(cmd[0]):
            continue
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2, check=False)
            desk = (res.stdout or "").strip().splitlines()[0] if res.stdout else ""
            if desk and "idm-linux" not in desk.lower():
                parsed = _extract_exec_from_desktop(desk)
                if parsed:
                    _add(parsed[0], parsed[1])
        except Exception:
            pass

    # 2. Kurulu Chromium ailesi tarayıcılar (--app= ile gerçek sekmesiz pencere destekler!)
    for name in _CHROMIUM_CANDIDATES:
        _add(shutil.which(name), "chromium")

    for opt_p in (
        "/opt/brave.com/brave-origin-nightly/brave-origin-nightly",
        "/opt/brave.com/brave-nightly/brave-browser-nightly",
        "/opt/brave.com/brave/brave-browser",
        "/opt/google/chrome/google-chrome",
        "/opt/vivaldi/vivaldi",
        "/opt/microsoft/msedge/msedge",
    ):
        _add(opt_p, "chromium")

    # 3. Kurulu Firefox / Gecko ailesi tarayıcılar (--new-window ile ayrı pencere açar!)
    for name in _GECKO_CANDIDATES:
        _add(shutil.which(name), "gecko")

    return found


def _spawn_and_check_alive(cmd: List[str], env: Optional[Dict[str, str]] = None) -> bool:
    """Süreci başlatır; 0.25 sn içinde sıfır-dışı hata koduyla ölmediyse başarılı kabul eder."""
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
        time.sleep(0.22)
        rc = proc.poll()
        # rc == None (pencere açık çalışıyor) veya rc == 0 (mevcut tarayıcı sürecine IPC ile yeni pencere açtırdı!)
        return rc is None or rc == 0
    except Exception:
        return False


def _screen_size() -> Tuple[int, int]:
    """v2.8.5: xrandr ile ekran çözünürlüğü (yoksa makul varsayılan)."""
    xrandr = shutil.which("xrandr")
    if xrandr:
        try:
            out = subprocess.run([xrandr, "--current"], capture_output=True, text=True, timeout=5, check=False).stdout
            import re as _re

            m = _re.search(r"(\d+)x(\d+)\+0\+0", out) or _re.search(r"current (\d+) x (\d+)", out)
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
    return 1920, 1080


def _best_effort_resize(width: int, height: int) -> None:
    """v2.8.5: Wayland/GNOME'da tarayıcı --width/--height yutarsa wmctrl/xdotool ile ideal boya getir."""
    time.sleep(1.2)
    for tool in ("wmctrl", "xdotool"):
        binp = shutil.which(tool)
        if not binp:
            continue
        try:
            if tool == "wmctrl":
                subs = subprocess.run([binp, "-l"], capture_output=True, text=True, timeout=5, check=False).stdout
                wid = ""
                for line in subs.splitlines():
                    if "BELGESELSEMO" in line.upper() or "YÖNTEM" in line.upper() or "PREMIUM" in line.upper():
                        wid = line.split()[0]
                        break
                if wid:
                    subprocess.run([binp, "-i", "-r", wid, "-e", f"0,-1,-1,{width},{height}"], timeout=5, check=False)
                    return
            else:
                ids = subprocess.run([binp, "search", "--onlyvisible", "--name", "BELGESELSEMO"], capture_output=True, text=True, timeout=5, check=False).stdout.split()
                if ids:
                    subprocess.run([binp, "windowsize", ids[-1], str(width), str(height)], timeout=5, check=False)
                    return
        except Exception:
            continue


def open_standalone_iframe_window(
    mode: str = "donation",
    lang_code: str = "tr",
    custom_url: Optional[str] = None,
    width: int = 1160,
    height: int = 740,
) -> Tuple[bool, str]:
    """
    Hedef bağış / POS / Premium URL'sini tarayıcı sekmesi olarak DEĞİL,
    yeni bağımsız bir pencerede <iframe> olarak açar.
    """
    host = EmbeddedIframeHost.instance()
    local_url = host.build_url(mode=mode, lang_code=lang_code, custom_url=custom_url)

    # v2.8.5: pencereyi ekranı kaplamayan İDEAL boyutta ve ortalanmış aç
    scr_w, scr_h = _screen_size()
    width = min(width, max(720, scr_w - 120))
    height = min(height, max(480, int(scr_h * 0.72)))
    pos_x = max(0, (scr_w - width) // 2)
    pos_y = max(0, (scr_h - height) // 2 - 10)

    def _launch_bg() -> None:
        browsers = _discover_window_browsers()
        for bin_path, fam in browsers:
            if fam == "chromium":
                # v3.14.1 SANDBOX UYUMLULUĞU: root/kapsayıcı/userns kapalı ortamlarda
                # (veya araç daha önce engele takıldıysa — kalıcı hafıza) --no-sandbox ile aç
                try:
                    from .sandbox import sandbox_launch_args

                    compat_args = sandbox_launch_args(bin_path)
                except Exception:
                    compat_args = []
                # --app=<url> mevcut açık Brave/Chrome oturumuyla bile sekme açmadan yeni bağımsız uygulama penceresi açar!
                cmd = [
                    bin_path,
                    f"--app={local_url}",
                    f"--window-size={width},{height}",
                    f"--window-position={pos_x},{pos_y}",
                ]
                # v2.8.6: Wayland'da --window-size yutuluyor -> XWayland üzerinden aç (boyut GARANTİLİ)
                if os.environ.get("WAYLAND_DISPLAY"):
                    cmd.append("--ozone-platform=x11")
            else:
                # Firefox/Zen/LibreWolf: --no-remote KULLANMADAN --new-window ile yeni pencerede açar!
                compat_args = []
                env = dict(os.environ)
                if os.environ.get("WAYLAND_DISPLAY"):
                    env["MOZ_ENABLE_WAYLAND"] = "0"  # v2.8.6: X11'de aç -> --width/--height geçerli
                cmd = [
                    bin_path,
                    "--new-window",
                    f"--width={width}",
                    f"--height={height}",
                    local_url,
                ]
                threading.Thread(target=_best_effort_resize, args=(width, height), daemon=True).start()
            if _spawn_and_check_alive(cmd + compat_args, env=env if fam != "chromium" else None):
                return
            # v3.14.1: bayraksız başlatma öldüyse ve sandbox imzası varsa — aracı
            # KALICI işaretle ve --no-sandbox ile bir kez daha dene (kökten çözüm)
            if fam == "chromium" and not compat_args:
                try:
                    from .sandbox import looks_like_sandbox_error, remember_no_sandbox

                    diag = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        start_new_session=True,
                    )
                    time.sleep(0.9)
                    if diag.poll() is None:
                        return  # bu deneme canlı kaldı — pencere açıldı, sandbox sorunu yok
                    err_txt = ""
                    try:
                        err_txt = (diag.stderr.read() or b"").decode("utf-8", "ignore")
                    except Exception:
                        pass
                    if looks_like_sandbox_error(err_txt):
                        remember_no_sandbox(bin_path, reason=err_txt.strip()[:180])
                        compat_args = ["--no-sandbox"]
                        if _spawn_and_check_alive(cmd + compat_args):
                            return
                except Exception:
                    pass

        # Son çare: xdg-open ile yerel iframe kabuğunu aç
        xdg = shutil.which("xdg-open")
        if xdg:
            try:
                subprocess.Popen(
                    [xdg, local_url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception:
                pass

    # GUI ana iş parçacığını 0.22 sn bile bekletmemek için arka plan thread'de başlat!
    threading.Thread(target=_launch_bg, daemon=True).start()
    return True, local_url
