#!/usr/bin/env bash
# DEB derleme (Debian/Ubuntu). Çıktı: dist/idm-linux_<sürüm>_all.deb
set -euo pipefail
cd "$(dirname "$0")/../.."
source packaging/vars.sh

# Kaynak kontrolü: uygulama giriş noktası yoksa anlamlı hata ver
SRC_ENTRY=""
for c in idm-linux.sh run.sh start.sh idm-linux main.py app.py idm_linux.py gui.py; do
  if [ -f "$c" ] || [ -x "$c" ]; then SRC_ENTRY="$c"; break; fi
done
if [ -z "$SRC_ENTRY" ]; then
  echo "HATA: Uygulama kaynak ağacı bulunamadı (main.py/app.py/idm_linux.py/gui.py/idm-linux.sh...)." >&2
  echo "       Kaynak ağacı repo köküne koyup tekrar deneyin." >&2
  exit 1
fi
echo "Kaynak bulundu: $SRC_ENTRY"

STAGE="build/deb/${APP_ID}"
rm -rf build/deb
mkdir -p "${STAGE}/DEBIAN" "${STAGE}/opt/${APP_ID}" "${STAGE}/usr/bin" \
         "${STAGE}/usr/share/applications" "${STAGE}/usr/share/icons/hicolor/256x256/apps" \
         "${STAGE}/usr/share/doc/${APP_ID}" dist

# Uygulama ağacı
tar -cf - --exclude=./.git --exclude=./.github --exclude=./build --exclude=./dist . \
  | tar -xf - -C "${STAGE}/opt/${APP_ID}"

install -m 0755 packaging/launcher.sh "${STAGE}/usr/bin/${APP_ID}"
install -m 0644 packaging/idm-linux.desktop "${STAGE}/usr/share/applications/${APP_ID}.desktop"
install -m 0644 LICENSE "${STAGE}/usr/share/doc/${APP_ID}/copyright"
rm -rf "${STAGE}/opt/${APP_ID}/packaging"

# İkon: repodaki gerçek ikon varsa onu kullan, yoksa marka ikonu üret
ICON=""
for c in icons/idm-linux.png icons/icon.png icon.png idm-linux.png; do
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
Depends: wine, python3
Recommends: xdg-utils
Installed-Size: $(du -sk "${STAGE}/opt/${APP_ID}" | cut -f1)
Maintainer: ${MAINTAINER}
Homepage: ${HOMEPAGE}
Description: IDM LINUX (BELGESELSEMO) — Internet Download Manager'ı Linux'ta tam işlevsel kullanma katmanı
 IDM'nin tüm gücünü Linux'a taşır: tarayıcı entegrasyonu, gofile desteği,
 gömülü torrent motoru (DHT), canlı yayın/DVR kaydı, deneme süresi
 sıfırlama ve Sistem Doktoru teşhis paneli.
EOF

cat > "${STAGE}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q || true
exit 0
EOF
chmod 0755 "${STAGE}/DEBIAN/postinst"

dpkg-deb --build --root-owner-group "${STAGE}" "dist/${APP_ID}_${VERSION}_all.deb"
echo "OK: dist/${APP_ID}_${VERSION}_all.deb"
