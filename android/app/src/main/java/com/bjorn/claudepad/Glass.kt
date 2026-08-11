package com.bjorn.claudepad

import android.app.Activity
import android.graphics.Color
import android.os.Build
import android.view.View
import android.view.WindowManager

/**
 * Efek kaca di atas wallpaper, dikendalikan slider intensitas (0..100).
 *
 * Dua lapis supaya SELALU terlihat efeknya:
 *  1. Blur asli antar-window (Android 12+, jika vendor mengaktifkannya).
 *  2. Lapisan "frost" — scrim gelap yang ikut menebal bersama intensitas.
 *     Ini jaminan: di perangkat yang mematikan cross-window blur
 *     (banyak vendor melakukannya), wallpaper tetap teredam sesuai slider.
 */
object Glass {

    fun apply(activity: Activity, rootView: View) {
        val intensity = Prefs.blurIntensity(activity)   // 0..100

        // Lapis 1: blur asli (best effort)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            try {
                val radius = (intensity * 1.5f).toInt() // 0..150 px
                activity.window.addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND)
                activity.window.attributes = activity.window.attributes.apply {
                    blurBehindRadius = radius
                }
                activity.window.setBackgroundBlurRadius(radius)
            } catch (e: Exception) { /* fallback tetap jalan */ }
        }

        // Lapis 2: frost — alpha 0x30 (transparan) .. 0xC8 (hampir pekat)
        val alpha = 0x30 + (intensity * 0x98 / 100)
        rootView.setBackgroundColor(Color.argb(alpha.coerceIn(0x30, 0xC8), 6, 6, 12))
    }
}
