<div align="center">

# 🚀 IDM LINUX (BELGESELSEMO)

[![Build & Release](https://github.com/vesvese55x/IDM-LINUX/actions/workflows/build.yml/badge.svg)](https://github.com/vesvese55x/IDM-LINUX/actions/workflows/build.yml)
[![Tests](https://github.com/vesvese55x/IDM-LINUX/actions/workflows/tests.yml/badge.svg)](https://github.com/vesvese55x/IDM-LINUX/actions/workflows/tests.yml)

![Version](https://img.shields.io/badge/s%C3%BCr%C3%BCm-1.0.0-0ea5e9?style=for-the-badge)
![Platform](https://img.shields.io/badge/platform-Linux%20x86__64-f97316?style=for-the-badge)
![Wine](https://img.shields.io/badge/back--end-Wine-red?style=for-the-badge)
![CI](https://img.shields.io/badge/CI-AppImage%20·%20deb%20·%20rpm%20·%20zst-22c55e?style=for-the-badge)

**Internet Download Manager'ın tüm gücü — Linux'ta, tam işlevsel, hafif ve kararlı.**

[🇹🇷 Türkçe](#turkce) · [🇬🇧 English](#english)

</div>

---

<a id="turkce"></a>
## 🇹🇷 Türkçe

**IDM LINUX**, Tonec Inc.'in efsanevi indirme yöneticisi **Internet Download Manager (IDM)**'i Linux'ta **tam işlevsel** şekilde kullanmanı sağlayan bağımsız bir entegrasyon katmanıdır. IDM'nin arayüzü, indirme motoru ve tüm yetenekleri Wine üzerinde aynen çalışmaya devam eder; IDM LINUX ise araya giren "tercüman" katman olarak:

- tarayıcından indirmeleri **otomatik yakalar**,
- **gofile.io** ve popüler video siteleri gibi senaryoları **kendi motor zinciriyle** çözer,
- **gömülü torrent motoru** ile magnet ve .torrent dosyalarını indirir,
- canlı yayın **DVR kaydı** yapar,
- ve tüm bunları **tek bir hafif arka plan servisi** üzerinden yürütür — masaüstünde kasma yok.

### ✨ Özellikler

| Özellik | Açıklama |
|---|---|
| 🌐 **Tarayıcı entegrasyonu** | Tarayıcı eklentisi, indirme taleplerini otomatik yakalar ve IDM'ye devreder; tıkla, gerisini IDM LINUX yapsın. |
| 📦 **gofile.io desteği** | gofile bağlantıları için konuk oturumu (guest token) ve doğrudan bağlantı çözümleme; dosyanın **bozuk inmesi engellenir**, indirme IDM üzerinden tamamlanır. |
| 🎬 **Video sitesi desteği** | yt-dlp / streamlink tabanlı motor zinciri; farklı siteler için en uygun motor otomatik seçilir, uygunsa doğrudan IDM'ye aktarılır. |
| 🧲 **Gömülü torrent motoru** | Magnet ve .torrent desteği, **DHT** ile tracker'sız peer keşfi, kararlı ve hızlı indirme; torrent tespit edilir edilmez IDM'ye devredilir. |
| 📺 **Canlı yayın / DVR kaydı** | Canlı akışlardan kayıt alabilen DVR katmanı, arayüzden yönetilir. |
| 🔑 **Deneme süresi sıfırlama** | IDM deneme süresi yönetimini arayüz üzerinden kolaylaştırır. |
| 🩺 **Sistem Doktoru** | Arayüzün içinde, motorların ve köprülerin çalışma anı kayıtlarını (log) gösteren teşhis paneli; sorun self-servis çözülür. |
| ✋ **"İptal = tam dur"** | Herhangi bir indirmeyi iptal ettiğinde, arka planda motorların hiçbiri devam etmez; kaynağı gereksiz yemez, dosya yarım bırakılmaz. |
| ⚡ **Hafif mimari** | Tüm iletişim `127.0.0.1` üzerindeki **yerel HTTP ağ geçidi** üzerinden yapılır (`127.0.0.1:17802`); arka planda sürekli CPU/RVM yükü yoktur. |
| 🖥️ **Masaüstü entegrasyonu** | Masaüstü girdisi (.desktop), ikon ve `idm-linux` komutu ile terminalden de başlatma. |

### 📋 Gereksinimler

- Linux (x86_64 önerilir; aarch64 üzerinde Wine x86 uyumluluk katmanı gerekebilir)
- **Wine** (güncel sürüm önerilir) — IDM'nin Windows tarafı için
- **Python 3** (3.8+)
- Çalışan bir masaüstü ortamı (X11 veya Wayland) — GUI kullanımı için

### 📥 Kurulum

Tüm paketler **sürüm 1.0.0** için GitHub Releases (veya Actions Artifacts) üzerinden dağıtılır.

**1) AppImage (her dağıtımda çalışır)**

```bash
chmod +x IDM-LINUX-1.0.0-x86_64.AppImage
./IDM-LINUX-1.0.0-x86_64.AppImage
```

**2) DEB — Debian / Ubuntu / Linux Mint / MX Linux**

```bash
sudo apt install ./idm-linux_1.0.0_all.deb
```

**3) RPM — Fedora / openSUSE / RHEL türevleri**

```bash
# Fedora / RHEL
sudo dnf install ./idm-linux-1.0.0-1.noarch.rpm
# openSUSE
sudo zypper install ./idm-linux-1.0.0-1.noarch.rpm
```

**4) Arch Linux / Manjaro / EndeavourOS (zst)**

```bash
sudo pacman -U idm-linux-1.0.0-1-any.pkg.tar.zst
```

> Paketler uygulama dosyalarını `/opt/idm-linux` altına kurar; `idm-linux` komutunu, uygulama menüsü girdisini ve ikonu sisteme kaydeder. Çalıştırılmadan önce sistemde **wine** ve **python3** bulunmalıdır (paket yöneticisi bağımlılıkları otomatik çeker).

### 🚀 Hızlı Başlangıç

1. **IDM LINUX'u başlat** — uygulama menüsünden *IDM LINUX* veya terminalden `idm-linux`.
2. **Tarayıcı eklentisini kur** — depodaki eklenti klasörünü tarayıcına yükle (Chromium tabanlılar: *geliştirici modu + "paketlenmemiş öğe yükle"*; Firefox: `about:debugging` → *Geçici eklenti yükle*).
3. İndirmek istediğin bağlantıya tıkla — eklenti indirmeyi yakalar, IDM devralır.
4. **Torrent** için: magnet bağlantısını ya da `.torrent` dosyasını IDM LINUX'a ver; motor DHT ile peer'lere bağlanır ve indirme doğrudan IDM listesinde görünür.
5. Bir sorun mu var? **Sistem Doktoru** sayfasından motor günlüklerini (log) kontrol et — hangi motorun ne yaptığını canlı görürsün.

### 🧠 Mimari (kısaca)

```
Tarayıcı eklentisi ──► Yerel HTTP Ağ Geçidi (127.0.0.1:17802) ──► Wine/IDM (COM köprüsü + CLI yedeği)
                                   │
                                   ├─ Motor zinciri: yt-dlp → streamlink → doğrudan HTTP
                                   ├─ gofile çözümleyici (guest token + doğrudan bağlantı)
                                   ├─ Gömülü torrent motoru (DHT, magnet, .torrent)
                                   └─ Canlı yayın / DVR kayıt katmanı
```

- Tüm trafik **yalnızca localhost** üzerinde dolaşır; dışarıya ek bir servis açılmaz.
- Her indirme tipi kendi motorunda çözülür; hangi motorun devraldığı Sistem Doktoru'ndan izlenebilir.
- İptal edilen bir indirmede ilgili motor **anında durdurulur**; arka planda "hayalet indirme" oluşmaz.

### ❓ SSS

**IDM lisansım gerekiyor mu?**
Evet. IDM ticari bir yazılımdır (Tonec Inc.). Bu proje IDM'nin bir kopyasını dağıtmaz; sadece Linux entegrasyon katmanıdır. IDM'yi meşru lisansınla kullanmalısın.

**Torrent indirmeleri neden bazen yavaş başlıyor?**
Torrent hızı, tracker/peer durumuna bağlıdır. Motor DHT ile peer keşfi yapar; az peer'li (nadiren seed'lenen) torrentlerde başlangıç doğal olarak yavaş olabilir.

**gofile bağlantısı neden IDM'ye gitmiyor?**
gofile zaman zaman API/CDN tarafını değiştirir. Sistem Doktoru'ndaki gofile kayıtlarını kontrol et; sorun sürüyorsa güncel çözümleyici için depoda hata (issue) aç.

**Paketleri nasıl derlerim?**
Depodaki `.github/workflows/build.yml` her push'ta 4 formatı (AppImage, deb, rpm, zst) otomatik derler ve Actions Artifacts'a ekler. Ayrıntılar için [`RELEASING.md`](RELEASING.md).

### 🩺 Sorun Giderme

- **İndirme yakalanmıyor:** Tarayıcı eklentisinin kurulu/etkin olduğunu ve IDM LINUX'un çalıştığını doğrula.
- **Torrent başlamıyor:** Sistem Doktoru → torrent motoru günlüğü; DHT bağlantısı ve peer sayısını görüntüle.
- **Wine hatası:** `wine --version` ile sürümü doğrula; güncel Wine önerilir.
- **Detaylı log:** Sistem Doktoru tüm motor/çözümleyici etkinliklerini zaman damgalı gösterir; hata bildiriminde bu bölümü paylaş.

### 🛠️ CI & Sürüm Akışı

- Her `push`: 4 paket formatı derlenir → **Actions → Artifacts** (30 gün saklanır, release'e eklenmez).
- `v1.0.0` gibi bir **etiket (tag)** pushlanınca: 4 paket **taslak (draft) GitHub Release**'e otomatik eklenir; yayın kararı sonuna kadar sende kalır — draft'ı düzenleyip *Publish* edersin.

### 📜 Sürüm Geçmişi

**1.0.0** — İlk halka açık sürüm: tarayıcı entegrasyonu, gofile desteği, video sitesi motor zinciri, gömülü torrent motoru (DHT), canlı yayın/DVR kaydı, deneme süresi sıfırlama, Sistem Doktoru ve 4 formatlı paketleme (AppImage / deb / rpm / zst).

### ⚖️ Lisans ve Yasal Not

Bu projenin kodu ve paketleme dosyaları **BELGESELSEMO**'ya aittir. "Internet Download Manager" ve "IDM", **Tonec Inc.**'in tescilli ürün ve markalarıdır. Bu proje bağımsız bir topluluk entegrasyonudur; Tonec Inc. ile bağlantılı değildir ve onaylanmamıştır. IDM yazılımını kullanmak için Tonec Inc. ile geçerli bir lisansın bulunması gerekir. Ayrıntılar için [`LICENSE`](LICENSE) dosyasına bak.

---

<a id="english"></a>
## 🇬🇧 English

**IDM LINUX** is an independent integration layer that lets you use **Internet Download Manager (IDM)** — the legendary download manager by Tonec Inc. — **fully functional** on Linux. IDM's interface, download engine and all of its capabilities keep running through Wine, while IDM LINUX acts as the smart middleware that:

- **captures downloads automatically** from your browser,
- solves tricky sources like **gofile.io** and popular video sites with its own **engine chain**,
- downloads magnet links and .torrent files with a **built-in torrent engine**,
- records live streams (**DVR**),
- and runs everything through **one lightweight background service** — no desktop lag.

### ✨ Features

| Feature | Description |
|---|---|
| 🌐 **Browser integration** | The browser extension intercepts download requests and hands them to IDM — click once, IDM LINUX does the rest. |
| 📦 **gofile.io support** | Guest-token session and direct-link resolution for gofile; prevents **corrupted/incomplete files**, downloads through IDM. |
| 🎬 **Video site support** | yt-dlp / streamlink based engine chain; the best engine is picked automatically and handed over to IDM when possible. |
| 🧲 **Built-in torrent engine** | Magnet + .torrent support, peer discovery via **DHT**, stable and fast downloads; torrents are detected and transferred to IDM instantly. |
| 📺 **Live stream / DVR recording** | A DVR layer that records live streams, managed from the UI. |
| 🔑 **Trial reset** | Simplifies IDM trial period management from the UI. |
| 🩺 **System Doctor** | A built-in diagnostics panel showing live logs of engines and bridges; troubleshoot without leaving the app. |
| ✋ **"Cancel = full stop"** | Cancel any download and no engine keeps running in the background — no wasted bandwidth, no half-written files. |
| ⚡ **Lightweight architecture** | All communication flows through a **local HTTP gateway** on `127.0.0.1` (`127.0.0.1:17802`); no constant background CPU/RAM load. |
| 🖥️ **Desktop integration** | .desktop entry, icon and the `idm-linux` command for terminal launches. |

### 📋 Requirements

- Linux (x86_64 recommended; aarch64 may require a Wine x86 compatibility layer)
- **Wine** (recent version recommended) — for the Windows side of IDM
- **Python 3** (3.8+)
- A running desktop session (X11 or Wayland) for the GUI

### 📥 Installation

All packages are distributed for **version 1.0.0** via GitHub Releases (or Actions Artifacts).

**1) AppImage (works on any distro)**

```bash
chmod +x IDM-LINUX-1.0.0-x86_64.AppImage
./IDM-LINUX-1.0.0-x86_64.AppImage
```

**2) DEB — Debian / Ubuntu / Linux Mint / MX Linux**

```bash
sudo apt install ./idm-linux_1.0.0_all.deb
```

**3) RPM — Fedora / openSUSE / RHEL-based**

```bash
# Fedora / RHEL
sudo dnf install ./idm-linux-1.0.0-1.noarch.rpm
# openSUSE
sudo zypper install ./idm-linux-1.0.0-1.noarch.rpm
```

**4) Arch Linux / Manjaro / EndeavourOS (zst)**

```bash
sudo pacman -U idm-linux-1.0.0-1-any.pkg.tar.zst
```

> Packages install the app under `/opt/idm-linux`, register the `idm-linux` command, the menu entry and the icon. **wine** and **python3** must be present on the system (package managers pull the dependencies automatically).

### 🚀 Quick Start

1. **Launch IDM LINUX** — from your app menu or by running `idm-linux` in a terminal.
2. **Install the browser extension** — load the extension folder from this repo (Chromium-based: *developer mode + "Load unpacked"*; Firefox: `about:debugging` → *Load Temporary Add-on*).
3. Click a download link — the extension captures it and IDM takes over.
4. **Torrents:** hand a magnet link or a `.torrent` file to IDM LINUX; the engine discovers peers via DHT and the download shows up right inside IDM.
5. Something off? Open the **System Doctor** page and watch live engine logs.

### 🧠 Architecture (short version)

```
Browser extension ──► Local HTTP Gateway (127.0.0.1:17802) ──► Wine/IDM (COM bridge + CLI fallback)
                                │
                                ├─ Engine chain: yt-dlp → streamlink → direct HTTP
                                ├─ gofile resolver (guest token + direct links)
                                ├─ Built-in torrent engine (DHT, magnet, .torrent)
                                └─ Live stream / DVR recording layer
```

- All traffic stays on **localhost**; no external service is exposed.
- Each download type is resolved by its own engine; which engine took over is visible in the System Doctor.
- Cancelling a download **stops the engine immediately** — no ghost downloads in the background.

### ❓ FAQ

**Do I need an IDM license?**
Yes. IDM is commercial software (Tonec Inc.). This project does not distribute IDM; it is only the Linux integration layer. You must use IDM with a valid license.

**Why do some torrents start slowly?**
Torrent speed depends on tracker/peer availability. The engine discovers peers via DHT; rarely-seeded torrents naturally start slow.

**Why isn't a gofile link going to IDM?**
gofile changes its API/CDN from time to time. Check the gofile entries in the System Doctor; if the problem persists, open an issue for the updated resolver.

**How do I build the packages?**
The `.github/workflows/build.yml` in this repo builds all four formats (AppImage, deb, rpm, zst) on every push and uploads them to Actions Artifacts. See [`RELEASING.md`](RELEASING.md) for details.

### 🩺 Troubleshooting

- **Download not captured:** Make sure the browser extension is installed/enabled and IDM LINUX is running.
- **Torrent not starting:** System Doctor → torrent engine log; check DHT connectivity and peer count.
- **Wine errors:** Verify with `wine --version`; a recent Wine build is recommended.
- **Detailed logs:** The System Doctor shows timestamped activity of every engine/resolver; include it when reporting issues.

### 🛠️ CI & Release Flow

- Every `push`: all four package formats are built → **Actions → Artifacts** (retained 30 days, NOT attached to releases).
- Pushing a **tag** such as `v1.0.0`: all four packages are attached to a **draft GitHub Release** automatically; publishing stays under your control — review the draft and hit *Publish*.

### 📜 Changelog

**1.0.0** — First public release: browser integration, gofile support, video site engine chain, built-in torrent engine (DHT), live stream/DVR recording, trial reset, System Doctor, and packaging in four formats (AppImage / deb / rpm / zst).

### ⚖️ License & Legal Notice

The code and packaging files of this project belong to **BELGESELSEMO**. "Internet Download Manager" and "IDM" are products and trademarks of **Tonec Inc.** This is an independent community integration project, not affiliated with or endorsed by Tonec Inc. A valid IDM license from Tonec Inc. is required to use IDM. See the [`LICENSE`](LICENSE) file for details.

---

<div align="center">

Made with ❤️ by **BELGESELSEMO** · IDM LINUX 1.0.0

</div>
