package xyz.vibestream.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.ClickableText
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.ThumbDown
import androidx.compose.material.icons.filled.ThumbUp
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material.icons.outlined.ThumbDown
import androidx.compose.material.icons.outlined.ThumbUp
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import xyz.vibestream.app.AppState
import xyz.vibestream.app.Debug
import xyz.vibestream.app.R
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.Card
import xyz.vibestream.app.api.DownloadState
import xyz.vibestream.app.api.EpisodeItem
import xyz.vibestream.app.api.EpisodeRelease
import xyz.vibestream.app.api.NextUp
import xyz.vibestream.app.api.PlayRequest
import xyz.vibestream.app.api.Release
import xyz.vibestream.app.api.SeasonDetail
import xyz.vibestream.app.api.SeasonPack
import java.time.LocalDate
import java.time.format.DateTimeFormatter

private enum class DetailTab(val label: String) { Episodes("Episodes"), More("Similar"), Versions("Versions"), About("About") }

sealed class SeasonStatus {
    data class Offer(val pack: SeasonPack) : SeasonStatus()
    data class Downloaded(val held: List<Pair<Int, Int>>) : SeasonStatus()
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DetailView(card: Card, nav: Navigator, onClose: () -> Unit) {
    val wide = isWide()
    var full by remember(card.mediaID) { mutableStateOf<Card?>(null) }
    val shown = full ?: card
    var tab by remember(card.mediaID) {
        val wanted = Debug.string("detailTab")?.lowercase()
        mutableStateOf(DetailTab.entries.firstOrNull { wanted != null && it.label.lowercase().startsWith(wanted) }
            ?: if (card.isSeries) DetailTab.Episodes else DetailTab.More)
    }
    var seasonNumber by remember(card.mediaID) { mutableStateOf<Int?>(null) }
    var seasonStatus by remember(card.mediaID) { mutableStateOf<SeasonStatus?>(null) }
    var revision by remember { mutableIntStateOf(0) }
    var queuing by remember { mutableStateOf(false) }
    var queuingSeason by remember { mutableStateOf(false) }
    var deletingSeason by remember { mutableStateOf(false) }
    var confirmingCancel by remember { mutableStateOf(false) }
    var confirmingSeasonDelete by remember { mutableStateOf(false) }
    var collection by remember { mutableStateOf<CollectionTarget?>(null) }
    var castPicking by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    fun chooseSeason() {
        val seasons = shown.seasons ?: return
        if (seasonNumber != null || seasons.isEmpty()) return
        Debug.int("season")?.let { seasonNumber = it; return }
        val remembered = AppState.lastSeason[card.mediaID]
        seasonNumber = when {
            remembered != null && seasons.any { it.number == remembered } -> remembered
            shown.nextUp?.season?.let { n -> seasons.any { it.number == n } } == true -> shown.nextUp!!.season
            else -> seasons.firstOrNull { it.hasFiles }?.number ?: seasons.first().number
        }
    }

    LaunchedEffect(card.mediaID) {
        chooseSeason()
        AppState.refreshDownloads()
        full = runCatching { Api.media(card.mediaID) }.getOrNull()
        if (shown.isSeries) tab = DetailTab.Episodes
        chooseSeason()
    }
    LaunchedEffect(seasonNumber) { seasonNumber?.let { AppState.lastSeason[card.mediaID] = it } }

    // Check every release, not just the primary: the copy on disk is often another one.
    val live: DownloadState? = run {
        val ids = shown.releases.orEmpty().map { it.id } + listOfNotNull(shown.primaryReleaseID)
        val known = ids.mapNotNull { AppState.downloads[it] }.filter { it.state != "removed" }
        known.firstOrNull { it.isPlayable } ?: known.firstOrNull { it.isWorking || it.isPreparing } ?: known.firstOrNull()
            ?: if (AppState.downloads.isEmpty()) shown.download else null
    }
    val resumeLabel = shown.resumeSeconds?.takeIf { it > 30 }?.let { "Resume from ${timecode(it)}" } ?: "Play"
    val action = TitleAction.of(live, resumeLabel, queuing)
    val isHere = live?.isPlayable == true

    fun play(request: PlayRequest) = nav.play(request)
    fun playNextUp(next: NextUp) = play(PlayRequest(next.playID, shown.title))

    fun startDownload(torrent: Int?) {
        if (torrent == null || queuing) return
        queuing = true
        note = null
        scope.launch {
            runCatching { AppState.download(torrent) }.onFailure { note = it.message }
            queuing = false
        }
    }

    fun press() {
        note = null
        if (action.busy) { confirmingCancel = true; return }
        if (action is TitleAction.Play) {
            val id = live?.id ?: shown.playableDownloadID
            if (id != null) {
                if (shown.isSeries) shown.nextUp?.let(::playNextUp) ?: run { tab = DetailTab.Episodes }
                else play(PlayRequest(id.toString(), shown.title))
                return
            }
        }
        if (action is TitleAction.Failed && live != null) { startDownload(live.torrentID); return }
        startDownload(shown.primaryReleaseID)
    }

    Box(Modifier.fillMaxSize().background(Palette.ground)) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).navigationBarsPadding().padding(bottom = 30.dp)) {
            Box(Modifier.fillMaxWidth().aspectRatio(16f / 9f)) {
                // Pinned to the top: a poster used as a backdrop loses heads when cropped about the middle.
                RemoteImage(shown.backdrop ?: shown.poster, Modifier.fillMaxSize(), alignment = Alignment.TopCenter)
                Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(90.dp)
                    .background(Brush.verticalGradient(listOf(Color.Transparent, Palette.ground))))
            }
            Column(
                Modifier.padding(horizontal = if (wide) 28.dp else 16.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Text(shown.title, fontSize = if (wide) 30.sp else 24.sp, fontWeight = FontWeight.Bold, color = Color.White)
                MetaRow(shown)
                Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    val width = if (wide) Modifier.widthIn(max = 280.dp).fillMaxWidth() else Modifier.fillMaxWidth()
                    val next = shown.nextUp
                    if (shown.isSeries && next != null) {
                        NextUpButton(next, width) { playNextUp(next) }
                        if (action.busy) TitleButton(action, width) { press() }
                    } else if (!(shown.isSeries && isHere)) {
                        TitleButton(action, width) { press() }
                    }
                }
                note?.let { Text(it, fontSize = 13.sp, color = Palette.dim) }
                shown.overview?.let { Text(it, fontSize = 15.sp, color = Palette.dim) }

                Row(Modifier.padding(vertical = 4.dp)) {
                    val saved = shown.mediaID in AppState.myList
                    ActionItem(if (saved) "Watchlist" else "Watchlist", Modifier.weight(1f), onClick = { AppState.toggleMyList(shown) }) {
                        Icon(if (saved) Icons.Filled.Check else Icons.Filled.Add, null, Modifier.size(26.dp))
                    }
                    val rating = AppState.ratings[shown.mediaID]
                    ActionItem("Not for me", Modifier.weight(1f), tint = if (rating == -1) Palette.accent else Color.White,
                        onClick = { AppState.rate(shown.mediaID, -1) }) {
                        Icon(if (rating == -1) Icons.Filled.ThumbDown else Icons.Outlined.ThumbDown, null, Modifier.size(24.dp))
                    }
                    ActionItem("Like it!", Modifier.weight(1f), tint = if (rating == 1) Palette.accent else Color.White,
                        onClick = { AppState.rate(shown.mediaID, 1) }) {
                        Icon(if (rating == 1) Icons.Filled.ThumbUp else Icons.Outlined.ThumbUp, null, Modifier.size(24.dp))
                    }
                    if (castRequest(shown, action, live) != null) {
                        ActionItem("Play on", Modifier.weight(1f), onClick = { castPicking = true }) {
                            Icon(painterResource(R.drawable.ic_cast), null, Modifier.size(24.dp))
                        }
                    }
                    if (shown.isSeries) {
                        val season = seasonNumber?.let { "Season $it" } ?: "Season"
                        when (val status = seasonStatus) {
                            is SeasonStatus.Offer -> {
                                val pack = status.pack
                                val packLive = AppState.downloads[pack.id]
                                val arriving = pack.completeRequest == true && (packLive?.let { TitleAction.of(it).busy } ?: true)
                                val percent = (packLive?.let { TitleAction.of(it) } as? TitleAction.Downloading)?.percent
                                ActionItem("${if (arriving) "Downloading" else "Download"}\n$season", Modifier.weight(1f),
                                    enabled = !arriving && !queuingSeason, onClick = {
                                        queuingSeason = true
                                        note = null
                                        scope.launch {
                                            runCatching { AppState.download(pack.id, everything = pack.download != null); revision++ }
                                                .onFailure { note = "Couldn't start the download: ${it.message}" }
                                            queuingSeason = false
                                        }
                                    }) {
                                    if (arriving || queuingSeason) DownloadRing(if (queuingSeason) null else percent, 24.dp, false)
                                    else Icon(painterResource(R.drawable.ic_download_season), null, Modifier.size(26.dp))
                                }
                            }
                            is SeasonStatus.Downloaded -> ActionItem(
                                if (deletingSeason) "Deleting\n$season" else "$season\nDownloaded", Modifier.weight(1f),
                                enabled = !deletingSeason, onClick = { confirmingSeasonDelete = true },
                            ) {
                                if (deletingSeason) DownloadRing(null, 24.dp, false)
                                else Icon(Icons.Outlined.CheckCircle, null, Modifier.size(26.dp))
                            }
                            null -> {}
                        }
                    }
                }

                val tabs = if (shown.isSeries) DetailTab.entries.toList() else listOf(DetailTab.More, DetailTab.Versions, DetailTab.About)
                Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                    tabs.forEach { option ->
                        Column(Modifier.width(androidx.compose.foundation.layout.IntrinsicSize.Max).pressable { tab = option },
                            verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(option.label, fontSize = 15.sp,
                                fontWeight = if (tab == option) FontWeight.Bold else FontWeight.Normal,
                                color = if (tab == option) Color.White else Palette.faint)
                            Box(Modifier.fillMaxWidth().height(3.dp)
                                .background(if (tab == option) Palette.accent else Color.Transparent))
                        }
                    }
                }

                when (tab) {
                    DetailTab.Episodes -> EpisodeList(shown, seasonNumber, { seasonNumber = it }, { seasonStatus = it }, revision) { play(it) }
                    DetailTab.More -> MoreLikeThis(card.mediaID, wide) { nav.open(it) }
                    DetailTab.Versions -> Versions(shown, onPlay = { d ->
                        if (shown.isSeries) shown.nextUp?.let(::playNextUp) ?: run { tab = DetailTab.Episodes }
                        else play(PlayRequest(d.id.toString(), shown.title))
                    }, onDownload = { startDownload(it) })
                    DetailTab.About -> TitleAbout(shown) { collection = it }
                }
            }
        }

        Box(Modifier.align(Alignment.TopEnd).padding(end = 4.dp, top = 6.dp).size(44.dp).pressable(onClick = onClose),
            contentAlignment = Alignment.Center) {
            Icon(Icons.Filled.Close, "Close", tint = Color.White,
                modifier = Modifier.size(22.dp).shadow(3.dp, CircleShape, ambientColor = Color.Black, spotColor = Color.Black))
        }
    }

    if (confirmingCancel) {
        AlertDialog(
            onDismissRequest = { confirmingCancel = false },
            title = { Text("Cancel download?") },
            text = { Text("${shown.title} will stop, and anything already downloaded will be deleted from the server.") },
            confirmButton = {
                TextButton({
                    confirmingCancel = false
                    live?.let { d -> scope.launch { runCatching { AppState.cancel(d.id, d.torrentID) }.onFailure { note = it.message } } }
                }) { Text("Cancel download", color = Color(0xFFFF5A6E)) }
            },
            dismissButton = { TextButton({ confirmingCancel = false }) { Text("Keep downloading", color = Color.White) } },
            containerColor = Color(0xFF242424),
        )
    }
    if (confirmingSeasonDelete) {
        val season = seasonNumber?.let { "Season $it" } ?: "Season"
        val held = (seasonStatus as? SeasonStatus.Downloaded)?.held.orEmpty()
        AlertDialog(
            onDismissRequest = { confirmingSeasonDelete = false },
            title = { Text("Delete $season?") },
            text = { Text("This removes all ${held.size} episodes of ${season.lowercase()} from the server and from your library.") },
            confirmButton = {
                TextButton({
                    confirmingSeasonDelete = false
                    deletingSeason = true
                    note = null
                    scope.launch {
                        runCatching { held.forEach { (episode, download) -> Api.deleteEpisode(episode, download) } }
                            .onFailure { note = "Couldn't delete the whole season: ${it.message}" }
                        AppState.refreshDownloads()
                        revision++
                        deletingSeason = false
                    }
                }) { Text("Delete $season", color = Color(0xFFFF5A6E)) }
            },
            dismissButton = { TextButton({ confirmingSeasonDelete = false }) { Text("Cancel", color = Color.White) } },
            containerColor = Color(0xFF242424),
        )
    }
    collection?.let { target ->
        CollectionSheet(target, onOpen = { collection = null; nav.open(it) }, onClose = { collection = null })
    }
    if (castPicking) {
        ModalBottomSheet(onDismissRequest = { castPicking = false }, containerColor = Palette.ground) {
            CastPicker { device ->
                castPicking = false
                val request = castRequest(shown, action, live) ?: return@CastPicker
                scope.launch { if (Cast.play(request, null, device, AppState.profile?.id)) onClose() }
            }
        }
    }
}

