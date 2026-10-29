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
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.NotificationsNone
import androidx.compose.material.icons.outlined.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
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
import xyz.vibestream.app.api.DownloadJob
import xyz.vibestream.app.api.DownloadJobs
import xyz.vibestream.app.api.DownloadTotals
import xyz.vibestream.app.api.NotificationItem
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

/** The green the TV and the web say Ready in. */
internal val readyGreen = Color(0xFF45D469)
private val deleteRed = Color(0xFFFF5A6E)

// The downloads manager, the iOS app's. Each row is something that was asked for (a film, an
// episode, a season) with the progress of its own files, newest first; the torrent under it is in
// the row's inspector.
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DownloadsView(nav: Navigator) {
    var data by remember { mutableStateOf<DownloadJobs?>(null) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var confirming by remember { mutableStateOf<DownloadJob?>(null) }
    var inspecting by remember { mutableStateOf<DownloadJob?>(null) }
    var working by remember { mutableStateOf<Set<Int>>(emptySet()) }
    var note by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    fun show(message: String) {
        note = message
        scope.launch { delay(3_000); if (note == message) note = null }
    }
    suspend fun load() {
        runCatching { Api.downloadJobs() }.onSuccess { data = it; loadError = null }.onFailure { loadError = it.said() }
    }
    // Polled while open: speeds and peers are live by nature.
    LaunchedEffect(Unit) {
        // inspectJob <id>: that job's inspector, to look at it.
        Debug.int("inspectJob")?.let { wanted -> load(); inspecting = data?.items?.firstOrNull { it.id == wanted } }
        while (true) { load(); delay(3_000) }
    }

    /* An episode or a film plays itself. A season plays the episode the
     * show's page would: carrying on from the last one watched, or its first. */
    fun play(job: DownloadJob) {
        job.playID?.let {
            nav.play(PlayRequest(it, job.title, season = job.episode?.season, episode = job.episode?.number))
            return
        }
        val media = job.mediaID?.takeIf { job.kind == "season" } ?: return
        scope.launch {
            val next = runCatching { Api.media(media) }.getOrNull()?.nextUp
            if (next != null) nav.play(PlayRequest(next.playID, job.title, season = next.season, episode = next.number))
            else show("Open ${job.title} to choose an episode")
        }
    }

    // Pulled down, it reads again now rather than at the next poll.
    PullToRefreshBox(refreshing, onRefresh = { scope.launch { refreshing = true; load(); refreshing = false } }) {
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
            items(data?.items.orEmpty(), key = { it.id }) { job ->
                JobRow(job, job.id in working,
                    onPlay = { play(job) },
                    // Asking again is what clears a failure, of the download
                    // or of its preparation.
                    onRetry = {
                        working = working + job.id
                        scope.launch {
                            runCatching { AppState.download(job.torrentID, job.episode?.id); load(); show("Trying ${deleteName(job)} again") }
                                .onFailure { Toasts.error(it.said()) }
                            working = working - job.id
                        }
                    },
                    onDelete = { confirming = job },
                    onInspect = { inspecting = job })
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

    inspecting?.let { job ->
        JobInspector(job, onPlay = { inspecting = null; play(it) }, onChange = { load() }, onClose = { inspecting = null })
    }
    confirming?.let { job ->
        DeleteJobDialog(job, onDismiss = { confirming = null }) {
            confirming = null
            working = working + job.id
            scope.launch {
                runCatching {
                    Api.deleteJob(job.id)
                    load()
                    // The catalog rows carry download state, so they are
                    // stale the moment one disappears.
                    AppState.loadFeed()
                    show("Removed ${deleteName(job)}")
                }.onFailure { Toasts.error("Couldn't remove it. Try again.") }
                working = working - job.id
            }
        }
    }
}

/** "Show S1:E3": the title with what of it this is. */
internal fun deleteName(job: DownloadJob) = listOfNotNull(job.title, job.label).joinToString(" ")

/*
 * What deleting costs. One episode of a pack others still use leaves the
 * torrent; the last of it takes the torrent, and before its seeding is done
 * that is a hit and run.
 */
internal fun deleteMessage(job: DownloadJob) = when {
    job.kind == "episode" && job.sharesTorrent ->
        "This removes the episode from the server and from your library. The rest of the season stays."
    !job.seeding.met ->
        "This removes it and its files from the server. It has only ${job.seeding.detail}, so deleting now counts as a hit and run on filelist."
    else -> "This removes it and its files from the server."
}

/** The confirmation every delete of a job goes through, here and in its inspector. */
@Composable
internal fun DeleteJobDialog(job: DownloadJob, onDismiss: () -> Unit, onConfirm: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Delete ${deleteName(job)}?") },
        text = { Text(deleteMessage(job)) },
        confirmButton = {
            TextButton(onConfirm) { Text(job.sizeBytes?.let { "Delete and free ${fileSize(it)}" } ?: "Delete", color = deleteRed) }
        },
        dismissButton = { TextButton(onDismiss) { Text("Cancel", color = Color.White) } },
        containerColor = Color(0xFF242424),
    )
}

/*
 * What the disk holds, as a ring: the renditions playback uses, the raw
 * torrent files, and what is free, with the used part named in the middle.
 */
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
                // The hole is 87dp across: 68 keeps the words off the ring.
                Column(Modifier.width(68.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    // Smaller rather than cut: "971.85 GB" does not fit the ring's
                    // middle at full size, and wrapped it lost its unit.
                    ShrinkText(fileSize(used), 17.sp, minimumScale = 0.6f, fontWeight = FontWeight.Bold, color = Color.White)
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
            add(if (totals.count == 1) "1 download" else "${totals.count} downloads")
            add("${fileSize(totals.uploadedBytes)} shared")
            if (totals.downloading > 0) { add("↓ ${fileSize(totals.dlSpeed)}/s"); add("↑ ${fileSize(totals.upSpeed)}/s") }
        }
        Text(parts.joinToString("  ·  "), fontSize = 13.sp, color = Palette.dim)
    }
}

/*
 * One job: what it is (the episode's still, or the poster), where it stands
 * in one line with a bar while it moves, and a menu. A tap opens its
 * inspector.
 */
@Composable
private fun JobRow(
    job: DownloadJob,
    working: Boolean,
    onPlay: () -> Unit,
    onRetry: () -> Unit,
    onDelete: () -> Unit,
    onInspect: () -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth().alpha(if (working) 0.5f else 1f).background(Palette.fill, RoundedCornerShape(16.dp))
        .pressable(onClick = onInspect).padding(12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        // The episode's still for an episode, wide; the poster for the rest.
        val still = job.episode?.still
        if (still != null) RemoteImage(still, Modifier.width(112.dp).height(63.dp).clip(RoundedCornerShape(6.dp)))
        else RemoteImage(job.poster, Modifier.width(62.dp).height(93.dp).clip(RoundedCornerShape(6.dp)))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text(job.title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = Color.White, maxLines = 2)
            jobSubtitle(job)?.let { Text(it, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = Palette.dim, maxLines = 2) }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                if (job.state == "failed") ErrorBadge(14.dp)
                val ready = job.state == "ready"
                Text(jobStatus(job), fontSize = 12.sp, fontWeight = if (ready) FontWeight.SemiBold else FontWeight.Normal,
                    color = if (ready) readyGreen else Palette.dim, maxLines = 2)
            }
            if (job.state == "downloading" || job.state == "paused")
                ProgressLine(job.percent, Modifier.padding(top = 2.dp).fillMaxWidth().clip(CircleShape), track = 0.2f)
            else if (job.state == "preparing")
                ProgressLine(job.preparePercent ?: 0.0, Modifier.padding(top = 2.dp).fillMaxWidth().clip(CircleShape), track = 0.2f, fill = Color.White)
        }
        Box {
            Box(Modifier.size(34.dp).pressable(!working) { menu = true }, contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.MoreHoriz, null, tint = Color.White)
            }
            DropdownMenu(menu, onDismissRequest = { menu = false }, containerColor = Color(0xFF242424)) {
                if (job.state == "ready") DropdownMenuItem(text = { Text("Play") }, leadingIcon = { Icon(Icons.Filled.PlayArrow, null) },
                    onClick = { menu = false; onPlay() })
                if (job.state == "failed") DropdownMenuItem(text = { Text("Try again") },
                    leadingIcon = { Icon(Icons.Filled.Refresh, null) }, onClick = { menu = false; onRetry() })
                DropdownMenuItem(text = { Text("Details") }, leadingIcon = { Icon(Icons.Outlined.Info, null) },
                    onClick = { menu = false; onInspect() })
                DropdownMenuItem(text = { Text("Delete", color = deleteRed) },
                    leadingIcon = { Icon(Icons.Outlined.Delete, null, tint = deleteRed) }, onClick = { menu = false; onDelete() })
            }
        }
    }
}

