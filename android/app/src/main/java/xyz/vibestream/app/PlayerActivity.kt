package xyz.vibestream.app

import android.app.PictureInPictureParams
import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.os.Build
import android.os.Bundle
import android.util.Rational
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCut
import androidx.compose.material.icons.filled.Forward10
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.material.icons.filled.FullscreenExit
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.UnfoldMore
import androidx.compose.material.icons.outlined.ClosedCaption
import androidx.compose.material.icons.outlined.Layers
import androidx.compose.material.icons.outlined.LightMode
import androidx.compose.material.icons.outlined.PictureInPictureAlt
import androidx.compose.material.icons.outlined.Speed
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.CaptionStyleCompat
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.Card
import xyz.vibestream.app.api.EpisodeItem
import xyz.vibestream.app.api.PlayInfo
import xyz.vibestream.app.api.PlayRequest
import xyz.vibestream.app.ui.BootSpinner
import xyz.vibestream.app.ui.Cast
import xyz.vibestream.app.ui.CastCommand
import xyz.vibestream.app.ui.CastPicker
import xyz.vibestream.app.ui.CastPlaying
import xyz.vibestream.app.ui.ClipEditor
import xyz.vibestream.app.ui.ClipSource
import xyz.vibestream.app.ui.Palette
import xyz.vibestream.app.ui.Pill
import xyz.vibestream.app.ui.PillLabel
import xyz.vibestream.app.ui.RemoteImage
import xyz.vibestream.app.ui.SeasonMenuLabel
import xyz.vibestream.app.ui.TitleAbout
import xyz.vibestream.app.ui.VibeTheme
import xyz.vibestream.app.ui.pressable
import xyz.vibestream.app.ui.timecode

class PlayerActivity : ComponentActivity() {
    companion object {
        fun intent(context: Context, request: PlayRequest) = Intent(context, PlayerActivity::class.java)
            .putExtra("playID", request.playID)
            .putExtra("title", request.title)
            .apply { request.startAt?.let { putExtra("startAt", it) } }
            // The profile travels with the title: after process death no profile is picked otherwise.
            .apply { AppState.profile?.id?.let { putExtra("profile", it) } }

        private fun read(extras: Bundle?) = PlayRequest(
            extras?.getString("playID").orEmpty(),
            extras?.getString("title").orEmpty(),
            if (extras?.containsKey("startAt") == true) extras.getDouble("startAt") else null,
        )
    }

    private var model: PlayerModel? = null
    private var request by mutableStateOf(PlayRequest("", ""))
    private var generation by mutableIntStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_FULL_USER
        // Restored from saved state: resume from the server's position; a cast's startAt is already spent.
        val saved = savedInstanceState?.takeIf { it.containsKey("playID") }
        adopt(saved ?: intent.extras)
        request = saved?.let { read(it).copy(startAt = null) } ?: read(intent.extras)
        setContent {
            VibeTheme {
                // Keyed by play id so nothing of the last episode leaks into the next.
                key(request.playID, generation) {
                    val m = remember { PlayerModel(this, request).also { model = it } }
                    DisposableEffect(m) { onDispose { m.stop() } }
                    PlayerScreen(m, onNext = { request = it }, onClose = { finish() }, onPip = { enterPip() })
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        model?.stop()
        adopt(intent.extras)
        request = read(intent.extras)
        generation++
    }

    private fun adopt(extras: Bundle?) {
        if (extras?.containsKey("profile") == true) Api.profileID = extras.getInt("profile")
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString("playID", request.playID)
        outState.putString("title", request.title)
        (model?.profile ?: Api.profileID)?.let { outState.putInt("profile", it) }
    }

    private fun enterPip() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            enterPictureInPictureMode(PictureInPictureParams.Builder().setAspectRatio(Rational(16, 9)).build())
        }
    }

    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        if (model?.isPlaying == true) enterPip()
    }

    override fun onPictureInPictureModeChanged(inPip: Boolean, newConfig: Configuration) {
        super.onPictureInPictureModeChanged(inPip, newConfig)
        model?.inPip = inPip
    }

    override fun onStop() {
        super.onStop()
        if (!isInPictureInPictureMode) model?.pauseForBackground()
    }
}

// Attach the HLS only once /prepare reports the rendition complete, so the whole timeline is seekable.
@androidx.annotation.OptIn(UnstableApi::class)
class PlayerModel(private val context: Context, val request: PlayRequest) : ClipSource {
    var info by mutableStateOf<PlayInfo?>(null)
    var ready by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var ended by mutableStateOf(false)
    override var isPlaying by mutableStateOf(false)
    var buffering by mutableStateOf(false)
    override var current by mutableDoubleStateOf(0.0)
    override var duration by mutableDoubleStateOf(0.0)
    override val playID: String get() = request.playID
    var rate by mutableStateOf(1f)
    var subtitleID by mutableStateOf<String?>(null)
    var audioIndex by mutableStateOf<Int?>(null)
    var inPip by mutableStateOf(false)
    var prefs = AppState.playerPrefs
    var subtitleSize by mutableStateOf(prefs.subtitleSize)
    var subtitleStyle by mutableStateOf(prefs.subtitleStyle)

    fun setLook(size: String? = null, style: String? = null) {
        size?.let { subtitleSize = it }
        style?.let { subtitleStyle = it }
        prefs = prefs.copy(subtitleSize = subtitleSize, subtitleStyle = subtitleStyle)
        AppState.playerPrefs = prefs
    }

    override val player: ExoPlayer = ExoPlayer.Builder(context)
        .setMediaSourceFactory(DefaultMediaSourceFactory(OkHttpDataSource.Factory(Api.http)))
        .build()

