package com.bjorn.claudepad

import android.app.Dialog
import android.graphics.Color
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.Context
import android.view.Gravity
import android.view.KeyEvent
import android.view.ViewTreeObserver
import android.view.inputmethod.InputMethodManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.EditText
import android.widget.PopupWindow
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Layar kendali utama: trackpad, tombol mouse, keyboard, volume, media.
 *
 * Arsitektur:
 * - Semua state ada di [ControlViewModel].
 * - Activity hanya mengikat UI ke state dan menangani gesture.
 * - TrackpadView listener memanggil WsClient langsung untuk performa
 *   (MoveSender butuh Choreographer frame callback, tidak boleh terdelay).
 */
class ControlActivity : AppCompatActivity() {

    private val vm: ControlViewModel by viewModels()

    private lateinit var tvStatus: TextView
    private lateinit var trackpad: TrackpadView
    private lateinit var volumeSlider: VolumeSlider
    private var advancePopup: PopupWindow? = null
    private var presentationMode = false

    // ── v3.7: Now Playing ──
    private lateinit var nowPlayingCard: View
    private lateinit var npStatus: TextView
    private lateinit var npTitle: TextView
    private lateinit var npArtist: TextView
    private lateinit var npSeek: SeekBar
    private var npLengthUs = 0L
    private var npUserSeeking = false

    // ──────────────────────────── Lifecycle ──────────────────────────────

    /** Layar ikut berputar mengikuti orientasi input trackpad. */
    private fun applyScreenOrientation() {
        requestedOrientation = when (Prefs.inputRotation(this)) {
            90 -> ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            270 -> ActivityInfo.SCREEN_ORIENTATION_REVERSE_LANDSCAPE
            else -> ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        applyScreenOrientation()
        setContentView(R.layout.activity_control)
        Haptics.init(this)
        Glass.apply(this, findViewById(R.id.rootControl))

        if (Prefs.keepAwake(this)) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }

        tvStatus = findViewById(R.id.tvStatus)
        trackpad = findViewById(R.id.trackpad)
        volumeSlider = findViewById(R.id.volumeSlider)

        // v3.7: sinkronisasi clipboard HP ⇄ PC
        ClipboardSync.init(this)

        WifiPerf.acquire(this)

        setupTrackpad()
        setupMouseButtons()
        setupKeyboard()
        setupShortcuts()
        setupVolume()
        setupMedia()
        setupNowPlaying()
        setupDpad()
        setupTopBar()
        setupPresentationButtons()
        applyAccent()

        Fonts.apply(findViewById(R.id.rootControl))

        // ─── Observe state dari ViewModel ───
        observeState()

        // Legacy callbacks untuk RemoteService (masih diperlukan)
        WsClient.onReconnecting = { n ->
            runOnUiThread { tvStatus.text = "menyambung ulang… ($n/5)" }
        }
    }

    // ──────────────────────────── State observation ──────────────────────

    private fun observeState() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                // ─── Connection state ───
                launch {
                    vm.connectionState.collect { state ->
                        when (state) {
                            is WsClient.ConnectionState.Connected -> {
                                val info = vm.connectionInfo.value
                                tvStatus.text = "${info.hostName} · ${info.transport}"
                                trackpad.deviceName = info.hostName
                                RemoteService.update(this@ControlActivity)
                                // v3.7: minta info now playing sekali saat auth_ok
                                if (info.nowPlayingSupported) vm.npGet()
                            }
                            is WsClient.ConnectionState.Error -> {
                                tvStatus.text = state.message
                                RemoteService.update(this@ControlActivity)
                                finish()
                            }
                            is WsClient.ConnectionState.Disconnected -> {
                                finish()
                            }
                            is WsClient.ConnectionState.Connecting -> {
                                tvStatus.text = "menyambung…"
                            }
                        }
                    }
                }

                // ─── Ping ───
                launch {
                    vm.pingMs.collect { ms ->
                        if (ms >= 0) {
                            renderPing(ms)
                            RemoteService.update(this@ControlActivity)
                        }
                    }
                }

                // ─── Volume ───
                launch {
                    vm.volume.collect { v ->
                        if (volumeSlider.value != v) {
                            volumeSlider.value = v
                        }
                    }
                }

                // ─── Toast messages (power_result, radio_result) ───
                launch {
                    vm.toastMessage.collect { msg ->
                        if (msg != null) {
                            if (vm.toastHapticOk.value) Haptics.medium() else Haptics.light()
                            Toast.makeText(this@ControlActivity, msg,
                                if (msg.length > 40) Toast.LENGTH_LONG else Toast.LENGTH_SHORT
                            ).show()
                            vm.onToastShown()
                        }
                    }
                }

