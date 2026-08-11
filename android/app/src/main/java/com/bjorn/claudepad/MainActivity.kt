package com.bjorn.claudepad

import android.content.Intent
import android.os.Bundle
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.launch

/**
 * Layar awal: kolom IP, PIN, tombol Hubungkan / USB / Cari / Setting.
 *
 * Arsitektur:
 * - Semua business logic ada di [MainViewModel].
 * - Activity hanya mengikat UI ke state dan merespons event.
 */
class MainActivity : AppCompatActivity() {

    private val vm: MainViewModel by viewModels()
    private lateinit var etIp: EditText
    private lateinit var etPin: EditText
    private lateinit var tvStatus: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        Haptics.init(this)
        Glass.apply(this, findViewById(R.id.rootMain))
        Accent.refresh()
        Accent.applyToKey(findViewById(R.id.btnConnect))

        etIp = findViewById(R.id.etIp)
        etPin = findViewById(R.id.etPin)
        tvStatus = findViewById(R.id.tvStatus)

        // Muat data tersimpan
        vm.loadSavedIp()
        etIp.setText(vm.ipAddress.value)
        etPin.setText(vm.pin.value)

        // ─── Two-way binding: EditText → ViewModel ───
        etIp.addTextChangedListener(object : android.text.TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, st: Int, c: Int, a: Int) {}
            override fun onTextChanged(s: CharSequence?, st: Int, b: Int, c: Int) {}
            override fun afterTextChanged(s: android.text.Editable?) {
                vm.ipAddress.value = s?.toString() ?: ""
            }
        })
        etPin.addTextChangedListener(object : android.text.TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, st: Int, c: Int, a: Int) {}
            override fun onTextChanged(s: CharSequence?, st: Int, b: Int, c: Int) {}
            override fun afterTextChanged(s: android.text.Editable?) {
                vm.pin.value = s?.toString() ?: ""
            }
        })

        // ─── Tombol ───
        findViewById<TextView>(R.id.btnConnect).setOnClickListener {
            Haptics.medium()
            vm.connect()
        }
        findViewById<TextView>(R.id.btnUsb).setOnClickListener {
            Haptics.medium()
            vm.connectUsb()
        }
        findViewById<TextView>(R.id.btnScan).setOnClickListener {
            Haptics.medium()
            vm.scan()
        }
        findViewById<TextView>(R.id.btnSettings).setOnClickListener {
            Haptics.light()
            startActivity(Intent(this, SettingsActivity::class.java))
        }

        // ─── Permission notifikasi (Android 13+) ───
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            if (checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                requestPermissions(
                    arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1)
            }
        }

        Fonts.apply(findViewById(R.id.rootMain))

        // ─── Observe state dari ViewModel ───
        observeState()
    }

    override fun onResume() {
        super.onResume()
        Haptics.enabled = Prefs.hapticEnabled(this)
        // Ambil alih kembali callback dari ControlActivity supaya status
        // koneksi tetap tampil di halaman ini.
        WsClient.onState = { ok, msg ->
            runOnUiThread { tvStatus.text = msg }
        }
        WsClient.onMessage = null

        // Sync EditText dengan ViewModel
        etIp.setText(vm.ipAddress.value)
        etPin.setText(vm.pin.value)
    }

    /**
     * Kumpulkan state dari ViewModel dan update UI.
     * Menggunakan repeatOnLifecycle agar hanya aktif saat Activity visible.
     */
    private fun observeState() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                // ─── Scan status ───
                launch {
                    vm.scanStatus.collect { status ->
                        if (status.isNotEmpty()) {
                            tvStatus.text = status
                        }
                    }
                }

                // ─── Connection state → navigasi ───
                launch {
                    vm.connectionState.collect { state ->
                        when (state) {
                            is WsClient.ConnectionState.Connected -> {
                                Haptics.heavy()
                                RemoteService.start(this@MainActivity)
                                startActivity(Intent(this@MainActivity, ControlActivity::class.java))
                            }
                            is WsClient.ConnectionState.Error -> {
                                Haptics.light()
                                tvStatus.text = state.message
                            }
                            is WsClient.ConnectionState.Connecting -> {
                                // Status sudah di-set oleh scanStatus
                            }
                            is WsClient.ConnectionState.Disconnected -> {
                                // Tidak perlu action khusus di Main
                            }
                        }
                    }
                }
            }
        }
    }
}
