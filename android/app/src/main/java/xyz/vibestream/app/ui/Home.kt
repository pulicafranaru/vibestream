package xyz.vibestream.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.outlined.VideoLibrary
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import xyz.vibestream.app.AppState
import xyz.vibestream.app.Debug
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.Card
import xyz.vibestream.app.api.GenreCount
import xyz.vibestream.app.api.HomeRow
import xyz.vibestream.app.api.PlayRequest

@Composable
fun isWide(): Boolean = LocalConfiguration.current.smallestScreenWidthDp >= 600

@Composable
fun posterWidth(): Dp = if (isWide()) Metrics.posterWidthPad else Metrics.posterWidth

sealed class BrowseTarget(val title: String, val mediaType: String? = null, val isFlat: Boolean = false) {
    data object Movies : BrowseTarget("Movies", "movie")
    data object Shows : BrowseTarget("Shows", "tv")
    data object NewAndHot : BrowseTarget("New & Hot")
    data class Genre(val name: String) : BrowseTarget(name, isFlat = true)
    data class Category(val name: String, val kind: String) : BrowseTarget(name, isFlat = true)
}

/** Only genres with enough titles behind them are offered as chips. */
private const val GENRE_MINIMUM = 12
private const val GENRE_LIMIT = 18

@Composable
fun HomeView(kind: String, nav: Navigator) {
    var destination by remember { mutableStateOf<BrowseTarget?>(null) }
    var genres by remember { mutableStateOf<List<GenreCount>>(emptyList()) }
    val wide = isWide()
    val width = posterWidth()

    LaunchedEffect(kind) {
        if (genres.isEmpty()) {
            genres = runCatching { Api.genres(kind) }.getOrDefault(emptyList()).filter { it.count >= GENRE_MINIMUM }
        }
        Debug.int("media")?.let { id -> runCatching { Api.media(id) }.getOrNull()?.let(nav.open) }
        Debug.string("browse")?.let {
            destination = when (it) {
                "movies" -> BrowseTarget.Movies
                "shows" -> BrowseTarget.Shows
                "new" -> BrowseTarget.NewAndHot
                else -> BrowseTarget.Genre(it)
            }
        }
    }

    LaunchedEffect(destination) { Pushed.tabs[kind] = destination != null }
    destination?.let { target ->
        BackHandler { destination = null }
        BrowseView(target, nav, onBack = { destination = null })
        return
    }

    val rows = AppState.rows(kind)
    val list = rememberLazyListState()
    ReportScrolledUnder(list)
    LaunchedEffect(rows.size) {
        if (Debug.has("scrollEnd") && rows.isNotEmpty()) list.scrollToItem(rows.size + 2)
    }
    Refreshable({ AppState.loadFeed() }, Modifier.fillMaxSize()) {
        LazyColumn(
            state = list,
            verticalArrangement = Arrangement.spacedBy(22.dp),
            contentPadding = PaddingValues(top = 4.dp + LocalTopClearance.current, bottom = 24.dp + TabBarClearance),
        ) {
            AppState.feeds[kind]?.hero?.let { hero ->
                item("hero") {
                    Box(Modifier.padding(horizontal = if (wide) 0.dp else 12.dp)) { HeroSection(hero, nav) }
                }
            }
            item("elsewhere") { PlayingElsewhereRow(if (wide) 340.dp else 260.dp) }
            if (rows.none { it.id == "continue" }) item("chips") { Chips(genres) { destination = BrowseTarget.Category(it, kind) } }
            rows.forEach { row ->
                if (row.id == "continue") {
                    item(row.id) {
                        CardRow("Resume Watching", row.items) { card ->
                            ContinueCard(card, width * 1.2f, onPlay = { resume(card, nav) })
                        }
                    }
                    item("chips") { Chips(genres) { destination = BrowseTarget.Category(it, kind) } }
                } else {
                    item(row.id) { CardRow(row.title, row.items) { card -> PosterCard(card, width) { nav.open(card) } } }
                }
            }
            if (rows.isEmpty() && !AppState.loading) item("empty") { Empty(AppState.loadError ?: "Nothing in the catalog yet") }
        }
        if (AppState.loading && AppState.feeds[kind] == null) Box(Modifier.align(Alignment.Center)) { BootSpinner() }
    }
}

