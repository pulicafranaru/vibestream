package xyz.vibestream.app.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import kotlinx.coroutines.launch
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import coil3.compose.SubcomposeAsyncImage
import coil3.toBitmap
import xyz.vibestream.app.AppState
import xyz.vibestream.app.R
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.Card
import xyz.vibestream.app.api.DownloadState

@Composable
fun RemoteImage(
    url: String?,
    modifier: Modifier = Modifier,
    contentScale: ContentScale = ContentScale.Crop,
    alignment: Alignment = Alignment.Center,
    onImage: ((android.graphics.Bitmap) -> Unit)? = null,
    colorFilter: androidx.compose.ui.graphics.ColorFilter? = null,
) {
    SubcomposeAsyncImage(
        model = Api.absolute(url),
        contentDescription = null,
        contentScale = contentScale,
        alignment = alignment,
        colorFilter = colorFilter,
        modifier = modifier.background(Palette.tile),
        loading = { Box(Modifier.fillMaxSize().background(Palette.tile)) },
        error = { Box(Modifier.fillMaxSize().background(Palette.tile)) },
        onSuccess = { state -> onImage?.let { runCatching { it(state.result.image.toBitmap()) } } },
    )
}

/*
 * Black or white, whichever will be seen against the top right corner of
 * the artwork: what the title page's close glyph is drawn in. Biased towards
 * white, since the artwork is usually dark, as on iOS (ArtworkTint).
 */
fun cornerTint(image: android.graphics.Bitmap): Color {
    val soft = if (image.config == android.graphics.Bitmap.Config.HARDWARE) image.copy(android.graphics.Bitmap.Config.ARGB_8888, false) else image
    val w = soft.width
    val h = soft.height
    val x0 = (w * 0.7).toInt()
    val y1 = maxOf(1, (h * 0.25).toInt())
    var sum = 0.0
    var count = 0
    val stepX = maxOf(1, (w - x0) / 24)
    val stepY = maxOf(1, y1 / 16)
    for (y in 0 until y1 step stepY) for (x in x0 until w step stepX) {
        val c = soft.getPixel(x, y)
        // Rec. 709 weights: green carries most of what the eye reads as bright.
        sum += (0.2126 * ((c shr 16) and 0xFF) + 0.7152 * ((c shr 8) and 0xFF) + 0.0722 * (c and 0xFF)) / 255
        count++
    }
    return if (count > 0 && sum / count > 0.62) Color.Black else Color.White
}

/** A press that dims and shrinks a touch, as SwiftUI's plain buttons do,
 *  without Material's ripple. */
@Composable
fun Modifier.pressable(enabled: Boolean = true, onClick: () -> Unit): Modifier {
    val source = remember { MutableInteractionSource() }
    val pressed by source.collectIsPressedAsState()
    return this
        .scale(if (pressed) 0.98f else 1f)
        .clickable(source, indication = null, enabled = enabled, onClick = onClick)
}

// Null progress is real: before qBittorrent reports anything there is no number, and 0% would read as a stall.
@Composable
fun DownloadRing(percent: Double?, size: Dp = 34.dp, showsLabel: Boolean = true) {
    val stroke = maxOf(2.5f, size.value * 0.09f).dp
    val spin = rememberInfiniteTransition(label = "ring")
    val turn by spin.animateFloat(0f, 360f, infiniteRepeatable(tween(1000, easing = LinearEasing)), label = "turn")
    Box(
        Modifier.size(size + stroke * 2).background(Color.Black.copy(alpha = 0.45f), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.size(size)) {
            val w = stroke.toPx()
            drawCircle(Color.White.copy(alpha = 0.28f), style = Stroke(w))
            if (percent != null) {
                val sweep = 360f * (percent / 100).coerceIn(0.02, 1.0).toFloat()
                drawArc(Palette.accent, -90f, sweep, false, style = Stroke(w, cap = StrokeCap.Round))
            } else {
                drawArc(Palette.accent, turn - 90f, 90f, false, style = Stroke(w, cap = StrokeCap.Round))
            }
        }
        if (percent != null && showsLabel && size >= 30.dp) {
            Text("${percent.toInt()}", color = Color.White, fontWeight = FontWeight.Bold,
                fontSize = (size.value * 0.3f).sp)
        }
    }
}

