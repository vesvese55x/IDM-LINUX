from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


def get_assets_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


@dataclass(frozen=True)
class ProjectEntry:
    slug: str
    category: str          # "web_media" | "google_play" | "desktop" | "upcoming"
    title: str
    subtitle: str
    status_badge: str
    badge_color: str
    platforms: str
    release_info: str
    stats_info: str
    icon_file: str
    banner_file: Optional[str]
    primary_url: str
    primary_btn_label: str
    secondary_url: Optional[str] = None
    secondary_btn_label: Optional[str] = None
    qr_url: str = ""
    description: str = ""
    highlights: List[str] = field(default_factory=list)


GOOGLE_PLAY_DEV_URL = "https://play.google.com/store/apps/dev?id=6389590761419224762"
BELGESELSEMO_WEB_URL = "https://belgeselsemo.com.tr"
BELGESELSEMO_PREMIUM_URL = "https://belgeselsemo.com.tr/premium-uyelik/"
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@belgeselsemo55"
NOWPAYMENTS_DONATION_URL = "https://nowpayments.io/donation/belgeselsemo55"
NOWPAYMENTS_POS_URL = "https://nowpayments.io/pos-terminal/belgeselsemo55"
NOWPAYMENTS_WIDGET_API_KEY = "9e3c60ca-46a0-46c5-930b-bc7100a831dd"
NOWPAYMENTS_WIDGET_URL = (
    f"https://nowpayments.io/embeds/donation-widget?api_key={NOWPAYMENTS_WIDGET_API_KEY}"
)
NOWPAYMENTS_IFRAME_SNIPPET = (
    '<iframe src="https://nowpayments.io/embeds/donation-widget?api_key='
    '9e3c60ca-46a0-46c5-930b-bc7100a831dd" width="346" height="623" '
    'frameborder="0" scrolling="no" style="overflow-y: hidden;">'
    "Can't load widget</iframe>"
)


