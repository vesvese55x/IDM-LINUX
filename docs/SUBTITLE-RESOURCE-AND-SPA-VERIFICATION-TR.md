# Altyazı kaynak sınırları, iptal ve SPA düzeltmesi

## Bu turun durumu

**Bu değişiklikler yerel kaynakta tamamlandı ve test edildi; uzak masaüstüne henüz dağıtılmadı.** Önceki `f8da2df` sürümündeki MDN native IDM indirme kanıtı korunuyor. Yeni değişikliklerin YouTube/OK/VK üzerinde canlı başarı kazandığı iddia edilmiyor.

Sürüm **1.0.0** korundu. Push, release, VPN müdahalesi veya iptal edilen tarayıcı/VPN medya aktarımını geri ekleme yapılmadı. Önceki testin geçici SSH anahtarı yeniden kullanılmadı.

## Bulunan ve düzeltilen riskler

### 1. Sıkıştırılmış altyazının sınırdan önce bellekte açılması

Önceki kod gövdeyi gzip/deflate ile açtıktan sonra boyut denetliyordu. Yeni altyazıya özel çözücü, açılan veriyi de sınırlar; genel video/HLS medya çözücüsü değiştirilmedi.

- Aktarılan ve açılan tek altyazı gövdesi için **8 MiB** sınırı.
- gzip, birleştirilmiş gzip üyeleri, zlib ve raw-deflate destekleniyor.
- Eksik gzip gövdesi tam dosya başarısı sayılmıyor. Probe, yalnız tanıma amacıyla eksik sıkıştırılmış öneki okuyabiliyor.
- HTTP `Content-Length` ile alınan bayt sayısı uyuşmuyorsa dosya tamamlanmış sayılmıyor.
- Küçük parçalarla sürekli veri gönderen sunucu her okumada toplam süreyi sıfırlayamıyor; tek yanıt bütçesi kontrol ediliyor.

### 2. HLS altyazılarının tüm segmentlerini birden kuyruğa sokması

Önceki uygulama her segment için Future oluşturuyordu. Artık:

- En fazla **8 daemon işçisi** ve işçi sayısıyla sınırlı kayan istek penceresi var.
- Segmentler paralel getirilse de çıktı oynatma listesi sırasıyla birleştiriliyor.
- Birleştirilen altyazı **8 MiB**, segment sayısı **20.000** ile sınırlı.
- Master listeden alt listeye geçerken **aynı toplam süre bütçesi** korunuyor; varsayılan hazırlama bütçesi **18 saniye**.
- Segmentlerden biri başarısızsa kalan bütün liste indirilmek üzere kuyruğa doldurulmuyor; kısmi altyazı başarı diye verilmiyor.
- İptal/zaman aşımında çağıran taraf executor kapanmasını bekleyerek takılmıyor. Başlamış bir OS/DNS işlemi zorla öldürülmüş sayılmıyor; daemon işçisi, OS çağrısı döndüğünde kapanır. Bu ayrım önemlidir.

### 3. Başarısız hazırlıktan sonra işin devam etmesi

Altyazı ön kontrolü **20 saniyede** tamamlanmazsa, çıktı boşsa veya iş başarısızsa iş durduruluyor ve aktif başarı bekleyen iş olarak bırakılmıyor. Altyazı iptal edildikten sonra geç gelen çıktı yeni bir hazır indirme gibi yayımlanmıyor. Hazırlanmış başarılı dosyanın işi ise durdurulmuyor.

Bekleme süreleri sistem duvar saati yerine monotonic saatle ölçülüyor.

### 4. YouTube altyazı ön getirmelerinin sınırsız paralelliği

- 25 altyazıyı aynı anda istemek yerine en fazla **4 eşzamanlı istek**.
- İstek başına **8 saniye**, gövde için **2.000.000 bayt** sınırı.
- Sayfa değişiminde ve pasifleştirmede yalnız eklentinin kendi altyazı ön getirmeleri iptal ediliyor; oynatıcı/video ve kullanıcının indirmeleri iptal edilmiyor.
- Kaynak farklı bir video kimliğine aitse eski player yanıtı yeni videoya uygulanmıyor.
- Aşırı uzun yanıtı kesip geçerli dosyaymış gibi kaydetme kaldırıldı.

### 5. SPA veya pasif/aktif geçişinden sonra eski metnin karışması

Genel fetch/XHR altyazı yakalamasında istek anındaki sayfa ve bağlam nesli saklanıyor. Sayfa değiştikten veya pasif/aktif geçişinden sonra tamamlanan eski yanıt yeni bara metin gönderemiyor. İncelenen fetch yanıtının kopyasında okuma bütçesi var; kopyayı iptal etmek sayfanın asıl isteğini iptal etmiyor.

Chromium ve Firefox aynalandı; CRX/ZIP/XPI yeniden üretildi.

## Doğrulama

| Kontrol | Sonuç |
|---|---|
| Tam Python unittest | **296 test, başarılı — 33,323 sn** |
| Yeni kaynak/süre/iptal testleri, tam suite'in alt kümesi | **19 test, başarılı — 0,674 sn** |
| Gerçek JS kaynaklarını çalıştıran Node harness | **Başarılı** |
| CRX imzası/kimliği, 1.0.0 sürümü, paket/kaynak eşitliği | **Başarılı** |
| Whitespace kontrolü | **Başarılı** |

Yeni kontroller gzip genişleme sınırı, gzip/deflate okuması, gerçek yerel HTTP sıkıştırma ve eksik Content-Length, trickle süresi, HLS segment sırası, toplam çıktı sınırı, iptal ve durdurulan hazırlık işini kapsıyor. Node testleri 25 rayda dört eşzamanlı istek, zaman aşımında kuyruk slotlarının bırakılması, eski video yanıtını reddetme ve pasif/aktif geçişinden sonra eski gövdenin atılmasını doğruluyor.

Loglar:
- `subtitle-hardening-resource-tests.log`
- `subtitle-hardening-browser-tests.log`
- `subtitle-hardening-full-unittest.log`

## Açık kalanlar

- Bu yeni kaynak checkpoint'inin uzak makinede kurulması ve native IDM ile tekrar kontrolü yapılmadı.
- YouTube/OK/VK için gerçek altyazı bulunan uygun erişilebilir örneklerde canlı indirme kanıtı hâlâ yok.
- Sınırları aşan içerik sessizce kesilmez; açık hata ile reddedilir. Her uzun içerik, eski karakter kodlaması ve altyazı biçimi için evrensel uyumluluk iddiası yoktur.
- DNS/OS çağrılarını süreç dışından zorla kesme veya bütün eşzamanlı işler için küresel bellek garantisi uygulanmış değildir.
- Windows ilk eklenti X/RestartBridge, GitHub Windows runner ve dört Linux paketinin gerçek kurulum/çalıştırma kapıları açık. Bunlar yerel unit testlerden geçmiş sayılmıyor.
- Mevcut release'in aynı 1.0.0 sürümünde EXE + BAT + dört Linux asset ile güncellenmesi henüz yapılmadı.