                // ─── Volume error ───
                launch {
                    vm.volumeError.collect { msg ->
                        if (msg != null) {
                            Toast.makeText(this@ControlActivity, msg,
                                Toast.LENGTH_LONG).show()
                            vm.onVolumeErrorShown()
                        }
                    }
                }

                // ─── Scroll indicator ───
                launch {
                    vm.scrollInfo.collect { info ->
                        trackpad.updateScrollIndicator(info)
                    }
                }

                // ─── Now Playing (v3.7) ───
                launch {
                    vm.nowPlaying.collect { np ->
                        renderNowPlaying(np)
                    }
                }

                // ─── Polling now playing: npget tiap 5 detik ───
                launch {
                    while (true) {
                        if (vm.isConnected &&
                            vm.connectionInfo.value.nowPlayingSupported) {
                            vm.npGet()
                        }
                        delay(5000)
                    }
                }
            }
        }
    }

    // ──────────────────────────── Visual ─────────────────────────────────

    /** Warna aksen mengikuti wallpaper. */
    private fun applyAccent() {
        Accent.refresh()
        Accent.applyToKey(findViewById(R.id.kEnter))
        Accent.applyToKey(findViewById(R.id.mPlay))
        findViewById<DpadView>(R.id.dpad).accentColor = Accent.bg(this)
    }

    // ──────────────────────────── Ping ───────────────────────────────────

    private val pingHandler = Handler(Looper.getMainLooper())
    private lateinit var tvPing: TextView
    private var pingRunning = false

    /** Indikator latensi, hanya untuk koneksi WiFi/Hotspot. */
    private fun setupPing() {
        tvPing = findViewById(R.id.tvPing)
        if (vm.transport != "wifi") {
            tvPing.visibility = View.GONE
            return
        }
        tvPing.visibility = View.VISIBLE
        tvPing.text = "…"

        pingRunning = true
        val tick = object : Runnable {
            override fun run() {
                if (!pingRunning || !vm.isConnected) return
                vm.measurePing()
                pingHandler.postDelayed(this, 2000)
            }
        }
        pingHandler.post(tick)
    }

    private fun renderPing(ms: Int) {
        tvPing.text = "${ms}ms"
        val color = when {
            ms < 40 -> 0xFF4ADE80.toInt()   // hijau - sangat baik
            ms < 90 -> 0xFFA3E635.toInt()   // hijau kekuningan - baik
            ms < 180 -> 0xFFFBBF24.toInt()  // kuning - cukup
            ms < 350 -> 0xFFFB923C.toInt()  // jingga - lambat
            else -> 0xFFFF6B6B.toInt()      // merah - buruk
        }
        tvPing.setTextColor(color)
    }

    // ──────────────────────────── Trackpad ───────────────────────────────

    private fun setupTrackpad() {
        trackpad.sensitivity = Prefs.sensitivity(this)
        trackpad.naturalScroll = Prefs.naturalScroll(this)
        trackpad.inputRotation = Prefs.inputRotation(this)
        trackpad.pointerLocation = Prefs.pointerLocation(this)
        trackpad.showTaps = Prefs.showTaps(this)

        // Trackpad listener memanggil WsClient langsung untuk performa.
        // MoveSender membutuhkan Choreographer frame callback tanpa delay.
        trackpad.listener = object : TrackpadView.Listener {
            override fun onMove(dx: Int, dy: Int) =
                MoveSender.move(dx.toFloat(), dy.toFloat())
            override fun onLeftClick() = vm.click("left")
            override fun onRightClick() = vm.click("right")
            override fun onScroll(notches: Int) = vm.scroll(notches)
            override fun onScrollHorizontal(notches: Int) = vm.scrollHorizontal(notches)
            override fun onMiddleClick() = vm.click("middle")
            override fun onZoom(direction: Int) = vm.zoom(direction)
            override fun onGesture(name: String) = vm.gesture(name)
            override fun onDragStart() = vm.buttonDown("left")
            override fun onDragEnd() {
                MoveSender.flush()
                vm.buttonUp("left")
            }
        }
    }

    // ──────────────────────────── Mouse buttons ──────────────────────────

    private fun tap(id: Int, level: Haptics.Level = Haptics.Level.LIGHT, action: () -> Unit) {
        findViewById<View>(id).setOnClickListener {
            Haptics.fire(level)
            action()
        }
    }

    private fun setupMouseButtons() {
        tap(R.id.btnLeft) { vm.click("left") }
        tap(R.id.btnMiddle) { vm.click("middle") }
        tap(R.id.btnRight) { vm.click("right") }
    }

    // ──────────────────────────── Keyboard ───────────────────────────────

    private lateinit var typeLabel: TextView
    private var typeDialog: Dialog? = null
    private var suppressWatcher = false

    private fun setupKeyboard() {
        typeLabel = findViewById(R.id.etType)
        typeLabel.setOnClickListener {
            Haptics.light()
            showTypePopup()
        }
        tap(R.id.kEnter, Haptics.Level.MEDIUM) { vm.key("enter") }
    }

    /**
     * Pop-up mengetik: kartu di tengah layar dengan latar diburamkan.
     */
    private fun showTypePopup() {
        if (typeDialog?.isShowing == true) return

        val dialog = Dialog(this, android.R.style.Theme_Translucent_NoTitleBar)
        dialog.setContentView(R.layout.popup_type)
        val root = dialog.findViewById<FrameLayout>(R.id.typeRoot)
        val card = dialog.findViewById<View>(R.id.typeCard)
        val et = dialog.findViewById<EditText>(R.id.etPopup)
        val enter = dialog.findViewById<TextView>(R.id.btnPopupEnter)
        Fonts.apply(root)
        Accent.applyToKey(enter)

        dialog.window?.apply {
            setLayout(WindowManager.LayoutParams.MATCH_PARENT,
                      WindowManager.LayoutParams.MATCH_PARENT)
            setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING or
                             WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                try {
                    addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND)
                    attributes = attributes.apply { blurBehindRadius = 90 }
                } catch (e: Exception) { }
            }
            addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
            setDimAmount(0.55f)
        }
        root.setBackgroundColor(Color.argb(0x66, 6, 6, 12))
        root.setOnClickListener { dialog.dismiss() }

        var baseHeight = 0
        card.viewTreeObserver.addOnGlobalLayoutListener {
            if (card.height > 0) {
                if (baseHeight == 0) baseHeight = card.height
                card.translationY = ((card.height - baseHeight) / 2f)
            }
        }

        val decor = dialog.window?.decorView
        decor?.viewTreeObserver?.addOnGlobalLayoutListener(object :
            ViewTreeObserver.OnGlobalLayoutListener {
            private var everOpen = false
            override fun onGlobalLayout() {
                val r = Rect()
                decor.getWindowVisibleDisplayFrame(r)
                val screenH = decor.height.takeIf { it > 0 } ?: return
                val keyboard = screenH - r.bottom
                if (keyboard > screenH * 0.15) everOpen = true
                else if (everOpen) decor.post { dialog.dismiss() }
            }
        })

        et.addTextChangedListener(object : TextWatcher {
            private var before = ""
            override fun beforeTextChanged(s: CharSequence, st: Int, c: Int, a: Int) {
                before = s.toString()
            }
            override fun onTextChanged(s: CharSequence, st: Int, b: Int, c: Int) {}
            override fun afterTextChanged(s: Editable) {
                if (suppressWatcher) return
                val now = s.toString()
                if (now.length > before.length && now.startsWith(before)) {
                    vm.text(now.substring(before.length))
                    Haptics.tick()
                } else if (now.length < before.length && before.startsWith(now)) {
                    repeat(before.length - now.length) { vm.key("backspace") }
                    Haptics.tick()
                } else if (now != before) {
                    repeat(before.length) { vm.key("backspace") }
                    if (now.isNotEmpty()) vm.text(now)
                    Haptics.tick()
                }
                typeLabel.text = if (now.isEmpty()) "ketik di sini" else now
            }
        })

        fun sendEnter() {
            Haptics.medium()
            vm.key("enter")
            suppressWatcher = true
            et.setText("")
            suppressWatcher = false
            typeLabel.text = "ketik di sini"
        }
        enter.setOnClickListener { sendEnter() }

        et.setOnKeyListener { _, keyCode, event ->
            if (keyCode == KeyEvent.KEYCODE_ENTER && event.action == KeyEvent.ACTION_DOWN) {
                sendEnter(); true
            } else false
        }

        dialog.setOnDismissListener {
            typeDialog = null
            val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
            imm.hideSoftInputFromWindow(et.windowToken, 0)
        }

        typeDialog = dialog
        dialog.show()
        et.requestFocus()
        et.post {
            val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
            imm.showSoftInput(et, InputMethodManager.SHOW_IMPLICIT)
        }
    }

    // ──────────────────────────── Shortcuts ──────────────────────────────

    private fun setupShortcuts() {
        tap(R.id.kWinTab, Haptics.Level.MEDIUM) { vm.key("tab", listOf("win")) }
        tap(R.id.kCloseTab, Haptics.Level.MEDIUM) { vm.key("w", listOf("ctrl")) }

        // grup salin / tempel
        findViewById<TextView>(R.id.btnClipGroup).setOnClickListener { anchor ->
            Haptics.medium()
            showGroupPopup(anchor, R.layout.popup_clip, 200, 0) { root, pop ->
                bindKey(root, pop, R.id.kCopy) { vm.key("c", listOf("ctrl")) }
                bindKey(root, pop, R.id.kPaste) { vm.key("v", listOf("ctrl")) }
            }
        }

        // grup urungkan / ulangi
        findViewById<TextView>(R.id.btnUndoGroup).setOnClickListener { anchor ->
            Haptics.medium()
            showGroupPopup(anchor, R.layout.popup_undo, 200, 0) { root, pop ->
                bindKey(root, pop, R.id.kUndo) { vm.key("z", listOf("ctrl")) }
                bindKey(root, pop, R.id.kRedo) {
                    vm.key("y", listOf("ctrl"))
                }
            }
        }

        // grup kontrol koneksi PC
        findViewById<TextView>(R.id.btnConnGroup).setOnClickListener { anchor ->
            Haptics.medium()
            showGroupPopup(anchor, R.layout.popup_conn, 215, 0) { root, pop ->
                bindKey(root, pop, R.id.kWifi, close = true) { vm.radio("wifi") }
                bindKey(root, pop, R.id.kBluetooth, close = true) { vm.radio("bluetooth") }
                bindKey(root, pop, R.id.kHotspot, close = true) { vm.radio("hotspot") }
            }
        }

        // panel Advance
        findViewById<TextView>(R.id.btnAdvance).setOnClickListener { anchor ->
            Haptics.medium()
            showGroupPopup(anchor, R.layout.popup_advance, 230, 350) { root, pop ->
                bindKey(root, pop, R.id.kEsc) { vm.key("esc") }
                bindKey(root, pop, R.id.kTab) { vm.key("tab") }
                bindKey(root, pop, R.id.kWin) { vm.key("win") }
                bindKey(root, pop, R.id.kDel) { vm.key("delete") }
                bindKey(root, pop, R.id.kSettings) { vm.key(",", listOf("ctrl")) }
                // Server Linux melaporkan aksi daya mana yang benar-benar
                // ada; "matikan layar" khususnya belum punya padanan standar
                // di Wayland. Yang tidak didukung diredupkan alih-alih
                // dibiarkan gagal diam-diam.
                bindPowerKey(root, pop, R.id.kScreenOff, "screenoff", "matikan layar")
                bindPowerKey(root, pop, R.id.kLock, "lock", "kunci pc")
                setupMacroInAdvance(root, Macros.all(this))
            }
        }
    }

    private fun showGroupPopup(
        anchor: View,
        layoutRes: Int,
        widthDp: Int,
        heightDp: Int,
        bind: (View, PopupWindow) -> Unit
    ) {
        advancePopup?.let {
            if (it.isShowing) { it.dismiss(); advancePopup = null; return }
        }
        val d = resources.displayMetrics.density
        val content = LayoutInflater.from(this).inflate(layoutRes, null)
        Fonts.apply(content)

        val h = if (heightDp > 0) (heightDp * d).toInt()
                else WindowManager.LayoutParams.WRAP_CONTENT
        val popup = PopupWindow(content, (widthDp * d).toInt(), h, true)
        popup.elevation = 24f
        bind(content, popup)
        popup.setOnDismissListener { advancePopup = null }

        content.measure(
            View.MeasureSpec.makeMeasureSpec((widthDp * d).toInt(), View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED))
        val popHeight = if (heightDp > 0) (heightDp * d).toInt() else content.measuredHeight
        popup.showAsDropDown(anchor, 0, -(popHeight + anchor.height + (8 * d).toInt()))
        advancePopup = popup
    }

    /**
     * Seperti [bindKey], tapi tombolnya diredupkan bila PC melaporkan
     * aksi daya itu tidak tersedia.
     */
    private fun bindPowerKey(root: View, popup: PopupWindow, id: Int,
                             action: String, label: String) {
        val view = root.findViewById<View>(id) ?: return
        if (!vm.connectionInfo.value.supportsPower(action)) {
            view.alpha = 0.35f
            view.setOnClickListener {
                Haptics.light()
                android.widget.Toast.makeText(
                    this, "$label tidak didukung pc ini",
                    android.widget.Toast.LENGTH_SHORT).show()
            }
            return
        }
        view.setOnClickListener {
            Haptics.medium()
            vm.power(action)
            popup.dismiss()
        }
    }

    private fun bindKey(root: View, popup: PopupWindow, id: Int,
                        close: Boolean = false, action: () -> Unit) {
        root.findViewById<View>(id)?.setOnClickListener {
            Haptics.medium()
            action()
            if (close) popup.dismiss()
        }
    }

    // ──────────────────────────── Volume ─────────────────────────────────

    private fun setupVolume() {
        volumeSlider.value = vm.volume.value
        volumeSlider.onValueChanged = { v -> vm.setVolume(v) }
        volumeSlider.onMuteTap = { vm.media("mute") }
        volumeSlider.onCommit = { v -> vm.commitVolume(v) }
    }

    // ──────────────────────────── Media ──────────────────────────────────

    private fun setupMedia() {
        tap(R.id.mPlay, Haptics.Level.MEDIUM) { vm.media("playpause") }
        tap(R.id.mPrev) { vm.media("prev") }
        tap(R.id.mNext) { vm.media("next") }
    }

    // ──────────────────────────── Now Playing (v3.7) ─────────────────────

    /**
     * Kartu kecil info lagu. Kontrolnya tetap mPlay/mPrev/mNext yang sudah
     * ada — kartu ini hanya menampilkan judul/artis + indikator play/pause,
     * plus seek bar bila pemutar mendukung seek.
     */
    private fun setupNowPlaying() {
        nowPlayingCard = findViewById(R.id.nowPlayingCard)
        npStatus = findViewById(R.id.npStatus)
        npTitle = findViewById(R.id.npTitle)
        npArtist = findViewById(R.id.npArtist)
        npSeek = findViewById(R.id.npSeek)

        npSeek.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {}
            override fun onStartTrackingTouch(sb: SeekBar?) {
                npUserSeeking = true
            }
            override fun onStopTrackingTouch(sb: SeekBar?) {
                npUserSeeking = false
                // Kirim posisi hanya saat user selesai drag — bukan saat
                // progress diubah secara programatik oleh data np baru.
                if (npLengthUs > 0) {
                    val posUs = (sb?.progress ?: 0).toLong() * npLengthUs / 1000L
                    vm.npSeek(posUs)
                    Haptics.light()
                }
            }
        })
    }

    private fun renderNowPlaying(np: WsClient.NowPlaying) {
        // Sembunyikan kartu bila server tidak mendukung now playing
        // atau PC sedang tidak memutar apa pun (ok:false).
        if (!np.ok || !vm.connectionInfo.value.nowPlayingSupported) {
            nowPlayingCard.visibility = View.GONE
            return
        }
        nowPlayingCard.visibility = View.VISIBLE
        npTitle.text = np.title.ifEmpty { "—" }
        npArtist.text = np.artist
        npStatus.text = if (np.playing) "▶" else "⏸"
        npLengthUs = np.lengthUs

        if (np.canSeek && np.lengthUs > 0) {
            npSeek.visibility = View.VISIBLE
            npSeek.max = 1000
            if (!npUserSeeking) {
                val pct = (np.posUs * 1000L / np.lengthUs).toInt().coerceIn(0, 1000)
                npSeek.progress = pct
            }
        } else {
            npSeek.visibility = View.GONE
        }
    }

    // ──────────────────────────── D-pad ──────────────────────────────────

    private fun setupDpad() {
        findViewById<DpadView>(R.id.dpad).onDirection = { dir -> vm.key(dir) }
    }

    // ──────────────────────────── Macros in Advance ──────────────────────

    private fun setupMacroInAdvance(popup: View, macros: List<Macros.Macro>) {
        val container = popup.findViewById<LinearLayout>(R.id.macroContainer)
        container.removeAllViews()

        if (macros.isEmpty()) {
            container.visibility = View.GONE
            return
        }

        container.visibility = View.VISIBLE

        // Bagi per 3 macro per baris
        val chunked = macros.chunked(3)
        for (chunk in chunked) {
            val row = LinearLayout(this).apply {
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                )
                orientation = LinearLayout.HORIZONTAL
            }
            for (m in chunk) {
                val btn = TextView(this).apply {
                    text = m.label.ifEmpty { m.key.uppercase() }
                    setBackgroundResource(R.drawable.glass_key)
                    gravity = Gravity.CENTER
                    textSize = 14f
                    setTextColor(getColor(R.color.text))
                    layoutParams = LinearLayout.LayoutParams(
                        0, 46.dpToPx(), 1f
                    ).apply {
                        setMargins(3.dpToPx(), 3.dpToPx(), 3.dpToPx(), 3.dpToPx())
                    }
                    setOnClickListener {
                        Haptics.medium()
                        Macros.fire(m)
                    }
                }
                row.addView(btn)
            }
            container.addView(row)
        }
    }

    // ──────────────────────────── Presentation mode ──────────────────────

    private fun setupPresentationButtons() {
        tap(R.id.presLeft, Haptics.Level.MEDIUM) { vm.key("left") }
        tap(R.id.presRight, Haptics.Level.MEDIUM) { vm.key("right") }
        tap(R.id.presWinP, Haptics.Level.MEDIUM) { vm.key("p", listOf("win")) }
        tap(R.id.presEsc, Haptics.Level.MEDIUM) { vm.key("esc") }
        tap(R.id.presF11, Haptics.Level.MEDIUM) { vm.key("f11") }
        tap(R.id.presExit, Haptics.Level.HEAVY) {
            presentationMode = false
            applyPresentationMode()
        }
    }

    private fun applyPresentationMode() {
        val normal = findViewById<View>(R.id.normalControls)
        val pres = findViewById<View>(R.id.presentationControls)
        normal.visibility = if (presentationMode) View.GONE else View.VISIBLE
        pres.visibility = if (presentationMode) View.VISIBLE else View.GONE
    }

    private fun Int.dpToPx(): Int = (this * resources.displayMetrics.density).toInt()

    // ──────────────────────────── Top bar ────────────────────────────────

    private fun setupTopBar() {
        val btnRotate = findViewById<TextView>(R.id.btnRotate)
        fun renderRotate() {
            val deg = trackpad.inputRotation
            btnRotate.alpha = if (deg == 0) 0.6f else 1f
            btnRotate.text = when (deg) {
                90 -> "⤡"
                270 -> "⤣"
                else -> "⤢"
            }
        }
        renderRotate()
        btnRotate.setOnClickListener {
            Haptics.heavy()
            val next = Prefs.nextRotation(trackpad.inputRotation)
            trackpad.inputRotation = next
            Prefs.setInputRotation(this, next)
            renderRotate()
            applyScreenOrientation()
        }
        findViewById<TextView>(R.id.btnPresentation).setOnClickListener {
            Haptics.heavy()
            presentationMode = !presentationMode
            applyPresentationMode()
        }
        findViewById<TextView>(R.id.btnSettings).setOnClickListener {
            Haptics.light()
            startActivity(Intent(this, SettingsActivity::class.java))
        }
        findViewById<TextView>(R.id.btnDisconnect).setOnClickListener {
            Haptics.heavy()
            vm.disconnect()
            finish()
        }
    }

    // ──────────────────────────── State ──────────────────────────────────

    override fun onResume() {
        super.onResume()
        Haptics.enabled = Prefs.hapticEnabled(this)
        Haptics.strength = Prefs.hapticStrength(this)
        Glass.apply(this, findViewById(R.id.rootControl))
        trackpad.sensitivity = Prefs.sensitivity(this)
        trackpad.naturalScroll = Prefs.naturalScroll(this)
        trackpad.inputRotation = Prefs.inputRotation(this)
        trackpad.pointerLocation = Prefs.pointerLocation(this)
        trackpad.showTaps = Prefs.showTaps(this)
        vm.setAutoReconnect(Prefs.autoReconnect(this))
        applyScreenOrientation()
        setupPing()

        if (presentationMode) {
            presentationMode = false
            applyPresentationMode()
        }

        if (!vm.isConnected) finish()
    }

    override fun onDestroy() {
        super.onDestroy()
        pingRunning = false
        WifiPerf.release()
        MoveSender.reset()
        WsClient.onReconnecting = null
        pingHandler.removeCallbacksAndMessages(null)
        typeDialog?.dismiss()
        advancePopup?.dismiss()
        if (isFinishing && !isChangingConfigurations) vm.disconnect()
    }
}
