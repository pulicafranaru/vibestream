package xyz.vibestream.app.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonTransformingSerializer
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.Serializable

// Mirrors the server's JSON field for field. Nearly everything is optional: titles are enriched in the background.

@Serializable
data class Quality(
    val resolution: String? = null,
    val hdr: String? = null,
    val source: String? = null,
    val codec: String? = null,
    val audio: String? = null,
    @SerialName("size_gb") val sizeGB: Double? = null,
) {
    val badges: List<String>
        get() = buildList {
            if (resolution == "2160p") add("4K")
            hdr?.let(::add)
            audio?.let(::add)
        }
}

@Serializable
data class DownloadState(
    val id: Int,
    @SerialName("torrent_id") val torrentID: Int,
    val state: String,
    val episodes: List<String>? = null,
    val percent: Double = 0.0,
    @SerialName("dl_speed") val dlSpeed: Long? = null,
    @SerialName("eta_seconds") val etaSeconds: Int? = null,
    @SerialName("downloaded_bytes") val downloadedBytes: Long? = null,
    // The raw failure, for the logs. Never shown: see errorMessage.
    val error: String? = null,
    // The same failure as a sentence for the screen.
    @SerialName("error_message") val errorMessage: String? = null,
    // The release this stands in for, when the tracker had deleted the one pressed.
    val replaces: Int? = null,
    @SerialName("on_disk") val onDisk: Boolean? = null,
    val playable: Boolean? = null,
    val preparing: Boolean? = null,
    @SerialName("prepare_error") val prepareError: String? = null,
    @SerialName("prepare_percent") val preparePercent: Double? = null,
) {
    val isPlayable get() = playable == true
    val isPreparing get() = preparing == true
    val isWorking get() = state in setOf("downloading", "adding", "requested")
}

@Serializable
data class Release(
    val id: Int,
    val name: String,
    @SerialName("size_gb") val sizeGB: Double? = null,
    val seeders: Int? = null,
    val resolution: String? = null,
    val source: String? = null,
    @SerialName("video_codec") val videoCodec: String? = null,
    @SerialName("audio_codec") val audioCodec: String? = null,
    val hdr: String? = null,
    @SerialName("release_group") val releaseGroup: String? = null,
    val season: Int? = null,
    val episode: Int? = null,
    @SerialName("origin_label") val originLabel: String? = null,
    val debrid: Boolean = false,
    val download: DownloadState? = null,
) {
    val tags: List<String>
        get() = listOfNotNull(resolution, hdr, videoCodec, audioCodec, sizeGB?.let { "%.2f GB".format(it) })
}

@Serializable
data class Facts(
    val cast: List<String>? = null,
    @SerialName("cast_all") val castAll: List<String>? = null,
    @SerialName("crew_heading") val crewHeading: String? = null,
    val crew: List<String>? = null,
    val certification: String? = null,
    val keywords: List<String>? = null,
    @SerialName("person_ids") val personIDs: Map<String, Int>? = null,
)

@Serializable
data class NextUp(
    val kind: String,
    @SerialName("play_id") val playID: String,
    val season: Int,
    val number: Int,
    val name: String,
    val label: String,
    @SerialName("resume_seconds") val resumeSeconds: Double = 0.0,
    @SerialName("resume_percent") val resumePercent: Double = 0.0,
) {
    val isResume get() = kind == "resume"
}

