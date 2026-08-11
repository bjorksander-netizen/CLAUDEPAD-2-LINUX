#!/usr/bin/env python3
"""
safe_harness - mock harness aman untuk test server CLAUDEPAD Linux.

Latar belakang: test pernah mengeksekusi aksi sistem NYATA di desktop
pengembang - power_action("lock"/"screenoff") mengunci layar dan
toggle_radio("wifi"/"bluetooth"/"hotspot") memutus jaringan. Harness ini
memastikan hal itu TIDAK BISA terjadi lagi:

  * `activate()` mem-patch semua fungsi berdampak-nyata menjadi stub:
    - daya/kecerahan (system_ctl.power_action, brightness_step, _lock_session,
      _screen_off, _logoff, setter kecerahan),
    - radio (input_core.toggle_radio, _nmcli_radio, _rfkill_toggle,
      _wifi_device),
    - volume (volume_set, volume_mute_toggle),
    - firewall (firewall_status, fix_firewall, _firewall_tool - mencegah
      pkexec memunculkan prompt grafis),
    - backend input (init_backend dipaksa "none", BACKEND=Null) sehingga
      TIDAK ada injeksi kursor/tombol nyata,
    - path data (paths.config_dir/data_path/state_dir + pc_server._PAIR_FILE
      diarahkan ke temp dir) sehingga test TIDAK menyentuh ~/.config/claudepad.
  * Stub TIDAK PERNAH menyentuh sistem:
      - tanpa env CLAUDEPAD_ALLOW_REAL=1  -> mengembalikan nilai simulasi
        dengan bentuk yang benar ((bool, str)) sehingga test yang
        memverifikasi FORMAT balasan tetap valid;
      - dengan env itu (HANYA di lingkungan terisolasi/CI) -> meneruskan
        ke fungsi asli (eksekusi nyata).
  * Setiap pemanggilan dicatat di SIMULATED / REAL_CALLS supaya test bisa
    membuktikan bahwa tidak ada aksi nyata yang dijalankan.

Pakai: panggil `safe_harness.activate()` di awal main() tiap test, sekali.
"""
import os
import sys
import tempfile

REAL_ENV = "CLAUDEPAD_ALLOW_REAL"

# Daftar pemanggilan: [(modul, nama, args, kwargs), ...]
SIMULATED = []   # aksi yang disimulasikan (tidak menyentuh sistem)
REAL_CALLS = []  # aksi yang diteruskan ke fungsi asli (butuh env izin)

_ORIGINALS = {}
_ACTIVE = False
_BACKEND_STATE = {}
_VARS = {}
_TEMP_DIR = None

_KNOWN_POWER_ACTIONS = {"shutdown", "restart", "sleep", "hibernate",
                        "logoff", "lock", "screenoff"}
_KNOWN_RADIO_DEVS = {"wifi", "bluetooth", "hotspot"}


def real_allowed():
    """True hanya kalau env CLAUDEPAD_ALLOW_REAL == '1'. Default: nonaktif."""
    return os.environ.get(REAL_ENV) == "1"


def allow_real(flag=True):
    """Atur izin eksekusi nyata. Dipakai hanya untuk membuktikan guard."""
    if flag:
        os.environ[REAL_ENV] = "1"
    else:
        os.environ.pop(REAL_ENV, None)


# ---------------------------------------------------------- Simulator -------
# Semua stub mengembalikan nilai dengan BENTUK yang sama seperti fungsi
# aslinya, supaya test yang memverifikasi format balasan tetap valid.
def _sim_power_action(action, *args, **kwargs):
    if action in _KNOWN_POWER_ACTIONS:
        return True, f"simulasi power_action({action}) (safe_harness)"
    return False, "aksi daya tidak dikenal"


def _sim_brightness_step(delta, *args, **kwargs):
    return True, f"simulasi brightness_step({delta}) (safe_harness)"


def _sim_toggle_radio(which, *args, **kwargs):
    if which in _KNOWN_RADIO_DEVS:
        return True, f"simulasi radio {which} (safe_harness)"
    return False, "perangkat tidak dikenal"


def _sim_nmcli_radio(which, *args, **kwargs):
    return True, f"simulasi nmcli radio {which} (safe_harness)"


def _sim_rfkill_toggle(kind, *args, **kwargs):
    return True, f"simulasi rfkill {kind} (safe_harness)"


def _sim_wifi_device(*args, **kwargs):
    return ""


def _sim_volume_set(percent, *args, **kwargs):
    return True


