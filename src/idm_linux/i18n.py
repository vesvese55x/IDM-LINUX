from __future__ import annotations

import locale
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class LanguageSpec:
    code: str
    native_name: str
    english_name: str
    badge: str
    idm_lang_id: int
    idm_lng_file: str
    idm_native_supported: bool
    rtl: bool = False

    @property
    def idm_supported_natively(self) -> bool:
        return self.idm_native_supported


# 20 Tam Destekli Dil ve Gerçek IDM 6.43 Build 16 (.lng + LanguageID) Eşleşme Tablosu
LANGUAGE_LIST: List[LanguageSpec] = [
    LanguageSpec("tr", "Türkçe", "Turkish", "TR", 0x1F, "idm_tr.lng", True, False),
    LanguageSpec("en", "English", "English", "EN", 0x09, "", True, False),
    LanguageSpec("de", "Deutsch", "German", "DE", 0x07, "idm_de.lng", True, False),
    LanguageSpec("fr", "Français", "French", "FR", 0x0C, "idm_fr.lng", True, False),
    LanguageSpec("ru", "Русский", "Russian", "RU", 0x19, "idm_ru.lng", True, False),
    LanguageSpec("zh", "简体中文", "Chinese", "ZH", 0x804, "idm_chn2.lng", True, False),
    LanguageSpec("ja", "日本語", "Japanese", "JA", 0x11, "idm_jp.lng", True, False),
    LanguageSpec("hi", "हिन्दी", "Hindi", "HI", 0x39, "idm_hi.lng", True, False),
    LanguageSpec("ar", "العربية", "Arabic", "AR", 0x01, "idm_ar.lng", True, True),
    LanguageSpec("nl", "Nederlands", "Dutch", "NL", 0x13, "idm_nl.lng", True, False),
    LanguageSpec("fa", "فارسی", "Persian", "FA", 0x29, "idm_fa.lng", True, True),
    LanguageSpec("el", "Ελληνικά", "Greek", "EL", 0x08, "idm_gr.lng", True, False),
    LanguageSpec("pt", "Português", "Portuguese", "PT", 0x816, "idm_pt.lng", True, False),
    LanguageSpec("vi", "Tiếng Việt", "Vietnamese", "VI", 0x2A, "idm_vn.lng", True, False),
    LanguageSpec("az", "Azərbaycanca", "Azerbaijani", "AZ", 0x09, "", False, False),
    LanguageSpec("ky", "Кыргызча", "Kyrgyz", "KY", 0x09, "", False, False),
    LanguageSpec("it", "Italiano", "Italian", "IT", 0x10, "idm_it.lng", True, False),
    LanguageSpec("id", "Bahasa Indonesia", "Indonesian", "ID", 0x21, "idm_id.lng", True, False),
    LanguageSpec("ka", "ქართული", "Georgian", "KA", 0x37, "idm_ge.lng", True, False),
    LanguageSpec("ro", "Română", "Romanian", "RO", 0x18, "idm_ro.lng", True, False),
]

SUPPORTED_LANGUAGES: Dict[str, LanguageSpec] = {sp.code: sp for sp in LANGUAGE_LIST}
LANGUAGE_MAP: Dict[str, LanguageSpec] = SUPPORTED_LANGUAGES

# Bazı sistemlerde locale ön ekleri farklı gelebilir (ör: gr -> el, jp -> ja, cn -> zh, ge -> ka, vn -> vi, in -> id)
_LOCALE_ALIASES: Dict[str, str] = {
    "tr": "tr", "tur": "tr",
    "en": "en", "eng": "en", "c": "en", "posix": "en",
    "de": "de", "ger": "de", "deu": "de",
    "fr": "fr", "fre": "fr", "fra": "fr",
    "ru": "ru", "rus": "ru",
    "zh": "zh", "cn": "zh", "zho": "zh", "chi": "zh",
    "ja": "ja", "jp": "ja", "jpn": "ja",
    "hi": "hi", "hin": "hi",
    "ar": "ar", "ara": "ar",
    "nl": "nl", "dut": "nl", "nld": "nl",
    "fa": "fa", "per": "fa", "fas": "fa", "ir": "fa",
    "el": "el", "gr": "el", "gre": "el", "ell": "el",
    "pt": "pt", "por": "pt",
    "vi": "vi", "vn": "vi", "vie": "vi",
    "az": "az", "aze": "az",
    "ky": "ky", "kg": "ky", "kir": "ky",
    "it": "it", "ita": "it",
    "id": "id", "in": "id", "ind": "id",
    "ka": "ka", "ge": "ka", "kat": "ka", "geo": "ka",
    "ro": "ro", "ron": "ro", "rum": "ro",
}


def normalize_lang_code(raw: str) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip().split(".")[0].split("@")[0]
    if ":" in cleaned:
        cleaned = cleaned.split(":")[0]
    primary = re.split(r"[-_]", cleaned)[0].lower()
    if primary in SUPPORTED_LANGUAGES:
        return primary
    return _LOCALE_ALIASES.get(primary)


