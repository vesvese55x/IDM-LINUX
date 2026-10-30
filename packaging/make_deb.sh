#!/usr/bin/env bash
# IDM-Linux .deb paketi üretici (dağıtım-bağımsız: Debian/Ubuntu/Mint)
set -euo pipefail
cd "$(dirname "$0")/.."
VER=$(python3 -c "import sys;sys.path.insert(0,'src');import idm_linux;print(idm_linux.__version__)")
ROOT="build/deb/idm-linux_${VER}_all"
rm -rf build/deb && mkdir -p "$ROOT/DEBIAN" "$ROOT/opt/idm-linux" "$ROOT/usr/bin" "$ROOT/usr/share/applications"
cp -r src extension language install.sh README.md pyproject.toml "$ROOT/opt/idm-linux/"
cat > "$ROOT/usr/bin/idm-linux" <<'EOF'
#!/bin/sh
export PYTHONPATH="/opt/idm-linux/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m idm_linux.cli "$@"
EOF
chmod +x "$ROOT/usr/bin/idm-linux"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: idm-linux
Version: ${VER}
Architecture: all
Maintainer: BELGESELSEMO <semihsy54@gmail.com>
Depends: python3, wine, ffmpeg, aria2
Section: net
Priority: optional
Description: Evrensel IDM (Internet Download Manager) Linux entegrasyon paketi
 Gercek Windows IDM'yi Wine uzerinde calistiran, 20 dilli kontrol merkezi,
 canli/DVR HLS kayit, torrent/magnet koprusu ve tarayici entegrasyonlari.
EOF
cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
/opt/idm-linux/install.sh --non-interactive || true
EOF
chmod +x "$ROOT/DEBIAN/postinst"
dpkg-deb --build "$ROOT" .
echo "DEB hazır: idm-linux_${VER}_all.deb"
