#!/usr/bin/env python3
"""
setup_core - logika inti install & uninstall server CLAUDEPAD Linux.

Diport dari install.sh / uninstall.sh (bash) ke Python murni supaya bisa
dipanggil dari wizard GUI (Tkinter) maupun dari baris perintah. Setiap
langkah adalah fungsi TERPISAH yang mengembalikan tuple (ok: bool, msg: str)
agar wizard bisa menampilkan hasil per-langkah dan test bisa mengisolasi.

Prinsip:
  * Idempoten - aman dijalankan berkali-kali (bila sudah ada, dilewati).
  * Sandbox-aware - bila input_core.is_sandbox() True, TIDAK ADA aksi sistem
    nyata yang dijalankan; hanya dicatat sebagai simulasi. Ini menjaga
    konvensi keamanan repo (OPEN-CONVENTIONS Bagian 4): test/CI tidak boleh
    menyentuh sistem sungguhan.
  * Import-safe - hanya mengimpor stdlib + paths + autostart di level modul;
    input_core diimpor secara malas di dalam fungsi yang butuh status sandbox,
    sehingga file ini bisa di-impor di test tanpa efek samping.
"""
import argparse
import grp
import os
import pwd
import shutil
import subprocess
import sys

from paths import resource_path
from autostart import set_autostart


# ----------------------------------------------------------- utilitas --------
def _log(logfn, msg):
    """Panggil callback log bila diberi; jika tidak, diam."""
    if logfn:
        logfn(msg)


def _is_sandbox():
    """True kalau mode sandbox aktif. Lazy import supaya aman di test."""
    try:
        import input_core
        return input_core.is_sandbox()
    except Exception:  # noqa: BLE001
        return False


def _run(cmd, as_root=False, logfn=None):
    """
    Jalankan perintah. as_root=True -> prafiks 'pkexec' bila bukan root
    (sama seperti fix_firewall.sh dipanggil dari GUI). Mengembalikan
    (ok, output_teks).
    """
    if as_root and os.geteuid() != 0:
        cmd = ["pkexec", *cmd]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def _xdg_dir(env_var, fallback):
    """$env_var/claudepad, atau fallback di home pengguna."""
    base = os.environ.get(env_var) or os.path.join(
        os.path.expanduser("~"), fallback)
    return os.path.join(base, "claudepad")


def _venv_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "claudepad", "venv")


# ---------------------------------------------------- preflight (read-only) --
def preflight():
    """
    Deteksi lingkungan TANPA efek samping. Mengembalikan dict:
      python_ok, tkinter_ok, distro, session, input_group_ok,
      udev_writable, firewall_tool.
    """
    info = {}

    info["python_ok"] = sys.version_info >= (3, 8)

    try:
        import tkinter  # noqa: F401
        info["tkinter_ok"] = True
    except Exception:  # noqa: BLE001
        info["tkinter_ok"] = False

    # Distro dari /etc/os-release.
    distro = "unknown"
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    distro = line.split("=", 1)[1].strip().strip('"')
                    break
                if line.startswith("ID=") and distro == "unknown":
                    distro = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    info["distro"] = distro

    # Sesi: Wayland / X11 / unknown.
    st = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if st == "wayland":
        session = "wayland"
    elif st == "x11":
        session = "x11"
    elif os.environ.get("WAYLAND_DISPLAY"):
        session = "wayland"
    elif os.environ.get("DISPLAY"):
        session = "x11"
    else:
        session = "unknown"
    info["session"] = session

    # Apakah pengguna sudah di grup 'input' (butuh untuk uinput/Wayland).
    try:
        user = pwd.getpwuid(os.getuid()).pw_name
        groups = [g.gr_name for g in grp.getgrall() if user in g.gr_mem]
        info["input_group_ok"] = "input" in groups
    except Exception:  # noqa: BLE001
        info["input_group_ok"] = False

    info["udev_writable"] = os.access("/etc/udev/rules.d", os.W_OK)

    fw = "none"
    if shutil.which("ufw"):
        fw = "ufw"
    elif shutil.which("firewall-cmd"):
        fw = "firewalld"
    info["firewall_tool"] = fw

    return info


# ------------------------------------------------------- langkah install ------
def step_venv(logfn=None):
    """Buat virtualenv & pasang dependensi. Idempoten."""
    if _is_sandbox():
        _log(logfn, "[SANDBOX] (simulasi) virtualenv + pip install")
        return (True, "disimulasikan (sandbox)")
    venv = _venv_dir()
    py = os.path.join(venv, "bin", "python")
    req = resource_path("requirements.txt")
    if os.path.exists(py):
        _log(logfn, f"virtualenv sudah ada: {venv}")
    else:
        _log(logfn, f"membuat virtualenv: {venv}")
        ok, msg = _run([sys.executable, "-m", "venv", venv])
        if not ok:
            return (False, f"gagal membuat virtualenv: {msg}")
    ok, msg = _run([os.path.join(venv, "bin", "pip"),
                    "install", "--upgrade", "pip"], logfn=logfn)
    if not ok:
        return (False, f"gagal upgrade pip: {msg}")
    ok, msg = _run([os.path.join(venv, "bin", "pip"), "install", "-r", req],
                   logfn=logfn)
    if not ok:
        return (False, f"gagal memasang dependensi: {msg}")
    return (True, f"dependensi terpasang di {venv}")


