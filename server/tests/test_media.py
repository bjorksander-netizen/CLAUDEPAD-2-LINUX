#!/usr/bin/env python3
"""
test_media.py - perintah media control (play/pause/prev/next) diproses benar.

Membuktikan: handle_message("media", a=...) memanggil BACKEND.media(action)
yang benar, dan membalas media_result. Berjalan dengan safe_harness AKTIF
-> tidak ada injeksi tombol nyata.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import safe_harness
safe_harness.activate()

import input_core

# Tangkap aksi media yang dikirim ke backend (di-stub oleh harness).
captured = []


def _fake_media(action):
    captured.append(action)


def main():
    # Override backend.media dengan penangkap agar kita tahu action diteruskan.
    orig = input_core.BACKEND.media
    input_core.BACKEND.media = _fake_media
    try:
        replies = []

        def reply(obj):
            replies.append(obj)

        for action in ("playpause", "next", "prev", "stop", "volup", "voldown", "mute"):
            captured.clear()
            replies.clear()
            input_core.handle_message({"t": "media", "a": action}, reply)
            # mute ditangani terpisah (volume_mute_toggle) -> bukan ke BACKEND.media
            if action == "mute":
                continue
            assert captured and captured[0] == action, \
                f"media({action}) tidak diteruskan ke backend: {captured}"
            assert any(r.get("t") == "media_result" and r.get("ok")
                       for r in replies), \
                f"media({action}) tidak membalas media_result ok"
            print(f"[i] media({action}) -> backend + media_result OK")

        # aksi tidak dikenal -> media_result ok=False
        replies.clear()
        input_core.handle_message({"t": "media", "a": "bukan_aksi"}, reply)
        assert any(r.get("t") == "media_result" and not r.get("ok")
                   for r in replies), "aksi media asing harus ok=False"
        print("[i] media(<asing>) -> media_result ok=False OK")
    finally:
        input_core.BACKEND.media = orig

    print("\nSEMUA UJI MEDIA LULUS")
    sys.exit(0)


if __name__ == "__main__":
    main()
