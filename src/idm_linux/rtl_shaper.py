from __future__ import annotations

import re
from typing import Dict, Tuple

# (Isolated, Final, Initial, Medial) — Initial/Medial None ise sağdan bağlanan (right-joining only) harftir.
_AR_FORMS: Dict[str, Tuple[str, str, str | None, str | None]] = {
    "\u0621": ("\uFE80", "\uFE80", None, None),          # ء
    "\u0622": ("\uFE81", "\uFE82", None, None),          # آ
    "\u0623": ("\uFE83", "\uFE84", None, None),          # أ
    "\u0624": ("\uFE85", "\uFE86", None, None),          # ؤ
    "\u0625": ("\uFE87", "\uFE88", None, None),          # إ
    "\u0626": ("\uFE89", "\uFE8A", "\uFE8B", "\uFE8C"),  # ئ
    "\u0627": ("\uFE8D", "\uFE8E", None, None),          # ا
    "\u0628": ("\uFE8F", "\uFE90", "\uFE91", "\uFE92"),  # ب
    "\u067E": ("\uFB56", "\uFB57", "\uFB58", "\uFB59"),  # پ (Persian Pe)
    "\u0629": ("\uFE93", "\uFE94", None, None),          # ة
    "\u062A": ("\uFE95", "\uFE96", "\uFE97", "\uFE98"),  # ت
    "\u062B": ("\uFE99", "\uFE9A", "\uFE9B", "\uFE9C"),  # ث
    "\u062C": ("\uFE9D", "\uFE9E", "\uFE9F", "\uFEA0"),  # ج
    "\u0686": ("\uFB7A", "\uFB7B", "\uFB7C", "\uFB7D"),  # چ (Persian Che)
    "\u062D": ("\uFEA1", "\uFEA2", "\uFEA3", "\uFEA4"),  # ح
    "\u062E": ("\uFEA5", "\uFEA6", "\uFEA7", "\uFEA8"),  # خ
    "\u062F": ("\uFEA9", "\uFEAA", None, None),          # د
    "\u0630": ("\uFEAB", "\uFEAC", None, None),          # ذ
    "\u0631": ("\uFEAD", "\uFEAE", None, None),          # ر
    "\u0632": ("\uFEAF", "\uFEB0", None, None),          # ز
    "\u0698": ("\uFB8A", "\uFB8B", None, None),          # ژ (Persian Zhe)
    "\u0633": ("\uFEB1", "\uFEB2", "\uFEB3", "\uFEB4"),  # س
    "\u0634": ("\uFEB5", "\uFEB6", "\uFEB7", "\uFEB8"),  # ش
    "\u0635": ("\uFEB9", "\uFEBA", "\uFEBB", "\uFEBC"),  # ص
    "\u0636": ("\uFEBD", "\uFEBE", "\uFEBF", "\uFEC0"),  # ض
    "\u0637": ("\uFEC1", "\uFEC2", "\uFEC3", "\uFEC4"),  # ط
    "\u0638": ("\uFEC5", "\uFEC6", "\uFEC7", "\uFEC8"),  # ظ
    "\u0639": ("\uFEC9", "\uFECA", "\uFECB", "\uFECC"),  # ع
    "\u063A": ("\uFECD", "\uFECE", "\uFECF", "\uFED0"),  # غ
    "\u0641": ("\uFED1", "\uFED2", "\uFED3", "\uFED4"),  # ف
    "\u0642": ("\uFED5", "\uFED6", "\uFED7", "\uFED8"),  # ق
    "\u0643": ("\uFED9", "\uFEDA", "\uFEDB", "\uFEDC"),  # ك
    "\u06A9": ("\uFB8E", "\uFB8F", "\uFB90", "\uFB91"),  # ک (Persian Keheh)
    "\u06AF": ("\uFB92", "\uFB93", "\uFB94", "\uFB95"),  # گ (Persian Gaf)
    "\u0644": ("\uFEDD", "\uFEDE", "\uFEDF", "\uFEE0"),  # ل
    "\u0645": ("\uFEE1", "\uFEE2", "\uFEE3", "\uFEE4"),  # م
    "\u0646": ("\uFEE5", "\uFEE6", "\uFEE7", "\uFEE8"),  # ن
    "\u0647": ("\uFEE9", "\uFEEA", "\uFEEB", "\uFEEC"),  # ه
    "\u06C0": ("\uFBA4", "\uFBA5", None, None),          # ۀ
    "\u0648": ("\uFEED", "\uFEEE", None, None),          # و
    "\u0649": ("\uFEEF", "\uFEF0", None, None),          # ى
    "\u064A": ("\uFEF1", "\uFEF2", "\uFEF3", "\uFEF4"),  # ي
    "\u06CC": ("\uFBFC", "\uFBFD", "\uFBFE", "\uFBFF"),  # ی (Persian Yeh)
}

