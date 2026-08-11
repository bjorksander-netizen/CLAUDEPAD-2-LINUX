package com.bjorn.claudepad

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Penyimpanan setting sederhana.
 * v3.2: Token disimpan di EncryptedSharedPreferences (enkripsi at-rest).
 */
object Prefs {
    private const val NAME = "claudepad"
    private const val SECURE_NAME = "claudepad_secure"

    private fun sp(ctx: Context): SharedPreferences =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    /** EncryptedSharedPreferences untuk data sensitif (token pairing). */
    private fun secureSp(ctx: Context): SharedPreferences {
        val masterKey = MasterKey.Builder(ctx)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        return EncryptedSharedPreferences.create(
            ctx,
            SECURE_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun hapticEnabled(ctx: Context) = sp(ctx).getBoolean("haptic", true)
    fun setHaptic(ctx: Context, v: Boolean) = sp(ctx).edit().putBoolean("haptic", v).apply()

    /**
     * Rotasi input trackpad dalam derajat: 0, 90, atau 270.
     * Hanya arah input yang berputar — layout tidak berubah sama sekali.
     */
    fun inputRotation(ctx: Context): Int {
        val v = sp(ctx).getInt("input_rotation", -1)
        if (v in intArrayOf(0, 90, 270)) return v
        // migrasi dari setting lama yang masih boolean
        val legacy = try { sp(ctx).getBoolean("input_rotated", false) } catch (e: Exception) { false }
        return if (legacy) 90 else 0
    }

    fun setInputRotation(ctx: Context, deg: Int) =
        sp(ctx).edit().putInt("input_rotation", if (deg in intArrayOf(0, 90, 270)) deg else 0).apply()

    /** Urutan siklus tombol rotasi: 0 -> 90 -> 270 -> 0. */
    fun nextRotation(cur: Int) = when (cur) {
        0 -> 90
        90 -> 270
        else -> 0
    }

    fun sensitivity(ctx: Context) = sp(ctx).getFloat("sens", 1.4f)
    fun setSensitivity(ctx: Context, v: Float) = sp(ctx).edit().putFloat("sens", v).apply()

    fun naturalScroll(ctx: Context) = sp(ctx).getBoolean("natscroll", false)
    fun setNaturalScroll(ctx: Context, v: Boolean) = sp(ctx).edit().putBoolean("natscroll", v).apply()

    /** Intensitas blur/frost background, 0..100. */
    fun blurIntensity(ctx: Context) = sp(ctx).getInt("blur", 55)
    fun setBlurIntensity(ctx: Context, v: Int) = sp(ctx).edit().putInt("blur", v).apply()

    /** Kekuatan haptic, 0.0..2.0 (1.0 = normal, 0 = sama dengan mati). */
    fun hapticStrength(ctx: Context) = sp(ctx).getFloat("haptic_str", 1.0f)
    fun setHapticStrength(ctx: Context, v: Float) = sp(ctx).edit().putFloat("haptic_str", v).apply()

    /** Garis bidik + koordinat jari di trackpad. Default MATI. */
    fun pointerLocation(ctx: Context) = sp(ctx).getBoolean("pointer_loc", false)
    fun setPointerLocation(ctx: Context, v: Boolean) =
        sp(ctx).edit().putBoolean("pointer_loc", v).apply()

    /** Lingkaran umpan balik saat menyentuh trackpad. Default NYALA. */
    fun showTaps(ctx: Context) = sp(ctx).getBoolean("show_taps", true)
    fun setShowTaps(ctx: Context, v: Boolean) =
        sp(ctx).edit().putBoolean("show_taps", v).apply()

    /** Token perangkat tepercaya — supaya PIN tidak perlu diketik ulang. */
    fun token(ctx: Context): String {
        // Migrasi: baca dari storage lama jika ada, lalu pindah ke encrypted
        val legacy = sp(ctx).getString("token", "") ?: ""
        if (legacy.isNotEmpty()) {
            secureSp(ctx).edit().putString("token", legacy).apply()
            sp(ctx).edit().remove("token").apply()
            return legacy
        }
        return secureSp(ctx).getString("token", "") ?: ""
    }
    fun setToken(ctx: Context, v: String) =
        secureSp(ctx).edit().putString("token", v).apply()

    /** MAC PC terakhir, dipakai Wake-on-LAN (eksperimental). */
    fun mac(ctx: Context): String = sp(ctx).getString("mac", "") ?: ""
    fun setMac(ctx: Context, v: String) = sp(ctx).edit().putString("mac", v).apply()

    fun autoReconnect(ctx: Context) = sp(ctx).getBoolean("auto_reconnect", true)
    fun setAutoReconnect(ctx: Context, v: Boolean) =
        sp(ctx).edit().putBoolean("auto_reconnect", v).apply()

    fun keepAwake(ctx: Context) = sp(ctx).getBoolean("awake", true)
    fun setKeepAwake(ctx: Context, v: Boolean) = sp(ctx).edit().putBoolean("awake", v).apply()

    fun ip(ctx: Context): String = sp(ctx).getString("ip", "") ?: ""
    fun setIp(ctx: Context, v: String) = sp(ctx).edit().putString("ip", v).apply()

    fun pin(ctx: Context): String = sp(ctx).getString("pin", "") ?: ""
    fun setPin(ctx: Context, v: String) = sp(ctx).edit().putString("pin", v).apply()
}
