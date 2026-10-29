package xyz.vibestream.app

import android.app.PendingIntent
import android.app.PictureInPictureParams
import android.app.RemoteAction
import android.content.BroadcastReceiver
import android.content.IntentFilter
import android.graphics.drawable.Icon
import androidx.core.content.ContextCompat
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
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.drag
import androidx.compose.ui.layout.layout
import kotlin.math.roundToInt
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.ui.input.pointer.positionChanged
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.unit.IntSize
import kotlinx.coroutines.flow.conflate
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.statusBars
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
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.Card
import xyz.vibestream.app.api.EpisodeItem
import xyz.vibestream.app.api.PlayInfo
import xyz.vibestream.app.api.PlayRequest
import xyz.vibestream.app.ui.BootSpinner
import xyz.vibestream.app.ui.Cast
import xyz.vibestream.app.ui.CastPicker
import xyz.vibestream.app.ui.ClipEditor
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
        private const val PIP_TOGGLE = "xyz.vibestream.app.PIP_TOGGLE"

        fun intent(context: Context, request: PlayRequest) = Intent(context, PlayerActivity::class.java)
            .putExtra("playID", request.playID)
            .putExtra("title", request.title)
            .apply { request.startAt?.let { putExtra("startAt", it) } }
            .apply { request.season?.let { putExtra("season", it) }; request.episode?.let { putExtra("episode", it) } }
            // Who is watching travels with the title: a player brought back
            // after the process was killed has no profile picked otherwise.
            .apply { AppState.profile?.id?.let { putExtra("profile", it) } }

        /** The whole screen for a title page, given its playback (PlayerSession.handed). */
        fun forPage(context: Context, request: PlayRequest, sideways: Boolean) = intent(context, request)
            .putExtra("forPage", true)
            .putExtra("sideways", sideways)

        private fun read(extras: Bundle?) = PlayRequest(
            extras?.getString("playID").orEmpty(),
            extras?.getString("title").orEmpty(),
            if (extras?.containsKey("startAt") == true) extras.getDouble("startAt") else null,
            if (extras?.containsKey("season") == true) extras.getInt("season") else null,
            if (extras?.containsKey("episode") == true) extras.getInt("episode") else null,
        )
    }

    private var model: PlayerModel? = null
    private var request by mutableStateOf(PlayRequest("", ""))
    private var generation by mutableIntStateOf(0)
    /** For a title page, whose playback this is and goes back to. */
    private var forPage = false
    private var handed: PlayerModel? = null
    /** Given back to the page: not stopped, and not paused on the way out. */
    private var givenBack = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_FULL_USER
        ContextCompat.registerReceiver(this, pipToggle, IntentFilter(PIP_TOGGLE), ContextCompat.RECEIVER_NOT_EXPORTED)
        // Rebuilt from saved state, the title is the one on screen at the
        // time and its place is the server's: a cast's startAt is spent.
        val saved = savedInstanceState?.takeIf { it.containsKey("playID") }
        adopt(saved ?: intent.extras)
        request = saved?.let { read(it).copy(startAt = null) } ?: read(intent.extras)
        forPage = intent.getBooleanExtra("forPage", false)
        val sideways = intent.getBooleanExtra("sideways", false) && saved == null
        handed = PlayerSession.handed?.takeIf { forPage && it.request.playID == request.playID }
        PlayerSession.handed = null
        setContent {
            VibeTheme {
                // Keyed by play id so nothing of the last episode leaks into the next.
                key(request.playID, generation) {
                    val m = remember { (handed ?: PlayerModel(this, request)).also { handed = null; model = it } }
                    DisposableEffect(m) { onDispose { if (!givenBack) m.stop() } }
                    // The little window kept told the picture's shape, and
                    // whether leaving the app should start it (only while playing).
                    LaunchedEffect(m.isPlaying, m.aspect) { updatePip() }
                    PlayerScreen(m, onNext = { request = it }, onPip = { enterPip() },
                        onClose = {
                            // Ended here: the page shows its artwork again.
                            if (forPage) PlayerSession.back = PlayerSession.Back(null, request)
                            finish()
                        },
                        mode = if (forPage) PlayerMode.ForPage else PlayerMode.Alone,
                        startSideways = sideways,
                        onUpright = {
                            givenBack = true
                            PlayerSession.back = PlayerSession.Back(m, request)
                            finish()
                            // No slide: the page's picture takes over where this one was.
                            @Suppress("DEPRECATION") overridePendingTransition(0, 0)
                        })
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

    // Picture in Picture: the window the shape of the film (within what the system allows), play
    // and pause on it, and on Android 12 and later it starts by itself on the way out of the app
    // while the film plays, so the picture shrinks straight into it.
    private fun pipParams(): PictureInPictureParams {
        val m = model
        val ratio = (m?.aspect ?: (16f / 9f)).coerceIn(1 / 2.39f, 2.39f)
        val playing = m?.isPlaying == true
        val toggle = RemoteAction(
            Icon.createWithResource(this, if (playing) android.R.drawable.ic_media_pause else android.R.drawable.ic_media_play),
            if (playing) "Pause" else "Play", if (playing) "Pause" else "Play",
            PendingIntent.getBroadcast(this, 0, Intent(PIP_TOGGLE).setPackage(packageName), PendingIntent.FLAG_IMMUTABLE),
        )
        return PictureInPictureParams.Builder()
            .setAspectRatio(Rational((ratio * 1000).toInt(), 1000))
            .setActions(listOf(toggle))
            .apply {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    setAutoEnterEnabled(playing)
                    setSeamlessResizeEnabled(false)
                }
            }
            .build()
    }

    private fun updatePip() { runCatching { setPictureInPictureParams(pipParams()) } }

    private fun enterPip() { runCatching { enterPictureInPictureMode(pipParams()) } }

    /** The window's play and pause button. */
    private val pipToggle = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) { model?.togglePlay() }
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(pipToggle) }
        super.onDestroy()
    }

    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        // Later Androids start it themselves; see pipParams.
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S && model?.isPlaying == true) enterPip()
    }

    override fun onPictureInPictureModeChanged(inPip: Boolean, newConfig: Configuration) {
        super.onPictureInPictureModeChanged(inPip, newConfig)
        model?.inPip = inPip
    }

    override fun onStop() {
        super.onStop()
        // Out of sight and not in the little window: pause, and save the place.
        if (!isInPictureInPictureMode && !givenBack) model?.pauseForBackground()
    }
}

