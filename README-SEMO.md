# ⊞ IDM SEMO — Windows

<a id="languages"></a>
<p align="center">🌐 <a href="#turkce">Türkçe</a> · <a href="#english">English</a> · <a href="#deutsch">Deutsch</a> · <a href="#russian">Русский</a> · <a href="#hindi">हिन्दी</a></p>

<p align="center"><img src="promo/assets/idm-semo-icon.png" width="104" alt="IDM SEMO"></p>

---

<a id="turkce"></a>
## Türkçe

### Windows için yerel IDM kontrol merkezi

<p align="justify" lang="tr"><strong>IDM SEMO</strong>; IDM entegrasyonu, tarayıcı köprüleri, video araçları, indirme hedefleri, tanı günlükleri ve kullanıcı tarafından başlatılan torrent/eD2K kuyruğunu yerel bir Windows arayüzünde birleştirir. Wine gerektirmez. Linux sürümünü arıyorsanız IDM LINUX rehberine geçin.</p>

<p align="center"><a href="https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-SEMO-1.0.0-x86_64.exe"><strong>⬇ EXE indir — önerilen</strong></a> · <a href="README.md">🐧 IDM LINUX rehberi</a> · <a href="https://rawgit.loltek.net/https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/promo/promo.html">Ortak tanıtım</a> · <a href="https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0">Sürüm notları</a></p>

### Neler sunar?

<p align="justify" lang="tr">🪟 <strong>Tek kontrol merkezi:</strong> kurulum, genel bakış, tarayıcılar, ayarlar, sistem doktoru, proje galerisi, destek, dil seçimi, hakkında ve torrent/eD2K olmak üzere 10 sayfa.</p>
<p align="justify" lang="tr">📂 <strong>Düzenli hedefler:</strong> IDM kategori kayıtları ve panel hedefleri <code>Downloads\IDM-SEMO</code> altında eşleştirilir.</p>
<p align="justify" lang="tr">⏯ <strong>Kontrol sizde:</strong> yeni torrent/eD2K girişleri durmuş satırlar olarak eklenir. Aktarımı siz başlatırsınız; Başlat/Duraklat tek kontrol üzerinden yönetilir. Mevcut kuyruğu koruma ve pencereyi yeniden açma/öne getirme davranışı sürer.</p>
<p align="justify" lang="tr">🌐 <strong>Tarayıcı ve video araçları:</strong> varsayılan tarayıcı algılama, Chromium/Firefox eklenti bağlantıları, eklenti klasörü ve Native Messaging durumu aynı panelde. Gerekli mağaza/izin adımlarını kullanıcı tamamlar.</p>
<p align="justify" lang="tr">🩺 <strong>Teşhis ve kişiselleştirme:</strong> canlı günlükler, sistem doktoru, 20 arayüz dili, BELGESELSEMO proje galerisi ve destek bağlantıları.</p>

### Üç kurulum yolu

| Yöntem | Kullanım | Komut penceresi |
|---|---|---|
| [**EXE**](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-SEMO-1.0.0-x86_64.exe) | İndirip açın; normal kurulum GUI’si görünür. | Başlatıcı CMD/PowerShell kabuğu çağırmaz. |
| [**BAT**](https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/belgeselsemo-idm-windows-installer.bat) | Güncel kaynak/payload kurucusunu çalıştırın. | Kısa süre görünebilir. |
| **CMD** | Aşağıdaki tek satırı CMD’ye yapıştırın. | CMD görünür; WSH/VBScript gerekir. |

<details>
<summary><strong>⌨ Windows CMD ile tek satırda kurulum</strong></summary>

<p align="justify" lang="tr">Komut İstemi’ni (CMD) açın, aşağıdaki komutu <strong>tek satır</strong> olarak yapıştırıp Enter’a basın. Güncel BAT resmî repodan <code>%TEMP%\idm.bat</code> yoluna indirilip çalıştırılır.</p>

```cmd
echo Set x=CreateObject("MSXML2.XMLHTTP"):x.Open "GET","https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/main/belgeselsemo-idm-windows-installer.bat",0:x.Send:Set s=CreateObject("ADODB.Stream"):s.Open:s.Type=1:s.Write x.responseBody:s.SaveToFile "%TEMP%\idm.bat",2 > "%TEMP%\d.vbs" & echo. & echo [i] Indiriliyor... / Downloading... & cscript //nologo "%TEMP%\d.vbs" & echo [+] Tamamlandi! / Completed! & call "%TEMP%\idm.bat"
```

