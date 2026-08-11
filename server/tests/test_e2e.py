#!/usr/bin/env python3
"""
Uji end-to-end server CLAUDEPAD Linux.

Dijalankan dari folder server/ (juga oleh CI). Tidak butuh display, tidak
butuh /dev/uinput: backend input jatuh ke NullBackend dan yang diuji adalah
protokol - persis lapisan yang harus cocok dengan APK.
"""
import asyncio
import base64
import inspect
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
import safe_harness                                           # noqa: E402
import system_ctl                                              # noqa: E402
import websockets                                              # noqa: E402

URL = "ws://127.0.0.1:8765/ws"
FAILED = []
SKIPPED = []


def check(label, cond):
    if cond:
        print(f"OK  - {label}")
    else:
        print(f"GAGAL - {label}")
        FAILED.append(label)


def skip(label):
    SKIPPED.append(label)
    print(f"SKIP - {label}")


async def recv_until(ws, wanted, timeout=30):
    """
    Baca pesan JSON sampai dapat t==wanted. Pesan lain (mis. push "clip"
    auto dari poller clipboard) diabaikan supaya urutan balasan
    deterministik.
    """
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout)
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", "replace")
        msg = json.loads(raw)
        if msg.get("t") == wanted:
            return msg


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

    # Aksi daya wajib SELALU mengembalikan (bool, str) - klien menunggu
    # balasan. Semua aksi (termasuk shutdown/restart/sleep/hibernate/logoff/
    # lock/screenoff) aman diuji DI SINI karena safe_harness mem-patch
    # system_ctl.power_action menjadi stub - tidak ada yang dieksekusi nyata.
    for act in ("lock", "screenoff", "shutdown", "restart", "sleep",
                "hibernate", "logoff", "bogus"):
        r = system_ctl.power_action(act)
        if not (isinstance(r, tuple) and len(r) == 2
                and isinstance(r[0], bool) and isinstance(r[1], str)):
            check(f"power_action('{act}') mengembalikan (bool, str)", False)
            break
    else:
        check("power_action selalu (bool, str)", True)

    for dev in ("wifi", "bluetooth", "hotspot", "bogus"):
        r = core.toggle_radio(dev)
        if not (isinstance(r, tuple) and len(r) == 2
                and isinstance(r[0], bool) and isinstance(r[1], str)):
            check(f"toggle_radio('{dev}') mengembalikan (bool, str)", False)
            break
    else:
        check("toggle_radio selalu (bool, str)", True)

    check("brightness_step mengembalikan tuple",
          isinstance(system_ctl.brightness_step(10), tuple))
    check("firewall_status mengembalikan bool",
          isinstance(core.firewall_status(), bool))

    # v3.7 - jalur clipboard unit (safe_harness men-stub clipboard.write,
    # jadi deterministik & NOL subprocess). Anti-loop: konten yang ditulis
    # server sendiri dicatat di ctx["last_server_write"].
    ctx = {"clipsync": True}
    ok, msg = core.clip_set("halo", ctx)
    check("clip_set menulis via stub + catat anti-loop",
          ok is True and ctx.get("last_server_write") == "halo")
    ok, msg = core.clip_set("ditolak", {"clipsync": False})
    check("clip_set ditolak saat clipsync off", ok is False)
    ok, s, msg = core.clip_get()
    check("clip_get via stub (ok, str, msg)",
          ok is True and isinstance(s, str) and isinstance(msg, str))

    # Guard harness: tanpa CLAUDEPAD_ALLOW_REAL, tidak boleh ada SATUPUN
    # eksekusi nyata; semua panggilan di atas harus tercatat sebagai simulasi.
    check("safe_harness: tidak ada aksi sistem nyata dieksekusi",
          safe_harness.REAL_CALLS == [])
    sim_power = [c for c in safe_harness.SIMULATED
                 if c[0] == "system_ctl" and c[1] == "power_action"]
    sim_radio = [c for c in safe_harness.SIMULATED
                 if c[0] == "input_core" and c[1] == "toggle_radio"]
    check("safe_harness: power_action disimulasikan lewat harness",
          len(sim_power) >= 8)
    check("safe_harness: toggle_radio disimulasikan lewat harness",
          len(sim_radio) >= 4)


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

    # Kebijakan v3.7: HANYA APK 3.7 yang diterima (protokol bebas berubah,
    # tidak ada kewajiban kompatibilitas dengan versi Windows/versi lama).
    core.reset_failed_attempts("127.0.0.1")
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "auth", "pin": core.PIN, "ver": "3.5"}))
        r = json.loads(await ws.recv())
        check("APK v3.5 lama ditolak (kebijakan v3.7)",
              r["t"] == "auth_fail" and r.get("reason") == "version")
    core.reset_failed_attempts("127.0.0.1")
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "auth", "pin": core.PIN, "ver": "3.6"}))
        r = json.loads(await ws.recv())
        check("APK v3.6 ditolak (kebijakan v3.7)",
              r["t"] == "auth_fail" and r.get("reason") == "version")

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
        # walau perangkatnya tidak ada di mesin ini. Server berjalan dengan
        # safe_harness aktif, jadi toggle_radio adalah STUB (simulasi) -
        # radio wifi/bluetooth/hotspot TIDAK disentuh sungguhan.
        # recv_until dipakai supaya push "clip" auto dari poller clipboard
        # (stub read -> "") tidak mengganggu urutan balasan.
        for dev in ("wifi", "bluetooth", "hotspot"):
            await ws.send(json.dumps({"t": "radio", "d": dev}))
            rr = await recv_until(ws, "radio_result")
            if not (rr["t"] == "radio_result" and rr["d"] == dev and "msg" in rr
                    and isinstance(rr["ok"], bool)):
                check(f"radio_result untuk {dev}", False)
                break
        else:
            check("radio_result selalu dibalas", True)

        await ws.send(json.dumps({"t": "bright", "d": 10}))
        br = await recv_until(ws, "bright_result")
        check("bright_result dibalas", br["t"] == "bright_result" and "msg" in br)

        # Aksi daya dikirim lewat wire untuk menguji dispatch & format
        # balasan. safe_harness memastikan SEMUA aksi disimulasikan, bukan
        # dieksekusi - dulu lock/screenoff mengunci layar sungguhan.
        for act in ("lock", "screenoff", "shutdown", "restart", "sleep",
                    "hibernate", "logoff"):
            await ws.send(json.dumps({"t": "power", "a": act}))
            pr = await recv_until(ws, "power_result")
            if not (pr["t"] == "power_result" and pr["a"] == act
                    and isinstance(pr["ok"], bool)):
                check(f"power_result untuk {act}", False)
                break
        else:
            check("power_result selalu dibalas", True)

    # ---- v3.7: clipboard & MPRIS lewat wire (safe_harness men-stub) ----
    core.reset_failed_attempts("127.0.0.1")
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "auth", "pin": core.PIN,
                                  "ver": "3.7"}))
        a = json.loads(await ws.recv())
        check("auth v3.7 diterima", a["t"] == "auth_ok")
        caps = a.get("caps", {})
        check("caps v3.7 membawa clipboard & nowplaying",
              isinstance(caps.get("clipboard"), bool)
              and isinstance(caps.get("nowplaying"), bool))

        # clipsync on (default juga on) -> clipsync_result ok.
        await ws.send(json.dumps({"t": "clipsync", "on": True}))
        r = await recv_until(ws, "clipsync_result")
        check("clipsync on -> clipsync_result ok", r.get("ok") is True)

        # clipget -> clip (ok bool, s str, msg str).
        await ws.send(json.dumps({"t": "clipget"}))
        r = await recv_until(ws, "clip")
        check("clipget -> clip dibalas",
              isinstance(r.get("ok"), bool) and "s" in r and "msg" in r)

        # clipset -> clipset_result.
        await ws.send(json.dumps({"t": "clipset", "s": "halo dari hp"}))
        r = await recv_until(ws, "clipset_result")
        check("clipset -> clipset_result dibalas",
              isinstance(r.get("ok"), bool) and "msg" in r)

        # npget -> np (semua kunci wajib kontrak).
        await ws.send(json.dumps({"t": "npget"}))
        r = await recv_until(ws, "np")
        required = ("ok", "title", "artist", "album", "playing",
                    "length_us", "pos_us", "canseek", "msg")
        check("npget -> np dibalas",
              all(k in r for k in required) and isinstance(r.get("ok"), bool))

        # npseek -> npseek_result.
        await ws.send(json.dumps({"t": "npseek", "pos_us": 123456789}))
        r = await recv_until(ws, "npseek_result")
        check("npseek -> npseek_result dibalas",
              isinstance(r.get("ok"), bool) and "msg" in r)

    # Push "clip" auto TIDAK boleh muncul saat clipsync off, dan clipset
    # wajib ditolak. Poller clipboard tiap ~1 dtk; stub read -> "" sehingga
    # tanpa sync tidak ada push sama sekali.
    core.reset_failed_attempts("127.0.0.1")
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"t": "auth", "pin": core.PIN,
                                  "ver": "3.7"}))
        await asyncio.wait_for(ws.recv(), 5)          # auth_ok
        # Matikan sinkronisasi; recv_until mengabaikan push clip auto yang
        # sempat ter-push sebelum clipsync off diterapkan.
        await ws.send(json.dumps({"t": "clipsync", "on": False}))
        await recv_until(ws, "clipsync_result")
        # Drain sisa antrian (scrollinfo, clip auto yang telanjur masuk).
        try:
            while True:
                await asyncio.wait_for(ws.recv(), 0.4)
        except asyncio.TimeoutError:
            pass
        # Sekarang tunggu ~2.5 dtk: dengan clipsync off, TIDAK BOLEH ada
        # push clip auto dari poller.
        try:
            raw = await asyncio.wait_for(ws.recv(), 2.5)
            msg = json.loads(raw.decode("utf-8", "replace")
                             if isinstance(raw, (bytes, bytearray)) else raw)
            check("TIDAK ada push clip auto saat clipsync off",
                  not (msg.get("t") == "clip" and msg.get("auto")))
        except asyncio.TimeoutError:
            check("TIDAK ada push clip auto saat clipsync off", True)
        # clipset saat off wajib DITOLAK.
        await ws.send(json.dumps({"t": "clipset", "s": "ditolak"}))
        r = await recv_until(ws, "clipset_result")
        check("clipset ditolak saat clipsync off", r.get("ok") is False)

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

    # Guard harness juga berlaku untuk jalur WebSocket: seluruh pemrosesan
    # pesan radio/power/bright di atas dilakukan lewat stub, bukan nyata.
    check("safe_harness: WebSocket tidak mengeksekusi aksi nyata",
          safe_harness.REAL_CALLS == [])
    sim_ws_power = [c for c in safe_harness.SIMULATED
                    if c[0] == "system_ctl" and c[1] == "power_action"]
    check("safe_harness: power lewat WebSocket disimulasikan",
          len(sim_ws_power) >= 7)

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
    # WAJIB paling awal: tanpa ini semua pemanggilan power/radio/bright di
    # bawah adalah aksi sistem NYATA (pernah mengunci layar & memutus WiFi).
    # Harness mem-patch system_ctl/input_core menjadi stub yang aman.
    safe_harness.activate()
    print("=== 1. kripto ===");            test_crypto()
    print("=== 2. binary protocol ===");   test_binary()
    print("=== 3. lapisan linux ===");     test_linux_layer()
    print("=== 4. websocket e2e ===");     asyncio.run(ws_tests())
    print()
    if SKIPPED:
        print(f"{len(SKIPPED)} SKIP (blocker sementara):")
        for s in SKIPPED:
            print(f"  - {s}")
        print()
    if FAILED:
        print(f"{len(FAILED)} UJI GAGAL:")
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    try:
        safe_harness.assert_no_real_calls()
    except AssertionError as e:
        print(f"GAGAL - {e}")
        sys.exit(1)
    print("SEMUA UJI LULUS")


if __name__ == "__main__":
    main()
