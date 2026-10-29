package xyz.vibestream.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.FolderDelete
import androidx.compose.material.icons.outlined.Warning
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import xyz.vibestream.app.AppState
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.DownloadJob
import xyz.vibestream.app.api.JobInspection
import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

// The iOS app's JobInspector. Downloads lists what was asked for; this is the one place the torrent
// itself shows, so the list stays about episodes and films.
@Composable
fun JobInspector(
    opened: DownloadJob,
    onPlay: (DownloadJob) -> Unit,
    // The list behind, told when something here changed it.
    onChange: suspend () -> Unit,
    onClose: () -> Unit,
) {
    var job by remember { mutableStateOf(opened) }
    var data by remember { mutableStateOf<JobInspection?>(null) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var confirmingDelete by remember { mutableStateOf(false) }
    var confirmingSource by remember { mutableStateOf(false) }
    var working by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    suspend fun load() {
        runCatching { Api.inspectJob(job.id) }
            .onSuccess { fresh -> data = fresh; fresh.job?.let { job = it }; loadError = null }
            .onFailure { if (data == null) loadError = it.said() }
    }
    // Live by nature, as the list is.
    LaunchedEffect(Unit) { while (true) { load(); delay(3_000) } }

    val bars = systemBarPadding()
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Column(Modifier.fillMaxSize().background(Palette.ground).padding(bars)) {
            Box(Modifier.fillMaxWidth().height(48.dp)) {
                Box(Modifier.padding(start = 4.dp).size(44.dp).align(Alignment.CenterStart).pressable(onClick = onClose), contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.Close, "Close", tint = Color.White)
                }
                Text("Details", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White, modifier = Modifier.align(Alignment.Center))
            }
            Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(start = 16.dp, end = 16.dp, bottom = 30.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Header(job, working, onPlay = { onPlay(job) }, onDelete = { confirmingDelete = true })
                val d = data
                when {
                    d != null -> {
                        if (!d.live) Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Outlined.Warning, null, tint = Color(0xFFFF9500), modifier = Modifier.size(16.dp))
                            Text("qBittorrent is not answering, so this is what was last recorded.", fontSize = 13.sp, color = Color(0xFFFF9500))
                        }
                        Activity(d, job)
                        if (d.pieces.count > 0) Pieces(d)
                        if (d.files.isNotEmpty()) Files(d)
                        if (d.live) Peers(d)
                        if (d.trackers.isNotEmpty()) Trackers(d)
                        Information(d, working, onRemoveSource = { confirmingSource = true })
                        d.release?.let { ReleaseFacts(it) }
                    }
                    loadError != null -> Text(loadError.orEmpty(), fontSize = 13.sp, color = Palette.dim)
                    else -> Box(Modifier.fillMaxWidth().padding(top = 40.dp), contentAlignment = Alignment.Center) { BootSpinner(32.dp, 3.dp) }
                }
            }
        }

        if (confirmingDelete) DeleteJobDialog(job, onDismiss = { confirmingDelete = false }) {
            confirmingDelete = false
            working = true
            scope.launch {
                runCatching { Api.deleteJob(job.id); onChange(); AppState.loadFeed(); onClose() }
                    .onFailure { Toasts.error("Couldn't remove it. Try again.") }
                working = false
            }
        }
        if (confirmingSource) {
            val bytes = data?.library?.sourceBytes ?: 0
            AlertDialog(
                onDismissRequest = { confirmingSource = false },
                title = { Text("Remove the torrent's copy?") },
                text = {
                    Text(if (job.seeding.met) "It still plays, from what was built from it. It stops seeding."
                    else "It still plays, from what was built from it. It has only ${job.seeding.detail}, so removing it now counts as a hit and run on filelist.")
                },
                confirmButton = {
                    TextButton({
                        confirmingSource = false
                        working = true
                        scope.launch {
                            // Before the seeding is done, only by insisting.
                            runCatching { Api.removeSource(job.downloadID, force = !job.seeding.met); load(); onChange() }
                                .onFailure { Toasts.error("Couldn't remove the torrent's copy. Try again.") }
                            working = false
                        }
                    }) { Text("Remove and free ${fileSize(bytes)}", color = Color(0xFFFF5A6E)) }
                },
                dismissButton = { TextButton({ confirmingSource = false }) { Text("Cancel", color = Color.White) } },
                containerColor = Color(0xFF242424),
            )
        }
    }
}

