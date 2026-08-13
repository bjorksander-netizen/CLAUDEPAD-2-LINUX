#!/usr/bin/env python3
"""
CLAUDEPAD Server untuk Linux (Ubuntu 20.04+ dan turunannya)
-----------------------------------------------------------
HP Android menjadi trackpad, keyboard, media control & volume untuk PC.
Koneksi: WiFi/Hotspot atau USB (adb reverse).

Protokol WebSocket-nya identik byte-per-byte dengan server Windows, jadi
APK yang sama bisa dipakai tanpa perubahan. Yang berganti hanya lapisan
sistem: injeksi input, volume, daya, radio, dan firewall.

Jalankan:  python3 pc_server.py            (GUI Tk)
           python3 pc_server.py --nogui    (konsol / systemd)
Butuh:     pip install -r requirements.txt
"""

import argparse
import asyncio
import base64
import http
import json
import os
import queue
import secrets
import socket
import sys
import threading

from paths import data_path

try:
    import websockets
except ImportError:
    raise SystemExit("Modul 'websockets' belum terpasang. "
                     "Jalankan: pip install -r requirements.txt")

import binary_protocol
import clipboard
import crypto_box
import input_core as core
import system_ctl
from autostart import is_autostart_enabled, set_autostart
from input_core import (CLIENTS, DISCOVERY_PORT, HOSTNAME, LOGQ, PLATFORM,
                        WS_PORT, capabilities, check_rate_limit,
                        desktop_name, discovery_loop, enable_usb_mode,
                        firewall_name, firewall_status, fix_firewall,
                        get_active_scroll_info, handle_message, init_backend,
                        local_ips, local_ips_detailed, log,
                        record_failed_attempt, reset_failed_attempts,
                        session_type, volume_get)

APP_VERSION = "3.9"

# Versi APK yang diterima. v3.9 menambah gesture 4 jari, clipboard gambar
# dua arah, perbaikan power control (caps), dan media_result. Protokol boleh
# berubah (tidak ada kewajiban kompatibilitas dengan versi Windows), jadi
# versi lain ditolak.
COMPATIBLE_APP_VERSIONS = {"3.9"}

# RSA-2048 keypair: digenerate sekali saat server start.
_RSA_KEYPAIR = None


def _ensure_rsa_keypair():
    global _RSA_KEYPAIR
    if _RSA_KEYPAIR is None:
        _RSA_KEYPAIR = crypto_box.generate_rsa_keypair()
    return _RSA_KEYPAIR


# ---------------------------------------------------------------- Token -----
# Token perangkat tepercaya: sekali dipasangkan, HP tidak perlu mengetik PIN
# lagi. Disimpan di keyring (KWallet/GNOME Keyring) bila ada; kalau tidak,
# di ~/.config/claudepad/paired.txt dengan mode 0600.
try:
    import keyring as _keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False

_KEYRING_SERVICE = "claudepad"
_KEYRING_USER = "paired_tokens"
_PAIR_FILE = data_path("paired.txt")


def load_tokens():
    if _KEYRING_AVAILABLE:
        try:
            raw = _keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
            if raw:
                return {t for t in raw.splitlines() if t.strip()}
        except Exception:                                      # noqa: BLE001
            pass
    try:
        with open(_PAIR_FILE, "r", encoding="utf-8") as f:
            return {l.strip() for l in f if l.strip()}
    except OSError:
        return set()


def save_token(token):
    tokens = load_tokens()
    tokens.add(token)
    if _KEYRING_AVAILABLE:
        try:
            _keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER,
                                  "\n".join(sorted(tokens)))
            try:
                if os.path.exists(_PAIR_FILE):
                    os.remove(_PAIR_FILE)
            except OSError:
                pass
            return True
        except Exception as e:                                 # noqa: BLE001
            log(f"[!] keyring gagal, fallback ke berkas: {e}")
    try:
        with open(_PAIR_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(tokens)))
        os.chmod(_PAIR_FILE, 0o600)
        return True
    except OSError as e:
        log(f"[!] Gagal menyimpan token pairing: {e}")
        return False


