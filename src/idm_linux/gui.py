from __future__ import annotations

import json
import os
from datetime import datetime
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import __idm_target_build__, __version__
from .browsers import (
    auto_install_and_open_default_browser,
    create_native_host_wrapper,
    detect_default_browser,
    get_browser_targets,
    register_all_browsers,
)
from .config import abyss_code_ok, DEFAULT_HTTP_PORT, DEFAULT_WS_PORT, IdmLinuxConfig, get_cache_dir, get_data_dir
from .crx_builder import validate_extension_directory, verify_crx3_package
from .daemon import is_daemon_running
from .distro import detect_system, install_standalone_ytdlp
from .installer import (
    apply_idm_registry_tweaks,
    deploy_browser_extensions,
    execute_install_pipeline,
    get_wine_prefix_choices,
    neutralize_windows_hook_binaries,
    run_uninstall,
    scan_existing_idm_installations,
    sync_idm_language_live,
)
from .gui_pages import (
    build_about_idm_page,
    build_language_selector_page,
    build_other_projects_page,
    build_support_thank_you_page,
    load_window_icons,
    make_scrollable_area,
    pick_ui_font_family,
)
from .i18n import I18nManager, LANGUAGE_LIST, SUPPORTED_LANGUAGES



def _gui_timing(tag: str) -> None:
    """v2.8.9: acilis profillemesi — yavas adimi kesin bulmak icin log/logs/gui_timing.log"""
    try:
        d = get_cache_dir(create=True) / "logs"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "gui_timing.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.time():.3f} {tag}\n")
    except Exception:
        pass
from .rtl_shaper import contains_rtl, sanitize_tk_symbols, shape_rtl_for_tk
from .wine_sender import WineIdmSender


def can_launch_gui() -> bool:
    """Sistemde aktif bir grafik oturumu (Wayland/X11) ve Tkinter olup olmadığını sınar."""
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        return False
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.destroy()
        return True
    except Exception:
        return False


def _find_project_root() -> Path:
    # Yeni depo düzeni: uygulama ağacı src/idm_linux'tedir (extension/ bu dizinde).
    here = Path(__file__).resolve()
    cand = here.parents[0]
    if (cand / "extension").exists():
        return cand
    app_dir = get_data_dir(create=False) / "app"
    if (app_dir / "extension").exists():
        return app_dir
    return cand


