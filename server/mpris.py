#!/usr/bin/env python3
"""
Query & seek pemutar media lewat MPRIS.

MPRIS (Media Player Remote Interfacing Specification) adalah standar D-Bus
untuk memutar/menjeda/mencari tahu pemutar media di desktop Linux. Query
dilakukan lewat `gdbus` (tersedia di hampir semua distro); bila gdbus tidak
ada, fallback ke `playerctl`.

Kontrak dengan aplikasi HP (lihat input_core.handle_message):
  * query() -> dict  {ok,title,artist,album,playing,length_us,pos_us,
                      canseek,trackid,msg}
  * seek(pos_us) -> (bool, str)   pos_us dalam microsecond

Semua panggilan punya timeout ketat dan TIDAK pernah memblokir. Tanpa
pemutar / tanpa D-Bus, query() mengembalikan ok:false secara anggun.

Keamanan (OPEN-CONVENTIONS Bagian 4): saat mode sandbox aktif, query()
mengembalikan ok:false "sandbox" dan seek() disimulasikan - TIDAK ada
subprocess yang dijalankan.
"""
import ast
import re
import shutil
import subprocess

_PREFIX = "org.mpris.MediaPlayer2."


def _sandbox():
    import input_core
    return input_core.is_sandbox()


def _log(msg):
    import input_core
    input_core.log(msg)


def _has(cmd):
    return shutil.which(cmd) is not None


def _run(args, timeout=8):
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


def available():
    """True kalau ada gdbus atau playerctl (syarat query/seek)."""
    return _has("gdbus") or _has("playerctl")


def _parse_gdbus_call(rc, out):
    """
    Ubah output `gdbus call` (nilai bertipe, mis. <true>, <'Playing'>,
    <int64 2500000>, <['A', 'B']>) menjadi struktur Python via
    ast.literal_eval. None kalau gagal.
    """
    if rc != 0 or not out:
        return None
    s = out.strip()
    # String lebih dulu supaya isi yang mengandung < > tidak ikut tertransform.
    s = re.sub(r"<'((?:[^'\\]|\\.)*)'\s*>", r"'\1'", s)
    # Tipe objectpath gdbus: <objectpath '/org/...'> -> '/org/...'
    s = re.sub(r"<objectpath\s+'((?:[^'\\]|\\.)*)'\s*>", r"'\1'", s)
    s = re.sub(r"<true\s*>", "True", s)
    s = re.sub(r"<false\s*>", "False", s)
    # Angka bertipe GLib (gdbus menampilkan <int64 N>, <double X>, ...).
    s = re.sub(r"<(?:int64|uint64|int32|uint32|int16|byte|double|single)"
               r"\s+(-?(?:\d+\.\d+|\d+))\s*>", r"\1", s)
    s = re.sub(r"<(-?\d+\.\d+)\s*>", r"\1", s)
    s = re.sub(r"<(-?\d+)\s*>", r"\1", s)
    # Array bertipe, mis. <['Artis Satu', 'Artis Dua']>.
    s = re.sub(r"<(\[[^\]]*\])\s*>", r"\1", s)
    # Dict bertipe, mis. <{'mpris:trackid': ...}> -> {...}.
    s = re.sub(r"<(\{.*\})\s*>", r"\1", s)
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return None


def _players():
    """Daftar nama bus MPRIS yang aktif di session bus (via gdbus)."""
    rc, out = _run(["gdbus", "call", "--session",
                    "--dest", "org.freedesktop.DBus",
                    "--object-path", "/org/freedesktop/DBus",
                    "--method", "org.freedesktop.DBus.ListNames"])
    parsed = _parse_gdbus_call(rc, out)
    if isinstance(parsed, tuple) and parsed:
        parsed = parsed[0]
    if not isinstance(parsed, list):
        return []
    return [n for n in parsed
            if isinstance(n, str) and n.startswith(_PREFIX)
            and n != _PREFIX + "playerctld"]


def _player_props(dest):
    """Properti org.mpris.MediaPlayer2.Player untuk satu pemutar."""
    rc, out = _run(["gdbus", "call", "--session", "--dest", dest,
                    "--object-path", "/org/mpris/MediaPlayer2",
                    "--method", "org.freedesktop.DBus.Properties.GetAll",
                    "org.mpris.MediaPlayer2.Player"])
    parsed = _parse_gdbus_call(rc, out)
    if isinstance(parsed, tuple) and parsed and isinstance(parsed[0], dict):
        return parsed[0]
    return {}


def _position_us(dest):
    """Posisi pemutaran saat ini (microsecond) lewat properti Position."""
    rc, out = _run(["gdbus", "call", "--session", "--dest", dest,
                    "--object-path", "/org/mpris/MediaPlayer2",
                    "--method", "org.freedesktop.DBus.Properties.Get",
                    "org.mpris.MediaPlayer2.Player", "Position"])
    parsed = _parse_gdbus_call(rc, out)
    if isinstance(parsed, tuple) and parsed:
        v = parsed[0]
        if isinstance(v, bool):
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0
    return 0


def _pick_player():
    """Pemutar terbaik: yang sedang Playing, kalau tidak ada yang pertama."""
    if not _has("gdbus"):
        return None
    players = _players()
    if not players:
        return None
    for dest in players:
        if _player_props(dest).get("PlaybackStatus") == "Playing":
            return dest
    return players[0]