<p align="justify" lang="tr">Windows Script Host/VBScript, MSXML ve ADODB.Stream erişimi gerekir. Bazı güncel veya kurum tarafından yönetilen sistemlerde bunlar kapalı olabilir; bu durumda EXE’yi seçin. Bu alternatif CMD penceresi gösterir; komut penceresiz açılış için EXE önerilir.</p>
<p align="justify" lang="tr">Komut internetten indirdiği betiği doğrudan çalıştırır; yalnızca resmî kaynağa güveniyorsanız kullanın. “Completed” mesajı kurulum başarısı garantisi değildir. İndirme/WSH hatası varsa devam etmeyin; eski <code>%TEMP%\idm.bat</code> dosyasına güvenmeyin.</p>

</details>

### Gereksinimler, uyumluluk ve lisans

<p align="justify" lang="tr">EXE, x64 Windows ve .NET Framework gerektirir. Sistem ağ/TLS desteği ve paketli motor sürümleri de önemlidir. <strong>Paket genelinde %100 Windows XP uyumu yoktur</strong>; paketli aria2 ve modern TLS/video araçları eski Windows sürümlerini sınırlar. Her Windows sürümünde canlı test yapılmış değildir.</p>
<p align="justify" lang="tr">IDM SEMO bağımsız bir entegrasyon/kontrol katmanıdır; Tonec Inc.’in resmî ürünü değildir ve IDM lisansı sağlamaz. Internet Download Manager’ın lisans ve kullanım koşulları geçerlidir. Değiştirilmiş, bilinmeyen kaynaklı kurucuları çalıştırmayın.</p>

### Gerçek Windows arayüzü ve doğrulama

<p align="justify" lang="tr">Galeri, GitHub Actions <strong>Windows Server 2022</strong> runner üzerinde üretim WinForms kontrollerinden <code>DrawToBitmap</code> ile alınan 10 gerçek arayüz görselini içerir. Bunlar maket veya Linux/Mono görüntüsü değildir; masaüstü ekran yakalaması ya da gerçek transfer/sürü testi kanıtı olarak sunulmaz. Başarılı doğrulama, 20 dil × 4 genişlikte yerleşim/hit-test ve 45 saniyelik EXE açılış gözleminde yeni görünür konsol penceresi bulunmamasını kapsar.</p>

<p><a href="#screenshots">🖼 10 gerçek Windows görselini aç</a> · <a href="https://github.com/vesvese55x/IDM-LINUX/actions/runs/41500997279">✓ Windows doğrulama kaydı</a> · <a href="#languages">↑ Dil seçimine dön</a></p>

---

## English

### A native IDM control center for Windows

<p align="justify" lang="en"><strong>IDM SEMO</strong> brings IDM integration, browser bridges, video tools, download destinations, diagnostic logs and a user-started torrent/eD2K queue into a native Windows interface. It does not require Wine. For the Linux edition, open the IDM LINUX guide.</p>

<p align="center"><a href="https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-SEMO-1.0.0-x86_64.exe"><strong>⬇ Download EXE — recommended</strong></a> · <a href="README.md">🐧 IDM LINUX guide</a> · <a href="https://rawgit.loltek.net/https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/promo/promo.html">Shared showcase</a> · <a href="https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0">Release notes</a></p>

### What does it offer?

<p align="justify" lang="en">🪟 <strong>One control center:</strong> 10 pages covering setup, overview, browsers, settings, system doctor, projects, support, language selection, about and torrent/eD2K.</p>
<p align="justify" lang="en">📂 <strong>Organized destinations:</strong> IDM category records and panel destinations are aligned under <code>Downloads\IDM-SEMO</code>.</p>
<p align="justify" lang="en">⏯ <strong>You stay in control:</strong> new torrent/eD2K inputs become stopped rows. You start each transfer; a single Start/Pause control manages it. Existing queues are preserved, with reopen/bring-to-front behavior.</p>
<p align="justify" lang="en">🌐 <strong>Browser and video tools:</strong> default-browser detection, Chromium/Firefox extension links, the extension folder and Native Messaging status share one panel. Required store/permission steps are completed by the user.</p>
<p align="justify" lang="en">🩺 <strong>Diagnostics and personalization:</strong> live logs, the system doctor, 20 interface languages, the BELGESELSEMO project gallery and support links.</p>