    private var resumeApplied = false
    private var pendingResume = 0.0
    private var startAt = request.startAt
    private var stopped = false
    private val jobs = mutableListOf<Job>()
    private var castToken: String? = null
    val profile = Api.profileID
    var onRemoteStop: (() -> Unit)? = null

    init {
        player.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(playing: Boolean) { isPlaying = playing }
            override fun onPlaybackStateChanged(state: Int) {
                buffering = state == Player.STATE_BUFFERING
                if (state == Player.STATE_READY) {
                    ready = true
                    if (duration == 0.0) duration = (player.duration.takeIf { it > 0 }?.div(1000.0)) ?: (info?.resume?.runtime ?: 0.0)
                    applyResumeIfNeeded()
                    applySubtitleSelection()
                }
                if (state == Player.STATE_ENDED) { ended = true; report() }
            }
            override fun onPlayerError(e: PlaybackException) { error = "${e.errorCodeName} · ${e.message.orEmpty()}" }
        })
        jobs += AppState.launch {
            while (isActive) {
                if (!seeking) current = player.currentPosition / 1000.0
                delay(250)
            }
        }
        jobs += AppState.launch {
            while (isActive) { delay(10_000); if (isPlaying) report() }
        }
        jobs += AppState.launch { start() }
        castToken = Cast.onControl { obey(it) }
        jobs += AppState.launch {
            while (isActive) {
                if (ready) {
                    val i = info
                    Cast.report(CastPlaying(
                        playID = request.playID, mediaID = i?.mediaID,
                        title = i?.presentation?.title ?: request.title, detail = i?.presentation?.episodeLine,
                        position = Math.round(current).toDouble(), duration = Math.round(duration).toDouble(), paused = !isPlaying,
                        presentation = i?.presentation, subtitles = i?.subtitles, audio = i?.audio,
                        subtitleID = subtitleID, audioIndex = audioIndex ?: i?.audio?.firstOrNull()?.index,
                        subtitleSize = subtitleSize, subtitleStyle = subtitleStyle))
                }
                delay(2_000)
            }
        }
    }


    private fun obey(command: CastCommand) {
        when (command.type) {
            "pause" -> player.pause()
            "resume" -> player.play()
            "seek" -> command.position?.let(::seek)
            "skip" -> command.delta?.let(::skip)
            "stop" -> onRemoteStop?.invoke()
            "subtitle" -> chooseSubtitle(command.subtitleID?.takeIf { it != "off" })
            "audio" -> chooseAudio(command.audioIndex)
            "appearance" -> setLook(command.subtitleSize, command.subtitleStyle)
        }
    }

    private suspend fun start() {
        try {
            val i = Api.playInfo(request.playID)
            info = i
            pendingResume = startAt ?: i.resume?.seconds ?: 0.0
            subtitleID = preferredSubtitle(i.subtitles)
            rate = prefs.speed
            waitForRendition()
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            error = e.message
        }
    }

    private suspend fun waitForRendition() {
        while (!stopped) {
            runCatching { Api.prepare(request.playID, audioIndex) }.getOrNull()?.let { state ->
                state.error?.let { error = it; return }
                if (state.ready) { attach(); return }
            }
            delay(2_000)
        }
    }

    private suspend fun attach() {
        val i = info ?: return
        var path = i.playback.hls
        audioIndex?.let { path += "?audio=$it" }
        val url = runCatching { Api.url(path) }.getOrElse { error = "Cannot reach the server"; return }
        player.setMediaItem(MediaItem.fromUri(url))
        player.prepare()
        player.setPlaybackSpeed(rate)
        player.playWhenReady = true
    }

    private fun preferredSubtitle(tracks: List<PlayInfo.SubtitleTrack>): String? {
        if (prefs.subtitlesOff) return null
        prefs.subtitleLanguage?.let { lang ->
            val matching = tracks.filter { it.language == lang }
            (matching.firstOrNull { it.forced != true } ?: matching.firstOrNull())?.let { return it.id }
        }
        return tracks.firstOrNull { it.default == true }?.id
    }

    private fun applyResumeIfNeeded() {
        if (resumeApplied || duration <= 0) return
        resumeApplied = true
        if (startAt != null) { startAt = null; seek(minOf(pendingResume, duration - 1)); return }
        if (pendingResume > 30 && pendingResume < duration - 60) seek(pendingResume)
    }

    private fun applySubtitleSelection() {
        val label = subtitleID?.let { id -> info?.subtitles?.firstOrNull { it.id == id }?.label }
        val params = player.trackSelectionParameters.buildUpon()
        if (label == null) {
            params.setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true)
        } else {
            params.setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false)
            val group = player.currentTracks.groups.firstOrNull { g ->
                g.type == C.TRACK_TYPE_TEXT && (0 until g.length).any { g.getTrackFormat(it).label == label }
            } ?: player.currentTracks.groups.firstOrNull { it.type == C.TRACK_TYPE_TEXT }
            group?.let { g ->
                val index = (0 until g.length).firstOrNull { g.getTrackFormat(it).label == label } ?: 0
                params.setOverrideForType(TrackSelectionOverride(g.mediaTrackGroup, index))
            }
        }
        player.trackSelectionParameters = params.build()
    }

    fun chooseSubtitle(id: String?) {
        subtitleID = id
        applySubtitleSelection()
        val language = id?.let { i -> info?.subtitles?.firstOrNull { it.id == i }?.language }
        prefs = prefs.copy(subtitlesOff = id == null, subtitleLanguage = language ?: prefs.subtitleLanguage)
        AppState.playerPrefs = prefs
    }

    /** Another audio track is another server rendition: rebuild and carry the position across. */
    fun chooseAudio(index: Int?) {
        if (index == audioIndex) return
        pendingResume = current
        resumeApplied = false
        audioIndex = index
        ready = false
        AppState.launch { waitForRendition() }
    }

    override fun togglePlay() { if (player.isPlaying) player.pause() else player.play() }

    private var seeking = false
    override fun seek(seconds: Double) {
        if (seconds < duration - 1) ended = false
        val clamped = seconds.coerceIn(0.0, maxOf(duration - 1, 0.0))
        current = clamped
        player.seekTo((clamped * 1000).toLong())
    }

    fun skip(delta: Double) = seek(current + delta)

    fun setSpeed(value: Float) {
        rate = value
        player.setPlaybackSpeed(value)
        prefs = prefs.copy(speed = value)
        AppState.playerPrefs = prefs
    }

    fun pauseForBackground() { player.pause(); report() }

    fun report() {
        if (duration <= 0 || current <= 0) return
        // Debug-driven runs must not write watch history.
        if (Debug.has("noProgress")) return
        val (id, pos, dur) = Triple(request.playID, current, duration)
        AppState.launch { Api.reportProgress(id, pos, dur, profile) }
    }

    fun stop() {
        if (stopped) return
        stopped = true
        report()
        castToken?.let(Cast::removeControl)
        Cast.report(null)
        jobs.forEach { it.cancel() }
        player.release()
    }
}

