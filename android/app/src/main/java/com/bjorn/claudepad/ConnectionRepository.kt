package com.bjorn.claudepad

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/**
 * Repository sentral untuk semua urusan koneksi.
 *
 * Menjadi **satu-satunya titik akses** ke WsClient bagi ViewModel.
 * Menggabungkan state dari WsClient dengan data dari Prefs menjadi
 * satu StateFlow yang konsisten.
 *
 * Contoh penggunaan di ViewModel:
 * ```
 * val connRepo = ConnectionRepository.getInstance()
 * // collect state
 * connRepo.connectionState.collect { ... }
 * // kirim perintah
 * connRepo.click("left")
 * ```
 */
class ConnectionRepository private constructor() {

    companion object {
        @Volatile
        private var INSTANCE: ConnectionRepository? = null

        fun getInstance(): ConnectionRepository =
            INSTANCE ?: synchronized(this) {
                INSTANCE ?: ConnectionRepository().also { INSTANCE = it }
            }
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    // ──────────────────────────── Derived state ──────────────────────────

    /** Status koneksi — delegasi ke WsClient. */
    val connectionState: StateFlow<WsClient.ConnectionState> = WsClient.connectionState

    /** Info koneksi setelah auth_ok. */
    val connectionInfo: StateFlow<WsClient.ConnectionInfo> = WsClient.connectionInfo

    /** Latensi ping. */
    val pingMs: StateFlow<Int> = WsClient.pingMs

    /** Sedang reconnecting. */
    val reconnectingTo: StateFlow<Int?> = WsClient.reconnectingTo

    /** Apakah terhubung. */
    val isConnected: Boolean get() = WsClient.connected

    /** Nama host. */
    val hostName: String get() = WsClient.hostName

    /** Transport. */
    val transport: String get() = WsClient.transport

    /** Token baru dari server (untuk pairing). */
    val newToken = WsClient.newToken

    /** Pesan dari server (volume, power_result, radio_result, dll). */
    val serverMessages = WsClient.serverMessages

    /** Informasi scroll window aktif (dari server). */
    val scrollInfo: StateFlow<ScrollInfo?> = WsClient.scrollInfo

    // ──────────────────────────── Connection commands ────────────────────

    fun connect(host: String, pin: String, appVersion: String, token: String) {
        WsClient.connect(host, 8765, pin, appVersion, token)
    }

    fun disconnect() {
        WsClient.disconnect()
    }

    fun setAutoReconnect(enabled: Boolean) {
        WsClient.autoReconnect = enabled
    }

    // ──────────────────────────── Input commands ─────────────────────────

    fun click(button: String, double: Boolean = false) = WsClient.click(button, double)
    fun buttonDown(button: String) = WsClient.buttonDown(button)
    fun buttonUp(button: String) = WsClient.buttonUp(button)
    fun scroll(dy: Int) = WsClient.scroll(dy)
    fun scrollHorizontal(dx: Int) = WsClient.scrollHorizontal(dx)
    fun zoom(dir: Int) = WsClient.zoom(dir)
    fun gesture(name: String) = WsClient.gesture(name)
    fun text(s: String) = WsClient.text(s)
    fun key(k: String, mods: List<String> = emptyList()) = WsClient.key(k, mods)
    fun move(dx: Int, dy: Int) = WsClient.move(dx, dy)

    // ──────────────────────────── Media commands ─────────────────────────

    fun media(action: String) = WsClient.media(action)
    fun volSet(v: Int) = WsClient.volSet(v)
    fun volGet() = WsClient.volGet()

    // ──────────────────────────── System commands ────────────────────────

    fun radio(device: String) = WsClient.radio(device)
    fun power(action: String) = WsClient.power(action)
    fun measurePing() = WsClient.measurePing()

    // ──────────────────────────── Prefs shortcuts ────────────────────────

    fun saveToken(context: Context, token: String) = Prefs.setToken(context, token)
    fun saveMac(context: Context, mac: String) = Prefs.setMac(context, mac)
}
