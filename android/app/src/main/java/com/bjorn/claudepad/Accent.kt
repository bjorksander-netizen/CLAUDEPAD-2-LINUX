package com.bjorn.claudepad

import android.app.WallpaperManager
import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.view.View
import androidx.core.graphics.ColorUtils

/**
 * Warna aksen mengikuti wallpaper perangkat.
 * Urutan sumber:
 *  1. WallpaperManager.getWallpaperColors — warna dominan wallpaper,
 *     tersedia sejak Android 8.1, TANPA izin apa pun (paling andal).
 *  2. system_accent1 Material You (Android 12+).
 *  3. Ungu default #7C6CFF.
 */
object Accent {

    private const val FALLBACK = 0xFF7C6CFF.toInt()
    private var cached: Int = 0

    fun color(ctx: Context): Int {
        if (cached != 0) return cached
        var c = 0

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            try {
                val wc = WallpaperManager.getInstance(ctx)
                    .getWallpaperColors(WallpaperManager.FLAG_SYSTEM)
                val prim = wc?.primaryColor?.toArgb() ?: 0
                if (prim != 0) c = brighten(prim)
            } catch (e: Exception) { /* lanjut ke sumber berikutnya */ }
        }

        if (c == 0 && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            try { c = ctx.getColor(android.R.color.system_accent1_300) }
            catch (e: Exception) { }
        }

        if (c == 0) c = FALLBACK
        cached = c
        return c
    }

    /** Warna wallpaper sering gelap/kusam — angkat ke rentang yang terlihat. */
    private fun brighten(color: Int): Int {
        val hsl = FloatArray(3)
        ColorUtils.colorToHSL(color, hsl)
        if (hsl[1] < 0.25f) hsl[1] = 0.35f          // saturasi minimal
        hsl[2] = hsl[2].coerceIn(0.55f, 0.72f)      // luminance nyaman di UI gelap
        return ColorUtils.HSLToColor(hsl)
    }

    /** Panggil saat kembali ke foreground agar ganti wallpaper terdeteksi. */
    fun refresh() { cached = 0 }

    fun bg(ctx: Context): Int = ColorUtils.setAlphaComponent(color(ctx), 0x99)

    fun applyToKey(v: View) {
        val ctx = v.context
        val radius = 16f * ctx.resources.displayMetrics.density
        val d = GradientDrawable().apply {
            cornerRadius = radius
            setColor(bg(ctx))
            setStroke((1 * ctx.resources.displayMetrics.density).toInt(),
                Color.parseColor("#40FFFFFF"))
        }
        v.background = d
    }
}
