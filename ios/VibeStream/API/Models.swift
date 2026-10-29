import Foundation

// Mirrors the server's JSON. Mostly optional: a freshly scraped title has little
// more than a name.

struct Quality: Codable, Hashable, Sendable {
    var resolution: String?
    var hdr: String?
    var source: String?
    var codec: String?
    var audio: String?
    var sizeGB: Double?

    enum CodingKeys: String, CodingKey {
        case resolution, hdr, source, codec, audio
        case sizeGB = "size_gb"
    }

    var badges: [String] {
        var out: [String] = []
        if resolution == "2160p" { out.append("4K") }
        if let hdr { out.append(hdr) }
        if let audio { out.append(audio) }
        return out
    }
}

struct DownloadState: Codable, Hashable, Identifiable, Sendable {
    var id: Int
    var torrentID: Int
    var state: String
    var episodes: [String]?
    var percent: Double
    var dlSpeed: Int?
    var etaSeconds: Int?
    var downloadedBytes: Int?
    /// The raw failure, for logs. Never shown: see errorMessage.
    var error: String?
    var errorMessage: String?
    var replaces: Int?
    var onDisk: Bool?
    /// On disk and prepared (rendition and thumbnails exist). Decided by the server.
    var playable: Bool?
    var preparing: Bool?
    var prepareError: String?
    /// Nil when the server cannot say: it keeps progress in memory only.
    var preparePercent: Double?

    enum CodingKeys: String, CodingKey {
        case id, state, percent, error, playable, preparing, episodes, replaces
        case torrentID = "torrent_id"
        case errorMessage = "error_message"
        case dlSpeed = "dl_speed"
        case etaSeconds = "eta_seconds"
        case downloadedBytes = "downloaded_bytes"
        case onDisk = "on_disk"
        case prepareError = "prepare_error"
        case preparePercent = "prepare_percent"
    }

    var isPlayable: Bool { playable == true }
    var isPreparing: Bool { preparing == true }
    var inLibrary: Bool { onDisk == true }
    var isWorking: Bool { ["downloading", "adding", "requested"].contains(state) }
}

struct Release: Codable, Hashable, Identifiable, Sendable {
    var id: Int
    var name: String
    var sizeGB: Double?
    var seeders: Int?
    var resolution: String?
    var source: String?
    var videoCodec: String?
    var audioCodec: String?
    var hdr: String?
    var releaseGroup: String?
    var season: Int?
    var episode: Int?
    var originLabel: String?
    var debrid: Bool?
    var download: DownloadState?

    enum CodingKeys: String, CodingKey {
        case id, name, seeders, resolution, source, hdr, season, episode, download, debrid
        case originLabel = "origin_label"
        case sizeGB = "size_gb"
        case videoCodec = "video_codec"
        case audioCodec = "audio_codec"
        case releaseGroup = "release_group"
    }

    var tags: [String] {
        [resolution, hdr, videoCodec, audioCodec, sizeGB.map { String(format: "%.2f GB", $0) }]
            .compactMap { $0 }
    }
}

struct Card: Codable, Hashable, Identifiable, Sendable {
    var mediaID: Int
    var mediaType: String?
    var title: String
    var year: Int?
    var overview: String?
    var tagline: String?
    var runtime: Int?
    var genres: [String]?
    var voteAverage: Double?
    var poster: String?
    var backdrop: String?
    var quality: Quality?
    var releaseCount: Int?
    var primaryReleaseID: Int?
    var download: DownloadState?
    var releases: [Release]?
    var resumeSeconds: Double?
    var resumePercent: Double?
    var resumeDownloadID: Int?
    /// "12" for a film, "e34" for an episode.
    var resumePlayID: String?
    var resumeLabel: String?
    var resumeEpisodeName: String?
    var seasons: [SeasonSummary]?
    var complete: Bool?
    var nextUp: NextUp?
    /// "resume" part way through an episode, "next" after a finished one.
    var resumeKind: String?
    var started: Bool?
    var addedAt: String?
    /// Above a kids profile's ceiling, kept on its watchlist: shown dimmed
    /// with a lock, never opened or played.
    var locked: Bool?
    /// What TMDB says about it, for the About tab. Only the title page's own
    /// request carries these.
    var facts: Facts?

