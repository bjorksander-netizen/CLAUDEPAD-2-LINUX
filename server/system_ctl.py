#!/usr/bin/env python3
"""
CLAUDEPAD LINUX - kontrol sistem PC: kecerahan, daya, dan identitas jaringan.

Semua aksi daya lewat systemd/logind. logind sengaja dipakai lewat
`systemctl` dan `loginctl` biasa (bukan sudo): pada desktop normal, polkit
sudah mengizinkan pengguna sesi aktif mematikan/menidurkan mesinnya sendiri,
jadi tidak ada prompt kata sandi dan tidak ada hak root yang perlu disimpan.
Kalau polkit menolak, alasannya dikembalikan apa adanya ke HP.
"""

import glob
import os
import shutil
import subprocess

IS_WINDOWS = False


def _has(cmd):
    return shutil.which(cmd) is not None


def _run(args, timeout=20):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except FileNotFoundError:
        return 127, f"{args[0]} tidak ditemukan"
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:                                     # noqa: BLE001
        return 1, str(e)


def _session_type():
    t = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if t:
        return t
    return "wayland" if os.environ.get("WAYLAND_DISPLAY") else (
        "x11" if os.environ.get("DISPLAY") else "tty")


# ============================================================== KECERAHAN ====
# Tiga jalur, dicoba berurutan:
#   1. brightnessctl / light  - alat khusus, sudah dipasangi aturan udev
#      sehingga bisa menulis tanpa root.
#   2. /sys/class/backlight   - tulis langsung; hanya jalan kalau pengguna
#      ada di grup video atau aturan udev sudah terpasang.
#   3. ddcutil                - monitor eksternal lewat DDC/CI.

def _backlight_dir():
    dirs = sorted(glob.glob("/sys/class/backlight/*"))
    return dirs[0] if dirs else ""


def _sysfs_get():
    d = _backlight_dir()
    if not d:
        return None
    try:
        with open(os.path.join(d, "brightness")) as f:
            cur = int(f.read().strip())
        with open(os.path.join(d, "max_brightness")) as f:
            mx = int(f.read().strip())
        if mx <= 0:
            return None
        return int(round(cur * 100.0 / mx))
    except (OSError, ValueError):
        return None


def _sysfs_set(percent):
    d = _backlight_dir()
    if not d:
        return False
    try:
        with open(os.path.join(d, "max_brightness")) as f:
            mx = int(f.read().strip())
        target = max(1, int(round(mx * percent / 100.0)))
        with open(os.path.join(d, "brightness"), "w") as f:
            f.write(str(target))
        return True
    except (OSError, ValueError):
        return False


def _brightnessctl_get():
    if not _has("brightnessctl"):
        return None
    rc, out = _run(["brightnessctl", "-m", "get"])
    rc2, out2 = _run(["brightnessctl", "-m", "max"])
    try:
        if rc == 0 and rc2 == 0:
            cur, mx = int(out.strip()), int(out2.strip())
            return int(round(cur * 100.0 / mx)) if mx > 0 else None
    except ValueError:
        pass
    return None


def _brightnessctl_set(percent):
    if not _has("brightnessctl"):
        return False
    rc, _ = _run(["brightnessctl", "-q", "set", f"{max(1, int(percent))}%"])
    return rc == 0


def _light_get():
    if not _has("light"):
        return None
    rc, out = _run(["light", "-G"])
    try:
        return int(round(float(out.strip()))) if rc == 0 else None
    except ValueError:
        return None


def _light_set(percent):
    if not _has("light"):
        return False
    rc, _ = _run(["light", "-S", str(max(1, int(percent)))])
    return rc == 0


def _ddc_get():
    if not _has("ddcutil"):
        return None
    rc, out = _run(["ddcutil", "getvcp", "10", "--brief"], timeout=25)
    if rc != 0:
        return None
    parts = out.split()
    # Bentuk brief: "VCP 10 C <current> <max>"
    try:
        if len(parts) >= 5:
            cur, mx = int(parts[3]), int(parts[4])
            return int(round(cur * 100.0 / mx)) if mx > 0 else None
    except ValueError:
        pass
    return None


def _ddc_set(percent):
    if not _has("ddcutil"):
        return False
    rc, _ = _run(["ddcutil", "setvcp", "10", str(int(percent))], timeout=25)
    return rc == 0


def brightness_get():
    """Kecerahan 0..100, atau None kalau tidak terbaca."""
    for fn in (_brightnessctl_get, _light_get, _sysfs_get, _ddc_get):
        v = fn()
        if v is not None:
            return v
    return None


def brightness_step(delta):
    """Naik/turunkan kecerahan sebesar delta persen. (berhasil, pesan)."""
    cur = brightness_get()
    if cur is None:
        return False, ("kecerahan tidak didukung - tidak ada backlight, "
                       "brightnessctl, maupun monitor DDC/CI")
    target = max(0, min(100, cur + delta))
    if target == cur:
        return True, f"kecerahan {cur}%"
    for fn in (_brightnessctl_set, _light_set, _sysfs_set, _ddc_set):
        if fn(target):
            return True, f"kecerahan {target}%"
    return False, ("gagal mengubah kecerahan - butuh izin tulis backlight; "
                   "pasang brightnessctl atau jalankan server/install.sh")


# ==================================================================== DAYA ===
# systemctl menangani mesin lewat logind; loginctl menangani sesi.
_SYSTEMCTL = {
    "shutdown": (["systemctl", "poweroff"], "PC dimatikan"),
    "restart": (["systemctl", "reboot"], "PC dimulai ulang"),
    "sleep": (["systemctl", "suspend"], "PC ditidurkan"),
    "hibernate": (["systemctl", "hibernate"], "PC hibernasi"),
}


