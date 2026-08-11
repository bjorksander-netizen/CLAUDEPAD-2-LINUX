package com.bjorn.claudepad

import android.content.Context
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Riwayat latensi koneksi, disimpan untuk keperluan diagnosis.
 * Hanya disimpan di memori aplikasi dan dibatasi jumlahnya supaya ringan;
 * pengguna dapat mengekspornya menjadi teks lalu membagikannya.
 */
object PingLog {

    data class Entry(val time: Long, val ms: Int, val transport: String, val host: String)

    private const val MAX = 600          // ~20 menit pada interval 2 detik
    private val entries = ArrayList<Entry>()

    @Synchronized
    fun record(ms: Int, transport: String, host: String) {
        if (entries.size >= MAX) entries.removeAt(0)
        entries.add(Entry(System.currentTimeMillis(), ms, transport, host))
    }

    @Synchronized
    fun clear() = entries.clear()

    @Synchronized
    fun size() = entries.size

    @Synchronized
    fun snapshot(): List<Entry> = ArrayList(entries)

    /** Ringkasan singkat untuk ditampilkan di halaman setting. */
    @Synchronized
    fun summary(): String {
        if (entries.isEmpty()) return "belum ada data"
        val values = entries.map { it.ms }
        val avg = values.average()
        return "${entries.size} sampel · rata-rata ${avg.toInt()}ms · " +
               "min ${values.min()}ms · maks ${values.max()}ms"
    }

    /** Laporan lengkap siap disimpan atau dibagikan. */
    fun report(ctx: Context): String {
        val list = snapshot()
        val fmt = SimpleDateFormat("HH:mm:ss", Locale.US)
        val sb = StringBuilder()
        sb.append("CLAUDEPAD — log ping\n")
        sb.append("versi apk : v${Diagnostic.appVersion(ctx)}\n")
        sb.append("dibuat    : ")
          .append(SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date()))
          .append('\n')

        if (list.isEmpty()) {
            sb.append("\nBelum ada data ping. Hubungkan lewat WiFi/Hotspot dahulu.\n")
            return sb.toString()
        }

        val values = list.map { it.ms }
        val avg = values.average()
        val sorted = values.sorted()
        val median = sorted[sorted.size / 2]
        // jitter = rata-rata selisih antar sampel berurutan
        var jitter = 0.0
        for (i in 1 until values.size) jitter += Math.abs(values[i] - values[i - 1])
        if (values.size > 1) jitter /= (values.size - 1)

        sb.append("pc        : ").append(list.last().host).append('\n')
        sb.append("jalur     : ").append(list.last().transport).append("\n\n")
        sb.append("RINGKASAN\n")
        sb.append("  sampel  : ").append(list.size).append('\n')
        sb.append("  rata2   : ").append(String.format(Locale.US, "%.1f ms", avg)).append('\n')
        sb.append("  median  : ").append(median).append(" ms\n")
        sb.append("  min/maks: ").append(sorted.first()).append(" / ")
          .append(sorted.last()).append(" ms\n")
        sb.append("  jitter  : ").append(String.format(Locale.US, "%.1f ms", jitter)).append('\n')
        sb.append("  >180ms  : ").append(values.count { it > 180 }).append(" sampel\n\n")

        sb.append("RINCIAN\n")
        for (e in list) {
            sb.append("  ").append(fmt.format(Date(e.time)))
              .append("  ").append(e.ms).append(" ms\n")
        }
        return sb.toString()
    }
}
