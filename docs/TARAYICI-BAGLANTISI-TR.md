# İki bağlantı modu — tarayıcı/VPN/oturum aktarımı

Sürüm ve etiket değişmez: **1.0.0**. Bu belge yeni indirme taşımasını açıklar; tüm siteler, bütün VPN yapılandırmaları veya diğer proje görevleri tamamlandı anlamına gelmez.

## Kullanım

1. Tarayıcıyı normal şekilde açın; gereken VPN ve site oturumunu kendiniz etkin tutun.
2. İzinli videoyu oynatın ve IDM video çubuğunun kalite menüsünü açın.
3. **Bağlantı → Doğrudan:** eski davranış, varsayılan seçim. Normal bağlantı yeterliyse bunu kullanın.
4. **Bağlantı → Tarayıcı bağlantısıyla — VPN/oturum:** dosya/segmentler seçilen kaynak sekme veya oynatıcı çerçevesindeki gerçek `fetch` isteğiyle alınır. Arka plan eklentisi yalnız yerel köprüye iletir.
5. **Çıkış kontrolü (api.ipify.org)** varsayılan açıktır. Bu üçüncü taraf hizmet tarayıcının çıkış IP'sini görür. IP bellekte SHA-256 ile özetlenir; Python köprüsüne yalnız özet gider. Kontrol engellenirse istek reddedilir. Kutuyu bilerek kapatmak mümkündür; o durumda çıkış değişikliği denetimi yapılmaz.
6. Kaynak sekmesini/çerçevesini açık bırakın. IDM'nin bu modda localhost adresini görmesi normaldir; gerçek medya baytları tarayıcıdan yerel köprüye gelir.

Eski içerik betiği/arka plan/köprü karışımı güvenli biçimde reddedilir: tarayıcı modu ayrı `IDM_DOWNLOAD_VIDEO_BROWSER` mesajı kullanır. Eski arka plan bu isteği normal indirmeye çeviremez. Aynı sürüm numarasıyla güncellenen eklenti arka planı henüz yenilenmemişse açık hata alınabilir; eski indirme yoluna otomatik dönüş yapılmaz.

## Desteklenen aktarım yolları

- Yakalanmış/çözülmüş HLS adresi: ana ve alt manifestler, video/ses segmentleri, standart AES-128 anahtarları aynı çerçeveden alınır.
- Önceden çözülmüş ayrı HTTP video + ses dosyaları: FFmpeg yalnız yerel, yetenek anahtarlı range köprüsünden okur.
- Progressive HTTP dosyası: yerel köprü iki MiB'lık kaynak aralıklarıyla aktarır. Büyük dosyada sunucunun uygun `206 Content-Range` cevabı ve tarayıcının bu başlığı okuyabilmesi gerekir.

Tarayıcının CORS, CSP, site oturumu, üçüncü taraf çerez ve diğer ağ kısıtları geçerlidir. Çerezli istek CORS yüzünden başarısız olursa **aynı çerçevede** çerezsiz tekrar denenebilir; Python/arka plan ağından veya farklı çerçeveden medya isteği yapılmaz. Medya yönlendirmeleri otomatik takip edilmez. Bu nedenle bazı sitede çalışan oynatıcının dosyası bu modda yine indirilemeyebilir.

Henüz desteklenmeyenler: çözümlenmemiş DASH/MPD manifesti veya segment dizisi, altyazı aktarımı, Abyss çözücü yolu ve DRM korumalı içerik. Bunlar açık hata verir. DRM, giriş, CAPTCHA veya ücret engeli aşılmaz.

Bu seçenek **indirme işinin taşımasına** uygulanır. Mevcut otomatik kalite/kaynak keşfi mekanizmasını veya diğer uygulamaların bütün internet trafiğini bir VPN tüneline dönüştürmez.

## Kesilme, duraklatma ve güvenlik sınırı

Tarayıcı işi ayrı Python dalında çalışır; yt-dlp/Streamlink/normal Internet motoruna fallback yoktur. FFmpeg'in HLS yolunda ağ protokolleri kapalıdır. Ayrı dosya mux yolunda yalnız yerel HTTP girdileri ve medya demuxer'ları kabul edilir; içeriğe gömülü ikinci bir manifest harici URL açtıramaz.

