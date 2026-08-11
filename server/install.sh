#!/usr/bin/env bash
# Pemasangan CLAUDEPAD Server untuk Linux.
#
# Yang dilakukan:
#   1. Pasang dependensi Python di virtualenv sendiri.
#   2. Pasang aturan udev supaya /dev/uinput bisa ditulis grup "input",
#      lalu masukkan pengguna ke grup itu. Ini yang membuat trackpad
#      bekerja di Wayland.
#   3. Pasang entri menu aplikasi.
#   4. Buka port firewall bila ufw/firewalld aktif.
#
# Bagian yang butuh root diminta lewat sudo satu per satu, dan setiap
# langkah dicetak sebelum dijalankan supaya tidak ada yang terjadi diam-diam.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/claudepad/venv"

say()  { printf '\n\033[1;35m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m  !\033[0m %s\n' "$1"; }
ok()   { printf '\033[1;32m  v\033[0m %s\n' "$1"; }

# ---------------------------------------------------------- 1. Python ------
say "Menyiapkan virtualenv Python di $VENV"
if ! python3 -c 'import venv' 2>/dev/null; then
  warn "modul venv tidak ada. Debian/Ubuntu: sudo apt install python3-venv"
  exit 1
fi
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r "$HERE/requirements.txt"
ok "dependensi terpasang"

if ! "$VENV/bin/python" -c 'import tkinter' 2>/dev/null; then
  warn "tkinter tidak ada - GUI tidak akan jalan, server tetap bisa --nogui."
  warn "  Debian/Ubuntu : sudo apt install python3-tk"
  warn "  Fedora        : sudo dnf install python3-tkinter"
  warn "  Arch          : sudo pacman -S tk"
fi

# ---------------------------------------------------------- 2. uinput ------
say "Memasang aturan udev untuk /dev/uinput"
if [ -w /etc/udev/rules.d ] || sudo -n true 2>/dev/null || true; then
  sudo cp "$HERE/99-claudepad-uinput.rules" /etc/udev/rules.d/
  sudo groupadd -f input
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=misc || true
  sudo modprobe uinput || warn "modul uinput gagal dimuat (kernel tanpa uinput?)"
  ok "aturan udev terpasang"
else
  warn "tidak bisa menulis /etc/udev/rules.d - lewati"
fi

if id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
  ok "pengguna $USER sudah ada di grup input"
else
  sudo usermod -aG input "$USER"
  warn "kamu baru dimasukkan ke grup 'input'."
  warn "LOGOUT dan LOGIN lagi supaya berlaku, kalau tidak trackpad"
  warn "akan jatuh ke backend X11 dan tidak jalan di Wayland."
fi

# ------------------------------------------------------- 3. Menu aplikasi --
say "Memasang entri menu aplikasi"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
cat > "$APPS/claudepad.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=CLAUDEPAD
Comment=Server remote trackpad & keyboard untuk HP Android
Exec=$HERE/start_server.sh
Icon=input-tablet
Terminal=false
Categories=Utility;RemoteAccess;
DESKTOP
update-desktop-database "$APPS" 2>/dev/null || true
ok "entri menu terpasang"

# ---------------------------------------------------------- 4. Firewall ----
say "Membuka port firewall (8765/tcp, 8766/udp)"
if command -v ufw >/dev/null 2>&1 || command -v firewall-cmd >/dev/null 2>&1; then
  sudo "$HERE/fix_firewall.sh"
  ok "port dibuka"
else
  ok "tidak ada ufw/firewalld - tidak ada yang perlu dibuka"
fi

say "Selesai."
echo "Jalankan server dengan:  $HERE/start_server.sh"
echo "Tanpa GUI (systemd/SSH):  $HERE/start_server.sh --nogui"
