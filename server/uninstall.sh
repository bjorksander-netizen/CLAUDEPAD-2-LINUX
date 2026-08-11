#!/usr/bin/env bash
# Penghapusan CLAUDEPAD Server untuk Linux.
#
# Kebalikan dari install.sh, idempotent (aman dijalankan berkali-kali), dan
# mencetak setiap langkah sebelum menjalankannya:
#   1. hapus virtualenv    ~/.local/share/claudepad/venv
#   2. hapus aturan udev   /etc/udev/rules.d/99-claudepad-uinput.rules
#   3. hapus entri menu    ~/.local/share/applications/claudepad.desktop
#   4. hapus autostart     ~/.config/autostart/claudepad.desktop
#   5. hapus unit systemd user  ~/.config/systemd/user/claudepad.service
#   6. (opsional) hapus konfigurasi  ~/.config/claudepad  -- butuh konfirmasi;
#      dilewati dengan --keep-config.
#
# Keanggotaan grup 'input' TIDAK dicabut: grup itu dipakai bersama oleh
# aplikasi lain, mencabutnya bisa merusak izin app lain di mesin yang sama.
# Untuk melepas manual:  sudo gpasswd -d "$USER" input
set -euo pipefail

KEEP_CONFIG=0
for arg in "$@"; do
  case "$arg" in
    --keep-config) KEEP_CONFIG=1 ;;
    -h|--help)
      echo "Pemakaian: $0 [--keep-config]"
      echo "  --keep-config  jangan hapus ~/.config/claudepad (token pairing, gesture)"
      exit 0
      ;;
    *)
      echo "Argumen tidak dikenal: $arg (lihat --help)" >&2
      exit 2
      ;;
  esac
done

say()  { printf '\n\033[1;35m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m  !\033[0m %s\n' "$1"; }
ok()   { printf '\033[1;32m  v\033[0m %s\n' "$1"; }

VENV="${XDG_DATA_HOME:-$HOME/.local/share}/claudepad/venv"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/claudepad"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
UDEV_RULE="/etc/udev/rules.d/99-claudepad-uinput.rules"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/claudepad.desktop"
SYSTEMD_UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/claudepad.service"

# Konfigurasi (token pairing, gesture) berisi data pribadi - jangan dihapus
# tanpa konfirmasi eksplisit.
REMOVE_CONFIG=0
if [ "$KEEP_CONFIG" = "0" ] && [ -d "$CONFIG_DIR" ]; then
  echo
  printf '\033[1;33m  !\033[0m %s' "Hapus juga $CONFIG_DIR (token pairing, gesture)? [y/N] "
  read -r ans
  case "$ans" in
    y|Y|yes|YES) REMOVE_CONFIG=1 ;;
    *) REMOVE_CONFIG=0 ;;
  esac
fi

# ---------------------------------------------------------- 1. Virtualenv ----
say "1. Virtualenv Python"
if [ -d "$VENV" ]; then
  rm -rf "$VENV"
  ok "virtualenv dihapus: $VENV"
else
  ok "tidak ada virtualenv - lewati"
fi

# ----------------------------------------------------------- 2. Udev rule ----
say "2. Aturan udev (uinput)"
if [ -f "$UDEV_RULE" ]; then
  if [ -w /etc/udev/rules.d ] || sudo -n true 2>/dev/null || true; then
    sudo rm -f "$UDEV_RULE"
    sudo udevadm control --reload-rules 2>/dev/null || true
    ok "aturan udev dihapus: $UDEV_RULE"
  else
    warn "tidak punya sudo - hapus manual: sudo rm $UDEV_RULE"
  fi
else
  ok "tidak ada aturan udev - lewati"
fi

# -------------------------------------------------------- 3. Menu aplikasi ---
say "3. Entri menu aplikasi"
if [ -f "$APPS/claudepad.desktop" ]; then
  rm -f "$APPS/claudepad.desktop"
  update-desktop-database "$APPS" 2>/dev/null || true
  ok "entri menu dihapus"
else
  ok "tidak ada entri menu - lewati"
fi

# ------------------------------------------------------------ 4. Autostart ---
say "4. Autostart saat login"
if [ -f "$AUTOSTART" ]; then
  rm -f "$AUTOSTART"
  ok "autostart dihapus: $AUTOSTART"
else
  ok "tidak ada autostart - lewati"
fi

# ---------------------------------------------------- 5. Unit systemd user ---
say "5. Unit systemd user"
if [ -f "$SYSTEMD_UNIT" ]; then
  systemctl --user disable --now claudepad 2>/dev/null || true
  rm -f "$SYSTEMD_UNIT"
  systemctl --user daemon-reload 2>/dev/null || true
  ok "unit systemd user dihapus"
else
  ok "tidak ada unit systemd user - lewati"
fi

# ------------------------------------------------------- 6. Konfigurasi ------
say "6. Konfigurasi CLAUDEPAD"
if [ "$REMOVE_CONFIG" = "1" ] && [ -d "$CONFIG_DIR" ]; then
  rm -rf "$CONFIG_DIR"
  ok "konfigurasi dihapus: $CONFIG_DIR"
else
  ok "konfigurasi dipertahankan: $CONFIG_DIR"
fi

say "Selesai."
echo "Pengguna '$USER' masih berada di grup 'input' (dipakai bersama aplikasi"
echo "lain). Untuk melepasnya:  sudo gpasswd -d \"$USER\" input"
