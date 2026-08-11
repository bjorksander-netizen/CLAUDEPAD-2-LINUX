#!/usr/bin/env python3
"""
Auto-start server CLAUDEPAD saat login, lewat XDG Autostart.

Versi Windows memakai registry HKCU\\...\\Run. Padanan Linux yang paling
lintas-desktop adalah berkas .desktop di ~/.config/autostart - dihormati
GNOME, KDE, XFCE, Cinnamon, MATE, LXQt, dan banyak lagi.

Sengaja BUKAN unit systemd --user sebagai default: unit systemd tidak
mewarisi variabel sesi grafis (DISPLAY, WAYLAND_DISPLAY, XDG_SESSION_TYPE)
tanpa impor lingkungan tambahan, dan tanpa variabel itu backend XTEST serta
aksi daya tidak bisa menemukan sesinya. Unit systemd tetap disediakan di
claudepad.service untuk yang menjalankan server tanpa GUI (mode --nogui).
"""

import os
import sys

from paths import FROZEN

AUTOSTART_NAME = "claudepad.desktop"


def _autostart_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, "autostart")


def _autostart_file():
    return os.path.join(_autostart_dir(), AUTOSTART_NAME)


def _exec_line():
    """Perintah yang dijalankan saat login."""
    if FROZEN:
        return f'"{sys.executable}" --minimized'
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "pc_server.py")
    return f'"{sys.executable}" "{script}" --minimized'


def _desktop_entry():
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=CLAUDEPAD\n"
        "Comment=Server remote trackpad & keyboard untuk HP Android\n"
        f"Exec={_exec_line()}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "NoDisplay=false\n"
    )


def set_autostart(enabled: bool) -> bool:
    """Aktifkan/nonaktifkan auto-start. True kalau berhasil."""
    path = _autostart_file()
    try:
        if enabled:
            os.makedirs(_autostart_dir(), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(_desktop_entry())
            os.chmod(path, 0o644)
        else:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        return True
    except OSError:
        return False


def is_autostart_enabled() -> bool:
    return os.path.exists(_autostart_file())
