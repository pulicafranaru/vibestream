package xyz.vibestream.app

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.snapping.SnapPosition
import androidx.compose.foundation.gestures.snapping.rememberSnapFlingBehavior
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.EpisodeItem
import xyz.vibestream.app.api.EpisodeRelease
import xyz.vibestream.app.api.SeasonSummary
import xyz.vibestream.app.ui.BootSpinner
import xyz.vibestream.app.ui.DownloadRing
import xyz.vibestream.app.ui.EpisodePhase
import xyz.vibestream.app.ui.Palette
import xyz.vibestream.app.ui.ProgressLine
import xyz.vibestream.app.ui.RemoteImage
import xyz.vibestream.app.ui.SeasonMenuLabel
import xyz.vibestream.app.ui.Toasts
import xyz.vibestream.app.ui.fileSize
import xyz.vibestream.app.ui.liveDownload
import xyz.vibestream.app.ui.phase
import xyz.vibestream.app.ui.pressable
import xyz.vibestream.app.ui.said

// The player's Episodes (iOS PlayerEpisodes). Sideways, beside the picture as Settings is: the
// season in a capsule menu and a close button over a column of episodes that scrolls up and down as
// a cover flow, the TV app's.
@Composable
internal fun PlayerEpisodes(
    mediaID: Int,
    startSeason: Int,
    playID: String,
    stacked: Boolean,
    onChoose: (EpisodeItem) -> Unit,
    onClose: (() -> Unit)? = null,
) {
    var seasons by remember { mutableStateOf<List<SeasonSummary>>(emptyList()) }
    var season by remember { mutableStateOf(startSeason) }
    var episodes by remember { mutableStateOf<List<EpisodeItem>?>(null) }
    var fetching by remember { mutableStateOf<Set<Int>>(emptySet()) }
    val scope = rememberCoroutineScope()

    fun phaseOf(item: EpisodeItem) = if (item.id in fetching) EpisodePhase.Waiting else item.phase(AppState.downloads)
    suspend fun load() {
        runCatching { Api.season(mediaID, season).episodes }
            .onSuccess { episodes = it }
            .onFailure { if (episodes == null) episodes = emptyList() }
    }
    fun fetch(item: EpisodeItem, release: EpisodeRelease) {
        fetching = fetching + item.id
        scope.launch {
            runCatching { AppState.download(release.id, if (release.seasonPack) item.id else null); load() }
                .onFailure { Toasts.error(it.said()) }
            fetching = fetching - item.id
        }
    }
    fun isCurrent(item: EpisodeItem) = (item.playID != null && item.playID == playID) || "e${item.id}" == playID

    LaunchedEffect(mediaID) { seasons = runCatching { Api.media(mediaID).seasons.orEmpty() }.getOrDefault(emptyList()) }
    LaunchedEffect(mediaID, season) {
        episodes = null
        load()
        while (true) {
            delay(5_000)
            if (episodes.orEmpty().any { phaseOf(it).busy }) load()
        }
    }

    val rows = Rows(::phaseOf, ::isCurrent, ::fetch, onChoose)
    if (stacked) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            SeasonMenu(seasons, season, large = false) { season = it }
            val list = episodes
            if (list == null) Box(Modifier.fillMaxWidth().padding(vertical = 30.dp), contentAlignment = Alignment.Center) { BootSpinner(32.dp, 3.dp) }
            else Column(verticalArrangement = Arrangement.spacedBy(14.dp)) { list.forEach { rows.ListRow(it) } }
        }
    } else {
        Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                SeasonMenu(seasons, season, large = true) { season = it }
                Spacer(Modifier.weight(1f))
                onClose?.let {
                    // Bare, as Settings' is.
                    Box(Modifier.size(44.dp).pressable(onClick = it), contentAlignment = Alignment.Center) {
                        Icon(Icons.Filled.Close, "Close episodes", tint = Color.White, modifier = Modifier.size(24.dp))
                    }
                }
            }
            val list = episodes
            if (list == null) Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { BootSpinner(32.dp, 3.dp) }
            else rows.Flow(list)
        }
    }
}

@Composable
private fun SeasonMenu(seasons: List<SeasonSummary>, season: Int, large: Boolean, onSeason: (Int) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        SeasonMenuLabel(seasons.firstOrNull { it.number == season }?.name ?: "Season $season", large) { if (seasons.size > 1) open = true }
        DropdownMenu(open, onDismissRequest = { open = false }, containerColor = Color(0xFF242424)) {
            seasons.forEach { s -> DropdownMenuItem(text = { Text(s.name) }, onClick = { onSeason(s.number); open = false }) }
        }
    }
}

