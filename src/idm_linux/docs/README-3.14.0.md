# IDM-Linux v3.14.0 — Evrensel Internet Download Manager (IDM) Linux Kurulum Sihirbazı & 20-Dilli Kontrol Merkezi

> **Bu araç [BELGESELSEMO](https://belgeselsemo.com.tr) tarafından ARENA.AI & Z.AI sayesinde yapılmıştır — [https://belgeselsemo.com.tr](https://belgeselsemo.com.tr)**

Linux dağıtımları (**Arch / CachyOS / Manjaro**, **Debian / Ubuntu / Mint**, **Gentoo**, **Fedora / RHEL**, **openSUSE**, **Void**, **Alpine**) üzerinde **her zaman en güncel resmi Windows Internet Download Manager** sürümünü `internetdownloadmanager.com` üzerinden dinamik çekip Wine ile sıfır çökme ile çalıştıran, tarayıcılarla çift kanallı entegre eden, **`.torrent` & `magnet:?` & `ed2k://` indirmelerini gerçek IDM üzerinden gerçekleştiren** ve **20 Bayraklı Dilli Modern Masaüstü GUI Kurulum Sihirbazı + Kontrol Merkezi** sunan uçtan uca entegrasyon paketidir.

---

## v3.14.0 Yenilikleri (Kullanıcı Raporu: Torrent Aşırı Yavaş ve Stabil Değil · TPB Magnetleri · Gofile 401 · Sistem Doktoru Günlükleri)

Bu sürüm, kullanıcının gerçek ölçümleriyle doğrulanmış **torrent motoru kök-neden
düzeltmeleri** ve günlüklerde görülen yan sorunların tamamını kapatır:

1. **Torrent "anlık iniyor sonra bekliyor" hastalığı KÖKTEN BİTTİ — GLOBAL BLOK
   KOORDİNASYONU:** Eski motorda bir parçayı TEK eş indiriyordu; o eş sessizleştiğinde
   parçanın blokları 90 sn kilitli kalıyor ve IDM akışı (kesintisiz bayt sınırı)
   DURUYORDU (kullanıcı ölçümü: ilk 100 sn ~9.7 MB/s, sonra 0.4 MB/s'ye düşüş,
   kesintisiz sınır 80+ sn sabit). Artık blok sahipliği oturumda TEK yerde tutulur:
   IDM'nin beklediği **kesintisiz sınır (frontier) parçasının blokları TÜM boş
   eşlere şeritlenir** — parça hızı eşlerin TOPLAM hızı olur. 8 sn yanıt gelmeyen
   her sahiplik ana döngüde otomatik serbest kalır (zombi parça imkânsız).
   **Gerçek ağ testi: 3 GB Linux Mint 22.3 ISO — 439 saniyede TAMAMLANDI
   (ortalama 6.91 MB/s, hız asla düşmedi), 1447/1447 parça SHA1 doğrulandı.**

2. **Tampon kilitlenmesi (v3.14 alfa testinde yakalandı) düzeltildi:** Doğrulanmamış
   blok tamponu dolunca motor TÜM talepleri durduruyor, kısmen dolu parçalar hiç
   tamamlanamıyordu. Artık sınır yalnız ileri-dolguyu durdurur; frontier bölgesi
   her koşulda talep edilir. Tampon ısındığında akış derinliği otomatik yarıya iner
   (RAM üst sınırı 96 MB — ultra hafif).

3. **TPB magnetleri ARTIK AÇILIYOR (kritik protokol hatası):** Eşlerin çoğu
   `ut_pex` uzantısına **1** kimliğini veriyor — bizim `ut_metadata` kimliğimizle
   ÇAKIŞIYORDU ve gelen meta veri parçaları PEX dalında sessizce YUTULUYORDU;
   magnet meta verisi ASLA tamamlanmıyordu ("TPB torrentlerini indirebiliyor mu
   hâlâ emin değilim" şikâyetinin kök nedeni). `ut_metadata` / `ut_pex` ayrımı
   artık mesaj İÇERİĞİYLE yapılır (kimlik çakışması önemsiz). Gerçek test: TPB
   magneti meta verisini **~18 saniyede** aldı, ardından ~6 MB/s ile indirdi.
   Ayrıca meta istek kilitleri 15 sn'de otomatik açılır (ölü eş kilidi imkânsız).

4. **Tit-for-tat: artık YÜKLÜYORUZ da unchoke Ediliyoruz:** Eşlerden `request`
   gelince doğrulanmış parçalardan cevap veriyoruz (eş başına 16 uçuş bloğu ile
   sınırlı — hafif). Küçük sürülerde (Ubuntu torrenti vakası: 5-17 eş) diğer
   leecherlar veri yükleyen istemciyi tercih eder; **Ubuntu 24.04 testi 1.48 →
   7.05 MB/s** çıktı. Frontier 12 sn ilerlemezse motor OTOMATİK ek eş keşfi
   (tracker + DHT) başlatır ve bulunan eşleri kuyruğun başına alır.

5. **Bütünlük kalkanı:** Hizasız/yanlış boyutlu bloklar parçayı kirlemeden reddedilir;
   SHA1'i düşen bir parçada İKİ denemede de katkısı olan (yani bozuk veri gönderen)
   eş oturum boyunca BANLANIR (libtorrent tarzı; masum tek-denklem katkıcılar korunur).

6. **WebSeed havuzu:** Tek iş parçacıklı, tek geçişli eski web seed akışı yerine
   **6 eşzamanlı işçi**; frontier-öncelikli çeker, P2P'nin çalıştığı parçalara
   dokunmaz, başarısız parçayı 20 sn sonra yeniden dener (web seed'li torrentlerde
   anında tam HTTP hızı).

7. **Gofile "HTTP 401" döndü:** Süresi dolan misafir token önbellekte kalınca
   /contents çağrısı kalıcı 401 veriyordu. Artık 401/403'te token geçersiz kılınıp
   TAZE misafir hesabı alınır ve çözümleme tekrarlanır; wt (websiteToken) sayfa
   HTML'inin yanında dist JS paketlerinden de kazınır ve daemon başında ARKA PLANDA
   ön-ısıtılır; store indirmeleri + yoklama artık `Cookie: accountToken=...`
   taşıyor (web uygulamasının birebir davranışı).

8. **Sistem doktoru günlüklerindeki gürültü bitti:** gofile linkleri yt-dlp'ye
   HİÇ verilmez (`[Piracy]` spam'i + 3-6 sn boşa gecikme kalktı); COM köprüsü
   üst üste 3 kez başarısız olursa 30 dakika atlanır (her gönderimde gereksiz
   cscript denemesi yok — CLI kanalı aynen çalışır).

9. **Yerinde kalan garantiler:** IDM'de iptal → 60 sn sonra motor DURAKLATILIR
   (arka planda asla indirme sürmez); yeniden bağlanınca kaldığı yerden devam.
   GUI'de DVR kartı yok — işlev daemon'da durur. Magnet/eD2k/torrent yakalama
   akışları korunur.

## v3.13.0 Yenilikleri (Kullanıcı Raporu: Trial Reset Hatası · Gofile Yakalama · ok.ru Hâlâ İnmüyor · TPB Torrentleri · Motor Hızı/İstikrarı · GUI Sadeliği)

Bu sürüm, kullanıcının altı somut şikâyetini kökten kapatır:

1. **Trial Reset "wine reg dönmedi" hatası BİTTİ:** Yeni akış `wine reg delete`
   çıkış koduna körü körüne güvenmez — her anahtar silindikten sonra `wine reg query`
   ile **VAR/YOK DOĞRULAMASI** yapılır (3 denemeli). Kalıcı wineserver reg işlemlerinden
   ÖNCE ısıtılır (soğuk başlangıç zaman aşımı yok); IDM kapanışı da doğrulanır.
   Artık Wine 10/11 (CachyOS Wine 11.20 dâhil) sahte dönüş kodu verse bile sayaç
   gerçekten silindiği sürece işlem **BAŞARILI** raporlanır.

2. **Gofile artık her koşulda IDM'de, tarayıcıda ASLA:** Yeni `gofile_resolver.py`
   gofile'ın resmî API'siyle (misafir hesap + wt + /contents) sayfa linkini
   (`gofile.io/d/<id>`) **ANINDA TAZE gerçek store linklerine** çözer. Yakalanan eski
   store linkleri bile referer'daki içerik kimliğinden yeniden üretilir → süresi dolmuş
   link = **bozuk dosya imkânsız**. Her link 1 baytlık yoklamayla doğrulanır:
   dürüst store cevabı varsa IDM **doğrudan, çok bağlantılı tam hızda** indirir;
   en küçük şüphede korumalı `/proxy/` köprüsüne düşer. Eklenti tarafında onay
   penceresi kalktı (otomatik yakalama), `location.assign/replace` ve gofile anchor
   tıklamaları da yakalanır, `downloads.onCreated/onDeterminingFilename` gofile'da
   her koşulda devralır.

3. **ok.ru kök çözüm:** `okcdn.ru` yt-dlp zincirine eklendi — bar'daki ok.ru/okcdn
   linklerine tıklandığında URL'ler **tıklama anında taze** çözülür (ok.ru linkleri
   dakikalar içinde süre dolduğu için eski akışta inmiyordu). Ayrıca yt-dlp'nin
   ok.ru/vk ekstraktörü kırıldığında ("unable to extract") 3 saatlik hızlı
   yükseltme penceresi otomatik açılır.

4. **TPB torrentleri dahil her magnet tıklanabilir:** Eklenti yalnız `magnet:?xt=`
   ile başlayan linkleri yakalıyordu (TPB magnetleri kaçardı) — artık **tüm**
   `magnet:` URİ'leri + shadow DOM kökündeki anchor'lar (composedPath) yakalanır.
   Motor tarafında UDP tracker anonsları BEP 15'e uygun **3 yeniden denemeli**,
   denenen tracker sayısı 12→24'e çıkarıldı; magnet meta takası eş başına 4 parça
   eşzamanlı istenir → meta saniyeler içinde iner.

5. **Native motor TAM GAZ ve ÇOK DAHA STABİL:**
   - **Takılı parça tuzağı bitti:** yanıtı gelmeyen blok talepleri 18 sn'de geri
     alınır ve yeniden istenir (eski akışta kayıp bir blok parçayı sonsuza dek
     kilitliyordu — "biraz stabil değil" şikâyetinin kök nedeni).
   - **Çoklu-parça hattı:** eş başına 8 eşzamanlı parça + 128 blok (2 MB) uçuş
     penceresi + 96 eş → IDMan'e akan sıralı bayt artık doyurucu hızda.
   - **Endgame modu:** son parçalar çift-talep edilir (ilk gelen kazanır).
   - **Sıfır-CPU durum:** tamamlanan bayt/bitfield artımlı tutulur (O(1) status),
     disk yazımları açık dosya tutamağı önbelleğiyle (LRU 96) syscall'sız.
   - Hâlâ **hiçbir dış araca bağımlılık yok** — aria2c yalnız yedek.

6. **IDM'de İPTAL = arka planda SIFIR indirme (tüm türler):** Köprü her IDM
   bağlantısını izler; tüm istemciler koptuktan 60 sn sonra torrent (native/aria2)
   ve eD2K motoru **DURAKLATILIR** — nokta kadar bant genişliği harcanmaz.
   IDM yeniden bağlanırsa (duraklat→devam) motor kaldığı yerden devam eder.
   Stream kayıtlarındaki mevcut 20 sn zarafet penceresi aynen korunur.

7. **GUI sadeliği:** Genel Bakış'taki "Aktif Canlı / DVR Kayıt İzleyicisi" kartı
   kaldırıldı (4.5 sn'lik gereksiz API yoklaması da bitti → GUI daha hafif).
   DVR/canlı kayıt İŞLEVİ daemon'da aynen yaşar; isteyen yine canlı yayın
   kaydı yapabilir.

## v3.12.0 Yenilikleri (Kullanıcı Raporu: Gofile Bozuk Dosya Bitti · ok.ru Anında Başlar · IDM Trial Reset · Görsel Rötuşlar)


Bu sürüm, kullanıcının canlı testlerinden dönen **dört somut şikâyeti** kökten kapatır ve
panelin bakım araçlarını genişletir. v3.11.0'da kanıtlanmış tüm kazanımlar (YouTube anında
kaynak, downsub-yaklaşımı altyazı, fullhdfilmizlesene akışı, torrent/eD2K motorları)
regresyon testleriyle kilitli tutulmuştur.

- **📦 GOFILE "3.27 KB bozuk dosya" TARİH OLDU — kanıtlanmış entegrasyon geri getirildi.**
  1. **KÖK NEDEN:** v3.11.0'daki "dinamik yoklama" denemesinde, gofile'ın anonim yoklamaya
     yanıt vermediği an (zaman aşımı/ağ kırpması) IDM'ye **çıplak sayfa URL'si** veriliyordu;
     IDM bunu indirince 3.27 KB'lık HTML hata sayfası dosya sanılıyordu.
  2. **ÇÖZÜM (kullanıcı kararı):** `gofile.io` yeniden **daima-köprü** (always-proxy) listesine
     alındı — api/store/gofile.io tüm alt alan adlarıyla ASMADA `/proxy/` köprüsünden akar;
     tarayıcı çerezleri + wt oturumuyla GERÇEK dosya iner, bütünlük koruması HTML sayfasını
     asla diske yazdırmaz (502 verir).
  3. **Anında yakalama KORUNDU:** page_hook'un `api.gofile.io/contents` JSON kancası
     aynen çalışır — dosya, sitedeki Download düğmesine basılmadan bara düşer; algılama hızı
     v3.11.0'daki gibi saniyeler içindedir. Yoklama beklemediği şekilde sonlanırsa YENİ
     **fail-safe** kuralı köprüye düşer ("yok" varsayıp ham URL vermek yasaklandı).

- **🟠 OK.RU İNDİRME ARTIK ANINDA BAŞLAR (YouTube/vk hızı).**
  1. **KÖK NEDEN:** ok.ru CDN'i (`vd*.okcdn.ru` / `mycdn.me`) çıplak istekte 400 döndüğü için
     her indirmede 1.3 sn anonim + 2.2 sn kimlikli **çift yoklama** çalışıyordu; IDM'nin
     başlaması ~4-5 sn gecikiyordu (vk'da doğrudan link olduğu için gecikme yoktu).
  2. **ÇÖZÜM:** `_FAST_PROXY_HOSTS` listesi eklendi (ok.ru, okcdn.ru, mycdn.me, vk.com,
     vkuser.net, userapi.com, bilibili, hdslb...) — bu CDN'lerde yoklama TAMAMEN atlanır,
     istek mikrosaniyelerde köprü biletine alınır; köprü Referer/Cookie'yi taşıdığı için
     400/403 kilidi köprüde çözülür. IDM tıklamayla <1 sn'de indirmeye başlar.
  3. **ok.ru progressive MP4 kazıyıcı:** ok.ru'nun `getVideoInfo` JSON'u ve sayfa
     data-options'ı içindeki uzantısız `vd*.okcdn.ru` / `mycdn.me` MP4 linkleri (type=33
     mobile vb.) artık yakalanır — bar DOĞRUDAN MP4 seçenekleri gösterir; HLS hazırlığı
     beklemeksizin anında iner (FF + Chromium eklentileri senkron güncellendi).

- **⏳ IDM TRIAL RESET (yeni özellik).**
  1. Genel Bakış & İndir sayfasındaki işlem çubuğuna **"⏳ IDM Trial Reset"** düğmesi eklendi
     (komut satırı: `idm-linux trial-reset`).
  2. Akış: IDMan.exe güvenle kapatılır → `HKCU\Software\DMCACount` deneme sayacı + nag
     değerleri (fSn/Checked/LastCheck/radxcnt) silinir → IDM arka planda yeniden ısıtılır.
  3. **GÜVENLİK:** kullanıcının kayıtlı lisans/serial verisi ASLA silinmez; onay penceresi
     20 dilde çevrilidir.

- **🎨 Görsel rötuşlar (kullanıcı kararı).**
  1. Alt bilgi notunda **Z.AI artık ARENA.AI ile AYNI yeşilimsi renkte** (#10b981).
  2. Sol menüdeki "IDM Hakkında" maddesinin ℹ️ simgesi, diğer madde simgeleriyle uyumlu
     **📖** simgesiyle değiştirildi (20 dilde senkron).

- **🧪 Kalite:** 10 yeni regresyon testi (`tests/test_v3120_fixes.py`) — gofile fail-safe,
  ok.ru hızlı yolu, trial-reset sabitleri; tam paket 139 testle yeşil.

---

## v3.11.0 Yenilikleri (Kullanıcı Raporu: YouTube Anında Kaynak · Altyazı 0 Bayt · ok.ru · Gofile · Torrent Hızı · eD2K Kökten Düzeltme)

Bu sürüm, kullanıcının canlı testlerle doğruladığı **yedi somut sorunun kök nedenini** kapatır
ve ağ motorlarına üç büyük hız katmanı ekler. Canlı testler: Linux Mint 22.3 resmi torrenti
(3 GB, ~30 MB/s, 60 eş), gerçek ok.ru videosu (okcdn.ru 400→206 doğrulaması), gerçek eD2K
sunucu girişi (client id atandı), DHT bootstrap 1.8 sn.

- **⚡ YouTube kaynakları ARTIK ANINDA (0 sn) bara düşer.**
  1. **KÖK NEDEN canlı doğrulandı:** eski sürümde `background.js` oynatıcının kendi çektiği
     `googlevideo.com/videoplayback` URL'lerini **bilinçli atlıyordu**; `page_hook.js` de
     medya MIME'ını eliyordu → "⚡ Hazır" anlık kaynaklar HİÇ doldurulamıyor, her şey 20-90 sn'lik
     yt-dlp çözümlemesine mahkûmdü ("bazen hiç bulamıyor" tam olarak buydu).
  2. Artık webRequest gözlemcisi videoplayback URL'lerini **akıllı tekilleştirmeyle** yakalar:
     `range/rn/rbuf/cmsg/keepalive` parametreleri SOYULUR (tam dosya indirilebilir URL kalır),
     `clen` parametresinden gerçek boyut okunur, aynı itag serisi sekme başına en fazla 4 kayıt.
  3. `page_hook.js` artık `ytInitialPlayerResponse.streamingData` içindeki **şifresiz muxed
     formatları** (itag 18/22/59/78) milisaniyeler içinde emit eder — video oynatılmadan ÖNCE bile
     kaynak hazır.
  4. yt-dlp yolu güçlendirildi: "Sign in to confirm you're not a bot" hatası = kırık demektir;
     **3 saatlik acil pencereyle** yt-dlp otomatik yükseltilir (24 saat bekleyen eski kural bitti).

- **📝 YouTube altyazı 0 bayt — DOWNSUB-YAKLAŞIMI ile kökten çözüldü.**
  1. Altyazı artık **SAYFA BAĞLAMINDA** (çerez + IP + POT/proof-of-origin dahil) indirilir:
     `page_hook.js` captionTracks baseUrl'ini `fetch(credentials:"include")` ile çeker, WEBVTT
     dönerse metin doğrudan daemon kasasına yazılır → IDM'de 0 bayt imkânsız.
  2. Sayfa-içi fetch başarısızsa (403/boş) eski URL girişi bırakılır; sunucu tarafında **4
     header-rotasyonu** + artık **timedtext yt-dlp yedeği** devreye girer: URL'den `lang=` ve
     video kimliği çıkarılıp yt-dlp'nin kendi istemci zinciri (tv/web_safari...) altyazıyı çözer.
  3. fullhdfilmizlesene/rapidvid akışı AYNEN korunmuştur (regresyon testleri kilitli).

- **🟠 ok.ru "bar gösteriyor ama inmiyor" — KÖK NEDEN: CDN alan adı değişmişti.**
  1. Canlı test: ok.ru videoları artık `vd*.okcdn.ru` / `mycdn.me`'den servis ediliyor ve bu
     CDN'ler **Referer'sız istekte 400**, `Referer: https://ok.ru/` ile 206 döndürüyor.
  2. Eski listede `okcdn.ru` YOKTU → linkler "direct" kalıp çıplak IDM'ye gidiyordu → 400.
     Artık `okcdn.ru`, `mycdn.me`, `vkuser.net`, `userapi.com` proxy-needy: kopma-diriltme
     relay'i Referer/çerez/UA ile akıtır.
  3. `auth_proxy` dinamik yoklaması 400'ü de "referer kilidi" sayar (kimlikli yoklama onaylarsa
     otomatik köprüye alınır) — gelecekteki CDN değişikliklerine karşı genel panzehir.

- **📁 Gofile algılama artık sayfa açılır açılmaz; üstelik GERÇEK linkle.**
  1. `page_hook.js` artık `api.gofile.io/contents` JSON yanıtını da inceler: her dosyanın
     GERÇEK `store*.gofile.io` linki + adı + boyutu **onay penceresi beklemeden** bara düşer
     (kullanıcı sitedeki Download'a basmadan önce indirme hazır).
  2. gofile artık her zaman-proxy listesinde DEĞİL: link anonim çalışıyorsa IDM'ye **gerçek
     gofile adresi** verilir; HTML/403 dönerse dinamik yoklama otomatik köprüye alır.
  3. Video olmayan dosyalar (zip/rar/pdf/apk/iso...) artık "Doğrudan Video (MP4)" diye SAHTE
     etiket almaz — gerçek uzantıyla **"Dosya (ZIP)"** görünür.

- **🧲 Torrent başlangıcı hızlandırıldı + UDP yasaklı ağlar kurtarıldı.**
  1. **Linux Mint resmi torrenti TEK udp tracker taşıyor** — güvenlik duvarı UDP'yi kapalıyorsa
     eski sürüm SIFIR eş buluyordu ("birkaç saat bekliyor"). Torrent <3 tracker taşıyorsa artık
     7 HTTP/HTTPS açık tracker'la ZENGİNLEŞTİRİLİR.
  2. **BEP 11 ut_pex** desteği: eşler artık EŞLERDEN de eş öğrenir (tracker/DHT yavaşsa hızlı
     başlangıç). Uzatılmış el sıkışmada ilan edilir, `added` paketleri ayrıştırılır.
  3. **DHT tamamen paralel:** bootstrap + get_peers eşzamanlı sorgularla çalışır (yavaş DNS
     tek başına bütçeyi yutabiliyordu); bootstrap sıfır düğümle döndüğünde bile get_peers
     ARTIK ÇALIŞIR (eski akışta DHT tamamen ölüyordu). Canlı test: bootstrap 1.8 sn.
  4. İstek penceresi 24→48 blok (eş başına 768 KB uçuş), akış penceresi 32→64 parça.
     Canlı test: 60 eşe 10 sn'de ulaştı, ilk bayt ~15 sn, 3 GB ~95 sn (≈30 MB/s).
  5. Çok dosyalı torrent tar akışına 15 dk dürüst zaman aşımı eklendi (eski akış sonsuza dek
     0 B/s bekleyebiliyordu).

- **🫏 eD2K KÖKTEN DÜZELTME + paralel kaynak taraması.**
  1. **ÖLÜMCÜL BULGULAR:** `parse_ed2k_link` hash'i STR döndürüyordu; oturum onu BYTES sanıyordu
     → `bytes+str` TypeError ile TÜM UDP sorguları, TÜM kaynak yanıtları ve TÜM eş paketleri
     sessizce çöküyordu. eD2K indirmesi asla başlayamazdı. Hex→bytes dönüşümü tek noktadan yapılır.
  2. Kaynak taraması İKİ AŞAMALI PARALEL: önce UDP globgetsources tüm sunuculara EŞZAMANLI
     (3-5 sn'de ilk kaynaklar), sonra TCP derin sorgu 4 işçiyle (eski akış 24 sunucuyu sıralı
     dolaşıyor, tur ~7 DAKİKA sürüyordu).
  3. Canlı test: sunucu girişi başarılı (client id atandı), docuwiki-formatı link ayrıştırması
     doğrulandı; referans-seeder uçtan uca aktarım testleri kilitli.

- **🪶 Bellek sızıntıları ve performans panzehirleri.**
  1. GUI `active_timers`: kendini yeniden zamanlayan döngüler artık ölü timer id biriktirmez
     (eski akış ≈57.600 ölü id/saat tutuyordu).
  2. Daemon probe: istek başına ThreadPoolExecutor yerine daemon Thread — asılı yt-dlp probe'u
     artık daemon sürecinin kapanmasını engelleyemez (py3.9+ atexit-join riski bitti).
  3. `_PROBE_INFLIGHT` toplu `.clear()` kaldırıldı (canlı Lock'u haritadan koparıp tekilleştirmeyi
     bozuyordu) — seçici zamana dayalı temizlik.
  4. YouTube videoplayback sayaçları sekme kapanınca/ gezinince düşürülür.

---

## v3.10.1 Yenilikleri (Kullanıcı Raporu: Torrent Boyutu · YouTube/ok.ru · Altyazı 0 Bayt · Gerçek Linkler)

Bu sürüm, v3.10.0'ı kuran kullanıcının bildirdiği **beş somut hatanın kök nedenini** kapatır.
Hiçbir özellik kaldırılmadı; hepsi düzeltildi ve testle kilitlendi.

- **🎬 YouTube & ok.ru "hiç kaynak bulamıyor" — KÖK NEDEN: yt-dlp kurulu değildi.**
  1. v3.10.0'da kurulum artık yetki (polkit) penceresi açmadığı için yt-dlp'yi **paket
     yöneticisiyle** kuramıyordu; sessizce atlanıyordu. Sonuç: YouTube/ok.ru/vk probe'ları
     boş dönüyordu.
  2. Artık `ensure_ytdlp()` **önce root'suz tek dosya binary** indirir
     (`~/.local/share/idm-linux/bin/yt-dlp`) — pip/PEP-668 ve yönetici izni gerekmez.
  3. İlk probe kurulumu **kısa süre bekler** (25 sn) ve hemen çözümler; kullanıcı boş bar
     görmez. Kurulum bitince bekleyen sayfalar için `IDM_MEDIA_UPDATED` yayınlanır, bar
     kendini tazeler.
  4. `find_ytdlp()` paketlenmiş ikiliyi ve `~/.local/bin` yolunu öncelikli arar.

- **🧲 Torrent "inmiyor, boyutu bile göstermiyor" — KÖK NEDEN: magnet meta verisi gelmeden
  IDM'ye adres veriliyordu.**
  1. Magnet'te dosya adı + boyut DHT/tracker'dan gelene kadar `totalLength=0` oluyordu; IDM
     boyut 0 görüp indirmeyi başlatamıyordu. Artık `dispatch_torrent_or_magnet` meta veriyi
     **en fazla 25 sn bekler** ve IDM'ye GERÇEK ad + GERÇEK boyutla gider (test: 792.723.456 bayt).
  2. Köprünün `HEAD` yanıtı da boyut bilinmiyorsa **12 sn bekler**; böylece IDM'nin ilk
     yoklaması da doğru boyutu alır.
  3. Meta veri hiç gelmezse sonsuza kadar %0'da bekletmek yerine **dürüst 503** mesajı verilir
     ("DHT/tracker üzerinden dosya bilgisi gelmedi...").
  4. Disk dolarsa/yazma hatası olursa motor artık sonsuz "parça yazılamadı" döngüsüne girmiyor;
     net hata mesajıyla duruyor.

- **📺 Altyazı "bar'da görünüyor ama IDM'de 0 baytta kalıyor" — KÖK NEDEN: dosya yanlış
  yere yazılıyordu.**
  1. Altyazı yalnızca `live.*` dosyasına yazılıyordu; köprü ise tamamlanan işlerde `ready.*`
     dosyasını okuyor → **0 bayt** gidiyordu. Artık metin doğrudan `output_file`'a yazılır.
  2. Boyut (`estimated_size`) ve `size_exact` ayarlanır → IDM **Content-Length** ve
     **206/Range** ile gerçek dosya indirir (duraklat/devam çalışır).
  3. Dosya adı/uzantı teslim edilen biçimle **birebir** eşleştirilir (`.vtt` → `.vtt`,
     `.srt` → gerçekten dönüştürülmüş `.srt`, `.ass` → `.ass`).
  4. MIME türleri düzeltildi (`text/vtt`, `application/x-subrip`...).

- **🔗 IDM'de artık LOCALHOST değil GERÇEK bağlantı görünüyor.**
  1. Yeni `prefer_real_urls` ayarı (varsayılan **açık**): tarayıcı barından gelen düz dosya
     indirmeleri IDM'ye **dosyanın gerçek CDN adresiyle** verilir (referer + çerez + UA ile);
     iletilmezse kopma-diriltme relay'ine otomatik düşülür.
  2. Torrent/magnet: IDM'nin **Referer/Kaynak** alanında gerçek `magnet:`/`.torrent` bağlantısı.
  3. eD2K: IDM'de gerçek `ed2k://` bağlantısı görünür.
  4. Altyazı ve HLS relay'lerinde de gerçek kaynak adresi referer alanına yazılır.

- **🫏 eD2K "boyut algılandı ama inmedi" — dürüst teşhis.**
  1. Dosya ağda paylaşılmıyorsa 2,5 dakika sonra net mesaj: "kaynak (tohum) bulunamadı".
  2. Sunucu girişi/çerçeve düzeltmeleri (v3.10.0) korunur; `REQUESTPARTS`, çok parçalı hash,
     kaynak birleştirme aynen çalışır.

- **⚡ VK/relay indirmelerinde kasma azaltıldı:** akış 64 KB yerine **256 KB** parçalarla ve
  1 MB'ta bir flush ile yazılır (syscall/flush fırtınası bitti).

- **🧪 KALITE:** 168 otomatik test (hepsi geçer) + canlı doğrulamalar: gerçek Debian magnet'i
  ile meta veri/boyut (792.723.456 bayt), altyazı köprüsünden Content-Length'li indirme,
  yt-dlp'nin root'suz kurulumu ve ilk probe'da hazır olması.

---

## v3.10.0 Yenilikleri (Yetki Penceresi Bitti · Dürüst Altyazı · Yerleşik eD2K Girişi · Yeni Kredi)

- **🔐 KURULUM/DAEMON ARTIK YETKİ (polkit) PENCERESİ AÇMIYOR:**
  1. Kök neden: tarayıcı zorunlu-kurulum politikası yazılırken `sudo -n` başarısız olunca
     `pkexec tee` yedeğine düşülüyordu — her açılışta parola penceresi. Bu yedek YOK EDİLDİ.
  2. Sıra artık: (a) hedef dizin yazılabilirse doğrudan yaz (root'suz, ör. `/etc/opt/chrome`
     izinliyse), (b) yalnızca `sudo -n` (parolasız), (c) olmadı → **sessizce atla**
     (`skip (yetki istenmedi)`) ve kullanıcı düzeyi yolla devam et.
  3. Kullanıcı düzeyi yollar korunur: Chromium `--load-extension` masaüstü sarmalayıcısı +
     Firefox profil `extensions/` kopyası — zorunlu politika OLMADAN da eklenti çalışır.
  4. İsteğe bağlı yükseltme: `write_policies_with_consent()` — yalnızca kullanıcı bir GUI
     düğmesine bastığında TEK bir yetki penceresi açar; kurulum akışında çağrılmaz.

- **📺 ALTYAZI DÜRÜSTLÜĞÜ (`.vtt` artık SRT diye inmiyor + oynatıcıya gömülü altyazılar barda):**
  1. Etiket ve dosya uzantısı KAYNAĞIN GERÇEK biçimini söyler (`1.vtt` → `.vtt`, `(VTT)`);
     SRT'ye yalnızca gerçekten dönüştürüldüğünde `.srt` denir.
  2. `vtt_to_srt()` gerçek SRT üretir: cue ayarları (`align:`/`position:`/`line:`), VTT'ye özel
     etiketler ve `NOTE`/`STYLE` blokları temizlenir.
  3. HTML hata sayfası (404 gövdesi) altyazı sanılıp dosyaya yazılmaz — gövde doğrulanır.
  4. Oynatıcıya gömülü (URL'siz, MSE/blob) altyazılar `textTracks` üzerinden VTT'ye
     serileştirilir, daemon kasasına yazılır (`POST /api/subtitle/register`) ve
     `http://127.0.0.1:<port>/subtitle/<hash>.vtt` adresinden IDM'ye sunulur.

- **🫏 eD2K SUNUCU GİRİŞİ KÖKTEN DÜZELDİ (yerleşik motor ağa gerçekten bağlanıyor):**
  1. Kök neden: paket çerçevesi ters yazılmıştı (`0xE3` + opcode + uzunluk). Doğrusu
     `0xE3` + uzunluk(4, LE) + opcode + gövde. Bu yüzden TÜM sunucular ya sessizce
     RST veriyor ya da yanıt vermiyordu.
  2. Sıkıştırılmış paket (`0xD4`) çözümü eMule tanımına çekildi (opcode açık, gövde zlib).
  3. Kaynak sorgusu boş yanıtta zaman aşımını beklemez; kaynaklar 24 sunucudan TOPLANIP
     birleştirilir ve ayrı iş parçacığında 25 saniyede bir tazelenir (indirme kilitlenmez).
  4. `REQUESTPARTS` eMule'ün beklediği 64 baytlık biçime geçti; ofsetler dosya başına göre;
     parça bitince aynı yükleme oturumunda sıradaki parçaya geçilir; kuyruk (`QUEUEFULL`)
     sonrası `STARTUPLOADREQ` ile sıraya yeniden girilir.
  5. Çok parçalı dosyalarda eD2K hash'i artık eMule tanımıyla doğrulanıyor
     (parça MD4'lerinin birleşiminin MD4'ü) — büyük dosyalar "bütünlük hatası" vermiyor.
  6. `ed2k://|file|…|/|sources,IP:PORT|/` içindeki kaynaklar anında kullanılır;
     `x-scheme-handler/ed2k` masaüstü kaydı eklendi. Hazır motor varken `/api/ed2k/install`
     harici (aMule) kurulum ve yetki penceresi BAŞLATMAZ.

- **💳 YENİ KREDİ:** Alt bilgi ve sol kenar çubuğu rozeti:
  “Bu araç **BELGESELSEMO** tarafından **ARENA.AI & Z.AI** sayesinde yapılmıştır.”
  (40 dil dosyası + karşılama sayfası + eklenti popup'ları aynı metni kullanır.)

- **🧪 KALITE:** 163 otomatik test (hepsi geçer) + canlı eD2K sunucu girişi doğrulaması
  (6 sunucu `OP_IDCHANGE` döndü) + referans eş ile uçtan uca çok parçalı eD2K indirme testi.

---

## v3.9.0 Yenilikleri (eD2K 'Unknown option H' + Torrent 0 B/s + Sahte Altyazı Eleme + Eklenti Canlı Güncelleme + Sürüklenebilir Bar)

- **🐴 eD2K 'eMule Add failed: Unknown option H' KÖKENDEN BİTTİ (gerçek aMule 2.3.3 üzerinde doğrulandı):**
  1. Kök neden: `amulecmd` host seçeneği `-h/--host=` (KÜÇÜK harf); `-H` diye seçenek yok —
     wxCommandLine 'Unknown option H' deyip çıkıyordu. Artık host argümanı hiç verilmez;
     ayrıca `--host=127.0.0.1` uzun biçimi yedek denemedir (4 aşamalı çağrı zinciri).
  2. **KUYRUK DOĞRULAMASI**: 'Add' başarılı görünsün de ne olursa — `Show DL` çıktısında
     dosya adı aranır; 'kuyruk doğrulandı' ibaresi yalnızca bağlantı GERÇEKTEN aMule'da
     beklerken gösterilir (sessiz başarısızlık bitti).
  3. Otomatik kurulum + bekleyen bağlantıyı otomatik iletme davranışı aynen korunur;
     indirilenler `~/.aMule/Incoming` klasörüne akar.

- **🧲 TORRENT '0 B/s + Bağlantı kesildi' (TPB raporu) 4 KALKANLA BİTTİ:**
  1. **Canlı tracker listesi**: ngosang/trackerslist 'best' listesi 12 saatlik önbellekle
     çekilir (raw.githubusercontent + jsdelivr yedeği), diskte saklanır ve statik listeyle
     birleştirilir — ölmüş trackerlar eş keşfini artık geciktiremez.
  2. **`--bt-prioritize-piece=head=48M`**: dosyanın İLK 48 MB'ı öncelikli iner — IDM
     saniyeler içinde gerçek bayt görür, '0 B/s' penceresi kökten biter.
  3. **Uçuşta tracker tazeleme**: arka planda 45 sn'de bir `aria2.changeOption` ile canlı
     tracker listesi çalışan motora uygulanır (gerçek aria2c 1.37 ile doğrulandı).
  4. Magnet meta bekleme 90 → 150 sn; daemon açılışında tracker listesi ön-ısıtılır.

- **📝 ALTYAZILAR: SAHTE GİRDİ YOK + DİL YAZAR + GERÇEK BOYUT (fullhdfilmizlesene raporu):**
  1. **Doğrulama**: her altyazı adayı probe edilir (4 başlık varyantı, içerik imzası:
     WEBVTT/ASS/TTML/SRT). CDN'in HTML hata sayfası döndürdüğü boş 'Default (Forced)'
     rayları gibi SAHTE girdiler bar'a HİÇ girmez.
  2. **Tekilleştirme**: aynı (host+yol) altyazının sorgu/şema varyantları tek satıra iner —
     '2 altyazı varken 3 gösterme' hatası bitti.
  3. **Dil etiketi**: `<track label/srclang>` → oyuncu konfigürasyonu bağlamı
     (`"label":"Türkçe Altyazı"`) → URL kalıbı (`?lang=tr`, `-tr.vtt`, `turkce`, `english`…)
     zinciriyle '📝 Altyazı: Türkçe' biçiminde YAZILIR.
  4. **Hotlink korumalı CDN indirmesi**: '0 bayt' vakasının kök nedeni — indirme artık 4
     başlık varyantıyla (tam tarayıcı → Origin'siz → çıplak → nötr) denenir.
  5. **Gerçek boyut**: doğrulanan altyazının tam bayt boyutu bar'da görünür ('52 KB').

- **🌐 EKLENTİ OTOMATİK KURULUM + SÜRÜM GÜNCELLEME (yeniden başlatma YOK):**
  1. Kurumsal policy güncelleme URL'i **sürüm damgalı** (`?v=3.9.0`): IDM güncellenince
     policy içeriği değişir, ÇALIŞAN Chromium bunu canlı algılar, yeni CRX'i kendi
     güncelleyicisiyle ÜZERİNE kurar (eski sürüm kaldırılıp kurulmaz — gerçek güncelleme).
  2. Policy yazımı sudo -n başarısızsa **pkexec GUI onay penceresiyle** tamamlanır.
  3. /welcome sayfası sürüm karşılaştırır: eski sürümlü eklenti sinyal verirse 'v3.8.0
     algılandı → v3.9.0 güncellemesi uygulanıyor' akışı + otomatik doğrulama tazelemesi.
  4. Firefox policy install_url de sürüm damgalı (bir sonraki açılışta otomatik güncelleme).

- **🖱️ IDM BAR: TIKLAMADAN OTOMATİK TESPİT + GERÇEK SÜRÜKLEME:**
  1. **Otomatik tespit**: video sayfası açılır açılmaz kaynaklar arka planda hazırlanır;
     YENİ akış/altyazı belirdiğinde bar kendini otomatik tazeler (tıklayınca hazır!).
     Rozet bulunan kaynak sayısını gösterir ('IDM · 3' / 'CC · 2').
  2. **Sürükleme kökten düzeltildi**: pill'in tamamı bir <button> olduğu için eski kod
     her tıklamada erken dönüyordu — sürükleme fiilen çalışmıyordu. Artık 6 px eşiğiyle
     SÜRÜKLEME/TIKLAMA ayrımı yapılır; pill'in her yerinden basılı tutup taşıyabilirsiniz.
  3. Bar konumu **siteye özel kalıcıdır** (storage) — bir kez taşıyın, SPA geçişlerinde
     bile yerinde durur.

- **🧪 KALITE**: 70 otomatik test (hepsi geçer) + GERÇEK aMule 2.3.3 üzerinde uçtan uca
  eD2K doğrulaması + gerçek aria2c 1.37 üzerinde argüman/RPC doğrulaması + sahte CDN
  simülatörüyle altyazı hattı e2e testi.

---

## v3.8.0 Yenilikleri (Tk 9.0 Tekerlek Kaydırma + eD2K Tam Otomatik Kurulum + Film Sitesi Altyazıları + aria2c Çöküşü + Hız)

- **🖱️ FARE TEKERLEĞİ Tk 9.0'DA KÖKTEN DÜZELDİ (Arch/CachyOS/Manjaro kullanıcılarının 'sayfa kaymıyor' raporu):**
  Tk 9.0, X11 fare tekerleği olay numaralarını yeniden numaralandırdı — yukarı=8 / aşağı=9
  (eski Tk 8.6'da 4/5). Global kaydırma dağıtıcısı `num == 4` diye bakıyordu; Tk 9.0'da
  yön tayini yapamıyordu. Artık çalışma anında Tk sürümü saptanır ve doğru tablo kullanılır:
  1. **Genel Bakış & Hızlı İndirme** sayfası dahil TÜM kaydırılabilir alanlar tekerleğe
     iki yönlü tepki verir (Xvfb otomasyonuyla birebir doğrulandı: `SCROLL_OK`).
  2. Oynatma Listesi liste kutusu da `<Button-4/5/8/9>` + `<MouseWheel>` ile kapsandı.
  3. Tk 8.6 (Debian/Fedora eski sürümleri) davranışı aynen korunur — sürüm uyumu garantili.

- **🐴 eD2K TAM OTOMATİK KURULUM — 'Kurulum başarısız — elle kurmayı deneyin' TARİH OLDU:**
  1. eD2K motoru (aMule) kurulu değilse daemon kurulumu **KENDİLİĞİNDEN** başlatır;
     tek onay, sistemin kendi **pkexec yetkilendirme penceresidir** — kullanıcıya
     `sudo pacman/apt/dnf` komutu ASLA gösterilmez (kullanıcı kararı v3.8.0).
  2. Bağlantı **beklemeye alınır**; kurulum + çekirdek başlangıcı bitince daemon
     bağlantıyı **otomatik olarak** motora iletir (ek tık yok).
  3. Eklenti onay penceresi aynı davranışta: motor yok → anında kurulum → bağlantı
     otomatik gönderim; başarısızlıkta dostane 'tekrar dene' mesajı (elle komut YOK).
  4. Çok stratejili kurulum zinciri: dağıtım deposundan aMule (Arch'ta mldonkey AUR'da
     olduğu için 'hedef bulunamadı' düşüşü bitti) → köksüz statik aMule paketi
     (GitHub, root/şifre gerektirmez). `developmentmachine/ed2k-downloader` değerlendirildi:
     zaten yalnızca aMule/mldonkey sarmalayıcı — mevcut motor yönetimimiz daha kapsamlı.

- **📝 FİLM SİTESİ ALTYAZILARI (fullhdfilmizlesene / rapidvid vb.) — 4 KATMANLI YAKALAMA:**
  1. **Arka plan webRequest ağ gözlemcisi** (v3.7.1): her çerçeve, Web Worker'lar ve sayfa
     açılmadan yüklenen `.vtt/.srt/.ass/.ttml/.dfxp/.smi/.sami/.sbv/.sub` dosyaları kaçmaz;
     `subs.rapidvid.org` gibi üçüncü taraf CDN altyazıları da yakalanır.
  2. **fetch/XHR yanıt gövdesi taraması**: oyuncular altyazı adresini JSON konfigürasyonunda
     taşır — 2 MB'a kadar text/json/javascript yanıtların gövdesi URL desenlerine taranır.
  3. **Resource Timing kaydı**: altyazı ÇOKTAN indirilmiş olsa bile tarayıcının kaynak
     kaydından URL kurtarılır (son 12 kaynak).
  4. Firefox eklentisi chromium ile **bayt-birebir aynı** içeriğe senkronlandı.

- **🧲 aria2c 'Unrecognized format' ÇÖKÜŞÜ (çıkış kodu 28) KÖKENDEN BİTTİ:**
  `--dht-entry-point` seçeneği TEK `HOST:PORT` kabul eder; virgüllü liste
  `[OptionHandlerImpl.cc] errorCode=1` ile süreç çökertiyordu. Tek giriş noktası +
  çökişte otomatik 'güvenli minimal argüman' ikinci denemesi; stub aria2c ile uçtan
  uca regresyon testi ekledi (yalnız 1 başlatma — yedek deneme gerekmeden RPC hazır).

- **⚡ PERFORMANS:**
  1. **QR kod LRU önbelleği**: 'Diğer Projeler' ve 'Teşekkür Et & Destekle' sayfalarının
     ~20 karekodu artık tekrar açılışlarda 0 ms (ilk üretimde zlib düzeyi 9→6 ≈ %35 hız).
  2. **İki yana yaslı metin debounce'u**: sayfa inşasında Canvas Configure fırtınaları
     artık tek idle yeniden çizime iner — Diğer Projeler sayfası ~%25 daha hızlı kurulur.
  3. Kelime ölçüm önbelleği (v3.7.1) aynen korunur.

- **🧪 KALITE: 129 otomatik test** — Tk 9.0 tekerlek eşlemesi, eD2K otomatik kurulum
  akışı (canlı daemon ucu + bekleyen bağlantı), stub aria2c uçtan uca başlatma,
  film sitesi altyazı katmanları ve QR önbelleği regresyonları dahil.

---

## v3.7.0 Yenilikleri (Torrent 503 Kökten Bitti + eD2K/eMule Desteği + Anında Video Kaynağı + IDM Kategori Klasörleri)

- **🧲 TORRENT 503 HATASI KÖKENDEN BİTTİ ('aria2c RPC servisi başlatılamadı' sona erdi):**
  1. **Senkron hazırlık kapısı**: IDM'ye köprü adresi YALNIZCA aria2c RPC gerçekten ayağa
     kalktıktan sonra gider — yarım motora bağlanıp 503 almak imkânsız.
  2. RPC hazır olma bekleme süresi 2.5 sn → 12 sn (soğuk başlangıçta sahte hata yok).
  3. aria2c çıktısı artık günlük dosyasına yazılır; motor ölürse popup GERÇEK nedeni
     (çıkış kodu + günlük kuyruğu) gösterir. BT/DHT portları rastgele seçilir (6881 çakışması bitti).
  4. Popup açılırken **motor ön-kontrolü**: aria2c kuruluysa yeşil sürüm rozatı,
     değilse paket yöneticisi kurulum komutu EN BAŞTA görünür.

- **🐴 eD2K (eMule) DESTEĞİ — docuwiki.net vb. siteler için:**
  1. `ed2k://|file|...` bağlantılarına tıklayınca şık onay penceresi açılır (tarayıcının
     'about:blank#blocked' engelini aşar); **mldonkey/aMule** motoruna `dllink` ile eklenir.
  2. mldonkey kuruluysa daemon `mlnet`'i ARKA PLANDA KENDİ KENDİNE başlatır — kullanıcı
     hiçbir şey yapmaz; aMule EC (4712) + `ed2k` CLI yedek yolları da desteklenir.
  3. Motor hiç yoksa **🛠 TEK TIK KURULUM**: pkexec + sistem paket yöneticisi
     (pacman/apt/dnf/zypper) ile mldonkey kurulur, kurulumdan sonra bağlantı eklenir.
  4. GUI 'Hızlı URL' kutusu `ed2k://` kabul eder; Genel Bakış sayfasında eD2K motor satırı.

- **⚡ VİDEO KAYNAĞI ARTIK ANINDA BULUNUYOR (yarış probe'u):**
  1. Eski 3'lü SIRALI deneme zinciri (135 sn'e kadar bekleme) KALDIRILDI: tv/web_safari
     ve default istemci setleri **AYNI ANDA** yarıştırılır; geçerli JSON üreten İLK
     süreç kazanır, diğerine kill atılır — YouTube tipik **2-6 sn** içinde dolar.
  2. `player_skip=webpage,configs` ile innertube adımları atlanır (daha da hızlı).
  3. YouTube DIŞI sitelerde gereksiz tekrar denemeleri bitti (90 sn tasarruf);
     her iki yarışçı da başarısızsa geniş yedek set tek denemede devreye girer.
  4. Kazanan tam `-J` info_dict'i olduğu için 4K/2K kaliteler + tüm altyazı dilleri
     eksiksiz bara düşer (hız-kalite tavizi YOK).

- **📝 ALTYAZILAR: yt-dlp -J artık güvenilir sonuç verdiği için** elle yüklenmiş +
  otomatik kapalı altyazılar (SRT/VTT/ASS/SSA/TTML/SBV/SUB/DFXP/SAMI) YouTube dahil
  tüm sitelerde '📝 Altyazı' grubunda listelenir; HLS TYPE=SUBTITLES ve MPD text
  AdaptationSet'leri motorda birleşip SRT'ye çevrilir.

- **🖥️ GUI:**
  1. Kaydırma çubuğu KALINLAŞTILDI: 16 px kanal + 12 px hap gövde; boşta bile net
     görünen renk, hover'da parlak cyan (kullanıcı raporu: 'aşırı ince, belli olmuyor').
  2. 'IDM Hakkında' sayfası GERÇEK IDM ikonunu kurulu IDMan.exe PE kaynaklarından
     çıkarır (256px'e kadar) + 3 yeni derinlemesine bölüm (hızlandırma tekniği,
     kategori sistemi, sürüm serileri).

- **📁 IDM KATEGORİ KLASFÖRLERİ: TÜM indirmeler artık IDM'in Windows'taki kategori
  düzenine göre klasörlenir** — Video → `Downloads/Video`, müzik → `Downloads/Music`,
  arşivler → `Downloads/Compressed`, belgeler → `Downloads/Documents`, programlar →
  `Downloads/Programs`. Tarayıcıdan, video barından, GUI panelinden ve oynatma
  listelerinden gelen her dosya doğru klasöre düşer; `Downloads` kökü tertemiz kalır.

---

## v3.6.0 Yenilikleri (Torrent Köprüsü Kökten Düzeltildi + Bar Donması Bitti + Altyazı Kapsaması Genişletildi + GUI Kaydırma)

- **🧲 TORRENT / MAGNET KÖPRÜSÜ KÖKTEN DÜZELTİLDİ ('Torrent başlatılamadı — IDM Linux
  köprüsüne ulaşılamadı' hatası BİTTİ):**
  1. Onay popup'unda 'Evet, IDM ile İndir' dendiğinde istek artık içerik betiğinden DEĞİL,
     arka plan servisinden gönderilir — sayfa kaynağından (örn. The Pirate Bay) yerel
     köprüye POST, CORS + güvenlik kalkanı nedeniyle her zaman reddediliyordu. Artık
     magnet ve .torrent indirmeleri 1. denemede aria2c motoruna düşer.
  2. `.torrent` dosyasını artık KÖPRÜNÜN KENDİSİ indirir (çerezler + Referer ile) —
     sayfa CSP/CORS engeline takılma ihtimali kalmadı.
  3. Köprü erişilirse ama torrent yine başlamazsa popup, GERÇEK nedeni gösterir
     (örn. 'aria2c kurulu değil' → 'Eksik Araçları Kur' yönlendirmesi).
  4. Native messaging'e 'torrent_download' yedek yolu eklendi; HTTP köprüsü uykudayken
     bile daemon uyandırılıp torrent iletebilir.

- **⚡ 'KALİTELER HAZIRLANIYOR...' TAKILMASI SÖNDÜ (asla video kaynakları gösterilemiyor
  sorunu bitti):**
  1. Arka plan servisindeki async handler'da BEKLENMEDİK bir istisna yanıtı kalıcı olarak
     yutuyordu (sendResponse hiç çağrılmıyordu) — bar sonsuza dek 'hazırlanıyor' da
     kalıyordu. Artık her koşulda yanıt döner.
  2. Daemon'da aynı sayfa için süren probe, ikinci isteği SONSUZ dek kilitliyordu.
     Kilit artık 20 sn'de bir açılır; ayrıca probe 75 sn'de sonuç vermezse anında
     'pending' yanıtı döner ve gerçek sonuç arkada bitince bara duyurulur.
  3. HTTP/native çağrıları 45 sn / 12 sn zaman aşımıyla sarıldı; bar 'hazırlanıyor'
     satırında CANLI saniye sayacı gösterir (donmuş arayüz yanılgısı biter) ve 2 dakikaya
     kadar kendi kendini yeniden tarar.

- **📝 ALTYAZI KAPSAMASI GENİŞLETİLDİ (film siteleri DAHİL):**
  1. jwplayer/artplayer/videojs gibi oyuncular altyazıyı <track> olmadan JS
     konfigürasyonunda tutar — sayfa kaynağı üzerinde sınırlı, hafif TEK geçişlik tarama
     eklendi (.vtt/.srt/.ass/.ttml/.sbv bağlantıları bar'a düşer).
  2. Altyazı yakalamaları artık yanlışlıkla 'Doğrudan Video (MP4)' seçeneği olarak
     SIZMAZ; yalnızca '📝 Altyazı: <dil>' grubunda listelenir.
  3. YouTube altyazı motoru 3 katına çıkarıldı (180 sn) ve SPA gezinmelerinde anında
     tazelenir ('yt-navigate-finish').

- **🖥️ GUI KAYDIRMA & TASARIM:**
  1. 'Genel Bakış & İndir' sayfası artık IDM Hakkında sayfası gibi kaydırılabilir;
     alt imza kartı ('Bu araç ... yapılmıştır') sabit kalır.
  2. Kalın/gri ttk kaydırma çubuğu kaldırıldı — koyu paletle uyumlu, 6 px ince, imleçle
     yanan ve sürüklenebilen özel kaydırma çubuğu tüm sayfalarda.

---

## v3.5.0 Yenilikleri (Altyazı Motoru Kökten Yenilendi + Torrent Onay Popup'u + Oynatma Listesi Kartı)

- **📝 ALTYAZI MOTORU KÖKTEN YENİLENDİ (YouTube DAHİL TÜM SİTELER):**
  1. YouTube'da elle yüklenen altyazı YOKSA bile **otomatik kapalı altyazılar
     (automatic_captions)** artık IDM barında listelenir — çoğu videonun altyazısının
     görünmemesinin kök nedeni buydu. Etiketler dil adıyla gelir: 'tr' yerine
     '📝 Türkçe', '📝 Otomatik Altyazı: English (SRT)' (48+ dil eşlemesi).
  2. **Sayfa içi YouTube altyazı motoru:** `ytInitialPlayerResponse` ->
     `captionTracks` TÜM rayları (elle + ASR otomatik) milisaniyeler içinde bara
     taşır; URL'lere `&fmt=vtt` eklenir, motor VTT→SRT dönüşümünü yapar.
  3. **Film siteleri:** altyazı tanıma desenleri genişletildi — `/api/subtitles`,
     `/caption?lang=..`, `timedtext`, `.ttml/.xml/.sbv/.ssa`, `text/vtt` MIME ve
     `application/x-subrip` artık yakalanır; timedtext URL'sinden dil kodu okunup
     yerel dil adı etiketi üretilir.
  4. **Bar'da ALTYAZI BÖLÜMÜ:** video kalitelerinin altında '─── 📝 Altyazılar ───'
     başlığıyla ayrı grup (başlık daemon'da 20 dile çevrilir). YouTube altyazı
     indirmeleri de artık 'Video [Türkçe].srt' gibi düzgün adla iner.
- **🧲 TORRENT / MAGNET ONAY POPUP'U:** herhangi bir bağlantı/buton `magnet:?` veya
  `.torrent` ise tıklamada ŞIK, IDM Linux temalı onay penceresi açılır:
  'Bu torrenti indirmek istiyor musunuz?' — 'Evet, IDM ile İndir' seçilirse içerik
  aria2c tabanlı torrent motorundan indirilir; 'Hayır' bağlantıyı tarayıcıya bırakır.
  Eski onaysız 'doğrudan gönder' yakalayıcısı kaldırıldı; popup 13 dilde yerleşiktir
  (tarayıcı diline göre seçilir), ESC/geri plan tıklaması ile kapanır.
- **TORRENT MOTORU GELİŞTİRİLDİ:** 14 tracker'a genişletilmiş liste + DHT önyükleme
  düğümleri (router.bittorrent.com vb.) — magnet meta keşfi saniyeler içinde;
  `--bt-max-peers=120`, `--bt-request-peer-speed-limit=10M`, `--min-split-size=1M`
  ile daha yüksek peer kullanımı ve akış hızı.
- **📋 OYNATMA LİSTESİ (PLAYLIST) İNDİR KARTI (Genel Bakış & İndir):**
  'Dağıtım & Ortam' kartının IDEAL KISALTILMIŞ devamında yeni kart: bağlantı kutusu
  SABİT, video listesi KAYDIRILABİLİR alanda. YouTube / Dailymotion / OK.ru / VK /
  Bilibili / Rutube + tüm yt-dlp siteleri — **site URL'den dinamik algılanır** (rozette
  görünür). '📥 Listele' ile videolar listelenir (süreleriyle), seçilenler SIRALI ve
  MAKSİMUM hızda (`-N 8` paralel parça) indirilir; her video için **canlı ilerleme
  (% + MB + hız + ETA)** ve **⏸ Duraklat / ▶ Devam / ✖ İptal** düğmeleri (SIGSTOP/
  SIGCONT ile anında, bağlantı korunur). Yarıda kalan video `.part` dosyasından
  kendiliğinden devam eder. Daemon kapanırken yt-dlp süreçleri zarifçe sonlanır.
- ** Playlist indirme yarış koşulları kapalı:** duraklatma proc-spawn penceresinde
  bile geçerli (`_in_worker` bayrağı) — sessiz no-op asla yaşanmaz.

## v3.4.0 Yenilikleri (IDM Hakkında Sayfası + Siyah Pencere Düzeltmesi + Anında YouTube + Altyazı/Multi-Ses Barı)

- **ℹ️ SOL MENÜ 9. SEÇENEK — 'IDM HAKKINDA':** IDM'nin resmi simgesiyle birlikte
  vikipedi düzeyinde detaylı bilgi sayfası: nedir, tarihsel gelişim (2001'den 6.43'e),
  özellikleri, IDM Linux projesi tanıtımı (BELGESELSEMO yapımı açık kaynak, Trial sürüm
  ve resmi siteden lisans notu) — metinler GERÇEK 'text-align: justify' (iki yana yaslı)
  piksel hassasiyetiyle dizilir ve **20 dilin TAMAMINA** çevrilidir.
- **SİYAH İNDİRME PENCERESİ KÖK NEDENİ DÜZELTİLDİ:** Wine 8.13+, Linux sistem koyu
  temasını Windows 'dark mode' bayrağına çeviriyordu; IDM 6.4x'in koyu-tema duyarlı
  diyalogları Wine GDI katmanında SİYAH'a boyanıyordu (OK.ru görselindeki sorun).
  Artık `AppsUseLightTheme=1 / SystemUsesLightTheme=1` bayrakları kurulumda VE her
  daemon açılışında sessizce dayatılır — IDM pencereleri daima AÇIK temada çizilir.
- **ANINDA YOUTUBE KAYNAKLARI (0 sn):** sayfada yakalanan googlevideo akışlarından
  '⚡ Hazır: 360p/720p (MP4 • sesli)' + '🎙 Ses' seçenekleri beklemeden bara düşer;
  arka plandaki tam yt-dlp çözümü bitince 4K'ya kadar tüm kaliteler + çok dilli
  altyazılar listeye eklenir. Probe istemci sırası hız önceliğine alındı
  (tv,web_safari → varsayılan → geniş yedek): ilk yanıt 5-15 sn'ye iner.
- **FİLM SİTESİ ALTYAZILARI BAR'DA + KÖK DÜZELTME:** `<track kind="subtitles">`
  yakalaması eklendi (altyazı açık olmasa bile tanınır). Ayrıca v3.2.2'de 'subs'
  tesliminin `direct_url`'i atamadan önce kullanması (UnboundLocalError) nedeniyle
  altyazı tıklamaları 500 çöküyordu — kökten giderildi; SRT indirmeleri artık sorunsuz.
- **ABYSS PASİF NOTU:** abyss kapalıyken abyss kaynakları bar'da HİÇ listelenmez;
  yerine 20 dilde yerelleştirilmiş not gösterilir: '💎 … IDM Linux Kurulum Merkezi →
  Yakalama & Wine Ayarları'ndan aktifleştirebilirsiniz'. Aktifken yalnız kaynaklar var.
- **GUI ARKA PLAN HAZIRLIĞI:** ağır sayfalar artık TEK TEK, 90 ms boşluklarla
  inşa edilir — açılış anında kasma yok, sayfaya tıklandığında içerik hazır.
- **Bar etiketleri 20 dilde:** kalite/ses/altyazı etiketleri daemon'un diliyle üretilir.

## v3.2.2 Yenilikleri (Bellek Sızıntısı KÖKTEN BİTTİ + Yeniden Başlatmasız Eklenti + Segmentli Altyazı SRT)

- **BELLEK SIZINTISI KÖK NEDENİ KAPATILDI (dsmartgo canlı izlemede OOM):**
  1. Canlı (dynamic) DVR MPD'lerinde SegmentTimeline'ın TAM genişletilmesi on binlerce
     segment URL'si üretiyordu; her probe farklı önbellek anahtarıyla 48 kayıt boyunca
     TUTULUYORDU → daemon RSS'i yüzlerce MB şişip 'Bellek Sıkıntısı' OOM'una yol açıyordu.
     Artık: dynamic MPD → kuyruk 360 segment, VOD → 5000; temsil başına 240/4000 sınırı.
  2. Probe önbelleği ÇİFT SINURLU (16 kayıt VE ~24 MB toplam gövde) ve önbellek kopyaları
     trimpli; yanıt gövdesi tam kalır (VOD indirmesi eksik kalmaz), cache key 8'lik
     kovalarla sabitlenir (canlı sayfada anahtar çöplüğü bitti).
  3. Katı bellek süpürme 10 dk → 3 dk; `_ASSIST`, `recent_urls`, proxy ticket'lar dahil.
  4. **RSS KALKANI:** 250MB'da anında önbellek boşaltma; 450MB'da (60 sn'de inmezse ve
     aktif indirme yoksa) daemon KENDİNİ zarifçe yeniden başlatır (systemd Restart=always
     saniyeler içinde sıfır bellekle kaldırır) + systemd `MemoryHigh=450M / MemoryMax=700M`
     son kalkan → 'Bellek Sıkıntısı Önlendi' bildirimi TARİH OLDU. GUI canlı 'Daemon
     Belleği' göstergesi eklendi.
  5. Blob yükleme (256MB'a dek) RAM'de 2x tutulup diske DOĞRUDAN akıtılır.
- **YENİDEN BAŞLATMADAN EKLENTİ KURULUMU:** kurumsal `ExtensionInstallForcelist` policy'si
  tüm Chromium ailesine yazılır (Chrome/Chromium/Brave/Edge/Vivaldi/Opera); Linux'ta policy
  dizini CANLI izlenir → kurulum sırasında tarayıcı açık olsa bile eklenti saniyeler içinde
  kendiliğinden yüklenir (RESTART YOK). Firefox ailesine `ExtensionSettings` policy + .xpi
  doorhanger (tek tık, anında aktif). Daemon `/crx-update.xml` + çıplak CRX güncelleyici
  uçlarıyla kurumsal mekanizmayı tam karşılar; uninstall policy'leri de temizler.
- **SEGMENTLİ ALTYAZILAR ARTIK SRT:** film sitelerinin HLS TYPE=SUBTITLES altyazı grupları
  (segmentli .vtt) sıralı indirilir, tek WebVTT'de birleştirilir ve SRT'ye çevrilir
  (AES-128 şifreli segmentler dahil); tek dosyalık .vtt/.srt/.ass da aynı kapıdan geçer.
  Bar seçeneği: '📝 Altyazı: <ad> (SRT)' → IDM native ilerlemeyle 'Video [Altyazı].srt' iner.
- **Performans:** Wine warm-up kadansı 45→60 sn (daha az arka plan CPU'su); `/api/status`
  artık daemon RSS + aktif kayıt sayısı raporlar.

## v3.2.1 Yenilikleri (Tek Bar + Taşınabilir Bar + Film Sitesi Altyazıları + GUI Rötuşları)

- **Çift bar BİTTİ:** gömülü oynatıcı (abyss.to / film siteleri) iframe'inde çıkan işlevsiz ikinci
  bar artık hiç monte edilmez; bar YALNIZCA üst çerçevede yaşar (işlevi olan tek bar kalır).
- **Bar videonun HEMEN ÜSTÜNDE:** üst çerçevede video öğesi yoksa bile bar, akış bildiren gömülü
  oyuncu iframe'inin tam üstüne çapalanır (z-index zaten 2147483647 = en üstte).
- **Sürükle-bırak bar:** pill alanından fareyle istenen yere taşınır; konum SPA geçişine dek korunur.
- **Film sitesi altyazıları bar'da:** JW/videojs gibi oyuncuların runtime çektiği .vtt/.srt dosyaları
  fetch/XHR sniffer ile yakalanır; sonradan eklenen <track> öğeleri de izlenir; altyazının gerçek
  adı (örn. 'Türkçe Altyazı') bar listesine düşer.
- **GUI:** 'Ayarları Kaydet ve Canlı Uygula' butonu ABYSS.TO bloğundan ÖNCE gelir; ipucu yazısı
  sola hizalı; tüm Combobox/dropdown'lar GUI ile aynı koyu temada (beyaz arkaplan yok, yazı beyaz).

## v3.2.0 Yenilikleri (TÜM indirmeler IDM'de NATİVE ilerler — 0 bayt donması TARİH OLDU)

1. **"Arka planda iniyor ama IDM 0 bayt gösteriyor" kök-nedeni KAPATILDI:** 3.1.0'da yt-dlp
   kaydı çalışır dosyasını (`ytdlp_merged.mp4`) GİZLİ yazıp ancak BİTİNCE IDM'ye veriyordu;
   abyss indiricisi ve yutto da aynısını yapıyordu. Artık **her motor** çıktısını doğrudan
   `stream_file`'a YAZAR (--no-part): yt-dlp ilerledikçe, abyss parçaları sırayla indikçe
   (paralel indirme sürerken sıralı canlı yazıcı!) baytlar IDM'den GERÇEK ZAMANLI akar —
   hız/yüzde/kalan süresi dahil. Probe önbelleği hızlı yolu: bar'ın arkada çözüttüğü -J
   sonucundan mux URL'leri SANSIYEDE alınır (YouTube'da -J tekrarı yok) → ffmpeg canlı
   fMP4 mux ile anında ilerleme. Sıra: canlı mux → taze -J çözümü (50 sn) → yt-dlp canlı
   kayıt → motor zinciri.
2. **IDM ÇOKLU BAĞLANTI YARIŞI fix (20-40 MB'ta kesilme sanığı #1):** IDM indirme ortasında
   bağlantı çevirir (eski bağlantıyı kapatır). Eski kod her kapanışı 'kullanıcı gitti' sanıp
   işçi 6 sn sonra DURUYORDU → kalan bağlantılar donuyor → indirme kesiliyordu. Artık AÇIK
   BAĞLANTI SAYACI var: bir bağlantı kapansa bile işçi sürer; yalnız TÜM bağlantılar kapanınca
   20 sn zarafet penceresi başlar.
3. **GERÇEK 206 RESUME:** boyutu kesin biletlerde köprü artık `Accept-Ranges: bytes` +
   `Content-Range` ile tam 206 yanıtı verir — IDM kendi bağlantısı kopsa bile KALDIĞI
   BAYTTAN devam eder. İşçi duraklatıldıysa resume'da OTOMATİK yeniden başlar; relay
   biletlerinde mevcut stream_file bayttan Range ile sürdürülür (test_98).
4. **Film siteleri (fullhdfilmizlesene/static3027 vb.) direct→RELAY:** bar'ın 'Doğrudan'
   seçenekleri artık çıplak URL olarak IDM'ye gitmez — KOPMA-DİRİLTME relay biletından akar
   (baytlar yine IDM'den NATİVE geçer): 16 deneme + header rotasyonu + 2 hakkı olan kaynak
   tazeleme (probe önbelleği + yt-dlp) + Range devamı → token ölümlerinde indirme KURTULUR.
5. **dsmartgo / canlı TV DVR SÜREKLİLİĞİ:** canlı HLS kaydında akış susarsa (ffmpeg çökmesi,
   playlist token ölümü, kısa kesinti) kayıt 3 sn sonra seq takibiyle KALDIĞI YERDEN devam
   eder (10 tura kadar, kopya segment YOK — resume_after/seq_tracker); playlist yeniden
   çekme pes etmesi 6→20 denemeye + üstel geri çekilmeye çıkarıldı; ENDLIST görülünce
   dürüstçe biter.
6. **ok.ru / vk.ru / vkvideo.ru barı geldi:** (a) sayfada video öğesi bulunamasa bile
   yakalanan medya akışı varsa bar SAĞ ÜSTTE görünür; (b) page-hook artık ok.ru
   getVideoInfo / vk al_video JSON yanıtındaki hlsManifestUrl/url1080/url720... anahtarlarını
   ve sayfa gömülü (data-options/playerParams) JSON'ları kazır; (c) ikisi de firefoxa senkron.
7. **abyss.to VARSAYILAN KAPALI (ABYSS PASİF):** GUI'de durum 'ABYSS PASİF' yazar; kodu
   yazıp EVET'e basmak YETERLİDİR — ayar anında canlı uygulanır (daemon'a /api/config ile
   itilir), 'Ayarları Kaydet ve Canlı Uygula' basmaya GEREK YOKTUR (GUI'ye ipucu satırı
   eklendi). Canlı yazım sayesinde ABYSS indirmesi de IDM'de anlık ilerler + kesin boyut
   (Content-Length) gösterilir.
8. **ffmpeg mux ses KOPYALAMA:** canlı mux'ta m4a/aac ses artık yeniden kodlanmaz (copy) —
   CPU boşa yanmaz, kalite kaybı yok; mp4'e kopyalanamayan codec'de otomatik aac yedeği.
9. 4 yeni regresyon testi (test_98..101: relay resume, bağlantı sayacı+restart, probe-
   önbelleği mux hızlı yolu, abyss varsayılan+GUI ipucu) → **100/100 test**.
10. Sürüm her yerde 3.2.0 (paket + chromium/firefox manifestleri + eklenti crx/zip/xpi
    yeniden derlendi).

---

## v3.1.0 Yenilikleri (YouTube 0-Bayt / bilibili / abyss.to / Yarıda Kesilme / Bellek Sızıntısı)

1. **YouTube 0-bayt donması KÖKTEN bitti (yt-dlp ilk motor):** 3.0.x'te bar'dan seçilen DASH
   seçenekleri önceden çözülmüş googlevideo URL'lerinin ffmpeg'e verilmesiyle indiriliyordu;
   YouTube'un SABR/PO-token kalkanında bu URL'ler 403 üretiyor, ffmpeg sessizce SIFIR bayt
   üretip IDM'i saatlerce %0'da tutuyordu (daemon.log kanıtı: ticket 8146ed5e). Artık bilinen
   yt-dlp sitelerinde indirme YT-DLP'NİN KENDİSİYLE başlar (SABR/PO-token/nsig'i içeriden
   halleder); YouTube için 3 aşamalı istemci stratejisi (varsayılan → tv_simply,tv,web_safari,mweb
   → android,web_embedded). IDM ilerlemesi aynen natif: büyüyen dosya anında köprüden akar.
2. **SESSİZ DONMA AVINCİ (idle watchdog):** ffmpeg-mux / canlı-mux / yt-dlp boru hattı motorları
   artık NE kadar süre bayt üretmezse o süreci kapatıp zincirdeki sonraki motora geçer (30-45 sn).
   Ses indirmesine 150 sn mutlak üst sınır. Artık hiçbir motor "0 bayt + kayıtsız" takılamaz —
   bellek/iş parçacığı sızıntısının birincil kaynağı buydu.
3. **bilibili tam çözüldü:** risk kontrolü (-352/412) panzehirli API katmanı (buvid3 sentetik +
   ana sayfa ısıtma), sunucu tarafı cid çözümü (pagelist/view), kalite adları (4K/HDR/1080P60/HD)
   + bantgenişliği×süre boyut tahmini, en yüksek kaliteli ses seçimi, b23.tv kısa link çözümü.
   Tarayıcı çerezleriyle (SESSDATA) 1080p+ kaliteler bara düşer.
4. **abyss.to Android protokolü uyarlandı (belgeselsemo fixi):** kullanıcının çalışan Android
   projesindeki AbyssVideoPort.java birebir port edildi — abyss.to/abyssplayer.com/short.icu
   HTML'indeki `const datas = "..."` blob'u base64→JSON→AES-256-CTR (anahtar
   md5(user_id:slug:md5_id)) çözülerek MP4 kaynakları çıkar; status/size/res_id/sub Java
   filtresi; sub.suffix taban mantığı (yeni CDN'ler sssrr.org vb. dahil). Klasik
   abysscdn.com/info ucu ölse bile çözümleme sürer. Parent sayfada iframe tarayıcı + tüm
   kaliteler bar'da boyutlarıyla listelenir (ABYSS 1080p • 963.2 MB). abyss_enabled artık
   VARSAYILAN AÇIK. Canlı doğrulama: belgeselsemo "Amerika'nın Hikayesi S1B1" → 1080p/720p/360p
   kaynakları + gerçek segment indirmesi (MP4 ftyp imzalı 2 MB segment) test edildi.
5. **Film sitelerinde yarıda kesilme panzehirleri güçlendi:** relay denemesi 8→16; 403/404/410'da
   header ROTASYONU (Referer/Origin/UA varyantları — static3027 gibi token'lı CDN kilitleri);
   5. denemeden sonra KAYNAK TAZELEME: probe önbelleği + yt-dlp ile yeni URL bulunup Range
   kaldığı bayttan sürdürülür (token süresi dolunca indirme ölmez).
6. **YouTube ilk açılış yavaşlığına köklü çözüm (arka plan probe):** bilinen sitelerde yt-dlp
   -J çözümlemesi (20-90 sn) ARKA PLANDA çalışır; bar ANINDA döner ("⚡ motor arka planda
   çözüyor" durumuyla), probe bitince önbelleğe yazılır + tarayıcıya IDM_MEDIA_UPDATED haberi
   gider → bar kendini tazeleyip tüm kaliteleri gösterir. Kısmi sonuç asla önbelleklenmez.
7. **Bellek sızıntısı + tarayıcı çökmesi avı:** content.js'in her 1.2 sn'de
   querySelectorAll("*") ile on binlerce düğümü gezmesi (YouTube'da CPU katliamı) hedefli
   oyuncu-konteyner taraması + 5 sn'de bir gölge yenilemesi + video yokken 5 tikte 1 çalışma
   ile değiştirildi; SPA geçişlerinde yakalama tamponları (hookedStreams/seenUrlSet) sıfırlanır;
   daemon tarafında watchdog'lar takılı işçi/süreç birikimini keser.
8. **dsmartgo gibi DRM'li canlı TV sitelerinde dürüst mesaj:** EME
   (requestMediaKeySystemAccess/mediaKeys) kancası Widevine/FairPlay kullanımını anlar; bar
   "bulunamadı" yerine "DRM korumalı — indirilemez" der; text/html iframe bildirimleri sahte
   "Doğrudan Video" olarak sızmaz.
9. 5 yeni regresyon testi (test_93..97: Java port protokolü, bilibili risk-kurtarma, sanal şema
   filtresi, 403 kaynak tazeleme, arka plan probe bildirimi) → **96/96 test**.
10. Sürüm her yerde 3.1.0 (paket + chromium/firefox manifestleri).

---

## v3.0.0 Yenilikleri (Kaynak Bulma Motoru Kökten Yenilendi — Kullanıcı Şikayetlerinin Kök-Nedenleri)

1. **ÖLÜ KOD SKANDALI bitirildi (`_is_known_ytdlp_site` çift tanım):** 2.9.x'te fonksiyon dosyada İKİ KEZ tanımlıydı; modül sonundaki (ölü kodlu) tanım düzgün olanı EZİYORDU. Sonuç: `vk.ru`, `vkvideo.ru`, `rutube`, `b23.tv`, `dai.ly` gibi sayfalarda yakalanan akış VARSA yt-dlp probe'u HİÇ çalışmıyordu — "bilibili/ok.ru/vk.ru'dan video bulamıyorum" şikayetinin asıl kök-nedeni. Tek ve doğru tanım + test_88 sonsuza dek kilitledi.
2. **YouTube boş-bar kök-nedeni kapatıldı:** Probe `timeout=20s` idi — YouTube `-J` çözümlemesi zorlanmış `player_client=default,tv,mweb` listesiyle bunu AŞIYOR, TimeoutExpired sessizce YUTULUYORDU. Artık: 45 sn × 2 deneme; 1. deneme yt-dlp'nin KENDİ varsayılan istemcileri (bakımcıların güncel tuttuğu set), 2. deneme `tv_simply,tv,web_safari,mweb` yedek seti; bot-check ("Sign in to confirm") görünce otomatik yedek istemciye düşer; stderr artık INFO loglanır (sessiz ölüm yok); hata/timeout durumunda yt-dlp otomatik güncelleme tetiklenir.
3. **Bilinen-site listesi 20'den 100+ domaine çıkarıldı:** IDM'in Windows'taki binlerce-site iddiasına en yakın eşik — vk.ru/vkvideo.ru/vkontakte.ru/userapi.com, rutube.ru, dzen.ru, mycdn.me, dai.ly, bilibili.tv, sibnet.ru, vidmoly/molystream/hdplayer/playerx (film sitesi gömülü playerları), weibo, xiaohongshu, cda.pl, iqiyi/youku/douyin, trovo, vkplay, wasd, odysee, rumble, bitchute vb. Sınır-farkındalıklı substring eşleşmesi: "x.com" deseni artık "netflix.com" ile YANLIŞ eşleşmez (test_88).
4. **Film sitesi "yarıda kesilme" sanası kökten kapandı (Range doğrulaması):** Content-Length'suz akış "temiz bitti"de sahte 'tamamlandı' yerine relay artık sunucuya `Range: bytes={alınan}-` sorusu sorar: 416 → gerçekten dosya sonu (dürüst tamam), 206 → sunucuda DAHA FAZLA veri var (kaldığı yerden sürer, gerçek boyut öğrenilir). test_90/test_91 iki yolu da kilitledi.
5. **Köprü hiç ölü bağlantı bırakmaz:** `/api/video/probe` ve TÜM POST uçları global kalkana alındı — beklenmeyen çökmede eklenti daima JSON hata yanıtı alır, "köprü servisine ulaşılamadı" yanılgısı biter.
6. **SELF-HEALING video bar:** Oynatıcı geç açılan (SPA/film siteleri) sayfalarda yakalanan akış, bar ilk boş sonucu verdikten SONRA geliyordu ve kullanıcı "Yenile"ye basmak zorunda kalıyordu. Artık yeni akış kaydı barı 1.5 sn'de otomatik yeniden tarar (debounce + sayfa başına 5 deneme sel koruması); boş sonuç + yakalanan akış varken 8 sn'lik otomatik yeniden tarama.
7. Test portu çakışmasına dayanıklılık (test_05) + 5 yeni regresyon testi → **91/91 test**.
8. Sürüm her yerde 3.0.0 (paket + chromium/firefox manifestleri).

---


## v2.9.11 Yenilikleri (Yarıda Kesilme Kök-Nedenleri Kapatıldı)

- **Segment birleştirme delik kapatması:** DASH segmentlerinden TEKİ bile kalıcı indirilemezse
  dosya delikli kalıp "tamamlandı" SANILMAZ — 5 deneme/segment, sonra motor zinciri devralır
  (test_84). Bu, film sitelerindeki "43 MB'ta tamamlandı" sahtesinin asıl kaynağıydı.
- **Relay Range-yok-sayar desteği:** CDN `Range` başlığını yok sayıp 200 dönerse relay pes etmez;
  gövdenin ilk N baytını çöpe atıp kaldığı yerden ekler (test_85).
- **Artık-dosya zehirlenmesi bitti (2.9.10 hatası):** relay başarısızlığında yarım dosya silinir,
  segment birleştirme de başta stream dosyasını truncate eder — hiçbir motor eski baytların
  ÜSTÜNE ekleme yapamaz (test_86).
- Segment birleştirme başında ses dosyası artığı da temizlenir (çift ses/bozuk mux engeli).
- **VOD HLS yerinde segment denemesi:** sıralı akışta ölü segment 5 kez yerinde yeniden denenir
  (test_87); CANLI/DVR kaydında ise tek ölü segment kaydı öldürmez, segment atlanıp yayın sürer.
- **Dürüst bitiş (sahte "tamamlandı" bitti):** baytlar tükendiği halde job tamamlanmadıysa köprü
  temiz kapanış yerine RST gönderir — IDM eksik dosyaya "İndirme tamamlandı" DEMEZ, hata raporlar.

## v2.9.10 Yenilikleri (Boş Bar + Yarıda Kesilme Kök-Neden Düzeltmeleri)

- **KRİTİK probe çökmesi düzeltildi:** 2.9.9'da `ytdlp_bin` değişkeni atanmadan önce okunuyordu
  (`UnboundLocalError`) → YouTube, bilibili, ok.ru ve abyss.to barları "İndirilebilir akış
  bulunamadı" diye BOŞ kalıyordu (film siteleri listede seçenek olduğu için etkilenmiyordu).
  Sıralama düzeltildi; test_81 bu regresyonu sonsuza dek kilitler.
- **KOPMA-DİRİLTME relay'i (`_run_single_url_relay`):** tek dosyalık medyada (film sitesi MP4'ü,
  ok.ru/vk relay'i) sunucu bağlantıyı ortada keserse (4 MB / 43 MB kesilmeleri) Range ile kaldığı
  bayttan yeniden bağlanır (8 deneme); Content-Length öğrenilince IDM'ye gerçek boyut bildirilir.
  test_82: ortada kesen sunucuda 300 KB'ın tam inmesini doğrular.
- **yt-dlp bulucu sertleşti:** daemon kısıtlı PATH ile başlasa bile `~/.local/bin`, `/usr/local/bin`
  ve interpreter dizinindeki kurulumlar görünür; PEP 668 (externally-managed) dağıtımlarında
  `--break-system-packages`, son çare `pipx` denenir.
- **Bar kendi kendini tazeler:** motor kurulurken/güncellenirken boş bar 30 sn'de bir otomatik
  yeniden tarar (6 kez) — kullanıcı "Yenile"ye basmak zorunda kalmaz.

## v2.9.9 Yenilikleri (Regression Avı + Teslimat Kemeri)

1. **Teslimat kemeri (`apply_delivery_guard`):** Referer/çerez taşıyan site yakalamaları (ok.ru `400 Bad Request`, film sitelerinde "4 MB'da kesilme") artık IDM'ye çıplak verilmez — köprü doğru başlıklarla TEK bağlantıdan relay yapar (hem kesilme biter hem anlık ilerleme akar). YouTube/googlevideo gibi açık CDN'ler DOĞRUDAN kalır (natif ilerleme korunur).
2. **yt-dlp otomatik GÜNCELLEME:** Site ekstrakları haftalık kırılır (YouTube/bilibili/ok.ru). Probe, bilinen sitede `-J` hata verirse 24 saatte bir `pip --upgrade yt-dlp` tetikler; bar "⏳ motor güncelleniyor, 1-2 dk içinde Yenile" ipucu gösterir.
3. **abyss zincir düşüşü:** abyss motoru (şifreli segment) susarsa işçi artık zincire düşer — yakalanan JW Player HLS manifesti devralır; 0-bayt yerine gerçek indirme.
4. **install.sh çalıştırılabilir** (`chmod +x`) olarak paketlenir.
5. `faridhafizh/video-downloader-ext` analizi: depo yalnızca **HLS AES-128** çözer; D-Smart seç-izle **Widevine CENC (senc)** olduğu için bu yaklaşımla AÇILAMAZ (lizans gerektirir). AES-128 tarafı zincirimizde (streamlink/yt-dlp) zaten destekli; DRM dürüst reddi duruşu korunur. D-Smart CANLI TV DVR/live hattına DOKUNULMADI.
6. Sürüm her yerde 2.9.9.

## v2.9.8 Yenilikleri (Etiket + Anlık İlerleme + 403/0-Bayt Panzehirleri)

1. **Çözünürlük etiketleri HER yerde:** MPD yakalamaları artık `parse_mpd_representations` ile 1080p/720p/… seçeneklerine ayrılır ("MPEG-DASH Video Akışı" belirsizliği bitti). bilibili için playurl'dan yükseklik etiketli DASH seçenekleri üretilir. vkvideo.ru/vk.ru/ok.ru yt-dlp zincirinde (progressive mp4 = doğal IDM ilerlemesi + etiket).
2. **CANLI mux (ffmpeg pipe→pipe):** DASH video+ses indirmelerinde baytlar mux edildikçe IDM'ye akar — `wait_mux` bekletmesi kalktı; IDM'de anlık hız/ilerleme GERÇEK, dosya sesli ve doğru. Segment modu ve tek-URL mux modu destekli.
3. **403 panzehiri:** abysscdn/iamcdn/hdslb/bilibili gibi Referer-şartlı CDN'ler IDM'ye çıplak `direct` verilmez; köprü (`stream_proxy`) doğru başlıklarla akıtır. page_hook, abyss sayfalarında 403-yemi çıplak mp4'leri artık emit etmez. Abyss segment indiricisi 403'te diğer CDN domainlerine döner ve dosyayı **sıralı büyüyerek** yazar (ilerleme görünür).
4. **justbeamit 0-bayt panzehiri:** IDM artık ilk **64 KB** P2P baytı gelmeden açılmaz (0-bayt kayıt imkânsız); blob devralma bastırması yalnızca 256 KB üstü gerçek akışta devreye girer, aksi halde eski güvenli yol çalışır.
5. Sürüm her yerde 2.9.8.

## v2.9.7 Yenilikleri (Köprü Asla Ölü Kalmaz)

1. **Köprü bekçisi (watchdog):** Companion her 20 sn'de bridge'i pingler; ulaşamazsa **Native Messaging ile daemon'u uyandırır** (`com.idmlinux.companion` → `status`), 1,2 sn bekleyip isteği **otomatik yeniden dener**. "Köprü servisine ulaşılamadı" hatası yerine bar "⚡ Köprü başlatılıyor…" deyip 4×2,5 sn kendi kendine yeniden dener.
2. **Probe çift vuruş:** Bridge kapalıyken açılan bar boş kalmaz — uyandırma sonrası probe bir kez daha koşar (bilibili kaynakları dahil).
3. **systemd sertleştirme:** servis birimi `Restart=always / RestartSec=2` — daemon herhangi bir sebeple ölürse (OOM dahil) systemd 2 sn'de yeniden kaldırır.
4. **Çökme karakutusu:** daemon beklenmedik çıkışta traceback'i `~/.cache/idm-linux/logs/daemon_crash.log`'a yazar; başlangıçta sürüm satırı loglanır. Bir daha "sessiz ölüm" yok.
5. Sürüm her yerde 2.9.7.

## v2.9.6 Yenilikleri (Kullanıcı Raporuyla Gelen Gerçek Hata Düzeltmeleri)

1. **Dil anahtarı hatası kökünden çözüldü:** Repoda İKİ `language/` klasörü vardı; installer kökteki (eski) kopyayı senkronluyordu, yeni anahtarlar (`set.abyss_*`) GUI'de ham key olarak görünüyordu. İki klasör birleştirildi/senkronlandı — abyss kutusu artık seçili dilde.
2. **bilibili "sessiz ölüm" düzeltildi:** page_hook tek bir IIFE olduğundan sonuna eklenen bilibili kazıyıcısı `emitStream`'i göremeyip ReferenceError ile SESSİZ ölüyordu. Köprü `window.__idmEmitStream` ile açıldı; ayrıca playurl artık **daemon tarafında çerezlerle** çağrılıyor (`biliCid` sayfa HTML'inden) — extension fetch'ine bağımlılık bitti.
3. **justbeamit gerçeği + anında IDM:** `/download?token=` ucunun çevrimiçiyken bile HTML/interstitial döndürdüğü canlı testle kanıtlandı (sahte kaynak bardan kaldırıldı). Yerine **WebRTC DataChannel sifonu**: P2P baytları alıcı sayfaya düştüğü anda daemon'a akıyor, IDM `/blobstream` büyüyen-dosya ucundan **beklemeden** indirmeye başlıyor; blob tamamlandığında akış kapanıyor. Yeşil Download'a bastığın an IDM açılır.
4. **yt-dlp otomatik kurulum:** ok.ru/vk.ru/bilibili zinciri yt-dlp eksikse arka planda `pip --user yt-dlp` ile kendini canlandırır (probe bloklanmaz).
5. Sürüm her yerde 2.9.6.

## v2.9.5 Yenilikleri (Canlı Ağ Doğrulaması Sonrası Sertleştirme)

1. **abyss "meta sniffing":** Oynatıcı artık JW Player + değişken info ucu kullanıyor (eski `abysscdn.com/info` 404). Companion, fetch/XHR yanıtlarındaki şifreli `{"media","md5_id"}` JSON'unu **yakalar**, daemon saf-Python AES-256-CTR ile çözer (`/api/abyss/meta`) — site domain rotasyonuna karşı dayanıklı. Segment/kripto motoru aynen geçerli.
2. **bilibili 412 panzehiri:** `view` API'si risk kontrolüne takılırsa companion önce ana sayfayla çerez ısıtıp bir kez daha dener; ayrıca `cid` doğrudan sayfa HTML'inden okunup probe'a taşınır (view hiç çalışmasa bile playurl çağrılır).
3. **justbeamit doğrulandı:** `eu.justbeamit.com:8443/download?token=<kod>` ucu canlı testte HTTP 200 döndü (gönderici çevrimdışıysa küçük hata gövdesi — IDM dürüstçe gösterir); eşleme hem barda hem dispatch'te aktif.
4. Sürüm her yerde 2.9.5.

## v2.9.4 Yenilikleri (Kaynak Bulma Devrimi)

1. **bilibili gerçekten çalışıyor:** İki katmanlı kaynak bulma — (a) sayfa içi `__playinfo__` kazıyıcı artık player geç açılsa bile 40×1,5 sn yeniden dener; (b) companion, `x/web-interface/view` + `x/player/playurl` API'lerini **sayfa çerezleriyle** çağırıp DASH video+ses baseUrl'lerini bara getirir (madebyhappy & CandyRGB bilibili-downloader repolarının yöntemi).
2. **justbeamit.com çözüldü:** `<kod>` sayfası görüldüğü anda IDM bar gerçek indirme ucunu (`eu.justbeamit.com:8443/download?token=<kod>`) kaynak olarak listeler; daemon dispatch'te de aynı eşlemeyi kurar. WebRTC blob beslemesi yedek olarak durur.
3. **Altyazılar IDM barında:** HLS `EXT-X-MEDIA SUBTITLES`, MPD `contentType="text"` ve sayfa `<track>` altyazıları "📝 Altyazı: …" olarak listelenir, tıklayınca IDM indirir.
4. **YouTube çok dilli sesler:** yt-dlp `-J` çıktısından tüm ses dilleri "🎙 Ses Dili: xx" ve manuel altyazılar "📝 Altyazı: xx" olarak bara gelir; tıkla-indir (ses rayı / srt dosyası).
5. **abyss.to / abyssplayer.com:** İki açık kaynak implementasyonun analiziyle protokol sıfırdan yazıldı — saf-Python AES-256-CTR (FIPS-197 testli), `abysscdn.com/info/{slug}` meta çözme, `md5(user:slug:md5)` anahtarı, çift-B64 segment token'ları, 8 işçili paralel segment indirme. GUI > Yakalama sayfasındaki kutuya **304358** yazıp EVET demeden kapalıdır (kod kaynakta 6 katman kodludur).
6. **Sekme izolasyonu:** Aynı sekmede sayfa değiştirdiğinizde (SPA pushState dahil) önceki sayfanın kaynakları bardan tamamen temizlenir — her sayfa yalnızca kendi kaynaklarını görür.
7. **Site listesi:** ok.ru, vk.ru/vk.com, dailymotion, vimeo, instagram, tiktok, facebook, rumble, nicovideo artık yt-dlp zincirinde.
8. Sürüm her yerde 2.9.4.

## v2.9.3 Yenilikleri (OOM-Panzehiri ve P2P Desteği)

1. **Bellek sızıntısı asla ve asla:**
   - HTTP köprü sunucusuna 45 sn soket zaman aşımı — IDM'nin açık keep-alive bağlantıları artık thread/RAM yığını yapamaz (çekirdek OOM-kill panzehiri).
   - daemon.log artık **2 MB'da döner** (tek .1 yedeği); log kuyruğu dosyanın tamamını değil son 128 KB'lık penceresini okur.
   - AuthProxyTicket'lar `created_at` taşıyor — bilet temizleyici gerçekten çalışır durumda.
2. **Eklenti pasif = tarayıcı indirir:** Sağ tık menüsünden "eklentiyi pasifleştir" seçildiğinde companion daemon'a `/api/ext-state {disabled:true}` bildirir; içerik betiği tıklama/gezinme dinleyicilerini kapatır, daemon tüm `/api/download` ve `/api/video/download` isteklerini reddeder — indirmeler %100 tarayıcının kendisinde gerçekleşir.
3. **bilibili:** `window.__playinfo__` DASH JSON'u sayfa betiğinden kazınır (video + ayrı ses yakalanır); bilibili/hdslb kaynakları Referer şartı için köprü üzerinden (`stream_proxy`) akıtılır; sistemde **yutto** (github.com/yutto-dev/yutto) kuruluysa motor zincirine `yt-dlp → yutto → streamlink` olarak katılır.
4. **justbeamit.com (WebRTC P2P):** 96 MB üstü blob'lar artık tek parça okunmaz — `blob.stream()` ile 384 KB'lık parçalar halinde `/api/blobfeed` üzerinden daemon'a beslenir, orada birleştirilip köprü biletiyle IDM'e verilir (Windows IDM'in bile yapamadığı P2P indirmeyi biz yapıyoruz).
5. **D-Smart GO canlı TV anında kaynak:** Sayfa canlı sınıfındaysa segment tahmini (600 HEAD fırtınası) ve manifest ağ yoklaması **atlanır** — IDM çubuğu yakalanan manifestlerden kaynakları anında listeler.
6. Sürüm her yerde 2.9.3.

## v2.9.2 Yenilikleri

1. **DRM GERÇEĞİ ve NET mesaj (0 bayt bitti):** D-Smart GO Seç-İzle VOD'larının Widevine+PlayReady (CENC `senc`) ile şifreli olduğu canlı kanıtlandı (MPD'de ContentProtection UUID'leri). DRM'li içerik artık indirme denemesi YAPMAZ: video bar'da "🔒 DRM KORUMALI — indirilemez" görünür, tıklanırsa ve segmente doğrudan tıklanırsa kullanıcıya açıklayıcı mesaj düşer (Windows IDM dahil hiçbir araç DRM çözemez; yasal+teknik engel).
2. **DRM'siz DASH'te KESİN indirme:** MPD `SegmentTimeline` ($Time$/$Number$, `r` tekrarları, initialization segmenti) birebir çözülür — video+ses ayrı seriler halinde inip ffmpeg ile birleşir; tahmin devri kapandı.
3. **Canlı/DVR seçeneği geri geldi:** yakalanan manifestte metin yoksa bile head çekilip `type="dynamic"` sınıflandırılır → video bar DVR/CANLI mod seçiciyi yeniden gösterir.
4. **bilibili / b23.tv / tubi.tv** bilinen yt-dlp sitelerine eklendi.
5. **KATI bellek koruması:** 10 dakikada bir koşulsuz süpürme (onay kuyruğu, probe kilitleri, proxy biletleri, süresi dolan ticket'lar, dispatch listesi, gc) + RSS eşiği 400MB'a indirildi.
6. **Arena teşhis sunucusu hazır:** `tools/remote_log_server.py` — daemon logları kullanıcının config'ine yazdığı URL'ye akar; PHP sürümü (`packaging/remote_log_server.php`) kendi domaini için duruyor.

---

## v2.9.1 Yenilikleri

1. **Canlı TV regresyonu giderildi + probe hızlandı:** manifest keşfi artık en fazla 3 aday × 1.5 sn (canlıda "Kaliteler hazırlanıyor" takılması bitti); canlı/DVR zinciri ve yedek motorlar korundu.
2. **IDM ↔ GUI duraklatma senkronu:** IDM'de indirmeyi duraklatıp/bırakınca bağlantı kopar; işçi 6 sn zarafetle bekler (resume ihtimali), dönen yoksa DURUR ve GUI'de "IDM'de duraklatıldı" görünür. Devam edince işçi yeniden akar.
3. **arena.ai 502 kesin çözüm (CORS aşıldı):** beslemeyi artık aynı origin'li sekmedeki content-script çeker (credentials include, CORS'suz) → parçalar daemon'a akar → IDM tek isteğinde dosyayı alır; arka plan fetch'i yedek kaldı.
4. **UZAK TEŞHİS LOG SİSTEMİ (kullanıcı isteği):** `packaging/remote_log_server.php` tek dosyalık sunucu — daemon 20 sn'de bir teşhis halkasını (dispatch/probe/assist/motor zinciri olayları + daemon.log kuyruğu) token'lı PHP'ye basar; GUI Doktor'da "📡 Uzak Log'a Gönder" anında gönderir; web'de "Logları İzle" 3 sn'de bir canlı yeniler. Kurulum: PHP'yi sitene at, TOKEN'i belirle, config.json'a `remote_log_url` + `remote_log_token` yaz.
5. **Segment 403 sertleştirmesi:** DASH parça isteklerine Origin + Sec-Fetch-* + Accept başlıkları eklendi (ercdn tarayıcı-benzeri istek ister).

---

## v2.9.0 Yenilikleri

1. **MOTOR ZİNCİRİ (0 bayt bitti):** bir motor başarısız olursa işçi otomatik olarak sıradakine geçer: segments → yt-dlp → streamlink → yerel HLS (backend'e göre sıralı). Kullanıcı kuralı uygulandı: streamlink deniyorsa yt-dlp, yt-dlp deniyorsa streamlink. Canlı/DVR istisnası korundu (yalnız streamlink).
2. **Gofile'de tarayıcı indirmesi KESİN bitti:** sayfanın programatik tetikleyicileri (window.open, location.href) sayfa dünyasında YUTULUR ve daemon'a devredilir; anchor tıklamaları + downloads.onCreated iptali ile üç katmanlı koruma.
3. **arena.ai auth diyaloğu bitti:** arena indirme tıklamaları/gezinmeleri tarayıcıda hiç açılmaz (401 Basic diyaloğu imkânsız); istek çerezlerle daemon proxy'sine gider, gerekirse tarayıcı-destekli besleme devreye girer.
4. **Bellek sızıntısı regressyonu giderildi:** manifest metinleri 8KB ile sınırlı, yakalama listesi 400→200 (tarayıcı tarafı ~200MB'lık birikme yolu kapandı).
5. **Eklenti sağ tık menüsüne PASİF/AKTİF:** ikon menüsünden tek tıkla yakalamayı durdur/başlat (bildirimle onaylanır).
6. **GUI daha da hızlandı:** ağır 3 sayfa (Projeler/Destek/Dil) pencere göründükten SONRA inşa edilir; splash pompası kısaltıldı. Açılış profili gui_timing.log'da kalmaya devam ediyor.

---

## v2.8.9 Yenilikleri

1. **GUI açılışı kökten hızlandı:** `cli panel` artık daemon/installer/crx gibi ağır modülleri açılışta import ETMEZ (PEP 562 tembel import); sistem tespiti arka plan iş parçacığına alındı; splash v2.8.7 semantiğine döndü (pencere görünmeden hemen önce kapanır). Açılış profili `log/logs/gui_timing.log`'a yazılır — kalan yavaş adım olursa tek bakışta bulunur. En büyük gizli maliyet de giderildi: `tkfont.families()` soğuk fontconfig'te 10-15 sn sürebiliyordu; artık font listesi 7 gün önbellekleniyor ve kurulumda `fc-list` ile önceden ısıtılıyor.
2. **D-Smart VOD için gerçek MPD yakalama:** oynatıcının kendi çektiği MPD manifesti (geçerli sid/token'la!) sayfa kancasıyla yakalanır ve TEK VİDEO/indirme yolunda ÖNCELİKLE kullanılır; türetme adaylarına `BASE.smil/manifest.mpd` de eklendi.
3. **Eklenti kurulum davranışı v2.8.7'ye döndürüldü:** yeniden başlatma onay penceresi KALDIRILDI; External Extensions policy'si ile kalıcı otomatik kurulum aynen devam eder.

---

## v2.8.8 Yenilikleri

1. **D-Smart GO "Seç-İzle" VOD artık iniyor (0 bayt bitti):** segment URL'sinden MPD manifest adresi otomatik türetilip doğrulanır (`BASE.smil/BASE.mpd?sid=...`); manifest bulunursa VOD **yt-dlp ile kökten** çekilir (ses+görüntü eksiksiz). Video bar'daki TEK VİDEO seçeneği de manifesti kullanır; manifest yoksa segment birleştirme motoru devrede kalır.
2. **Tarayıcının kendi indirme penceresi GÖRÜNMEZ:** IDM devraldığı anda (gofile vb.) companion, `chrome.downloads` üzerinden tarayıcının başlattığı aynı indirmeyi anında iptal+silme yapar; çift indirme ve çift pencere bitti.
3. **arena.ai / HttpOnly+Cloudflare korumalı dosyalar (502 bitti):** proxy 401/403'e takılırsa dosyayı **BIZZAT TARAYICI** kendi oturumuyla çeker ve 384KB'lık parçalar halinde daemon'a besler; IDM tek isteğinde kesintisiz dosyayı alır.
4. **GUI ANINDA açılıyor:** splash kapanıp pencere ÖNCE görünüyor, sayfalar görünürken inşa ediliyor; kurulum ayrıca bayt-kodu önceden derliyor (ilk açılış da hızlı).
5. **Eklenti kurulumdan sonra tek tıkla aktif:** tarayıcı kurulum sırasında çalışıyorsa oturum-korumalı yeniden başlatma önerilir (sekmeler geri gelir); External Extensions policy'si zaten kalıcı otomatik kurulumu sağlar.

---

## v2.8.7 Yenilikleri

1. **D-Smart GO donma/sızıntı zinciri KIRILDI (5 katman):** (a) page_hook'ta seri başına en fazla 4 segment bildirimi + `reported` Set tavanı; (b) content.js'te O(1) tekilleştirme ve segment başına mesaj yerine **1.2 sn'de bir TOPLU kayıt paketi**; (c) format önbelleği segment başına değil en fazla 8 sn'de bir düşürülür (probe/yt-dlp seli bitti); (d) background'ta sekme başına 300 kayıt tavanı; (e) daemon'da aynı sayfa için eşzamanlı probe'lar tek kilide bağlandı.
2. **Bütünlük koruması (bozuk dosya ASLA):** bir indirme "tamamlandı" işaretlenirken dosyanın başı HTML hata sayfası mı diye koklanır; auth-proxy uzak sunucu HTML döndürürse IDM'ye temiz **502** gider — gofile'daki 3.3KB bozuk dosya vakası imkânsızlaştı, onun yerine net hata + yeniden deneme.
3. **Gofile tam destek:** `wt` token'lı gerçek indirme bağlantısı sayfada yakalanır (tıklama + ağ kancası), çerez/referer/UA ile daemon'a gider; `gofile.io` her zaman auth-proxy'den geçer → IDM doğru baytları alır.
4. **Kararlılık:** HTML-uyanıcısı beklenen ikili dosyada (`zip/mp4/exe...`) tetiklenir; `.html/.m3u8/.mpd` gibi meşru metin çıktıları etkilenmez.

---

## v2.8.6 Yenilikleri

1. **Bellek sızıntısı panzehiri (3 katman):** (a) sayfa yakalama listesi sınırlı — segment sitelerinde binlerce parça URL'si birikip tarayıcıyı çökertemez (seri başına 4, toplam 300; content.js tarafında da 400 sert sınır); (b) daemon probe önbelleği 48 kayıtta FIFO ile sabit; (c) RSS nöbetçisi: daemon 600MB üstüne çıkarsa önbellekleri boşaltıp yaşlı biten job'ları atar.
2. **Duraklat/Devam (Resume):** köprü akışları artık `Range: bytes=N-` isteğini anlar — IDM duraklatıp dönünce kaldığı ofsetten devam eder, baştan başlamaz; yt-dlp backend'i `--continue` + `.part` izleme ile fragment seviyesinde devam eder.
3. **Magnet/torrent otomatik yakalama + KULLANICI ONAYI:** pano izleyicisi magnet veya .torrent bağlantısı yakalar; önce companion uzantı sayfada `confirm()` sorar (3 sn poll), tarayıcı kapalıysa zenity/yad/kdialog masaüstü onayı devreye girer; onayda indirme kusursuzca başlar. Sayfada `.torrent` dosyasına tıklamak da onaylı otomatik indirme başlatır.
4. **iframe pencereleri Wayland'da da ideal boyda:** Wayland'da `--window-size` yutulduğu için yardımcı pencere XWayland'da açılır (`--ozone-platform=x11` / `MOZ_ENABLE_WAYLAND=0`) → 1160×%72 yükseklik garantili uygulanır.

---

## v2.8.5 Yenilikleri

1. **DASH segment serileri TEK VİDEO:** Tarayıcı videoyu segment segment sunsa bile (D-Smart GO / ercdn `.dash` zincirleri gibi) video bar artık parça çöplüğü göstermez: seri algılanır, HEAD yoklamasıyla 0'dan sonuna kadar TÜM liste çıkarılır ve **herhangi bir segmente tıklansa bile** baştan sona tek dosya (ayrık ses serisi varsa ffmpeg ile sesli mux) olarak indirilir. 8 paralel bağlantı + sıralı yazım = IDM canlı ilerleme görür; mux gereken durumda IDM'ye ancak doğru dosya akar (`wait_mux`).
2. **`.dash` tanıma:** manifest/segment ayrımı dispatch'e eklendi; segment URL'leri artık auth-proxy ham indirmesine düşmez, doğrudan birleştirme motoruna gider.
3. **iframe destek pencereleri ideal boyda:** 1160×800 sabiti yerine ekranın %72'sini aşmayan, ortalanmış pencere; Wayland'de tarayıcı boyut yutarsa wmctrl/xdotool ile en iyi eforlu düzeltme.

---

## v2.8.4 Yenilikleri

1. **IDM Boyut + Kalan süre artık DOLU:** VOD HLS listelerinde tekdüze segment analiziyle KESİN toplam boyut hesaplanır (`estimate_hls_total_bytes`: ilk==orta segment → toplam = s·(n−1)+son) ve büyüyen akışa gerçek `Content-Length` declare edilir; yt-dlp formatları kesin `filesize` bildiriyorsa (YouTube mux çiftleri dahil) aynı şey geçerli. GUI/CLI izleyicisi de `X / Y MB` gösterir.
2. **DASH/MPD VOD → yt-dlp backend:** minik fragment MP4'ler arka planda TEK MP4'te birleşir (`--concurrent-fragments 8 --merge-output-format mp4 --no-part`), büyüyen dosya anında IDM'ye akar; MPD canlı/DVR streamlink'te kalır; progressive mp4'ler native IDM'de (max hız + gerçek metadata).
3. **Kopma/duraksama gardı:** yt-dlp `--retries 10 --fragment-retries 10 --retry-sleep linear=1:4 --socket-timeout 15`; probe `--extractor-args youtube:player_client=default,tv,mweb` + 20 sn timeout (YouTube kalite algısı daha sağlam).

---

## v2.8.3 Yenilikleri

1. **Anında açılış + Splash ekranı:** GUI artık 10-15 sn değil ~1-2 sn'de görünür; hazırlık boyunca sistem dilinde "Lütfen bekleyiniz.. Program birazdan açılacaktır.." splash'i gösterilir ve ana pencere gelmeden hemen önce kapanır. Kök nedenler: açılışta senkron `wine --version` alt süreci (8 sn'ye varan donma) ve senkron eski IDM taraması → ikisi de arka plana alındı (Wine sürümü önbellekten gelip canlı tazelenir).
2. **Sebepsiz DVR/Canlı bitti:** manifest sınıflandırıcı (`classify_manifest_live`) HLS/M3U8 ve DASH/MPD'nin CANLI mı VOD mu olduğunu gerçek verilere göre belirler; YouTube/film VOD'larına artık DVR-canlı muamelesi yapılmaz, video bar'daki mod seçici YALNIZCA gerçek canlı yayınlarda görünür (varsayılan VOD).
3. **Akıllı hata mesajları:** "DRM korumalı olabilir" yalnızca gerçek DRM sinyali varsa; yt-dlp eksikse kurulum önerisi; değilse Yenile önerisi gösterilir.

---

## v2.8.2 Yenilikleri

1. **DVR/Canlı HLS kayıtları TAMAMEN streamlink ile:** `streamlink "<url>" best --hls-live-restart -o "<dosya>"` (DVR) ve `streamlink "<url>" best -o "<dosya>"` (Canlı) semantiği arka planda çalışır; büyüyen dosya anında IDM'ye akıtılır (IDM ilerlemeyi gösterir). streamlink yoksa `apt/pacman/dnf/zypper/emerge/xbps/apk` ile otomatik kurulur; kurulamazsa yerel motor yedek kalır.
2. **Ses bozulması çözüldü:** streamlink backend'i MPEG-TS'i yeniden muxlamadan ham aktarır (konteyner `.ts`), böylece canlı/DVR kayıtlarında ses+video bozulmaz.
3. **Şifreli yayın desteği genişletildi:** AES-128 anahtar/segment başlıkları streamlink'e `--http-header` ile taşınır; **MPEG-DASH (.mpd)** URL'leri de artık otomatik olarak streamlink backend'ine yönlendirilir.
4. **Kayıt İzleyici temizlenebilir:** Karta "Bitenleri Temizle" ve "Tümünü Temizle" butonları eklendi (`/api/streams/clear`); tamamlanan kayıtlarda 📁 "klasörde göster" butonu var; liste son 8 kayıtla sınırlı.

---

## v2.8.1 Düzeltmeleri & Ekstra Entegrasyonlar

1. **`%86 name 'gecko_home_roots' is not defined` kurulum hatası GİDERİLDİ:** `installer.py` eksik `browsers` importları (`gecko_home_roots`, `open_folder_native`, `wine_path_to_unix`) eklendi; kurulum hattı uçtan uca duman testinden geçti.
2. **Geri-dönüş engelleyici AST regresyon testi (`test_42`):** tüm çekirdek modüller "tanımsız isim" taramasından geçer; bu sınıf hatalar bir daha asla release'e çıkmaz.
3. **Canlı Kayıt İzleyici:** Kontrol Merkezi Genel Bakış'a aktif Canlı/DVR kayıtlarını listeleyen ve tek tıkla durduran kart eklendi (`/api/streams` + `idm-linux streams`).
4. **Doktor 8 adıma çıktı:** Firefox imzalı XPI sideload doğrulaması ve Wine "Klasörü Aç" yönlendirmesi artık otomatik teşhis+onarım kapsamında.
5. **GitHub Actions Release Otomasyonu (`.github/workflows/release.yml`):** `v*` tag'inde Linux (tar.gz + .deb) ve macOS (Intel + Apple Silicon zip/pkg) paketleri CI'da derlenip test edilerek GitHub Release'e otomatik yüklenir.

---

## v2.8.0 Yenilikleri

1. **Firefox "Add-on could not be installed because it has not been verified" Hatasının Kökten Çözümü (`firefox_ext.py`):**
   - Firefox RELEASE imzasız XPI'yi kabul etmediği için kurulum stratejisi üç katmana ayrıldı: IDM paketinden çıkarılan **AMO imzalı resmi `idmmzcc3.xpi`** tüm Gecko profillerine sideload edilir (doğrulama duvarından geçer ve yakalamayı köprü WS'imize bağlar); imzasız companion XPI ise yalnızca ESR/Nightly/Developer gibi pref'e izin veren derlemelerde `user.js` (`xpinstall.signatures.required=false`, `extensions.autoDisableScopes=0`) + profil sideload ile kurulur; yazılabilirse distro sistem eklenti dizinine de bırakılır.
2. **Streamlink Semantikli Canlı / DVR HLS Kayıt Motoru (`hls_streamer.py`):**
   - `streamlink URL best --hls-live-restart -o dosya` davranışı: **DVR modu** playlist'in ilk segmentinden başlar, yeni segmentler geldikçe CANLI takip eder ve yayın bitene (`#EXT-X-ENDLIST`) veya kullanıcı durdurana dek sürer; **Canlı mod** ise canlı kenardan (son segment) başlayarak aynı şekilde takip eder. İstenen özel dosya adıyla kayıt yapılabilir (`--name`, GUI diyaloğu, video bar mod seçici).
   - Kaynak bittiğinde/kayıt tamamlandığında, IDM bağlantısı kopmuş olsa bile dosya otomatik olarak İndirilenler klasörüne arşivlenir; `idm-linux stream-stop <ticket>` ve `/api/stream/stop` ile canlı kayıt istenince sonlandırılır.
3. **Oynatma Listesi & Ana Akım Video Sitesi İndirici (YouTube, Dailymotion, Twitch, ...):**
   - Playlist URL'si yapıştırıldığında GUI toplu seçim diyaloğu açar (`yt-dlp --flat-playlist`), seçilen/tüm videolar tek tıkla IDM kuyruğuna girer; tekil video linkleri ve ham `.m3u8` adresleri de tüm giriş noktalarında (GUI, CLI `idm-linux add/playlist`, pano, eklenti) otomatik olarak video motoruna yönlendirilir.
4. **Wine "Klasörü Aç" → Linux Varsayılan Dosya Yöneticisi:**
   - `HKEY_CLASSES_ROOT\folder\shell\open\command` yönlendirmesi `user.reg` üzerine doğrudan (wine reg.exe çalıştırmadan, timeoutsuz) yazılır; IDM'nin açtığı her klasör artık `gio/xdg-open/dolphin/nautilus/thunar...` ile açılır. Wine içi linkler/mailto da `WineBrowser=xdg-open` ile yerli uygulamalara gider.
5. **Stream İndirmeleri Tarayıcı Kapanışından Bağımsız:**
   - Canlı/DVR işleri tamamen daemon tarafında çalışır; video penceresi/sekmeler kapansa bile kayıt sürer, tamamlanınca arşivlenir.
6. **GUI Cilası:** ilk açılıştaki beyaz sidebar flaşı kaldırıldı (pencere tema inşasına dek gizli + butonlar doğrudan temalı oluşturulur); sol sidebar'a köprü kartıyla aynı rozet tasarımında **canlı saat (24s SS:DD) + gg.MM.yyyy - gün adı** kartı eklendi (20 dilde gün adları); alt imza kartının ortasına tıklanabilir **semihsy54@gmail.com** (mailto) yerleştirildi; `(iframe)` bağımsız pencereleri artık tam ekran değil ideal **1160x800** boyutta açılıyor.

---

## v2.7.0 Yenilikleri

1. **Resmi IDM Sitesinden Dinamik En Güncel Sürüm Çekici (`resolve_latest_official_idm_release`):**
   - Sabit tek sürüme bağımlı kalmadan `internetdownloadmanager.com/download.html` üzerinden her zaman en güncel resmi `idman*build*.exe` paketini otomatik algılar, indirir, PE başlığından gerçek sürümü doğrular ve kurar.
2. **Gerçek Orijinal IDM Görev Çubuğu Simgesi (`pe_icon_extractor.py` + `idman.exe.desktop`):**
   - Kurulan gerçek `IDMan.exe` dosyasının PE `.rsrc` tablosundan orijinal `256×256`..`16×16` Tonec IDM ikonlarını saf Python ile çıkarır ve Wayland (`kwin_wayland` / `mutter`) + X11 görev çubuğunda **IDM'nin kendi orijinal simgesiyle** (Kontrol Merkezi simgesinden tamamen ayrı!) görünmesini sağlar (`kbuildsycoca6` / `gtk-update-icon-cache` yenilemeli).
3. **Sıfır-Timeout %100 Temiz Kaldırıcı (`purge_wine_prefix_idm_artifacts`):**
   - Wine-11.x soğuk başlatmalarında `wine reg delete` kaynaklı `TimeoutExpired` hatalarını tamamen ortadan kaldırarak doğrudan `.reg` dosyaları üzerinden milisaniyede sıfır kalıntılı kaldırma yapar.
4. **Bağımsız `<iframe>` Pencere Açıcı Düzeltmesi (`webview_modal.py`):**
   - 3. ve 4. destek yöntemlerindeki `(iframe)` bağlantılarına ve butonlarına tıklandığında kullanıcının varsayılan tarayıcısını `.desktop` üzerinden bulup çakışmasız `--app=` / `--new-window` bağımsız penceresinde ilgili web içeriğini anında `<iframe>` olarak gösterir.
5. **Tam Uyumlu (`Full Adaptive`) Buton Çubukları, Hizalı Kart Tasarımı, 20 Bayrak İkonu & Arapça/Farsça Harf Birleştirici:**
   - Küçük pencerelerde hiçbir butonun kesilmemesi için `create_adaptive_button_bar` eklendi; sol paneldeki köprü/sistem kutusu `BELGESELSEMO × ARENA.AI` rozetiyle ikiz kart tasarımına kavuşturuldu; alt imza kartı içerik alanındaki `YÖNTEM` kartlarıyla aynı sol-sağ genişlik hizasına alındı; `Dil Seçimi` ekranına 20 ülkenin gerçek PNG bayrak simgeleri (`flag_<code>.png`) ve X11 Tk için Arapça/Farsça harf birleştirme (`rtl_shaper.py`) eklendi.

---

## v2.6.0 Yenilikleri

1. **`language/*.txt` Tabanlı 20 Dilli Tam Arayüz Yerelleştirmesi (`🌐 Dil Seçimi`):**
   - Sol menüdeki **`🌐 Dil Seçimi`** sekmesi ve `language/` klasörü altındaki 20 ayrı UTF-8 `.txt` dil paketi (`tr`, `en`, `de`, `fr`, `ru`, `zh`, `ja`, `hi`, `ar`, `nl`, `fa`, `el`, `pt`, `vi`, `az`, `ky`, `it`, `id`, `ka`, `ro`) ile tüm GUI metinleri %100 yerelleştirilmiştir; dil seçildiği anda tüm sekmeler canlı olarak yenilenir.
2. **Otomatik İşletim Sistemi Dili Algılama & Gerçek Windows IDM Dil Senkronizasyonu:**
   - İlk açılışta sistem dili (`LC_ALL` / `LC_MESSAGES` / `LANG`) otomatik algılanır.
   - Wine içindeki IDM arayüzü, seçilen dili yerel olarak destekliyorsa kendi `.lng` paketine (`idm_tr.lng`, `idm_de.lng`, `idm_chn2.lng`, `idm_jp.lng`, `idm_gr.lng`, `idm_ge.lng`, `idm_ro.lng` vb.), yerel dil paketi bulunmuyorsa (`az`, `ky`) otomatik olarak **İngilizceye (`0x09`)** ayarlanır.
3. **Bağımsız Uygulama Penceresinde `<iframe>` Olarak Açılan NOWPayments Bağış & POS Terminali (`webview_modal.py`):**
   - Köprü servisi kapalı olsa dahi çalışan gömülü yerel iframe sunucusu ve kromsuz pencere başlatıcısı (`GTK WebKit2` / `QtWebEngine` / izole `Chromium --app` / kromsuz `Firefox`) sayesinde `https://nowpayments.io/donation/belgeselsemo55` ve `https://nowpayments.io/pos-terminal/belgeselsemo55` bağlantıları tarayıcı sekmesi olarak değil, **yeni bağımsız bir pencerede `<iframe>` olarak** açılır.
4. **4. Destek Yöntemi: BELGESELSEMO Premium Üyelik & Gerçek İki Yana Yaslı (`Justified`) Modern Tipografi:**
   - `Teşekkür Et & Destekle` sekmesine **`https://belgeselsemo.com.tr/premium-uyelik/`** (HD/Full HD tek ve seri belgeseller, indirme özelliği, reklamsız izleme, Watch Party, koleksiyonlar ve 500 TL+ hayır kurumu bağış makbuzu paylaşanlara ücretsiz Premium sosyal sorumluluk hediyesi) 4. yöntem olarak eklenmiştir.
   - `Diğer Projeler` ve `Teşekkür Et & Destekle` sekmeleri piksel hassasiyetli **tam iki yana yaslı (`text justify align`)** metin motoru ve X11 üzerinde bozulmayan RGBA PNG rozet ikonlarıyla modernize edilmiştir.

---

## v2.5.0 Yenilikleri

1. **Gerçek IDM ile `.torrent` Dosyası ve `magnet:?` Bağlantısı İndirme Köprüsü (`v2.5.0`):**
   - Saf Python Bencode (`.torrent`) ve `magnet:?xt=urn:btih:...` çözümleyicisi + `aria2c` sıralı (`--stream-piece-selector=inorder`) BitTorrent/DHT/PEX/WebSeed motoru sayesinde `.torrent` dosyaları ve `magnet:?` linkleri canlı HTTP akışına (`/torrent/<ticket>/<dosya>`) dönüştürülür ve **doğrudan gerçek Windows IDM (`IDMan.exe`)** üzerinden indirilir!
   - JSON-RPC `bitfield` ardışık doğrulanmış parça sayacı sayesinde IDM'ye **yalnızca SHA-1 doğrulaması tamamlanmış baytlar** aktarılır; çok dosyalı paket torrent'ler ise otomatik canlı `.tar` akışı olarak indirilir.
   - Hem tarayıcıda (`magnet:?` tıklamaları, sağ tık menüsü, `.torrent` yakalama, eklenti popup), hem Kontrol Paneli'nde (`🧲 .torrent Seç...` ve hızlı yapıştırma), hem de terminalde (`idm-linux add dosya.torrent` / `idm-linux add "magnet:?..."`) tam desteklidir.
2. **Pencere Başlık Çubuğu & Görev Çubuğu (Wayland / X11 Taskbar) İkonu (`v2.5.0`):**
   - `tk.Tk(className="idm-linux-panel")` + çoklu boyutta (`128x128`..`16x16`) yüksek netlikli PNG `iconphoto(True, ...)` + `StartupWMClass=idm-linux-panel` ve `hicolor` ikon kurulumu ile pencere başlığındaki ve görev çubuğundaki varsayılan X.org ikonu tamamen kaldırılarak orijinal IDM-Linux simgesi atanmıştır.
3. **`🌟 Diğer Projeler` Vitrin Sekmesi & Saf Python Karekod (`QR`) Üretici (`v2.5.0`):**
   - Sol menüdeki **Diğer Projeler** sekmesinde `BELGESELSEMO` (`belgeselsemo.com.tr`), `MATPAY` (`matpay.blogspot.com`), `BELGESELSEMO Learn & Explore` YouTube (`@belgeselsemo55`), `BELGESELSEMOFLIX` (Linux/Windows/macOS), Google Play'deki 5 resmi Android uygulaması ve yakında yayınlanacak **`BELGESELSEMO RETRO EMULATOR`** (MOPHUN • J2ME • NES • SNES • GAMEBOY) ile **`BELGESELSEMO ECONOMY`** projeleri ikonları, istatistikleri, açıklamaları, linkleri ve büyütülebilir **Karekodları** ile yer alır.
4. **`❤️ Teşekkür Et & Destekle` Sekmesi + Canlı NOWPayments Bağış Widget'ı (`v2.5.0`):**
   - Sol menüdeki **Teşekkür Et & Destekle** sekmesinde 3 destek yöntemi (YouTube & Mobil Uygulama Yorum/Puan, Doğaya/Hayvanlara/İnsanlara Manevi İyilik Halkası, NOWPayments POS Terminali & Karekod + `/support` üzerinde sıfır arayüz bozulmasıyla çalışan canlı `346×623` NOWPayments Bağış Widget'ı) sunulur.

---

## v2.4.0 Yenilikleri & Çözülen Kritik Noktalar

1. **Oturumlu / Kimlik Doğrulamalı Siteler (`arena.ai`, HuggingFace, GitHub vb.) ve `blob:` İndirmelerinde %100 Otomatik Çerez & Kimlik Köprüsü (`v2.4.0`):**
   - Eklenti (`webRequest.onBeforeSendHeaders` `extraHeaders` + `cookies.getAll` + CHIPS `partitionKey`) VE yerel açık tarayıcı SQLite çerez çözücüsü (`browser_cookies.py` — `Brave-Origin-Nightly`, `Brave`, `Chrome`, `Chromium`, `Firefox` `v10`/`v11` `HttpOnly` çerez desteği!) birlikte çalışarak oturum çerezlerini ve `Authorization` başlıklarını otomatik tamamlar.
   - Kimlik doğrulamalı / Cloudflare korumalı / `blob:` indirmeleri yerel `HTTP 206 Range`-destekli TLS 1.3 köprüsü (`/proxy/<ticket>/<filename>`) üzerinden gerçek dosya adıyla IDM'ye aktarılır; IDM **asla `"Authorization Required — Kullanıcı adınızı ve şifrenizi yazın"` hatası vermez**.
2. **`/welcome` Tek Tıkla Otomatik Eklenti Yükleme (`Brave-Origin-Nightly` & Chrome 142+ Dahil) ve Engellenmeyen `.ZIP` Paketi (`v2.4.0`):**
   - `Brave-Origin-Nightly`, `Brave-Nightly`, `Brave-Beta`, `Thorium`, `Ungoogled-Chromium` ve tüm özel `~/.config` Chromium profilleri dinamik olarak keşfedilir; sarmalayıcı betiklerin arkasındaki gerçek ELF süreçleri `/proc/<pid>` üzerinden bulunup açık sekmeler korunarak (`--restore-last-session` + `--disable-features=DisableLoadExtensionCommandLineSwitch,ExtensionDisableUnsupportedDeveloper` + `--load-extension` ve Chrome 142+ için CDP Pipe `Extensions.loadUnpacked`) otomatik etkinleştirilir.
   - Tarayıcıların engellediği ve `CRX_REQUIRED_PROOF_MISSING` hatası veren `.crx` indirmesi yerine **engellenmeyen ve sürükle-bırak ile sıfır hatayla kurulan `.ZIP` paketi** sunulur.
3. **"IDM, tarayıcı ve sistem ilişkilendirmesi için gerekli olan 5 dosyayı bulamıyor" Uyarısı Kökten Giderildi:**
   - `IDMan.exe`'nin bütünlük denetçisinin (`sub_45F3B0`) kontrol ettiği `IDMGrHlp.exe`, `idmbrbtn.dll`, `IDMNetMon.dll`, `IDMNetMon64.dll` ve `idmbrbtn64.dll` (ve diğer Windows hook ikilileri) 1536 baytlık güvenli, penceresiz sessiz PE32/PE32+ stub ikilileriyle korunur (`missing = 0`).

1. **Film Sitelerinde `%0` Beklemesi Kaldırıldı — İlk Saniyeden İtibaren Gerçek Zamanlı Canlı IDM İlerlemesi:**
   - **Sayfa İçi Derin `#EXTM3U` & Gizli `.txt` / JSON Manifest Yakalayıcı (`page_hook.js`):** `fullhdfilmizlesene` ve benzeri film sitelerindeki gömülü player'ların (`FirePlayer`, `Vidmoly`, `Atom`, `Moly`, `CloseLoad`, `Rapidrame`) güvenlik duvarlarından gizlemek için `.txt`, `.json` veya `POST getVideo` ile çektiği tüm `#EXTM3U` akışları sayfa dünyasında (`world: "MAIN"`) anında yakalanır ve doğrudan 16-kanallı yerel HLS motoruna aktarılır.
   - **16-Kanallı Yerel HLS + Ayrık Türkçe Ses Birleştirici + Anlık Paket Flush (`0.15 sn`):** Segmentler 16 paralel iş parçacığıyla çekilir, sahte PNG/JPEG başlıkları ve AES-128 şifresi soyulur, Master Playlist içindeki ayrık Türkçe Dublaj ses akışları (`#EXT-X-MEDIA:TYPE=AUDIO`) otomatik birleştirilir ve `-frag_duration 250000 -flush_packets 1` + ham ikili HTTP akışı (`TCP_NODELAY`, `Transfer-Encoding: chunked` olmadan!) ile her 64 KB indikçe **anında IDM ekranına yansır**.
   - **Yedek `yt-dlp` Motorunda da Bekletme Kaldırıldı:** Eski bekleten dosya modu kaldırılarak `yt-dlp -o -` canlı boru hattına geçildi; hiçbir sitede video bitene kadar `%0` beklemesi yaşanmaz.
2. **Sıfır Kalıntılı ("Hiç Kurulmamış Gibi") Tam Kaldırma (Uninstaller) Motoru:**
   - Tüm çalışan `IDMan.exe`, `IEMonitor.exe` ve köprü süreçleri sonlandırılır, `systemd` servisi devre dışı bırakılır.
   - Wine içerisindeki tüm IDM klasörleri (`Program Files`, `AppData/Roaming/IDM`, `AppData/Local/IDM`, `DMCache`, `Start Menu`, `Temp`) ve **Wine Kayıt Defteri (`user.reg` / `system.reg` içindeki tüm `DownloadManager`, `IDMan.*` ve COM GUID anahtarları)** diğer Wine programlarınıza zarar verilmeden cerrahi olarak silinir.
   - Tüm tarayıcı köprüleri, `*-flags.conf` eklenti bayrakları, uygulama/masaüstü kısayolları, `~/.local/share/idm-linux`, `~/.config/idm-linux`, `~/.cache/idm-linux` ve **tüm log dosyaları** tek bir iz bile bırakmadan temizlenir (salt-okuma işlemleri artık klasörleri tekrar oluşturmaz).

---

## Kurulum & Güncelleme

```bash
tar -xzf idm-linux-v2.6.0.tar.gz
cd idm-linux
bash install.sh
```
