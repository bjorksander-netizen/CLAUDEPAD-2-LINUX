#!/usr/bin/env python3
"""
CLAUDEPAD LINUX - injeksi input, volume, gesture, discovery, firewall.

Protokolnya identik dengan versi Windows; yang berganti hanya lapisan paling
bawah. Ada tiga backend input, dicoba berurutan:

  1. uinput (python-evdev)  - membuat perangkat virtual di kernel.
     Satu-satunya cara yang bekerja di Wayland MAUPUN X11, jadi ini utama.
     Butuh akses tulis ke /dev/uinput (lihat 99-claudepad-uinput.rules).
  2. XTEST (python-xlib)    - hanya X11, tapi tidak butuh izin khusus.
  3. xdotool                - proses luar, paling lambat; jaring pengaman
     terakhir dan tetap berguna untuk mengetik karakter non-ASCII di X11.

Roda scroll memakai sumbu hi-res kernel (REL_WHEEL_HI_RES) yang satuannya
1/120 notch - kebetulan persis sama dengan WHEEL_DELTA milik Windows, jadi
angka dari HP dipakai apa adanya tanpa pembulatan yang membuat scroll patah.
"""

import json
import os
import queue
import random
import shutil
import socket
import subprocess
import time

from paths import resource_path, data_path

import clipboard
import mpris
import system_ctl

WS_PORT = 8765
DISCOVERY_PORT = 8766

PLATFORM = "linux"

PIN = f"{random.randint(0, 99999999):08d}"
CLIENTS = {}          # peer -> transport ("wifi" / "usb")
LOGQ = queue.Queue()
HOSTNAME = socket.gethostname()

# Dipertahankan agar kode yang di-port dari versi Windows tetap terbaca:
# nilainya selalu False di sini dan dipakai untuk mematikan cabang khusus
# Windows (mis. indikator scrollbar Win32).
IS_WINDOWS = False

# -- Rate limiting: anti brute-force PIN (identik dengan versi Windows) --
FAILED_ATTEMPTS = {}  # ip -> [waktu_gagal, ...]
MAX_FAILED = 3
LOCKOUT_SECONDS = 30
WINDOW_SECONDS = 60


def log(msg):
    LOGQ.put(msg)


def new_pin():
    global PIN
    PIN = f"{random.randint(0, 99999999):08d}"
    return PIN


def check_rate_limit(ip):
    """True kalau IP boleh mencoba autentikasi, False kalau sedang diblokir."""
    now = time.time()
    attempts = [t for t in FAILED_ATTEMPTS.get(ip, []) if now - t < WINDOW_SECONDS]
    FAILED_ATTEMPTS[ip] = attempts
    if len(attempts) >= MAX_FAILED:
        elapsed = now - attempts[0]
        if elapsed < LOCKOUT_SECONDS:
            log(f"[!] {ip} diblokir {int(LOCKOUT_SECONDS - elapsed)}s lagi "
                f"({len(attempts)} gagal)")
            return False
        FAILED_ATTEMPTS[ip] = []
    return True


def record_failed_attempt(ip):
    FAILED_ATTEMPTS.setdefault(ip, []).append(time.time())
    log(f"[!] {ip} gagal autentikasi ({len(FAILED_ATTEMPTS[ip])}/{MAX_FAILED})")


def reset_failed_attempts(ip):
    FAILED_ATTEMPTS.pop(ip, None)


def _has(cmd):
    return shutil.which(cmd) is not None


