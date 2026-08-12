#!/usr/bin/env bash
# Pemasangan CLAUDEPAD Server untuk Linux.
#
# Wrapper tipis ke setup_core.py (logika inti ada di sana, idempoten &
# sandbox-aware). setup_core hanya butuh modul Python standar + modul
# se-folder (paths, autostart), sehingga python3 sistem langsung cukup —
# tidak perlu virtualenv server. Setiap langkah dicetak sebelum dijalankan;
# bagian yang butuh root diminta lewat pkexec/sudo.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Pemasangan CLAUDEPAD Server (via setup_core.py)"
exec python3 "$HERE/setup_core.py" install "$@"
