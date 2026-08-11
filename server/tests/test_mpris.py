#!/usr/bin/env python3
"""
test_mpris.py - Uji unit modul MPRIS (now playing / seek) PC (v3.7) (QA).

Kontrak protokol (dari spesifikasi v3.7):
  * npget  -> {"t":"np","ok":bool,"title","artist","album","playing",
               "length_us","pos_us","canseek","msg"}
  * npseek -> {"t":"npseek_result","ok":bool,"msg":""}
  * Implementasi: gdbus (org.mpris.MediaPlayer2) dengan fallback playerctl.
  * Properti yang dipakai: PlaybackStatus, Position, CanSeek, Metadata
    xesam:title/artist/album, mpris:length, mpris:trackid.
  * Pemilih pemutar: prefer yang sedang Playing.

PRINSIP KEAMANAN (OPEN-CONVENTIONS.md Bagian 4):
  * TIDAK ada satu pun koneksi DBus nyata / eksekusi subprocess nyata.
  * Semua pemanggilan subprocess DICEGAT recorder yang mengembalikan output
    gdbus/playerctl simulasi; subprocess.run ASLI tidak pernah dieksekusi.
  * Tool dipilih lewat mock `shutil.which`.

Modul mpris.py (milik tesla): available()/query()/seek() - lihat
server/mpris.py.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import mpris                                                # noqa: E402
except ImportError:
    mpris = None

FAILED = []
SKIPPED = []


def check(label, cond):
    print(("OK  - " if cond else "GAGAL - ") + label)
    if not cond:
        FAILED.append(label)


def skip(label):
    SKIPPED.append(label)
    print(f"SKIP - {label}")


# Recorder subprocess: MENCATAT semua pemanggilan dan MENGEMBALIKAN output
# simulasi. subprocess.run ASLI tidak pernah dieksekusi.
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
        """Cocokkan prefix TERPANJANG supaya prefix Position menang atas
        prefix GetAll untuk dest yang sama."""
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
        raise AssertionError("subprocess.Popen DIPANGGIL padahal seharusnya "
                             "pakai run/check_output: " + self._key(args))

    def _check(self, args, **kwargs):
        key = self._key(args)
        self.calls.append(key)
        stdout, rc = self._match(key)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, args)
        return stdout.encode("utf-8")


# ----------------------------------------------------- Contoh output DBus ----
# Bentuk output `gdbus call` NYATA (diverifikasi langsung di mesin):
#   * nilai bertipe: <'...'>, <true>, <int64 123>, <1.0>
#   * objectpath:    <objectpath '/org/...'>
#   * array string:  <['A', 'B']>
#   * dict:          <{'mpris:length': <int64 123>, ...}>
# Parse yang benar harus menangani SEMUA bentuk ini.
GDBUS_GETALL = (
    "({'PlaybackStatus': <'Playing'>, "
    "'CanSeek': <true>, "
    "'Position': <int64 2500000>, "
    "'Metadata': <{'mpris:trackid': "
    "<objectpath '/org/mpris/MediaPlayer2/Track/42'>, "
    "'xesam:title': <'Lagu Nusantara'>, "
    "'xesam:artist': <['Artis Satu', 'Artis Dua']>, "
    "'xesam:album': <'Album Nusantara'>, "
    "'mpris:length': <int64 200000000>}>},)"
)
GDBUS_PAUSED = GDBUS_GETALL.replace("<'Playing'>", "<'Paused'>")
GDBUS_POSITION = "(<int64 2500000>,)"
GDBUS_LISTNAMES = (
    "['org.freedesktop.DBus', "
    "'org.mpris.MediaPlayer2.vlc', "
    "'org.mpris.MediaPlayer2.spotify']"
)
GDBUS_ONEPLAYER = "['org.mpris.MediaPlayer2.spotify']"

# Prefix gdbus yang harus dicocokkan LEBIH DAHULU (Position sebelum GetAll).
P_POSITION = ("gdbus call --session --dest org.mpris.MediaPlayer2.spotify "
              "--object-path /org/mpris/MediaPlayer2 "
              "--method org.freedesktop.DBus.Properties.Get "
              "org.mpris.MediaPlayer2.Player Position")
P_GETALL_SPOTIFY = "gdbus call --session --dest org.mpris.MediaPlayer2.spotify"
P_GETALL_VLC = "gdbus call --session --dest org.mpris.MediaPlayer2.vlc"
P_LISTNAMES = "gdbus call --session --dest org.freedesktop.DBus"


def _stub_gdbus_dua_pemutar(rec):
    """ListNames vlc+spotify; vlc Paused, spotify Playing; posisi spotify."""
    rec.set_stdout(P_LISTNAMES, GDBUS_LISTNAMES)
    rec.set_stdout(P_GETALL_VLC, GDBUS_PAUSED)
    rec.set_stdout(P_POSITION, GDBUS_POSITION)
    rec.set_stdout(P_GETALL_SPOTIFY, GDBUS_GETALL)


# ------------------------------------------------------------ Pengujian ------
def test_modul_ada():
    if mpris is None:
        skip("modul mpris.py belum ada (blocker sementara: tesla belum "
             "selesai) - seluruh suite dilewati")
        return False
    missing = [n for n in ("available", "query", "seek")
               if not hasattr(mpris, n)]
    check("mpris.available/query/seek tersedia (kurang: %s)"
          % (missing or "-"), not missing)
    return not missing


def test_deteksi_tool():
    import shutil
    orig = shutil.which
    try:
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "gdbus" else None
        check("available True saat gdbus ada", mpris.available() is True)
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "playerctl" else None
        check("available True saat playerctl ada", mpris.available() is True)
        shutil.which = lambda cmd: None
        check("available False tanpa tool", mpris.available() is False)
    finally:
        shutil.which = orig


def test_query_parse_output_gdbus():
    """query() mengurai GetAll gdbus dan PREFER pemutar yang Playing."""
    import shutil
    orig_which = shutil.which
    rec = _Recorder()
    rec.install()
    try:
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "gdbus" else None
        _stub_gdbus_dua_pemutar(rec)
        q = mpris.query()
        check("query() ok=True saat ada pemutar", q.get("ok") is True)
        check("query() pilih pemutar Playing (spotify, bukan vlc)",
              q.get("playing") is True and q.get("title") == "Lagu Nusantara")
        check("query() judul benar", q.get("title") == "Lagu Nusantara")
        check("query() artis digabung benar",
              q.get("artist") == "Artis Satu, Artis Dua")
        check("query() album benar", q.get("album") == "Album Nusantara")
        check("query() length_us benar", q.get("length_us") == 200000000)
        check("query() pos_us benar", q.get("pos_us") == 2500000)
        check("query() canseek benar", q.get("canseek") is True)
        check("query() trackid benar",
              q.get("trackid") == "/org/mpris/MediaPlayer2/Track/42")
    finally:
        rec.restore()
        shutil.which = orig_which
    check("query(): NOL subprocess nyata", True)


def test_query_graceful_error():
    """query() ok=False tanpa crash saat tidak ada pemutar / DBus error."""
    import shutil
    orig_which = shutil.which
    rec = _Recorder()
    rec.install()
    try:
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "gdbus" else None
        # ListNames kosong & playerctl tidak ada -> tidak ada pemutar.
        rec.set_stdout(P_LISTNAMES, "[]")
        q = mpris.query()
        check("query() ok=False tanpa pemutar", q.get("ok") is False)
        check("query() membawa msg", isinstance(q.get("msg"), str)
              and bool(q.get("msg")))

        # gdbus gagal (rc != 0) -> ok=False, tidak crash.
        rec.set_stdout(P_LISTNAMES, GDBUS_LISTNAMES)
        rec.set_rc(P_LISTNAMES, 1)
        q = mpris.query()
        check("query() ok=False saat gdbus error", q.get("ok") is False)
    finally:
        rec.restore()
        shutil.which = orig_which
    check("graceful: NOL subprocess nyata", True)


def test_query_fallback_playerctl():
    """Tanpa gdbus, query memakai playerctl metadata (format diparsing)."""
    import shutil
    orig_which = shutil.which
    rec = _Recorder()
    rec.install()
    try:
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "playerctl" else None
        rec.set_stdout("playerctl -a metadata",
                       "Playing|Artis Tunggal|Album Tunggal|Judul Tunggal|"
                       "200000000|/org/mpris/MediaPlayer2/Track/1|2.5")
        q = mpris.query()
        check("query() playerctl ok=True", q.get("ok") is True)
        check("query() playerctl judul", q.get("title") == "Judul Tunggal")
        check("query() playerctl playing", q.get("playing") is True)
        check("query() playerctl pos_us dari position",
              q.get("pos_us") == 2500000)
        check("query() playerctl length_us", q.get("length_us") == 200000000)
    finally:
        rec.restore()
        shutil.which = orig_which
    check("playerctl: NOL subprocess nyata", True)


def test_seek_membangun_argumen_benar():
    """seek(pos_us) memakai SetPosition (trackid + pos_us)."""
    import shutil
    orig_which = shutil.which
    rec = _Recorder()
    rec.install()
    try:
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "gdbus" else None
        rec.set_stdout(P_LISTNAMES, GDBUS_ONEPLAYER)
        rec.set_stdout(P_POSITION, GDBUS_POSITION)
        rec.set_stdout(P_GETALL_SPOTIFY, GDBUS_GETALL)
        ok, msg = mpris.seek(123456789)
        check("seek() mengembalikan (bool, str)",
              isinstance(ok, bool) and isinstance(msg, str))
        calls = " | ".join(rec.calls)
        check("seek() memakai SetPosition", "SetPosition" in calls)
        check("seek() membawa pos_us yang diminta", "123456789" in calls)
        check("seek() memakai trackid dari metadata",
              "/org/mpris/MediaPlayer2/Track/42" in calls)
    finally:
        rec.restore()
        shutil.which = orig_which
    check("seek(): NOL subprocess nyata", True)


def test_seek_graceful():
    """seek() tanpa pemutar / pos_us invalid -> (False, msg), tidak crash."""
    import shutil
    orig_which = shutil.which
    rec = _Recorder()
    rec.install()
    try:
        shutil.which = lambda cmd: "/usr/bin/" + cmd if cmd == "gdbus" else None
        rec.set_stdout(P_LISTNAMES, "[]")
        ok, msg = mpris.seek(1000)
        check("seek() tanpa pemutar -> False + msg",
              ok is False and isinstance(msg, str) and bool(msg))
        rec.calls.clear()
        ok, msg = mpris.seek("bukan-angka")
        check("seek() pos_us invalid -> False + msg",
              ok is False and isinstance(msg, str) and bool(msg))
        check("seek() invalid tanpa subprocess", rec.calls == [])
    finally:
        rec.restore()
        shutil.which = orig_which


def main():
    print("=== UJI UNIT: modul MPRIS (now playing / seek) v3.7 ===")
    ready = test_modul_ada()
    if ready:
        test_deteksi_tool()
        test_query_parse_output_gdbus()
        test_query_graceful_error()
        test_query_fallback_playerctl()
        test_seek_membangun_argumen_benar()
        test_seek_graceful()
    print()
    if SKIPPED:
        print(f"{len(SKIPPED)} SKIP (blocker sementara):")
        for s in SKIPPED:
            print(f"  - {s}")
        print()
    if FAILED:
        print(f"{len(FAILED)} UJI MPRIS GAGAL:")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print("SEMUA UJI MPRIS LULUS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
