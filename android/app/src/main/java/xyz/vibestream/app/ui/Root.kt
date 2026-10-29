package xyz.vibestream.app.ui

import kotlinx.coroutines.delay

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.runtime.snapshotFlow
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.ui.graphics.Brush
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.NotificationsNone
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.WifiOff
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import xyz.vibestream.app.AppState
import xyz.vibestream.app.Debug
import xyz.vibestream.app.R
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.Card
import xyz.vibestream.app.api.PlayRequest

class Navigator(
    val open: (Card) -> Unit,
    val play: (PlayRequest) -> Unit,
    val showDownloads: () -> Unit,
)

private val ORDER = listOf("movie", "tv", "search", "mine")

object Pushed {
    val tabs = androidx.compose.runtime.mutableStateMapOf<String, Boolean>()
}

val LocalScrolledUnder = compositionLocalOf<(Boolean) -> Unit> { {} }

@Composable
fun ReportScrolledUnder(list: LazyListState) {
    val report = LocalScrolledUnder.current
    LaunchedEffect(list) { snapshotFlow { list.canScrollBackward }.collect { report(it) } }
}

val TopFade = 28.dp

val LocalTopClearance = compositionLocalOf { 0.dp }

/** What scroll views leave clear at the bottom, above the floating bar. */
val TabBarClearance = 70.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RootView(onPlay: (PlayRequest) -> Unit) {
    var tab by rememberSaveable { mutableStateOf(Debug.string("tab") ?: "movie") }
    var selection by remember { mutableStateOf<Card?>(null) }
    var showingDownloads by remember { mutableStateOf(Debug.has("showDownloads")) }
    var switchingProfile by remember { mutableStateOf(Debug.has("switchProfile")) }
    var showingNotifications by remember { mutableStateOf(Debug.has("notifications")) }
    var introPlayed by rememberSaveable { mutableStateOf(false) }

    // Handed to the title page opened to play, for that opening only.
    var autoplay by remember { mutableStateOf<PlayRequest?>(null) }
    // Play from outside a title's page: the page opens, its picture playing. There is one page for
    // a title, playing or not, so a tile's Play, the hero, Downloads and another device all go
    // there rather than to a player with a page of its own.
    fun openPlaying(request: PlayRequest) {
        AppState.launch {
            val info = runCatching { Api.playInfo(request.playID) }.getOrNull()
            val card = info?.mediaID?.let { runCatching { Api.media(it) }.getOrNull() }
            if (card == null || card.locked == true) { onPlay(request); return@launch }
            // The page's season list lands on the episode playing.
            val episode = info.presentation?.episode
            // One sheet at a time, and the same title's page opened afresh, so it starts playing.
            if (showingDownloads || showingNotifications || selection != null) {
                showingDownloads = false
                showingNotifications = false
                selection = null
                delay(450)
            }
            autoplay = request.copy(season = request.season ?: episode?.season, episode = request.episode ?: episode?.number)
            selection = card
            delay(1_000)
            autoplay = null
        }
    }
    val nav = remember {
        Navigator(
            open = { if (it.locked != true) selection = it },
            play = { openPlaying(it) },
            showDownloads = { showingDownloads = true },
        )
    }

    LaunchedEffect(AppState.profile?.id) {
        Cast.start(AppState.profile?.id)
        Cast.watchElsewhere()
    }
    LaunchedEffect(Cast.target == null) { if (Cast.target == null && AppState.profile != null) AppState.loadFeed() }
    // Cleared on dispose so the handler never keeps a finished activity alive.
    DisposableEffect(Unit) {
        val handler: (CastCommand) -> Unit = { command ->
            command.playID?.let { playID ->
                AppState.launch {
                    val wanted = command.profileID
                    if (wanted != null && wanted != AppState.profile?.id) {
                        AppState.profiles.firstOrNull { it.id == wanted }?.let { AppState.pick(it) }
                    }
                    openPlaying(PlayRequest(playID, command.title.orEmpty(), command.position))
                }
            }
        }
        Cast.onPlay = handler
        onDispose { if (Cast.onPlay === handler) Cast.onPlay = null }
    }
    LaunchedEffect(Unit) {
        AppState.start()
        Debug.string("play")?.let { openPlaying(PlayRequest(it, "Debug", Debug.string("at")?.toDoubleOrNull())) }
        Debug.string("toast")?.let { delay(12_000); Toasts.error(it) }
    }
    // A title chosen in the player (Similar, a name in About) opens here
    // once the player has gone.
    LaunchedEffect(xyz.vibestream.app.PlayerHandOff.title) {
        xyz.vibestream.app.PlayerHandOff.title?.let { selection = it; xyz.vibestream.app.PlayerHandOff.title = null }
    }
    LaunchedEffect(AppState.needsProfilePick) {
        if (AppState.needsProfilePick && AppState.profile != null) switchingProfile = true
    }

    Box(Modifier.fillMaxSize().background(Palette.ground)) {
        when {
            AppState.startingUp -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { BootSpinner() }
            AppState.profile == null && AppState.profiles.isEmpty() && AppState.loadError != null -> StartupFailure()
            AppState.profile == null -> ProfilesView(dismissable = false, onDone = {})
            else -> Tabs(
                tab = tab,
                onTab = { tab = it },
                nav = nav,
                onDownloads = { showingDownloads = true },
                onBell = { showingNotifications = true },
                onProfile = { switchingProfile = true },
            )
        }
        if (!introPlayed && !AppState.startingUp && AppState.profile != null) IntroView { introPlayed = true }
    }

    if (isWide()) {
        androidx.compose.animation.AnimatedVisibility(selection != null, enter = fadeIn(), exit = fadeOut()) {
            Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.7f))
                .pointerInput(Unit) { detectTapGestures { selection = null } }) {}
        }
        selection?.let { card ->
            androidx.activity.compose.BackHandler { selection = null }
            val landscape = androidx.compose.ui.platform.LocalConfiguration.current.orientation ==
                android.content.res.Configuration.ORIENTATION_LANDSCAPE
            Box(Modifier.fillMaxSize().statusBarsPadding().padding(top = 6.dp), contentAlignment = Alignment.TopCenter) {
                androidx.compose.runtime.key(card.mediaID) {
                    Box(Modifier.widthIn(max = if (landscape) 720.dp else 1040.dp).fillMaxSize().padding(horizontal = 14.dp)
                        .clip(RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp)).background(Palette.ground)
                        .pointerInput(Unit) { detectTapGestures { } }) {
                        DetailView(card, nav, autoplay, onClose = { selection = null })
                    }
                }
            }
        }
    } else selection?.let { card ->
        val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        // Read the status bar height in the main window: a sheet's own window can report none (seen on Samsung).
        val statusBar = WindowInsets.statusBars.asPaddingValues().calculateTopPadding()
        ModalBottomSheet(
            onDismissRequest = { selection = null },
            sheetState = sheet,
            containerColor = Palette.ground,
            dragHandle = null,
            contentWindowInsets = { WindowInsets(0) },
            modifier = Modifier.padding(top = statusBar),
        ) {
            androidx.compose.runtime.key(card.mediaID) {
                DetailView(card, nav, autoplay, onClose = { selection = null })
            }
        }
    }
    if (showingDownloads) {
        ModalBottomSheet(onDismissRequest = { showingDownloads = false }, containerColor = Palette.ground) {
            DownloadsView(nav)
        }
    }
    // After an update, once: what is new for whoever is watching.
    AppState.news?.let { news ->
        ModalBottomSheet(onDismissRequest = { AppState.newsSeen() }, containerColor = Palette.ground) {
            WhatsNewSheet(news) { AppState.newsSeen() }
        }
    }
    if (showingNotifications) {
        ModalBottomSheet(onDismissRequest = { showingNotifications = false }, containerColor = Palette.ground) {
            NotificationsList(
                onOpen = { card -> showingNotifications = false; selection = card },
                onDownloads = { showingNotifications = false; showingDownloads = true },
                onClose = { showingNotifications = false },
            )
        }
    }
    if (Cast.remoteShown) {
        ModalBottomSheet(onDismissRequest = { Cast.remoteShown = false }, containerColor = Palette.ground,
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
            CastRemote(onClose = { Cast.remoteShown = false }, onTitle = { Cast.remoteShown = false; selection = it })
        }
    }
    if (switchingProfile) {
        ModalBottomSheet(onDismissRequest = { switchingProfile = false }, containerColor = Palette.ground) {
            ProfilesView(dismissable = true, onDone = { switchingProfile = false })
        }
    }
}

