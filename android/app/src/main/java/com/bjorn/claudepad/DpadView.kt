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
import kotlin.math.abs
import kotlin.math.min

/**
 * D-Pad berbentuk salib ala DualShock: 4 arah dengan auto-repeat saat ditahan.
 * Arah yang ditekan disorot memakai warna aksen yang mengikuti wallpaper.
 */
class DpadView @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null
) : View(context, attrs) {

    /** Dipanggil dengan "up" / "down" / "left" / "right". */
    var onDirection: ((String) -> Unit)? = null

    private val basePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#3DFFFFFF")
    }
    private val pressPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#997C6CFF")
    }

    /** Warna sorot arah, diisi dari Accent (mengikuti wallpaper perangkat). */
    var accentColor: Int
        get() = pressPaint.color
        set(value) { pressPaint.color = value; invalidate() }

    private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 2f
        color = Color.parseColor("#40FFFFFF")
    }
    private val arrowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
    }

    private val cross = Path()
    private val arrow = Path()
    private var pressed: String? = null

    private val repeatDelay = 380L
    private val repeatInterval = 55L
    private var repeatRunnable: Runnable? = null

    private fun buildCross(w: Float, h: Float) {
        val size = min(w, h)
        val cx = w / 2f
        val cy = h / 2f
        val arm = size / 2f * 0.94f
        val half = arm * 0.34f
        val r = arm * 0.16f
        cross.reset()
        val rect = RectF()
        rect.set(cx - half, cy - arm, cx + half, cy + arm)
        cross.addRoundRect(rect, r, r, Path.Direction.CW)
        rect.set(cx - arm, cy - half, cx + arm, cy + half)
        cross.addRoundRect(rect, r, r, Path.Direction.CW)
    }

    override fun onSizeChanged(w: Int, h: Int, ow: Int, oh: Int) {
        super.onSizeChanged(w, h, ow, oh)
        buildCross(w.toFloat(), h.toFloat())
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawPath(cross, basePaint)
        canvas.drawPath(cross, strokePaint)

        val w = width.toFloat(); val h = height.toFloat()
        val cx = w / 2f; val cy = h / 2f
        val size = min(w, h)
        val arm = size / 2f * 0.94f

        // sorot arah yang ditekan
        pressed?.let { dir ->
            val half = arm * 0.34f
            val r = arm * 0.16f
            val rect = RectF()
            when (dir) {
                "up" -> rect.set(cx - half, cy - arm, cx + half, cy - half)
                "down" -> rect.set(cx - half, cy + half, cx + half, cy + arm)
                "left" -> rect.set(cx - arm, cy - half, cx - half, cy + half)
                else -> rect.set(cx + half, cy - half, cx + arm, cy + half)
            }
            canvas.drawRoundRect(rect, r, r, pressPaint)
        }

        // panah
        val a = arm * 0.30f
        val off = arm * 0.62f
        drawArrow(canvas, cx, cy - off, a, 0)
        drawArrow(canvas, cx, cy + off, a, 180)
        drawArrow(canvas, cx - off, cy, a, 270)
        drawArrow(canvas, cx + off, cy, a, 90)
    }

    private fun drawArrow(canvas: Canvas, cx: Float, cy: Float, size: Float, rotation: Int) {
        arrow.reset()
        val h = size * 0.55f
        arrow.moveTo(0f, -h)
        arrow.lineTo(h * 0.9f, h * 0.6f)
        arrow.lineTo(-h * 0.9f, h * 0.6f)
        arrow.close()
        canvas.save()
        canvas.translate(cx, cy)
        canvas.rotate(rotation.toFloat())
        canvas.drawPath(arrow, arrowPaint)
        canvas.restore()
    }

    private fun hitTest(x: Float, y: Float): String? {
        val cx = width / 2f
        val cy = height / 2f
        val dx = x - cx
        val dy = y - cy
        val size = min(width, height) / 2f
        if ((dx * dx + dy * dy) < (size * 0.18f) * (size * 0.18f)) return null
        if (abs(dx) > size || abs(dy) > size) return null
        return if (abs(dx) > abs(dy)) {
            if (dx > 0) "right" else "left"
        } else {
            if (dy > 0) "down" else "up"
        }
    }

    private fun startRepeat(dir: String) {
        stopRepeat()
        val r = object : Runnable {
            override fun run() {
                onDirection?.invoke(dir)
                Haptics.tick()
                postDelayed(this, repeatInterval)
            }
        }
        repeatRunnable = r
        postDelayed(r, repeatDelay)
    }

    private fun stopRepeat() {
        repeatRunnable?.let { removeCallbacks(it) }
        repeatRunnable = null
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                val dir = hitTest(e.x, e.y) ?: return true
                pressed = dir
                invalidate()
                Haptics.light()
                onDirection?.invoke(dir)
                startRepeat(dir)
            }
            MotionEvent.ACTION_MOVE -> {
                val dir = hitTest(e.x, e.y)
                if (dir != pressed) {
                    pressed = dir
                    invalidate()
                    stopRepeat()
                    if (dir != null) {
                        Haptics.light()
                        onDirection?.invoke(dir)
                        startRepeat(dir)
                    }
                }
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                pressed = null
                stopRepeat()
                invalidate()
            }
        }
        return true
    }

    override fun onDetachedFromWindow() {
        super.onDetachedFromWindow()
        stopRepeat()
    }
}
