package xyz.vibestream.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.LibraryAdd
import androidx.compose.material.icons.outlined.PlayCircle
import androidx.compose.material.icons.outlined.VideoLibrary
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import xyz.vibestream.app.AppState
import xyz.vibestream.app.Debug
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.Card
import xyz.vibestream.app.api.Clip
import xyz.vibestream.app.api.PlayRequest

@Composable
fun LibraryView(nav: Navigator) {
    var showingMyList by remember { mutableStateOf(false) }
    var playingClip by remember { mutableStateOf<Clip?>(null) }
    var framingClip by remember { mutableStateOf<Clip?>(null) }
    val width = posterWidth()
    val rows = AppState.rows
    val continueRow = rows.firstOrNull { it.id == "continue" }?.items.orEmpty()
    val myList = rows.firstOrNull { it.id == "mylist" }?.items.orEmpty()
    val library = rows.firstOrNull { it.id == "library" }?.items.orEmpty()
    val watchAgain = AppState.library?.rows?.firstOrNull { it.id == "watchagain" }?.items.orEmpty()
    val arriving = AppState.downloads.values.filter { it.isWorking || it.isPreparing }.sortedBy { it.id }

    LaunchedEffect(myList.isEmpty()) { if (myList.isNotEmpty() && Debug.has("myList")) showingMyList = true }

    LaunchedEffect(showingMyList) { Pushed.tabs["mine"] = showingMyList }
    if (showingMyList) {
        BackHandler { showingMyList = false }
        MyListView(nav) { showingMyList = false }
        return
    }

    val list = rememberLazyListState()
    ReportScrolledUnder(list)
    LazyColumn(state = list, verticalArrangement = Arrangement.spacedBy(24.dp), contentPadding = PaddingValues(top = LocalTopClearance.current, bottom = 24.dp + TabBarClearance)) {
        if (continueRow.isNotEmpty()) item {
            CardRow("Resume Watching", continueRow) { card ->
                ContinueCard(card, width * 1.2f, onPlay = {
                    card.resumePlayID?.let { nav.play(PlayRequest(it, card.title)) } ?: nav.open(card)
                }, onInfo = { nav.open(card) })
            }
        }
        if (myList.isNotEmpty()) item {
            CardRow("Watchlist", myList, trailing = {
                Row(Modifier.pressable { showingMyList = true }, verticalAlignment = Alignment.CenterVertically) {
                    Text("See All", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Color.White, modifier = Modifier.size(18.dp))
                }
            }) { card -> PosterCard(card, width) { nav.open(card) } }
        }
        if (watchAgain.isNotEmpty()) item {
            CardRow("Watch It Again", watchAgain) { card -> PosterCard(card, width) { nav.open(card) } }
        }
        if (AppState.clips.isNotEmpty()) item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Clips you've saved", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = Color.White,
                    modifier = Modifier.padding(horizontal = 16.dp))
                LazyRow(horizontalArrangement = Arrangement.spacedBy(Metrics.rowSpacing), contentPadding = PaddingValues(horizontal = 16.dp)) {
                    items(AppState.clips, key = { it.id }) { clip ->
                        ClipCard(clip, width * 1.6f, onPlay = { playingClip = clip }, onVertical = { framingClip = clip },
                            onDelete = { AppState.deleteClip(clip) })
                    }
                }
            }
        }
        if (library.isNotEmpty()) item {
            CardRow("Ready to Play", library) { card -> PosterCard(card, width) { nav.open(card) } }
        }
        if (arriving.isNotEmpty()) item {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("On its way to the server", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = Color.White,
                    modifier = Modifier.padding(horizontal = 16.dp))
                arriving.forEach { d ->
                    val title = AppState.rows.flatMap { it.items }.firstOrNull { c ->
                        c.primaryReleaseID == d.torrentID || c.releases.orEmpty().any { it.id == d.torrentID }
                    }?.title ?: "Download"
                    Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        DownloadRing(if (d.isWorking && d.percent >= 1) d.percent else null, 34.dp)
                        Column {
                            Text(title, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White, maxLines = 1)
                            Text(if (d.isPreparing) "Preparing" else if (d.percent >= 1) "Downloading ${d.percent.toInt()}%" else "Waiting",
                                fontSize = 12.sp, color = Palette.faint)
                        }
                    }
                }
            }
        }
        if (continueRow.isEmpty() && myList.isEmpty() && watchAgain.isEmpty() && library.isEmpty() && arriving.isEmpty() && AppState.clips.isEmpty()) {
            item {
                if (AppState.loading && AppState.feed == null) {
                    Box(Modifier.fillMaxWidth().padding(top = 80.dp), contentAlignment = Alignment.Center) { BootSpinner() }
                } else {
                    Column(Modifier.fillMaxWidth().padding(top = 80.dp, start = 32.dp, end = 32.dp),
                        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Icon(Icons.Outlined.VideoLibrary, null, tint = Palette.faint, modifier = Modifier.size(36.dp))
                        Text("Nothing here yet", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                        Text("Titles you download, and anything you start watching, show up here.", fontSize = 15.sp,
                            color = Palette.dim, textAlign = TextAlign.Center)
                    }
                }
            }
        }
    }

    playingClip?.let { clip -> ClipPlayer(clip) { playingClip = null } }
    framingClip?.let { clip -> VerticalEditor(clip) { framingClip = null } }
    LaunchedEffect(AppState.clips) {
        Debug.int("vertical")?.let { id -> AppState.clips.firstOrNull { it.id == id }?.let { framingClip = it } }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ClipCard(clip: Clip, width: Dp, onPlay: () -> Unit, onVertical: () -> Unit, onDelete: () -> Unit) {
    var thumb by remember { mutableStateOf<String?>(null) }
    var menu by remember { mutableStateOf(false) }
    LaunchedEffect(clip.id) { thumb = runCatching { Api.url(clip.thumb) }.getOrNull() }
    Column(Modifier.width(width).combinedClickable(onClick = onPlay, onLongClick = { menu = true }),
        verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Box(Modifier.width(width).height(width * 9 / 16).clip(RoundedCornerShape(6.dp)).background(Color.Black)) {
            RemoteImage(thumb, Modifier.fillMaxSize())
            Box(Modifier.align(Alignment.Center).size(38.dp).background(Color.Black.copy(alpha = 0.45f), CircleShape)
                .border(1.5.dp, Color.White.copy(alpha = 0.85f), CircleShape), contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.PlayArrow, null, tint = Color.White, modifier = Modifier.size(22.dp))
            }
            val total = clip.duration.toInt()
            Text("%d:%02d".format(total / 60, total % 60), fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
                modifier = Modifier.align(Alignment.BottomEnd).padding(6.dp)
                    .background(Color.Black.copy(alpha = 0.7f), CircleShape).padding(horizontal = 6.dp, vertical = 3.dp))
        }
        Text(clip.title, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White, maxLines = 1)
        clip.subtitle?.let { Text(it, fontSize = 12.sp, color = Palette.dim, maxLines = 1) }
        DropdownMenu(menu, onDismissRequest = { menu = false }, containerColor = Color(0xFF242424)) {
            DropdownMenuItem(text = { Text("Make Vertical") }, onClick = { menu = false; onVertical() })
            DropdownMenuItem(text = { Text("Delete Clip", color = Color(0xFFFF5A6E)) }, onClick = { menu = false; onDelete() })
        }
    }
}

