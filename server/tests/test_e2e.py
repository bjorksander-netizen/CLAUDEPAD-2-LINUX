#!/usr/bin/env python3
"""
Uji end-to-end server CLAUDEPAD Linux.

Dijalankan dari folder server/ (juga oleh CI). Tidak butuh display, tidak
butuh /dev/uinput: backend input jatuh ke NullBackend dan yang diuji adalah
protokol - persis lapisan yang harus cocok dengan APK.
"""
import asyncio
import base64
import json
import os
import socket
import sys
import urllib.request

# Modul server ada di folder induk; uji ini sengaja bisa dijalankan baik
# dari server/ maupun dari server/tests/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = ["test", "--nogui"]

import binary_protocol as bp                                   # noqa: E402
import crypto_box as cb                                        # noqa: E402
import input_core as core                                      # noqa: E402
import pc_server as srv                                        # noqa: E402
import system_ctl                                              # noqa: E402
import websockets                                              # noqa: E402

URL = "ws://127.0.0.1:8765/ws"
FAILED = []


def check(label, cond):
    if cond:
        print(f"OK  - {label}")
    else:
        print(f"GAGAL - {label}")
        FAILED.append(label)


# ------------------------------------------------------------ 1. Kripto ----
def test_crypto():
    key = bytes(range(32))
    nonce = bytes([0, 0, 0, 0, 0, 0, 0, 0x4a, 0, 0, 0, 0])
    plain = (b"Ladies and Gentlemen of the class of '99: If I could offer you "
             b"only one tip for the future, sunscreen would be it.")
    ct = cb.chacha20(key, nonce, plain, 1)
    check("ChaCha20 cocok vektor RFC 8439",
          ct[:16] == bytes.fromhex("6e2e359a2568f98041ba0728dd0d6981"))

    salt = cb.new_salt()
    a = cb.Session.derive("1234", salt)
    b = cb.Session.derive("1234", salt)
    check("seal/open bolak-balik", b.open(a.seal(b"halo")) == b"halo")

    c = cb.Session.derive("9999", salt)
    try:
        c.open(a.seal(b"x"))
        check("kunci salah ditolak", False)
    except ValueError:
        check("kunci salah ditolak", True)

    pub_pem, priv = cb.generate_rsa_keypair()
    check("RSA-2048 encrypt/decrypt",
          cb.rsa_decrypt(priv, cb.rsa_encrypt(pub_pem, b"12345678")) == b"12345678")
    pem2 = cb.rsa_pubkey_from_b64(cb.rsa_pubkey_to_b64(pub_pem))
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    check("pubkey base64 round-trip",
          load_pem_public_key(pub_pem, backend=default_backend()).public_numbers()
          == load_pem_public_key(pem2, backend=default_backend()).public_numbers())


# --------------------------------------------------- 2. Binary protocol ----
def test_binary():
    cases = [
        {"t": "move", "dx": 5, "dy": -3}, {"t": "click", "b": "left"},
        {"t": "click", "b": "right", "double": True},
        {"t": "down", "b": "left"}, {"t": "up", "b": "middle"},
        {"t": "scroll", "dy": 120, "dx": -50},
        {"t": "zoom", "dir": 1}, {"t": "zoom", "dir": -1},
        {"t": "gesture", "g": "taskview"}, {"t": "gesture", "g": "showdesktop"},
        {"t": "gesture", "g": "appnext"}, {"t": "gesture", "g": "appprev"},
        {"t": "text", "s": "halo dunia"}, {"t": "key", "k": "enter"},
        {"t": "key", "k": "tab", "mods": ["win"]},
        {"t": "key", "k": "c", "mods": ["ctrl"]},
        {"t": "media", "a": "playpause"}, {"t": "media", "a": "volup"},
        {"t": "volset", "v": 73}, {"t": "volget"},
        {"t": "radio", "d": "wifi"}, {"t": "radio", "d": "bluetooth"},
        {"t": "power", "a": "shutdown"}, {"t": "power", "a": "lock"},
        {"t": "bright", "d": 10}, {"t": "bright", "d": -5}, {"t": "ping"},
    ]
    good = all(bp.decode(bp.encode(m)) is not None and
               bp.decode(bp.encode(m))["t"] == m["t"] for m in cases)
    check(f"{len(cases)} command encode/decode round-trip", good)
    check("move mempertahankan nilai",
          bp.decode(bp.encode({"t": "move", "dx": 1000, "dy": -2000}))["dx"] == 1000)
    check("paket move 5 byte", len(bp.encode({"t": "move", "dx": 0, "dy": 0})) == 5)
    check("command tak dikenal ditolak", bp.encode({"t": "unknown"}) is None)
    check("data rusak ditolak", bp.decode(b"\xff\x00") is None and bp.decode(b"") is None)