def forget_tokens():
    if _KEYRING_AVAILABLE:
        try:
            _keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USER)
        except Exception:                                      # noqa: BLE001
            pass
    try:
        if os.path.exists(_PAIR_FILE):
            os.remove(_PAIR_FILE)
    except OSError:
        return False
    log("[i] Semua perangkat tepercaya dilupakan")
    return True


ACTIVE_SOCKETS = set()
MAIN_LOOP = None


def disconnect_clients():
    loop = MAIN_LOOP
    if loop is None:
        return
    for ws in list(ACTIVE_SOCKETS):
        try:
            asyncio.run_coroutine_threadsafe(
                ws.close(code=1000, reason="disconnect"), loop)
        except Exception:                                      # noqa: BLE001
            pass
    log("[i] Semua klien diputus dari server")


# ------------------------------------------------------- Scroll info --------
async def scrollinfo_poller(reply, stop_event):
    """
    Di Windows ini mengirim posisi scrollbar window aktif. Linux tidak punya
    padanannya, jadi indikator dimatikan sekali di awal (pos -1) alih-alih
    dipoll terus-menerus tanpa guna.
    """
    try:
        if get_active_scroll_info() is None:
            reply({"t": "scrollinfo", "pos": -1})
    except Exception:                                          # noqa: BLE001
        pass
    await stop_event.wait()