def _empty(msg):
    return {"ok": False, "title": "", "artist": "", "album": "",
            "playing": False, "length_us": 0, "pos_us": 0,
            "canseek": False, "trackid": "", "msg": msg}


def _build(dest, props):
    """Bentuk dict np dari properti MPRIS satu pemutar."""
    meta = props.get("Metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    title = str(meta.get("xesam:title") or "")
    artists = meta.get("xesam:artist") or []
    if isinstance(artists, list):
        artist = ", ".join(str(a) for a in artists)
    else:
        artist = str(artists) if artists else ""
    album = str(meta.get("xesam:album") or "")
    try:
        length_us = int(meta.get("mpris:length") or 0)
    except (TypeError, ValueError):
        length_us = 0
    trackid = str(meta.get("mpris:trackid") or "")
    canseek = bool(props.get("CanSeek")) or bool(trackid)
    return {
        "ok": True,
        "title": title,
        "artist": artist,
        "album": album,
        "playing": props.get("PlaybackStatus") == "Playing",
        "length_us": length_us,
        "pos_us": _position_us(dest),
        "canseek": canseek,
        "trackid": trackid,
        "msg": "",
    }


def _query_gdbus(players):
    for dest in players:
        props = _player_props(dest)
        if props and props.get("PlaybackStatus") == "Playing":
            return _build(dest, props)
    dest = players[0]
    props = _player_props(dest)
    if not props:
        return _empty("tidak ada data MPRIS")
    return _build(dest, props)


def _query_playerctl():
    rc, out = _run(["playerctl", "-a", "metadata", "--format",
                    "{{status}}|{{xesam:artist}}|{{xesam:album}}|"
                    "{{xesam:title}}|{{mpris:length}}|{{mpris:trackid}}|"
                    "{{position}}"])
    if rc != 0:
        return _empty("tidak ada pemutar media (MPRIS)")
    best = None
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 7:
            continue
        if parts[0] == "Playing":
            best = parts
            break
        if best is None:
            best = parts
    if best is None:
        return _empty("tidak ada pemutar media (MPRIS)")
    status, artist, album, title, length, trackid, position = best[:7]
    try:
        length_us = int(length) if length else 0
    except ValueError:
        length_us = 0
    try:
        pos_us = int(float(position) * 1_000_000) if position else 0
    except ValueError:
        pos_us = 0
    return {
        "ok": True,
        "title": title,
        "artist": artist,
        "album": album,
        "playing": status == "Playing",
        "length_us": length_us,
        "pos_us": pos_us,
        "canseek": bool(trackid) or bool(length_us),
        "trackid": trackid,
        "msg": "",
    }


def query():
    """
    Status pemutar media saat ini. Selalu dict dengan bentuk np; kalau tidak
    ada pemutar/DBus, ok:False dan msg menjelaskan alasannya.
    """
    if _sandbox():
        _log("sandbox: simulasi mpris.query -> tidak ada pemutar")
        return _empty("sandbox")
    if _has("gdbus"):
        players = _players()
        if players:
            return _query_gdbus(players)
        if _has("playerctl"):
            return _query_playerctl()
        return _empty("tidak ada pemutar media (MPRIS)")
    if _has("playerctl"):
        return _query_playerctl()
    return _empty("gdbus/playerctl tidak tersedia")


def _seek_gdbus(dest, pos_us):
    props = _player_props(dest)
    meta = props.get("Metadata") or {}
    trackid = str(meta.get("mpris:trackid") or "") if isinstance(meta, dict) else ""
    if trackid:
        rc, _ = _run(["gdbus", "call", "--session", "--dest", dest,
                      "--object-path", "/org/mpris/MediaPlayer2",
                      "--method", "org.mpris.MediaPlayer2.Player.SetPosition",
                      "o", trackid, "x", str(pos_us)])
        if rc == 0:
            return True, ""
    delta = pos_us - _position_us(dest)
    rc, out = _run(["gdbus", "call", "--session", "--dest", dest,
                    "--object-path", "/org/mpris/MediaPlayer2",
                    "--method", "org.mpris.MediaPlayer2.Player.Seek",
                    "x", str(delta)])
    if rc == 0:
        return True, ""
    return False, (out[:120] or "pemutar menolak perintah seek")


def _seek_playerctl(pos_us):
    rc, out = _run(["playerctl", "position", f"{pos_us / 1_000_000.0:.6f}"])
    if rc == 0:
        return True, ""
    return False, (out[:120] or "playerctl menolak perintah seek")


def seek(pos_us):
    """
    Pindah posisi pemutar ke pos_us (microsecond). (bool, msg).
    Prioritas SetPosition (butuh trackid); fallback Seek relatif.
    """
    if _sandbox():
        _log(f"sandbox: simulasi mpris.seek({pos_us})")
        return True, "seek disimulasikan (sandbox)"
    try:
        pos_us = int(pos_us)
    except (TypeError, ValueError):
        return False, "pos_us harus bilangan bulat"
    if _has("gdbus"):
        dest = _pick_player()
        if dest is not None:
            return _seek_gdbus(dest, pos_us)
        if _has("playerctl"):
            return _seek_playerctl(pos_us)
        return False, "tidak ada pemutar media (MPRIS)"
    if _has("playerctl"):
        return _seek_playerctl(pos_us)
    return False, "gdbus/playerctl tidak tersedia"
