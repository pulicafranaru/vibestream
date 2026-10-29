package xyz.vibestream.app

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import coil3.SingletonImageLoader
import coil3.request.CachePolicy
import coil3.request.ImageRequest
import coil3.request.allowHardware
import coil3.toBitmap
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.PlayInfo
import xyz.vibestream.app.api.PlayRequest
import xyz.vibestream.app.api.Trickplay
import xyz.vibestream.app.ui.Cast
import xyz.vibestream.app.ui.CastCommand
import xyz.vibestream.app.ui.CastPlaying
import xyz.vibestream.app.ui.ClipSource
import xyz.vibestream.app.ui.said
// The model: the server's HLS through ExoPlayer, attached only once the rendition is complete.
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
    /** The audio playing: the one chosen, else the one the server plays
     *  when none is asked for, which is the track flagged default. */
    val currentAudio: Int? get() = audioIndex ?: info?.defaultAudio?.index
    var inPip by mutableStateOf(false)
    /** The picture's width over its height, once the video says. */
    var aspect by mutableStateOf<Float?>(null)
    var prefs = AppState.playerPrefs
    /** How subtitles look: the TV's sizes and styles, remembered per profile. */
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
    /** What the player is doing, for the stats overlay. */
    val stats = PlayerStats(player)

    private var pendingResume = 0.0
    // Where a seek still landing is going, so the clock ticks do not drag the scrubber back to.
    private var seekTarget: Double? = null
    private var seekSerial = 0
    private var renditionJob: Job? = null
    private var watchdog: Job? = null
    /** Whether the start has been rebuilt once already. See watchStart. */
    private var rebuilt = false
    /** Paused by the person, which the start must not undo. */
    private var heldByUser = false
    /** An item attached and not yet begun: its first ready is the start. */
    private var starting = false
    private var startAt = request.startAt
    private var stopped = false
    private val jobs = mutableListOf<Job>()
    private var castToken: String? = null
    /** Whose progress this is, kept for the last report after a switch. */
    val profile = Api.profileID
    /** Set by the screen: a stop sent from the remote closes the player. */
    var onRemoteStop: (() -> Unit)? = null

    init {
        player.addListener(object : Player.Listener {
            // Playing is wanting to play, waiting for data included, as iOS
            // reads it: the button says pause while a seek loads.
            override fun onVideoSizeChanged(size: androidx.media3.common.VideoSize) {
                if (size.width > 0 && size.height > 0) aspect = size.width * size.pixelWidthHeightRatio / size.height
            }
            override fun onEvents(p: Player, events: Player.Events) {
                isPlaying = p.playWhenReady && (p.playbackState == Player.STATE_READY || p.playbackState == Player.STATE_BUFFERING)
            }
            override fun onPlaybackStateChanged(state: Int) {
                buffering = state == Player.STATE_BUFFERING
                if (state == Player.STATE_READY) {
                    player.duration.takeIf { it > 0 }?.let { duration = it / 1000.0 }
                    if (duration == 0.0) duration = info?.resume?.runtime ?: 0.0
                    applySubtitleSelection()
                    if (starting) begin()
                }
                if (state == Player.STATE_ENDED) { ended = true; report() }
            }
            override fun onPlayerError(e: PlaybackException) {
                watchdog?.cancel()
                error = sentence(e)
            }
        })
        jobs += AppState.launch {
            // Four ticks a second: enough for the scrubber to look continuous.
            while (isActive) {
                val at = player.currentPosition / 1000.0
                val target = seekTarget
                if (target == null) current = at
                // Landed: the clock is where the knob was put, and runs on.
                else if (player.playbackState == Player.STATE_READY && kotlin.math.abs(at - target) < 1.5) {
                    seekTarget = null
                    current = at
                }
                delay(250)
            }
        }
        jobs += AppState.launch {
            while (isActive) { delay(10_000); if (isPlaying) report() }
        }
        jobs += AppState.launch { start() }
        // Another device's remote: its commands in, and what this is doing
        // out, every two seconds while it plays.
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
                        subtitleID = subtitleID, audioIndex = currentAudio,
                        subtitleSize = subtitleSize, subtitleStyle = subtitleStyle))
                }
                delay(2_000)
            }
        }
    }


    private fun obey(command: CastCommand) {
        when (command.type) {
            "pause" -> if (player.playWhenReady) togglePlay()
            "resume" -> if (!player.playWhenReady) togglePlay()
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
            prepareRendition()
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            error = e.said()
        }
    }

    /** The wait for the rendition, started afresh: any earlier one is dropped. */
    private fun prepareRendition() {
        renditionJob?.cancel()
        renditionJob = AppState.launch { waitForRendition() }
    }

    // A start that goes nowhere is rebuilt once, then said.
    private fun watchStart() {
        watchdog?.cancel()
        watchdog = AppState.launch {
            var loaded = -1L
            var still = 0
            while (isActive) {
                delay(1_000)
                if (stopped || error != null || player.playerError != null || heldByUser) return@launch
                if (player.isPlaying && current > 0) return@launch
                val now = player.bufferedPosition
                if (now != loaded) { loaded = now; still = 0; continue }
                if (++still < 15) continue
                if (rebuilt) {
                    error = "The video stopped loading. Try again."
                    player.pause()
                } else {
                    rebuilt = true
                    restart(seekTarget ?: if (current > 0) current else pendingResume)
                }
                return@launch
            }
        }
    }

    /** The item built again from the start, landing at `position`. */
    private fun restart(position: Double) {
        ready = false
        error = null
        startAt = position
        pendingResume = position
        prepareRendition()
    }

    /** Try Again on the error card: one more go from where it was. */
    fun retry() {
        rebuilt = false
        // Not even the title's details came: those first.
        if (info == null) { error = null; jobs += AppState.launch { start() }; return }
        restart(if (current > 0) current else pendingResume)
    }

    /** What went wrong, as a sentence: the codes are for the logs. */
    private fun sentence(e: PlaybackException) = when (e.errorCode) {
        in 2000..2999 -> "The connection to the server dropped."
        in 3000..3999 -> "The video could not be read."
        in 4000..4999 -> "This device cannot play this video's format."
        else -> "Playback stopped."
    }

    /** Poll /prepare until the rendition is complete, then attach it. */
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
        // Opened at the resume point rather than played from zero and sent
        // there: the first frame shown is the right one, never 0:00 first.
        val target = resumeTarget()
        target?.let { current = it; seekSerial++; seekTarget = it }
        player.setMediaItem(MediaItem.fromUri(url), ((target ?: 0.0) * 1000).toLong())
        player.setPlaybackSpeed(rate)
        player.playWhenReady = false
        heldByUser = false
        starting = true
        player.prepare()
        watchStart()
        if (trickplay == null) loadTrickplay()
    }

    // The start, one step after another: the item ready at its place, its subtitles chosen, then.
    private fun begin() {
        starting = false
        ready = true
        seekTarget = null
        if (!heldByUser) player.play()
    }

    // Where to start, once the item is known: exactly where another device handed over, or where
    // this profile stopped if that is worth resuming (somewhere in, and not in the closing minute).
    // The title's runtime stands in for the duration, which is not known until the item is.
    private fun resumeTarget(): Double? {
        val length = if (duration > 0) duration else info?.resume?.runtime ?: 0.0
        if (startAt != null) {
            startAt = null
            return if (length > 0) minOf(pendingResume, length - 1) else pendingResume
        }
        if (pendingResume <= 30 || (length > 0 && pendingResume >= length - 60)) return null
        return pendingResume
    }

    /** The language chosen last time, if the file has it, else the file's
     *  default; off stays off. A forced track is passed over for a full one. */
    private fun preferredSubtitle(tracks: List<PlayInfo.SubtitleTrack>): String? {
        if (prefs.subtitlesOff) return null
        prefs.subtitleLanguage?.let { lang ->
            val matching = tracks.filter { it.language == lang }
            (matching.firstOrNull { it.forced != true } ?: matching.firstOrNull())?.let { return it.id }
        }
        return tracks.firstOrNull { it.default == true }?.id
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

    /** Another audio track is another rendition on the server: rebuilt, and
     *  the place carried across. */
    fun chooseAudio(index: Int?) {
        if (index == null || index == currentAudio) return
        val at = current
        audioIndex = index
        // The old track is not played on under the spinner, and the new one
        // starts exactly where it was, however near either end.
        player.playWhenReady = false
        ready = false
        startAt = at
        pendingResume = at
        prepareRendition()
    }

    override fun togglePlay() {
        if (player.playWhenReady) { heldByUser = true; player.pause() }
        else { heldByUser = false; player.play() }
    }

    override fun seek(seconds: Double) {
        // Seeking back from the end is watching again, not finishing.
        if (seconds < duration - 1) ended = false
        val clamped = seconds.coerceIn(0.0, maxOf(duration - 1, 0.0))
        current = clamped
        val serial = ++seekSerial
        seekTarget = clamped
        player.seekTo((clamped * 1000).toLong())
        // A seek that never reports landing lets go of the knob anyway.
        AppState.launch { delay(6_000); if (seekSerial == serial) seekTarget = null }
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
        // Runs driven from a script must not write into anybody's history.
        if (Debug.has("noProgress")) return
        val (id, pos, dur) = Triple(request.playID, current, duration)
        AppState.launch { Api.reportProgress(id, pos, dur, profile) }
    }

    // ------------------------------------------------------------ trickplay

    /** The scrubber's sprite sheets, once the server has made them. */
    var trickplay by mutableStateOf<Trickplay?>(null)
    /** The last few sheets decoded, and the fetches under way, by address.
     *  A fetch, once started, finishes whoever stops waiting for it, so a
     *  moving finger does not cancel the sheet it is about to need. */
    private val sheets = LinkedHashMap<String, ImageBitmap>()
    private val sheetLoads = mutableMapOf<String, CompletableDeferred<ImageBitmap?>>()

    private fun loadTrickplay() {
        jobs += AppState.launch {
            val manifest = runCatching { Api.trickplay(request.playID) }.getOrNull()?.takeIf { it.isUsable } ?: return@launch
            trickplay = manifest
            // Every sheet, once the start has had a moment to itself, so a
            // scrub anywhere finds its frames already here: fetched into the
            // image cache, decoded at a pixel, which costs next to nothing.
            delay(4_000)
            val loader = SingletonImageLoader.get(context)
            sheetURLs(manifest).forEach { url ->
                if (stopped) return@launch
                runCatching {
                    loader.execute(ImageRequest.Builder(context).data(url).size(1, 1).memoryCachePolicy(CachePolicy.DISABLED).build())
                }
            }
        }
    }

    private suspend fun sheetURLs(t: Trickplay): List<String> {
        val base = t.url ?: return emptyList()
        val perSheet = t.perSheet?.takeIf { it > 0 } ?: return emptyList()
        val count = t.count ?: return emptyList()
        return (0 until (count + perSheet - 1) / perSheet).mapNotNull { runCatching { Api.url("$base/$it.jpg") }.getOrNull() }
    }

    /** The frame nearest `seconds`: its sheet, and where on it. */
    suspend fun thumbnail(seconds: Double): ThumbFrame? {
        val t = trickplay ?: return null
        val base = t.url ?: return null
        val columns = t.columns ?: return null
        val perSheet = t.perSheet ?: return null
        val w = t.tileWidth ?: return null
        val h = t.tileHeight ?: return null
        val index = t.frameIndex(seconds)
        val cell = index % perSheet
        val url = runCatching { Api.url("$base/${index / perSheet}.jpg") }.getOrNull() ?: return null
        val sheet = sheet(url) ?: return null
        return ThumbFrame(sheet, IntOffset((cell % columns) * w, (cell / columns) * h), IntSize(w, h))
    }

    private suspend fun sheet(url: String): ImageBitmap? {
        sheets[url]?.let { return it }
        val load = sheetLoads.getOrPut(url) {
            CompletableDeferred<ImageBitmap?>().also { done ->
                AppState.launch {
                    val result = runCatching {
                        SingletonImageLoader.get(context).execute(ImageRequest.Builder(context).data(url).allowHardware(false).build())
                    }.getOrNull()
                    val image = result?.image?.toBitmap()?.asImageBitmap()
                    sheetLoads.remove(url)
                    if (image != null) {
                        sheets[url] = image
                        // Some 9 MB a sheet decoded: only the last few are kept.
                        while (sheets.size > 3) sheets.remove(sheets.keys.first())
                    }
                    done.complete(image)
                }
            }
        }
        return load.await()
    }

    fun stop() {
        if (stopped) return
        stopped = true
        report()
        castToken?.let(Cast::removeControl)
        Cast.report(null)
        jobs.forEach { it.cancel() }
        sheets.clear()
        renditionJob?.cancel()
        watchdog?.cancel()
        player.release()
    }
}

/** What the player keeps on this device whoever is watching, as iOS keeps
 *  it in its own defaults. */
object PlayerPrefs {
    private const val STATS = "vibestream.player.stats"
    private fun store(context: Context) = context.getSharedPreferences("vibestream", Context.MODE_PRIVATE)

    fun statsShown(context: Context) = store(context).getBoolean(STATS, false)
    fun setStatsShown(context: Context, on: Boolean) = store(context).edit().putBoolean(STATS, on).apply()
}

/** One cell of a sprite sheet: the sheet, and the cell's place on it in pixels. */
class ThumbFrame(val sheet: ImageBitmap, val offset: IntOffset, val size: IntSize)