/** The pieces both layouts are made of, sharing what an episode's state is. */
private class Rows(
    val phase: (EpisodeItem) -> EpisodePhase,
    val isCurrent: (EpisodeItem) -> Boolean,
    val fetch: (EpisodeItem, EpisodeRelease) -> Unit,
    val onChoose: (EpisodeItem) -> Unit,
) {
    /** The cover flow beside the sideways picture. */
    @Composable
    fun Flow(episodes: List<EpisodeItem>) {
        val stillWidth = if (LocalConfiguration.current.smallestScreenWidthDp >= 600) 220.dp else 150.dp
        val height = stillWidth * 9f / 16f
        val gap = 10.dp
        val list = rememberLazyListState()
        val scope = rememberCoroutineScope()
        // The episode in the middle: the row nearest the column's middle.
        val centred by remember {
            derivedStateOf {
                val info = list.layoutInfo
                val middle = (info.viewportStartOffset + info.viewportEndOffset) / 2
                info.visibleItemsInfo.minByOrNull { kotlin.math.abs(it.offset + it.size / 2 - middle) }?.index
            }
        }
        // The one playing, in its own season; the first in another.
        LaunchedEffect(episodes.isNotEmpty()) {
            val at = episodes.indexOfFirst(isCurrent)
            if (at > 0) list.scrollToItem(at)
        }
        BoxWithConstraints(Modifier.fillMaxSize()) {
            // Room above the first and below the last, so they too come to the middle.
            val margin = ((maxHeight - height) / 2).coerceAtLeast(0.dp)
            LazyColumn(
                state = list,
                contentPadding = PaddingValues(vertical = margin, horizontal = 6.dp),
                verticalArrangement = Arrangement.spacedBy(gap),
                flingBehavior = rememberSnapFlingBehavior(list, SnapPosition.Center),
                modifier = Modifier.fillMaxSize()
                    .graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen }
                    .drawWithContent {
                        drawContent()
                        drawRect(Brush.verticalGradient(0f to Color.Transparent, 0.1f to Color.Black, 0.9f to Color.Black, 1f to Color.Transparent),
                            blendMode = BlendMode.DstIn)
                    },
            ) {
                itemsIndexed(episodes, key = { _, item -> item.id }) { index, item ->
                    val middle = centred == index
                    FlowRow(item, middle, stillWidth, height, Modifier.graphicsLayer {
                        // Smaller and dimmer with the distance from the middle,
                        // all through a scroll, from the left edge so the stills
                        // stay in one column.
                        val info = list.layoutInfo
                        val row = info.visibleItemsInfo.firstOrNull { it.index == index }
                        val away = if (row == null) 1f else {
                            val centre = (info.viewportStartOffset + info.viewportEndOffset) / 2f
                            (kotlin.math.abs(row.offset + row.size / 2f - centre) / (height + gap).toPx()).coerceAtMost(1f)
                        }
                        scaleX = 1 - 0.16f * away
                        scaleY = 1 - 0.16f * away
                        alpha = 1 - 0.62f * away
                        transformOrigin = TransformOrigin(0f, 0.5f)
                    }) {
                        if (!middle) scope.launch { list.animateScrollToItem(index) }
                        else if (!isCurrent(item)) {
                            if (item.playable) onChoose(item)
                            else if (phase(item) == EpisodePhase.Downloadable) item.releases?.firstOrNull()?.let { fetch(item, it) }
                        }
                    }
                }
            }
        }
    }

    @Composable
    private fun FlowRow(item: EpisodeItem, middle: Boolean, stillWidth: Dp, height: Dp, modifier: Modifier, onTap: () -> Unit) {
        val current = isCurrent(item)
        Row(modifier.fillMaxWidth().height(height).then(if (current) Modifier.background(CURRENT_CARD, RoundedCornerShape(8.dp)) else Modifier)
            .pressable(onClick = onTap), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.shadow(if (middle) 14.dp else 0.dp, RoundedCornerShape(4.dp)), contentAlignment = Alignment.Center) {
                Still(item, stillWidth, marked = middle)
                when (val p = phase(item)) {
                    EpisodePhase.Waiting -> DownloadRing(null, 40.dp)
                    is EpisodePhase.Arriving -> DownloadRing(p.percent, 40.dp, showsLabel = false)
                    is EpisodePhase.Preparing -> DownloadRing(p.percent, 40.dp, showsLabel = false)
                    EpisodePhase.Downloadable -> if (middle && item.releases?.firstOrNull() != null) {
                        Box(Modifier.size(40.dp).background(Color.Black.copy(alpha = 0.45f), CircleShape)
                            .border(1.5.dp, Color.White.copy(alpha = 0.85f), CircleShape), contentAlignment = Alignment.Center) {
                            Icon(painterResource(R.drawable.ic_download), "Download episode ${item.episode}", tint = Color.White, modifier = Modifier.size(18.dp))
                        }
                    }
                    else -> {}
                }
            }
            Column(Modifier.weight(1f).padding(vertical = if (current) 6.dp else 0.dp, horizontal = 0.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Title(item, current, 15)
                Status(item, current, 12)
                item.overview?.takeIf { it.isNotEmpty() }?.let {
                    // Whatever room the row has left, cut short to fit.
                    Text(it, fontSize = 12.sp, color = Palette.dim, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                }
            }
        }
    }

    /** One episode in the upright tab's list. A tap plays it when it is here. */
    @Composable
    fun ListRow(item: EpisodeItem) {
        val current = isCurrent(item)
        val p = phase(item)
        Column(Modifier.fillMaxWidth().alpha(if (p == EpisodePhase.Unobtainable) 0.55f else 1f)
            .then(if (current) Modifier.background(CURRENT_CARD, RoundedCornerShape(10.dp)).padding(10.dp) else Modifier)
            .pressable(!current && item.playable) { onChoose(item) },
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Still(item, 136.dp)
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Title(item, current, 15)
                    Status(item, current, 13)
                }
                // Download for an episode that can be fetched, the ring while it comes.
                Box(Modifier.size(40.dp), contentAlignment = Alignment.Center) {
                    when (p) {
                        EpisodePhase.Waiting -> DownloadRing(null, 30.dp)
                        is EpisodePhase.Arriving -> DownloadRing(p.percent, 30.dp, showsLabel = false)
                        is EpisodePhase.Preparing -> DownloadRing(p.percent, 30.dp, showsLabel = false)
                        EpisodePhase.Downloadable -> item.releases?.firstOrNull()?.let { release ->
                            Box(Modifier.size(40.dp).pressable { fetch(item, release) }, contentAlignment = Alignment.Center) {
                                Icon(painterResource(R.drawable.ic_download), "Download episode ${item.episode}", tint = Color.White, modifier = Modifier.size(20.dp))
                            }
                        }
                        else -> {}
                    }
                }
            }
            item.overview?.takeIf { it.isNotEmpty() }?.let {
                Text(it, fontSize = 13.sp, color = if (current) Palette.faint else Palette.dim, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
    }

    @Composable
    private fun Title(item: EpisodeItem, current: Boolean, size: Int) {
        Text("${item.episode}. ${item.name}", fontSize = size.sp, fontWeight = FontWeight.SemiBold,
            color = if (current) Palette.dim else Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }

    /** Its length, or where it is on the way to being playable. */
    @Composable
    private fun Status(item: EpisodeItem, current: Boolean, size: Int) {
        if (current) {
            Text("Playing", fontSize = size.sp, fontWeight = FontWeight.SemiBold, color = Palette.accent, maxLines = 1)
            return
        }
        val line = when (val p = phase(item)) {
            EpisodePhase.Waiting -> "Waiting for download"
            // How fast and how long, as the TV says it, not a bare figure.
            is EpisodePhase.Arriving -> buildList {
                add(p.percent?.let { "Downloading ${it.toInt()}%" } ?: "Downloading")
                item.liveDownload(AppState.downloads)?.let { live ->
                    live.dlSpeed?.takeIf { it > 0 }?.let { add("${fileSize(it)}/s") }
                    live.etaSeconds?.takeIf { it in 1 until 360_000 }?.let { add("${maxOf(1, it / 60)}m left") }
                }
            }.joinToString(" · ")
            is EpisodePhase.Preparing -> p.percent?.let { "Preparing ${it.toInt()}%" } ?: "Preparing"
            is EpisodePhase.Failed -> p.error
            else -> item.lengthLabel
        } ?: return
        Text(line, fontSize = size.sp, color = Palette.faint, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }

    /** The still, with a play mark when a tap plays it and how much has been
     *  watched along the bottom; the one playing dimmed under a waveform. */
    @Composable
    private fun Still(item: EpisodeItem, width: Dp, marked: Boolean = true) {
        val current = isCurrent(item)
        Box(Modifier.width(width).height(width * 9f / 16f).clip(RoundedCornerShape(4.dp)).background(Color.Black), contentAlignment = Alignment.Center) {
            RemoteImage(item.still, Modifier.fillMaxSize())
            if (current) {
                Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.55f)))
                val wave = rememberInfiniteTransition(label = "wave")
                val level by wave.animateFloat(0.55f, 1f, infiniteRepeatable(tween(700, easing = LinearEasing), RepeatMode.Reverse), label = "level")
                Icon(Icons.Filled.GraphicEq, "Playing", tint = Color.White.copy(alpha = level), modifier = Modifier.size(22.dp))
            } else if (item.playable && marked) {
                Box(Modifier.size(36.dp).background(Color.Black.copy(alpha = 0.45f), CircleShape)
                    .border(1.5.dp, Color.White.copy(alpha = 0.85f), CircleShape), contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.PlayArrow, null, tint = Color.White, modifier = Modifier.size(20.dp))
                }
            }
            if (item.watched || item.resumePercent > 1) {
                ProgressLine(if (item.watched) 100.0 else item.resumePercent, Modifier.align(Alignment.BottomCenter).fillMaxWidth())
            }
        }
    }
}

/** The grey card under the episode playing. */
private val CURRENT_CARD = Color.White.copy(alpha = 0.08f)
