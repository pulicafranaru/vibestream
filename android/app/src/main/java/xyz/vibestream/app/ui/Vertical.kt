package xyz.vibestream.app.ui

import android.content.Context
import android.content.Intent
import android.view.TextureView
import androidx.annotation.OptIn
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoFixHigh
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.RemoveCircleOutline
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.FileProvider
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.effect.MatrixTransformation
import androidx.media3.effect.Presentation
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.transformer.Composition
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.Effects
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.ProgressHolder
import androidx.media3.transformer.Transformer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import okhttp3.Request
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.Clip
import xyz.vibestream.app.api.ClipVertical
import java.io.File
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.math.abs

data class VerticalWindow(val x: Double, val y: Double, val width: Double, val height: Double, val zoom: Double)

// Server path per shot, with hand keyframes as a correction on top; a cut ends a keyframe's influence.
class VerticalPath(val vertical: ClipVertical, val aspect: Double, val duration: Double) {
    companion object {
        const val TALL = 9.0 / 16.0
        const val MAX_ZOOM = 4.0
    }

    private val picture = vertical.picture ?: ClipVertical.Picture(1.0, 1.0)

    val shots: List<ClipVertical.Shot>
        get() = vertical.crop?.shots?.takeIf { it.isNotEmpty() }
            ?: listOf(ClipVertical.Shot(0.0, maxOf(duration, 0.1), listOf(listOf(0.0, 0.5))))

    private fun shot(time: Double): ClipVertical.Shot? =
        shots.firstOrNull { time >= it.start && time < it.end }
            ?: if (time >= (shots.lastOrNull()?.end ?: 0.0)) shots.lastOrNull() else shots.firstOrNull()

    fun auto(time: Double): Double {
        val s = shot(time) ?: return 0.5
        val first = s.points.firstOrNull()?.takeIf { it.size == 2 } ?: return 0.5
        if (s.points.size == 1 || time <= first[0]) return first[1]
        for ((a, b) in s.points.zipWithNext()) {
            if (a.size == 2 && b.size == 2 && time >= a[0] && time <= b[0]) {
                val span = b[0] - a[0]
                return if (span > 0) a[1] + (b[1] - a[1]) * (time - a[0]) / span else b[1]
            }
        }
        return s.points.lastOrNull()?.lastOrNull() ?: 0.5
    }

    fun window(time: Double): VerticalWindow {
        val base = auto(time)
        var dx = 0.0
        var y = 0.5
        var zoom = 1.0
        val here = shot(time)
        val mine = vertical.keyframes.filter { shot(it.t) == here }.sortedBy { it.t }
        if (mine.isNotEmpty()) {
            fun offset(k: ClipVertical.Keyframe) = k.x - auto(k.t)
            val first = mine.first()
            val last = mine.last()
            when {
                time <= first.t -> { dx = offset(first); y = first.y; zoom = first.zoom }
                time >= last.t -> { dx = offset(last); y = last.y; zoom = last.zoom }
                else -> {
                    val b = mine.first { it.t >= time }
                    val a = mine.last { it.t <= time }
                    val f = if (b.t > a.t) (time - a.t) / (b.t - a.t) else 0.0
                    dx = offset(a) + (offset(b) - offset(a)) * f
                    y = a.y + (b.y - a.y) * f
                    zoom = a.zoom + (b.zoom - a.zoom) * f
                }
            }
        }
        return place(base + dx, y, zoom)
    }

    fun place(x: Double, y: Double, zoom: Double): VerticalWindow {
        val z = zoom.coerceIn(1.0, MAX_ZOOM)
        val height = picture.height / z
        val width = minOf(1.0, height * TALL / maxOf(aspect, 0.1))
        val barsX = (1 - picture.width) / 2
        val barsY = (1 - picture.height) / 2
        val cx = x.coerceIn(barsX + width / 2, maxOf(barsX + width / 2, 1 - barsX - width / 2))
        val cy = y.coerceIn(barsY + height / 2, maxOf(barsY + height / 2, 1 - barsY - height / 2))
        return VerticalWindow(if (width >= 1 - 2 * barsX) 0.5 else cx, if (height >= 1 - 2 * barsY) 0.5 else cy, width, height, z)
    }

    val cuts: List<Double> get() = shots.drop(1).map { it.start }
}

