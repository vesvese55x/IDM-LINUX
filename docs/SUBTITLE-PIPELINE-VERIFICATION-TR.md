# Harici altyazı düzeltmesi — doğrulananlar ve açık kalanlar

## Sonuç özeti

**Genel bir video sitesinde altyazı algılama → IDM barından seçim → native IDM ile gerçek indirme doğrulandı.** Bu, YouTube/OK/VK altyazılarında canlı başarı elde edildiği anlamına gelmez.

- Sürüm **1.0.0** korundu. GitHub'a push/release yapılmadı.
- İptal edilen tarayıcı/VPN medya aktarımı yeniden eklenmedi.
- Tarayıcı, VPN ve Wine yeniden başlatılmadı. Yalnız kendi companion eklentisi teknik yenileme için kapatılıp açıldı; kullanıcıya yönelik pasif modda bırakılmadı.
- Mevcut dosyalar, filmler, Wine prefix ve önceki teslimler korunuyor.

## Düzeltmeler

- Harici `<track>`, iç içe/stringify edilmiş oynatıcı JSON'u, göreli altyazı adresleri ve iframe kaynak bağlamı için yakalama genişletildi.
- OK/VK ve diğer yt-dlp çıkarıcılarının verdiği gerçek altyazı adresleri ortak doğrulama/indirme yoluna bağlandı. Desteklenen açık VK video adresleri için sıkı URL eşleme eklendi.
- Altyazı doğrulaması dört arka plan işçisi, sınırlı kuyruk ve bağlama duyarlı kısa ömürlü önbellekle ayrıldı; kontrol edilen/erişilemeyen satırlar için durum alanları eklendi.
- JSON3/SRV konuşma altyazıları WebVTT'ye dönüştürülüyor. Thumbnail/storyboard VTT dosyaları konuşma altyazısı olarak kabul edilmiyor.
- HLS altyazı göreli adres çözümü; DASH XML ad alanı, iç içe BaseURL ve dil okuması düzeltildi. Desteklenmeyen parçalı MP4 metin rayları düz VTT diye sunulmuyor.
- Eksik veya HTML dönen HLS altyazı segmenti, geçersiz anahtar ve boş konuşma çıktısı başarı sayılmıyor. Altyazı hatası video indirmesine düşmek yerine HTTP 422 döndürüyor.
- Canlı testte bulunan çift dil satırı düzeltildi: harici `<track>` için ayrıca bağımsız TextTrack kopyası üretilmiyor. Gömülü raylarda milisaniyeler korunuyor; sınırı aşan cue listesi sessizce kesilmiyor.
- Chromium ve Firefox kaynakları ile paketli CRX/ZIP/XPI yeniden eşitlendi; sürüm ve Chromium eklenti kimliği korunarak imza/paket içeriği doğrulandı.

## Testler

| Kontrol | Sonuç |
|---|---|
| Tam Python unittest | **277 test, başarılı — 32,911 sn** |
| Yeni altyazı pipeline alt kümesi | **23 test, başarılı — 0,891 sn** |
| Gerçek JS kaynaklarını çalıştıran Node tarayıcı harness'i | **Başarılı** |
| CRX imzası, kimliği, sürümü ve arşiv/kaynak eşitliği | **Başarılı** |
| Uzak makineye dağıtım | **60 hedef, SHA eşitliği; uzak pipeline testleri başarılı** |
| Son daemon durumu | **ok / media_ready / idm_running; aktif iş 0** |

Tam suite'in ilk tekrarında HTTP Range muhasebesi testindeki thread yarışı görüldü: istemci Content-Length kadar veriyi okuduktan hemen sonra sunucunun sayaç güncellemesi henüz tamamlanmamış olabiliyordu. Test, gerçek muhasebe işleminin tamamlanmasını sınırlı süreli Event ile bekleyecek şekilde düzeltildi; üretim sayacı değiştirilmedi. Son tam suite yukarıdaki gibi başarılıdır.

## Gerçek native altyazı indirmesi

Test sayfası: https://iandevlin.github.io/mdn/video-player-with-captions/

1. Son dağıtım ve kendi eklentisinin yenilenmesinden sonra bar **English, Deutsch, Español** olmak üzere **üç ayrı altyazı satırı** gösterdi; önceki altı satırlık çift liste giderildi.
2. English satırına tarayıcı barından tıklandı. Native IDM'nin dosya bilgisi penceresi ve ardından **Download complete** sonucu görüldü.
3. `QA-MDN-English-final.vtt` gerçek indirme klasöründe **966 bayt** olarak bulundu.
4. Her iki dosyadaki **14 cue'nun bütün zamanları ve konuşma metinleri eşit**. Kaynağın 965 bayt olmasına karşılık çıktıdaki fark yalnız sondaki boşluk/yeni satır normalleştirmesidir; byte-byte aynılık iddia edilmiyor.
5. SHA-256: `82da8127b0620ec080d99b99f1954783389482add071a896c3251bb88a42c600`.

Kanıtlar: `mdn-native-subtitle-final-proof.json`, `mdn-native-subtitle-download-complete.png`, `mdn-subtitle-three-language-menu.png`.

Ayrı olumsuz testte kasıtlı eksik altyazı isteği **HTTP 422 / api_ok=false** döndürdü; native indirme çağrısı sayısı değişmedi. Boş IDM indirme penceresi açılmadı.

## Henüz doğrulanmayanlar

- **YouTube altyazısı: canlı native başarı yok.** Normal oynatıcıda video kullanılamıyor hatası, companion gerçek passthrough durumundayken de ana videoda buffering görüldü. Bu, tek başına kesin kök neden teşhisi değildir. Pasif durum sonradan geri alındı.
- **OK.ru altyazısı: canlı başarı yok.** Seçilen açık örnekte 5 video formatı, 1 ses ve 0 altyazı bulundu. Önceki OK video indirme başarısı altyazı kanıtı değildir.
- **VK altyazısı/video: canlı başarı yok.** Denenen açık örnek format döndürmedi.
- Her site/biçim için evrensel uyumluluk, sıfır hata veya tam performans garantisi verilmiyor. Bu turda kapsamlı yük/uzun süre dayanıklılık testi yapılmadı. DRM, giriş, CAPTCHA veya lisans engeli aşılmadı.
- Windows ilk eklenti X/RestartBridge düzeltmesi, GitHub runner üzerinde gerçek Windows testi, dört Linux paketinin gerçek kurulum/çalıştırma kapıları ve toplam 22 konunun tamamı bitmiş değildir.
- Mevcut 1.0.0 release'ine EXE + BAT + AppImage/DEB/RPM/ZST yayınlama kapıları ve son onay hâlâ bekliyor.

## Dosyalar

- `subtitle-general-unittest.log`
- `subtitle-new-pipeline-tests.log`
- `subtitle-browser-capture-tests.log`
- `subtitle-pipeline-remote-deploy.log`
- `mdn-native-subtitle-final-proof.json`
- `mdn-native-subtitle-download-complete.png`
- Son kaynak checkpoint'i için ayrıca ZIP ve Git bundle hazırlanmıştır; bunlar kuruluma hazır yeni Linux/Windows release paketi değildir.
