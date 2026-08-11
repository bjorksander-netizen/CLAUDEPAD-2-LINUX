# AUDIT KEAMANAN TEST — Aksi Sistem Nyata (beta / QA)

Tanggal audit: 2026-08-12 · HEAD: 6da2e88 (branch main)
Aturan acuan: `OPEN-CONVENTIONS.md` Bagian 4 (test dilarang mengeksekusi
aksi sistem nyata; wajib mock; guard `CLAUDEPAD_ALLOW_REAL=1`; mode `--sandbox`).

Status integrasi agen lain (tesla) saat audit: **fondasi sudah masuk working
tree** (`server/tests/safe_harness.py`, mode `--sandbox` di `pc_server.py`,
stub SANDBOX di `input_core.py`/`system_ctl.py`, `test_e2e.py` memakai
`safe_harness.activate()` di `main()`). File yang diubah tesla TIDAK disentuh
oleh audit ini; audit hanya menambah `test_safety.py` + file ini.

---

## 1. DAFTAR TITIK RISIKO EKSEKUSI SISTEM-NYATA

Legend status: **[NYATA]** masih bisa menyentuh sistem · **[DI-STUB]** sudah
dimock oleh safe_harness/sandbox · **[READ]** hanya baca, tanpa efek ·
**[TIDAK DIPANGGIL TEST]** tidak dipanggil dari suite test.

### A. `server/system_ctl.py`

| # | File:Baris | Fungsi | Perintah nyata yang dijalankan | Cara dipanggil test | Dampak | Status |
|---|-----------|--------|-------------------------------|--------------------|--------|--------|
| 1 | system_ctl.py:271-292 | `power_action` | dispatcher → lihat #2-#5 | test_e2e (langsung & via WS); test_safety (stub) | daya | **[DI-STUB]** |
| 2 | system_ctl.py:195-209 | `_lock_session` | `loginctl lock-session` (197-198), `xdg-screensaver lock` (201), `gnome-screensaver-command --lock` (202), `qdbus … ScreenSaver Lock` (203), `swaylock`/`i3lock` (204) | test_e2e lama via `power_action("lock")` | **LAYAR TERKUNCI** | **[DI-STUB]** (safe_harness + SANDBOX) |
| 3 | system_ctl.py:230-250 | `_screen_off` | `xset dpms force off` (233), `swaymsg output * power off` (238), `hyprctl dispatch dpms off` (242), `gnome-screensaver-command --activate` (246) | test_e2e lama via `power_action("screenoff")` | **LAYAR MATI** | **[DI-STUB]** |
| 4 | system_ctl.py:212-227 | `_logoff` | `gnome-session-quit --logout` (213), `qdbus ksmserver logout` (214), `xfce4-session-logout` (215), `cinnamon-session-quit` (216), `loginctl terminate-session` (223) | tidak langsung (via power_action di test baru) | **KELUAR SESI** | **[DI-STUB]** |
| 5 | system_ctl.py:177-182, 279-291 | `power_action` (shutdown/restart/sleep/hibernate) | `systemctl poweroff|reboot|suspend|hibernate` | tidak langsung (via power_action di test baru) | **PC MATI/TIDUR** | **[DI-STUB]** |
| 6 | system_ctl.py:159-172 | `brightness_step` | `brightnessctl -q set` (105), `light -S` (122), tulis `/sys/class/backlight/*/brightness` (73-85), `ddcutil setvcp` (146) | test_e2e lama (`brightness_step(10)` + WS `{"t":"bright"}`) | **KECERAHAN BERUBAH** | **[DI-STUB]** |
| 7 | system_ctl.py:150-156 | `brightness_get` | `brightnessctl -m get/max`, `light -G`, baca sysfs | test_e2e (capabilities) | baca saja | **[READ]** |
| 8 | system_ctl.py:185-192 | `_can` | `systemctl can-power-off/reboot/suspend/hibernate` | test_e2e (capabilities) | baca saja | **[READ]** |
| 9 | system_ctl.py:305-325 | `mac_address` | `ip route show default` + baca sysfs | test_e2e (auth_ok) | baca saja | **[READ]** |

### B. `server/input_core.py`

