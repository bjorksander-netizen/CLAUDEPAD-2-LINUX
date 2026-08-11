#!/usr/bin/env python3
"""
Uji backend input nyata di X11 (Xvfb).

Uji protokol saja tidak cukup: yang paling mudah salah justru lapisan
paling bawah - arah scroll terbalik, modifier tidak terlepas, karakter
salah petak. Di sini server benar-benar menggerakkan pointer dan menekan
tombol di server X sungguhan, lalu hasilnya dibaca kembali.

Butuh: Xvfb + python-xlib. Dilewati (bukan gagal) kalau keduanya tak ada.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DISPLAY = ":99"
FAILED = []


def check(label, cond):
    print(("OK  - " if cond else "GAGAL - ") + label)
    if not cond:
        FAILED.append(label)


def main():
    if not any(os.access(os.path.join(p, "Xvfb"), os.X_OK)
               for p in os.environ.get("PATH", "").split(":") if p):
        print("Xvfb tidak ada - uji input X11 dilewati")
        return 0
    try:
        import Xlib                                            # noqa: F401
    except ImportError:
        print("python-xlib tidak ada - uji input X11 dilewati")
        return 0

    xvfb = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        os.environ["DISPLAY"] = DISPLAY
        os.environ["XDG_SESSION_TYPE"] = "x11"
        os.environ.pop("WAYLAND_DISPLAY", None)

        import input_core as core
        backend = core.init_backend("xtest")
        check("backend xtest terpilih di X11", backend == "xtest")
        if backend != "xtest":
            return 1

        from Xlib import X, XK, display
        dpy = display.Display(DISPLAY)
        root = dpy.screen().root

        # ---- pointer ----
        root.warp_pointer(400, 300)
        dpy.sync()
        core.mouse_move(50, 30)
        dpy.sync()
        time.sleep(0.2)
        p = root.query_pointer()
        check(f"pointer bergerak +50/+30 (jadi {p.root_x},{p.root_y})",
              (p.root_x, p.root_y) == (450, 330))

        core.mouse_move(-100, -80)
        dpy.sync()
        time.sleep(0.2)
        p = root.query_pointer()
        check("pointer bergerak mundur", (p.root_x, p.root_y) == (350, 250))

        # ---- jendela penerima event ----
        win = root.create_window(0, 0, 1280, 800, 0, dpy.screen().root_depth,
                                 X.InputOutput, X.CopyFromParent,
                                 background_pixel=dpy.screen().black_pixel,
                                 event_mask=(X.KeyPressMask | X.KeyReleaseMask
                                             | X.ButtonPressMask
                                             | X.ButtonReleaseMask))
        win.map()
        dpy.sync()
        time.sleep(0.4)
        win.set_input_focus(X.RevertToParent, X.CurrentTime)
        dpy.sync()
        time.sleep(0.3)

        def drain():
            evs = []
            for _ in range(dpy.pending_events()):
                evs.append(dpy.next_event())
            return evs

        drain()

        def keysym_of(ev):
            return dpy.keycode_to_keysym(ev.detail, 0)

        # ---- tombol tunggal ----
        core.press_key("a")
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.KeyPress]
        check("tombol 'a' sampai ke jendela",
              bool(evs) and XK.keysym_to_string(keysym_of(evs[0])) == "a")

        core.press_key("enter")
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.KeyPress]
        check("tombol 'enter' dipetakan ke Return",
              bool(evs) and keysym_of(evs[0]) == XK.string_to_keysym("Return"))

        # ---- kombinasi modifier ----
        core.press_key("c", ["ctrl"])
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.KeyPress]
        target = [e for e in evs
                  if XK.keysym_to_string(keysym_of(e)) == "c"]
        check("ctrl+c terkirim sebagai 'c'", bool(target))
        check("modifier ctrl aktif saat 'c' ditekan",
              bool(target) and bool(target[0].state & X.ControlMask))

        # Modifier WAJIB dilepas lagi; kalau tidak, seluruh ketikan
        # berikutnya jadi shortcut dan aplikasi terasa "rusak".
        core.press_key("a")
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.KeyPress]
        after = [e for e in evs if XK.keysym_to_string(keysym_of(e)) == "a"]
        check("ctrl dilepas setelah kombinasi",
              bool(after) and not (after[0].state & X.ControlMask))

        # ---- gesture memakai peta desktop ----
        core.gesture("appnext")          # default: alt+tab
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.KeyPress]
        tabs = [e for e in evs
                if keysym_of(e) == XK.string_to_keysym("Tab")]
        check("gesture appnext menekan Tab", bool(tabs))
        check("gesture appnext memakai modifier alt",
              bool(tabs) and bool(tabs[0].state & X.Mod1Mask))

        # ---- tombol mouse ----
        core.mouse_click("left")
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.ButtonPress]
        check("klik kiri = tombol X 1", bool(evs) and evs[0].detail == 1)

        core.mouse_click("right")
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.ButtonPress]
        check("klik kanan = tombol X 3", bool(evs) and evs[0].detail == 3)

        core.mouse_click("middle")
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.ButtonPress]
        check("klik tengah = tombol X 2", bool(evs) and evs[0].detail == 2)

        # ---- arah scroll ----
        # 120 = satu notch ke ATAS (konvensi WHEEL_DELTA), di X11 tombol 4.
        core.mouse_scroll(dy=120)
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.ButtonPress]
        check("scroll atas = tombol X 4", bool(evs) and evs[0].detail == 4)

        core.mouse_scroll(dy=-120)
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.ButtonPress]
        check("scroll bawah = tombol X 5", bool(evs) and evs[0].detail == 5)

        core.mouse_scroll(dx=120)
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.ButtonPress]
        check("scroll kanan = tombol X 7", bool(evs) and evs[0].detail == 7)

        core.mouse_scroll(dx=-120)
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.ButtonPress]
        check("scroll kiri = tombol X 6", bool(evs) and evs[0].detail == 6)

        # Scroll setengah notch tidak boleh menghasilkan klik apa pun,
        # tapi sisanya harus disimpan sampai genap satu notch.
        drain()
        core.mouse_scroll(dy=60)
        dpy.sync(); time.sleep(0.25)
        check("scroll 60 (setengah notch) belum memicu klik",
              not [e for e in drain() if e.type == X.ButtonPress])
        core.mouse_scroll(dy=60)
        dpy.sync(); time.sleep(0.25)
        evs = [e for e in drain() if e.type == X.ButtonPress]
        check("dua kali 60 menghasilkan tepat satu notch",
              len(evs) == 1 and evs[0].detail == 4)

        # ---- zoom = ctrl + scroll ----
        drain()
        core.zoom(1)
        dpy.sync(); time.sleep(0.3)
        evs = [e for e in drain() if e.type == X.ButtonPress]
        check("zoom masuk = ctrl + scroll atas",
              bool(evs) and evs[0].detail == 4 and bool(evs[0].state & X.ControlMask))

        # ---- mengetik teks ----
        drain()
        core.type_text("hi")
        dpy.sync(); time.sleep(0.5)
        typed = "".join(
            XK.keysym_to_string(keysym_of(e)) or ""
            for e in drain() if e.type == X.KeyPress)
        check(f"type_text('hi') menghasilkan 'hi' (dapat '{typed}')", typed == "hi")

        # ---- tombol media ----
        # Xvfb polos jarang memetakan XF86Audio* ke keycode nyata, jadi yang
        # diuji adalah resolusi keysym-nya: inilah yang dulu diam-diam gagal
        # karena python-xlib menamainya "XF86_AudioPlay", bukan
        # "XF86AudioPlay" seperti di xdotool.
        XK.load_keysym_group("xf86")
        unresolved = [a for a, name in core.MEDIA_X11.items()
                      if XK.string_to_keysym(name) == 0
                      and XK.string_to_keysym("XF86_" + name[4:]) == 0]
        check(f"keysym semua tombol media terselesaikan ({unresolved})",
              not unresolved)
        for action in core.MEDIA_X11:
            core.media_key(action)          # tidak boleh melempar exception
        dpy.sync()
        check("media_key tidak crash walau tombolnya tak terpetakan", True)

        core.BACKEND.close()
        dpy.close()
    finally:
        xvfb.terminate()
        xvfb.wait(timeout=10)

    print()
    if FAILED:
        print(f"{len(FAILED)} UJI INPUT GAGAL:")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print("SEMUA UJI INPUT X11 LULUS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
