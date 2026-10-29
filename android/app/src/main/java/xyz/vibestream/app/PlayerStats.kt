package xyz.vibestream.app

import android.media.AudioManager
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.media3.common.Format
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.analytics.AnalyticsListener
import androidx.media3.exoplayer.source.LoadEventInfo
import androidx.media3.exoplayer.source.MediaLoadData
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import xyz.vibestream.app.ui.fileSize

// Playback stats: what the player is actually doing, over the picture (iOS PlayerStats).
@androidx.annotation.OptIn(UnstableApi::class)
class PlayerStats(private val player: ExoPlayer) {
    data class Sample(val kbps: Double, val kilobytes: Double, val buffer: Double)

    /** The last minute, oldest first. */
    var samples by mutableStateOf<List<Sample>>(emptyList())
    var observedKbps by mutableDoubleStateOf(0.0)
    var variantKbps by mutableDoubleStateOf(0.0)
    var kilobytes by mutableDoubleStateOf(0.0)
    var buffer by mutableDoubleStateOf(0.0)
    var dropped by mutableIntStateOf(0)
    var watched by mutableDoubleStateOf(0.0)
    var stalls by mutableIntStateOf(0)
    var presentation by mutableStateOf(IntSize.Zero)
    var server by mutableStateOf<String?>(null)
    var now by mutableStateOf(ZonedDateTime.now())

    private var estimate = 0L
    private var bytes = 0L
    private var droppedSoFar = 0
    private var stallsSoFar = 0
    private var hostSeen: String? = null
    /** Waiting for data because of a seek, which is not a stall. */
    private var seeking = false
    private var played = false

    init {
        player.addAnalyticsListener(object : AnalyticsListener {
            override fun onBandwidthEstimate(time: AnalyticsListener.EventTime, loadMs: Int, loaded: Long, bitrate: Long) { estimate = bitrate }
            override fun onLoadCompleted(time: AnalyticsListener.EventTime, load: LoadEventInfo, data: MediaLoadData) {
                bytes += load.bytesLoaded
                load.uri.host?.let { hostSeen = it }
            }
            override fun onDroppedVideoFrames(time: AnalyticsListener.EventTime, count: Int, elapsedMs: Long) { droppedSoFar += count }
            override fun onPositionDiscontinuity(time: AnalyticsListener.EventTime, old: Player.PositionInfo, new: Player.PositionInfo, reason: Int) {
                if (reason == Player.DISCONTINUITY_REASON_SEEK) seeking = true
            }
            override fun onPlaybackStateChanged(time: AnalyticsListener.EventTime, state: Int) {
                when (state) {
                    Player.STATE_READY -> { played = true; seeking = false }
                    Player.STATE_BUFFERING -> if (played && !seeking && player.playWhenReady) stallsSoFar++
                }
            }
        })
    }

    /** One reading, a second after the last. */
    fun tick() {
        now = ZonedDateTime.now()
        observedKbps = estimate / 1000.0
        variantKbps = player.videoFormat?.let { f -> listOf(f.peakBitrate, f.bitrate, f.averageBitrate).firstOrNull { it != Format.NO_VALUE } }
            ?.div(1000.0) ?: 0.0
        kilobytes = bytes / 1024.0
        bytes = 0
        buffer = ((player.bufferedPosition - player.currentPosition) / 1000.0).coerceAtLeast(0.0)
        dropped = droppedSoFar
        stalls = stallsSoFar
        server = hostSeen
        if (player.isPlaying) watched += 1
        presentation = player.videoSize.let { IntSize(it.width, it.height) }
        samples = (samples + Sample(observedKbps, kilobytes, buffer)).takeLast(60)
    }
}

/** The overlay: labels on the right edge of a column, values beside them,
 *  three of them with a minute's graph. Sized to the picture it sits on. */
