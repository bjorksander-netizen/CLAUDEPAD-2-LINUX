package com.bjorn.claudepad

import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.File
import android.os.Bundle
import android.view.View
import android.widget.SeekBar
import android.widget.TextView
import androidx.activity.viewModels
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.launch

/**
 * Halaman pengaturan.
 *
 * Arsitektur:
 * - [SettingsViewModel] mengelola state koneksi.
 * - Prefs tetap diakses langsung untuk setting lokal (haptic, sensitivity, dll).
 * - UI binding tetap di Activity karena settings adalah UI-heavy.
 */
class SettingsActivity : AppCompatActivity() {

    private val vm: SettingsViewModel by viewModels()

    companion object {
        const val README_URL =
            "https://github.com/bjorksander-netizen/CLAUDEPAD-2-LINUX#readme"

        val GESTURE_GUIDE = """
            1 jari geser         gerakkan kursor
            1 jari tap           klik kiri
            2 jari tap           klik kanan
            3 jari tap           klik tengah
            2 jari geser tegak   scroll atas/bawah
            2 jari geser datar   scroll kiri/kanan
            2 jari cubit         zoom (Ctrl + scroll)
            3 jari ke atas       ikhtisar jendela
            3 jari ke bawah      tampilkan desktop
            3 jari kiri/kanan    ganti aplikasi
            tap 2x lalu tahan    drag & drop

            Di PC Linux, ketiga gestur itu dipetakan ke pintasan desktop
            yang kamu pakai (GNOME, KDE, XFCE, Cinnamon). Kalau pintasannya
            berbeda, ubah di PC pada berkas
            ~/.config/claudepad/gestures.json — tanpa perlu build ulang APK.

            Sumbu scroll dikunci setelah arah dominan terdeteksi,
            jadi gulungan tidak berpindah arah di tengah jalan.

            Tombol orientasi memutar seluruh tampilan (0°, 90°, 270°).
            Arah gestur selalu mengikuti layar apa adanya — geser ke atas
            berarti kursor ke atas, di orientasi mana pun.
        """.trimIndent()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)
        Haptics.init(this)
        Glass.apply(this, findViewById(R.id.rootSettings))
        // v3.7: siapkan sinkronisasi clipboard (idempoten)
        ClipboardSync.init(this)

        bindConnectionInfo()
        bindToggles()
        bindSensitivity()
        bindPower()
        bindMacros()
        bindPingLog()
        bindAbout()

        findViewById<TextView>(R.id.btnBack).setOnClickListener {
            Haptics.light()
            finish()
        }
        findViewById<TextView>(R.id.btnDisconnect).setOnClickListener {
            Haptics.heavy()
            vm.disconnect()
            val i = Intent(this, MainActivity::class.java)
            i.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
            startActivity(i)
            finish()
        }