private const val UP_NEXT_LEAD = 20.0
private const val UP_NEXT_AFTER_END = 5.0

@androidx.annotation.OptIn(UnstableApi::class)
@kotlin.OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PlayerScreen(model: PlayerModel, onNext: (PlayRequest) -> Unit, onClose: () -> Unit, onPip: () -> Unit) {
    val configuration = LocalConfiguration.current
    val upright = configuration.orientation == Configuration.ORIENTATION_PORTRAIT
    var chrome by remember { mutableStateOf(true) }
    var locked by remember { mutableStateOf(Debug.has("locked")) }
    var lockHint by remember { mutableStateOf(false) }
    var tray by remember { mutableStateOf(Debug.string("tray")) }
    var tracksOpen by remember { mutableStateOf(false) }
    var castPicking by remember { mutableStateOf(false) }
    var clipping by remember { mutableStateOf(false) }
    LaunchedEffect(model) { model.onRemoteStop = onClose }
    var episodesOpen by remember { mutableStateOf(false) }
    var creditsChosen by remember { mutableStateOf(false) }
    var filling by remember { mutableStateOf(false) }
    var hideJob by remember { mutableStateOf<Job?>(null) }
    val scope = rememberCoroutineScope()
    val activity = androidx.compose.ui.platform.LocalContext.current as ComponentActivity

    fun showChrome() {
        chrome = true
        hideJob?.cancel()
        hideJob = scope.launch { delay(4_000); if (model.isPlaying && tray == null) chrome = false }
    }
    fun playNext() {
        val next = model.info?.next ?: return
        model.stop()
        onNext(PlayRequest(next.playID, model.request.title))
    }
    fun playEpisode(item: EpisodeItem) {
        val id = item.playID ?: return
        model.stop()
        onNext(PlayRequest(id, model.request.title))
    }

    LaunchedEffect(upright) {
        val controller = WindowInsetsControllerCompat(activity.window, activity.window.decorView)
        if (upright) controller.show(WindowInsetsCompat.Type.statusBars())
        else {
            controller.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            controller.hide(WindowInsetsCompat.Type.systemBars())
        }
        if (upright) { episodesOpen = false; tray = null }
        showChrome()
    }
    LaunchedEffect(Unit) {
        showChrome()
        if (Debug.has("chrome")) { delay(6_000); showChrome() }
        if (Debug.has("tracksPanel")) { delay(7_000); tracksOpen = true }
        if (Debug.has("episodesPanel")) { delay(7_000); episodesOpen = true }
        if (Debug.has("clipEditor")) { delay(9_000); clipping = true }
    }
    LaunchedEffect(model.ended) {
        if (!model.ended) return@LaunchedEffect
        if (model.info?.next == null) { onClose(); return@LaunchedEffect }
        if (creditsChosen) delay((UP_NEXT_AFTER_END * 1000).toLong())
        playNext()
    }
    BackHandler { if (episodesOpen) episodesOpen = false else onClose() }

    val upNext = model.info?.next?.takeIf {
        model.ready && model.error == null && !locked && model.duration > 0 &&
            (model.ended || (!creditsChosen && model.duration - model.current <= UP_NEXT_LEAD))
    }
    val fill = if (model.ended) 1.0 else (1 - (model.duration - model.current).coerceAtLeast(0.0) / UP_NEXT_LEAD).coerceIn(0.0, 1.0)

    Column(Modifier.fillMaxSize().background(Color.Black)) {
        BoxWithConstraints(
            Modifier.fillMaxWidth()
                .then(if (upright) Modifier.statusBarsPadding().aspectRatio(16f / 9f) else Modifier.fillMaxSize())
                .pointerInput(locked, tray, episodesOpen) {
                    detectTapGestures {
                        when {
                            locked -> { lockHint = true; scope.launch { delay(3_000); lockHint = false } }
                            tray != null -> { tray = null; showChrome() }
                            episodesOpen -> episodesOpen = false
                            chrome -> chrome = false
                            else -> showChrome()
                        }
                    }
                },
        ) {
            // Re-created when the clip editor closes: its preview took over the player's surface.
            key(clipping) { AndroidView(
                factory = { ctx ->
                    PlayerView(ctx).apply {
                        useController = false
                        player = model.player
                        setShutterBackgroundColor(android.graphics.Color.BLACK)
                    }
                },
                update = {
                    it.resizeMode = if (filling && !upright) AspectRatioFrameLayout.RESIZE_MODE_ZOOM else AspectRatioFrameLayout.RESIZE_MODE_FIT
                    applyLook(it, model.subtitleSize, model.subtitleStyle)
                },
                modifier = Modifier.fillMaxSize(),
            ) }
            if (episodesOpen && !upright) Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.55f)))

            model.error?.let { message ->
                Column(Modifier.align(Alignment.Center).padding(if (upright) 10.dp else 40.dp)
                    .background(Color(0xE6202020), RoundedCornerShape(20.dp)).padding(if (upright) 14.dp else 26.dp),
                    horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("Cannot play this title", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Palette.accent)
                    Text(message, fontSize = 13.sp, color = Palette.dim)
                    Pill(false, Modifier.width(120.dp), onClick = onClose) { PillLabel("Close") }
                }
            }
            if (model.error == null && (!model.ready || model.buffering)) Box(Modifier.align(Alignment.Center)) { BootSpinner() }

            androidx.compose.animation.AnimatedVisibility(chrome && !locked && model.error == null && !model.inPip, enter = fadeIn(), exit = fadeOut()) {
                if (upright) CompactChrome(model, onClose, onPip, onCast = { castPicking = true },
                    onFull = { activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE }, onTouch = ::showChrome)
                else FullChrome(model, tray,
                    onClose = onClose, onPip = onPip, onCast = { castPicking = true }, onLock = { locked = true; chrome = false },
                    onTray = { tray = if (tray == it) null else it; showChrome() },
                    onClip = { if (model.isPlaying) model.togglePlay(); clipping = true },
                    onTracks = { tracksOpen = true },
                    onEpisodes = if (model.info?.presentation?.episode != null) ({ episodesOpen = true }) else null,
                    onNext = if (model.info?.next != null) ({ playNext() }) else null,
                    filling = filling, onFill = { filling = !filling },
                    onExit = { activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_PORTRAIT },
                    onTouch = ::showChrome)
            }

            upNext?.let { next ->
                UpNextPills(next, fill, model.ended, onCredits = { creditsChosen = true }, onNext = ::playNext,
                    modifier = Modifier.align(Alignment.BottomEnd)
                        .padding(end = if (upright) 12.dp else 24.dp, bottom = if (upright) (if (chrome) 46.dp else 10.dp) else (if (chrome) 104.dp else 26.dp)))
            }

            if (locked && lockHint) {
                SlideToUnlock(Modifier.align(Alignment.BottomCenter).padding(bottom = 34.dp)) { locked = false; lockHint = false; showChrome() }
            }

            if (episodesOpen && !upright) {
                val media = model.info?.mediaID
                val episode = model.info?.presentation?.episode
                if (media != null && episode != null) {
                    EpisodesBand(media, episode.season, model.request.playID, onChoose = ::playEpisode, onClose = { episodesOpen = false })
                }
            }
        }

        if (upright) PlayerPage(model, onEpisode = ::playEpisode, onTitle = { onClose() })
    }

    if (clipping) {
        BackHandler { clipping = false; showChrome() }
        ClipEditor(model) { clipping = false; showChrome() }
    }
    if (castPicking) {
        ModalBottomSheet(onDismissRequest = { castPicking = false }, containerColor = Palette.ground) {
            CastPicker { device ->
                castPicking = false
                model.report()
                scope.launch {
                    val at = model.current
                    if (Cast.play(PlayRequest(model.request.playID, model.info?.presentation?.title ?: model.request.title), at, device,
                            AppState.profile?.id)) onClose()
                }
            }
        }
    }
    if (tracksOpen) {
        ModalBottomSheet(onDismissRequest = { tracksOpen = false }, containerColor = Color(0xFF161616)) {
            TrackPanel(model)
        }
    }
}