@Composable
private fun Tabs(
    tab: String,
    onTab: (String) -> Unit,
    nav: Navigator,
    onDownloads: () -> Unit,
    onBell: () -> Unit,
    onProfile: () -> Unit,
) {
    val keyboard = WindowInsets.ime.getBottom(LocalDensity.current) > 0 || OnScreenKeyboard.up
    LaunchedEffect(tab) { if (tab == "mine") AppState.loadClips() }

    Box(Modifier.fillMaxSize()) {
        val shown = ORDER.indexOf(tab)
        ORDER.forEachIndexed { index, value ->
            val chosen = index == shown
            val alpha by animateFloatAsState(if (chosen) 1f else 0f, if (chosen) spring() else tween(160), label = "a")
            val shift by animateFloatAsState(if (chosen) 0f else if (index < shown) -34f else 34f, spring(), label = "x")
            Box(
                Modifier.fillMaxSize().graphicsLayer { this.alpha = alpha; translationX = shift * density }
                    .then(if (chosen) Modifier else Modifier.alpha(0f)),
            ) {
                if (chosen || alpha > 0f) {
                    val barred = Pushed.tabs[value] != true
                    var barHeight by remember { mutableStateOf(0.dp) }
                    var under by remember { mutableStateOf(false) }
                    val shade by animateFloatAsState(if (under) 1f else 0f, tween(180), label = "shade")
                    val density = LocalDensity.current
                    Box(Modifier.fillMaxSize()) {
                        CompositionLocalProvider(
                            LocalTopClearance provides if (barred) barHeight else 0.dp,
                            LocalScrolledUnder provides { under = it },
                        ) {
                            when (value) {
                                "movie" -> HomeView("movie", nav)
                                "tv" -> HomeView("tv", nav)
                                "search" -> SearchView(nav, active = chosen)
                                else -> LibraryView(nav)
                            }
                        }
                        if (barred) {
                            val fade = if (value == "search") 0.dp else TopFade
                            Box(
                                Modifier.fillMaxWidth().height(barHeight + fade).alpha(shade).background(
                                    Brush.verticalGradient(
                                        0f to Palette.ground.copy(alpha = 0.97f),
                                        (barHeight / (barHeight + fade)).coerceIn(0f, 1f) to Palette.ground.copy(alpha = 0.8f),
                                        1f to Color.Transparent,
                                    ),
                                ),
                            )
                            TopBar(
                                title = when (value) { "movie" -> "Movies"; "tv" -> "Shows"; "search" -> "Search"; else -> "Library" },
                                onDownloads = onDownloads, onBell = onBell, onProfile = onProfile,
                                modifier = Modifier.onSizeChanged { barHeight = with(density) { it.height.toDp() } },
                            )
                        }
                    }
                }
            }
        }

        // Hidden while a keyboard is up: the keyboard has its own background and must never be shaded.
        val nav = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
        val fade = 64.dp
        if (!keyboard) Box(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(fade + nav).background(
                Brush.verticalGradient(
                    0f to Color.Transparent,
                    fade / (fade + nav) to Palette.ground.copy(alpha = 0.92f),
                    1f to Palette.ground,
                ),
            ),
        )

        AnimatedVisibility(!keyboard, Modifier.align(Alignment.BottomCenter), enter = fadeIn(), exit = fadeOut()) {
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
                CastBar()
                AppTabBar(tab, AppState.profile?.avatar, onTab)
            }
        }
    }
}