def _run(args, timeout=10):
    """Jalankan perintah, kembalikan (returncode, stdout+stderr)."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except FileNotFoundError:
        return 127, f"{args[0]} tidak ditemukan"
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:                                    # noqa: BLE001
        return 1, str(e)


# =========================================================== Sesi desktop ====
def session_type():
    """'wayland', 'x11', atau 'tty' - menentukan backend yang masuk akal."""
    t = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if t in ("wayland", "x11"):
        return t
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "tty"


def desktop_name():
    """Nama desktop environment sebagaimana dilaporkan sesi, mis. 'GNOME'."""
    for var in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION"):
        v = os.environ.get(var)
        if v:
            return v.split(":")[0].strip()
    return "unknown"


def _desktop_key():
    d = desktop_name().lower()
    for key in ("gnome", "kde", "plasma", "xfce", "cinnamon", "mate",
                "budgie", "lxqt", "sway", "hyprland", "i3"):
        if key in d:
            return "kde" if key == "plasma" else key
    return "unknown"


# ============================================================ Peta tombol ====
# Nama tombol di protokol -> nama konstanta evdev, dan -> keysym X11.
# Keduanya harus sinkron: HP mengirim nama yang sama ke backend mana pun.
_EVDEV_KEYS = {
    "enter": "KEY_ENTER", "esc": "KEY_ESC", "tab": "KEY_TAB",
    "backspace": "KEY_BACKSPACE", "delete": "KEY_DELETE", "space": "KEY_SPACE",
    "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
    "home": "KEY_HOME", "end": "KEY_END", "pgup": "KEY_PAGEUP",
    "pgdn": "KEY_PAGEDOWN", "win": "KEY_LEFTMETA", "ctrl": "KEY_LEFTCTRL",
    "alt": "KEY_LEFTALT", "shift": "KEY_LEFTSHIFT", "insert": "KEY_INSERT",
    "capslock": "KEY_CAPSLOCK", "printscreen": "KEY_SYSRQ", "d": "KEY_D",
    **{f"f{i}": f"KEY_F{i}" for i in range(1, 13)},
}

_X11_KEYS = {
    "enter": "Return", "esc": "Escape", "tab": "Tab", "backspace": "BackSpace",
    "delete": "Delete", "space": "space", "up": "Up", "down": "Down",
    "left": "Left", "right": "Right", "home": "Home", "end": "End",
    "pgup": "Prior", "pgdn": "Next", "win": "Super_L", "ctrl": "Control_L",
    "alt": "Alt_L", "shift": "Shift_L", "insert": "Insert",
    "capslock": "Caps_Lock", "printscreen": "Print", "d": "d",
    **{f"f{i}": f"F{i}" for i in range(1, 13)},
}

MEDIA_EVDEV = {
    "playpause": "KEY_PLAYPAUSE", "next": "KEY_NEXTSONG",
    "prev": "KEY_PREVIOUSSONG", "stop": "KEY_STOPCD",
    "volup": "KEY_VOLUMEUP", "voldown": "KEY_VOLUMEDOWN", "mute": "KEY_MUTE",
}

MEDIA_X11 = {
    "playpause": "XF86AudioPlay", "next": "XF86AudioNext",
    "prev": "XF86AudioPrev", "stop": "XF86AudioStop",
    "volup": "XF86AudioRaiseVolume", "voldown": "XF86AudioLowerVolume",
    "mute": "XF86AudioMute",
}

# Peta karakter ASCII -> (nama tombol evdev, perlu shift) untuk tata letak
# QWERTY-US. Dipakai HANYA oleh backend uinput, karena uinput mengirim
# scancode mentah dan tidak tahu-menahu soal tata letak. Untuk karakter di
# luar tabel ini, teks dialihkan ke wtype/xdotool yang sadar tata letak.
_ASCII_UNSHIFTED = {
    "a": "KEY_A", "b": "KEY_B", "c": "KEY_C", "d": "KEY_D", "e": "KEY_E",
    "f": "KEY_F", "g": "KEY_G", "h": "KEY_H", "i": "KEY_I", "j": "KEY_J",
    "k": "KEY_K", "l": "KEY_L", "m": "KEY_M", "n": "KEY_N", "o": "KEY_O",
    "p": "KEY_P", "q": "KEY_Q", "r": "KEY_R", "s": "KEY_S", "t": "KEY_T",
    "u": "KEY_U", "v": "KEY_V", "w": "KEY_W", "x": "KEY_X", "y": "KEY_Y",
    "z": "KEY_Z",
    "1": "KEY_1", "2": "KEY_2", "3": "KEY_3", "4": "KEY_4", "5": "KEY_5",
    "6": "KEY_6", "7": "KEY_7", "8": "KEY_8", "9": "KEY_9", "0": "KEY_0",
    " ": "KEY_SPACE", "\t": "KEY_TAB", "\n": "KEY_ENTER",
    "-": "KEY_MINUS", "=": "KEY_EQUAL", "[": "KEY_LEFTBRACE",
    "]": "KEY_RIGHTBRACE", "\\": "KEY_BACKSLASH", ";": "KEY_SEMICOLON",
    "'": "KEY_APOSTROPHE", "`": "KEY_GRAVE", ",": "KEY_COMMA",
    ".": "KEY_DOT", "/": "KEY_SLASH",
}

_ASCII_SHIFTED = {
    "!": "KEY_1", "@": "KEY_2", "#": "KEY_3", "$": "KEY_4", "%": "KEY_5",
    "^": "KEY_6", "&": "KEY_7", "*": "KEY_8", "(": "KEY_9", ")": "KEY_0",
    "_": "KEY_MINUS", "+": "KEY_EQUAL", "{": "KEY_LEFTBRACE",
    "}": "KEY_RIGHTBRACE", "|": "KEY_BACKSLASH", ":": "KEY_SEMICOLON",
    '"': "KEY_APOSTROPHE", "~": "KEY_GRAVE", "<": "KEY_COMMA",
    ">": "KEY_DOT", "?": "KEY_SLASH",
    **{c.upper(): f"KEY_{c.upper()}" for c in "abcdefghijklmnopqrstuvwxyz"},
}


# ============================================================== Backend ======
class _Backend:
    """Antarmuka bersama semua backend input."""

    name = "none"
    available = False

    def move(self, dx, dy): ...
    def button(self, btn, press): ...
    def scroll(self, dy=0, dx=0): ...
    def key(self, name, press): ...
    def tap(self, name, mods=()): ...
    def text(self, s): ...
    def media(self, action): ...
    def close(self): ...


class _NullBackend(_Backend):
    """Dipakai di CI dan di mesin tanpa akses input. Semua panggilan no-op."""

    name = "none"
    available = False

    def __getattr__(self, _n):
        return lambda *a, **k: None


class UinputBackend(_Backend):
    """Perangkat virtual kernel. Bekerja di Wayland dan X11."""

    name = "uinput"

    def __init__(self):
        from evdev import UInput, ecodes as e            # noqa: PLC0415
        self._e = e

        # Dua perangkat terpisah: compositor (libinput) mengelompokkan
        # perangkat berdasarkan kapabilitasnya. Perangkat gabungan
        # keyboard+mouse kadang salah diklasifikasi dan pointer-nya diabaikan.
        pointer_caps = {
            e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
            e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL],
        }
        # Sumbu hi-res baru ada di kernel modern; kalau tidak ada, cukup
        # pakai sumbu klasik.
        self.hi_res = hasattr(e, "REL_WHEEL_HI_RES") and hasattr(e, "REL_HWHEEL_HI_RES")
        if self.hi_res:
            pointer_caps[e.EV_REL] += [e.REL_WHEEL_HI_RES, e.REL_HWHEEL_HI_RES]

        key_caps = {e.EV_KEY: sorted(
            {v for k, v in e.ecodes.items()
             if k.startswith("KEY_") and isinstance(v, int) and 0 < v < 0x2ff}
        )}

        self.pointer = UInput(pointer_caps, name="CLAUDEPAD Virtual Pointer",
                              vendor=0xC1AD, product=0x0001, version=1)
        self.keyboard = UInput(key_caps, name="CLAUDEPAD Virtual Keyboard",
                               vendor=0xC1AD, product=0x0002, version=1)
        self._wheel_acc = 0
        self._hwheel_acc = 0
        self.available = True

    # -- pointer --
    def move(self, dx, dy):
        e = self._e
        dx, dy = int(dx), int(dy)
        if dx:
            self.pointer.write(e.EV_REL, e.REL_X, dx)
        if dy:
            self.pointer.write(e.EV_REL, e.REL_Y, dy)
        if dx or dy:
            self.pointer.syn()

    _BTN = {"left": "BTN_LEFT", "right": "BTN_RIGHT", "middle": "BTN_MIDDLE"}

    def button(self, btn, press):
        e = self._e
        code = getattr(e, self._BTN.get(btn, "BTN_LEFT"))
        self.pointer.write(e.EV_KEY, code, 1 if press else 0)
        self.pointer.syn()

    def scroll(self, dy=0, dx=0):
        """dy/dx dalam satuan WHEEL_DELTA Windows (120 = satu notch)."""
        e = self._e
        dy, dx = int(dy), int(dx)
        if not dy and not dx:
            return
        if self.hi_res:
            if dy:
                self.pointer.write(e.EV_REL, e.REL_WHEEL_HI_RES, dy)
            if dx:
                self.pointer.write(e.EV_REL, e.REL_HWHEEL_HI_RES, dx)
        # Banyak aplikasi lama hanya membaca sumbu klasik, jadi sisa
        # akumulasi tetap dipancarkan sebagai notch bulat.
        self._wheel_acc += dy
        self._hwheel_acc += dx
        notches_y, self._wheel_acc = divmod_signed(self._wheel_acc, 120)
        notches_x, self._hwheel_acc = divmod_signed(self._hwheel_acc, 120)
        if notches_y:
            self.pointer.write(e.EV_REL, e.REL_WHEEL, notches_y)
        if notches_x:
            self.pointer.write(e.EV_REL, e.REL_HWHEEL, notches_x)
        self.pointer.syn()

    # -- keyboard --
    def _code(self, evdev_name):
        return getattr(self._e, evdev_name, None)

    def key(self, name, press):
        code = self._code(_EVDEV_KEYS.get(name, ""))
        if code is None:
            return
        self.keyboard.write(self._e.EV_KEY, code, 1 if press else 0)
        self.keyboard.syn()

    def _tap_code(self, code, mod_codes=()):
        e = self._e
        for m in mod_codes:
            self.keyboard.write(e.EV_KEY, m, 1)
        self.keyboard.write(e.EV_KEY, code, 1)
        self.keyboard.write(e.EV_KEY, code, 0)
        for m in reversed(list(mod_codes)):
            self.keyboard.write(e.EV_KEY, m, 0)
        self.keyboard.syn()

    def tap(self, name, mods=()):
        mod_codes = [self._code(_EVDEV_KEYS.get(m, "")) for m in mods]
        mod_codes = [c for c in mod_codes if c is not None]
        evname = _EVDEV_KEYS.get(name)
        if evname is None and len(name) == 1:
            return self._type_char(name, mod_codes)
        code = self._code(evname or "")
        if code is None:
            return
        self._tap_code(code, mod_codes)

    def _type_char(self, ch, extra_mods=()):
        """Ketik satu karakter ASCII lewat tata letak QWERTY-US."""
        shift = False
        evname = _ASCII_UNSHIFTED.get(ch)
        if evname is None:
            evname = _ASCII_SHIFTED.get(ch)
            shift = evname is not None
        if evname is None:
            return False
        code = self._code(evname)
        if code is None:
            return False
        mods = list(extra_mods)
        if shift:
            mods.append(self._code("KEY_LEFTSHIFT"))
        self._tap_code(code, [m for m in mods if m is not None])
        return True

    def text(self, s):
        for ch in s:
            if not self._type_char(ch):
                # Karakter di luar QWERTY-US - serahkan ke alat yang
                # sadar tata letak. Kalau tidak ada, karakter dilewati
                # dan pengguna diberi tahu sekali.
                if not _type_text_external(ch):
                    log(f"[!] karakter '{ch}' butuh wtype (Wayland) atau "
                        f"xdotool (X11) - dilewati")

    def media(self, action):
        code = self._code(MEDIA_EVDEV.get(action, ""))
        if code is None:
            return
        self._tap_code(code)

    def close(self):
        for dev in (getattr(self, "pointer", None), getattr(self, "keyboard", None)):
            try:
                dev.close()
            except Exception:                                  # noqa: BLE001
                pass


class XtestBackend(_Backend):
    """XTEST lewat python-xlib. Hanya X11, tapi tanpa izin khusus."""

    name = "xtest"

    def __init__(self):
        from Xlib import display, X                          # noqa: PLC0415
        from Xlib.ext import xtest                           # noqa: PLC0415
        self._X = X
        self._xtest = xtest
        self.dpy = display.Display()
        self._wheel_acc = 0
        self._hwheel_acc = 0
        self.available = True

    _xf86_loaded = False

    def _keycode(self, keysym_name):
        from Xlib import XK                                  # noqa: PLC0415
        if not XtestBackend._xf86_loaded:
            # Keysym XF86* (tombol media) tidak dimuat python-xlib secara
            # default, jadi harus diminta sekali.
            try:
                XK.load_keysym_group("xf86")
            except Exception:                                  # noqa: BLE001
                pass
            XtestBackend._xf86_loaded = True
        sym = XK.string_to_keysym(keysym_name)
        if sym == 0 and keysym_name.startswith("XF86"):
            # xdotool dan xmodmap menulis "XF86AudioPlay"; python-xlib
            # menamainya "XF86_AudioPlay". Peta kami memakai ejaan xdotool
            # karena itu yang lazim, jadi di sini diterjemahkan.
            sym = XK.string_to_keysym("XF86_" + keysym_name[4:])
        if sym == 0:
            return None
        kc = self.dpy.keysym_to_keycode(sym)
        return kc or None

    def move(self, dx, dy):
        self._xtest.fake_input(self.dpy, self._X.MotionNotify, detail=True,
                               x=int(dx), y=int(dy))
        self.dpy.sync()

    _BTN = {"left": 1, "middle": 2, "right": 3}

    def button(self, btn, press):
        n = self._BTN.get(btn, 1)
        self._xtest.fake_input(
            self.dpy,
            self._X.ButtonPress if press else self._X.ButtonRelease, n)
        self.dpy.sync()

    def _click_button(self, n, times):
        for _ in range(times):
            self._xtest.fake_input(self.dpy, self._X.ButtonPress, n)
            self._xtest.fake_input(self.dpy, self._X.ButtonRelease, n)
        self.dpy.sync()

    def scroll(self, dy=0, dx=0):
        self._wheel_acc += int(dy)
        self._hwheel_acc += int(dx)
        ny, self._wheel_acc = divmod_signed(self._wheel_acc, 120)
        nx, self._hwheel_acc = divmod_signed(self._hwheel_acc, 120)
        if ny:
            self._click_button(4 if ny > 0 else 5, abs(ny))
        if nx:
            self._click_button(7 if nx > 0 else 6, abs(nx))

    def key(self, name, press):
        kc = self._keycode(_X11_KEYS.get(name, ""))
        if kc is None:
            return
        self._xtest.fake_input(
            self.dpy, self._X.KeyPress if press else self._X.KeyRelease, kc)
        self.dpy.sync()

    def _tap_keycode(self, kc, mod_names=()):
        mods = [self._keycode(_X11_KEYS.get(m, "")) for m in mod_names]
        mods = [m for m in mods if m]
        for m in mods:
            self._xtest.fake_input(self.dpy, self._X.KeyPress, m)
        self._xtest.fake_input(self.dpy, self._X.KeyPress, kc)
        self._xtest.fake_input(self.dpy, self._X.KeyRelease, kc)
        for m in reversed(mods):
            self._xtest.fake_input(self.dpy, self._X.KeyRelease, m)
        self.dpy.sync()

    def tap(self, name, mods=()):
        keysym = _X11_KEYS.get(name, name if len(name) == 1 else "")
        kc = self._keycode(keysym)
        if kc is None:
            return
        self._tap_keycode(kc, mods)

    def text(self, s):
        # xdotool jauh lebih baik dalam menangani karakter di luar tata
        # letak aktif karena bisa memetakan ulang keycode sementara.
        if _type_text_external(s):
            return
        for ch in s:
            self.tap(ch if ch != "\n" else "enter")

    def media(self, action):
        kc = self._keycode(MEDIA_X11.get(action, ""))
        if kc is None:
            return
        self._tap_keycode(kc)

    def close(self):
        try:
            self.dpy.close()
        except Exception:                                      # noqa: BLE001
            pass


class XdotoolBackend(_Backend):
    """Jaring pengaman terakhir: memanggil xdotool untuk tiap perintah."""

    name = "xdotool"

    def __init__(self):
        if not _has("xdotool"):
            raise RuntimeError("xdotool tidak terpasang")
        # Tanpa DISPLAY, xdotool gagal diam-diam untuk SETIAP perintah.
        # Lebih baik menolak di sini supaya server melaporkan "tidak ada
        # backend" daripada berpura-pura bekerja.
        if not os.environ.get("DISPLAY"):
            raise RuntimeError("DISPLAY tidak diset (sesi bukan X11)")
        self._wheel_acc = 0
        self._hwheel_acc = 0
        self.available = True

    @staticmethod
    def _x(*args):
        subprocess.run(["xdotool", *args], capture_output=True, timeout=5)

    def move(self, dx, dy):
        self._x("mousemove_relative", "--", str(int(dx)), str(int(dy)))

    _BTN = {"left": "1", "middle": "2", "right": "3"}

    def button(self, btn, press):
        self._x("mousedown" if press else "mouseup", self._BTN.get(btn, "1"))

    def scroll(self, dy=0, dx=0):
        self._wheel_acc += int(dy)
        self._hwheel_acc += int(dx)
        ny, self._wheel_acc = divmod_signed(self._wheel_acc, 120)
        nx, self._hwheel_acc = divmod_signed(self._hwheel_acc, 120)
        for _ in range(abs(ny)):
            self._x("click", "4" if ny > 0 else "5")
        for _ in range(abs(nx)):
            self._x("click", "7" if nx > 0 else "6")

    def key(self, name, press):
        sym = _X11_KEYS.get(name, name)
        self._x("keydown" if press else "keyup", sym)

    def tap(self, name, mods=()):
        sym = _X11_KEYS.get(name, name)
        combo = "+".join([_X11_KEYS.get(m, m) for m in mods] + [sym])
        self._x("key", "--clearmodifiers", combo)

    def text(self, s):
        self._x("type", "--clearmodifiers", "--delay", "8", "--", s)

    def media(self, action):
        sym = MEDIA_X11.get(action)
        if sym:
            self._x("key", sym)


def divmod_signed(total, step):
    """Bagi menuju nol supaya sisa scroll tidak pernah berbalik arah."""
    whole = int(total / step)
    return whole, total - whole * step


def _type_text_external(s):
    """Ketik teks lewat wtype (Wayland) atau xdotool (X11). True kalau sukses."""
    if session_type() == "wayland" and _has("wtype"):
        rc, _ = _run(["wtype", s], timeout=15)
        return rc == 0
    if _has("xdotool") and os.environ.get("DISPLAY"):
        rc, _ = _run(["xdotool", "type", "--clearmodifiers",
                      "--delay", "8", "--", s], timeout=20)
        return rc == 0
    return False


BACKEND = _NullBackend()
BACKEND_NOTE = "belum diinisialisasi"


def init_backend(prefer=None):
    """
    Pilih backend input terbaik yang tersedia.
    `prefer` boleh 'uinput', 'xtest', 'xdotool', atau None (otomatis).
    Mengembalikan nama backend yang terpilih.
    """
    global BACKEND, BACKEND_NOTE
    if SANDBOX:
        # Mode uji: TIDAK BOLEH membuat perangkat virtual / koneksi X nyata.
        BACKEND = _NullBackend()
        BACKEND_NOTE = "sandbox: backend input dinonaktifkan"
        log(f"[i] {BACKEND_NOTE}")
        return "none"
    order = ["uinput", "xtest", "xdotool"]
    if prefer in order:
        order = [prefer] + [o for o in order if o != prefer]

    problems = []
    for name in order:
        try:
            if name == "uinput":
                BACKEND = UinputBackend()
            elif name == "xtest":
                if not os.environ.get("DISPLAY"):
                    raise RuntimeError("DISPLAY tidak diset (sesi bukan X11)")
                BACKEND = XtestBackend()
            else:
                BACKEND = XdotoolBackend()
            BACKEND_NOTE = f"backend input: {BACKEND.name}"
            log(f"[i] {BACKEND_NOTE}")
            return BACKEND.name
        except PermissionError:
            problems.append(f"{name}: izin ditolak (/dev/uinput) - "
                            f"jalankan server/install.sh")
        except ImportError as e:
            problems.append(f"{name}: modul belum terpasang ({e})")
        except Exception as e:                                 # noqa: BLE001
            problems.append(f"{name}: {e}")

    BACKEND = _NullBackend()
    BACKEND_NOTE = "TIDAK ADA backend input - " + "; ".join(problems)
    log(f"[!] {BACKEND_NOTE}")
    return "none"


# ============================================================ Aksi input =====
def mouse_move(dx, dy):
    BACKEND.move(dx, dy)


def mouse_button(btn, press):
    BACKEND.button(btn, press)


def mouse_click(btn="left", double=False):
    for _ in range(2 if double else 1):
        BACKEND.button(btn, True)
        BACKEND.button(btn, False)


def mouse_scroll(dy=0, dx=0):
    BACKEND.scroll(dy, dx)


def press_key(name, mods=None):
    BACKEND.tap((name or "").lower() if len(name or "") != 1 else name,
                mods or [])


def type_text(text):
    if text:
        BACKEND.text(text)


def media_key(action):
    BACKEND.media(action)


def zoom(direction):
    """Pinch: Ctrl + scroll, sama seperti di Windows."""
    BACKEND.key("ctrl", True)
    BACKEND.scroll(120 if direction > 0 else -120)
    BACKEND.key("ctrl", False)


# ============================================================== Gesture ======
# Gesture 3-jari tidak punya padanan universal di Linux: tiap desktop memakai
# pintasan sendiri. Defaultnya dipilih per-desktop, dan pengguna bisa
# menimpanya lewat ~/.config/claudepad/gestures.json tanpa menyentuh kode.
_GESTURE_DEFAULTS = {
    "gnome": {
        "taskview":    {"key": "win", "mods": []},
        "showdesktop": {"key": "d", "mods": ["win"]},
        "appnext":     {"key": "tab", "mods": ["alt"]},
        "appprev":     {"key": "tab", "mods": ["alt", "shift"]},
        "workspace_next": {"key": "right", "mods": ["ctrl", "alt"]},
        "workspace_prev": {"key": "left", "mods": ["ctrl", "alt"]},
    },
    "kde": {
        "taskview":    {"key": "w", "mods": ["ctrl"]},
        "showdesktop": {"key": "d", "mods": ["ctrl", "alt"]},
        "appnext":     {"key": "tab", "mods": ["alt"]},
        "appprev":     {"key": "tab", "mods": ["alt", "shift"]},
        "workspace_next": {"key": "right", "mods": ["ctrl", "alt"]},
        "workspace_prev": {"key": "left", "mods": ["ctrl", "alt"]},
    },
    "xfce": {
        "taskview":    {"key": "w", "mods": ["ctrl", "alt"]},
        "showdesktop": {"key": "d", "mods": ["ctrl", "alt"]},
        "appnext":     {"key": "tab", "mods": ["alt"]},
        "appprev":     {"key": "tab", "mods": ["alt", "shift"]},
        "workspace_next": {"key": "right", "mods": ["ctrl", "alt"]},
        "workspace_prev": {"key": "left", "mods": ["ctrl", "alt"]},
    },
    "cinnamon": {
        "taskview":    {"key": "up", "mods": ["ctrl", "alt"]},
        "showdesktop": {"key": "d", "mods": ["win"]},
        "appnext":     {"key": "tab", "mods": ["alt"]},
        "appprev":     {"key": "tab", "mods": ["alt", "shift"]},
        "workspace_next": {"key": "right", "mods": ["ctrl", "alt"]},
        "workspace_prev": {"key": "left", "mods": ["ctrl", "alt"]},
    },
    "unknown": {
        "taskview":    {"key": "win", "mods": []},
        "showdesktop": {"key": "d", "mods": ["win"]},
        "appnext":     {"key": "tab", "mods": ["alt"]},
        "appprev":     {"key": "tab", "mods": ["alt", "shift"]},
        "workspace_next": {"key": "right", "mods": ["ctrl", "alt"]},
        "workspace_prev": {"key": "left", "mods": ["ctrl", "alt"]},
    },
}

_GESTURE_FILE = "gestures.json"
_gesture_map = None


def gesture_map():
    """Peta gesture aktif. Dibaca sekali, lalu di-cache."""
    global _gesture_map
    if _gesture_map is not None:
        return _gesture_map
    base = dict(_GESTURE_DEFAULTS.get(_desktop_key(),
                                      _GESTURE_DEFAULTS["unknown"]))
    path = data_path(_GESTURE_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
        for name, spec in (user or {}).items():
            if isinstance(spec, dict) and "key" in spec:
                base[name] = {"key": str(spec["key"]),
                              "mods": [str(m) for m in spec.get("mods", [])]}
        log(f"[i] gesture kustom dimuat dari {path}")
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        log(f"[!] {path} tidak terbaca ({e}) - memakai default")
    _gesture_map = base
    return base


def write_default_gestures():
    """Tulis contoh gestures.json kalau belum ada, supaya mudah diedit."""
    path = data_path(_GESTURE_FILE)
    if os.path.exists(path):
        return path
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_GESTURE_DEFAULTS.get(_desktop_key(),
                                            _GESTURE_DEFAULTS["unknown"]),
                      f, indent=2)
        os.chmod(path, 0o600)
    except OSError as e:
        log(f"[!] gagal menulis {path}: {e}")
    return path


def gesture(name):
    spec = gesture_map().get(name)
    if not spec:
        return
    press_key(spec["key"], spec.get("mods", []))


# =============================================================== Volume ======
_VOL_TOOL = None


def _volume_tool():
    """'wpctl' (PipeWire), 'pactl' (PulseAudio/PipeWire), 'amixer', atau None."""
    global _VOL_TOOL
    if _VOL_TOOL is not None:
        return _VOL_TOOL
    for tool in ("wpctl", "pactl", "amixer"):
        if _has(tool):
            _VOL_TOOL = tool
            return tool
    _VOL_TOOL = ""
    log("[!] Tidak ada wpctl/pactl/amixer - slider volume beralih ke tombol media")
    return ""


def volume_get():
    """Volume 0..100, atau None kalau tidak terbaca."""
    tool = _volume_tool()
    try:
        if tool == "wpctl":
            rc, out = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
            if rc == 0 and "Volume:" in out:
                return int(round(float(out.split("Volume:")[1].split()[0]) * 100))
        if tool in ("wpctl", "pactl") and _has("pactl"):
            rc, out = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
            if rc == 0 and "%" in out:
                return int(out.split("/")[1].strip().rstrip("%"))
            # pactl lawas tidak punya get-sink-volume
            rc, out = _run(["pactl", "list", "sinks"])
            if rc == 0:
                for line in out.splitlines():
                    if line.strip().startswith("Volume:") and "%" in line:
                        return int(line.split("/")[1].strip().rstrip("%"))
        if tool == "amixer":
            rc, out = _run(["amixer", "-M", "get", "Master"])
            if rc == 0 and "[" in out:
                for part in out.split("["):
                    if "%]" in part:
                        return int(part.split("%]")[0])
    except (ValueError, IndexError):
        pass
    return None


def volume_set(percent):
    if SANDBOX:
        log(f"sandbox: simulasi volume_set({percent})")
        return True
    percent = max(0, min(100, int(percent)))
    tool = _volume_tool()
    if not tool:
        return False
    if tool == "wpctl":
        rc, _ = _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@",
                      f"{percent / 100:.2f}"])
        if rc == 0:
            return True
    if _has("pactl"):
        rc, _ = _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"])
        if rc == 0:
            return True
    if _has("amixer"):
        rc, _ = _run(["amixer", "-M", "-q", "set", "Master", f"{percent}%"])
        return rc == 0
    return False


def volume_mute_toggle():
    if SANDBOX:
        log("sandbox: simulasi volume_mute_toggle")
        return True
    tool = _volume_tool()
    if tool == "wpctl":
        rc, _ = _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
        if rc == 0:
            return True
    if _has("pactl"):
        rc, _ = _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
        if rc == 0:
            return True
    if _has("amixer"):
        rc, _ = _run(["amixer", "-q", "set", "Master", "toggle"])
        return rc == 0
    return False


# ================================================================ Radio ======
# ============================================================== Sandbox ======
# Mode uji global: saat aktif, semua fungsi berdampak-nyata (radio, daya,
# kecerahan) DISIMULASIKAN alih-alih menyentuh sistem. Diaktifkan lewat
# --sandbox / CLAUDEPAD_SANDBOX=1 (lihat pc_server.py). Perilaku NONAKTIF
# (produksi) tidak berubah sama sekali.
SANDBOX = False


def set_sandbox(flag):
    """Aktifkan/nonaktifkan mode sandbox (input_core + system_ctl)."""
    global SANDBOX
    SANDBOX = bool(flag)
    system_ctl.set_sandbox(SANDBOX)
    log(f"[i] Mode sandbox {'AKTIF' if SANDBOX else 'nonaktif'} - "
        f"aksi daya/radio/kecerahan disimulasikan")


def is_sandbox():
    return SANDBOX


def _nmcli_radio(which):
    """Toggle wifi lewat NetworkManager. (ok, pesan)."""
    rc, out = _run(["nmcli", "radio", which])
    if rc != 0:
        return None
    state = out.strip().splitlines()[-1].strip().lower() if out.strip() else ""
    target = "off" if state == "enabled" else "on"
    rc2, out2 = _run(["nmcli", "radio", which, target])
    if rc2 == 0:
        return True, f"{which} {'menyala' if target == 'on' else 'mati'}"
    return False, out2.splitlines()[-1][:90] if out2 else "gagal"


def _rfkill_toggle(kind):
    rc, out = _run(["rfkill", "list", kind])
    if rc != 0:
        return False, f"rfkill: {out[:80]}"
    blocked = "Soft blocked: yes" in out
    rc2, out2 = _run(["rfkill", "unblock" if blocked else "block", kind])
    if rc2 == 0:
        return True, f"{kind} {'menyala' if blocked else 'mati'}"
    return False, (out2[:90] or "gagal")


def toggle_radio(which):
    """Nyalakan/matikan 'wifi', 'bluetooth', atau 'hotspot' di PC."""
    if SANDBOX:
        log(f"sandbox: simulasi radio {which}")
        if which in ("wifi", "bluetooth", "hotspot"):
            return True, f"{which} disimulasikan (sandbox)"
        return False, "perangkat tidak dikenal"
    if which == "wifi":
        if _has("nmcli"):
            res = _nmcli_radio("wifi")
            if res:
                ok, msg = res
                log(f"[i] {msg}")
                return ok, msg
        if _has("rfkill"):
            return _rfkill_toggle("wifi")
        return False, "wifi: butuh nmcli atau rfkill"

    if which == "bluetooth":
        if _has("bluetoothctl"):
            rc, out = _run(["bluetoothctl", "show"])
            powered_on = "Powered: yes" in out
            rc2, out2 = _run(["bluetoothctl", "power",
                              "off" if powered_on else "on"], timeout=15)
            if rc2 == 0:
                msg = f"bluetooth {'mati' if powered_on else 'menyala'}"
                log(f"[i] {msg}")
                return True, msg
        if _has("rfkill"):
            return _rfkill_toggle("bluetooth")
        return False, "bluetooth: butuh bluetoothctl atau rfkill"

    if which == "hotspot":
        if not _has("nmcli"):
            return False, "hotspot: butuh NetworkManager (nmcli)"
        rc, out = _run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show",
                        "--active"])
        active = [l.split(":")[0] for l in out.splitlines()
                  if l.lower().endswith(":wifi") or ":802-11-wireless" in l.lower()]
        hotspot_on = any(n.lower().startswith("hotspot") for n in active)
        if hotspot_on:
            name = next(n for n in active if n.lower().startswith("hotspot"))
            rc2, out2 = _run(["nmcli", "connection", "down", name], timeout=30)
            if rc2 == 0:
                log("[i] hotspot mati")
                return True, "hotspot mati"
            return False, (out2.splitlines()[-1][:90] if out2 else "gagal")
        dev = _wifi_device()
        if not dev:
            return False, "hotspot: tidak ada perangkat wifi di PC ini"
        rc2, out2 = _run(["nmcli", "device", "wifi", "hotspot", "ifname", dev,
                          "ssid", "CLAUDEPAD", "password", "claudepad123"],
                         timeout=45)
        if rc2 == 0:
            log("[i] hotspot menyala (ssid CLAUDEPAD)")
            return True, "hotspot menyala - ssid CLAUDEPAD, sandi claudepad123"
        return False, (out2.splitlines()[-1][:90] if out2 else "gagal")

    return False, "perangkat tidak dikenal"


def _wifi_device():
    rc, out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"])
    if rc != 0:
        return ""
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] == "wifi":
            return parts[0]
    return ""


# ============================================================= Dispatch ======
def clip_set(text=None, img_b64=None, ctx=None):
    """
    Tulis ke clipboard PC. Bisa teks (`text`) atau gambar (`img_b64` adalah
    string base64 PNG). `ctx` adalah dict state per-koneksi dari
    pc_server.handle() (bukan global): {clipsync, last_server_write}.

    Saat sinkronisasi clipboard nonaktif untuk koneksi ini, permintaan
    ditolak. Konten yang ditulis dicatat di ctx["last_server_write"] supaya
    poller clipboard TIDAK memantulkannya kembali ke HP (anti-loop).
    """
    if ctx is not None and not ctx.get("clipsync", True):
        return False, "sinkronisasi clipboard nonaktif (clipsync off)"
    if img_b64 is not None:
        try:
            import base64
            data = base64.b64decode(img_b64)
        except Exception:                                      # noqa: BLE001
            return False, "gambar tidak valid (bukan base64)"
        if not clipboard.write_image(data):
            return False, "tidak bisa menulis gambar ke clipboard"
        if ctx is not None:
            ctx["last_server_write"] = "[image]"
        return True, ""
    if text is not None:
        if not clipboard.write(text):
            return False, "tidak bisa menulis clipboard (tool clipboard tidak ada)"
        if ctx is not None:
            ctx["last_server_write"] = text
        return True, ""
    return False, "tidak ada konten (text/img)"


def clip_get():
    """
    Baca isi clipboard PC saat ini. Mengembalikan (ok, teks, img_b64, msg).
    Kalau clipboard berisi gambar, `img_b64` berisi base64 PNG dan `teks`
    kosong; jika teks, sebaliknya.
    """
    data = clipboard.read_image()
    if data:
        import base64
        return True, "", base64.b64encode(data).decode("ascii"), ""
    s = clipboard.read()
    return True, s, None, ""


def handle_message(m, reply, ctx=None):
    """
    Proses satu pesan protokol. `reply` adalah callable(dict) untuk balasan.
    `ctx` (opsional) adalah state per-koneksi: clipsync + anti-loop clipboard
    dari pc_server.handle(). Bentuk pesannya identik dengan versi Windows -
    inilah yang membuat APK yang sama bisa dipakai tanpa perubahan.
    """
    t = m.get("t")
    if t == "move":
        mouse_move(m.get("dx", 0), m.get("dy", 0))
    elif t == "click":
        mouse_click(m.get("b", "left"), m.get("double", False))
    elif t == "down":
        mouse_button(m.get("b", "left"), True)
    elif t == "up":
        mouse_button(m.get("b", "left"), False)
    elif t == "scroll":
        mouse_scroll(m.get("dy", 0), m.get("dx", 0))
    elif t == "zoom":
        zoom(m.get("dir", 1))
    elif t == "gesture":
        gesture(m.get("g", ""))
    elif t == "text":
        type_text(m.get("s", ""))
    elif t == "key":
        press_key(m.get("k", ""), m.get("mods"))
    elif t == "media":
        action = m.get("a", "")
        # Mute lewat mixer lebih andal daripada tombol media, karena tidak
        # semua desktop memasang pintasan XF86AudioMute.
        if action == "mute" and volume_mute_toggle():
            pass
        elif action in MEDIA_EVDEV:
            media_key(action)
            reply({"t": "media_result", "a": action, "ok": True})
        else:
            reply({"t": "media_result", "a": action, "ok": False,
                   "msg": "aksi media tidak dikenal"})
    elif t == "volset":
        if not volume_set(m.get("v", 50)):
            reply({"t": "volerr"})
    elif t == "volget":
        reply({"t": "vol", "v": volume_get()})
    elif t == "bright":
        ok, msg = system_ctl.brightness_step(int(m.get("d", 10)))
        reply({"t": "bright_result", "ok": ok, "msg": msg})
    elif t == "power":
        act = m.get("a", "")
        ok, msg = system_ctl.power_action(act)
        if ok:
            log(f"[i] Aksi daya: {act}")
        reply({"t": "power_result", "a": act, "ok": ok, "msg": msg})
    elif t == "radio":
        which = m.get("d", "")
        ok, msg = toggle_radio(which)
        reply({"t": "radio_result", "d": which, "ok": ok, "msg": msg})
    elif t == "clipset":
        img = m.get("img")
        if img is not None:
            ok, msg = clip_set(img_b64=str(img), ctx=ctx)
        else:
            ok, msg = clip_set(text=str(m.get("s") or ""), ctx=ctx)
        reply({"t": "clipset_result", "ok": ok, "msg": msg})
    elif t == "clipget":
        ok, s, img, msg = clip_get()
        if img is not None:
            reply({"t": "clip", "ok": ok, "img": img, "msg": msg})
        else:
            reply({"t": "clip", "ok": ok, "s": s, "msg": msg})
    elif t == "clipsync":
        on = bool(m.get("on", True))
        if ctx is not None:
            ctx["clipsync"] = on
        log(f"[i] Sinkronisasi clipboard koneksi ini: "
            f"{'nyala' if on else 'mati'}")
        reply({"t": "clipsync_result", "ok": True})
    elif t == "npget":
        reply({"t": "np", **mpris.query()})
    elif t == "npseek":
        ok, msg = mpris.seek(m.get("pos_us"))
        reply({"t": "npseek_result", "ok": ok, "msg": msg})
    elif t == "ping":
        reply({"t": "pong"})
    return t


def get_active_scroll_info():
    """
    Di Windows server membaca posisi scrollbar window aktif lewat Win32.
    X11 dan Wayland tidak menyediakan padanan yang bisa dipakai lintas
    toolkit, jadi indikator scroll selalu disembunyikan di Linux.
    """
    return None


# ============================================================ Discovery ======
def discovery_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", DISCOVERY_PORT))
    except OSError as e:
        log(f"[!] Discovery gagal bind: {e}")
        return
    while True:
        try:
            data, addr = s.recvfrom(256)
            if data.strip() == b"DISCOVER_CLAUDEPAD":
                # Bidang keempat baru; klien lama hanya membaca bidang
                # pertama sehingga tetap kompatibel.
                s.sendto(f"CLAUDEPAD|{HOSTNAME}|{WS_PORT}|{PLATFORM}".encode(),
                         addr)
        except OSError:
            break


# =========================================================== Alamat IP =======
# Antarmuka yang HARUS ditandai virtual: menampilkan alamatnya membuat
# pengguna mengetik IP yang mustahil dijangkau dari HP.
VIRTUAL_HINTS = (
    "docker", "br-", "virbr", "veth", "vmnet", "vboxnet", "lxcbr", "lxdbr",
    "tun", "tap", "wg", "tailscale", "zt", "ham", "podman", "cni", "flannel",
    "kube", "utun",
)


def _is_virtual(name):
    low = (name or "").lower()
    return any(low.startswith(h) or h in low for h in VIRTUAL_HINTS)


def _score(ip, name):
    """Makin kecil makin diprioritaskan untuk ditampilkan ke pengguna."""
    if _is_virtual(name):
        return 100
    if ip.startswith("192.168.43."):     # hotspot Android
        return 0
    if ip.startswith("192.168."):
        return 1
    if ip.startswith("10.42."):          # hotspot NetworkManager
        return 1
    if ip.startswith("10."):
        return 2
    if ip.startswith("172."):
        try:
            if 16 <= int(ip.split(".")[1]) <= 31:
                return 90               # rentang favorit Docker
        except (ValueError, IndexError):
            pass
    return 50


def _ip_addresses():
    """[(nama_interface, ipv4)] dari `ip -o -4 addr`, atau [] kalau gagal."""
    rc, out = _run(["ip", "-o", "-4", "addr", "show"])
    if rc != 0:
        return []
    found = []
    for line in out.splitlines():
        parts = line.split()
        # Bentuknya: "2: wlan0    inet 192.168.1.5/24 brd ... scope global ..."
        if len(parts) >= 4 and parts[2] == "inet":
            name = parts[1]
            ip = parts[3].split("/")[0]
            if not ip.startswith("127."):
                found.append((name, ip))
    return found


def local_ips_detailed():
    """
    [(ip, nama_interface, virtual?)] terurut dari yang paling mungkin dipakai HP.
    Interface virtual tetap dikembalikan tapi ditandai, supaya GUI bisa
    meredupkannya alih-alih menyembunyikannya diam-diam.
    """
    found, seen = [], set()
    for name, ip in _ip_addresses():
        if ip in seen:
            continue
        seen.add(ip)
        found.append((ip, name, _is_virtual(name) or _score(ip, name) >= 90))

    if not found:                              # `ip` tidak ada - jalur cadangan
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None,
                                           socket.AF_INET):
                ip = info[4][0]
                if not ip.startswith("127.") and ip not in seen:
                    seen.add(ip)
                    found.append((ip, "network", _score(ip, "") >= 90))
        except socket.gaierror:
            pass

    found.sort(key=lambda t: _score(t[0], t[1]))
    return found


def local_ips():
    """Hanya IP yang layak dipakai (interface virtual dibuang)."""
    detailed = local_ips_detailed()
    real = [ip for ip, _n, virt in detailed if not virt]
    return real if real else [ip for ip, _n, _v in detailed]


# ============================================================== Firewall =====
def _firewall_tool():
    """'ufw', 'firewalld', atau '' kalau mesin tidak memakai firewall."""
    if SANDBOX:
        return ""
    if _has("ufw"):
        rc, out = _run(["ufw", "status"])
        # Tanpa root, ufw menolak dengan pesan izin - itu tetap berarti
        # ufw terpasang, jadi tetap dilaporkan.
        if rc == 0 or "root" in out.lower() or "permission" in out.lower():
            return "ufw"
    if _has("firewall-cmd"):
        return "firewalld"
    return ""


def firewall_status():
    """
    True kalau port CLAUDEPAD bisa dilewati. Mesin tanpa firewall aktif
    juga True - tidak ada yang perlu diperbaiki di sana.
    """
    if SANDBOX:
        log("sandbox: simulasi firewall_status")
        return True
    tool = _firewall_tool()
    if not tool:
        return True
    if tool == "ufw":
        rc, out = _run(["ufw", "status"])
        if rc != 0:
            rc, out = _run(["pkexec", "--disable-internal-agent", "ufw", "status"],
                           timeout=5)
        if rc != 0:
            return False
        if "inactive" in out.lower():
            return True                       # ufw mati = port terbuka
        return str(WS_PORT) in out and str(DISCOVERY_PORT) in out
    rc, out = _run(["firewall-cmd", "--state"])
    if rc != 0 or "running" not in out:
        return True                           # firewalld mati = port terbuka
    rc1, o1 = _run(["firewall-cmd", f"--query-port={WS_PORT}/tcp"])
    rc2, o2 = _run(["firewall-cmd", f"--query-port={DISCOVERY_PORT}/udp"])
    return o1.strip() == "yes" and o2.strip() == "yes"


def firewall_name():
    return _firewall_tool() or "tidak ada"


def fix_firewall():
    """
    Buka port lewat pkexec (prompt kata sandi grafis), memakai skrip
    terpisah agar tidak ada perintah panjang yang di-quote berlapis.
    """
    if SANDBOX:
        log("sandbox: simulasi fix_firewall")
        return True
    tool = _firewall_tool()
    if not tool:
        log("[i] Tidak ada firewall aktif - tidak ada yang perlu diperbaiki.")
        return True
    script = resource_path("fix_firewall.sh")
    if not os.path.exists(script):
        log("[!] fix_firewall.sh tidak ditemukan di folder server")
        return False
    try:
        os.chmod(script, 0o755)
    except OSError:
        pass
    runner = ["pkexec"] if _has("pkexec") else (["sudo"] if _has("sudo") else [])
    if not runner:
        log("[!] pkexec/sudo tidak ada - buka port manual: "
            f"sudo ufw allow {WS_PORT}/tcp && sudo ufw allow {DISCOVERY_PORT}/udp")
        return False
    rc, out = _run(runner + [script], timeout=120)
    if rc != 0:
        log(f"[!] fix_firewall.sh gagal (kode {rc}): {out[:200]}")
    if firewall_status():
        log("[i] Port firewall terbuka.")
        return True
    log("[!] Port masih tertutup - prompt kata sandi ditolak?")
    return False


# ============================================================== Mode USB =====
def enable_usb_mode():
    """adb reverse supaya HP bisa konek lewat kabel USB."""
    if not _has("adb"):
        log("[USB] adb tidak ditemukan. Pasang: sudo apt install adb")
        return False
    _run(["adb", "start-server"], timeout=20)
    rc, out = _run(["adb", "reverse", f"tcp:{WS_PORT}", f"tcp:{WS_PORT}"],
                   timeout=20)
    if rc == 0:
        log("[USB] Aktif. Di aplikasi HP tekan tombol USB.")
        return True
    log("[USB] Gagal: " + (out.strip() or "cek kabel & USB debugging"))
    return False


# =============================================================== Ringkasan ===
def capabilities():
    """
    Daftar kemampuan yang benar-benar ada di mesin ini. Dikirim ke HP di
    auth_ok supaya aplikasi bisa meredupkan tombol yang mustahil bekerja,
    alih-alih membiarkan pengguna menekannya lalu gagal diam-diam.
    """
    return {
        "input": BACKEND.name,
        "volume": bool(_volume_tool()),
        "brightness": system_ctl.brightness_get() is not None,
        "power": system_ctl.supported_power_actions(),
        "radio": [r for r in ("wifi", "bluetooth", "hotspot")
                  if (r != "hotspot" and (_has("nmcli") or _has("rfkill")
                                          or _has("bluetoothctl")))
                  or (r == "hotspot" and _has("nmcli"))],
        "scrollinfo": False,
        "usb": _has("adb"),
        # Fitur v3.7: clipboard dua arah & now-playing MPRIS.
        "clipboard": clipboard.available(),
        "nowplaying": mpris.available(),
    }
