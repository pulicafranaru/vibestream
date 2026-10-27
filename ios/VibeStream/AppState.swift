import Foundation
import SwiftUI

// @Observable rather than ObservableObject, so a view reading only `downloads`
// is not re-rendered when the feed reloads.
@MainActor
@Observable
final class AppState {
    var profiles: [Profile] = []
    var profile: Profile?
    var needsProfilePick = false
    /// Shared, so opening any tab's bell clears the dot on all of them.
    var notificationsSeen = ""
    var avatarChoices: [String] = AvatarArt.all

    var feed: HomeFeed?
    var feeds: [String: HomeFeed] = [:]
    var library: HomeFeed?
    var loading = false
    var loadError: String?

    /// torrent id -> live state, polled independently of the catalog.
    var downloads: [Int: DownloadState] = [:]
    /// media id -> -1 not for me, 1 like it.
    var ratings: [Int: Int] = [:]
    var myList: Set<Int> = []
    var clips: [Clip] = []
    /// True until the profile list has answered, so the picker is not drawn empty.
    var startingUp = true
    var lastSeason: [Int: Int] = [:]

    private var pollTask: Task<Void, Never>?
    // Do not rename: installed copies store the profile under this key.
    private let storedProfileKey = "vibestream.profile"

    func start() async {
        await loadProfiles()
        startPolling()
    }

    /// `keepingSelection` keeps the current profile through an edit instead of
    /// returning to the picker.
    func loadProfiles(keepingSelection: Bool = false) async {
        defer { startingUp = false }
        do {
            let response = try await APIClient.shared.profiles()
            let list = response.profiles
            profiles = list
            if let choices = response.avatars, !choices.isEmpty { avatarChoices = choices }
            if keepingSelection {
                if let current = profile, let fresh = list.first(where: { $0.id == current.id }) {
                    profile = fresh
                }
                return
            }
            // The stored id is validated against the server so a deleted profile cannot strand the app.
            #if DEBUG
            // -profile <id>: who is watching, for runs driven from a script.
            let arguments = ProcessInfo.processInfo.arguments
            // -askPin <id>: Who's Watching, asking for that profile's PIN.
            if arguments.contains("-askPin") {
                needsProfilePick = true
                return
            }
            if let flag = arguments.firstIndex(of: "-profile"),
               arguments.index(after: flag) < arguments.endIndex,
               let id = Int(arguments[arguments.index(after: flag)]),
               let found = list.first(where: { $0.id == id }) {
                await pick(found)
                return
            }
            #endif
            let stored = UserDefaults.standard.integer(forKey: storedProfileKey)
            if let found = list.first(where: { $0.id == stored }) {
                await pick(found)
            } else if list.count == 1, !list[0].locked {
                await pick(list[0])
            } else {
                needsProfilePick = true
            }
        } catch {
            loadError = error.localizedDescription
            needsProfilePick = true
        }
    }

    func retryStartup() async {
        loadError = nil
        startingUp = true
        await loadProfiles()
    }

    /// Every request carries the profile header, so deleting the active profile must
    /// hand the app to another.
    func profileWasDeleted(_ id: Int) async {
        let wasActive = profile?.id == id
        await loadProfiles(keepingSelection: !wasActive)
        guard wasActive else { return }
        if let next = profiles.first, !next.locked {
            await pick(next)
        } else {
            profile = nil
            needsProfilePick = true
        }
    }

    func pick(_ chosen: Profile) async {
        // Clear the old profile's rows before the new feed loads.
        if profile?.id != chosen.id {
            feed = nil
            feeds = [:]
            ratings = [:]
            myList = []
            clips = []
            lastSeason = [:]
        }
        loading = true
        profile = chosen
        needsProfilePick = false
        UserDefaults.standard.set(chosen.id, forKey: storedProfileKey)
        await APIClient.shared.setProfile(chosen.id)
        await loadRatings()
        await loadMyList()
        await loadClips()
        await loadFeed()
    }