    struct Facts: Codable, Sendable, Hashable {
        var cast: [String]?
        var castAll: [String]?
        var crewHeading: String?
        var crew: [String]?
        var certification: String?
        var keywords: [String]?
        var personIDs: [String: Int]?

        enum CodingKeys: String, CodingKey {
            case cast, crew, certification, keywords
            case castAll = "cast_all"
            case crewHeading = "crew_heading"
            case personIDs = "person_ids"
        }
    }

    var id: Int { mediaID }

    struct NextUp: Codable, Hashable, Sendable {
        var kind: String          // resume | next | start
        var playID: String
        var season: Int
        var number: Int
        var name: String
        var label: String         // "S2:E5"
        var resumeSeconds: Double
        var resumePercent: Double

        var isResume: Bool { kind == "resume" }

        enum CodingKeys: String, CodingKey {
            case kind, season, number, name, label
            case playID = "play_id"
            case resumeSeconds = "resume_seconds"
            case resumePercent = "resume_percent"
        }
    }

    enum CodingKeys: String, CodingKey {
        case title, year, overview, tagline, runtime, genres, poster, backdrop
        case quality, releases, download, started, facts, locked
        case addedAt = "added_at"
        case mediaID = "media_id"
        case mediaType = "media_type"
        case voteAverage = "vote_average"
        case releaseCount = "release_count"
        case primaryReleaseID = "primary_release_id"
        case resumeSeconds = "resume_seconds"
        case resumePercent = "resume_percent"
        case resumeDownloadID = "resume_download_id"
        case resumePlayID = "resume_play_id"
        case resumeLabel = "resume_label"
        case resumeEpisodeName = "resume_episode_name"
        case resumeKind = "resume_kind"
        case nextUp = "next_up"
        case seasons, complete
    }

    var isSeries: Bool { mediaType == "tv" }
    var isLocked: Bool { locked ?? false }

    var resumeTitle: String {
        guard let label = resumeLabel else { return title }
        guard let name = resumeEpisodeName, !name.isEmpty else {
            return "\(title): \(label)"
        }
        return "\(title): \(label) \(name)"
    }

    var playableDownloadID: Int? {
        if let resumeDownloadID { return resumeDownloadID }
        if let download, download.isPlayable { return download.id }
        return releases?.first(where: { $0.download?.isPlayable == true })?.download?.id
    }

    var metaLine: String {
        var parts: [String] = []
        if let year { parts.append(String(year)) }
        if let runtime, runtime > 0 {
            parts.append(runtime >= 60 ? "\(runtime / 60)h \(runtime % 60)m" : "\(runtime)m")
        }
        if isSeries { parts.append("Series") }
        return parts.joined(separator: "  ·  ")
    }
}

struct HomeFeed: Codable, Sendable {
    var hero: Card?
    var rows: [Row]

    struct Row: Codable, Identifiable, Sendable {
        var id: String
        var title: String
        var kind: String?
        var items: [Card]
    }
}

struct MyListPage: Codable, Sendable {
    var items: [Card]
}

struct Clip: Codable, Hashable, Identifiable, Sendable {
    var id: Int
    var mediaID: Int?
    var playID: String
    var title: String
    var subtitle: String?
    var start: Double
    var end: Double
    var duration: Double
    var video: String
    var thumb: String

    enum CodingKeys: String, CodingKey {
        case id, title, subtitle, start, end, duration, video, thumb
        case mediaID = "media_id"
        case playID = "play_id"
    }
}

struct ClipPage: Codable, Sendable {
    var items: [Clip]
}

struct CatalogPage: Codable, Sendable {
    var items: [Card]

    enum CodingKeys: String, CodingKey { case items }

    /// A release with a null media_id is skipped rather than failing the decode.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        items = try c.decode([Matched].self, forKey: .items).compactMap(\.card)
    }

    private struct Matched: Decodable {
        let card: Card?

        enum Keys: String, CodingKey { case mediaID = "media_id" }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            if try c.decodeIfPresent(Int.self, forKey: .mediaID) == nil {
                card = nil
            } else {
                card = try Card(from: decoder)
            }
        }
    }
}