@Composable
private fun ChromeButton(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, size: Int = 22, onClick: () -> Unit) {
    Box(Modifier.size(44.dp).pressable(onClick = onClick), contentAlignment = Alignment.Center) {
        Icon(icon, label, tint = Color.White, modifier = Modifier.size(size.dp).shadow(3.dp, CircleShape, ambientColor = Color.Black, spotColor = Color.Black))
    }
}

private fun sizeScale(size: String) = when (size) { "small" -> 0.75f; "large" -> 1.4f; else -> 1f }

@androidx.annotation.OptIn(UnstableApi::class)
private fun applyLook(view: PlayerView, size: String, style: String) {
    val white = android.graphics.Color.WHITE
    val clear = android.graphics.Color.TRANSPARENT
    val black = android.graphics.Color.BLACK
    val look = when (style) {
        "outline" -> CaptionStyleCompat(white, clear, clear, CaptionStyleCompat.EDGE_TYPE_OUTLINE, black, null)
        "yellow" -> CaptionStyleCompat(android.graphics.Color.rgb(255, 214, 10), clear, clear, CaptionStyleCompat.EDGE_TYPE_DROP_SHADOW, black, null)
        "boxed" -> CaptionStyleCompat(white, android.graphics.Color.argb(200, 0, 0, 0), clear, CaptionStyleCompat.EDGE_TYPE_NONE, black, null)
        else -> CaptionStyleCompat(white, clear, clear, CaptionStyleCompat.EDGE_TYPE_DROP_SHADOW, black, null)
    }
    view.subtitleView?.setStyle(look)
    view.subtitleView?.setFractionalTextSize(androidx.media3.ui.SubtitleView.DEFAULT_TEXT_SIZE_FRACTION * sizeScale(size))
}

@Composable
private fun CastButton(onClick: () -> Unit) {
    Box(Modifier.size(44.dp).pressable(onClick = onClick), contentAlignment = Alignment.Center) {
        Icon(androidx.compose.ui.res.painterResource(R.drawable.ic_cast), "Play on another device", tint = Color.White, modifier = Modifier.size(22.dp))
    }
}