### Three installation methods

| Method | Usage | Console window |
|---|---|---|
| [**EXE**](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-SEMO-1.0.0-x86_64.exe) | Download and open it; the normal setup GUI appears. | The launcher does not invoke a CMD/PowerShell shell. |
| [**BAT**](https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/belgeselsemo-idm-windows-installer.bat) | Run the current authoritative source/payload installer. | May appear briefly. |
| **CMD** | Paste the single line below into CMD. | CMD is visible; WSH/VBScript is required. |

<details>
<summary><strong>⌨ One-line installation with Windows CMD</strong></summary>

<p align="justify" lang="en">Open Command Prompt (CMD), paste the following command as <strong>one line</strong>, then press Enter. It downloads the current BAT from the official repository to <code>%TEMP%\idm.bat</code> and runs it.</p>

```cmd
echo Set x=CreateObject("MSXML2.XMLHTTP"):x.Open "GET","https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/main/belgeselsemo-idm-windows-installer.bat",0:x.Send:Set s=CreateObject("ADODB.Stream"):s.Open:s.Type=1:s.Write x.responseBody:s.SaveToFile "%TEMP%\idm.bat",2 > "%TEMP%\d.vbs" & echo. & echo [i] Indiriliyor... / Downloading... & cscript //nologo "%TEMP%\d.vbs" & echo [+] Tamamlandi! / Completed! & call "%TEMP%\idm.bat"
```

<p align="justify" lang="en">Windows Script Host/VBScript, MSXML and ADODB.Stream must be available. They may be disabled on newer or organization-managed systems; choose the EXE in that case. This alternative shows CMD; use the EXE for startup without a console shell.</p>
<p align="justify" lang="en">The command immediately runs downloaded code; use it only if you trust the official source. “Completed” does not guarantee successful installation. Do not continue after a download/WSH error or trust an old <code>%TEMP%\idm.bat</code> file.</p>

</details>

### Requirements, compatibility and licensing

<p align="justify" lang="en">The EXE requires x64 Windows and .NET Framework. System network/TLS support and bundled engine versions also matter. <strong>The complete bundle is not Windows XP compatible</strong>; bundled aria2 and modern TLS/video tools limit older Windows versions. Not every Windows version has been live-tested.</p>
<p align="justify" lang="en">IDM SEMO is an independent integration/control layer, not an official Tonec Inc. product, and provides no IDM license. Internet Download Manager’s own licensing and usage terms apply. Do not run modified installers from unknown sources.</p>

### Real Windows interface and verification

<p align="justify" lang="en">The gallery contains 10 real UI renders produced from production WinForms controls using <code>DrawToBitmap</code> on a GitHub Actions <strong>Windows Server 2022</strong> runner. They are not mockups or Linux/Mono images, and are not presented as desktop captures or real transfer/swarm evidence. The successful verification covers layout/hit-tests across 20 languages × 4 widths and a 45-second EXE startup observation with no newly visible console window.</p>

<p><a href="#screenshots">🖼 Open the 10 real Windows images</a> · <a href="https://github.com/vesvese55x/IDM-LINUX/actions/runs/41500997279">✓ Windows verification record</a> · <a href="#languages">↑ Back to language selection</a></p>

---

## Deutsch

### Eine native IDM-Steuerzentrale für Windows

<p align="justify" lang="de"><strong>IDM SEMO</strong> vereint IDM-Integration, Browser-Brücken, Videowerkzeuge, Downloadziele, Diagnoseprotokolle und eine vom Benutzer gestartete Torrent/eD2K-Warteschlange in einer nativen Windows-Oberfläche. Wine ist nicht erforderlich. Die Linux-Ausgabe finden Sie in der IDM-LINUX-Anleitung.</p>

<p align="center"><a href="https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-SEMO-1.0.0-x86_64.exe"><strong>⬇ EXE herunterladen — empfohlen</strong></a> · <a href="README.md">🐧 IDM-LINUX-Anleitung</a> · <a href="https://rawgit.loltek.net/https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/promo/promo.html">Gemeinsame Produktvorstellung</a> · <a href="https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0">Versionshinweise</a></p>

### Was bietet IDM SEMO?