// ------------------------------------------------------------------ header

@Composable
private fun Header(job: DownloadJob, working: Boolean, onPlay: () -> Unit, onDelete: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        RemoteImage(job.episode?.still ?: job.backdrop ?: job.poster, Modifier.fillMaxWidth().height(180.dp).clip(RoundedCornerShape(14.dp)))
        Text(job.title, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
        listOfNotNull(job.label, job.episode?.name).joinToString(" · ").takeIf { it.isNotEmpty() }?.let {
            Text(it, fontSize = 15.sp, fontWeight = FontWeight.Medium, color = Palette.dim)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
            if (job.state == "failed") ErrorBadge(16.dp)
            Text(stateWords(job), fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
        }
        if (job.state == "downloading" || job.state == "paused")
            ProgressLine(job.percent, Modifier.fillMaxWidth().clip(CircleShape), track = 0.2f)
        Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            if (job.state == "ready") Pill(true, Modifier.weight(1f), onClick = onPlay) {
                PillLabel("Play") { Icon(Icons.Filled.PlayArrow, null, Modifier.size(22.dp)) }
            }
            Pill(false, Modifier.weight(1f).alpha(if (working) 0.5f else 1f), enabled = !working, onClick = onDelete) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Icon(Icons.Outlined.Delete, null, tint = Palette.danger, modifier = Modifier.size(20.dp))
                    Text("Delete", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Palette.danger)
                }
            }
        }
    }
}

/** The list's status line, with a longer ETA and no size, as iOS has it here. */
private fun stateWords(job: DownloadJob): String = when (job.state) {
    "queued" -> "Queued"
    "paused" -> "Paused at ${job.percent.toInt()}%"
    "downloading" -> buildList {
        add(if (job.percent >= 1) "Downloading ${job.percent.toInt()}%" else "Downloading")
        if (job.dlSpeed > 0) add("${fileSize(job.dlSpeed)}/s")
        job.etaSeconds?.takeIf { it in 1 until 360_000 }?.let { add("${duration(it.toLong())} left") }
    }.joinToString(" · ")
    "preparing" -> job.preparePercent?.let { "Preparing ${it.toInt()}%" } ?: "Preparing"
    "failed" -> job.errorMessage ?: "Something went wrong. Try again."
    else -> "Ready"
}

// ---------------------------------------------------------------- sections

@Composable
private fun Activity(data: JobInspection, job: DownloadJob) {
    val t = data.torrent
    Section("Activity") {
        Facts(listOf(
            "State" to t.state?.let(::qbitState),
            "Progress" to t.progress?.let { "%.1f%%".format(it) },
            "Size" to t.sizeBytes?.let(::fileSize),
            "Downloaded" to t.downloadedBytes?.let(::fileSize),
            "Uploaded" to t.uploadedBytes?.let(::fileSize),
            "Ratio" to t.ratio?.let { "%.2f".format(it) },
            "Download speed" to speeds(t.dlSpeed, t.dlSpeedAvg),
            "Upload speed" to speeds(t.upSpeed, t.upSpeedAvg),
            "Time left" to t.etaSeconds?.takeIf { it in 1 until 8_640_000 }?.let(::duration),
            "Seeds" to pair(t.seeds, t.seedsTotal),
            "Leechers" to pair(t.leechers, t.leechersTotal),
            "Connections" to pair(t.connections, t.connectionsLimit),
            "Wasted" to t.wastedBytes?.takeIf { it > 0 }?.let(::fileSize),
            "Active for" to t.elapsedSeconds?.takeIf { it > 0 }?.let(::duration),
            "Seeding for" to t.seedingSeconds?.takeIf { it > 0 }?.let(::duration),
            "Seeding goal" to if (data.library.sourceRemoved) null
                else if (job.seeding.met) "Met" else "Not yet: ${job.seeding.detail}",
            "Next announce" to t.reannounceSeconds?.takeIf { it > 0 }?.let(::duration),
        ))
    }
}