def step_udev(logfn=None):
    """Salin aturan udev, reload, dan modprobe uinput. Butuh root."""
    if _is_sandbox():
        _log(logfn, "[SANDBOX] (simulasi) aturan udev + modprobe uinput")
        return (True, "disimulasikan (sandbox)")
    rule_src = resource_path("99-claudepad-uinput.rules")
    dest = "/etc/udev/rules.d/99-claudepad-uinput.rules"
    if os.access("/etc/udev/rules.d", os.W_OK) or os.geteuid() == 0:
        try:
            shutil.copy(rule_src, dest)
        except OSError as e:
            return (False, f"gagal menulis aturan udev: {e}")
    else:
        ok, msg = _run(["cp", rule_src, dest], as_root=True)
        if not ok:
            return (False, f"gagal menulis aturan udev (perlu root): {msg}")
    _run(["groupadd", "-f", "input"], as_root=True)
    _run(["udevadm", "control", "--reload-rules"], as_root=True)
    _run(["udevadm", "trigger", "--subsystem-match=misc"], as_root=True)
    _run(["modprobe", "uinput"], as_root=True)
    return (True, "aturan udev terpasang")


def step_group_input(logfn=None):
    """Tambahkan pengguna ke grup 'input'. Idempoten (groupadd -f)."""
    if _is_sandbox():
        _log(logfn, "[SANDBOX] (simulasi) tambah ke grup input")
        return (True, "disimulasikan (sandbox)")
    try:
        user = pwd.getpwuid(os.getuid()).pw_name
    except Exception:  # noqa: BLE001
        user = os.environ.get("USER", "")
    ok, msg = _run(["usermod", "-aG", "input", user], as_root=True)
    if not ok:
        return (False, f"gagal menambah ke grup input: {msg}")
    return (True, f"pengguna {user} ditambahkan ke grup input "
                  f"(logout+login agar berlaku di Wayland)")


def step_menu(logfn=None):
    """Tulis entri menu aplikasi .desktop. Idempoten."""
    if _is_sandbox():
        _log(logfn, "[SANDBOX] (simulasi) entri menu aplikasi")
        return (True, "disimulasikan (sandbox)")
    apps = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    apps = os.path.join(apps, "applications")
    os.makedirs(apps, exist_ok=True)
    start = resource_path("start_server.sh")
    entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=CLAUDEPAD\n"
        "Comment=Server remote trackpad & keyboard untuk HP Android\n"
        f"Exec={start}\n"
        "Icon=input-tablet\n"
        "Terminal=false\n"
        "Categories=Utility;RemoteAccess;\n"
    )
    path = os.path.join(apps, "claudepad.desktop")
    with open(path, "w", encoding="utf-8") as f:
        f.write(entry)
    os.chmod(path, 0o644)
    _run(["update-desktop-database", apps])
    return (True, f"entri menu terpasang: {path}")


def step_autostart(logfn=None):
    """Aktifkan autostart via XDG Autostart. Idempoten."""
    if _is_sandbox():
        _log(logfn, "[SANDBOX] (simulasi) autostart")
        return (True, "disimulasikan (sandbox)")
    ok = set_autostart(True)
    return (ok, "autostart diatur" if ok else "gagal mengatur autostart")


def step_firewall(logfn=None):
    """Buka port firewall lewat fix_firewall.sh (butuh root/pkexec)."""
    if _is_sandbox():
        _log(logfn, "[SANDBOX] (simulasi) buka port firewall")
        return (True, "disimulasikan (sandbox)")
    fw = resource_path("fix_firewall.sh")
    ok, msg = _run(["bash", fw], as_root=True)
    return (ok, f"firewall: {(msg or 'port dibuka').strip()}")


# ----------------------------------------------------- orkestrasi install ----
def install_all(logfn=None):
    """
    Jalankan semua langkah install berurutan. Mengembalikan list
    tuple (step_name, ok, msg). Setiap langkah menangani sandbox sendiri.
    """
    results = []
    steps = [
        ("virtualenv", step_venv),
        ("udev", step_udev),
        ("grup input", step_group_input),
        ("menu", step_menu),
        ("autostart", step_autostart),
        ("firewall", step_firewall),
    ]
    for name, fn in steps:
        _log(logfn, f"==> {name}")
        ok, msg = fn(logfn)
        results.append((name, ok, msg))
        if not ok:
            _log(logfn, f"  ! {name} gagal: {msg}")
    return results


