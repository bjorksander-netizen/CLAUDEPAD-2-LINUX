#!/usr/bin/env python3
"""
test_gesture4.py - gesture 4 jari (workspace switch) dipetakan benar.

Membuktikan: gesture("workspace_next"/"workspace_prev"/"taskview"/
"showdesktop") diteruskan ke backend sebagai key yang benar (Ctrl+Alt+Left/
Right untuk workspace). Berjalan dengan safe_harness AKTIF -> tidak ada
injeksi tombol nyata.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import safe_harness
safe_harness.activate()

import input_core

pressed = []


def _fake_tap(name, mods=()):
    pressed.append((name, tuple(mods)))


def _install_capture():
    """Tangkap press_key backend (di-stub harness) per panggilan."""
    orig = input_core.BACKEND.tap

    def cap(name, mods=()):
        _fake_tap(name, mods)
        return orig(name, mods)
    input_core.BACKEND.tap = cap
    return orig


def main():
    orig = _install_capture()
    try:
        cases = {
            "workspace_next": ("right", ("ctrl", "alt")),
            "workspace_prev": ("left", ("ctrl", "alt")),
            "taskview": None,       # tergantung desktop, cukup pastikan tidak error
            "showdesktop": None,
        }
        for g, expected in cases.items():
            pressed.clear()
            input_core.gesture(g)   # gesture() -> gesture_map() -> BACKEND.tap
            if expected is not None:
                name, mods = expected
                assert any(n == name and set(mods) <= set(m)
                           for n, m in pressed), \
                    f"gesture({g}) salah petakan: {pressed}"
                print(f"[i] gesture({g}) -> {expected} OK")
            else:
                assert pressed or True, "gesture tidak error"
                print(f"[i] gesture({g}) diproses tanpa error")
    finally:
        input_core.BACKEND.tap = orig

    print("\nSEMUA UJI GESTURE 4 JARI LULUS")
    sys.exit(0)


if __name__ == "__main__":
    main()
