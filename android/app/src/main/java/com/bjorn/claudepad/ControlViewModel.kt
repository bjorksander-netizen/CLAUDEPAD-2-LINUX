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
import org.json.JSONObject

/**
 * ViewModel untuk [ControlActivity].
 *
 * Mengelola semua state UI layar kendali:
 * - Status koneksi (nama host, transport)
 * - Latensi ping
 * - Status reconnecting
 * - Volume (termasuk fallback ke stepped mode)
 * - Pesan dari server (power_result, radio_result)
 */
class ControlViewModel(application: Application) : AndroidViewModel(application) {

    private val repo = ConnectionRepository.getInstance()

    // ──────────────────────────── Connection state ───────────────────────

    /** Status koneksi — dikoleksi Activity untuk navigasi & pesan. */
    val connectionState: StateFlow<WsClient.ConnectionState> = repo.connectionState

    /** Info koneksi (host, transport, version, dll). */
    val connectionInfo: StateFlow<WsClient.ConnectionInfo> = repo.connectionInfo

    /** Latensi ping. */
    val pingMs: StateFlow<Int> = repo.pingMs

    /** Sedang reconnecting (retry count, null = tidak). */
    val reconnectingTo: StateFlow<Int?> = repo.reconnectingTo

    /** Nama host PC. */
    val hostName: String get() = repo.hostName

    /** Transport yang dipakai. */
    val transport: String get() = repo.transport

    /** Apakah terhubung. */
    val isConnected: Boolean get() = repo.isConnected

    /** Informasi scroll window aktif. */
    val scrollInfo: StateFlow<ScrollInfo?> = repo.scrollInfo

    /** v3.7: info lagu yang sedang diputar di PC. */
    val nowPlaying: StateFlow<WsClient.NowPlaying> = repo.nowPlaying

    /** v3.7: status clipboard di PC. */
    val clipboardContent: StateFlow<WsClient.ClipboardState> = repo.clipboardContent

    // ──────────────────────────── Volume state ───────────────────────────

    /** Volume terkini. */
    private val _volume = MutableStateFlow(50)
    val volume: StateFlow<Int> = _volume.asStateFlow()

    /** Apakah server mendukung volume absolut (pycaw). */
    private val _absVolume = MutableStateFlow(true)
    val absVolume: StateFlow<Boolean> = _absVolume.asStateFlow()

    /** Toast untuk error volume. */
    private val _volumeError = MutableStateFlow<String?>(null)
    val volumeError: StateFlow<String?> = _volumeError.asStateFlow()

    /** Timestamp pengiriman volume terakhir (untuk throttling). */
    private var lastVolSent = -1
    private var lastVolTime = 0L
    private var volErrToasted = false

    // ──────────────────────────── Server messages ────────────────────────

    /** Toast dari server (power_result, radio_result). */
    private val _toastMessage = MutableStateFlow<String?>(null)
    val toastMessage: StateFlow<String?> = _toastMessage.asStateFlow()

    /** Level haptic untuk toast (medium = ok, light = gagal). */
    private val _toastHapticOk = MutableStateFlow(true)
    val toastHapticOk: StateFlow<Boolean> = _toastHapticOk.asStateFlow()

    // ──────────────────────────── Init ───────────────────────────────────

    init {
        // Inisialisasi volume dari info koneksi
        viewModelScope.launch {
            connectionInfo.collect { info ->
                if (_volume.value == 50 && info.volume != 50) {
                    _volume.value = info.volume
                }
            }
        }

        // Dengarkan pesan dari server
        viewModelScope.launch {
            repo.serverMessages.collect { msg ->
                handleServerMessage(msg)
            }
        }

        // Dengarkan perubahan token
        viewModelScope.launch {
            repo.newToken.collect { token ->
                val context = getApplication<Application>()
                Prefs.setToken(context, token)
            }
        }

        // Dengarkan MAC address
        viewModelScope.launch {
            connectionInfo.collect { info ->
                if (info.macAddress.isNotEmpty()) {
                    val context = getApplication<Application>()
                    Prefs.setMac(context, info.macAddress)
                }
            }
        }

        // Request volume dari server
        repo.volGet()
    }

