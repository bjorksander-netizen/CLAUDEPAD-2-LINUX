package com.bjorn.claudepad

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Klien WebSocket ke server CLAUDEPAD.
 *
 * Sejak v3.0 lalu lintas terenkripsi: alur handshake-nya
 *   1. onOpen  -> kirim {"t":"hello"} (plaintext)
 *   2. server balas {"t":"hello_ok","salt":...}
 *   3. turunkan kunci sesi dari PIN/token + salt, kirim {"t":"auth"} (plaintext)
 *   4. server balas auth_ok, lalu SEMUA pesan berikutnya biner terenkripsi.
 *
 * Arsitektur state:
 * - ConnectionState (StateFlow): status koneksi terkini
 * - serverMessages (SharedFlow): pesan dari server (volume, power_result, dll)
 * - pingMs (StateFlow): latensi terkini
 * - reconnectingTo (StateFlow): info reconnect, null = tidak reconnecting
 * - newToken (SharedFlow): token baru dari server
 *
 * Callback lama (onState, onMessage, dll) dipertahankan untuk RemoteService.
 */
object WsClient {

    // ──────────────────────────── state types ────────────────────────────

    /** Status koneksi WebSocket. */
    sealed class ConnectionState {
        data object Disconnected : ConnectionState()
        data object Connecting : ConnectionState()
        data object Connected : ConnectionState()
        data class Error(val message: String) : ConnectionState()
    }

    /** Informasi koneksi setelah auth_ok berhasil. */
    data class ConnectionInfo(
        val hostName: String = "—",
        val transport: String = "—",
        val serverVersion: String = "—",
        val volume: Int = 50,
        val macAddress: String = "",
        val encrypted: Boolean = false,
        /** "linux" atau "windows". Server lama tidak mengirimnya. */
        val platform: String = "",
        /** Desktop environment PC, mis. "GNOME". Kosong di server Windows. */
        val desktop: String = "",
        /** Jenis sesi grafis PC: "wayland", "x11", atau "tty". */
        val session: String = "",
        /**
         * Aksi daya yang benar-benar didukung PC, mis. ["shutdown","lock"].
         * null berarti server TIDAK melaporkannya (server Windows, atau
         * APK ini dipakai dengan server lama) — dalam hal itu semua tombol
         * ditampilkan seperti sediakala dan server yang menolak.
         */
        val powerActions: Set<String>? = null,
        /** Backend injeksi input di sisi PC: "uinput", "xtest", "none", ... */
        val inputBackend: String = "",
        /** v3.7: PC melaporkan dukungan sinkron clipboard (caps.clipboard). */
        val clipboardSupported: Boolean = false,
        /** v3.7: PC melaporkan dukungan now playing (caps.nowplaying). */
        val nowPlayingSupported: Boolean = false
    ) {
        /** Label singkat untuk ditampilkan di halaman Setting. */
        fun systemLabel(): String = when {
            platform.isEmpty() -> "windows"
            desktop.isEmpty() -> platform
            else -> "$platform · $desktop" +
                (if (session.isNotEmpty()) " ($session)" else "")
        }

        /**
         * Apakah aksi daya [action] layak ditampilkan.
         * Server yang tidak melaporkan kemampuannya dianggap mendukung
         * semuanya, supaya APK ini tetap bekerja dengan server Windows.
         */
        fun supportsPower(action: String): Boolean =
            powerActions?.contains(action) ?: true
    }

    /** Status clipboard di PC, hasil {"t":"clip"} dari server (v3.7+). */
    data class ClipboardState(
        val content: String? = null,
        val ok: Boolean = false,
        val auto: Boolean = false,
        /** v3.9: gambar clipboard PC dalam bentuk base64 PNG (null kalau teks). */
        val imgB64: String? = null
    )

    /** Info lagu yang sedang diputar di PC, hasil {"t":"np"} (v3.7). */
    data class NowPlaying(
        val ok: Boolean = false,
        val title: String = "",
        val artist: String = "",
        val album: String = "",
        val playing: Boolean = false,
        val lengthUs: Long = 0L,
        val posUs: Long = 0L,
        val canSeek: Boolean = false,
        val msg: String = ""
    )

    // ──────────────────────────── StateFlow API ──────────────────────────