// The pieces as a block of cells, each the share of its pieces that is here: dark for none, the
// accent for all, in between in between. The ones being fetched right now are white. Square cells,
// 24 across the card, as many rows as it takes, so nothing is cut off.
@Composable
private fun Pieces(data: JobInspection) {
    val cells = data.pieces
    val caption = pieceCaption(data)
    Section("Pieces") {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            BoxWithConstraints(Modifier.fillMaxWidth()) {
                val columns = 24
                val rows = (cells.have.size + columns - 1) / columns
                val gap = 2.dp
                val cell = (maxWidth - gap * (columns - 1)) / columns
                Canvas(Modifier.fillMaxWidth().height(cell * rows + gap * (rows - 1).coerceAtLeast(0)).semantics { contentDescription = caption }) {
                    val side = cell.toPx()
                    val step = side + gap.toPx()
                    val corner = CornerRadius(2.dp.toPx())
                    cells.have.forEachIndexed { i, have ->
                        drawRoundRect(colour(have, cells.busy.getOrNull(i) == 1),
                            topLeft = Offset(i % columns * step, i / columns * step), size = Size(side, side), cornerRadius = corner)
                    }
                }
            }
            Text(caption, fontSize = 13.sp, color = Palette.dim)
        }
    }
}

private fun colour(have: Int, busy: Boolean): Color = when {
    busy -> Color.White
    have == 0 -> Color(0xFF2E2E2E)
    else -> Palette.accent.copy(alpha = (0.3f + 0.7f * have / 100f).coerceIn(0f, 1f))
}

private fun pieceCaption(data: JobInspection): String {
    val t = data.torrent
    return listOfNotNull(
        t.piecesCount?.let { "%,d pieces".format(it) + (t.pieceSize?.let { size -> " of ${fileSize(size)}" } ?: "") },
        t.piecesHave?.let { "%,d here".format(it) },
    ).joinToString(" · ")
}