@Composable
private fun CentreControls(model: PlayerModel, compact: Boolean, onTouch: () -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(if (compact) 46.dp else 54.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Filled.Replay10, "Back 10 seconds", tint = Color.White,
            modifier = Modifier.size(if (compact) 30.dp else 40.dp).pressable { model.skip(-10.0); onTouch() })
        Icon(if (model.isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow, if (model.isPlaying) "Pause" else "Play", tint = Color.White,
            modifier = Modifier.size(if (compact) 44.dp else 58.dp).pressable { model.togglePlay(); onTouch() })
        Icon(Icons.Filled.Forward10, "Forward 10 seconds", tint = Color.White,
            modifier = Modifier.size(if (compact) 30.dp else 40.dp).pressable { model.skip(10.0); onTouch() })
    }
}

@Composable
private fun Scrubber(model: PlayerModel, modifier: Modifier = Modifier, onTouch: () -> Unit) {
    var width by remember { mutableStateOf(1) }
    var dragging by remember { mutableStateOf<Double?>(null) }
    val shown = dragging ?: model.current
    val fraction = if (model.duration > 0) (shown / model.duration).coerceIn(0.0, 1.0).toFloat() else 0f
    Row(modifier, verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Box(
            Modifier.weight(1f).height(28.dp).onSizeChanged { width = it.width }
                .pointerInput(model.duration) {
                    detectTapGestures { model.seek(it.x / width * model.duration); onTouch() }
                }
                .pointerInput(model.duration) {
                    detectHorizontalDragGestures(
                        onDragStart = { dragging = (it.x / width * model.duration) },
                        onDragEnd = { dragging?.let(model::seek); dragging = null; onTouch() },
                        onDragCancel = { dragging = null },
                    ) { change, _ -> dragging = (change.position.x / width).coerceIn(0f, 1f) * model.duration; onTouch() }
                },
            contentAlignment = Alignment.CenterStart,
        ) {
            Box(Modifier.fillMaxWidth().height(4.dp).background(Color.White.copy(alpha = 0.3f), CircleShape))
            Box(Modifier.fillMaxWidth(fraction).height(4.dp).background(Palette.accent, CircleShape))
            val knob = if (dragging != null) 20.dp else 14.dp
            val density = LocalDensity.current
            Box(Modifier.offset { IntOffset((fraction * width - with(density) { knob.toPx() } / 2).toInt(), 0) }
                .size(knob).background(Palette.accent, CircleShape))
        }
        Text(timecode((model.duration - shown).coerceAtLeast(0.0)), fontSize = 13.sp, color = Color.White)
    }
}

@Composable
private fun CompactChrome(model: PlayerModel, onClose: () -> Unit, onPip: () -> Unit, onCast: () -> Unit, onFull: () -> Unit, onTouch: () -> Unit) {
    Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color.Black.copy(alpha = 0.55f), Color.Black.copy(alpha = 0.15f), Color.Black.copy(alpha = 0.65f))))) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp)) {
            ChromeButton(Icons.Filled.Close, "Close", onClick = onClose)
            Spacer(Modifier.weight(1f))
            if (model.ready) {
                CastButton(onCast)
                ChromeButton(Icons.Outlined.PictureInPictureAlt, "Picture in Picture", onClick = onPip)
            }
        }
        if (model.ready) {
            Box(Modifier.align(Alignment.Center)) { CentreControls(model, compact = true, onTouch = onTouch) }
            Row(Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(start = 16.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Scrubber(model, Modifier.weight(1f), onTouch)
                ChromeButton(Icons.Filled.Fullscreen, "Full Screen", onClick = onFull)
            }
        }
    }
}

@Composable
private fun FullChrome(
    model: PlayerModel,
    tray: String?,
    onClose: () -> Unit,
    onPip: () -> Unit,
    onCast: () -> Unit,
    onLock: () -> Unit,
    onTray: (String) -> Unit,
    onClip: () -> Unit,
    onTracks: () -> Unit,
    onEpisodes: (() -> Unit)?,
    onNext: (() -> Unit)?,
    filling: Boolean,
    onFill: () -> Unit,
    onExit: () -> Unit,
    onTouch: () -> Unit,
) {
    val tablet = LocalConfiguration.current.smallestScreenWidthDp >= 600
    Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color.Black.copy(alpha = 0.65f), Color.Transparent, Color.Black.copy(alpha = 0.8f))))
        .padding(horizontal = 20.dp, vertical = 14.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            ChromeButton(Icons.Filled.Close, "Close", onClick = onClose)
            Column(Modifier.weight(1f)) {
                Text(model.info?.presentation?.title ?: model.request.title, fontSize = 17.sp, fontWeight = FontWeight.SemiBold,
                    color = Color.White, maxLines = 1)
                model.info?.presentation?.episodeLine?.let { Text(it, fontSize = 13.sp, color = Color.White.copy(alpha = 0.75f), maxLines = 1) }
            }
            if (model.ready) CastButton(onCast)
            if (model.ready) ChromeButton(Icons.Outlined.PictureInPictureAlt, "Picture in Picture", onClick = onPip)
            ChromeButton(Icons.Filled.LockOpen, "Lock", onClick = onLock)
        }
        if (model.ready) {
            if (tray == null) Box(Modifier.align(Alignment.Center)) { CentreControls(model, compact = false, onTouch = onTouch) }
            Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (tray == "speed") SpeedTray(model, onTouch)
                if (tray == "brightness") BrightnessTray(onTouch)
                Scrubber(model, Modifier.fillMaxWidth(), onTouch)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(if (tablet) 30.dp else 22.dp), verticalAlignment = Alignment.CenterVertically) {
                    ChromeButton(Icons.Filled.ContentCut, "Clip", onClick = onClip)
                    Spacer(Modifier.weight(1f))
                    ChromeButton(Icons.Outlined.Speed, "Speed (${if (model.rate == 1f) "1x" else "${model.rate}x"})") { onTray("speed") }
                    ChromeButton(Icons.Outlined.LightMode, "Brightness") { onTray("brightness") }
                    ChromeButton(Icons.Outlined.ClosedCaption, "Audio & Subtitles", onClick = onTracks)
                    if (tablet) ChromeButton(if (filling) Icons.Filled.FullscreenExit else Icons.Filled.Fullscreen, if (filling) "Fit" else "Full Screen", onClick = onFill)
                    onEpisodes?.let { ChromeButton(Icons.Outlined.Layers, "Episodes", onClick = it) }
                    onNext?.let { ChromeButton(Icons.Filled.SkipNext, "Next Episode", onClick = it) }
                    if (!tablet) ChromeButton(Icons.Filled.FullscreenExit, "Exit Full Screen", onClick = onExit)
                }
            }
        }
    }
}