@Composable
private fun ClipPlayer(clip: Clip, onClose: () -> Unit) {
    val context = LocalContext.current
    var url by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(clip.id) { url = runCatching { Api.url(clip.video) }.getOrNull() }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            url?.let { source ->
                val player = remember(source) {
                    ExoPlayer.Builder(context).build().apply {
                        setMediaItem(MediaItem.fromUri(source)); prepare(); playWhenReady = true
                    }
                }
                DisposableEffect(player) { onDispose { player.release() } }
                AndroidView({ PlayerView(it).apply { this.player = player } }, Modifier.fillMaxSize())
            }
            Box(Modifier.align(Alignment.TopStart).statusBarsPadding().padding(8.dp).size(44.dp).pressable(onClick = onClose),
                contentAlignment = Alignment.Center) { Icon(Icons.Filled.Close, "Close", tint = Color.White) }
        }
    }
}

@Composable
private fun MyListView(nav: Navigator, onBack: () -> Unit) {
    var items by remember { mutableStateOf<List<Card>>(emptyList()) }
    var loaded by remember { mutableStateOf(false) }
    var kind by remember { mutableStateOf<String?>(null) }
    var started by remember { mutableStateOf<Boolean?>(null) }
    var sort by remember { mutableStateOf("Recently Added") }
    var sortOpen by remember { mutableStateOf(false) }
    val wide = isWide()

    LaunchedEffect(AppState.myList.size) {
        runCatching { Api.myList() }.getOrNull()?.let { items = it }
        loaded = true
    }
    val filtered = items.filter { c ->
        c.mediaID in AppState.myList && (kind == null || c.mediaType == kind) && (started == null || (c.started ?: false) == started)
    }
    val shown = when (sort) {
        "A to Z" -> filtered.sortedBy { it.title.lowercase() }
        "Release Year" -> filtered.sortedByDescending { it.year ?: 0 }
        else -> filtered
    }

    Column(Modifier.fillMaxSize()) {
        PushedBar("Watchlist", onBack)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp), contentPadding = PaddingValues(bottom = 24.dp + TabBarClearance)) {
            item {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        item { FilterChip("TV Shows", kind == "tv") { kind = if (kind == "tv") null else "tv" } }
                        item { FilterChip("Movies", kind == "movie") { kind = if (kind == "movie") null else "movie" } }
                        item { FilterChip("Haven't Started", started == false) { started = if (started == false) null else false } }
                        item { FilterChip("Started", started == true) { started = if (started == true) null else true } }
                    }
                    Box {
                        Column(Modifier.pressable { sortOpen = true }) {
                            Text("Sort By", fontSize = 12.sp, color = Palette.dim)
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(sort, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                                Icon(Icons.Filled.KeyboardArrowDown, null, tint = Color.White, modifier = Modifier.size(18.dp))
                            }
                        }
                        DropdownMenu(sortOpen, onDismissRequest = { sortOpen = false }, containerColor = Color(0xFF242424)) {
                            listOf("Recently Added", "A to Z", "Release Year").forEach { option ->
                                DropdownMenuItem(text = { Text(option) }, onClick = { sort = option; sortOpen = false })
                            }
                        }
                    }
                }
            }
            items(shown, key = { it.mediaID }) { card ->
                val art = if (wide) 240.dp else 150.dp
                Row(Modifier.fillMaxWidth().pressable { nav.open(card) }.padding(horizontal = 16.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    RemoteImage(card.backdrop ?: card.poster, Modifier.width(art).height(art * 9 / 16).clip(RoundedCornerShape(6.dp)))
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(card.title, fontSize = if (wide) 19.sp else 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
                            maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(listOfNotNull(card.year?.toString(), if (card.isSeries) "Series" else "Film",
                            if (card.started == true) "Started" else null).joinToString(" · "), fontSize = 12.sp, color = Palette.dim)
                    }
                    val film = if (card.isSeries) null else card.playableDownloadID
                    if (film != null) {
                        Icon(Icons.Outlined.PlayCircle, "Play ${card.title}", tint = Color.White,
                            modifier = Modifier.size(36.dp).pressable { nav.play(PlayRequest(film.toString(), card.title)) })
                    }
                }
            }
            if (loaded && shown.isEmpty()) item {
                Column(Modifier.fillMaxWidth().padding(top = 60.dp), horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Icon(Icons.Outlined.LibraryAdd, null, tint = Palette.faint, modifier = Modifier.size(36.dp))
                    Text(if (items.isEmpty()) "Your list is empty" else "Nothing matches these filters", fontSize = 17.sp,
                        fontWeight = FontWeight.SemiBold, color = Color.White)
                    if (items.isEmpty()) Text("Tap Watchlist on any title to save it here for later.", fontSize = 15.sp, color = Palette.dim)
                }
            }
        }
    }
}

@Composable
private fun FilterChip(label: String, on: Boolean, onClick: () -> Unit) {
    Text(label, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = if (on) Color.Black else Color.White,
        modifier = Modifier.clip(CircleShape).background(if (on) Color.White else Color.Transparent)
            .border(1.dp, Color.White.copy(alpha = if (on) 0f else 0.35f), CircleShape)
            .pressable(onClick = onClick).padding(horizontal = 14.dp, vertical = 8.dp))
}