<p align="justify" lang="de">🪟 <strong>Eine Steuerzentrale:</strong> 10 Seiten für Installation, Übersicht, Browser, Einstellungen, Systemdiagnose, Projekte, Unterstützung, Sprachauswahl, Programminformationen und Torrent/eD2K.</p>
<p align="justify" lang="de">📂 <strong>Geordnete Ziele:</strong> IDM-Kategorieeinträge und die Zielordner der Oberfläche werden unter <code>Downloads\IDM-SEMO</code> aufeinander abgestimmt.</p>
<p align="justify" lang="de">⏯ <strong>Sie behalten die Kontrolle:</strong> neue Torrent/eD2K-Eingaben erscheinen als gestoppte Einträge. Sie starten die Übertragung; ein gemeinsames Start/Pause-Steuerelement verwaltet sie. Vorhandene Warteschlangen bleiben erhalten; das Fenster lässt sich erneut öffnen und in den Vordergrund holen.</p>
<p align="justify" lang="de">🌐 <strong>Browser- und Videowerkzeuge:</strong> Standardbrowser-Erkennung, Chromium/Firefox-Erweiterungslinks, Erweiterungsordner und Native-Messaging-Status befinden sich in derselben Oberfläche. Erforderliche Store- und Berechtigungsschritte führt der Benutzer aus.</p>
<p align="justify" lang="de">🩺 <strong>Diagnose und Anpassung:</strong> Live-Protokolle, Systemdiagnose, 20 Oberflächensprachen, die BELGESELSEMO-Projektgalerie und Unterstützungslinks.</p>

### Drei Installationswege

| Methode | Verwendung | Konsolenfenster |
|---|---|---|
| [**EXE**](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-SEMO-1.0.0-x86_64.exe) | Herunterladen und öffnen; der normale grafische Installer erscheint. | Der Starter ruft keine CMD-/PowerShell-Shell auf. |
| [**BAT**](https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/belgeselsemo-idm-windows-installer.bat) | Den aktuellen Installer mit Originalquellen und Nutzdaten ausführen. | Kann kurz erscheinen. |
| **CMD** | Die folgende einzelne Zeile in CMD einfügen. | CMD bleibt sichtbar; WSH/VBScript wird benötigt. |

<details>
<summary><strong>⌨ Installation mit einer Zeile in Windows CMD</strong></summary>

<p align="justify" lang="de">Öffnen Sie die Eingabeaufforderung (CMD), fügen Sie den folgenden Befehl als <strong>eine Zeile</strong> ein und drücken Sie Enter. Die aktuelle BAT wird aus dem offiziellen Repository nach <code>%TEMP%\idm.bat</code> heruntergeladen und ausgeführt.</p>

```cmd
echo Set x=CreateObject("MSXML2.XMLHTTP"):x.Open "GET","https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/main/belgeselsemo-idm-windows-installer.bat",0:x.Send:Set s=CreateObject("ADODB.Stream"):s.Open:s.Type=1:s.Write x.responseBody:s.SaveToFile "%TEMP%\idm.bat",2 > "%TEMP%\d.vbs" & echo. & echo [i] Indiriliyor... / Downloading... & cscript //nologo "%TEMP%\d.vbs" & echo [+] Tamamlandi! / Completed! & call "%TEMP%\idm.bat"
```

<p align="justify" lang="de">Windows Script Host/VBScript, MSXML und ADODB.Stream müssen verfügbar sein. Auf neueren oder zentral verwalteten Systemen können sie deaktiviert sein; wählen Sie dann die EXE. Diese Alternative zeigt CMD an. Für einen Start ohne Konsolen-Shell verwenden Sie die EXE.</p>
<p align="justify" lang="de">Der Befehl führt heruntergeladenen Code direkt aus. Verwenden Sie ihn nur, wenn Sie der offiziellen Quelle vertrauen. „Completed“ garantiert keine erfolgreiche Installation. Fahren Sie nach einem Download-/WSH-Fehler nicht fort und vertrauen Sie keiner alten Datei <code>%TEMP%\idm.bat</code>.</p>

</details>

### Voraussetzungen, Kompatibilität und Lizenz

<p align="justify" lang="de">Die EXE benötigt Windows x64 und .NET Framework. Netzwerk-/TLS-Unterstützung und die enthaltenen Engine-Versionen sind ebenfalls wichtig. <strong>Das Gesamtpaket ist nicht Windows-XP-kompatibel</strong>; die enthaltene aria2-Version sowie moderne TLS-/Videowerkzeuge schränken ältere Windows-Versionen ein. Nicht jede Windows-Version wurde live getestet.</p>
<p align="justify" lang="de">IDM SEMO ist eine unabhängige Integrations- und Steuerschicht, kein offizielles Produkt von Tonec Inc., und stellt keine IDM-Lizenz bereit. Es gelten die Lizenz- und Nutzungsbedingungen von Internet Download Manager. Führen Sie keine veränderten Installer aus unbekannten Quellen aus.</p>

