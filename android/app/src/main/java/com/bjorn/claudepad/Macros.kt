package com.bjorn.claudepad

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * Makro kustom: satu pintasan keyboard per tombol, ditentukan pengguna.
 * Server sudah bisa memproses {key, mods}, jadi makro cukup disimpan dan
 * dikirim seperti pintasan bawaan.
 */
object Macros {

    data class Macro(
        val label: String,          // teks tombol, mis. "Save" atau "⛶"
        val key: String,            // tombol utama, mis. "s", "f4", "enter"
        val ctrl: Boolean,
        val shift: Boolean,
        val alt: Boolean,
        val win: Boolean
    ) {
        fun mods(): List<String> = buildList {
            if (ctrl) add("ctrl"); if (shift) add("shift")
            if (alt) add("alt"); if (win) add("win")
        }

        /** Ringkasan kombinasi untuk ditampilkan, mis. "Ctrl+Shift+S". */
        fun combo(): String {
            val parts = mutableListOf<String>()
            if (ctrl) parts.add("Ctrl"); if (shift) parts.add("Shift")
            if (alt) parts.add("Alt"); if (win) parts.add("Win")
            parts.add(key.uppercase())
            return parts.joinToString("+")
        }

        fun toJson(): JSONObject = JSONObject()
            .put("label", label).put("key", key)
            .put("ctrl", ctrl).put("shift", shift)
            .put("alt", alt).put("win", win)

        companion object {
            fun fromJson(o: JSONObject) = Macro(
                o.optString("label"), o.optString("key"),
                o.optBoolean("ctrl"), o.optBoolean("shift"),
                o.optBoolean("alt"), o.optBoolean("win"))
        }
    }

    private const val KEY = "macros"
    const val MAX = 6

    private fun sp(ctx: Context) = ctx.getSharedPreferences("claudepad", Context.MODE_PRIVATE)

    fun all(ctx: Context): MutableList<Macro> {
        val raw = sp(ctx).getString(KEY, null) ?: return mutableListOf()
        return try {
            val arr = JSONArray(raw)
            MutableList(arr.length()) { Macro.fromJson(arr.getJSONObject(it)) }
        } catch (e: Exception) { mutableListOf() }
    }

    fun save(ctx: Context, list: List<Macro>) {
        val arr = JSONArray()
        list.take(MAX).forEach { arr.put(it.toJson()) }
        sp(ctx).edit().putString(KEY, arr.toString()).apply()
    }

    fun add(ctx: Context, m: Macro) {
        val list = all(ctx)
        if (list.size < MAX) { list.add(m); save(ctx, list) }
    }

    fun removeAt(ctx: Context, i: Int) {
        val list = all(ctx)
        if (i in list.indices) { list.removeAt(i); save(ctx, list) }
    }

    fun fire(m: Macro) = WsClient.key(m.key, m.mods())
}
