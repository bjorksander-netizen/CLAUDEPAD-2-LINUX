package com.bjorn.claudepad

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View

/**
 * Slider volume vertikal bergaya Control Center iOS:
 * kapsul membulat, bagian terisi berwarna terang, ikon speaker di bawah.
 */
class VolumeSlider @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null
) : View(context, attrs) {

    /** Dipanggil terus-menerus saat digeser, nilai 0..100. */
    var onValueChanged: ((Int) -> Unit)? = null
    /** Dipanggil sekali saat jari dilepas. */
    var onCommit: ((Int) -> Unit)? = null
    /** Ketukan pada ikon speaker di bawah slider = bisukan. */
    var onMuteTap: (() -> Unit)? = null

    var value: Int = 50
        set(v) {
            val clamped = v.coerceIn(0, 100)
            if (clamped != field) { field = clamped; invalidate() }
        }

    private val trackPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#33FFFFFF")
    }
    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#F2FFFFFF")
    }
    private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 2f
        color = Color.parseColor("#40FFFFFF")
    }
    private val iconPaint = Paint(Paint.ANTI_ALIAS_FLAG)

    private val rect = RectF()
    private val clipPath = Path()
    private val iconPath = Path()
    private var lastNotch = -1
    private var downOnIcon = false

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val pad = 2f
        rect.set(pad, pad, width - pad, height - pad)
        val r = rect.width() / 2f

        canvas.drawRoundRect(rect, r, r, trackPaint)

        // bagian terisi (dari bawah)
        val fillTop = rect.bottom - rect.height() * (value / 100f)
        if (value > 0) {
            clipPath.reset()
            clipPath.addRoundRect(rect, r, r, Path.Direction.CW)
            canvas.save()
            canvas.clipPath(clipPath)
            canvas.drawRect(rect.left, fillTop, rect.right, rect.bottom, fillPaint)
            canvas.restore()
        }
        canvas.drawRoundRect(rect, r, r, strokePaint)

        // ikon speaker di bagian bawah, warnanya kontras terhadap isi slider
        val cx = rect.centerX()
        val cy = rect.bottom - r * 0.95f
        iconPaint.color = if (cy > fillTop) Color.parseColor("#1A1A22") else Color.WHITE
        drawSpeaker(canvas, cx, cy, r * 0.52f)
    }

    private fun drawSpeaker(canvas: Canvas, cx: Float, cy: Float, s: Float) {
        iconPath.reset()
        // badan speaker
        iconPath.moveTo(cx - s * 0.75f, cy - s * 0.28f)
        iconPath.lineTo(cx - s * 0.35f, cy - s * 0.28f)
        iconPath.lineTo(cx + s * 0.05f, cy - s * 0.72f)
        iconPath.lineTo(cx + s * 0.05f, cy + s * 0.72f)
        iconPath.lineTo(cx - s * 0.35f, cy + s * 0.28f)
        iconPath.lineTo(cx - s * 0.75f, cy + s * 0.28f)
        iconPath.close()
        canvas.drawPath(iconPath, iconPaint)

        if (value > 0) {
            val wave = Paint(iconPaint).apply {
                style = Paint.Style.STROKE
                strokeWidth = s * 0.16f
                isAntiAlias = true
            }
            val arc = RectF(cx - s * 0.15f, cy - s * 0.55f, cx + s * 0.65f, cy + s * 0.55f)
            canvas.drawArc(arc, -55f, 110f, false, wave)
            if (value > 55) {
                val arc2 = RectF(cx - s * 0.05f, cy - s * 0.85f, cx + s * 1.05f, cy + s * 0.85f)
                canvas.drawArc(arc2, -55f, 110f, false, wave)
            }
        }
    }

    private fun valueFromY(y: Float): Int {
        val h = (height - 4f).coerceAtLeast(1f)
        val ratio = 1f - ((y - 2f) / h)
        return (ratio * 100f).toInt().coerceIn(0, 100)
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                // area ikon speaker di ujung bawah dipakai untuk mute
                if (e.y > height - width * 1.15f) {
                    downOnIcon = true
                    parent?.requestDisallowInterceptTouchEvent(true)
                    return true
                }
                downOnIcon = false
                parent?.requestDisallowInterceptTouchEvent(true)
                val v = valueFromY(e.y)
                if (v != value) {
                    value = v
                    onValueChanged?.invoke(v)
                    val notch = v / 5
                    if (notch != lastNotch) { lastNotch = notch; Haptics.tick() }
                }
            }
            MotionEvent.ACTION_MOVE -> {
                if (downOnIcon) return true
                parent?.requestDisallowInterceptTouchEvent(true)
                val v = valueFromY(e.y)
                if (v != value) {
                    value = v
                    onValueChanged?.invoke(v)
                    val notch = v / 5
                    if (notch != lastNotch) { lastNotch = notch; Haptics.tick() }
                }
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                parent?.requestDisallowInterceptTouchEvent(false)
                if (downOnIcon) {
                    downOnIcon = false
                    Haptics.medium()
                    onMuteTap?.invoke()
                } else {
                    Haptics.light()
                    onCommit?.invoke(value)
                }
            }
        }
        return true
    }
}