@Composable
internal fun StatsOverlay(model: PlayerModel, area: Size, modifier: Modifier = Modifier) {
    val stats = model.stats
    val info = model.info
    val context = LocalContext.current
    val density = LocalDensity.current.density
    val font = (area.width / 62f).coerceIn(8.5f, 13f)
    val row = (font * 1.5f).dp
    val video = info?.media?.video

    val engine = "${info?.playID ?: "?"} / ${if (info?.playback?.engine == "live") "live remux" else "prepared rendition"}, ${info?.playback?.mode ?: "?"}"
    val file = info?.file?.let { f -> f.name.orEmpty().ifEmpty { "?" } + (f.sizeBytes?.let { " (${fileSize(it)})" } ?: "") } ?: "?"
    val frames = Math.round(stats.watched * (video?.frameRate ?: 24.0))
    val viewport = "${area.width.toInt()}x${area.height.toInt()}*${"%.2f".format(density)} / ${stats.dropped} dropped of $frames"
    val current = if (stats.presentation == IntSize.Zero) "?" else "${stats.presentation.width}x${stats.presentation.height}"
    val source = video?.let { v ->
        if (v.width == null || v.height == null) null
        else "${v.width}x${v.height}" + (v.frameRate?.let { "@" + "%.2f".format(it).trimEnd('0').trimEnd('.') } ?: "")
    }
    val audio = context.getSystemService(AudioManager::class.java)
    val device = audio?.let { 100 * it.getStreamVolume(AudioManager.STREAM_MUSIC) / maxOf(1, it.getStreamMaxVolume(AudioManager.STREAM_MUSIC)) }
    val volume = "${Math.round(model.player.volume * 100)}% / ${device ?: "?"}% device"
    val videoPart = listOfNotNull(video?.codec, video?.profile).joinToString(" ") + (video?.bitDepth?.let { " $it-bit" } ?: "")
    val sourceAudio = info?.media?.audio?.firstOrNull { it.index == model.currentAudio }
    val audioPart = listOfNotNull(sourceAudio?.codec, sourceAudio?.channels?.let { "${it}ch" }).joinToString(" ") +
        (if (info?.playback?.audioTranscoded == true) " > aac" else "")
    val codecs = "${videoPart.trim().ifEmpty { "?" }} / ${audioPart.trim().ifEmpty { "?" }}"
    val colour = when {
        video == null -> "?"
        video.dolbyVision == true -> "Dolby Vision" + if (video.hdr == true) " / HDR10 base" else ""
        video.hdr == true -> "HDR (${video.bitDepth ?: 10}-bit)"
        else -> "SDR"
    }
    val variant = if (stats.variantKbps > 0) "${Math.round(stats.variantKbps)} Kbps variant" else "variant ?"
    val stream = "$variant${info?.media?.container?.let { ", $it" } ?: ""}, ${stats.stalls} stalls, ${stats.server ?: "?"}"

    val style = TextStyle(fontSize = font.sp, color = Color.White, shadow = Shadow(Color.Black.copy(alpha = 0.9f), Offset.Zero, 4f))
    val rows: List<Pair<String, @Composable () -> Unit>> = listOf(
        "Play ID / Engine" to { Value(engine, style) },
        "File" to { Value(file, style) },
        "Viewport / Frames" to { Value(viewport, style) },
        "Current / Source Res" to { Value(if (source == null) current else "$current / $source", style) },
        "Volume" to { Value(volume, style) },
        "Codecs" to { Value(codecs, style) },
        "Color" to { Value(colour, style) },
        "Connection Speed" to { Graph(stats.samples.map { it.kbps }, BLUE, font, "${Math.round(stats.observedKbps)} Kbps", style) },
        "Network Activity" to { Graph(stats.samples.map { it.kilobytes }, TEAL, font, "${Math.round(stats.kilobytes)} KB", style) },
        "Buffer Health" to { Graph(stats.samples.map { it.buffer }, LIME, font, "%.2f s".format(stats.buffer), style) },
        "Stream" to { Value(stream, style) },
        "Date" to { Value(stats.now.format(DATE), style) },
    )
    Row(modifier.widthIn(max = (area.width - 28).coerceAtLeast(120f).dp).background(Color.Black.copy(alpha = 0.45f), RoundedCornerShape(8.dp))
        .padding(10.dp), horizontalArrangement = Arrangement.spacedBy((font * 0.8f).dp)) {
        Column(horizontalAlignment = Alignment.End) {
            rows.forEach { (label, _) ->
                Box(Modifier.height(row), contentAlignment = Alignment.CenterEnd) {
                    Text(label, style = style, fontWeight = FontWeight.Bold, maxLines = 1)
                }
            }
        }
        Column {
            rows.forEach { (_, value) -> Box(Modifier.height(row), contentAlignment = Alignment.CenterStart) { value() } }
        }
    }
}

@Composable
private fun Value(text: String, style: TextStyle) {
    Text(text, style = style, maxLines = 1, overflow = TextOverflow.Ellipsis)
}

@Composable
private fun Graph(values: List<Double>, tint: Color, font: Float, value: String, style: TextStyle) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy((font * 0.6f).dp)) {
        Sparkline(values, tint, Modifier.size((font * 13).dp, (font * 1.35f).dp))
        Value(value, style)
    }
}

/** A minute of a measure as bars, scaled to the largest. */
@Composable
private fun Sparkline(values: List<Double>, tint: Color, modifier: Modifier) {
    Canvas(modifier) {
        val slots = 60
        val width = size.width / slots
        val top = maxOf(values.maxOrNull() ?: 0.0, 0.0001)
        drawRect(Color.White.copy(alpha = 0.08f))
        values.forEachIndexed { i, value ->
            val height = maxOf(1f, size.height * (value / top).toFloat())
            drawRect(tint, Offset((slots - values.size + i) * width, size.height - height), Size(maxOf(1f, width - 0.5f), height))
        }
    }
}

/** "Fri Oct 23 2026 20:26:08 GMT+03:00", seconds always two digits. */
private val DATE = DateTimeFormatter.ofPattern("EEE MMM d yyyy HH:mm:ss 'GMT'xxx", Locale.US)

private val BLUE = Color(0xFF2980C7)
private val TEAL = Color(0xFF5CBF9E)
private val LIME = Color(0xFFDBF08F)