def _sim_volume_mute_toggle(*args, **kwargs):
    return True


def _sim_lock_session(*args, **kwargs):
    return True, "simulasi lock (safe_harness)"


def _sim_screen_off(*args, **kwargs):
    return True, "simulasi screenoff (safe_harness)"


def _sim_logoff(*args, **kwargs):
    return True, "simulasi logoff (safe_harness)"


def _sim_firewall_status(*args, **kwargs):
    return True


def _sim_fix_firewall(*args, **kwargs):
    return True


def _sim_firewall_tool(*args, **kwargs):
    return ""


def _sim_init_backend(prefer=None, *args, **kwargs):
    """Backend input dipaksa 'none' - TIDAK ada injeksi kursor/tombol."""
    return "none"


# ---- v3.7: clipboard & MPRIS (harus bisa di-mock, OPEN-CONVENTIONS B4) ----
def _sim_clipboard_read(*args, **kwargs):
    return ""


def _sim_clipboard_write(text, *args, **kwargs):
    return True


def _sim_clipboard_available(*args, **kwargs):
    return True


def _sim_mpris_query(*args, **kwargs):
    return {"ok": False, "title": "", "artist": "", "album": "",
            "playing": False, "length_us": 0, "pos_us": 0,
            "canseek": False, "trackid": "",
            "msg": "simulasi mpris.query (safe_harness)"}


def _sim_mpris_seek(pos_us, *args, **kwargs):
    return True, f"simulasi mpris.seek({pos_us}) (safe_harness)"


def _sim_mpris_available(*args, **kwargs):
    return True


# ---- Isolasi path data: test tidak boleh menyentuh ~/.config/claudepad. ----
def _temp_dir():
    global _TEMP_DIR
    if _TEMP_DIR is None:
        _TEMP_DIR = tempfile.mkdtemp(prefix="claudepad-test-")
    return _TEMP_DIR


def _sim_config_dir(*args, **kwargs):
    return _temp_dir()


def _sim_data_path(name, *args, **kwargs):
    return os.path.join(_temp_dir(), name)


def _sim_state_dir(*args, **kwargs):
    return _temp_dir()


def _save_backend_state():
    import input_core
    _BACKEND_STATE["BACKEND"] = input_core.BACKEND
    _BACKEND_STATE["BACKEND_NOTE"] = input_core.BACKEND_NOTE


def _restore_backend_state():
    import input_core
    if _BACKEND_STATE:
        input_core.BACKEND = _BACKEND_STATE["BACKEND"]
        input_core.BACKEND_NOTE = _BACKEND_STATE["BACKEND_NOTE"]
        _BACKEND_STATE.clear()


def _save_var(module, name):
    """Simpan nilai variabel modul untuk dipulihkan di restore()."""
    _VARS[(module.__name__, name)] = getattr(module, name)


def _restore_vars():
    for (mod_name, name), val in _VARS.items():
        mod = sys.modules.get(mod_name)
        if mod is not None:
            setattr(mod, name, val)
    _VARS.clear()


# ----------------------------------------------------------- Pemasangan -----
def _install(module, name, simulator):
    """Pasang stub pada module.name. Fungsi asli disimpan sekali saja."""
    key = (module.__name__, name)
    if key not in _ORIGINALS:
        _ORIGINALS[key] = getattr(module, name)
    real = _ORIGINALS[key]

    def stub(*args, **kwargs):
        if real_allowed():
            REAL_CALLS.append((module.__name__, name, args, kwargs))
            return real(*args, **kwargs)
        SIMULATED.append((module.__name__, name, args, kwargs))
        return simulator(*args, **kwargs)

    stub.__name__ = name
    stub.__doc__ = (f"Stub aman (safe_harness) untuk "
                    f"{module.__name__}.{name} - tidak menyentuh sistem.")
    setattr(module, name, stub)