@Serializable
data class Card(
    @SerialName("media_id") val mediaID: Int,
    @SerialName("media_type") val mediaType: String? = null,
    val title: String,
    val year: Int? = null,
    val overview: String? = null,
    val tagline: String? = null,
    val runtime: Int? = null,
    val genres: List<String>? = null,
    @SerialName("vote_average") val voteAverage: Double? = null,
    val poster: String? = null,
    val backdrop: String? = null,
    val logo: String? = null,
    val certification: String? = null,
    val quality: Quality? = null,
    @SerialName("release_count") val releaseCount: Int? = null,
    @SerialName("primary_release_id") val primaryReleaseID: Int? = null,
    val download: DownloadState? = null,
    val releases: List<Release>? = null,
    @SerialName("resume_seconds") val resumeSeconds: Double? = null,
    @SerialName("resume_percent") val resumePercent: Double? = null,
    @SerialName("resume_download_id") val resumeDownloadID: Int? = null,
    @SerialName("resume_play_id") val resumePlayID: String? = null,
    @SerialName("resume_label") val resumeLabel: String? = null,
    @SerialName("resume_episode_name") val resumeEpisodeName: String? = null,
    val seasons: List<SeasonSummary>? = null,
    val complete: Boolean? = null,
    @SerialName("next_up") val nextUp: NextUp? = null,
    @SerialName("resume_kind") val resumeKind: String? = null,
    val started: Boolean? = null,
    @SerialName("added_at") val addedAt: String? = null,
    // Above a kids profile's ceiling, kept on its watchlist: dimmed, never opened or played.
    val locked: Boolean? = null,
    val facts: Facts? = null,
) {
    val isSeries get() = mediaType == "tv"
    val isLocked get() = locked == true

    val resumeTitle: String
        get() {
            val label = resumeLabel ?: return title
            val name = resumeEpisodeName
            return if (name.isNullOrEmpty()) "$title: $label" else "$title: $label $name"
        }

    val playableDownloadID: Int?
        get() = resumeDownloadID
            ?: download?.takeIf { it.isPlayable }?.id
            ?: releases?.firstOrNull { it.download?.isPlayable == true }?.download?.id
}

@Serializable
data class HomeRow(
    val id: String,
    val title: String,
    val kind: String? = null,
    val items: List<Card> = emptyList(),
)

@Serializable
data class HomeFeed(val hero: Card? = null, val rows: List<HomeRow> = emptyList())

@Serializable
data class CatalogPage(@Serializable(with = TitledCards::class) val items: List<Card> = emptyList())

/** Drops releases with no media_id: they have no title page to open. */
object TitledCards : JsonTransformingSerializer<List<Card>>(ListSerializer(Card.serializer())) {
    override fun transformDeserialize(element: JsonElement): JsonElement =
        JsonArray(element.jsonArray.filter { (it as? JsonObject)?.get("media_id") is JsonPrimitive && it.jsonObject["media_id"] != JsonNull })
}

@Serializable
data class GenreCount(val name: String, val count: Int)

@Serializable
data class PersonPage(
    val id: Int,
    val name: String,
    val profile: String? = null,
    @SerialName("known_for") val knownFor: String? = null,
    val items: List<Card> = emptyList(),
)

@Serializable
data class SeasonSummary(
    val number: Int,
    val name: String,
    val overview: String? = null,
    @SerialName("air_date") val airDate: String? = null,
    val poster: String? = null,
    @SerialName("episode_count") val episodeCount: Int = 0,
    val downloaded: Boolean? = null,
) {
    val hasFiles get() = downloaded == true
}

@Serializable
data class SeasonPack(
    val id: Int,
    val name: String,
    @SerialName("size_gb") val sizeGB: Double? = null,
    @SerialName("complete_request") val completeRequest: Boolean? = null,
    val download: DownloadState? = null,
)

@Serializable
data class SeasonDetail(
    val season: SeasonSummary,
    val episodes: List<EpisodeItem> = emptyList(),
    @SerialName("season_pack") val seasonPack: SeasonPack? = null,
)

@Serializable
data class EpisodeRelease(
    val id: Int,
    val name: String,
    @SerialName("size_gb") val sizeGB: Double? = null,
    val seeders: Int? = null,
    val resolution: String? = null,
    @SerialName("season_pack") val seasonPack: Boolean = false,
    @SerialName("episode_size_gb") val episodeSizeGB: Double? = null,
    @SerialName("episode_size_exact") val episodeSizeExact: Boolean? = null,
) {
    val episodeCost: String?
        get() {
            val gb = episodeSizeGB ?: return null
            if (gb <= 0) return null
            return (if (episodeSizeExact == true) "" else "about ") + "%.1f GB".format(gb)
        }
}