_LAM_ALEF: Dict[str, Tuple[str, str]] = {
    "\u0622": ("\uFEF5", "\uFEF6"),  # لآ
    "\u0623": ("\uFEF7", "\uFEF8"),  # لأ
    "\u0625": ("\uFEF9", "\uFEFA"),  # لإ
    "\u0627": ("\uFEFB", "\uFEFC"),  # لا
}

_HARAKAT = set("\u064B\u064C\u064D\u064E\u064F\u0650\u0651\u0652\u0653\u0654\u0655\u0670")
_RTL_CHAR_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_MIRROR_PAIRS = str.maketrans("()[]{}<>«»", ")(][}{><»«")


def contains_rtl(text: str) -> bool:
    return bool(text and _RTL_CHAR_RE.search(text))


def _can_join_after(ch: str) -> bool:
    if ch == "\u0640":  # Tatweel
        return True
    f = _AR_FORMS.get(ch)
    return bool(f and f[2] is not None)


def _can_join_before(ch: str) -> bool:
    if ch == "\u0640":
        return True
    return ch in _AR_FORMS


def shape_arabic_word_chars(text: str) -> str:
    """Arapça / Farsça harfleri bağlamına göre bitişik glif formlarına (Presentation Forms) dönüştürür."""
    if not contains_rtl(text):
        return text

    chars = [c for c in text if c not in _HARAKAT]
    n = len(chars)
    out: list[str] = []
    i = 0
    while i < n:
        ch = chars[i]
        # Lam + Alef ligatürü
        if ch == "\u0644" and i + 1 < n and chars[i + 1] in _LAM_ALEF:
            prev_joins = i > 0 and _can_join_after(chars[i - 1])
            iso_lig, fin_lig = _LAM_ALEF[chars[i + 1]]
            out.append(fin_lig if prev_joins else iso_lig)
            i += 2
            continue

        forms = _AR_FORMS.get(ch)
        if forms is None:
            out.append(ch)
            i += 1
            continue

        prev_j = i > 0 and _can_join_after(chars[i - 1])
        next_j = (forms[2] is not None) and (i + 1 < n) and _can_join_before(chars[i + 1])

        if prev_j and next_j and forms[3]:
            out.append(forms[3])
        elif prev_j:
            out.append(forms[1])
        elif next_j and forms[2]:
            out.append(forms[2])
        else:
            out.append(forms[0])
        i += 1

    return "".join(out)


_LTR_RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:@+\-%]*")

# X11 libXft (renkli emoji desteği olmayan klasik Tk) üzerinde '▯' kutusu olabilen U+1Fxxx kod noktalarını
# her Linux dağıtımında %100 net çizilen BMP vektör sembollerine dönüştürür.
_X11_SAFE_BMP_MAP = {
    "🚀": "➤",
    "📊": "◈",
    "🧩": "❖",
    "🌐": "✦",
    "🩺": "✚",
    "🌟": "★",
    "🗔": "↗",
    "👑": "★",
    "📋": "⧉",
    "🔗": "↗",
    "💳": "◈",
}


def sanitize_tk_symbols(text: str) -> str:
    if not text:
        return text
    for k, v in _X11_SAFE_BMP_MAP.items():
        if k in text:
            text = text.replace(k, v)
    return text


def shape_rtl_for_tk(text: str) -> str:
    """
    X11/Tkinter'ın soldan-sağa metin çizicisi için Arapça/Farsça satırları hem
    harf birleştirmeli (contextual shaping) hem de görsel BiDi sırasında hazırlar.
    """
    if not text or not contains_rtl(text):
        return text

    out_lines: list[str] = []
    for line in text.split("\n"):
        if not contains_rtl(line):
            out_lines.append(line)
            continue
        shaped = shape_arabic_word_chars(line)
        # Parantezleri aynala ve tüm satırı ters çevir, ardından içindeki LTR/sayı dizilerini düzelt
        mirrored = shaped.translate(_MIRROR_PAIRS)[::-1]
        fixed = _LTR_RUN_RE.sub(lambda m: m.group(0)[::-1], mirrored)
        out_lines.append(fixed)
    return "\n".join(out_lines)