@Composable
private fun Files(data: JobInspection) {
    val many = data.files.size > 1
    Section(if (many) "Files (${data.files.size})" else "File") {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            data.files.forEach { file ->
                val skipped = file.priority == 0
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                        if (file.mine && many) Box(Modifier.size(7.dp).background(Palette.accent, CircleShape).semantics { contentDescription = "This download" })
                        Text(file.name.substringAfterLast('/'), fontSize = 13.sp,
                            fontWeight = if (file.mine) FontWeight.SemiBold else FontWeight.Normal,
                            color = if (skipped) Palette.faint else Color.White, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        ProgressLine(file.progress, Modifier.weight(1f).clip(CircleShape), track = 0.2f, fill = if (skipped) Palette.faint else Palette.accent)
                        Text(if (skipped) "Skipped" else "%.0f%%".format(file.progress), fontSize = 12.sp, color = Palette.dim,
                            style = digits, textAlign = TextAlign.End, modifier = Modifier.width(58.dp))
                        Text(fileSize(file.sizeBytes), fontSize = 12.sp, color = Palette.dim,
                            style = digits, textAlign = TextAlign.End, modifier = Modifier.width(66.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun Peers(data: JobInspection) {
    Section(if (data.peers.isEmpty()) "Peers" else "Peers (${data.peers.size})") {
        if (data.peers.isEmpty()) Text("No peers connected", fontSize = 13.sp, color = Palette.dim)
        else Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            data.peers.forEach { peer ->
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(peer.address ?: "?", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = Color.White,
                            style = digits, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(listOfNotNull(peer.client, peer.country, peer.connection, peer.flags).joinToString(" · "),
                            fontSize = 12.sp, color = Palette.faint, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text("%.0f%%".format(peer.progress), fontSize = 12.sp, color = Color.White, style = digits)
                        Text("↓ ${fileSize(peer.dlSpeed)}/s  ↑ ${fileSize(peer.upSpeed)}/s", fontSize = 12.sp, color = Palette.dim, style = digits)
                    }
                }
            }
        }
    }
}

@Composable
private fun Trackers(data: JobInspection) {
    Section("Trackers") {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            data.trackers.forEach { tracker ->
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(tracker.host, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = Color.White, modifier = Modifier.weight(1f))
                        Text(capitalized(tracker.status), fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                            color = when (tracker.status) { "working" -> readyGreen; "not working" -> Palette.danger; else -> Palette.dim })
                    }
                    val counts = listOf("seeds" to tracker.seeds, "leechers" to tracker.leechers, "peers" to tracker.peers)
                        .mapNotNull { (label, n) -> n?.takeIf { it >= 0 }?.let { "$it $label" } }
                    if (counts.isNotEmpty()) Text(counts.joinToString(" · "), fontSize = 12.sp, color = Palette.faint)
                    tracker.message?.let { Text(it, fontSize = 12.sp, color = Palette.dim) }
                }
            }
        }
    }
}

@Composable
private fun Information(data: JobInspection, working: Boolean, onRemoveSource: () -> Unit) {
    val t = data.torrent
    val library = data.library
    Section("Information") {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Facts(listOf(
                "Torrent" to t.name,
                "Info hash" to t.infoHash,
                "Saved in" to t.savePath,
                "Content" to t.contentPath,
                "In the library" to library.libraryPath,
                "Asked for" to (library.wanted?.joinToString(", ") ?: "All of it"),
                "Preparation" to preparation(library.preparation),
                "Created by" to t.createdBy,
                "Created" to date(t.createdAt),
                "Requested" to date(library.requestedAt),
                "Added" to date(t.addedAt),
                "Completed" to date(t.completedAt),
                "Torrent's copy" to when {
                    library.sourceRemoved -> "Removed; plays from what was built"
                    library.sourceRemovable -> "Can go: ${fileSize(library.sourceBytes ?: 0)} back"
                    else -> "Kept"
                },
            ), wide = true)
            if (library.sourceRemovable && !library.sourceRemoved) {
                Pill(false, Modifier.fillMaxWidth().alpha(if (working) 0.5f else 1f), enabled = !working, onClick = onRemoveSource) {
                    PillLabel("Remove the torrent's copy") { Icon(Icons.Outlined.FolderDelete, null, Modifier.size(20.dp)) }
                }
            }
        }
    }
}

@Composable
private fun ReleaseFacts(release: JobInspection.Release) {
    Section("Release") {
        Facts(listOf(
            "Category" to release.categoryName,
            "Size" to release.sizeBytes?.let(::fileSize),
            "Video" to listOfNotNull(release.resolution, release.source, release.videoCodec, release.hdr).joinToString(" · ").ifEmpty { null },
            "Audio" to release.audioCodec,
            "Group" to release.releaseGroup,
            "Uploaded" to date(release.uploadDate),
            "On the tracker" to pair(release.seeders, release.leechers)?.let { "$it seeds/leechers" },
            "Flags" to listOfNotNull(if (release.freeleech == true) "Freeleech" else null, if (release.internal == true) "Internal" else null)
                .joinToString(" · ").ifEmpty { null },
        ))
    }
}

// ------------------------------------------------------- pieces of pieces

/** Figures of one width, so columns of them line up. */
private val digits = TextStyle(fontFeatureSettings = "tnum")

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().background(Palette.fill, RoundedCornerShape(16.dp)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(title.uppercase(), fontSize = 12.sp, fontWeight = FontWeight.Bold, color = Palette.faint)
        content()
    }
}