@Composable
private fun BrightnessTray(onTouch: () -> Unit) {
    val activity = androidx.compose.ui.platform.LocalContext.current as ComponentActivity
    var level by remember {
        mutableStateOf(activity.window.attributes.screenBrightness.takeIf { it >= 0 } ?: 0.6f)
    }
    Column(Modifier.widthIn(max = 420.dp).fillMaxWidth().background(Color(0xE6202020), RoundedCornerShape(20.dp)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Brightness", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
        androidx.compose.material3.Slider(level, onValueChange = { v ->
            level = v
            activity.window.attributes = activity.window.attributes.apply { screenBrightness = v.coerceIn(0.02f, 1f) }
            onTouch()
        }, colors = androidx.compose.material3.SliderDefaults.colors(thumbColor = Color.White, activeTrackColor = Color.White,
            inactiveTrackColor = Color.White.copy(alpha = 0.25f)))
    }
}

@Composable
private fun SpeedTray(model: PlayerModel, onTouch: () -> Unit) {
    val speeds = listOf(0.5f, 0.75f, 1f, 1.25f, 1.5f)
    Column(Modifier.widthIn(max = 420.dp).fillMaxWidth().background(Color(0xE6202020), RoundedCornerShape(20.dp)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Speed", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            speeds.forEach { s ->
                val on = model.rate == s
                Column(Modifier.pressable { model.setSpeed(s); onTouch() }, horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Box(Modifier.size(if (on) 22.dp else 14.dp).background(if (on) Color.White else Color.White.copy(alpha = 0.45f), CircleShape))
                    Text(if (s == 1f) "1x (Normal)" else "${s}x".replace(".0x", "x"), fontSize = 12.sp,
                        fontWeight = if (on) FontWeight.Bold else FontWeight.Normal, color = Color.White)
                }
            }
        }
    }
}

@Composable
private fun UpNextPills(next: PlayInfo.NextEpisode, fill: Double, ended: Boolean, onCredits: () -> Unit, onNext: () -> Unit, modifier: Modifier) {
    Column(modifier, horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Next: S${next.season}:E${next.number} ${next.name}", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
            color = Color.White.copy(alpha = 0.88f), maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.widthIn(max = 360.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            if (!ended) Text("Watch Credits", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
                modifier = Modifier.height(44.dp).background(Color(0xE0383838), CircleShape).pressable(onClick = onCredits)
                    .padding(horizontal = 18.dp).wrapCenter())
            Box(Modifier.width(196.dp).height(44.dp).clip(CircleShape).background(Color(0xE0383838)).pressable(onClick = onNext)) {
                NextLabel(Color.White, Modifier.fillMaxSize())
                Box(Modifier.fillMaxHeight().fillMaxWidth(fill.toFloat()).clip(RoundedCornerShape(0.dp)).background(Color.White)) {
                    NextLabel(Color.Black, Modifier.width(196.dp).fillMaxHeight())
                }
            }
        }
    }
}

@Composable
private fun NextLabel(color: Color, modifier: Modifier) {
    Row(modifier, horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Filled.PlayArrow, null, tint = color, modifier = Modifier.size(20.dp))
        Text("Next Episode", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = color, modifier = Modifier.padding(start = 6.dp))
    }
}

private fun Modifier.wrapCenter() = this.then(Modifier.padding(top = 11.dp))

@Composable
private fun SlideToUnlock(modifier: Modifier, onUnlock: () -> Unit) {
    var drag by remember { mutableStateOf(0f) }
    var track by remember { mutableStateOf(1) }
    val density = LocalDensity.current
    val knob = with(density) { 44.dp.toPx() }
    Box(modifier.width(240.dp).height(52.dp).background(Color(0xCC202020), CircleShape).onSizeChanged { track = it.width }.padding(4.dp)) {
        Text("Slide to unlock", fontSize = 15.sp, color = Color.White.copy(alpha = (1 - drag / (track - knob).coerceAtLeast(1f)).coerceIn(0f, 1f)),
            modifier = Modifier.align(Alignment.Center))
        Box(Modifier.offset { IntOffset(drag.toInt(), 0) }.size(44.dp).background(Color.White, CircleShape)
            .pointerInput(track) {
                detectHorizontalDragGestures(
                    onDragEnd = { if (drag > (track - knob) * 0.8f) onUnlock() else drag = 0f },
                ) { _, amount -> drag = (drag + amount).coerceIn(0f, track - knob - 8) }
            }, contentAlignment = Alignment.Center) {
            Icon(Icons.Filled.Lock, null, tint = Color.Black, modifier = Modifier.size(20.dp))
        }
    }
}

