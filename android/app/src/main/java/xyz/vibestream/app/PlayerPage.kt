package xyz.vibestream.app

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.ClickableText
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.Card
import xyz.vibestream.app.api.EpisodeAbout
import xyz.vibestream.app.api.EpisodeItem
import xyz.vibestream.app.ui.BootSpinner
import xyz.vibestream.app.ui.CollectionTarget
import xyz.vibestream.app.ui.Grid
import xyz.vibestream.app.ui.Palette
import xyz.vibestream.app.ui.PosterCard
import xyz.vibestream.app.ui.TitleAbout
import xyz.vibestream.app.ui.pressable

// The upright player's page (iOS PlayerPage): what sits under the picture when a phone is held
// upright. The title and what it is about, then the tabs: Episodes (a show's only), About, Similar,
// and Audio & Subtitles.
@Composable
internal fun PlayerPage(model: PlayerModel, onEpisode: (EpisodeItem) -> Unit, onTitle: (Card) -> Unit) {
    val presentation = model.info?.presentation
    val mediaID = model.info?.mediaID
    var card by remember { mutableStateOf<Card?>(null) }
    var similar by remember { mutableStateOf<List<Card>?>(null) }
    var about by remember { mutableStateOf<EpisodeAbout?>(null) }
    var collection by remember { mutableStateOf<CollectionTarget?>(null) }
    /** What happens in it, all of it rather than the first three lines. */
    var expanded by remember { mutableStateOf(false) }
    val tabs = buildList {
        if (presentation?.episode != null) add("Episodes")
        add("About"); add("Similar")
        if (model.ready) add("Audio & Subtitles")
    }
    var tab by remember { mutableStateOf<String?>(null) }
    val shownTab = tab?.takeIf { it in tabs } ?: tabs.first()
    LaunchedEffect(mediaID) { mediaID?.let { id -> card = runCatching { Api.media(id) }.getOrNull() } }
    // An episode's play id is "e" and its id: its own About, once.
    LaunchedEffect(model.request.playID, presentation?.episode != null) {
        val id = model.request.playID.takeIf { it.startsWith("e") }?.drop(1)?.toIntOrNull()
        if (presentation?.episode != null && id != null) about = runCatching { Api.episodeAbout(id) }.getOrNull()
    }

    Column(Modifier.fillMaxSize().background(Palette.ground).verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp)) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(presentation?.title ?: model.request.title, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Color.White)
            presentation?.episodeLine?.let { Text(it, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = Color.White) }
            val meta = listOfNotNull(presentation?.year?.toString(), card?.voteAverage?.takeIf { it > 0 }?.let { "%.1f".format(it) },
                card?.genres?.take(2)?.joinToString(", "))
            if (meta.isNotEmpty()) Text(meta.joinToString("  ·  "), fontSize = 13.sp, color = Palette.dim)
            // The episode's, for an episode; the film's, for a film. A tap shows all of it.
            (presentation?.overview ?: card?.overview)?.takeIf { it.isNotEmpty() }?.let {
                Text(it, fontSize = 15.sp, color = Palette.dim, maxLines = if (expanded) Int.MAX_VALUE else 3, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 4.dp).animateContentSize().pressable { expanded = !expanded })
            }
        }
        if (model.info != null) {
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                tabs.forEach { option ->
                    Column(Modifier.width(IntrinsicSize.Max).pressable { tab = option }, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(option, fontSize = 15.sp, fontWeight = if (shownTab == option) FontWeight.Bold else FontWeight.Normal,
                            color = if (shownTab == option) Color.White else Palette.faint, maxLines = 1)
                        Box(Modifier.fillMaxWidth().height(3.dp).background(if (shownTab == option) Palette.accent else Color.Transparent))
                    }
                }
            }
            when (shownTab) {
                "Episodes" -> {
                    val episode = presentation?.episode
                    // Another episode is another list position to start at.
                    if (mediaID != null && episode != null) key(model.request.playID) {
                        PlayerEpisodes(mediaID, episode.season, model.request.playID, stacked = true, onChoose = onEpisode)
                    }
                }
                "About" -> card?.let { show ->
                    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                        // The episode first: it is what is playing. Then the show.
                        if (presentation?.episode != null) {
                            about?.let { EpisodeSection(it) { target -> collection = target } }
                            if (about != null) Box(Modifier.fillMaxWidth().padding(vertical = 6.dp).height(1.dp).background(Color.White.copy(alpha = 0.1f)))
                            Text("About ${show.title}", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
                            // A show's own synopsis: the header has the episode's.
                            show.overview?.takeIf { it.isNotEmpty() }?.let { Text(it, fontSize = 15.sp, color = Palette.dim) }
                        }
                        TitleAbout(show, heading = presentation?.episode == null) { target -> collection = target }
                    }
                } ?: Loading()
                "Similar" -> {
                    LaunchedEffect(mediaID) { mediaID?.let { id -> similar = runCatching { Api.similar(id) }.getOrDefault(emptyList()) } }
                    when (val list = similar) {
                        null -> Loading()
                        emptyList<Card>() -> Text("Nothing like this in the catalog yet", fontSize = 13.sp, color = Palette.faint)
                        else -> Grid(list, 3, 12.dp) { other -> PosterCard(other, width = null) { onTitle(other) } }
                    }
                }
                else -> TrackPanel(model, inline = true)
            }
        }
    }
    collection?.let { target ->
        PeopleSheet(target, onOpen = { collection = null; onTitle(it) }, onClose = { collection = null })
    }
}

