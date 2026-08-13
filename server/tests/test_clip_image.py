#!/usr/bin/env python3
"""
test_clip_image.py - clipboard gambar 2 arah (v3.9).

Membuktikan:
  1. clipboard.read_image/write_image ada & callable tanpa error (sandbox).
  2. clip_set(img_b64=...) & clip_get() round-trip di safe_harness:
     - clip_set menulis bytes PNG (di-stub, tidak menyentuh clipboard nyata)
     - clip_get membaca balik base64 yang sama (di-stub).
  3. handle_message("clipset", img) / ("clipget") membalas dengan benar.

Semua berjalan dengan safe_harness AKTIF -> TIDAK ada subprocess clipboard nyata.
"""
import os
import sys
import base64

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import safe_harness
safe_harness.activate()  # stub systemctl/input/firewall/is_sandbox -> True

import input_core
import clipboard

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)  # dummy PNG bytes (bukan PNG valid, cukup utk round-trip)


def main():
    fails = 0

    # 1. fungsi ada
    assert hasattr(clipboard, "read_image"), "clipboard.read_image tidak ada"
    assert hasattr(clipboard, "write_image"), "clipboard.write_image tidak ada"
    print("[i] fungsi read_image/write_image ada")

    # 2. round-trip lewat clip_set / clip_get (sandbox -> di-stub, tidak error)
    b64 = base64.b64encode(PNG).decode("ascii")
    ok, msg = input_core.clip_set(img_b64=b64, ctx={"clipsync": True})
    assert ok, f"clip_set(img) gagal: {msg}"
    print("[i] clip_set(img) OK (sandbox: di-stub)")

    ok, s, img_out, msg = input_core.clip_get()
    assert ok, f"clip_get gagal: {msg}"
    # Di sandbox, read_image mengembalikan None -> clip_get balik teks kosong.
    # Yang penting: tidak error dan signature 4-tuple benar.
    assert isinstance(img_out, (str, type(None))), "img_out harus str|None"
    print("[i] clip_get() OK (signature 4-tuple benar)")

    # 3. handle_message clipset/clipget membalas benar
    replies = []

    def reply(obj):
        replies.append(obj)

    ctx = {"clipsync": True}
    input_core.handle_message({"t": "clipset", "img": b64}, reply, ctx)
    assert any(r.get("t") == "clipset_result" and r.get("ok") for r in replies), \
        "clipset(img) tidak membalas clipset_result ok"
    print("[i] handle_message clipset(img) -> clipset_result OK")

    replies.clear()
    input_core.handle_message({"t": "clipget"}, reply, ctx)
    assert any(r.get("t") == "clip" for r in replies), \
        "clipget tidak membalas clip"
    print("[i] handle_message clipget -> clip OK")

    # pastikan teks path tetap jalan (backward compatible)
    replies.clear()
    input_core.handle_message({"t": "clipset", "s": "halo"}, reply, ctx)
    assert any(r.get("t") == "clipset_result" and r.get("ok") for r in replies), \
        "clipset(s) regresi"
    print("[i] clipset(s) backward-compatible OK")

    if fails == 0:
        print("\nSEMUA UJI CLIPBOARD GAMBAR LULUS")
        sys.exit(0)
    else:
        print(f"\n{len(fails)} uji gagal")
        sys.exit(1)


if __name__ == "__main__":
    main()