struct PersonPage: Codable, Sendable {
    var id: Int
    var name: String
    var profile: String?
    var knownFor: String?
    var items: [Card]

    enum CodingKeys: String, CodingKey {
        case id, name, profile, items
        case knownFor = "known_for"
    }
}

struct GenreCount: Codable, Hashable, Identifiable, Sendable {
    var name: String
    var count: Int
    var id: String { name }
}

struct SeasonSummary: Codable, Hashable, Identifiable, Sendable {
    var number: Int
    var name: String
    var overview: String?
    var airDate: String?
    var poster: String?
    var episodeCount: Int
    /// Optional: absent when a season is sent on its own.
    var downloaded: Bool?

    var id: Int { number }
    var hasFiles: Bool { downloaded == true }

    enum CodingKeys: String, CodingKey {
        case number, name, overview, poster, downloaded
        case airDate = "air_date"
        case episodeCount = "episode_count"
    }
}

struct SeasonDetail: Codable, Sendable {
    var season: SeasonSummary
    var episodes: [EpisodeItem]
    var seasonPack: SeasonPack?

    enum CodingKeys: String, CodingKey {
        case season, episodes
        case seasonPack = "season_pack"
    }

    struct SeasonPack: Codable, Hashable, Sendable {
        var id: Int
        var name: String
        var sizeGB: Double?
        var completeRequest: Bool?
        var download: DownloadState?

        enum CodingKeys: String, CodingKey {
            case id, name, download
            case sizeGB = "size_gb"
            case completeRequest = "complete_request"
        }
    }
}

struct EpisodeItem: Codable, Hashable, Identifiable, Sendable {
    var id: Int
    var season: Int
    var episode: Int
    var name: String
    var overview: String?
    var airDate: String?
    var runtime: Int?
    var still: String?
    var available: Bool
    var playable: Bool
    var preparing: Bool
    var prepareError: String?
    var playID: String?
    var downloadID: Int?
    var sizeBytes: Int?
    var watched: Bool
    var resumeSeconds: Int
    var resumePercent: Double
    var releases: [EpisodeRelease]?
    var download: DownloadState?

    struct EpisodeRelease: Codable, Hashable, Identifiable, Sendable {
        var id: Int
        var name: String
        var sizeGB: Double?
        var seeders: Int?
        var resolution: String?
        var seasonPack: Bool
        /// Exact once the pack's file list is known, else an estimate.
        var episodeSizeGB: Double?
        var episodeSizeExact: Bool?

        enum CodingKeys: String, CodingKey {
            case id, name, seeders, resolution
            case sizeGB = "size_gb"
            case seasonPack = "season_pack"
            case episodeSizeGB = "episode_size_gb"
            case episodeSizeExact = "episode_size_exact"
        }

        var episodeCost: String? {
            guard let gb = episodeSizeGB, gb > 0 else { return nil }
            return (episodeSizeExact == true ? "" : "about ") + String(format: "%.1f GB", gb)
        }

        var label: String {
            var parts: [String] = []
            if let resolution { parts.append(resolution) }
            if let sizeGB { parts.append(String(format: "%.1f GB", sizeGB)) }
            if seasonPack { parts.append("whole season") }
            return parts.joined(separator: "  ·  ")
        }
    }

    enum CodingKeys: String, CodingKey {
        case id, season, episode, name, overview, runtime, still, available
        case playable, preparing, watched, releases, download
        case airDate = "air_date"
        case prepareError = "prepare_error"
        case playID = "play_id"
        case downloadID = "download_id"
        case sizeBytes = "size_bytes"
        case resumeSeconds = "resume_seconds"
        case resumePercent = "resume_percent"
    }

    var comingOn: Date? {
        guard !available, let airDate else { return nil }
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.timeZone = TimeZone(identifier: "UTC")
        guard let date = formatter.date(from: airDate) else { return nil }
        return date > Date() ? date : nil
    }