@OptIn(UnstableApi::class)
@Composable
fun VerticalEditor(clip: Clip, onClose: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val player = remember { ExoPlayer.Builder(context).build().apply { repeatMode = Player.REPEAT_MODE_ONE } }
    var vertical by remember { mutableStateOf(ClipVertical()) }
    var aspect by remember { mutableDoubleStateOf(16.0 / 9.0) }
    var duration by remember { mutableDoubleStateOf(clip.duration) }
    var time by remember { mutableDoubleStateOf(0.0) }
    var playing by remember { mutableStateOf(false) }
    var loaded by remember { mutableStateOf(false) }
    var gestureFrom by remember { mutableStateOf<VerticalWindow?>(null) }
    var confirmingAuto by remember { mutableStateOf(false) }
    var exporting by remember { mutableStateOf<Double?>(null) }
    var failure by remember { mutableStateOf<String?>(null) }
    var saveJob by remember { mutableStateOf<Job?>(null) }
    val path = VerticalPath(vertical, aspect, duration)
    val keyframeHere = vertical.keyframes.indexOfFirst { abs(it.t - time) < 0.2 }.takeIf { it >= 0 }

    fun pause() { player.pause(); playing = false; time = player.currentPosition / 1000.0 }
    fun seek(seconds: Double) { time = seconds; player.seekTo((seconds * 1000).toLong()) }
    fun scheduleSave() {
        saveJob?.cancel()
        val keyframes = vertical.keyframes
        saveJob = scope.launch {
            delay(500)
            runCatching { Api.saveClipVertical(clip.id, keyframes) }.onFailure { failure = "Couldn't keep the change: ${it.message}" }
        }
    }
    fun placeKeyframe(w: VerticalWindow) {
        val list = vertical.keyframes.toMutableList()
        val index = list.indexOfFirst { abs(it.t - time) < 0.2 }
        if (index >= 0) list[index] = list[index].copy(x = w.x, y = w.y, zoom = w.zoom)
        else { list.add(ClipVertical.Keyframe(time, w.x, w.y, w.zoom)); list.sortBy { it.t } }
        vertical = vertical.copy(keyframes = list)
    }

    DisposableEffect(player) { onDispose { player.release(); saveJob?.cancel() } }
    LaunchedEffect(clip.id) {
        runCatching { Api.url(clip.video) }.getOrNull()?.let { player.setMediaItem(MediaItem.fromUri(it)); player.prepare() }
        runCatching { Api.clipVertical(clip.id) }.getOrNull()?.let { vertical = it; it.crop?.let { c -> aspect = c.aspect } }
        loaded = true
        player.play()
        playing = true
        if (xyz.vibestream.app.Debug.has("verticalExport")) {
            runCatching { exportVertical(context, clip, VerticalPath(vertical, aspect, duration)) { } }
                .onSuccess { made -> made.copyTo(File(context.getExternalFilesDir(null), "vertical-test.mp4"), overwrite = true)
                    android.util.Log.i("VibeStream", "vertical export ok ${made.length()} bytes") }
                .onFailure { android.util.Log.e("VibeStream", "vertical export failed", it) }
        }
        while (vertical.crop == null) {
            delay(2_000)
            runCatching { Api.clipVertical(clip.id) }.getOrNull()?.takeIf { it.crop != null }?.let {
                vertical = vertical.copy(crop = it.crop, picture = it.picture); aspect = it.crop!!.aspect
            }
        }
    }
    LaunchedEffect(Unit) {
        while (true) {
            if (gestureFrom == null && playing) time = player.currentPosition / 1000.0
            if (player.duration > 0) duration = player.duration / 1000.0
            delay(33)
        }
    }

    // Pad by the app window's bar insets: the dialog's own insets report no navigation bar.
    val bars = systemBarPadding()
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Column(Modifier.fillMaxSize().background(Color.Black).padding(bars)) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(44.dp).pressable(onClick = onClose), contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.Close, "Close", tint = Color.White)
                }
                Text("Vertical", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
                    textAlign = TextAlign.Center, modifier = Modifier.weight(1f))
                Text("Export", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.Black,
                    modifier = Modifier.height(34.dp).background(Color.White, CircleShape)
                        .pressable(loaded && exporting == null) {
                            failure = null
                            exporting = 0.0
                            pause()
                            scope.launch {
                                runCatching { exportVertical(context, clip, path) { exporting = it } }
                                    .onSuccess { share(context, it) }
                                    .onFailure { failure = "Couldn't make the video: ${it.message}" }
                                exporting = null
                            }
                        }.padding(horizontal = 16.dp, vertical = 6.dp))
            }

            BoxWithConstraints(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                val density = LocalDensity.current
                val heightDp = minOf(maxHeight.value - 12, maxWidth.value * 0.86f * 16 / 9)
                val widthDp = heightDp * VerticalPath.TALL.toFloat()
                val window = path.window(time)
                val fullHeight = heightDp / window.height.toFloat()
                val fullWidth = fullHeight * aspect.toFloat()
                Box(Modifier.size(widthDp.dp, heightDp.dp).clip(RoundedCornerShape(14.dp)).background(Color(0xFF0F0F0F))
                    .border(1.dp, Color.White.copy(alpha = if (gestureFrom == null) 0.12f else 0.6f), RoundedCornerShape(14.dp))
                    .pointerInput(path, time) {
                        detectTransformGestures(onGesture = { _, pan, zoomBy, _ ->
                            val from = gestureFrom ?: run {
                                if (playing) pause()
                                path.window(time).also { gestureFrom = it }
                            }
                            val fh = with(density) { (heightDp / from.height.toFloat()).dp.toPx() }
                            val fw = fh * aspect.toFloat()
                            val moved = path.place(from.x - pan.x / fw, from.y - pan.y / fh, from.zoom * zoomBy)
                            gestureFrom = moved
                            placeKeyframe(moved)
                        })
                    }
                    .pointerInput(Unit) {
                        awaitPointerEventScope {
                            while (true) {
                                val event = awaitPointerEvent()
                                if (event.changes.all { !it.pressed } && gestureFrom != null) { gestureFrom = null; scheduleSave() }
                            }
                        }
                    }
                    .pointerInput(playing) { detectTapGestures { if (playing) pause() else { player.play(); playing = true } } },
                    contentAlignment = Alignment.Center) {
                    AndroidView({ TextureView(it).also { tv -> player.setVideoTextureView(tv) } },
                        Modifier.requiredSize(fullWidth.dp, fullHeight.dp).offset {
                            IntOffset(((0.5 - window.x) * fullWidth).dp.roundToPx(), ((0.5 - window.y) * fullHeight).dp.roundToPx())
                        })
                    if (!loaded) BootSpinner(32.dp, 3.dp)
                }
            }

            Text(when {
                vertical.crop == null && loaded -> "Finding the action…"
                failure != null -> failure.orEmpty()
                vertical.keyframes.isEmpty() -> "Following the action automatically. Drag to reframe, pinch to zoom."
                vertical.keyframes.size == 1 -> "1 keyframe"
                else -> "${vertical.keyframes.size} keyframes"
            }, fontSize = 13.sp, color = if (failure != null) Palette.accent else Palette.dim, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 10.dp))

            BoxWithConstraints(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp).height(48.dp)
                .pointerInput(duration) {
                    detectDragGestures(onDragStart = { if (playing) pause(); seek((it.x / size.width).coerceIn(0f, 1f) * duration) }) { change, _ ->
                        seek((change.position.x / size.width).coerceIn(0f, 1f) * duration)
                    }
                }
                .pointerInput(duration) { detectTapGestures { if (playing) pause(); seek((it.x / size.width).coerceIn(0f, 1f) * duration) } },
                contentAlignment = Alignment.CenterStart) {
                val span = maxOf(duration, 0.1)
                val w = maxWidth
                Box(Modifier.fillMaxWidth().height(36.dp).background(Color.White.copy(alpha = 0.1f), RoundedCornerShape(6.dp)))
                path.cuts.forEach { cut -> Box(Modifier.offset(x = w * (cut / span).toFloat()).width(1.5.dp).height(20.dp).background(Color.White.copy(alpha = 0.35f))) }
                vertical.keyframes.forEachIndexed { i, k ->
                    Box(Modifier.offset(x = w * (k.t / span).toFloat() - 6.dp).size(12.dp)
                        .background(if (i == keyframeHere) Color.White else Palette.accent, CircleShape)
                        .pressable { seek(k.t) })
                }
                Box(Modifier.offset(x = w * (time / span).coerceIn(0.0, 1.0).toFloat() - 1.5.dp).width(3.dp).height(48.dp).background(Color.White, CircleShape))
            }

            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                Icon(if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, if (playing) "Pause" else "Play", tint = Color.White,
                    modifier = Modifier.size(44.dp).padding(8.dp).pressable { if (playing) pause() else { player.play(); playing = true } })
                Text("${clockShort(time)} / ${clockShort(duration)}", fontSize = 13.sp, color = Palette.dim)
                Spacer(Modifier.weight(1f))
                keyframeHere?.let { index ->
                    Tool("Remove", Icons.Outlined.RemoveCircleOutline) {
                        vertical = vertical.copy(keyframes = vertical.keyframes.filterIndexed { i, _ -> i != index })
                        scheduleSave()
                    }
                }
                Tool("Automatic", Icons.Filled.AutoFixHigh, enabled = vertical.keyframes.isNotEmpty()) { confirmingAuto = true }
            }
        }
        exporting?.let { done ->
            Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.7f)), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    DownloadRing(done * 100, 56.dp)
                    Text("Making the vertical video… ${(done * 100).toInt()}%", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                }
            }
        }
    }
    if (confirmingAuto) {
        AlertDialog(
            onDismissRequest = { confirmingAuto = false },
            title = { Text("Back to automatic?") },
            text = { Text("Every keyframe placed by hand goes, and the frame follows the action on its own again.") },
            confirmButton = { TextButton({ confirmingAuto = false; vertical = vertical.copy(keyframes = emptyList()); scheduleSave() }) {
                Text("Clear Keyframes", color = Color(0xFFFF5A6E)) } },
            dismissButton = { TextButton({ confirmingAuto = false }) { Text("Cancel", color = Color.White) } },
            containerColor = Color(0xFF242424),
        )
    }
}

