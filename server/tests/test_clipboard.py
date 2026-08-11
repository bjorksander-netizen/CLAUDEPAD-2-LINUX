#!/usr/bin/env python3
"""
test_clipboard.py - Uji unit modul clipboard PC (v3.7) (QA).

Kontrak protokol (dari spesifikasi v3.7):
  * clipset  -> clipboard.write(s)
  * clipget  -> clipboard.read()
  * clipsync -> state sinkronisasi per-koneksi (di pc_server/input_core,
                BUKAN di modul ini); modul ini hanya read/write/available.
  * Implementasi: wl-copy/wl-paste (Wayland) atau xclip/xsel (X11);
    read() memakai subprocess.run, write() memakai subprocess.Popen (stdin).

PRINSIP KEAMANAN (OPEN-CONVENTIONS.md Bagian 4):
  * TIDAK ada satu pun eksekusi sistem nyata di test ini.
  * Semua pemanggilan subprocess DICEGAT oleh recorder yang mengembalikan
    hasil simulasi; subprocess.run/Popen ASLI tidak pernah dieksekusi.
  * Tool dipilih lewat mock `shutil.which`, bukan deteksi nyata.

Modul clipboard.py (milik tesla): available()/read()/write() - lihat
server/clipboard.py.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import clipboard                                          # noqa: E402
except ImportError:
    clipboard = None

FAILED = []
SKIPPED = []


def check(label, cond):
    print(("OK  - " if cond else "GAGAL - ") + label)
    if not cond:
        FAILED.append(label)


def skip(label):
    SKIPPED.append(label)
    print(f"SKIP - {label}")


# Recorder subprocess: MENCATAT semua pemanggilan dan MENGEMBALIKAN hasil
# simulasi. subprocess.run/Popen ASLI tidak pernah dieksekusi - setiap
# pemanggilan dari modul clipboard dicegat di sini.
class _Recorder:
    def __init__(self):
        self.calls = []
        self.stdout_map = []          # (prefix command, stdout teks)
        self.rc_map = {}              # prefix -> returncode (default 0)
        self._orig_run = subprocess.run
        self._orig_popen = subprocess.Popen
        self._orig_check = subprocess.check_output

    def install(self):
        subprocess.run = self._run
        subprocess.Popen = self._popen
        subprocess.check_output = self._check

    def restore(self):
        subprocess.run = self._orig_run
        subprocess.Popen = self._orig_popen
        subprocess.check_output = self._orig_check

    def set_stdout(self, prefix, text):
        self.stdout_map = [(p, t) for (p, t) in self.stdout_map if p != prefix]
        self.stdout_map.append((prefix, text))

    def set_rc(self, prefix, rc):
        self.rc_map[prefix] = rc

    def _key(self, args):
        if isinstance(args, (list, tuple)):
            return " ".join(str(a) for a in args)
        return str(args)

    def _match(self, key):
        """Cocokkan prefix TERPANJANG supaya 'wl-paste --no-newline'
        menang atas 'wl-paste'."""
        stdout = ""
        rc = 0
        best_std = -1
        for prefix, text in self.stdout_map:
            if key.startswith(prefix) and len(prefix) > best_std:
                best_std = len(prefix)
                stdout = text
        best_rc = -1
        for prefix, code in self.rc_map.items():
            if key.startswith(prefix) and len(prefix) > best_rc:
                best_rc = len(prefix)
                rc = code
        return stdout, rc

    def _run(self, args, **kwargs):
        key = self._key(args)
        self.calls.append(key)
        stdout, rc = self._match(key)
        if kwargs.get("text"):
            return subprocess.CompletedProcess(args, rc, stdout=stdout)
        return subprocess.CompletedProcess(args, rc,
                                           stdout=stdout.encode("utf-8"))

    def _popen(self, args, **kwargs):
        key = self._key(args)
        self.calls.append(key)
        stdout, rc = self._match(key)
        return _FakeProc(args, rc)

    def _check(self, args, **kwargs):
        key = self._key(args)
        self.calls.append(key)
        stdout, rc = self._match(key)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, args)
        return stdout.encode("utf-8")


class _FakeStdin:
    def __init__(self):
        self.data = b""

    def write(self, b):
        self.data += b if isinstance(b, bytes) else b.encode("utf-8",
                                                             "surrogateescape")
        return len(self.data)

    def close(self):
        pass


class _FakeProc:
    """Pengganti subprocess.Popen: stdin bisa ditulis, wait selesai segera."""
    def __init__(self, args, rc=0):
        self.args = args
        self.returncode = rc
        self.stdin = _FakeStdin()
        self.stdout = subprocess.DEVNULL
        self.stderr = _FakeStdin()

    def wait(self, timeout=None):
        return self.returncode


# ------------------------------------------------------------ Pengujian ------
def test_modul_ada():
    if clipboard is None:
        skip("modul clipboard.py belum ada (blocker sementara: tesla belum "
             "selesai) - seluruh suite dilewati")
        return False
    missing = [n for n in ("available", "read", "write")
               if not hasattr(clipboard, n)]
    check("clipboard.available/read/write tersedia (kurang: %s)"
          % (missing or "-"), not missing)
    return not missing


def test_deteksi_tool():
    """available() mengikuti ketersediaan tool (mock shutil.which)."""
    import shutil
    orig = shutil.which
    try:
        # wl butuh wl-copy DAN wl-paste.
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd in ("wl-copy",
                                                                "wl-paste") else None
        check("available True saat wl-copy+wl-paste ada",
              clipboard.available() is True)
        # xclip saja cukup.
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "xclip" else None
        check("available True saat xclip ada", clipboard.available() is True)
        # xsel saja cukup.
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "xsel" else None
        check("available True saat xsel ada", clipboard.available() is True)
        # Tanpa tool sama sekali.
        shutil.which = lambda cmd: None
        check("available False tanpa tool", clipboard.available() is False)
    finally:
        shutil.which = orig


def test_read_memakai_tool_benar():
    """read() memanggil tool yang tersedia dengan argumen yang benar."""
    import shutil
    orig_which = shutil.which
    rec = _Recorder()
    rec.install()
    try:
        # Wayland: wl-paste --no-newline.
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd in ("wl-copy",
                                                                "wl-paste") else None
        rec.set_stdout("wl-paste", "teks wayland")
        check("read() memakai wl-paste --no-newline",
              clipboard.read() == "teks wayland"
              and any(c.startswith("wl-paste --no-newline") for c in rec.calls))

        # Fallback wl-paste lama: --no-newline gagal -> wl-paste + strip \n.
        rec.calls.clear()
        rec.set_rc("wl-paste --no-newline", 1)
        rec.set_stdout("wl-paste --no-newline", "")
        rec.set_stdout("wl-paste", "teks wayland lama\n")
        got = clipboard.read()
        check("read() fallback wl-paste tanpa --no-newline",
              got == "teks wayland lama")

        # X11: xclip -selection clipboard -o.
        rec.calls.clear()
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "xclip" else None
        rec.set_stdout("xclip", "teks xclip")
        check("read() memakai xclip",
              clipboard.read() == "teks xclip"
              and any(c.startswith("xclip -selection clipboard -o")
                      for c in rec.calls))

        # X11: xsel --clipboard --output.
        rec.calls.clear()
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "xsel" else None
        rec.set_stdout("xsel", "teks xsel")
        check("read() memakai xsel",
              clipboard.read() == "teks xsel"
              and any(c.startswith("xsel --clipboard --output")
                      for c in rec.calls))
    finally:
        rec.restore()
        shutil.which = orig_which


def test_write_memakai_tool_benar():
    """write() memanggil tool tulis yang tersedia dengan stdin benar."""
    import shutil
    orig_which = shutil.which
    rec = _Recorder()
    rec.install()
    try:
        # Wayland: wl-copy (stdin).
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd in ("wl-copy",
                                                                "wl-paste") else None
        ok = clipboard.write("halo dari hp")
        check("write() True saat wl-copy tersedia", ok is True)
        check("write() memakai wl-copy", any(c == "wl-copy" for c in rec.calls))

        # X11: xclip -selection clipboard (stdin).
        rec.calls.clear()
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "xclip" else None
        ok = clipboard.write("halo x")
        check("write() memakai xclip", ok is True
              and any(c == "xclip -selection clipboard" for c in rec.calls))

        # X11: xsel --clipboard --input (stdin).
        rec.calls.clear()
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "xsel" else None
        ok = clipboard.write("halo s")
        check("write() memakai xsel", ok is True
              and any(c == "xsel --clipboard --input" for c in rec.calls))

        # Gagal (rc != 0) -> False, tidak crash.
        rec.calls.clear()
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "xsel" else None
        rec.set_rc("xsel", 1)
        check("write() False saat tool gagal", clipboard.write("x") is False)
    finally:
        rec.restore()
        shutil.which = orig_which


def test_graceful_tanpa_tool():
    """read()/write() tidak crash & menolak lembut kalau tool tidak ada."""
    import shutil
    orig_which = shutil.which
    rec = _Recorder()
    rec.install()
    try:
        shutil.which = lambda cmd: None
        check("read() tanpa tool -> ''", clipboard.read() == "")
        check("write() tanpa tool -> False", clipboard.write("x") is False)
    finally:
        rec.restore()
        shutil.which = orig_which
    check("tanpa tool: tidak ada pemanggilan subprocess sama sekali",
          rec.calls == [])


def main():
    print("=== UJI UNIT: modul clipboard PC (v3.7) ===")
    ready = test_modul_ada()
    if ready:
        test_deteksi_tool()
        test_read_memakai_tool_benar()
        test_write_memakai_tool_benar()
        test_graceful_tanpa_tool()
    print()
    if SKIPPED:
        print(f"{len(SKIPPED)} SKIP (blocker sementara):")
        for s in SKIPPED:
            print(f"  - {s}")
        print()
    if FAILED:
        print(f"{len(FAILED)} UJI CLIPBOARD GAGAL:")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print("SEMUA UJI CLIPBOARD LULUS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