### Echte Windows-Oberfläche und Überprüfung

<p align="justify" lang="de">Die Galerie enthält 10 echte Oberflächenbilder aus den produktiven WinForms-Steuerelementen. Sie wurden mit <code>DrawToBitmap</code> auf einem GitHub-Actions-Runner mit <strong>Windows Server 2022</strong> erzeugt. Es handelt sich weder um Entwürfe noch um Linux-/Mono-Bilder; sie sind auch keine Desktop-Aufnahmen oder Nachweise realer Transfers/Schwarmaktivität. Die erfolgreiche Überprüfung umfasst Layout-/Hit-Tests in 20 Sprachen × 4 Breiten sowie eine 45-sekündige Beobachtung des EXE-Starts ohne neu sichtbares Konsolenfenster.</p>

<p><a href="#screenshots">🖼 Die 10 echten Windows-Bilder öffnen</a> · <a href="https://github.com/vesvese55x/IDM-LINUX/actions/runs/41500997279">✓ Windows-Prüfprotokoll</a> · <a href="#languages">↑ Zurück zur Sprachauswahl</a></p>

---

## Russian

### IDM SEMO — центр управления IDM для Windows

<p align="justify" lang="ru"><strong>IDM SEMO</strong> объединяет интеграцию IDM, браузерные мосты, инструменты для видео, папки загрузок, журналы диагностики и запускаемую пользователем очередь torrent/eD2K в собственном интерфейсе Windows. Wine не требуется. Версия для Linux описана в руководстве IDM LINUX.</p>

<p align="center"><a href="https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-SEMO-1.0.0-x86_64.exe"><strong>⬇ Скачать EXE — рекомендуется</strong></a> · <a href="README.md">🐧 Руководство IDM LINUX</a> · <a href="https://rawgit.loltek.net/https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/promo/promo.html">Общая презентация</a> · <a href="https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0">Примечания к выпуску</a></p>

### Возможности

<p align="justify" lang="ru">🪟 <strong>Единый центр управления:</strong> 10 страниц — установка, обзор, браузеры, настройки, диагностика системы, проекты, поддержка, выбор языка, сведения о программе и torrent/eD2K.</p>
<p align="justify" lang="ru">📂 <strong>Упорядоченные папки:</strong> записи категорий IDM и пути в панели согласуются внутри <code>Downloads\IDM-SEMO</code>.</p>
<p align="justify" lang="ru">⏯ <strong>Управление в ваших руках:</strong> новые torrent/eD2K-задания добавляются остановленными. Передачу запускаете вы; для запуска и паузы используется одна кнопка. Существующая очередь сохраняется, окно можно открыть повторно и вывести на передний план.</p>
<p align="justify" lang="ru">🌐 <strong>Браузеры и видео:</strong> определение браузера по умолчанию, ссылки на расширения Chromium/Firefox, папка расширений и состояние Native Messaging доступны в одной панели. Необходимые действия в магазине расширений и выдачу разрешений выполняет пользователь.</p>
<p align="justify" lang="ru">🩺 <strong>Диагностика и настройка:</strong> журналы в реальном времени, диагностика системы, 20 языков интерфейса, галерея проектов BELGESELSEMO и ссылки поддержки.</p>

### Три способа установки

| Способ | Использование | Окно консоли |
|---|---|---|
| [**EXE**](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-SEMO-1.0.0-x86_64.exe) | Скачайте и откройте файл; появится обычный графический установщик. | Загрузчик не вызывает оболочку CMD/PowerShell. |
| [**BAT**](https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/belgeselsemo-idm-windows-installer.bat) | Запустите актуальный установщик с исходным кодом и данными. | Может ненадолго появиться. |
| **CMD** | Вставьте следующую строку в CMD. | CMD виден; требуются WSH/VBScript. |

<details>
<summary><strong>⌨ Установка одной строкой в Windows CMD</strong></summary>

<p align="justify" lang="ru">Откройте командную строку (CMD), вставьте команду ниже <strong>одной строкой</strong> и нажмите Enter. Актуальный BAT скачивается из официального репозитория в <code>%TEMP%\idm.bat</code> и запускается.</p>

