#!/usr/bin/env bash
# Compila cast-dlna a un binario único con Nuitka e instala el symlink.
#
#   ./build.sh              compila
#   ./build.sh --install    compila y enlaza en ~/.local/bin/cast-dlna
set -euo pipefail

cd "$(dirname "$0")"
BIN_DIR="$HOME/.local/bin"
OUT="$PWD/dist/cast-dlna"

mkdir -p dist

python3 -m nuitka \
    --onefile \
    --output-filename=cast-dlna \
    --output-dir=dist \
    --include-package=cast_dlna \
    --assume-yes-for-downloads \
    --remove-output \
    --quiet \
    cast-dlna.py

echo "binario: $OUT"
"$OUT" --help >/dev/null && echo "smoke test: ok"

if [[ "${1:-}" == "--install" ]]; then
    mkdir -p "$BIN_DIR"
    ln -sfn "$OUT" "$BIN_DIR/cast-dlna"
    echo "symlink: $BIN_DIR/cast-dlna → $OUT"
fi
