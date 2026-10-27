package xyz.vibestream.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.NotificationsNone
import androidx.compose.material.icons.outlined.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import xyz.vibestream.app.AppState
import xyz.vibestream.app.Debug
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.DownloadItem
import xyz.vibestream.app.api.DownloadManager
import xyz.vibestream.app.api.DownloadTotals
import xyz.vibestream.app.api.NotificationItem
import xyz.vibestream.app.api.PackEpisode
import xyz.vibestream.app.api.PlayRequest
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneOffset

fun fileSize(bytes: Long): String {
    if (bytes <= 0) return "0 B"
    val units = listOf("B", "kB", "MB", "GB", "TB")
    var value = bytes.toDouble()
    var unit = 0
    while (value >= 1000 && unit < units.lastIndex) { value /= 1000; unit++ }
    return if (unit <= 1) "${value.toInt()} ${units[unit]}" else "%.2f %s".format(value, units[unit]).replace(".00 ", " ")
}

@Composable
fun DownloadsView(nav: Navigator) {
    var data by remember { mutableStateOf<DownloadManager?>(null) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var confirming by remember { mutableStateOf<DownloadItem?>(null) }
    var confirmingEpisode by remember { mutableStateOf<Pair<DownloadItem, PackEpisode>?>(null) }
    var working by remember { mutableStateOf<Set<Int>>(emptySet()) }
    var note by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    fun show(message: String) {
        note = message
        scope.launch { delay(3_000); if (note == message) note = null }
    }
    suspend fun load() {
        runCatching { Api.downloadManager() }.onSuccess { data = it; loadError = null }.onFailure { loadError = it.message }
    }
    LaunchedEffect(Unit) { while (true) { load(); delay(3_000) } }

    Box {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 30.dp)) {
            item {
                Text("My Downloads", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
                    modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            }
            data?.totals?.let { item { Summary(it) } }
            if (data?.live == false) item {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.Warning, null, tint = Color(0xFFFF9500), modifier = Modifier.size(16.dp))
                    Text("qBittorrent is not answering, so speeds and peers are the last known values.", fontSize = 13.sp, color = Color(0xFFFF9500))
                }
            }
            items(data?.items.orEmpty(), key = { it.downloadID }) { item ->
                DownloadRow(item, item.downloadID in working,
                    onPlay = {
                        if (item.mediaType != "tv" || item.mediaID == null) nav.play(PlayRequest(item.downloadID.toString(), item.title))
                        else scope.launch {
                            val next = runCatching { Api.media(item.mediaID) }.getOrNull()?.nextUp
                            if (next != null) nav.play(PlayRequest(next.playID, item.title)) else show("Open ${item.title} to choose an episode")
                        }
                    },
                    onRetry = {
                        working = working + item.downloadID
                        scope.launch {
                            runCatching { AppState.download(item.torrentID); load(); show("Preparing ${item.title} again") }
                                .onFailure { show("Could not retry: ${it.message}") }
                            working = working - item.downloadID
                        }
                    },
                    onDelete = { confirming = item },
                    onDeleteEpisode = { confirmingEpisode = item to it })
            }
            if (data?.items?.isEmpty() == true) item {
                Column(Modifier.fillMaxWidth().padding(top = 60.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Outlined.Download, null, tint = Palette.faint, modifier = Modifier.size(36.dp))
                    Text("Nothing downloaded yet", fontSize = 15.sp, color = Palette.dim, modifier = Modifier.padding(top = 10.dp))
                }
            }
            if (data == null && loadError != null) item { Text(loadError.orEmpty(), fontSize = 13.sp, color = Palette.dim, modifier = Modifier.padding(top = 40.dp)) }
            if (data == null && loadError == null) item { Box(Modifier.fillMaxWidth().padding(40.dp), contentAlignment = Alignment.Center) { BootSpinner() } }
        }
        note?.let {
            Text(it, fontSize = 13.sp, color = Color.White, modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 18.dp)
                .background(Color(0xFF2A2A2A), RoundedCornerShape(12.dp)).padding(horizontal = 16.dp, vertical = 10.dp))
        }
    }

    confirming?.let { item ->
        AlertDialog(
            onDismissRequest = { confirming = null },
            title = { Text("Delete ${item.title}?") },
            text = {
                Text(if (item.seeding.met) "This removes the torrent and its files from the server."
                else "This removes the torrent and its files from the server. It has only ${item.seeding.detail}, so deleting now counts as a hit and run on filelist.")
            },
            confirmButton = {
                TextButton({
                    confirming = null
                    working = working + item.downloadID
                    scope.launch {
                        runCatching { Api.deleteDownload(item.downloadID); load(); AppState.loadFeed(); show("Removed ${item.title}") }
                            .onFailure { show("Could not remove it: ${it.message}") }
                        working = working - item.downloadID
                    }
                }) { Text("Delete and free ${fileSize(item.sizeBytes)}", color = Color(0xFFFF5A6E)) }
            },
            dismissButton = { TextButton({ confirming = null }) { Text("Cancel", color = Color.White) } },
            containerColor = Color(0xFF242424),
        )
    }
    confirmingEpisode?.let { (item, episode) ->
        AlertDialog(
            onDismissRequest = { confirmingEpisode = null },
            title = { Text("Delete ${episode.label} of ${item.title}?") },
            text = { Text("This removes the episode from the server and from your library. The rest of the season stays.") },
            confirmButton = {
                TextButton({
                    confirmingEpisode = null
                    working = working + item.downloadID
                    scope.launch {
                        runCatching { Api.deleteEpisode(episode.episodeID, item.downloadID); load(); AppState.loadFeed(); show("Removed ${episode.label} of ${item.title}") }
                            .onFailure { show("Could not remove it: ${it.message}") }
                        working = working - item.downloadID
                    }
                }) { Text("Delete Episode", color = Color(0xFFFF5A6E)) }
            },
            dismissButton = { TextButton({ confirmingEpisode = null }) { Text("Cancel", color = Color.White) } },
            containerColor = Color(0xFF242424),
        )
    }
}