        Fonts.apply(findViewById(R.id.rootSettings))
    }

    override fun onResume() {
        super.onResume()
        bindConnectionInfo()
    }

    // ──────────────────────────── Connection info ────────────────────────

    private fun bindConnectionInfo() {
        val connected = vm.isConnected
        val info = vm.connectionInfo
        findViewById<TextView>(R.id.tvConnStatus).apply {
            text = if (connected) "terhubung" else "terputus"
            setTextColor(getColor(if (connected) R.color.green else R.color.red))
        }
        findViewById<TextView>(R.id.tvTransport).text =
            if (!connected) "—" else when (info.transport) {
                "usb" -> "kabel usb"
                "wifi" -> "wifi / hotspot"
                else -> info.transport
            }
        findViewById<TextView>(R.id.tvHost).text = if (connected) info.hostName else "—"
        findViewById<TextView>(R.id.tvServerVer).text =
            if (connected) "v${info.serverVersion}" else "—"
        findViewById<TextView>(R.id.tvSystem).text =
            if (connected) info.systemLabel() else "—"

        // Backend input hanya relevan di PC Linux; di Windows barisnya
        // disembunyikan supaya tidak menampilkan baris kosong.
        val inputRow = findViewById<View>(R.id.rowInputBackend)
        val backend = info.inputBackend
        if (connected && backend.isNotEmpty()) {
            inputRow.visibility = View.VISIBLE
            findViewById<TextView>(R.id.tvInputBackend).apply {
                text = when (backend) {
                    "uinput" -> "uinput (wayland & x11)"
                    "xtest", "xdotool" -> "$backend (hanya x11)"
                    "none" -> "tidak aktif"
                    else -> backend
                }
                setTextColor(getColor(
                    if (backend == "none") R.color.red else R.color.text_muted))
            }
        } else {
            inputRow.visibility = View.GONE
        }
    }

    // ──────────────────────────── Toggles ────────────────────────────────

    private fun toggleRow(rowId: Int, labelId: Int, get: () -> Boolean, set: (Boolean) -> Unit,
                          onText: String = "aktif", offText: String = "nonaktif") {
        val label = findViewById<TextView>(labelId)
        fun render() { label.text = if (get()) onText else offText }
        render()
        findViewById<View>(rowId).setOnClickListener {
            set(!get())
            Haptics.medium()
            render()
        }
    }

    private fun bindToggles() {
        toggleRow(R.id.rowHaptic, R.id.tvHaptic,
            { Prefs.hapticEnabled(this) },
            { v -> Prefs.setHaptic(this, v); Haptics.enabled = v })

        toggleRow(R.id.rowNatural, R.id.tvNatural,
            { Prefs.naturalScroll(this) },
            { v -> Prefs.setNaturalScroll(this, v) })

        toggleRow(R.id.rowAwake, R.id.tvAwake,
            { Prefs.keepAwake(this) },
            { v -> Prefs.setKeepAwake(this, v) })

        toggleRow(R.id.rowAutoReconnect, R.id.tvAutoReconnect,
            { Prefs.autoReconnect(this) },
            { v -> Prefs.setAutoReconnect(this, v); vm.setAutoReconnect(v) })

        // v3.7: sinkron clipboard otomatis — saat berubah & terhubung,
        // ClipboardSync yang mengirim clipSync(on) ke server.
        toggleRow(R.id.rowClipAuto, R.id.tvClipAuto,
            { Prefs.clipAuto(this) },
            { v -> Prefs.setClipAuto(this, v); ClipboardSync.setEnabled(v) })

        findViewById<View>(R.id.rowShowNotif).setOnClickListener {
            Haptics.medium()
            RemoteService.start(this)
            toast("notifikasi kontrol ditampilkan")
        }

        findViewById<TextView>(R.id.tvPairState).text =
            if (Prefs.token(this).isEmpty()) "belum dipasangkan" else "tersimpan"
        findViewById<View>(R.id.rowForgetPair).setOnClickListener {
            Haptics.medium()
            AlertDialog.Builder(this)
                .setTitle("lupakan pemasangan")
                .setMessage("PIN akan diminta lagi saat menyambung berikutnya.")
                .setPositiveButton("lupakan") { _, _ ->
                    vm.clearToken()
                    findViewById<TextView>(R.id.tvPairState).text = "belum dipasangkan"
                }
                .setNegativeButton("batal", null)
                .show()
        }

        toggleRow(R.id.rowShowTaps, R.id.tvShowTaps,
            { Prefs.showTaps(this) },
            { v -> Prefs.setShowTaps(this, v) })

        toggleRow(R.id.rowPointerLoc, R.id.tvPointerLoc,
            { Prefs.pointerLocation(this) },
            { v -> Prefs.setPointerLocation(this, v) })

        bindRotationRow()
    }

    private fun bindRotationRow() {
        val label = findViewById<TextView>(R.id.tvOrientation)
        fun render() {
            val deg = Prefs.inputRotation(this)
            label.text = if (deg == 0) "normal" else "diputar ${deg}°"
        }
        render()
        findViewById<View>(R.id.rowOrientation).setOnClickListener {
            Haptics.medium()
            Prefs.setInputRotation(this, Prefs.nextRotation(Prefs.inputRotation(this)))
            render()
        }
    }

    // ──────────────────────────── Sensitivity ────────────────────────────

    private fun bindSensitivity() {
        val tv = findViewById<TextView>(R.id.tvSens)
        val seek = findViewById<SeekBar>(R.id.seekSens)
        fun toSens(p: Int) = 0.5f + p / 10f
        val current = Prefs.sensitivity(this)
        seek.progress = ((current - 0.5f) * 10f).toInt().coerceIn(0, 40)
        tv.text = String.format("%.1fx", current)

        seek.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, p: Int, fromUser: Boolean) {
                val s = toSens(p)
                tv.text = String.format("%.1fx", s)
                if (fromUser) {
                    Prefs.setSensitivity(this@SettingsActivity, s)
                    Haptics.tick()
                }
            }
            override fun onStartTrackingTouch(sb: SeekBar?) {}
            override fun onStopTrackingTouch(sb: SeekBar?) { Haptics.light() }
        })

        // ---- blur background ----
        val tvBlur = findViewById<TextView>(R.id.tvBlur)
        val seekBlur = findViewById<SeekBar>(R.id.seekBlur)
        seekBlur.progress = Prefs.blurIntensity(this)
        tvBlur.text = "${seekBlur.progress}%"
        seekBlur.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, p: Int, fromUser: Boolean) {
                tvBlur.text = "$p%"
                if (fromUser) {
                    Prefs.setBlurIntensity(this@SettingsActivity, p)
                    Glass.apply(this@SettingsActivity, findViewById(R.id.rootSettings))
                }
            }
            override fun onStartTrackingTouch(sb: SeekBar?) {}
            override fun onStopTrackingTouch(sb: SeekBar?) { Haptics.light() }
        })

        // ---- kekuatan haptic ----
        val tvH = findViewById<TextView>(R.id.tvHapticStr)
        val seekH = findViewById<SeekBar>(R.id.seekHaptic)
        seekH.progress = (Prefs.hapticStrength(this) * 100).toInt().coerceIn(0, 200)
        tvH.text = "${seekH.progress}%"
        seekH.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, p: Int, fromUser: Boolean) {
                tvH.text = "$p%"
                if (fromUser) {
                    val str = p / 100f
                    Prefs.setHapticStrength(this@SettingsActivity, str)
                    Haptics.strength = str
                    Haptics.medium()
                }
            }
            override fun onStartTrackingTouch(sb: SeekBar?) {}
            override fun onStopTrackingTouch(sb: SeekBar?) {}
        })
    }

    // ──────────────────────────── Power ──────────────────────────────────

    private fun bindPower() {
        findViewById<View>(R.id.rowPower).setOnClickListener { anchor ->
            Haptics.medium()
            if (!vm.isConnected) {
                toast("belum terhubung ke pc")
                return@setOnClickListener
            }
            showPowerPopup(anchor)
        }

        val wolLabel = findViewById<TextView>(R.id.tvWol)
        findViewById<View>(R.id.rowWol).setOnClickListener {
            Haptics.medium()
            val mac = Prefs.mac(this).ifEmpty { WsClient.macAddress }
            if (mac.isEmpty()) {
                showText("wake-on-lan (eksperimental)",
                    "Alamat MAC PC belum diketahui.\n\n" +
                    "Sambungkan sekali ke PC lewat WiFi supaya aplikasi " +
                    "dapat mencatat alamatnya, lalu coba lagi.")
                return@setOnClickListener
            }
            AlertDialog.Builder(this)
                .setTitle("wake-on-lan (eksperimental)")
                .setMessage("Kirim sinyal penyalaan ke $mac?\n\n" +
                    "Fitur ini eksperimental. Agar berhasil, Wake-on-LAN harus " +
                    "diaktifkan di BIOS/UEFI dan pada adapter jaringan PC " +
                    "(di Linux: ethtool -s <iface> wol g), serta HP harus " +
                    "berada di jaringan yang sama dengan PC. Umumnya hanya " +
                    "bekerja lewat kabel LAN — banyak adapter WiFi tidak " +
                    "mendukungnya.\n\n" +
                    "Catatan: menyalakan PC lewat kabel USB dari HP tidak bisa " +
                    "dilakukan. Android tidak mengizinkan aplikasi menyamar " +
                    "sebagai perangkat USB pembangun daya.")
                .setPositiveButton("kirim") { _, _ ->
                    Thread {
                        val res = WakeOnLan.send(mac)
                        runOnUiThread {
                            wolLabel.text = if (res.isSuccess) "sinyal terkirim" else "gagal"
                            toast(if (res.isSuccess)
                                "sinyal terkirim — tunggu beberapa detik"
                            else "gagal: ${res.exceptionOrNull()?.message}")
                        }
                    }.start()
                }
                .setNegativeButton("batal", null)
                .show()
        }
    }

    private fun showPowerPopup(anchor: View) {
        val d = resources.displayMetrics.density
        val content = layoutInflater.inflate(R.layout.popup_power, null)
        Fonts.apply(content)

        val popup = android.widget.PopupWindow(content,
            (230 * d).toInt(),
            android.view.WindowManager.LayoutParams.WRAP_CONTENT, true)
        popup.elevation = 24f

        val info = vm.connectionInfo

        fun act(id: Int, label: String, action: String, confirm: Boolean) {
            val view = content.findViewById<View>(id)
            // Server Linux melaporkan aksi mana yang benar-benar bisa
            // dijalankan (mis. hibernasi sering dimatikan). Yang tidak
            // didukung diredupkan, bukan dibiarkan gagal diam-diam.
            if (!info.supportsPower(action)) {
                view.alpha = 0.35f
                view.setOnClickListener {
                    Haptics.light()
                    toast("$label tidak didukung pc ini")
                }
                return
            }
            view.setOnClickListener {
                Haptics.medium()
                if (confirm) {
                    popup.dismiss()
                    AlertDialog.Builder(this)
                        .setTitle(label)
                        .setMessage("Yakin ingin $label? Pekerjaan yang belum " +
                                    "disimpan di PC bisa hilang.")
                        .setPositiveButton("lanjutkan") { _, _ -> vm.power(action) }
                        .setNegativeButton("batal", null)
                        .show()
                } else {
                    vm.power(action)
                    popup.dismiss()
                }
            }
        }
        act(R.id.pShutdown, "matikan pc", "shutdown", true)
        act(R.id.pRestart, "mulai ulang pc", "restart", true)
        act(R.id.pSleep, "tidurkan pc", "sleep", false)
        act(R.id.pHibernate, "hibernasi pc", "hibernate", false)
        act(R.id.pLogoff, "keluar sesi", "logoff", true)

        content.measure(
            View.MeasureSpec.makeMeasureSpec((230 * d).toInt(), View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED))
        popup.showAsDropDown(anchor, 0, (8 * d).toInt())
    }

    private fun toast(s: String) =
        android.widget.Toast.makeText(this, s, android.widget.Toast.LENGTH_SHORT).show()

    // ──────────────────────────── Macros ─────────────────────────────────

    private fun bindMacros() {
        refreshMacroCount()
        findViewById<View>(R.id.rowMacros).setOnClickListener {
            Haptics.medium()
            showMacroManager()
        }
    }

    private fun refreshMacroCount() {
        findViewById<TextView>(R.id.tvMacroCount).text =
            "${Macros.all(this).size}/${Macros.MAX}"
    }

    private fun showMacroManager() {
        val list = Macros.all(this)
        val items = list.map { "${it.label.ifEmpty { it.key }}  ·  ${it.combo()}" }
            .toMutableList()
        val canAdd = list.size < Macros.MAX
        if (canAdd) items.add("+ tambah makro")

        AlertDialog.Builder(this)
            .setTitle("tombol makro (${list.size}/${Macros.MAX})")
            .setItems(items.toTypedArray()) { _, which ->
                if (canAdd && which == items.size - 1) {
                    showMacroEditor()
                } else {
                    AlertDialog.Builder(this)
                        .setTitle(list[which].combo())
                        .setMessage("Hapus makro ini?")
                        .setPositiveButton("hapus") { _, _ ->
                            Macros.removeAt(this, which)
                            refreshMacroCount()
                        }
                        .setNegativeButton("batal", null)
                        .show()
                }
            }
            .setNegativeButton("tutup", null)
            .show()
    }

    private fun showMacroEditor() {
        val view = layoutInflater.inflate(R.layout.dialog_macro, null)
        val etLabel = view.findViewById<android.widget.EditText>(R.id.etLabel)
        val etKey = view.findViewById<android.widget.EditText>(R.id.etKey)
        val cbCtrl = view.findViewById<android.widget.CheckBox>(R.id.cbCtrl)
        val cbShift = view.findViewById<android.widget.CheckBox>(R.id.cbShift)
        val cbAlt = view.findViewById<android.widget.CheckBox>(R.id.cbAlt)
        val cbWin = view.findViewById<android.widget.CheckBox>(R.id.cbWin)

        AlertDialog.Builder(this)
            .setTitle("makro baru")
            .setView(view)
            .setPositiveButton("simpan") { _, _ ->
                val key = etKey.text.toString().trim().lowercase()
                if (key.isEmpty()) {
                    toast("tombol utama tidak boleh kosong")
                    return@setPositiveButton
                }
                val label = etLabel.text.toString().trim()
                Macros.add(this, Macros.Macro(
                    if (label.isEmpty()) key.uppercase() else label,
                    key, cbCtrl.isChecked, cbShift.isChecked,
                    cbAlt.isChecked, cbWin.isChecked))
                refreshMacroCount()
                toast("makro disimpan")
            }
            .setNegativeButton("batal", null)
            .show()
    }

    // ──────────────────────────── Ping log ───────────────────────────────

    private fun bindPingLog() {
        findViewById<TextView>(R.id.tvPingLog).text = PingLog.summary()

        findViewById<View>(R.id.rowPingView).setOnClickListener {
            Haptics.light()
            showText("laporan ping", PingLog.report(this))
        }

        findViewById<View>(R.id.rowPingShare).setOnClickListener {
            Haptics.medium()
            sharePingLog()
        }

        findViewById<View>(R.id.rowPingClear).setOnClickListener {
            Haptics.medium()
            AlertDialog.Builder(this)
                .setTitle("hapus rekaman")
                .setMessage("Semua data ping yang tersimpan akan dihapus.")
                .setPositiveButton("hapus") { _, _ ->
                    PingLog.clear()
                    findViewById<TextView>(R.id.tvPingLog).text = PingLog.summary()
                }
                .setNegativeButton("batal", null)
                .show()
        }
    }

    private fun sharePingLog() {
        if (PingLog.size() == 0) {
            android.widget.Toast.makeText(this,
                "belum ada data ping — hubungkan lewat wifi dulu",
                android.widget.Toast.LENGTH_SHORT).show()
            return
        }
        try {
            val dir = File(cacheDir, "logs").apply { mkdirs() }
            val stamp = java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.US)
                .format(java.util.Date())
            val file = File(dir, "claudepad-ping-$stamp.txt")
            file.writeText(PingLog.report(this))

            val uri = FileProvider.getUriForFile(
                this, "$packageName.fileprovider", file)

            val send = Intent(Intent.ACTION_SEND).apply {
                type = "text/plain"
                putExtra(Intent.EXTRA_STREAM, uri)
                putExtra(Intent.EXTRA_SUBJECT, "CLAUDEPAD — log ping")
                putExtra(Intent.EXTRA_TEXT, PingLog.summary())
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(send, "bagikan log ping"))
        } catch (e: Exception) {
            showText("gagal membagikan", "Tidak bisa menyimpan berkas log.\n\n${e.message}")
        }
    }

    // ──────────────────────────── About ──────────────────────────────────

    private fun bindAbout() {
        val version = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: "—"
        } catch (e: Exception) { "—" }
        findViewById<TextView>(R.id.tvVersion).text = "v$version"

        findViewById<View>(R.id.rowDiagnose).setOnClickListener {
            Haptics.medium()
            runDiagnostic()
        }
        findViewById<View>(R.id.rowGesture).setOnClickListener {
            Haptics.light()
            showText("panduan gesture", GESTURE_GUIDE)
        }
        findViewById<View>(R.id.rowHelp).setOnClickListener {
            Haptics.light()
            try {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(README_URL)))
            } catch (e: Exception) {
                showText("bantuan", "Tidak ada browser.\n\nBuka manual:\n$README_URL")
            }
        }
    }

    private fun runDiagnostic() {
        val dlg = AlertDialog.Builder(this)
            .setTitle("diagnosa koneksi")
            .setMessage("menjalankan pemeriksaan…")
            .setCancelable(false)
            .create()
        dlg.show()
        val ip = Prefs.ip(this)
        Thread {
            val report = try {
                Diagnostic.run(this, ip)
            } catch (e: Exception) {
                "Diagnosa gagal: ${e.message}"
            }
            runOnUiThread {
                dlg.dismiss()
                AlertDialog.Builder(this)
                    .setTitle("diagnosa koneksi")
                    .setMessage(report)
                    .setPositiveButton("tutup", null)
                    .setNeutralButton("salin") { _, _ ->
                        val cm = getSystemService(CLIPBOARD_SERVICE)
                            as android.content.ClipboardManager
                        cm.setPrimaryClip(
                            android.content.ClipData.newPlainText("diagnosa", report))
                        android.widget.Toast.makeText(this, "laporan disalin",
                            android.widget.Toast.LENGTH_SHORT).show()
                    }
                    .show()
            }
        }.start()
    }

    private fun showText(title: String, body: String) {
        AlertDialog.Builder(this)
            .setTitle(title)
            .setMessage(body)
            .setPositiveButton("tutup", null)
            .show()
    }
}
