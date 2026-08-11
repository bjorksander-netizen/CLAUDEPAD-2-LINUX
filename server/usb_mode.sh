#!/usr/bin/env bash
# Teruskan port server ke HP lewat kabel USB (adb reverse).
set -eu
PORT=8765
if ! command -v adb >/dev/null 2>&1; then
  echo "adb tidak ditemukan. Pasang dulu:"
  echo "  Debian/Ubuntu : sudo apt install adb"
  echo "  Fedora        : sudo dnf install android-tools"
  echo "  Arch          : sudo pacman -S android-tools"
  exit 1
fi
adb start-server >/dev/null 2>&1 || true
echo "Perangkat terhubung:"
adb devices
adb reverse "tcp:${PORT}" "tcp:${PORT}"
echo "Mode USB aktif. Di aplikasi HP tekan tombol usb, lalu isi PIN."