@Composable
private fun TopBar(title: String, onDownloads: () -> Unit, onBell: () -> Unit, onProfile: () -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().statusBarsPadding().padding(start = 18.dp, end = 10.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        VMark(22.dp)
        Text(title, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Color.White,
            modifier = Modifier.padding(start = 10.dp).weight(1f))
        Box(Modifier.size(44.dp).pressable(onClick = onDownloads), contentAlignment = Alignment.Center) {
            Icon(painterResource(R.drawable.ic_download), "My Downloads", tint = Color.White, modifier = Modifier.size(21.dp))
        }
        NotificationsBell(onBell)
        Box(Modifier.size(44.dp).pressable(onClick = onProfile), contentAlignment = Alignment.Center) {
            Avatar(AppState.profile?.avatar, 30.dp)
        }
    }
}

@Composable
private fun AppTabBar(tab: String, avatar: String?, onTab: (String) -> Unit) {
    Box(Modifier.fillMaxWidth().navigationBarsPadding().padding(start = 18.dp, end = 18.dp, top = 2.dp, bottom = 10.dp), contentAlignment = Alignment.Center) {
        Row(
            Modifier.widthIn(max = 420.dp).fillMaxWidth()
                .shadow(18.dp, CircleShape, ambientColor = Color.Black, spotColor = Color.Black)
                .background(Color(0xFF161616), CircleShape)
                .border(1.dp, Color.White.copy(alpha = 0.09f), CircleShape)
                .padding(3.dp),
            horizontalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            listOf("movie" to "Movies", "tv" to "Shows", "search" to "Search", "mine" to "Library").forEach { (value, label) ->
                val chosen = tab == value
                val pill by animateColorAsState(if (chosen) Color(0xFF2B2B2B) else Color.Transparent, label = "pill")
                val tint = if (chosen) Color.White else Color(0xFF9E9E9E)
                Column(
                    Modifier.weight(1f).background(pill, CircleShape).pressable { onTab(value) }.padding(vertical = 5.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(1.dp),
                ) {
                    Box(Modifier.height(21.dp), contentAlignment = Alignment.Center) {
                        when (value) {
                            "movie" -> Icon(Icons.Outlined.Movie, null, tint = tint, modifier = Modifier.size(21.dp))
                            "tv" -> Icon(painterResource(R.drawable.ic_shows), null, tint = tint, modifier = Modifier.size(21.dp))
                            "search" -> Icon(Icons.Outlined.Search, null, tint = tint, modifier = Modifier.size(21.dp))
                            else -> Avatar(avatar, 21.dp)
                        }
                    }
                    Text(label, fontSize = 10.sp, lineHeight = 12.sp, fontWeight = FontWeight.Medium, color = tint, maxLines = 1)
                }
            }
        }
    }
}

@Composable
private fun StartupFailure() {
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(Icons.Outlined.WifiOff, null, tint = Palette.faint, modifier = Modifier.size(40.dp))
        Text("Can't reach VibeStream", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White,
            modifier = Modifier.padding(top = 14.dp))
        Text("Check that the server is running and that this device is online.", fontSize = 15.sp,
            color = Palette.dim, textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            modifier = Modifier.padding(top = 14.dp))
        Pill(true, Modifier.padding(top = 20.dp).widthIn(min = 160.dp), onClick = { AppState.retryStartup() }) {
            PillLabel("Try Again")
        }
    }
}