@Serializable
data class EpisodeItem(
    val id: Int,
    val season: Int,
    val episode: Int,
    val name: String = "",
    val overview: String? = null,
    @SerialName("air_date") val airDate: String? = null,
    val runtime: Int? = null,
    val still: String? = null,
    val available: Boolean = false,
    val playable: Boolean = false,
    val preparing: Boolean = false,
    @SerialName("prepare_error") val prepareError: String? = null,
    @SerialName("play_id") val playID: String? = null,
    @SerialName("download_id") val downloadID: Int? = null,
    @SerialName("size_bytes") val sizeBytes: Long? = null,
    val watched: Boolean = false,
    @SerialName("resume_seconds") val resumeSeconds: Int = 0,
    @SerialName("resume_percent") val resumePercent: Double = 0.0,
    val releases: List<EpisodeRelease>? = null,
    val download: DownloadState? = null,
) {
    val lengthLabel: String?
        get() {
            val r = runtime ?: return null
            if (r <= 0) return null
            return if (r >= 60) "${r / 60}h ${r % 60}m" else "${r}m"
        }
}

@Serializable
data class EpisodeAbout(
    val season: Int? = null,
    val number: Int? = null,
    val name: String? = null,
    @SerialName("air_date") val airDate: String? = null,
    val runtime: Int? = null,
    @SerialName("vote_average") val voteAverage: Double? = null,
    val directors: List<String>? = null,
    val writers: List<String>? = null,
    @SerialName("guest_stars") val guestStars: List<Guest>? = null,
    @SerialName("person_ids") val personIDs: Map<String, Int>? = null,
) {
    @Serializable
    data class Guest(val name: String, val character: String? = null)
}

@Serializable
data class PackEpisode(
    @SerialName("episode_id") val episodeID: Int,
    val label: String,
    val name: String? = null,
    val here: Boolean = false,
)

@Serializable
data class Preparation(
    val ready: Boolean = false,
    val percent: Double = 0.0,
    val stage: String = "",
    val error: String? = null,
)

@Serializable
data class SeedingGoal(
    val met: Boolean = false,
    val detail: String = "",
    val hours: Double = 0.0,
    @SerialName("min_hours") val minHours: Int = 0,
    val ratio: Double = 0.0,
    @SerialName("min_ratio") val minRatio: Double = 0.0,
)

@Serializable
data class DownloadItem(
    @SerialName("download_id") val downloadID: Int,
    @SerialName("torrent_id") val torrentID: Int,
    @SerialName("media_id") val mediaID: Int? = null,
    @SerialName("media_type") val mediaType: String? = null,
    val title: String,
    val episodes: List<String>? = null,
    val year: Int? = null,
    val poster: String? = null,
    val release: String? = null,
    val state: String,
    val percent: Double = 0.0,
    @SerialName("size_bytes") val sizeBytes: Long = 0,
    @SerialName("downloaded_bytes") val downloadedBytes: Long = 0,
    @SerialName("uploaded_bytes") val uploadedBytes: Long = 0,
    val ratio: Double = 0.0,
    @SerialName("dl_speed") val dlSpeed: Long = 0,
    @SerialName("up_speed") val upSpeed: Long = 0,
    @SerialName("eta_seconds") val etaSeconds: Int? = null,
    val seeders: Int? = null,
    val leechers: Int? = null,
    @SerialName("seeding_hours") val seedingHours: Double = 0.0,
    val error: String? = null,
    val playable: Boolean = false,
    val preparation: Preparation = Preparation(),
    val seeding: SeedingGoal = SeedingGoal(),
    @SerialName("episode_list") val episodeList: List<PackEpisode>? = null,
) {
    val isPack get() = (episodeList?.size ?: 0) > 1
    val isWorking get() = state in setOf("downloading", "adding", "requested")
    val isPreparing get() = !playable && !isWorking && preparation.error == null

    val stateLabel: String
        get() {
            if (playable) return "Ready"
            if (preparation.error != null) return "Preparation failed"
            if (isPreparing) {
                val p = preparation.percent.toInt()
                return if (p > 0) "Preparing $p%" else "Preparing"
            }
            return when (state) {
                "requested" -> "Queued"
                "adding" -> "Starting"
                "downloading" -> "Downloading"
                "paused" -> "Paused"
                "error" -> "Failed"
                else -> state.replaceFirstChar { it.uppercase() }
            }
        }
}

