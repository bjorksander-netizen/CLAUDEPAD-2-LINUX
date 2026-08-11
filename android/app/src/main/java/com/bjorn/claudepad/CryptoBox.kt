package com.bjorn.claudepad

import android.util.Base64
import java.security.KeyFactory
import java.security.SecureRandom
import java.security.spec.X509EncodedKeySpec
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.OAEPParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.PSource
import javax.crypto.spec.SecretKeySpec
import java.security.spec.MGF1ParameterSpec

/**
 * Enkripsi lalu lintas — pasangan Kotlin dari server/crypto_box.py.
 *
 * Sebelum v3.0 semua perintah dikirim JSON polos: penyadap WiFi bisa membaca
 * apa yang diketik. Kini kunci sesi diturunkan dari PIN/token + garam acak
 * memakai PBKDF2, dan tidak pernah dikirim. Tiap pesan dienkripsi ChaCha20
 * lalu diberi tag HMAC-SHA256 (encrypt-then-MAC) dengan nomor urut anti-ulang.
 *
 * Harus identik byte-per-byte dengan sisi Python, karena keduanya menurunkan
 * kunci sendiri dari rahasia yang sama.
 */
class CryptoBox private constructor(key: ByteArray) {

    private val encKey = sha256(key + "|enc".toByteArray())
    private val macKey = sha256(key + "|mac".toByteArray())
    private var sendSeq = 0L
    private var recvSeq = -1L
    private val rnd = SecureRandom()

    companion object {
        private const val PBKDF2_ROUNDS = 60_000
        private const val KEY_LEN = 32
        const val TAG_LEN = 32

        fun derive(secret: String, salt: ByteArray): CryptoBox {
            val spec = PBEKeySpec(secret.toCharArray(), salt, PBKDF2_ROUNDS, KEY_LEN * 8)
            val key = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
                .generateSecret(spec).encoded
            return CryptoBox(key)
        }

        /**
         * Enkripsi data dengan RSA public key (OAEP + SHA-256).
         * Dipakai untuk mengenkripsi PIN/token sebelum dikirim ke server.
         * pubKeyBase64: public key dalam format base64 (tanpa header PEM).
         */
        fun encryptWithPublicKey(pubKeyBase64: String, data: ByteArray): ByteArray {
            val keyBytes = Base64.decode(pubKeyBase64, Base64.DEFAULT)
            val keyFactory = KeyFactory.getInstance("RSA")
            val spec = X509EncodedKeySpec(keyBytes)
            val publicKey = keyFactory.generatePublic(spec)
            val cipher = Cipher.getInstance("RSA/ECB/OAEPWithSHA-256AndMGF1Padding")
            cipher.init(
                Cipher.ENCRYPT_MODE, publicKey,
                OAEPParameterSpec(
                    "SHA-256", "MGF1",
                    MGF1ParameterSpec("SHA-256"),
                    PSource.PSpecified(ByteArray(0))
                )
            )
            return cipher.doFinal(data)
        }

        private fun sha256(b: ByteArray): ByteArray =
            java.security.MessageDigest.getInstance("SHA-256").digest(b)
    }

    /** seq(8) | nonce(12) | ciphertext | tag(32) */
    fun seal(plain: ByteArray): ByteArray {
        sendSeq++
        val seq = longToBytes(sendSeq)
        val nonce = ByteArray(12).also { rnd.nextBytes(it) }
        val ct = chacha20(encKey, nonce, plain, 1)
        val body = seq + nonce + ct
        return body + hmac(macKey, body)
    }

