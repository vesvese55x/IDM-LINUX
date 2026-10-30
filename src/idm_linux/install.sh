#!/usr/bin/env bash
# =============================================================================
# IDM-Linux v2.0 Evrensel Başlatıcı & Kurulum Sihirbazı
# (Grafik masaüstünde Modern GUI Kurulum & Kontrol Merkezini açar;
#  --cli veya -y verilirse ya da ekransız ortamdaysa terminal modunda çalışır)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ]; then
    echo "[!] Uyarı: Bu betiği 'sudo ./install.sh' olarak DEĞİL, normal kullanıcınızla ('./install.sh') çalıştırın!"
    echo "    (Wine ortamınız ve tarayıcı profilleriniz kendi kullanıcı dizininizdedir; paket kurulumu gerekirse betik kendisi yetki isteyecektir.)"
    exit 1
fi

get_priv() {
    if [ "$(id -u)" -eq 0 ]; then
        echo ""
    elif [ ! -t 0 ] && command -v pkexec >/dev/null 2>&1; then
        echo "pkexec"
    elif command -v sudo >/dev/null 2>&1; then
        echo "sudo"
    elif command -v doas >/dev/null 2>&1; then
        echo "doas"
    elif command -v pkexec >/dev/null 2>&1; then
        echo "pkexec"
    else
        echo ""
    fi
}

install_pkg_for_python_tk() {
    PRIV="$(get_priv)"
    if command -v pacman >/dev/null 2>&1; then
        $PRIV pacman -Sy --needed --noconfirm python tk curl
    elif command -v apt-get >/dev/null 2>&1; then
        $PRIV apt-get update && $PRIV apt-get install -y python3 python3-tk curl
    elif command -v dnf >/dev/null 2>&1; then
        $PRIV dnf install -y python3 python3-tkinter curl
    elif command -v zypper >/dev/null 2>&1; then
        $PRIV zypper --non-interactive install python3 python3-tk curl
    elif command -v xbps-install >/dev/null 2>&1; then
        $PRIV xbps-install -Sy python3 python3-tkinter curl
    elif command -v apk >/dev/null 2>&1; then
        $PRIV apk add python3 py3-tkinter curl
    elif command -v emerge >/dev/null 2>&1; then
        $PRIV emerge --noreplace --ask=n dev-lang/python net-misc/curl
    fi
}

# Python3 kontrolü
if ! command -v python3 >/dev/null 2>&1; then
    install_pkg_for_python_tk
fi

# Grafik oturum aktifse ve --cli istenmediyse tkinter modülünün de kurulu olduğundan emin ol
WANT_CLI=0
for arg in "$@"; do
    case "$arg" in
        --cli|-y|--yes) WANT_CLI=1 ;;
    esac
done

if [ "$WANT_CLI" -eq 0 ] && { [ -n "${WAYLAND_DISPLAY:-}" ] || [ -n "${DISPLAY:-}" ]; }; then
    if ! python3 -c "import tkinter" >/dev/null 2>&1; then
        install_pkg_for_python_tk || true
    fi
fi

# ~/.local/bin PATH kaydı
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *)
        for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
            if [ -f "$rc" ] && ! grep -q 'HOME/.local/bin' "$rc" 2>/dev/null; then
                printf '\n# IDM-Linux CLI\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc"
            fi
        done
        export PATH="$HOME/.local/bin:$PATH"
        ;;
esac

# PYTHONPATH: install.sh yeni düzende src/idm_linux/ altındadır; idm_linux paketini
# içeren taban bir üst dizindir (src/).
export PYTHONPATH="$(cd "$SCRIPT_DIR/.." && pwd)${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m idm_linux.cli install "$@"