@Serializable
data class DownloadTotals(
    val count: Int = 0,
    @SerialName("size_bytes") val sizeBytes: Long = 0,
    @SerialName("uploaded_bytes") val uploadedBytes: Long = 0,
    @SerialName("dl_speed") val dlSpeed: Long = 0,
    @SerialName("up_speed") val upSpeed: Long = 0,
    val leechers: Int = 0,
    val downloading: Int = 0,
    @SerialName("free_bytes") val freeBytes: Long? = null,
    @SerialName("torrent_bytes") val torrentBytes: Long? = null,
    @SerialName("playback_bytes") val playbackBytes: Long? = null,
)

@Serializable
data class DownloadManager(
    val live: Boolean = false,
    val totals: DownloadTotals = DownloadTotals(),
    val items: List<DownloadItem> = emptyList(),
)

// ----------------------------------------------------------- download jobs

/** Downloads as what was asked for: a film, an episode, a season, each with
 *  the progress of its own files. The torrents are in each job's inspector. */
@Serializable
data class DownloadJobs(
    val live: Boolean = false,
    val totals: DownloadTotals = DownloadTotals(),
    val items: List<DownloadJob> = emptyList(),
)

@Serializable
data class DownloadJob(
    @SerialName("job_id") val id: Int,
    // title (a film, or a release of one episode), episode, season.
    val kind: String,
    @SerialName("download_id") val downloadID: Int,
    @SerialName("torrent_id") val torrentID: Int,
    @SerialName("media_id") val mediaID: Int? = null,
    @SerialName("media_type") val mediaType: String? = null,
    val title: String,
    val year: Int? = null,
    val poster: String? = null,
    val backdrop: String? = null,
    val episode: Episode? = null,
    // "S1:E3", "Season 1".
    val label: String? = null,
    val release: String? = null,
    val resolution: String? = null,
    val hdr: String? = null,
    val seeding: SeedingGoal = SeedingGoal(),
    // Other jobs live on the same torrent, so deleting this one keeps it.
    @SerialName("shares_torrent") val sharesTorrent: Boolean = false,
    // queued, downloading, paused, preparing, ready, failed.
    val state: String,
    val percent: Double = 0.0,
    @SerialName("size_bytes") val sizeBytes: Long? = null,
    @SerialName("downloaded_bytes") val downloadedBytes: Long? = null,
    @SerialName("dl_speed") val dlSpeed: Long = 0,
    @SerialName("eta_seconds") val etaSeconds: Int? = null,
    @SerialName("prepare_percent") val preparePercent: Double? = null,
    @SerialName("play_id") val playID: String? = null,
    @SerialName("error_message") val errorMessage: String? = null,
) {
    @Serializable
    data class Episode(val id: Int, val season: Int, val number: Int, val name: String? = null, val still: String? = null)

    val isActive get() = state in setOf("queued", "downloading", "paused")
}

/** The torrent under a job, as a torrent client's inspector has it. Every
 *  field optional: qBittorrent's half is missing when it does not answer. */