# ------------------------------------------------- 3. Lapisan Linux --------
def test_linux_layer():
    sent = []
    msgs = [
        {"t": "move", "dx": 5, "dy": -3}, {"t": "click", "b": "left"},
        {"t": "down", "b": "left"}, {"t": "up", "b": "left"},
        {"t": "scroll", "dy": 120}, {"t": "scroll", "dx": -240},
        {"t": "zoom", "dir": 1}, {"t": "gesture", "g": "taskview"},
        {"t": "gesture", "g": "bogus"}, {"t": "text", "s": "halo"},
        {"t": "key", "k": "enter"}, {"t": "key", "k": "c", "mods": ["ctrl"]},
        {"t": "media", "a": "playpause"}, {"t": "media", "a": "bogus"},
        {"t": "volget"}, {"t": "ping"}, {"t": "unknown"}, {},
    ]
    for m in msgs:
        core.handle_message(m, sent.append)
    check(f"{len(msgs)} varian pesan diproses tanpa crash", True)
    check("PIN 8 digit", len(core.new_pin()) == 8)

    # Backend jatuh ke null tanpa display/uinput, dan itu TIDAK boleh crash.
    check("init_backend aman tanpa display",
          core.init_backend() in ("uinput", "xtest", "xdotool", "none"))

    # Pembulatan scroll: sisa tidak boleh berbalik arah.
    check("divmod_signed positif", core.divmod_signed(200, 120) == (1, 80))
    check("divmod_signed negatif", core.divmod_signed(-200, 120) == (-1, -80))
    check("divmod_signed pas", core.divmod_signed(240, 120) == (2, 0))

    # Penyaringan interface virtual (akar bug koneksi WiFi di versi Windows).
    check("docker0 dianggap virtual", core._is_virtual("docker0"))
    check("veth dianggap virtual", core._is_virtual("veth1a2b3c"))
    check("wlan0 bukan virtual", not core._is_virtual("wlan0"))
    check("hotspot android skor tertinggi",
          core._score("192.168.43.12", "wlan0") == 0)
    check("rentang docker diturunkan", core._score("172.17.0.1", "unknown") >= 90)
    check("local_ips tidak crash", isinstance(core.local_ips(), list))

    # Gesture: tiap desktop harus punya keempat gesture, tanpa kecuali.
    for dname, gmap in core._GESTURE_DEFAULTS.items():
        missing = {"taskview", "showdesktop", "appnext", "appprev"} - set(gmap)
        check(f"gesture lengkap untuk {dname}", not missing)
    check("gesture_map mengembalikan dict", isinstance(core.gesture_map(), dict))

    # Kemampuan harus selalu terlaporkan, walau semuanya kosong.
    caps = core.capabilities()
    check("capabilities punya kunci wajib",
          {"input", "volume", "brightness", "power", "radio"} <= set(caps))
    check("scrollinfo dimatikan di linux", core.get_active_scroll_info() is None)

    # Aksi daya wajib SELALU mengembalikan (bool, str) - klien menunggu balasan.
    # Hanya aksi yang relatif aman diuji langsung: shutdown/restart/sleep/
    # hibernate/logoff TIDAK dijalankan di mesin nyata karena polkit
    # mengizinkannya pada sesi desktop aktif - laptop bisa ikut mati/tidur.
    for act in ("lock", "screenoff", "bogus"):
        r = system_ctl.power_action(act)
        if not (isinstance(r, tuple) and len(r) == 2
                and isinstance(r[0], bool) and isinstance(r[1], str)):
            check(f"power_action('{act}') mengembalikan (bool, str)", False)
            break
    else:
        check("power_action selalu (bool, str)", True)

    for dev in ("wifi", "bluetooth", "hotspot", "bogus"):
        r = core.toggle_radio(dev)
        if not (isinstance(r, tuple) and len(r) == 2):
            check(f"toggle_radio('{dev}') mengembalikan tuple", False)
            break
    else:
        check("toggle_radio selalu (bool, str)", True)

    check("brightness_step mengembalikan tuple",
          isinstance(system_ctl.brightness_step(10), tuple))
    check("firewall_status mengembalikan bool",
          isinstance(core.firewall_status(), bool))