def launch_control_panel(initial_page: str = "overview", project_root: Optional[Path] = None) -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as exc:
        print(f"  [!] Grafik arayüz (tkinter) başlatılamadı: {exc}")
        return 1

    proj_root = project_root or _find_project_root()
    cfg = IdmLinuxConfig.load(create_if_missing=False)
    i18n = I18nManager(cfg.language)
    # v2.8.9: sistem tespiti bile pencereyi BEKLEMEZ — arka planda dolar, arayüz anında kurulur
    _gui_timing("launch_start")

    class _SysInfoBox:
        distro_id = "linux"
        distro_name = "Linux"
        pkg_manager = ""
        init_system = "…"
        display_server = "…"
        wine_installed = False
        wine_version = ""
        ffmpeg_installed = False
        ytdlp_path = None
        tkinter_available = True
        aria2_installed = False

    sys_info = _SysInfoBox()

    def _fill_sys_info() -> None:
        try:
            real = detect_system(quick=True)
            for k in (
                "distro_id", "distro_name", "pkg_manager", "init_system", "display_server",
                "wine_installed", "wine_version", "ffmpeg_installed", "ytdlp_path",
                "tkinter_available", "aria2_installed",
            ):
                setattr(sys_info, k, getattr(real, k))
        except Exception:
            pass

    threading.Thread(target=_fill_sys_info, daemon=True).start()

    # Başlangıçta IDM kuruluysa sistemden/ayarlardan algılanan dili IDM'ye de otomatik senkronize et
    if cfg.find_idm_exe() is not None:
        def _sync_lang_job() -> None:
            try:
                from .installer import sync_idm_language_live as _sync_fn

                _sync_fn(cfg)
            except Exception:
                pass

        threading.Thread(target=_sync_lang_job, daemon=True).start()

    # Modern Koyu Slate & Neon Cyan/Emerald Renk Paleti
    BG_ROOT = "#090e17"
    BG_SIDEBAR = "#0f172a"
    BG_MAIN = "#0b1120"
    BG_CARD = "#131c31"
    BG_CARD_ALT = "#192540"
    BG_CONSOLE = "#050811"
    BG_INPUT = "#090e17"
    BORDER_SUBTLE = "#23324d"
    FG_TEXT = "#f8fafc"
    FG_MUTED = "#94a3b8"
    FG_GREEN = "#10b981"  # v2.9.4
    FG_DIM = "#64748b"
    ACCENT_CYAN = "#0ea5e9"
    ACCENT_HOVER = "#0284c7"
    ACCENT_GREEN = "#10b981"
    ACCENT_GREEN_DK = "#059669"
    ACCENT_AMBER = "#f59e0b"
    ACCENT_RED = "#ef4444"

    root = tk.Tk(className="idm-linux-panel")
    root.title(i18n.t("app.window_title", version=__version__))
    root.geometry("1150x755")
    root.minsize(990, 660)
    root.configure(bg=BG_ROOT)

    # Pencere başlık çubuğu ve görev çubuğu (Wayland/X11 taskbar) simgesini ata (X.org simgesini kaldırır!)
    _win_icons = load_window_icons(tk)
    if _win_icons:
        root._app_icons = _win_icons  # type: ignore[attr-defined]
        try:
            root.iconphoto(True, *_win_icons)
        except Exception:
            pass

    # v2.8.3 SPLASH: ana pencere hazırlanana dek sistem dilinde bilgi ekranı (sessiz 10-15 sn bekleyiş YOK!)
    # KRİTİK: root withdraw edilmeden splash etiket metinleri X11'de çizilmiyor (kanıtlanmış davranış)
    root.withdraw()
    splash = tk.Toplevel(root)
    splash.overrideredirect(True)
    splash.configure(bg="#0b1120")
    splash_w, splash_h = 520, 178
    splash.geometry(
        f"{splash_w}x{splash_h}+{(splash.winfo_screenwidth() - splash_w) // 2}+{(splash.winfo_screenheight() - splash_h) // 2}"
    )
    splash_box = tk.Frame(splash, bg="#0b1120", highlightthickness=1, highlightbackground="#23324d")
    splash_box.pack(fill="both", expand=True, padx=2, pady=2)
    tk.Label(splash_box, text="IDM LINUX", bg="#0b1120", fg="#0ea5e9", font=("DejaVu Sans", 20, "bold")).pack(pady=(26, 0))
    tk.Label(splash_box, text=f"v{__version__}", bg="#0b1120", fg="#64748b", font=("DejaVu Sans", 9)).pack()
    splash_msg = tk.Label(
        splash_box, text=i18n.t("splash.wait"), bg="#0b1120", fg="#f8fafc", font=("DejaVu Sans", 10, "bold")
    )
    splash_msg.pack(pady=(16, 0))
    splash_bar = tk.Frame(splash_box, bg="#131c31", height=4)
    splash_bar.pack(fill="x", padx=60, pady=(12, 0))
    import time as _time_mod
    try:
        splash.lift()
        # Expose olayları WM haritaladıktan SONRA gelir: metin çizimi için kısa olay pompası
        for _ in range(2):  # v2.9.0: pompa kısaltıldı (açılış hızı)
            splash.update_idletasks()
            splash.update()
            _time_mod.sleep(0.03)
    except Exception as _pexc:
        with open("/tmp/splash_dbg.log", "a", encoding="utf-8") as _fh:
            _fh.write(f"pump EXC {_pexc!r}\n")

    inst_sum_lbl_ref: List[Any] = []

    def _post_splash_build() -> None:
        _gui_timing("post_splash_start")
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        shell_holder = tk.Frame(root, bg=BG_ROOT)
        shell_holder.pack(fill="both", expand=True)


        active_timers: List[str] = []
        install_busy_ref = [False]
        inst_sum_lbl_ref: List[Any] = []
        current_page_ref = [initial_page]

        def _cancel_timers() -> None:
            while active_timers:
                tid = active_timers.pop()
                try:
                    root.after_cancel(tid)
                except Exception:
                    pass

        def _apply_ttk_styles(ui_font: str) -> None:
            style.configure("TFrame", background=BG_MAIN)
            style.configure("TLabel", background=BG_CARD, foreground=FG_TEXT, font=(ui_font, 10))
            style.configure(
                "Primary.TButton",
                background=ACCENT_CYAN,
                foreground="#ffffff",
                padding=(13, 8),
                font=(ui_font, 9, "bold"),
                borderwidth=0,
            )
            style.map("Primary.TButton", background=[("active", ACCENT_HOVER), ("disabled", "#334155")])

            style.configure(
                "Success.TButton",
                background=ACCENT_GREEN,
                foreground="#ffffff",
                padding=(15, 9),
                font=(ui_font, 9, "bold"),
                borderwidth=0,
            )
            style.map("Success.TButton", background=[("active", ACCENT_GREEN_DK), ("disabled", "#334155")])

            style.configure(
                "Danger.TButton",
                background="#b91c1c",
                foreground="#ffffff",
                padding=(12, 8),
                font=(ui_font, 9, "bold"),
                borderwidth=0,
            )
            style.map("Danger.TButton", background=[("active", ACCENT_RED)])

            style.configure(
                "Secondary.TButton",
                background="#1e293b",
                foreground="#e2e8f0",
                padding=(11, 7),
                font=(ui_font, 9, "bold"),
                borderwidth=0,
            )
            style.map("Secondary.TButton", background=[("active", "#334155")])

            style.configure(
                "Card.TCheckbutton",
                background=BG_CARD,
                foreground=FG_TEXT,
                font=(ui_font, 9),
            )
            style.map("Card.TCheckbutton", background=[("active", BG_CARD)])

            style.configure(
                "Card.TRadiobutton",
                background=BG_CARD_ALT,
                foreground=FG_TEXT,
                font=(ui_font, 9),
            )
            style.map("Card.TRadiobutton", background=[("active", BG_CARD_ALT)])

            # v3.2.1: dropdown/seçkeler GUI ile AYNI koyu temada (beyaz arkaplan gitti)
            style.configure(
                "TCombobox",
                fieldbackground=BG_INPUT,
                background=BG_INPUT,
                foreground=FG_TEXT,
                arrowcolor=FG_TEXT,
                bordercolor=BG_INPUT,
                lightcolor=BG_INPUT,
                darkcolor=BG_INPUT,
                selectbackground=ACCENT_CYAN,
                selectforeground="#0b1220",
            )
            style.map(
                "TCombobox",
                fieldbackground=[("readonly", BG_INPUT), ("disabled", BG_INPUT)],
                foreground=[("readonly", FG_TEXT), ("disabled", FG_MUTED)],
                arrowcolor=[("disabled", FG_MUTED)],
            )
            try:
                root.option_add("*TCombobox*Listbox.background", BG_INPUT)
                root.option_add("*TCombobox*Listbox.foreground", FG_TEXT)
                root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_CYAN)
                root.option_add("*TCombobox*Listbox.selectForeground", "#0b1220")
            except Exception:
                pass

            style.configure(
                "Idm.Horizontal.TProgressbar",
                troughcolor=BG_CONSOLE,
                background=ACCENT_GREEN,
                bordercolor=BORDER_SUBTLE,
                lightcolor=ACCENT_CYAN,
                darkcolor=ACCENT_GREEN,
                thickness=16,
            )

        def _switch_ui_language(new_code: str, target_page: Optional[str] = None) -> None:
            nonlocal cfg
            if install_busy_ref[0]:
                return
            code = i18n.set_language(new_code)
            cfg.language = code
            cfg.save()
            root.title(i18n.t("app.window_title", version=__version__))

            def _bg_sync_lang() -> None:
                sync_idm_language_live(cfg)
                try:
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{cfg.http_port}/api/config",
                        data=json.dumps(cfg.__dict__).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=2.5).read()
                except Exception:
                    pass

            threading.Thread(target=_bg_sync_lang, daemon=True).start()
            page_to_show = target_page or current_page_ref[0]
            _rebuild_shell(page_to_show)

        def _rebuild_shell(open_page: str) -> None:
            nonlocal cfg
            _cancel_timers()
            for child in shell_holder.winfo_children():
                child.destroy()

            raw_t = i18n.t

            def t(key: str, **kwargs: Any) -> str:
                val = sanitize_tk_symbols(raw_t(key, **kwargs))
                return shape_rtl_for_tk(val) if contains_rtl(val) else val

            ui_font = pick_ui_font_family(root, i18n.lang)
            _apply_ttk_styles(ui_font)
            root.title(raw_t("app.window_title", version=__version__))

            shell = tk.Frame(shell_holder, bg=BG_ROOT)
            shell.pack(fill="both", expand=True)

            sidebar = tk.Frame(shell, bg=BG_SIDEBAR, width=252, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
            sidebar.pack(side="left", fill="y")
            sidebar.pack_propagate(False)

            content_outer = tk.Frame(shell, bg=BG_MAIN)
            content_outer.pack(side="left", fill="both", expand=True)

            def _open_belgeselsemo(_event: Any = None) -> None:
                url = "https://belgeselsemo.com.tr"
                if shutil.which("xdg-open"):
                    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    webbrowser.open(url)

            # Alt İmza Kartı: İçerik alanındaki YÖNTEM / üst Hero kartlarıyla BİREBİR AYNI sol-sağ hizasında (padx=22) ve kart stilinde!
            CREDIT_BG = "#101b33"
            CREDIT_BORDER = "#243b61"
            credit_outer = tk.Frame(content_outer, bg=BG_MAIN)
            credit_outer.pack(side="bottom", fill="x", padx=22, pady=(2, 12))

            credit_bar = tk.Frame(
                credit_outer,
                bg=CREDIT_BG,
                padx=18,
                pady=8,
                highlightthickness=1,
                highlightbackground=CREDIT_BORDER,
            )
            credit_bar.pack(fill="x")

            credit_left = tk.Frame(credit_bar, bg=CREDIT_BG)
            credit_left.pack(side="left")
            tmpl = raw_t("footer.credit_template")
            for seg in re.split(r"(\{belgeselsemo\}|\{arena\}|\{zai\})", tmpl):
                if not seg:
                    continue
                if seg == "{belgeselsemo}":
                    tk.Label(credit_left, text="BELGESELSEMO", bg=CREDIT_BG, fg="#38bdf8", font=(ui_font, 8, "bold")).pack(side="left")
                elif seg == "{arena}":
                    tk.Label(credit_left, text="ARENA.AI", bg=CREDIT_BG, fg=ACCENT_GREEN, font=(ui_font, 8, "bold")).pack(side="left")
                elif seg == "{zai}":
                    # v3.12.0 (kullanıcı kararı): Z.AI de ARENA.AI ile AYNI yeşilimsi renkte
                    tk.Label(credit_left, text="Z.AI", bg=CREDIT_BG, fg=ACCENT_GREEN, font=(ui_font, 8, "bold")).pack(side="left")
                else:
                    seg_disp = shape_rtl_for_tk(seg) if contains_rtl(seg) else seg
                    tk.Label(credit_left, text=seg_disp, bg=CREDIT_BG, fg="#cbd5e1", font=(ui_font, 8)).pack(side="left")

            lbl_mail_link = tk.Label(
                credit_bar,
                text="semihsy54@gmail.com",
                bg=CREDIT_BG,
                fg="#fbbf24",
                cursor="hand2",
                font=(ui_font, 8, "bold"),
            )
            lbl_mail_link.pack(side="left", expand=True)

            def _open_mailto(_e: Any = None) -> None:
                def _bg() -> None:
                    for cmd in (
                        ["xdg-open", "mailto:semihsy54@gmail.com"],
                        ["gio", "open", "mailto:semihsy54@gmail.com"],
                    ):
                        if shutil.which(cmd[0]):
                            try:
                                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                return
                            except OSError:
                                continue
                threading.Thread(target=_bg, daemon=True).start()

            lbl_mail_link.bind("<Button-1>", _open_mailto)
            lbl_mail_link.bind("<Enter>", lambda _e: lbl_mail_link.configure(fg="#fde68a"))
            lbl_mail_link.bind("<Leave>", lambda _e: lbl_mail_link.configure(fg="#fbbf24"))

            lbl_site_link = tk.Label(
                credit_bar,
                text="https://belgeselsemo.com.tr ↗",
                bg=CREDIT_BG,
                fg="#38bdf8",
                cursor="hand2",
                font=(ui_font, 8, "bold", "underline"),
            )
            lbl_site_link.pack(side="right")
            lbl_site_link.bind("<Button-1>", _open_belgeselsemo)
            lbl_site_link.bind("<Enter>", lambda _e: lbl_site_link.configure(fg="#7dd3fc"))
            lbl_site_link.bind("<Leave>", lambda _e: lbl_site_link.configure(fg="#38bdf8"))

            content_host = tk.Frame(content_outer, bg=BG_MAIN)
            content_host.pack(side="top", fill="both", expand=True)

            # Sidebar Logo & Başlık
            brand_box = tk.Frame(sidebar, bg=BG_SIDEBAR, padx=16, pady=14)
            brand_box.pack(fill="x")

            _assets_root = Path(__file__).resolve().parent / "assets"
            _sidebar_icon_path = _assets_root / "idm_icon_48.png"
            if _sidebar_icon_path.is_file():
                try:
                    _sb_img = tk.PhotoImage(file=str(_sidebar_icon_path))
                    shell._sb_brand_icon = _sb_img  # type: ignore[attr-defined]
                    tk.Label(brand_box, image=_sb_img, bg=BG_SIDEBAR).pack(side="left")
                except Exception:
                    _sidebar_icon_path = Path("/nonexistent")

            if not _sidebar_icon_path.is_file():
                logo_cv = tk.Canvas(brand_box, width=42, height=42, bg=BG_SIDEBAR, highlightthickness=0)
                logo_cv.pack(side="left")
                logo_cv.create_oval(3, 3, 35, 35, fill="#0284c7", outline="#7dd3fc", width=1.5)

            brand_txt = tk.Frame(brand_box, bg=BG_SIDEBAR)
            brand_txt.pack(side="left", fill="x", expand=True, padx=(10, 0))
            tk.Label(brand_txt, text="IDM LINUX", bg=BG_SIDEBAR, fg=FG_TEXT, anchor="w", font=(ui_font, 13, "bold")).pack(fill="x")
            _raw_ver = cfg.detect_installed_idm_version() or __idm_target_build__
            _short_ver = _raw_ver.replace(" Build ", " b")
            lbl_brand_sub = tk.Label(
                brand_txt,
                text=f"v{__version__} • IDM {_short_ver}",
                bg=BG_SIDEBAR,
                fg=ACCENT_CYAN,
                anchor="w",
                justify="left",
                font=(ui_font, 8, "bold"),
            )
            lbl_brand_sub.pack(fill="x")

            tk.Frame(sidebar, bg=BORDER_SUBTLE, height=1).pack(fill="x", padx=14, pady=(0, 8))

            pages: Dict[str, tk.Frame] = {}
            nav_buttons: Dict[str, tk.Button] = {}

            def switch_page(page_key: str) -> None:
                # v2.9.0: henüz inşa edilmemiş gecikmeli sayfaya geçilirse anında inşa et
                try:
                    _pend = deferred_builders.pop(page_key, None)
                    if _pend:
                        _pend()
                except Exception:
                    pass
                current_page_ref[0] = page_key
                for k, frame in pages.items():
                    if k == page_key:
                        frame.pack(fill="both", expand=True)
                    else:
                        frame.pack_forget()
                for k, btn in nav_buttons.items():
                    if k == page_key:
                        btn.configure(bg="#1e293b", fg="#38bdf8", activebackground="#1e293b", activeforeground="#38bdf8")
                    else:
                        btn.configure(bg=BG_SIDEBAR, fg=FG_MUTED, activebackground="#162036", activeforeground=FG_TEXT)

            _nav_flag_img: Optional[Any] = None
            _nav_flag_path = _assets_root / f"flag_{i18n.lang}.png"
            if _nav_flag_path.is_file():
                try:
                    # 40x28 bayraktan sol menü için zarif 20x14 boyuta subsample(2, 2)
                    _full_flg = tk.PhotoImage(file=str(_nav_flag_path))
                    _nav_flag_img = _full_flg.subsample(2, 2)
                    shell._sb_nav_flag = _nav_flag_img  # type: ignore[attr-defined]
                except Exception:
                    _nav_flag_img = None

            nav_items = [
                ("installer", t("nav.installer")),
                ("overview", t("nav.overview")),
                ("browsers", t("nav.browsers")),
                ("settings", t("nav.settings")),
                ("doctor", t("nav.doctor")),
                ("projects", t("nav.projects")),
                ("support", t("nav.support")),
                ("language", f"{t('nav.language')} [{i18n.lang.upper()}]"),
                ("about", t("nav.about")),  # v3.4.0: 9. seçenek — IDM Hakkında
            ]

            for idx_nav, (key, label) in enumerate(nav_items):
                if idx_nav in (5, 7, 8):
                    tk.Frame(sidebar, bg=BORDER_SUBTLE, height=1).pack(fill="x", padx=14, pady=(5, 5))
                p_frame = tk.Frame(content_host, bg=BG_MAIN, padx=22, pady=12)
                pages[key] = p_frame
                btn_kwargs: Dict[str, Any] = {}
                if key == "language" and _nav_flag_img is not None:
                    btn_kwargs = {"image": _nav_flag_img, "compound": "right"}
                b = tk.Button(
                    sidebar,
                    text=f"{label}  " if btn_kwargs else label,
                    anchor="w",
                    padx=14,
                    pady=7,
                    relief="flat",
                    bd=0,
                    bg=BG_SIDEBAR,
                    fg=FG_MUTED,
                    activebackground="#162036",
                    activeforeground=FG_TEXT,
                    highlightthickness=0,
                    cursor="hand2",
                    font=(ui_font, 9, "bold"),
                    command=lambda k=key: switch_page(k),
                    **btn_kwargs,
                )
                b.pack(fill="x", padx=10, pady=1)
                nav_buttons[key] = b

            # Sidebar Alt: Köprü/Sistem Bilgi Kartı VE BELGESELSEMO × ARENA.AI Rozeti (BİREBİR AYNI KART TASARIMINDA!)
            SIDE_BADGE_BG = "#131c31"
            sidebar_footer = tk.Frame(sidebar, bg=BG_SIDEBAR, padx=14, pady=12)
            sidebar_footer.pack(side="bottom", fill="x")

            side_clock_box = tk.Frame(
                sidebar_footer,
                bg=SIDE_BADGE_BG,
                padx=10,
                pady=8,
                highlightthickness=1,
                highlightbackground=BORDER_SUBTLE,
            )
            side_clock_box.pack(fill="x", pady=(0, 8))
            lbl_side_clock = tk.Label(
                side_clock_box,
                text=datetime.now().strftime("%H:%M"),
                bg=SIDE_BADGE_BG,
                fg="#e2e8f0",
                font=(ui_font, 15, "bold"),
            )
            lbl_side_clock.pack(anchor="w")
            lbl_side_date = tk.Label(
                side_clock_box,
                text="",
                bg=SIDE_BADGE_BG,
                fg="#94a3b8",
                font=(ui_font, 8, "bold"),
            )
            lbl_side_date.pack(anchor="w", pady=(2, 0))

            clock_timer_ref: List[Any] = []

            def _tick_clock() -> None:
                if not shell.winfo_exists():
                    return
                now = datetime.now()
                lbl_side_clock.configure(text=now.strftime("%H:%M"))
                wd_list = [w.strip() for w in raw_t("clock.weekdays").split(",")]
                wd_name = wd_list[now.weekday()] if len(wd_list) > now.weekday() else ""
                lbl_side_date.configure(text=f"{now.strftime('%d.%m.%Y')} - {wd_name}")
                if clock_timer_ref:
                    try:
                        root.after_cancel(clock_timer_ref[0])
                    except Exception:
                        pass
                clock_timer_ref[:] = [root.after(1000, _tick_clock)]

            _tick_clock()

            side_info_box = tk.Frame(
                sidebar_footer,
                bg=SIDE_BADGE_BG,
                padx=10,
                pady=8,
                highlightthickness=1,
                highlightbackground=BORDER_SUBTLE,
            )
            side_info_box.pack(fill="x", pady=(0, 8))

            lbl_side_daemon = tk.Label(
                side_info_box,
                text=t("side.bridge_checking"),
                bg=SIDE_BADGE_BG,
                fg=ACCENT_AMBER,
                font=(ui_font, 8, "bold"),
            )
            lbl_side_daemon.pack(anchor="w")
            lbl_side_distro = tk.Label(
                side_info_box,
                text=f"{sys_info.distro_name}\n{sys_info.display_server.upper()} • {sys_info.pkg_manager}",
                bg=SIDE_BADGE_BG,
                fg="#94a3b8",
                justify="left",
                font=(ui_font, 8),
            )
            lbl_side_distro.pack(anchor="w", pady=(3, 0))

            side_credit_box = tk.Frame(
                sidebar_footer,
                bg=SIDE_BADGE_BG,
                padx=10,
                pady=8,
                highlightthickness=1,
                highlightbackground=BORDER_SUBTLE,
            )
            side_credit_box.pack(fill="x")
            tk.Label(
                side_credit_box,
                text="BELGESELSEMO × ARENA.AI & Z.AI",
                bg=SIDE_BADGE_BG,
                fg="#38bdf8",
                font=(ui_font, 8, "bold"),
            ).pack(anchor="w")
            # v3.10.0 (kullanıcı kararı): alt bilgi cümlesi sidebar rozetinde de yazar
            tk.Label(
                side_credit_box,
                text=t("footer.credit_template", belgeselsemo="BELGESELSEMO", arena="ARENA.AI", zai="Z.AI"),
                bg=SIDE_BADGE_BG,
                fg="#cbd5e1",
                font=(ui_font, 7),
                wraplength=196,
                justify="left",
            ).pack(anchor="w", pady=(2, 0))
            lbl_side_url = tk.Label(
                side_credit_box,
                text="belgeselsemo.com.tr ↗",
                bg=SIDE_BADGE_BG,
                fg=ACCENT_GREEN,
                cursor="hand2",
                font=(ui_font, 8, "underline"),
            )
            lbl_side_url.pack(anchor="w", pady=(2, 0))
            lbl_side_url.bind("<Button-1>", _open_belgeselsemo)

            def copy_to_clipboard(text: str, toast_msg: Optional[str] = None) -> None:
                root.clipboard_clear()
                root.clipboard_append(text)
                root.update_idletasks()
                try:
                    if splash.winfo_exists():
                        splash.update_idletasks()
                        splash.update()
                except Exception:
                    pass

                if toast_msg:
                    messagebox.showinfo(t("common.copied_title"), toast_msg)

            def make_card(parent: tk.Widget, title: str = "", subtitle: str = "", pady: Tuple[int, int] = (0, 11)) -> tk.Frame:
                outer = tk.Frame(parent, bg=BG_CARD, padx=16, pady=12, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
                outer.pack(fill="x", pady=pady)
                if title:
                    hdr = tk.Frame(outer, bg=BG_CARD)
                    hdr.pack(fill="x", pady=(0, 7))
                    tk.Label(hdr, text=title, bg=BG_CARD, fg=FG_TEXT, font=(ui_font, 11, "bold")).pack(side="left")
                    if subtitle:
                        tk.Label(hdr, text=subtitle, bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 9)).pack(side="right")
                return outer

            # ==================================================================
            # SAYFA 1: 🚀 KURULUM & GÜNCELLEME SİHİRBAZI
            # ==================================================================
            pg_inst = pages["installer"]

            inst_hdr = tk.Frame(pg_inst, bg=BG_MAIN)
            inst_hdr.pack(fill="x", pady=(0, 10))
            tk.Label(inst_hdr, text=t("inst.title"), bg=BG_MAIN, fg=FG_TEXT, font=(ui_font, 14, "bold")).pack(anchor="w")
            inst_sum_lbl = tk.Label(
                inst_hdr,
                text=t(
                    "inst.sys_summary",
                    distro=sys_info.distro_name,
                    pm=sys_info.pkg_manager,
                    wine=sys_info.wine_version if sys_info.wine_installed else t("inst.auto_install"),
                    ytdlp="✓" if sys_info.ytdlp_path else t("inst.will_download"),
                    ffmpeg="✓" if sys_info.ffmpeg_installed else t("inst.will_install"),
                    aria2="✓" if sys_info.aria2_installed else t("inst.will_install"),
                ),
                bg=BG_MAIN,
                fg=ACCENT_CYAN,
                font=(ui_font, 9, "bold"),
            )
            inst_sum_lbl.pack(anchor="w", pady=(3, 0))
            inst_sum_lbl_ref.append(inst_sum_lbl)

            existing_list: List[Any] = []  # v2.8.3: tarama arka planda (açılış bloklanmaz)
            var_inst_action = tk.StringVar(value="fresh")

            exist_card = make_card(pg_inst, title=t("inst.card1_title"), subtitle=t("inst.card1_sub"))
            exist_body = tk.Frame(exist_card, bg=BG_CARD)
            exist_body.pack(fill="x")

            def render_existing_box(scanned: Optional[List[Any]] = None) -> None:
                for w in exist_body.winfo_children():
                    w.destroy()
                nonlocal existing_list
                existing_list = scanned if scanned is not None else scan_existing_idm_installations()
                if not existing_list:
                    var_inst_action.set("fresh")
                    tk.Label(
                        exist_body,
                        text=t("inst.clean_ready"),
                        bg=BG_CARD,
                        fg=ACCENT_GREEN,
                        font=(ui_font, 10, "bold"),
                    ).pack(anchor="w")
                    return

                if var_inst_action.get() == "fresh":
                    var_inst_action.set("clean")

                det_txt = t("inst.detected_prefix", items="  |  ".join(f"{e.label}" for e in existing_list))
                tk.Label(
                    exist_body,
                    text=det_txt,
                    bg=BG_CARD,
                    fg=ACCENT_AMBER,
                    font=(ui_font, 9, "bold"),
                    wraplength=780,
                    justify="left",
                ).pack(anchor="w", pady=(0, 6))
                modes_box = tk.Frame(exist_body, bg=BG_CARD_ALT, padx=10, pady=8, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
                modes_box.pack(fill="x")
                for val_k, txt_k in (
                    ("clean", "inst.opt_clean"),
                    ("update", "inst.opt_update"),
                    ("uninstall", "inst.opt_uninstall"),
                ):
                    ttk.Radiobutton(
                        modes_box,
                        text=t(txt_k),
                        value=val_k,
                        variable=var_inst_action,
                        style="Card.TRadiobutton",
                    ).pack(anchor="w", pady=2)

            def _async_scan_existing() -> None:
                def _bg_scan() -> None:
                    try:
                        scanned = scan_existing_idm_installations()
                    except Exception:
                        scanned = []
                    try:
                        root.after(0, lambda: render_existing_box(scanned))
                    except RuntimeError:
                        pass

                threading.Thread(target=_bg_scan, daemon=True).start()

            _async_scan_existing()

            env_card = make_card(pg_inst, title=t("inst.card2_title"), subtitle=t("inst.card2_sub"))
            pfx_choices = get_wine_prefix_choices()
            default_pfx_str = str(pfx_choices[0][1]) if pfx_choices else cfg.wine_prefix
            var_inst_pfx = tk.StringVar(value=default_pfx_str)
            var_inst_dldir = tk.StringVar(value=cfg.download_dir)
            var_inst_lang_ct = tk.BooleanVar(value=True)
            var_inst_warm = tk.BooleanVar(value=cfg.keep_wine_warm)
            var_inst_desk = tk.BooleanVar(value=True)
            var_inst_autobrowser = tk.BooleanVar(value=True)

            row_pfx = tk.Frame(env_card, bg=BG_CARD)
            row_pfx.pack(fill="x", pady=(0, 6))
            tk.Label(row_pfx, text=t("inst.lbl_prefix"), width=26, anchor="w", bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 9, "bold")).pack(side="left")
            cmb_inst_pfx = ttk.Combobox(row_pfx, textvariable=var_inst_pfx, values=[str(p) for _, p in pfx_choices])
            cmb_inst_pfx.pack(side="left", fill="x", expand=True, padx=(0, 8))

            def _browse_inst_pfx() -> None:
                chosen = filedialog.askdirectory(initialdir=var_inst_pfx.get())
                if chosen:
                    var_inst_pfx.set(chosen)

            ttk.Button(row_pfx, text=t("common.browse"), style="Secondary.TButton", command=_browse_inst_pfx).pack(side="left")

            row_dl = tk.Frame(env_card, bg=BG_CARD)
            row_dl.pack(fill="x", pady=(0, 8))
            tk.Label(row_dl, text=t("inst.lbl_dldir"), width=26, anchor="w", bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 9, "bold")).pack(side="left")
            ent_inst_dl = tk.Entry(row_dl, textvariable=var_inst_dldir, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat")
            ent_inst_dl.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))

            def _browse_inst_dl() -> None:
                chosen = filedialog.askdirectory(initialdir=var_inst_dldir.get())
                if chosen:
                    var_inst_dldir.set(chosen)

            ttk.Button(row_dl, text=t("common.browse"), style="Secondary.TButton", command=_browse_inst_dl).pack(side="left")

            chk_grid = tk.Frame(env_card, bg=BG_CARD)
            chk_grid.pack(fill="x")
            ttk.Checkbutton(chk_grid, text=t("inst.chk_lang_ct"), variable=var_inst_lang_ct, style="Card.TCheckbutton").pack(side="left", padx=(0, 12))
            ttk.Checkbutton(chk_grid, text=t("inst.chk_warm"), variable=var_inst_warm, style="Card.TCheckbutton").pack(side="left", padx=(0, 12))
            ttk.Checkbutton(chk_grid, text=t("inst.chk_desktop"), variable=var_inst_desk, style="Card.TCheckbutton").pack(side="left", padx=(0, 12))
            ttk.Checkbutton(chk_grid, text=t("inst.chk_autobrowser"), variable=var_inst_autobrowser, style="Card.TCheckbutton").pack(side="left")

            run_card = tk.Frame(pg_inst, bg=BG_CARD, padx=16, pady=12, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
            run_card.pack(fill="both", expand=True)

            prog_top = tk.Frame(run_card, bg=BG_CARD)
            prog_top.pack(fill="x", pady=(0, 6))
            lbl_inst_stage = tk.Label(prog_top, text=t("inst.stage_ready"), bg=BG_CARD, fg=FG_TEXT, font=(ui_font, 10, "bold"))
            lbl_inst_stage.pack(side="left")
            lbl_inst_pct = tk.Label(prog_top, text="0%", bg=BG_CARD, fg=ACCENT_CYAN, font=(ui_font, 10, "bold"))
            lbl_inst_pct.pack(side="right")

            inst_pbar = ttk.Progressbar(run_card, orient="horizontal", mode="determinate", maximum=100, style="Idm.Horizontal.TProgressbar")
            inst_pbar.pack(fill="x", pady=(0, 10))

            act_bar = tk.Frame(run_card, bg=BG_CARD)
            act_bar.pack(fill="x", pady=(0, 8))

            btn_start_install = ttk.Button(act_bar, text=t("inst.btn_start"), style="Success.TButton")
            btn_start_install.pack(side="left")

            btn_direct_uninstall = ttk.Button(act_bar, text=t("inst.btn_uninstall"), style="Danger.TButton")
            btn_direct_uninstall.pack(side="left", padx=(10, 0))

            post_actions_frame = tk.Frame(act_bar, bg=BG_CARD)
            post_actions_frame.pack(side="right")

            console_wrap = tk.Frame(run_card, bg=BG_CONSOLE, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
            console_wrap.pack(fill="both", expand=True)

            inst_log_txt = tk.Text(
                console_wrap,
                bg=BG_CONSOLE,
                fg="#cbd5e1",
                font=("Monospace", 9),
                height=6,
                relief="flat",
                padx=10,
                pady=8,
                wrap="word",
                state="disabled",
            )
            inst_scroll = ttk.Scrollbar(console_wrap, orient="vertical", command=inst_log_txt.yview)
            inst_log_txt.configure(yscrollcommand=inst_scroll.set)
            inst_scroll.pack(side="right", fill="y")
            inst_log_txt.pack(side="left", fill="both", expand=True)

            inst_log_txt.tag_configure("ok", foreground="#4ade80")
            inst_log_txt.tag_configure("info", foreground="#38bdf8")
            inst_log_txt.tag_configure("warn", foreground="#fbbf24")
            inst_log_txt.tag_configure("err", foreground="#f87171")

            ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()

            def append_inst_log(line: str) -> None:
                inst_log_txt.configure(state="normal")
                tag = ""
                if "[✓]" in line:
                    tag = "ok"
                elif "[*]" in line or "->" in line:
                    tag = "info"
                elif "[!]" in line:
                    tag = "warn"
                elif "[✗]" in line or "Error" in line or "Hata" in line:
                    tag = "err"
                inst_log_txt.insert("end", line + "\n", (tag,) if tag else ())
                inst_log_txt.see("end")
                inst_log_txt.configure(state="disabled")

            append_inst_log(t("inst.log_ready", version=__version__))
            append_inst_log(t("inst.log_default_pfx", prefix=default_pfx_str))
            append_inst_log(t("inst.log_ports", http_port=DEFAULT_HTTP_PORT, ws_port=DEFAULT_WS_PORT))

            def _populate_post_install_buttons(res: Any) -> None:
                for w in post_actions_frame.winfo_children():
                    w.destroy()

                def _auto_open_and_install_ext() -> None:
                    c_now = IdmLinuxConfig.load(create_if_missing=False)
                    ok, msg = auto_install_and_open_default_browser(
                        http_port=c_now.http_port,
                        chrom_ext_dir=res.chrom_ext_dir,
                        ff_xpi_path=res.ff_xpi_path,
                        restart_if_running=False,
                    )
                    append_inst_log(f"  [{'✓' if ok else '!'}] {msg}")

                ttk.Button(post_actions_frame, text=t("inst.post_ext_btn"), style="Primary.TButton", command=_auto_open_and_install_ext).pack(
                    side="left", padx=4
                )
                ttk.Button(
                    post_actions_frame,
                    text=t("inst.post_open_idm"),
                    style="Secondary.TButton",
                    command=lambda: WineIdmSender(IdmLinuxConfig.load(create_if_missing=False)).open_idm_window(),
                ).pack(side="left", padx=4)
                ttk.Button(
                    post_actions_frame,
                    text=t("inst.post_panel_btn"),
                    style="Secondary.TButton",
                    command=lambda: switch_page("overview"),
                ).pack(side="left", padx=4)

            def _drain_ui_queue() -> None:
                if not shell.winfo_exists():
                    return
                try:
                    while True:
                        kind, payload = ui_queue.get_nowait()
                        if kind == "log":
                            append_inst_log(str(payload))
                        elif kind == "progress":
                            pct, title = payload
                            inst_pbar["value"] = pct
                            lbl_inst_pct.configure(text=f"{pct}%")
                            lbl_inst_stage.configure(text=title, fg=FG_TEXT)
                        elif kind == "done_install":
                            res = payload
                            btn_start_install.configure(state="normal", text=t("inst.btn_reinstall"))
                            btn_direct_uninstall.configure(state="normal")
                            lbl_inst_stage.configure(text=t("inst.done_ok"), fg=ACCENT_GREEN)
                            render_existing_box()
                            _populate_post_install_buttons(res)
                            _refresh_all_status_once()
                        elif kind == "done_uninstall":
                            btn_start_install.configure(state="normal", text=t("inst.btn_start"))
                            btn_direct_uninstall.configure(state="normal")
                            inst_pbar["value"] = 100
                            lbl_inst_pct.configure(text="100%")
                            lbl_inst_stage.configure(text=t("inst.done_uninstalled"), fg=ACCENT_GREEN)
                            render_existing_box()
                            render_browser_rows()
                            _reload_logs()
                            _refresh_all_status_once()
                            messagebox.showinfo(t("inst.uninstalled_popup_title"), t("inst.uninstalled_popup_body"))
                        elif kind == "error":
                            btn_start_install.configure(state="normal", text=t("inst.btn_retry"))
                            btn_direct_uninstall.configure(state="normal")
                            lbl_inst_stage.configure(text=t("inst.err_prefix", error=payload), fg=ACCENT_RED)
                            append_inst_log(f"  [✗] {t('inst.err_prefix', error=payload)}")
                except queue.Empty:
                    pass
                # v3.11.0 SIZINTI DÜZELTMESİ: kendini yeniden zamanlayan kalıcı döngülerin
                # timer id'leri artık active_timers'a EKLENMEZ. Eski akış her 60 ms'de
                # bir ölü id biriktiriyordu (≈57.600 ölü id/saat — bellek şişmesi).
                # _cancel_timers() yalnız tek-seferlik bekleyen id'lere ihtiyaç duyar;
                # bu döngü zaten shell öldüğünde kendi kendine durur.
                root.after(60, _drain_ui_queue)

            def _start_install_worker() -> None:
                if install_busy_ref[0]:
                    return
                action = var_inst_action.get()
                if action == "uninstall":
                    if not messagebox.askyesno(t("inst.confirm_uninstall_title"), t("inst.confirm_uninstall_body")):
                        return

                install_busy_ref[0] = True
                btn_start_install.configure(state="disabled", text=t("inst.btn_busy"))
                btn_direct_uninstall.configure(state="disabled")
                for w in post_actions_frame.winfo_children():
                    w.destroy()
                inst_log_txt.configure(state="normal")
                inst_log_txt.delete("1.0", "end")
                inst_log_txt.configure(state="disabled")

                chosen_pfx = Path(var_inst_pfx.get().strip() or default_pfx_str)
                chosen_dl = Path(var_inst_dldir.get().strip() or cfg.download_dir)
                lang_code = i18n.lang if var_inst_lang_ct.get() else "en"
                warm_flag = var_inst_warm.get()
                desk_flag = var_inst_desk.get()
                autobrowser_flag = var_inst_autobrowser.get()

                def _worker() -> None:
                    nonlocal cfg
                    try:
                        if action == "uninstall":
                            ui_queue.put(("progress", (25, t("inst.btn_busy"))))
                            run_uninstall(remove_wine_idm=True, log_fn=lambda s: ui_queue.put(("log", s)))
                            ui_queue.put(("done_uninstall", None))
                            return

                        res = execute_install_pipeline(
                            project_root=proj_root,
                            chosen_prefix=chosen_pfx,
                            download_dir=chosen_dl,
                            existing_action=action,
                            existing_items=existing_list,
                            language=lang_code,
                            keep_wine_warm=warm_flag,
                            create_desktop_icons=desk_flag,
                            auto_open_browser=autobrowser_flag,
                            prefer_gui_auth=True,
                            log_fn=lambda s: ui_queue.put(("log", s)),
                            progress_cb=lambda p, st: ui_queue.put(("progress", (p, st))),
                        )
                        cfg = IdmLinuxConfig.load(create_if_missing=False)
                        ui_queue.put(("done_install", res))
                    except Exception as exc:
                        ui_queue.put(("error", str(exc)))
                    finally:
                        install_busy_ref[0] = False

                threading.Thread(target=_worker, daemon=True).start()

            def _trigger_direct_uninstall() -> None:
                if install_busy_ref[0]:
                    return
                switch_page("installer")
                var_inst_action.set("uninstall")
                _start_install_worker()

            btn_start_install.configure(command=_start_install_worker)
            btn_direct_uninstall.configure(command=_trigger_direct_uninstall)

            # ==================================================================
            # SAYFA 2: 📊 GENEL BAKIŞ & HIZLI İNDİRME
            # v3.6.0: sayfa içeriği artık KAYDIRILABİLİR (IDM Hakkında sayfası gibi);
            # 'Bu araç ... yapılmıştır' alt imza kartı zaten genel düzende sabit durur.
            # ==================================================================
            pg_ov = make_scrollable_area(tk, ttk, pages["overview"], BG_MAIN)

            ov_hdr = tk.Frame(pg_ov, bg=BG_MAIN)
            ov_hdr.pack(fill="x", pady=(0, 12))
            tk.Label(ov_hdr, text=t("ov.title"), bg=BG_MAIN, fg=FG_TEXT, font=(ui_font, 14, "bold")).pack(side="left")

            cards_row = tk.Frame(pg_ov, bg=BG_MAIN)
            cards_row.pack(fill="x", pady=(0, 12))
            for i in range(4):
                cards_row.columnconfigure(i, weight=1)

            def _stat_card(col: int, title: str) -> tk.Label:
                c = tk.Frame(cards_row, bg=BG_CARD, padx=14, pady=12, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
                c.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0 if col == 3 else 6))
                tk.Label(c, text=title, bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 9)).pack(anchor="w")
                val = tk.Label(c, text="...", bg=BG_CARD, fg=FG_TEXT, font=(ui_font, 12, "bold"))
                val.pack(anchor="w", pady=(6, 0))
                return val

            lbl_ov_daemon = _stat_card(0, t("ov.stat_bridge", ws=cfg.ws_port, http=cfg.http_port))
            lbl_ov_idm = _stat_card(1, t("ov.stat_idm"))
            lbl_ov_media = _stat_card(2, t("ov.stat_media"))
            lbl_ov_count = _stat_card(3, t("ov.stat_count"))

            quick_dl_card = make_card(pg_ov, title=t("ov.quick_title"), subtitle=t("ov.quick_sub"))
            q_row = tk.Frame(quick_dl_card, bg=BG_CARD)
            q_row.pack(fill="x")
            var_quick_url = tk.StringVar()
            ent_quick_url = tk.Entry(
                q_row,
                textvariable=var_quick_url,
                bg=BG_INPUT,
                fg=FG_TEXT,
                insertbackground=FG_TEXT,
                relief="flat",
                font=(ui_font, 10),
            )
            ent_quick_url.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

            def _ensure_daemon_up(c_now: IdmLinuxConfig) -> bool:
                if is_daemon_running(c_now):
                    return True
                subprocess.Popen(
                    [sys.executable, "-m", "idm_linux.cli", "start"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                import time as _t
                for _ in range(12):
                    _t.sleep(0.2)
                    if is_daemon_running(c_now):
                        return True
                return False

            def _paste_quick_url() -> None:
                try:
                    clip = root.clipboard_get().strip()
                    if clip:
                        var_quick_url.set(clip)
                except Exception:
                    pass

            def _pick_local_torrent_file() -> None:
                chosen = filedialog.askopenfilename(
                    title=t("ov.pick_torrent_title"),
                    filetypes=[("BitTorrent", "*.torrent"), ("*", "*.*")],
                )
                if not chosen:
                    return
                var_quick_url.set(chosen)
                _send_quick_url()

            def _open_hls_mode_dialog(target_url: str) -> None:
                from .hls_streamer import looks_like_hls_url as _lk

                if not _lk(target_url):
                    return
                dlg = tk.Toplevel(root)
                dlg.title(t("ov.hls_title"))
                dlg.geometry("460x250")
                dlg.configure(bg=BG_CARD)
                dlg.transient(root)
                dlg.grab_set()
                tk.Label(dlg, text=t("ov.hls_desc"), bg=BG_CARD, fg=FG_TEXT, font=(ui_font, 9, "bold"), wraplength=420, justify="left").pack(padx=14, pady=(14, 8), anchor="w")
                var_mode = tk.StringVar(value="dvr")
                for val, key in (("dvr", "ov.hls_mode_dvr"), ("live", "ov.hls_mode_live"), ("vod", "ov.hls_mode_vod")):
                    ttk.Radiobutton(dlg, text=t(key), value=val, variable=var_mode, style="Card.TRadiobutton").pack(anchor="w", padx=22, pady=1)
                tk.Label(dlg, text=t("ov.hls_name_lbl"), bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 8, "bold")).pack(anchor="w", padx=22, pady=(8, 2))
                default_name = urllib.parse.unquote(urllib.parse.urlparse(target_url).path.rsplit("/", 1)[-1] or "canli-yayin")
                default_name = Path(default_name).stem or "canli-yayin"
                ent_name = tk.Entry(dlg, bg=BG_CONSOLE, fg=FG_TEXT, insertbackground=FG_TEXT, font=(ui_font, 9))
                ent_name.insert(0, default_name)
                ent_name.pack(fill="x", padx=22)

                def _go() -> None:
                    nm = ent_name.get().strip() or default_name
                    dlg.destroy()
                    _post_quick(target_url, filename=nm, hls_mode=var_mode.get())

                ttk.Button(dlg, text=t("ov.hls_btn_start"), style="Primary.TButton", command=_go).pack(pady=(12, 0))

            def _open_playlist_dialog(target_url: str) -> None:
                dlg = tk.Toplevel(root)
                dlg.title(t("ov.pl_title"))
                dlg.geometry("620x460")
                dlg.configure(bg=BG_CARD)
                dlg.transient(root)
                dlg.grab_set()
                lbl_st = tk.Label(dlg, text=t("ov.pl_probing"), bg=BG_CARD, fg=ACCENT_AMBER, font=(ui_font, 9, "bold"))
                lbl_st.pack(anchor="w", padx=14, pady=(12, 6))
                list_box = tk.Listbox(dlg, bg=BG_CONSOLE, fg=FG_TEXT, selectmode="extended", font=(ui_font, 9), activestyle="none")
                list_box.pack(fill="both", expand=True, padx=14)
                entries_ref: List[Dict[str, Any]] = []

                def _fill() -> None:
                    c_now = IdmLinuxConfig.load(create_if_missing=False)
                    try:
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{c_now.http_port}/api/playlist/probe",
                            data=json.dumps({"url": target_url}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=90) as resp:
                            info = json.loads(resp.read().decode("utf-8"))
                    except Exception as exc:
                        info = {"ok": False, "error": str(exc)}

                    def _apply() -> None:
                        if not dlg.winfo_exists():
                            return
                        if not info.get("ok"):
                            lbl_st.configure(text=f"{t('ov.pl_error')}: {info.get('error', '')}", fg=ACCENT_RED)
                            return
                        entries_ref.extend(info.get("entries", []))
                        lbl_st.configure(text=f"{info.get('title', '') or target_url} — {len(entries_ref)} {t('ov.pl_items')}", fg=ACCENT_GREEN)
                        for e in entries_ref:
                            list_box.insert("end", f"{e['index']:>3}.  {e['title'][:80]}")
                        if entries_ref:
                            list_box.selection_set(0, len(entries_ref) - 1)

                    root.after(0, _apply)

                threading.Thread(target=_fill, daemon=True).start()

                def _download(sel_only: bool) -> None:
                    idxs = list_box.curselection() if sel_only else tuple(range(list_box.size()))
                    chosen = [entries_ref[i] for i in idxs if i < len(entries_ref)]
                    if not chosen:
                        return
                    dlg.destroy()

                    def _bg() -> None:
                        c_now = IdmLinuxConfig.load(create_if_missing=False)
                        try:
                            req = urllib.request.Request(
                                f"http://127.0.0.1:{c_now.http_port}/api/playlist/download",
                                data=json.dumps({"entries": chosen, "referer": target_url}).encode("utf-8"),
                                headers={"Content-Type": "application/json"},
                                method="POST",
                            )
                            urllib.request.urlopen(req, timeout=60).read()
                        except Exception:
                            pass

                    threading.Thread(target=_bg, daemon=True).start()

                btn_row = tk.Frame(dlg, bg=BG_CARD)
                btn_row.pack(fill="x", padx=14, pady=(8, 12))
                ttk.Button(btn_row, text=t("ov.pl_btn_sel"), style="Primary.TButton", command=lambda: _download(True)).pack(side="left", padx=(0, 6))
                ttk.Button(btn_row, text=t("ov.pl_btn_all"), style="Success.TButton", command=lambda: _download(False)).pack(side="left")

            def _post_quick(target_url: str, filename: str = "", hls_mode: str = "vod") -> None:
                def _bg_post() -> None:
                    c_now = IdmLinuxConfig.load(create_if_missing=False)
                    if _ensure_daemon_up(c_now):
                        try:
                            req = urllib.request.Request(
                                f"http://127.0.0.1:{c_now.http_port}/api/download",
                                data=json.dumps(
                                    {"url": target_url, "force": True, "source": "gui-panel", "filename": filename, "hlsMode": hls_mode}
                                ).encode("utf-8"),
                                headers={"Content-Type": "application/json"},
                                method="POST",
                            )
                            urllib.request.urlopen(req, timeout=15).read()
                            return
                        except Exception:
                            pass
                    from .protocol import DownloadRequest as _DR
                    WineIdmSender(c_now).send_download(_DR(url=target_url, filename=filename, source="gui-panel"))

                threading.Thread(target=_bg_post, daemon=True).start()

            def _send_quick_url() -> None:
                from .stream_engine import is_playlist_url as _is_pl
                from .hls_streamer import looks_like_hls_url as _lk_hls

                u = var_quick_url.get().strip()
                is_local_tor = Path(u).expanduser().is_file() and u.lower().endswith(".torrent")
                is_magnet = u.lower().startswith("magnet:?")
                # v3.7.0: eD2K (eMule) bağlantıları — docuwiki.net vb. siteler için
                is_ed2k = u.lower().startswith("ed2k://")
                if not (
                    u.startswith(("http://", "https://", "ftp://"))
                    or is_magnet
                    or is_local_tor
                    or is_ed2k
                ):
                    messagebox.showwarning(t("ov.invalid_url_title"), t("ov.invalid_url_msg"))
                    return
                var_quick_url.set("")
                if is_ed2k:
                    def _bg_ed2k() -> None:
                        c_now = IdmLinuxConfig.load(create_if_missing=False)
                        res: Optional[Dict[str, Any]] = None
                        if _ensure_daemon_up(c_now):
                            try:
                                req = urllib.request.Request(
                                    f"http://127.0.0.1:{c_now.http_port}/api/ed2k/download",
                                    data=json.dumps({"link": u, "source": "gui-ed2k"}).encode("utf-8"),
                                    headers={"Content-Type": "application/json"},
                                    method="POST",
                                )
                                with urllib.request.urlopen(req, timeout=30) as resp:
                                    res = json.loads(resp.read().decode("utf-8"))
                            except Exception:
                                res = None
                        def _show() -> None:
                            if res and res.get("ok"):
                                messagebox.showinfo(
                                    "eD2K (eMule)",
                                    res.get("message") or t("ov.ed2k_sent"),
                                )
                            elif res:
                                messagebox.showwarning("eD2K (eMule)", res.get("message") or t("ov.ed2k_fail"))
                            else:
                                messagebox.showwarning("eD2K (eMule)", t("ov.offline_help"))
                        try:
                            root.after(0, _show)
                        except RuntimeError:
                            pass

                    threading.Thread(target=_bg_ed2k, daemon=True).start()
                    return
                if _is_pl(u):
                    _open_playlist_dialog(u)
                    return
                if _lk_hls(u):
                    _open_hls_mode_dialog(u)
                    return

                def _bg_send() -> None:
                    from .protocol import DownloadRequest
                    c_now = IdmLinuxConfig.load(create_if_missing=False)
                    if (is_local_tor or is_magnet) and _ensure_daemon_up(c_now):
                        try:
                            t_body = {
                                "local_path": str(Path(u).expanduser().resolve()) if is_local_tor else "",
                                "magnet": u if is_magnet else "",
                                "source": "gui-torrent",
                            }
                            req = urllib.request.Request(
                                f"http://127.0.0.1:{c_now.http_port}/api/torrent/download",
                                data=json.dumps(t_body).encode("utf-8"),
                                headers={"Content-Type": "application/json"},
                                method="POST",
                            )
                            urllib.request.urlopen(req, timeout=12).read()
                            return
                        except Exception as exc:
                            root.after(0, lambda msg=str(exc): messagebox.showwarning("Torrent/Magnet", msg))
                            return

                    _post_quick(u)

                threading.Thread(target=_bg_send, daemon=True).start()

            ttk.Button(q_row, text=t("ov.btn_pick_torrent"), style="Secondary.TButton", command=_pick_local_torrent_file).pack(side="left", padx=(0, 6))
            ttk.Button(q_row, text=t("ov.btn_paste"), style="Secondary.TButton", command=_paste_quick_url).pack(side="left", padx=(0, 6))
            ttk.Button(q_row, text=t("ov.btn_send_idm"), style="Primary.TButton", command=_send_quick_url).pack(side="left")

            ctrl_card = make_card(pg_ov, title=t("ov.actions_title"))
            ctrl_row = tk.Frame(ctrl_card, bg=BG_CARD)
            ctrl_row.pack(fill="x")

            def _act_open_idm() -> None:
                ok, msg = WineIdmSender(IdmLinuxConfig.load(create_if_missing=False)).open_idm_window()
                if not ok:
                    messagebox.showwarning("IDM Linux", msg)

            def _act_restart_bridge() -> None:
                cli_bin = Path.home() / ".local" / "bin" / "idm-linux"
                cmd = [str(cli_bin), "restart"] if cli_bin.exists() else [sys.executable, "-m", "idm_linux.cli", "restart"]
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                def _refresh_and_forget() -> None:
                    # v3.11.0: ateşlenen tek-seferlik timer id'si listeden düşülür (birikme yok)
                    try:
                        active_timers.remove(_one_shot[0])
                    except (ValueError, IndexError):
                        pass
                    _refresh_all_status_once()

                _one_shot = [root.after(1200, _refresh_and_forget)]
                active_timers.append(_one_shot[0])

            def _act_open_downloads() -> None:
                dl = Path(IdmLinuxConfig.load(create_if_missing=False).download_dir)
                dl.mkdir(parents=True, exist_ok=True)
                subprocess.Popen(["xdg-open", str(dl)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            def _act_trial_reset() -> None:
                # v3.12.0: IDM 30 günlük deneme sayacını güvenli sıfırlama (DMCACount)
                if not messagebox.askyesno(t("ov.trial_reset_confirm_title"), t("ov.trial_reset_confirm_msg")):
                    return

                def _bg_reset() -> None:
                    try:
                        sender = WineIdmSender(IdmLinuxConfig.load(create_if_missing=False))
                        ok_r, msg_r = sender.trial_reset_idm()
                    except Exception as exc:
                        ok_r, msg_r = False, str(exc)

                    def _show() -> None:
                        try:
                            if ok_r:
                                messagebox.showinfo("IDM Linux", t("ov.trial_reset_ok"))
                            else:
                                messagebox.showwarning("IDM Linux", msg_r)
                        except Exception:
                            pass

                    try:
                        root.after(0, _show)
                    except Exception:
                        pass

                threading.Thread(target=_bg_reset, daemon=True).start()

            ttk.Button(ctrl_row, text=t("ov.btn_open_idm"), style="Primary.TButton", command=_act_open_idm).pack(side="left", padx=(0, 8))
            ttk.Button(ctrl_row, text=t("ov.btn_restart_bridge"), style="Secondary.TButton", command=_act_restart_bridge).pack(side="left", padx=4)
            ttk.Button(ctrl_row, text=t("ov.btn_trial_reset"), style="Secondary.TButton", command=_act_trial_reset).pack(side="left", padx=4)
            ttk.Button(ctrl_row, text=t("ov.btn_open_dldir"), style="Secondary.TButton", command=_act_open_downloads).pack(side="left", padx=4)
            ttk.Button(ctrl_row, text=t("ov.btn_quick_doctor"), style="Secondary.TButton", command=lambda: (switch_page("doctor"), _run_gui_doctor())).pack(side="left", padx=4)


            ttk.Button(ctrl_row, text=t("ov.btn_uninstall_idm"), style="Danger.TButton", command=_trigger_direct_uninstall).pack(side="right")

            sys_det_card = tk.Frame(pg_ov, bg=BG_CARD, padx=16, pady=10, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
            # v3.5.0: kart yüksekliği idele indirildi (içerik 8 satır) — devamına
            # Oynatma Listesi kartı geldiği için 'expand' artık bu karta verilmez.
            sys_det_card.pack(fill="x")
            lbl_ov_details = tk.Label(sys_det_card, text="", bg=BG_CARD, fg=FG_MUTED, justify="left", anchor="nw", font=("Monospace", 9), height=8)
            lbl_ov_details.pack(fill="x")

            # ==================================================================
            # v3.5.0: 📋 OYNATMA LİSTESİ (PLAYLIST) İNDİR KARTI
            # YouTube / Dailymotion / OK.ru / VK + tüm yt-dlp siteleri — site
            # URL'den dinamik algılanır. Link kutusu SABİT, video listesi
            # KAYDIRILABİLİR; her video için ilerleme + duraklat/devam/iptal.
            # ==================================================================
            pl_card = tk.Frame(pg_ov, bg=BG_CARD, padx=16, pady=12, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
            pl_card.pack(fill="both", expand=True, pady=(11, 0))
            pl_hdr = tk.Frame(pl_card, bg=BG_CARD)
            pl_hdr.pack(fill="x")
            tk.Label(pl_hdr, text=t("ov.pl_card_title"), bg=BG_CARD, fg=FG_TEXT, font=(ui_font, 11, "bold")).pack(side="left")
            tk.Label(pl_card, text=t("ov.pl_card_sub"), bg=BG_CARD, fg=FG_MUTED, justify="left", wraplength=820, font=(ui_font, 8)).pack(anchor="w", pady=(1, 6))

            pl_url_row = tk.Frame(pl_card, bg=BG_CARD)
            pl_url_row.pack(fill="x")
            var_pl_url = tk.StringVar()
            ent_pl_url = tk.Entry(pl_url_row, textvariable=var_pl_url, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat", font=(ui_font, 10))
            ent_pl_url.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

            pl_site_lbl = tk.Label(pl_card, text="", bg=BG_CARD, fg=ACCENT_CYAN, font=(ui_font, 8, "bold"))

            pl_rows_wrap = tk.Frame(pl_card, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
            pl_canvas = tk.Canvas(pl_rows_wrap, bg=BG_CONSOLE, highlightthickness=0, height=170)
            pl_vsb = ttk.Scrollbar(pl_rows_wrap, orient="vertical", command=pl_canvas.yview)
            pl_inner = tk.Frame(pl_canvas, bg=BG_CONSOLE)
            pl_inner.bind("<Configure>", lambda _e: pl_canvas.configure(scrollregion=pl_canvas.bbox("all")))
            pl_canvas.create_window((0, 0), window=pl_inner, anchor="nw", tags="pl_inner")
            pl_canvas.bind("<Configure>", lambda e: pl_canvas.itemconfigure("pl_inner", width=e.width))
            pl_canvas.configure(yscrollcommand=pl_vsb.set)
            pl_canvas.pack(side="left", fill="both", expand=True)
            pl_vsb.pack(side="right", fill="y")
            pl_rows_wrap.pack_forget()  # liste dolana kadar gizli

            def _pl_on_wheel(e: Any) -> None:
                # v3.8.0: Linux X11 tekerleği (Tk 8.6: Button-4/5, Tk 9.0: Button-8/9)
                # de desteklenir — delta tabanlı MouseWheel macOS/Windows'a kalır.
                try:
                    num = getattr(e, "num", None)
                    delta = getattr(e, "delta", 0) or 0
                    if (delta > 0) or (num is not None and num in (4, 8)):
                        pl_canvas.yview_scroll(-1, "units")
                    elif (delta < 0) or (num is not None and num in (5, 9)):
                        pl_canvas.yview_scroll(1, "units")
                except Exception:
                    pass

            _PL_WHEEL_PATTERNS = ("<MouseWheel>", "<Button-4>", "<Button-5>", "<Button-8>", "<Button-9>")

            def _pl_bind_wheel(_e: Any = None) -> None:
                for _p in _PL_WHEEL_PATTERNS:
                    try:
                        pl_canvas.bind_all(_p, _pl_on_wheel)
                    except Exception:
                        pass

            def _pl_unbind_wheel(_e: Any = None) -> None:
                for _p in _PL_WHEEL_PATTERNS:
                    try:
                        pl_canvas.unbind_all(_p)
                    except Exception:
                        pass

            pl_canvas.bind("<Enter>", _pl_bind_wheel)
            pl_canvas.bind("<Leave>", _pl_unbind_wheel)

            pl_state: Dict[str, Any] = {"entries": [], "batch_id": "", "polling": False}
            pl_row_refs: Dict[int, Dict[str, Any]] = {}

            def _pl_fmt_dur(sec: int) -> str:
                if not sec:
                    return ""
                m, s = divmod(int(sec), 60)
                return f"{m}:{s:02d}" if m < 60 else f"{m // 60}:{m % 60:02d}:{s:02d}"

            def _pl_status_color(st: str) -> str:
                return {
                    "downloading": ACCENT_AMBER,
                    "paused": ACCENT_CYAN,
                    "completed": ACCENT_GREEN,
                    "failed": ACCENT_RED,
                    "cancelled": FG_DIM,
                }.get(st, FG_MUTED)

            def _pl_clear_rows() -> None:
                for w in pl_inner.winfo_children():
                    w.destroy()
                pl_row_refs.clear()
                pl_state["entries"] = []
                pl_rows_wrap.pack_forget()
                pl_site_lbl.pack_forget()

            def _pl_render_rows() -> None:
                for w in pl_inner.winfo_children():
                    w.destroy()
                pl_row_refs.clear()
                ents = pl_state["entries"]
                if not ents:
                    pl_rows_wrap.pack_forget()
                    return
                pl_rows_wrap.pack(fill="both", expand=True, pady=(6, 0))
                hdr = tk.Frame(pl_inner, bg=BG_CONSOLE)
                hdr.pack(fill="x", padx=6, pady=(5, 2))
                tk.Label(hdr, text=f"{'#':>3}", bg=BG_CONSOLE, fg=FG_DIM, font=("Monospace", 8, "bold"), width=4).pack(side="left")
                tk.Label(hdr, text=t("ov.pl_col_title"), bg=BG_CONSOLE, fg=FG_DIM, font=(ui_font, 8, "bold")).pack(side="left", padx=(4, 0))
                tk.Label(hdr, text=t("ov.pl_col_status"), bg=BG_CONSOLE, fg=FG_DIM, font=(ui_font, 8, "bold")).pack(side="right", padx=(0, 84))
                for e in ents:
                    idx = int(e.get("index", len(pl_row_refs) + 1))
                    row = tk.Frame(pl_inner, bg=BG_CONSOLE)
                    row.pack(fill="x", padx=6, pady=1)
                    var_sel = tk.BooleanVar(value=True)
                    tk.Label(row, text=f"{idx:>3}", bg=BG_CONSOLE, fg=FG_MUTED, font=("Monospace", 8), width=4).pack(side="left")
                    cb = tk.Checkbutton(row, variable=var_sel, bg=BG_CONSOLE, fg=FG_TEXT, activebackground=BG_CONSOLE, activeforeground=FG_TEXT, selectcolor=BG_INPUT, relief="flat", highlightthickness=0, bd=0)
                    cb.pack(side="left", padx=(0, 2))
                    dur = _pl_fmt_dur(int(e.get("duration") or 0))
                    ttl = str(e.get("title") or "")[:74]
                    tk.Label(row, text=f"{ttl}" + (f"  ·  {dur}" if dur else ""), bg=BG_CONSOLE, fg=FG_TEXT, font=(ui_font, 8), anchor="w").pack(side="left", fill="x", expand=True, padx=(0, 6))
                    st_lbl = tk.Label(row, text=t("ov.pl_status_queued"), bg=BG_CONSOLE, fg=FG_MUTED, font=(ui_font, 8), width=14, anchor="e")
                    st_lbl.pack(side="right", padx=(4, 0))
                    bar = ttk.Progressbar(row, orient="horizontal", length=96, maximum=100, style="Idm.Horizontal.TProgressbar")
                    bar.pack(side="right", padx=4)
                    btn_pause = ttk.Button(row, text="⏸", width=2, style="Secondary.TButton", command=lambda i=idx: _pl_control("pause", i))
                    btn_resume = ttk.Button(row, text="▶", width=2, style="Success.TButton", command=lambda i=idx: _pl_control("resume", i))
                    btn_cancel = ttk.Button(row, text="✖", width=2, style="Danger.TButton", command=lambda i=idx: _pl_control("cancel", i))
                    btn_pause.pack_forget()
                    btn_resume.pack_forget()
                    btn_cancel.pack_forget()
                    pl_row_refs[idx] = {"var": var_sel, "status": st_lbl, "bar": bar, "pause": btn_pause, "resume": btn_resume, "cancel": btn_cancel, "row": row}

            def _pl_apply_status(info: Dict[str, Any]) -> None:
                """Daemon durum güncellemesini satırlara işler (poll döngüsünden çağrılır)."""
                if not pl_card.winfo_exists():
                    return
                for ed in info.get("entries") or []:
                    idx = int(ed.get("index") or 0)
                    ref = pl_row_refs.get(idx)
                    if not ref:
                        continue
                    st = str(ed.get("status") or "queued")
                    total = int(ed.get("total") or 0)
                    got = int(ed.get("downloaded") or 0)
                    pct = min(100.0, (got * 100.0 / total) if total else 0.0)
                    ref["bar"].configure(value=pct)
                    if st == "downloading":
                        spd = ed.get("speed") or 0
                        txt = f"{pct:.0f}% · {got // (1024 * 1024)}MB · {spd // 1024}KB/s"
                    elif st == "completed":
                        txt = t("ov.pl_status_completed")
                    elif st == "paused":
                        txt = t("ov.pl_status_paused")
                    elif st == "failed":
                        txt = t("ov.pl_status_failed")
                    elif st == "cancelled":
                        txt = t("ov.pl_status_cancelled")
                    else:
                        txt = t("ov.pl_status_queued")
                    ref["status"].configure(text=txt, fg=_pl_status_color(st))
                    # düğme görünürlüğü
                    for key in ("pause", "resume", "cancel"):
                        ref[key].pack_forget()
                    if st == "downloading":
                        ref["pause"].pack(side="right")
                        ref["cancel"].pack(side="right")
                    elif st == "paused":
                        ref["resume"].pack(side="right")
                        ref["cancel"].pack(side="right")
                    elif st == "queued":
                        ref["cancel"].pack(side="right")

            def _pl_control(action: str, index: int = 0) -> None:
                bid = str(pl_state.get("batch_id") or "")
                if not bid:
                    return

                def _bg() -> None:
                    c_now = IdmLinuxConfig.load(create_if_missing=False)
                    try:
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{c_now.http_port}/api/playlist/batch/control",
                            data=json.dumps({"batch_id": bid, "action": action, "index": index}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        urllib.request.urlopen(req, timeout=6).read()
                    except Exception:
                        pass
                    try:
                        root.after(0, _pl_poll_once)
                    except RuntimeError:
                        pass

                threading.Thread(target=_bg, daemon=True).start()

            def _pl_poll_once() -> None:
                bid = str(pl_state.get("batch_id") or "")
                if not bid:
                    return

                def _bg() -> None:
                    c_now = IdmLinuxConfig.load(create_if_missing=False)
                    info: Dict[str, Any] = {}
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{c_now.http_port}/api/playlist/batch/status?batch_id={bid}", timeout=4) as r:
                            info = json.loads(r.read().decode("utf-8"))
                    except Exception:
                        info = {}

                    def _apply() -> None:
                        if not pl_card.winfo_exists():
                            return
                        batch = info.get("batch")
                        if not batch:
                            return
                        _pl_apply_status(batch)
                        if batch.get("done"):
                            pl_state["batch_id"] = ""
                            pl_state["polling"] = False
                            return
                        if pl_state.get("polling"):
                            root.after(1000, _pl_poll_once)

                    root.after(0, _apply)

                threading.Thread(target=_bg, daemon=True).start()

            def _pl_list() -> None:
                u = var_pl_url.get().strip()
                if not u.startswith(("http://", "https://")):
                    messagebox.showwarning(t("ov.invalid_url_title"), t("ov.pl_need_url"))
                    return
                if pl_state.get("batch_id"):
                    # aktif iş varken yeni liste çözme — önce iptal ister
                    if not messagebox.askyesno(t("ov.pl_card_title"), t("ov.pl_active_confirm")):
                        return
                    _pl_control("cancel")
                    pl_state["batch_id"] = ""
                btn_list.configure(state="disabled")
                pl_site_lbl.configure(text=t("ov.pl_fetching"), fg=ACCENT_AMBER)
                pl_site_lbl.pack(anchor="w", pady=(5, 0))
                _pl_clear_rows()

                def _bg() -> None:
                    c_now = IdmLinuxConfig.load(create_if_missing=False)
                    try:
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{c_now.http_port}/api/playlist/probe",
                            data=json.dumps({"url": u, "maxItems": 120}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=90) as resp:
                            info = json.loads(resp.read().decode("utf-8"))
                    except Exception as exc:
                        info = {"ok": False, "error": str(exc), "entries": [], "site": ""}

                    def _apply() -> None:
                        if not pl_card.winfo_exists():
                            return
                        btn_list.configure(state="normal")
                        if not info.get("ok"):
                            pl_site_lbl.configure(text=f"{t('ov.pl_error')}: {info.get('error', '')[:120]}", fg=ACCENT_RED)
                            return
                        ents = info.get("entries") or []
                        pl_state["entries"] = ents
                        site = info.get("site") or ""
                        badge = f"{t('ov.pl_site_detected', site=site)}  ·  {len(ents)} {t('ov.pl_videos_word')}"
                        pl_site_lbl.configure(text=badge, fg=ACCENT_CYAN)
                        if info.get("title"):
                            pl_site_lbl.configure(text=f"{info['title'][:70]}  ·  " + badge)
                        _pl_render_rows()

                    root.after(0, _apply)

                threading.Thread(target=_bg, daemon=True).start()

            def _pl_selected() -> List[Dict[str, Any]]:
                chosen = []
                for e in pl_state["entries"]:
                    ref = pl_row_refs.get(int(e.get("index", 0)))
                    if ref and ref["var"].get():
                        chosen.append(e)
                return chosen

            def _pl_start() -> None:
                chosen = _pl_selected()
                if not chosen:
                    messagebox.showinfo(t("ov.pl_card_title"), t("ov.pl_no_selection"))
                    return
                u = var_pl_url.get().strip()

                def _bg() -> None:
                    c_now = IdmLinuxConfig.load(create_if_missing=False)
                    if not _ensure_daemon_up(c_now):
                        root.after(0, lambda: messagebox.showwarning("IDM Linux", t("ov.pl_bridge_down")))
                        return
                    res: Dict[str, Any] = {}
                    try:
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{c_now.http_port}/api/playlist/batch/start",
                            data=json.dumps({"playlist_url": u, "entries": chosen}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            res = json.loads(resp.read().decode("utf-8"))
                    except Exception as exc:
                        res = {"ok": False, "error": str(exc)}

                    def _apply() -> None:
                        if not pl_card.winfo_exists():
                            return
                        if not res.get("ok"):
                            messagebox.showwarning(t("ov.pl_card_title"), str(res.get("error") or ""))
                            return
                        pl_state["batch_id"] = str(res.get("batch_id") or "")
                        pl_state["polling"] = True
                        _pl_poll_once()

                    root.after(0, _apply)

                threading.Thread(target=_bg, daemon=True).start()

            def _pl_sel_all(val: bool) -> None:
                for ref in pl_row_refs.values():
                    ref["var"].set(val)

            def _pl_cancel_all() -> None:
                if pl_state.get("batch_id"):
                    _pl_control("cancel")
                for ref in pl_row_refs.values():
                    ref["status"].configure(text=t("ov.pl_status_cancelled"), fg=FG_DIM)
                    ref["bar"].configure(value=0)
                pl_state["batch_id"] = ""

            pl_btn_row = tk.Frame(pl_card, bg=BG_CARD)
            pl_btn_row.pack(fill="x", pady=(8, 0))
            btn_list = ttk.Button(pl_url_row, text=t("ov.pl_card_btn_list"), style="Primary.TButton", command=_pl_list)
            btn_list.pack(side="left")
            ent_pl_url.bind("<Return>", lambda _e: _pl_list())  # Enter = Listele
            ttk.Button(pl_btn_row, text=t("ov.pl_btn_sel_all"), style="Secondary.TButton", command=lambda: _pl_sel_all(True)).pack(side="left", padx=(0, 6))
            ttk.Button(pl_btn_row, text=t("ov.pl_btn_sel_none"), style="Secondary.TButton", command=lambda: _pl_sel_all(False)).pack(side="left", padx=(0, 6))
            ttk.Button(pl_btn_row, text=t("ov.pl_btn_cancel_all"), style="Danger.TButton", command=_pl_cancel_all).pack(side="right", padx=(6, 0))
            ttk.Button(pl_btn_row, text=t("ov.pl_btn_download"), style="Success.TButton", command=_pl_start).pack(side="right")

            # ==================================================================
            # SAYFA 3: 🧩 TARAYICI & EKLENTİ MERKEZİ
            # ==================================================================
            pg_br = pages["browsers"]
            tk.Label(pg_br, text=t("br.title"), bg=BG_MAIN, fg=FG_TEXT, font=(ui_font, 14, "bold")).pack(anchor="w", pady=(0, 11))

            ext_base = get_data_dir(create=False) / "extensions"
            chrom_dir_path = ext_base / "chromium"
            xpi_file_path = ext_base / "idm-linux-companion-firefox.xpi"

            det_b = detect_default_browser()
            det_b_label = f"{det_b.name} ({det_b.family})" if det_b else t("br.auto_ready")
            auto_br_card = make_card(
                pg_br,
                title=t("br.auto_card_title"),
                subtitle=t("br.auto_card_sub", browser=det_b_label),
            )

            def _gui_trigger_auto_browser() -> None:
                if not chrom_dir_path.exists() or not xpi_file_path.exists():
                    deploy_browser_extensions(proj_root)
                c_now = IdmLinuxConfig.load(create_if_missing=False)
                ok, msg = auto_install_and_open_default_browser(
                    http_port=c_now.http_port,
                    chrom_ext_dir=chrom_dir_path,
                    ff_xpi_path=xpi_file_path,
                    restart_if_running=False,
                )
                if not ok:
                    messagebox.showwarning("IDM Linux", msg)

            auto_br_row = tk.Frame(auto_br_card, bg=BG_CARD)
            auto_br_row.pack(fill="x")
            tk.Label(auto_br_row, text=t("br.auto_desc"), bg=BG_CARD, fg=FG_MUTED, wraplength=540, justify="left", font=(ui_font, 9)).pack(
                side="left", padx=(0, 12)
            )
            ttk.Button(auto_br_row, text=t("br.btn_auto_open"), style="Success.TButton", command=_gui_trigger_auto_browser).pack(side="right")

            chrom_card = make_card(pg_br, title=t("br.chrom_card_title"), subtitle=t("br.chrom_card_sub"))
            tk.Label(
                chrom_card,
                text=t("br.chrom_steps"),
                bg=BG_CARD,
                fg=FG_MUTED,
                justify="left",
                wraplength=820,
                font=(ui_font, 9),
            ).pack(anchor="w", pady=(0, 8))

            c_btn_row = tk.Frame(chrom_card, bg=BG_CARD)
            c_btn_row.pack(fill="x")
            ttk.Button(
                c_btn_row,
                text=t("br.btn_copy_chrom_dir"),
                style="Primary.TButton",
                command=lambda: copy_to_clipboard(str(chrom_dir_path), t("br.copied_chrom_msg", path=str(chrom_dir_path))),
            ).pack(side="left", padx=(0, 8))
            ttk.Button(
                c_btn_row,
                text=t("br.btn_open_ext_dir"),
                style="Secondary.TButton",
                command=lambda: subprocess.Popen(["xdg-open", str(ext_base)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
            ).pack(side="left", padx=4)

            def _open_firefox_xpi() -> None:
                if not xpi_file_path.exists():
                    deploy_browser_extensions(proj_root)
                for ff_bin in ("firefox", "librewolf", "waterfox"):
                    if shutil.which(ff_bin):
                        subprocess.Popen([ff_bin, str(xpi_file_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return
                subprocess.Popen(["xdg-open", str(ext_base)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            ttk.Button(c_btn_row, text=t("br.btn_firefox_xpi"), style="Secondary.TButton", command=_open_firefox_xpi).pack(side="left", padx=4)

            br_tbl_card = tk.Frame(pg_br, bg=BG_CARD, padx=16, pady=12, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
            br_tbl_card.pack(fill="both", expand=True)
            tk.Label(br_tbl_card, text=t("br.tbl_title"), bg=BG_CARD, fg=FG_TEXT, font=(ui_font, 11, "bold")).pack(anchor="w", pady=(0, 6))

            br_list_frame = tk.Frame(br_tbl_card, bg=BG_CONSOLE, padx=12, pady=8, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
            br_list_frame.pack(fill="both", expand=True)

            def render_browser_rows() -> None:
                for w in br_list_frame.winfo_children():
                    w.destroy()
                for bt in get_browser_targets():
                    row = tk.Frame(br_list_frame, bg=BG_CONSOLE)
                    row.pack(fill="x", pady=2)
                    tk.Label(row, text=f"{bt.name:<18}", bg=BG_CONSOLE, fg=FG_TEXT, font=("Monospace", 9, "bold")).pack(side="left")
                    inst_s = t("br.status_installed") if bt.installed else t("br.status_not_installed")
                    inst_c = ACCENT_GREEN if bt.installed else FG_DIM
                    tk.Label(row, text=f"{inst_s:<18}", bg=BG_CONSOLE, fg=inst_c, font=(ui_font, 9)).pack(side="left")
                    reg_s = t("br.status_registered") if bt.registered else t("br.status_unregistered")
                    reg_c = ACCENT_CYAN if bt.registered else FG_DIM
                    tk.Label(row, text=reg_s, bg=BG_CONSOLE, fg=reg_c, font=(ui_font, 9)).pack(side="left")

            render_browser_rows()

            custom_row = tk.Frame(br_tbl_card, bg=BG_CARD)
            custom_row.pack(fill="x", pady=(10, 0))
            tk.Label(custom_row, text=t("br.lbl_extra_id"), bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 9)).pack(side="left")
            ent_extra_id = tk.Entry(custom_row, width=32, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat")
            ent_extra_id.pack(side="left", padx=8, ipady=4)

            def _resync_browsers() -> None:
                crx_p, chrom_d, _ = deploy_browser_extensions(proj_root)
                src_dir = get_data_dir(create=False) / "app" / "src"
                if not src_dir.exists():
                    src_dir = Path(__file__).resolve().parents[1]
                wrapper = create_native_host_wrapper(sys.executable, src_dir)
                extra = [ent_extra_id.get().strip()] if ent_extra_id.get().strip() else []
                register_all_browsers(wrapper, crx_path=crx_p, chrom_ext_dir=chrom_d, extra_chromium_ids=extra)
                render_browser_rows()
                messagebox.showinfo(t("br.resync_ok_title"), t("br.resync_ok_msg"))

            ttk.Button(custom_row, text=t("br.btn_resync"), style="Primary.TButton", command=_resync_browsers).pack(side="right")

            # ==================================================================
            # SAYFA 4: ⚙️ YAKALAMA, VİDEO BAR & WINE AYARLARI
            # ==================================================================
            pg_set = pages["settings"]
            tk.Label(pg_set, text=t("set.title"), bg=BG_MAIN, fg=FG_TEXT, font=(ui_font, 14, "bold")).pack(anchor="w", pady=(0, 11))

            set_card = tk.Frame(pg_set, bg=BG_CARD, padx=18, pady=14, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
            set_card.pack(fill="both", expand=True)

            var_s_capture = tk.BooleanVar(value=cfg.capture_downloads)
            var_s_vbar = tk.BooleanVar(value=cfg.video_bar_enabled)
            var_s_clip = tk.BooleanVar(value=cfg.clipboard_monitor)
            var_s_silent = tk.BooleanVar(value=cfg.silent_mode)
            var_s_warm = tk.BooleanVar(value=cfg.keep_wine_warm)

            lang_display_items = [f"{s.code} — {s.native_name}" for s in LANGUAGE_LIST]
            cur_spec = SUPPORTED_LANGUAGES.get(i18n.lang, SUPPORTED_LANGUAGES["tr"])
            var_s_lang = tk.StringVar(value=f"{cur_spec.code} — {cur_spec.native_name}")
            var_s_dpi = tk.StringVar(value=str(cfg.dpi_scale))
            var_s_conn = tk.StringVar(value=str(cfg.max_connections))
            var_s_pfx = tk.StringVar(value=cfg.wine_prefix)
            var_s_dldir = tk.StringVar(value=cfg.download_dir)

            for txt_k, v in (
                ("set.chk_capture", var_s_capture),
                ("set.chk_vbar", var_s_vbar),
                ("set.chk_clip", var_s_clip),
                ("set.chk_silent", var_s_silent),
                ("set.chk_warm", var_s_warm),
            ):
                ttk.Checkbutton(set_card, text=t(txt_k), variable=v, style="Card.TCheckbutton").pack(anchor="w", pady=2)

            s_opt = tk.Frame(set_card, bg=BG_CARD)
            s_opt.pack(fill="x", pady=(10, 8))
            tk.Label(s_opt, text=t("set.lbl_lang"), bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 9)).pack(side="left")
            ttk.Combobox(s_opt, textvariable=var_s_lang, values=lang_display_items, width=22, state="readonly").pack(side="left", padx=(6, 16))
            tk.Label(s_opt, text=t("set.lbl_dpi"), bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 9)).pack(side="left")
            ttk.Combobox(s_opt, textvariable=var_s_dpi, values=["0", "96", "120", "144", "192"], width=6, state="readonly").pack(side="left", padx=(6, 16))
            tk.Label(s_opt, text=t("set.lbl_conn"), bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 9)).pack(side="left")
            ttk.Combobox(s_opt, textvariable=var_s_conn, values=["8", "16", "24", "32"], width=6, state="readonly").pack(side="left", padx=6)

            def _path_row(label: str, var: tk.StringVar) -> None:
                r = tk.Frame(set_card, bg=BG_CARD)
                r.pack(fill="x", pady=3)
                tk.Label(r, text=label, width=24, anchor="w", bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 9)).pack(side="left")
                tk.Entry(r, textvariable=var, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat").pack(
                    side="left", fill="x", expand=True, ipady=4, padx=(0, 8)
                )
                ttk.Button(
                    r,
                    text=t("common.select"),
                    style="Secondary.TButton",
                    command=lambda: (lambda d: var.set(d) if d else None)(filedialog.askdirectory(initialdir=var.get())),
                ).pack(side="left")

            _path_row(t("set.lbl_prefix"), var_s_pfx)
            _path_row(t("set.lbl_dldir"), var_s_dldir)

            tk.Label(set_card, text=t("set.lbl_exts"), bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 9)).pack(anchor="w", pady=(8, 2))
            ent_s_exts = tk.Entry(set_card, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat")
            ent_s_exts.insert(0, " ".join(cfg.file_extensions))
            ent_s_exts.pack(fill="x", ipady=4)

            tk.Label(set_card, text=t("set.lbl_excl"), bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 9)).pack(anchor="w", pady=(8, 2))
            ent_s_excl = tk.Entry(set_card, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat")
            ent_s_excl.insert(0, ", ".join(cfg.excluded_domains))
            ent_s_excl.pack(fill="x", ipady=4)

            # ------------------------------------------------------------------
            # v2.9.4: ABYSS.TO kod kilidi (kod kaynakta şifreli tutulur)
            # ------------------------------------------------------------------
            def _save_all_settings() -> None:
                nonlocal cfg
                c = IdmLinuxConfig.load(create_if_missing=False)
                c.capture_downloads = var_s_capture.get()
                c.video_bar_enabled = var_s_vbar.get()
                c.clipboard_monitor = var_s_clip.get()
                c.silent_mode = var_s_silent.get()
                c.keep_wine_warm = var_s_warm.get()
                chosen_lang = var_s_lang.get().split("—", 1)[0].strip().lower()
                prev_lang = i18n.lang
                c.language = chosen_lang if chosen_lang in SUPPORTED_LANGUAGES else prev_lang
                c.dpi_scale = int(var_s_dpi.get() or "0")
                c.max_connections = int(var_s_conn.get() or "24")
                if var_s_pfx.get().strip():
                    c.wine_prefix = str(Path(var_s_pfx.get().strip()).expanduser())
                if var_s_dldir.get().strip():
                    c.download_dir = str(Path(var_s_dldir.get().strip()).expanduser())
                c.file_extensions = [e.strip().upper() for e in ent_s_exts.get().split() if e.strip()]
                c.excluded_domains = [d.strip().lower() for d in ent_s_excl.get().split(",") if d.strip()]
                c.save()
                cfg = c

                def _bg_apply() -> None:
                    try:
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{c.http_port}/api/config",
                            data=json.dumps(c.__dict__).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        urllib.request.urlopen(req, timeout=4).read()
                    except Exception:
                        pass
                    apply_idm_registry_tweaks(c, log_fn=lambda _s: None)

                threading.Thread(target=_bg_apply, daemon=True).start()
                if c.language != prev_lang:
                    i18n.set_language(c.language)
                    _rebuild_shell("settings")
                messagebox.showinfo(i18n.t("set.saved_title"), i18n.t("set.saved_msg"))

            ttk.Button(set_card, text=t("set.btn_save"), style="Success.TButton", command=_save_all_settings).pack(anchor="e", pady=(14, 0))

            # v3.2.2: 'Ayarları Kaydet ve Canlı Uygula' ile ABYSS bloğu arasına NET AYRIM:
            # ince ayraç çizgisi + ferah boşluk (kullanıcı isteği — iki bölge karışmasın)
            ttk.Separator(set_card, orient="horizontal").pack(fill="x", padx=2, pady=(16, 0))

            abyss_row = tk.Frame(set_card, bg=BG_CARD)
            abyss_row.pack(fill="x", pady=(20, 0))
            tk.Label(abyss_row, text=t("set.abyss_lbl"), bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 9)).pack(side="left")
            ent_abyss = tk.Entry(abyss_row, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat", width=14)
            ent_abyss.pack(side="left", padx=(8, 6), ipady=3)
            lbl_abyss_state = tk.Label(
                abyss_row,
                text=t("set.abyss_on") if cfg.abyss_enabled else t("set.abyss_off"),
                bg=BG_CARD,
                fg=FG_GREEN if cfg.abyss_enabled else FG_MUTED,
                font=(ui_font, 9, "bold"),
            )
            lbl_abyss_state.pack(side="right")

            def _abyss_set(on: bool) -> None:
                nonlocal cfg
                if on and not abyss_code_ok(ent_abyss.get()):
                    messagebox.showwarning(t("set.abyss_bad_title"), t("set.abyss_bad"))
                    on = False
                c = IdmLinuxConfig.load(create_if_missing=False)
                c.abyss_enabled = on
                c.save()
                cfg = c
                # v3.2.0: EVET/HAYIR = ANINDA canlı uygulama — ayrıca 'Kaydet'e basmaya gerek yok
                lbl_abyss_state.config(
                    text=(t("set.abyss_on") if on else t("set.abyss_off")) + " ✓",
                    fg=FG_GREEN if on else FG_MUTED,
                )
                ent_abyss.delete(0, "end")

                def _push() -> None:
                    try:
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{c.http_port}/api/config",
                            data=json.dumps(c.__dict__).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        urllib.request.urlopen(req, timeout=4).read()
                    except Exception:
                        pass

                threading.Thread(target=_push, daemon=True).start()

            ttk.Button(abyss_row, text=t("set.abyss_yes"), style="Success.TButton", command=lambda: _abyss_set(True)).pack(side="left", padx=(0, 4))
            ttk.Button(abyss_row, text=t("set.abyss_no"), style="Secondary.TButton", command=lambda: _abyss_set(False)).pack(side="left")

            # v3.2.0: kullanıcı sorusuna net cevap GUI'de — EVET yeterli, canlı uygulanır
            try:
                tk.Label(set_card, text=t("set.abyss_hint"), bg=BG_CARD, fg=FG_MUTED, font=(ui_font, 8), wraplength=560, justify="left", anchor="w").pack(fill="x", pady=(4, 0), anchor="w")
            except Exception:
                pass


            # ==================================================================
            # SAYFA 5: 🩺 SİSTEM DOKTORU & CANLI GÜNLÜKLER
            # ==================================================================
            pg_doc = pages["doctor"]
            doc_top = tk.Frame(pg_doc, bg=BG_MAIN)
            doc_top.pack(fill="x", pady=(0, 10))
            tk.Label(doc_top, text=t("doc.title"), bg=BG_MAIN, fg=FG_TEXT, font=(ui_font, 14, "bold")).pack(side="left")

            doc_card = make_card(pg_doc, title=t("doc.card_title"))
            doc_btn_bar = tk.Frame(doc_card, bg=BG_CARD)
            doc_btn_bar.pack(fill="x", pady=(0, 8))

            doc_out = tk.Text(doc_card, height=8, bg=BG_CONSOLE, fg="#cbd5e1", font=("Monospace", 9), relief="flat", padx=10, pady=8, state="disabled")
            doc_out.pack(fill="x")
            doc_out.tag_configure("ok", foreground="#4ade80")
            doc_out.tag_configure("warn", foreground="#fbbf24")

            def _run_gui_doctor() -> None:
                doc_out.configure(state="normal")
                doc_out.delete("1.0", "end")
                doc_out.insert("end", t("doc.running") + "\n")
                doc_out.configure(state="disabled")

                def _job() -> None:
                    lines: List[Tuple[str, str]] = []
                    c = IdmLinuxConfig.load(create_if_missing=False)
                    lines.append((t("doc.step1_ok", http=c.http_port, ws=c.ws_port), "ok"))

                    idm_exe = c.find_idm_exe()
                    if idm_exe and idm_exe.exists():
                        n_dis = neutralize_windows_hook_binaries(idm_exe.parent)
                        lines.append((t("doc.step2_ok", count=n_dis), "ok"))
                    else:
                        lines.append((t("doc.step2_warn"), "warn"))

                    chrom_d = None
                    try:
                        crx_p, chrom_d, _ = deploy_browser_extensions(proj_root)
                        miss = validate_extension_directory(chrom_d)
                        ok_crx, msg_crx = verify_crx3_package(crx_p)
                        if not miss and ok_crx:
                            lines.append((t("doc.step3_ok", msg=msg_crx), "ok"))
                        else:
                            lines.append((t("doc.step3_warn", msg=f"{miss} / {msg_crx}"), "warn"))
                    except Exception as exc:
                        lines.append((t("doc.step3_warn", msg=str(exc)), "warn"))
                        crx_p = None

                    src_dir = get_data_dir(create=False) / "app" / "src"
                    if not src_dir.exists():
                        src_dir = Path(__file__).resolve().parents[1]
                    wrapper = create_native_host_wrapper(sys.executable, src_dir)
                    targets = register_all_browsers(wrapper, crx_path=crx_p, chrom_ext_dir=chrom_d)
                    lines.append((t("doc.step4_ok", count=sum(1 for bt in targets if bt.registered)), "ok"))

                    if idm_exe:
                        apply_idm_registry_tweaks(c, log_fn=lambda _s: None)
                        lines.append((t("doc.step5_ok"), "ok"))

                    if not is_daemon_running(c):
                        subprocess.Popen([sys.executable, "-m", "idm_linux.cli", "start"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        import time as _t
                        for _ in range(10):
                            _t.sleep(0.25)
                            if is_daemon_running(c):
                                break

                    if is_daemon_running(c):
                        lines.append((t("doc.step6_ok", http=c.http_port), "ok"))
                    else:
                        lines.append((t("doc.step6_warn"), "warn"))

                    def _show() -> None:
                        if not doc_out.winfo_exists():
                            return
                        doc_out.configure(state="normal")
                        doc_out.delete("1.0", "end")
                        for txt, tg in lines:
                            doc_out.insert("end", txt + "\n", (tg,))
                        doc_out.configure(state="disabled")
                        render_browser_rows()
                        _refresh_all_status_once()

                    root.after(0, _show)

                threading.Thread(target=_job, daemon=True).start()

            def _update_ytdlp_gui() -> None:
                def _job() -> None:
                    p = install_standalone_ytdlp(log_fn=lambda _s: None)
                    msg = t("doc.ytdlp_ok", path=str(p)) if p else t("doc.ytdlp_err")
                    root.after(0, lambda: messagebox.showinfo(t("doc.ytdlp_title"), msg))
                threading.Thread(target=_job, daemon=True).start()

            def _clear_stream_cache() -> None:
                st_dir = get_cache_dir(create=False) / "streams"
                if st_dir.exists():
                    shutil.rmtree(st_dir, ignore_errors=True)
                messagebox.showinfo(t("doc.cache_cleared_title"), t("doc.cache_cleared_msg"))

            ttk.Button(doc_btn_bar, text=t("doc.btn_run"), style="Primary.TButton", command=_run_gui_doctor).pack(side="left", padx=(0, 8))
            ttk.Button(doc_btn_bar, text=t("doc.btn_ytdlp"), style="Secondary.TButton", command=_update_ytdlp_gui).pack(side="left", padx=4)
            ttk.Button(doc_btn_bar, text=t("doc.btn_clear_cache"), style="Secondary.TButton", command=_clear_stream_cache).pack(side="left", padx=4)

            log_card = tk.Frame(pg_doc, bg=BG_CARD, padx=16, pady=12, highlightthickness=1, highlightbackground=BORDER_SUBTLE)
            log_card.pack(fill="both", expand=True)
            l_hdr = tk.Frame(log_card, bg=BG_CARD)
            l_hdr.pack(fill="x", pady=(0, 6))
            tk.Label(l_hdr, text=t("doc.log_title"), bg=BG_CARD, fg=FG_TEXT, font=(ui_font, 10, "bold")).pack(side="left")

            log_txt = tk.Text(log_card, bg=BG_CONSOLE, fg="#93c5fd", font=("Monospace", 9), relief="flat", padx=10, pady=8)
            log_txt.pack(fill="both", expand=True)

            def _reload_logs() -> None:
                if not log_txt.winfo_exists():
                    return
                log_txt.delete("1.0", "end")
                for fn in ("daemon.log", "native_host.log"):
                    p = get_cache_dir(create=False) / "logs" / fn
                    log_txt.insert("end", f"=== {fn} ===\n")
                    if p.exists():
                        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()[-80:]
                        log_txt.insert("end", "\n".join(lines) + "\n\n")
                    else:
                        log_txt.insert("end", f"{t('doc.log_empty')}\n\n")
                log_txt.see("end")

            def _clear_logs() -> None:
                for fn in ("daemon.log", "native_host.log"):
                    p = get_cache_dir(create=False) / "logs" / fn
                    if p.exists():
                        p.write_text("", encoding="utf-8")
                _reload_logs()

            ttk.Button(l_hdr, text=t("common.clear"), style="Secondary.TButton", command=_clear_logs).pack(side="right", padx=(6, 0))

            def _send_remote_log() -> None:
                def _job() -> None:
                    try:
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{IdmLinuxConfig.load(create_if_missing=False).http_port}/api/remote-log/flush",
                            data=json.dumps({}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        res = json.loads(urllib.request.urlopen(req, timeout=12).read().decode("utf-8"))
                        msg = (
                            f"{res.get('sent', 0)} log satırı uzak sunucuya gönderildi."
                            if res.get("configured")
                            else "Uzak log kurulu değil: config.json'a remote_log_url + remote_log_token ekleyin "
                            "(packaging/remote_log_server.php)."
                        )
                    except Exception as exc:
                        msg = f"Uzak log gönderilemedi: {exc}"
                    root.after(0, lambda: messagebox.showinfo("Uzak Log", msg))

                threading.Thread(target=_job, daemon=True).start()

            ttk.Button(
                doc_btn_bar, text="📡 Uzak Log'a Gönder", style="Secondary.TButton", command=_send_remote_log
            ).pack(side="left", padx=4)
            ttk.Button(l_hdr, text=t("common.refresh"), style="Secondary.TButton", command=_reload_logs).pack(side="right")

            # ==================================================================
            # SAYFA 6, 7 & 8: 🌟 DİĞER PROJELER  +  ❤️ DESTEKLE  +  🌐 DİL SEÇİMİ
            # ==================================================================
            _theme_colors = {
                "BG_MAIN": BG_MAIN,
                "BG_CARD": BG_CARD,
                "BG_CARD_ALT": BG_CARD_ALT,
                "BG_CONSOLE": BG_CONSOLE,
                "BORDER_SUBTLE": BORDER_SUBTLE,
                "FG_TEXT": FG_TEXT,
                "FG_MUTED": FG_MUTED,
                "ACCENT_CYAN": ACCENT_CYAN,
                "ACCENT_GREEN": ACCENT_GREEN,
            }
            # v2.9.0 ANINDA AÇILIŞ: ağır 3 sayfa pencere göründükten SONRA inşa edilir
            deferred_builders: Dict[str, Any] = {
                "projects": lambda: build_other_projects_page(
                    tk, ttk, root, pages["projects"], _theme_colors, copy_to_clipboard, i18n=i18n, font_family=ui_font
                ),
                "support": lambda: build_support_thank_you_page(
                    tk, ttk, root, pages["support"], _theme_colors, copy_to_clipboard, i18n=i18n, font_family=ui_font
                ),
                "language": lambda: build_language_selector_page(
                    tk,
                    ttk,
                    root,
                    pages["language"],
                    _theme_colors,
                    i18n=i18n,
                    on_select_language=lambda code: _switch_ui_language(code, target_page="language"),
                    font_family=ui_font,
                ),
                # v3.4.0: 9. sayfa — IDM Hakkında (vikipedi düzeyinde bilgi, iki yana yaslı metin)
                "about": lambda: build_about_idm_page(
                    tk, ttk, root, pages["about"], _theme_colors, i18n=i18n, font_family=ui_font, cfg=cfg
                ),
            }

            def _flush_deferred_pages() -> None:
                # v3.4.0 SINIRLI ARKA PLAN İNŞASI: eski davranış TÜM ağır sayfaları TEK olay
                # turunda inşa ediyordu -> açılışta belirgin takılma (kasma). Artık sayfalar
                # TEK TEK, 90 ms aralıklı boşluklarda inşa edilir: arayüz daima akıcı kalır,
                # kullanıcı bir sayfaya tıklarsa inşa ANINDA tamamlanır (switch_page zaten
                # bekleyen inşacıyı anında çalıştırır) — içerik her zaman hazır olur.
                if not deferred_builders:
                    return
                try:
                    _k, _fn = deferred_builders.popitem()
                    _fn()
                except Exception:
                    pass
                if deferred_builders:
                    try:
                        root.after(90, _flush_deferred_pages)
                    except Exception:
                        pass

            # ------------------------------------------------------------------
            # Canlı Durum Yenileyici (Asenkron — Arayüzü ASLA Dondurmaz!)
            # ------------------------------------------------------------------
            def _refresh_all_status_once() -> None:
                def _probe() -> None:
                    c_now = IdmLinuxConfig.load(create_if_missing=False)
                    data: Optional[Dict[str, Any]] = None
                    ed2k_data: Optional[Dict[str, Any]] = None
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{c_now.http_port}/api/status", timeout=1.0) as r:
                            data = json.loads(r.read().decode("utf-8"))
                    except Exception:
                        data = None
                    # v3.7.0: eD2K motor durumu (Genel Bakış detay satırı için)
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{c_now.http_port}/api/ed2k/status", timeout=2.0) as r:
                            ed2k_data = json.loads(r.read().decode("utf-8"))
                    except Exception:
                        ed2k_data = None

                    def _apply_ui() -> None:
                        if not shell.winfo_exists():
                            return
                        det_ver = (c_now.detect_installed_idm_version() or __idm_target_build__).replace(" Build ", " b")
                        lbl_brand_sub.configure(text=f"v{__version__} • IDM {det_ver}")
                        if data and data.get("ok"):
                            lbl_side_daemon.configure(text=t("side.bridge_active", port=c_now.http_port), fg=ACCENT_GREEN)
                            lbl_ov_daemon.configure(text=t("ov.state_active"), fg=ACCENT_GREEN)
                            lbl_ov_idm.configure(
                                text=t("ov.state_warm") if data.get("idm_running") else t("ov.state_idle"),
                                fg=ACCENT_GREEN if data.get("idm_running") else ACCENT_AMBER,
                            )
                            media_ok = data.get("ytdlp_installed") and data.get("ffmpeg_installed")
                            lbl_ov_media.configure(
                                text=t("ov.state_4k") if media_ok else t("ov.state_basic"),
                                fg=ACCENT_GREEN if media_ok else ACCENT_AMBER,
                            )
                            lbl_ov_count.configure(text=str(data.get("downloads_dispatched", 0)), fg=ACCENT_CYAN)
                            off_str = (
                                t("ov.det_official_connected")
                                if data.get("official_extension_connected")
                                else t("ov.det_official_hybrid")
                            )
                            # v3.10.0: torrent motoru artık KENDİ motorumuz (saf Python) —
                            # aria2c yalnız yedek. Durum satırı native motoru da "hazır" sayar.
                            tor_ok = bool(data.get("native_torrent") or data.get("aria2_installed"))
                            tor_str = t("ov.det_torrent_ready") if tor_ok else t("ov.det_torrent_webseed")
                            # v3.7.0: eD2K motor satırı
                            # v3.10.0: yerel (native) eD2K motoru da geçerli motordur
                            if ed2k_data and (
                                ed2k_data.get("backend") in ("mldonkey", "amule", "native", "native-ed2k")
                                or ed2k_data.get("native")
                            ):
                                _eng_name = ed2k_data.get("backend") or "native"
                                if _eng_name in ("native", "native-ed2k"):
                                    _eng_name = "IDM-Linux (native eD2K)"
                                _ed2k_running = bool(ed2k_data.get("running") or ed2k_data.get("native"))
                                ed2k_str = (
                                    t("ov.det_ed2k_ready", engine=_eng_name)
                                    if _ed2k_running
                                    else t("ov.det_ed2k_idle", engine=_eng_name)
                                )
                            else:
                                ed2k_str = t("ov.det_ed2k_missing")
                            lbl_ov_details.configure(
                                text="\n".join(
                                    [
                                        t("ov.det_distro", distro=sys_info.distro_name, display=sys_info.display_server, init=sys_info.init_system),
                                        t("ov.det_prefix", prefix=data.get("wine_prefix")),
                                        t("ov.det_wine", wine=data.get("wine_version") or t("ov.det_not_installed_short")),
                                        t("ov.det_idm_exe", exe=data.get("idm_exe") or t("ov.det_not_installed_long")),
                                        t("ov.det_ports", http=data.get("http_port"), ws=data.get("ws_port")),
                                        t("ov.det_memory", rss=data.get("rss_mb", 0), jobs=data.get("active_stream_jobs", 0)),
                                        t("ov.det_torrent", status=tor_str),
                                        t("ov.det_ed2k", status=ed2k_str),
                                        t("ov.det_official_ext", status=off_str),
                                        t("ov.det_dldir", dldir=c_now.download_dir),
                                    ]
                                )
                            )
                        else:
                            lbl_side_daemon.configure(text=t("side.bridge_offline"), fg=ACCENT_RED)
                            lbl_ov_daemon.configure(text=t("ov.state_offline"), fg=ACCENT_RED)
                            lbl_ov_idm.configure(text="—", fg=FG_MUTED)
                            lbl_ov_media.configure(text="—", fg=FG_MUTED)
                            lbl_ov_details.configure(text=t("ov.offline_help"))

                    try:
                        root.after(0, _apply_ui)
                    except RuntimeError:
                        pass

                threading.Thread(target=_probe, daemon=True).start()

            def _periodic_status_loop() -> None:
                if not shell.winfo_exists():
                    return
                _refresh_all_status_once()
                # v3.11.0 SIZINTI DÜZELTMESİ: kalıcı döngü id'leri biriktirilmez (+800 ölü id/saat)
                root.after(4500, _periodic_status_loop)

            _reload_logs()
            switch_page(open_page if open_page in pages else "overview")
            _drain_ui_queue()
            _periodic_status_loop()

        root.withdraw()  # v2.8.0: tema + sidebar inşa edilene dek pencereyi gizle (beyaz flaş YOK)
        _rebuild_shell(initial_page)
        try:
            root.update_idletasks()
            root.update()
        except Exception:
            pass
        try:
            if splash.winfo_exists():
                splash.update_idletasks()
                splash.update()
        except Exception:
            pass

    def _run_build_and_finish() -> None:
        _post_splash_build()
        # v2.8.3: tam sistem bilgisini arka planda tazele (Wine sürümü vb. etiketleri canlı güncellenir)
        def _bg_full_sysinfo() -> None:
            info = detect_system(quick=False)

            def _apply() -> None:
                lbl = inst_sum_lbl_ref[0] if inst_sum_lbl_ref else None
                if lbl is not None and lbl.winfo_exists():
                    lbl.configure(
                        text=i18n.t(
                            "inst.sys_summary",
                            distro=info.distro_name,
                            pm=info.pkg_manager,
                            wine=info.wine_version if info.wine_installed else i18n.t("inst.auto_install"),
                            ytdlp="✓" if info.ytdlp_path else i18n.t("inst.will_download"),
                            ffmpeg="✓" if info.ffmpeg_installed else i18n.t("inst.will_install"),
                            aria2="✓" if info.aria2_installed else i18n.t("inst.will_install"),
                        )
                    )

            try:
                root.after(0, _apply)
            except RuntimeError:
                pass

        threading.Thread(target=_bg_full_sysinfo, daemon=True).start()

        _gui_timing("build_done")
        # Splash, ana pencere görünmeden hemen önce kapanır (kullanıcıya kesintisiz geçiş)
        try:
            if splash.winfo_exists():
                splash.destroy()
                splash.update()
        except Exception:
            pass
        root.deiconify()
        try:
            root.after(150, _flush_deferred_pages)
        except Exception:
            pass

    # v2.8.3: splash GERÇEK olay döngüsünde çizilir (metinler garantili görünür), ağır inşa after() içinde
    root.after(250, _run_build_and_finish)
    root.mainloop()
    return 0