/*
 * This episode: when it aired, how long it is and how it is rated, then who
 * directed and wrote it and who guest stars, as the show's About lists its
 * cast. Each name opens what else they are in.
 */
@Composable
private fun EpisodeSection(about: EpisodeAbout, onCollection: (CollectionTarget) -> Unit) {
    fun person(name: String, shown: String = name) = shown to about.personIDs?.get(name)?.let { CollectionTarget(name, personID = it) }
    val meta = buildList {
        about.airDate?.let { runCatching { LocalDate.parse(it) }.getOrNull() }?.let {
            add("Aired " + it.format(DateTimeFormatter.ofPattern("d MMMM yyyy", Locale.getDefault())))
        }
        about.runtime?.takeIf { it > 0 }?.let { add(if (it >= 60) "${it / 60}h ${it % 60}m" else "${it}m") }
        about.voteAverage?.takeIf { it > 0 }?.let { add("%.1f".format(it)) }
    }
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("This Episode", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
        if (meta.isNotEmpty()) Text(meta.joinToString("  ·  "), fontSize = 15.sp, color = Palette.dim)
        about.directors?.takeIf { it.isNotEmpty() }?.let { names ->
            LinkRow(if (names.size == 1) "Directed by" else "Directors", names.map { person(it) }, onCollection)
        }
        about.writers?.takeIf { it.isNotEmpty() }?.let { names -> LinkRow("Written by", names.map { person(it) }, onCollection) }
        about.guestStars?.takeIf { it.isNotEmpty() }?.let { guests ->
            LinkRow("Guest Stars", guests.map { g -> person(g.name, g.character?.let { "${g.name} ($it)" } ?: g.name) }, onCollection)
        }
    }
}

/** A dim label, then names; those with somewhere to go are white and open it. */
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
        text.getStringAnnotations("target", offset, offset).firstOrNull()?.let { values[it.item.toInt()].second?.let(onCollection) }
    }
}

/** A person's titles or a genre's, as a grid over the player; one chosen
 *  leaves the player for its page. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PeopleSheet(target: CollectionTarget, onOpen: (Card) -> Unit, onClose: () -> Unit) {
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
            when (val list = items) {
                null -> Loading()
                emptyList<Card>() -> Text("Nothing in the catalog yet", fontSize = 13.sp, color = Palette.faint)
                else -> Grid(list, 3, 12.dp) { card -> PosterCard(card, width = null) { onOpen(card) } }
            }
        }
    }
}

@Composable
private fun Loading() {
    Box(Modifier.fillMaxWidth().padding(vertical = 30.dp), contentAlignment = Alignment.Center) { BootSpinner(32.dp, 3.dp) }
}
