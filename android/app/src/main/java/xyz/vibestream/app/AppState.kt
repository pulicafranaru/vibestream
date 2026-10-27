package xyz.vibestream.app

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.Card
import xyz.vibestream.app.api.Clip
import xyz.vibestream.app.api.DownloadState
import xyz.vibestream.app.api.HomeFeed
import xyz.vibestream.app.api.HomeRow
import xyz.vibestream.app.api.Profile
import xyz.vibestream.app.ui.AvatarArt
import xyz.vibestream.app.ui.Cast

object AppState {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var store: SharedPreferences

    var profiles by mutableStateOf<List<Profile>>(emptyList())
    var profile by mutableStateOf<Profile?>(null)
    var needsProfilePick by mutableStateOf(false)
    /** PIN for the active profile, used in the cast hello. Kept in memory only. */
    var profilePin: String? = null
    var notificationsSeen by mutableStateOf("")
    var avatarChoices by mutableStateOf(AvatarArt.all)

    var feed by mutableStateOf<HomeFeed?>(null)
    var feeds by mutableStateOf<Map<String, HomeFeed>>(emptyMap())
    var library by mutableStateOf<HomeFeed?>(null)
    var loading by mutableStateOf(false)
    var loadError by mutableStateOf<String?>(null)
    var startingUp by mutableStateOf(true)

    val downloads = mutableStateMapOf<Int, DownloadState>()
    /** media id to -1 (not for me) or 1 (like it). */
    val ratings = mutableStateMapOf<Int, Int>()
    var myList by mutableStateOf<Set<Int>>(emptySet())
    var clips by mutableStateOf<List<Clip>>(emptyList())
    val lastSeason = mutableStateMapOf<Int, Int>()

    private var poll: Job? = null
    // Same key as iOS.
    private const val STORED_PROFILE = "vibestream.profile"

    fun init(context: Context) {
        store = context.getSharedPreferences("vibestream", Context.MODE_PRIVATE)
    }

    // Runs outside the caller's scope: picking a profile closes the profile screen and would cancel it.
    private suspend fun detached(block: suspend CoroutineScope.() -> Unit) = scope.launch(block = block).join()

    fun start() {
        scope.launch {
            loadProfiles()
            startPolling()
        }
    }

