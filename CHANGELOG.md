# Changelog

## v3.9.1 — perbaikan NPE paste-image (APK)

- **Bug fix**: `pasteImageToClipboard` di APK tidak lagi NPE saat clipboard PC
  berisi teks (predikat menunggu `imgB64 != null`, bukan `|| ok`).
- Versi server & APK diselaraskan ke 3.9.1.

## v3.9 — gesture 4 jari, clipboard gambar, perbaikan power/media

- **Fitur baru**
  - Gesture 4 jari di trackpad: swipe kiri/kanan = ganti workspace
    (`workspace_prev`/`workspace_next`), atas/bawah = task view / show desktop.
  - Clipboard gambar dua arah (PNG): "copy image" kirim gambar clipboard HP ke
    PC, "paste image" simpan gambar clipboard PC ke folder Download HP.
- **Perbaikan**
  - Power control: `caps.power` kini melaporkan aksi yang benar-benar tersedia
    di sesi (systemd/loginctl) sehingga tombol matikan/restart/tidur/hibernasi/
    keluar sesi tidak lagi TEREDUPKAN ("hanya lock yang jalan" teratasi).
  - Media control: server membalas `media_result` agar APK bisa menampilkan
    toast bila perintah media gagal (tidak diam).
  - Tray: tombol "Ke Tray" tetap ada; tombol X (tutup window) kini mematikan
    proses server, bukan cuma bersembunyi.
- **Internal**: `clip_set`/`clip_get` dukung field `img` (base64 PNG);
  `build-apk.yml` menjalankan `test_media`, `test_gesture4`, `test_clip_image`.

## v3.8 — wizard install & uninstall (PC Linux)

Logika pemasangan/penghapusan diport dari bash (`install.sh`/`uninstall.sh`)
ke Python murni (`setup_core.py`) dan diberi wizard grafis (`wizard.py`).

### Fitur baru

- **Wizard setup (Tkinter).** Tombol "Setup Wizard" di jendela server, atau
  `python3 pc_server.py --wizard` dari konsol, membuka panduan multi-step:
  pasang virtualenv + dependensi, aturan udev & grup input, entri menu,
  autostart, dan buka port firewall. Tanpa `tkinter`, wizard jatuh ke mode
  CLI (prompt teks).
- **Idempoten & sandbox-aware.** `setup_core` aman dijalankan berkali-kali;
  saat mode `--sandbox` aktif semua aksi sistem hanya disimulasikan.
- **`install.sh`/`uninstall.sh` jadi wrapper tipis** ke `setup_core.py`
  (sumber kebenaran sekarang di Python, bukan bash).