@Serializable
data class JobInspection(
    val live: Boolean = false,
    val release: Release? = null,
    val torrent: Torrent = Torrent(),
    val pieces: Pieces = Pieces(),
    val files: List<File> = emptyList(),
    val peers: List<Peer> = emptyList(),
    val trackers: List<Tracker> = emptyList(),
    val library: Library = Library(),
    // The job itself as it is now.
    val job: DownloadJob? = null,
) {
    @Serializable
    data class Release(
        val name: String? = null,
        @SerialName("category_name") val categoryName: String? = null,
        @SerialName("size_bytes") val sizeBytes: Long? = null,
        val resolution: String? = null,
        val source: String? = null,
        @SerialName("video_codec") val videoCodec: String? = null,
        @SerialName("audio_codec") val audioCodec: String? = null,
        val hdr: String? = null,
        @SerialName("release_group") val releaseGroup: String? = null,
        @SerialName("upload_date") val uploadDate: String? = null,
        val seeders: Int? = null,
        val leechers: Int? = null,
        val freeleech: Boolean? = null,
        val internal: Boolean? = null,
    )

    @Serializable
    data class Torrent(
        val name: String? = null,
        @SerialName("info_hash") val infoHash: String? = null,
        val state: String? = null,
        @SerialName("save_path") val savePath: String? = null,
        @SerialName("content_path") val contentPath: String? = null,
        @SerialName("size_bytes") val sizeBytes: Long? = null,
        @SerialName("total_size_bytes") val totalSizeBytes: Long? = null,
        val progress: Double? = null,
        @SerialName("downloaded_bytes") val downloadedBytes: Long? = null,
        @SerialName("uploaded_bytes") val uploadedBytes: Long? = null,
        @SerialName("wasted_bytes") val wastedBytes: Long? = null,
        val ratio: Double? = null,
        @SerialName("dl_speed") val dlSpeed: Long? = null,
        @SerialName("up_speed") val upSpeed: Long? = null,
        @SerialName("dl_speed_avg") val dlSpeedAvg: Long? = null,
        @SerialName("up_speed_avg") val upSpeedAvg: Long? = null,
        @SerialName("eta_seconds") val etaSeconds: Long? = null,
        @SerialName("seeding_seconds") val seedingSeconds: Long? = null,
        @SerialName("elapsed_seconds") val elapsedSeconds: Long? = null,
        val connections: Int? = null,
        @SerialName("connections_limit") val connectionsLimit: Int? = null,
        val seeds: Int? = null,
        @SerialName("seeds_total") val seedsTotal: Int? = null,
        val leechers: Int? = null,
        @SerialName("leechers_total") val leechersTotal: Int? = null,
        @SerialName("piece_size") val pieceSize: Long? = null,
        @SerialName("pieces_have") val piecesHave: Int? = null,
        @SerialName("pieces_count") val piecesCount: Int? = null,
        @SerialName("reannounce_seconds") val reannounceSeconds: Long? = null,
        @SerialName("created_by") val createdBy: String? = null,
        @SerialName("created_at") val createdAt: String? = null,
        @SerialName("added_at") val addedAt: String? = null,
        @SerialName("completed_at") val completedAt: String? = null,
    )

    // How much of each cell is here, 0 to 100; busy is 1 where some is being fetched.
    @Serializable
    data class Pieces(val count: Int = 0, val have: List<Int> = emptyList(), val busy: List<Int> = emptyList())

    @Serializable
    data class File(
        val name: String,
        @SerialName("size_bytes") val sizeBytes: Long = 0,
        val progress: Double = 0.0,
        // 0: skipped.
        val priority: Int = 1,
        val mine: Boolean = false,
    )

    @Serializable
    data class Peer(
        val address: String? = null,
        val client: String? = null,
        val country: String? = null,
        @SerialName("country_code") val countryCode: String? = null,
        val connection: String? = null,
        val flags: String? = null,
        val progress: Double = 0.0,
        @SerialName("dl_speed") val dlSpeed: Long = 0,
        @SerialName("up_speed") val upSpeed: Long = 0,
        val downloaded: Long = 0,
        val uploaded: Long = 0,
    )

    @Serializable
    data class Tracker(
        val host: String,
        val status: String = "",
        val seeds: Int? = null,
        val leechers: Int? = null,
        val peers: Int? = null,
        val downloaded: Int? = null,
        val message: String? = null,
    )

    @Serializable
    data class Library(
        @SerialName("requested_at") val requestedAt: String? = null,
        @SerialName("library_path") val libraryPath: String? = null,
        @SerialName("play_path") val playPath: String? = null,
        val wanted: List<String>? = null,
        val preparation: Prep? = null,
        @SerialName("source_removed") val sourceRemoved: Boolean = false,
        @SerialName("source_removable") val sourceRemovable: Boolean = false,
        @SerialName("source_bytes") val sourceBytes: Long? = null,
    ) {
        @Serializable
        data class Prep(val ready: Boolean? = null, val percent: Double? = null, val stage: String? = null, val error: String? = null)
    }
}

