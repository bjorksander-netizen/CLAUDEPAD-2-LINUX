#!/usr/bin/env python3
"""
CLAUDEPAD - Binary protocol encoder/decoder (v3.3).
Menggantikan JSON untuk command yang sering dikirim (move, scroll, click, dll).
Paket 4-10x lebih kecil dari JSON, mengurangi latency & CPU di kedua sisi.

Wire format:
  [CMD_ID: 1 byte][PAYLOAD: 0..N bytes]

Semua integer multi-byte memakai little-endian.
"""

import struct

# ── Command IDs ──────────────────────────────────────────────────────────────
CMD_MOVE       = 0x01   # dx: i16, dy: i16
CMD_CLICK      = 0x02   # button_id: u8, double: u8 (0/1)
CMD_DOWN       = 0x03   # button_id: u8
CMD_UP         = 0x04   # button_id: u8
CMD_SCROLL     = 0x05   # dy: i16, dx: i16
CMD_ZOOM       = 0x06   # dir: i8
CMD_GESTURE    = 0x07   # gesture_id: u8
CMD_TEXT       = 0x08   # len: u16, utf8_bytes:[len]
CMD_KEY        = 0x09   # key_id: u8, mod_count: u8, mod_ids: [u8]
CMD_MEDIA      = 0x0A   # action_id: u8
CMD_VOLSET     = 0x0B   # volume: u8
CMD_VOLGET     = 0x0C   # (empty)
CMD_RADIO      = 0x0D   # device_id: u8
CMD_POWER      = 0x0E   # action_id: u8
CMD_BRIGHT     = 0x0F   # delta: i8
CMD_PING       = 0x10   # (empty)
CMD_SCROLLINFO = 0x13   # server -> client: posisi scroll window aktif

# ── Lookup tables ────────────────────────────────────────────────────────────
_BUTTON_IDS = {"left": 0, "right": 1, "middle": 2}
_BUTTON_NAMES = {v: k for k, v in _BUTTON_IDS.items()}

_GESTURE_IDS = {"taskview": 0, "showdesktop": 1, "appnext": 2, "appprev": 3}
_GESTURE_NAMES = {v: k for k, v in _GESTURE_IDS.items()}

_MEDIA_IDS = {
    "playpause": 0, "next": 1, "prev": 2, "stop": 3,
    "volup": 4, "voldown": 5, "mute": 6,
}
_MEDIA_NAMES = {v: k for k, v in _MEDIA_IDS.items()}

_RADIO_IDS = {"wifi": 0, "bluetooth": 1, "hotspot": 2}
_RADIO_NAMES = {v: k for k, v in _RADIO_IDS.items()}

_POWER_IDS = {"shutdown": 0, "restart": 1, "sleep": 2, "lock": 3}
_POWER_NAMES = {v: k for k, v in _POWER_IDS.items()}

# VK codes yang umum dipakai (sama dengan input_core.VK)
_VK_IDS = {
    "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "backspace": 0x08, "delete": 0x2E,
    "space": 0x20, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdn": 0x22, "win": 0x5B,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "insert": 0x2D, "capslock": 0x14,
    "printscreen": 0x2C, "d": 0x44,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}
_VK_NAMES = {v: k for k, v in _VK_IDS.items()}

# Key ID 0x00 = custom/UTF8, diikuti len:u16 + bytes
KEY_CUSTOM = 0x00


# ── Encoder ──────────────────────────────────────────────────────────────────

def encode(msg: dict) -> bytes | None:
    """
    Encode satu pesan protokol ke binary.  Kembalikan None kalau command
    tidak dikenal atau payload tidak valid — caller harus fallback ke JSON.
    """
    t = msg.get("t")

    if t == "move":
        dx = _clamp_i16(msg.get("dx", 0))
        dy = _clamp_i16(msg.get("dy", 0))
        return struct.pack("<Bhh", CMD_MOVE, dx, dy)

    if t == "click":
        bid = _BUTTON_IDS.get(msg.get("b", "left"), 0)
        dbl = 1 if msg.get("double", False) else 0
        return struct.pack("<BBB", CMD_CLICK, bid, dbl)

    if t == "down":
        bid = _BUTTON_IDS.get(msg.get("b", "left"), 0)
        return struct.pack("<BB", CMD_DOWN, bid)

    if t == "up":
        bid = _BUTTON_IDS.get(msg.get("b", "left"), 0)
        return struct.pack("<BB", CMD_UP, bid)

    if t == "scroll":
        dy = _clamp_i16(msg.get("dy", 0))
        dx = _clamp_i16(msg.get("dx", 0))
        return struct.pack("<Bhh", CMD_SCROLL, dy, dx)

    if t == "zoom":
        d = _clamp_i8(msg.get("dir", 1))
        return struct.pack("<Bb", CMD_ZOOM, d)

    if t == "gesture":
        gid = _GESTURE_IDS.get(msg.get("g", ""), None)
        if gid is None:
            return None
        return struct.pack("<BB", CMD_GESTURE, gid)

    if t == "text":
        text = msg.get("s", "")
        encoded = text.encode("utf-8")
        if len(encoded) > 65535:
            return None
        return struct.pack("<BH", CMD_TEXT, len(encoded)) + encoded

    if t == "key":
        k = msg.get("k", "")
        mods = msg.get("mods") or []
        vk = _VK_IDS.get(k.lower(), None)
        if vk is not None:
            mod_bytes = bytes([_VK_IDS.get(m.lower(), 0x11) for m in mods])
            if len(mod_bytes) > 255:
                return None
            return struct.pack("<BB", CMD_KEY, vk) + struct.pack("B", len(mod_bytes)) + mod_bytes
        # Custom key (UTF-8 character)
        key_bytes = k.encode("utf-8")
        if len(key_bytes) > 65535:
            return None
        mod_bytes = bytes([_VK_IDS.get(m.lower(), 0x11) for m in mods])
        if len(mod_bytes) > 255:
            return None
        header = struct.pack("<BBH", CMD_KEY, KEY_CUSTOM, len(key_bytes))
        return header + key_bytes + struct.pack("B", len(mod_bytes)) + mod_bytes

    if t == "media":
        mid = _MEDIA_IDS.get(msg.get("a", ""), None)
        if mid is None:
            return None
        return struct.pack("<BB", CMD_MEDIA, mid)

    if t == "volset":
        v = max(0, min(100, int(msg.get("v", 50))))
        return struct.pack("<BB", CMD_VOLSET, v)

    if t == "volget":
        return struct.pack("<B", CMD_VOLGET)

    if t == "radio":
        did = _RADIO_IDS.get(msg.get("d", ""), None)
        if did is None:
            return None
        return struct.pack("<BB", CMD_RADIO, did)

    if t == "power":
        aid = _POWER_IDS.get(msg.get("a", ""), None)
        if aid is None:
            return None
        return struct.pack("<BB", CMD_POWER, aid)

    if t == "bright":
        d = _clamp_i8(msg.get("d", 10))
        return struct.pack("<Bb", CMD_BRIGHT, d)

    if t == "ping":
        return struct.pack("<B", CMD_PING)

    return None