    var lengthLabel: String? {
        guard let runtime, runtime > 0 else { return nil }
        return runtime >= 60 ? "\(runtime / 60)h \(runtime % 60)m" : "\(runtime)m"
    }
}

struct DownloadItem: Codable, Hashable, Identifiable, Sendable {
    var downloadID: Int
    var torrentID: Int
    var mediaID: Int?
    var mediaType: String?
    var title: String
    var episodes: [String]?
    var year: Int?
    var poster: String?
    var release: String?
    var state: String
    var percent: Double
    var sizeBytes: Int
    var downloadedBytes: Int
    var uploadedBytes: Int
    var ratio: Double
    var dlSpeed: Int
    var upSpeed: Int
    var etaSeconds: Int?
    /// Nil when qBittorrent is not answering, which is not the same as 0.
    var seeders: Int?
    var leechers: Int?
    var seedingHours: Double
    var error: String?
    var playable: Bool
    var preparation: Preparation
    var seeding: SeedingGoal
    var episodeList: [PackEpisode]?

    var id: Int { downloadID }

    var isPack: Bool { (episodeList?.count ?? 0) > 1 }

    struct PackEpisode: Codable, Hashable, Sendable, Identifiable {
        var episodeID: Int
        var label: String
        var name: String?
        var here: Bool

        var id: Int { episodeID }

        enum CodingKeys: String, CodingKey {
            case label, name, here
            case episodeID = "episode_id"
        }
    }

    enum CodingKeys: String, CodingKey {
        case title, year, poster, release, state, percent, ratio, error, episodes
        case episodeList = "episode_list"
        case playable, preparation, seeding, seeders, leechers
        case downloadID = "download_id"
        case torrentID = "torrent_id"
        case mediaID = "media_id"
        case mediaType = "media_type"
        case sizeBytes = "size_bytes"
        case downloadedBytes = "downloaded_bytes"
        case uploadedBytes = "uploaded_bytes"
        case dlSpeed = "dl_speed"
        case upSpeed = "up_speed"
        case etaSeconds = "eta_seconds"
        case seedingHours = "seeding_hours"
    }

    struct Preparation: Codable, Hashable, Sendable {
        var ready: Bool
        var percent: Double
        var stage: String
        var error: String?
    }

    struct SeedingGoal: Codable, Hashable, Sendable {
        var met: Bool
        var detail: String
        var hours: Double
        var minHours: Int
        var ratio: Double
        var minRatio: Double

        enum CodingKeys: String, CodingKey {
            case met, detail, hours, ratio
            case minHours = "min_hours"
            case minRatio = "min_ratio"
        }
    }

    var isWorking: Bool { ["downloading", "adding", "requested"].contains(state) }

    var isPreparing: Bool { !playable && !isWorking && preparation.error == nil }

    var stateLabel: String {
        if playable { return "Ready" }
        if preparation.error != nil { return "Preparation failed" }
        if isPreparing {
            let percent = Int(preparation.percent)
            return percent > 0 ? "Preparing \(percent)%" : "Preparing"
        }
        switch state {
        case "requested": return "Queued"
        case "adding": return "Starting"
        case "downloading": return "Downloading"
        case "paused": return "Paused"
        case "error": return "Failed"
        default: return state.capitalized
        }
    }
}

struct DownloadManager: Codable, Sendable {
    /// False when qBittorrent is unreachable: the numbers are the last stored ones.
    var live: Bool
    var totals: Totals
    var items: [DownloadItem]

    struct Totals: Codable, Sendable {
        var count: Int
        var sizeBytes: Int
        var uploadedBytes: Int
        var dlSpeed: Int
        var upSpeed: Int
        var leechers: Int
        var downloading: Int
        var freeBytes: Int?
        var torrentBytes: Int?
        var playbackBytes: Int?

        enum CodingKeys: String, CodingKey {
            case count, downloading, leechers
            case torrentBytes = "torrent_bytes"
            case playbackBytes = "playback_bytes"
            case sizeBytes = "size_bytes"
            case uploadedBytes = "uploaded_bytes"
            case dlSpeed = "dl_speed"
            case upSpeed = "up_speed"
            case freeBytes = "free_bytes"
        }
    }
}

