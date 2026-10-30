#!/usr/bin/env bash
# RPM derleme (Fedora/openSUSE vb., noarch). Çıktı: dist/idm-linux-<sürüm>-1.noarch.rpm
set -euo pipefail
cd "$(dirname "$0")/../.."
source packaging/vars.sh
command -v rpmbuild >/dev/null 2>&1 || { sudo apt-get update -qq && sudo apt-get install -y -qq rpm; }

# Kaynak kontrolü: uygulama giriş noktası yoksa anlamlı hata ver
SRC_ENTRY=""
for c in idm-linux.sh run.sh start.sh idm-linux bin/idm-linux main.py app.py idm_linux.py gui.py; do
  if [ -f "$c" ] || [ -x "$c" ]; then SRC_ENTRY="$c"; break; fi
done
if [ -z "$SRC_ENTRY" ]; then
  echo "HATA: Uygulama kaynak ağacı bulunamadı (main.py/app.py/idm_linux.py/gui.py/idm-linux.sh...)." >&2
  echo "       Kaynak ağacı repo köküne koyup tekrar deneyin." >&2
  exit 1
fi
echo "Kaynak bulundu: $SRC_ENTRY"

TOP="build/rpmbuild"
rm -rf build/rpmbuild
mkdir -p "$TOP/BUILD" "$TOP/RPMS" "$TOP/SOURCES" "$TOP/SPECS" "$TOP/SRPMS" dist

# Kaynak ağacını paketle
tar -czf "$TOP/SOURCES/${APP_ID}.tar.gz" \
  --exclude=./.git --exclude=./.github --exclude=./build --exclude=./dist --exclude=./tests --exclude=./docs .

# İkon
ICON=""
for c in icons/idm-linux.png icons/icon.png icon.png idm-linux.png; do
  if [ -f "$c" ]; then ICON="$c"; break; fi
done
if [ -z "$ICON" ]; then
  python3 -c "import PIL" 2>/dev/null || sudo apt-get install -y -qq python3-pil
  python3 packaging/icon_gen.py "$TOP/SOURCES/${APP_ID}.png"
else
  cp "$ICON" "$TOP/SOURCES/${APP_ID}.png"
fi

cat > "$TOP/SPECS/${APP_ID}.spec" <<EOF
Name:           ${APP_ID}
Version:        ${VERSION}
Release:        1%{?dist}
Summary:        IDM LINUX (BELGESELSEMO) — Internet Download Manager Linux entegrasyonu
BuildArch:      noarch
License:        Proprietary — see LICENSE
URL:            ${HOMEPAGE}
Source0:        ${APP_ID}.tar.gz
Source1:        ${APP_ID}.png
Requires:       wine, python3

%description
IDM LINUX, Internet Download Manager'in tum gucunu Linux'a tasiyan
entegrasyon katmanidir: tarayici entegrasyonu, gofile destegi, gomulu
torrent motoru (DHT), canli yayin/DVR kaydi, deneme suresi sifirlama ve
Sistem Doktoru teshis paneli. (BELGESELSEMO)

%prep
%setup -q -c

%build

%install
mkdir -p %{buildroot}/opt/%{name}
cp -a %{_builddir}/%{name}-%{version}/. %{buildroot}/opt/%{name}/
install -Dm0755 %{buildroot}/opt/%{name}/packaging/launcher.sh %{buildroot}/usr/bin/%{name}
install -Dm0644 %{buildroot}/opt/%{name}/packaging/idm-linux.desktop %{buildroot}/usr/share/applications/%{name}.desktop
install -Dm0644 %{SOURCE1} %{buildroot}/usr/share/icons/hicolor/256x256/apps/%{name}.png
rm -rf %{buildroot}/opt/%{name}/packaging
rm -f  %{buildroot}/opt/%{name}/.gitignore

%files
/opt/%{name}
/usr/bin/%{name}
/usr/share/applications/%{name}.desktop
/usr/share/icons/hicolor/256x256/apps/%{name}.png
%doc LICENSE
EOF

rpmbuild -bb --define "_topdir $(pwd)/$TOP" "$TOP/SPECS/${APP_ID}.spec"
cp "$TOP"/RPMS/*/*.rpm dist/
echo "OK: dist/ — $(ls dist)"
