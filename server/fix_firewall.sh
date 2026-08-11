#!/usr/bin/env bash
# Buka port CLAUDEPAD di firewall. Dijalankan lewat pkexec/sudo dari GUI.
# Skrip terpisah (bukan perintah inline panjang) supaya tidak ada quoting
# berlapis yang rawan salah.
set -u

WS_PORT=8765
DISCOVERY_PORT=8766

if [ "$(id -u)" -ne 0 ]; then
  echo "Skrip ini harus dijalankan sebagai root (pkexec/sudo)." >&2
  exit 1
fi

opened=0

if command -v ufw >/dev/null 2>&1; then
  ufw allow "${WS_PORT}/tcp"        comment "CLAUDEPAD TCP" || true
  ufw allow "${DISCOVERY_PORT}/udp" comment "CLAUDEPAD discovery" || true
  echo "ufw: port ${WS_PORT}/tcp dan ${DISCOVERY_PORT}/udp diizinkan"
  opened=1
fi

if command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="${WS_PORT}/tcp" || true
  firewall-cmd --permanent --add-port="${DISCOVERY_PORT}/udp" || true
  firewall-cmd --reload || true
  echo "firewalld: port ${WS_PORT}/tcp dan ${DISCOVERY_PORT}/udp diizinkan"
  opened=1
fi

if [ "$opened" -eq 0 ]; then
  echo "Tidak ada ufw maupun firewalld - kemungkinan tidak ada firewall aktif."
fi