# ----------------------------------------------------- 4. WebSocket E2E ----
async def ws_tests():
    srv.start_server_thread()
    await asyncio.sleep(1.2)
    check("server siap", srv.SERVER_READY.is_set() and not srv.SERVER_ERROR[0])

    async with websockets.connect(URL) as ws:
        bad = "0000" if core.PIN != "0000" else "1111"
        await ws.send(json.dumps({"t": "auth", "pin": bad, "ver": srv.APP_VERSION}))
        check("PIN salah ditolak", json.loads(await ws.recv())["t"] == "auth_fail")

    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "auth", "pin": core.PIN, "ver": "9.9"}))
        r = json.loads(await ws.recv())
        check("versi APK asing ditolak",
              r["t"] == "auth_fail" and r.get("reason") == "version")

    # Kompatibilitas mundur: APK v3.5 dari repo CLAUDEPAD-2 harus tetap masuk.
    core.reset_failed_attempts("127.0.0.1")
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "auth", "pin": core.PIN, "ver": "3.5"}))
        check("APK v3.5 lama tetap diterima",
              json.loads(await ws.recv())["t"] == "auth_ok")

    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "auth", "pin": core.PIN,
                                  "ver": srv.APP_VERSION}))
        r = json.loads(await ws.recv())
        check("auth_ok membawa metadata",
              r["t"] == "auth_ok" and r["host"] == core.HOSTNAME
              and r["version"] == srv.APP_VERSION)
        check("auth_ok melaporkan platform linux", r.get("platform") == "linux")
        check("auth_ok membawa caps", isinstance(r.get("caps"), dict))
        check("auth_ok membawa desktop & session",
              "desktop" in r and "session" in r)

        for m in ({"t": "move", "dx": 3, "dy": 3},
                  {"t": "gesture", "g": "taskview"},
                  {"t": "key", "k": "tab", "mods": ["win"]},
                  {"t": "volset", "v": 50}):
            await ws.send(json.dumps(m))
        await ws.send("{json rusak")
        await ws.send(json.dumps({"t": "ping"}))
        for _ in range(12):
            r = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if r["t"] == "pong":
                break
        else:
            check("pong diterima setelah JSON rusak", False)
        check("pesan kontrol & JSON rusak ditangani", True)

        # Klien tidak boleh menggantung: setiap perintah sistem WAJIB dibalas,
        # walau perangkatnya tidak ada di mesin ini.
        for dev in ("wifi", "bluetooth", "hotspot"):
            await ws.send(json.dumps({"t": "radio", "d": dev}))
            rr = json.loads(await asyncio.wait_for(ws.recv(), 60))
            if not (rr["t"] == "radio_result" and rr["d"] == dev and "msg" in rr):
                check(f"radio_result untuk {dev}", False)
                break
        else:
            check("radio_result selalu dibalas", True)

        await ws.send(json.dumps({"t": "bright", "d": 10}))
        br = json.loads(await asyncio.wait_for(ws.recv(), 30))
        check("bright_result dibalas", br["t"] == "bright_result" and "msg" in br)

        # Hanya aksi aman yang dikirim lewat wire: sleep/hibernate/logoff
        # sungguhan dieksekusi polkit di sesi desktop aktif.
        for act in ("lock", "screenoff"):
            await ws.send(json.dumps({"t": "power", "a": act}))
            pr = json.loads(await asyncio.wait_for(ws.recv(), 30))
            if not (pr["t"] == "power_result" and pr["a"] == act):
                check(f"power_result untuk {act}", False)
                break
        else:
            check("power_result selalu dibalas", True)

    # Pairing token.
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "auth", "pin": core.PIN,
                                  "ver": srv.APP_VERSION}))
        tok = json.loads(await ws.recv()).get("token", "")
        check("server memberi token pairing", bool(tok))
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "auth", "token": tok,
                                  "ver": srv.APP_VERSION}))
        check("token diterima", json.loads(await ws.recv())["t"] == "auth_ok")
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "auth", "token": "palsu",
                                  "ver": srv.APP_VERSION}))
        check("token palsu ditolak",
              json.loads(await ws.recv())["t"] == "auth_fail")

    # Handshake terenkripsi penuh: hello -> salt+pubkey -> auth RSA -> ChaCha20.
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "hello"}))
        h = json.loads(await ws.recv())
        check("hello_ok membawa salt & pubkey",
              h["t"] == "hello_ok" and "salt" in h and "pubkey" in h)
        salt = bytes.fromhex(h["salt"])
        enc_pin = cb.rsa_encrypt(cb.rsa_pubkey_from_b64(h["pubkey"]),
                                 core.PIN.encode())
        await ws.send(json.dumps({"t": "auth",
                                  "pin_enc": base64.b64encode(enc_pin).decode(),
                                  "ver": srv.APP_VERSION}))
        a = json.loads(await ws.recv())
        check("auth RSA diterima & sesi terenkripsi",
              a["t"] == "auth_ok" and a["encrypted"] is True)
        box = cb.Session.derive(core.PIN, salt)
        # scrollinfo dikirim sekali di awal; abaikan sampai ketemu pong.
        await ws.send(box.seal(json.dumps({"t": "ping"}).encode()))
        for _ in range(6):
            raw = await asyncio.wait_for(ws.recv(), 5)
            check("balasan sesi berbentuk biner", isinstance(raw, (bytes, bytearray)))
            msg = json.loads(box.open(raw).decode())
            if msg["t"] == "pong":
                break
        else:
            check("pong terenkripsi diterima", False)
        check("enkripsi lalu lintas end-to-end", True)

    # PIN salah yang terenkripsi RSA juga harus ditolak, bukan diloloskan.
    core.reset_failed_attempts("127.0.0.1")
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "hello"}))
        h = json.loads(await ws.recv())
        enc_bad = cb.rsa_encrypt(cb.rsa_pubkey_from_b64(h["pubkey"]), b"00000000"
                                 if core.PIN != "00000000" else b"11111111")
        await ws.send(json.dumps({"t": "auth",
                                  "pin_enc": base64.b64encode(enc_bad).decode(),
                                  "ver": srv.APP_VERSION}))
        check("PIN salah terenkripsi ditolak",
              json.loads(await ws.recv())["t"] == "auth_fail")

    # Rate limiting harus benar-benar memblokir setelah 3 kali gagal.
    core.reset_failed_attempts("127.0.0.1")
    seen_limit = False
    for _ in range(5):
        async with websockets.connect(URL) as ws:
            await ws.send(json.dumps({"t": "auth", "pin": "00000001",
                                      "ver": srv.APP_VERSION}))
            r = json.loads(await ws.recv())
            if r.get("reason") == "rate_limit":
                seen_limit = True
                break
    check("rate limit memblokir brute-force", seen_limit)
    core.reset_failed_attempts("127.0.0.1")

    # Binary protocol lewat sesi terenkripsi.
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "hello"}))
        h = json.loads(await ws.recv())
        salt = bytes.fromhex(h["salt"])
        enc_pin = cb.rsa_encrypt(cb.rsa_pubkey_from_b64(h["pubkey"]),
                                 core.PIN.encode())
        await ws.send(json.dumps({"t": "auth",
                                  "pin_enc": base64.b64encode(enc_pin).decode(),
                                  "ver": srv.APP_VERSION, "binary": True}))
        a = json.loads(await ws.recv())
        check("server menyetujui binary protocol", a.get("binary") is True)
        box = cb.Session.derive(core.PIN, salt)
        await ws.send(box.seal(bp.encode({"t": "move", "dx": 5, "dy": -3})))
        await ws.send(box.seal(bp.encode({"t": "ping"})))
        for _ in range(6):
            msg = json.loads(box.open(await asyncio.wait_for(ws.recv(), 5)).decode())
            if msg["t"] == "pong":
                break
        else:
            check("pong lewat binary protocol", False)
        check("binary protocol E2E lewat sesi terenkripsi", True)

    await asyncio.sleep(0.5)
    check("registry klien dibersihkan", len(core.CLIENTS) == 0)

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    s.sendto(b"DISCOVER_CLAUDEPAD", ("127.0.0.1", 8766))
    data, _ = s.recvfrom(256)
    s.close()
    parts = data.decode().split("|")
    check("discovery UDP menjawab", parts[0] == "CLAUDEPAD")
    check("discovery menyebut platform linux", len(parts) >= 4 and parts[3] == "linux")

    body = urllib.request.urlopen("http://127.0.0.1:8765/", timeout=5).read().decode()
    check("health HTTP di port 8765",
          "CLAUDEPAD OK" in body and srv.APP_VERSION in body)
    check("health menyebut platform", "linux" in body)
    print(f"    generasi API websockets: {srv._ws_api_generation()} "
          f"(websockets {websockets.__version__})")


def main():
    print("=== 1. kripto ===");            test_crypto()
    print("=== 2. binary protocol ===");   test_binary()
    print("=== 3. lapisan linux ===");     test_linux_layer()
    print("=== 4. websocket e2e ===");     asyncio.run(ws_tests())
    print()
    if FAILED:
        print(f"{len(FAILED)} UJI GAGAL:")
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("SEMUA UJI LULUS")


if __name__ == "__main__":
    main()