# -------------------------------------------------- Clipboard sync (v3.7) ----
async def clipboard_poller(reply, stop_event, conn):
    """
    Pantau clipboard PC tiap ~1 detik. Bila isinya berubah DAN sinkronisasi
    nyala untuk koneksi ini, dorong ke HP (auto:true).

    Anti-loop: konten yang barusan ditulis server sendiri (dari clipset,
    tercatat di conn["last_server_write"]) tidak dipantulkan kembali.

    Keamanan: poller hanya membaca lewat clipboard.read(). Di mode sandbox
    atau saat harness test aktif, read() sudah disimulasikan sehingga di
    sini TIDAK PERNAH ada subprocess wl-paste/xclip.
    """
    last = None
    while not stop_event.is_set():
        try:
            cur = clipboard.read()
        except Exception:                                      # noqa: BLE001
            cur = None
        if cur is not None and cur != last:
            if conn.get("clipsync", True) and conn.get("last_server_write") != cur:
                reply({"t": "clip", "ok": True, "s": cur, "auto": True})
            conn.pop("last_server_write", None)
            last = cur
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------- Handler ---
async def handle(ws):
    authed = False
    crypto = None
    binary_enabled = False
    peer = ws.remote_address[0] if ws.remote_address else "?"
    transport = "usb" if peer.startswith("127.") else "wifi"
    pending_salt = [None]
    ACTIVE_SOCKETS.add(ws)
    stop_poller = asyncio.Event()
    poller_task = None
    clip_task = None
    # State per-koneksi (bukan global): sinkronisasi clipboard default nyala,
    # dan catatan anti-loop untuk konten yang server tulis dari clipset.
    conn = {"clipsync": True}

    # Matikan algoritma Nagle. Tanpa ini paket gerakan kursor yang mungil
    # ditahan menunggu paket lain, dan kursor terasa tersendat.
    try:
        sock = None
        for attr in ("transport", "socket"):
            obj = getattr(ws, attr, None)
            if obj is not None:
                sock = obj.get_extra_info("socket") if hasattr(obj, "get_extra_info") else obj
                if sock is not None:
                    break
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception:                                          # noqa: BLE001
        pass

    log(f"[+] Koneksi dari {peer} ({transport})")

    async def _send(payload):
        # Klien bisa menutup soket tepat saat balasan sedang dijadwalkan.
        # Tanpa penadah ini asyncio mencetak "Task exception was never
        # retrieved" setiap kali HP memutus koneksi - berisik dan menutupi
        # galat yang benar-benar penting di kotak log.
        try:
            await ws.send(payload)
        except (websockets.ConnectionClosed, RuntimeError):
            pass

    def reply(obj):
        data = json.dumps(obj)
        payload = crypto.seal(data.encode("utf-8")) if crypto is not None else data
        asyncio.create_task(_send(payload))

    try:
        async for raw in ws:
            if crypto is not None and isinstance(raw, (bytes, bytearray)):
                try:
                    raw = crypto.open(bytes(raw))
                except Exception as e:                         # noqa: BLE001
                    log(f"[!] {peer} paket ditolak: {e}")
                    continue
                if binary_enabled:
                    try:
                        m = binary_protocol.decode(raw)
                    except Exception:                          # noqa: BLE001
                        m = None
                    if m is not None:
                        handle_message(m, reply, conn)
                        continue
                try:
                    raw = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
            try:
                m = json.loads(raw)
            except (ValueError, TypeError):
                continue

            # Handshake enkripsi. Kunci sesi TIDAK pernah dikirim: kedua
            # pihak menurunkannya sendiri dari PIN/token memakai garam ini.
            if not authed and m.get("t") == "hello":
                pending_salt[0] = crypto_box.new_salt()
                pub_pem, _ = _ensure_rsa_keypair()
                await ws.send(json.dumps({
                    "t": "hello_ok",
                    "salt": pending_salt[0].hex(),
                    "pubkey": crypto_box.rsa_pubkey_to_b64(pub_pem),
                    "version": APP_VERSION,
                    "platform": PLATFORM,
                }))
                continue

            if not authed:
                if m.get("t") == "auth":
                    if not check_rate_limit(peer):
                        await ws.send(json.dumps({
                            "t": "auth_fail", "reason": "rate_limit"}))
                        log(f"[!] {peer} diblokir: terlalu banyak percobaan gagal")
                        continue

                    app_ver = str(m.get("ver", ""))
                    if app_ver not in COMPATIBLE_APP_VERSIONS:
                        await ws.send(json.dumps({
                            "t": "auth_fail", "reason": "version",
                            "server": APP_VERSION, "app": app_ver}))
                        log(f"[!] {peer} ditolak: versi APK '{app_ver}' "
                            f"tidak kompatibel (server {APP_VERSION})")
                        continue

                pin_plain = str(m.get("pin", ""))
                token_plain = str(m.get("token", ""))

                # PIN/token boleh dikirim terenkripsi RSA (v3.2+) atau polos.
                # Yang terenkripsi menimpa yang polos bila keduanya ada.
                if m.get("t") == "auth":
                    _, priv_key = _ensure_rsa_keypair()
                    decrypt_failed = False

                    def _rsa_open(blob):
                        return crypto_box.rsa_decrypt(
                            priv_key, base64.b64decode(blob)).decode("utf-8")

                    if m.get("pin_enc"):
                        try:
                            pin_plain = _rsa_open(m["pin_enc"])
                        except Exception as e:                 # noqa: BLE001
                            log(f"[!] {peer} gagal dekripsi pin_enc: {e}")
                            decrypt_failed = True
                    if not decrypt_failed and m.get("token_enc"):
                        try:
                            token_plain = _rsa_open(m["token_enc"])
                        except Exception as e:                 # noqa: BLE001
                            log(f"[!] {peer} gagal dekripsi token_enc: {e}")
                            decrypt_failed = True
                    if decrypt_failed:
                        record_failed_attempt(peer)
                        await ws.send(json.dumps(
                            {"t": "auth_fail", "reason": "pin"}))
                        continue

                token = token_plain
                by_token = bool(token) and token in load_tokens()
                by_pin = pin_plain == core.PIN

                if m.get("t") == "auth" and (by_pin or by_token):
                    authed = True
                    binary_enabled = m.get("binary", False)
                    CLIENTS[peer] = transport
                    reset_failed_attempts(peer)

                    new_token = ""
                    if by_pin and not by_token:
                        new_token = secrets.token_hex(16)
                        save_token(new_token)

                    if pending_salt[0] is not None:
                        secret = token if by_token else core.PIN
                        crypto = crypto_box.Session.derive(secret, pending_salt[0])
                        log(f"[+] {peer} lalu lintas terenkripsi")

                    stop_poller.clear()
                    poller_task = asyncio.create_task(
                        scrollinfo_poller(reply, stop_poller))
                    clip_task = asyncio.create_task(
                        clipboard_poller(reply, stop_poller, conn))

                    await ws.send(json.dumps({
                        "t": "auth_ok",
                        "host": HOSTNAME,
                        "transport": transport,
                        "version": APP_VERSION,
                        "vol": volume_get(),
                        "mac": system_ctl.mac_address(),
                        "token": new_token,
                        "encrypted": pending_salt[0] is not None,
                        "binary": True,
                        # Bidang baru v3.6. APK v3.5 mengabaikannya begitu
                        # saja karena membaca field dengan optString/optBoolean.
                        "platform": PLATFORM,
                        "desktop": desktop_name(),
                        "session": session_type(),
                        "caps": capabilities(),
                    }))
                    log(f"[+] {peer} terautentikasi"
                        + (" (token tersimpan)" if new_token else
                           " (token tepercaya)" if by_token else ""))
                elif m.get("t") == "auth":
                    record_failed_attempt(peer)
                    await ws.send(json.dumps({"t": "auth_fail", "reason": "pin"}))
                    log(f"[!] {peer} PIN salah")
                continue
            handle_message(m, reply, conn)
    except websockets.ConnectionClosed:
        pass
    except Exception as e:                                     # noqa: BLE001
        log(f"[!] Error dari {peer}: {e}")
    finally:
        stop_poller.set()
        if poller_task is not None:
            poller_task.cancel()
        if clip_task is not None:
            clip_task.cancel()
        ACTIVE_SOCKETS.discard(ws)
        CLIENTS.pop(peer, None)
        log(f"[-] {peer} terputus")