```cmd
echo Set x=CreateObject("MSXML2.XMLHTTP"):x.Open "GET","https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/main/belgeselsemo-idm-windows-installer.bat",0:x.Send:Set s=CreateObject("ADODB.Stream"):s.Open:s.Type=1:s.Write x.responseBody:s.SaveToFile "%TEMP%\idm.bat",2 > "%TEMP%\d.vbs" & echo. & echo [i] Indiriliyor... / Downloading... & cscript //nologo "%TEMP%\d.vbs" & echo [+] Tamamlandi! / Completed! & call "%TEMP%\idm.bat"
```

<p align="justify" lang="ru">Необходимы Windows Script Host/VBScript, MSXML и ADODB.Stream. На новых или управляемых организацией системах они могут быть отключены; тогда используйте EXE. Этот способ показывает окно CMD. Для запуска без консольной оболочки выбирайте EXE.</p>
<p align="justify" lang="ru">Команда сразу выполняет загруженный код; используйте её только при доверии к официальному источнику. Сообщение «Completed» не гарантирует успешную установку. При ошибке загрузки/WSH не продолжайте и не полагайтесь на старый файл <code>%TEMP%\idm.bat</code>.</p>

</details>

### Требования, совместимость и лицензия

<p align="justify" lang="ru">EXE требует Windows x64 и .NET Framework. Также важны поддержка сети/TLS и версии включённых движков. <strong>Полный комплект не совместим с Windows XP</strong>: включённая версия aria2 и современные TLS/видеоинструменты ограничивают поддержку старых систем. Проверка вживую проводилась не на всех версиях Windows.</p>
<p align="justify" lang="ru">IDM SEMO — независимый слой интеграции и управления, а не официальный продукт Tonec Inc.; лицензия IDM не предоставляется. Действуют собственные условия лицензии и использования Internet Download Manager. Не запускайте изменённые установщики из неизвестных источников.</p>

### Настоящий интерфейс Windows и проверка

<p align="justify" lang="ru">В галерее показаны 10 настоящих изображений интерфейса, созданных из рабочих элементов WinForms методом <code>DrawToBitmap</code> на runner GitHub Actions с <strong>Windows Server 2022</strong>. Это не макеты и не изображения Linux/Mono; они не являются снимками рабочего стола или доказательством реальной передачи/активности пиров. Успешная проверка включает тесты размещения и доступности кнопок для 20 языков × 4 ширин и 45 секунд наблюдения за запуском EXE без новых видимых окон консоли.</p>

<p><a href="#screenshots">🖼 Открыть 10 настоящих изображений Windows</a> · <a href="https://github.com/vesvese55x/IDM-LINUX/actions/runs/41500997279">✓ Журнал проверки Windows</a> · <a href="#languages">↑ Вернуться к выбору языка</a></p>

---

## Hindi

### Windows के लिए स्थानीय IDM नियंत्रण केंद्र

<p align="justify" lang="hi"><strong>IDM SEMO</strong> एक स्थानीय Windows इंटरफ़ेस में IDM एकीकरण, ब्राउज़र ब्रिज, वीडियो उपकरण, डाउनलोड फ़ोल्डर, निदान लॉग और उपयोगकर्ता द्वारा शुरू की जाने वाली torrent/eD2K कतार को एक साथ लाता है। Wine की आवश्यकता नहीं है। Linux संस्करण के लिए IDM LINUX मार्गदर्शिका खोलें।</p>

<p align="center"><a href="https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-SEMO-1.0.0-x86_64.exe"><strong>⬇ EXE डाउनलोड करें — अनुशंसित</strong></a> · <a href="README.md">🐧 IDM LINUX मार्गदर्शिका</a> · <a href="https://rawgit.loltek.net/https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/promo/promo.html">दोनों उत्पादों का परिचय</a> · <a href="https://github.com/vesvese55x/IDM-LINUX/releases/tag/v1.0.0">रिलीज़ विवरण</a></p>

### इसमें क्या मिलता है?