/*
 * Label and value, a row each; the ones with no value are left out. Wide puts
 * the value under its label, for paths and hashes, and lets it be copied.
 */
@Composable
private fun Facts(rows: List<Pair<String, String?>>, wide: Boolean = false) {
    Column(verticalArrangement = Arrangement.spacedBy(if (wide) 10.dp else 7.dp)) {
        rows.forEach { (label, value) ->
            if (value == null) return@forEach
            if (wide) Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(label, fontSize = 12.sp, color = Palette.faint)
                SelectionContainer { Text(value, fontSize = 13.sp, color = Color.White) }
            } else Row(verticalAlignment = Alignment.Top) {
                Text(label, fontSize = 13.sp, color = Palette.dim)
                Text(value, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = Color.White, style = digits,
                    textAlign = TextAlign.End, modifier = Modifier.weight(1f).padding(start = 12.dp))
            }
        }
    }
}

private fun speeds(now: Long?, average: Long?): String? {
    now ?: return null
    // qBittorrent reports a few bytes a second of chatter on an idle torrent;
    // that is nothing moving.
    val current = "${fileSize(if (now < 1000) 0 else now)}/s"
    return if (average != null && average > 0) "$current, ${fileSize(average)}/s average" else current
}

private fun pair(a: Int?, b: Int?): String? {
    a ?: return null
    return if (b == null || b < 0) "$a" else "$a of $b"
}

private fun preparation(prep: JobInspection.Library.Prep?): String? {
    prep ?: return null
    if (prep.error != null) return "Could not be made playable"
    if (prep.ready == true) return "Done"
    val percent = prep.percent
    if (percent != null && percent > 0) return "${prep.stage?.let(::capitalized) ?: "Working"} ${percent.toInt()}%"
    return prep.stage?.let(::capitalized)
}

/** Every word with a capital, as Swift's capitalized. */
private fun capitalized(text: String) = text.split(" ").joinToString(" ") { it.replaceFirstChar(Char::uppercaseChar) }

/** qBittorrent's states in words. */
private fun qbitState(raw: String) = mapOf(
    "downloading" to "Downloading", "stalledDL" to "Waiting for peers", "metaDL" to "Fetching metadata",
    "queuedDL" to "Queued", "forcedDL" to "Downloading (forced)", "checkingDL" to "Checking",
    "pausedDL" to "Paused", "stoppedDL" to "Stopped", "allocating" to "Allocating space",
    "uploading" to "Seeding", "stalledUP" to "Seeding, nobody downloading", "queuedUP" to "Queued to seed",
    "forcedUP" to "Seeding (forced)", "checkingUP" to "Checking", "pausedUP" to "Finished",
    "stoppedUP" to "Finished", "checkingResumeData" to "Checking", "moving" to "Moving",
    "missingFiles" to "Files missing", "error" to "Error",
)[raw] ?: raw

private val dateWords = DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM, FormatStyle.SHORT)

/** An ISO timestamp as Oct 28, 2026, 3:04 PM; anything else as it came. */
private fun date(iso: String?): String? {
    iso ?: return null
    val instant = runCatching { OffsetDateTime.parse(iso).toInstant() }.getOrNull()
        ?: runCatching { Instant.parse(iso) }.getOrNull()
        ?: runCatching { LocalDateTime.parse(iso.replace(' ', 'T')).toInstant(ZoneOffset.UTC) }.getOrNull()
        ?: return iso
    return dateWords.format(instant.atZone(ZoneId.systemDefault()))
}

private fun duration(seconds: Long): String {
    val days = seconds / 86_400
    val hours = seconds % 86_400 / 3600
    val minutes = seconds % 3600 / 60
    return when {
        days > 0 -> "${days}d ${hours}h"
        hours > 0 -> "${hours}h ${minutes}m"
        else -> "${maxOf(1, minutes)}m"
    }
}