def _can(action):
    """Tanya logind apakah aksi ini mungkin di mesin ini."""
    verb = {"shutdown": "can-power-off", "restart": "can-reboot",
            "sleep": "can-suspend", "hibernate": "can-hibernate"}.get(action)
    if not verb or not _has("systemctl"):
        return False
    rc, out = _run(["systemctl", verb], timeout=8)
    return rc == 0 and out.strip() in ("yes", "challenge")


def _lock_session():
    if _has("loginctl"):
        sid = os.environ.get("XDG_SESSION_ID", "")
        rc, out = _run(["loginctl", "lock-session"] + ([sid] if sid else []))
        if rc == 0:
            return True, "PC dikunci"
    for cmd in (["xdg-screensaver", "lock"],
                ["gnome-screensaver-command", "--lock"],
                ["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "Lock"],
                ["swaylock"], ["i3lock"]):
        if _has(cmd[0]):
            rc, _ = _run(cmd, timeout=8)
            if rc == 0:
                return True, "PC dikunci"
    return False, "penguncian layar tidak tersedia - pasang loginctl/xdg-screensaver"


def _logoff():
    for cmd in (["gnome-session-quit", "--logout", "--no-prompt"],
                ["qdbus", "org.kde.ksmserver", "/KSMServer", "logout", "0", "0", "0"],
                ["xfce4-session-logout", "--logout"],
                ["cinnamon-session-quit", "--logout", "--no-prompt"]):
        if _has(cmd[0]):
            rc, out = _run(cmd, timeout=10)
            if rc == 0:
                return True, "keluar dari sesi"
    sid = os.environ.get("XDG_SESSION_ID", "")
    if _has("loginctl") and sid:
        rc, out = _run(["loginctl", "terminate-session", sid], timeout=10)
        if rc == 0:
            return True, "keluar dari sesi"
        return False, out[:90] or "gagal keluar sesi"
    return False, "keluar sesi tidak didukung di desktop ini"


def _screen_off():
    st = _session_type()
    if st == "x11" and _has("xset"):
        rc, out = _run(["xset", "dpms", "force", "off"], timeout=8)
        if rc == 0:
            return True, "layar dimatikan"
        return False, out[:90] or "xset gagal"
    if _has("swaymsg"):
        rc, _ = _run(["swaymsg", "output", "*", "power", "off"], timeout=8)
        if rc == 0:
            return True, "layar dimatikan"
    if _has("hyprctl"):
        rc, _ = _run(["hyprctl", "dispatch", "dpms", "off"], timeout=8)
        if rc == 0:
            return True, "layar dimatikan"
    if _has("gnome-screensaver-command"):
        rc, _ = _run(["gnome-screensaver-command", "--activate"], timeout=8)
        if rc == 0:
            return True, "screensaver diaktifkan"
    return False, ("matikan layar belum didukung di sesi ini - "
                   "Wayland tidak menyediakan perintah standar")


def supported_power_actions():
    """Daftar aksi daya yang benar-benar bisa dijalankan di mesin ini."""
    out = []
    for act in ("shutdown", "restart", "sleep", "hibernate"):
        if _can(act):
            out.append(act)
    if _has("loginctl") or _has("xdg-screensaver") or _has("swaylock"):
        out.append("lock")
    if (_has("gnome-session-quit") or _has("qdbus")
            or _has("xfce4-session-logout") or _has("cinnamon-session-quit")
            or (_has("loginctl") and os.environ.get("XDG_SESSION_ID"))):
        out.append("logoff")
    if (_session_type() == "x11" and _has("xset")) or _has("swaymsg") \
            or _has("hyprctl"):
        out.append("screenoff")
    return out


def power_action(action):
    """shutdown / restart / sleep / hibernate / logoff / lock / screenoff."""
    if action == "lock":
        return _lock_session()
    if action == "screenoff":
        return _screen_off()
    if action == "logoff":
        return _logoff()
    if action in _SYSTEMCTL:
        if not _has("systemctl"):
            return False, "systemd tidak tersedia di sistem ini"
        args, msg = _SYSTEMCTL[action]
        rc, out = _run(args, timeout=15)
        if rc == 0:
            return True, msg
        low = out.lower()
        if "not authorized" in low or "interactive authentication" in low:
            return False, f"{action}: polkit menolak - butuh izin dari sesi aktif"
        if "not supported" in low or "no such" in low:
            return False, f"{action}: tidak didukung mesin ini"
        return False, (out.splitlines()[-1][:90] if out else f"{action} gagal")
    return False, "aksi daya tidak dikenal"


# ============================================================ IDENTITAS ======
def _default_iface():
    rc, out = _run(["ip", "route", "show", "default"], timeout=8)
    if rc == 0:
        parts = out.split()
        if "dev" in parts:
            return parts[parts.index("dev") + 1]
    return ""


def mac_address():
    """
    MAC interface default dalam format AA:BB:CC:DD:EE:FF, untuk Wake-on-LAN.
    Dibaca dari sysfs supaya alamatnya adalah alamat kartu yang sebenarnya,
    bukan tebakan uuid.getnode() yang bisa mengarang.
    """
    iface = _default_iface()
    candidates = [iface] if iface else []
    if not candidates:
        candidates = [os.path.basename(p) for p in
                      sorted(glob.glob("/sys/class/net/*"))
                      if os.path.basename(p) != "lo"]
    for name in candidates:
        try:
            with open(f"/sys/class/net/{name}/address") as f:
                mac = f.read().strip().upper()
            if mac and mac != "00:00:00:00:00:00":
                return mac
        except OSError:
            continue
    return ""
