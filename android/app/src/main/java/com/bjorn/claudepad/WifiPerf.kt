package com.bjorn.claudepad

import android.content.Context
import android.net.wifi.WifiManager
import android.os.Build

/**
 * Mengunci radio WiFi pada mode performa tinggi selama aplikasi dipakai.
 *
 * Tanpa ini Android menidurkan radio di antara paket untuk menghemat daya.
 * Efeknya terlihat jelas pada log ping pengguna: latensi berselang-seling
 * antara 4–9 ms (radio terjaga) dan 46–59 ms (ongkos membangunkan radio).
 * Jitter seperti itu jauh lebih merusak kehalusan kursor daripada latensi
 * tinggi yang stabil.
 */
object WifiPerf {

    private var lock: WifiManager.WifiLock? = null

    fun acquire(ctx: Context) {
        if (lock?.isHeld == true) return
        try {
            val wm = ctx.applicationContext
                .getSystemService(Context.WIFI_SERVICE) as? WifiManager ?: return
            val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
                WifiManager.WIFI_MODE_FULL_LOW_LATENCY
            else
                @Suppress("DEPRECATION") WifiManager.WIFI_MODE_FULL_HIGH_PERF
            lock = wm.createWifiLock(mode, "claudepad:latency").apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (e: Exception) {
            // perangkat menolak kunci WiFi — aplikasi tetap berjalan normal
        }
    }

    fun release() {
        try {
            lock?.let { if (it.isHeld) it.release() }
        } catch (e: Exception) {
        } finally {
            lock = null
        }
    }
}