@Composable
fun BootSpinner(size: Dp = 48.dp, line: Dp = 4.dp) {
    val spin = rememberInfiniteTransition(label = "boot")
    val turn by spin.animateFloat(0f, 360f, infiniteRepeatable(tween(900, easing = LinearEasing), RepeatMode.Restart), label = "turn")
    Canvas(Modifier.size(size).rotate(turn)) {
        val w = line.toPx()
        val inset = w / 2
        val box = Size(this.size.width - w, this.size.height - w)
        drawArc(Color.White.copy(alpha = 0.14f), 0f, 360f, false, Offset(inset, inset), box, style = Stroke(w))
        drawArc(Palette.accent, 225f, 90f, false, Offset(inset, inset), box, style = Stroke(w))
    }
}

object GenreColor {
    private val colours = mapOf(
        "Action" to Triple(240, 68, 44), "Adventure" to Triple(227, 155, 45),
        "Action & Adventure" to Triple(238, 107, 43), "Comedy" to Triple(242, 195, 53),
        "Drama" to Triple(176, 58, 98), "Romance" to Triple(228, 108, 140),
        "Horror" to Triple(176, 18, 30), "Thriller" to Triple(154, 184, 58),
        "Crime" to Triple(79, 125, 179), "Mystery" to Triple(42, 140, 140),
        "Science Fiction" to Triple(47, 155, 235), "Fantasy" to Triple(122, 91, 224),
        "Sci-Fi & Fantasy" to Triple(78, 125, 235), "Animation" to Triple(181, 101, 232),
        "Family" to Triple(242, 148, 107), "Kids" to Triple(46, 196, 201),
        "Documentary" to Triple(79, 163, 143), "History" to Triple(176, 125, 78),
        "War" to Triple(124, 132, 64), "War & Politics" to Triple(124, 132, 64),
        "Western" to Triple(184, 90, 51), "Music" to Triple(227, 72, 156),
        "Reality" to Triple(255, 123, 92), "News" to Triple(94, 127, 168),
        "Talk" to Triple(217, 170, 75), "Soap" to Triple(192, 138, 216),
    )

    fun of(name: String): Color {
        val (r, g, b) = colours[name] ?: Triple(142, 138, 134)
        return Color(r, g, b)
    }
}

/** Prefer the polled live state: the card's own copy is a snapshot from when its row was fetched. */
fun liveDownload(card: Card): DownloadState? {
    val primary = card.primaryReleaseID
    val live = primary?.let { AppState.downloads[it] }
    if (live != null && live.state != "removed") return live
    return if (AppState.downloads.isEmpty()) card.download else null
}

@Composable
fun ProgressLine(percent: Double, modifier: Modifier = Modifier, track: Float = 0.3f, fill: Color = Palette.accent) {
    Box(modifier.height(3.dp).background(Color.White.copy(alpha = track))) {
        Box(Modifier.fillMaxWidth((percent / 100).coerceIn(0.0, 1.0).toFloat()).height(3.dp).background(fill))
    }
}

