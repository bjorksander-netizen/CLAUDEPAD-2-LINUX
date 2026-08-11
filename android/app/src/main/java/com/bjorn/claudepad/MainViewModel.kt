package com.bjorn.claudepad

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress

/**
 * ViewModel untuk [MainActivity].
 *
 * Mengelola:
 * - Status koneksi (delegasi ke ConnectionRepository)
 * - Input IP & PIN (dua-way binding dengan EditText)
 * - Proses scan jaringan (auto-discovery)
 * - Navigasi ke ControlActivity setelah koneksi berhasil
 */
class MainViewModel(application: Application) : AndroidViewModel(application) {

    private val repo = ConnectionRepository.getInstance()

    // ──────────────────────────── UI state ───────────────────────────────

    /** Status koneksi — dikoleksi oleh Activity untuk update tvStatus. */
    val connectionState: StateFlow<WsClient.ConnectionState> = repo.connectionState

    /** Status scan — "mencari pc di jaringan…", "ketemu: ...", dll. */
    private val _scanStatus = MutableStateFlow("")
    val scanStatus: StateFlow<String> = _scanStatus.asStateFlow()

    /** IP yang diketik pengguna. */
    val ipAddress = MutableStateFlow("")

    /** PIN yang diketik pengguna. */
    val pin = MutableStateFlow("")

    /** Apakah sedang dalam proses menghubungkan. */
    val isConnecting: StateFlow<Boolean> = repo.connectionState
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), false)
        .let { flow ->
            // Convert ConnectionState → Boolean
            MutableStateFlow(false).also { result ->
                viewModelScope.launch {
                    flow.collect { state ->
                        result.value = state is WsClient.ConnectionState.Connecting
                    }
                }
            }
        }

    // ──────────────────────────── Actions ────────────────────────────────

    /**
     * Mulai koneksi ke server.
     * Activity harus observe [connectionState] untuk navigasi ke ControlActivity.
     */
    fun connect() {
        val host = ipAddress.value.trim()
        if (host.isEmpty()) {
            _scanStatus.value = "isi alamat ip dulu, atau tekan cari otomatis"
            return
        }
        val context = getApplication<Application>()
        val pinValue = pin.value.trim()

        Prefs.setIp(context, host)
        Prefs.setPin(context, pinValue)

        _scanStatus.value = if (Prefs.token(context).isEmpty())
            "menghubungkan ke $host…" else "menghubungkan ($host)…"

        val appVersion = try {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "0"
        } catch (e: Exception) { "0" }

        // Simpan token baru saat diterima
        viewModelScope.launch {
            repo.connectionState.collect { state ->
                if (state is WsClient.ConnectionState.Error) {
                    _scanStatus.value = state.message
                }
            }
        }
        viewModelScope.launch {
            repo.newToken.collect { token ->
                Prefs.setToken(context, token)
            }
        }

        repo.connect(host, pinValue, appVersion, Prefs.token(context))
    }

    /**
     * Koneksi via USB (ADB reverse — server di 127.0.0.1).
     */
    fun connectUsb() {
        ipAddress.value = "127.0.0.1"
        connect()
    }

    /**
     * Scan jaringan untuk menemukan PC secara otomatis.
     * Berjalan di background thread, mengupdate [scanStatus].
     */
    fun scan() {
        _scanStatus.value = "mencari pc di jaringan…"
        viewModelScope.launch {
            val result = scanNetwork()
            if (result != null) {
                ipAddress.value = result
                _scanStatus.value = "ketemu: $result"
            } else {
                _scanStatus.value = "tidak ketemu — tekan ⚙ lalu Diagnosa koneksi"
            }
        }
    }

    /**
     * Ambil IP dari Prefs.
     */
    fun loadSavedIp() {
        val context = getApplication<Application>()
        ipAddress.value = Prefs.ip(context)
        pin.value = Prefs.pin(context)
    }

    // ──────────────────────────── Network scan ───────────────────────────

    /**
     * Kirim broadcast UDP ke semua interface untuk menemukan server.
     * Mengembalikan IP server pertama yang menjawab, atau null.
     */
    private suspend fun scanNetwork(): String? = kotlinx.coroutines.withContext(
        kotlinx.coroutines.Dispatchers.IO
    ) {
        var found: String? = null
        val sockets = mutableListOf<DatagramSocket>()
        try {
            val ifaces = Net.interfaces()
            for (i in ifaces) {
                try {
                    val ds = DatagramSocket(null)
                    ds.reuseAddress = true
                    ds.broadcast = true
                    ds.bind(InetSocketAddress(i.address, 0))
                    ds.soTimeout = 700
                    sockets.add(ds)
                } catch (e: Exception) { }
            }
            if (sockets.isEmpty()) {
                sockets.add(DatagramSocket().apply { broadcast = true; soTimeout = 700 })
            }

            val msg = "DISCOVER_CLAUDEPAD".toByteArray()
            val buf = ByteArray(256)

            attempts@ for (attempt in 1..3) {
                for ((idx, ds) in sockets.withIndex()) {
                    val targets = mutableSetOf<InetAddress>()
                    ifaces.getOrNull(idx)?.broadcast?.let { targets.add(it) }
                    try { targets.add(InetAddress.getByName("255.255.255.255")) } catch (e: Exception) {}
                    for (t in targets) {
                        try { ds.send(DatagramPacket(msg, msg.size, t, 8766)) }
                        catch (e: Exception) { }
                    }
                }
                for (ds in sockets) {
                    try {
                        val resp = DatagramPacket(buf, buf.size)
                        ds.receive(resp)
                        val parts = String(resp.data, 0, resp.length).split("|")
                        if (parts.isNotEmpty() && parts[0] == "CLAUDEPAD") {
                            found = resp.address.hostAddress
                            break@attempts
                        }
                    } catch (e: Exception) { }
                }
            }
        } catch (e: Exception) {
        } finally {
            for (ds in sockets) try { ds.close() } catch (e: Exception) {}
        }
        found
    }
}