/** Prefer the play id: for a show it names the episode last stopped on. */
fun resume(card: Card, nav: Navigator) {
    when {
        card.resumePlayID != null -> nav.play(PlayRequest(card.resumePlayID, card.resumeTitle))
        card.playableDownloadID != null -> nav.play(PlayRequest(card.playableDownloadID.toString(), card.title))
        else -> nav.open(card)
    }
}

@Composable
private fun Chips(genres: List<GenreCount>, onPick: (String) -> Unit) {
    if (genres.isEmpty()) return
    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), contentPadding = PaddingValues(horizontal = 16.dp)) {
        items(genres.take(GENRE_LIMIT), key = { it.name }) { genre ->
            val colour = GenreColor.of(genre.name)
            Box(
                Modifier.height(58.dp).widthIn(min = 112.dp)
                    .background(Palette.chip, RoundedCornerShape(10.dp))
                    .background(Brush.linearGradient(listOf(colour.copy(alpha = 0.42f), colour.copy(alpha = 0.12f))), RoundedCornerShape(10.dp))
                    .pressable { onPick(genre.name) }
                    .padding(horizontal = 20.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(genre.name.uppercase(), fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Color.White,
                    letterSpacing = 0.4.sp, maxLines = 1)
            }
        }
    }
}

@Composable
fun Empty(text: String) {
    Column(Modifier.fillMaxWidth().padding(top = 60.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Icon(Icons.Outlined.VideoLibrary, null, tint = Palette.faint, modifier = Modifier.size(36.dp))
        Text(text, fontSize = 15.sp, color = Palette.dim, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 10.dp))
    }
}

@Composable
fun HeroSection(card: Card, nav: Navigator) {
    var queuing by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val live = card.primaryReleaseID?.let { AppState.downloads[it] } ?: card.download

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        HeroCard(
            card = card,
            wide = isWide(),
            download = live,
            busy = queuing,
            saved = card.mediaID in AppState.myList,
            onPlay = {
                if (card.isSeries) {
                    card.resumePlayID?.let { nav.play(PlayRequest(it, card.title)) } ?: nav.open(card)
                } else {
                    (live?.id ?: card.playableDownloadID)?.let { nav.play(PlayRequest(it.toString(), card.title)) }
                }
            },
            onDownload = {
                val torrent = card.primaryReleaseID ?: return@HeroCard
                queuing = true
                scope.launch {
                    runCatching { AppState.download(torrent) }.onFailure { Toasts.error(it.said()) }
                    queuing = false
                }
            },
            onInfo = { nav.open(card) },
            onMyList = { AppState.toggleMyList(card) },
        )
    }
}

