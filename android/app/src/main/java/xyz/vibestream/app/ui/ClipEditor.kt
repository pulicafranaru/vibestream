package xyz.vibestream.app.ui

import androidx.annotation.OptIn
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import coil3.SingletonImageLoader
import coil3.request.ImageRequest
import coil3.request.allowHardware
import coil3.toBitmap
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import xyz.vibestream.app.AppState
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.Trickplay
import kotlin.math.ceil
import kotlin.math.floor

private const val LONGEST = 120.0
private const val SHORTEST = 2.0
private const val SPAN = 130.0
private const val MARGIN = 4.0
private val START_GREEN = Color(0xFF2EBF6E)

interface ClipSource {
    val player: ExoPlayer
    val duration: Double
    val current: Double
    val isPlaying: Boolean
    val playID: String
    fun seek(seconds: Double)
    fun togglePlay()
}

// Clips run SHORTEST to LONGEST seconds; the strip shows SPAN seconds of film.
@OptIn(UnstableApi::class)
@Composable
fun ClipEditor(source: ClipSource, onClose: () -> Unit) {
    val duration = maxOf(source.duration, SHORTEST)
    // Default to the 30 seconds ending at the current position.
    var end by remember { mutableDoubleStateOf(minOf(duration, maxOf(source.current, minOf(duration, 30.0)))) }
    var start by remember { mutableDoubleStateOf(maxOf(0.0, end - 30)) }
    var windowStart by remember { mutableDoubleStateOf(maxOf(0.0, minOf(start - MARGIN, duration - SPAN))) }
    val windowEnd = minOf(duration, windowStart + SPAN)
    var previewing by remember { mutableStateOf(true) }
    var saving by remember { mutableStateOf(false) }
    var saved by remember { mutableStateOf(false) }
    var failure by remember { mutableStateOf<String?>(null) }
    var trickplay by remember { mutableStateOf<Trickplay?>(null) }
    val upright = LocalConfiguration.current.let { it.screenHeightDp > it.screenWidthDp }
    val scope = rememberCoroutineScope()

    fun hold(at: Double) { if (source.isPlaying) source.togglePlay(); previewing = false; source.seek(at) }
    fun replay() { source.seek(start); if (!source.isPlaying) source.togglePlay(); previewing = true }
    fun follow() {
        var from = windowStart
        if (end > windowStart + SPAN - MARGIN) from = end + MARGIN - SPAN
        if (start < from + MARGIN) from = start - MARGIN
        windowStart = from.coerceIn(0.0, maxOf(0.0, duration - SPAN))
    }
    fun moveStart(wanted: Double) {
        start = minOf(maxOf(0.0, wanted), end - SHORTEST, duration - SHORTEST)
        if (end - start > LONGEST) end = start + LONGEST
        follow(); hold(start)
    }
    fun moveEnd(wanted: Double) {
        end = maxOf(minOf(duration, wanted), start + SHORTEST, SHORTEST)
        if (end - start > LONGEST) start = end - LONGEST
        follow(); hold(maxOf(start, end - 1))
    }
    fun rollFilm(from: Pair<Double, Double>, delta: Double) {
        val length = from.second - from.first
        start = (from.first + delta).coerceIn(0.0, duration - length)
        end = start + length
        follow(); hold(start)
    }

    LaunchedEffect(Unit) {
        trickplay = runCatching { Api.trickplay(source.playID) }.getOrNull()?.takeIf { it.isUsable }
        source.seek(start)
        if (!source.isPlaying) source.togglePlay()
        while (true) {
            delay(150)
            if (previewing && (source.current >= end || source.current < start - 1)) source.seek(start)
        }
    }

    Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color.Black, Color(0xFF171717))))
        .pointerInput(Unit) { detectTapGestures { } }) {
        Column(Modifier.fillMaxSize().statusBarsPadding()) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(44.dp).pressable { if (source.isPlaying) source.togglePlay(); onClose() }, contentAlignment = Alignment.Center) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Color.White)
                }
                Text("Clip a Moment", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center, modifier = Modifier.weight(1f))
                Box(Modifier.widthIn(min = 70.dp).background(Color.White, RoundedCornerShape(6.dp))
                    .pressable(!saving && !saved) {
                        saving = true
                        failure = null
                        scope.launch {
                            runCatching { AppState.saveClip(source.playID, start, end) }
                                .onSuccess { saving = false; saved = true; delay(1_200); if (source.isPlaying) source.togglePlay(); onClose() }
                                .onFailure { saving = false; failure = "Couldn't save the clip. Try again." }
                        }
                    }.padding(horizontal = 16.dp, vertical = 10.dp), contentAlignment = Alignment.Center) {
                    if (saving) BootSpinner(18.dp, 2.dp) else Text("Save", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.Black)
                }
            }
            failure?.let { Text(it, fontSize = 13.sp, color = Palette.accent, modifier = Modifier.align(Alignment.CenterHorizontally)) }
            Spacer(Modifier.weight(1f))
            val preview: @Composable (Modifier) -> Unit = { modifier ->
                Box(modifier.widthIn(max = 640.dp).aspectRatio(16f / 9f).clip(RoundedCornerShape(10.dp)).background(Color.Black)
                    .border(1.5.dp, Color.White.copy(alpha = 0.3f), RoundedCornerShape(10.dp))) {
                    AndroidView({ PlayerView(it).apply { useController = false; player = source.player } }, Modifier.fillMaxSize())
                    Row(Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(10.dp)) {
                        Icon(if (previewing && source.isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow, null, tint = Color.White,
                            modifier = Modifier.size(44.dp).padding(10.dp).pressable { source.togglePlay(); previewing = source.isPlaying })
                        Spacer(Modifier.weight(1f))
                        Icon(Icons.Filled.Replay, "Play from the start", tint = Color.White,
                            modifier = Modifier.size(44.dp).padding(9.dp).pressable { replay() })
                    }
                }
            }
            if (upright) {
                Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(22.dp)) {
                    preview(Modifier.fillMaxWidth())
                    Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp)) {
                        Bound("Start", start, START_GREEN, 32)
                        Spacer(Modifier.weight(1f))
                        Bound("End", end, Palette.accent, 32)
                    }
                }
            } else {
                Row(Modifier.fillMaxWidth().padding(horizontal = 24.dp), horizontalArrangement = Arrangement.spacedBy(28.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Bound("Start", start, START_GREEN, 38)
                    preview(Modifier.weight(1f))
                    Bound("End", end, Palette.accent, 38)
                }
            }
            Spacer(Modifier.weight(1f))
            Strip(source, trickplay, start, end, windowStart, windowEnd,
                onStart = ::moveStart, onEnd = ::moveEnd, onRoll = ::rollFilm, onDone = { replay() },
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 24.dp))
        }
        if (saved) {
            Row(Modifier.align(Alignment.Center).background(Color(0xFF292929), CircleShape).padding(horizontal = 22.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Filled.CheckCircle, null, tint = Color.White)
                Text("Saved to Library", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
            }
        }
    }
}

