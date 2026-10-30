# 🚀 IDM LINUX — GitHub Yayınlama & Sürüm Rehberi (BELGESELSEMO)

Bu rehber; depoyu oluşturmayı, yetkilendirmeyi, push etmeyi ve sürüm (release) yayınlamayı adım adım anlatır.

---

## 1) Depoyu GitHub'da Oluştur

1. https://github.com/new adresine git.
2. **Repository name:** `IDM-LINUX`
   > ⚠️ GitHub depo adlarında **boşluk ve parantez kullanılamaz** (harf, rakam, `-`, `_`, `.` serbest). "IDM LINUX (BELGESELSEMO)" ifadesini **Description** alanına yaz:
   > `IDM LINUX (BELGESELSEMO) — Internet Download Manager'ın tüm gücü Linux'ta`
3. **Public** seç, ve **"Add a README" / ".gitignore" / "license" seçeneklerinin HİÇBİRİNİ işaretleme** (bizim dosyalarımızla çakışır).
4. **Create repository** → depo boş olarak oluşturulur.

---

## 2) Yetkilendirme — İki Seçenek

### Seçenek A: Bana Personal Access Token (PAT) ver → ben pushlarım

1. GitHub → sağ üstten profil → **Settings** → sol menü en altta **Developer settings**
2. **Personal access tokens → Fine-grained tokens** → **Generate new token**
3. Ayarlar:
   - **Token name:** `idm-linux-push`
   - **Expiration:** kısa süre (7 gün önerilir)
   - **Repository access:** *Only select repositories* → `IDM-LINUX` seç
   - **Permissions → Repository permissions → Contents:** `Read and write`
   - (Diğer izinler kapalı kalsın)
4. **Generate token** → çıkan kodu bana bu sohbette gönder.
5. Ben: kaynak birleştirme + sürüm numaralarını 1.0.0'a çevirme + push + (istediğin an) `v1.0.0` etiketiyle taslak release'i hazırlarım.
6. İş bitince **token'ı revoke et** (Settings → Developer settings → Fine-grained tokens → Delete).

> 🔒 Güvenlik: Token yalnızca bu tek depoya, sadece "Contents" yetkisiyle ve kısa süreli verilir. Sohbette paylaştıktan sonra bile iş bitiminde iptal etmen en güvenlisidir.

### Seçenek B: Kendin pushlarsın

```bash
# ZIP'i açtıktan sonra klasörün içinde:
cd IDM-LINUX

git remote add origin https://github.com/<KULLANICI_ADIN>/IDM-LINUX.git
git push -u origin main
# GitHub kullanıcı adı + şifre yerine Personal Access Token girmen istenir.
```

---

## 3) CI & Sürüm Akışı

- **v1.0.0** paketleri, *"IDM-LINUX-1.0.0 Building (İnşa Ediliyor)"* iş akışının **nihai çalıştırmasıyla** derlendi ve doğrudan GitHub Release'e eklendi.
- Geçici iş akışları (build/tests) kaldırıldı; Actions geçmişinde yalnızca bu nihai çalıştırma korunur.
- **Yeni sürüm (örn. 1.0.1) çıkarken** paketleri kendi makinen derleyip release'e elle ekleyebilirsin:

```bash
# AppImage
bash packaging/appimage/build.sh
# DEB
bash packaging/deb/build.sh
# RPM
bash packaging/rpm/build.sh
# Arch (zst) — makepkg gerektirir
cd packaging/arch && makepkg -f --nodeps && mv *.pkg.tar.zst ../../
```

- Ardından **Releases → Draft a new release** ile yeni etiketi (örn. `v1.0.1`) oluştur, derlenen 4 paketi sürükle-bırak ekle ve publish et.

---

## 4) Sürüm Numaraları

- Uygulama **ve** tarayıcı eklentisi sürüm numaraları **1.0.0** olarak ayarlanır.
- `packaging/vars.sh` içindeki `VERSION="1.0.0"` değeri, paket dosya adlarını (örn. `idm-linux_1.0.0_all.deb`) besler.
- Yeni sürümde: kod (`src/idm_linux/__init__.py`, `pyproject.toml`, eklenti manifest'leri) + `packaging/vars.sh` içindeki `VERSION` değerini güncelle, paketleri derleyip `vX.Y.Z` etiketiyle yeni release'e ekle.

---

## 5) Kontrol Listesi (v1.0.0 — tamamlandı ✅)

- [x] Repo oluşturuldu; kaynak birleştirildi, sürüm numaraları 1.0.0 yapıldı
- [x] `git push -u origin main` tamam
- [x] `v1.0.0` etiketi pushlandı → *"IDM-LINUX-1.0.0 Building (İnşa Ediliyor)"* çalıştı
- [x] 4 paket release'e eklendi (AppImage / deb / rpm / zst) ve yayından önce doğrulandı
- [x] Release **v1.0.0** yayınlandı 🎉
- [x] Geçici iş akışları ve eski run'lar temizlendi; Actions'ta yalnızca nihai çalıştırma kaldı