    func loadFeed() async {
        // Drop a late answer for a profile since switched away from.
        let owner = profile?.id
        loading = true
        defer { if profile?.id == owner { loading = false } }
        do {
            async let all = APIClient.shared.home()
            async let movies = APIClient.shared.home(mediaType: "movie")
            async let shows = APIClient.shared.home(mediaType: "tv")
            let (everything, movie, tv) = try await (all, movies, shows)
            guard profile?.id == owner else { return }
            feed = everything
            feeds = ["movie": movie, "tv": tv]
            if let mine = try? await APIClient.shared.mine(), profile?.id == owner { library = mine }
            loadError = nil
        } catch {
            guard profile?.id == owner else { return }
            loadError = error.localizedDescription
        }
    }

    /// The server sends every genre, most of them empty.
    var rows: [HomeFeed.Row] {
        (feed?.rows ?? []).filter { !$0.items.isEmpty }
    }

    func rows(_ kind: String) -> [HomeFeed.Row] {
        (feeds[kind]?.rows ?? []).filter { !$0.items.isEmpty }
    }

    // Subtitles and speed, remembered per profile so they carry across episodes.
    struct PlayerPrefs: Codable, Equatable {
        /// `subtitlesOff` is the explicit choice of none.
        var subtitleLanguage: String?
        var subtitlesOff = false
        var speed: Float = 1.0
        var subtitleSize: SubtitleSize = .medium
        var subtitleStyle: SubtitleStyle = .shadow

        init() {}

