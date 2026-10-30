#!/usr/bin/env bash
# macOS kurulum taslağı (v2.9-mac dalının çekirdeği): brew + launchd entegrasyonu
set -euo pipefail
echo "[*] macOS bağımlılıkları (brew): wine-stable ffmpeg aria2 python@3.12"
command -v brew >/dev/null && brew list wine-stable >/dev/null 2>&1 || brew install --cask wine-stable || true
command -v brew >/dev/null && brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg aria2 || true
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/../src"
python3 -m idm_linux.cli install || python3 -m idm_linux.cli install-gui