# ----------------------------------------------------- langkah uninstall ------
def _remove_file(path, as_root=False, logfn=None):
    if os.path.exists(path):
        if as_root and os.access(os.path.dirname(path) or "/", os.W_OK) is False \
                and os.geteuid() != 0:
            ok, msg = _run(["rm", "-f", path], as_root=True)
        else:
            try:
                os.remove(path)
                ok, msg = True, ""
            except OSError as e:
                ok, msg = _run(["rm", "-f", path], as_root=True)
        if not ok:
            _log(logfn, f"  ! gagal hapus {path}: {msg}")
            return False
        return True
    return None  # tidak ada -> lewati


def uninstall_all(keep_config=False, logfn=None):
    """
    Hapus semua artefak pemasangan. Idempoten. Mengembalikan list
    tuple (step_name, ok, msg).

    Keanggotaan grup 'input' TIDAK dicabut (dipakai bersama app lain).
    Konfigurasi (~/.config/claudepad) hanya dihapus bila keep_config False.
    """
    results = []
    venv = _venv_dir()

    # 1. Virtualenv
    if os.path.isdir(venv):
        shutil.rmtree(venv, ignore_errors=True)
        results.append(("virtualenv", True, f"dihapus: {venv}"))
    else:
        results.append(("virtualenv", True, "tidak ada - lewati"))

    # 2. Aturan udev
    if _is_sandbox():
        _log(logfn, "[SANDBOX] (simulasi) hapus aturan udev")
        results.append(("udev", True, "disimulasikan (sandbox)"))
    else:
        dest = "/etc/udev/rules.d/99-claudepad-uinput.rules"
        r = _remove_file(dest, as_root=True, logfn=logfn)
        if r is True:
            _run(["udevadm", "control", "--reload-rules"], as_root=True)
            results.append(("udev", True, f"dihapus: {dest}"))
        elif r is False:
            results.append(("udev", False, "gagal hapus aturan udev"))
        else:
            results.append(("udev", True, "tidak ada - lewati"))

    # 3. Entri menu
    apps = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    menu = os.path.join(apps, "applications", "claudepad.desktop")
    if os.path.exists(menu):
        os.remove(menu)
        _run(["update-desktop-database", apps])
        results.append(("menu", True, f"dihapus: {menu}"))
    else:
        results.append(("menu", True, "tidak ada - lewati"))

    # 4. Autostart
    if _is_sandbox():
        results.append(("autostart", True, "disimulasikan (sandbox)"))
    else:
        ok = set_autostart(False)
        results.append(("autostart", ok,
                        "dinonaktifkan" if ok else "gagal nonaktifkan autostart"))

    # 5. Unit systemd user
    if _is_sandbox():
        results.append(("systemd", True, "disimulasikan (sandbox)"))
    else:
        unit = os.path.join(_xdg_dir("XDG_CONFIG_HOME", ".config"),
                            "systemd", "user", "claudepad.service")
        if os.path.exists(unit):
            _run(["systemctl", "--user", "disable", "--now", "claudepad"],
                 logfn=logfn)
            try:
                os.remove(unit)
            except OSError:
                _run(["rm", "-f", unit], as_root=True)
            _run(["systemctl", "--user", "daemon-reload"], logfn=logfn)
            results.append(("systemd", True, f"dihapus: {unit}"))
        else:
            results.append(("systemd", True, "tidak ada - lewati"))

    # 6. Konfigurasi (token pairing, gesture)
    cfg = _xdg_dir("XDG_CONFIG_HOME", ".config")
    if keep_config:
        results.append(("konfigurasi", True, f"dipertahankan: {cfg}"))
    elif _is_sandbox():
        results.append(("konfigurasi", True, "disimulasikan (sandbox)"))
    elif os.path.isdir(cfg):
        shutil.rmtree(cfg, ignore_errors=True)
        results.append(("konfigurasi", True, f"dihapus: {cfg}"))
    else:
        results.append(("konfigurasi", True, "tidak ada - lewati"))

    # Grup input sengaja TIDAK dicabut.
    _log(logfn, "catatan: pengguna tetap di grup 'input' (dipakai bersama "
                "aplikasi lain).")
    return results


# --------------------------------------------------------------- CLI main ------
def main():
    p = argparse.ArgumentParser(description="Setup CLAUDEPAD Server (Linux)")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("install", help="Pasang server (venv, udev, menu, dll)")
    up = sub.add_parser("uninstall", help="Hapus server")
    up.add_argument("--keep-config", action="store_true",
                    help="Jangan hapus ~/.config/claudepad")
    sub.add_parser("preflight", help="Cetak deteksi lingkungan (read-only)")

    args = p.parse_args()
    if args.cmd == "install":
        print("=== Install CLAUDEPAD ===")
        for name, ok, msg in install_all(print):
            print(f"  [{'v' if ok else '!'}] {name}: {msg}")
    elif args.cmd == "uninstall":
        print("=== Uninstall CLAUDEPAD ===")
        for name, ok, msg in uninstall_all(keep_config=args.keep_config,
                                           logfn=print):
            print(f"  [{'v' if ok else '!'}] {name}: {msg}")
    elif args.cmd == "preflight":
        import json
        print(json.dumps(preflight(), indent=2, ensure_ascii=False))
    else:
        p.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
