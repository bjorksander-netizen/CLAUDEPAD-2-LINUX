package com.bjorn.claudepad

import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Binary protocol encoder/decoder — pasangan Kotlin dari server/binary_protocol.py.
 *
 * v3.3: Menggantikan JSON untuk command yang sering dikirim (move, scroll, click).
 * Paket 4-10x lebih kecil dari JSON, mengurangi latency & CPU.
 *
 * Wire format: [CMD_ID: 1 byte][PAYLOAD: 0..N bytes]
 * Semua integer multi-byte memakai little-endian.
 */
object BinaryProtocol {

    // ── Command IDs ──
    private const val CMD_MOVE     = 0x01
    private const val CMD_CLICK    = 0x02
    private const val CMD_DOWN     = 0x03
    private const val CMD_UP       = 0x04
    private const val CMD_SCROLL   = 0x05
    private const val CMD_ZOOM     = 0x06
    private const val CMD_GESTURE  = 0x07
    private const val CMD_TEXT     = 0x08
    private const val CMD_KEY      = 0x09
    private const val CMD_MEDIA    = 0x0A
    private const val CMD_VOLSET   = 0x0B
    private const val CMD_VOLGET   = 0x0C
    private const val CMD_RADIO    = 0x0D
    private const val CMD_POWER    = 0x0E
    private const val CMD_BRIGHT   = 0x0F
    private const val CMD_PING     = 0x10
    const val CMD_SCROLLINFO = 0x13  // server -> client: posisi scroll window aktif
    private const val KEY_CUSTOM   = 0x00

    // ── Lookup tables ──
    private val BUTTON_IDS = mapOf("left" to 0, "right" to 1, "middle" to 2)
    private val BUTTON_NAMES = BUTTON_IDS.entries.associate { (k, v) -> v to k }

    private val GESTURE_IDS = mapOf("taskview" to 0, "showdesktop" to 1, "appnext" to 2, "appprev" to 3)
    private val GESTURE_NAMES = GESTURE_IDS.entries.associate { (k, v) -> v to k }

    private val MEDIA_IDS = mapOf(
        "playpause" to 0, "next" to 1, "prev" to 2, "stop" to 3,
        "volup" to 4, "voldown" to 5, "mute" to 6
    )
    private val MEDIA_NAMES = MEDIA_IDS.entries.associate { (k, v) -> v to k }

    private val RADIO_IDS = mapOf("wifi" to 0, "bluetooth" to 1, "hotspot" to 2)
    private val RADIO_NAMES = RADIO_IDS.entries.associate { (k, v) -> v to k }

    private val POWER_IDS = mapOf("shutdown" to 0, "restart" to 1, "sleep" to 2, "lock" to 3)
    private val POWER_NAMES = POWER_IDS.entries.associate { (k, v) -> v to k }

    private val VK_IDS = mutableMapOf(
        "enter" to 0x0D, "esc" to 0x1B, "tab" to 0x09, "backspace" to 0x08,
        "delete" to 0x2E, "space" to 0x20, "up" to 0x26, "down" to 0x28,
        "left" to 0x25, "right" to 0x27, "home" to 0x24, "end" to 0x23,
        "pgup" to 0x21, "pgdn" to 0x22, "win" to 0x5B, "ctrl" to 0x11,
        "alt" to 0x12, "shift" to 0x10, "insert" to 0x2D, "capslock" to 0x14,
        "printscreen" to 0x2C, "d" to 0x44
    )
    private val VK_NAMES = mutableMapOf<Int, String>()

    init {
        // Isi VK_NAMES kebalikan dari VK_IDS + tambah F1..F13
        for ((k, v) in VK_IDS) VK_NAMES[v] = k
        for (i in 1..13) {
            VK_IDS["f$i"] = 0x6F + i
            VK_NAMES[0x6F + i] = "f$i"
        }
    }