# ── Decoder ──────────────────────────────────────────────────────────────────

def decode(data: bytes) -> dict | None:
    """
    Decode satu paket binary ke dict JSON.  Kembalikan None kalau data
    tidak valid atau command ID tidak dikenal.
    """
    if len(data) < 1:
        return None

    cmd = data[0]

    try:
        if cmd == CMD_MOVE:
            _, dx, dy = struct.unpack_from("<Bhh", data, 0)
            return {"t": "move", "dx": dx, "dy": dy}

        if cmd == CMD_CLICK:
            _, bid, dbl = struct.unpack_from("<BBB", data, 0)
            return {"t": "click", "b": _BUTTON_NAMES.get(bid, "left"), "double": dbl == 1}

        if cmd == CMD_DOWN:
            _, bid = struct.unpack_from("<BB", data, 0)
            return {"t": "down", "b": _BUTTON_NAMES.get(bid, "left")}

        if cmd == CMD_UP:
            _, bid = struct.unpack_from("<BB", data, 0)
            return {"t": "up", "b": _BUTTON_NAMES.get(bid, "left")}

        if cmd == CMD_SCROLL:
            _, dy, dx = struct.unpack_from("<Bhh", data, 0)
            return {"t": "scroll", "dy": dy, "dx": dx}

        if cmd == CMD_ZOOM:
            _, d = struct.unpack_from("<Bb", data, 0)
            return {"t": "zoom", "dir": d}

        if cmd == CMD_GESTURE:
            _, gid = struct.unpack_from("<BB", data, 0)
            return {"t": "gesture", "g": _GESTURE_NAMES.get(gid, "")}

        if cmd == CMD_TEXT:
            _, tlen = struct.unpack_from("<BH", data, 0)
            text = data[3:3 + tlen].decode("utf-8")
            return {"t": "text", "s": text}

        if cmd == CMD_KEY:
            _, vk_or_zero = struct.unpack_from("<BB", data, 0)
            pos = 2
            if vk_or_zero == KEY_CUSTOM:
                klen = struct.unpack_from("<H", data, pos)[0]
                pos += 2
                k = data[pos:pos + klen].decode("utf-8")
                pos += klen
            else:
                k = _VK_NAMES.get(vk_or_zero, "")
                pos = 2
            mcount = data[pos]
            pos += 1
            mods = [_VK_NAMES.get(data[pos + i], "") for i in range(mcount)]
            return {"t": "key", "k": k, "mods": mods}

        if cmd == CMD_MEDIA:
            _, mid = struct.unpack_from("<BB", data, 0)
            return {"t": "media", "a": _MEDIA_NAMES.get(mid, "")}

        if cmd == CMD_VOLSET:
            _, v = struct.unpack_from("<BB", data, 0)
            return {"t": "volset", "v": v}

        if cmd == CMD_VOLGET:
            return {"t": "volget"}

        if cmd == CMD_RADIO:
            _, did = struct.unpack_from("<BB", data, 0)
            return {"t": "radio", "d": _RADIO_NAMES.get(did, "")}

        if cmd == CMD_POWER:
            _, aid = struct.unpack_from("<BB", data, 0)
            return {"t": "power", "a": _POWER_NAMES.get(aid, "")}

        if cmd == CMD_BRIGHT:
            _, d = struct.unpack_from("<Bb", data, 0)
            return {"t": "bright", "d": d}

        if cmd == CMD_PING:
            return {"t": "ping"}

    except (struct.error, IndexError, UnicodeDecodeError):
        return None

    return None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _clamp_i16(v):
    return max(-32768, min(32767, int(v)))


def _clamp_i8(v):
    return max(-128, min(127, int(v)))