@Composable
fun PosterCard(card: Card, width: Dp? = Metrics.posterWidth, onClick: () -> Unit) {
    val shape = RoundedCornerShape(6.dp)
    val base = if (width != null) Modifier.width(width).aspectRatio(Metrics.posterAspect)
    else Modifier.fillMaxWidth().aspectRatio(Metrics.posterAspect)
    val locked = card.locked == true
    // Locked by parental controls: dimmed and greyed, with what it carries
    // still on it, under a padlock, as on iOS.
    Box(base.pressable(onClick = onClick), contentAlignment = Alignment.Center) {
        Box(Modifier.fillMaxSize().clip(shape).alpha(if (locked) 0.35f else 1f)) {
            RemoteImage(card.poster, Modifier.fillMaxSize(),
                colorFilter = if (locked) androidx.compose.ui.graphics.ColorFilter.colorMatrix(
                    androidx.compose.ui.graphics.ColorMatrix().apply { setToSaturation(0.4f) }) else null)
            val download = liveDownload(card)
            if (download != null && (download.isWorking || download.isPreparing)) {
                Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.45f)), contentAlignment = Alignment.Center) {
                    DownloadRing(if (download.isWorking && download.percent > 0) download.percent else null, 42.dp)
                }
            }
            val percent = card.resumePercent ?: 0.0
            if (percent > 1) ProgressLine(percent, Modifier.align(Alignment.BottomCenter).fillMaxWidth())
            if (card.quality?.resolution == "2160p") {
                // A line as tall as the letters: the theme's line height made the
                // box taller than wide.
                Text("4K", fontSize = 9.sp, fontWeight = FontWeight.Black, color = Color.White, style = TightText,
                    modifier = Modifier.align(Alignment.TopEnd).padding(5.dp)
                        .background(Color.Black.copy(alpha = 0.65f), RoundedCornerShape(3.dp))
                        .padding(horizontal = 4.dp, vertical = 2.dp))
            }
            // An amber dot: this one is on the server and plays now.
            if (card.playableDownloadID != null) {
                Box(Modifier.align(Alignment.TopStart).padding(6.dp).size(8.dp)
                    .border(2.dp, Palette.ground.copy(alpha = 0.75f), CircleShape)
                    .background(Palette.good, CircleShape))
            }
        }
        if (locked) LockBadge()
    }
}

/** A padlock on a dark disc: locked by parental controls. */
@Composable
fun LockBadge(size: Dp = 20.dp) {
    Icon(Icons.Filled.Lock, "Locked by parental controls", tint = Color.White,
        modifier = Modifier.background(Color.Black.copy(alpha = 0.6f), CircleShape).padding(size * 0.6f).size(size))
}

/*
 * Continue Watching: a wider tile, a play affordance and the progress
 * directly under the artwork. A tap opens the title page already playing,
 * so the corner button that led to the page went, as on iOS.
 */
@Composable
fun ContinueCard(card: Card, width: Dp, onPlay: () -> Unit) {
    Column(Modifier.width(width).clip(RoundedCornerShape(6.dp))) {
        Box(Modifier.width(width).aspectRatio(Metrics.posterAspect).pressable(onClick = onPlay)) {
            RemoteImage(card.poster, Modifier.fillMaxSize())
            Box(
                Modifier.align(Alignment.Center).size(42.dp)
                    .background(Color.Black.copy(alpha = 0.35f), CircleShape)
                    .border(1.5.dp, Color.White.copy(alpha = 0.9f), CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Filled.PlayArrow, null, tint = Color.White, modifier = Modifier.size(24.dp).padding(start = 1.dp))
            }
            card.resumeLabel?.let { label ->
                Text(if (card.resumeKind == "next") "Next: $label" else label,
                    fontSize = 11.sp, fontWeight = FontWeight.Bold, color = Color.White,
                    modifier = Modifier.align(Alignment.BottomStart).padding(6.dp)
                        .background(Color.Black.copy(alpha = 0.78f), RoundedCornerShape(4.dp))
                        .padding(horizontal = 5.dp, vertical = 2.dp))
            }
        }
        ProgressLine(card.resumePercent ?: 0.0, Modifier.width(width), track = 0.28f)
    }
}

@Composable
fun CardRow(title: String, items: List<Card>, trailing: (@Composable () -> Unit)? = null, tile: @Composable (Card) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(title, fontSize = 17.sp, fontWeight = FontWeight.Bold, color = Color.White, modifier = Modifier.weight(1f))
            trailing?.invoke()
        }
        LazyRow(
            horizontalArrangement = Arrangement.spacedBy(Metrics.rowSpacing),
            contentPadding = PaddingValues(horizontal = 16.dp),
        ) {
            items(items, key = { it.mediaID }) { tile(it) }
        }
    }
}

@Composable
fun Pill(
    prominent: Boolean = true,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    onClick: () -> Unit,
    content: @Composable () -> Unit,
) {
    Box(
        modifier.height(46.dp)
            .clip(RoundedCornerShape(50))
            .background(if (prominent) Color.White else Color.White.copy(alpha = 0.16f))
            .pressable(enabled, onClick),
        contentAlignment = Alignment.Center,
    ) {
        androidx.compose.runtime.CompositionLocalProvider(
            androidx.compose.material3.LocalContentColor provides if (prominent) Color.Black else Color.White,
        ) { content() }
    }
}

