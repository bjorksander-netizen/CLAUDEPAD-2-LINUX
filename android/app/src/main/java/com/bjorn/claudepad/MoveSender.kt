package com.bjorn.claudepad

import android.view.Choreographer

/**
 * Penggabung gerakan kursor (coalescing).
 *
 * MASALAH YANG DIPECAHKAN:
 * Layar HP melaporkan gerakan jari 60–120 kali per detik. Sebelumnya setiap
 * event dikirim sebagai satu pesan WebSocket tersendiri, sehingga radio WiFi
 * dibanjiri ratusan paket mungil per detik. Begitu jaringan tersendat sesaat,
 * pesan-pesan itu mengantre lalu dilepas sekaligus — kursor terlihat melompat
 * menyusul. Itulah gerakan patah-patah yang dilaporkan pengguna.
 *
 * SOLUSI: pergeseran dijumlahkan, lalu dikirim satu kali per frame tampilan
 * (mengikuti Choreographer, jadi selaras dengan laju layar). Gerakan yang
 * menumpuk digabung menjadi satu pesan, bukan diantre.
 */
object MoveSender {

    private var pendingX = 0f
    private var pendingY = 0f
    private var scheduled = false

    private val callback = Choreographer.FrameCallback {
        scheduled = false
        flush()
    }

    /** Tambahkan pergeseran; pengiriman ditunda sampai frame berikutnya. */
    @Synchronized
    fun move(dx: Float, dy: Float) {
        pendingX += dx
        pendingY += dy
        if (!scheduled) {
            scheduled = true
            Choreographer.getInstance().postFrameCallback(callback)
        }
    }

    /** Kirim sisa pergeseran sekarang juga (dipakai saat jari diangkat). */
    @Synchronized
    fun flush() {
        val x = pendingX.toInt()
        val y = pendingY.toInt()
        if (x != 0 || y != 0) {
            // sisa pecahan disimpan agar gerakan pelan tidak hilang
            pendingX -= x
            pendingY -= y
            WsClient.move(x, y)
        }
    }

    @Synchronized
    fun reset() {
        pendingX = 0f
        pendingY = 0f
    }
}
