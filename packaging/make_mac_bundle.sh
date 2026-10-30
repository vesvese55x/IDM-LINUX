#!/usr/bin/env bash
# macOS için taşınabilir paket (pkg kaynağı) — Wine katmanı kullanıcı tarafında brew ile kurulur
set -euo pipefail
ARCH="${1:-arm64}"
cd "$(dirname "$0")/.."
VER=$(python3 -c "import sys;sys.path.insert(0,'src');import idm_linux;print(idm_linux.__version__)")
OUT="idm-linux-v${VER}-macos-${ARCH}.pkg.tar"
tar -cf "$OUT" src extension language README.md packaging/macos-install.sh 2>/dev/null || true
echo "macOS bundle hazır: $OUT"
