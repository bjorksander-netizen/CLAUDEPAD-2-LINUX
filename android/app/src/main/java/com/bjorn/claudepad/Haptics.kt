package com.bjorn.claudepad

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

/**
 * Getaran bertingkat: kekuatan disesuaikan dengan bobot aksi.
 * TICK   - gerakan halus (scroll, ganti langkah slider)
 * LIGHT  - tap / klik biasa
 * MEDIUM - tombol keyboard, toggle
 * HEAVY  - gesture 3 jari, aksi besar (rotasi, connect)
 */
object Haptics {

    enum class Level(val ms: Long, val amp: Int) {
        TICK(8, 40), LIGHT(14, 90), MEDIUM(22, 150), HEAVY(34, 230)
    }

    var enabled = true

    /** Pengali kekuatan dari setting (0.0..2.0). */
    var strength = 1.0f

    private var vib: Vibrator? = null

    fun init(ctx: Context) {
        vib = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val mgr = ctx.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
            mgr?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            ctx.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        }
        enabled = Prefs.hapticEnabled(ctx)
        strength = Prefs.hapticStrength(ctx)
    }

    fun fire(level: Level) {
        if (!enabled || strength <= 0.05f) return
        val v = vib ?: return
        if (!v.hasVibrator()) return
        val ms = (level.ms * strength).toLong().coerceIn(4L, 120L)
        val amp = (level.amp * strength).toInt().coerceIn(1, 255)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                v.vibrate(VibrationEffect.createOneShot(ms, amp))
            } else {
                @Suppress("DEPRECATION")
                v.vibrate(ms)
            }
        } catch (e: Exception) {
            // perangkat tanpa vibrator / izin dicabut - abaikan
        }
    }

    fun tick() = fire(Level.TICK)
    fun light() = fire(Level.LIGHT)
    fun medium() = fire(Level.MEDIUM)
    fun heavy() = fire(Level.HEAVY)
}
