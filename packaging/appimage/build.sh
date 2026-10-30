#!/usr/bin/env bash
# AppImage derleme (x86_64). Çıktı: dist/IDM-LINUX-<sürüm>-x86_64.AppImage
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

APPDIR="build/AppDir"
rm -rf build
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/idm-linux" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps" dist

# Uygulama ağacını AppDir içine kopyala
tar -cf - --exclude=./.git --exclude=./.github --exclude=./build --exclude=./dist . \
  | tar -xf - -C "$APPDIR/usr/share/idm-linux"
install -m 0755 packaging/launcher.sh "$APPDIR/usr/bin/${APP_ID}"
rm -rf "$APPDIR/usr/share/idm-linux/packaging"

# Masaüstü girdisi
cat > "$APPDIR/usr/share/applications/${APP_ID}.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=${VERSION}
Name=${DISPLAY_NAME}
GenericName=Download Manager
GenericName[tr]=İndirme Yöneticisi
Comment=Internet Download Manager Linux integration (BELGESELSEMO)
Comment[tr]=Internet Download Manager Linux entegrasyonu (BELGESELSEMO)
Exec=${APP_ID}
TryExec=${APP_ID}
Icon=${APP_ID}
Terminal=false
Categories=Network;FileTransfer;
StartupNotify=true
EOF
cp "$APPDIR/usr/share/applications/${APP_ID}.desktop" "$APPDIR/${APP_ID}.desktop"

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
install -m 0644 "$ICON" "$APPDIR/${APP_ID}.png"
install -m 0644 "$ICON" "$APPDIR/usr/share/icons/hicolor/256x256/apps/${APP_ID}.png"
ln -sf "${APP_ID}.png" "$APPDIR/.DirIcon"

# AppRun
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
export APPDIR="$HERE"
exec "$HERE/usr/bin/idm-linux" "$@"
EOF
chmod 0755 "$APPDIR/AppRun"

# appimagetool
TOOL="build/appimagetool-x86_64.AppImage"
if [ ! -f "$TOOL" ]; then
  wget -q -O "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
fi
chmod +x "$TOOL"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "dist/IDM-LINUX-${VERSION}-x86_64.AppImage"

echo "OK: dist/IDM-LINUX-${VERSION}-x86_64.AppImage"
