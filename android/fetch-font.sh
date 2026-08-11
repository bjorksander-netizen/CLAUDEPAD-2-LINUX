#!/usr/bin/env bash
# Unduh JetBrains Mono untuk build lokal. Opsional — tanpa ini aplikasi
# memakai monospace bawaan sistem.
set -e
DIR="$(dirname "$0")/app/src/main/res/font"
mkdir -p "$DIR"
curl -fsSL -o "$DIR/jetbrains_mono.ttf" \
  "https://raw.githubusercontent.com/JetBrains/JetBrainsMono/v2.304/fonts/ttf/JetBrainsMono-Regular.ttf"
echo "JetBrains Mono tersimpan di $DIR"