    // ──────────────────────────── Input commands ─────────────────────────

    fun click(button: String, double: Boolean = false) = repo.click(button, double)
    fun buttonDown(button: String) = repo.buttonDown(button)
    fun buttonUp(button: String) = repo.buttonUp(button)
    fun scroll(dy: Int) = repo.scroll(dy)
    fun scrollHorizontal(dx: Int) = repo.scrollHorizontal(dx)
    fun zoom(dir: Int) = repo.zoom(dir)
    fun gesture(name: String) = repo.gesture(name)
    fun text(s: String) = repo.text(s)
    fun key(k: String, mods: List<String> = emptyList()) = repo.key(k, mods)
    fun move(dx: Int, dy: Int) = repo.move(dx, dy)

    // ──────────────────────────── Media commands ─────────────────────────

    fun media(action: String) = repo.media(action)

    // ──────────────────────────── v3.7: now playing ──────────────────────

    /** Minta info lagu yang sedang diputar di PC. */
    fun npGet() = repo.npGet()

    /** Lompat ke posisi [posUs] pada pemutar PC. */
    fun npSeek(posUs: Long) = repo.npSeek(posUs)

    fun setVolume(v: Int) {
        val now = System.currentTimeMillis()
        if (v != lastVolSent && now - lastVolTime >= 40L) {
            sendVolumeInternal(v)
        }
    }

    fun commitVolume(v: Int) {
        _volume.value = v
        repo.volSet(v)
        lastVolSent = v
    }

    // ──────────────────────────── System commands ────────────────────────

    fun radio(device: String) = repo.radio(device)
    fun power(action: String) = repo.power(action)
    fun measurePing() = repo.measurePing()

    // ──────────────────────────── Connection commands ────────────────────

    fun disconnect() = repo.disconnect()

    fun setAutoReconnect(enabled: Boolean) = repo.setAutoReconnect(enabled)

    // ──────────────────────────── Private ────────────────────────────────

    private fun sendVolumeInternal(v: Int) {
        if (_absVolume.value) {
            lastVolSent = v
            lastVolTime = System.currentTimeMillis()
            repo.volSet(v)
        } else {
            val prev = if (lastVolSent < 0) _volume.value else lastVolSent
            val steps = (v - prev) / 2
            if (steps != 0) {
                repeat(kotlin.math.abs(steps)) {
                    repo.media(if (steps > 0) "volup" else "voldown")
                }
                lastVolSent = prev + steps * 2
                lastVolTime = System.currentTimeMillis()
            }
        }
    }

    private fun handleServerMessage(msg: JSONObject) {
        when (msg.optString("t")) {
            "vol" -> {
                if (!msg.isNull("v")) {
                    _volume.value = msg.optInt("v", _volume.value)
                }
            }
            "volerr" -> {
                _absVolume.value = false
                if (!volErrToasted) {
                    volErrToasted = true
                    _volumeError.value = "server tanpa pycaw — slider memakai mode bertingkat"
                }
            }
            "power_result" -> {
                val msgText = msg.optString("msg")
                val ok = msg.optBoolean("ok")
                _toastHapticOk.value = ok
                _toastMessage.value = msgText
            }
            "radio_result" -> {
                val msgText = msg.optString("msg")
                val ok = msg.optBoolean("ok")
                _toastHapticOk.value = ok
                _toastMessage.value = msgText
            }
        }
    }

    /** Toast telah ditampilkan, bersihkan. */
    fun onToastShown() {
        _toastMessage.value = null
    }

    /** Volume error telah ditampilkan. */
    fun onVolumeErrorShown() {
        _volumeError.value = null
    }
}