@Composable
private fun EpisodesBand(mediaID: Int, season: Int, playing: String, onChoose: (EpisodeItem) -> Unit, onClose: () -> Unit) {
    var episodes by remember { mutableStateOf<List<EpisodeItem>>(emptyList()) }
    LaunchedEffect(mediaID, season) { episodes = runCatching { Api.season(mediaID, season).episodes }.getOrDefault(emptyList()) }
    Column(Modifier.fillMaxWidth().padding(top = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.padding(horizontal = 24.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Season $season", fontSize = 20.sp, fontWeight = FontWeight.SemiBold, color = Color.White, modifier = Modifier.weight(1f))
            ChromeButton(Icons.Filled.Close, "Close", onClick = onClose)
        }
        androidx.compose.foundation.lazy.LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 24.dp)) {
            items(episodes.size) { i ->
                val e = episodes[i]
                Column(Modifier.width(220.dp).pressable(e.playable && e.playID != playing) { onChoose(e) },
                    verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Box(Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(6.dp))
                        .then(if (e.playID == playing) Modifier.border(3.dp, Palette.accent, RoundedCornerShape(6.dp)) else Modifier)) {
                        RemoteImage(e.still, Modifier.fillMaxSize())
                    }
                    Text("${e.episode}. ${e.name}", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Color.White, maxLines = 1)
                    Text(if (e.playID == playing) "Now playing" else e.lengthLabel ?: "", fontSize = 12.sp, color = Palette.dim)
                }
            }
        }
    }
}

@Composable
private fun PlayerPage(model: PlayerModel, onEpisode: (EpisodeItem) -> Unit, onTitle: (Card) -> Unit) {
    val presentation = model.info?.presentation
    var card by remember { mutableStateOf<Card?>(null) }
    var similar by remember { mutableStateOf<List<Card>?>(null) }
    val tabs = buildList {
        if (presentation?.episode != null) add("Episodes")
        add("About"); add("Similar")
        if (model.ready) add("Audio & Subtitles")
    }
    var tab by remember { mutableStateOf<String?>(null) }
    val shownTab = tab?.takeIf { it in tabs } ?: tabs.first()
    LaunchedEffect(model.info?.mediaID) { model.info?.mediaID?.let { id -> card = runCatching { Api.media(id) }.getOrNull() } }

    Column(Modifier.fillMaxSize().background(Palette.ground).verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp)) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(presentation?.title ?: model.request.title, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Color.White)
            presentation?.episodeLine?.let { Text(it, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = Color.White) }
            val meta = listOfNotNull(presentation?.year?.toString(), card?.voteAverage?.takeIf { it > 0 }?.let { "%.1f".format(it) },
                card?.genres?.take(2)?.joinToString(", "))
            if (meta.isNotEmpty()) Text(meta.joinToString("  ·  "), fontSize = 13.sp, color = Palette.dim)
            (presentation?.overview ?: card?.overview)?.let { Text(it, fontSize = 15.sp, color = Palette.dim, maxLines = 3, overflow = TextOverflow.Ellipsis) }
        }
        if (model.info != null) {
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                tabs.forEach { option ->
                    Column(Modifier.width(androidx.compose.foundation.layout.IntrinsicSize.Max).pressable { tab = option },
                        verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(option, fontSize = 15.sp, fontWeight = if (shownTab == option) FontWeight.Bold else FontWeight.Normal,
                            color = if (shownTab == option) Color.White else Palette.faint, maxLines = 1)
                        Box(Modifier.fillMaxWidth().height(3.dp).background(if (shownTab == option) Palette.accent else Color.Transparent))
                    }
                }
            }
            when (shownTab) {
                "Episodes" -> {
                    val media = model.info?.mediaID
                    val episode = presentation?.episode
                    if (media != null && episode != null) PageEpisodes(media, episode.season, model.request.playID, onEpisode)
                }
                "About" -> card?.let { TitleAbout(it, heading = false) { } }
                "Similar" -> {
                    LaunchedEffect(model.info?.mediaID) {
                        model.info?.mediaID?.let { id -> similar = runCatching { Api.similar(id) }.getOrDefault(emptyList()) }
                    }
                    similar?.let { list -> xyz.vibestream.app.ui.Grid(list, 3, 12.dp) { c -> xyz.vibestream.app.ui.PosterCard(c, width = null) { onTitle(c) } } }
                }
                else -> TrackPanel(model, inline = true)
            }
        }
    }
}

@Composable
private fun PageEpisodes(mediaID: Int, startSeason: Int, playing: String, onEpisode: (EpisodeItem) -> Unit) {
    var season by remember { mutableStateOf(startSeason) }
    var seasons by remember { mutableStateOf<List<xyz.vibestream.app.api.SeasonSummary>>(emptyList()) }
    var episodes by remember { mutableStateOf<List<EpisodeItem>>(emptyList()) }
    var open by remember { mutableStateOf(false) }
    LaunchedEffect(mediaID) { seasons = runCatching { Api.media(mediaID).seasons.orEmpty() }.getOrDefault(emptyList()) }
    LaunchedEffect(mediaID, season) { episodes = runCatching { Api.season(mediaID, season).episodes }.getOrDefault(emptyList()) }
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Box {
            SeasonMenuLabel(seasons.firstOrNull { it.number == season }?.name ?: "Season $season") { open = true }
            DropdownMenu(open, onDismissRequest = { open = false }, containerColor = Color(0xFF242424)) {
                seasons.forEach { s -> DropdownMenuItem(text = { Text(s.name) }, onClick = { season = s.number; open = false }) }
            }
        }
        episodes.forEach { e ->
            val now = e.playID == playing
            Column(Modifier.fillMaxWidth().pressable(e.playable && !now) { onEpisode(e) }, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.width(130.dp).aspectRatio(16f / 9f).clip(RoundedCornerShape(6.dp))) {
                        RemoteImage(e.still, Modifier.fillMaxSize())
                        if (e.playable && !now) Box(Modifier.align(Alignment.Center).size(34.dp).background(Color.Black.copy(alpha = 0.35f), CircleShape)
                            .border(1.2.dp, Color.White.copy(alpha = 0.9f), CircleShape), contentAlignment = Alignment.Center) {
                            Icon(Icons.Filled.PlayArrow, null, tint = Color.White, modifier = Modifier.size(20.dp))
                        }
                        if (e.resumePercent > 1 && !e.watched) xyz.vibestream.app.ui.ProgressLine(e.resumePercent, Modifier.align(Alignment.BottomCenter).fillMaxWidth())
                    }
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text("${e.episode}. ${e.name}", fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                            color = if (now || !e.playable) Palette.dim else Color.White, maxLines = 2)
                        Text(if (now) "Now playing" else e.lengthLabel ?: "", fontSize = 13.sp, color = Palette.faint)
                    }
                }
                e.overview?.let { Text(it, fontSize = 13.sp, color = Palette.dim, maxLines = 3, overflow = TextOverflow.Ellipsis) }
            }
        }
    }
}