@Composable
fun BrowseView(target: BrowseTarget, nav: Navigator, onBack: () -> Unit) {
    var rows by remember { mutableStateOf<List<HomeRow>>(emptyList()) }
    var hero by remember { mutableStateOf<Card?>(null) }
    var flat by remember { mutableStateOf<List<Card>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var failure by remember { mutableStateOf<String?>(null) }
    var categories by remember { mutableStateOf<List<GenreCount>>(emptyList()) }
    var category by rememberSaveable { mutableStateOf<String?>(null) }
    val wide = isWide()
    val width = posterWidth()
    val grid = target.isFlat || category != null

    LaunchedEffect(target) {
        target.mediaType?.let { kind ->
            categories = runCatching { Api.genres(kind) }.getOrDefault(emptyList())
            Debug.string("category")?.let { category = it }
        }
    }
    LaunchedEffect(target, category) {
        loading = true
        val asked = category
        try {
            fun pickHero(items: List<Card>) {
                hero = items.firstOrNull { it.backdrop != null && it.overview != null }
                flat = items.filterNot { it.mediaID == hero?.mediaID }
            }
            if (asked != null && target.mediaType != null) {
                val items = Api.catalog(genre = asked, mediaType = target.mediaType)
                if (asked == category) { rows = emptyList(); pickHero(items) }
            } else {
                flat = emptyList()
                when (target) {
                    BrowseTarget.Movies, BrowseTarget.Shows -> {
                        val feed = Api.home(target.mediaType)
                        rows = feed.rows.filter { it.items.isNotEmpty() }
                        hero = feed.hero
                    }
                    BrowseTarget.NewAndHot -> {
                        val feed = Api.home()
                        rows = feed.rows.filter { it.id in setOf("recent", "new", "uhd") && it.items.isNotEmpty() }
                        hero = rows.firstOrNull()?.items?.firstOrNull { it.backdrop != null }
                    }
                    is BrowseTarget.Category -> pickHero(Api.catalog(genre = target.name, mediaType = target.kind))
                    is BrowseTarget.Genre -> pickHero(Api.catalog(genre = target.name))
                }
            }
            failure = null
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            failure = e.message
        } finally {
            loading = false
        }
    }

    Column(Modifier.fillMaxSize()) {
        PushedBar(target.title, onBack)
        Box(Modifier.fillMaxSize()) {
            if (grid) {
                LazyVerticalGrid(
                    columns = if (wide) GridCells.Adaptive(width) else GridCells.Fixed(3),
                    horizontalArrangement = Arrangement.spacedBy(if (wide) 12.dp else 8.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                    contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 24.dp + TabBarClearance),
                ) {
                    if (target.mediaType != null && categories.isNotEmpty()) {
                        item(span = { GridItemSpan(maxLineSpan) }) {
                            Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                                CategoriesMenu(target, categories, category) { category = it }
                            }
                        }
                    }
                    hero?.let { h -> item(span = { GridItemSpan(maxLineSpan) }) { HeroSection(h, nav) } }
                    items(flat, key = { it.mediaID }) { card -> PosterCard(card, width = null) { nav.open(card) } }
                    if (!loading && flat.isEmpty() && hero == null) {
                        item(span = { GridItemSpan(maxLineSpan) }) { Empty(failure ?: "Nothing here yet") }
                    }
                }
            } else {
                LazyColumn(
                    verticalArrangement = Arrangement.spacedBy(20.dp),
                    contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp + TabBarClearance),
                ) {
                    if (target.mediaType != null && categories.isNotEmpty()) {
                        item {
                            Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                                CategoriesMenu(target, categories, category) { category = it }
                            }
                        }
                    }
                    hero?.let { h -> item { Box(Modifier.padding(horizontal = if (wide) 0.dp else 12.dp)) { HeroSection(h, nav) } } }
                    items(rows, key = { it.id }) { row ->
                        CardRow(row.title, row.items) { card -> PosterCard(card, width) { nav.open(card) } }
                    }
                    if (!loading && rows.isEmpty()) item { Empty(failure ?: "Nothing here yet") }
                }
            }
            if (loading) Box(Modifier.align(Alignment.Center)) { BootSpinner() }
        }
    }
}

@Composable
fun PushedBar(title: String, onBack: () -> Unit) {
    Box(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 12.dp, vertical = 6.dp)) {
        Box(
            Modifier.align(Alignment.CenterStart).size(44.dp).background(Palette.fill, CircleShape).pressable(onClick = onBack),
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Color.White) }
        Text(title, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White, modifier = Modifier.align(Alignment.Center))
    }
}

@Composable
private fun CategoriesMenu(target: BrowseTarget, categories: List<GenreCount>, chosen: String?, onPick: (String?) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val all = if (target == BrowseTarget.Movies) "All Movies" else "All Shows"
    Box {
        Row(
            Modifier.background(Palette.fill, CircleShape).pressable { open = true }.padding(horizontal = 18.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(chosen ?: "Categories", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
            Icon(Icons.Filled.ArrowDropDown, null, tint = Color.White)
        }
        DropdownMenu(open, onDismissRequest = { open = false }, containerColor = Color(0xFF242424)) {
            DropdownMenuItem(text = { Text(all) }, onClick = { onPick(null); open = false },
                leadingIcon = { if (chosen == null) Icon(Icons.Filled.Check, null) })
            HorizontalDivider()
            categories.forEach { genre ->
                DropdownMenuItem(text = { Text(genre.name) }, onClick = { onPick(genre.name); open = false },
                    leadingIcon = { if (chosen == genre.name) Icon(Icons.Filled.Check, null) })
            }
        }
    }
}