# ------------------------------------------------------------ Health --------
def _health_body():
    return (
        "CLAUDEPAD OK\n"
        f"server  : v{APP_VERSION}\n"
        f"platform: {PLATFORM} ({desktop_name()}, {session_type()})\n"
        f"input   : {core.BACKEND.name}\n"
        f"host    : {HOSTNAME}\n"
        f"port    : {WS_PORT}\n\n"
        "Halaman ini tampil berarti HP SUDAH bisa menjangkau PC.\n"
        "Kalau aplikasi tetap gagal, masalahnya bukan di firewall.\n"
    )


def _ws_api_generation():
    """
    2 = API baru (websockets >= 14, process_request(connection, request))
    1 = API lama (websockets < 14, process_request(path, headers))
    """
    try:
        major = int(str(websockets.__version__).split(".")[0])
    except Exception:                                          # noqa: BLE001
        major = 0
    return 2 if major >= 14 else 1


async def _health_legacy(path, request_headers):
    if path.startswith("/ws"):
        return None
    return (http.HTTPStatus.OK,
            [("Content-Type", "text/plain; charset=utf-8"),
             ("Access-Control-Allow-Origin", "*")],
            _health_body().encode())


def _health_modern(connection, request):
    try:
        path = getattr(request, "path", "/") or "/"
        if path.startswith("/ws"):
            return None
        return connection.respond(http.HTTPStatus.OK, _health_body())
    except Exception as e:                                     # noqa: BLE001
        log(f"[!] health endpoint error: {e}")
        return None


def health_request():
    return _health_modern if _ws_api_generation() == 2 else _health_legacy


SERVER_READY = threading.Event()
SERVER_ERROR = [None]