@Composable
private fun TrackPanel(model: PlayerModel, inline: Boolean = false) {
    val info = model.info ?: return
    var audioOpen by remember { mutableStateOf(false) }
    var subsOpen by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(horizontal = if (inline) 0.dp else 16.dp).padding(bottom = if (inline) 0.dp else 30.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        if (!inline) Text("Audio & Subtitles", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
            modifier = Modifier.fillMaxWidth(), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        Column(Modifier.background(Color.White.copy(alpha = 0.08f), RoundedCornerShape(14.dp))) {
            Box {
                TrackRow("Audio", info.audio.firstOrNull { it.index == (model.audioIndex ?: info.audio.firstOrNull()?.index) }?.label ?: "Default") { audioOpen = true }
                DropdownMenu(audioOpen, onDismissRequest = { audioOpen = false }, containerColor = Color(0xFF242424)) {
                    info.audio.forEach { a -> DropdownMenuItem(text = { Text(a.label) }, onClick = { audioOpen = false; model.chooseAudio(a.index) }) }
                }
            }
            Box {
                TrackRow("Subtitles", info.subtitles.firstOrNull { it.id == model.subtitleID }?.label ?: "Off") { subsOpen = true }
                DropdownMenu(subsOpen, onDismissRequest = { subsOpen = false }, containerColor = Color(0xFF242424)) {
                    DropdownMenuItem(text = { Text("Off") }, onClick = { subsOpen = false; model.chooseSubtitle(null) })
                    info.subtitles.forEach { s -> DropdownMenuItem(text = { Text(s.label) }, onClick = { subsOpen = false; model.chooseSubtitle(s.id) }) }
                }
            }
        }
        Text("Subtitle Appearance", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
        Column(Modifier.fillMaxWidth().background(Color.White.copy(alpha = 0.08f), RoundedCornerShape(14.dp)).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.fillMaxWidth().height(110.dp).background(Brush.verticalGradient(listOf(Color(0xFF3A3A3A), Color(0xFF1C1C1C))), RoundedCornerShape(10.dp)),
                contentAlignment = Alignment.BottomCenter) {
                val style = model.subtitleStyle
                Text("Where are we going?", fontSize = (17 * sizeScale(model.subtitleSize)).sp, fontWeight = FontWeight.Bold,
                    color = if (style == "yellow") Color(0xFFFFD60A) else Color.White,
                    style = androidx.compose.ui.text.TextStyle(shadow = if (style == "boxed") null else
                        androidx.compose.ui.graphics.Shadow(Color.Black, androidx.compose.ui.geometry.Offset(0f, 2f), if (style == "outline") 2f else 6f)),
                    modifier = Modifier.padding(bottom = 16.dp)
                        .then(if (style == "boxed") Modifier.background(Color.Black.copy(alpha = 0.78f)).padding(horizontal = 6.dp, vertical = 2.dp) else Modifier))
            }
            Text("SIZE", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = Palette.faint)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("small" to "Small", "medium" to "Medium", "large" to "Large").forEach { (value, label) ->
                    val on = model.subtitleSize == value
                    Text(label, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = if (on) Color.Black else Color.White,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                        modifier = Modifier.weight(1f).background(if (on) Color.White else Color.White.copy(alpha = 0.12f), CircleShape)
                            .pressable { model.setLook(size = value) }.padding(vertical = 8.dp))
                }
            }
            Text("STYLE", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = Palette.faint)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("shadow" to "Drop Shadow", "outline" to "Outline", "yellow" to "Yellow", "boxed" to "Boxed").forEach { (value, label) ->
                    val on = model.subtitleStyle == value
                    Column(Modifier.weight(1f).background(Color.White.copy(alpha = if (on) 0.18f else 0.06f), RoundedCornerShape(10.dp))
                        .then(if (on) Modifier.border(1.5.dp, Color.White, RoundedCornerShape(10.dp)) else Modifier)
                        .pressable { model.setLook(style = value) }.padding(vertical = 10.dp),
                        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("Aa", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = if (value == "yellow") Color(0xFFFFD60A) else Color.White,
                            modifier = if (value == "boxed") Modifier.background(Color.Black).padding(horizontal = 4.dp) else Modifier)
                        Text(label, fontSize = 11.sp, color = if (on) Color.White else Palette.dim, maxLines = 1)
                    }
                }
            }
        }
    }
}

@Composable
private fun TrackRow(label: String, value: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().pressable(onClick = onClick).padding(horizontal = 16.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, fontSize = 16.sp, color = Color.White, modifier = Modifier.weight(1f))
        Text(value, fontSize = 16.sp, color = Color.White)
        Icon(Icons.Filled.UnfoldMore, null, tint = Palette.dim, modifier = Modifier.size(18.dp).padding(start = 4.dp))
    }
}