/** The label and the episode's name, or the label, or the year. */
private fun jobSubtitle(job: DownloadJob): String? {
    if (job.episode != null) return listOfNotNull(job.label, job.episode.name).joinToString(" · ").ifEmpty { null }
    return job.label ?: job.year?.toString()
}

/*
 * Where a job stands, in one line. Under one percent is what a stall looks
 * like, so it says only that it is under way until there is a figure worth
 * printing; an ETA past a hundred hours is qBittorrent's way of saying never.
 */
private fun jobStatus(job: DownloadJob): String = when (job.state) {
    "queued" -> "Queued"
    "paused" -> "Paused at ${job.percent.toInt()}%"
    "downloading" -> buildList {
        add(if (job.percent >= 1) "Downloading ${job.percent.toInt()}%" else "Downloading")
        if (job.dlSpeed > 0) add("${fileSize(job.dlSpeed)}/s")
        job.etaSeconds?.takeIf { it in 1 until 360_000 }?.let { add("${maxOf(1, it / 60)}m left") }
    }.joinToString(" · ")
    "preparing" -> job.preparePercent?.let { "Preparing ${it.toInt()}%" } ?: "Preparing"
    "failed" -> job.errorMessage ?: "Something went wrong. Try again."
    else -> listOfNotNull("Ready", job.sizeBytes?.let(::fileSize)).joinToString(" · ")
}

// ------------------------------------------------------------ notifications

/*
 * The bell, the same one the web and iOS apps have. What it lists is worked
 * out by the server; what it counts is this device's: anything newer than the
 * last time this profile opened the list here. In-app only.
 */
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
fun NotificationsList(onOpen: (xyz.vibestream.app.api.Card) -> Unit, onDownloads: () -> Unit, onClose: (() -> Unit)? = null) {
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { Notifications.load(); Notifications.markRead() }
    LaunchedEffect(Notifications.items) { Notifications.markRead() }
    LazyColumn(contentPadding = PaddingValues(vertical = 8.dp)) {
        item {
            Box(Modifier.fillMaxWidth().padding(bottom = 8.dp), contentAlignment = Alignment.Center) {
                Text("Notifications", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                // A way out besides dragging the sheet, as iOS has.
                onClose?.let { close ->
                    Box(Modifier.align(Alignment.CenterEnd).padding(end = 6.dp).size(40.dp).pressable(onClick = close),
                        contentAlignment = Alignment.Center) {
                        Icon(Icons.Filled.Close, "Close", tint = Color.White, modifier = Modifier.size(20.dp))
                    }
                }
            }
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
