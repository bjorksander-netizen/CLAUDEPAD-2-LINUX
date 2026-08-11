package com.bjorn.claudepad

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import kotlinx.coroutines.flow.StateFlow

/**
 * ViewModel untuk [SettingsActivity].
 *
 * Ringan — hanya menyediakan akses ke state koneksi
 * dan delegasi perintah ke ConnectionRepository.
 */
class SettingsViewModel(application: Application) : AndroidViewModel(application) {

    private val repo = ConnectionRepository.getInstance()

    /** Status koneksi. */
    val connectionState: StateFlow<WsClient.ConnectionState> = repo.connectionState

    /** Apakah terhubung. */
    val isConnected: Boolean get() = repo.isConnected

    /** Info koneksi. */
    val connectionInfo: WsClient.ConnectionInfo get() = repo.connectionInfo.value

    /** Putuskan koneksi. */
    fun disconnect() = repo.disconnect()

    /** Atur auto-reconnect. */
    fun setAutoReconnect(enabled: Boolean) = repo.setAutoReconnect(enabled)

    /** Kirim aksi daya ke PC. */
    fun power(action: String) = repo.power(action)

    /** Simpan token. */
    fun clearToken() {
        val context = getApplication<Application>()
        Prefs.setToken(context, "")
    }
}
