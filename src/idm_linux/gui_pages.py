from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .i18n import (
    I18nManager,
    LANGUAGE_LIST,
    SUPPORTED_LANGUAGES,
    detect_system_language,
    get_idm_registry_language_pair,
)
from .projects_data import (
    BELGESELSEMO_PREMIUM_URL,
    BELGESELSEMO_WEB_URL,
    GOOGLE_PLAY_DEV_URL,
    NOWPAYMENTS_DONATION_URL,
    NOWPAYMENTS_POS_URL,
    PROJECTS_CATALOG,
    ProjectEntry,
    YOUTUBE_CHANNEL_URL,
    get_assets_dir,
)
from .qr_gen import render_qr_base64
from .rtl_shaper import contains_rtl, sanitize_tk_symbols, shape_rtl_for_tk
from .webview_modal import open_standalone_iframe_window


def _load_real_idm_icon_photo(tk_mod: Any, cfg: Any, img_refs: List[Any]) -> Optional[Any]:
    """v3.7.0: IDM Hakkında sayfası için GERÇEK IDM ikonunu kurulu IDMan.exe PE
    kaynaklarından çıkarır (256/128/64/48/32 px'lik en büyük resmi simge) ve
    önbelleğe alır. IDMan.exe yoksa None döner — çağıran jenerik ikona düşer.
    Kullanıcı raporu: 'IDM Hakkındaki ikon gerçek orijinal IDM ikonu olsun.'"""
    try:
        from .config import get_cache_dir
        from .pe_icon_extractor import extract_idman_official_icons

        exe = cfg.find_idm_exe() if cfg is not None else None
        if not exe:
            return None
        cache_dir = get_cache_dir(create=True) / "icons"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_png = cache_dir / "idman_official_hero.png"
        if not cached_png.is_file():
            icons = extract_idman_official_icons(Path(exe))
            if not icons:
                return None
            best_size = max(icons.keys())
            cached_png.write_bytes(icons[best_size])
        photo = tk_mod.PhotoImage(file=str(cached_png))
        img_refs.append(photo)
        return photo
    except Exception:
        return None


def open_external_url(url: str) -> None:
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(url)


def load_window_icons(tk_mod: Any) -> List[Any]:
    """Pencere başlığı ve görev çubuğu (Wayland/X11) için çoklu boyutta PNG ikonlarını yükler."""
    assets = get_assets_dir()
    icons: List[Any] = []
    for sz in (128, 64, 48, 32, 16):
        p = assets / f"idm_icon_{sz}.png"
        if p.is_file():
            try:
                icons.append(tk_mod.PhotoImage(file=str(p)))
            except Exception:
                pass
    return icons