// A title chosen in the player, for the app's own screen to open once the player has gone.
object PlayerHandOff {
    var title by mutableStateOf<Card?>(null)
}

// One page for a title, playing or not, as on iOS: Play turns the title page's artwork into the
// player (Inline), and the phone turned sideways or Full Screen hands the same playback to this
// activity (ForPage), which hands it back, still playing, when the phone is upright again.
enum class PlayerMode { Alone, Inline, ForPage }

/** The playback on its way between the title page and the whole screen. */
object PlayerSession {
    /** Given to the whole screen by the title page. */
    var handed: PlayerModel? = null
    /** Given back: the model playing (null when it ended there) and what it plays. */
    class Back(val model: PlayerModel?, val request: PlayRequest)
    var back by mutableStateOf<Back?>(null)
}

private const val UP_NEXT_LEAD = 20.0
private const val UP_NEXT_AFTER_END = 5.0

@androidx.annotation.OptIn(UnstableApi::class)
@kotlin.OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun PlayerScreen(
    model: PlayerModel,
    onNext: (PlayRequest) -> Unit,
    onClose: () -> Unit,
    onPip: () -> Unit,
    mode: PlayerMode = PlayerMode.Alone,
    /** Inline: the strip's X, which is the page's. */
    onClosePage: (() -> Unit)? = null,
    /** Inline: the whole screen, turned sideways at once (true) or already sideways. */
    onFullScreen: ((Boolean) -> Unit)? = null,
    /** ForPage: upright again, back to the page. */
    onUpright: (() -> Unit)? = null,
    /** ForPage: opened by Full Screen, so turned sideways at once. */
    startSideways: Boolean = false,
) {
    val configuration = LocalConfiguration.current
    val portrait = configuration.orientation == Configuration.ORIENTATION_PORTRAIT
    // The page's picture is the strip whatever the window; the whole screen
    // for a page is never the upright player, which would be a second page.
    val upright = when (mode) {
        PlayerMode.Inline -> true
        PlayerMode.ForPage -> false
        PlayerMode.Alone -> portrait
    }
    val phone = !xyz.vibestream.app.ui.isWide()
    var chrome by remember { mutableStateOf(true) }
    var locked by remember { mutableStateOf(false) }
    /** The padlock is closing but the screen has not gone yet. */
    var locking by remember { mutableStateOf(false) }
    /** The padlock, which a tap on a locked screen brings back. */
    var lockHint by remember { mutableStateOf(false) }
    /** The padlock tapped: it has opened out into the slider. */
    var unlockOpen by remember { mutableStateOf(false) }
    /** Just unlocked: a larger open padlock where the slider was, for a moment. */
    var justUnlocked by remember { mutableStateOf(false) }
    var lockJob by remember { mutableStateOf<Job?>(null) }
    /** Full Screen, or its way back, pressed: the window is held sideways
     *  (true) or upright (false) until the phone is turned to match. */
    var turnedTo by remember { mutableStateOf<Boolean?>(null) }
    /** What the window was asked to do before the lock held it. */
    var heldFrom by remember { mutableIntStateOf(ActivityInfo.SCREEN_ORIENTATION_FULL_USER) }
    var tray by remember { mutableStateOf(Debug.string("tray")) }
    /** Settings, sideways: the picture in a box on the left, pills on the right. */
    var settingsOpen by remember { mutableStateOf(false) }
    /** Settings is on Subtitle Appearance: a sample line on the picture. */
    var previewingLook by remember { mutableStateOf(false) }
    /** Playback stats over the picture, chosen in Settings > Debug. Kept. */
    val context = androidx.compose.ui.platform.LocalContext.current
    var statsShown by remember { mutableStateOf(PlayerPrefs.statsShown(context)) }
    var castPicking by remember { mutableStateOf(false) }
    var clipping by remember { mutableStateOf(false) }
    LaunchedEffect(model) { model.onRemoteStop = onClose }
    var episodesOpen by remember { mutableStateOf(false) }
    var creditsChosen by remember { mutableStateOf(false) }
    var filling by remember { mutableStateOf(false) }
    var hideJob by remember { mutableStateOf<Job?>(null) }
    var scrubbing by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val activity = androidx.compose.ui.platform.LocalContext.current as ComponentActivity
    // Awake while the film plays and only then: paused, the phone may dim
    // and sleep as usual.
    DisposableEffect(model.isPlaying) {
        if (model.isPlaying) activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose { activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }

    fun showChrome() {
        chrome = true
        hideJob?.cancel()
        // Four seconds, paused or not; never from under a finger on the
        // scrubber or while something opened from the controls is up.
        hideJob = scope.launch {
            delay(4_000)
            if (!scrubbing && tray == null && !episodesOpen && !clipping && !settingsOpen) chrome = false
        }
    }
    // A locked screen shows nothing at all, so a hand resting on the phone cannot pause or seek.
    // The padlock is summoned rather than parked: a tap anywhere brings it back, a tap on it opens
    // it out into "Slide to unlock", and only a slide most of the way along lets go.
    fun showLockHint() {
        lockHint = true
        lockJob?.cancel()
        // The same four seconds the controls get, then folded back to the
        // padlock so the next tap starts over.
        lockJob = scope.launch { delay(4_000); lockHint = false; unlockOpen = false }
    }
    fun lock() {
        if (locking || locked) return
        hideJob?.cancel()
        // The padlock seen closing first: it is the only confirmation the
        // action gives, and taking the controls away at once hid it.
        locking = true
        scope.launch {
            delay(420)
            locked = true
            chrome = false
            locking = false
            // Locked means the screen stays the way it is, turning included.
            heldFrom = activity.requestedOrientation
            activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LOCKED
            // Shown once on the way in, so the way out has been seen.
            showLockHint()
        }
    }
    fun unlock() {
        lockJob?.cancel()
        locked = false
        lockHint = false
        unlockOpen = false
        // Free to turn again.
        activity.requestedOrientation = heldFrom
        // Then just the picture: no controls in its place (a tap brings
        // them, as always), only the open padlock for a moment.
        justUnlocked = true
        scope.launch { delay(1_000); justUnlocked = false }
    }

    // Full Screen from the strip, and back. The window is turned whichever way the phone is held,
    // as the reference does, so a phone lying upright on a table still goes sideways.
    fun turn(sideways: Boolean) {
        turnedTo = sideways
        activity.requestedOrientation =
            if (sideways) ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE else ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
    }
    /** The phone now held the way the window was turned: let go of it. */
    fun settle(sideways: Boolean) {
        val wanted = turnedTo ?: return
        if (locked || locking || wanted != sideways) return
        val autoRotate = android.provider.Settings.System.getInt(activity.contentResolver,
            android.provider.Settings.System.ACCELEROMETER_ROTATION, 0) == 1
        if (sideways && !autoRotate) return
        turnedTo = null
        activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_FULL_USER
    }

    fun playNext() {
        val next = model.info?.next ?: return
        model.stop()
        onNext(PlayRequest(next.playID, model.request.title, season = next.season, episode = next.number))
    }
    fun playEpisode(item: EpisodeItem) {
        val id = item.playID ?: return
        model.stop()
        onNext(PlayRequest(id, model.request.title, season = item.season, episode = item.episode))
    }

    LaunchedEffect(upright) {
        val controller = WindowInsetsControllerCompat(activity.window, activity.window.decorView)
        if (mode == PlayerMode.Inline) Unit
        else if (upright) controller.show(WindowInsetsCompat.Type.statusBars())
        else {
            controller.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            controller.hide(WindowInsetsCompat.Type.systemBars())
        }
        if (upright) { episodesOpen = false; tray = null; settingsOpen = false }
        showChrome()
    }
    // For a page: Full Screen turns at once; upright again, the page has it.
    var seenSideways by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { if (mode == PlayerMode.ForPage && startSideways) turn(sideways = true) }
    LaunchedEffect(portrait) {
        if (mode != PlayerMode.ForPage) return@LaunchedEffect
        if (!portrait) seenSideways = true
        else if (seenSideways && !locked) onUpright?.invoke()
    }
    LaunchedEffect(Unit) {
        showChrome()
        if (Debug.has("locked")) lock()
        if (Debug.has("chrome")) { delay(6_000); showChrome() }
        if (Debug.has("settings")) { delay(7_000); settingsOpen = true }
        if (Debug.has("episodesPanel")) { delay(7_000); episodesOpen = true }
        if (Debug.has("clipEditor")) { delay(9_000); clipping = true }
    }
    LaunchedEffect(model.ended) {
        if (!model.ended) return@LaunchedEffect
        if (model.info?.next == null) { onClose(); return@LaunchedEffect }
        if (creditsChosen) delay((UP_NEXT_AFTER_END * 1000).toLong())
        playNext()
    }
    // Which way the phone itself is held, whatever the window is doing.
    // Inline: turned upright once since, so a phone already sideways when
    // the whole screen gave the playback back does not take it again at once.
    val seenUpright = remember { mutableStateOf(false) }
    DisposableEffect(Unit) {
        val natural = naturallyLandscape(activity)
        val listener = object : android.view.OrientationEventListener(activity) {
            override fun onOrientationChanged(degrees: Int) {
                // Flat on a table says nothing; between the two, neither yet.
                val sideways = when {
                    degrees < 0 -> return
                    degrees in 60..120 || degrees in 240..300 -> true
                    degrees <= 30 || degrees >= 330 || degrees in 150..210 -> false
                    else -> return
                } != natural
                if (mode == PlayerMode.Inline) {
                    // The page's picture, and the phone turned sideways: the
                    // whole screen, with the same playback.
                    if (!sideways) seenUpright.value = true
                    else if (seenUpright.value && phone && model.ready && model.error == null) {
                        seenUpright.value = false
                        onFullScreen?.invoke(false)
                    }
                    return
                }
                settle(sideways)
            }
        }
        listener.enable()
        onDispose { listener.disable() }
    }
    // Sampled only while the playback stats are on screen.
    LaunchedEffect(statsShown && model.ready) {
        if (!statsShown || !model.ready) return@LaunchedEffect
        while (true) { model.stats.tick(); delay(1_000) }
    }
    BackHandler(enabled = mode != PlayerMode.Inline) {
        when {
            // A swipe from the edge is as easy for a palm as a tap.
            locked -> showLockHint()
            settingsOpen -> { settingsOpen = false; showChrome() }
            episodesOpen -> { episodesOpen = false; showChrome() }
            else -> onClose()
        }
    }

    val upNext = model.info?.next?.takeIf {
        model.ready && model.error == null && !locked && model.duration > 0 &&
            (model.ended || (!creditsChosen && model.duration - model.current <= UP_NEXT_LEAD))
    }
    val fill = if (model.ended) 1.0 else (1 - (model.duration - model.current).coerceAtLeast(0.0) / UP_NEXT_LEAD).coerceIn(0.0, 1.0)

    Column((if (mode == PlayerMode.Inline) Modifier.fillMaxWidth() else Modifier.fillMaxSize()).background(Color.Black)) {
        BoxWithConstraints(
            Modifier.fillMaxWidth()
                .then(when {
                    mode == PlayerMode.Inline -> Modifier.aspectRatio(16f / 9f)
                    upright -> Modifier.statusBarsPadding().aspectRatio(16f / 9f)
                    else -> Modifier.fillMaxSize()
                }),
        ) {
            // One picture, whichever way up and whatever is open. Settings open sideways, it is the
            // same picture, still playing, in a rounded 16:9 box at the left, as wide as leaves the
            // panel a column and never taller than the screen.
            val boxed = (settingsOpen || episodesOpen) && !upright
            val boxWidth = minOf(maxWidth * 0.58f, (maxHeight - 36.dp) * 16f / 9f)
            val stageWidth by animateDpAsState(if (boxed) boxWidth else maxWidth, label = "width")
            val stageHeight by animateDpAsState(if (boxed) boxWidth * 9f / 16f else maxHeight, label = "height")
            val inset by animateDpAsState(if (boxed) 6.dp else 0.dp, label = "inset")
            val corner by animateDpAsState(if (boxed) 22.dp else 0.dp, label = "corner")
            // Subtitles lifted clear of the controls while they show.
            val lift = if (chrome && !locked && !boxed) (if (upright) 0.24f else 0.2f) else 0.06f
            Box(
                Modifier.align(Alignment.CenterStart).padding(start = inset).size(stageWidth, stageHeight)
                    .shadow(if (boxed) 24.dp else 0.dp, RoundedCornerShape(corner)).clip(RoundedCornerShape(corner)).background(Color.Black)
                    // Sideways, filling the screen is a pinch, on a phone and a
                    // tablet alike: spread to fill, pinch to fit the whole picture.
                    .pointerInput(upright, locked, episodesOpen, clipping, boxed) {
                        if (upright || locked || episodesOpen || clipping || boxed) return@pointerInput
                        awaitEachGesture {
                            awaitFirstDown(requireUnconsumed = false)
                            var zoom = 1f
                            do {
                                val event = awaitPointerEvent()
                                if (event.changes.count { it.pressed } >= 2) {
                                    zoom *= event.calculateZoom()
                                    // Two fingers are a pinch, never a tap as well.
                                    event.changes.forEach { if (it.positionChanged()) it.consume() }
                                }
                            } while (event.changes.any { it.pressed })
                            if (zoom > 1.05f) filling = true else if (zoom < 0.95f) filling = false
                        }
                    }
                    .pointerInput(locked, tray, episodesOpen, boxed) {
                        detectTapGestures {
                            when {
                                locked -> showLockHint()
                                // The box beside Settings or Episodes plays and pauses; the X closes.
                                boxed -> model.togglePlay()
                                // A tap on the picture puts away whatever is open, as a menu.
                                tray != null -> { tray = null; showChrome() }
                                chrome -> chrome = false
                                else -> showChrome()
                            }
                        }
                    },
            ) {
                // Made again when the clip editor closes: its preview took the
                // player's picture, and this view has to take it back.
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
                        it.subtitleView?.let { view ->
                            SubtitleLook.apply(view, model.subtitleSize, model.subtitleStyle, stageHeight.value, lift)
                            // The sample line stands in for them while the look is chosen.
                            view.visibility = if (boxed && previewingLook) android.view.View.INVISIBLE else android.view.View.VISIBLE
                        }
                    },
                    modifier = Modifier.fillMaxSize(),
                ) }
                // The picture is a SurfaceView, which a clip does not reach:
                // its corners are rounded by painting the ground over them.
                if (corner > 0.dp) androidx.compose.foundation.Canvas(Modifier.fillMaxSize()) {
                    val radius = corner.toPx()
                    drawPath(androidx.compose.ui.graphics.Path().apply {
                        fillType = androidx.compose.ui.graphics.PathFillType.EvenOdd
                        addRect(androidx.compose.ui.geometry.Rect(androidx.compose.ui.geometry.Offset.Zero, size))
                        addRoundRect(androidx.compose.ui.geometry.RoundRect(androidx.compose.ui.geometry.Rect(androidx.compose.ui.geometry.Offset.Zero, size),
                            androidx.compose.ui.geometry.CornerRadius(radius)))
                    }, Color.Black)
                }
                if (boxed && previewingLook) {
                    SubtitleSample(SAMPLE_CAPTION, model.subtitleSize, model.subtitleStyle, base = SubtitleLook.base(stageHeight.value),
                        modifier = Modifier.align(Alignment.BottomCenter).padding(horizontal = 24.dp).padding(bottom = stageHeight * 0.06f))
                }

                model.error?.let { message ->
                    Column(Modifier.align(Alignment.Center).padding(if (upright) 10.dp else 40.dp)
                        .background(Color(0xE6202020), RoundedCornerShape(20.dp)).padding(if (upright) 14.dp else 26.dp),
                        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("Cannot play this title", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Palette.accent)
                        Text(message, fontSize = 13.sp, color = Palette.dim, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            Pill(true, Modifier.width(130.dp), onClick = model::retry) { PillLabel("Try Again") }
                            Pill(false, Modifier.width(120.dp), onClick = onClose) { PillLabel("Close") }
                        }
                    }
                }
                if (model.error == null && (!model.ready || model.buffering)) Box(Modifier.align(Alignment.Center)) { BootSpinner() }

                // In the settings box a tap plays and pauses; paused, it says so.
                androidx.compose.animation.AnimatedVisibility(boxed && model.ready && !model.isPlaying && !model.buffering && model.error == null,
                    modifier = Modifier.align(Alignment.Center), enter = fadeIn() + scaleIn(initialScale = 0.85f), exit = fadeOut() + scaleOut(targetScale = 0.85f)) {
                    Box(Modifier.size(64.dp).background(Color.Black.copy(alpha = 0.45f), CircleShape), contentAlignment = Alignment.Center) {
                        Icon(Icons.Filled.PlayArrow, null, tint = Color.White, modifier = Modifier.size(36.dp))
                    }
                }

                // Stays up with the controls: drawn under them, and moved down
                // clear of the top bar while it shows.
                if (statsShown && model.ready && !model.inPip) {
                    val clear = chrome && !locked && !boxed && model.error == null
                    val top by animateDpAsState((if (upright || boxed) 8.dp else 14.dp) + (if (clear) (if (upright) 40.dp else 58.dp) else 0.dp), label = "top")
                    StatsOverlay(model, androidx.compose.ui.geometry.Size(stageWidth.value, stageHeight.value),
                        Modifier.padding(top = top, start = if (upright || boxed) 8.dp else 14.dp)
                            .graphicsLayer { val k = if (boxed) 0.85f else 1f; scaleX = k; scaleY = k; transformOrigin = TransformOrigin(0f, 0f) })
                }

                androidx.compose.animation.AnimatedVisibility(chrome && !locked && !boxed && model.error == null && !model.inPip, enter = fadeIn(), exit = fadeOut()) {
                    if (upright) CompactChrome(model, if (mode == PlayerMode.Inline) onClosePage ?: onClose else onClose,
                        if (mode == PlayerMode.Inline) null else onPip, onCast = { castPicking = true },
                        onFull = { if (mode == PlayerMode.Inline) onFullScreen?.invoke(true) else turn(sideways = true) },
                        onScrub = { scrubbing = it }, onTouch = ::showChrome)
                    else FullChrome(model, tray,
                        onClose = onClose, onPip = onPip, onCast = { castPicking = true }, locking = locking, onLock = ::lock,
                        onTray = { tray = if (tray == it) null else it; showChrome() },
                        onClip = { if (model.isPlaying) model.togglePlay(); clipping = true },
                        onSettings = { tray = null; episodesOpen = false; settingsOpen = true },
                        onEpisodes = if (model.info?.mediaID != null && model.info?.presentation?.episode != null)
                            ({ tray = null; settingsOpen = false; episodesOpen = true }) else null,
                        onNext = if (model.info?.next != null) ({ playNext() }) else null,
                        onExit = { turn(sideways = false) },
                        onScrub = { scrubbing = it }, onTouch = ::showChrome)
                }

                upNext?.takeIf { !boxed }?.let { next ->
                    UpNextPills(next, fill, model.ended, onCredits = { creditsChosen = true }, onNext = ::playNext,
                        modifier = Modifier.align(Alignment.BottomEnd)
                            .padding(end = if (upright) 12.dp else 24.dp, bottom = if (upright) (if (chrome) 46.dp else 10.dp) else (if (chrome) 104.dp else 26.dp)))
                }

                androidx.compose.animation.AnimatedVisibility(locked && lockHint, Modifier.align(Alignment.BottomCenter).padding(bottom = 34.dp),
                    enter = fadeIn(), exit = fadeOut()) {
                    SlideToUnlock(unlockOpen,
                        onOpen = { unlockOpen = true; showLockHint() },
                        onUnlock = ::unlock,
                        // Kept up for as long as a finger is on it, and the usual while after.
                        onTouch = { dragging -> if (dragging) lockJob?.cancel() else showLockHint() })
                }
                // Said once, where the slider was: it is unlocked.
                androidx.compose.animation.AnimatedVisibility(justUnlocked, Modifier.align(Alignment.BottomCenter).padding(bottom = 34.dp),
                    enter = fadeIn() + scaleIn(initialScale = 0.8f), exit = fadeOut(tween(500))) {
                    Icon(Icons.Filled.LockOpen, "Unlocked", tint = Color.White,
                        modifier = Modifier.size(44.dp).shadow(6.dp, CircleShape, ambientColor = Color.Black, spotColor = Color.Black))
                }

            }

            androidx.compose.animation.AnimatedVisibility(boxed, modifier = Modifier.align(Alignment.CenterEnd),
                enter = slideInHorizontally { it / 2 } + fadeIn(), exit = slideOutHorizontally { it / 2 } + fadeOut()) {
                Box(Modifier.width(maxOf(240.dp, maxWidth - boxWidth - 34.dp)).fillMaxHeight().padding(vertical = 14.dp).padding(end = 14.dp)) {
                    val media = model.info?.mediaID
                    val episode = model.info?.presentation?.episode
                    if (settingsOpen) PlayerSettings(model, statsShown,
                        onStats = { statsShown = it; PlayerPrefs.setStatsShown(activity, it) },
                        onPreviewLook = { previewingLook = it },
                        onClose = { settingsOpen = false; showChrome() })
                    else if (media != null && episode != null) PlayerEpisodes(media, episode.season, model.request.playID, stacked = false,
                        onChoose = ::playEpisode, onClose = { episodesOpen = false; showChrome() })
                }
            }
        }

        // Another title is somewhere else: the player goes and its page opens.
        if (mode == PlayerMode.Alone && upright) PlayerPage(model, onEpisode = ::playEpisode, onTitle = { PlayerHandOff.title = it; onClose() })
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
}