@Composable
fun PillLabel(text: String, icon: @Composable (() -> Unit)? = null) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        icon?.invoke()
        Text(text, fontSize = 17.sp, fontWeight = FontWeight.SemiBold,
            color = androidx.compose.material3.LocalContentColor.current, maxLines = 1)
    }
}

sealed class TitleAction {
    data object Download : TitleAction()
    data object Queuing : TitleAction()
    data object Waiting : TitleAction()
    data class Downloading(val percent: Double?) : TitleAction()
    data class Preparing(val percent: Double?) : TitleAction()
    data class Play(val text: String) : TitleAction()
    data class Failed(val reason: String) : TitleAction()

    val busy get() = this is Queuing || this is Waiting || this is Downloading || this is Preparing

    companion object {
        fun of(live: DownloadState?, resume: String? = null, optimistic: Boolean = false): TitleAction {
            if (live == null || live.state == "removed") return if (optimistic) Queuing else Download
            if (live.isPlayable) return Play(resume ?: "Play")
            // The sentence the server wrote for the screen, never the raw error.
            if (live.prepareError != null) return Failed("It arrived but could not be made playable. Try again.")
            if (live.isPreparing) return Preparing(live.preparePercent)
            if (live.state == "error") return Failed(live.errorMessage ?: "The download could not start. Try again.")
            if (live.state == "downloading") return Downloading(live.percent.takeIf { it >= 1 })
            if (live.isWorking) return Waiting
            return if (optimistic) Queuing else Download
        }
    }
}

@Composable
fun TitleButton(action: TitleAction, modifier: Modifier = Modifier, onPress: () -> Unit) {
    val label = when (action) {
        TitleAction.Download -> "Download"
        TitleAction.Queuing -> "Starting download"
        TitleAction.Waiting -> "Waiting for download"
        is TitleAction.Downloading -> action.percent?.let { "Downloading ${it.toInt()}%" } ?: "Downloading"
        is TitleAction.Preparing -> action.percent?.let { "Preparing ${it.toInt()}%" } ?: "Preparing"
        is TitleAction.Play -> action.text
        is TitleAction.Failed -> "Try again"
    }
    val prominent = action is TitleAction.Download || action is TitleAction.Play || action is TitleAction.Failed
    Box(modifier) {
        Pill(prominent, Modifier.fillMaxWidth(), onClick = onPress) {
            PillLabel(label) {
                when (action) {
                    TitleAction.Download -> Icon(painterResource(R.drawable.ic_download), null, Modifier.size(20.dp))
                    is TitleAction.Play -> Icon(Icons.Filled.PlayArrow, null, Modifier.size(24.dp))
                    is TitleAction.Failed -> Icon(Icons.Filled.Refresh, null, Modifier.size(22.dp))
                    is TitleAction.Downloading -> DownloadRing(action.percent, 22.dp, showsLabel = false)
                    is TitleAction.Preparing -> DownloadRing(action.percent, 22.dp, showsLabel = false)
                    else -> DownloadRing(null, 22.dp, showsLabel = false)
                }
            }
        }
        // The last attempt failed: said on the button itself, so it still
        // shows after the toast has gone.
        if (action is TitleAction.Failed) ErrorBadge(22.dp, Modifier.align(Alignment.TopEnd).offset(x = 5.dp, y = (-5).dp))
    }
}

