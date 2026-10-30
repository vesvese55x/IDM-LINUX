#!/bin/bash
# IDM LINUX başlatıcı.
# Paket (deb/rpm/pacman), AppImage ve kaynak ağaçta çalışacak şekilde yol çözer.
set -u

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

APP_HOME=""
if [ -n "${APPDIR:-}" ] && [ -d "$APPDIR/usr/share/idm-linux" ]; then
  APP_HOME="$APPDIR/usr/share/idm-linux"          # AppImage
elif [ -d "/opt/idm-linux" ]; then
  APP_HOME="/opt/idm-linux"                        # deb / rpm / pacman paketi
elif [ -f "$SCRIPT_DIR/../main.py" ] || [ -f "$SCRIPT_DIR/../app.py" ] || [ -f "$SCRIPT_DIR/../idm_linux.py" ] || [ -x "$SCRIPT_DIR/../bin/idm-linux" ]; then
  APP_HOME="$(cd "$SCRIPT_DIR/.." && pwd)"         # kaynaktan çalıştırma (packaging/ altından)
fi

if [ -z "$APP_HOME" ]; then
  echo "IDM LINUX: uygulama dizini bulunamadı (beklenen: /opt/idm-linux)." >&2
  exit 1
fi
cd "$APP_HOME"

# install.sh davranışı (paket kurulumlarının ilk açılış sözü):
# Argümansız çağrıda grafik oturum varsa "Kurulum & Kontrol Merkezi"ni (GUI
# sihirbazı) aç — IDM'nin Wine'a kurulumu, CRX3/native messaging kaydı ve
# eksik araçların kurulumunu sihirbaz tamamlar. Ekransız ortamda (SSH vb.)
# durum raporunu bas. Açıkça verilen argümanlar hiç dokunulmadan iletilir.
if [ "$#" -eq 0 ]; then
  if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
    set -- install
  else
    set -- status
  fi
fi

# 1) Kabuk başlatıcıları dene (yeni düzende src/idm_linux/bin/idm-linux, eski düzende bin/idm-linux)
for c in idm-linux.sh run.sh start.sh idm-linux src/idm_linux/bin/idm-linux bin/idm-linux; do
  if [ -x "$c" ]; then
    exec "./$c" "$@"
  fi
done

# 2) Python giriş noktalarını dene
for c in main.py app.py idm_linux.py gui.py; do
  if [ -f "$c" ]; then
    exec python3 "$c" "$@"
  fi
done

echo "IDM LINUX: giriş noktası bulunamadı ($APP_HOME)." >&2
exit 1
