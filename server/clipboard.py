#!/usr/bin/env python3
"""
Lapisan akses clipboard PC - baca/tulis lewat CLI tooling desktop.

  * Wayland : wl-copy / wl-paste  (paket wl-clipboard)
  * X11     : xclip, lalu xsel    (paket xclip / xsel)

Modul ini hanya membaca dan menulis. Logika anti-loop ("jangan dorong
konten yang barusan ditulis sendiri") diurus oleh poller per-koneksi di
pc_server.py; modul ini tidak menyimpan state sama sekali.

Keamanan (OPEN-CONVENTIONS Bagian 4): saat mode sandbox aktif, write
disimulasikan dan read mengembalikan string kosong / None - TIDAK ada subprocess
yang dijalankan, sehingga test/harness tidak pernah menyentuh clipboard
desktop pengguna.
"""
import shutil
import subprocess


def _sandbox():
    # Lazy import: clipboard.py diimpor oleh input_core.py, jadi impor
    # langsung di sini akan jadi circular. Pola sama dengan system_ctl.
    import input_core
    return input_core.is_sandbox()


def _log(msg):
    import input_core
    input_core.log(msg)


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
    except Exception:                                          # noqa: BLE001
        return 1, "gagal"


def _run_with_input(args, text, timeout=5):
    """
    Jalankan perintah dengan teks di stdin. Dipakai untuk wl-copy/xclip/xsel
    yang membaca isi clipboard dari stdin.

    xclip/xsel tetap hidup sebagai pemilik seleksi setelah menulis (normal
    di X11), jadi kita tidak menunggu exit tanpa batas: bila proses belum
    selesai setelah `timeout` detik, kita anggap tulisannya berhasil.
    """
    try:
        p = subprocess.Popen(args, stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE)
    except FileNotFoundError:
        return 127, f"{args[0]} tidak ditemukan"
    except Exception:                                          # noqa: BLE001
        return 1, "gagal"
    try:
        p.stdin.write(text.encode("utf-8", "surrogateescape"))
        p.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # xclip/xsel menjaga seleksi sebagai daemon - itu sukses, bukan gagal.
        return 0, ""
    return p.returncode, ""


def _run_bytes(args, timeout=10):
    """Sama seperti _run, tapi menangkap stdout sebagai bytes (bukan teks).

    Penting untuk gambar: PNG adalah data biner, dan decode UTF-8 di _run
    (text=True) akan merusak / memotong byte yang tidak valid sehingga
    read_image mengembalikan None. Runner ini mengembalikan (rc, bytes).
    """
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout)
        return r.returncode, r.stdout or b""
    except FileNotFoundError:
        return 127, b""
    except subprocess.TimeoutExpired:
        return 124, b""
    except Exception:                                          # noqa: BLE001
        return 1, b""


def _run_with_input_bytes(args, data, timeout=5):
    """Sama seperti _run_with_input, tapi menulis bytes (gambar PNG)."""
    try:
        p = subprocess.Popen(args, stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE)
    except FileNotFoundError:
        return 127, f"{args[0]} tidak ditemukan"
    except Exception:                                          # noqa: BLE001
        return 1, "gagal"
    try:
        p.stdin.write(data)
        p.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return 0, ""
    return p.returncode, ""


def _tool():
    """Nama tool clipboard terbaik: 'wl' | 'xclip' | 'xsel' | None."""
    if _has("wl-copy") and _has("wl-paste"):
        return "wl"
    if _has("xclip"):
        return "xclip"
    if _has("xsel"):
        return "xsel"
    return None


def available():
    """True kalau ada tool clipboard yang bisa dipakai."""
    return _tool() is not None


def read():
    """
    Baca isi clipboard PC. Selalu mengembalikan str ("" kalau kosong /
    gagal / tool tidak ada). Di mode sandbox: "" tanpa subprocess.
    """
    if _sandbox():
        _log("sandbox: simulasi clipboard.read() -> konten kosong")
        return ""
    tool = _tool()
    if not tool:
        return ""
    try:
        if tool == "wl":
            # --no-newline tersedia di wl-clipboard 2.1+; fallback ke strip
            # satu newline untuk distro lama (Ubuntu 22.04 punya 2.0).
            rc, out = _run(["wl-paste", "--no-newline"], timeout=5)
            if rc != 0:
                rc, out = _run(["wl-paste"], timeout=5)
                out = out.rstrip("\n")
            return out if rc == 0 else ""
        if tool == "xclip":
            rc, out = _run(["xclip", "-selection", "clipboard", "-o"], timeout=5)
            return out if rc == 0 else ""
        rc, out = _run(["xsel", "--clipboard", "--output"], timeout=5)
        return out if rc == 0 else ""
    except Exception:                                          # noqa: BLE001
        return ""


def write(text):
    """
    Tulis teks ke clipboard PC. True kalau berhasil (atau disimulasikan).
    Di mode sandbox: log + True, tanpa menyentuh sistem.
    """
    if _sandbox():
        _log(f"sandbox: simulasi clipboard.write({len(text)} byte)")
        return True
    tool = _tool()
    if not tool:
        return False
    try:
        if tool == "wl":
            rc, _ = _run_with_input(["wl-copy"], text)
            return rc == 0
        if tool == "xclip":
            rc, _ = _run_with_input(["xclip", "-selection", "clipboard"], text)
            return rc == 0
        rc, _ = _run_with_input(["xsel", "--clipboard", "--input"], text)
        return rc == 0
    except Exception:                                          # noqa: BLE001
        return False


def read_image():
    """
    Baca gambar dari clipboard PC. Mengembalikan bytes PNG, atau None kalau
    kosong / bukan gambar / tool tidak ada. Di mode sandbox: None tanpa
    subprocess.
    """
    if _sandbox():
        _log("sandbox: simulasi clipboard.read_image() -> None")
        return None
    tool = _tool()
    if not tool:
        return None
    try:
        if tool == "wl":
            rc, out = _run_bytes(["wl-paste", "--type", "image/png"], timeout=5)
            return out if rc == 0 and out else None
        if tool == "xclip":
            rc, out = _run_bytes(["xclip", "-selection", "clipboard",
                                  "-t", "image/png", "-o"], timeout=5)
            return out if rc == 0 and out else None
        rc, out = _run_bytes(["xsel", "--clipboard", "--type", "image/png",
                              "--output"], timeout=5)
        return out if rc == 0 and out else None
    except Exception:                                          # noqa: BLE001
        return None


def write_image(data: bytes):
    """
    Tulis gambar (bytes PNG) ke clipboard PC. True kalau berhasil (atau
    disimulasikan). Di mode sandbox: log + True, tanpa menyentuh sistem.
    """
    if _sandbox():
        _log(f"sandbox: simulasi clipboard.write_image({len(data)} byte)")
        return True
    tool = _tool()
    if not tool:
        return False
    try:
        if tool == "wl":
            rc, _ = _run_with_input_bytes(
                ["wl-copy", "--type", "image/png"], data)
            return rc == 0
        if tool == "xclip":
            rc, _ = _run_with_input_bytes(
                ["xclip", "-selection", "clipboard", "-t", "image/png"], data)
            return rc == 0
        rc, _ = _run_with_input_bytes(
            ["xsel", "--clipboard", "--type", "image/png", "--input"], data)
        return rc == 0
    except Exception:                                          # noqa: BLE001
        return False
