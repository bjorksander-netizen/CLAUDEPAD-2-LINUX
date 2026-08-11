package com.bjorn.claudepad

import android.content.Context
import android.graphics.Typeface
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.core.content.res.ResourcesCompat

/**
 * JetBrains Mono (diunduh saat build oleh task Gradle `fetchFont`).
 * Kalau file font tidak ada, otomatis jatuh ke monospace bawaan sistem —
 * jadi aplikasi tetap ter-compile & berjalan normal.
 */
object Fonts {

    private var cached: Typeface? = null

    fun mono(ctx: Context): Typeface {
        cached?.let { return it }
        val tf = try {
            val id = ctx.resources.getIdentifier("jetbrains_mono", "font", ctx.packageName)
            if (id != 0) ResourcesCompat.getFont(ctx, id) ?: Typeface.MONOSPACE
            else Typeface.MONOSPACE
        } catch (e: Exception) {
            Typeface.MONOSPACE
        }
        cached = tf
        return tf
    }

    /** Terapkan ke seluruh TextView di dalam hierarchy. */
    fun apply(root: View) {
        val tf = mono(root.context)
        walk(root) { v ->
            if (v is TextView) {
                val style = v.typeface?.style ?: Typeface.NORMAL
                v.setTypeface(tf, style)
            }
        }
    }

    private fun walk(v: View, action: (View) -> Unit) {
        action(v)
        if (v is ViewGroup) {
            for (i in 0 until v.childCount) walk(v.getChildAt(i), action)
        }
    }
}