struct DownloadJobs: Codable, Sendable {
    var live: Bool
    var totals: DownloadManager.Totals
    var items: [DownloadJob]
}

struct DownloadJob: Codable, Hashable, Identifiable, Sendable {
    var id: Int
    /// title (a film, or a release of one episode), episode, season.
    var kind: String
    var downloadID: Int
    var torrentID: Int
    var mediaID: Int?
    var mediaType: String?
    var title: String
    var year: Int?
    var poster: String?
    var backdrop: String?
    var episode: Episode?
    var label: String?
    var release: String?
    var resolution: String?
    var hdr: String?
    var seeding: DownloadItem.SeedingGoal
    /// Other jobs live on the same torrent, so deleting this one keeps it.
    var sharesTorrent: Bool
    /// queued, downloading, paused, preparing, ready, failed.
    var state: String
    var percent: Double
    var sizeBytes: Int?
    var downloadedBytes: Int?
    var dlSpeed: Int
    var etaSeconds: Int?
    var preparePercent: Double?
    var playID: String?
    var errorMessage: String?

    struct Episode: Codable, Hashable, Sendable {
        var id: Int
        var season: Int
        var number: Int
        var name: String?
        var still: String?
    }

    enum CodingKeys: String, CodingKey {
        case kind, title, year, poster, backdrop, episode, label, release, resolution, hdr
        case seeding, state, percent
        case id = "job_id"
        case downloadID = "download_id"
        case torrentID = "torrent_id"
        case mediaID = "media_id"
        case mediaType = "media_type"
        case sharesTorrent = "shares_torrent"
        case sizeBytes = "size_bytes"
        case downloadedBytes = "downloaded_bytes"
        case dlSpeed = "dl_speed"
        case etaSeconds = "eta_seconds"
        case preparePercent = "prepare_percent"
        case playID = "play_id"
        case errorMessage = "error_message"
    }

    var isActive: Bool { ["queued", "downloading", "paused"].contains(state) }
}

/// Every field optional: qBittorrent's half is missing when it does not answer.
struct JobInspection: Decodable, Sendable {
    var live: Bool
    var release: Release?
    var torrent: Torrent
    var pieces: Pieces
    var files: [File]
    var peers: [Peer]
    var trackers: [Tracker]
    var library: Library

    struct Release: Decodable, Sendable {
        var name: String?
        var categoryName: String?
        var sizeBytes: Int?
        var resolution: String?
        var source: String?
        var videoCodec: String?
        var audioCodec: String?
        var hdr: String?
        var releaseGroup: String?
        var uploadDate: String?
        var seeders: Int?
        var leechers: Int?
        var freeleech: Bool?
        var `internal`: Bool?
    }

    struct Torrent: Decodable, Sendable {
        var name: String?
        var infoHash: String?
        var state: String?
        var savePath: String?
        var contentPath: String?
        var sizeBytes: Int?
        var totalSizeBytes: Int?
        var progress: Double?
        var downloadedBytes: Int?
        var uploadedBytes: Int?
        var wastedBytes: Int?
        var ratio: Double?
        var dlSpeed: Int?
        var upSpeed: Int?
        var dlSpeedAvg: Int?
        var upSpeedAvg: Int?
        var etaSeconds: Int?
        var seedingSeconds: Int?
        var elapsedSeconds: Int?
        var connections: Int?
        var connectionsLimit: Int?
        var seeds: Int?
        var seedsTotal: Int?
        var leechers: Int?
        var leechersTotal: Int?
        var pieceSize: Int?
        var piecesHave: Int?
        var piecesCount: Int?
        var reannounceSeconds: Int?
        var createdBy: String?
        var createdAt: String?
        var addedAt: String?
        var completedAt: String?
    }

    struct Pieces: Decodable, Sendable {
        var count: Int
        /// How much of each cell is here, 0 to 100.
        var have: [Int]
        /// 1 where some of the cell is being fetched right now.
        var busy: [Int]
    }