@Composable
private fun Tool(title: String, icon: androidx.compose.ui.graphics.vector.ImageVector, enabled: Boolean = true, onClick: () -> Unit) {
    Column(Modifier.widthIn(min = 56.dp).pressable(enabled, onClick).padding(vertical = 2.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Icon(icon, null, tint = Color.White.copy(alpha = if (enabled) 1f else 0.4f), modifier = Modifier.size(20.dp))
        Text(title, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = Color.White.copy(alpha = if (enabled) 1f else 0.4f))
    }
}

private fun clockShort(seconds: Double): String {
    val s = maxOf(0, seconds.toInt())
    return "%d:%02d".format(s / 60, s % 60)
}

@OptIn(UnstableApi::class)
private suspend fun exportVertical(context: Context, clip: Clip, path: VerticalPath, progress: (Double) -> Unit): File {
    val folder = File(context.cacheDir, "vertical").apply { mkdirs() }
    val source = File(folder, "clip-${clip.id}-wide.mp4")
    withContext(Dispatchers.IO) {
        val url = Api.url(clip.video)
        Api.http.newCall(Request.Builder().url(url).build()).execute().use { response ->
            if (!response.isSuccessful) throw java.io.IOException("download failed (${response.code})")
            source.outputStream().use { out -> response.body!!.byteStream().copyTo(out) }
        }
    }
    progress(0.05)
    val name = clip.title.replace("/", " ")
    val target = File(folder, "$name (vertical).mp4").apply { delete() }

    // In normalised device coordinates; the later stretch to 9:16 restores the shape.
    val crop = MatrixTransformation { presentationTimeUs ->
        val w = path.window(presentationTimeUs / 1_000_000.0)
        android.graphics.Matrix().apply {
            postTranslate(-(2 * w.x - 1).toFloat(), (2 * w.y - 1).toFloat())
            postScale((1 / w.width).toFloat(), (1 / w.height).toFloat())
        }
    }
    val edited = EditedMediaItem.Builder(MediaItem.fromUri(android.net.Uri.fromFile(source)))
        .setEffects(Effects(emptyList(), listOf(crop, Presentation.createForWidthAndHeight(1080, 1920, Presentation.LAYOUT_STRETCH_TO_FIT))))
        .build()
    return withContext(Dispatchers.Main) {
        suspendCancellableCoroutine { cont ->
            val transformer = Transformer.Builder(context)
                .setVideoMimeType(MimeTypes.VIDEO_H264)
                .addListener(object : Transformer.Listener {
                    override fun onCompleted(composition: Composition, result: ExportResult) { source.delete(); progress(1.0); cont.resume(target) }
                    override fun onError(composition: Composition, result: ExportResult, exception: ExportException) {
                        source.delete(); cont.resumeWithException(exception)
                    }
                })
                .build()
            transformer.start(edited, target.absolutePath)
            val holder = ProgressHolder()
            val ticker = kotlinx.coroutines.MainScope().launch {
                while (true) {
                    if (transformer.getProgress(holder) == Transformer.PROGRESS_STATE_AVAILABLE) progress(0.05 + 0.95 * holder.progress / 100.0)
                    delay(200)
                }
            }
            cont.invokeOnCancellation { transformer.cancel() }
            kotlinx.coroutines.MainScope().launch { while (cont.isActive) delay(200); ticker.cancel() }
        }
    }
}

private fun share(context: Context, file: File) {
    val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
    val send = Intent(Intent.ACTION_SEND).setType("video/mp4").putExtra(Intent.EXTRA_STREAM, uri)
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    context.startActivity(Intent.createChooser(send, null).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
}