    /** Encode JSON command ke binary. Kembalikan null kalau tidak bisa di-encode. */
    fun encode(msg: JSONObject): ByteArray? {
        val t = msg.optString("t")
        return when (t) {
            "move" -> {
                val dx = msg.optInt("dx", 0).coerceIn(-32768, 32767).toShort()
                val dy = msg.optInt("dy", 0).coerceIn(-32768, 32767).toShort()
                ByteBuffer.allocate(5).order(ByteOrder.LITTLE_ENDIAN)
                    .put(CMD_MOVE.toByte()).putShort(dx).putShort(dy).array()
            }
            "click" -> {
                val bid = BUTTON_IDS[msg.optString("b", "left")] ?: 0
                val dbl = if (msg.optBoolean("double", false)) 1 else 0
                byteArrayOf(CMD_CLICK.toByte(), bid.toByte(), dbl.toByte())
            }
            "down" -> {
                val bid = BUTTON_IDS[msg.optString("b", "left")] ?: 0
                byteArrayOf(CMD_DOWN.toByte(), bid.toByte())
            }
            "up" -> {
                val bid = BUTTON_IDS[msg.optString("b", "left")] ?: 0
                byteArrayOf(CMD_UP.toByte(), bid.toByte())
            }
            "scroll" -> {
                val dy = msg.optInt("dy", 0).coerceIn(-32768, 32767).toShort()
                val dx = msg.optInt("dx", 0).coerceIn(-32768, 32767).toShort()
                ByteBuffer.allocate(5).order(ByteOrder.LITTLE_ENDIAN)
                    .put(CMD_SCROLL.toByte()).putShort(dy).putShort(dx).array()
            }
            "zoom" -> {
                val d = msg.optInt("dir", 1).coerceIn(-128, 127).toByte()
                byteArrayOf(CMD_ZOOM.toByte(), d)
            }
            "gesture" -> {
                val gid = GESTURE_IDS[msg.optString("g", "")] ?: return null
                byteArrayOf(CMD_GESTURE.toByte(), gid.toByte())
            }
            "text" -> {
                val s = msg.optString("s", "")
                val encoded = s.toByteArray(Charsets.UTF_8)
                if (encoded.size > 65535) return null
                val buf = ByteBuffer.allocate(3 + encoded.size).order(ByteOrder.LITTLE_ENDIAN)
                buf.put(CMD_TEXT.toByte())
                buf.putShort(encoded.size.toShort())
                buf.put(encoded)
                buf.array()
            }
            "key" -> {
                val k = msg.optString("k", "")
                val mods = msg.optJSONArray("mods")
                val modList = mutableListOf<Byte>()
                if (mods != null) {
                    for (i in 0 until mods.length()) {
                        val m = mods.optString(i, "")
                        modList.add((VK_IDS[m.lowercase()] ?: 0x11).toByte())
                    }
                }
                if (modList.size > 255) return null
                val vk = VK_IDS[k.lowercase()]
                if (vk != null) {
                    val buf = ByteBuffer.allocate(3 + modList.size).order(ByteOrder.LITTLE_ENDIAN)
                    buf.put(CMD_KEY.toByte())
                    buf.put(vk.toByte())
                    buf.put(modList.size.toByte())
                    for (m in modList) buf.put(m)
                    return buf.array()
                }
                // Custom UTF-8 key
                val keyBytes = k.toByteArray(Charsets.UTF_8)
                if (keyBytes.size > 65535) return null
                val buf = ByteBuffer.allocate(5 + keyBytes.size + modList.size).order(ByteOrder.LITTLE_ENDIAN)
                buf.put(CMD_KEY.toByte())
                buf.put(KEY_CUSTOM.toByte())
                buf.putShort(keyBytes.size.toShort())
                buf.put(keyBytes)
                buf.put(modList.size.toByte())
                for (m in modList) buf.put(m)
                buf.array()
            }
            "media" -> {
                val mid = MEDIA_IDS[msg.optString("a", "")] ?: return null
                byteArrayOf(CMD_MEDIA.toByte(), mid.toByte())
            }
            "volset" -> {
                val v = msg.optInt("v", 50).coerceIn(0, 100).toByte()
                byteArrayOf(CMD_VOLSET.toByte(), v)
            }
            "volget" -> byteArrayOf(CMD_VOLGET.toByte())
            "radio" -> {
                val did = RADIO_IDS[msg.optString("d", "")] ?: return null
                byteArrayOf(CMD_RADIO.toByte(), did.toByte())
            }
            "power" -> {
                val aid = POWER_IDS[msg.optString("a", "")] ?: return null
                byteArrayOf(CMD_POWER.toByte(), aid.toByte())
            }
            "bright" -> {
                val d = msg.optInt("d", 10).coerceIn(-128, 127).toByte()
                byteArrayOf(CMD_BRIGHT.toByte(), d)
            }
            "ping" -> byteArrayOf(CMD_PING.toByte())
            else -> null
        }
    }
}

/** Informasi posisi scroll dari server (CMD_SCROLLINFO). */
data class ScrollInfo(val pos: Int, val min: Int, val max: Int, val page: Int)

/** Decode binary CMD_SCROLLINFO payload (16 bytes: 4 x little-endian Int). */
fun decodeScrollInfo(data: ByteBuffer): ScrollInfo? {
    if (data.remaining() < 16) return null
    return try {
        ScrollInfo(
            pos = data.getInt(),
            min = data.getInt(),
            max = data.getInt(),
            page = data.getInt()
        )
    } catch (e: Exception) { null }
}
