package com.bjorn.claudepad

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.widget.RemoteViews
import androidx.core.app.NotificationCompat

/**
 * Foreground service yang menjaga koneksi tetap hidup saat aplikasi ditutup
 * dan menampilkan notifikasi kontrol permanen.
 *
 * Dua wajah notifikasi:
 *  - TERHUBUNG   : media control + volume, info PC, tombol putuskan.
 *  - BELUM/PUTUS : tombol hubungkan / cari otomatis / usb (tanpa perlu
 *                  membuka aplikasi), memakai pairing token.
 *
 * Catatan Android 13+: pengguna tetap boleh menggeser notifikasi FGS untuk
 * menutupnya; sistem tidak mengizinkan pemaksaan. Kita memunculkannya lagi
 * beberapa detik kemudian, dibatasi 3 kali beruntun agar tidak dianggap
 * mengganggu (lalu bisa dipanggil lagi dari Setting).
 */
class RemoteService : Service() {

    companion object {
        const val CHANNEL = "claudepad_remote"
        const val NOTIF_ID = 4201

        const val ACTION_START = "start"
        const val ACTION_UPDATE = "update"
        const val ACTION_STOP = "stop"
        const val ACTION_MEDIA = "media"          // extra "a"
        const val ACTION_VOL = "vol"              // extra "d" (+/-)
        const val ACTION_DISCONNECT = "disconnect"
        const val ACTION_CONNECT = "connect"      // extra "mode": ip/scan/usb
        const val ACTION_DISMISSED = "dismissed"

        fun start(ctx: Context) {
            val i = Intent(ctx, RemoteService::class.java).setAction(ACTION_START)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                ctx.startForegroundService(i) else ctx.startService(i)
        }

        fun update(ctx: Context) {
            ctx.startService(Intent(ctx, RemoteService::class.java).setAction(ACTION_UPDATE))
        }

        fun stop(ctx: Context) {
            ctx.startService(Intent(ctx, RemoteService::class.java).setAction(ACTION_STOP))
        }
    }

    private val handler = Handler(Looper.getMainLooper())
    private var reshowCount = 0

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> { stopSelf(); return START_NOT_STICKY }

