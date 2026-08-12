#!/usr/bin/env python3
"""
wizard.py - wizard install/uninstall server CLAUDEPAD Linux (GUI Tkinter).

Wizard ini memanggil logika di setup_core (yang idempoten & sandbox-aware).
Setiap langkah dijalankan di thread terpisah agar GUI tidak freeze, lalu
hasilnya dicatat ke kotak log via root.after (sama seperti do_fix_firewall
di pc_server.py). Bila tkinter tidak tersedia, wizard jatuh ke mode CLI
(prompt teks biasa).
"""
import sys
import threading

import setup_core


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
    try:
        import tkinter.font as tkfont
        fams = set(tkfont.families())
    except Exception:  # noqa: BLE001
        fams = set()
    for fam in (MONO, "DejaVu Sans Mono", "Liberation Mono", "Ubuntu Mono",
                "Noto Sans Mono", "monospace"):
        if fam in fams:
            return (fam, size, weight)
    return ("TkFixedFont", size, weight)


# ----------------------------------------------------------- GUI wizard ------
def run_wizard():
    import tkinter as tk

    root = tk.Tk()
    root.title("CLAUDEPAD - Setup Wizard")
    root.geometry("600x680")
    root.minsize(520, 560)
    root.configure(bg=BG)

    # --- header ---
    hdr = tk.Frame(root, bg=BG)
    hdr.pack(fill="x", padx=22, pady=(20, 6))
    tk.Label(hdr, text="Setup Wizard", font=_mono(20, "bold"),
             bg=BG, fg=FG).pack(anchor="w")
    tk.Label(hdr, text="Pasang atau lepas server CLAUDEPAD di PC ini",
             font=_mono(9), bg=BG, fg=MUTED).pack(anchor="w")

    # --- mode pilihan (install / uninstall) ---
    mode_frame = tk.Frame(root, bg=BG)
    mode_frame.pack(fill="x", padx=22, pady=(4, 8))
    mode = tk.StringVar(value="install")

    def _seg(text, val):
        b = tk.Label(mode_frame, text=text, font=_mono(10),
                     bg=ACCENT if val == "install" else CARD2,
                     fg="#ffffff", padx=16, pady=8, cursor="hand2")
        b.pack(side="left", padx=(0, 8))

        def click(e, v=val):
            mode.set(v)
            for child in mode_frame.winfo_children():
                child.config(bg=CARD2)
            b.config(bg=ACCENT)
        b.bind("<Button-1>", click)
        return b

    _seg("Pasang", "install")
    _seg("Lepas", "uninstall")

    # --- checklist install (info) ---
    info = tk.Frame(root, bg=CARD, highlightthickness=1,
                    highlightbackground=CARD2)
    info.pack(fill="x", padx=22, pady=(2, 8))
    info_inner = tk.Frame(info, bg=CARD)
    info_inner.pack(fill="x", padx=18, pady=12)
    tk.Label(info_inner,
             text="Langkah pemasangan:\n"
                  "  1. Virtualenv Python + dependensi\n"
                  "  2. Aturan udev (/dev/uinput) & grup input\n"
                  "  3. Entri menu aplikasi\n"
                  "  4. Autostart saat login\n"
                  "  5. Buka port firewall",
             font=_mono(9), bg=CARD, fg=MUTED, justify="left").pack(anchor="w")
    keep_var = tk.BooleanVar(value=False)
    tk.Checkbutton(info_inner, variable=keep_var,
                   text="Lepas: pertahankan konfigurasi (~/.config/claudepad)",
                   bg=CARD, fg=MUTED, selectcolor=CARD, activebackground=CARD,
                   activeforeground=FG, font=_mono(9)).pack(anchor="w",
                                                             padx=0, pady=(6, 0))

    # --- tombol jalankan ---
    btnbar = tk.Frame(root, bg=BG)
    btnbar.pack(fill="x", padx=22, pady=(2, 8))

    def flat_btn(parent, text, cmd, accent=False):
        b = tk.Label(parent, text=text, font=_mono(10),
                     bg=ACCENT if accent else CARD2,
                     fg="#ffffff" if accent else FG, padx=16, pady=10,
                     cursor="hand2")
        b.pack(side="left", padx=(0, 8))
        b.bind("<Button-1>", lambda e: cmd())
        return b

    # --- log box ---
    tk.Label(root, text="LOG", font=_mono(9), bg=BG, fg=MUTED,
             anchor="w").pack(fill="x", padx=22, pady=(4, 2))
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

    def log(msg):
        logbox.config(state="normal")
        logbox.insert("end", str(msg) + "\n")
        logbox.see("end")
        logbox.config(state="disabled")

    def set_status(text, color):
        root.after(0, lambda: status_lbl.config(text="  " + text, fg=color))

    status_lbl = tk.Label(root, text="  Siap", font=_mono(11),
                         bg=CARD, fg=MUTED, anchor="w")
    status_lbl.pack(fill="x", padx=22, pady=(0, 10))

    def run():
        chosen = mode.get()
        logfn = log

        def work():
            set_status(" menjalankan...", AMBER)
            if chosen == "install":
                results = setup_core.install_all(logfn)
            else:
                results = setup_core.uninstall_all(
                    keep_config=keep_var.get(), logfn=logfn)
            failed = [n for n, ok, _m in results if not ok]
            if failed:
                set_status(" selesai dengan gagal: " + ", ".join(failed), RED)
            else:
                set_status(" selesai", GREEN)
            for n, ok, m in results:
                log(f"  [{'v' if ok else '!'}] {n}: {m}")

        threading.Thread(target=work, daemon=True).start()

    flat_btn(btnbar, "Jalankan", run, accent=True)
    flat_btn(btnbar, "Keluar", lambda: root.destroy())

    log("Pilih 'Pasang' atau 'Lepas', lalu klik Jalankan.")
    log("Setiap langkah yang butuh root akan meminta izin (pkexec).")
    root.mainloop()


# ------------------------------------------------------------ CLI fallback ----
def run_cli():
    print("=== CLAUDEPAD Setup (CLI) ===")
    while True:
        print("\n  1) Pasang    2) Lepas    3) Keluar")
        try:
            p = input("Pilihan: ").strip()
        except EOFError:
            return
        if p == "1":
            for n, ok, m in setup_core.install_all(print):
                print(f"  [{'v' if ok else '!'}] {n}: {m}")
        elif p == "2":
            keep = input("Pertahankan konfigurasi? [y/N] ").strip().lower()
            keep_config = keep in ("y", "yes")
            for n, ok, m in setup_core.uninstall_all(keep_config=keep_config,
                                                      logfn=print):
                print(f"  [{'v' if ok else '!'}] {n}: {m}")
        elif p == "3":
            return
        else:
            print("Pilihan tidak dikenal.")


def main():
    try:
        import tkinter  # noqa: F401
        run_wizard()
    except Exception:  # noqa: BLE001
        print("(tkinter tidak tersedia - mode CLI)")
        run_cli()


if __name__ == "__main__":
    main()