Sekme/çerçeve kapanması veya gezinmesi, eklentinin yakalama özelliğinin pasifleştirilmesi, başarısız aktarım, iptal veya çıkış özeti değişmesi yetkiyi iptal eder. Yanıt gelmeyen istemcinin kiralama süresi **15 saniyedir**. İptal edilen tarayıcı yetkisi otomatik yeniden açılmaz. Kesilen/duraklatılan tarayıcı işi için aynı eski yerel URL ile otomatik devam garantisi yoktur; yeni tarayıcı indirme oturumu başlatmak gerekebilir. Doğrudan modun mevcut devam davranışı korunur.

**Bu bir VPN kill-switch'i değildir.** IP kontrolü yaklaşık iki saniye önbelleklidir ve istek öncesi/sonrası yapılır. VPN düşerken sağlayıcının normal ağa dönmesi, kontrol ile istek arasındaki zaman aralığı, bölünmüş tünel ve alan adına göre PAC/proxy kuralları yüzünden her kaçak kusursuz engellenemez. IP hizmetinin çıkışı ile medya alan adının çıkışı aynı olmak zorunda değildir. Sıfır normal-ağ çıkışı gerekiyorsa VPN'in sistem düzeyinde firewall/kill-switch özelliğini kullanın.

Kaynak URL'lerde yerel/özel **literal IP** ve localhost reddi vardır; bu bir DNS yeniden bağlama önleyici sistem güvenlik duvarı iddiası değildir. Yerel uç noktalar rastgele yetenek anahtarlarıyla ve kayıt yapan eklentinin Origin'iyle sınırlandırılır.

## Kaynak ve kaynak tüketimi

- Aynı anda en fazla iki tarayıcı indirme işi; arka planda toplam dört gerçek frame-fetch.
- Python isteği başına sekiz MiB; en fazla 32 bekleyen istek; broker içindeki toplam bytearray kuyruğu en fazla 64 MiB.
- JSON/base64 parçaları 393.216 ham baytla sınırlı; ofset ve metadata sırası doğrulanır.
- HLS video ve ses paralelliği ikişer; tamamlanmış future tamponlarının da sınırlı kalması için dört girdilik pencere/batch kullanılır.
- 64 MiB yalnız broker kuyruğu sınırıdır; Python, FFmpeg, tarayıcı ve tamamlanmış future tamponları birlikte daha fazla RAM kullanabilir. Bu sürüm bütün VPN/uzun canlı yayın kombinasyonlarıyla bellek stres sertifikası almış sayılmaz.

## Doğrulama

- 139 mevcut ana test; 26 medya kurulumu; 23 kurtarma; 17 güvenli yakalama; 6 altyazı; 1 gerçek FFmpeg mux; 17 HLS bütünlüğü; 19 yeni taşıma testi: PASS.
- Gerçek Chromium + gerçek FFmpeg, tamamen denetimli çevrimdışı ağ fixture'ları: **8 PASS**.
- HLS: 124.374 bayt / 4,040272 saniye, 5 tarayıcı isteği; Python upstream çağrısı yasakken başarı.
- Master + standart AES-128 anahtarı + ayrı ses: 124.366 bayt / 12 tarayıcı isteği.
- Progressive: 4.658.000 bayt / 3 tarayıcı range isteği / kaynak SHA-256 eşit.
- Önceden çözülmüş ayrı video + ses: 124.393 bayt, her iki track ffprobe ile doğrulandı.
- Çıkış değişmesi, gezinme, ağ/CORS başarısızlığı ve FFmpeg'i harici URL'ye yönlendirmeye çalışan iç içe manifest: güvenli ret.
- Chromium/Firefox kaynak eşitliği, manifest/CRX imza/ID/sürüm ve paket-kaynak eşitliği doğrulandı. Firefox gerçek çalışma testi yapılmadı.

Gerçek Chromium fixture testi gerçek Urban veya başka marka VPN üzerinden ticari site testi değildir. Kullanıcının uzak masaüstünde tarayıcı kapalı bulundu; tarayıcı, VPN veya Wine yeniden başlatılmadan dosyalar ve yalnız IDM köprüsü güncellendi. Yeni modun o profilde bir site/VPN ile uçtan uca kullanımı ayrıca doğrulanmalıdır.