// -------------------------------------------------------------- profiles

@Serializable
data class Profile(
    val id: Int,
    val name: String,
    val avatar: String? = null,
    @SerialName("has_pin") val hasPin: Boolean? = null,
    @SerialName("is_kids") val isKids: Boolean? = null,
    // Parental controls: an adult without a PIN chooses one before it is used.
    @SerialName("needs_pin") val needsPin: Boolean? = null,
    // A kids profile's ceiling under parental controls, as words ("7+").
    @SerialName("max_maturity_label") val maxMaturityLabel: String? = null,
) {
    val locked get() = hasPin == true
    val kids get() = isKids == true
    val mustChoosePin get() = needsPin == true
}

@Serializable
data class ProfileList(
    val profiles: List<Profile> = emptyList(),
    val avatars: List<String>? = null,
    @SerialName("parental_controls") val parentalControls: Boolean? = null,
)

@Serializable
data class NotificationItem(
    val id: String,
    val kind: String,
    val heading: String,
    val text: String,
    val image: String? = null,
    @SerialName("media_id") val mediaID: Int? = null,
    val at: String,
)

@Serializable
data class NotificationFeed(val items: List<NotificationItem> = emptyList())

@Serializable
data class PlayInfo(
    @SerialName("play_id") val playID: String,
    val title: String? = null,
    @SerialName("media_id") val mediaID: Int? = null,
    val resume: Resume? = null,
    val preparation: PlayPreparation? = null,
    val playback: Playback,
    val subtitles: List<SubtitleTrack> = emptyList(),
    val audio: List<AudioTrack> = emptyList(),
    val next: NextEpisode? = null,
    val presentation: Presentation? = null,
    // What the file is, as the server probed it, and the file itself. For the stats overlay.
    val media: MediaSummary? = null,
    val file: FileSummary? = null,
) {
    /** The track the server plays when none is asked for: the one flagged
     *  default, else the first. */
    val defaultAudio: AudioTrack? get() = audio.firstOrNull { it.default == true } ?: audio.firstOrNull()

    @Serializable
    data class MediaSummary(
        val container: String? = null,
        val bitrate: Long? = null,
        val video: Video? = null,
        val audio: List<Audio>? = null,
    ) {
        @Serializable
        data class Video(
            val codec: String? = null,
            val profile: String? = null,
            val width: Int? = null,
            val height: Int? = null,
            @SerialName("bit_depth") val bitDepth: Int? = null,
            @SerialName("frame_rate") val frameRate: Double? = null,
            val hdr: Boolean? = null,
            @SerialName("dolby_vision") val dolbyVision: Boolean? = null,
        )

        @Serializable
        data class Audio(val index: Int, val codec: String? = null, val channels: Int? = null)
    }

    @Serializable
    data class FileSummary(val name: String? = null, @SerialName("size_bytes") val sizeBytes: Long? = null)

    @Serializable
    data class Resume(val seconds: Double = 0.0, val runtime: Double = 0.0, val finished: Boolean = false)

    @Serializable
    data class PlayPreparation(
        val ready: Boolean = false,
        val percent: Double = 0.0,
        @SerialName("eta_seconds") val etaSeconds: Int? = null,
        val error: String? = null,
    )

    @Serializable
    data class Playback(
        val mode: String = "",
        @SerialName("video_passthrough") val videoPassthrough: Boolean = false,
        val hls: String,
        // "live" (segments made while watching) or "renditions".
        val engine: String? = null,
        @SerialName("audio_transcoded") val audioTranscoded: Boolean? = null,
    )

    @Serializable
    data class SubtitleTrack(
        val id: String,
        val label: String,
        val language: String? = null,
        val forced: Boolean? = null,
        val sdh: Boolean? = null,
        val default: Boolean? = null,
    )

    @Serializable
    data class AudioTrack(
        val index: Int,
        val label: String,
        val language: String? = null,
        val channels: Int? = null,
        val default: Boolean? = null,
    )

    @Serializable
    data class NextEpisode(
        @SerialName("play_id") val playID: String,
        val season: Int,
        val number: Int,
        val name: String = "",
        val still: String? = null,
    )

    @Serializable
    data class Presentation(
        val title: String,
        val year: Int? = null,
        val overview: String? = null,
        val certification: String? = null,
        val episode: Ep? = null,
    ) {
        @Serializable
        data class Ep(val season: Int, val number: Int, val name: String? = null)

        val episodeLine: String?
            get() {
                val e = episode ?: return null
                val label = "S${e.season}:E${e.number}"
                return if (e.name.isNullOrEmpty()) label else "$label ${e.name}"
            }
    }
}