def start_server_thread():
    def run():
        async def main():
            global MAIN_LOOP
            MAIN_LOOP = asyncio.get_running_loop()
            async with websockets.serve(handle, "0.0.0.0", WS_PORT,
                                        ping_interval=20, ping_timeout=20,
                                        process_request=health_request()):
                SERVER_READY.set()
                await asyncio.Future()
        try:
            asyncio.run(main())
        except OSError as e:
            SERVER_ERROR[0] = f"Port {WS_PORT} sudah dipakai program lain ({e})"
            log(f"[!] {SERVER_ERROR[0]}")
        except Exception as e:                                 # noqa: BLE001
            SERVER_ERROR[0] = f"Server gagal jalan: {type(e).__name__}: {e}"
            log(f"[!] {SERVER_ERROR[0]}")
    threading.Thread(target=discovery_loop, daemon=True).start()
    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- GUI -------
BG = "#0e0e14"
CARD = "#191922"
CARD2 = "#20202c"
FG = "#f2f2f7"
MUTED = "#8e8ea0"
ACCENT = "#7c6cff"
GREEN = "#4ade80"
AMBER = "#fbbf24"
RED = "#ff6b6b"
MONO = "JetBrains Mono"


def _mono(size, weight="normal"):
    """JetBrains Mono kalau terpasang, kalau tidak monospace bawaan."""
    import tkinter.font as tkfont
    fams = set(tkfont.families())
    for fam in (MONO, "DejaVu Sans Mono", "Liberation Mono", "Ubuntu Mono",
                "Noto Sans Mono", "monospace"):
        if fam in fams:
            return (fam, size, weight)
    return ("TkFixedFont", size, weight)