private fun castRequest(shown: Card, action: TitleAction, live: DownloadState?): PlayRequest? {
    if (shown.isSeries) return shown.nextUp?.let { PlayRequest(it.playID, shown.title) }
    if (action is TitleAction.Play) (live?.id ?: shown.playableDownloadID)?.let { return PlayRequest(it.toString(), shown.title) }
    return null
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MetaRow(shown: Card) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.Center) {
        val style = Modifier.align(Alignment.CenterVertically)
        shown.voteAverage?.takeIf { it > 0 }?.let {
            Text("%.1f".format(it), fontSize = 12.sp, fontWeight = FontWeight.Bold, color = Palette.good, modifier = style)
        }
        shown.year?.let { Text("$it", fontSize = 13.sp, color = Palette.dim, modifier = style) }
        val seasons = shown.seasons?.count { it.number > 0 } ?: 0
        if (shown.isSeries && seasons > 0) {
            Text(if (seasons == 1) "1 Season" else "$seasons Seasons", fontSize = 13.sp, color = Palette.dim, modifier = style)
            if (shown.complete == true) Text("Complete", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Palette.good, modifier = style)
        } else if (!shown.isSeries) {
            shown.runtime?.takeIf { it > 0 }?.let { r ->
                Text(if (r >= 60) (if (r % 60 == 0) "${r / 60}h" else "${r / 60}h ${r % 60}m") else "${r}m",
                    fontSize = 13.sp, color = Palette.dim, modifier = style)
            }
        }
        shown.facts?.certification?.takeIf { it.isNotEmpty() }?.let {
            Badge(it, Color.White, Color.White.copy(alpha = 0.6f), style)
        }
        shown.quality?.badges?.forEach { Badge(it, Palette.dim, Palette.faint, style) }
    }
}