- **Test keamanan setup.** `tests/test_setup.py` membuktikan install/uninstall
  tidak menjalankan subprocess nyata saat `safe_harness` aktif, dan
  `safe_harness` kini men-stub `input_core.is_sandbox()` (GAP #3) supaya
  wizard tidak menyentuh sistem di jalur test.

### Catatan kompatibilitas

- Versi naik ke **3.8**; server hanya menerima APK 3.8
  (`COMPATIBLE_APP_VERSIONS = {"3.8"}`).

## v3.7 — clipboard dua arah, now playing, uninstall

Keputusan proyek: **lepas kompatibilitas dengan server Windows**. Protokol
kini bebas berkembang, dan server hanya menerima APK dengan versi **3.7**
yang sama (`COMPATIBLE_APP_VERSIONS = {"3.7"}`).

### Fitur baru

- **Clipboard dua arah (otomatis).** Saat teks disalin di PC, server
  mendeteksinya (polling ~1 detik lewat `wl-paste`/`xclip`) dan mengirimnya ke
  HP; sebaliknya, teks yang disalin di HP otomatis masuk ke clipboard PC.
  Dilengkapi **anti-loop** di kedua sisi (konten yang baru saja ditulis sendiri
  tidak dipantulkan kembali), **toggle privasi** di ⚙ Setting (default nyala,
  hanya aktif saat terhubung), dan perintah manual `clipget`/`clipset` tetap
  tersedia. Tombol lama Ctrl+C/Ctrl+V di popup tetap dipertahankan.
- **Now playing (MPRIS).** Kartu lagu di halaman kontrol menampilkan judul,
  artis, dan status play/pause dari pemutar yang sedang aktif di PC (dibaca
  lewat `gdbus`/`playerctl`, prefer pemutar yang sedang Playing). Kontrol
  play/pause/next/prev memakai tombol media yang sudah ada; **seek bar**
  muncul bila pemutar mendukung (`CanSeek`) dan menggesernya melompatkan
  pemutaran (`SetPosition`/`Seek`).
- **Uninstall server.** `server/uninstall.sh` menghapus virtualenv, aturan
  udev, entri menu, autostart, dan unit systemd. Idempoten dan mencetak tiap
  langkah; config (`~/.config/claudepad`) hanya dihapus dengan konfirmasi
  atau `--keep-config`.

### Keamanan pengujian (penting)

- Test **tidak boleh lagi mengeksekusi aksi sistem nyata** di mesin
  pengembang: fondasi `server/tests/safe_harness.py` memaksa semua aksi
  berdampak-nyata (daya, radio, kecerahan, volume, firewall, input, clipboard,
  MPRIS) menjadi simulasi; eksekusi nyata hanya lewat env
  `CLAUDEPAD_ALLOW_REAL=1` di lingkungan terisolasi.
- **Mode `--sandbox`** di server (atau `CLAUDEPAD_SANDBOX=1`) mensimulasikan
  semua aksi sistem sehingga jalur penuh bisa diuji tanpa efek samping.
- `tests/test_safety.py` menjadi **gerbang wajib** di CI sebelum test lain.

### Perubahan lain

- Backend clipboard: `wl-copy`/`wl-paste` (Wayland) → `xclip`/`xsel` (X11).
  Now playing: `gdbus` → fallback `playerctl`. Tanpa tool, tombol/indikator
  diredupkan lewat `caps.clipboard` dan `caps.nowplaying`.
- APK naik ke versionCode 21 (versionName 3.7).

## v3.6 — port Linux (rilis pertama repo ini)

Turunan dari [CLAUDEPAD-2](https://github.com/bjorksander-netizen/CLAUDEPAD-2)
v3.5. Protokol jaringan **tidak diubah**; yang ditulis ulang adalah lapisan
sistem di server.

### Server: baru sepenuhnya

- **Backend input berlapis.** `uinput` (python-evdev) sebagai utama karena
  hanya itu yang bekerja di Wayland maupun X11; turun ke XTEST (python-xlib)
  lalu xdotool bila `/dev/uinput` tidak bisa diakses. Backend yang terpilih
  dilaporkan ke HP dan tampil di jendela server, jadi kegagalan izin terlihat
  jelas alih-alih berwujud "kursor tidak bergerak".
- **Scroll hi-res.** Memakai `REL_WHEEL_HI_RES` yang satuannya 1/120 notch —
  persis sama dengan `WHEEL_DELTA` Windows, sehingga angka dari HP dipakai apa
  adanya. Sisa di bawah satu notch disimpan, bukan dibuang, jadi scroll pelan
  tidak patah dan tidak pernah berbalik arah.
- **Volume** lewat `wpctl` → `pactl` → `amixer`. Mute dilakukan di mixer, bukan
  lewat tombol media, karena tidak semua desktop memasang `XF86AudioMute`.
- **Kecerahan** lewat `brightnessctl` → `light` → sysfs → `ddcutil`.
- **Daya** lewat systemd/logind. Sebelum menampilkan tombol, server menanyakan
  ke logind aksi mana yang benar-benar mungkin (`can-hibernate` dan
  kawan-kawan) lalu mengirimkannya ke HP.
- **WiFi / Bluetooth / hotspot** lewat `nmcli`, `rfkill`, dan `bluetoothctl`.
- **Firewall** `ufw` dan `firewalld`, dibuka lewat `pkexec`. Mesin tanpa
  firewall aktif dilaporkan sebagai "sudah terbuka" alih-alih "bermasalah".
- **Gesture per-desktop.** GNOME, KDE, XFCE, dan Cinnamon punya default
  masing-masing, dan bisa ditimpa lewat `~/.config/claudepad/gestures.json`
  tanpa build ulang.
- **Path XDG.** Token dan konfigurasi di `~/.config/claudepad` (mode 0700),
  bukan lagi di sebelah executable. Token disimpan di keyring desktop bila
  ada, kalau tidak di berkas mode 0600.
- **Auto-start** lewat `~/.config/autostart/claudepad.desktop`. Unit systemd
  `--user` disertakan untuk pemakaian tanpa GUI.
- **Penyaringan interface virtual** disesuaikan ke Linux: `docker0`, `br-*`,
  `veth*`, `virbr*`, `tun/tap`, WireGuard, Tailscale, ZeroTier.
- **`install.sh`** memasang dependensi di virtualenv sendiri (aman terhadap
  PEP 668), memasang aturan udev untuk `/dev/uinput`, membuat entri menu, dan
  membuka port firewall.

### Server: perbaikan yang juga berlaku untuk versi Windows

- Balasan yang dijadwalkan saat klien menutup soket tidak lagi memunculkan
  `Task exception was never retrieved` di log setiap kali HP memutus koneksi.
- Alamat MAC untuk Wake-on-LAN dibaca dari sysfs interface default, bukan
  ditebak dari `uuid.getnode()` yang bisa mengarang alamat.

### Aplikasi Android

- Membaca bidang baru `platform`, `desktop`, `session`, dan `caps` dari
  `auth_ok`. Server yang tidak mengirimnya (termasuk server Windows v3.5)
  ditangani sebagai "tidak melapor", dan aplikasi berperilaku persis seperti
  sebelumnya.
- **⚙ Setting → sistem** menampilkan platform dan desktop PC;
  **backend input** menampilkan backend yang dipakai, merah bila tidak aktif.
  Barisnya disembunyikan saat tersambung ke server Windows.
- Tombol daya yang dilaporkan tidak didukung (mis. hibernasi tanpa swap, atau
  matikan layar di Wayland) **diredupkan** dan memberi pesan jelas, alih-alih
  gagal diam-diam.
- Panduan gesture memakai istilah netral dan menyebutkan berkas
  `gestures.json`.
- Versi naik ke 3.6 (versionCode 20).

### Kompatibilitas

- Server Linux menerima APK **v3.6 dan v3.5**, jadi APK CLAUDEPAD-2 yang sudah
  terpasang tetap bisa dipakai apa adanya — hanya tanpa tampilan info platform
  dan peredupan tombol.
- APK v3.6 tetap bisa tersambung ke server Windows v3.5 kalau versi di sisi
  Windows dinaikkan; tanpa itu server Windows menolak karena mensyaratkan
  kecocokan persis.

### Uji

- `tests/test_keymaps.py` — memverifikasi setiap nama tombol di protokol
  benar-benar ada di evdev dan X11, dan tabel ASCII menutup seluruh karakter
  cetak. Uji ini menangkap satu bug nyata: python-xlib menamai tombol media
  `XF86_AudioPlay`, bukan `XF86AudioPlay` seperti xdotool.
- `tests/test_e2e.py` — kripto (vektor RFC 8439), binary protocol, handshake
  RSA + ChaCha20, pairing token, rate limiting, discovery UDP, health HTTP.
- `tests/test_input_x11.py` — menggerakkan pointer dan menekan tombol di
  server X sungguhan (Xvfb), lalu membaca event-nya kembali: arah scroll,
  pelepasan modifier, akumulasi setengah notch, dan pemetaan tombol.
- CI menjalankan ketiganya di websockets 12.0, 13.1, dan 15.0.1, plus sekali
  lagi tanpa dependensi opsional untuk memastikan server tetap hidup.