@Composable
private fun Summary(totals: DownloadTotals) {
    val slices = buildList {
        if (totals.playbackBytes != null && totals.torrentBytes != null) {
            add(Triple("Playback", totals.playbackBytes, Palette.accent))
            add(Triple("Torrents", totals.torrentBytes, Palette.good))
        } else add(Triple("On disk", totals.sizeBytes, Palette.accent))
        totals.freeBytes?.let { add(Triple("Free", it, Color(0xFF3D3D3D))) }
    }
    val used = slices.filter { it.first != "Free" }.sumOf { it.second }
    val whole = slices.sumOf { it.second }.coerceAtLeast(1)
    Column(Modifier.fillMaxWidth().background(Palette.fill, RoundedCornerShape(18.dp)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(22.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(128.dp), contentAlignment = Alignment.Center) {
                Canvas(Modifier.size(128.dp)) {
                    val stroke = size.width * 0.16f
                    val inset = stroke / 2
                    var start = -90f
                    slices.forEach { (_, bytes, colour) ->
                        val sweep = 360f * bytes.coerceAtLeast(1) / whole
                        drawArc(colour, start + 0.75f, (sweep - 1.5f).coerceAtLeast(0.5f), false,
                            topLeft = androidx.compose.ui.geometry.Offset(inset, inset),
                            size = androidx.compose.ui.geometry.Size(size.width - stroke, size.height - stroke),
                            style = Stroke(stroke, cap = StrokeCap.Butt))
                        start += sweep
                    }
                }
                Column(Modifier.width(80.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(fileSize(used), fontSize = 16.sp, fontWeight = FontWeight.Bold, color = Color.White, maxLines = 1)
                    if (totals.freeBytes != null) Text("of ${fileSize(whole)}", fontSize = 11.sp, fontWeight = FontWeight.Medium, color = Palette.faint)
                }
            }
            Column(verticalArrangement = Arrangement.spacedBy(11.dp)) {
                slices.forEach { (label, bytes, colour) ->
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(10.dp).background(colour, CircleShape))
                        Column {
                            Text(fileSize(bytes), fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                            Text(label, fontSize = 12.sp, color = Palette.faint)
                        }
                    }
                }
            }
        }
        val parts = buildList {
            add(if (totals.count == 1) "1 title" else "${totals.count} titles")
            add("${fileSize(totals.uploadedBytes)} shared")
            if (totals.downloading > 0) { add("↓ ${fileSize(totals.dlSpeed)}/s"); add("↑ ${fileSize(totals.upSpeed)}/s") }
        }
        Text(parts.joinToString("  ·  "), fontSize = 13.sp, color = Palette.dim)
    }
}