@Composable
fun Badge(text: String, color: Color, border: Color, modifier: Modifier = Modifier) {
    Text(text, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = color,
        modifier = modifier.border(1.dp, border, RoundedCornerShape(3.dp)).padding(horizontal = 5.dp, vertical = 2.dp))
}

@Composable
private fun NextUpButton(next: NextUp, modifier: Modifier, onClick: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Pill(true, modifier, onClick = onClick) {
            Row(Modifier.padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.PlayArrow, null, Modifier.size(24.dp))
                Text(if (next.isResume) "Resume ${next.label}" else "Play ${next.label}",
                    fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.Black, maxLines = 1,
                    modifier = Modifier.padding(start = 8.dp))
                if (next.isResume && next.resumePercent > 0) {
                    Spacer(Modifier.weight(1f))
                    Box(Modifier.widthIn(min = 36.dp, max = 110.dp).fillMaxWidth().height(4.dp)
                        .background(Color.Black.copy(alpha = 0.18f), CircleShape)) {
                        Box(Modifier.fillMaxWidth((next.resumePercent / 100).coerceIn(0.0, 1.0).toFloat()).height(4.dp)
                            .background(Palette.accent, CircleShape))
                    }
                }
            }
        }
        Text("${next.label}  ${next.name}", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Palette.dim, maxLines = 1)
    }
}

@Composable
private fun ActionItem(
    label: String,
    modifier: Modifier,
    tint: Color = Color.White,
    enabled: Boolean = true,
    onClick: () -> Unit,
    icon: @Composable () -> Unit,
) {
    Column(modifier.pressable(enabled, onClick), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Box(Modifier.height(26.dp), contentAlignment = Alignment.Center) {
            androidx.compose.runtime.CompositionLocalProvider(androidx.compose.material3.LocalContentColor provides tint) { icon() }
        }
        Text(label, fontSize = 11.sp, color = tint, textAlign = TextAlign.Center)
    }
}

@Composable
private fun MoreLikeThis(mediaID: Int, wide: Boolean, onOpen: (Card) -> Unit) {
    var similar by remember(mediaID) { mutableStateOf<List<Card>?>(null) }
    LaunchedEffect(mediaID) { similar = runCatching { Api.similar(mediaID) }.getOrDefault(emptyList()) }
    val list = similar
    when {
        list == null -> Box(Modifier.fillMaxWidth().padding(vertical = 30.dp), contentAlignment = Alignment.Center) { BootSpinner(32.dp, 3.dp) }
        list.isEmpty() -> Text("Nothing like this in the catalog yet", fontSize = 13.sp, color = Palette.faint)
        else -> Grid(list, if (wide) 4 else 3, 12.dp) { other -> PosterCard(other, width = null) { onOpen(other) } }
    }
}

