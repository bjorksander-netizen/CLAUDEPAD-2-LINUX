package com.bjorn.claudepad

import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/**
 * Wake-on-LAN — FITUR EKSPERIMENTAL.
 *
 * Mengirim "magic packet" ke alamat MAC PC. Keberhasilannya bergantung pada
 * hal-hal di luar kendali aplikasi: WoL harus diaktifkan di BIOS/UEFI, pada
 * properti adapter jaringan Windows, dan umumnya hanya bekerja lewat kabel
 * LAN — banyak adapter WiFi tidak mendukungnya sama sekali.
 */
object WakeOnLan {

    fun send(mac: String, broadcast: String = "255.255.255.255"): Result<Unit> {
        return try {
            val bytes = parseMac(mac) ?: return Result.failure(
                IllegalArgumentException("format MAC tidak valid"))

            // magic packet: 6 byte 0xFF lalu MAC diulang 16 kali
            val payload = ByteArray(6 + 16 * 6)
            for (i in 0 until 6) payload[i] = 0xFF.toByte()
            for (i in 0 until 16) System.arraycopy(bytes, 0, payload, 6 + i * 6, 6)

            // dikirim ke beberapa port yang lazim dipakai perangkat WoL
            for (port in intArrayOf(9, 7)) {
                DatagramSocket().use { sock ->
                    sock.broadcast = true
                    sock.send(DatagramPacket(payload, payload.size,
                        InetAddress.getByName(broadcast), port))
                }
            }
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private fun parseMac(mac: String): ByteArray? {
        val parts = mac.split(':', '-')
        if (parts.size != 6) return null
        return try {
            ByteArray(6) { parts[it].toInt(16).toByte() }
        } catch (e: Exception) {
            null
        }
    }
}
