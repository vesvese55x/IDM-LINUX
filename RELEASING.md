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

- **Her push / PR:** `.github/workflows/build.yml` çalışır → AppImage, deb, rpm, zst derlenir → **Actions → (run) → Artifacts** (30 gün saklanır). Bu paketler release'e **eklenmez**.
- **Sürüm yayınlamak istediğinde** (örn. 1.0.0):

```bash
git tag v1.0.0
git push origin v1.0.0
```

- Etiket pushlanınca 4 paket otomatik olarak **taslak (draft) GitHub Release**'e eklenir.
- Yayın kararı sende: **Releases → v1.0.0 (draft) → düzenle → Publish release**.
- "Buildleri ben söylersem release'e ekleyelim" isteğin için akış tam olarak budur: etiketi ne zaman pushlarsak paketler o an release'e düşer, sen de publish edersin.

---

## 4) Sürüm Numaraları

- Uygulama **ve** tarayıcı eklentisi sürüm numaraları **1.0.0** olarak ayarlanır.
- Workflow dosyasındaki `VERSION: "1.0.0"` değeri, paket dosya adlarını (örn. `idm-linux_1.0.0_all.deb`) ve release etiketini besler.
- Yeni sürümde: kodda + workflow'daki `VERSION` değerini güncelle, `vX.Y.Z` etiketi pushla.

---

## 5) Kontrol Listesi (ilk yayın)

- [ ] Boş repo oluşturuldu (README/gitignore/license seçilmeden)
- [ ] Kaynak zip birleştirildi, sürüm numaraları 1.0.0 yapıldı
- [ ] `git push -u origin main` tamam
- [ ] Actions sekmesinde "Build & Release" yeşil ✔
- [ ] Artifacts altında 4 paket görünüyor
- [ ] `v1.0.0` etiketi pushlandı → taslak release oluştu
- [ ] Release Publish edildi 🎉