/** A tablet whose sensor's zero is a landscape hold. */
@Suppress("DEPRECATION")
private fun naturallyLandscape(activity: ComponentActivity): Boolean {
    val rotation = (if (Build.VERSION.SDK_INT >= 30) activity.display?.rotation else activity.windowManager.defaultDisplay.rotation) ?: 0
    val landscape = activity.resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE
    val turned = rotation == android.view.Surface.ROTATION_90 || rotation == android.view.Surface.ROTATION_270
    return landscape != turned
}

@Composable
private fun ChromeButton(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, size: Int = 22, dim: Boolean = false,
                         onClick: () -> Unit) {
    Box(Modifier.size(44.dp).pressable(onClick = onClick), contentAlignment = Alignment.Center) {
        Icon(icon, label, tint = Color.White.copy(alpha = if (dim) 0.5f else 1f), modifier = Modifier.size(size.dp).shadow(3.dp, CircleShape, ambientColor = Color.Black, spotColor = Color.Black))
    }
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

/*
 * The scrubber: an Ember line with a knob, the time left at its end. A drag
 * moves the knob and seeks on release; while it lasts, the frame under the
 * knob rides above the finger with its time, from the trickplay sheets.
 */
@Composable
private fun Scrubber(model: PlayerModel, modifier: Modifier = Modifier, onScrub: (Boolean) -> Unit, onTouch: () -> Unit) {
    var width by remember { mutableStateOf(1) }
    var dragging by remember { mutableStateOf<Double?>(null) }
    var preview by remember { mutableStateOf<ThumbFrame?>(null) }
    // One lookup at a time, each for wherever the knob is by the time the
    // last one finished, so the frame keeps up with a moving finger.
    LaunchedEffect(model) {
        snapshotFlow { dragging }.conflate().collect { at ->
            if (at == null) preview = null else model.thumbnail(at)?.let { preview = it }
        }
    }
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
                        onDragStart = { dragging = (it.x / width * model.duration); onScrub(true) },
                        onDragEnd = { dragging?.let(model::seek); dragging = null; onScrub(false); onTouch() },
                        onDragCancel = { dragging = null; onScrub(false) },
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
            dragging?.let { at ->
                val tile = 150.dp
                val ratio = preview?.let { it.size.height.toFloat() / maxOf(1, it.size.width) } ?: (9f / 16f)
                Column(Modifier.align(Alignment.BottomStart).wrapContentSize(Alignment.BottomStart, unbounded = true)
                    // Clamped so it cannot slide off either end of the screen.
                    .offset { IntOffset((fraction * width - tile.toPx() / 2).coerceIn(0f, maxOf(0f, width - tile.toPx())).toInt(), -34.dp.roundToPx()) },
                    horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Box(Modifier.size(tile, tile * ratio).clip(RoundedCornerShape(6.dp)).background(Color.Black.copy(alpha = 0.6f))
                        .border(1.5.dp, Color.White.copy(alpha = 0.9f), RoundedCornerShape(6.dp))) {
                        // While the next frame loads, the last one stays up.
                        preview?.let { frame ->
                            androidx.compose.foundation.Canvas(Modifier.fillMaxSize()) {
                                drawImage(frame.sheet, frame.offset, frame.size, IntOffset.Zero, IntSize(size.width.toInt(), size.height.toInt()))
                            }
                        }
                    }
                    Text(timecode(at), fontSize = 11.sp, color = Color.White,
                        modifier = Modifier.background(Color.Black.copy(alpha = 0.8f), RoundedCornerShape(4.dp)).padding(horizontal = 7.dp, vertical = 2.dp))
                }
            }
        }
        Text(timecode((model.duration - shown).coerceAtLeast(0.0)), fontSize = 13.sp, color = Color.White)
    }
}

