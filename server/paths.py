#!/usr/bin/env python3
"""
Resolusi path untuk server Linux.

Berbeda dengan versi Windows yang menyimpan segalanya di sebelah .exe,
versi Linux mengikuti XDG Base Directory Specification:

  * Berkas bundel read-only (mis. fix_firewall.sh) ada di folder skrip
    - atau di sys._MEIPASS kalau dibungkus PyInstaller.
  * Berkas yang perlu BERTAHAN (token pairing, konfigurasi gesture)
    disimpan di $XDG_CONFIG_HOME/claudepad, default ~/.config/claudepad.
    Folder itu dibuat dengan mode 0700 supaya token tidak terbaca
    pengguna lain di mesin yang sama.
"""

import os
import sys

FROZEN = getattr(sys, "frozen", False)

APP_DIR_NAME = "claudepad"


def resource_path(name: str) -> str:
    """Berkas bundel read-only (skrip pendamping, ikon)."""
    if FROZEN:
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


def config_dir() -> str:
    """$XDG_CONFIG_HOME/claudepad, dibuat kalau belum ada (mode 0700)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    d = os.path.join(base, APP_DIR_NAME)
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        # Kalau folder sudah ada dari versi lama dengan mode longgar, rapatkan.
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def data_path(name: str) -> str:
    """Berkas yang perlu bertahan antar-sesi."""
    return os.path.join(config_dir(), name)


def state_dir() -> str:
    """$XDG_STATE_HOME/claudepad untuk log. Dibuat kalau belum ada."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state")
    d = os.path.join(base, APP_DIR_NAME)
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
    except OSError:
        pass
    return d