def run_gui(minimized=False):
    import tkinter as tk

    root = tk.Tk()
    root.title("CLAUDEPAD" + (" [SANDBOX]" if core.is_sandbox() else ""))
    root.geometry("560x660")
    root.minsize(480, 560)
    root.configure(bg=BG)

    state = {"tray": None, "hidden": False}

    header = tk.Frame(root, bg=BG)
    header.pack(fill="x", padx=22, pady=(20, 6))
    tk.Label(header, text="CLAUDEPAD", font=_mono(20, "bold"),
             bg=BG, fg=FG).pack(anchor="w")
    tk.Label(header,
             text=f"linux server  v{APP_VERSION}  ·  {desktop_name()} "
                  f"({session_type()})",
             font=_mono(9), bg=BG, fg=MUTED).pack(anchor="w")

    def card(parent, pady=(0, 10)):
        outer = tk.Frame(parent, bg=CARD, highlightthickness=1,
                         highlightbackground=CARD2)
        outer.pack(fill="x", padx=22, pady=pady)
        return outer

    c1 = card(root, (10, 10))
    inner = tk.Frame(c1, bg=CARD)
    inner.pack(fill="x", padx=18, pady=16)

    left = tk.Frame(inner, bg=CARD)
    left.pack(side="left", anchor="n")
    tk.Label(left, text="PIN", font=_mono(9), bg=CARD, fg=MUTED).pack(anchor="w")
    pin_lbl = tk.Label(left, text=core.PIN, font=_mono(32, "bold"),
                       bg=CARD, fg=ACCENT)
    pin_lbl.pack(anchor="w")

    right = tk.Frame(inner, bg=CARD)
    right.pack(side="right", anchor="n")
    tk.Label(right, text="ALAMAT UNTUK HP", font=_mono(9),
             bg=CARD, fg=MUTED).pack(anchor="e")

    detailed = local_ips_detailed()
    ips = local_ips()
    if not detailed:
        tk.Label(right, text="tidak ada jaringan", font=_mono(12),
                 bg=CARD, fg=FG).pack(anchor="e")
    else:
        for ip, name, virtual in detailed[:5]:
            row = tk.Frame(right, bg=CARD)
            row.pack(anchor="e")
            tk.Label(row, text=(f"  {name} (virtual, jangan dipakai)"
                                if virtual else f"  {name}"),
                     font=_mono(8), bg=CARD, fg="#5a5a70").pack(side="left")
            tk.Label(row, text=ip, font=_mono(13 if not virtual else 10),
                     bg=CARD, fg=(FG if not virtual else "#5a5a70")).pack(side="left")
        tk.Label(right, text=f"port {WS_PORT}", font=_mono(9),
                 bg=CARD, fg=MUTED).pack(anchor="e", pady=(4, 0))

    c2 = card(root)
    status_lbl = tk.Label(c2, text="  Menunggu koneksi", font=_mono(11),
                          bg=CARD, fg=AMBER, anchor="w")
    status_lbl.pack(fill="x", padx=18, pady=(14, 4))

    input_lbl = tk.Label(c2, text="  Memeriksa backend input...", font=_mono(10),
                         bg=CARD, fg=MUTED, anchor="w")
    input_lbl.pack(fill="x", padx=18, pady=(0, 4))

    fw_lbl = tk.Label(c2, text="  Memeriksa firewall...", font=_mono(10),
                      bg=CARD, fg=MUTED, anchor="w")
    fw_lbl.pack(fill="x", padx=18, pady=(0, 14))

    def render_input():
        name = core.BACKEND.name
        if name == "uinput":
            input_lbl.config(text="  Input: uinput (Wayland & X11)", fg=GREEN)
        elif name in ("xtest", "xdotool"):
            input_lbl.config(text=f"  Input: {name} (hanya X11)", fg=AMBER)
        else:
            input_lbl.config(text="  Input: TIDAK AKTIF - jalankan install.sh",
                             fg=RED)

    def render_firewall():
        if firewall_status():
            fw_lbl.config(text=f"  Firewall ({firewall_name()}): port terbuka",
                          fg=GREEN)
        else:
            fw_lbl.config(
                text=f"  Firewall ({firewall_name()}): port TERTUTUP - "
                     f"klik Perbaiki Firewall", fg=AMBER)

    def do_fix_firewall():
        fw_lbl.config(text="  Meminta izin (pkexec)...", fg=MUTED)

        def work():
            fix_firewall()
            root.after(1200, render_firewall)
        threading.Thread(target=work, daemon=True).start()

    btnbar = tk.Frame(root, bg=BG)
    btnbar.pack(fill="x", padx=22, pady=(2, 10))

    def flat_btn(parent, text, cmd, accent=False):
        b = tk.Label(parent, text=text, font=_mono(10),
                     bg=ACCENT if accent else CARD2,
                     fg="#ffffff" if accent else FG, padx=12, pady=9,
                     cursor="hand2")
        b.pack(side="left", padx=(0, 8))
        b.bind("<Button-1>", lambda e: cmd())
        hover = "#8f80ff" if accent else "#2b2b3a"
        base = ACCENT if accent else CARD2
        b.bind("<Enter>", lambda e: b.config(bg=hover))
        b.bind("<Leave>", lambda e: b.config(bg=base))
        return b

    def copy_ip():
        if ips:
            root.clipboard_clear()
            root.clipboard_append(ips[0])
            log(f"[i] IP {ips[0]} disalin")

    def regen_pin():
        pin_lbl.config(text=core.new_pin())
        log("[i] PIN baru dibuat")

    flat_btn(btnbar, "Salin IP", copy_ip)
    flat_btn(btnbar, "PIN Baru", regen_pin)
    flat_btn(btnbar, "Mode USB",
             lambda: threading.Thread(target=enable_usb_mode, daemon=True).start(),
             accent=True)
    flat_btn(btnbar, "Putuskan", disconnect_clients)
    flat_btn(btnbar, "Perbaiki Firewall", do_fix_firewall)
    flat_btn(btnbar, "Setup Wizard",
             lambda: threading.Thread(target=_launch_wizard, daemon=True).start())

    tk.Label(root, text="LOG", font=_mono(9), bg=BG, fg=MUTED,
             anchor="w").pack(fill="x", padx=22, pady=(6, 4))
    logframe = tk.Frame(root, bg=CARD)
    logframe.pack(fill="both", expand=True, padx=22, pady=(0, 12))
    scroll = tk.Scrollbar(logframe, bg=CARD, troughcolor=CARD,
                          activebackground=ACCENT, bd=0, highlightthickness=0)
    scroll.pack(side="right", fill="y")
    logbox = tk.Text(logframe, bg=CARD, fg="#c9c9d4", insertbackground=FG,
                     relief="flat", font=_mono(9), state="disabled",
                     yscrollcommand=scroll.set, padx=14, pady=12, wrap="word")
    logbox.pack(fill="both", expand=True)
    scroll.config(command=logbox.yview)

    def make_tray_icon():
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            log("[!] pystray/pillow belum ada; tray dinonaktifkan.")
            return None
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((6, 6, 58, 58), radius=14, fill=(124, 108, 255, 255))
        d.rounded_rectangle((20, 18, 44, 46), radius=6, fill=(255, 255, 255, 255))
        return pystray.Icon(
            "claudepad", img, "CLAUDEPAD",
            menu=pystray.Menu(
                pystray.MenuItem("Tampilkan", lambda: root.after(0, show_window),
                                 default=True),
                pystray.MenuItem("Keluar", lambda: root.after(0, quit_app)),
            ))

    def hide_to_tray():
        icon = state["tray"]
        if icon is None:
            icon = make_tray_icon()
            if icon is None:
                root.iconify()
                return
            state["tray"] = icon
            threading.Thread(target=icon.run, daemon=True).start()
        root.withdraw()
        state["hidden"] = True
        log("[i] Diminimalkan ke area notifikasi")

    def show_window():
        root.deiconify()
        root.lift()
        root.focus_force()
        state["hidden"] = False

    def quit_app():
        if state["tray"]:
            try:
                state["tray"].stop()
            except Exception:                                  # noqa: BLE001
                pass
        try:
            core.BACKEND.close()
        except Exception:                                      # noqa: BLE001
            pass
        try:
            root.destroy()
        except Exception:                                       # noqa: BLE001
            pass
        # Pastikan seluruh proses server (termasuk thread asyncio) benar-benar
        # berhenti, bukan cuma menyembunyikan window.
        os._exit(0)

    flat_btn(btnbar, "Ke Tray", hide_to_tray)
    # Tombol X tutup window DAN mematikan proses server (bukan ke tray).
    root.protocol("WM_DELETE_WINDOW", quit_app)

    frame_auto = tk.Frame(root, bg=BG)
    frame_auto.pack(fill="x", padx=22, pady=(2, 6))
    auto_var = tk.BooleanVar(value=is_autostart_enabled())

    def toggle_autostart():
        enabled = auto_var.get()
        if not set_autostart(enabled):
            auto_var.set(not enabled)
            log("[!] Gagal mengubah pengaturan startup")

    tk.Checkbutton(frame_auto, variable=auto_var, command=toggle_autostart,
                   text="Jalankan server otomatis saat login",
                   bg=BG, fg=MUTED, selectcolor=CARD, activebackground=BG,
                   activeforeground=FG, font=_mono(9)).pack(anchor="w", padx=10)

    def poll():
        try:
            while True:
                msg = LOGQ.get_nowait()
                logbox.config(state="normal")
                logbox.insert("end", msg + "\n")
                logbox.see("end")
                logbox.config(state="disabled")
        except queue.Empty:
            pass
        if CLIENTS:
            names = ", ".join(f"{ip} ({t})" for ip, t in sorted(CLIENTS.items()))
            status_lbl.config(text=f"  Terhubung: {names}", fg=GREEN)
        else:
            status_lbl.config(text="  Menunggu koneksi", fg=AMBER)
        root.after(300, poll)

    init_backend()
    core.write_default_gestures()
    start_server_thread()

    def self_check():
        """Pastikan server benar-benar menerima koneksi, bukan cuma terlihat hidup."""
        ok = SERVER_READY.wait(timeout=6)
        if not ok or SERVER_ERROR[0]:
            msg = SERVER_ERROR[0] or "Server tidak siap dalam 6 detik"
            root.after(0, lambda: status_lbl.config(text=f"  GAGAL: {msg}", fg=RED))
            log(f"[!] {msg}")
            return
        try:
            import urllib.request
            body = urllib.request.urlopen(
                f"http://127.0.0.1:{WS_PORT}/", timeout=5).read().decode()
            if "CLAUDEPAD OK" in body:
                log(f"[i] Uji mandiri OK - websockets {websockets.__version__}")
            else:
                log("[!] Uji mandiri: balasan tak terduga")
        except Exception as e:                                 # noqa: BLE001
            SERVER_ERROR[0] = f"Uji mandiri gagal: {e}"
            log(f"[!] {SERVER_ERROR[0]}")
            root.after(0, lambda: status_lbl.config(
                text="  GAGAL: server tidak merespons - lihat log", fg=RED))

    threading.Thread(target=self_check, daemon=True).start()
    log(f"[i] Server aktif di port {WS_PORT} sebagai '{HOSTNAME}'")
    if ips:
        log(f"[i] Tes dari HP: buka http://{ips[0]}:{WS_PORT} di browser")
    render_input()
    render_firewall()
    poll()
    if minimized:
        root.after(800, hide_to_tray)
    root.mainloop()