@Composable
fun <T> Grid(items: List<T>, columns: Int, spacing: androidx.compose.ui.unit.Dp, cell: @Composable (T) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(spacing)) {
        items.chunked(columns).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(spacing)) {
                row.forEach { Box(Modifier.weight(1f)) { cell(it) } }
                repeat(columns - row.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Versions(shown: Card, onPlay: (DownloadState) -> Unit, onDownload: (Int) -> Unit) {
    val releases = shown.releases.orEmpty()
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (releases.isEmpty()) Text("No releases known for this title yet", fontSize = 13.sp, color = Palette.faint)
        releases.forEach { release ->
            val d = AppState.downloads[release.id] ?: release.download
            Column(
                Modifier.fillMaxWidth().background(Palette.fill, RoundedCornerShape(10.dp)).pressable {
                    when {
                        d != null && d.isPlayable -> onPlay(d)
                        d?.isWorking == true || d?.isPreparing == true -> {}
                        else -> onDownload(release.id)
                    }
                }.padding(10.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text(release.name, fontSize = 12.sp, color = Color.White, maxLines = 2)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    if (release.id == shown.primaryReleaseID) Tag("BEST", Palette.accent)
                    release.originLabel?.let { OriginTag(it) }
                    if (release.debrid) OriginTag("Debrid")
                    release.tags.forEach { Tag(it) }
                    release.seeders?.let { Tag("$it seeders") }
                    if (d != null && d.state != "removed") {
                        Tag(releaseStatus(d), if (d.isPlayable) Palette.good.copy(alpha = 0.5f) else Color(0xFF4D4D4D))
                    }
                }
            }
        }
    }
}

private fun releaseStatus(d: DownloadState): String = when (val a = TitleAction.of(d)) {
    is TitleAction.Play -> "Downloaded"
    is TitleAction.Preparing -> a.percent?.let { "Preparing ${it.toInt()}%" } ?: "Preparing"
    is TitleAction.Downloading -> a.percent?.let { "Downloading ${it.toInt()}%" } ?: "Downloading"
    TitleAction.Waiting, TitleAction.Queuing -> "Waiting"
    is TitleAction.Failed -> "Failed"
    TitleAction.Download -> d.state
}

@Composable
private fun Tag(text: String, tint: Color = Color(0xFF383838)) {
    Text(text, fontSize = 10.sp, fontWeight = FontWeight.Medium, color = Color.White,
        modifier = Modifier.background(tint, RoundedCornerShape(3.dp)).padding(horizontal = 5.dp, vertical = 2.dp))
}

@Composable
private fun OriginTag(text: String) {
    Text(text, fontSize = 10.sp, fontWeight = FontWeight.Medium, color = Color.White,
        modifier = Modifier.border(1.dp, Color.White.copy(alpha = 0.3f), RoundedCornerShape(3.dp))
            .padding(horizontal = 5.dp, vertical = 2.dp))
}

sealed class EpisodePhase {
    data object Playable : EpisodePhase()
    data object Waiting : EpisodePhase()
    data class Arriving(val percent: Double?) : EpisodePhase()
    data class Preparing(val percent: Double?) : EpisodePhase()
    data class Failed(val error: String) : EpisodePhase()
    data object Downloadable : EpisodePhase()
    data object Unobtainable : EpisodePhase()

    val busy get() = this is Waiting || this is Arriving || this is Preparing
}

fun EpisodeItem.liveDownload(downloads: Map<Int, DownloadState>): DownloadState? {
    val label = "S$season:E$episode"
    for (release in releases.orEmpty()) {
        val fresh = downloads[release.id] ?: continue
        if (fresh.state == "removed") continue
        if (fresh.episodes != null && label !in fresh.episodes) continue
        return fresh
    }
    return if (downloads.isEmpty()) download else null
}

fun EpisodeItem.phase(downloads: Map<Int, DownloadState>): EpisodePhase {
    if (playable) return EpisodePhase.Playable
    liveDownload(downloads)?.let { live ->
        if (live.isWorking) {
            return (TitleAction.of(live) as? TitleAction.Downloading)?.let { EpisodePhase.Arriving(it.percent) } ?: EpisodePhase.Waiting
        }
        (live.prepareError ?: prepareError)?.let { return EpisodePhase.Failed(it) }
        if (live.error == null) return EpisodePhase.Preparing(live.preparePercent)
    }
    if (preparing) return EpisodePhase.Preparing(null)
    prepareError?.let { return EpisodePhase.Failed(it) }
    if (available) return EpisodePhase.Preparing(null)
    return if (releases.isNullOrEmpty()) EpisodePhase.Unobtainable else EpisodePhase.Downloadable
}

fun EpisodeItem.comingOn(): LocalDate? {
    if (available) return null
    val date = airDate?.let { runCatching { LocalDate.parse(it) }.getOrNull() } ?: return null
    return if (date.isAfter(LocalDate.now())) date else null
}

private fun statusOf(detail: SeasonDetail): SeasonStatus? {
    val held = detail.episodes.mapNotNull { e -> if (e.available) e.downloadID?.let { e.id to it } else null }
    val missing = detail.episodes.any { !it.available && it.comingOn() == null }
    if (!missing && held.isNotEmpty()) return SeasonStatus.Downloaded(held)
    if (detail.episodes.any { !it.available }) detail.seasonPack?.let { return SeasonStatus.Offer(it) }
    return null
}

@Composable
fun SeasonMenuLabel(name: String, large: Boolean = false, onClick: () -> Unit) {
    Row(
        Modifier.background(Color.White.copy(alpha = 0.16f), CircleShape).pressable(onClick = onClick)
            .padding(horizontal = if (large) 20.dp else 14.dp, vertical = if (large) 10.dp else 7.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(if (large) 10.dp else 6.dp),
    ) {
        Text(name, fontSize = if (large) 20.sp else 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
        Icon(Icons.Filled.KeyboardArrowDown, null, tint = Color.White, modifier = Modifier.size(18.dp))
    }
}

@Composable
private fun EpisodeList(
    card: Card,
    seasonNumber: Int?,
    onSeason: (Int) -> Unit,
    onStatus: (SeasonStatus?) -> Unit,
    revision: Int,
    onPlay: (PlayRequest) -> Unit,
) {
    val seasons = card.seasons.orEmpty()
    val current = seasons.firstOrNull { it.number == seasonNumber } ?: seasons.firstOrNull()
    var episodes by remember(card.mediaID) { mutableStateOf<List<EpisodeItem>>(emptyList()) }
    var episodesFor by remember(card.mediaID) { mutableStateOf<Int?>(null) }
    var failure by remember { mutableStateOf<String?>(null) }
    var failureFor by remember { mutableStateOf<Int?>(null) }
    var downloadNote by remember { mutableStateOf<String?>(null) }
    var seasonPack by remember { mutableStateOf<SeasonPack?>(null) }
    var queuing by remember { mutableStateOf<Set<Int>>(emptySet()) }
    var removing by remember { mutableStateOf<Set<Int>>(emptySet()) }
    var confirmingDelete by remember { mutableStateOf<EpisodeItem?>(null) }
    var previewing by remember { mutableStateOf<EpisodeItem?>(null) }
    var pickerOpen by remember { mutableStateOf(false) }
    var reload by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()

    fun phaseOf(e: EpisodeItem) = if (e.id in queuing) EpisodePhase.Waiting else e.phase(AppState.downloads)

    suspend fun load() {
        val number = seasonNumber ?: return
        if (episodesFor != number) onStatus(null)
        val result = runCatching { Api.season(card.mediaID, number) }
        if (number != seasonNumber) return
        result.onSuccess { detail ->
            episodes = detail.episodes
            seasonPack = detail.seasonPack
            onStatus(statusOf(detail))
            episodesFor = number
            failure = null
            failureFor = null
        }.onFailure {
            if (episodesFor != number) { failure = it.message; failureFor = number }
        }
    }

    LaunchedEffect(seasonNumber, revision, reload) {
        while (true) {
            load()
            if (episodes.none { phaseOf(it).busy }) break
            delay(5_000)
        }
    }
    LaunchedEffect(episodes.size) {
        val n = Debug.int("previewEpisode") ?: return@LaunchedEffect
        if (previewing == null) previewing = episodes.firstOrNull { it.episode == n }
    }

    val shown = if (episodesFor == seasonNumber) episodes else emptyList()
    val waiting = seasonNumber?.let { episodesFor != it && failureFor != it } ?: seasons.isNotEmpty()

    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        if (seasons.size > 1) {
            Box {
                SeasonMenuLabel(current?.name ?: "Season") { pickerOpen = true }
                DropdownMenu(pickerOpen, onDismissRequest = { pickerOpen = false }, containerColor = Color(0xFF242424)) {
                    seasons.forEach { season ->
                        DropdownMenuItem(
                            text = {
                                Column {
                                    Text(season.name)
                                    if (season.hasFiles) Text("Downloaded", fontSize = 12.sp, color = Palette.dim)
                                }
                            },
                            leadingIcon = { if (season.number == current?.number) Icon(Icons.Filled.Check, null) },
                            onClick = { onSeason(season.number); pickerOpen = false },
                        )
                    }
                }
            }
        } else seasons.firstOrNull()?.let { Text(it.name, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Palette.dim) }

        if (waiting) Box(Modifier.fillMaxWidth().padding(vertical = 30.dp), contentAlignment = Alignment.Center) { BootSpinner(32.dp, 3.dp) }
        downloadNote?.let { Text(it, fontSize = 13.sp, color = Palette.accent) }

        shown.forEach { episode ->
            val phase = phaseOf(episode)
            EpisodeRow(
                episode, phase,
                removing = episode.id in removing,
                seasonPack = seasonPack,
                onOpen = {
                    if (episode.playID != null && episode.playable) onPlay(PlayRequest(episode.playID, card.title))
                    else previewing = episode
                },
                onDelete = { confirmingDelete = episode },
                onDownload = { release ->
                    queuing = queuing + episode.id
                    scope.launch {
                        downloadNote = null
                        runCatching { AppState.download(release.id, if (release.seasonPack) episode.id else null); load() }
                            .onFailure { downloadNote = "Couldn't start the download: ${it.message}" }
                        queuing = queuing - episode.id
                    }
                },
                onSeason = { pack ->
                    scope.launch {
                        downloadNote = null
                        runCatching { AppState.download(pack.id, everything = pack.download != null); load() }
                            .onFailure { downloadNote = "Couldn't start the download: ${it.message}" }
                    }
                },
            )
        }

        if (failure != null && shown.isEmpty() && failureFor == seasonNumber) {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Couldn't load this season.", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                Text(failure.orEmpty(), fontSize = 13.sp, color = Palette.faint, maxLines = 2)
                Pill(false, Modifier.widthIn(min = 120.dp), onClick = { failureFor = null; reload++ }) { PillLabel("Try Again") }
            }
        }
        if (episodes.isEmpty() && failure == null && seasons.isEmpty()) {
            Text("No episode information for this show yet.", fontSize = 13.sp, color = Palette.faint)
        }
    }

    confirmingDelete?.let { episode ->
        AlertDialog(
            onDismissRequest = { confirmingDelete = null },
            title = { Text("Delete S${episode.season}:E${episode.episode}?") },
            text = { Text("This removes the episode from the server and from your library. The rest of the season stays.") },
            confirmButton = {
                TextButton({
                    confirmingDelete = null
                    val download = episode.downloadID ?: return@TextButton
                    removing = removing + episode.id
                    scope.launch {
                        downloadNote = null
                        runCatching { Api.deleteEpisode(episode.id, download); AppState.refreshDownloads(); load() }
                            .onFailure { downloadNote = "Couldn't delete the episode: ${it.message}" }
                        removing = removing - episode.id
                    }
                }) { Text("Delete Episode", color = Color(0xFFFF5A6E)) }
            },
            dismissButton = { TextButton({ confirmingDelete = null }) { Text("Cancel", color = Color.White) } },
            containerColor = Color(0xFF242424),
        )
    }
    previewing?.let { episode ->
        EpisodePreview(card, episode, onClose = { previewing = null; reload++ },
            onPlay = { previewing = null; episode.playID?.let { onPlay(PlayRequest(it, card.title)) } },
            onPlayOther = { other -> previewing = null; other.playID?.let { onPlay(PlayRequest(it, card.title)) } })
    }
}

@Composable
private fun EpisodeRow(
    episode: EpisodeItem,
    phase: EpisodePhase,
    removing: Boolean,
    seasonPack: SeasonPack?,
    onOpen: () -> Unit,
    onDelete: () -> Unit,
    onDownload: (EpisodeRelease) -> Unit,
    onSeason: (SeasonPack) -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    Column(
        Modifier.fillMaxWidth().alpha(if (phase == EpisodePhase.Unobtainable) 0.55f else 1f).pressable(onClick = onOpen).padding(vertical = 6.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.width(116.dp).height(66.dp).clip(RoundedCornerShape(6.dp)), contentAlignment = Alignment.Center) {
                RemoteImage(episode.still, Modifier.fillMaxSize())
                if (phase == EpisodePhase.Playable) {
                    Box(Modifier.size(30.dp).background(Color.Black.copy(alpha = 0.35f), CircleShape)
                        .border(1.2.dp, Color.White.copy(alpha = 0.9f), CircleShape), contentAlignment = Alignment.Center) {
                        Icon(Icons.Filled.PlayArrow, null, tint = Color.White, modifier = Modifier.size(18.dp))
                    }
                } else if (phase == EpisodePhase.Unobtainable) {
                    Icon(if (episode.comingOn() != null) Icons.Outlined.Schedule else Icons.Outlined.CloudOff, null,
                        tint = Color.White.copy(alpha = 0.85f), modifier = Modifier.size(18.dp))
                }
                if (episode.resumePercent > 1 && !episode.watched) {
                    ProgressLine(episode.resumePercent, Modifier.align(Alignment.BottomCenter).fillMaxWidth())
                }
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text("${episode.episode}. ${episode.name}", fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                    color = if (phase == EpisodePhase.Unobtainable) Palette.dim else Color.White, maxLines = 2, overflow = TextOverflow.Ellipsis)
                episode.lengthLabel?.let { Text(it, fontSize = 12.sp, color = Palette.faint) }
                EpisodeStatus(episode, phase)
            }
            Box(Modifier.size(40.dp), contentAlignment = Alignment.Center) {
                when (phase) {
                    EpisodePhase.Playable -> if (episode.downloadID != null) {
                        if (removing) BootSpinner(24.dp, 2.dp)
                        else Icon(Icons.Outlined.Delete, "Delete episode ${episode.episode}", tint = Color.White,
                            modifier = Modifier.size(22.dp).pressable(onClick = onDelete))
                    }
                    EpisodePhase.Waiting -> DownloadRing(null, 30.dp)
                    is EpisodePhase.Arriving -> DownloadRing(phase.percent, 30.dp)
                    is EpisodePhase.Preparing -> DownloadRing(phase.percent, 30.dp)
                    EpisodePhase.Downloadable -> {
                        Box(Modifier.size(40.dp).pressable { menu = true }, contentAlignment = Alignment.Center) {
                            Icon(painterResource(R.drawable.ic_download), "Download episode ${episode.episode}",
                                tint = Color.White, modifier = Modifier.size(20.dp))
                        }
                        DropdownMenu(menu, onDismissRequest = { menu = false }, containerColor = Color(0xFF242424)) {
                            episode.releases.orEmpty().forEach { release ->
                                DropdownMenuItem(
                                    text = {
                                        Column {
                                            Text("Download Episode" + (release.episodeCost?.let { " · $it" } ?: ""))
                                            Text(release.resolution ?: release.name, fontSize = 12.sp, color = Palette.dim)
                                        }
                                    },
                                    onClick = { menu = false; onDownload(release) },
                                )
                            }
                            if (seasonPack != null && seasonPack.completeRequest != true) {
                                DropdownMenuItem(
                                    text = { Text("Download Season" + (seasonPack.sizeGB?.let { " · %.1f GB".format(it) } ?: "")) },
                                    onClick = { menu = false; onSeason(seasonPack) },
                                )
                            }
                        }
                    }
                    else -> {}
                }
            }
        }
        episode.overview?.takeIf { it.isNotEmpty() }?.let {
            Text(it, fontSize = 13.sp, color = Palette.dim, maxLines = 3, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
private fun EpisodeStatus(episode: EpisodeItem, phase: EpisodePhase) {
    val small = 11.sp
    when (phase) {
        EpisodePhase.Waiting -> Text("Waiting for download", fontSize = small, color = Palette.dim)
        is EpisodePhase.Arriving -> Text(phase.percent?.let { "Downloading ${it.toInt()}%" } ?: "Downloading", fontSize = small, color = Palette.dim)
        is EpisodePhase.Preparing -> Text(phase.percent?.let { "Preparing ${it.toInt()}%" } ?: "Preparing", fontSize = small, color = Palette.faint)
        is EpisodePhase.Failed -> Text(phase.error, fontSize = small, color = Palette.accent, maxLines = 1)
        EpisodePhase.Playable -> if (episode.watched) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                Icon(Icons.Filled.CheckCircle, null, tint = Color(0xFF45D469), modifier = Modifier.size(13.dp))
                Text("Watched", fontSize = small, color = Color(0xFF45D469))
            }
        }
        EpisodePhase.Unobtainable -> {
            val date = episode.comingOn()
            Text(date?.let { "Coming ${it.format(DateTimeFormatter.ofPattern("d MMM"))}" } ?: "Not available yet",
                fontSize = small, color = Palette.faint)
        }
        EpisodePhase.Downloadable -> Text("Not downloaded", fontSize = small, color = Palette.faint)
    }
}

@Composable
private fun EpisodePreview(card: Card, episode: EpisodeItem, onClose: () -> Unit, onPlay: () -> Unit,
                           onPlayOther: ((EpisodeItem) -> Unit)? = null, onTitle: ((Card) -> Unit)? = null) {
    var item by remember(episode.id) { mutableStateOf(episode) }
    var tab by remember { mutableStateOf("Episodes") }
    var seasonEpisodes by remember { mutableStateOf<List<EpisodeItem>>(emptyList()) }
    var similar by remember { mutableStateOf<List<Card>?>(null) }
    var pack by remember { mutableStateOf<SeasonPack?>(null) }
    var starting by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf<String?>(null) }
    var about by remember { mutableStateOf<xyz.vibestream.app.api.EpisodeAbout?>(null) }
    val scope = rememberCoroutineScope()
    val phase = item.phase(AppState.downloads)

    suspend fun refresh() {
        runCatching { Api.season(card.mediaID, item.season) }.getOrNull()?.let { detail ->
            pack = detail.seasonPack
            seasonEpisodes = detail.episodes
            detail.episodes.firstOrNull { it.id == item.id }?.let { item = it }
        }
    }
    LaunchedEffect(item.id) {
        about = runCatching { Api.episodeAbout(item.id) }.getOrNull()
        refresh()
        while (true) { delay(4_000); if (item.phase(AppState.downloads).busy || starting) refresh() }
    }

    val bars = systemBarPadding()
    androidx.compose.ui.window.Dialog(onDismissRequest = onClose,
        properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Column(Modifier.fillMaxSize().background(Palette.ground).padding(bars).verticalScroll(rememberScrollState())) {
            Box(Modifier.fillMaxWidth().aspectRatio(16f / 9f)) {
                RemoteImage(item.still ?: card.backdrop, Modifier.fillMaxSize())
                Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color.Black.copy(alpha = 0.55f), Color.Black.copy(alpha = 0.35f), Color.Black.copy(alpha = 0.7f)))))
                Box(Modifier.padding(start = 4.dp, top = 2.dp).size(44.dp).pressable(onClick = onClose), contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.Close, "Close", tint = Color.White)
                }
                Column(Modifier.align(Alignment.Center).padding(horizontal = 40.dp), horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    when (phase) {
                        EpisodePhase.Playable -> Pill(true, Modifier.widthIn(max = 260.dp).fillMaxWidth(),
                            onClick = { onPlayOther?.invoke(item) ?: onPlay() }) {
                            PillLabel("Play") { Icon(Icons.Filled.PlayArrow, null, Modifier.size(24.dp)) }
                        }
                        EpisodePhase.Downloadable -> item.releases?.firstOrNull()?.let { release ->
                            Pill(true, Modifier.widthIn(max = 260.dp).fillMaxWidth(), enabled = !starting, onClick = {
                                starting = true
                                note = null
                                scope.launch {
                                    runCatching { AppState.download(release.id, if (release.seasonPack) item.id else null); refresh() }
                                        .onFailure { note = "Couldn't start the download: ${it.message}" }
                                    starting = false
                                }
                            }) {
                                PillLabel("Download Episode") {
                                    if (starting) DownloadRing(null, 20.dp, false)
                                    else Icon(painterResource(R.drawable.ic_download), null, Modifier.size(20.dp))
                                }
                            }
                            release.episodeCost?.let { Text(it, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Color.White.copy(alpha = 0.85f)) }
                            pack?.takeIf { it.completeRequest != true }?.let { p ->
                                Text("Download Season" + (p.sizeGB?.let { " · %.1f GB".format(it) } ?: ""), fontSize = 13.sp,
                                    fontWeight = FontWeight.SemiBold, color = Color.White,
                                    modifier = Modifier.height(32.dp).background(Color.White.copy(alpha = 0.16f), CircleShape)
                                        .pressable(!starting) {
                                            starting = true
                                            scope.launch {
                                                runCatching { AppState.download(p.id, everything = p.download != null); refresh() }
                                                    .onFailure { note = "Couldn't start the download: ${it.message}" }
                                                starting = false
                                            }
                                        }.padding(horizontal = 14.dp, vertical = 7.dp))
                            }
                        }
                        EpisodePhase.Waiting -> PreviewProgress(null, "Waiting for download")
                        is EpisodePhase.Arriving -> PreviewProgress(phase.percent, phase.percent?.let { "Downloading ${it.toInt()}%" } ?: "Downloading")
                        is EpisodePhase.Preparing -> PreviewProgress(phase.percent, phase.percent?.let { "Preparing ${it.toInt()}%" } ?: "Preparing")
                        is EpisodePhase.Failed -> Text(phase.error, fontSize = 13.sp, color = Color.White)
                        EpisodePhase.Unobtainable -> Text(item.comingOn()?.let { "Coming ${it.format(DateTimeFormatter.ofPattern("d MMMM"))}" }
                            ?: "Not available yet", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                    }
                    note?.let { Text(it, fontSize = 13.sp, color = Color.White) }
                }
            }
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(card.title, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Color.White)
                Text("S${item.season}:E${item.episode} ${item.name}", fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                Text(listOfNotNull(card.year?.toString(), about?.voteAverage?.takeIf { it > 0 }?.let { "%.1f".format(it) },
                    card.genres?.take(2)?.joinToString(", ")).joinToString("  ·  "), fontSize = 13.sp, color = Palette.dim)
                item.overview?.let { Text(it, fontSize = 15.sp, color = Palette.dim, modifier = Modifier.padding(top = 6.dp)) }
                Row(Modifier.padding(top = 14.dp), horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                    listOf("Episodes", "About", "Similar").forEach { option ->
                        Column(Modifier.width(androidx.compose.foundation.layout.IntrinsicSize.Max).pressable { tab = option },
                            verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(option, fontSize = 15.sp, fontWeight = if (tab == option) FontWeight.Bold else FontWeight.Normal,
                                color = if (tab == option) Color.White else Palette.faint)
                            Box(Modifier.fillMaxWidth().height(3.dp).background(if (tab == option) Palette.accent else Color.Transparent))
                        }
                    }
                }
                Column(Modifier.padding(top = 14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    when (tab) {
                        "Episodes" -> seasonEpisodes.forEach { e ->
                            val here = e.id == item.id
                            Row(Modifier.fillMaxWidth().pressable(!here) {
                                if (e.playable && onPlayOther != null) onPlayOther(e) else item = e
                            }, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                Box(Modifier.width(130.dp).aspectRatio(16f / 9f).clip(RoundedCornerShape(6.dp))
                                    .then(if (here) Modifier.border(2.dp, Palette.accent, RoundedCornerShape(6.dp)) else Modifier)) {
                                    RemoteImage(e.still, Modifier.fillMaxSize())
                                }
                                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                    Text("${e.episode}. ${e.name}", fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                                        color = if (here) Palette.dim else Color.White, maxLines = 2)
                                    Text(if (here) "Shown" else e.lengthLabel ?: "", fontSize = 12.sp, color = Palette.faint)
                                }
                            }
                        }
                        "About" -> about?.let { a ->
                            a.directors?.takeIf { it.isNotEmpty() }?.let { AboutRow("Directed by", it.joinToString(", ")) }
                            a.writers?.takeIf { it.isNotEmpty() }?.let { AboutRow("Written by", it.joinToString(", ")) }
                            a.guestStars?.takeIf { it.isNotEmpty() }?.let { g -> AboutRow("Guest stars", g.joinToString(", ") { it.name }) }
                            a.airDate?.let { AboutRow("Aired", it) }
                        } ?: TitleAbout(card, heading = false) { }
                        else -> {
                            LaunchedEffect(card.mediaID) { if (similar == null) similar = runCatching { Api.similar(card.mediaID) }.getOrDefault(emptyList()) }
                            similar?.let { list -> Grid(list, 3, 12.dp) { other -> PosterCard(other, width = null) { onTitle?.invoke(other) } } }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PreviewProgress(percent: Double?, label: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        DownloadRing(percent, 44.dp)
        Text(label, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
    }
}

data class CollectionTarget(val title: String, val personID: Int? = null, val genre: String? = null)

@Composable
fun TitleAbout(card: Card, heading: Boolean = true, onCollection: (CollectionTarget) -> Unit) {
    val facts = card.facts
    val cast = facts?.castAll ?: facts?.cast ?: emptyList()
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        if (heading) Text("About ${card.title}", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
        val crew = facts?.crew
        if (facts?.crewHeading != null && !crew.isNullOrEmpty()) {
            LinkRow(facts.crewHeading, crew.map { it to facts.personIDs?.get(it)?.let { id -> CollectionTarget(it, personID = id) } }, onCollection)
        }
        if (cast.isNotEmpty()) LinkRow("Cast", cast.map { it to facts?.personIDs?.get(it)?.let { id -> CollectionTarget(it, personID = id) } }, onCollection)
        card.genres?.takeIf { it.isNotEmpty() }?.let { genres ->
            LinkRow("Genres", genres.map { it to CollectionTarget(it, genre = it) }, onCollection)
        }
        facts?.keywords?.takeIf { it.isNotEmpty() }?.let { words ->
            AboutRow(if (card.isSeries) "This show is about" else "This movie is about",
                words.joinToString(", ") { w -> w.replaceFirstChar { it.uppercase() } })
        }
        facts?.certification?.takeIf { it.isNotEmpty() }?.let { rating ->
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Maturity Rating:", fontSize = 15.sp, color = Palette.faint)
                Badge(rating, Color.White, Color.White.copy(alpha = 0.6f))
                RATING_MEANING[rating]?.let { Text(it, fontSize = 15.sp, color = Color.White) }
            }
        }
        card.quality?.let { q ->
            AboutRow("Quality", listOfNotNull(q.source, q.codec, q.audio).joinToString("  ·  "))
        }
    }
}

@Composable
private fun AboutRow(label: String, value: String) {
    Text(buildAnnotatedString {
        withStyle(SpanStyle(color = Palette.faint)) { append("$label: ") }
        withStyle(SpanStyle(color = Color.White)) { append(value) }
    }, fontSize = 15.sp)
}

@Suppress("DEPRECATION")
@Composable
private fun LinkRow(label: String, values: List<Pair<String, CollectionTarget?>>, onCollection: (CollectionTarget) -> Unit) {
    val text = buildAnnotatedString {
        withStyle(SpanStyle(color = Palette.faint)) { append("$label: ") }
        values.forEachIndexed { index, (name, target) ->
            if (index > 0) withStyle(SpanStyle(color = Palette.faint)) { append(", ") }
            pushStringAnnotation("target", index.toString())
            withStyle(SpanStyle(color = if (target != null) Color.White else Palette.dim)) { append(name) }
            pop()
        }
    }
    ClickableText(text, style = TextStyle(fontSize = 15.sp)) { offset ->
        text.getStringAnnotations("target", offset, offset).firstOrNull()?.let { a ->
            values[a.item.toInt()].second?.let(onCollection)
        }
    }
}

private val RATING_MEANING = mapOf(
    "G" to "General Audiences", "PG" to "Parental Guidance Suggested",
    "PG-13" to "Parents Strongly Cautioned", "R" to "Restricted",
    "NC-17" to "Adults Only", "TV-Y" to "All Children", "TV-Y7" to "Ages 7+",
    "TV-G" to "General Audience", "TV-PG" to "Parental Guidance Suggested",
    "TV-14" to "Parents Strongly Cautioned", "TV-MA" to "Mature Audience Only",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CollectionSheet(target: CollectionTarget, onOpen: (Card) -> Unit, onClose: () -> Unit) {
    var items by remember(target) { mutableStateOf<List<Card>?>(null) }
    var subtitle by remember(target) { mutableStateOf<String?>(null) }
    LaunchedEffect(target) {
        items = runCatching {
            if (target.personID != null) Api.person(target.personID).also { subtitle = it.knownFor }.items
            else Api.catalog(genre = target.genre)
        }.getOrDefault(emptyList())
    }
    ModalBottomSheet(onDismissRequest = onClose, containerColor = Palette.ground) {
        Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 30.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text(target.title, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Color.White)
            subtitle?.let { Text(it, fontSize = 14.sp, color = Palette.dim) }
            val list = items
            if (list == null) Box(Modifier.fillMaxWidth().padding(30.dp), contentAlignment = Alignment.Center) { BootSpinner(32.dp, 3.dp) }
            else if (list.isEmpty()) Text("Nothing in the catalog yet", fontSize = 13.sp, color = Palette.faint)
            else Grid(list, 3, 12.dp) { card -> PosterCard(card, width = null) { onOpen(card) } }
        }
    }
}