def _font_families_cached(root: Any) -> Dict[str, str]:
    """v2.8.9: tkfont.families() soğuk fontconfig'te 10-15 sn sürebilir! Liste 7 gün önbelleklenir;
    kurulumda fc-list ile önceden ısıtılır. Önbellek yoksa ancak o zaman enumerate edilir."""
    import json as _json
    import time as _time

    try:
        import tkinter.font as tkfont
    except Exception:
        return {}
    try:
        from .config import get_cache_dir

        cf = get_cache_dir(create=True) / "font_families.json"
        if cf.is_file() and (_time.time() - cf.stat().st_mtime) < 7 * 86400:
            data = _json.loads(cf.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return {str(f).lower(): str(f) for f in data}
    except Exception:
        pass
    fams = {f.lower(): f for f in tkfont.families(root)}
    try:
        cf.write_text(_json.dumps(list(fams.values())), encoding="utf-8")
    except Exception:
        pass
    return fams


def pick_ui_font_family(root: Any, lang_code: str = "tr") -> str:
    """Seçilen dilin alfabesini (CJK, Devanagari, Arapça, Gürcüce, Kiril, Latin) en iyi çizen sistem fontunu seçer."""
    fams = _font_families_cached(root)
    if not fams:
        return "Sans"

    preferred_by_lang: Dict[str, List[str]] = {
        "zh": ["noto sans cjk sc", "noto sans sc", "wenquanyi micro hei", "droid sans fallback", "noto sans"],
        "ja": ["noto sans cjk jp", "noto sans jp", "ipagothic", "vl gothic", "droid sans fallback", "noto sans"],
        "hi": ["noto sans devanagari", "lohit devanagari", "gargi", "noto sans"],
        "ar": ["noto sans arabic", "noto naskh arabic", "amiri", "dejavu sans", "noto sans"],
        "fa": ["vazirmatn", "noto sans arabic", "noto naskh arabic", "dejavu sans", "noto sans"],
        "ka": ["noto sans georgian", "bpg glaho", "dejavu sans", "noto sans"],
    }
    candidates = preferred_by_lang.get(lang_code, []) + ["noto sans", "inter", "ubuntu", "cantarell", "dejavu sans"]
    for c in candidates:
        if c in fams:
            return fams[c]
    return "Sans"


def _tokenize_for_justify(text: str, lang_code: str) -> List[str]:
    """Boşluklu dillerde kelimelere, boşluksuz CJK (zh/ja) metinlerinde ise karakter/kelime birimlerine ayırır."""
    clean = " ".join(text.strip().split())
    if not clean:
        return []
    if lang_code in ("zh", "ja") and clean.count(" ") < max(2, len(clean) // 18):
        tokens: List[str] = []
        buf = ""
        for ch in clean:
            if ch.isascii() and (ch.isalnum() or ch in ".-_/+%"):
                buf += ch
            else:
                if buf:
                    tokens.append(buf)
                    buf = ""
                if not ch.isspace():
                    tokens.append(ch)
        if buf:
            tokens.append(buf)
        return tokens
    return clean.split(" ")


_JUSTIFY_MEASURE_CACHE: Dict[Tuple[str, int, str, str, str], int] = {}

def _measure_word_cached(font_key: Tuple[str, int, str, str], fnt: Any, word: str) -> int:
    """v3.7.1: fnt.measure() sonucunu (font, kelime) başına önbelleğe alır."""
    key = (font_key[0], font_key[1], font_key[2], font_key[3], word)
    val = _JUSTIFY_MEASURE_CACHE.get(key)
    if val is None:
        try:
            val = int(fnt.measure(word))
        except Exception:
            val = len(word) * 7
        if len(_JUSTIFY_MEASURE_CACHE) > 30000:
            _JUSTIFY_MEASURE_CACHE.clear()
        _JUSTIFY_MEASURE_CACHE[key] = val
    return val


def create_justified_text(
    tk_mod: Any,
    parent: Any,
    text: str,
    bg: str,
    fg: str,
    font_spec: Tuple[Any, ...] = ("Sans", 10),
    lang_code: str = "tr",
    rtl: bool = False,
    line_spacing: int = 5,
    initial_width: int = 680,
) -> Any:
    """
    Piksel hassasiyetli gerçek 'text-align: justify' (iki yana yaslama) Canvas bileşeni.
    Ara satırlardaki kelimeleri hem sol hem sağ kenara sıfır taşma ile hizalar; son satırı doğal hizada bırakır.
    """
    import tkinter.font as tkfont

    cv = tk_mod.Canvas(
        parent,
        bg=bg,
        highlightthickness=0,
        bd=0,
        height=24,
    )

    fam = font_spec[0] if len(font_spec) > 0 else "Sans"
    sz = int(font_spec[1]) if len(font_spec) > 1 else 10
    wt = "bold" if (len(font_spec) > 2 and "bold" in str(font_spec[2]).lower()) else "normal"
    sl = "italic" if (len(font_spec) > 2 and "italic" in str(font_spec[2]).lower()) else "roman"
    fnt = tkfont.Font(root=cv, family=fam, size=sz, weight=wt, slant=sl)
    _font_key: Tuple[str, int, str, str] = (str(fam), int(sz), str(wt), str(sl))

    paragraphs = [p.strip() for p in text.splitlines()]
    last_w = [0]

    def _redraw(avail_w: int) -> None:
        if avail_w < 80:
            return
        cv.delete("all")
        space_w = max(3, fnt.measure(" ")) if lang_code not in ("zh", "ja") else 0
        line_h = max(16, fnt.metrics("linespace") + line_spacing)
        y = 1
        pad_r = 2
        usable_w = max(60, avail_w - pad_r)

        for p_idx, para in enumerate(paragraphs):
            if not para:
                y += line_h // 2
                continue
            words = _tokenize_for_justify(para, lang_code)
            if not words:
                continue

            # v3.7.1 FONT ÖLÇÜM ÖNBELLEĞİ: aynı kelime aynı fontta defalarca ölçülüyordu
            # (15 kart × ~40 kelime = yüzlerce X11 turu). Önbellek ağır sayfaları
            # (Diğer Projeler / Teşekkür / IDM Hakkında) belirgin hızlandırır.
            word_widths = [_measure_word_cached(_font_key, fnt, w) for w in words]
            lines: List[Tuple[List[str], List[int], bool]] = []
            cur_w: List[str] = []
            cur_ww: List[int] = []
            cur_sum = 0

            for w_str, w_px in zip(words, word_widths):
                gap = space_w if cur_w else 0
                if cur_w and (cur_sum + gap + w_px > usable_w):
                    lines.append((cur_w, cur_ww, False))
                    cur_w = [w_str]
                    cur_ww = [w_px]
                    cur_sum = w_px
                else:
                    cur_w.append(w_str)
                    cur_ww.append(w_px)
                    cur_sum += gap + w_px
            if cur_w:
                lines.append((cur_w, cur_ww, True))

            for ln_words, ln_widths, is_last in lines:
                total_words_px = sum(ln_widths)
                gaps = len(ln_words) - 1
                natural_px = total_words_px + gaps * space_w
                slack = usable_w - natural_px

                # Son satır değilse, en az 2 kelime varsa ve boşluk oranı makulse tam iki yana yasla!
                do_justify = (not is_last) and (gaps >= 1) and (0 <= slack <= usable_w * 0.42)

                if rtl:
                    shaped_words = [shape_rtl_for_tk(w_s) if contains_rtl(w_s) else w_s for w_s in ln_words]
                    shaped_widths = [_measure_word_cached(_font_key, fnt, sw) for sw in shaped_words]
                    if not do_justify:
                        x_right = float(usable_w)
                        for sw_str, sw_px in zip(shaped_words, shaped_widths):
                            cv.create_text(int(round(x_right)), y, text=sw_str, anchor="ne", fill=fg, font=fnt)
                            x_right -= (sw_px + space_w)
                    else:
                        rtl_slack = max(0.0, float(usable_w - (sum(shaped_widths) + gaps * space_w)))
                        extra_per_gap = rtl_slack / float(gaps)
                        x_right = float(usable_w)
                        for sw_str, sw_px in zip(shaped_words, shaped_widths):
                            cv.create_text(int(round(x_right)), y, text=sw_str, anchor="ne", fill=fg, font=fnt)
                            x_right -= (sw_px + space_w + extra_per_gap)
                else:
                    if not do_justify:
                        full_line = (" " if space_w > 0 else "").join(ln_words)
                        cv.create_text(0, y, text=full_line, anchor="nw", fill=fg, font=fnt)
                    else:
                        extra_per_gap = slack / float(gaps)
                        x_left = 0.0
                        for w_str, w_px in zip(ln_words, ln_widths):
                            cv.create_text(int(round(x_left)), y, text=w_str, anchor="nw", fill=fg, font=fnt)
                            x_left += (w_px + space_w + extra_per_gap)

                y += line_h

            if p_idx < len(paragraphs) - 1:
                y += 4

        cv.configure(height=max(line_h, y + 2))

    _pending_redraw: Dict[str, Any] = {"after": None, "w": 0}

    def _on_cfg(ev: Any) -> None:
        # v3.8.0 PERFORMANS DEBounce: sayfa inşası sırasında aynı Canvas onlarca
        # Configure alır (ebeveyn genişlemeleri) — her biri TÜM metin öğelerini
        # silip yeniden yaratıyordu (3 kart × ~30 öğe ≈ yüzlerce Tk turu). Artık
        # kısa bir pencerede (12 ms) gelen olaylar TEK idle yeniden çizime iner;
        # son genişlik kazanır, görsel sonuç birebir aynı kalır.
        w = int(getattr(ev, "width", 0) or cv.winfo_width())
        if w <= 60 or abs(w - last_w[0]) < 3:
            return
        if _pending_redraw["after"] is not None:
            _pending_redraw["w"] = w
            return
        _pending_redraw["w"] = w
        try:
            _pending_redraw["after"] = cv.after(12, _flush_pending_redraw)
        except Exception:
            _pending_redraw["after"] = None
            _redraw(w)

    def _flush_pending_redraw() -> None:
        _pending_redraw["after"] = None
        w = int(_pending_redraw.get("w") or 0)
        try:
            if w > 60 and abs(w - last_w[0]) >= 3 and cv.winfo_exists():
                last_w[0] = w
                _redraw(w)
        except Exception:
            pass

    cv.bind("<Configure>", _on_cfg)
    _redraw(initial_width)
    return cv


def create_adaptive_button_bar(
    tk_mod: Any,
    ttk_mod: Any,
    parent: Any,
    bg: str,
    button_specs: List[Tuple[str, str, Callable[[], Any]]],
    gap_x: int = 8,
    gap_y: int = 6,
) -> Any:
    """
    Tam genişlik uyumlu (Full Adaptive / Responsive) buton çubuğu:
    - Genişlik yeterliyse tüm butonları tek satırda %100 eşit/tam genişlikte yayar.
    - Pencere küçüldüğünde sığmayan butonu alt satıra sarar ve her satırı yine %100 tam genişliğe yayar!
    """
    bar = tk_mod.Frame(parent, bg=bg)
    buttons: List[Any] = []
    for lbl_txt, style_name, cmd in button_specs:
        clean_lbl = sanitize_tk_symbols(lbl_txt)
        lbl_shaped = shape_rtl_for_tk(clean_lbl) if contains_rtl(clean_lbl) else clean_lbl
        btn = ttk_mod.Button(bar, text=lbl_shaped, style=style_name, command=cmd)
        buttons.append(btn)

    bar.update_idletasks()
    req_widths = [max(96, b.winfo_reqwidth() + 8) for b in buttons]
    current_cols = [0]

    def _apply_cols(cols: int) -> None:
        n = len(buttons)
        if n == 0:
            return
        cols = max(1, min(cols, n))
        if current_cols[0] == cols:
            return
        current_cols[0] = cols

        for b in buttons:
            b.grid_forget()
        for c in range(max(n, 4)):
            bar.columnconfigure(c, weight=0, uniform="")

        for c in range(cols):
            bar.columnconfigure(c, weight=1, uniform=f"adp_{id(bar)}_{cols}")

        for idx, b in enumerate(buttons):
            r_i, c_i = divmod(idx, cols)
            is_last_orphan = (idx == n - 1) and (c_i < cols - 1) and (r_i > 0)
            cspan = (cols - c_i) if is_last_orphan else 1
            px_l = 0 if c_i == 0 else gap_x // 2
            px_r = 0 if (c_i + cspan) >= cols else gap_x - (gap_x // 2)
            py_t = 0 if r_i == 0 else gap_y
            b.grid(row=r_i, column=c_i, columnspan=cspan, sticky="ew", padx=(px_l, px_r), pady=(py_t, 0))

    def _on_bar_cfg(ev: Any) -> None:
        w = int(getattr(ev, "width", 0) or bar.winfo_width())
        if w < 60:
            return
        n = len(buttons)
        # En yüksek sığabilen sütun sayısını seç
        chosen = 1
        for try_cols in range(n, 0, -1):
            # Her satırdaki en geniş grup sığıyor mu?
            fits = True
            for start in range(0, n, try_cols):
                grp = req_widths[start : start + try_cols]
                need = sum(grp) + max(0, len(grp) - 1) * gap_x
                if need > w:
                    fits = False
                    break
            if fits:
                chosen = try_cols
                break
        _apply_cols(chosen)

    _apply_cols(len(buttons))
    bar.bind("<Configure>", _on_bar_cfg)
    return bar


_SCROLL_AREA_REGISTRY: List[Dict[str, Any]] = []
_SCROLL_GLOBAL_BOUND = [False]

# v3.8.0 KRİTİK UYUMLULUK: Tk 9.0'da (Arch/Manjaro gibi güncel dağıtımlar) fare
# tekerleği olay numaraları yeniden numaralandı — X11 tekerlek yukarı=8 / aşağı=9
# (eski Tk 8.6'da 4/5 idi; 8/9 ise fiziksel yan tuşlardı). num alanına bakmadan
# sürümüne göre doğru eşleme seçilir; aksi hâlde dağıtıcı YÖN TAYİN EDEMEZ ve
# sayfa tekerleğe tepki vermez (kullanıcının 'Genel Bakış sayfası kaymıyor' raporu).
_WHEEL_UP_NUMS: Tuple[int, ...] = (4, 8)
_WHEEL_DOWN_NUMS: Tuple[int, ...] = (5, 9)


def _wheel_nums_for_runtime() -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
    """Çalışan Tk sürümüne göre (yukarı_numaraları, aşağı_numaraları) döner."""
    try:
        import tkinter as _tkmod

        if _tkmod.TkVersion >= 9.0:
            return (8,), (9,)
    except Exception:
        pass
    return (4,), (5,)


def _widget_ancestry(widget: Any) -> List[Any]:
    """Widget'ı kök pencereye dek ancestor zinciriyle döner."""
    chain: List[Any] = []
    seen: set = set()
    w = widget
    while w is not None and id(w) not in seen:
        seen.add(id(w))
        chain.append(w)
        try:
            parent_name = w.winfo_parent()
            w = w.nametowidget(parent_name) if parent_name else None
        except Exception:
            break
    return chain


def _global_scroll_dispatch(event: Any) -> None:
    """v3.7.1: Fare tekerleğini imlecin altındaki KAYDIRILABİLİR ALANA yönlendirir.

    Eski yöntem (her çocuğa tek tek bind) hem yeni eklenen bileşenleri kaçırıyordu
    (Genel Bakış sayfası tekerleğe tepki vermiyordu) hem de dinamik satırlarda
    sessizce kırılıyordu. bind_all + soy ağacı eşleşmesi TÜM bileşenleri — sonradan
    eklenenler dahil — otomatik kapsar; yalnızca imlecin bulunduğu sayfa kayar.
    v3.8.0: Tk 9.0 num eşlemesi (tekerlek 8/9) çalışma anında saptanır — yön
    tayini artık Tk 8.6 (4/5) ve Tk 9.0 (8/9) üzerinde birebir doğru çalışır.
    """
    global _WHEEL_UP_NUMS, _WHEEL_DOWN_NUMS
    try:
        if getattr(_global_scroll_dispatch, "_nums_ready", False) is not True:
            _WHEEL_UP_NUMS, _WHEEL_DOWN_NUMS = _wheel_nums_for_runtime()
            _global_scroll_dispatch._nums_ready = True  # type: ignore[attr-defined]
        delta = 3
        num = getattr(event, "num", None)
        wheel_delta = getattr(event, "delta", 0) or 0
        if (num is not None and num in _WHEEL_UP_NUMS) or wheel_delta > 0:
            delta = -3
        elif num is not None and num in _WHEEL_DOWN_NUMS:
            delta = 3
        src = getattr(event, "widget", None)
        if src is None:
            return
        if isinstance(src, str):
            try:
                src = _SCROLL_AREA_REGISTRY[0]["canvas"].nametowidget(src)
            except Exception:
                return
        chain = _widget_ancestry(src)
        chain_ids = {id(w) for w in chain}
        best: Optional[Dict[str, Any]] = None
        best_depth: Optional[int] = None
        for area in _SCROLL_AREA_REGISTRY:
            try:
                cv = area["canvas"]
                if not cv.winfo_exists():
                    continue
            except Exception:
                continue
            depth: Optional[int] = None
            for target in (area["canvas"], area["sb"]):
                if id(target) in chain_ids:
                    d = chain.index(target)
                    if depth is None or d < depth:
                        depth = d
            if depth is not None and (best_depth is None or depth < best_depth):
                best = area
                best_depth = depth
        if best is not None:
            best["step"](delta)
    except Exception:
        pass


def make_scrollable_area(
    tk_mod: Any,
    ttk_mod: Any,
    parent: Any,
    bg_color: str,
) -> Any:
    """Fare tekerleği (Linux X11/Wayland Button-4/5 + MouseWheel) destekli dikey kaydırılabilir alan.

    v3.7.0: kullanıcının 'aşırı ince, belli olmuyor' raporu üzerine çubuk KALINLAŞTIRILDI:
    16 px kanal + 12 px hap gövde; boşta bile net görünen açık gri-mavi renk, hover'da
    parlak cyan, sürüklerken koyu cyan. IDM Hakkında / Projeler / Genel Bakış dahil
    tüm kaydırılabilir sayfalarda aynı görünür çubuk kullanılır.
    """
    wrap = tk_mod.Frame(parent, bg=bg_color)
    wrap.pack(fill="both", expand=True)

    canvas = tk_mod.Canvas(wrap, bg=bg_color, highlightthickness=0, bd=0)
    sb = tk_mod.Canvas(wrap, width=16, bg=bg_color, highlightthickness=0, bd=0, cursor="arrow")

    sb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    # --- görünür (kalın) özel kaydırma çubuğu çizimi ---
    sb_cfg = {"hover": False, "dragging": False, "drag_off": 0.0}
    THUMB_W = 12         # v3.7.0: 6 -> 12 px (eşik-altı 'görünmez' çubuk şikayeti biter)
    THUMB_IDLE = "#46598a"    # boşta bile net seçilebilir (eski #2e405e çok soluktu)
    THUMB_HOVER = "#3ba3e8"
    THUMB_DRAG = "#0ea5e9"

    def _sb_on_yview(f0: Any, f1: Any) -> None:
        sb.delete("all")
        try:
            # v3.7.1 KRİTİK: Tkinter yscrollcommand argümanlarını DİZE olarak iletir;
            # dönüşüm yapılmazsa 'f1 - f0' TypeError fırlatır ve thumb HİÇ ÇİZİLEMEZDİ
            # (kullanıcının 'çubuk neredeyse belli olmuyor' şikayetinin gizli kök nedeni).
            f0f = float(f0)
            f1f = float(f1)
        except Exception:
            return
        try:
            sb_h = sb.winfo_height()
        except Exception:
            return
        if sb_h <= 2 or f1f - f0f >= 0.999:
            return  # kaydırılacak bir şey yok — çubuk gizli kalır
        if sb_cfg["dragging"]:
            color = THUMB_DRAG
        elif sb_cfg["hover"]:
            color = THUMB_HOVER
        else:
            color = THUMB_IDLE
        x0 = 2
        x1 = x0 + THUMB_W
        y0 = max(1.0, f0f * sb_h)
        y1 = min(sb_h - 1.0, f1f * sb_h)
        if y1 - y0 < 28:
            ort = (y0 + y1) / 2.0
            y0, y1 = ort - 14, ort + 14
        r = min(6.0, (x1 - x0) / 2.0, (y1 - y0) / 2.0)
        sb.create_rectangle(x0 + r, y0, x1 - r, y1, fill=color, outline="", width=0, tags=("thumb",))
        if r > 0:
            sb.create_oval(x0, y0 + r - r, x1, y0 + 2 * r, fill=color, outline="", width=0, tags=("thumb",))
            sb.create_oval(x0, y1 - 2 * r, x1, y1 - r + r, fill=color, outline="", width=0, tags=("thumb",))

    canvas.configure(yscrollcommand=_sb_on_yview)

    def _sb_update(_ev: Any = None) -> None:
        try:
            f0, f1 = canvas.yview()
        except Exception:
            return
        _sb_on_yview(f0, f1)

    sb.bind("<Enter>", lambda _e: (sb_cfg.__setitem__("hover", True), _sb_update()))
    sb.bind("<Leave>", lambda _e: (sb_cfg.__setitem__("hover", False), _sb_update()))

    def _sb_press(ev: Any) -> None:
        try:
            f0, f1 = canvas.yview()
            sb_h = sb.winfo_height()
            thumb_y0, thumb_y1 = f0 * sb_h, f1 * sb_h
            if thumb_y0 <= ev.y <= thumb_y1:
                sb_cfg["dragging"] = True
                sb_cfg["drag_off"] = ev.y - thumb_y0
            else:
                # kanala tıklama: sayfa atla (aşağı/yukarı)
                if ev.y < thumb_y0:
                    canvas.yview_scroll(-1, "pages")
                else:
                    canvas.yview_scroll(1, "pages")
                _sb_update()
        except Exception:
            pass

    def _sb_drag(ev: Any) -> None:
        if not sb_cfg["dragging"]:
            return
        try:
            sb_h = sb.winfo_height()
            f0, f1 = canvas.yview()
            frac = f1 - f0
            y0 = max(0.0, ev.y - sb_cfg["drag_off"])
            new_f0 = y0 / sb_h
            new_f0 = min(max(new_f0, 0.0), 1.0 - frac)
            canvas.yview_moveto(new_f0)
            _sb_update()
        except Exception:
            pass

    def _sb_release(_ev: Any = None) -> None:
        if sb_cfg["dragging"]:
            sb_cfg["dragging"] = False
            _sb_update()

    sb.bind("<Button-1>", _sb_press)
    sb.bind("<B1-Motion>", _sb_drag)
    sb.bind("<ButtonRelease-1>", _sb_release)

    inner = tk_mod.Frame(canvas, bg=bg_color)
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_cfg(_ev: Any = None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))
        _sb_update()

    def _on_canvas_cfg(ev: Any) -> None:
        canvas.itemconfigure(win_id, width=ev.width)
        _sb_update()

    inner.bind("<Configure>", _on_inner_cfg)
    canvas.bind("<Configure>", _on_canvas_cfg)

    def _scroll_step(units: int) -> None:
        try:
            canvas.yview_scroll(units, "units")
        except Exception:
            pass

    # v3.7.1 GLOBAL TEKERLEK DAĞITICISI: artık her çocuğa tek tek bind YOK —
    # alan kayıt defterine eklenir, bind_all olayları soy ağacıyla en derin
    # kaydırılabilir alana yönlendirilir. Sonradan eklenen bileşenler (Genel
    # Bakış canlı durum satırları, filtre kartları...) otomatik olarak kapsanır.
    _SCROLL_AREA_REGISTRY.append({"canvas": canvas, "sb": sb, "step": _scroll_step})
    canvas.bind("<Destroy>", lambda _e: _prune_scroll_registry(), add="+")

    if not _SCROLL_GLOBAL_BOUND[0]:
        _SCROLL_GLOBAL_BOUND[0] = True
        try:
            canvas.bind_all("<Button-4>", _global_scroll_dispatch, add="+")
            canvas.bind_all("<Button-5>", _global_scroll_dispatch, add="+")
            canvas.bind_all("<MouseWheel>", _global_scroll_dispatch, add="+")
        except Exception:
            pass

    def _rebind_mousewheel() -> None:
        # geriye dönük uyumluluk: çağıranlar hâlâ bunu çağırır; global dağıtıcı
        # sayesinde yapacak iş yok (yeni çocuklar zaten kapsanır).
        return None

    inner._rebind_mousewheel = _rebind_mousewheel  # type: ignore[attr-defined]
    return inner


def _prune_scroll_registry() -> None:
    """Yok edilmiş pencere alanlarını kayıt defterinden temizler."""
    try:
        alive = []
        for area in _SCROLL_AREA_REGISTRY:
            try:
                if area["canvas"].winfo_exists() and area["sb"].winfo_exists():
                    alive.append(area)
            except Exception:
                continue
        _SCROLL_AREA_REGISTRY[:] = alive
    except Exception:
        pass


def show_qr_modal(
    tk_mod: Any,
    ttk_mod: Any,
    root: Any,
    title: str,
    url: str,
    copy_fn: Callable[[str, Optional[str]], None],
    i18n: Optional[I18nManager] = None,
    font_family: str = "Sans",
) -> None:
    """Tıklandığında büyük boy yüksek netlikli Karekod (QR) penceresi açar."""
    t = i18n.t if i18n else (lambda k, **kw: k)
    win = tk_mod.Toplevel(root)
    win.title(t("common.qr_modal_title", title=title) if i18n else f"QR — {title}")
    win.configure(bg="#0f172a")
    win.resizable(False, False)
    win.transient(root)

    box = tk_mod.Frame(win, bg="#131c31", padx=24, pady=20, highlightthickness=1, highlightbackground="#23324d")
    box.pack(padx=16, pady=16)

    tk_mod.Label(
        box,
        text=title,
        bg="#131c31",
        fg="#f8fafc",
        font=(font_family, 12, "bold"),
        wraplength=360,
    ).pack(pady=(0, 10))

    b64 = render_qr_base64(url, scale=6, border=4)
    qr_img = tk_mod.PhotoImage(data=b64)
    win._qr_img = qr_img  # type: ignore[attr-defined]

    qr_lbl = tk_mod.Label(box, image=qr_img, bg="#ffffff", bd=4, relief="flat")
    qr_lbl.pack(pady=6)

    tk_mod.Label(
        box,
        text=t("common.qr_scan_hint") if i18n else "Scan with your phone camera to open directly.",
        bg="#131c31",
        fg="#94a3b8",
        font=(font_family, 9),
        wraplength=360,
    ).pack(pady=(8, 6))

    tk_mod.Label(
        box,
        text=url,
        bg="#090e17",
        fg="#38bdf8",
        padx=10,
        pady=6,
        font=("Monospace", 8),
        wraplength=360,
    ).pack(fill="x", pady=(0, 12))

    btns = tk_mod.Frame(box, bg="#131c31")
    btns.pack(fill="x")
    ttk_mod.Button(
        btns,
        text=t("common.open_browser") if i18n else "Open in Browser",
        style="Primary.TButton",
        command=lambda: open_external_url(url),
    ).pack(side="left", expand=True, fill="x", padx=(0, 6))
    ttk_mod.Button(
        btns,
        text=t("common.copy_link") if i18n else "Copy Link",
        style="Secondary.TButton",
        command=lambda: copy_fn(url, t("common.copied_msg", url=url) if i18n else url),
    ).pack(side="left", expand=True, fill="x", padx=(0, 6))
    ttk_mod.Button(
        btns,
        text=t("common.close") if i18n else "Close",
        style="Secondary.TButton",
        command=win.destroy,
    ).pack(side="left")


def build_other_projects_page(
    tk_mod: Any,
    ttk_mod: Any,
    root: Any,
    parent: Any,
    colors: Dict[str, str],
    copy_fn: Callable[[str, Optional[str]], None],
    i18n: Optional[I18nManager] = None,
    font_family: str = "Sans",
) -> None:
    """Sol menüdeki '🌟 Diğer Projeler' modern ve iki yana yaslı vitrin sayfasını oluşturur."""
    i18n_mgr = i18n or I18nManager("tr")
    t = i18n_mgr.t
    lang_code = i18n_mgr.lang
    rtl = bool(SUPPORTED_LANGUAGES.get(lang_code) and SUPPORTED_LANGUAGES[lang_code].rtl)

    BG_MAIN = colors["BG_MAIN"]
    BG_CARD = colors["BG_CARD"]
    BG_CARD_ALT = colors["BG_CARD_ALT"]
    BG_CONSOLE = colors["BG_CONSOLE"]
    BORDER = colors["BORDER_SUBTLE"]
    FG_TEXT = colors["FG_TEXT"]
    FG_MUTED = colors["FG_MUTED"]
    ACCENT_CYAN = colors["ACCENT_CYAN"]
    ACCENT_GREEN = colors["ACCENT_GREEN"]

    img_refs: List[Any] = []
    parent._proj_img_refs = img_refs  # type: ignore[attr-defined]
    assets_dir = get_assets_dir()

    def _load_png(filename: str) -> Optional[Any]:
        fp = assets_dir / filename
        if fp.is_file():
            try:
                im = tk_mod.PhotoImage(file=str(fp))
                img_refs.append(im)
                return im
            except Exception:
                return None
        return None

    bullet_emerald_img = _load_png("bullet_emerald.png")

    # Modern Üst Hero Banner Kartı
    hero = tk_mod.Frame(
        parent,
        bg="#101b33",
        padx=18,
        pady=14,
        highlightthickness=1,
        highlightbackground="#243b61",
    )
    hero.pack(fill="x", pady=(0, 10))

    hero_top = tk_mod.Frame(hero, bg="#101b33")
    hero_top.pack(fill="x")

    tk_mod.Label(
        hero_top,
        text=t("proj.title"),
        bg="#101b33",
        fg=FG_TEXT,
        font=(font_family, 14, "bold"),
    ).pack(side="left")

    top_links = tk_mod.Frame(hero_top, bg="#101b33")
    top_links.pack(side="right")
    ttk_mod.Button(
        top_links,
        text=t("proj.btn_gplay_dev"),
        style="Secondary.TButton",
        command=lambda: open_external_url(GOOGLE_PLAY_DEV_URL),
    ).pack(side="left", padx=(0, 6))
    ttk_mod.Button(
        top_links,
        text=t("proj.btn_youtube"),
        style="Primary.TButton",
        command=lambda: open_external_url(YOUTUBE_CHANNEL_URL),
    ).pack(side="left")

    sub_j = create_justified_text(
        tk_mod,
        hero,
        text=t("proj.subtitle"),
        bg="#101b33",
        fg="#cbd5e1",
        font_spec=(font_family, 9),
        lang_code=lang_code,
        rtl=rtl,
        line_spacing=4,
        initial_width=780,
    )
    sub_j.pack(fill="x", pady=(6, 8))

    # İstatistik Çipleri (Modern Pill Rozetler)
    pills_row = tk_mod.Frame(hero, bg="#101b33")
    pills_row.pack(fill="x")
    for pill_txt, pill_fg, pill_border in (
        (t("proj.stat_total"), "#38bdf8", "#0369a1"),
        (t("proj.stat_gplay"), "#34d399", "#047857"),
        (t("proj.stat_platforms"), "#fbbf24", "#b45309"),
    ):
        tk_mod.Label(
            pills_row,
            text=f"  {pill_txt}  ",
            bg="#091122",
            fg=pill_fg,
            padx=8,
            pady=3,
            font=(font_family, 8, "bold"),
            highlightthickness=1,
            highlightbackground=pill_border,
        ).pack(side="left", padx=(0, 8))

    # Kategori Filtre Çubuğu
    filter_bar = tk_mod.Frame(parent, bg=BG_MAIN)
    filter_bar.pack(fill="x", pady=(0, 8))

    active_cat = tk_mod.StringVar(value="all")
    _filter_seq = 0  # v3.7.1: filtre değişirse eski kart akışını iptal etmek için seri no
    filter_btns: Dict[str, Any] = {}

    categories = [
        ("all", t("proj.cat_all", count=len(PROJECTS_CATALOG))),
        ("web_media", t("proj.cat_web")),
        ("desktop", t("proj.cat_desktop")),
        ("google_play", t("proj.cat_gplay")),
        ("upcoming", t("proj.cat_upcoming")),
    ]

    scroll_inner = make_scrollable_area(tk_mod, ttk_mod, parent, BG_MAIN)
    cards_holder = tk_mod.Frame(scroll_inner, bg=BG_MAIN)
    cards_holder.pack(fill="x", expand=True, padx=(0, 8))

    qr_cache: Dict[str, Any] = {}

    def _get_small_qr(url: str) -> Any:
        if url not in qr_cache:
            b64 = render_qr_base64(url, scale=2, border=2)
            im = tk_mod.PhotoImage(data=b64)
            qr_cache[url] = im
            img_refs.append(im)
        return qr_cache[url]

    def _proj_text(proj: ProjectEntry, suffix: str, fallback: str) -> str:
        key = f"proj.item.{proj.slug}.{suffix}"
        val = t(key)
        return fallback if val == key else val

    def _render_project_card(proj: ProjectEntry) -> None:
        p_title = _proj_text(proj, "title", proj.title)
        p_sub = _proj_text(proj, "sub", proj.subtitle)
        p_badge = _proj_text(proj, "badge", proj.status_badge)
        p_meta = _proj_text(proj, "meta", f"{proj.release_info}  |  {proj.stats_info}  |  {proj.platforms}")
        p_desc = _proj_text(proj, "desc", proj.description)
        p_btn1 = _proj_text(proj, "btn1", proj.primary_btn_label)

        card_shell = tk_mod.Frame(
            cards_holder,
            bg=BG_CARD,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        card_shell.pack(fill="x", pady=(0, 12))

        # Sol dikey vurgu çizgisi (projenin kendi renk kodunda modern şerit)
        accent_stripe = tk_mod.Frame(card_shell, bg=proj.badge_color, width=5)
        accent_stripe.pack(side="left", fill="y")

        card = tk_mod.Frame(card_shell, bg=BG_CARD, padx=16, pady=14)
        card.pack(side="left", fill="both", expand=True)

        row_main = tk_mod.Frame(card, bg=BG_CARD)
        row_main.pack(fill="x")

        # Sol Sütun: Uygulama İkonu
        left_col = tk_mod.Frame(row_main, bg=BG_CARD)
        left_col.pack(side="left", anchor="n", padx=(0, 14))
        icon_img = _load_png(proj.icon_file)
        if icon_img is not None:
            icon_box = tk_mod.Frame(left_col, bg="#0b1324", padx=4, pady=4, highlightthickness=1, highlightbackground="#253654")
            icon_box.pack()
            tk_mod.Label(icon_box, image=icon_img, bg="#0b1324").pack()

        # Sağ Sütun: Karekod (QR) Kutusu
        if proj.qr_url:
            right_col = tk_mod.Frame(
                row_main,
                bg="#0b1324",
                padx=8,
                pady=8,
                highlightthickness=1,
                highlightbackground="#253654",
            )
            right_col.pack(side="right", anchor="n", padx=(14, 0))
            qr_im = _get_small_qr(proj.qr_url)
            qr_btn = tk_mod.Label(right_col, image=qr_im, bg="#ffffff", bd=2, cursor="hand2")
            qr_btn.pack()
            qr_btn.bind(
                "<Button-1>",
                lambda _e, pt=p_title, pu=proj.qr_url: show_qr_modal(
                    tk_mod, ttk_mod, root, pt, pu, copy_fn, i18n=i18n_mgr, font_family=font_family
                ),
            )
            qr_cap = tk_mod.Label(
                right_col,
                text=t("common.zoom_qr"),
                bg="#0b1324",
                fg=ACCENT_CYAN,
                cursor="hand2",
                font=(font_family, 8, "bold"),
            )
            qr_cap.pack(pady=(5, 0))
            qr_cap.bind(
                "<Button-1>",
                lambda _e, pt=p_title, pu=proj.qr_url: show_qr_modal(
                    tk_mod, ttk_mod, root, pt, pu, copy_fn, i18n=i18n_mgr, font_family=font_family
                ),
            )

        # Orta Sütun: Başlık + İki Yana Yaslı Açıklama + Özellikler + Butonlar
        mid_col = tk_mod.Frame(row_main, bg=BG_CARD)
        mid_col.pack(side="left", fill="both", expand=True)

        title_row = tk_mod.Frame(mid_col, bg=BG_CARD)
        title_row.pack(fill="x")
        tk_mod.Label(
            title_row,
            text=p_title,
            bg=BG_CARD,
            fg=FG_TEXT,
            font=(font_family, 11, "bold"),
        ).pack(side="left")

        tk_mod.Label(
            title_row,
            text=f" {p_badge} ",
            bg=proj.badge_color,
            fg="#ffffff",
            padx=7,
            pady=2,
            font=(font_family, 8, "bold"),
        ).pack(side="right")

        tk_mod.Label(
            mid_col,
            text=p_sub,
            bg=BG_CARD,
            fg="#7dd3fc",
            anchor="w",
            justify="left",
            font=(font_family, 9, "bold"),
        ).pack(fill="x", pady=(3, 5))

        meta_strip = tk_mod.Frame(mid_col, bg="#0b1324", padx=10, pady=5, highlightthickness=1, highlightbackground="#1e2d47")
        meta_strip.pack(fill="x", pady=(0, 8))
        tk_mod.Label(
            meta_strip,
            text=f"📅  {p_meta}",
            bg="#0b1324",
            fg="#cbd5e1",
            anchor="w",
            font=(font_family, 8, "bold"),
        ).pack(fill="x")

        # BELGESELSEMO RETRO EMULATOR özel sanat afişi (brand-splash.png)
        if proj.banner_file:
            banner_img = _load_png(proj.banner_file)
            if banner_img is not None:
                b_wrap = tk_mod.Frame(
                    mid_col,
                    bg=BG_CONSOLE,
                    padx=6,
                    pady=6,
                    highlightthickness=1,
                    highlightbackground="#f59e0b",
                )
                b_wrap.pack(fill="x", pady=(0, 8))
                tk_mod.Label(b_wrap, image=banner_img, bg=BG_CONSOLE).pack()
                tk_mod.Label(
                    b_wrap,
                    text=t("proj.retro_banner_caption"),
                    bg=BG_CONSOLE,
                    fg="#fbbf24",
                    font=(font_family, 8, "bold"),
                ).pack(pady=(4, 0))

        # Tam iki yana yaslı (Justified) açıklama metni!
        desc_block = create_justified_text(
            tk_mod,
            mid_col,
            text=p_desc,
            bg=BG_CARD,
            fg="#e2e8f0",
            font_spec=(font_family, 9),
            lang_code=lang_code,
            rtl=rtl,
            line_spacing=4,
            initial_width=560,
        )
        desc_block.pack(fill="x", pady=(0, 6))

        # Öne çıkan maddeler (PNG bullet + iki yana yaslı satırlar)
        hl_box = tk_mod.Frame(mid_col, bg="#0f182b", padx=10, pady=7, highlightthickness=1, highlightbackground="#1e2d47")
        hl_box.pack(fill="x", pady=(0, 8))
        for idx_h in (1, 2):
            fb_h = proj.highlights[idx_h - 1] if len(proj.highlights) >= idx_h else ""
            h_txt = _proj_text(proj, f"h{idx_h}", fb_h)
            if not h_txt:
                continue
            h_row = tk_mod.Frame(hl_box, bg="#0f182b")
            h_row.pack(fill="x", pady=2)
            if bullet_emerald_img is not None:
                tk_mod.Label(h_row, image=bullet_emerald_img, bg="#0f182b").pack(side="left", anchor="n", padx=(0, 7), pady=(2, 0))
            else:
                tk_mod.Label(h_row, text="✓", bg="#0f182b", fg=ACCENT_GREEN, font=(font_family, 9, "bold")).pack(side="left", anchor="n", padx=(0, 6))
            hj = create_justified_text(
                tk_mod,
                h_row,
                text=h_txt,
                bg="#0f182b",
                fg="#cbd5e1",
                font_spec=(font_family, 9),
                lang_code=lang_code,
                rtl=rtl,
                line_spacing=3,
                initial_width=510,
            )
            hj.pack(side="left", fill="x", expand=True)

        # Aksiyon Butonları (Tam Genişlik Uyumlu / Adaptive)
        proj_btn_specs: List[Tuple[str, str, Callable[[], Any]]] = [
            (f"↗  {p_btn1}", "Primary.TButton", lambda u=proj.primary_url: open_external_url(u)),
        ]
        if proj.secondary_url and proj.secondary_btn_label:
            p_btn2 = _proj_text(proj, "btn2", proj.secondary_btn_label)
            proj_btn_specs.append((p_btn2, "Secondary.TButton", lambda u=proj.secondary_url: open_external_url(u)))
        proj_btn_specs.append(
            (f"📋 {t('common.copy_link')}", "Secondary.TButton", lambda u=proj.primary_url: copy_fn(u, t("common.copied_msg", url=u)))
        )
        act_row = create_adaptive_button_bar(tk_mod, ttk_mod, mid_col, BG_CARD, proj_btn_specs)
        act_row.pack(fill="x", pady=(2, 0))

    def _apply_filter(cat_key: str) -> None:
        # v3.7.1 PROGRESSIVE RENDER: filtre ANINDA uygulanır; proje kartları
        # 3'lü gruplar hâlinde olay döngüsünde akar — sayfa kilitlenmez,
        # ilk kartlar milisaniyeler içinde görünür (kullanıcı raporu:
        # 'Diğer Projeler sayfası geç ve kasarak açılıyor').
        nonlocal _filter_seq
        _filter_seq += 1
        seq_now = _filter_seq
        active_cat.set(cat_key)
        for k, b in filter_btns.items():
            if k == cat_key:
                b.configure(bg=ACCENT_CYAN, fg="#ffffff", activebackground=ACCENT_CYAN, activeforeground="#ffffff")
            else:
                b.configure(bg=BG_CARD_ALT, fg=FG_MUTED, activebackground="#263554", activeforeground=FG_TEXT)

        for w in cards_holder.winfo_children():
            w.destroy()

        selected = [p for p in PROJECTS_CATALOG if cat_key == "all" or p.category == cat_key]

        state = {"i": 0}

        def _next_chunk() -> None:
            if seq_now != _filter_seq:
                return  # kullanıcı yeni filtre seçti — eski akışı bırak
            for p in selected[state["i"]:state["i"] + 3]:
                try:
                    _render_project_card(p)
                except Exception:
                    pass
            state["i"] += 3
            if state["i"] < len(selected):
                try:
                    root.after(30, _next_chunk)
                except Exception:
                    state["i"] = len(selected)
                    _next_chunk()

        _next_chunk()
        scroll_inner._rebind_mousewheel()

    for c_key, c_lbl in categories:
        fb = tk_mod.Button(
            filter_bar,
            text=c_lbl,
            padx=12,
            pady=6,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            cursor="hand2",
            font=(font_family, 9, "bold"),
            command=lambda k=c_key: _apply_filter(k),
        )
        fb.pack(side="left", padx=(0, 6))
        filter_btns[c_key] = fb

    _apply_filter("all")


def build_support_thank_you_page(
    tk_mod: Any,
    ttk_mod: Any,
    root: Any,
    parent: Any,
    colors: Dict[str, str],
    copy_fn: Callable[[str, Optional[str]], None],
    i18n: Optional[I18nManager] = None,
    font_family: str = "Sans",
) -> None:
    """Sol menüdeki '❤️ Teşekkür Et & Destekle' (4 yöntemli, iframe pencereli, iki yana yaslı) sayfasını oluşturur."""
    i18n_mgr = i18n or I18nManager("tr")
    t = i18n_mgr.t
    lang_code = i18n_mgr.lang
    rtl = bool(SUPPORTED_LANGUAGES.get(lang_code) and SUPPORTED_LANGUAGES[lang_code].rtl)

    BG_MAIN = colors["BG_MAIN"]
    BG_CARD = colors["BG_CARD"]
    BG_CARD_ALT = colors["BG_CARD_ALT"]
    BG_CONSOLE = colors["BG_CONSOLE"]
    BORDER = colors["BORDER_SUBTLE"]
    FG_TEXT = colors["FG_TEXT"]
    FG_MUTED = colors["FG_MUTED"]
    ACCENT_CYAN = colors["ACCENT_CYAN"]
    ACCENT_GREEN = colors["ACCENT_GREEN"]

    img_refs: List[Any] = []
    parent._supp_img_refs = img_refs  # type: ignore[attr-defined]
    assets_dir = get_assets_dir()

    def _load_asset_png(name: str) -> Optional[Any]:
        fp = assets_dir / name
        if fp.is_file():
            try:
                im = tk_mod.PhotoImage(file=str(fp))
                img_refs.append(im)
                return im
            except Exception:
                return None
        return None

    badge_yt = _load_asset_png("badge_yt.png")
    badge_heart = _load_asset_png("badge_heart.png")
    badge_crypto = _load_asset_png("badge_crypto.png")
    badge_crown = _load_asset_png("badge_crown.png")
    bullet_emerald = _load_asset_png("bullet_emerald.png")
    bullet_gold = _load_asset_png("bullet_gold.png")

    def _qr_photo(url: str, scale: int = 3) -> Any:
        b64 = render_qr_base64(url, scale=scale, border=2)
        im = tk_mod.PhotoImage(data=b64)
        img_refs.append(im)
        return im

    def _make_qr_tile(holder: Any, label: str, url: str, modal_title: str, scale: int = 2) -> None:
        box = tk_mod.Frame(holder, bg="#0b1324", padx=8, pady=7, highlightthickness=1, highlightbackground="#253654")
        box.pack(side="left", padx=(8, 0))
        im = _qr_photo(url, scale=scale)
        ql = tk_mod.Label(box, image=im, bg="#ffffff", bd=2, cursor="hand2")
        ql.pack()
        ql.bind(
            "<Button-1>",
            lambda _e: show_qr_modal(tk_mod, ttk_mod, root, modal_title, url, copy_fn, i18n=i18n_mgr, font_family=font_family),
        )
        cap = tk_mod.Label(box, text=label, bg="#0b1324", fg=ACCENT_CYAN, cursor="hand2", font=(font_family, 8, "bold"))
        cap.pack(pady=(4, 0))
        cap.bind(
            "<Button-1>",
            lambda _e: show_qr_modal(tk_mod, ttk_mod, root, modal_title, url, copy_fn, i18n=i18n_mgr, font_family=font_family),
        )

    # Üst Hero Başlık Kartı (Tam İki Yana Yaslı Açıklama)
    hero = tk_mod.Frame(
        parent,
        bg="#101b33",
        padx=18,
        pady=13,
        highlightthickness=1,
        highlightbackground="#243b61",
    )
    hero.pack(fill="x", pady=(0, 10))
    tk_mod.Label(
        hero,
        text=f"❤️  {t('sup.title')}",
        bg="#101b33",
        fg=FG_TEXT,
        font=(font_family, 14, "bold"),
    ).pack(anchor="w")

    hero_sub = create_justified_text(
        tk_mod,
        hero,
        text=t("sup.subtitle"),
        bg="#101b33",
        fg="#cbd5e1",
        font_spec=(font_family, 9),
        lang_code=lang_code,
        rtl=rtl,
        line_spacing=4,
        initial_width=780,
    )
    hero_sub.pack(fill="x", pady=(5, 0))

    scroll_inner = make_scrollable_area(tk_mod, ttk_mod, parent, BG_MAIN)
    body = tk_mod.Frame(scroll_inner, bg=BG_MAIN)
    body.pack(fill="x", expand=True, padx=(0, 8))

    def _method_shell(stripe_color: str, border_color: str) -> tk_mod.Frame:
        sh = tk_mod.Frame(body, bg=BG_CARD, highlightthickness=1, highlightbackground=border_color)
        sh.pack(fill="x", pady=(0, 12))
        tk_mod.Frame(sh, bg=stripe_color, width=5).pack(side="left", fill="y")
        inner = tk_mod.Frame(sh, bg=BG_CARD, padx=16, pady=14)
        inner.pack(side="left", fill="both", expand=True)
        return inner

    def _method_header(card_frame: Any, badge_img: Optional[Any], pill_bg: str, badge_txt: str, title_txt: str) -> None:
        hdr = tk_mod.Frame(card_frame, bg=BG_CARD)
        hdr.pack(fill="x", pady=(0, 8))
        if badge_img is not None:
            tk_mod.Label(hdr, image=badge_img, bg=BG_CARD).pack(side="left", padx=(0, 10))
        hdr_text_col = tk_mod.Frame(hdr, bg=BG_CARD)
        hdr_text_col.pack(side="left", fill="x", expand=True)
        pill_row = tk_mod.Frame(hdr_text_col, bg=BG_CARD)
        pill_row.pack(anchor="w")
        tk_mod.Label(
            pill_row,
            text=f" {badge_txt} ",
            bg=pill_bg,
            fg="#ffffff",
            padx=7,
            pady=2,
            font=(font_family, 8, "bold"),
        ).pack(side="left")
        title_lbl = tk_mod.Label(
            hdr_text_col,
            text=shape_rtl_for_tk(title_txt) if contains_rtl(title_txt) else title_txt,
            bg=BG_CARD,
            fg=FG_TEXT,
            anchor="w",
            justify="left",
            wraplength=560,
            font=(font_family, 11, "bold"),
        )
        title_lbl.pack(fill="x", pady=(4, 0))
        hdr_text_col.bind(
            "<Configure>",
            lambda ev, lb=title_lbl: lb.configure(wraplength=max(240, int(ev.width) - 8)),
        )

    def _build_method_1() -> None:
        # ───────────────────────────────────────────────────────────────────
        # 1. YÖNTEM: YOUTUBE ABONELİĞİ & MOBİL UYGULAMA İNDİRME / YORUM / PUAN
        # ───────────────────────────────────────────────────────────────────
        c1 = _method_shell("#ef4444", "#3b2331")
        _method_header(c1, badge_yt, "#dc2626", t("sup.m1_badge"), t("sup.m1_title"))

        c1_row = tk_mod.Frame(c1, bg=BG_CARD)
        c1_row.pack(fill="x")

        c1_qrs = tk_mod.Frame(c1_row, bg=BG_CARD)
        c1_qrs.pack(side="right", anchor="n", padx=(12, 0))
        _make_qr_tile(c1_qrs, t("sup.m1_qr_yt"), YOUTUBE_CHANNEL_URL, "BELGESELSEMO Learn & Explore (YouTube)")
        _make_qr_tile(c1_qrs, t("sup.m1_qr_gp"), GOOGLE_PLAY_DEV_URL, "BELGESELSEMO Google Play")

        c1_left = tk_mod.Frame(c1_row, bg=BG_CARD)
        c1_left.pack(side="left", fill="both", expand=True)

        c1_desc = create_justified_text(
            tk_mod,
            c1_left,
            text=t("sup.m1_desc"),
            bg=BG_CARD,
            fg="#e2e8f0",
            font_spec=(font_family, 9),
            lang_code=lang_code,
            rtl=rtl,
            line_spacing=4,
            initial_width=520,
        )
        c1_desc.pack(fill="x", pady=(0, 6))

        c1_btns = create_adaptive_button_bar(
            tk_mod,
            ttk_mod,
            c1,
            BG_CARD,
            [
                (f"▶  {t('sup.m1_btn_yt')}", "Primary.TButton", lambda: open_external_url(YOUTUBE_CHANNEL_URL)),
                (f"★  {t('sup.m1_btn_gp')}", "Success.TButton", lambda: open_external_url(GOOGLE_PLAY_DEV_URL)),
                (f"✦  {t('sup.m1_btn_web')}", "Secondary.TButton", lambda: open_external_url(BELGESELSEMO_WEB_URL)),
            ],
        )
        c1_btns.pack(fill="x", pady=(8, 0))


    def _build_method_2() -> None:
        # ───────────────────────────────────────────────────────────────────
        # 2. YÖNTEM: MANEVİ DESTEK & İYİLİK HALKASI (PNG İkonlu, 2 Sütunlu)
        # ───────────────────────────────────────────────────────────────────
        c2 = _method_shell("#10b981", "#1d3d38")
        _method_header(c2, badge_heart, "#059669", t("sup.m2_badge"), t("sup.m2_title"))

        c2_desc = create_justified_text(
            tk_mod,
            c2,
            text=t("sup.m2_desc"),
            bg=BG_CARD,
            fg="#e2e8f0",
            font_spec=(font_family, 9),
            lang_code=lang_code,
            rtl=rtl,
            line_spacing=4,
            initial_width=740,
        )
        c2_desc.pack(fill="x", pady=(0, 10))

        deeds_grid = tk_mod.Frame(c2, bg=BG_CARD)
        deeds_grid.pack(fill="x")
        deeds_grid.columnconfigure(0, weight=1)
        deeds_grid.columnconfigure(1, weight=1)

        for idx_d in range(6):
            r_i, col_i = divmod(idx_d, 2)
            d_cell = tk_mod.Frame(
                deeds_grid,
                bg="#0c1527",
                padx=11,
                pady=9,
                highlightthickness=1,
                highlightbackground="#1e3a3a",
            )
            d_cell.grid(row=r_i, column=col_i, sticky="nsew", padx=(0 if col_i == 0 else 5, 5 if col_i == 0 else 0), pady=4)
            if bullet_emerald is not None:
                tk_mod.Label(d_cell, image=bullet_emerald, bg="#0c1527").pack(side="left", anchor="n", padx=(0, 8), pady=(2, 0))
            dj = create_justified_text(
                tk_mod,
                d_cell,
                text=t(f"sup.m2_d{idx_d + 1}"),
                bg="#0c1527",
                fg="#d1fae5",
                font_spec=(font_family, 9),
                lang_code=lang_code,
                rtl=rtl,
                line_spacing=3,
                initial_width=320,
            )
            dj.pack(side="left", fill="x", expand=True)


    def _build_method_3() -> None:
        # ───────────────────────────────────────────────────────────────────
        # 3. YÖNTEM: KRİPTO BAĞIŞ & POS TERMİNALİ (Bağımsız <iframe> Penceresi!)
        # ───────────────────────────────────────────────────────────────────
        c3 = _method_shell("#f59e0b", "#45341b")
        _method_header(c3, badge_crypto, "#d97706", t("sup.m3_badge"), t("sup.m3_title"))

        c3_row = tk_mod.Frame(c3, bg=BG_CARD)
        c3_row.pack(fill="x")

        c3_qrs = tk_mod.Frame(c3_row, bg=BG_CARD)
        c3_qrs.pack(side="right", anchor="n", padx=(12, 0))
        _make_qr_tile(c3_qrs, t("sup.m3_qr_don"), NOWPAYMENTS_DONATION_URL, t("sup.iframe_tab_donation"))
        _make_qr_tile(c3_qrs, t("sup.m3_qr_pos"), NOWPAYMENTS_POS_URL, t("sup.iframe_tab_pos"))

        c3_left = tk_mod.Frame(c3_row, bg=BG_CARD)
        c3_left.pack(side="left", fill="both", expand=True)

        c3_desc = create_justified_text(
            tk_mod,
            c3_left,
            text=t("sup.m3_desc"),
            bg=BG_CARD,
            fg="#e2e8f0",
            font_spec=(font_family, 9),
            lang_code=lang_code,
            rtl=rtl,
            line_spacing=4,
            initial_width=510,
        )
        c3_desc.pack(fill="x", pady=(0, 8))

        # Doğrudan NOWPayments Bağış ve POS Link Kutuları (Tıklanabilir -> Bağımsız Iframe Penceresi!)
        links_panel = tk_mod.Frame(c3_left, bg="#09101f", padx=10, pady=8, highlightthickness=1, highlightbackground="#293852")
        links_panel.pack(fill="x", pady=(0, 10))

        for lbl_k, target_u, mode_k in (
            ("sup.m3_lbl_don", NOWPAYMENTS_DONATION_URL, "donation"),
            ("sup.m3_lbl_pos", NOWPAYMENTS_POS_URL, "pos"),
        ):
            lr = tk_mod.Frame(links_panel, bg="#09101f", cursor="hand2")
            lr.pack(fill="x", pady=2)
            lbl_tag = tk_mod.Label(
                lr,
                text=shape_rtl_for_tk(t(lbl_k)) if rtl else t(lbl_k),
                bg="#09101f",
                fg="#fbbf24",
                cursor="hand2",
                font=("Monospace", 8, "bold"),
            )
            lbl_tag.pack(side="left", padx=(0, 6))
            ul = tk_mod.Label(
                lr,
                text=target_u,
                bg="#09101f",
                fg="#38bdf8",
                cursor="hand2",
                font=("Monospace", 8, "underline"),
            )
            ul.pack(side="left")
            for clickable_w in (lr, lbl_tag, ul):
                clickable_w.bind(
                    "<Button-1>",
                    lambda _e, mk=mode_k, tu=target_u: open_standalone_iframe_window(
                        mode=mk,
                        lang_code=lang_code,
                        custom_url=tu,
                    ),
                )

        c3_btns1 = create_adaptive_button_bar(
            tk_mod,
            ttk_mod,
            c3,
            BG_CARD,
            [
                (
                    f"↗  {t('sup.m3_btn_widget_win')}",
                    "Success.TButton",
                    lambda: open_standalone_iframe_window(
                        mode="donation",
                        lang_code=lang_code,
                        custom_url=NOWPAYMENTS_DONATION_URL,
                    ),
                ),
                (
                    f"↗  {t('sup.m3_btn_pos_win')}",
                    "Primary.TButton",
                    lambda: open_standalone_iframe_window(
                        mode="pos",
                        lang_code=lang_code,
                        custom_url=NOWPAYMENTS_POS_URL,
                    ),
                ),
            ],
        )
        c3_btns1.pack(fill="x", pady=(8, 6))

        c3_btns2 = create_adaptive_button_bar(
            tk_mod,
            ttk_mod,
            c3,
            BG_CARD,
            [
                (
                    f"⧉  {t('sup.m3_btn_copy_don')}",
                    "Secondary.TButton",
                    lambda: copy_fn(NOWPAYMENTS_DONATION_URL, t("common.copied_msg", url=NOWPAYMENTS_DONATION_URL)),
                ),
                (
                    f"⧉  {t('sup.m3_btn_copy_pos')}",
                    "Secondary.TButton",
                    lambda: copy_fn(NOWPAYMENTS_POS_URL, t("common.copied_msg", url=NOWPAYMENTS_POS_URL)),
                ),
            ],
        )
        c3_btns2.pack(fill="x")


    def _build_method_4() -> None:
        # ───────────────────────────────────────────────────────────────────
        # 4. YÖNTEM: BELGESELSEMO PREMIUM ÜYELİK (https://belgeselsemo.com.tr/premium-uyelik/)
        # ───────────────────────────────────────────────────────────────────
        c4 = _method_shell("#a855f7", "#462963")
        _method_header(c4, badge_crown, "#7e22ce", t("sup.m4_badge"), t("sup.m4_title"))

        c4_row = tk_mod.Frame(c4, bg=BG_CARD)
        c4_row.pack(fill="x")

        c4_qrs = tk_mod.Frame(c4_row, bg=BG_CARD)
        c4_qrs.pack(side="right", anchor="n", padx=(12, 0))
        _make_qr_tile(c4_qrs, t("sup.m4_qr_lbl"), BELGESELSEMO_PREMIUM_URL, t("sup.m4_badge"), scale=3)

        c4_left = tk_mod.Frame(c4_row, bg=BG_CARD)
        c4_left.pack(side="left", fill="both", expand=True)

        c4_desc = create_justified_text(
            tk_mod,
            c4_left,
            text=t("sup.m4_desc"),
            bg=BG_CARD,
            fg="#e2e8f0",
            font_spec=(font_family, 9),
            lang_code=lang_code,
            rtl=rtl,
            line_spacing=4,
            initial_width=560,
        )
        c4_desc.pack(fill="x", pady=(0, 8))

        prem_box = tk_mod.Frame(c4_left, bg="#12142b", padx=11, pady=8, highlightthickness=1, highlightbackground="#3b275e")
        prem_box.pack(fill="x", pady=(0, 8))
        for idx_p in range(1, 5):
            pr = tk_mod.Frame(prem_box, bg="#12142b")
            pr.pack(fill="x", pady=2)
            if bullet_gold is not None:
                tk_mod.Label(pr, image=bullet_gold, bg="#12142b").pack(side="left", anchor="n", padx=(0, 8), pady=(2, 0))
            pj = create_justified_text(
                tk_mod,
                pr,
                text=t(f"sup.m4_h{idx_p}"),
                bg="#12142b",
                fg="#fef3c7",
                font_spec=(font_family, 9),
                lang_code=lang_code,
                rtl=rtl,
                line_spacing=3,
                initial_width=510,
            )
            pj.pack(side="left", fill="x", expand=True)

        # Sosyal Sorumluluk Hediyesi Kutusu
        soc_box = tk_mod.Frame(c4_left, bg="#0b1f22", padx=11, pady=8, highlightthickness=1, highlightbackground="#10b981")
        soc_box.pack(fill="x", pady=(0, 10))
        soc_j = create_justified_text(
            tk_mod,
            soc_box,
            text=t("sup.m4_social_note"),
            bg="#0b1f22",
            fg="#a7f3d0",
            font_spec=(font_family, 9, "bold"),
            lang_code=lang_code,
            rtl=rtl,
            line_spacing=3,
            initial_width=530,
        )
        soc_j.pack(fill="x")

        # Tıklanabilir Premium Üyelik (iframe) URL Satırı
        prem_link_panel = tk_mod.Frame(c4_left, bg="#09101f", padx=10, pady=7, highlightthickness=1, highlightbackground="#3b275e", cursor="hand2")
        prem_link_panel.pack(fill="x", pady=(0, 8))
        prem_lr = tk_mod.Frame(prem_link_panel, bg="#09101f", cursor="hand2")
        prem_lr.pack(fill="x")
        prem_lbl_tag = tk_mod.Label(
            prem_lr,
            text=f"★ {shape_rtl_for_tk(t('sup.m4_btn_win')) if rtl else t('sup.m4_btn_win')}:",
            bg="#09101f",
            fg="#d8b4fe",
            cursor="hand2",
            font=("Monospace", 8, "bold"),
        )
        prem_lbl_tag.pack(side="left", padx=(0, 6))
        prem_ul = tk_mod.Label(
            prem_lr,
            text=BELGESELSEMO_PREMIUM_URL,
            bg="#09101f",
            fg="#38bdf8",
            cursor="hand2",
            font=("Monospace", 8, "underline"),
        )
        prem_ul.pack(side="left")
        for pw in (prem_link_panel, prem_lr, prem_lbl_tag, prem_ul):
            pw.bind(
                "<Button-1>",
                lambda _e: open_standalone_iframe_window(
                    mode="premium",
                    lang_code=lang_code,
                    custom_url=BELGESELSEMO_PREMIUM_URL,
                ),
            )

        c4_btns = create_adaptive_button_bar(
            tk_mod,
            ttk_mod,
            c4,
            BG_CARD,
            [
                (
                    f"★  {t('sup.m4_btn_open')}",
                    "Primary.TButton",
                    lambda: open_external_url(BELGESELSEMO_PREMIUM_URL),
                ),
                (
                    f"↗  {t('sup.m4_btn_win')}",
                    "Secondary.TButton",
                    lambda: open_standalone_iframe_window(
                        mode="premium",
                        lang_code=lang_code,
                        custom_url=BELGESELSEMO_PREMIUM_URL,
                    ),
                ),
                (
                    f"⧉  {t('common.copy_link')}",
                    "Secondary.TButton",
                    lambda: copy_fn(BELGESELSEMO_PREMIUM_URL, t("common.copied_msg", url=BELGESELSEMO_PREMIUM_URL)),
                ),
            ],
        )
        c4_btns.pack(fill="x", pady=(8, 0))


    _method_builders = [_build_method_1, _build_method_2, _build_method_3, _build_method_4]

    def _drain_method_builders() -> None:
        # v3.7.1 PROGRESSIVE RENDER: sayfa ANINDA açılır (hero + iskelet); ağır
        # yöntem kartları olay döngüsünde TEKER TEKER akar — arayüz asla kilitlenmez.
        if not _method_builders:
            return
        fn_b = _method_builders.pop(0)
        try:
            fn_b()
        except Exception:
            pass
        try:
            root.after(45, _drain_method_builders)
        except Exception:
            pass

    _drain_method_builders()

    scroll_inner._rebind_mousewheel()


def build_language_selector_page(
    tk_mod: Any,
    ttk_mod: Any,
    root: Any,
    parent: Any,
    colors: Dict[str, str],
    i18n: I18nManager,
    on_select_language: Callable[[str], None],
    font_family: str = "Sans",
) -> None:
    """Sol menüdeki '🌐 Dil Seçimi' (20 Bayraklı Dil + Otomatik Sistem & IDM Dil Senkronizasyonu) sayfasını oluşturur."""
    t = i18n.t
    lang_code = i18n.lang
    rtl = bool(SUPPORTED_LANGUAGES.get(lang_code) and SUPPORTED_LANGUAGES[lang_code].rtl)

    def _ui_txt(s: str) -> str:
        s_clean = sanitize_tk_symbols(s)
        return shape_rtl_for_tk(s_clean) if contains_rtl(s_clean) else s_clean

    BG_MAIN = colors["BG_MAIN"]
    BG_CARD = colors["BG_CARD"]
    BORDER = colors["BORDER_SUBTLE"]
    FG_TEXT = colors["FG_TEXT"]
    FG_MUTED = colors["FG_MUTED"]
    ACCENT_GREEN = colors["ACCENT_GREEN"]

    assets_dir = get_assets_dir()
    img_refs: List[Any] = []
    flag_map: Dict[str, Any] = {}
    for lspec in LANGUAGE_LIST:
        fp = assets_dir / f"flag_{lspec.code}.png"
        if fp.is_file():
            try:
                f_img = tk_mod.PhotoImage(file=str(fp))
                img_refs.append(f_img)
                flag_map[lspec.code] = f_img
            except Exception:
                pass
    parent._lang_flag_refs = img_refs  # type: ignore[attr-defined]

    hero = tk_mod.Frame(
        parent,
        bg="#101b33",
        padx=18,
        pady=14,
        highlightthickness=1,
        highlightbackground="#243b61",
    )
    hero.pack(fill="x", pady=(0, 12))
    hero_hdr = tk_mod.Frame(hero, bg="#101b33")
    hero_hdr.pack(fill="x")
    if lang_code in flag_map:
        tk_mod.Label(hero_hdr, image=flag_map[lang_code], bg="#101b33").pack(side="left", padx=(0, 10))
    tk_mod.Label(
        hero_hdr,
        text=_ui_txt(t("lang.title")),
        bg="#101b33",
        fg=FG_TEXT,
        font=(font_family, 14, "bold"),
    ).pack(side="left")

    sub_j = create_justified_text(
        tk_mod,
        hero,
        text=t("lang.subtitle"),
        bg="#101b33",
        fg="#cbd5e1",
        font_spec=(font_family, 9),
        lang_code=lang_code,
        rtl=rtl,
        line_spacing=4,
        initial_width=780,
    )
    sub_j.pack(fill="x", pady=(6, 0))

    # Aktif Dil & IDM Senkronizasyon Durum Kartı
    spec = SUPPORTED_LANGUAGES[lang_code]
    sys_code = detect_system_language()
    sys_spec = SUPPORTED_LANGUAGES.get(sys_code, SUPPORTED_LANGUAGES["en"])
    raw_env_locale = (
        os.environ.get("LC_ALL")
        or os.environ.get("LC_MESSAGES")
        or os.environ.get("LANG")
        or sys_code
    )
    lang_id, lng_file = get_idm_registry_language_pair(lang_code)

    status_card = tk_mod.Frame(
        parent,
        bg=BG_CARD,
        padx=16,
        pady=12,
        highlightthickness=1,
        highlightbackground=BORDER,
    )
    status_card.pack(fill="x", pady=(0, 12))
    tk_mod.Label(
        status_card,
        text=_ui_txt(t("lang.active_card_title")),
        bg=BG_CARD,
        fg=FG_TEXT,
        font=(font_family, 11, "bold"),
    ).pack(anchor="w", pady=(0, 6))

    cur_row = tk_mod.Frame(status_card, bg=BG_CARD)
    cur_row.pack(anchor="w", pady=1)
    if lang_code in flag_map:
        tk_mod.Label(cur_row, image=flag_map[lang_code], bg=BG_CARD).pack(side="left", padx=(0, 8))
    tk_mod.Label(
        cur_row,
        text=_ui_txt(
            t(
                "lang.current_gui_lang",
                native=spec.native_name,
                english=spec.english_name,
                code=spec.code.upper(),
            )
        ),
        bg=BG_CARD,
        fg="#38bdf8",
        font=(font_family, 9, "bold"),
    ).pack(side="left")

    tk_mod.Label(
        status_card,
        text=_ui_txt(t("lang.detected_sys_lang", sys_lang=f"{sys_spec.native_name} ({raw_env_locale})")),
        bg=BG_CARD,
        fg=FG_MUTED,
        font=(font_family, 9),
    ).pack(anchor="w", pady=1)

    if spec.idm_supported_natively:
        idm_txt = t("lang.idm_match_native", lng_file=lng_file or "Built-in English", lang_id=lang_id)
        idm_fg = ACCENT_GREEN
    else:
        idm_txt = t("lang.idm_match_fallback")
        idm_fg = "#fbbf24"

    tk_mod.Label(
        status_card,
        text=_ui_txt(idm_txt),
        bg=BG_CARD,
        fg=idm_fg,
        font=(font_family, 9, "bold"),
        wraplength=800,
        justify="left",
    ).pack(anchor="w", pady=(3, 0))

    # 20 Dil Izgarası (4 Sütun x 5 Satır — Her Kartta Gerçek PNG Bayrak Simgesi!)
    grid_card = tk_mod.Frame(
        parent,
        bg=BG_CARD,
        padx=16,
        pady=12,
        highlightthickness=1,
        highlightbackground=BORDER,
    )
    grid_card.pack(fill="both", expand=True)
    tk_mod.Label(
        grid_card,
        text=_ui_txt(t("lang.grid_title")),
        bg=BG_CARD,
        fg=FG_TEXT,
        font=(font_family, 11, "bold"),
    ).pack(anchor="w", pady=(0, 8))

    scroll_inner = make_scrollable_area(tk_mod, ttk_mod, grid_card, BG_CARD)
    grid_wrap = tk_mod.Frame(scroll_inner, bg=BG_CARD)
    grid_wrap.pack(fill="x", expand=True, padx=(0, 6))

    for col in range(4):
        grid_wrap.columnconfigure(col, weight=1, uniform="langcol")

    for idx, lspec in enumerate(LANGUAGE_LIST):
        r_i, c_i = divmod(idx, 4)
        is_sel = lspec.code == lang_code
        tile_bg = "#172b4d" if is_sel else "#0c1527"
        tile_border = "#38bdf8" if is_sel else "#22324f"
        tile_thick = 2 if is_sel else 1

        tile = tk_mod.Frame(
            grid_wrap,
            bg=tile_bg,
            padx=11,
            pady=9,
            cursor="hand2",
            highlightthickness=tile_thick,
            highlightbackground=tile_border,
        )
        tile.grid(row=r_i, column=c_i, sticky="nsew", padx=5, pady=5)

        top_r = tk_mod.Frame(tile, bg=tile_bg, cursor="hand2")
        top_r.pack(fill="x")

        clickable_widgets: List[Any] = [tile, top_r]

        f_icon = flag_map.get(lspec.code)
        if f_icon is not None:
            flg_lbl = tk_mod.Label(top_r, image=f_icon, bg=tile_bg, cursor="hand2")
            flg_lbl.pack(side="left", padx=(0, 7))
            clickable_widgets.append(flg_lbl)

        code_lbl = tk_mod.Label(
            top_r,
            text=f"{'✓ ' if is_sel else ''}{lspec.code.upper()}",
            bg="#0284c7" if is_sel else "#1e293b",
            fg="#ffffff" if is_sel else "#94a3b8",
            padx=6,
            pady=1,
            font=("Monospace", 8, "bold"),
            cursor="hand2",
        )
        code_lbl.pack(side="left")
        clickable_widgets.append(code_lbl)

        idm_pill_txt = _ui_txt(t("lang.badge_idm_native") if lspec.idm_supported_natively else t("lang.badge_idm_en"))
        idm_pill_fg = "#34d399" if lspec.idm_supported_natively else "#fbbf24"
        idm_lbl = tk_mod.Label(
            top_r,
            text=idm_pill_txt,
            bg=tile_bg,
            fg=idm_pill_fg,
            font=(font_family, 7, "bold"),
            cursor="hand2",
        )
        idm_lbl.pack(side="right", padx=(4, 0))
        clickable_widgets.append(idm_lbl)

        tile_font = pick_ui_font_family(root, lspec.code)
        nat_lbl = tk_mod.Label(
            tile,
            text=_ui_txt(lspec.native_name),
            bg=tile_bg,
            fg="#ffffff" if is_sel else FG_TEXT,
            anchor="w",
            font=(tile_font, 11, "bold"),
            cursor="hand2",
        )
        nat_lbl.pack(fill="x", pady=(7, 1))
        clickable_widgets.append(nat_lbl)

        eng_lbl = tk_mod.Label(
            tile,
            text=lspec.english_name,
            bg=tile_bg,
            fg="#7dd3fc" if is_sel else FG_MUTED,
            anchor="w",
            font=(font_family, 8),
            cursor="hand2",
        )
        eng_lbl.pack(fill="x")
        clickable_widgets.append(eng_lbl)

        def _hover_in(_ev: Any = None, ws: List[Any] = clickable_widgets, sel: bool = is_sel, t_w: Any = tile, c_w: Any = code_lbl) -> None:
            if not sel:
                t_w.configure(highlightbackground="#38bdf8")

        def _hover_out(_ev: Any = None, sel: bool = is_sel, t_w: Any = tile) -> None:
            if not sel:
                t_w.configure(highlightbackground="#22324f")

        tile.bind("<Enter>", _hover_in)
        tile.bind("<Leave>", _hover_out)

        def _bind_click(w_item: Any, target_code: str = lspec.code) -> None:
            w_item.bind("<Button-1>", lambda _e: on_select_language(target_code))

        for w_sub in clickable_widgets:
            _bind_click(w_sub)

    scroll_inner._rebind_mousewheel()


# v3.4.0 — 9. SAYFA: ℹ️ IDM HAKKINDA
# =========================================================================
IDM_OFFICIAL_SITE_URL = "https://www.internetdownloadmanager.com/"


def build_about_idm_page(
    tk_mod: Any,
    ttk_mod: Any,
    root: Any,
    parent: Any,
    colors: Dict[str, str],
    i18n: Optional[I18nManager] = None,
    font_family: str = "Sans",
    cfg: Optional[Any] = None,
) -> None:
    """Sol menü 9. seçenek 'ℹ️ IDM Hakkında': IDM'nin resmi IDM simgesiyle birlikte
    vikipedi düzeyinde detaylı bilgisi — metinler GERÇEK 'text-align: justify'
    (iki yana yaslı) piksel hassasiyetiyle dizilir; 20 dilde tam çeviridir.

    Sayfa ayrıca IDM Linux projesini tanıtır (BELGESELSEMO açık kaynak, trial sürüm
    ve resmi siteden lisans alınması notu) ve kurulu IDM sürümünü gösterir."""
    i18n_mgr = i18n or I18nManager("tr")
    t = i18n_mgr.t
    lang_code = i18n_mgr.lang
    rtl = bool(SUPPORTED_LANGUAGES.get(lang_code) and SUPPORTED_LANGUAGES[lang_code].rtl)

    BG_MAIN = colors["BG_MAIN"]
    BG_CARD = colors["BG_CARD"]
    BG_CARD_ALT = colors["BG_CARD_ALT"]
    BORDER = colors["BORDER_SUBTLE"]
    FG_TEXT = colors["FG_TEXT"]
    FG_MUTED = colors["FG_MUTED"]
    ACCENT_CYAN = colors["ACCENT_CYAN"]
    ACCENT_GREEN = colors["ACCENT_GREEN"]

    img_refs: List[Any] = []
    parent._about_img_refs = img_refs  # type: ignore[attr-defined]

    # Sayfanın tamamı kaydırılabilir alan (fare tekeri destekli)
    scroll_inner = make_scrollable_area(tk_mod, ttk_mod, parent, BG_MAIN)

    # --- HERO: IDM simgesi + başlık + slogan + bilgi çipleri -----------------
    hero = tk_mod.Frame(
        scroll_inner,
        bg="#101b33",
        padx=18,
        pady=16,
        highlightthickness=1,
        highlightbackground="#243b61",
    )
    hero.pack(fill="x", pady=(0, 10))

    hero_body = tk_mod.Frame(hero, bg="#101b33")
    hero_body.pack(fill="x")

    icon_path = get_assets_dir() / "idm_icon_128.png"
    real_ic = _load_real_idm_icon_photo(tk_mod, cfg, img_refs)
    if real_ic is not None:
        try:
            tk_mod.Label(hero_body, image=real_ic, bg="#101b33").pack(side="left", padx=(0, 14))
        except Exception:
            real_ic = None
    if real_ic is None and icon_path.is_file():
        try:
            _ic = tk_mod.PhotoImage(file=str(icon_path))
            img_refs.append(_ic)
            tk_mod.Label(hero_body, image=_ic, bg="#101b33").pack(side="left", padx=(0, 14))
        except Exception:
            pass

    hero_txt = tk_mod.Frame(hero_body, bg="#101b33")
    hero_txt.pack(side="left", fill="x", expand=True)
    tk_mod.Label(
        hero_txt,
        text=t("about.title"),
        bg="#101b33",
        fg=FG_TEXT,
        font=(font_family, 15, "bold"),
        anchor="w",
    ).pack(fill="x")
    tk_mod.Label(
        hero_txt,
        text=t("about.tagline"),
        bg="#101b33",
        fg=ACCENT_CYAN,
        font=(font_family, 9, "bold"),
        anchor="w",
        wraplength=640,
        justify="left",
    ).pack(fill="x", pady=(3, 0))

    chips_row = tk_mod.Frame(hero, bg="#101b33")
    chips_row.pack(fill="x", pady=(10, 0))

    idm_ver = ""
    if cfg is not None:
        try:
            idm_ver = (cfg.detect_installed_idm_version() or "").strip()
        except Exception:
            idm_ver = ""

    def _chip(txt: str, fg: str, border: str) -> None:
        c = tk_mod.Label(
            chips_row,
            text=sanitize_tk_symbols(txt),
            bg="#0c1526",
            fg=fg,
            font=(font_family, 8, "bold"),
            padx=10,
            pady=4,
            highlightthickness=1,
            highlightbackground=border,
        )
        c.pack(side="left", padx=(0, 6), pady=2)

    _chip(t("about.chip_owner"), "#38bdf8", "#0369a1")
    _chip(t("about.chip_first"), "#34d399", "#047857")
    _chip(t("about.chip_platform"), "#fbbf24", "#b45309")
    if idm_ver:
        _chip(t("about.chip_version", version=idm_ver.replace(" Build ", " b")), "#a78bfa", "#6d28d9")
    else:
        _chip(t("about.chip_target"), "#a78bfa", "#6d28d9")

    # --- Bilgi kartları (iki yana yaslı uzun metinler) ----------------------
    def _section(title: str, body: str, accent: str = ACCENT_CYAN, fg_body: str = "#cbd5e1") -> None:
        card = tk_mod.Frame(
            scroll_inner,
            bg=BG_CARD,
            padx=16,
            pady=12,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        card.pack(fill="x", pady=(0, 10))
        tk_mod.Label(
            card,
            text=title,
            bg=BG_CARD,
            fg=accent,
            font=(font_family, 11, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 6))
        body_j = create_justified_text(
            tk_mod,
            card,
            text=body,
            bg=BG_CARD,
            fg=fg_body,
            font_spec=(font_family, 9),
            lang_code=lang_code,
            rtl=rtl,
            line_spacing=5,
            initial_width=820,
        )
        body_j.pack(fill="x")

    _section(t("about.section_what"), t("about.what"), ACCENT_CYAN)
    _section(t("about.section_history"), t("about.history"), "#38bdf8")
    _section(t("about.section_features"), t("about.features"), ACCENT_GREEN)
    # v3.7.0: kullanıcı talebi — bilgi metinleri daha da uzun ve derinlemesine
    _section(t("about.section_speed"), t("about.speed"), "#f472b6")
    _section(t("about.section_categories"), t("about.categories"), "#fbbf24")
    _section(t("about.section_versions"), t("about.versions"), "#a78bfa")

    # --- IDM LINUX PROJESİ kartı --------------------------------------------
    proj_card = tk_mod.Frame(
        scroll_inner,
        bg="#0d1a2d",
        padx=16,
        pady=12,
        highlightthickness=1,
        highlightbackground="#1d4ed8",
    )
    proj_card.pack(fill="x", pady=(0, 10))
    tk_mod.Label(
        proj_card,
        text=t("about.section_project"),
        bg="#0d1a2d",
        fg="#7dd3fc",
        font=(font_family, 11, "bold"),
        anchor="w",
    ).pack(fill="x", pady=(0, 6))
    proj_j = create_justified_text(
        tk_mod,
        proj_card,
        text=t("about.project"),
        bg="#0d1a2d",
        fg="#dbeafe",
        font_spec=(font_family, 9),
        lang_code=lang_code,
        rtl=rtl,
        line_spacing=5,
        initial_width=820,
    )
    proj_j.pack(fill="x")
    # Lisans notu vurgulu (emerald) satır
    lic_j = create_justified_text(
        tk_mod,
        proj_card,
        text=t("about.license_note"),
        bg="#0d1a2d",
        fg="#6ee7b7",
        font_spec=(font_family, 9, "bold"),
        lang_code=lang_code,
        rtl=rtl,
        line_spacing=5,
        initial_width=820,
    )
    lic_j.pack(fill="x", pady=(8, 0))

    # --- Resmi site + yerel kurulum satırı ----------------------------------
    foot = tk_mod.Frame(scroll_inner, bg=BG_CARD_ALT, padx=16, pady=10, highlightthickness=1, highlightbackground=BORDER)
    foot.pack(fill="x", pady=(0, 4))
    foot_l = tk_mod.Frame(foot, bg=BG_CARD_ALT)
    foot_l.pack(side="left", fill="x", expand=True)
    tk_mod.Label(
        foot_l,
        text=t("about.official_note"),
        bg=BG_CARD_ALT,
        fg=FG_MUTED,
        font=(font_family, 8),
        anchor="w",
        wraplength=620,
        justify="left",
    ).pack(fill="x")
    ttk_mod.Button(
        foot,
        text=t("about.btn_official"),
        style="Primary.TButton",
        command=lambda: open_external_url(IDM_OFFICIAL_SITE_URL),
    ).pack(side="right", padx=(10, 0))

    scroll_inner._rebind_mousewheel()