    fun open(blob: ByteArray): ByteArray {
        if (blob.size < 8 + 12 + TAG_LEN) throw SecurityException("paket terlalu pendek")
        val body = blob.copyOfRange(0, blob.size - TAG_LEN)
        val tag = blob.copyOfRange(blob.size - TAG_LEN, blob.size)
        if (!constantEquals(tag, hmac(macKey, body)))
            throw SecurityException("tag tidak cocok")
        val seq = bytesToLong(body, 0)
        if (seq <= recvSeq) throw SecurityException("pesan lama diputar ulang")
        recvSeq = seq
        val nonce = body.copyOfRange(8, 20)
        return chacha20(encKey, nonce, body.copyOfRange(20, body.size), 1)
    }

    // ---------------------------------------------------------- ChaCha20 --
    private fun chacha20(key: ByteArray, nonce: ByteArray, data: ByteArray,
                         counter: Int): ByteArray {
        val out = ByteArray(data.size)
        var i = 0
        while (i < data.size) {
            val block = chachaBlock(key, counter + i / 64, nonce)
            var j = 0
            while (j < 64 && i + j < data.size) {
                out[i + j] = (data[i + j].toInt() xor block[j].toInt()).toByte()
                j++
            }
            i += 64
        }
        return out
    }

    private fun rotl(v: Int, c: Int) = (v shl c) or (v ushr (32 - c))

    private fun chachaBlock(key: ByteArray, counter: Int, nonce: ByteArray): ByteArray {
        val state = IntArray(16)
        state[0] = 0x61707865; state[1] = 0x3320646e
        state[2] = 0x79622d32; state[3] = 0x6b206574
        for (k in 0 until 8) state[4 + k] = leInt(key, k * 4)
        state[12] = counter
        for (k in 0 until 3) state[13 + k] = leInt(nonce, k * 4)
        val w = state.copyOf()
        repeat(10) {
            qr(w, 0, 4, 8, 12); qr(w, 1, 5, 9, 13)
            qr(w, 2, 6, 10, 14); qr(w, 3, 7, 11, 15)
            qr(w, 0, 5, 10, 15); qr(w, 1, 6, 11, 12)
            qr(w, 2, 7, 8, 13); qr(w, 3, 4, 9, 14)
        }
        val out = ByteArray(64)
        for (k in 0 until 16) {
            val v = w[k] + state[k]
            out[k * 4] = v.toByte()
            out[k * 4 + 1] = (v ushr 8).toByte()
            out[k * 4 + 2] = (v ushr 16).toByte()
            out[k * 4 + 3] = (v ushr 24).toByte()
        }
        return out
    }

    private fun qr(x: IntArray, a: Int, b: Int, c: Int, d: Int) {
        x[a] += x[b]; x[d] = rotl(x[d] xor x[a], 16)
        x[c] += x[d]; x[b] = rotl(x[b] xor x[c], 12)
        x[a] += x[b]; x[d] = rotl(x[d] xor x[a], 8)
        x[c] += x[d]; x[b] = rotl(x[b] xor x[c], 7)
    }

    private fun leInt(b: ByteArray, off: Int): Int =
        (b[off].toInt() and 0xFF) or
        ((b[off + 1].toInt() and 0xFF) shl 8) or
        ((b[off + 2].toInt() and 0xFF) shl 16) or
        ((b[off + 3].toInt() and 0xFF) shl 24)

    // ---------------------------------------------------------- helpers ---
    private fun hmac(key: ByteArray, data: ByteArray): ByteArray {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key, "HmacSHA256"))
        return mac.doFinal(data)
    }

    private fun constantEquals(a: ByteArray, b: ByteArray): Boolean {
        if (a.size != b.size) return false
        var r = 0
        for (i in a.indices) r = r or (a[i].toInt() xor b[i].toInt())
        return r == 0
    }

    private fun longToBytes(v: Long): ByteArray {
        val o = ByteArray(8)
        for (i in 0 until 8) o[i] = (v ushr (56 - i * 8)).toByte()
        return o
    }

    private fun bytesToLong(b: ByteArray, off: Int): Long {
        var v = 0L
        for (i in 0 until 8) v = (v shl 8) or (b[off + i].toLong() and 0xFF)
        return v
    }
}