    suspend fun loadProfiles(keepingSelection: Boolean = false) = detached {
        try {
            val response = Api.profiles()
            val list = response.profiles
            profiles = list
            response.avatars?.takeIf { it.isNotEmpty() }?.let { avatarChoices = it }
            if (keepingSelection) {
                profile?.let { current -> list.firstOrNull { it.id == current.id }?.let { profile = it } }
                return@detached
            }
            if (Debug.has("askPin")) {
                needsProfilePick = true
                return@detached
            }
            Debug.int("profile")?.let { id ->
                list.firstOrNull { it.id == id }?.let { pick(it); return@detached }
            }
            val stored = store.getInt(STORED_PROFILE, 0)
            val found = list.firstOrNull { it.id == stored }
            when {
                found != null -> pick(found)
                list.size == 1 && !list[0].locked -> pick(list[0])
                else -> needsProfilePick = true
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            loadError = e.message
            needsProfilePick = true
        } finally {
            startingUp = false
        }
    }

    fun retryStartup() {
        loadError = null
        startingUp = true
        scope.launch { loadProfiles() }
    }

    suspend fun profileWasDeleted(id: Int) = detached {
        val wasActive = profile?.id == id
        loadProfiles(keepingSelection = !wasActive)
        if (!wasActive) return@detached
        val next = profiles.firstOrNull()
        if (next != null && !next.locked) pick(next) else {
            profile = null
            needsProfilePick = true
        }
    }

    suspend fun pick(chosen: Profile, pin: String? = null) = detached {
        if (profile?.id != chosen.id || pin != null) profilePin = pin
        if (profile?.id != chosen.id) {
            feed = null
            feeds = emptyMap()
            library = null
            ratings.clear()
            myList = emptySet()
            clips = emptyList()
            lastSeason.clear()
        }
        loading = true
        profile = chosen
        needsProfilePick = false
        store.edit().putInt(STORED_PROFILE, chosen.id).apply()
        notificationsSeen = store.getString(seenKey(), "").orEmpty()
        Api.profileID = chosen.id
        loadRatings()
        loadMyList()
        loadClips()
        loadFeed()
    }

    private fun still(id: Int?) = profile?.id == id

    suspend fun loadFeed() = detached {
        val id = profile?.id
        loading = true
        try {
            val all = scope.async { Api.home() }
            val movies = scope.async { Api.home("movie") }
            val shows = scope.async { Api.home("tv") }
            val main = all.await()
            val typed = mapOf("movie" to movies.await(), "tv" to shows.await())
            val mine = runCatching { Api.mine() }.getOrNull()
            if (!still(id)) return@detached
            feed = main
            feeds = typed
            mine?.let { library = it }
            loadError = null
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            if (still(id)) loadError = e.message
        } finally {
            if (still(id)) loading = false
        }
    }

    val rows: List<HomeRow> get() = feed?.rows.orEmpty().filter { it.items.isNotEmpty() }

    fun rows(kind: String): List<HomeRow> = feeds[kind]?.rows.orEmpty().filter { it.items.isNotEmpty() }

    private fun seenKey() = "vibestream.notifications.seen.${profile?.id ?: 0}"

    fun markNotificationsSeen(newest: String) {
        if (newest <= notificationsSeen) return
        notificationsSeen = newest
        store.edit().putString(seenKey(), newest).apply()
    }

    @Serializable
    data class PlayerPrefs(
        val subtitleLanguage: String? = null,
        val subtitlesOff: Boolean = false,
        val speed: Float = 1f,
        val subtitleSize: String = "medium",
        val subtitleStyle: String = "shadow",
    )

    private fun prefsKey() = "vibestream.player.${profile?.id ?: Api.profileID ?: 0}"

    var playerPrefs: PlayerPrefs
        get() = store.getString(prefsKey(), null)
            ?.let { runCatching { Api.json.decodeFromString(PlayerPrefs.serializer(), it) }.getOrNull() }
            ?: PlayerPrefs()
        set(value) {
            store.edit().putString(prefsKey(), Api.json.encodeToString(PlayerPrefs.serializer(), value)).apply()
        }

    suspend fun loadRatings() {
        val p = profile ?: return
        val raw = runCatching { Api.ratings(p.id) }.getOrNull() ?: return
        if (!still(p.id)) return
        ratings.clear()
        raw.forEach { (k, v) -> k.toIntOrNull()?.let { ratings[it] = v } }
    }

    fun rate(mediaID: Int, value: Int) {
        val p = profile ?: return
        val next = if (ratings[mediaID] == value) 0 else value
        if (next == 0) ratings.remove(mediaID) else ratings[mediaID] = next
        scope.launch { Api.rate(p.id, mediaID, next) }
    }

    suspend fun loadClips() {
        val id = profile?.id
        runCatching { Api.clips() }.getOrNull()?.let { if (still(id)) clips = it }
    }

    suspend fun saveClip(playID: String, start: Double, end: Double): Clip {
        val id = profile?.id
        val clip = Api.saveClip(playID, start, end)
        if (still(id)) clips = listOf(clip) + clips
        return clip
    }

    fun deleteClip(clip: Clip) {
        clips = clips.filterNot { it.id == clip.id }
        scope.launch { runCatching { Api.deleteClip(clip.id) }.onFailure { loadClips() } }
    }

    suspend fun loadMyList() {
        val p = profile ?: return
        runCatching { Api.myListIDs(p.id) }.getOrNull()?.let { if (still(p.id)) myList = it.toSet() }
    }

    fun toggleMyList(card: Card) {
        val p = profile ?: return
        val adding = card.mediaID !in myList
        apply(card, adding)
        scope.launch {
            runCatching { Api.setInMyList(p.id, card.mediaID, adding) }.onFailure { if (still(p.id)) apply(card, !adding) }
        }
    }

    private fun apply(card: Card, adding: Boolean) {
        myList = if (adding) myList + card.mediaID else myList - card.mediaID
        feed = feed?.let { patched(it, card, adding) }
        val kind = card.mediaType
        val typed = kind?.let { feeds[it] }
        if (kind != null && typed != null) feeds = feeds + (kind to patched(typed, card, adding))
    }

    private fun patched(feed: HomeFeed, card: Card, adding: Boolean): HomeFeed {
        val rows = feed.rows.toMutableList()
        val index = rows.indexOfFirst { it.id == "mylist" }
        if (index >= 0) {
            val items = rows[index].items.filterNot { it.mediaID == card.mediaID }
            rows[index] = rows[index].copy(items = if (adding) listOf(card) + items else items)
        } else if (adding) {
            val after = rows.indexOfFirst { it.id == "continue" }.let { if (it >= 0) it + 1 else 0 }
            rows.add(after, HomeRow("mylist", "Watchlist", "mylist", listOf(card)))
        }
        return feed.copy(rows = rows)
    }

    private var pollWanted = false
    private var foreground = false

    fun setForeground(on: Boolean) {
        foreground = on
        if (on) { if (pollWanted) startPolling() } else { poll?.cancel(); poll = null }
        Cast.setForeground(on)
    }

    fun startPolling() {
        pollWanted = true
        poll?.cancel()
        poll = null
        if (!foreground) return
        poll = scope.launch {
            while (isActive) {
                var active = false
                runCatching { Api.downloads() }.getOrNull()?.let { rows ->
                    val map = rows.associateBy { it.torrentID }
                    active = rows.any { it.isWorking || it.isPreparing }
                    downloads.keys.retainAll(map.keys)
                    downloads.putAll(map)
                }
                delay(if (active) 2_000 else 15_000)
            }
        }
    }

    suspend fun download(torrent: Int, episode: Int? = null, everything: Boolean = false): DownloadState {
        val started = Api.startDownload(torrent, episode, everything)
        downloads[started.torrentID] = started
        startPolling()
        return started
    }

    suspend fun cancel(downloadID: Int, torrent: Int) {
        Api.deleteDownload(downloadID)
        downloads.remove(torrent)
        startPolling()
    }

    suspend fun refreshDownloads() {
        val rows = runCatching { Api.downloads() }.getOrNull() ?: return
        val map = rows.associateBy { it.torrentID }
        downloads.keys.retainAll(map.keys)
        downloads.putAll(map)
    }

    fun launch(block: suspend CoroutineScope.() -> Unit) = scope.launch(block = block)
}
