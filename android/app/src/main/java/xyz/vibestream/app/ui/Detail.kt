package xyz.vibestream.app.ui

import androidx.compose.foundation.background
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.ui.layout.layout
import xyz.vibestream.app.PlayerActivity
import xyz.vibestream.app.PlayerMode
import xyz.vibestream.app.PlayerModel
import xyz.vibestream.app.PlayerScreen
import xyz.vibestream.app.PlayerSession
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.zIndex
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
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

// Versions always last, as on iOS, the TV and the web: the raw releases, for
// the curious, after everything about the title itself.
private enum class DetailTab(val label: String) { Episodes("Episodes"), More("Similar"), About("About"), Versions("Versions") }

sealed class SeasonStatus {
    data class Offer(val pack: SeasonPack) : SeasonStatus()
    data class Downloaded(val held: List<Pair<Int, Int>>) : SeasonStatus()
}

/*
 * The title sheet: artwork, title and meta, the one big button, the
 * synopsis, the row of icon actions, then the tabs. The same order and the
 * same behaviour as the iOS DetailView.
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun DetailView(card: Card, nav: Navigator, autoplay: PlayRequest? = null, onClose: () -> Unit) {
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
    // The whole title could not be fetched yet, and is being asked again.
    var unreachable by remember { mutableStateOf(false) }
    // Cancelled before the server said what to cancel.
    var pendingCancel by remember { mutableStateOf(false) }
    // Playing, in this page's own picture. Play turns the artwork into the player and the page
    // stays as it was under it: one page for a title, not a title page and a player's page saying
    // the same things.
    var playing by remember(card.mediaID) { mutableStateOf(autoplay) }
    var session by remember(card.mediaID) { mutableStateOf<PlayerModel?>(null) }
    /** The whole screen has the playback. */
    var handedAway by remember(card.mediaID) { mutableStateOf(false) }
    /** The episode last on, which after autoplay is not the one pressed. */
    var lastPlayed by remember(card.mediaID) { mutableStateOf(autoplay) }
    val activity = androidx.compose.ui.platform.LocalContext.current.findActivity()
    // Legible against whatever the artwork puts behind the close button.
    var closeTint by remember(card.mediaID) { mutableStateOf(Color.White) }
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
        // The whole title, asked for again until it comes.
        var wait = 1_000L
        while (full == null) {
            full = runCatching { Api.media(card.mediaID) }.getOrNull()
            unreachable = full == null
            if (full == null) { delay(wait); wait = minOf(wait * 2, 8_000L) }
        }
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

    fun play(request: PlayRequest) {
        if (request.playID == playing?.playID) return
        session?.stop()
        session = null
        lastPlayed = request
        playing = request
        request.season?.let { seasonNumber = it }
    }
    fun playNextUp(next: NextUp) = play(PlayRequest(next.playID, shown.title, season = next.season, episode = next.number))

    /*
     * Back from playing: the page reads itself again, because the episode
     * just watched, the Play button's next episode and Resume Watching have
     * all moved, and the season list follows the episode last on.
     */
    fun afterPlayback() {
        lastPlayed?.season?.let { seasonNumber = it }
        revision++
        scope.launch {
            runCatching { Api.media(card.mediaID) }.getOrNull()?.let { full = it }
            AppState.loadFeed()
        }
    }
    fun stopPlaying() {
        session?.stop()
        session = null
        playing = null
        afterPlayback()
    }

    // The playback, made once there is something to play here.
    LaunchedEffect(playing, handedAway) {
        val request = playing ?: return@LaunchedEffect
        if (session == null && !handedAway && activity != null) session = PlayerModel(activity, request)
    }
    // Given back by the whole screen: still playing, or ended there.
    LaunchedEffect(PlayerSession.back) {
        val back = PlayerSession.back ?: return@LaunchedEffect
        if (!handedAway) return@LaunchedEffect
        PlayerSession.back = null
        lastPlayed = back.request
        if (back.model != null) {
            session = back.model
            playing = back.request
            back.request.season?.let { seasonNumber = it }
            handedAway = false
        } else {
            handedAway = false
            session = null
            playing = null
            afterPlayback()
        }
    }
    // The page closed: the film with it, unless the whole screen has it.
    val sessionNow by androidx.compose.runtime.rememberUpdatedState(session)
    val awayNow by androidx.compose.runtime.rememberUpdatedState(handedAway)
    androidx.compose.runtime.DisposableEffect(card.mediaID) { onDispose { if (!awayNow) sessionNow?.stop() } }

    fun startDownload(torrent: Int?) {
        if (torrent == null || queuing) return
        queuing = true
        scope.launch {
            runCatching {
                val started = AppState.download(torrent)
                // Cancelled while the request was in flight: there was no id
                // to cancel then, and there is one now.
                if (pendingCancel) runCatching { AppState.cancel(started.id, started.torrentID) }
                    .onFailure { Toasts.error("Couldn't stop the download. Try again.") }
            }.onFailure { Toasts.error(it.said()) }
            pendingCancel = false
            queuing = false
        }
    }

    fun press() {
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

    // Watchlist, the two ratings, Play on and, for a show, Download Season.
    @Composable
    fun ActionRow() {
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
            // What Play would play here, to send to another device instead.
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
                                scope.launch {
                                    runCatching { AppState.download(pack.id, everything = pack.download != null); revision++ }
                                        .onFailure { Toasts.error(it.said()) }
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
    }

    // The title's one button, on its picture: see HeroDisc.
    val hero: Hero? = when {
        shown.isSeries && shown.nextUp != null -> shown.nextUp!!.let { next ->
            Hero(HeroKind.Play, next.label, if (next.isResume) "Resume ${next.label}" else "Play ${next.label}") { playNextUp(next) }
        }
        // A show all here, with nothing next: its episodes are below.
        shown.isSeries && isHere -> null
        else -> when (action) {
            is TitleAction.Play -> Hero(HeroKind.Play, null, "Play") { press() }
            TitleAction.Download -> Hero(HeroKind.Download, null, "Download") { press() }
            is TitleAction.Failed -> Hero(HeroKind.Retry, "Try again", "Try again") { press() }
            TitleAction.Queuing, TitleAction.Waiting -> Hero(HeroKind.Busy(null), null, "Waiting for download") { press() }
            is TitleAction.Downloading -> Hero(HeroKind.Busy(action.percent), null, "Downloading") { press() }
            is TitleAction.Preparing -> Hero(HeroKind.Busy(action.percent), "Preparing", "Preparing") { press() }
        }
    }
    val pad = if (wide) 28.dp else 16.dp

    Box(Modifier.fillMaxSize().background(Palette.ground)) {
        Column(Modifier.fillMaxSize()) {
            // The picture, pinned while the page scrolls under it: the
            // artwork, and the player in its place once it plays.
            val model = session
            if (playing != null) Box(Modifier.fillMaxWidth().aspectRatio(16f / 9f).background(Color.Black)) {
                // The player reads the activity from its context, which in a
                // sheet's window is a wrapper around it.
                if (model != null && !handedAway && activity != null) androidx.compose.runtime.key(model) {
                    androidx.compose.runtime.CompositionLocalProvider(androidx.compose.ui.platform.LocalContext provides activity) {
                    PlayerScreen(
                        model,
                        // The next episode, here: a new playback in the same picture.
                        onNext = { next ->
                            session = null
                            lastPlayed = next
                            playing = next
                            next.season?.let { seasonNumber = it }
                        },
                        onClose = { stopPlaying() },
                        onPip = {},
                        mode = PlayerMode.Inline,
                        onClosePage = onClose,
                        onFullScreen = { sideways ->
                            val request = lastPlayed ?: model.request
                            if (activity != null && !handedAway) {
                                handedAway = true
                                PlayerSession.handed = model
                                activity.startActivity(PlayerActivity.forPage(activity, model.request.copy(
                                    season = request.season, episode = request.episode), sideways))
                                @Suppress("DEPRECATION") activity.overridePendingTransition(0, 0)
                            }
                        },
                    )
                    }
                }
            } else Box(Modifier.fillMaxWidth().aspectRatio(16f / 9f).clipToBounds()) {
                // Pinned to the top, as on iOS: a title with no backdrop shows
                // its poster here, and cropped about the middle that cut
                // everyone's head off.
                RemoteImage(shown.backdrop ?: shown.poster, Modifier.fillMaxSize(), alignment = Alignment.TopCenter,
                    onImage = { image -> scope.launch { closeTint = withContext(Dispatchers.Default) { cornerTint(image) } } })
                Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(90.dp)
                    .background(Brush.verticalGradient(listOf(Color.Transparent, Palette.ground))))
                hero?.let { HeroDisc(it, wide) }
            }
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 30.dp + systemBarPadding().calculateBottomPadding())) {
                item {
                    Column(Modifier.padding(start = pad, end = pad, top = 4.dp, bottom = 14.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                        Text(shown.title, fontSize = if (wide) 30.sp else 24.sp, fontWeight = FontWeight.Bold, color = Color.White)
                        MetaRow(shown)
                        ActionRow()
                    }
                }
                // The tabs stay pinned once the page has scrolled up to them,
                // so another episode or Similar is always a tap away; what
                // scrolls under fades into them rather than meeting an edge.
                stickyHeader {
                    val tabs = if (shown.isSeries) DetailTab.entries.toList() else listOf(DetailTab.More, DetailTab.About, DetailTab.Versions)
                    Row(
                        Modifier.fillMaxWidth().zIndex(1f).drawBehind {
                            drawRect(Brush.verticalGradient(listOf(Palette.ground, Palette.ground.copy(alpha = 0f)),
                                startY = size.height, endY = size.height + 22.dp.toPx()),
                                topLeft = androidx.compose.ui.geometry.Offset(0f, size.height),
                                size = androidx.compose.ui.geometry.Size(size.width, 22.dp.toPx()))
                        }.background(Palette.ground).padding(start = pad, end = pad, top = 14.dp, bottom = 4.dp),
                        horizontalArrangement = Arrangement.spacedBy(20.dp),
                    ) {
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
                }
                item {
                    Box(Modifier.padding(start = pad, end = pad, top = 20.dp)) {
                        when (tab) {
                            DetailTab.Episodes -> if (full == null) {
                                // Not "no episodes" before the title has even said.
                                Row(Modifier.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                    BootSpinner(18.dp, 2.5.dp)
                                    if (unreachable) Text("Can't reach the server. Trying again.", fontSize = 13.sp, color = Palette.faint)
                                }
                            } else EpisodeList(shown, seasonNumber, { seasonNumber = it }, { seasonStatus = it }, revision,
                                playingID = playing?.playID) { play(it) }
                            DetailTab.More -> MoreLikeThis(card.mediaID, wide) { nav.open(it) }
                            DetailTab.Versions -> Versions(shown, onPlay = { d ->
                                if (shown.isSeries) shown.nextUp?.let(::playNextUp) ?: run { tab = DetailTab.Episodes }
                                else play(PlayRequest(d.id.toString(), shown.title))
                            }, onDownload = { startDownload(it) })
                            DetailTab.About -> TitleAbout(shown, overview = true) { collection = it }
                        }
                    }
                }
            }
        }

        // A bare glyph, not a capsule: with no plate behind it, it takes its colour from the corner
        // it covers and carries a soft halo of the opposite one, so it reads over a busy poster as
        // well as a plain one. While the picture plays, the strip's X is this page's.
        val tint by animateColorAsState(closeTint, label = "close")
        if (playing == null) Box(Modifier.align(Alignment.TopEnd).padding(end = 4.dp, top = 6.dp).size(44.dp).pressable(onClick = onClose),
            contentAlignment = Alignment.Center) {
            Icon(Icons.Filled.Close, "Close", tint = tint,
                modifier = Modifier.size(22.dp).shadow(3.dp, CircleShape,
                    ambientColor = if (tint == Color.Black) Color.White else Color.Black,
                    spotColor = if (tint == Color.Black) Color.White else Color.Black))
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
                    // Still queuing: no row yet, so the decision waits for the answer.
                    val d = live
                    if (d == null) pendingCancel = true
                    else scope.launch { runCatching { AppState.cancel(d.id, d.torrentID) }.onFailure { Toasts.error("Couldn't stop the download. Try again.") } }
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
                    scope.launch {
                        runCatching { held.forEach { (episode, download) -> Api.deleteEpisode(episode, download) } }
                            .onFailure { Toasts.error("Couldn't delete the whole season. Try again.") }
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

// One line of what the title is: score, year, how long (a show's seasons), its rating, and the
// picture's 4K and HDR. Never wrapped: where it does not fit, the badges go before anything breaks
// a line. "Complete" and the audio badge went, as on iOS:
@Composable
private fun MetaRow(shown: Card) {
    FirstThatFits({ MetaLine(shown, badges = true) }, { MetaLine(shown, badges = false) })
}

@Composable
private fun MetaLine(shown: Card, badges: Boolean) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        shown.voteAverage?.takeIf { it > 0 }?.let {
            Text("%.1f".format(it), fontSize = 12.sp, fontWeight = FontWeight.Bold, color = Palette.good, maxLines = 1)
        }
        shown.year?.let { Text("$it", fontSize = 13.sp, color = Palette.dim, maxLines = 1) }
        // A show's runtime is one episode's: it says how many seasons instead.
        val seasons = shown.seasons?.count { it.number > 0 } ?: 0
        if (shown.isSeries && seasons > 0) {
            Text(if (seasons == 1) "1 Season" else "$seasons Seasons", fontSize = 13.sp, color = Palette.dim, maxLines = 1)
        } else if (!shown.isSeries) {
            shown.runtime?.takeIf { it > 0 }?.let { r ->
                Text(if (r >= 60) (if (r % 60 == 0) "${r / 60}h" else "${r / 60}h ${r % 60}m") else "${r}m",
                    fontSize = 13.sp, color = Palette.dim, maxLines = 1)
            }
        }
        shown.facts?.certification?.takeIf { it.isNotEmpty() }?.let {
            Badge(it, Color.White, Color.White.copy(alpha = 0.6f))
        }
        // The picture's 4K and HDR; the sound is in Versions.
        if (badges) {
            if (shown.quality?.resolution == "2160p") Badge("4K", Palette.dim, Palette.faint)
            shown.quality?.hdr?.let { Badge(it, Palette.dim, Palette.faint) }
        }
    }
}

@Composable
fun Badge(text: String, color: Color, border: Color, modifier: Modifier = Modifier) {
    Text(text, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = color,
        modifier = modifier.border(1.dp, border, RoundedCornerShape(3.dp)).padding(horizontal = 5.dp, vertical = 2.dp))
}

// The title's one button, on its picture, as on iOS and the web: the play triangle when something
// is here (a show's next episode, named under it), the download arrow when not, a ring filling
// while it arrives, and Try again after a failure. A press on the ring asks whether to cancel.
private sealed class HeroKind {
    data object Play : HeroKind()
    data object Download : HeroKind()
    data object Retry : HeroKind()
    data class Busy(val percent: Double?) : HeroKind()
}

private class Hero(val kind: HeroKind, val caption: String?, val label: String, val press: () -> Unit)

@Composable
private fun HeroDisc(hero: Hero, wide: Boolean) {
    val size = if (wide) 88.dp else 72.dp
    // The whole picture answers; the disc says so.
    Column(
        Modifier.fillMaxSize().clickable(remember { androidx.compose.foundation.interaction.MutableInteractionSource() }, null, onClick = hero.press)
            .semantics { contentDescription = hero.label },
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(10.dp, Alignment.CenterVertically),
    ) {
        Box(Modifier.size(size).shadow(12.dp, CircleShape), contentAlignment = Alignment.Center) {
            Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.45f), CircleShape))
            when (val kind = hero.kind) {
                is HeroKind.Busy -> {
                    DownloadRing(kind.percent, size, showsLabel = false)
                    kind.percent?.let {
                        Text("${it.toInt()}%", fontSize = (size.value * 0.22f).sp, fontWeight = FontWeight.Bold, color = Color.White)
                    }
                }
                else -> {
                    Box(Modifier.fillMaxSize().border(2.dp, Color.White.copy(alpha = 0.9f), CircleShape))
                    val glyph = Modifier.size(size * 0.46f)
                    when (kind) {
                        // Material's triangle already sits right of the middle of
                        // its box, so it looks centred in the circle as it is.
                        HeroKind.Play -> Icon(Icons.Filled.PlayArrow, null, glyph, tint = Color.White)
                        HeroKind.Retry -> Icon(Icons.Filled.Refresh, null, glyph, tint = Color.White)
                        else -> Icon(painterResource(R.drawable.ic_download), null, Modifier.size(size * 0.36f), tint = Color.White)
                    }
                }
            }
            if (hero.kind == HeroKind.Retry) ErrorBadge(22.dp, Modifier.align(Alignment.TopEnd).offset(x = 2.dp, y = (-2).dp))
        }
        hero.caption?.let {
            Text(it, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
                modifier = Modifier.background(Color.Black.copy(alpha = 0.55f), CircleShape).padding(horizontal = 10.dp, vertical = 4.dp))
        }
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

private const val UNPREPARED = "Arrived, but could not be made playable."

fun EpisodeItem.phase(downloads: Map<Int, DownloadState>): EpisodePhase {
    if (playable) return EpisodePhase.Playable
    liveDownload(downloads)?.let { live ->
        if (live.isWorking) {
            // Read here rather than through TitleAction.of, which answers Play
            // first: a season pack fetching one more episode is still playable
            // for the ones it has, and this episode sat on Waiting throughout.
            if (live.state == "downloading") return EpisodePhase.Arriving(live.percent.takeIf { it >= 1 })
            return EpisodePhase.Waiting
        }
        // Sentences for the screen, never the raw error.
        if (live.state == "error") return EpisodePhase.Failed(live.errorMessage ?: "The download could not start.")
        if (live.prepareError != null || prepareError != null) return EpisodePhase.Failed(UNPREPARED)
        if (live.error == null) return EpisodePhase.Preparing(live.preparePercent)
    }
    if (preparing) return EpisodePhase.Preparing(null)
    if (prepareError != null) return EpisodePhase.Failed(UNPREPARED)
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
    playingID: String? = null,
    onPlay: (PlayRequest) -> Unit,
) {
    val seasons = card.seasons.orEmpty()
    val current = seasons.firstOrNull { it.number == seasonNumber } ?: seasons.firstOrNull()
    var episodes by remember(card.mediaID) { mutableStateOf<List<EpisodeItem>>(emptyList()) }
    var episodesFor by remember(card.mediaID) { mutableStateOf<Int?>(null) }
    var failure by remember { mutableStateOf<String?>(null) }
    var failureFor by remember { mutableStateOf<Int?>(null) }
    var seasonPack by remember { mutableStateOf<SeasonPack?>(null) }
    var queuing by remember { mutableStateOf<Set<Int>>(emptySet()) }
    var removing by remember { mutableStateOf<Set<Int>>(emptySet()) }
    var confirmingDelete by remember { mutableStateOf<EpisodeItem?>(null) }
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

        shown.forEach { episode ->
            val phase = phaseOf(episode)
            val now = playingID != null && episode.playID == playingID
            EpisodeRow(
                episode, phase,
                playing = now,
                removing = episode.id in removing,
                seasonPack = seasonPack,
                // Played when it is here, fetched when it is not, its progress then on the row.
                onOpen = {
                    if (now) Unit
                    else if (episode.playID != null && episode.playable) {
                        onPlay(PlayRequest(episode.playID, card.title, season = episode.season, episode = episode.episode))
                    } else if (phase == EpisodePhase.Downloadable) episode.releases?.firstOrNull()?.let { release ->
                        queuing = queuing + episode.id
                        scope.launch {
                            runCatching { AppState.download(release.id, if (release.seasonPack) episode.id else null); load() }
                                .onFailure { Toasts.error(it.said()) }
                            queuing = queuing - episode.id
                        }
                    }
                },
                onDelete = { confirmingDelete = episode },
                onDownload = { release ->
                    queuing = queuing + episode.id
                    scope.launch {
                        runCatching { AppState.download(release.id, if (release.seasonPack) episode.id else null); load() }
                            .onFailure { Toasts.error(it.said()) }
                        queuing = queuing - episode.id
                    }
                },
                onSeason = { pack ->
                    scope.launch {
                        runCatching { AppState.download(pack.id, everything = pack.download != null); load() }
                            .onFailure { Toasts.error(it.said()) }
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
                        runCatching { Api.deleteEpisode(episode.id, download); AppState.refreshDownloads(); load() }
                            .onFailure { Toasts.error("Couldn't delete the episode. Try again.") }
                        removing = removing - episode.id
                    }
                }) { Text("Delete Episode", color = Color(0xFFFF5A6E)) }
            },
            dismissButton = { TextButton({ confirmingDelete = null }) { Text("Cancel", color = Color.White) } },
            containerColor = Color(0xFF242424),
        )
    }
}