@Composable
private fun Bound(label: String, seconds: Double, tint: Color, size: Int) {
    Column(Modifier.widthIn(min = 110.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(label, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = tint)
        Text(clock(seconds), fontSize = size.sp, color = Color.White)
    }
}

private fun clock(seconds: Double): String {
    val total = floor(maxOf(0.0, seconds)).toInt()
    val h = total / 3600
    val m = (total % 3600) / 60
    val s = total % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
}

@Composable
private fun Strip(
    source: ClipSource,
    trickplay: Trickplay?,
    start: Double,
    end: Double,
    windowStart: Double,
    windowEnd: Double,
    onStart: (Double) -> Unit,
    onEnd: (Double) -> Unit,
    onRoll: (Pair<Double, Double>, Double) -> Unit,
    onDone: () -> Unit,
    modifier: Modifier,
) {
    val density = LocalDensity.current
    val context = LocalContext.current
    val sheets = remember { mutableStateMapOf<Int, ImageBitmap>() }
    BoxWithConstraints(modifier.fillMaxWidth().height(106.dp)) {
        val handle = 36.dp
        val handlePx = with(density) { handle.toPx() }
        val widthPx = maxOf(1f, constraints.maxWidth - handlePx * 2)
        val span = maxOf(1.0, windowEnd - windowStart)
        fun x(t: Double) = handlePx + ((t - windowStart) / span * widthPx).toFloat()
        fun seconds(dx: Float) = dx / widthPx * span
        val filmHeight = with(density) { 64.dp.toPx() }
        val top = with(density) { 30.dp.toPx() }
        val step = minOf(SPAN, source.duration.coerceAtLeast(SHORTEST)) / 16

        LaunchedEffect(trickplay, floor(windowStart / step)) {
            val t = trickplay ?: return@LaunchedEffect
            val perSheet = t.perSheet ?: return@LaunchedEffect
            val base = t.url ?: return@LaunchedEffect
            val first = maxOf(0, floor(windowStart / step).toInt() - 4)
            val last = ceil(windowEnd / step).toInt() + 4
            (first..last).map { t.frameIndex((it + 0.5) * step) / perSheet }.distinct().forEach { sheet ->
                if (sheet in sheets) return@forEach
                val url = runCatching { Api.url("$base/$sheet.jpg") }.getOrNull() ?: return@forEach
                val result = SingletonImageLoader.get(context).execute(ImageRequest.Builder(context).data(url).allowHardware(false).build())
                result.image?.toBitmap()?.asImageBitmap()?.let { sheets[sheet] = it }
            }
        }

        var rollFrom by remember { mutableStateOf<Pair<Double, Double>?>(null) }
        var travelled by remember { mutableStateOf(0f) }
        var coast by remember { mutableStateOf<kotlinx.coroutines.Job?>(null) }
        val scope = rememberCoroutineScope()
        val tracker = remember { androidx.compose.ui.input.pointer.util.VelocityTracker() }
        Canvas(Modifier.fillMaxSize().pointerInput(windowStart, start, end) {
            detectDragGestures(
                onDragStart = {
                    coast?.cancel(); coast = null
                    rollFrom = start to end; travelled = 0f; tracker.resetTracking()
                },
                onDragEnd = {
                    val from = rollFrom
                    var speed = -seconds(tracker.calculateVelocity().x)
                    if (from == null || kotlin.math.abs(speed) <= 4) { rollFrom = null; onDone(); return@detectDragGestures }
                    coast = scope.launch {
                        var delta = -seconds(travelled)
                        while (kotlin.math.abs(speed) > 1) {
                            delay(16)
                            delta += speed / 60
                            onRoll(from, delta)
                            speed *= 0.94
                        }
                        rollFrom = null
                        coast = null
                        onDone()
                    }
                },
                onDragCancel = { rollFrom = null },
            ) { change, amount ->
                tracker.addPosition(change.uptimeMillis, change.position)
                travelled += amount.x
                rollFrom?.let { onRoll(it, -seconds(travelled)) }
                change.consume()
            }
        }) {
            drawRoundRect(Color(0xFF1F1F1F), Offset(handlePx, top), Size(widthPx, filmHeight), androidx.compose.ui.geometry.CornerRadius(4.dp.toPx()))
            val t = trickplay
            if (t != null && t.perSheet != null && t.columns != null && t.tileWidth != null && t.tileHeight != null) {
                val firstCell = floor(windowStart / step).toInt()
                val lastCell = maxOf(firstCell + 1, ceil(windowEnd / step).toInt())
                val cell = (widthPx * step / span).toFloat()
                for (index in firstCell until lastCell) {
                    val frame = t.frameIndex((index + 0.5) * step)
                    val sheet = sheets[frame / t.perSheet] ?: continue
                    val within = frame % t.perSheet
                    val srcX = (within % t.columns) * t.tileWidth
                    val srcY = (within / t.columns) * t.tileHeight
                    val left = handlePx + ((index * step - windowStart) / span * widthPx).toFloat()
                    val right = minOf(left + cell + 1, handlePx + widthPx)
                    val clippedLeft = maxOf(left, handlePx)
                    if (right <= clippedLeft) continue
                    val drawWidth = right - clippedLeft
                    val srcW = (t.tileWidth * minOf(1f, drawWidth / (filmHeight * 16 / 9))).toInt().coerceAtLeast(1)
                    drawImage(sheet, IntOffset(srcX + (t.tileWidth - srcW) / 2, srcY), IntSize(srcW, t.tileHeight),
                        IntOffset(clippedLeft.toInt(), top.toInt()), IntSize(drawWidth.toInt(), filmHeight.toInt()))
                }
            }
            val frameLeft = x(start) - handlePx
            val frameWidth = maxOf(handlePx * 2, x(end) - x(start) + handlePx * 2)
            drawRoundRect(Color.White, Offset(frameLeft, top - 6.dp.toPx()), Size(frameWidth, filmHeight + 12.dp.toPx()),
                androidx.compose.ui.geometry.CornerRadius(10.dp.toPx()), style = androidx.compose.ui.graphics.drawscope.Stroke(3.dp.toPx()))
            val playhead = x(source.current.coerceIn(start, end))
            drawRoundRect(Color.White, Offset(playhead - 2.dp.toPx(), top - 2.dp.toPx()), Size(4.dp.toPx(), filmHeight + 4.dp.toPx()),
                androidx.compose.ui.geometry.CornerRadius(2.dp.toPx()))
        }
        Text(clock(source.current.coerceIn(start, end)), fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
            modifier = Modifier.offset { IntOffset((x(source.current.coerceIn(start, end)) - 18.dp.toPx()).toInt(), 0) })
        Handle(START_GREEN, Modifier.offset { IntOffset((x(start) - handlePx).toInt(), (top - 6.dp.toPx()).toInt()) },
            onDrag = { from, dx -> onStart(from + seconds(dx)) }, from = start, onDone = onDone)
        Handle(Palette.accent, Modifier.offset { IntOffset(x(end).toInt(), (top - 6.dp.toPx()).toInt()) },
            onDrag = { from, dx -> onEnd(from + seconds(dx)) }, from = end, onDone = onDone)
    }
}

@Composable
private fun Handle(tint: Color, modifier: Modifier, from: Double, onDrag: (Double, Float) -> Unit, onDone: () -> Unit) {
    var origin by remember { mutableStateOf(from) }
    var travelled by remember { mutableStateOf(0f) }
    Box(modifier.width(36.dp).height(76.dp).background(tint, RoundedCornerShape(8.dp))
        .pointerInput(Unit) {
            detectDragGestures(onDragStart = { origin = from; travelled = 0f }, onDragEnd = onDone) { change, amount ->
                travelled += amount.x
                onDrag(origin, travelled)
                change.consume()
            }
        }, contentAlignment = Alignment.Center) {
        Text("◂▸", fontSize = 10.sp, color = Color.White)
    }
}
