#!/usr/bin/env python3
"""
test_safety.py - JARING PENGAMAN PERMANEN aksi sistem-nyata (QA).

Latar belakang: test_e2e.py pernah mengeksekusi aksi sistem NYATA di desktop
pengembang (power_action lock/screenoff, toggle_radio wifi/bluetooth/hotspot)
sehingga layar terkunci dan WiFi/BT mati-nyala. OPEN-CONVENTIONS.md Bagian 4
mewajibkan: test TIDAK BOLEH mengeksekusi aksi sistem nyata; semua aksi wajib
di-mock/disimulasikan; eksekusi nyata hanya dengan CLAUDEPAD_ALLOW_REAL=1 di
lingkungan terisolasi; mode --sandbox server boleh untuk jalur penuh.

File ini adalah penjaga permanen yang DETERMINISTIK, tanpa efek samping, dan
hijau. Ia membuktikan:

  1. safe_harness memblokir semua fungsi sistem-nyata tanpa
     CLAUDEPAD_ALLOW_REAL=1 (nilai simulasi, bentuk balasan tetap benar).
  2. Memanggil toggle_radio/power_action/brightness_step/volume_set lewat
     jalur test dengan harness AKTIF tidak menjalankan SATUPUN subprocess
     nyata (diverifikasi lewat recorder, bukan eksekusi).
  3. Gerbang CLAUDEPAD_ALLOW_REAL bekerja (logika keputusan; TIDAK mengeksekusi).
  4. assert_no_real_calls() gagal keras kalau ada eksekusi nyata.
  5. Mode sandbox server (core.set_sandbox) mensimulasikan dan tidak
     mengeksekusi subprocess.
  6. Daftar pola perintah berbahaya lengkap (menjaga penjaga itu sendiri).

TIDAK ada satu pun pengujian di sini yang menjalankan aksi sistem nyata.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clipboard                                              # noqa: E402
import input_core as core                                      # noqa: E402
import mpris                                                   # noqa: E402
import safe_harness                                           # noqa: E402
import system_ctl                                              # noqa: E402

FAILED = []
WARNINGS = []

# ---------------------------------------------------------------- Utilitas ----
def check(label, cond):
    print(("OK  - " if cond else "GAGAL - ") + label)
    if not cond:
        FAILED.append(label)


def warn(msg):
    WARNINGS.append(msg)
    print(f"CATATAN - {msg}")


def clear_lists():
    safe_harness.SIMULATED.clear()
    safe_harness.REAL_CALLS.clear()


# Recorder subprocess: MENCATAT dan MENOLAK semua eksekusi; kalau ada fungsi
# yang benar-benar memanggil subprocess, test ini GAGAL (recorder melempar).
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

    def _key(self, args):
        if isinstance(args, (list, tuple)):
            return " ".join(str(a) for a in args)
        return str(args)

    def _run(self, args, **kwargs):
        self.calls.append(self._key(args))
        raise AssertionError(
            "subprocess.run DIPANGGIL padahal seharusnya ter-stub: "
            + self._key(args))

    def _popen(self, args, **kwargs):
        self.calls.append(self._key(args))
        raise AssertionError(
            "subprocess.Popen DIPANGGIL padahal seharusnya ter-stub: "
            + self._key(args))


# Daftar pola perintah BERBAHAYA — dipakai untuk menjaga penjaga itu sendiri.
DANGEROUS_PATTERNS = (
    "systemctl poweroff", "systemctl reboot", "systemctl suspend",
    "systemctl hibernate",
    "loginctl lock-session", "loginctl terminate-session",
    "xdg-screensaver lock", "swaylock", "i3lock",
    "gnome-screensaver-command --lock",
    "xset dpms force off", "swaymsg output * power off",
    "hyprctl dispatch dpms off",
    "nmcli radio wifi", "nmcli radio bluetooth",
    "nmcli connection down", "nmcli device wifi hotspot",
    "rfkill block", "rfkill unblock",
    "bluetoothctl power on", "bluetoothctl power off",
    "brightnessctl set", "light -S", "ddcutil setvcp",
    "wpctl set-volume", "pactl set-sink-volume", "pactl set-sink-mute",
    "amixer set", "amixer -q set",
    # v3.7 - clipboard & MPRIS: menulis clipboard / menggeser pemutar juga
    # efek nyata di desktop pengguna (dan gdbus/playerctl mengirim perintah
    # ke pemutar yang sedang berjalan).
    "wl-copy", "wl-paste", "xclip", "xsel", "gdbus", "playerctl",
    "dbus-send", "qdbus",
    "pkexec", "sudo",
)


# ------------------------------------------------------------ Pengujian -------
def test_harness_memblokir_semua_aksi_sistem():
    """Tanpa CLAUDEPAD_ALLOW_REAL=1 semua aksi disimulasikan, tidak nyata."""
    clear_lists()
    os.environ.pop("CLAUDEPAD_ALLOW_REAL", None)
    safe_harness.activate()

    # Daya — SEMUA aksi termasuk shutdown/restart/sleep harus simulasi.
    for act in ("shutdown", "restart", "sleep", "hibernate",
                "logoff", "lock", "screenoff"):
        ok, msg = system_ctl.power_action(act)
        check(f"harness: power_action('{act}') simulasi",
              ok is True and "safe_harness" in str(msg))
    ok, msg = system_ctl.power_action("bogus")
    check("harness: aksi daya tak dikenal ditolak",
          ok is False and isinstance(msg, str))

    # Radio.
    for dev in ("wifi", "bluetooth", "hotspot"):
        ok, msg = core.toggle_radio(dev)
        check(f"harness: toggle_radio('{dev}') simulasi",
              ok is True and "safe_harness" in str(msg))

    # Kecerahan & volume.
    ok, msg = system_ctl.brightness_step(10)
    check("harness: brightness_step simulasi",
          ok is True and "safe_harness" in str(msg))
    check("harness: volume_set simulasi", core.volume_set(50) is True)
    check("harness: volume_mute_toggle simulasi",
          core.volume_mute_toggle() is True)

    # Tidak boleh ada satu pun eksekusi nyata.
    check("harness: REAL_CALLS kosong", safe_harness.REAL_CALLS == [])
    check("harness: SIMULATED tercatat",
          len(safe_harness.SIMULATED) >= 12)
    safe_harness.assert_no_real_calls()


def test_harness_tidak_menjalankan_subprocess_nyata():
    """Dengan harness aktif, jalur berbahaya TIDAK memanggil subprocess."""
    rec = _SubprocessRecorder()
    rec.install()
    try:
        system_ctl.power_action("lock")
        system_ctl.power_action("screenoff")
        system_ctl.power_action("shutdown")
        core.toggle_radio("wifi")
        core.toggle_radio("bluetooth")
        core.toggle_radio("hotspot")
        system_ctl.brightness_step(10)
        core.volume_set(50)
    finally:
        rec.restore()
    check("harness: NOL panggilan subprocess untuk jalur berbahaya",
          rec.calls == [])


def test_gerbang_claudepad_allow_real():
    """Keputusan izin eksekusi nyata; TIDAK mengeksekusi apa pun."""
    os.environ.pop("CLAUDEPAD_ALLOW_REAL", None)
    check("gerbang: default nonaktif", safe_harness.real_allowed() is False)
    safe_harness.allow_real(True)
    check("gerbang: allow_real(True) aktif",
          safe_harness.real_allowed() is True)
    safe_harness.allow_real(False)
    check("gerbang: allow_real(False) nonaktif",
          safe_harness.real_allowed() is False)
    os.environ.pop("CLAUDEPAD_ALLOW_REAL", None)


def test_assert_no_real_calls_gagal_saat_ada_eksekusi_nyata():
    """Penjaga harus berteriak kalau ada yang meneruskan ke fungsi nyata."""
    safe_harness.REAL_CALLS.append(("system_ctl", "power_action",
                                    ("lock",), {}))
    try:
        safe_harness.assert_no_real_calls()
        check("assert_no_real_calls: melempar saat REAL_CALLS terisi", False)
    except AssertionError:
        check("assert_no_real_calls: melempar saat REAL_CALLS terisi", True)
    finally:
        safe_harness.REAL_CALLS.clear()


def test_harness_activate_restore_idempotent():
    """activate()/restore() berulang aman dan mengembalikan fungsi asli."""
    safe_harness.restore()                     # pastikan fungsi asli kembali
    orig_power = system_ctl.power_action
    safe_harness.activate()
    safe_harness.activate()                      # kedua kali: no-op
    stub_power = system_ctl.power_action
    check("harness: dua kali activate tetap satu lapis stub",
          stub_power is not orig_power)
    check("harness: stub berlabel safe_harness",
          "safe_harness" in (stub_power.__doc__ or ""))
    safe_harness.restore()
    check("harness: restore mengembalikan fungsi asli",
          system_ctl.power_action is orig_power)
    safe_harness.activate()
    safe_harness.restore()
    check("harness: activate/restore kedua aman",
          system_ctl.power_action is orig_power)


def test_mode_sandbox_menyimulasikan_tanpa_subprocess():
    """core.set_sandbox(True): radio/power/bright simulasi, NOL subprocess."""
    core.set_sandbox(False)
    rec = _SubprocessRecorder()
    rec.install()
    try:
        core.set_sandbox(True)
        ok, msg = core.toggle_radio("wifi")
        check("sandbox: toggle_radio wifi simulasi",
              ok is True and "disimulasikan (sandbox)" in str(msg))
        ok, msg = system_ctl.power_action("shutdown")
        check("sandbox: power_action shutdown simulasi",
              ok is True and "disimulasikan (sandbox)" in str(msg))
        ok, msg = system_ctl.power_action("lock")
        check("sandbox: power_action lock simulasi",
              ok is True and "disimulasikan (sandbox)" in str(msg))
        ok, msg = system_ctl.brightness_step(10)
        check("sandbox: brightness_step simulasi",
              ok is True and "simulasi sandbox" in str(msg))
        check("sandbox: is_sandbox() benar",
              core.is_sandbox() is True and system_ctl.is_sandbox() is True)
    finally:
        core.set_sandbox(False)
        rec.restore()
    check("sandbox: NOL panggilan subprocess saat simulasi", rec.calls == [])
    check("sandbox: dimatikan lagi", core.is_sandbox() is False
          and system_ctl.is_sandbox() is False)


def test_harness_stub_clipboard_mpris():
    """
    Gerbang v3.7: dengan harness AKTIF, clipboard/mpris TIDAK BOLEH
    menyentuh subprocess. Pemanggilan read/write/query/seek harus
    disimulasikan, tercatat di SIMULATED, dan NOL eksekusi nyata.
    Recorder MELEMPAR kalau ada jalur yang mencoba menjalankan
    wl-paste/xclip/gdbus/playerctl sungguhan - test ini akan GAGAL
    (regresi keamanan) selama safe_harness belum men-stub modul baru.
    """
    clear_lists()
    os.environ.pop("CLAUDEPAD_ALLOW_REAL", None)
    safe_harness.activate()
    rec = _SubprocessRecorder()
    rec.install()
    stubs_ok = True
    try:
        s = clipboard.read()
        w = clipboard.write("halo")
        q = mpris.query()
        ok, msg = mpris.seek(1000)
    except AssertionError as e:
        stubs_ok = False
        warn(f"GAP KEAMANAN: subprocess nyata hampir dieksekusi oleh "
             f"clipboard/mpris: {e}")
    finally:
        rec.restore()
    check("harness: clipboard/mpris NOL subprocess (stub terpasang)",
          stubs_ok and rec.calls == [])
    if stubs_ok:
        check("harness: clipboard.read disimulasikan -> ''", s == "")
        check("harness: clipboard.write disimulasikan -> True", w is True)
        check("harness: mpris.query disimulasikan",
              q.get("ok") is False and "safe_harness" in q.get("msg", ""))
        check("harness: mpris.seek disimulasikan",
              ok is True and "safe_harness" in str(msg))
        sim = [c for c in safe_harness.SIMULATED
               if c[0] in ("clipboard", "mpris")]
        check("harness: SIMULATED mencatat clipboard/mpris", len(sim) >= 4)
    safe_harness.assert_no_real_calls()
    # Kembalikan fungsi asli supaya test berikutnya (sandbox) menguji
    # implementasi ASLI, bukan stub harness.
    safe_harness.restore()


def test_sandbox_clipboard_mpris():
    """Mode sandbox server: clipboard & MPRIS disimulasikan, NOL subprocess,
    sistem tidak berubah."""
    core.set_sandbox(False)
    rec = _SubprocessRecorder()
    rec.install()
    try:
        core.set_sandbox(True)
        s = clipboard.read()
        w = clipboard.write("halo")
        q = mpris.query()
        ok, msg = mpris.seek(123)
    finally:
        core.set_sandbox(False)
        rec.restore()
    check("sandbox: clipboard.read -> ''", s == "")
    check("sandbox: clipboard.write -> True", w is True)
    check("sandbox: mpris.query -> ok False (sandbox)",
          q.get("ok") is False and "sandbox" in q.get("msg", ""))
    check("sandbox: mpris.seek -> disimulasikan",
          ok is True and "sandbox" in str(msg))
    check("sandbox: NOL subprocess clipboard/mpris", rec.calls == [])
    check("sandbox: dimatikan lagi", core.is_sandbox() is False)


def test_pola_perintah_berbahaya_lengkap():
    """Setiap pola kunci yang pernah membahayakan wajib ada di daftar."""
    required = (
        "loginctl lock-session", "xset dpms force off",
        "nmcli radio wifi", "nmcli radio bluetooth",
        "rfkill block", "rfkill unblock",
        "bluetoothctl power on", "brightnessctl set",
        "wpctl set-volume", "pkexec", "sudo",
        "systemctl poweroff", "systemctl suspend",
        # v3.7: pola clipboard & MPRIS wajib dijaga.
        "wl-copy", "wl-paste", "xclip", "gdbus", "playerctl",
    )
    missing = [p for p in required if p not in DANGEROUS_PATTERNS]
    check("daftar pola berbahaya lengkap (kurang: %s)" % (missing or "-"),
          not missing)


def catat_gap_firewall_dan_volume():
    """
    INFORMASI (tidak menggagalkan): safe_harness belum men-stub
    firewall_status/fix_firewall dan mode sandbox belum men-stub volume_set.
    Kalau gap ini sudah ditutup oleh pengembangan, CATATAN ini hilang dengan
    sendirinya karena pemeriksaan di bawah menjadi tidak berlaku.
    """
    # 1. safe_harness tidak mem-patch firewall -> firewall_status masih nyata
    #    (di mesin dengan ufw, tanpa root bisa memicu pkexec = prompt grafis).
    try:
        import inspect
        src = inspect.getsource(safe_harness)
    except Exception:                                          # noqa: BLE001
        src = ""
    if "firewall_status" not in src and "_firewall_tool" not in src:
        warn("safe_harness BELUM men-stub firewall_status/_firewall_tool; "
             "test yang memanggil firewall_status bisa memicu pkexec "
             "(prompt grafis) di mesin ber-ufw tanpa root - rekomendasi: "
             "tambahkan stub ke safe_harness")
    # 2. mode sandbox tidak men-stub volume_set -> volset via --sandbox
    #    masih mengubah volume sungguhan.
    if "volume_set" not in getattr(system_ctl, "__doc__", "") \
            and not _sandbox_volume_guarded():
        warn("mode --sandbox BELUM mensimulasikan volume_set/volume_mute; "
             "pesan volset/media-mute tetap menyentuh wpctl/pactl/amixer "
             "nyata - rekomendasi: tambahkan cabang SANDBOX di volume_set")


def _sandbox_volume_guarded():
    """True kalau implementasi volume_set sudah punya cabang sandbox."""
    try:
        import inspect
        src = inspect.getsource(core.volume_set)
        return "SANDBOX" in src
    except Exception:                                          # noqa: BLE001
        return False


def main():
    print("=== JARING PENGAMAN: aksi sistem-nyata dilarang di test ===")
    test_harness_memblokir_semua_aksi_sistem()
    test_harness_tidak_menjalankan_subprocess_nyata()
    test_gerbang_claudepad_allow_real()
    test_assert_no_real_calls_gagal_saat_ada_eksekusi_nyata()
    test_harness_activate_restore_idempotent()
    test_mode_sandbox_menyimulasikan_tanpa_subprocess()
    test_harness_stub_clipboard_mpris()
    test_sandbox_clipboard_mpris()
    test_pola_perintah_berbahaya_lengkap()
    catat_gap_firewall_dan_volume()

    # Pastikan tidak ada jejak: harness dan sandbox nonaktif di akhir.
    safe_harness.restore()
    core.set_sandbox(False)
    os.environ.pop("CLAUDEPAD_ALLOW_REAL", None)

    print()
    if WARNINGS:
        print(f"{len(WARNINGS)} CATATAN (tidak menggagalkan):")
        for w in WARNINGS:
            print(f"  - {w}")
        print()
    if FAILED:
        print(f"{len(FAILED)} UJI KEAMANAN GAGAL:")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print("SEMUA UJI KEAMANAN LULUS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