    struct File: Decodable, Sendable, Identifiable {
        var name: String
        var sizeBytes: Int
        var progress: Double
        /// 0: skipped.
        var priority: Int
        var mine: Bool
        var id: String { name }
    }

    struct Peer: Decodable, Sendable, Identifiable {
        var address: String?
        var client: String?
        var country: String?
        var countryCode: String?
        var connection: String?
        var flags: String?
        var progress: Double
        var dlSpeed: Int
        var upSpeed: Int
        var downloaded: Int
        var uploaded: Int
        var id: String { address ?? "\(client ?? "?")-\(downloaded)-\(uploaded)" }
    }

    struct Tracker: Decodable, Sendable, Identifiable {
        var host: String
        var status: String
        var seeds: Int?
        var leechers: Int?
        var peers: Int?
        var downloaded: Int?
        var message: String?
        var id: String { host }
    }

    struct Library: Decodable, Sendable {
        var requestedAt: String?
        var libraryPath: String?
        var playPath: String?
        var wanted: [String]?
        var preparation: Preparation?
        var sourceRemoved: Bool
        var sourceRemovable: Bool
        var sourceBytes: Int?

        struct Preparation: Decodable, Sendable {
            var ready: Bool?
            var percent: Double?
            var stage: String?
            var error: String?
        }
    }
}

struct Profile: Codable, Hashable, Identifiable, Sendable {
    var id: Int
    var name: String
    var avatar: String?
    var hasPin: Bool?
    var isKids: Bool?
    /// Parental controls: an adult without a PIN chooses one before it is used.
    var needsPin: Bool?
    /// A kids profile's ceiling under parental controls, as words ("7+").
    var maxMaturityLabel: String?

    enum CodingKeys: String, CodingKey {
        case id, name, avatar
        case hasPin = "has_pin"
        case isKids = "is_kids"
        case needsPin = "needs_pin"
        case maxMaturityLabel = "max_maturity_label"
    }

    var locked: Bool { hasPin ?? false }
    var kids: Bool { isKids ?? false }
    var mustChoosePin: Bool { needsPin ?? false }
}

struct ProfileList: Codable, Sendable {
    var profiles: [Profile]
    /// Parental controls: profiles are made in the admin, adults keep a PIN.
    var parentalControls: Bool?
    /// Every avatar id the server will accept. Sent with the list so the
    /// client picker can never offer one that fails to save.
    var avatars: [String]?

    enum CodingKeys: String, CodingKey {
        case profiles, avatars
        case parentalControls = "parental_controls"
    }
}

struct EpisodeAbout: Codable, Sendable {
    var season: Int?
    var number: Int?
    var name: String?
    var airDate: String?
    var runtime: Int?
    var voteAverage: Double?
    var directors: [String]?
    var writers: [String]?
    var guestStars: [Guest]?
    var personIDs: [String: Int]?

    struct Guest: Codable, Sendable, Hashable {
        var name: String
        var character: String?
    }

    enum CodingKeys: String, CodingKey {
        case season, number, name, runtime, directors, writers
        case airDate = "air_date"
        case voteAverage = "vote_average"
        case guestStars = "guest_stars"
        case personIDs = "person_ids"
    }
}

struct PlayInfo: Codable, Sendable {
    var playID: String
    var title: String?
    var mediaID: Int?
    var resume: Resume?
    var preparation: Preparation?
    var playback: Playback
    var subtitles: [Track]
    var audio: [AudioTrack]
    var defaultAudioIndex: Int? {
        (audio.first { $0.default == true } ?? audio.first)?.index
    }
    var next: NextEpisode?
    var presentation: Presentation?
    var media: MediaSummary?
    var file: FileSummary?

    enum CodingKeys: String, CodingKey {
        case title, resume, preparation, playback, subtitles, audio, next, presentation, media, file
        case playID = "play_id"
        case mediaID = "media_id"
    }

    struct MediaSummary: Codable, Sendable {
        var container: String?
        var bitrate: Int?
        var video: Video?
        var audio: [Audio]?

        struct Video: Codable, Sendable {
            var codec: String?
            var profile: String?
            var width: Int?
            var height: Int?
            var bitDepth: Int?
            var frameRate: Double?
            var hdr: Bool?
            var dolbyVision: Bool?

