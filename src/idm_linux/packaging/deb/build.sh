#!/usr/bin/env bash
# DEB derleme (Debian/Ubuntu). Çıktı: dist/idm-linux_<sürüm>_all.deb
# Yeni depo düzeni: betik src/idm_linux/packaging/deb/ altındadır; kök üç üst dizin.
#
# v3.14.2 DÜZELTMESİ: dpkg-deb -Zxz — GitHub Actions runner'ının yeni dpkg'si
# data.tar'ı VARSAYILAN zstd sıkıştırıyor; eski dpkg'ler (Debian 10/11, Ubuntu
# 20.04/22.04) ve birçok GUI kurucu (gdebi/GNOME Software/Synaptic eski sürümler)
# data.tar.zst açamayıp "geçersiz veya bozuk paket / okunamıyor" hatası veriyor.
# xz her dpkg sürümünde (Debian 6+) okunur — evrensel uyumluluk için xz ZORUNLU.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
source src/idm_linux/packaging/vars.sh

# Kaynak kontrolü: uygulama giriş noktası yoksa anlamlı hata ver
SRC_ENTRY=""
for c in src/idm_linux/bin/idm-linux bin/idm-linux idm-linux.sh run.sh start.sh idm-linux main.py app.py idm_linux.py gui.py; do
  if [ -f "$c" ] || [ -x "$c" ]; then SRC_ENTRY="$c"; break; fi
done
if [ -z "$SRC_ENTRY" ]; then
  echo "HATA: Uygulama kaynak ağacı bulunamadı (src/idm_linux/bin/idm-linux ...)" >&2
  echo "       Depo kökünde src/idm_linux ağacı ile tekrar deneyin." >&2
  exit 1
fi
echo "Kaynak bulundu: $SRC_ENTRY"

STAGE="build/deb/${APP_ID}"
rm -rf build/deb
mkdir -p "${STAGE}/DEBIAN" "${STAGE}/opt/${APP_ID}" "${STAGE}/usr/bin" \
         "${STAGE}/usr/share/applications" "${STAGE}/usr/share/icons/hicolor/256x256/apps" \
         "${STAGE}/usr/share/doc/${APP_ID}" dist

# Uygulama ağacı (yeni düzen: src/idm_linux altında HER ŞEY — packaging/tests/docs hariç)
tar -cf - --exclude=./.git --exclude=./.github --exclude=./build --exclude=./dist \
  --exclude='__pycache__' --exclude='*.pyc' \
  --exclude=./src/idm_linux/tests --exclude=./src/idm_linux/docs --exclude=./src/idm_linux/packaging \
  . | tar -xf - -C "${STAGE}/opt/${APP_ID}"

install -m 0755 src/idm_linux/packaging/launcher.sh "${STAGE}/usr/bin/${APP_ID}"
# Büyük/küçük harf kolaylığı: IDM-LINUX ve IDM-Linux da çalışsın
ln -sf "${APP_ID}" "${STAGE}/usr/bin/IDM-LINUX"
ln -sf "${APP_ID}" "${STAGE}/usr/bin/IDM-Linux"
install -m 0644 src/idm_linux/packaging/idm-linux.desktop "${STAGE}/usr/share/applications/${APP_ID}.desktop"
install -m 0644 LICENSE "${STAGE}/usr/share/doc/${APP_ID}/copyright"
rm -rf "${STAGE}/opt/${APP_ID}/src/idm_linux/packaging" "${STAGE}/opt/${APP_ID}/packaging"

# İkon: paket içindeki gerçek marka ikonu; yoksa üret
ICON=""
for c in src/idm_linux/assets/idm-linux-icon.png icons/idm-linux.png icons/icon.png icon.png idm-linux.png; do
  if [ -f "$c" ]; then ICON="$c"; break; fi
done
if [ -z "$ICON" ]; then
  python3 -c "import PIL" 2>/dev/null || sudo apt-get install -y -qq python3-pil
  python3 packaging/icon_gen.py "build/${APP_ID}.png"
  ICON="build/${APP_ID}.png"
fi
install -m 0644 "$ICON" "${STAGE}/usr/share/icons/hicolor/256x256/apps/${APP_ID}.png"

cat > "${STAGE}/DEBIAN/control" <<EOF
Package: ${APP_ID}
Version: ${VERSION}
Section: net
Priority: optional
Architecture: all
Depends: wine, python3, python3-tk
Recommends: yt-dlp, ffmpeg, aria2, xdg-utils
Installed-Size: $(du -sk "${STAGE}/opt/${APP_ID}" | cut -f1)
Maintainer: ${MAINTAINER}
Homepage: ${HOMEPAGE}
Description: IDM LINUX (BELGESELSEMO) — Internet Download Manager'ı Linux'ta tam işlevsel kullanma katmanı
 IDM'nin tüm gücünü Linux'a taşır: tarayıcı entegrasyonu, dosya barındırma
 sitesi desteği, gömülü torrent motoru (DHT), canlı yayın/DVR kaydı, deneme
 süresi sıfırlama ve Sistem Doktoru teşhis paneli.
 Menüden ilk açılışta Kurulum & Kontrol Merkezi (GUI sihirbazı) başlar.
EOF

cat > "${STAGE}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
# gdebi / GNOME Software / Synaptic / dpkg -i TAM UYUMLU postinst:
# etkileşimsiz, soru sormaz ve ASLA kurulumu başarısızlığa uğratmaz.
export DEBIAN_FRONTEND=noninteractive
(command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q) || true
(command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -qf /usr/share/icons/hicolor) || true
(command -v update-mime-database >/dev/null 2>&1 && update-mime-database /usr/share/mime) || true
ldconfig 2>/dev/null || true
echo ""
echo "  =============================================================="
echo "   IDM LINUX kuruldu (BELGESELSEMO)"
echo "  =============================================================="
echo "   Sonraki adım: Uygulama menüsünden 'IDM LINUX' girdisini açın."
echo "   Kurulum & Kontrol Merkezi (GUI sihirbazı) açılır; IDM'yi Wine"
echo "   ortamına kurar, tarayıcı CRX3/Native Messaging kaydını ve eksik"
echo "   araçları (yt-dlp/ffmpeg/aria2c) tamamlar."
echo "   Terminal: idm-linux install | status | doctor | panel"
echo "  =============================================================="
echo ""
exit 0
EOF
chmod 0755 "${STAGE}/DEBIAN/postinst"

# -Zxz: eski dpkg/GUI kurucuların data.tar.zst açamaması kökten çözülür (evrensel uyumluluk)
dpkg-deb --build --root-owner-group -Zxz "${STAGE}" "dist/${APP_ID}_${VERSION}_all.deb"
echo "OK: dist/${APP_ID}_${VERSION}_all.deb"
