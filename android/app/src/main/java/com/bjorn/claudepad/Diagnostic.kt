package com.bjorn.claudepad

import android.content.Context
import java.io.BufferedReader
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket

/**
 * Diagnosa koneksi bertahap. Setiap langkah dilaporkan sendiri sehingga
 * jelas DI MANA koneksi putus, bukan sekadar "gagal".
 */
object Diagnostic {

    fun run(ctx: Context, targetIp: String): String {
        val sb = StringBuilder()
        fun line(s: String = "") = sb.append(s).append('\n')

        line("TARGET : ${if (targetIp.isEmpty()) "(kosong)" else targetIp}:8765")
        line("APK    : v${appVersion(ctx)}")
        line()

        // ---- 1. Interface jaringan HP ----
        line("1. INTERFACE HP")
        val ifaces = Net.interfaces()
        if (ifaces.isEmpty()) {
            line("   TIDAK ADA interface aktif — WiFi/hotspot mati?")
        } else {
            for (i in ifaces) {
                val tag = when {
                    i.name.startsWith("ap") || i.name.startsWith("swlan") -> "  <- hotspot"
                    i.name.startsWith("wlan") -> "  <- wifi"
                    i.name.startsWith("rmnet") || i.name.startsWith("ccmni") -> "  <- seluler"
                    else -> ""
                }
                line("   ${i.name}  ${i.address.hostAddress}/${i.prefix}$tag")
            }
        }
        line()

        if (targetIp.isEmpty()) {
            line("Isi alamat IP PC dulu untuk melanjutkan diagnosa.")
            return sb.toString()
        }

        // ---- 2. Pemilihan rute ----
        line("2. RUTE KE PC")
        val local = Net.localAddressFor(targetIp)
        if (local != null) {
            line("   OK — keluar lewat ${local.hostAddress}")
            line("   (satu subnet dengan PC, paket tidak lari ke seluler)")
        } else {
            line("   PERINGATAN — tidak ada interface HP yang satu subnet")
            line("   dengan $targetIp.")
            line("   Artinya IP PC itu kemungkinan SALAH — biasanya karena")
            line("   yang tertulis di server adalah adapter virtual")
            line("   (WSL/Hyper-V/VirtualBox, sering 172.x.x.x).")
            line("   Pakai IP yang TIDAK ditandai virtual di jendela server.")
        }
        line()

        // ---- 3. Tes TCP ----
        line("3. TES PORT 8765 (TCP)")
        val tcp = testTcp(targetIp, 8765, local)
        line("   $tcp")
        line()

        // ---- 4. Tes HTTP health ----
        line("4. TES BALASAN SERVER (HTTP)")
        line("   ${testHttp(targetIp, local)}")
        line()

        // ---- 5. Tes discovery ----
        line("5. TES PENCARIAN (UDP 8766)")
        line("   ${testDiscovery()}")
        line()

        // ---- kesimpulan ----
        line("KESIMPULAN")
        when {
            tcp.startsWith("OK") -> line("   Jaringan sehat. Kalau aplikasi tetap gagal,\n" +
                                         "   cek kecocokan versi APK dengan server.")
            local == null -> line("   IP PC salah. Buka jendela server, pakai alamat\n" +
                                  "   yang TIDAK berlabel virtual.")
            else -> line("   Rute sudah benar tetapi port tertutup.\n" +
                         "   Di jendela server klik 'Perbaiki Firewall',\n" +
                         "   setujui prompt Administrator, lalu coba lagi.")
        }
        return sb.toString()
    }

    private fun testTcp(ip: String, port: Int, local: InetAddress?): String {
        return try {
            val s = Socket()
            if (local != null) s.bind(InetSocketAddress(local, 0))
            s.connect(InetSocketAddress(ip, port), 5000)
            s.close()
            "OK — port terbuka dan menerima koneksi"
        } catch (e: Exception) {
            "GAGAL — ${e.message ?: e.javaClass.simpleName}"
        }
    }

    private fun testHttp(ip: String, local: InetAddress?): String {
        return try {
            val s = Socket()
            if (local != null) s.bind(InetSocketAddress(local, 0))
            s.connect(InetSocketAddress(ip, 8765), 5000)
            s.soTimeout = 5000
            s.getOutputStream().write(
                "GET / HTTP/1.1\r\nHost: $ip\r\nConnection: close\r\n\r\n".toByteArray())
            val reader = s.getInputStream().bufferedReader()
            val body = readSome(reader)
            s.close()
            if (body.contains("CLAUDEPAD")) {
                val ver = Regex("server\\s*:\\s*v([0-9.]+)").find(body)?.groupValues?.get(1)
                "OK — server menjawab" + (ver?.let { " (v$it)" } ?: "")
            } else "Terhubung tapi balasan tak dikenali"
        } catch (e: Exception) {
            "GAGAL — ${e.message ?: e.javaClass.simpleName}"
        }
    }

    private fun readSome(r: BufferedReader): String {
        val sb = StringBuilder()
        var n = 0
        while (n < 40) {
            val l = r.readLine() ?: break
            sb.append(l).append('\n'); n++
        }
        return sb.toString()
    }

    private fun testDiscovery(): String {
        val sockets = mutableListOf<DatagramSocket>()
        return try {
            val ifaces = Net.interfaces()
            for (i in ifaces) {
                try {
                    val ds = DatagramSocket(null)
                    ds.reuseAddress = true; ds.broadcast = true
                    ds.bind(InetSocketAddress(i.address, 0))
                    ds.soTimeout = 900
                    sockets.add(ds)
                } catch (e: Exception) { }
            }
            val msg = "DISCOVER_CLAUDEPAD".toByteArray()
            for ((idx, ds) in sockets.withIndex()) {
                ifaces.getOrNull(idx)?.broadcast?.let {
                    try { ds.send(DatagramPacket(msg, msg.size, it, 8766)) } catch (e: Exception) {}
                }
                try { ds.send(DatagramPacket(msg, msg.size,
                    InetAddress.getByName("255.255.255.255"), 8766)) } catch (e: Exception) {}
            }
            val buf = ByteArray(256)
            for (ds in sockets) {
                try {
                    val p = DatagramPacket(buf, buf.size)
                    ds.receive(p)
                    return "OK — " + String(p.data, 0, p.length) +
                           " dari " + (p.address.hostAddress ?: "?")
                } catch (e: Exception) { }
            }
            "Tidak ada balasan (firewall UDP atau server tidak jalan)"
        } catch (e: Exception) {
            "GAGAL — ${e.message}"
        } finally {
            for (ds in sockets) try { ds.close() } catch (e: Exception) {}
        }
    }

    fun appVersion(ctx: Context): String = try {
        ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?"
    } catch (e: Exception) { "?" }
}