@Composable
fun HeroCard(
    card: Card,
    wide: Boolean = false,
    download: DownloadState?,
    busy: Boolean,
    saved: Boolean,
    onPlay: () -> Unit,
    onDownload: () -> Unit,
    onInfo: () -> Unit,
    onMyList: () -> Unit,
) {
    val action = if (download == null && card.playableDownloadID != null) TitleAction.Play("Play")
    else TitleAction.of(download, optimistic = busy)
    val press = {
        when (action) {
            is TitleAction.Play -> onPlay()
            TitleAction.Download, is TitleAction.Failed -> onDownload()
            else -> onInfo()
        }
    }
    if (wide) { Billboard(card, action, saved, press, onInfo, onMyList); return }
    Box(
        Modifier.fillMaxWidth().aspectRatio(Metrics.posterAspect).clip(RoundedCornerShape(10.dp))
            .clickable(remember { MutableInteractionSource() }, null, onClick = onInfo),
    ) {
        RemoteImage(card.poster ?: card.backdrop, Modifier.fillMaxSize())
        Box(Modifier.fillMaxSize().background(Brush.verticalGradient(
            0.38f to Color.Transparent, 0.68f to Color.Black.copy(alpha = 0.55f), 1f to Color.Black.copy(alpha = 0.96f),
        )))
        Column(
            Modifier.align(Alignment.BottomCenter).padding(bottom = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            card.genres?.takeIf { it.isNotEmpty() }?.let {
                Text(it.take(3).joinToString("  •  "), fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
            }
            Row(Modifier.padding(horizontal = 14.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                TitleButton(action, Modifier.weight(1f), onPress = press)
                Pill(false, Modifier.weight(1f), onClick = onMyList) {
                    PillLabel("Watchlist") {
                        Icon(if (saved) Icons.Filled.Check else Icons.Filled.Add,
                            null, Modifier.size(22.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun Billboard(card: Card, action: TitleAction, saved: Boolean, onAction: () -> Unit, onInfo: () -> Unit, onMyList: () -> Unit) {
    val configuration = androidx.compose.ui.platform.LocalConfiguration.current
    val landscape = configuration.screenWidthDp > configuration.screenHeightDp
    val height = maxOf(360f, configuration.screenHeightDp * if (landscape) 0.82f else 0.66f)
        .coerceAtMost(maxOf(360f, configuration.screenWidthDp * 0.62f)).dp
    Box(Modifier.fillMaxWidth().height(height).clickable(remember { MutableInteractionSource() }, null, onClick = onInfo)) {
        SubcomposeAsyncImage(model = card.backdrop ?: card.poster, contentDescription = null, contentScale = ContentScale.Crop,
            alignment = Alignment.TopCenter, modifier = Modifier.fillMaxSize().background(Palette.tile))
        Box(Modifier.fillMaxSize().background(Brush.radialGradient(
            listOf(Palette.ground.copy(alpha = 0.85f), Color.Transparent),
            center = Offset(0f, Float.POSITIVE_INFINITY), radius = 1400f)))
        Box(Modifier.fillMaxSize().background(Brush.verticalGradient(
            0.5f to Color.Transparent, 0.82f to Palette.ground.copy(alpha = 0.7f), 1f to Palette.ground)))
        Column(Modifier.align(Alignment.BottomStart).widthIn(max = 560.dp).padding(start = 28.dp, bottom = 26.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(card.title, fontSize = 44.sp, fontWeight = FontWeight.Black, color = Color.White, maxLines = 2, lineHeight = 46.sp)
            val facts = buildList {
                card.year?.let { add("$it") }
                card.runtime?.takeIf { it > 0 }?.let { add(if (it >= 60) "${it / 60}h ${it % 60}m" else "${it}m") }
                addAll(card.genres.orEmpty().take(3))
            }
            if (facts.isNotEmpty()) Text(facts.joinToString("  •  "), fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                color = Color.White.copy(alpha = 0.9f))
            card.overview?.takeIf { it.isNotEmpty() }?.let {
                Text(it, fontSize = 16.sp, color = Color.White.copy(alpha = 0.82f), maxLines = 3, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
            }
            Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                TitleButton(action, Modifier.width(230.dp), onPress = onAction)
                Pill(false, Modifier.width(230.dp), onClick = onMyList) {
                    PillLabel("Watchlist") { Icon(if (saved) Icons.Filled.Check else Icons.Filled.Add, null, Modifier.size(22.dp)) }
                }
            }
        }
    }
}

@Composable
fun Gap(height: Dp) = Spacer(Modifier.height(height))

@Composable
fun InfoGlyph() = Icon(Icons.Outlined.Info, null)

/** Full-screen dialog padding from the app window's bars: the dialog's window is told of neither bar
 *  yet runs a status bar's height past the bottom. */
@Composable
fun systemBarPadding(): androidx.compose.foundation.layout.PaddingValues {
    val activity = androidx.compose.ui.platform.LocalContext.current as? android.app.Activity
    val density = androidx.compose.ui.platform.LocalDensity.current
    val insets = activity?.window?.decorView?.let { androidx.core.view.ViewCompat.getRootWindowInsets(it) }
        ?.getInsets(androidx.core.view.WindowInsetsCompat.Type.systemBars())
    return with(density) {
        androidx.compose.foundation.layout.PaddingValues(bottom = ((insets?.bottom ?: 0) + (insets?.top ?: 0)).toDp())
    }
}

/** The first of these that fits the width at its natural size, else the
 *  last: SwiftUI's ViewThatFits, for a line that must never wrap. */
@Composable
fun FirstThatFits(vararg options: @Composable () -> Unit) {
    androidx.compose.ui.layout.SubcomposeLayout { constraints ->
        val loose = constraints.copy(minWidth = 0, maxWidth = androidx.compose.ui.unit.Constraints.Infinity)
        var chosen: androidx.compose.ui.layout.Placeable? = null
        for ((index, option) in options.withIndex()) {
            val placeable = subcompose(index, option).first().measure(loose)
            chosen = placeable
            if (placeable.width <= constraints.maxWidth) break
        }
        val p = chosen!!
        layout(p.width.coerceAtMost(constraints.maxWidth), p.height) { p.place(0, 0) }
    }
}

/** For a small badge: a line no taller than its letters, no font padding. */
val TightText = androidx.compose.ui.text.TextStyle(
    lineHeight = 1.em,
    platformStyle = androidx.compose.ui.text.PlatformTextStyle(includeFontPadding = false),
    lineHeightStyle = androidx.compose.ui.text.style.LineHeightStyle(
        androidx.compose.ui.text.style.LineHeightStyle.Alignment.Center,
        androidx.compose.ui.text.style.LineHeightStyle.Trim.Both,
    ),
)

/** One line that shrinks to fit, down to `minimumScale` of its size, as
 *  SwiftUI's minimumScaleFactor: never wrapped, never cut mid number. */
@Composable
fun ShrinkText(
    text: String,
    fontSize: androidx.compose.ui.unit.TextUnit,
    minimumScale: Float = 0.7f,
    fontWeight: FontWeight? = null,
    color: Color = Color.Unspecified,
    modifier: Modifier = Modifier,
) {
    var scale by remember(text) { mutableStateOf(1f) }
    Text(
        text, modifier, color = color, fontSize = fontSize * scale, fontWeight = fontWeight,
        maxLines = 1, softWrap = false,
        onTextLayout = { layout ->
            if (layout.didOverflowWidth && scale > minimumScale) scale = maxOf(minimumScale, scale - 0.05f)
        },
    )
}

/*
 * Pulled down, a screen reads its rows again now rather than at the next
 * load, as iOS's refreshable. The indicator comes down under the floating
 * top bar, not behind it.
 */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun Refreshable(onRefresh: suspend () -> Unit, modifier: Modifier = Modifier, content: @Composable androidx.compose.foundation.layout.BoxScope.() -> Unit) {
    var refreshing by remember { mutableStateOf(false) }
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    val state = androidx.compose.material3.pulltorefresh.rememberPullToRefreshState()
    val top = LocalTopClearance.current
    androidx.compose.material3.pulltorefresh.PullToRefreshBox(
        refreshing,
        onRefresh = { scope.launch { refreshing = true; runCatching { onRefresh() }; refreshing = false } },
        modifier = modifier,
        state = state,
        indicator = {
            androidx.compose.material3.pulltorefresh.PullToRefreshDefaults.Indicator(state, refreshing,
                Modifier.align(Alignment.TopCenter).padding(top = top), containerColor = Palette.chip, color = Palette.accent)
        },
        content = content,
    )
}

/** The activity under a context, which in a sheet's window is wrapped. */
fun android.content.Context.findActivity(): androidx.activity.ComponentActivity? {
    var c: android.content.Context? = this
    while (c is android.content.ContextWrapper) {
        if (c is androidx.activity.ComponentActivity) return c
        c = c.baseContext
    }
    return null
}