            ACTION_MEDIA -> intent.getStringExtra("a")?.let { WsClient.media(it) }
            ACTION_VOL -> {
                val d = intent.getIntExtra("d", 0)
                val v = (WsClient.volume + d).coerceIn(0, 100)
                WsClient.volume = v
                WsClient.volSet(v)
            }
            ACTION_DISCONNECT -> {
                WsClient.disconnect()
            }
            ACTION_CONNECT -> {
                connectFromNotification(intent.getStringExtra("mode") ?: "scan")
            }
            ACTION_DISMISSED -> {
                // notifikasi digeser tutup saat masih terhubung -> munculkan lagi
                if (WsClient.connected && reshowCount < 3) {
                    reshowCount++
                    handler.postDelayed({ pushNotification() }, 2500)
                }
                return START_STICKY
            }
        }

        // reset penghitung reshow tiap ada aksi selain dismiss
        if (intent?.action != ACTION_DISMISSED) reshowCount = 0

        startForeground(NOTIF_ID, buildNotification())
        return START_STICKY
    }

    // ---------------------------------------------------------------- notif --
    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(CHANNEL, "CLAUDEPAD",
                NotificationManager.IMPORTANCE_LOW).apply {
                setShowBadge(false)
                description = "Kontrol jarak jauh CLAUDEPAD"
            }
            (getSystemService(NotificationManager::class.java)).createNotificationChannel(ch)
        }
    }

    private fun pushNotification() {
        (getSystemService(NotificationManager::class.java))
            .notify(NOTIF_ID, buildNotification())
    }

    private fun pi(action: String, vararg extras: Pair<String, Any>): PendingIntent {
        val i = Intent(this, RemoteService::class.java).setAction(action)
        for ((k, v) in extras) when (v) {
            is String -> i.putExtra(k, v)
            is Int -> i.putExtra(k, v)
        }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0)
        // request code unik per action+extra agar tidak saling menimpa
        val rc = (action + extras.joinToString()).hashCode()
        return PendingIntent.getService(this, rc, i, flags)
    }

    private fun openAppIntent(): PendingIntent {
        val i = packageManager.getLaunchIntentForPackage(packageName)
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0)
        return PendingIntent.getActivity(this, 0, i, flags)
    }

    private fun buildNotification(): Notification {
        return if (WsClient.connected) connectedNotification()
        else disconnectedNotification()
    }

    private fun connectedNotification(): Notification {
        val collapsed = RemoteViews(packageName, R.layout.notif_collapsed)
        val expanded = RemoteViews(packageName, R.layout.notif_expanded)

        val host = WsClient.hostName
        collapsed.setTextViewText(R.id.nHost, host)
        expanded.setTextViewText(R.id.nHost, host)

        val ping = if (WsClient.transport == "wifi" && WsClient.pingMs.value >= 0)
            " · ${WsClient.pingMs.value}ms" else ""
        expanded.setTextViewText(R.id.nInfo, "via ${WsClient.transport}$ping")

        for (rv in arrayOf(collapsed, expanded)) {
            rv.setOnClickPendingIntent(R.id.nPrev, pi(ACTION_MEDIA, "a" to "prev"))
            rv.setOnClickPendingIntent(R.id.nPlay, pi(ACTION_MEDIA, "a" to "playpause"))
            rv.setOnClickPendingIntent(R.id.nNext, pi(ACTION_MEDIA, "a" to "next"))
            rv.setOnClickPendingIntent(R.id.nVolDown, pi(ACTION_VOL, "d" to -5))
            rv.setOnClickPendingIntent(R.id.nVolUp, pi(ACTION_VOL, "d" to 5))
        }
        expanded.setOnClickPendingIntent(R.id.nDisconnect, pi(ACTION_DISCONNECT))

        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notif)
            .setStyle(NotificationCompat.DecoratedCustomViewStyle())
            .setCustomContentView(collapsed)
            .setCustomBigContentView(expanded)
            .setContentIntent(openAppIntent())
            .setOngoing(true)
            .setDeleteIntent(pi(ACTION_DISMISSED))
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build()
    }

    private fun disconnectedNotification(): Notification {
        val paired = Prefs.token(this).isNotEmpty() && Prefs.ip(this).isNotEmpty()

        val b = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle("CLAUDEPAD — belum terhubung")
            .setContentText(if (paired) "ketuk untuk menyambung ke PC"
                            else "buka aplikasi untuk menyambung")
            .setContentIntent(openAppIntent())
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)

        // Tombol sambung hanya berguna bila sudah pernah dipasangkan (punya
        // token & IP), karena notifikasi tidak bisa memuat kolom PIN.
        if (paired) {
            b.addAction(R.drawable.ic_link, "hubungkan", pi(ACTION_CONNECT, "mode" to "ip"))
            b.addAction(R.drawable.ic_link, "cari otomatis", pi(ACTION_CONNECT, "mode" to "scan"))
            b.addAction(R.drawable.ic_link, "usb", pi(ACTION_CONNECT, "mode" to "usb"))
        }
        return b.build()
    }

    // ---------------------------------------------------------------- connect --
    private var wasConnected = false

    private fun connectFromNotification(mode: String) {
        val ver = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: "0"
        } catch (e: Exception) { "0" }
        val pin = Prefs.pin(this)
        val token = Prefs.token(this)

        WsClient.onNewToken = { t -> Prefs.setToken(this, t) }
        WsClient.onState = { ok, _ ->
            handler.post {
                if (ok && !wasConnected) {
                    wasConnected = true
                    // beri tahu pengguna & tawarkan buka aplikasi
                    showConnectedPrompt()
                }
                pushNotification()
            }
        }

        val host = when (mode) {
            "usb" -> "127.0.0.1"
            else -> Prefs.ip(this)
        }
        if (host.isEmpty()) {
            // tidak ada alamat tersimpan -> arahkan buka aplikasi
            openAppIntent().send()
            return
        }
        if (mode == "scan") scanThenConnect(ver, pin, token)
        else WsClient.connect(host, 8765, pin, ver, token)
    }

    private fun scanThenConnect(ver: String, pin: String, token: String) {
        Thread {
            val found = Discovery.findFirst()
            handler.post {
                val host = found ?: Prefs.ip(this)
                if (host.isNotEmpty()) {
                    if (found != null) Prefs.setIp(this, found)
                    WsClient.connect(host, 8765, pin, ver, token)
                }
            }
        }.start()
    }

    /** Pop-up singkat lewat notifikasi terpisah: OK, atau buka aplikasi. */
    private fun showConnectedPrompt() {
        val nm = getSystemService(NotificationManager::class.java)
        val n = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle("Tersambung ke ${WsClient.hostName}")
            .setContentText("Trackpad siap dipakai")
            .addAction(0, "buka aplikasi", openAppIntent())
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()
        nm.notify(NOTIF_ID + 1, n)
    }

    override fun onDestroy() {
        super.onDestroy()
        handler.removeCallbacksAndMessages(null)
    }
}