| # | File:Baris | Fungsi | Perintah nyata | Cara dipanggil test | Dampak | Status |
|---|-----------|--------|----------------|--------------------|--------|--------|
| 10 | input_core.py:852-905 | `toggle_radio` | lihat #11-#13 | test_e2e lama (langsung + WS) | radio | **[DI-STUB]** |
| 11 | input_core.py:828-838 | `_nmcli_radio` | `nmcli radio wifi` + `nmcli radio wifi on/off` (830, 835) | via toggle_radio("wifi") | **WiFi MATI-NYALA** | **[DI-STUB]** |
| 12 | input_core.py:841-849 | `_rfkill_toggle` | `rfkill list`, `rfkill block/unblock` (842, 846) | via toggle_radio("wifi"/"bluetooth") | **WiFi/BT MATI** | **[DI-STUB]** |
| 13 | input_core.py:865-903 | `toggle_radio` bluetooth & hotspot | `bluetoothctl show` (867), `bluetoothctl power on/off` (869-870), `nmcli connection down` (889), `nmcli device wifi hotspot …` (897-899) | via toggle_radio("bluetooth"/"hotspot") | **BT MATI / HOTSPOT NYALA-MATI** | **[DI-STUB]** |
| 14 | input_core.py:791-808 | `volume_set` | `wpctl set-volume` (797), `pactl set-sink-volume` (802), `amixer -M -q set` (806) | test_e2e lama via WS `{"t":"volset","v":50}` | **VOLUME BERUBAH** | **[DI-STUB] (safe_harness)** — sandbox BELUM |
| 15 | input_core.py:811-824 | `volume_mute_toggle` | `wpctl set-mute` (814), `pactl set-sink-mute` (818), `amixer toggle` (822) | via handle_message("media" mute) | **MUTE NYATA** | **[DI-STUB] (safe_harness)** — sandbox BELUM |
| 16 | input_core.py:762-788 | `volume_get` | `wpctl get-volume`, `pactl get-sink-volume/list`, `amixer -M get` | test_e2e (auth_ok, volget) | baca saja | **[READ]** |
| 17 | input_core.py:561-570 | `_type_text_external` | `wtype` (564), `xdotool type` (567) | jalur text backend uinput/X11 | **KETIKAN NYATA** | **[TIDAK DIPANGGIL TEST]** (BACKEND null di audit) |
| 18 | input_core.py:516-517 | `XdotoolBackend._x` | `subprocess.run(["xdotool", …])` | test_input_x11 (di Xvfb) | input X nyata | **[TIDAK DIPANGGIL TEST]** (test_input_x11 hanya di Xvfb) |
| 19 | input_core.py:577-613 | `init_backend` | buka `/dev/uinput` (UinputBackend), buka display X (XtestBackend) | test_e2e (`init_backend()`), test_input_x11 | **PERANGKAT INPUT VIRTUAL / KONEKSI X NYATA** | **[TIDAK DI-STUB]** — lihat GAP #2 |
| 20 | input_core.py:617-651 | `mouse_move/click/scroll/press_key/type_text/media_key/zoom` | injeksi via BACKEND terpilih | test_e2e lama (langsung + WS move/key/gesture) | **KURSOR/TOMBOL NYATA** | **[TIDAK DI-STUB]** — lihat GAP #2 |
| 21 | input_core.py:1095-1105 | `_firewall_tool` | `ufw status` (1098), `firewall-cmd --state` (1104) | via firewall_status | baca (bisa salah terdeteksi) | **[READ]** |
| 22 | input_core.py:1108-1131 | `firewall_status` | `ufw status` (1117), **`pkexec --disable-internal-agent ufw status` (1119)**, `firewall-cmd --query-port` (1129-1130) | test_e2e `test_linux_layer` (firewall_status) | **PROMPT GRAFIS pkexec** di mesin ber-ufw tanpa root | **[NYATA — GAP #1]** |
| 23 | input_core.py:1138-1167 | `fix_firewall` | `pkexec fix_firewall.sh` (1160) | tidak dipanggil test (tombol GUI) | **UBAH FIREWALL** | **[TIDAK DIPANGGIL TEST]** |
| 24 | input_core.py:1171-1183 | `enable_usb_mode` | `adb start-server`, `adb reverse` (1176-1177) | tidak dipanggil test (tombol GUI) | adb nyata | **[TIDAK DIPANGGIL TEST]** |
| 25 | input_core.py:1042-1056 | `_ip_addresses` | `ip -o -4 addr show` | test_e2e (local_ips) | baca saja | **[READ]** |
| 26 | input_core.py:920-973 | `handle_message` | dispatcher → #14-#20, system_ctl | test_e2e (langsung + WS) | tergantung pesan | lihat per-baris |

### C. `server/pc_server.py`

| # | File:Baris | Fungsi | Keterangan | Status |
|---|-----------|--------|------------|--------|
| 27 | pc_server.py:173-363 | `handle` (WebSocket) | meneruskan pesan terautentikasi ke `handle_message` — termasuk radio/power/bright/volset | jalur nyata; aman selama stub aktif |
| 28 | pc_server.py:771-773 | `--sandbox` / `CLAUDEPAD_SANDBOX=1` | mengaktifkan `core.set_sandbox(True)` | **[BARU] mode sandbox** |

### D. Test files

| # | File:Baris | Keterangan | Status |
|---|-----------|------------|--------|
| 29 | test_e2e.py (lama, commit ≤ 0267f66) | `power_action("lock"/"screenoff")`, `toggle_radio(wifi/bluetooth/hotspot)`, `brightness_step`, WS `radio/power/bright/volset` → semuanya NYATA | diperbaiki oleh tesla |
| 30 | test_e2e.py:400-420 (baru) | `safe_harness.activate()` di awal `main()`; `assert_no_real_calls()` di akhir | **[DI-STUB]** |
| 31 | test_e2e.py:174-175 (baru) | `core.firewall_status()` **masih nyata** → pkexec | **[NYATA — GAP #1]** |
| 32 | test_keymaps.py | verifikasi tabel statis; tanpa subprocess | aman |
| 33 | test_input_x11.py | hanya jalan di Xvfb + python-xlib; skip bila tak ada | aman (terisolasi Xvfb) |
| 34 | test_safety.py (BARU, audit) | jaring pengaman permanen; hijau; tanpa efek samping | **[BARU]** |

---

## 2. HASIL JALANKAN SUITE

Lingkungan: sesi Wayland, `/dev/uinput` dapat diakses user (grup `input`),
`nmcli/rfkill/bluetoothctl/loginctl/brightnessctl/wpctl/amixer/ufw/pkexec`
terpasang; `evdev`/`Xlib` TIDAK terpasang di env python ini; Xvfb tidak ada.

| Suite | Cara jalan | Hasil |
|-------|-----------|-------|
| test_keymaps.py | langsung | **LULUS** (exit 0) |
| test_e2e.py | guard audit (semua subprocess diblokir) — versi lama | LULUS, 85 panggilan diblokir (lock/radio/bright/volset terlihat) |
| test_e2e.py | safe_harness + guard pkexec/sudo + NullBackend — versi baru | **LULUS** (exit 0); guard mencatat 1 panggilan `pkexec` |
| test_safety.py | langsung | **LULUS** (exit 0) |
| test_input_x11.py | langsung | **SKIP** (Xvfb & python-xlib tidak ada) |

## 3. BUKTI SISTEM TIDAK BERUBAH (SEBELUM vs SESUDAH)

Snapshot read-only `nmcli radio`, `rfkill list`, `loginctl show-session`,
`wpctl get-volume`, `amixer`, `brightnessctl` diambil sebelum & sesudah
setiap fase. Hasil `diff` seluruh fase: **hanya baris timestamp yang berbeda**;
tidak ada perubahan WIFI/BT/kunci-layar/volume/kecerahan.

Contoh kunci (sebelum = sesudah):
- `nmcli radio`: `WIFI enabled`, `WWAN enabled`
- `rfkill list`: `Soft blocked: no` untuk tpacpi_bluetooth_sw, hci0, phy0
- `loginctl show-session 3`: `LockedHint=no`, `Active=yes`
- `wpctl`: `Volume: 0.80`; `brightnessctl`: 1061/1515

## 4. STATUS UJI MODE --SANDBOX

`python3 pc_server.py --sandbox --nogui` di-spawn nyata; banner
`[SANDBOX - aksi daya/radio/kecerahan disimulasikan]` tampil; autentikasi
WebSocket + kirim `radio wifi/bluetooth/hotspot`, `power lock/screenoff/
shutdown/restart/sleep/hibernate/logoff`, `bright 10`, `ping`:
- **SEMUA UJI SANDBOX LULUS** (exit 0): balasan `ok=True` + pesan
  `"disimulasikan (sandbox)"` / `"simulasi sandbox"`.
- Sistem tidak berubah (diff snapshot hanya timestamp).
- Log server mencatat `sandbox: simulasi …` untuk tiap aksi — tidak ada
  eksekusi nyata.

## 5. RINGKASAN test_safety.py (jaring pengaman permanen)

File baru `server/tests/test_safety.py` — deterministik, tanpa efek samping,
hijau. Menguji:
1. safe_harness mensimulasikan SEMUA aksi daya (shutdown/restart/sleep/
   hibernate/logoff/lock/screenoff), radio (wifi/bluetooth/hotspot),
   brightness, volume tanpa `CLAUDEPAD_ALLOW_REAL=1`; `REAL_CALLS == []`.
2. Dengan harness aktif, jalur berbahaya TIDAK memanggil subprocess sama
   sekali (recorder yang melempar; nol panggilan).
3. Gerbang `CLAUDEPAD_ALLOW_REAL` (logika keputusan, tanpa eksekusi).
4. `assert_no_real_calls()` melempar saat `REAL_CALLS` terisi.
5. `activate()`/`restore()` idempotent dan mengembalikan fungsi asli.
6. Mode sandbox menyimulasikan radio/power/bright dengan NOL subprocess.
7. Daftar pola perintah berbahaya lengkap (menjaga penjaga itu sendiri).
8. CATATAN (tidak menggagalkan): gap firewall & gap volume sandbox.

## 6. GAP / REKOMENDASI (untuk bjorn-v2 / tesla — bukan diperbaiki audit)

1. **[GAP #1 — pkexec prompt]** `firewall_status()`/`_firewall_tool()`
   tidak di-stub safe_harness; di mesin ber-ufw tanpa root, `test_e2e.py`
   (`test_linux_layer`) memicu `pkexec --disable-internal-agent ufw status`
   → prompt grafis di desktop. **Bukti**: guard minimal mencatat
   `BLOKIR-PROMPT: pkexec --disable-internal-agent ufw status` saat
   test_e2e jalan. **Reproduksi**: mesin dengan `ufw` terpasang (non-root),
   jalankan `python3 tests/test_e2e.py` → dialog otentikasi pkexec muncul.
   **Rekomendasi**: tambahkan stub `firewall_status`/`_firewall_tool`/
   `fix_firewall` ke `safe_harness.activate()` (pola sama dengan yang lain);
   pertimbangkan juga stub di mode `--sandbox`.
2. **[GAP #2 — injeksi input nyata (laten)]** `safe_harness` dan mode
   `--sandbox` tidak men-stub backend input (`init_backend`/`mouse_*`/
   `press_key`/`type_text`). Di mesin dev dengan `evdev` terpasang
   (requirements.txt), `init_backend()` memilih UinputBackend dan test_e2e
   lama menggerakkan kursor/menekan tombol sungguhan. Di mesin audit ini
   tidak termanifestasi karena `evdev` tidak terpasang. **Reproduksi**:
   `pip install evdev` lalu jalankan test_e2e versi lama → perangkat virtual
   `CLAUDEPAD Virtual Pointer/Keyboard` dibuat dan input nyata dikirim.
   **Rekomendasi**: safe_harness/sandbox memaksa backend `none`
   (stub `init_backend` atau set `BACKEND=_NullBackend`) di jalur test.
3. **[GAP #3 — volume di sandbox]** mode `--sandbox` hanya men-stub
   radio/power/bright; `volume_set`/`volume_mute_toggle` masih menyentuh
   `wpctl/pactl/amixer` nyata. **Reproduksi**: jalankan `--sandbox`, kirim
   WS `{"t":"volset","v":50}` → volume berubah sungguhan.
   **Rekomendasi**: tambahkan cabang `SANDBOX` di `volume_set`/
   `volume_mute_toggle` (atau stub lewat safe_harness saat sandbox aktif).
4. **[GAP #4 — input di test_input_x11]** test_input_x11 menjalankan injeksi
   input sungguhan — aman karena di Xvfb, tetapi pastikan CI selalu
   menyediakan Xvfb terisolasi; jangan pernah dijalankan terhadap `:0`.
5. **[SARAN]** CI: jalankan `test_safety.py` sebagai gerbang wajib sebelum
   `test_e2e.py`; gunakan `--sandbox` untuk uji jalur penuh.
6. **[SARAN]** `safe_harness.restore()` dipanggil test_safety di akhir;
   pastikan test lain tidak bergantung pada state harness antar-proses.

## 7. CATATAN PROSES AUDIT

- Tidak ada file yang diubah tesla yang diedit oleh audit.
- Tidak ada aksi sistem nyata yang dijalankan selama audit; semua verifikasi
  memakai guard (blok subprocess) atau mode sandbox.
- File baru audit: `server/tests/test_safety.py`, `server/tests/AUDIT-SAFETY.md`.
