#!/usr/bin/env bash
# Penghapusan CLAUDEPAD Server untuk Linux.
#
# Wrapper tipis ke setup_core.py (logika inti ada di sana, idempoten &
# sandbox-aware). setup_core hanya butuh modul Python standar + modul
# se-folder, sehingga python3 sistem langsung cukup. setup_core menghapus:
# virtualenv, aturan udev, entri menu, autostart, unit systemd user, dan
# konfigurasi (kecuali --keep-config). Keanggotaan grup 'input' sengaja
# TIDAK dicabut (dipakai bersama app lain).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Penghapusan CLAUDEPAD Server (via setup_core.py)"
exec python3 "$HERE/setup_core.py" uninstall "$@"