    private val _connectionState = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected)
    val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()

    private val _connectionInfo = MutableStateFlow(ConnectionInfo())
    val connectionInfo: StateFlow<ConnectionInfo> = _connectionInfo.asStateFlow()

    private val _pingMs = MutableStateFlow(-1)
    val pingMs: StateFlow<Int> = _pingMs.asStateFlow()

    private val _reconnectingTo = MutableStateFlow<Int?>(null)
    val reconnectingTo: StateFlow<Int?> = _reconnectingTo.asStateFlow()

    private val _serverMessages = MutableSharedFlow<JSONObject>(extraBufferCapacity = 16)
    val serverMessages: SharedFlow<JSONObject> = _serverMessages.asSharedFlow()

    private val _newToken = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val newToken: SharedFlow<String> = _newToken.asSharedFlow()

    private val _scrollInfo = MutableStateFlow<ScrollInfo?>(null)
    val scrollInfo: StateFlow<ScrollInfo?> = _scrollInfo.asStateFlow()

    // v3.7: clipboard & now playing dari server
    private val _clipboardContent = MutableStateFlow(ClipboardState())
    val clipboardContent: StateFlow<ClipboardState> = _clipboardContent.asStateFlow()

    private val _nowPlaying = MutableStateFlow(NowPlaying())
    val nowPlaying: StateFlow<NowPlaying> = _nowPlaying.asStateFlow()

    // ──────────────────────────── legacy callbacks ───────────────────────
    // Dipertahankan untuk RemoteService (tidak lifecycle-aware).

    var onState: ((Boolean, String) -> Unit)? = null
    var onNewToken: ((String) -> Unit)? = null
    var onMessage: ((JSONObject) -> Unit)? = null
    var onPing: ((Int) -> Unit)? = null
    var onReconnecting: ((Int) -> Unit)? = null

    // ──────────────────────────── internal state ─────────────────────────

    private fun buildClient(host: String): OkHttpClient {
        val b = OkHttpClient.Builder()
            .pingInterval(15, TimeUnit.SECONDS)
            .connectTimeout(8, TimeUnit.SECONDS)
        Net.localAddressFor(host)?.let { local ->
            boundVia = local.hostAddress ?: ""
            b.socketFactory(Net.BoundSocketFactory(local))
        } ?: run { boundVia = "" }
        return b.build()
    }

    @Volatile var boundVia: String = ""
        private set

    @Volatile var encrypted = false
        private set
    private var crypto: CryptoBox? = null
    private var serverPubKey: String = ""  // v3.2: RSA public key dari server
    @Volatile var binaryEnabled = false   // v3.3: binary protocol aktif
        private set

    private var ws: WebSocket? = null

    @Volatile var connected = false
        private set

    @Volatile var hostName: String = "—"
        private set
    @Volatile var transport: String = "—"
        private set
    @Volatile var serverVersion: String = "—"
        private set
    @Volatile var macAddress: String = ""
        private set
    @Volatile var platform: String = ""
        private set
    @Volatile var desktop: String = ""
        private set
    @Volatile var session: String = ""
        private set
    @Volatile var inputBackend: String = ""
        private set
    @Volatile var powerActions: Set<String>? = null
        private set
    @Volatile var volume: Int = 50

    // v3.7: kemampuan baru dari caps.auth_ok
    @Volatile var clipboardSupported = false
        private set
    @Volatile var nowPlayingSupported = false
        private set

    // Raw ping value — hanya untuk kompatibilitas RemoteService.
    // ViewModel harus pakai StateFlow `pingMs`.
    @Volatile private var _pingMsRaw: Int = -1
    private var pingSentAt = 0L

    private var lastHost = ""
    private var lastPort = 8765
    private var lastPin = ""
    private var lastToken = ""
    private var lastVersion = ""
    private var retryCount = 0
    private var manualClose = false

    var autoReconnect = true

    // ──────────────────────────── public API ─────────────────────────────

    fun connect(host: String, port: Int, pin: String, appVersion: String,
                token: String = "") {
        lastHost = host; lastPort = port; lastPin = pin
        lastVersion = appVersion; lastToken = token
        manualClose = false
        _connectionState.value = ConnectionState.Connecting
        openSocket()
    }

    fun disconnect() {
        manualClose = true
        connected = false
        _pingMsRaw = -1
        _pingMs.value = -1
        pingSentAt = 0L
        retryCount = 0
        crypto = null
        encrypted = false
        serverPubKey = ""
        binaryEnabled = false
        platform = ""
        desktop = ""
        session = ""
        inputBackend = ""
        powerActions = null
        clipboardSupported = false
        nowPlayingSupported = false
        _clipboardContent.value = ClipboardState()
        _nowPlaying.value = NowPlaying()
        _connectionInfo.value = ConnectionInfo()
        _reconnectingTo.value = null
        _connectionState.value = ConnectionState.Disconnected
        closeQuietly()
    }

    fun measurePing() {
        if (ws == null) return
        val now = System.currentTimeMillis()
        if (pingSentAt > 0L && now - pingSentAt < 4000) return
        pingSentAt = now
        send("ping")
    }

    // ──────────────────────────── send commands ──────────────────────────

    private fun send(o: JSONObject) {
        val sock = ws ?: return
        val box = crypto
        // v3.3: pakai binary protocol kalau server mendukung
        if (binaryEnabled) {
            val bin = BinaryProtocol.encode(o)
            if (bin != null && box != null && encrypted) {
                try { sock.send(box.seal(bin).toByteString()) }
                catch (e: Exception) { }
                return
            }
        }
        if (box != null && encrypted) {
            try { sock.send(box.seal(o.toString().toByteArray()).toByteString()) }
            catch (e: Exception) { sock.send(o.toString()) }
        } else {
            sock.send(o.toString())
        }
    }

    private fun send(t: String) = send(JSONObject().put("t", t))

    fun move(dx: Int, dy: Int) = send(JSONObject().put("t", "move").put("dx", dx).put("dy", dy))
    fun click(b: String, double: Boolean = false) =
        send(JSONObject().put("t", "click").put("b", b).put("double", double))
    fun buttonDown(b: String) = send(JSONObject().put("t", "down").put("b", b))
    fun buttonUp(b: String) = send(JSONObject().put("t", "up").put("b", b))
    fun scroll(dy: Int) = send(JSONObject().put("t", "scroll").put("dy", dy))
    fun scrollHorizontal(dx: Int) = send(JSONObject().put("t", "scroll").put("dx", dx))
    fun zoom(dir: Int) = send(JSONObject().put("t", "zoom").put("dir", dir))
    fun gesture(g: String) = send(JSONObject().put("t", "gesture").put("g", g))
    fun text(s: String) = send(JSONObject().put("t", "text").put("s", s))

    fun key(k: String, mods: List<String> = emptyList()) {
        val o = JSONObject().put("t", "key").put("k", k)
        if (mods.isNotEmpty()) o.put("mods", JSONArray(mods))
        send(o)
    }

    fun media(a: String) = send(JSONObject().put("t", "media").put("a", a))
    fun radio(device: String) = send(JSONObject().put("t", "radio").put("d", device))
    fun power(action: String) = send(JSONObject().put("t", "power").put("a", action))
    fun volSet(v: Int) = send(JSONObject().put("t", "volset").put("v", v))
    fun volGet() = send("volget")

    // ──────────────────────────── v3.7: clipboard & now playing ──────────

    /** Kirim teks clipboard HP ke PC. */
    fun clipSet(s: String) = send(JSONObject().put("t", "clipset").put("s", s))

    /** Kirim gambar clipboard HP ke PC (PNG bytes, di-base64-kan). */
    fun clipSet(img: ByteArray) {
        val b64 = android.util.Base64.encodeToString(img, android.util.Base64.NO_WRAP)
        send(JSONObject().put("t", "clipset").put("img", b64))
    }

    /** Minta isi clipboard PC (server akan balas {"t":"clip",...}). */
    fun clipGet() = send("clipget")

    /** Aktif/nonaktifkan sinkronisasi clipboard di sisi server. */
    fun clipSync(on: Boolean) = send(JSONObject().put("t", "clipsync").put("on", on))

    /** Minta info lagu yang sedang diputar di PC. */
    fun npGet() = send("npget")

    /** Lompat ke posisi [posUs] mikrodetik pada pemutar PC. */
    fun npSeek(posUs: Long) =
        send(JSONObject().put("t", "npseek").put("pos_us", posUs))

    // ──────────────────────────── WebSocket internals ────────────────────

    private fun openSocket() {
        val host = lastHost
        val port = lastPort
        val pin = lastPin
        val token = lastToken
        val appVersion = lastVersion
        closeQuietly()
        val req = Request.Builder().url("ws://$host:$port/ws").build()
        ws = buildClient(host).newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                crypto = null
                encrypted = false
                serverPubKey = ""
                webSocket.send(JSONObject().put("t", "hello").toString())
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                val box = crypto ?: return
                val plain = try { String(box.open(bytes.toByteArray())) }
                            catch (e: Exception) { return }
                handleJson(plain, webSocket, pin, token, appVersion)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleJson(text, webSocket, pin, token, appVersion)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                connected = false
                val raw = t.message ?: "koneksi gagal"
                val msg = if (raw.contains("failed to connect", true) ||
                              raw.contains("ETIMEDOUT", true)) {
                    "tidak sampai ke pc — tekan ⚙ lalu Diagnosa koneksi"
                } else raw
                if (!tryReconnect()) {
                    _connectionState.value = ConnectionState.Error(msg)
                    onState?.invoke(false, msg)
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                connected = false
                if (!tryReconnect()) {
                    _connectionState.value = ConnectionState.Disconnected
                    onState?.invoke(false, "terputus")
                }
            }
        })
    }

    private fun handleJson(text: String, webSocket: WebSocket,
                           pin: String, token: String, appVersion: String) {
        val o = try { JSONObject(text) } catch (e: Exception) { return }
        when (o.optString("t")) {
            "hello_ok" -> {
                try {
                    val salt = hexToBytes(o.optString("salt"))
                    val secret = if (token.isNotEmpty()) token else pin
                    crypto = CryptoBox.derive(secret, salt)
                } catch (e: Exception) { crypto = null }

                // v3.2: Simpan public key RSA dari server untuk enkripsi auth.
                serverPubKey = o.optString("pubkey", "")

                // Kirim auth — PIN/token dienkripsi RSA jika server punya pubkey.
                val auth = JSONObject().put("t", "auth").put("ver", appVersion)
                    .put("binary", true)  // v3.3: minta binary protocol
                if (serverPubKey.isNotEmpty()) {
                    try {
                        val encPin = CryptoBox.encryptWithPublicKey(
                            serverPubKey, pin.toByteArray())
                        auth.put("pin_enc", android.util.Base64.encodeToString(
                            encPin, android.util.Base64.NO_WRAP))
                    } catch (e: Exception) {
                        // Fallback ke pin plain jika enkripsi gagal
                        auth.put("pin", pin)
                    }
                    if (token.isNotEmpty()) {
                        try {
                            val encToken = CryptoBox.encryptWithPublicKey(
                                serverPubKey, token.toByteArray())
                            auth.put("token_enc", android.util.Base64.encodeToString(
                                encToken, android.util.Base64.NO_WRAP))
                        } catch (e: Exception) {
                            auth.put("token", token)
                        }
                    }
                } else {
                    // Server lama tanpa pubkey — kirim plain
                    auth.put("pin", pin)
                    if (token.isNotEmpty()) auth.put("token", token)
                }
                webSocket.send(auth.toString())
            }
            "auth_ok" -> {
                connected = true
                hostName = o.optString("host", "PC")
                transport = o.optString("transport", "wifi")
                serverVersion = o.optString("version", "—")
                if (!o.isNull("vol")) volume = o.optInt("vol", 50)
                macAddress = o.optString("mac", "")
                encrypted = o.optBoolean("encrypted", false)
                binaryEnabled = o.optBoolean("binary", false)  // v3.3

                // v3.6: server Linux melaporkan platform & kemampuannya.
                // Server Windows tidak mengirim bidang ini; optString/
                // optJSONObject mengembalikan nilai kosong, dan aplikasi
                // otomatis kembali ke perilaku lama.
                platform = o.optString("platform", "")
                desktop = o.optString("desktop", "")
                session = o.optString("session", "")
                val caps = o.optJSONObject("caps")
                inputBackend = caps?.optString("input", "") ?: ""
                powerActions = caps?.optJSONArray("power")?.let { arr ->
                    (0 until arr.length())
                        .map { arr.optString(it) }
                        .filter { it.isNotEmpty() }
                        .toSet()
                }
                // v3.7: kemampuan baru — default false supaya APK ini tetap
                // aman dipakai dengan server lama yang tidak mengirimnya.
                clipboardSupported = caps?.optBoolean("clipboard", false) ?: false
                nowPlayingSupported = caps?.optBoolean("nowplaying", false) ?: false

                val fresh = o.optString("token", "")

                // Emit ke StateFlow
                _connectionInfo.value = ConnectionInfo(
                    hostName = hostName,
                    transport = transport,
                    serverVersion = serverVersion,
                    volume = volume,
                    macAddress = macAddress,
                    encrypted = encrypted,
                    platform = platform,
                    desktop = desktop,
                    session = session,
                    powerActions = powerActions,
                    inputBackend = inputBackend,
                    clipboardSupported = clipboardSupported,
                    nowPlayingSupported = nowPlayingSupported
                )
                _connectionState.value = ConnectionState.Connected
                _reconnectingTo.value = null
                retryCount = 0

                // Emit token baru
                if (fresh.isNotEmpty()) {
                    _newToken.tryEmit(fresh)
                    onNewToken?.invoke(fresh)
                }

                onState?.invoke(true, "terhubung")
            }
            "auth_fail" -> {
                connected = false
                val reason = o.optString("reason")
                val msg = when (reason) {
                    "version" -> "versi tidak cocok — server v" + o.optString("server", "?") +
                        ", apk v" + o.optString("app", "?") +
                        ". perbarui apk dan folder server ke versi yang sama."
                    "rate_limit" -> "terlalu banyak percobaan gagal — tunggu sebentar lalu coba lagi"
                    else -> "pin salah"
                }
                _connectionState.value = ConnectionState.Error(msg)
                onState?.invoke(false, msg)
                webSocket.close(1000, null)
            }
            "pong" -> {
                if (pingSentAt > 0L) {
                    val ms = (System.currentTimeMillis() - pingSentAt).toInt().coerceAtMost(9999)
                    _pingMsRaw = ms
                    _pingMs.value = ms
                    pingSentAt = 0L
                    PingLog.record(ms, transport, hostName)
                    onPing?.invoke(ms)
                }
            }
            "vol" -> {
                if (!o.isNull("v")) {
                    volume = o.optInt("v", volume)
                    _connectionInfo.value = _connectionInfo.value.copy(volume = volume)
                }
                _serverMessages.tryEmit(o)
                onMessage?.invoke(o)
            }
            "scrollinfo" -> {
                val pos = o.optInt("pos", -1)
                if (pos >= 0) {
                    _scrollInfo.value = ScrollInfo(
                        pos = pos,
                        min = o.optInt("min", 0),
                        max = o.optInt("max", 100),
                        page = o.optInt("page", 1)
                    )
                } else {
                    _scrollInfo.value = null  // sembunyikan indikator
                }
            }
            // ── v3.7: clipboard & now playing ──
            "clip" -> {
                val hasS = o.has("s") && !o.isNull("s")
                val s = if (hasS) o.optString("s") else null
                val img = if (o.has("img") && !o.isNull("img")) o.optString("img") else null
                // Push otomatis dari server {"t":"clip","s":...,"auto":true}
                // tidak menyertakan "ok" - kehadiran "s"/"img" yang valid cukup
                // untuk menganggap pesan ini sah.
                val ok = if (o.has("ok")) o.optBoolean("ok", false)
                         else !(s.isNullOrEmpty() && img.isNullOrEmpty())
                val auto = o.optBoolean("auto", false)
                _clipboardContent.value = ClipboardState(
                    content = s, ok = ok, auto = auto, imgB64 = img)
                // Diteruskan supaya ClipboardSync bisa menulis ke clipboard HP.
                _serverMessages.tryEmit(o)
                onMessage?.invoke(o)
            }
            "np" -> {
                _nowPlaying.value = NowPlaying(
                    ok = o.optBoolean("ok", false),
                    title = o.optString("title", ""),
                    artist = o.optString("artist", ""),
                    album = o.optString("album", ""),
                    playing = o.optBoolean("playing", false),
                    lengthUs = o.optLong("length_us", 0L),
                    posUs = o.optLong("pos_us", 0L),
                    canSeek = o.optBoolean("canseek", false),
                    msg = o.optString("msg", "")
                )
            }
            "clipset_result", "clipsync_result", "npseek_result" -> {
                _serverMessages.tryEmit(o)
                onMessage?.invoke(o)
            }
            else -> {
                _serverMessages.tryEmit(o)
                onMessage?.invoke(o)
            }
        }
    }

    private fun hexToBytes(hex: String): ByteArray {
        val out = ByteArray(hex.length / 2)
        for (i in out.indices) {
            out[i] = ((Character.digit(hex[i * 2], 16) shl 4) +
                      Character.digit(hex[i * 2 + 1], 16)).toByte()
        }
        return out
    }

    private fun tryReconnect(): Boolean {
        if (manualClose || !autoReconnect || lastHost.isEmpty()) return false
        if (retryCount >= 5) return false
        retryCount++
        _reconnectingTo.value = retryCount
        val delay = (retryCount * 900L).coerceAtMost(4000L)
        onReconnecting?.invoke(retryCount)
        android.os.Handler(android.os.Looper.getMainLooper())
            .postDelayed({ if (!manualClose && !connected) openSocket() }, delay)
        return true
    }

    private fun closeQuietly() {
        ws?.close(1000, null)
        ws = null
    }
}
