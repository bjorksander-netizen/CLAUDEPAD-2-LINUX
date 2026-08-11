# CLAUDEPAD LINUX

HP Android menjadi **trackpad, keyboard, media control, pengatur volume,
clipboard dua arah, dan now-playing** untuk PC **Linux**. Terhubung lewat
**WiFi / Hotspot** atau **kabel USB**.

Port dari [CLAUDEPAD-2](https://github.com/bjorksander-netizen/CLAUDEPAD-2)
(server Windows). Protokol jaringannya tidak diubah sedikit pun, jadi APK yang
sama bicara dengan server Windows maupun Linux — yang ditulis ulang hanya
lapisan sistem: injeksi input, volume, daya, radio, dan firewall.

**[⬇ Unduh APK + server terbaru](../../releases/tag/latest)** — dibangun
otomatis oleh GitHub Actions.

---

## 1. Menyiapkan PC Linux

```bash
git clone https://github.com/bjorksander-netizen/CLAUDEPAD-2-LINUX.git
cd CLAUDEPAD-2-LINUX/server
./install.sh
```

`install.sh` melakukan empat hal, dan mencetak setiap langkah sebelum
menjalankannya:

1. membuat virtualenv sendiri di `~/.local/share/claudepad/venv` lalu memasang
   dependensi Python di sana — Python sistem tidak disentuh;
2. memasang aturan udev supaya `/dev/uinput` bisa ditulis grup `input`, dan
   memasukkan kamu ke grup itu;
3. memasang entri menu aplikasi;
4. membuka port firewall bila `ufw` atau `firewalld` aktif.

> **Logout lalu login lagi setelah instalasi pertama.** Keanggotaan grup
> `input` baru berlaku di sesi baru. Tanpa itu server turun ke backend X11
> dan **tidak akan bekerja di Wayland** — yang merupakan default Ubuntu 22.04
> ke atas.

Jalankan servernya:

```bash
./start_server.sh              # dengan GUI
./start_server.sh --nogui      # konsol / SSH / systemd
```

> **Mode sandbox** (`--sandbox` atau `CLAUDEPAD_SANDBOX=1`): semua aksi
> berdampak-nyata (radio, daya, kecerahan, volume, clipboard, seek pemutar)
> **disimulasikan** — untuk menguji protokol tanpa menyentuh sistem.
> Jendela/konsol menampilkan `[SANDBOX]`.

Jendela CLAUDEPAD menampilkan **PIN**, **alamat IP**, **backend input**, dan
**status firewall**.

**Bacalah alamat IP dengan benar.** Alamat yang diberi label *virtual, jangan
dipakai* berasal dari `docker0`, `virbr0`, `veth*`, VPN, dan sejenisnya —
alamat itu **tidak bisa** dijangkau HP. Pakai alamat di baris paling atas.

### Distribusi yang diuji

| Distro | Sesi | Backend input |
|---|---|---|
| Ubuntu 22.04 / 24.04 | Wayland (GNOME) | uinput |
| Ubuntu 20.04 | X11 (GNOME) | uinput, cadangan XTEST |
| Fedora, Debian, Arch, Mint | X11 / Wayland | uinput |

Yang dibutuhkan hanyalah kernel dengan modul `uinput` (semua kernel Linux
modern punya) dan Python 3.8+.

## 2. Menghubungkan HP

### WiFi / Hotspot

HP dan PC harus di jaringan yang sama — boleh lewat router yang sama, hotspot
HP, atau hotspot PC.

Buka aplikasi → **cari otomatis** (atau ketik IP dari jendela server) → isi
**PIN** → **hubungkan**.

### USB

1. Di HP: aktifkan **Developer Options → USB Debugging**.
2. Colok kabel, setujui prompt di HP.
3. Di PC: klik **Mode USB** di jendela server, atau jalankan
   `server/usb_mode.sh`. Butuh `adb` (`sudo apt install adb`).
4. Di aplikasi: tekan **usb**, isi PIN.

---

## Yang berubah dari versi Windows

Protokol, enkripsi, pairing, discovery, dan seluruh tampilan aplikasi tetap
sama. Yang diganti adalah bagian yang memang tidak punya padanan langsung:

| Fungsi | Windows | Linux |
|---|---|---|
| Injeksi input | `SendInput` (Win32) | `uinput` (kernel), cadangan XTEST / xdotool |
| Volume | pycaw / Core Audio | `wpctl` → `pactl` → `amixer` |
| Kecerahan | WMI / DDC-CI | `brightnessctl` → `light` → sysfs → `ddcutil` |
| Daya | `shutdown.exe`, `SetSuspendState` | `systemctl`, `loginctl` |
| Kunci layar | `LockWorkStation` | `loginctl lock-session`, `xdg-screensaver` |
| WiFi / Bluetooth | Radio Management API | `nmcli`, `rfkill`, `bluetoothctl` |
| Hotspot | WinRT tethering | `nmcli device wifi hotspot` |
| Firewall | `netsh advfirewall` | `ufw` / `firewalld` lewat `pkexec` |
| Auto-start | Registry `HKCU\...\Run` | `~/.config/autostart/claudepad.desktop` |
| Simpan token | Credential Manager | keyring (KWallet/GNOME Keyring), cadangan berkas 0600 |
| Data aplikasi | di sebelah `.exe` | `~/.config/claudepad` (XDG) |
| Clipboard (v3.7) | API Win32 | `wl-copy`/`wl-paste` (Wayland) atau `xclip`/`xsel` (X11) |
| Now-playing (v3.7) | `AddIn` media | MPRIS lewat `gdbus`, fallback `playerctl` |

### Backend input

Ada tiga, dicoba berurutan:

1. **uinput** — membuat perangkat virtual di kernel. Satu-satunya yang bekerja
   di **Wayland maupun X11**, jadi ini yang utama. Butuh akses tulis ke
   `/dev/uinput`.
2. **XTEST** — hanya X11, tapi tanpa izin khusus. Otomatis dipakai kalau
   uinput tidak bisa diakses.
3. **xdotool** — jaring pengaman terakhir; juga dipakai untuk mengetik
   karakter di luar tata letak QWERTY-US.

Backend yang sedang dipakai tampil di jendela server dan di
**⚙ Setting → backend input** pada HP.

Paksa backend tertentu untuk menguji:

```bash
./start_server.sh --input-backend xtest
```

### Gesture tiga jari

Linux tidak punya pintasan universal untuk Task View dan Show Desktop, jadi
CLAUDEPAD memilih default sesuai desktop yang terdeteksi (GNOME, KDE, XFCE,
Cinnamon). Kalau pintasan di mesinmu berbeda, ubah di
`~/.config/claudepad/gestures.json` — berkasnya dibuat otomatis saat server
pertama kali jalan, dan tidak perlu build ulang apa pun:

```json
{
  "taskview":    { "key": "win", "mods": [] },
  "showdesktop": { "key": "d",   "mods": ["win"] },
  "appnext":     { "key": "tab", "mods": ["alt"] },
  "appprev":     { "key": "tab", "mods": ["alt", "shift"] }
}
```

### Yang belum ada padanannya

- **Indikator posisi scroll.** Server Windows membacanya lewat
  `GetScrollInfo`. X11 dan Wayland tidak menyediakan padanan lintas-toolkit,
  jadi indikatornya tidak ditampilkan di Linux.
- **Matikan layar di Wayland.** Tersedia di X11 (`xset dpms`), Sway, dan
  Hyprland; di GNOME/KDE Wayland belum ada perintah standar. Tombolnya
  otomatis diredupkan bila PC melaporkan tidak mendukungnya.
- **Hibernasi** sering dimatikan distro yang tanpa partisi swap. Server
  menanyakannya ke logind lebih dulu, dan tombol yang tidak didukung
  diredupkan di HP.

---

## Clipboard dua arah (v3.7)

Salin teks di HP → langsung bisa **paste** di PC, dan sebaliknya.

- **HP → PC:** menu salin di aplikasi mengirim teks ke clipboard PC.
- **PC → HP:** server memantau clipboard PC tiap ~1 detik; begitu isinya
  berubah, teks otomatis dikirim ke HP (anti-loop: teks yang barusan dikirim
  dari HP tidak dikirim balik).
- **Sinkronisasi bisa dimatikan** per koneksi dari aplikasi. Saat mati,
  server tidak lagi memantau dan permintaan "salin dari HP" ditolak dengan
  pesan "sinkronisasi clipboard nonaktif".
- Butuh `wl-clipboard` (Wayland) atau `xclip`/`xsel` (X11). Tanpa tool
  tersebut fitur dilaporkan tidak tersedia di *Setting* dan permintaan
  clipboard gagal dengan pesan yang jelas.

## Now Playing (MPRIS, v3.7)

Server membaca judul, artis, album, status putar, dan posisi pemutar media
melalui **MPRIS** — standar D-Bus yang didukung Spotify, VLC, Rhythmbox,
Firefox (plugin), dan banyak lagi.

- **Info pemutar** tampil di aplikasi dan diperbarui lewat tombol *refresh*.
- **Seek** memakai `SetPosition` (presisi microsecond) saat track id
  tersedia, fallback `Seek` relatif.
- Query memakai `gdbus`; kalau tidak ada, fallback ke `playerctl`.
  Tanpa pemutar / tanpa D-Bus, permintaan dibalas `ok:false` dengan pesan
  alasan — tidak pernah menggantung.

## Menghapus server

```bash
cd CLAUDEPAD-2-LINUX/server
./uninstall.sh          # hapus semuanya, kecuali konfigurasi (ditanyakan)
./uninstall.sh --keep-config   # hapus program, pertahankan token pairing
```

`uninstall.sh` idempotent dan mencetak tiap langkah: virtualenv, aturan udev,
entri menu, autostart, dan unit systemd user. Keanggotaan grup `input` tidak
dicabut otomatis karena dipakai bersama aplikasi lain.

---

## Gesture trackpad

| Gesture | Fungsi |
|---|---|
| 1 jari geser | gerakkan kursor |
| 1 jari tap | klik kiri |
| 2 jari tap | klik kanan |
| 2 jari geser | scroll |
| 2 jari cubit | zoom (Ctrl + scroll) |
| 3 jari ke atas | ikhtisar jendela |
| 3 jari ke bawah | tampilkan desktop |
| 3 jari kiri / kanan | ganti aplikasi |
| 3 jari ketuk | klik tengah |
| tap 2× lalu tahan | drag & drop |

Roda scroll memakai sumbu hi-res kernel (`REL_WHEEL_HI_RES`) yang satuannya
1/120 notch — kebetulan persis sama dengan `WHEEL_DELTA` milik Windows, jadi
angka dari HP dipakai apa adanya. Sisa di bawah satu notch disimpan, tidak
dibuang, sehingga scroll pelan tetap mulus dan tidak pernah berbalik arah.

---

## Kalau koneksi bermasalah

### Langkah 1 — Diagnosa koneksi

Buka **⚙ Setting → diagnosa koneksi** di HP. Laporannya menunjukkan interface
HP, rute yang dipilih, hasil tes TCP, balasan server, dan tes pencarian.

### Langkah 2 — Tes lewat browser

Buka **`http://<ip-pc>:8765`** di browser HP.

- **Muncul halaman status** → jaringan dan firewall sudah benar.
- **Tidak bisa dijangkau** → firewall atau alamat IP-nya salah.

### Tabel masalah umum

| Masalah | Penyebab & solusi |
|---|---|
| Kursor tidak bergerak sama sekali, jendela server bilang "Input: TIDAK AKTIF" | `/dev/uinput` tak bisa ditulis. Jalankan `server/install.sh`, lalu **logout & login** |
| Jalan di X11 tapi mati di Wayland | Backend turun ke XTEST. Sama seperti di atas: butuh uinput |
| Cari otomatis tidak ketemu | Klik **Perbaiki Firewall**, atau `sudo ufw allow 8765/tcp && sudo ufw allow 8766/udp` |
| Koneksi timeout | IP yang dipakai kemungkinan interface virtual — pakai alamat yang tidak berlabel virtual |
| "versi tidak cocok" | Perbarui APK dan folder `server/` ke versi yang sama |
| Volume tidak berubah | Pasang salah satu: `wireplumber` (wpctl), `pulseaudio-utils` (pactl), atau `alsa-utils` (amixer) |
| Kecerahan tidak berubah | `sudo apt install brightnessctl`; untuk monitor eksternal `ddcutil` |
| Huruf beraksen tidak muncul | Pasang `wtype` (Wayland) atau `xdotool` (X11) — uinput saja tidak tahu tata letak keyboard |
| Tray tidak muncul | GNOME butuh ekstensi AppIndicator; server tetap jalan, jendelanya cukup diminimalkan biasa |
| USB gagal | Cek `adb devices` menampilkan device, bukan `unauthorized` |

---

## Jalan otomatis saat login

Centang **"Jalankan server otomatis saat login"** di jendela server. Itu
menulis `~/.config/autostart/claudepad.desktop`.

Untuk server tanpa GUI (mis. PC yang dipakai lewat SSH), tersedia unit
systemd:

```bash
mkdir -p ~/.config/systemd/user
cp server/claudepad.service ~/.config/systemd/user/
systemctl --user enable --now claudepad
```

Unit itu sengaja bukan default: systemd `--user` tidak mewarisi
`DISPLAY`/`WAYLAND_DISPLAY` dari sesi grafis, dan tanpa variabel itu backend
XTEST serta beberapa aksi daya tidak menemukan sesinya.

---

## Build APK sendiri

1. Install [Android Studio](https://developer.android.com/studio).
2. **Open** → pilih folder `android/`, tunggu Gradle sync.
3. **Build → Build App Bundle(s)/APK(s) → Build APK(s)**.

Font JetBrains Mono opsional: jalankan `android/fetch-font.sh`. Tanpa berkas
font, aplikasi memakai monospace bawaan sistem dan build tetap berhasil.

## Keamanan

- Server meminta **PIN acak** yang berubah setiap kali dijalankan.
- Setelah berhasil sekali, server memberi **token pairing** sehingga koneksi
  berikutnya tidak perlu mengetik PIN. Token disimpan di keyring desktop, atau
  di `~/.config/claudepad/paired.txt` dengan mode `0600` bila keyring tidak
  ada. Bisa dihapus lewat Setting.
- **PIN dienkripsi RSA-2048/OAEP** saat dikirim, lalu seluruh lalu lintas
  dienkripsi ChaCha20 dengan tag HMAC-SHA256. Kunci sesi diturunkan sendiri
  oleh kedua pihak lewat PBKDF2 dan tidak pernah melintas di jaringan.
- **Rate limiting**: tiga PIN salah dalam satu menit memblokir IP itu 30 detik.
- **Kunci versi**: APK dengan versi yang tidak dikenal ditolak.
- Hanya untuk jaringan lokal. Jangan buka port 8765 ke internet.

### Catatan tentang uinput

Aturan udev di repo ini memberi grup `input` akses tulis ke `/dev/uinput`.
Artinya program apa pun yang dijalankan pengguna di grup itu bisa membuat
perangkat input virtual — dan dengan begitu bisa menyuntikkan ketikan. Ini
model izin yang sama dengan yang dipakai `ydotool`, Wooting, dan alat
aksesibilitas lain, tapi tetap perlu kamu ketahui sebelum memasangnya.

## Struktur

```
CLAUDEPAD-2-LINUX/
├── server/                    jalan di PC Linux
│   ├── pc_server.py           GUI desktop + layer WebSocket
│   ├── input_core.py          backend input, volume, gesture, discovery, firewall, clipboard & MPRIS dispatch
│   ├── clipboard.py           baca/tulis clipboard (wl-copy/wl-paste, xclip/xsel)
│   ├── mpris.py               now-playing & seek via MPRIS (gdbus, fallback playerctl)
│   ├── system_ctl.py          kecerahan, daya, MAC untuk WoL
│   ├── crypto_box.py          enkripsi ChaCha20 + HMAC + RSA (pasangan CryptoBox.kt)
│   ├── binary_protocol.py     encoder biner (pasangan BinaryProtocol.kt)
│   ├── paths.py               path XDG
│   ├── autostart.py           entri autostart XDG
│   ├── install.sh             pemasangan sekali jalan
│   ├── uninstall.sh           penghapusan (kebalikan install.sh)
│   ├── start_server.sh        jalankan (bikin virtualenv sendiri)
│   ├── fix_firewall.sh        buka port lewat pkexec
│   ├── usb_mode.sh            adb reverse
│   ├── claudepad.service      unit systemd --user (opsional)
│   ├── 99-claudepad-uinput.rules   aturan udev
│   └── tests/                 uji protokol, peta tombol, keamanan, dan input X11
└── android/                   project Android Studio (Kotlin)
```

## Uji

Semua uji jalan tanpa perangkat keras khusus dan ikut dijalankan di CI:

```bash
cd server
python3 tests/test_keymaps.py     # peta tombol evdev & X11
python3 tests/test_safety.py      # jaring pengaman: tidak ada aksi sistem nyata
python3 tests/test_e2e.py         # kripto, binary protocol, handshake, discovery
python3 tests/test_input_x11.py   # backend input di X server Xvfb sungguhan
```

`test_input_x11.py` benar-benar menggerakkan pointer dan menekan tombol di
server X, lalu membaca event-nya kembali — jadi arah scroll, pelepasan
modifier, dan pemetaan tombol diverifikasi, bukan diasumsikan.