PROJECTS_CATALOG: List[ProjectEntry] = [
    # ─── WEB, AKADEMİK & YOUTUBE EKOSİSTEMİ ───────────────────────────────
    ProjectEntry(
        slug="belgeselsemo-web",
        category="web_media",
        title="BELGESELSEMO — Türkçe HD Belgesel & Araçlar Portalı",
        subtitle="Tek & Seri Belgesel Arşivi • Bilim, Tarih, Uzay, Doğa & Ücretsiz Web Araçları",
        status_badge="AKTİF WEB PORTALI",
        badge_color="#0ea5e9",
        platforms="Web (Tüm Cihazlar)",
        release_info="Kuruluş: 20 Ekim 2020 • Kesintisiz Güncel",
        stats_info="1.000+ HD Belgesel • Kar Amacı Gütmeyen Kültür Platformu",
        icon_file="app_belgeselsemo.png",
        banner_file=None,
        primary_url="https://belgeselsemo.com.tr",
        primary_btn_label="🌐 belgeselsemo.com.tr'yi Aç",
        qr_url="https://belgeselsemo.com.tr",
        description=(
            "20 Ekim 2020'de kurulan BELGESELSEMO; bilim, uzay, tarih, doğa, vahşi yaşam, teknoloji ve "
            "biyografi kategorilerinde yaklaşık 1.000 adet tek parça ve çok bölümlü Türkçe HD belgeseli "
            "kar amacı gütmeden bir araya getiren bağımsız bilgi ve kültür platformudur."
        ),
        highlights=[
            "Tek ve seri belgesellerde zengin kategori arşivi, hızlı arama ve yüksek çözünürlüklü izleme",
            "Gömülü çevrimiçi araçlar (EPG TV Rehberi, Ekonomi, Sözlük/Wiki, Çeviri ve pratik hesaplayıcılar)",
            "Reklam karmaşasından uzak, tamamen bilgi paylaşımı odaklı bağımsız yayın anlayışı",
        ],
    ),
    ProjectEntry(
        slug="youtube-learn-explore",
        category="web_media",
        title="BELGESELSEMO Learn & Explore (YouTube)",
        subtitle="Belgesel • Sesli Kitap • Eğitim Dersleri • Bilim & Tarih Keşifleri",
        status_badge="RESMİ YOUTUBE KANALI",
        badge_color="#ef4444",
        platforms="YouTube (@belgeselsemo55)",
        release_info="Aktif Video & Sesli Kitap Serileri",
        stats_info="Ücretsiz Eğitim, Belgesel & Sesli Kitap Arşivi",
        icon_file="proj_youtube.png",
        banner_file=None,
        primary_url="https://www.youtube.com/@belgeselsemo55",
        primary_btn_label="▶️ YouTube Kanalına Git & Abone Ol",
        qr_url="https://www.youtube.com/@belgeselsemo55",
        description=(
            "BELGESELSEMO'nun resmi YouTube kanalı! Belgeseller, sesli kitaplar, akademik ve genel kültür "
            "eğitim içerikleri ile tarihten uzaya uzanan merak uyandırıcı keşif serilerini tek çatı altında sunar."
        ),
        highlights=[
            "Özenle hazırlanmış Türkçe belgesel seçkileri, sesli kitaplar ve anlatımlı ders serileri",
            "Abone olup bildirimleri açarak tüm projelere ücretsiz ve doğrudan destek olabilirsiniz",
        ],
    ),
    ProjectEntry(
        slug="matpay",
        category="web_media",
        title="MATPAY — Matematik Paylaşımları (Lisans Ders Notları)",
        subtitle="Üniversite / Lisans Düzeyi Matematik Ders Notları, İspatlar ve Akademik Kaynaklar",
        status_badge="AKADEMİK ARŞİV",
        badge_color="#6366f1",
        platforms="Web Blog (matpay.blogspot.com)",
        release_info="Akademik Lisans Arşivi",
        stats_info="Ücretsiz Matematik Ders Notları & Teorem İspatları",
        icon_file="proj_matpay.png",
        banner_file=None,
        primary_url="http://matpay.blogspot.com",
        primary_btn_label="📐 MATPAY Ders Notlarını Aç",
        qr_url="http://matpay.blogspot.com",
        description=(
            "Matematik bölümü ve mühendislik öğrencileri için hazırlanmış lisans düzeyi matematik ders notları, "
            "teorem ispatları, çözümlü örnekler ve akademik kaynak paylaşımlarını barındıran eğitim arşivi."
        ),
        highlights=[
            "Analiz, Cebir, Diferansiyel Denklemler, Topoloji ve ileri lisans derslerine yönelik derli toplu notlar",
            "Öğrenciler ve araştırmacılar için tamamen açık erişimli akademik kaynak paylaşımı",
        ],
    ),

    # ─── MASAÜSTÜ UYGULAMALARI (LINUX / WINDOWS / MACOS) ──────────────────
    ProjectEntry(
        slug="belgeselsemoflix",
        category="desktop",
        title="BELGESELSEMOFLIX — Masaüstü Medya & Araç Üssü",
        subtitle="Tauri 2 Tabanlı Çapraz Platform Belgesel, Canlı TV Kapısı & Entegre Araçlar",
        status_badge="LINUX • WINDOWS • MACOS",
        badge_color="#10b981",
        platforms="Linux (.deb / .rpm / .pkg.tar.zst / .AppImage) • Windows (Setup & Win7+ Portable) • macOS (.dmg)",
        release_info="Sürüm: v1.0.0 • Açık Kaynak (GitHub)",
        stats_info="Tüm Masaüstü Dağıtımları İçin Yerel Paket Desteği",
        icon_file="proj_belgeselsemoflix.png",
        banner_file=None,
        primary_url="https://github.com/vesvese55x/belgeselsemoflix",
        primary_btn_label="💻 GitHub Sayfası & İndir",
        secondary_url="https://rawgit.loltek.net/https://raw.githubusercontent.com/vesvese55x/belgeselsemoflix/refs/heads/main/promo/promo.html",
        secondary_btn_label="✨ Canlı Tanıtım",
        qr_url="https://github.com/vesvese55x/belgeselsemoflix",
        description=(
            "BELGESELSEMO'nun tüm içeriğini modern, hafif ve ultra hızlı Tauri 2 masaüstü deneyimine taşıyan "
            "resmi uygulama! Arch/CachyOS (.pkg.tar.zst), Debian/Ubuntu (.deb), Fedora (.rpm), AppImage, "
            "Windows 7/10/11 ve macOS paketleriyle tek tıkla çalışır."
        ),
        highlights=[
            "Tek ve seri HD belgeseller, kategoriler, YouTube koleksiyonları ve Premium indirme merkezi",
            "DsmartGo & Ekstra TV hızlı erişim kapıları + dahili EPG TV Rehberi",
            "Entegre Çeviri, PDF Görüntüleyici, Wiki, Müzik Çalar ve Ekonomi takip modülleri",
        ],
    ),

    # ─── GOOGLE PLAY RESMİ ANDROID UYGULAMALARI (5 UYGULAMA) ──────────────
    ProjectEntry(
        slug="gp-epgviewer",
        category="google_play",
        title="BELGESELSEMO TV REHBERİ / TV GUIDE (EPG)",
        subtitle="com.belgeselsemo.epgviewer • Android Telefon, Tablet & Android TV Kumanda Uyumlu",
        status_badge="GOOGLE PLAY • 1.000+ İNDİRME",
        badge_color="#22c55e",
        platforms="Android & Android TV",
        release_info="Son Güncelleme: 14 Aralık 2025 • Sürüm 2.3",
        stats_info="1.000+ (1,7B+) İndirme • Küresel EPG Motoru",
        icon_file="app_epg.png",
        banner_file=None,
        primary_url="https://play.google.com/store/apps/details?id=com.belgeselsemo.epgviewer",
        primary_btn_label="📱 Google Play'de Görüntüle",
        secondary_url=GOOGLE_PLAY_DEV_URL,
        secondary_btn_label="🏪 Geliştirici Sayfası",
        qr_url="https://play.google.com/store/apps/details?id=com.belgeselsemo.epgviewer",
        description=(
            "Dünya genelinde 250'den fazla hazır EPG kaynağını ve kendi özel XMLTV / .xml.gz listelerinizi "
            "modern cam (glassmorphism) arayüzle sunan gelişmiş Elektronik Program Rehberi."
        ),
        highlights=[
            "250+ küresel EPG kaynağı, 25+ dil, 15+ görsel tema ve tam Android TV kumanda (D-Pad) desteği",
            "3 kademeli favori sistemi, akıllı program hatırlatıcıları, Sezon/Bölüm ve CANLI (LIVE) etiketleri",
        ],
    ),
    ProjectEntry(
        slug="gp-belgeselsemo",
        category="google_play",
        title="BELGESELSEMO — HD Belgesel & 20+ Günlük Araç",
        subtitle="com.belgeselsemo.tr • 1.000 Belgesel + 20'den Fazla Ücretsiz Pratik Araç Tek Uygulamada",
        status_badge="GOOGLE PLAY • 500+ İNDİRME • 5.0 ★",
        badge_color="#22c55e",
        platforms="Android",
        release_info="Yayın: 24 Tem 2025 • Güncelleme: 17 Kasım 2025",
        stats_info="500+ İndirme • 5,0 ★ Tam Puan",
        icon_file="app_belgeselsemo.png",
        banner_file=None,
        primary_url="https://play.google.com/store/apps/details?id=com.belgeselsemo.tr",
        primary_btn_label="📱 Google Play'de Görüntüle",
        qr_url="https://play.google.com/store/apps/details?id=com.belgeselsemo.tr",
        description=(
            "Yaklaşık 1.000 Türkçe HD belgesel arşivini ve günlük hayatta ihtiyaç duyulan 20'den fazla "
            "ücretsiz aracı (13 dil desteğiyle) tek bir süper uygulamada birleştirir."
        ),
        highlights=[
            "Dahili Araçlar: Hesap Makinesi, Pusula, Hava Durumu, Karekod, Nöbetçi Eczane, Çeviri, PDF/Müzik/Çizim",
            "Eğitim Modülleri: Güneş Sistemi, Periyodik Tablo, Ülkeler Rehberi, Ekonomi, TV Rehberi ve Wiki",
        ],
    ),
    ProjectEntry(
        slug="gp-nb724",
        category="google_play",
        title="NÖBETÇİ ECZANELER 7/24 TR-KKTC",
        subtitle="com.belgeselsemo.nb724 • Türkiye (81 İl) & KKTC Anlık Nöbetçi Eczane ve GPS Yol Tarifi",
        status_badge="GOOGLE PLAY • SAĞLIK",
        badge_color="#ef4444",
        platforms="Android",
        release_info="Son Güncelleme: 28 Aralık 2025",
        stats_info="100+ İndirme • 81 İl + KKTC 7/24 Canlı Veri",
        icon_file="app_nb724.png",
        banner_file=None,
        primary_url="https://play.google.com/store/apps/details?id=com.belgeselsemo.nb724",
        primary_btn_label="📱 Google Play'de Görüntüle",
        qr_url="https://play.google.com/store/apps/details?id=com.belgeselsemo.nb724",
        description=(
            "Türkiye'nin 81 ilindeki tüm ilçeler ve Kuzey Kıbrıs Türk Cumhuriyeti (KKTC) için 7/24 güncel "
            "nöbetçi eczaneleri en yakın konum sırasıyla listeleyen hayat kurtarıcı sağlık uygulaması."
        ),
        highlights=[
            "GPS ile size en yakın nöbetçi eczaneyi anında bulma, interaktif harita, tek dokunuşla arama ve yol tarifi",
            "15+ modern tema ve 7 dil desteğiyle gece/acil durumlarda göz yormayan hızlı arayüz",
        ],
    ),
    ProjectEntry(
        slug="gp-nutuk",
        category="google_play",
        title="NUTUK 1919-1927 (Sesli Kitap, Sözlük & Bilgi Yarışması)",
        subtitle="com.belgeselsemo.nutuk • Gazi Mustafa Kemal Atatürk'ün Ölümsüz Eseri 20+ Dilde",
        status_badge="GOOGLE PLAY • TARİH & KÜLTÜR",
        badge_color="#f59e0b",
        platforms="Android",
        release_info="Son Güncelleme: 21 Aralık 2025",
        stats_info="100+ İndirme • 20+ Dil & Çevrimdışı Okuma",
        icon_file="app_nutuk.png",
        banner_file=None,
        primary_url="https://play.google.com/store/apps/details?id=com.belgeselsemo.nutuk",
        primary_btn_label="📱 Google Play'de Görüntüle",
        qr_url="https://play.google.com/store/apps/details?id=com.belgeselsemo.nutuk",
        description=(
            "Cumhuriyetimizin kurucusu Gazi Mustafa Kemal Atatürk'ün 1919-1927 yıllarını anlattığı "
            "Nutuk eserini 20'den fazla dilde okuma, sesli dinleme ve etkileşimli öğrenme deneyimiyle sunar."
        ),
        highlights=[
            "Hız ve ton ayarlı Sesli Kitap (TTS) modu, entegre dönem sözlüğü ve 15+ özel okuma teması",
            "Etkileşimli Nutuk bilgi yarışması (Quiz), liderlik tablosu ve tamamen çevrimdışı erişim",
        ],
    ),
    ProjectEntry(
        slug="gp-trivia",
        category="google_play",
        title="BELGESELSEMO TRIVIA — Online Bilgi Yarışması",
        subtitle="com.belgeselsemo.trivia • 24 Kategori, 18+ Dil ve Gerçek Zamanlı Çok Oyunculu Düello",
        status_badge="GOOGLE PLAY • EĞİTİCİ OYUN",
        badge_color="#a855f7",
        platforms="Android",
        release_info="Yayın: 24 Ağu 2025 • Güncelleme: 17 Kasım 2025",
        stats_info="50+ İndirme • Sürüm 1.1 • Online Düello",
        icon_file="app_trivia.png",
        banner_file=None,
        primary_url="https://play.google.com/store/apps/details?id=com.belgeselsemo.trivia",
        primary_btn_label="📱 Google Play'de Görüntüle",
        qr_url="https://play.google.com/store/apps/details?id=com.belgeselsemo.trivia",
        description=(
            "Bilimden tarihe, coğrafyadan sanata 24 farklı kategoride binlerce soru içeren, hem tek başınıza "
            "hem de gerçek zamanlı online rakiplere karşı yarışabileceğiniz modern bilgi yarışması."
        ),
        highlights=[
            "4 klasik joker (50:50, Seyirci, Telefon, Soru Değiştir), XP/Seviye gelişimi ve günlük görevler",
            "18+ dil desteği, gerçek zamanlı online düello odaları ve yerel çoklu profil desteği",
        ],
    ),

    # ─── YAKINDA YAYINLANACAK YENİ NESİL PROJELER ─────────────────────────
    ProjectEntry(
        slug="upcoming-retro-emulator",
        category="upcoming",
        title="BELGESELSEMO RETRO EMULATOR",
        subtitle="MOPHUN (.mpn) • J2ME (.jar) • NES • SNES • GAMEBOY — Hepsi Tek Uygulamada!",
        status_badge="🚀 YAKINDA • ÇAPRAZ PLATFORM",
        badge_color="#38bdf8",
        platforms="Linux • Windows • macOS • Android",
        release_info="Durum: Aktif Geliştirme Aşamasında (Çok Yakında!)",
        stats_info="5 Klasik Konsol & Mobil Mimari Tek Çatıda",
        icon_file="proj_retro_icon.png",
        banner_file="proj_retro_banner.png",
        primary_url="https://belgeselsemo.com.tr",
        primary_btn_label="🌐 Duyurular: belgeselsemo.com.tr",
        secondary_url=GOOGLE_PLAY_DEV_URL,
        secondary_btn_label="🏪 Google Play Geliştirici Sayfası",
        qr_url="https://belgeselsemo.com.tr",
        description=(
            "Geçmişin efsanevi oyunlarını modern cihazlara taşıyan hepsi-bir-arada nostalji üssü! "
            "Nadir bulunan MOPHUN (.mpn) oyunlarından klasik tuşlu telefonların J2ME (.jar) arşivine, "
            "NES, SNES ve GameBoy klasiklerine kadar tüm sistemleri hem masaüstünde hem Android'de birleştirir."
        ),
        highlights=[
            "MOPHUN (.mpn), J2ME (.jar), NES, SNES ve GameBoy oyun motorları tek bir akıcı arayüzde",
            "Linux, Windows, macOS masaüstü sürümleri ve dokunmatik sanal tuş takımlı Android sürümü",
            "HD geniş ekran ölçekleme, hızlı kayıt (Save State), gamepad/klavye atama ve yüksek performans",
        ],
    ),
    ProjectEntry(
        slug="upcoming-economy",
        category="upcoming",
        title="BELGESELSEMO ECONOMY",
        subtitle="Canlı Döviz • Kripto Para • Değerli Madenler • Emtia • Hesaplama & Ekonomi Haberleri",
        status_badge="🚀 YAKINDA • ANDROID",
        badge_color="#10b981",
        platforms="Android (Google Play'de Çok Yakında)",
        release_info="Durum: Aktif Geliştirme Aşamasında (Çok Yakında!)",
        stats_info="Küresel & Yerel Piyasalar + Finansal Hesaplayıcılar",
        icon_file="proj_economy.png",
        banner_file=None,
        primary_url=GOOGLE_PLAY_DEV_URL,
        primary_btn_label="🏪 Google Play Geliştirici Sayfası",
        secondary_url="https://belgeselsemo.com.tr",
        secondary_btn_label="🌐 belgeselsemo.com.tr",
        qr_url=GOOGLE_PLAY_DEV_URL,
        description=(
            "Finansal piyasaları tek ekrandan anlık takip etmeniz için tasarlanan kapsamlı ekonomi asistanı! "
            "Döviz kurları, kripto paralar, altın/gümüş başta olmak üzere değerli madenler ve küresel emtia "
            "verilerini gelişmiş hesaplama araçları ve ekonomi haberleriyle bir araya getirir."
        ),
        highlights=[
            "Canlı Döviz, Kripto Para, Altın/Gümüş/Değerli Madenler ve Enerji/Tarım Emtia takibi",
            "Pratik kur/portföy/kar-zarar hesaplama araçları ile yerel ve küresel ekonomi-ticaret haber akışı",
        ],
    ),
]