@Composable
private fun DownloadRow(
    item: DownloadItem,
    working: Boolean,
    onPlay: () -> Unit,
    onRetry: () -> Unit,
    onDelete: () -> Unit,
    onDeleteEpisode: (PackEpisode) -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    var episodesMenu by remember { mutableStateOf(false) }
    val tint = when {
        item.playable -> Color(0xFF45D469)
        item.state == "error" || item.preparation.error != null -> Palette.accent
        else -> Color.White
    }
    Row(Modifier.fillMaxWidth().alpha(if (working) 0.5f else 1f).background(Palette.fill, RoundedCornerShape(16.dp)).padding(12.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        RemoteImage(item.poster, Modifier.width(62.dp).height(93.dp).clip(RoundedCornerShape(6.dp)))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(item.title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = Color.White, maxLines = 2, modifier = Modifier.weight(1f, false))
                item.year?.let { Text("$it", fontSize = 13.sp, color = Palette.faint) }
            }
            Text(item.stateLabel.uppercase(), fontSize = 10.sp, fontWeight = FontWeight.Bold, color = tint,
                modifier = Modifier.background(tint.copy(alpha = 0.2f), CircleShape).padding(horizontal = 7.dp, vertical = 3.dp))
            item.episodes?.takeIf { it.isNotEmpty() }?.let {
                Text("Episodes ${it.joinToString(", ")} of the season", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
            }
            if (item.isWorking) ProgressLine(item.percent, Modifier.fillMaxWidth().clip(CircleShape), track = 0.2f)
            else if (item.isPreparing) ProgressLine(item.preparation.percent, Modifier.fillMaxWidth().clip(CircleShape), track = 0.2f, fill = Color.White)
            val cost = buildList {
                add(fileSize(item.sizeBytes))
                if (item.isWorking) {
                    add("${item.percent.toInt()}%")
                    if (item.dlSpeed > 0) add("${fileSize(item.dlSpeed)}/s")
                    item.etaSeconds?.takeIf { it > 0 }?.let { add("${it / 60}m left") }
                }
                item.seeders?.let { add("$it seeds") }
            }
            Text(cost.joinToString("  ·  "), fontSize = 12.sp, color = Palette.dim)
            val share = buildList {
                item.leechers?.let { add("$it leeching") }
                if (item.upSpeed > 0) add("↑ ${fileSize(item.upSpeed)}/s")
                add("shared ${fileSize(item.uploadedBytes)}")
                add("ratio %.2f".format(item.ratio))
                add("seeded %.1fh".format(item.seedingHours))
            }
            Text(share.joinToString("  ·  "), fontSize = 12.sp, color = Palette.dim)
            (item.error ?: item.preparation.error)?.let { Text(it, fontSize = 11.sp, color = Palette.accent, maxLines = 2) }
        }
        Box {
            Box(Modifier.size(34.dp).pressable(!working) { menu = true }, contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.MoreHoriz, null, tint = Color.White)
            }
            DropdownMenu(menu, onDismissRequest = { menu = false }, containerColor = Color(0xFF242424)) {
                if (item.playable) DropdownMenuItem(text = { Text("Play") }, leadingIcon = { Icon(Icons.Filled.PlayArrow, null) },
                    onClick = { menu = false; onPlay() })
                if (!item.playable && item.preparation.error != null) DropdownMenuItem(text = { Text("Try again") },
                    leadingIcon = { Icon(Icons.Filled.Refresh, null) }, onClick = { menu = false; onRetry() })
                if (item.isPack) DropdownMenuItem(text = { Text("Delete Episode", color = Color(0xFFFF5A6E)) },
                    leadingIcon = { Icon(Icons.Outlined.Delete, null, tint = Color(0xFFFF5A6E)) }, onClick = { menu = false; episodesMenu = true })
                DropdownMenuItem(text = { Text(if (item.isPack) "Delete Season" else "Delete", color = Color(0xFFFF5A6E)) },
                    leadingIcon = { Icon(Icons.Outlined.Delete, null, tint = Color(0xFFFF5A6E)) }, onClick = { menu = false; onDelete() })
            }
            DropdownMenu(episodesMenu, onDismissRequest = { episodesMenu = false }, containerColor = Color(0xFF242424)) {
                item.episodeList.orEmpty().forEach { e ->
                    DropdownMenuItem(text = {
                        Column { Text(e.label, color = Color(0xFFFF5A6E)); e.name?.let { Text(it, fontSize = 12.sp, color = Palette.dim) } }
                    }, onClick = { episodesMenu = false; onDeleteEpisode(e) })
                }
            }
        }
    }
}

