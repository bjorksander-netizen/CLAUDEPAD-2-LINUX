#!/usr/bin/env bash
# Jalankan server CLAUDEPAD. Membuat virtualenv sendiri di
# ~/.local/share/claudepad/venv saat pertama kali, supaya tidak mengotori
# Python sistem dan tidak tersandung PEP 668 (externally-managed-environment).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/claudepad/venv"

if [ ! -x "$VENV/bin/python" ]; then
  echo "Menyiapkan virtualenv di $VENV ..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip >/dev/null
  "$VENV/bin/pip" install -r "$HERE/requirements.txt"
fi

exec "$VENV/bin/python" "$HERE/pc_server.py" "$@"
