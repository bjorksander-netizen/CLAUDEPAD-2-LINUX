package com.bjorn.claudepad

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * Sinkronisasi clipboard dua arah HP ⇄ PC (v3.7).
 *
 * HP → PC: saat isi clipboard HP berubah (ada teks), kirim {"t":"clipset","s":...}
 *          ke server.
 * PC → HP: saat server push {"t":"clip","s":...}, tulis ke clipboard HP.
 *
 * GUARD anti-loop (mencegah ping-pong):
 *  1. Sebelum menulis ke clipboard HP (dari PC), set flag [ignoreNext].
 *     Listener yang terpicu akibat tulisan kita sendiri membaca flag itu,
 *     mengonsumsinya, lalu tidak mengirim balik ke PC.
 *  2. Lapisan kedua: teks hasil tulisan kita dicatat di [lastSentText].
 *     Perubahan clipboard yang isinya sama persis dengan kiriman terakhir
 *     tidak diteruskan — jadi echo apa pun (dari server maupun OS) tidak
 *     menimbulkan putaran.
 *
 * Lifecycle: listener didaftarkan HANYA saat ketiganya terpenuhi —
 * koneksi terautentikasi + toggle pengguna ON + server melaporkan
 * caps.clipboard=true. Saat salah satu mati, listener dibatalkan (tidak bocor).
 */
object ClipboardSync {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    @Volatile private var appContext: Context? = null
    @Volatile private var clipboard: ClipboardManager? = null

    @Volatile private var connected = false
    @Volatile private var enabled = false
    @Volatile private var registered = false

    /** Echo guard lapisan 1: abaikan satu perubahan clipboard berikutnya. */
    @Volatile private var ignoreNext = false

    /** Echo guard lapisan 2: teks terakhir yang dikirim/diterima dari PC. */
    @Volatile private var lastSentText: String? = null

    private var collectJob: Job? = null

    private val listener = ClipboardManager.OnPrimaryClipChangedListener {
        // Guard lapisan 1: ini echo dari tulisan kita sendiri → jangan balas.
        if (ignoreNext) {
            ignoreNext = false
            return@OnPrimaryClipChangedListener
        }
        val text = currentText()
        // Guard lapisan 2: isi tidak berubah vs. kiriman terakhir → jangan balas.
        if (text != null && text != lastSentText && canSync()) {
            lastSentText = text
            WsClient.clipSet(text)
        }
    }

    /**
     * Inisialisasi object (idempoten). Panggil dari Activity/Service yang
     * menjadi pintu masuk aplikasi.
     */
    fun init(ctx: Context) {
        appContext = ctx.applicationContext
        if (clipboard == null) {
            clipboard = appContext
                ?.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
        }
        enabled = Prefs.clipAuto(appContext ?: return)
        start()
    }

    /** Ubah toggle pengguna. Saat terhubung, ikut sinkronkan ke server. */
    fun setEnabled(v: Boolean) {
        enabled = v
        refresh()
        if (connected && WsClient.connectionInfo.value.clipboardSupported) {
            WsClient.clipSync(v)
        }
    }

    private fun start() {
        if (collectJob != null) return
        collectJob = scope.launch {
            // Pantau status koneksi — aktif juga saat koneksi dibuat dari
            // RemoteService (notifikasi), bukan hanya dari ControlActivity.
            WsClient.connectionState.collect { state ->
                val wasConnected = connected
                connected = state is WsClient.ConnectionState.Connected
                if (connected && !wasConnected) {
                    // Baseline: jangan kirim ulang isi clipboard yang sudah
                    // ada di HP ke PC saat baru tersambung.
                    lastSentText = currentText()
                    // Sinkronkan toggle pengguna ke server sesuai Prefs.
                    if (WsClient.connectionInfo.value.clipboardSupported) {
                        WsClient.clipSync(enabled)
                    }
                }
                refresh()
            }
        }
        scope.launch {
            // PC → HP: tulis push clipboard ke clipboard HP.
            WsClient.serverMessages.collect { msg ->
                if (msg.optString("t") == "clip") {
                    val hasS = msg.has("s") && !msg.isNull("s")
                    val s = if (hasS) msg.optString("s") else null
                    // Push otomatis server tidak menyertakan "ok" — kehadiran
                    // "s" non-kosong dianggap sah (sama seperti di WsClient).
                    val ok = if (msg.has("ok")) msg.optBoolean("ok", false)
                             else !s.isNullOrEmpty()
                    onClipFromPc(s, ok)
                }
            }
        }
    }

    /** PC → HP: tulis teks dari server ke clipboard HP. */
    fun onClipFromPc(text: String?, ok: Boolean) {
        if (!canSync() || !ok) return
        val t = text ?: return
        if (t.isEmpty()) return
        val cm = clipboard ?: return
        if (t == currentText()) return  // sudah sama — tidak perlu menulis

        ignoreNext = true
        lastSentText = t
        try {
            cm.setPrimaryClip(ClipData.newPlainText("claudepad", t))
        } catch (e: Exception) {
            // Gagal menulis — kembalikan flag supaya perubahan pengguna
            // berikutnya tidak salah diabaikan.
            ignoreNext = false
        }
    }

    private fun refresh() {
        val want = canSync()
        val cm = clipboard ?: return
        if (want && !registered) {
            registered = true
            ignoreNext = false
            lastSentText = currentText()
            cm.addPrimaryClipChangedListener(listener)
        } else if (!want && registered) {
            registered = false
            cm.removePrimaryClipChangedListener(listener)
        }
    }

    private fun canSync(): Boolean =
        connected && enabled && WsClient.connectionInfo.value.clipboardSupported

    private fun currentText(): String? {
        val cm = clipboard ?: return null
        return try {
            cm.primaryClip?.coerceToText(appContext)?.toString()
        } catch (e: Exception) {
            null
        }
    }
}