def detect_system_language(default_fallback: str = "en") -> str:
    """
    İşletim sisteminin aktif dilini (IDM_LINUX_LANG, LC_ALL, LC_MESSAGES, LANGUAGE, LANG)
    otomatik olarak algılar. 20 destekli dilden biriyse onu, değilse 'en' döndürür.
    """
    has_explicit_non_match = False
    for env_key in ("IDM_LINUX_LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        val = os.environ.get(env_key, "").strip()
        if not val:
            continue
        for item in val.split(":"):
            s = item.strip()
            if not s or s.lower() in ("c", "c.utf-8", "posix"):
                continue
            matched = normalize_lang_code(s)
            if matched and matched in SUPPORTED_LANGUAGES:
                return matched
            has_explicit_non_match = True
        if has_explicit_non_match:
            return default_fallback

    try:
        loc_pair = locale.getlocale()
        if loc_pair and loc_pair[0] and loc_pair[0].lower() not in ("c", "c.utf-8", "posix"):
            matched = normalize_lang_code(loc_pair[0])
            if matched and matched in SUPPORTED_LANGUAGES:
                return matched
    except Exception:
        pass

    return default_fallback


def get_language_spec(lang_code: str) -> LanguageSpec:
    norm = normalize_lang_code(lang_code) or "en"
    return SUPPORTED_LANGUAGES.get(norm, SUPPORTED_LANGUAGES["en"])


def get_idm_registry_language_pair(lang_code: str) -> Tuple[int, str]:
    """
    Verilen dil kodu için Wine IDM Kayıt Defteri (LanguageID, fulllngfile)
    ikilisini döndürür. IDM'nin desteklemediği bir dilse otomatik İngilizce (0x09, "") döner!
    """
    spec = get_language_spec(lang_code)
    if spec.idm_native_supported:
        return (spec.idm_lang_id, spec.idm_lng_file)
    return (0x09, "")


def find_all_language_dirs() -> List[Path]:
    """v2.9.6: tüm aday dil klasörleri (eksik anahtarlar birleştirilir — ham key asla görünmez)."""
    here = Path(__file__).resolve().parent
    candidates = [
        here.parents[1] / "language",
        here / "language",
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        / "idm-linux"
        / "app"
        / "language",
    ]
    seen = []
    for c in candidates:
        if c.is_dir() and (c / "tr.txt").is_file() and c.resolve() not in [x.resolve() for x in seen]:
            seen.append(c)
    return seen or [candidates[0]]


def find_language_dir() -> Path:
    """language/*.txt dil dosyalarının bulunduğu klasörü bulur."""
    here = Path(__file__).resolve().parent
    candidates = [
        here.parents[1] / "language",           # repo kökü: idm-linux/language/
        here / "language",                      # paket içi: src/idm_linux/language/
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        / "idm-linux"
        / "app"
        / "language",
    ]
    for c in candidates:
        if c.is_dir() and (c / "tr.txt").is_file():
            return c
    return candidates[0]


def parse_lang_txt_file(txt_path: Path) -> Dict[str, str]:
    """
    UTF-8 kodlamalı language/<kod>.txt dosyasını okur.
    """
    entries: Dict[str, str] = {}
    if not txt_path.is_file():
        return entries
    content = txt_path.read_text(encoding="utf-8-sig", errors="replace")
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        k = key.strip()
        v = val.strip().replace("\\n", "\n")
        if k:
            entries[k] = v
    return entries


class I18nManager:
    """
    language/<kod>.txt dosyalarından 20 dilde dinamik çeviri sağlayan ve canlı dil
    değişiminde kayıtlı dinleyicileri tetikleyen yerelleştirme yöneticisi.
    """

    def __init__(self, initial_lang: Optional[str] = None) -> None:
        self._cache: Dict[str, Dict[str, str]] = {}
        self._listeners: List[Callable[[str], None]] = []
        chosen = normalize_lang_code(initial_lang or "") or detect_system_language()
        self._current_lang: str = chosen

    @property
    def lang(self) -> str:
        return self._current_lang

    @property
    def spec(self) -> LanguageSpec:
        return get_language_spec(self._current_lang)

    def _get_table(self, code: str) -> Dict[str, str]:
        if code not in self._cache:
            table: Dict[str, str] = {}
            # v2.9.6: TÜM kopyaları birleştir (eski kurulum kalıntısı ham key gösteremez)
            for ldir in find_all_language_dirs():
                for k, v in parse_lang_txt_file(ldir / f"{code}.txt").items():
                    table.setdefault(k, v)
            self._cache[code] = table
        return self._cache[code]

    def set_language(self, lang_code: str) -> str:
        norm = normalize_lang_code(lang_code) or "en"
        if norm not in SUPPORTED_LANGUAGES:
            norm = "en"
        changed = norm != self._current_lang
        self._current_lang = norm
        if changed:
            for cb in list(self._listeners):
                try:
                    cb(norm)
                except Exception:
                    pass
        return self._current_lang

    def on_change(self, callback: Callable[[str], None]) -> None:
        self._listeners.append(callback)

    def t(self, key: str, **kwargs: Any) -> str:
        tbl = self._get_table(self._current_lang)
        raw = tbl.get(key)
        if raw is None and self._current_lang != "en":
            raw = self._get_table("en").get(key)
        if raw is None and self._current_lang != "tr":
            raw = self._get_table("tr").get(key)
        if raw is None:
            raw = key
        if kwargs:
            try:
                return raw.format(**kwargs)
            except Exception:
                # v3.10.0: eksik yer tutucu yüzünden metin ham kalmasın — bilinmeyen
                # anahtarlar boş yazılır ({zai} gibi sonradan eklenenler için).
                try:
                    class _Missing(dict):
                        def __missing__(self, key: str) -> str:
                            return ""

                    return raw.format_map(_Missing(kwargs))
                except Exception:
                    return raw
        return raw


_GLOBAL_I18N: Optional[I18nManager] = None


def get_i18n(lang_code: Optional[str] = None) -> I18nManager:
    global _GLOBAL_I18N
    if _GLOBAL_I18N is None:
        _GLOBAL_I18N = I18nManager(initial_lang=lang_code)
    elif lang_code:
        _GLOBAL_I18N.set_language(lang_code)
    return _GLOBAL_I18N