def activate():
    """
    Pasang stub aman untuk semua fungsi berdampak-nyata. Idempotent:
    aman dipanggil berkali-kali dan dari test mana pun.
    """
    global _ACTIVE
    if _ACTIVE:
        return
    import clipboard
    import input_core
    import mpris
    import paths
    import system_ctl    # Daya & kecerahan (system_ctl) - termasuk jalur internal yang berbahaya.
    _install(system_ctl, "power_action", _sim_power_action)
    _install(system_ctl, "brightness_step", _sim_brightness_step)
    _install(system_ctl, "_lock_session", _sim_lock_session)
    _install(system_ctl, "_screen_off", _sim_screen_off)
    _install(system_ctl, "_logoff", _sim_logoff)
    _install(system_ctl, "_sysfs_set", lambda *a, **k: False)
    _install(system_ctl, "_brightnessctl_set", lambda *a, **k: False)
    _install(system_ctl, "_light_set", lambda *a, **k: False)
    _install(system_ctl, "_ddc_set", lambda *a, **k: False)

    # Radio (input_core) beserta pembantunya.
    _install(input_core, "toggle_radio", _sim_toggle_radio)
    _install(input_core, "_nmcli_radio", _sim_nmcli_radio)
    _install(input_core, "_rfkill_toggle", _sim_rfkill_toggle)
    _install(input_core, "_wifi_device", _sim_wifi_device)

    # Volume: mengubah volume sistem juga efek nyata di desktop.
    _install(input_core, "volume_set", _sim_volume_set)
    _install(input_core, "volume_mute_toggle", _sim_volume_mute_toggle)

    # Firewall (GAP #1): firewall_status dapat memicu pkexec = prompt grafis.
    _install(input_core, "firewall_status", _sim_firewall_status)
    _install(input_core, "fix_firewall", _sim_fix_firewall)
    _install(input_core, "_firewall_tool", _sim_firewall_tool)

    # Backend input (GAP #2): paksa "none" supaya TIDAK ada injeksi
    # kursor/tombol nyata lewat uinput/XTEST/xdotool di jalur test.
    _install(input_core, "init_backend", _sim_init_backend)
    _save_backend_state()
    input_core.BACKEND = input_core._NullBackend()

    # Isolasi path data (rekomendasi): test TIDAK boleh menulis ke
    # ~/.config/claudepad (token pairing, gestures) pengguna sungguhan.
    _install(paths, "config_dir", _sim_config_dir)
    _install(paths, "data_path", _sim_data_path)
    _install(paths, "state_dir", _sim_state_dir)

    # pc_server menghitung _PAIR_FILE saat import (bukan runtime), jadi
    # patch paths.data_path tidak cukup - arahkan ke temp dir secara
    # langsung, dan matikan keyring agar token tidak bocor ke keyring
    # pengguna sungguhan (fallback menulis ke file temp).
    import pc_server
    _save_var(pc_server, "_PAIR_FILE")
    pc_server._PAIR_FILE = os.path.join(_temp_dir(), "paired.txt")
    _save_var(pc_server, "_KEYRING_AVAILABLE")
    pc_server._KEYRING_AVAILABLE = False

    # v3.7 - Clipboard & MPRIS: stub membaca/menulis clipboard dan query/seek
    # pemutar. Stub `_run` kedua modul dijadikan jaring pengaman kedua supaya
    # TIDAK ADA subprocess (wl-paste, xclip, gdbus, playerctl) di jalur test.
    _install(clipboard, "read", _sim_clipboard_read)
    _install(clipboard, "write", _sim_clipboard_write)
    _install(clipboard, "available", _sim_clipboard_available)
    _install(clipboard, "_run", lambda *a, **k: (127, ""))
    _install(clipboard, "_run_with_input", lambda *a, **k: (127, ""))
    _install(mpris, "query", _sim_mpris_query)
    _install(mpris, "seek", _sim_mpris_seek)
    _install(mpris, "available", _sim_mpris_available)
    _install(mpris, "_run", lambda *a, **k: (127, ""))
    _ACTIVE = True


def restore():
    """Kembalikan semua fungsi asli. Idempotent."""
    global _ACTIVE
    for (mod_name, name), orig in _ORIGINALS.items():
        mod = sys.modules.get(mod_name)
        if mod is not None:
            setattr(mod, name, orig)
    _ORIGINALS.clear()
    _restore_backend_state()
    _restore_vars()
    _ACTIVE = False


def assert_no_real_calls():
    """
    Gagal (AssertionError) kalau ada eksekusi nyata yang tercatat.
    Tanpa CLAUDEPAD_ALLOW_REAL=1, REAL_CALLS harus selalu kosong.
    """
    if REAL_CALLS:
        raise AssertionError(
            f"{len(REAL_CALLS)} aksi sistem NYATA dieksekusi oleh test: "
            f"{REAL_CALLS!r}. Tanpa {REAL_ENV}=1 eksekusi nyata dilarang.")


def simulated():
    """Ringkasan pemanggilan yang disimulasikan: [(modul.nama(args)), ...]."""
    return [f"{m}.{n}({', '.join(map(repr, a))})"
            for m, n, a, _k in SIMULATED]
