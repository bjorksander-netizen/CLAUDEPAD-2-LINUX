package com.bjorn.claudepad

import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress

/** Pencarian server CLAUDEPAD lewat broadcast UDP per-interface. */
object Discovery {

    /** Kembalikan IP PC pertama yang menjawab, atau null. */
    fun findFirst(): String? {
        val sockets = mutableListOf<DatagramSocket>()
        try {
            val ifaces = Net.interfaces()
            for (i in ifaces) {
                try {
                    val ds = DatagramSocket(null)
                    ds.reuseAddress = true; ds.broadcast = true
                    ds.bind(InetSocketAddress(i.address, 0))
                    ds.soTimeout = 700
                    sockets.add(ds)
                } catch (e: Exception) { }
            }
            if (sockets.isEmpty()) {
                sockets.add(DatagramSocket().apply { broadcast = true; soTimeout = 700 })
            }
            val msg = "DISCOVER_CLAUDEPAD".toByteArray()
            val buf = ByteArray(256)
            repeat(3) {
                for ((idx, ds) in sockets.withIndex()) {
                    val targets = mutableSetOf<InetAddress>()
                    ifaces.getOrNull(idx)?.broadcast?.let { targets.add(it) }
                    try { targets.add(InetAddress.getByName("255.255.255.255")) } catch (e: Exception) {}
                    for (t in targets) {
                        try { ds.send(DatagramPacket(msg, msg.size, t, 8766)) } catch (e: Exception) {}
                    }
                }
                for (ds in sockets) {
                    try {
                        val resp = DatagramPacket(buf, buf.size)
                        ds.receive(resp)
                        val parts = String(resp.data, 0, resp.length).split("|")
                        if (parts.isNotEmpty() && parts[0] == "CLAUDEPAD")
                            return resp.address.hostAddress
                    } catch (e: Exception) { }
                }
            }
        } catch (e: Exception) {
        } finally {
            for (ds in sockets) try { ds.close() } catch (e: Exception) {}
        }
        return null
    }
}