        // Every field optional, so preferences saved by an older build still load.
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            subtitleLanguage = try c.decodeIfPresent(String.self, forKey: .subtitleLanguage)
            subtitlesOff = try c.decodeIfPresent(Bool.self, forKey: .subtitlesOff) ?? false
            speed = try c.decodeIfPresent(Float.self, forKey: .speed) ?? 1.0
            subtitleSize = try c.decodeIfPresent(SubtitleSize.self, forKey: .subtitleSize) ?? .medium
            subtitleStyle = try c.decodeIfPresent(SubtitleStyle.self, forKey: .subtitleStyle) ?? .shadow
        }
    }

    private var prefsKey: String { "vibestream.player.\(profile?.id ?? 0)" }

    var playerPrefs: PlayerPrefs {
        get {
            guard let data = UserDefaults.standard.data(forKey: prefsKey),
                  let prefs = try? JSONDecoder().decode(PlayerPrefs.self, from: data)
            else { return PlayerPrefs() }
            return prefs
        }
        set {
            if let data = try? JSONEncoder().encode(newValue) {
                UserDefaults.standard.set(data, forKey: prefsKey)
            }
        }
    }

    func loadRatings() async {
        guard let profile else { return }
        guard let raw = try? await APIClient.shared.ratings(profile: profile.id),
              self.profile?.id == profile.id else { return }
        ratings = Dictionary(uniqueKeysWithValues: raw.compactMap { key, value in
            Int(key).map { ($0, value) }
        })
    }

    func rate(_ mediaID: Int, _ value: Int) async {
        guard let profile else { return }
        let next = ratings[mediaID] == value ? 0 : value
        ratings[mediaID] = next == 0 ? nil : next
        await APIClient.shared.rate(profile: profile.id, media: mediaID, value: next)
    }

    func loadClips() async {
        let owner = profile?.id
        guard let fresh = try? await APIClient.shared.clips(), profile?.id == owner else { return }
        clips = fresh
    }

    @discardableResult
    func saveClip(playID: String, start: Double, end: Double) async throws -> Clip {
        let clip = try await APIClient.shared.saveClip(playID: playID, start: start, end: end)
        clips.insert(clip, at: 0)
        return clip
    }

    func deleteClip(_ clip: Clip) async {
        clips.removeAll { $0.id == clip.id }
        do {
            try await APIClient.shared.deleteClip(clip.id)
        } catch {
            await loadClips()
        }
    }

    func loadMyList() async {
        guard let profile else { return }
        guard let ids = try? await APIClient.shared.myListIDs(profile: profile.id),
              self.profile?.id == profile.id else { return }
        myList = Set(ids)
    }

    // Optimistic, reverted if the server refuses. The home row is patched in place
    // so the scroll position survives.
    func toggleMyList(_ card: Card) async {
        guard let profile else { return }
        let adding = !myList.contains(card.mediaID)
        apply(card, adding)
        do {
            try await APIClient.shared.setInMyList(profile: profile.id, media: card.mediaID, adding)
        } catch {
            apply(card, !adding)
        }
    }

    private func apply(_ card: Card, _ adding: Bool) {
        if adding { myList.insert(card.mediaID) } else { myList.remove(card.mediaID) }
        feed = feed.map { patched($0, card, adding) }
        if let kind = card.mediaType, let typed = feeds[kind] {
            feeds[kind] = patched(typed, card, adding)
        }
    }

    private func patched(_ feed: HomeFeed, _ card: Card, _ adding: Bool) -> HomeFeed {
        var current = feed
        if let index = current.rows.firstIndex(where: { $0.id == "mylist" }) {
            current.rows[index].items.removeAll { $0.mediaID == card.mediaID }
            if adding { current.rows[index].items.insert(card, at: 0) }
        } else if adding {
            let after = current.rows.firstIndex(where: { $0.id == "continue" }).map { $0 + 1 } ?? 0
            current.rows.insert(
                HomeFeed.Row(id: "mylist", title: "Watchlist", kind: "mylist", items: [card]),
                at: after
            )
        }
        return current
    }

    /// Polls the small downloads endpoint: refetching the feed would rebuild every
    /// tile and lose the scroll position.
    func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                var active = false
                if let rows = try? await APIClient.shared.downloads() {
                    var map: [Int: DownloadState] = [:]
                    for row in rows {
                        map[row.torrentID] = row
                        if row.isWorking || row.isPreparing { active = true }
                    }
                    self.downloads = self.linked(map)
                    self.sayNewFailures(rows)
                }
                // Fast while something is active, so an idle phone is not waking the radio.
                try? await Task.sleep(for: .seconds(active ? 2 : 15))
            }
        }
    }

    func stopPolling() { pollTask?.cancel() }

    // The POST returns the new row, so it goes straight into the map. The catalog is
    // not reloaded: it is slow and nothing on screen needs it.
    @discardableResult
    func download(torrent: Int, episode: Int? = nil, everything: Bool = false) async throws -> DownloadState {
        let started = try await APIClient.shared.startDownload(
            torrent: torrent, episode: episode, everything: everything
        )
        downloads[started.torrentID] = started
        // The tracker deleted the release pressed: its button now follows the replacement.
        if let replaced = started.replaces {
            replacements[replaced] = started.torrentID
            downloads[replaced] = started
        }
        startPolling()   // restart, so the fast cadence begins now
        return started
    }

    /// Release pressed -> the release downloading in its place.
    @ObservationIgnored private var replacements: [Int: Int] = [:]

    private func linked(_ map: [Int: DownloadState]) -> [Int: DownloadState] {
        var map = map
        for (pressed, actual) in replacements {
            if let row = map[actual] { map[pressed] = row }
        }
        return map
    }

    // A failure after acceptance gets one toast; failures present at the first look do not.
    @ObservationIgnored private var failuresSeen: Set<Int>?

    private func sayNewFailures(_ rows: [DownloadState]) {
        let failed = rows.filter { $0.state == "error" }
        let ids = Set(failed.map(\.id))
        defer { failuresSeen = (failuresSeen ?? []).union(ids) }
        guard let seen = failuresSeen else { return }
        if let fresh = failed.first(where: { !seen.contains($0.id) }) {
            Toasts.shared.error(fresh.errorMessage ?? "A download failed.")
        }
    }

    func cancel(download id: Int, torrent: Int) async throws {
        try await APIClient.shared.deleteDownload(id)
        downloads[torrent] = nil
        startPolling()
    }

    func refreshDownloads() async {
        guard let rows = try? await APIClient.shared.downloads() else { return }
        var map: [Int: DownloadState] = [:]
        for row in rows { map[row.torrentID] = row }
        downloads = linked(map)
        sayNewFailures(rows)
    }
}
