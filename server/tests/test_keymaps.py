#!/usr/bin/env python3
"""
Uji peta tombol.

Salah ketik satu nama konstanta di peta tombol tidak membuat apa pun crash:
tombolnya hanya diam-diam tidak berfungsi, dan itu baru ketahuan setelah
dipakai. Jadi setiap entri diverifikasi benar-benar ada di evdev dan X11.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import input_core as core                                      # noqa: E402
import binary_protocol as bp                                   # noqa: E402

FAILED = []


def check(label, cond):
    print(("OK  - " if cond else "GAGAL - ") + label)
    if not cond:
        FAILED.append(label)


def main():
    # Protokol mendefinisikan nama tombol di binary_protocol._VK_IDS.
    # Setiap nama itu HARUS punya padanan di kedua backend, kalau tidak
    # ada tombol yang bekerja di uinput tapi mati di X11 (atau sebaliknya).
    proto_keys = set(bp._VK_IDS)
    check("semua tombol protokol ada di peta evdev",
          not (proto_keys - set(core._EVDEV_KEYS)))
    check("semua tombol protokol ada di peta X11",
          not (proto_keys - set(core._X11_KEYS)))
    check("peta evdev dan X11 punya kunci yang sama",
          set(core._EVDEV_KEYS) == set(core._X11_KEYS))
    check("semua aksi media ada di kedua peta",
          set(core.MEDIA_EVDEV) == set(core.MEDIA_X11))

    try:
        from evdev import ecodes
    except ImportError:
        print("evdev tidak ada - verifikasi konstanta evdev dilewati")
    else:
        bad = [f"{k}->{v}" for k, v in core._EVDEV_KEYS.items()
               if not hasattr(ecodes, v)]
        check(f"konstanta evdev tombol valid ({bad})", not bad)
        bad = [f"{k}->{v}" for k, v in core.MEDIA_EVDEV.items()
               if not hasattr(ecodes, v)]
        check(f"konstanta evdev media valid ({bad})", not bad)
        bad = [f"{c!r}->{v}" for c, v in
               {**core._ASCII_UNSHIFTED, **core._ASCII_SHIFTED}.items()
               if not hasattr(ecodes, v)]
        check(f"konstanta evdev tabel ASCII valid ({bad})", not bad)

    try:
        from Xlib import XK
    except ImportError:
        print("python-xlib tidak ada - verifikasi keysym X11 dilewati")
    else:
        bad = [f"{k}->{v}" for k, v in core._X11_KEYS.items()
               if XK.string_to_keysym(v) == 0]
        check(f"keysym X11 tombol valid ({bad})", not bad)
        # Peta memakai ejaan xdotool ("XF86AudioPlay"); python-xlib
        # menamainya "XF86_AudioPlay". XtestBackend menerjemahkannya,
        # jadi yang diuji di sini adalah hasil terjemahan itu.
        XK.load_keysym_group("xf86")
        bad = [f"{k}->{v}" for k, v in core.MEDIA_X11.items()
               if XK.string_to_keysym(v) == 0
               and XK.string_to_keysym("XF86_" + v[4:]) == 0]
        check(f"keysym X11 media valid ({bad})", not bad)

    # Tabel ASCII harus menutup seluruh karakter cetak ASCII, kalau tidak
    # ada karakter yang diam-diam hilang saat mengetik lewat uinput.
    covered = set(core._ASCII_UNSHIFTED) | set(core._ASCII_SHIFTED)
    printable = {chr(c) for c in range(0x20, 0x7f)}
    check(f"tabel ASCII menutup semua karakter cetak "
          f"(kurang: {sorted(printable - covered)})",
          not (printable - covered))
    overlap = set(core._ASCII_UNSHIFTED) & set(core._ASCII_SHIFTED)
    check(f"tidak ada karakter ganda antar tabel ({sorted(overlap)})", not overlap)

    print()
    if FAILED:
        print(f"{len(FAILED)} UJI PETA TOMBOL GAGAL:")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print("SEMUA UJI PETA TOMBOL LULUS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
