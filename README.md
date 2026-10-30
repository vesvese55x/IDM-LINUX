<div align="center">

  <img src="assets/idm-linux-icon.png" width="128" alt="IDM LINUX uygulama simgesi" />

# 🚀 IDM LINUX (BELGESELSEMO)

**Internet Download Manager'ın tüm gücü — Linux'ta, tam işlevsel, hafif ve kararlı.**

[![Sürüm](https://img.shields.io/github/v/release/vesvese55x/IDM-LINUX?style=for-the-badge&label=s%C3%BCr%C3%BCm&color=0ea5e9)](https://github.com/vesvese55x/IDM-LINUX/releases/latest)
[![İndirmeler](https://img.shields.io/github/downloads/vesvese55x/IDM-LINUX/total?style=for-the-badge&label=indirmeler&color=f97316)](https://github.com/vesvese55x/IDM-LINUX/releases)
![Platform](https://img.shields.io/badge/platform-Linux%20x86__64-black?style=for-the-badge)
![Wine](https://img.shields.io/badge/back--end-Wine-red?style=for-the-badge)
![Python](https://img.shields.io/badge/python-3.8%2B-3776ab?style=for-the-badge)
![Paketler](https://img.shields.io/badge/paket-AppImage%20%C2%B7%20deb%20%C2%B7%20rpm%20%C2%B7%20zst-22c55e?style=for-the-badge)
![Testler](https://img.shields.io/badge/testler-149%2F149%20%E2%9C%94-22c55e?style=for-the-badge)

[🇹🇷 Türkçe](#turkce) · [🇬🇧 English](#english) · [🇷🇺 Русский](#русский) · [🇨🇳 中文](#中文)

</div>

---

<a id="turkce"></a>
## 🇹🇷 Türkçe

**IDM LINUX**, Tonec Inc.'in efsanevi indirme yöneticisi **Internet Download Manager (IDM)**'i Linux'ta **tam işlevsel** şekilde kullanmanı sağlayan bağımsız bir entegrasyon katmanıdır. IDM'nin arayüzü, indirme motoru ve tüm yetenekleri Wine üzerinde aynen çalışmaya devam eder; IDM LINUX ise araya giren "tercüman" katman olarak:

- tarayıcından indirmeleri **otomatik yakalar**,
- popüler **dosya barındırma siteleri** ve video siteleri gibi senaryoları **kendi motor zinciriyle** çözer,
- **gömülü torrent motoru** ile magnet ve .torrent dosyalarını indirir,
- canlı yayın **DVR kaydı** yapar,
- ve tüm bunları **tek bir hafif arka plan servisi** üzerinden yürütür — masaüstünde kasma yok.

### ✨ Özellikler

| Özellik | Açıklama |
|---|---|
| 🌐 **Tarayıcı entegrasyonu** | Tarayıcı eklentisi, indirme taleplerini otomatik yakalar ve IDM'ye devreder; tıkla, gerisini IDM LINUX yapsın. |
| 📦 **Dosya barındırma siteleri desteği** | Popüler dosya barındırma siteleri için konuk oturumu (guest token) ve doğrudan bağlantı çözümleme; dosyanın **bozuk inmesini engeller**, indirme IDM üzerinden tamamlanır. |
| 🎬 **Video sitesi desteği** | yt-dlp / streamlink tabanlı motor zinciri; farklı siteler için en uygun motor otomatik seçilir, uygunsa doğrudan IDM'ye aktarılır. |
| 🧲 **Gömülü torrent motoru** | Magnet ve .torrent desteği, **DHT** ile tracker'sız peer keşfi, kararlı ve hızlı indirme; torrent tespit edilir edilmez IDM'ye devredilir. |
| 📺 **Canlı yayın / DVR kaydı** | Canlı akışlardan kayıt alabilen DVR katmanı, arayüzden yönetilir. |
| 🔑 **Deneme süresi sıfırlama** | IDM deneme süresi yönetimini arayüz üzerinden kolaylaştırır. |
| 🩺 **Sistem Doktoru** | Arayüzün içinde, motorların ve köprülerin çalışma anı kayıtlarını (log) gösteren teşhis paneli; sorun self-servis çözülür. |
| ✋ **"İptal = tam dur"** | Herhangi bir indirmeyi iptal ettiğinde, arka planda motorların hiçbiri devam etmez; kaynağı gereksiz yemez, dosya yarım bırakılmaz. |
| ⚡ **Hafif mimari** | Tüm iletişim `127.0.0.1` üzerindeki **yerel HTTP ağ geçidi** üzerinden yapılır (`127.0.0.1:17802`); arka planda sürekli CPU/RAM yükü yoktur. |
| 🖥️ **Masaüstü entegrasyonu** | Masaüstü girdisi (.desktop), ikon ve `idm-linux` komutu ile terminalden de başlatma. |

### 📋 Gereksinimler

- Linux (x86_64 önerilir; aarch64 üzerinde Wine x86 uyumluluk katmanı gerekebilir)
- **Wine** (güncel sürüm önerilir) — IDM'nin Windows tarafı için
- **Python 3** (3.8+)
- Çalışan bir masaüstü ortamı (X11 veya Wayland) — GUI kullanımı için

### 📥 Kurulum

Tüm paketler **sürüm 1.0.0** için [GitHub Releases](https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0) üzerinden dağıtılır:

| Paket | Boyut | Kimin için |
|---|---|---|
| [`IDM-LINUX-1.0.0-x86_64.AppImage`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-LINUX-1.0.0-x86_64.AppImage) | ≈ 2,3 MB | Her dağıtımda çalışan tek dosya, kurulum gerektirmez |
| [`idm-linux_1.0.0_all.deb`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/idm-linux_1.0.0_all.deb) | ≈ 1,1 MB | Debian / Ubuntu / Linux Mint / MX Linux |
| [`idm-linux-1.0.0-1.noarch.rpm`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/idm-linux-1.0.0-1.noarch.rpm) | ≈ 1,8 MB | Fedora / openSUSE / RHEL türevleri |
| [`idm-linux-1.0.0-1-any.pkg.tar.zst`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/idm-linux-1.0.0-1-any.pkg.tar.zst) | ≈ 1,5 MB | Arch Linux / Manjaro / EndeavourOS |

> ✅ **Kalite kontrolü:** Bu dört paket de yayından önce otomatik doğrulamadan geçirildi — AppImage çıkarım + çalıştırma testi, deb için `dpkg-deb` denetimi, rpm içerik çıkarımı ve zst paket yapısı incelemesi; sürüm `1.0.0` ve `/opt/idm-linux` dizin düzeni her pakette tek tek doğrulandı.

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
>
> 🧙 **İlk açılış sihirbazı:** Paketi kurduktan sonra menüden **IDM LINUX** girdisini aç — **Kurulum & Kontrol Merkezi** (GUI sihirbazı) IDM'nin Wine'a kurulumunu, tarayıcı CRX3/Native Messaging kaydını ve eksik araçları (yt-dlp/ffmpeg/aria2c) tamamlar. Bu, `install.sh`'nin yaptığı işi paket kurulumundan sonra senin adına yürütür. Terminalden de: `idm-linux install`.

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
                                   ├─ Dosya barındırma çözümleyici (guest token + doğrudan bağlantı)
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

**Dosya barındırma sitesi bağlantısı neden IDM'ye gitmiyor?**
Dosya barındırma siteleri zaman zaman API/CDN tarafını değiştirir. Sistem Doktoru'ndaki ilgili çözümleyici kayıtlarını kontrol et; sorun sürüyorsa güncel çözümleyici için depoda hata (issue) aç.

**Paketleri nasıl derlerim?**
`packaging/` klasöründeki betiklerle kendi makinenizde derleyebilirsin: `appimage/build.sh`, `deb/build.sh`, `rpm/build.sh`, Arch için `arch/PKGBUILD` (`makepkg -f`). Ayrıntılar için [`RELEASING.md`](RELEASING.md).

### 🩺 Sorun Giderme

- **İndirme yakalanmıyor:** Tarayıcı eklentisinin kurulu/etkin olduğunu ve IDM LINUX'un çalıştığını doğrula.
- **Torrent başlamıyor:** Sistem Doktoru → torrent motoru günlüğü; DHT bağlantısı ve peer sayısını görüntüle.
- **Wine hatası:** `wine --version` ile sürümü doğrula; güncel Wine önerilir.
- **Detaylı log:** Sistem Doktoru tüm motor/çözümleyici etkinliklerini zaman damgalı gösterir; hata bildiriminde bu bölümü paylaş.

### 🛠️ Sürüm Akışı

- **v1.0.0** paketleri, *"IDM-LINUX-1.0.0 Building (İnşa Ediliyor)"* iş akışının nihai çalıştırmasıyla derlendi ve doğrudan [Release](https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0)'e eklendi; geçici iş akışları kaldırıldı, Actions geçmişinde yalnızca bu nihai çalıştırma korunur.
- Yeni bir sürüm çıkarırken paketleri `packaging/` betikleriyle kendi makinen derleyip yeni etikete (örn. `v1.0.1`) elle ekleyebilirsin — adımlar için [`RELEASING.md`](RELEASING.md).

### 📜 Sürüm Geçmişi

**1.0.0** — İlk halka açık sürüm: tarayıcı entegrasyonu, dosya barındırma sitesi desteği, video sitesi motor zinciri, gömülü torrent motoru (DHT), canlı yayın/DVR kaydı, deneme süresi sıfırlama, Sistem Doktoru ve 4 formatlı paketleme (AppImage / deb / rpm / zst).

### ⚖️ Lisans ve Yasal Not

Bu projenin kodu ve paketleme dosyaları **BELGESELSEMO**'ya aittir. "Internet Download Manager" ve "IDM", **Tonec Inc.**'in tescilli ürün ve markalarıdır. Bu proje bağımsız bir topluluk entegrasyonudur; Tonec Inc. ile bağlantılı değildir ve onaylanmamıştır. IDM yazılımını kullanmak için Tonec Inc. ile geçerli bir lisansın bulunması gerekir. Ayrıntılar için [`LICENSE`](LICENSE) dosyasına bak.

---

<a id="english"></a>
## 🇬🇧 English

**IDM LINUX** is an independent integration layer that lets you use **Internet Download Manager (IDM)** — the legendary download manager by Tonec Inc. — **fully functional** on Linux. IDM's interface, download engine and all of its capabilities keep running through Wine, while IDM LINUX acts as the smart middleware that:

- **captures downloads automatically** from your browser,
- solves tricky sources like popular **file hosting sites** and video sites with its own **engine chain**,
- downloads magnet links and .torrent files with a **built-in torrent engine**,
- records live streams (**DVR**),
- and runs everything through **one lightweight background service** — no desktop lag.

### ✨ Features

| Feature | Description |
|---|---|
| 🌐 **Browser integration** | The browser extension intercepts download requests and hands them to IDM — click once, IDM LINUX does the rest. |
| 📦 **File hosting site support** | Guest-token session and direct-link resolution for popular file hosting sites; prevents **corrupted/incomplete downloads**, the download completes through IDM. |
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

All packages are distributed for **version 1.0.0** via [GitHub Releases](https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0):

| Package | Size | For |
|---|---|---|
| [`IDM-LINUX-1.0.0-x86_64.AppImage`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-LINUX-1.0.0-x86_64.AppImage) | ≈ 2.3 MB | Any distro — single file, no installation |
| [`idm-linux_1.0.0_all.deb`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/idm-linux_1.0.0_all.deb) | ≈ 1.1 MB | Debian / Ubuntu / Linux Mint / MX Linux |
| [`idm-linux-1.0.0-1.noarch.rpm`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/idm-linux-1.0.0-1.noarch.rpm) | ≈ 1.8 MB | Fedora / openSUSE / RHEL-based |
| [`idm-linux-1.0.0-1-any.pkg.tar.zst`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/idm-linux-1.0.0-1-any.pkg.tar.zst) | ≈ 1.5 MB | Arch Linux / Manjaro / EndeavourOS |

> ✅ **Quality assurance:** All four packages passed automated verification before release — AppImage extraction + run test, `dpkg-deb` inspection for deb, RPM payload extraction and zst package structure review; version `1.0.0` and the `/opt/idm-linux` layout were verified in every package.

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
>
> 🧙 **First-launch wizard:** After installing the package, open **IDM LINUX** from the app menu — the **Setup & Control Center** (GUI wizard) installs IDM into Wine, registers the browser CRX3/Native Messaging hooks and installs missing tools (yt-dlp/ffmpeg/aria2c). It performs the same job `install.sh` does, on your behalf, right after the package installation. From a terminal: `idm-linux install`.

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
                                ├─ File hosting resolver (guest token + direct links)
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

**Why isn't a file hosting link going to IDM?**
File hosting sites change their API/CDN from time to time. Check the resolver entries in the System Doctor; if the problem persists, open an issue for the updated resolver.

**How do I build the packages?**
Build them on your own machine with the scripts under `packaging/`: `appimage/build.sh`, `deb/build.sh`, `rpm/build.sh`, and `arch/PKGBUILD` (`makepkg -f`) for Arch. See [`RELEASING.md`](RELEASING.md) for details.

### 🩺 Troubleshooting

- **Download not captured:** Make sure the browser extension is installed/enabled and IDM LINUX is running.
- **Torrent not starting:** System Doctor → torrent engine log; check DHT connectivity and peer count.
- **Wine errors:** Verify with `wine --version`; a recent Wine build is recommended.
- **Detailed logs:** The System Doctor shows timestamped activity of every engine/resolver; include it when reporting issues.

### 🛠️ Release Flow

- The **v1.0.0** packages were built by the single final run of the *"IDM-LINUX-1.0.0 Building (İnşa Ediliyor)"* workflow and attached directly to the [Release](https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0); temporary workflows were removed and only this final run is kept in the Actions history.
- For a new release, build the packages with the `packaging/` scripts on your own machine and attach them to a fresh tag (e.g. `v1.0.1`) — see [`RELEASING.md`](RELEASING.md) for the steps.

### 📜 Changelog

**1.0.0** — First public release: browser integration, file hosting site support, video site engine chain, built-in torrent engine (DHT), live stream/DVR recording, trial reset, System Doctor, and packaging in four formats (AppImage / deb / rpm / zst).

### ⚖️ License & Legal Notice

The code and packaging files of this project belong to **BELGESELSEMO**. "Internet Download Manager" and "IDM" are products and trademarks of **Tonec Inc.** This is an independent community integration project, not affiliated with or endorsed by Tonec Inc. A valid IDM license from Tonec Inc. is required to use IDM. See the [`LICENSE`](LICENSE) file for details.

---

<a id="русский"></a>
## 🇷🇺 Русский

**IDM LINUX** — независимый слой интеграции, который позволяет использовать легендарный менеджер загрузок **Internet Download Manager (IDM)** от Tonec Inc. **в полной мере на Linux**. Интерфейс, движок загрузки и все возможности IDM продолжают работать через Wine, а IDM LINUX выступает «переводчиком»:

- **автоматически перехватывает загрузки** из браузера,
- решает сложные сценарии — популярные **файлообменники** и видеосайты — собственной **цепочкой движков**,
- загружает magnet-ссылки и .torrent файлы с помощью **встроенного torrent-движка**,
- записывает прямые трансляции (**DVR**),
- и всё это через **один лёгкий фоновый сервис** — без нагрузки на рабочий стол.

### ✨ Возможности

| Возможность | Описание |
|---|---|
| 🌐 **Интеграция с браузером** | Расширение перехватывает загрузки и передаёт их IDM — один клик, остальное делает IDM LINUX. |
| 📦 **Поддержка файлообменников** | Гостевые сессии (guest token) и разрешение прямых ссылок для популярных файлообменных сайтов; защищает от **повреждённых загрузок**, скачивание завершается через IDM. |
| 🎬 **Поддержка видеосайтов** | Цепочка движков на основе yt-dlp / streamlink; оптимальный движок выбирается автоматически и передаётся в IDM, когда это возможно. |
| 🧲 **Встроенный torrent-движок** | Поддержка magnet и .torrent, поиск пиров через **DHT**, стабильная и быстрая загрузка; торрент сразу передаётся в IDM. |
| 📺 **Прямые трансляции / DVR** | Слой записи DVR для прямых трансляций, управление из интерфейса. |
| 🔑 **Сброс пробного периода** | Управление пробным периодом IDM прямо из интерфейса. |
| 🩺 **Системный доктор** | Встроенная панель диагностики с живыми логами движков и мостов; проблемы решаются на месте. |
| ✋ **«Отмена = полная остановка»** | При отмене загрузки ни один движок не продолжает работу в фоне — ни лишнего трафика, ни недокачанных файлов. |
| ⚡ **Лёгкая архитектура** | Всё общение через **локальный HTTP-шлюз** на `127.0.0.1` (`127.0.0.1:17802`); постоянной нагрузки на CPU/RAM нет. |
| 🖥️ **Интеграция с рабочим столом** | Запись .desktop, значок и команда `idm-linux` для запуска из терминала. |

### 📋 Требования

- Linux (рекомендуется x86_64; для aarch64 может потребоваться слой совместимости Wine x86)
- **Wine** (рекомендуется свежая версия) — для Windows-части IDM
- **Python 3** (3.8+)
- Запущенный графический сеанс (X11 или Wayland) для GUI

### 📥 Установка

Все пакеты распространяются для **версии 1.0.0** через [GitHub Releases](https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0):

| Пакет | Размер | Для кого |
|---|---|---|
| [`IDM-LINUX-1.0.0-x86_64.AppImage`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-LINUX-1.0.0-x86_64.AppImage) | ≈ 2,3 МБ | Любой дистрибутив — один файл, без установки |
| [`idm-linux_1.0.0_all.deb`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/idm-linux_1.0.0_all.deb) | ≈ 1,1 МБ | Debian / Ubuntu / Linux Mint / MX Linux |
| [`idm-linux-1.0.0-1.noarch.rpm`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/idm-linux-1.0.0-1.noarch.rpm) | ≈ 1,8 МБ | Fedora / openSUSE / RHEL |
| [`idm-linux-1.0.0-1-any.pkg.tar.zst`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/idm-linux-1.0.0-1-any.pkg.tar.zst) | ≈ 1,5 МБ | Arch Linux / Manjaro / EndeavourOS |

> ✅ **Контроль качества:** все четыре пакета прошли автоматическую проверку перед выпуском — распаковка и запуск AppImage, инспекция deb через `dpkg-deb`, распаковка содержимого rpm и разбор структуры пакета zst; версия `1.0.0` и структура каталогов `/opt/idm-linux` проверены в каждом пакете.

**1) AppImage (работает на любом дистрибутиве)**

```bash
chmod +x IDM-LINUX-1.0.0-x86_64.AppImage
./IDM-LINUX-1.0.0-x86_64.AppImage
```

**2) DEB — Debian / Ubuntu / Linux Mint / MX Linux**

```bash
sudo apt install ./idm-linux_1.0.0_all.deb
```

**3) RPM — Fedora / openSUSE / RHEL**

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

> Пакеты устанавливают приложение в `/opt/idm-linux`, регистрируют команду `idm-linux`, пункт меню и значок. Требуются **wine** и **python3** (пакетные менеджеры подтянут зависимости автоматически).
>
> 🧙 **Мастер первого запуска:** после установки пакета откройте **IDM LINUX** в меню приложений — **Центр установки и управления** (GUI-мастер) установит IDM в Wine, зарегистрирует CRX3/Native Messaging в браузере и доустановит недостающие инструменты (yt-dlp/ffmpeg/aria2c). Он выполняет ту же работу, что и `install.sh`, сразу после установки пакета. Из терминала: `idm-linux install`.

### 🚀 Быстрый старт

1. **Запустите IDM LINUX** — из меню приложений или командой `idm-linux`.
2. **Установите расширение браузера** — из репозитория (Chromium: *режим разработчика + «Загрузить распакованное расширение»*; Firefox: `about:debugging` → *Загрузить временное дополнение*).
3. Кликните по ссылке — расширение перехватит её, IDM подхватит загрузку.
4. **Torrent:** передайте magnet-ссылку или `.torrent` файл — движок найдёт пиров через DHT, и загрузка появится прямо в IDM.
5. Что-то не так? Откройте **Системного доктора** и смотрите живые логи движков.

### 🧠 Архитектура (кратко)

```
Расширение браузера ──► Локальный HTTP-шлюз (127.0.0.1:17802) ──► Wine/IDM (COM-мост + CLI-резерв)
                                │
                                ├─ Цепочка движков: yt-dlp → streamlink → прямой HTTP
                                ├─ Решатель файлообменников (guest token + прямые ссылки)
                                ├─ Встроенный torrent-движок (DHT, magnet, .torrent)
                                └─ Слой записи прямых трансляций / DVR
```

- Весь трафик остаётся на **localhost**; наружу не открывается ни один сервис.
- Каждый тип загрузки решает свой движок; видно в Системном докторе.
- Отменённая загрузка **останавливает движок мгновенно** — «призрачных» загрузок в фоне не остаётся.

### ❓ FAQ

**Нужна ли лицензия IDM?**
Да. IDM — коммерческое ПО (Tonec Inc.). Проект не распространяет IDM; это только слой интеграции для Linux. Используйте IDM с действующей лицензией.

**Почему torrent иногда стартует медленно?**
Скорость зависит от трекеров и пиров. Движок ищет пиров через DHT; торренты с малым числом сидов стартуют естественно медленнее.

**Почему ссылка файлообменника не уходит в IDM?**
Файлообменники периодически меняют API/CDN. Проверьте записи решателя в Системном докторе; если проблема остаётся — откройте issue в репозитории.

**Как собрать пакеты самому?**
Соберите их на своей машине скриптами из `packaging/`: `appimage/build.sh`, `deb/build.sh`, `rpm/build.sh`, для Arch — `arch/PKGBUILD` (`makepkg -f`). Подробности — в [`RELEASING.md`](RELEASING.md).

### 🩺 Устранение неполадок

- **Загрузка не перехватывается:** убедитесь, что расширение установлено/включено и IDM LINUX запущен.
- **Torrent не стартует:** Системный доктор → лог torrent-движка; проверьте DHT и число пиров.
- **Ошибки Wine:** проверьте `wine --version`; рекомендуется свежий Wine.
- **Подробные логи:** Системный доктор показывает всё с метками времени; приложите их к issue.

### 🛠️ Процесс релизов

- Пакеты **v1.0.0** собраны единственным финальным запуском workflow *«IDM-LINUX-1.0.0 Building (İnşa Ediliyor)»* и приложены прямо к [Release](https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0); временные workflow удалены, в истории Actions остался только этот финальный запуск.
- Для нового релиза соберите пакеты скриптами `packaging/` на своей машине и приложите их к новой метке (например `v1.0.1`) — шаги в [`RELEASING.md`](RELEASING.md).

### 📜 История версий

**1.0.0** — Первый публичный выпуск: интеграция с браузером, поддержка файлообменников, цепочка движков для видеосайтов, встроенный torrent-движок (DHT), запись прямых трансляций/DVR, сброс пробного периода, Системный доктор и пакеты в 4 форматах (AppImage / deb / rpm / zst).

### ⚖️ Лицензия и правовая заметка

Код и файлы пакетирования принадлежат **BELGESELSEMO**. «Internet Download Manager» и «IDM» — продукты и товарные знаки **Tonec Inc.** Это независимый проект сообщества, не связанный с Tonec Inc. и не одобренный ею. Для использования IDM требуется действующая лицензия от Tonec Inc. Подробности — в файле [`LICENSE`](LICENSE).

---

<a id="中文"></a>
## 🇨🇳 中文

**IDM LINUX** 是一个独立的集成层，让你在 Linux 上**完整地**使用 Tonec Inc. 出品的传奇下载工具 **Internet Download Manager (IDM)**。IDM 的界面、下载引擎和全部能力继续通过 Wine 运行，IDM LINUX 则作为“翻译层”：

- 从浏览器**自动捕获下载**，
- 用自研的**引擎链**处理热门**文件托管站**和视频网站等场景，
- 通过**内置种子引擎**下载磁力链接和 .torrent 文件，
- 录制直播流（**DVR**），
- 全部由**一个轻量后台服务**完成 — 桌面零卡顿。

### ✨ 功能特性

| 功能 | 说明 |
|---|---|
| 🌐 **浏览器集成** | 浏览器扩展自动拦截下载请求并交给 IDM — 点一下，剩下的交给 IDM LINUX。 |
| 📦 **文件托管站支持** | 为热门文件托管站解析访客会话（guest token）与直链；防止**文件损坏或不完整**，下载通过 IDM 完成。 |
| 🎬 **视频网站支持** | 基于 yt-dlp / streamlink 的引擎链；自动选择最合适的引擎，并尽可能移交 IDM。 |
| 🧲 **内置种子引擎** | 支持磁力链接和 .torrent，通过 **DHT** 发现节点，稳定快速；识别到种子后立即移交 IDM。 |
| 📺 **直播 / DVR 录制** | 可录制直播流的 DVR 层，在界面中管理。 |
| 🔑 **试用期重置** | 在界面中轻松管理 IDM 试用期。 |
| 🩺 **系统医生** | 内置诊断面板，实时显示引擎与桥接日志；问题自助排查。 |
| ✋ **“取消 = 完全停止”** | 取消下载时后台引擎立即全部停止；不浪费带宽，不留半截文件。 |
| ⚡ **轻量架构** | 所有通信都走 `127.0.0.1` 上的**本地 HTTP 网关**（`127.0.0.1:17802`）；后台没有持续的 CPU/内存占用。 |
| 🖥️ **桌面集成** | .desktop 桌面入口、图标以及可在终端使用的 `idm-linux` 命令。 |

### 📋 系统要求

- Linux（推荐 x86_64；aarch64 可能需要 Wine x86 兼容层）
- **Wine**（建议较新版本）— 用于 IDM 的 Windows 部分
- **Python 3**（3.8+）
- 图形桌面会话（X11 或 Wayland）— GUI 需要

### 📥 安装

所有包都通过 [GitHub Releases](https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0) 发布 **1.0.0 版本**：

| 软件包 | 大小 | 适用 |
|---|---|---|
| [`IDM-LINUX-1.0.0-x86_64.AppImage`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-LINUX-1.0.0-x86_64.AppImage) | ≈ 2.3 MB | 任意发行版 — 单文件，免安装 |
| [`idm-linux_1.0.0_all.deb`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/idm-linux_1.0.0_all.deb) | ≈ 1.1 MB | Debian / Ubuntu / Linux Mint / MX Linux |
| [`idm-linux-1.0.0-1.noarch.rpm`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/idm-linux-1.0.0-1.noarch.rpm) | ≈ 1.8 MB | Fedora / openSUSE / RHEL 系列 |
| [`idm-linux-1.0.0-1-any.pkg.tar.zst`](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/idm-linux-1.0.0-1-any.pkg.tar.zst) | ≈ 1.5 MB | Arch Linux / Manjaro / EndeavourOS |

> ✅ **质量保证：** 四个软件包在发布前都通过了自动验证 — AppImage 解压与运行测试、deb 的 `dpkg-deb` 检查、rpm 内容解压与 zst 包结构审查；每个包都核对了 `1.0.0` 版本号与 `/opt/idm-linux` 目录结构。

**1) AppImage（任何发行版可用）**

```bash
chmod +x IDM-LINUX-1.0.0-x86_64.AppImage
./IDM-LINUX-1.0.0-x86_64.AppImage
```

**2) DEB — Debian / Ubuntu / Linux Mint / MX Linux**

```bash
sudo apt install ./idm-linux_1.0.0_all.deb
```

**3) RPM — Fedora / openSUSE / RHEL 系列**

```bash
# Fedora / RHEL
sudo dnf install ./idm-linux-1.0.0-1.noarch.rpm
# openSUSE
sudo zypper install ./idm-linux-1.0.0-1.noarch.rpm
```

**4) Arch Linux / Manjaro / EndeavourOS（zst）**

```bash
sudo pacman -U idm-linux-1.0.0-1-any.pkg.tar.zst
```

> 软件包安装到 `/opt/idm-linux`，注册 `idm-linux` 命令、菜单入口和图标；需要系统已安装 **wine** 与 **python3**（包管理器会自动拉取依赖）。
>
> 🧙 **首启向导：** 安装软件包后，在应用菜单中打开 **IDM LINUX** — **安装与控制中心**（GUI 向导）会把 IDM 安装到 Wine、注册浏览器 CRX3/Native Messaging 并补齐缺失工具（yt-dlp/ffmpeg/aria2c）。它会在包安装完成后替你完成与 `install.sh` 相同的工作。终端方式：`idm-linux install`。

### 🚀 快速上手

1. **启动 IDM LINUX** — 应用菜单或终端运行 `idm-linux`。
2. **安装浏览器扩展** — Chromium 系：*开发者模式 + 加载已解压的扩展程序*；Firefox：`about:debugging` → *临时载入附加组件*。
3. 点击下载链接 — 扩展捕获后交给 IDM。
4. **BT 种子**：把磁力链接或 `.torrent` 交给 IDM LINUX；引擎通过 DHT 连接节点，任务直接出现在 IDM 列表中。
5. 遇到问题？打开**系统医生**查看引擎实时日志。

### 🧠 架构（简述）

```
浏览器扩展 ──► 本地 HTTP 网关 (127.0.0.1:17802) ──► Wine/IDM（COM 桥 + CLI 兜底）
                     │
                     ├─ 引擎链：yt-dlp → streamlink → 直接 HTTP
                     ├─ 文件托管站解析器（访客令牌 + 直链）
                     ├─ 内置种子引擎（DHT、磁力、.torrent）
                     └─ 直播 / DVR 录制层
```

- 所有流量只在 **localhost** 上流转；不对外暴露任何服务。
- 每种下载类型由各自的引擎处理；由谁接管可在系统医生中查看。
- 取消下载会**立即停止对应引擎** — 后台不会留下“幽灵任务”。

### ❓ 常见问题

**需要 IDM 授权吗？**
需要。IDM 是 Tonec Inc. 的商业软件；本项目不分发 IDM，只是 Linux 集成层。请使用合法授权的 IDM。

**BT 下载有时为什么很慢？**
取决于 tracker/节点状况。引擎用 DHT 发现节点；做种少的种子启动自然较慢。

**文件托管站链接为什么没有进入 IDM？**
文件托管站会不定期调整 API/CDN。查看系统医生中的解析器日志；仍未解决请在仓库提交 issue。

**如何自行构建软件包？**
使用 `packaging/` 下的脚本在本机构建：`appimage/build.sh`、`deb/build.sh`、`rpm/build.sh`，Arch 用 `arch/PKGBUILD`（`makepkg -f`）。详见 [`RELEASING.md`](RELEASING.md)。

### 🩺 故障排除

- **下载未被捕获：** 确认扩展已启用且 IDM LINUX 正在运行。
- **种子不开始：** 系统医生 → 种子引擎日志；检查 DHT 连接与节点数。
- **Wine 报错：** 用 `wine --version` 检查；建议较新的 Wine。
- **详细日志：** 系统医生带时间戳地记录全部引擎活动；提交 issue 时附上。

### 🛠️ 发布流程

- **v1.0.0** 的软件包由 *「IDM-LINUX-1.0.0 Building (İnşa Ediliyor)」* 工作流的唯一最终运行构建，并直接附加到 [Release](https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0)；临时工作流已移除，Actions 历史中仅保留该最终运行。
- 发布新版本时，用 `packaging/` 脚本在本机构建软件包，再附加到新标签（如 `v1.0.1`）— 步骤见 [`RELEASING.md`](RELEASING.md)。

### 📜 更新日志

**1.0.0** — 首个公开版本：浏览器集成、文件托管站支持、视频网站引擎链、内置种子引擎（DHT）、直播/DVR 录制、试用期重置、系统医生以及 4 种格式的打包（AppImage / deb / rpm / zst）。

### ⚖️ 许可与法律声明

本项目代码与打包文件归 **BELGESELSEMO** 所有。"Internet Download Manager" 与 "IDM" 是 **Tonec Inc.** 的产品和商标。本项目是独立的社区集成项目，与 Tonec Inc. 无关联亦未获其认可。使用 IDM 需持有 Tonec Inc. 的有效许可。详见 [`LICENSE`](LICENSE) 文件。

---

<div align="center">

[🇹🇷 Türkçe](#turkce) · [🇬🇧 English](#english) · [🇷🇺 Русский](#русский) · [🇨🇳 中文](#中文)

Made with ❤️ by **BELGESELSEMO** · IDM LINUX 1.0.0

</div>
