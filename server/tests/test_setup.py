#!/usr/bin/env python3
"""
test_setup.py - jaring pengaman setup wizard (install/uninstall).

Membuktikan dua hal tanpa menyentuh sistem pengguna sungguhan:

  1. KEAMANAN: dengan safe_harness AKTIF, install_all()/uninstall_all()
     tidak menjalankan SATUPUN subprocess nyata (diverifikasi lewat
     _SubprocessRecorder yang MELEMPAR bila ada subprocess dipanggil).
     Ini menjaga konvensi OPEN-CONVENTIONS Bagian 4: test tidak boleh
     mengeksekusi aksi sistem nyata.

  2. IDEMPOTENSI: install_all() lalu uninstall_all() berulang di direktori
     temp tidak melempar dan mengembalikan hasil (ok, msg) berbentuk benar.
     uninstall_all() kedua kali aman (tidak ada -> "lewati").

TIDAK ada satu pun pengujian di sini yang menulis ke ~/.config/claudepad
asli; safe_harness mengarahkan path data ke temp dir.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import safe_harness                                       # noqa: E402
import setup_core                                          # noqa: E402

FAILED = []


def check(label, cond):
    print(("OK  - " if cond else "GAGAL - ") + label)
    if not cond:
        FAILED.append(label)


# Recorder subprocess: MENCATAT dan MENOLAK semua eksekusi nyata.
class _SubprocessRecorder:
    def __init__(self):
        self.calls = []
        self._orig_run = subprocess.run
        self._orig_popen = subprocess.Popen

    def install(self):
        subprocess.run = self._run
        subprocess.Popen = self._popen

    def restore(self):
        subprocess.run = self._orig_run
        subprocess.Popen = self._orig_popen

    def _run(self, args, **kwargs):
        self.calls.append(str(args))
        raise AssertionError(
            "subprocess.run DIPANGGIL padahal seharusnya ter-stub: " + str(args))

    def _popen(self, args, **kwargs):
        self.calls.append(str(args))
        raise AssertionError(
            "subprocess.Popen DIPANGGIL padahal seharusnya ter-stub: " + str(args))


def test_install_uninstall_tanpa_subprocess_nyata():
    """Dengan harness aktif, install lalu uninstall NOL subprocess nyata."""
    os.environ.pop("CLAUDEPAD_ALLOW_REAL", None)
    safe_harness.activate()
    rec = _SubprocessRecorder()
    rec.install()
    try:
        res_i = setup_core.install_all()
        res_u = setup_core.uninstall_all()
    except AssertionError as e:
        rec.restore()
        safe_harness.restore()
        check("setup: install/uninstall TIDAK memanggil subprocess nyata", False)
        FAILED.append(f"subprocess nyata hampir dieksekusi: {e}")
        return
    finally:
        rec.restore()
    check("setup: install mengembalikan list hasil", isinstance(res_i, list)
          and len(res_i) == 6)
    check("setup: uninstall mengembalikan list hasil", isinstance(res_u, list)
          and len(res_u) == 6)
    # Setiap langkah harus berhasil (karena disimulasikan oleh harness).
    check("setup: semua langkah install ok (simulasi)",
          all(ok for _n, ok, _m in res_i))
    check("setup: semua langkah uninstall ok (simulasi)",
          all(ok for _n, ok, _m in res_u))
    check("setup: NOL panggilan subprocess saat install/uninstall",
          rec.calls == [])
    safe_harness.assert_no_real_calls()
    safe_harness.restore()


def test_preflight_readonly():
    """preflight() tidak memanggil subprocess apa pun (deteksi murni)."""
    rec = _SubprocessRecorder()
    rec.install()
    try:
        info = setup_core.preflight()
    finally:
        rec.restore()
    check("setup: preflight mengembalikan dict", isinstance(info, dict))
    for key in ("python_ok", "tkinter_ok", "distro", "session",
                "input_group_ok", "udev_writable", "firewall_tool"):
        check(f"setup: preflight['{key}'] ada", key in info)
    check("setup: preflight NOL subprocess", rec.calls == [])


def test_uninstall_idempoten():
    """uninstall_all() kedua kali aman (artefak sudah tiada -> lewati)."""
    os.environ.pop("CLAUDEPAD_ALLOW_REAL", None)
    safe_harness.activate()
    try:
        first = setup_core.uninstall_all()
        second = setup_core.uninstall_all()
    finally:
        safe_harness.restore()
    check("setup: uninstall pertama menghasilkan 6 langkah", len(first) == 6)
    check("setup: uninstall kedua menghasilkan 6 langkah (idempoten)",
          len(second) == 6)
    # Langkah yang "tidak ada" harus dilaporkan sebagai lewati, bukan gagal.
    msgs = [m for _n, _ok, m in second]
    check("setup: uninstall ke-2 melaporkan 'lewati' untuk yang tiada",
          any("lewati" in (m or "") for m in msgs))
    safe_harness.assert_no_real_calls()


def main():
    print("=== JARING PENGAMAN: setup wizard (install/uninstall) ===")
    test_install_uninstall_tanpa_subprocess_nyata()
    test_preflight_readonly()
    test_uninstall_idempoten()

    safe_harness.restore()
    os.environ.pop("CLAUDEPAD_ALLOW_REAL", None)

    print()
    if FAILED:
        print(f"{len(FAILED)} UJI SETUP GAGAL:")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print("SEMUA UJI SETUP LULUS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