def _launch_wizard():
    """Buka wizard setup (GUI bila tkinter ada, selain itu CLI)."""
    try:
        import wizard
        wizard.main()
    except Exception as e:                                 # noqa: BLE001
        log(f"[!] Wizard gagal: {e}")


def run_console():
    init_backend()
    core.write_default_gestures()
    start_server_thread()
    mode = "  [SANDBOX - aksi daya/radio/kecerahan disimulasikan]" \
        if core.is_sandbox() else ""
    print("=" * 52)
    print(f"  CLAUDEPAD Server v{APP_VERSION} (linux, konsol){mode}")
    print(f"  Desktop : {desktop_name()} / {session_type()}")
    print(f"  Input   : {core.BACKEND.name}")
    print(f"  PIN     : {core.PIN}")
    print(f"  Port    : {WS_PORT}")
    for ip in local_ips():
        print(f"  IP      : {ip}")
    print("=" * 52)

    def printer():
        while True:
            print(LOGQ.get(), flush=True)
    threading.Thread(target=printer, daemon=True).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("Server berhenti.")
        core.BACKEND.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CLAUDEPAD Server (Linux)")
    parser.add_argument("--nogui", action="store_true", help="Jalankan tanpa GUI")
    parser.add_argument("--minimized", action="store_true",
                        help="Mulai terminimalkan ke area notifikasi")
    parser.add_argument("--wizard", action="store_true",
                        help="Buka wizard install/uninstall lalu keluar "
                             "(tanpa menjalankan server)")
    parser.add_argument("--input-backend", choices=["uinput", "xtest", "xdotool"],
                        help="Paksa backend input tertentu")
    parser.add_argument("--sandbox", action="store_true",
                        help="Mode sandbox: simulasi aksi daya/radio/kecerahan "
                             "(tidak menyentuh sistem; aman untuk uji jalur penuh)")
    args, _unknown = parser.parse_known_args()

    # Mode sandbox: flag baris perintah ATAU env CLAUDEPAD_SANDBOX=1.
    if args.sandbox or os.environ.get("CLAUDEPAD_SANDBOX") == "1":
        core.set_sandbox(True)

    # Mode wizard: buka wizard lalu keluar, tanpa menjalankan server.
    if args.wizard:
        _launch_wizard()
        sys.exit(0)

    if args.input_backend:
        _forced = args.input_backend
        _orig_init = init_backend
        init_backend = lambda prefer=None: _orig_init(_forced)   # noqa: E731

    if args.nogui or not (os.environ.get("DISPLAY")
                          or os.environ.get("WAYLAND_DISPLAY")):
        run_console()
    else:
        try:
            run_gui(minimized=args.minimized)
        except Exception as e:                                 # noqa: BLE001
            print(f"GUI gagal ({e}), fallback ke konsol.")
            run_console()