@Serializable
data class Clip(
    val id: Int,
    @SerialName("media_id") val mediaID: Int? = null,
    @SerialName("play_id") val playID: String,
    val title: String,
    val subtitle: String? = null,
    val start: Double,
    val end: Double,
    val duration: Double,
    val video: String,
    val thumb: String,
)

@Serializable
data class ClipPage(val items: List<Clip> = emptyList())

/** Where a play starts: a download id ("12") or an episode ("e34"). The
 *  season and episode, when known, let the title page land on that episode. */
data class PlayRequest(
    val playID: String,
    val title: String,
    val startAt: Double? = null,
    val season: Int? = null,
    val episode: Int? = null,
)

@Serializable
data class Trickplay(
    val ready: Boolean = false,
    val interval: Double? = null,
    val count: Int? = null,
    val times: List<Double>? = null,
    @SerialName("per_sheet") val perSheet: Int? = null,
    val columns: Int? = null,
    val rows: Int? = null,
    @SerialName("tile_width") val tileWidth: Int? = null,
    @SerialName("tile_height") val tileHeight: Int? = null,
    val url: String? = null,
) {
    val isUsable get() = ready && (count ?: 0) > 0 && times != null

    fun frameIndex(seconds: Double): Int {
        val t = times ?: return 0
        if (t.isEmpty()) return 0
        var low = 0
        var high = t.size - 1
        var found = 0
        while (low <= high) {
            val mid = (low + high) / 2
            if (t[mid] <= seconds) { found = mid; low = mid + 1 } else high = mid - 1
        }
        return found
    }
}

// Positions are fractions of the wide frame, so one set drives both preview and export at any size.
@Serializable
data class ClipVertical(
    val picture: Picture? = null,
    val crop: Crop? = null,
    val keyframes: List<Keyframe> = emptyList(),
) {
    @Serializable data class Picture(val width: Double = 1.0, val height: Double = 1.0)
    @Serializable data class Crop(val aspect: Double = 16.0 / 9.0, val shots: List<Shot> = emptyList())
    @Serializable data class Shot(val start: Double, val end: Double, val points: List<List<Double>> = emptyList())
    @Serializable data class Keyframe(val t: Double, val x: Double, val y: Double = 0.5, val zoom: Double = 1.0)
}

/** The releases since an app last said what was new, newest first, each
 *  with its items for this app. */
@Serializable
data class WhatsNew(val version: String, val releases: List<Release> = emptyList()) {
    @Serializable
    data class Release(val version: String, val items: List<Item> = emptyList())

    @Serializable
    data class Item(val title: String = "", val text: String = "")
}