<p align="justify" lang="hi">🪟 <strong>एक नियंत्रण केंद्र:</strong> इंस्टॉलेशन, अवलोकन, ब्राउज़र, सेटिंग्स, सिस्टम निदान, प्रोजेक्ट, सहायता, भाषा चयन, परिचय और torrent/eD2K के लिए 10 पृष्ठ।</p>
<p align="justify" lang="hi">📂 <strong>व्यवस्थित डाउनलोड:</strong> IDM श्रेणियों के रिकॉर्ड और पैनल के गंतव्य फ़ोल्डर <code>Downloads\IDM-SEMO</code> के अंतर्गत एक-दूसरे से मिलाए जाते हैं।</p>
<p align="justify" lang="hi">⏯ <strong>नियंत्रण आपके हाथ में:</strong> नए torrent/eD2K कार्य रुकी हुई पंक्तियों के रूप में जुड़ते हैं। स्थानांतरण आप शुरू करते हैं; शुरू/विराम के लिए एक ही नियंत्रण है। मौजूदा कतार सुरक्षित रहती है और विंडो को दोबारा खोलकर सामने लाया जा सकता है।</p>
<p align="justify" lang="hi">🌐 <strong>ब्राउज़र और वीडियो उपकरण:</strong> डिफ़ॉल्ट ब्राउज़र की पहचान, Chromium/Firefox एक्सटेंशन लिंक, एक्सटेंशन फ़ोल्डर और Native Messaging की स्थिति एक ही पैनल में हैं। स्टोर और अनुमति के आवश्यक चरण उपयोगकर्ता पूरे करता है।</p>
<p align="justify" lang="hi">🩺 <strong>निदान और अनुकूलन:</strong> लाइव लॉग, सिस्टम निदान, इंटरफ़ेस की 20 भाषाएँ, BELGESELSEMO प्रोजेक्ट गैलरी और सहायता लिंक।</p>

### इंस्टॉल करने के तीन तरीके