object Notifications {
    var items by mutableStateOf<List<NotificationItem>>(emptyList())

    suspend fun load() {
        runCatching { Api.notifications() }.getOrNull()?.let { items = it.items }
    }

    // ISO timestamps from one server compare correctly as strings.
    val unread: Int get() = items.count { it.at > AppState.notificationsSeen }

    fun markRead() { items.firstOrNull()?.at?.let(AppState::markNotificationsSeen) }
}

@Composable
fun NotificationsBell(onOpen: () -> Unit) {
    LaunchedEffect(AppState.profile?.id) {
        while (true) { Notifications.load(); delay(300_000) }
    }
    Box(Modifier.size(44.dp).pressable { onOpen() }, contentAlignment = Alignment.Center) {
        Icon(Icons.Outlined.NotificationsNone, if (Notifications.unread > 0) "Notifications, ${Notifications.unread} new" else "Notifications",
            tint = Color.White, modifier = Modifier.size(24.dp))
        if (Notifications.unread > 0) {
            Box(Modifier.align(Alignment.TopEnd).padding(top = 9.dp, end = 10.dp).size(9.dp)
                .background(Palette.ground, CircleShape).padding(2.dp).background(Palette.accent, CircleShape))
        }
    }
}

@Composable
fun NotificationsList(onOpen: (xyz.vibestream.app.api.Card) -> Unit, onDownloads: () -> Unit) {
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { Notifications.load(); Notifications.markRead() }
    LaunchedEffect(Notifications.items) { Notifications.markRead() }
    LazyColumn(contentPadding = PaddingValues(vertical = 8.dp)) {
        item {
            Text("Notifications", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
                modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        }
        if (Notifications.items.isEmpty()) item {
            Text("Nothing new yet", fontSize = 15.sp, color = Palette.dim, modifier = Modifier.fillMaxWidth().padding(top = 60.dp),
                textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        }
        items(Notifications.items, key = { it.id }) { item ->
            Row(Modifier.fillMaxWidth().pressable {
                if (item.kind == "failed") onDownloads()
                else item.mediaID?.let { id -> scope.launch { runCatching { Api.media(id) }.getOrNull()?.let(onOpen) } }
            }.padding(horizontal = 16.dp, vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                RemoteImage(item.image, Modifier.width(112.dp).height(63.dp).clip(RoundedCornerShape(4.dp)))
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    Text(item.heading, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                        color = if (item.kind == "failed") Palette.accent else Color.White)
                    Text(item.text, fontSize = 13.sp, color = Palette.dim, maxLines = 2)
                    Text(ago(item.at), fontSize = 11.sp, color = Palette.faint)
                }
            }
        }
    }
}

private fun ago(at: String): String {
    val instant = runCatching { OffsetDateTime.parse(at).toInstant() }.getOrNull()
        ?: runCatching { LocalDateTime.parse(at).toInstant(ZoneOffset.UTC) }.getOrNull() ?: return ""
    val days = Duration.between(instant, Instant.now()).toDays()
    return when {
        days <= 0 -> "Today"
        days == 1L -> "1 day ago"
        days < 7 -> "$days days ago"
        days / 7 == 1L -> "1 week ago"
        else -> "${days / 7} weeks ago"
    }
}