@Composable
private fun EpisodeRow(
    episode: EpisodeItem,
    phase: EpisodePhase,
    playing: Boolean = false,
    removing: Boolean,
    seasonPack: SeasonPack?,
    onOpen: () -> Unit,
    onDelete: () -> Unit,
    onDownload: (EpisodeRelease) -> Unit,
    onSeason: (SeasonPack) -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    Column(
        // The one in the picture above: a quiet card behind it, the word
        // "Playing" the only colour.
        Modifier.fillMaxWidth().alpha(if (phase == EpisodePhase.Unobtainable) 0.55f else 1f)
            .then(if (playing) Modifier.bleed(8.dp).background(Color.White.copy(alpha = 0.07f), RoundedCornerShape(12.dp))
                .padding(horizontal = 8.dp) else Modifier)
            .pressable(onClick = onOpen).padding(vertical = 6.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.width(116.dp).height(66.dp).clip(RoundedCornerShape(6.dp)), contentAlignment = Alignment.Center) {
                RemoteImage(episode.still, Modifier.fillMaxSize())
                if (playing) {
                    Box(Modifier.align(Alignment.BottomStart).padding(5.dp).background(Color.Black.copy(alpha = 0.6f), CircleShape)
                        .padding(horizontal = 7.dp, vertical = 4.dp)) {
                        Icon(Icons.Filled.GraphicEq, "Playing", tint = Color.White, modifier = Modifier.size(13.dp))
                    }
                } else if (phase == EpisodePhase.Playable) {
                    Box(Modifier.size(30.dp).background(Color.Black.copy(alpha = 0.35f), CircleShape)
                        .border(1.2.dp, Color.White.copy(alpha = 0.9f), CircleShape), contentAlignment = Alignment.Center) {
                        Icon(Icons.Filled.PlayArrow, null, tint = Color.White, modifier = Modifier.size(18.dp))
                    }
                } else if (phase == EpisodePhase.Downloadable) {
                    // A tap fetches it.
                    Box(Modifier.size(30.dp).background(Color.Black.copy(alpha = 0.35f), CircleShape)
                        .border(1.2.dp, Color.White.copy(alpha = 0.9f), CircleShape), contentAlignment = Alignment.Center) {
                        Icon(painterResource(R.drawable.ic_download), null, tint = Color.White, modifier = Modifier.size(14.dp))
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
                if (playing) Text("Playing", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Palette.accent)
                else EpisodeStatus(episode, phase)
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
        is EpisodePhase.Failed -> Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            ErrorBadge(12.dp)
            Text(phase.error, fontSize = small, color = Palette.danger, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
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

// ------------------------------------------------------------------ about

/** A name or genre on the About tab opens what the catalog has of it. */
data class CollectionTarget(val title: String, val personID: Int? = null, val genre: String? = null)

@Composable
fun TitleAbout(card: Card, heading: Boolean = true, overview: Boolean = false, onCollection: (CollectionTarget) -> Unit) {
    val facts = card.facts
    val cast = facts?.castAll ?: facts?.cast ?: emptyList()
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        if (heading) Text("About ${card.title}", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
        // What it is about, under the heading: the title page keeps it here
        // rather than between its buttons, under a picture that may be playing.
        if (overview) card.overview?.takeIf { it.isNotEmpty() }?.let { Text(it, fontSize = 15.sp, color = Palette.dim) }
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
    var failure by remember(target) { mutableStateOf<String?>(null) }
    LaunchedEffect(target) {
        runCatching {
            if (target.personID != null) Api.person(target.personID).also { page ->
                // TMDB's department, said as what the person is.
                subtitle = page.knownFor?.let { if (it == "Acting") "Actor" else it }
            }.items
            else Api.catalog(genre = target.genre)
        }.onSuccess { items = it }.onFailure { failure = it.said(); items = emptyList() }
    }
    ModalBottomSheet(onDismissRequest = onClose, containerColor = Palette.ground) {
        Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 30.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text(target.title, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Color.White)
            subtitle?.let { Text(it, fontSize = 14.sp, color = Palette.dim) }
            val list = items
            if (list == null) Box(Modifier.fillMaxWidth().padding(30.dp), contentAlignment = Alignment.Center) { BootSpinner(32.dp, 3.dp) }
            else if (list.isEmpty()) Text(failure ?: "Nothing in the catalog yet", fontSize = 13.sp, color = Palette.faint)
            else Grid(list, if (isWide()) 5 else 3, 12.dp) { card -> PosterCard(card, width = null) { onOpen(card) } }
        }
    }
}

/** Wider than the column by `x` on each side, for a card behind a row whose
 *  contents stay lined up with the rest. */
private fun Modifier.bleed(x: androidx.compose.ui.unit.Dp) = layout { measurable, constraints ->
    val px = x.roundToPx()
    val placeable = measurable.measure(constraints.copy(
        minWidth = constraints.minWidth + 2 * px,
        maxWidth = if (constraints.hasBoundedWidth) constraints.maxWidth + 2 * px else constraints.maxWidth))
    layout(placeable.width - 2 * px, placeable.height) { placeable.place(-px, 0) }
}
