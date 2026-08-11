package com.bjorn.claudepad

import java.net.Inet4Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket
import javax.net.SocketFactory

/**
 * Penanganan routing jaringan.
 *
 * MASALAH YANG DIPECAHKAN:
 * Saat HP menjadi hotspot sambil data seluler menyala, Android mengikat
 * socket aplikasi ke jaringan default = SELULER. Akibatnya paket menuju PC
 * (yang menempel di hotspot, mis. 192.168.43.x) malah dikirim ke internet
 * dan koneksi gagal dengan pesan seperti
 *   "failed to connect to /192.168.43.1 ... from /10.240.31.97".
 *
 * SOLUSI: cari alamat lokal HP yang berada di SUBNET YANG SAMA dengan tujuan,
 * lalu ikat socket ke alamat itu. Paket dipaksa keluar lewat interface hotspot.
 */
object Net {

    data class Iface(val name: String, val address: Inet4Address, val prefix: Int) {
        val broadcast: InetAddress?
            get() = try { broadcastOf(address, prefix) } catch (e: Exception) { null }
    }

    /** Semua interface IPv4 yang aktif (loopback dibuang). */
    fun interfaces(): List<Iface> {
        val out = mutableListOf<Iface>()
        try {
            val ifs = NetworkInterface.getNetworkInterfaces() ?: return out
            for (ni in ifs) {
                if (!ni.isUp || ni.isLoopback) continue
                for (ia in ni.interfaceAddresses) {
                    val a = ia.address
                    if (a is Inet4Address && !a.isLoopbackAddress) {
                        out.add(Iface(ni.name, a, ia.networkPrefixLength.toInt()))
                    }
                }
            }
        } catch (e: Exception) { }
        return out
    }

    private fun toInt(a: InetAddress): Int {
        val b = a.address
        return ((b[0].toInt() and 0xFF) shl 24) or
               ((b[1].toInt() and 0xFF) shl 16) or
               ((b[2].toInt() and 0xFF) shl 8) or
               (b[3].toInt() and 0xFF)
    }

    private fun broadcastOf(addr: Inet4Address, prefix: Int): InetAddress {
        val mask = if (prefix == 0) 0 else (-1 shl (32 - prefix))
        val bc = toInt(addr) or mask.inv()
        return InetAddress.getByAddress(byteArrayOf(
            (bc ushr 24).toByte(), (bc ushr 16).toByte(),
            (bc ushr 8).toByte(), bc.toByte()))
    }

    fun sameSubnet(a: InetAddress, b: InetAddress, prefix: Int): Boolean {
        if (prefix !in 1..32) return false
        val mask = -1 shl (32 - prefix)
        return (toInt(a) and mask) == (toInt(b) and mask)
    }

    /** Alamat lokal yang satu subnet dengan [target], atau null kalau tak ada. */
    fun localAddressFor(target: String): Inet4Address? {
        val dst = try { InetAddress.getByName(target) } catch (e: Exception) { return null }
        if (dst !is Inet4Address) return null
        for (i in interfaces()) {
            if (sameSubnet(i.address, dst, i.prefix)) return i.address
        }
        return null
    }

    /**
     * SocketFactory yang mengikat socket keluar ke [local].
     * Inilah yang memaksa lalu lintas lewat interface hotspot.
     */
    class BoundSocketFactory(private val local: InetAddress) : SocketFactory() {
        private fun bound(): Socket {
            val s = Socket()
            try { s.bind(InetSocketAddress(local, 0)) } catch (e: Exception) { }
            return s
        }
        override fun createSocket(): Socket = bound()
        override fun createSocket(host: String, port: Int): Socket =
            bound().apply { connect(InetSocketAddress(host, port), 8000) }
        override fun createSocket(host: String, port: Int,
                                  localHost: InetAddress?, localPort: Int): Socket =
            createSocket(host, port)
        override fun createSocket(host: InetAddress, port: Int): Socket =
            bound().apply { connect(InetSocketAddress(host, port), 8000) }
        override fun createSocket(host: InetAddress, port: Int,
                                  localAddr: InetAddress?, localPort: Int): Socket =
            createSocket(host, port)
    }

    /** Ringkasan interface untuk laporan diagnosa. */
    fun describe(): String = interfaces().joinToString("\n") {
        "  ${it.name}  ${it.address.hostAddress}/${it.prefix}  bc=${it.broadcast?.hostAddress ?: "-"}"
    }.ifEmpty { "  (tidak ada interface aktif)" }
}
