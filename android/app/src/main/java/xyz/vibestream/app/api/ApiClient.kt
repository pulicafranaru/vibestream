package xyz.vibestream.app.api

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import okhttp3.Cache
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import xyz.vibestream.app.BuildConfig
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

// Public URL first, then LAN (some routers refuse to resolve the public name to a private IP).
// The answering one is kept until a connection fails, then re-probed at most every 15 s.
object Server {
    val candidates: List<String> = listOf(BuildConfig.PUBLIC_URL, BuildConfig.LAN_URL)
        .filter { it.isNotBlank() }
        .map { it.trimEnd('/') }
}

class ApiException(val code: Int, private val body: String) : IOException() {
    override val message: String
        get() {
            runCatching {
                val detail = Api.json.parseToJsonElement(body).jsonObject["detail"]?.jsonPrimitive?.content
                if (!detail.isNullOrEmpty()) return detail.replaceFirstChar { it.uppercase() }
            }
            if (code >= 500) return "The server had a problem. Try again in a moment."
            return "The server said no ($code)."
        }
}

class UnreachableException : IOException("Cannot reach the VibeStream server on this network.")

object Api {
    val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        coerceInputValues = true
    }

    @Volatile private var base: String? = null
    @Volatile private var baseOrigin: HttpUrl? = null
    @Volatile private var stale = false
    private var probedAt = 0L
    private val probing = Mutex()
    @Volatile var profileID: Int? = null

    /** A generic browser string: requests must not identify the app. */
    private const val USER_AGENT =
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    private const val REPROBE_AFTER_MS = 15_000L
    private const val PROFILE_HEADER = "X-VibeStream-Profile"

    private fun isServer(url: HttpUrl): Boolean {
        val origin = baseOrigin ?: return false
        return url.scheme == origin.scheme && url.host == origin.host && url.port == origin.port
    }

    lateinit var http: OkHttpClient
        private set

    fun init(cacheDir: File) {
        http = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .cache(Cache(File(cacheDir, "http"), 256L shl 20))
            // A failed connection may mean the network changed: re-probe on the next request.
            .addInterceptor { chain ->
                try {
                    chain.proceed(chain.request())
                } catch (e: IOException) {
                    if (!chain.call().isCanceled() && isServer(chain.request().url)) stale = true
                    throw e
                }
            }
            // Added per hop, so a redirect never carries the profile to another host.
            .addNetworkInterceptor { chain ->
                val request = chain.request()
                val builder = request.newBuilder().header("User-Agent", USER_AGENT)
                // A header rather than a query param, so it stays out of the HLS URLs the server rewrites.
                if (!isServer(request.url)) builder.removeHeader(PROFILE_HEADER)
                else if (request.header(PROFILE_HEADER) == null) profileID?.let { builder.header(PROFILE_HEADER, it.toString()) }
                chain.proceed(builder.build())
            }
            .build()
    }

    suspend fun baseURL(): String = probing.withLock {
        val known = base
        val now = System.currentTimeMillis()
        if (known != null && (!stale || now - probedAt < REPROBE_AFTER_MS)) return known
        probedAt = now
        for (candidate in Server.candidates) {
            if (reachable(candidate)) {
                base = candidate
                baseOrigin = candidate.toHttpUrl()
                stale = false
                return candidate
            }
        }
        if (known != null) stale = true
        throw UnreachableException()
    }

    private suspend fun reachable(url: String): Boolean = withContext(Dispatchers.IO) {
        runCatching {
            val quick = http.newBuilder().callTimeout(5, TimeUnit.SECONDS).build()
            quick.newCall(Request.Builder().url("$url/tv-ping.gif").header("Cache-Control", "no-cache").build())
                .execute().use { it.code == 200 }
        }.getOrDefault(false)
    }

    fun absolute(path: String?): String? {
        if (path == null || path.startsWith("http://") || path.startsWith("https://")) return path
        val root = base ?: return null
        return root + (if (path.startsWith("/")) path else "/$path")
    }

    suspend fun url(path: String): String {
        if (path.startsWith("http://") || path.startsWith("https://")) return path
        return baseURL() + (if (path.startsWith("/")) path else "/$path")
    }

    private suspend fun build(path: String, query: Map<String, String>): HttpUrl {
        val builder = (baseURL() + path).toHttpUrl().newBuilder()
        query.forEach { (k, v) -> builder.addQueryParameter(k, v) }
        return builder.build()
    }

    private suspend fun raw(
        path: String,
        query: Map<String, String> = emptyMap(),
        method: String = "GET",
        body: JsonObject? = null,
        headers: Map<String, String> = emptyMap(),
    ): String = withContext(Dispatchers.IO) {
        val url = build(path, query)
        val requestBody = when {
            body != null -> body.toString().toRequestBody("application/json".toMediaType())
            method == "GET" || method == "DELETE" -> null
            else -> ByteArray(0).toRequestBody(null)
        }
        val request = Request.Builder().url(url).method(method, requestBody).apply {
            headers.forEach { (k, v) -> header(k, v) }
        }.build()
        http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) throw ApiException(response.code, text)
            text
        }
    }

    private suspend fun <T> get(
        serializer: KSerializer<T>, path: String, query: Map<String, String> = emptyMap(),
        method: String = "GET", body: JsonObject? = null,
    ): T = json.decodeFromString(serializer, raw(path, query, method, body))

    suspend fun home(mediaType: String? = null) =
        get(HomeFeed.serializer(), "/api/catalog/home", mediaType?.let { mapOf("media_type" to it) } ?: emptyMap())

    suspend fun mine() = get(HomeFeed.serializer(), "/api/catalog/mine")

    suspend fun media(id: Int) = get(Card.serializer(), "/api/catalog/media/$id")

    suspend fun similar(id: Int) = get(CatalogPage.serializer(), "/api/catalog/media/$id/similar").items

    suspend fun person(id: Int) = get(PersonPage.serializer(), "/api/catalog/person/$id")

    suspend fun episodeAbout(id: Int) = get(EpisodeAbout.serializer(), "/api/catalog/episodes/$id/about")

    suspend fun search(term: String, limit: Int = 40) =
        get(CatalogPage.serializer(), "/api/catalog", mapOf("q" to term, "limit" to "$limit")).items

    suspend fun spoken(heard: List<String>): String {
        val body = buildJsonObject { putJsonArray("heard") { heard.forEach { add(JsonPrimitive(it)) } } }
        val answer = json.parseToJsonElement(raw("/api/catalog/spoken", method = "POST", body = body))
        return answer.jsonObject["term"]?.jsonPrimitive?.content.orEmpty()
    }

    suspend fun season(media: Int, number: Int) =
        get(SeasonDetail.serializer(), "/api/catalog/media/$media/seasons/$number")

    suspend fun genres(mediaType: String? = null): List<GenreCount> {
        val query = mediaType?.let { mapOf("media_type" to it, "order" to "name") } ?: emptyMap()
        return get(ListSerializer(GenreCount.serializer()), "/api/catalog/genres", query)
    }

    suspend fun catalog(genre: String? = null, mediaType: String? = null, sort: String = "popular", limit: Int = 120): List<Card> {
        val query = buildMap {
            put("limit", "$limit")
            put("sort", sort)
            genre?.let { put("genre", it) }
            mediaType?.let { put("media_type", it) }
        }
        return get(CatalogPage.serializer(), "/api/catalog", query).items
    }

    suspend fun notifications() = get(NotificationFeed.serializer(), "/api/notifications")

    suspend fun profiles() = get(ProfileList.serializer(), "/api/profiles")

    suspend fun createProfile(name: String, avatar: String) =
        get(Profile.serializer(), "/api/profiles", mapOf("name" to name, "avatar" to avatar), "POST")

    /** A PIN-protected profile needs the PIN: 403 without it. */
    suspend fun updateProfile(id: Int, name: String?, avatar: String?, pin: String? = null) =
        json.decodeFromString(Profile.serializer(), raw("/api/profiles/$id",
            buildMap { name?.let { put("name", it) }; avatar?.let { put("avatar", it) } }, "PATCH",
            headers = pin?.let { mapOf("X-Profile-Pin" to it) } ?: emptyMap()))

    suspend fun deleteProfile(id: Int, pin: String? = null) {
        raw("/api/profiles/$id", method = "DELETE", headers = pin?.let { mapOf("X-Profile-Pin" to it) } ?: emptyMap())
    }

    suspend fun checkPin(id: Int, pin: String) {
        raw("/api/profiles/$id/pin/check", method = "POST", body = buildJsonObject { put("pin", pin) })
    }

    suspend fun setPin(id: Int, pin: String?, current: String?) {
        raw("/api/profiles/$id/pin", method = "PUT", body = buildJsonObject {
            put("pin", pin?.let(::JsonPrimitive) ?: JsonNull)
            put("current", current?.let(::JsonPrimitive) ?: JsonNull)
        })
    }

    suspend fun ratings(profile: Int): Map<String, Int> =
        get(MapSerializer(String.serializer(), Int.serializer()), "/api/profiles/$profile/ratings")

    suspend fun rate(profile: Int, media: Int, value: Int) {
        runCatching { raw("/api/profiles/$profile/ratings/$media", mapOf("value" to "$value"), "PUT") }
    }

    suspend fun myListIDs(profile: Int): List<Int> =
        get(ListSerializer(Int.serializer()), "/api/profiles/$profile/my-list")

    suspend fun setInMyList(profile: Int, media: Int, inList: Boolean) {
        raw("/api/profiles/$profile/my-list/$media", method = if (inList) "PUT" else "DELETE")
    }

    suspend fun myList() = get(CatalogPage.serializer(), "/api/catalog/my-list").items

    suspend fun clips() = get(ClipPage.serializer(), "/api/clips").items

    suspend fun saveClip(playID: String, start: Double, end: Double): Clip {
        val body = buildJsonObject { put("play_id", playID); put("start", start); put("end", end) }
        return json.decodeFromString(Clip.serializer(), raw("/api/clips", method = "POST", body = body))
    }

    suspend fun deleteClip(id: Int) { raw("/api/clips/$id", method = "DELETE") }

    suspend fun clipVertical(id: Int) = get(ClipVertical.serializer(), "/api/clips/$id/vertical")

    suspend fun saveClipVertical(id: Int, keyframes: List<ClipVertical.Keyframe>) {
        val body = buildJsonObject {
            put("keyframes", json.encodeToJsonElement(ListSerializer(ClipVertical.Keyframe.serializer()), keyframes))
        }
        raw("/api/clips/$id/vertical", method = "PUT", body = body)
    }

    suspend fun downloads() = get(ListSerializer(DownloadState.serializer()), "/api/downloads")

    suspend fun startDownload(torrent: Int, episode: Int? = null, everything: Boolean = false) =
        get(DownloadState.serializer(), "/api/downloads/$torrent", buildMap {
            episode?.let { put("episode", "$it") }
            if (everything) put("scope", "all")
        }, "POST")

    suspend fun downloadManager() = get(DownloadManager.serializer(), "/api/downloads/manager")

    suspend fun deleteDownload(id: Int) {
        raw("/api/downloads/$id", mapOf("delete_files" to "true"), "DELETE")
    }

    suspend fun deleteEpisode(episodeID: Int, of: Int) {
        raw("/api/downloads/$of/episodes/$episodeID", method = "DELETE")
    }

    suspend fun playInfo(playID: String) = get(PlayInfo.serializer(), "/api/play/$playID/info")

    suspend fun prepare(playID: String, audio: Int? = null) =
        get(PlayInfo.PlayPreparation.serializer(), "/api/play/$playID/prepare",
            audio?.let { mapOf("audio" to "$it") } ?: emptyMap())

    suspend fun trickplay(playID: String) = get(Trickplay.serializer(), "/api/play/$playID/thumbs.json")

    suspend fun reportProgress(playID: String, position: Double, duration: Double, profile: Int? = null) {
        runCatching {
            raw("/api/play/$playID/progress",
                mapOf("position" to "${position.toInt()}", "duration" to "${duration.toInt()}"), "POST",
                headers = profile?.let { mapOf(PROFILE_HEADER to it.toString()) } ?: emptyMap())
        }
    }

    suspend fun castRaw(path: String, query: Map<String, String> = emptyMap(), method: String = "GET",
                        body: JsonObject? = null, headers: Map<String, String> = emptyMap()): String =
        raw("/api/cast/$path", query, method, body, headers)
}