| तरीका | उपयोग | कंसोल विंडो |
|---|---|---|
| [**EXE**](https://github.com/vesvese55x/IDM-LINUX/releases/download/v1.0.0/IDM-SEMO-1.0.0-x86_64.exe) | डाउनलोड करके खोलें; सामान्य ग्राफ़िकल इंस्टॉलर दिखाई देगा। | लॉन्चर CMD/PowerShell शेल नहीं चलाता। |
| [**BAT**](https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/belgeselsemo-idm-windows-installer.bat) | वर्तमान मूल स्रोत और डेटा वाला इंस्टॉलर चलाएँ। | थोड़ी देर दिखाई दे सकती है। |
| **CMD** | नीचे दी गई एक पंक्ति CMD में पेस्ट करें। | CMD दिखाई देता है; WSH/VBScript आवश्यक है। |

<details>
<summary><strong>⌨ Windows CMD में एक पंक्ति से इंस्टॉलेशन</strong></summary>

<p align="justify" lang="hi">Command Prompt (CMD) खोलें, नीचे की कमांड को <strong>एक ही पंक्ति</strong> में पेस्ट करें और Enter दबाएँ। यह आधिकारिक रिपॉज़िटरी से वर्तमान BAT को <code>%TEMP%\idm.bat</code> में डाउनलोड करके चलाती है।</p>

```cmd
echo Set x=CreateObject("MSXML2.XMLHTTP"):x.Open "GET","https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/main/belgeselsemo-idm-windows-installer.bat",0:x.Send:Set s=CreateObject("ADODB.Stream"):s.Open:s.Type=1:s.Write x.responseBody:s.SaveToFile "%TEMP%\idm.bat",2 > "%TEMP%\d.vbs" & echo. & echo [i] Indiriliyor... / Downloading... & cscript //nologo "%TEMP%\d.vbs" & echo [+] Tamamlandi! / Completed! & call "%TEMP%\idm.bat"
```

<p align="justify" lang="hi">Windows Script Host/VBScript, MSXML और ADODB.Stream उपलब्ध होने चाहिए। नए या संगठन द्वारा प्रबंधित सिस्टम में ये बंद हो सकते हैं; ऐसी स्थिति में EXE चुनें। इस विकल्प में CMD विंडो दिखाई देती है। कंसोल शेल के बिना शुरुआत के लिए EXE इस्तेमाल करें।</p>
<p align="justify" lang="hi">यह कमांड डाउनलोड किए गए कोड को तुरंत चलाती है; इसका उपयोग तभी करें जब आपको आधिकारिक स्रोत पर भरोसा हो। “Completed” संदेश सफल इंस्टॉलेशन की गारंटी नहीं है। डाउनलोड/WSH त्रुटि होने पर आगे न बढ़ें और पुरानी <code>%TEMP%\idm.bat</code> फ़ाइल पर भरोसा न करें।</p>

</details>

### आवश्यकताएँ, संगतता और लाइसेंस

<p align="justify" lang="hi">EXE के लिए x64 Windows और .NET Framework चाहिए। सिस्टम का नेटवर्क/TLS समर्थन और शामिल इंजनों के संस्करण भी महत्वपूर्ण हैं। <strong>पूरा पैकेज Windows XP के साथ संगत नहीं है</strong>; शामिल aria2 और आधुनिक TLS/वीडियो उपकरण पुराने Windows संस्करणों को सीमित करते हैं। हर Windows संस्करण पर लाइव परीक्षण नहीं किया गया है।</p>
<p align="justify" lang="hi">IDM SEMO एक स्वतंत्र एकीकरण और नियंत्रण परत है, Tonec Inc. का आधिकारिक उत्पाद नहीं है और IDM लाइसेंस प्रदान नहीं करता। Internet Download Manager की अपनी लाइसेंस और उपयोग शर्तें लागू होती हैं। अज्ञात स्रोतों से बदले हुए इंस्टॉलर न चलाएँ।</p>

### वास्तविक Windows इंटरफ़ेस और सत्यापन

<p align="justify" lang="hi">गैलरी में GitHub Actions के <strong>Windows Server 2022</strong> runner पर उत्पादन WinForms नियंत्रणों से <code>DrawToBitmap</code> द्वारा बनाए गए 10 वास्तविक इंटरफ़ेस चित्र हैं। ये डिज़ाइन नमूने या Linux/Mono चित्र नहीं हैं; इन्हें डेस्कटॉप स्क्रीनशॉट या वास्तविक स्थानांतरण/पीयर गतिविधि के प्रमाण के रूप में प्रस्तुत नहीं किया गया है। सफल सत्यापन में 20 भाषाओं × 4 चौड़ाइयों पर लेआउट/हिट-टेस्ट और EXE शुरू होने के 45 सेकंड तक कोई नई दिखाई देने वाली कंसोल विंडो न होना शामिल है।</p>

<p><a href="#screenshots">🖼 Windows के 10 वास्तविक चित्र खोलें</a> · <a href="https://github.com/vesvese55x/IDM-LINUX/actions/runs/41500997279">✓ Windows सत्यापन रिकॉर्ड</a> · <a href="#languages">↑ भाषा चयन पर वापस जाएँ</a></p>

---

<a id="screenshots"></a>
## 🖼 Arayüz galerisi / Interface gallery

<p align="center"><img src="promo/assets/screens/idm-semo/overview.png" alt="IDM SEMO — Overview" width="92%"></p>
<p align="center"><img src="promo/assets/screens/idm-semo/browsers.png" alt="IDM SEMO — Browsers &amp; Extensions" width="92%"></p>
<p align="center"><img src="promo/assets/screens/idm-semo/installer.png" alt="IDM SEMO — Setup" width="92%"></p>
<p align="center"><img src="promo/assets/screens/idm-semo/settings.png" alt="IDM SEMO — Settings" width="92%"></p>
<p align="center"><img src="promo/assets/screens/idm-semo/doctor.png" alt="IDM SEMO — System Doctor" width="92%"></p>
<p align="center"><img src="promo/assets/screens/idm-semo/projects.png" alt="IDM SEMO — Projects" width="92%"></p>
<p align="center"><img src="promo/assets/screens/idm-semo/support.png" alt="IDM SEMO — Support" width="92%"></p>
<p align="center"><img src="promo/assets/screens/idm-semo/language.png" alt="IDM SEMO — Languages" width="92%"></p>
<p align="center"><img src="promo/assets/screens/idm-semo/about.png" alt="IDM SEMO — About" width="92%"></p>
<p align="center"><img src="promo/assets/screens/idm-semo/torrent-ed2k.png" alt="IDM SEMO — Torrent &amp; eD2K" width="92%"></p>

<p align="center"><a href="#languages">🌐 Türkçe · English · Deutsch · Русский · हिन्दी</a> · <a href="https://rawgit.loltek.net/https://raw.githubusercontent.com/vesvese55x/IDM-LINUX/refs/heads/main/promo/promo.html">IDM LINUX × IDM SEMO</a> · <a href="https://belgeselsemo.com.tr">BELGESELSEMO</a> · <a href="mailto:semihsy54@gmail.com">semihsy54@gmail.com</a></p>