            enum CodingKeys: String, CodingKey {
                case codec, profile, width, height, hdr
                case bitDepth = "bit_depth"
                case frameRate = "frame_rate"
                case dolbyVision = "dolby_vision"
            }
        }

        struct Audio: Codable, Sendable {
            var index: Int
            var codec: String?
            var channels: Int?
        }
    }

    struct FileSummary: Codable, Sendable {
        var name: String?
        var sizeBytes: Int?

        enum CodingKeys: String, CodingKey {
            case name
            case sizeBytes = "size_bytes"
        }
    }

    struct Presentation: Codable, Hashable, Sendable {
        var title: String
        var year: Int?
        var overview: String?
        var episode: Episode?

        struct Episode: Codable, Hashable, Sendable {
            var season: Int
            var number: Int
            var name: String?
        }

        var episodeLine: String? {
            guard let episode else { return nil }
            let label = "S\(episode.season):E\(episode.number)"
            guard let name = episode.name, !name.isEmpty else { return label }
            return "\(label) \(name)"
        }
    }

    struct NextEpisode: Codable, Hashable, Sendable {
        var playID: String
        var season: Int
        var number: Int
        var name: String
        var still: String?

        enum CodingKeys: String, CodingKey {
            case season, number, name, still
            case playID = "play_id"
        }
    }

    struct Resume: Codable, Sendable {
        var seconds: Double
        var runtime: Double
        var finished: Bool
    }

    struct Preparation: Codable, Sendable {
        var ready: Bool
        var percent: Double
        var etaSeconds: Int?
        var error: String?

        enum CodingKeys: String, CodingKey {
            case ready, percent, error
            case etaSeconds = "eta_seconds"
        }
    }

    struct Playback: Codable, Sendable {
        var mode: String
        var videoPassthrough: Bool
        var hls: String
        /// "live" (segments made while watching) or "renditions".
        var engine: String?
        var audioTranscoded: Bool?

        enum CodingKeys: String, CodingKey {
            case mode, hls, engine
            case videoPassthrough = "video_passthrough"
            case audioTranscoded = "audio_transcoded"
        }
    }

    struct Track: Codable, Hashable, Identifiable, Sendable {
        var id: String
        var label: String
        var language: String?
        var forced: Bool?
        var sdh: Bool?
        var `default`: Bool?
    }

    struct AudioTrack: Codable, Hashable, Identifiable, Sendable {
        var index: Int
        var label: String
        var language: String?
        var channels: Int?
        var `default`: Bool?
        var id: Int { index }
    }
}

/// Frame times are listed, never derived from an interval.
struct Trickplay: Codable, Sendable {
    var ready: Bool
    var interval: Double?
    var count: Int?
    var times: [Double]?
    var perSheet: Int?
    var columns: Int?
    var rows: Int?
    var tileWidth: Int?
    var tileHeight: Int?
    var url: String?

    enum CodingKeys: String, CodingKey {
        case ready, interval, count, times, columns, rows, url
        case perSheet = "per_sheet"
        case tileWidth = "tile_width"
        case tileHeight = "tile_height"
    }

    var isUsable: Bool { ready && (count ?? 0) > 0 && times != nil }

    /// Binary search: the frames are not evenly spaced.
    func frameIndex(at seconds: Double) -> Int {
        guard let times, !times.isEmpty else { return 0 }
        var low = 0, high = times.count - 1, found = 0
        while low <= high {
            let mid = (low + high) / 2
            if times[mid] <= seconds { found = mid; low = mid + 1 } else { high = mid - 1 }
        }
        return found
    }
}

// MARK: - What is new

/// The releases since an app last said what was new, newest first, each
/// with its items for this app.
struct WhatsNew: Codable, Sendable, Identifiable {
    var version: String
    var releases: [Release]
    var id: String { version }

    struct Release: Codable, Sendable {
        var version: String
        var items: [Item]
    }

    struct Item: Codable, Sendable, Hashable {
        var title: String
        var text: String
    }
}