@Composable
private fun CompactChrome(model: PlayerModel, onClose: () -> Unit, onPip: (() -> Unit)?, onCast: () -> Unit, onFull: () -> Unit,
                          onScrub: (Boolean) -> Unit, onTouch: () -> Unit) {
    Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color.Black.copy(alpha = 0.55f), Color.Black.copy(alpha = 0.15f), Color.Black.copy(alpha = 0.65f))))) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp)) {
            ChromeButton(Icons.Filled.Close, "Close", onClick = onClose)
            Spacer(Modifier.weight(1f))
            if (model.ready) {
                CastButton(onCast)
                onPip?.let { ChromeButton(Icons.Outlined.PictureInPictureAlt, "Picture in Picture", onClick = it) }
            }
        }
        if (model.ready) {
            Box(Modifier.align(Alignment.Center)) { CentreControls(model, compact = true, onTouch = onTouch) }
            Row(Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(start = 16.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Scrubber(model, Modifier.weight(1f), onScrub, onTouch)
                ChromeButton(Icons.Filled.Fullscreen, "Full Screen", onClick = onFull)
            }
        }
    }
}

// The sideways controls. The top bar: the X (only where there is no Exit Full Screen, which on a
// phone already is the way out), what is playing, then playing elsewhere, Picture in Picture and
// the lock.
@Composable
private fun FullChrome(
    model: PlayerModel,
    tray: String?,
    onClose: () -> Unit,
    onPip: () -> Unit,
    onCast: () -> Unit,
    locking: Boolean,
    onLock: () -> Unit,
    onTray: (String) -> Unit,
    onClip: () -> Unit,
    onSettings: () -> Unit,
    onEpisodes: (() -> Unit)?,
    onNext: (() -> Unit)?,
    onExit: () -> Unit,
    onScrub: (Boolean) -> Unit,
    onTouch: () -> Unit,
) {
    val tablet = LocalConfiguration.current.smallestScreenWidthDp >= 600
    Column(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color.Black.copy(alpha = 0.65f), Color.Transparent, Color.Black.copy(alpha = 0.8f))))
        .padding(horizontal = 20.dp, vertical = 14.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            if (tablet) ChromeButton(Icons.Filled.Close, "Close", onClick = onClose)
            Column(Modifier.weight(1f)) {
                Text(model.info?.presentation?.title ?: model.request.title, fontSize = 17.sp, fontWeight = FontWeight.SemiBold,
                    color = Color.White, maxLines = 1)
                model.info?.presentation?.episodeLine?.let { Text(it, fontSize = 13.sp, color = Color.White.copy(alpha = 0.75f), maxLines = 1) }
            }
            if (model.ready) CastButton(onCast)
            if (model.ready) ChromeButton(Icons.Outlined.PictureInPictureAlt, "Picture in Picture", onClick = onPip)
            // The padlock visibly closes before the screen goes.
            androidx.compose.animation.Crossfade(locking, label = "lock") { closing ->
                ChromeButton(if (closing) Icons.Filled.Lock else Icons.Filled.LockOpen, "Lock", onClick = onLock)
            }
        }
        Spacer(Modifier.weight(1f))
        if (model.ready) {
            Box(Modifier.align(Alignment.CenterHorizontally)) { CentreControls(model, compact = false, onTouch = onTouch) }
            Spacer(Modifier.weight(1f))
            if (tray != null) Box(Modifier.fillMaxWidth().padding(bottom = 12.dp), contentAlignment = Alignment.Center) {
                if (tray == "speed") SpeedTray(model, onTouch) else BrightnessTray(onTouch)
            }
            Scrubber(model, Modifier.fillMaxWidth(), onScrub, onTouch)
            Spacer(Modifier.height(8.dp))
            // One row of icons, no names: they say what they are.
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(if (tablet) 30.dp else 22.dp), verticalAlignment = Alignment.CenterVertically) {
                ChromeButton(Icons.Filled.ContentCut, "Clip", onClick = onClip)
                Spacer(Modifier.weight(1f))
                onEpisodes?.let { ChromeButton(Icons.Outlined.Layers, "Episodes", onClick = it) }
                onNext?.let { ChromeButton(Icons.Filled.SkipNext, "Next Episode", onClick = it) }
                ChromeButton(Icons.Outlined.Speed, "Speed (${speedLabel(model.rate)})", dim = tray == "brightness") { onTray("speed") }
                ChromeButton(Icons.Outlined.LightMode, "Brightness", dim = tray == "speed") { onTray("brightness") }
                ChromeButton(Icons.Outlined.Settings, "Settings", onClick = onSettings)
                if (!tablet) ChromeButton(Icons.Filled.FullscreenExit, "Exit Full Screen", onClick = onExit)
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

/*
 * Speed: six stops on a line, the one playing as the large dot. A tap on a
 * stop or a slide along the line chooses, with a tick under the finger at
 * each stop passed.
 */
@Composable
private fun SpeedTray(model: PlayerModel, onTouch: () -> Unit) {
    val stops = listOf(0.5f, 0.75f, 1f, 1.25f, 1.5f, 2f)
    val view = androidx.compose.ui.platform.LocalView.current
    var width by remember { mutableIntStateOf(1) }
    fun choose(x: Float) {
        val index = (x / width * (stops.size - 1)).roundToInt().coerceIn(0, stops.lastIndex)
        if (stops[index] != model.rate) {
            model.setSpeed(stops[index])
            view.performHapticFeedback(android.view.HapticFeedbackConstants.CLOCK_TICK)
        }
        onTouch()
    }
    TrayCard {
        Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("Playback Speed", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Color.White.copy(alpha = 0.7f))
            Column(Modifier.padding(horizontal = 14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(Modifier.fillMaxWidth().height(24.dp).onSizeChanged { width = maxOf(1, it.width) }
                    .pointerInput(Unit) {
                        awaitEachGesture {
                            val down = awaitFirstDown()
                            choose(down.position.x)
                            drag(down.id) { change -> choose(change.position.x); change.consume() }
                        }
                    }, contentAlignment = Alignment.CenterStart) {
                    Box(Modifier.fillMaxWidth().height(2.dp).background(Color.White.copy(alpha = 0.25f), CircleShape))
                    stops.forEachIndexed { index, stop ->
                        val chosen = model.rate == stop
                        val dot by animateDpAsState(if (chosen) 20.dp else 8.dp, label = "dot")
                        Box(Modifier.centredAt(index / (stops.size - 1f)).size(dot)
                            .background(Color.White.copy(alpha = if (chosen) 1f else 0.55f), CircleShape))
                    }
                }
                Box(Modifier.fillMaxWidth()) {
                    stops.forEachIndexed { index, stop ->
                        val chosen = model.rate == stop
                        Text(speedLabel(stop), fontSize = 12.sp, fontWeight = if (chosen) FontWeight.Bold else FontWeight.Normal,
                            color = Color.White.copy(alpha = if (chosen) 1f else 0.6f), maxLines = 1,
                            modifier = Modifier.centredAt(index / (stops.size - 1f)))
                    }
                }
            }
        }
    }
}

private fun speedLabel(rate: Float) = if (rate == 1f) "1x" else "${rate}x".replace(".0x", "x")

/** Laid out across the whole width, with its middle at `fraction` of it. */
private fun Modifier.centredAt(fraction: Float) = layout { measurable, constraints ->
    val placeable = measurable.measure(constraints.copy(minWidth = 0))
    layout(constraints.maxWidth, placeable.height) {
        placeable.place((constraints.maxWidth * fraction - placeable.width / 2f).roundToInt(), 0)
    }
}

@Composable
private fun TrayCard(content: @Composable () -> Unit) {
    Box(Modifier.widthIn(max = 380.dp).fillMaxWidth().background(Color(0xE6202020), RoundedCornerShape(22.dp))
        .padding(horizontal = 22.dp, vertical = 16.dp)) { content() }
}

/*
 * Up next: twenty seconds from the end two pills appear, Watch Credits and
 * Next Episode, and Next Episode fills up from the left; full, the next
 * episode starts. The fill is the time left, so it never cuts one short.
 */
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

// The padlock, and what it opens into. Folded, it is the white knob alone, and a tap opens it out
// into the track: "Slide to unlock". Dragged past most of the way along the shackle opens, with a
// tap felt, and letting go there unlocks; let go short of it and it springs back.
@Composable
private fun SlideToUnlock(open: Boolean, onOpen: () -> Unit, onUnlock: () -> Unit, onTouch: (Boolean) -> Unit) {
    val density = LocalDensity.current
    val width = 250.dp
    val knob = 48.dp
    val inset = 4.dp
    val travel = with(density) { (width - knob - inset * 2).toPx() }
    val offset = remember { Animatable(0f) }
    val scope = rememberCoroutineScope()
    val view = androidx.compose.ui.platform.LocalView.current
    val past = offset.value > travel * 0.85f
    LaunchedEffect(past) {
        if (past) view.performHapticFeedback(
            if (Build.VERSION.SDK_INT >= 30) android.view.HapticFeedbackConstants.CONFIRM else android.view.HapticFeedbackConstants.VIRTUAL_KEY)
    }
    val trackWidth by animateDpAsState(if (open) width else knob + inset * 2, label = "track")
    Box(Modifier.width(trackWidth).height(knob + inset * 2)
        .background(if (open) Color(0xCC202020) else Color.Transparent, CircleShape), contentAlignment = Alignment.CenterStart) {
        if (open) Text("Slide to unlock", fontSize = 15.sp, fontWeight = FontWeight.Medium, maxLines = 1,
            color = Color.White.copy(alpha = 0.85f * (1 - offset.value / travel * 1.6f).coerceIn(0f, 1f)),
            modifier = Modifier.align(Alignment.Center).padding(start = knob * 0.6f))
        Box(Modifier.offset { IntOffset((inset.toPx() + offset.value).toInt(), 0) }.size(knob).background(Color.White, CircleShape)
            .pointerInput(open) {
                if (!open) { detectTapGestures { onOpen() }; return@pointerInput }
                detectHorizontalDragGestures(
                    onDragStart = { onTouch(true) },
                    onDragEnd = {
                        scope.launch {
                            if (offset.value > travel * 0.85f) {
                                offset.animateTo(travel, tween(120))
                                // The shackle seen opening before the slider gives way.
                                delay(280)
                                onUnlock()
                            } else {
                                offset.animateTo(0f, spring(dampingRatio = 0.6f))
                                onTouch(false)
                            }
                        }
                    },
                    onDragCancel = { scope.launch { offset.animateTo(0f) }; onTouch(false) },
                ) { change, amount ->
                    change.consume()
                    scope.launch { offset.snapTo((offset.value + amount).coerceIn(0f, travel)) }
                }
            }, contentAlignment = Alignment.Center) {
            androidx.compose.animation.Crossfade(past, label = "shackle") { opened ->
                Icon(if (opened) Icons.Filled.LockOpen else Icons.Filled.Lock, if (open) "Slide to unlock" else "Screen locked",
                    tint = Color.Black, modifier = Modifier.size(20.dp))
            }
        }
    }
}

@Composable
internal fun TrackPanel(model: PlayerModel, inline: Boolean = false) {
    val info = model.info ?: return
    var audioOpen by remember { mutableStateOf(false) }
    var subsOpen by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(horizontal = if (inline) 0.dp else 16.dp).padding(bottom = if (inline) 0.dp else 30.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        if (!inline) Text("Audio & Subtitles", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
            modifier = Modifier.fillMaxWidth(), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        Column(Modifier.background(Color.White.copy(alpha = 0.08f), RoundedCornerShape(14.dp))) {
            Box {
                TrackRow("Audio", info.audio.firstOrNull { it.index == model.currentAudio }?.label ?: "Default") { audioOpen = true }
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
                SubtitleSample("Where are we going?", model.subtitleSize, model.subtitleStyle, modifier = Modifier.padding(bottom = 16.dp))
            }
            Text("SIZE", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = Palette.faint)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SubtitleLook.sizes.forEach { (value, label) ->
                    val on = model.subtitleSize == value
                    Text(label, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = if (on) Color.Black else Color.White,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                        modifier = Modifier.weight(1f).background(if (on) Color.White else Color.White.copy(alpha = 0.12f), CircleShape)
                            .pressable { model.setLook(size = value) }.padding(vertical = 8.dp))
                }
            }
            Text("STYLE", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = Palette.faint)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SubtitleLook.styles.forEach { (value, label) ->
                    val on = model.subtitleStyle == value
                    Column(Modifier.weight(1f).background(Color.White.copy(alpha = if (on) 0.18f else 0.06f), RoundedCornerShape(10.dp))
                        .then(if (on) Modifier.border(1.5.dp, Color.White, RoundedCornerShape(10.dp)) else Modifier)
                        .pressable { model.setLook(style = value) }.padding(vertical = 10.dp),
                        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        SubtitleSample("Aa", "medium", value)
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
