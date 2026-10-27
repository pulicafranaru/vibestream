import Foundation

// Tries the public name, then the LAN address (some routers refuse DNS answers
// with a private IP). The first to answer is kept for the rest of the launch.
enum Server {
    static let candidates: [URL] = {
        #if DEBUG
        // -server <url>: one server only, for runs against a test copy.
        let arguments = ProcessInfo.processInfo.arguments
        if let flag = arguments.firstIndex(of: "-server"), flag + 1 < arguments.count,
           let url = URL(string: arguments[flag + 1]) {
            return [url]
        }
        #endif
        return ["VSPublicURL", "VSLanURL"].compactMap { key in
            (Bundle.main.object(forInfoDictionaryKey: key) as? String).flatMap(URL.init(string:))
        }
    }()
}

actor APIClient {
    static let shared = APIClient()

    private var base: URL?
    private var profileID: Int?

    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        // Fail at once with no network instead of waiting for connectivity.
        config.waitsForConnectivity = false
        config.timeoutIntervalForRequest = 20
        // TMDB artwork never changes, so a real disk cache pays off.
        config.urlCache = URLCache(memoryCapacity: 32 << 20, diskCapacity: 256 << 20)
        return URLSession(configuration: config)
    }()

    private let decoder = JSONDecoder()

    func setProfile(_ id: Int?) { profileID = id }

    func baseURL() async throws -> URL {
        if let base { return base }
        for candidate in Server.candidates {
            if await reachable(candidate) {
                base = candidate
                return candidate
            }
        }
        throw APIError.unreachable
    }

    private func reachable(_ url: URL) async -> Bool {
        var request = URLRequest(url: url.appendingPathComponent("tv-ping.gif"))
        request.timeoutInterval = 5
        request.cachePolicy = .reloadIgnoringLocalCacheData
        do {
            let (_, response) = try await session.data(for: request)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    private func request(
        _ path: String, query: [String: String] = [:], method: String = "GET"
    ) async throws -> URLRequest {
        let root = try await baseURL()
        var components = URLComponents(
            url: root.appending(path: path), resolvingAgainstBaseURL: false
        )!
        if !query.isEmpty {
            components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        // The profile goes in a header so it stays out of the HLS URLs the server rewrites.
        if let profileID { request.setValue(String(profileID), forHTTPHeaderField: "X-VibeStream-Profile") }
        return request
    }

    private func fetch<T: Decodable>(
        _ type: T.Type, _ path: String, query: [String: String] = [:], method: String = "GET"
    ) async throws -> T {
        let request = try await request(path, query: query, method: method)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.badResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.status(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
        return try decoder.decode(T.self, from: data)
    }

    /// The inbox is a long poll, so the timeout is the caller's.
    func cast<T: Decodable>(
        _ type: T.Type, _ path: String, query: [String: String] = [:],
        method: String = "GET", body: [String: Any]? = nil, headers: [String: String] = [:],
        timeout: TimeInterval = 20
    ) async throws -> T {
        var request = try await request("/api/cast/" + path, query: query, method: method)
        request.timeoutInterval = timeout
        for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.badResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.status(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
        return try decoder.decode(T.self, from: data)
    }

    /// Resolved against the root, not appended: `appending(path:)` would escape the
    /// `?` in `master.m3u8?audio=1` into `%3F`.
    func url(for path: String) async throws -> URL {
        let root = try await baseURL()
        guard let url = URL(string: path, relativeTo: root)?.absoluteURL else {
            return root.appending(path: path)
        }
        return url
    }

    func home(mediaType: String? = nil) async throws -> HomeFeed {
        try await fetch(HomeFeed.self, "/api/catalog/home",
                        query: mediaType.map { ["media_type": $0] } ?? [:])
    }

    func mine() async throws -> HomeFeed {
        try await fetch(HomeFeed.self, "/api/catalog/mine")
    }

    func episodeAbout(_ episodeID: Int) async throws -> EpisodeAbout {
        try await fetch(EpisodeAbout.self, "/api/catalog/episodes/\(episodeID)/about")
    }

    func media(_ id: Int) async throws -> Card {
        try await fetch(Card.self, "/api/catalog/media/\(id)")
    }

    func similar(_ id: Int) async throws -> [Card] {
        try await fetch(CatalogPage.self, "/api/catalog/media/\(id)/similar").items
    }

    func person(_ id: Int) async throws -> PersonPage {
        try await fetch(PersonPage.self, "/api/catalog/person/\(id)")
    }

    func search(_ term: String, limit: Int = 40) async throws -> [Card] {
        try await fetch(CatalogPage.self, "/api/catalog",
                        query: ["q": term, "limit": String(limit)]).items
    }

    func spoken(_ heard: [String]) async throws -> String {
        struct Answer: Decodable { let term: String }
        let data = try await sendJSON("/api/catalog/spoken", method: "POST", body: ["heard": heard])
        return try decoder.decode(Answer.self, from: data).term
    }

    func season(media: Int, number: Int) async throws -> SeasonDetail {
        try await fetch(SeasonDetail.self, "/api/catalog/media/\(media)/seasons/\(number)")
    }

    func genres(mediaType: String? = nil) async throws -> [GenreCount] {
        guard let mediaType else {
            return try await fetch([GenreCount].self, "/api/catalog/genres")
        }
        return try await fetch([GenreCount].self, "/api/catalog/genres",
                               query: ["media_type": mediaType, "order": "name"])
    }

    func catalog(
        genre: String, mediaType: String? = nil, limit: Int = 120
    ) async throws -> [Card] {
        var query = ["genre": genre, "limit": String(limit), "sort": "popular"]
        if let mediaType { query["media_type"] = mediaType }
        return try await fetch(CatalogPage.self, "/api/catalog", query: query).items
    }

    func notifications() async throws -> NotificationFeed {
        try await fetch(NotificationFeed.self, "/api/notifications")
    }

    func profiles() async throws -> ProfileList {
        try await fetch(ProfileList.self, "/api/profiles")
    }

    func createProfile(name: String, avatar: String) async throws -> Profile {
        try await fetch(Profile.self, "/api/profiles",
                        query: ["name": name, "avatar": avatar], method: "POST")
    }

    @discardableResult
    func updateProfile(_ id: Int, name: String?, avatar: String?, pin: String? = nil) async throws -> Profile {
        var query: [String: String] = [:]
        if let name { query["name"] = name }
        if let avatar { query["avatar"] = avatar }
        var request = try await request("/api/profiles/\(id)", query: query, method: "PATCH")
        if let pin { request.setValue(pin, forHTTPHeaderField: "X-Profile-Pin") }
        let data = try await send(request)
        return try decoder.decode(Profile.self, from: data)
    }

    /// Throws: the server refuses to delete the last profile.
    func deleteProfile(_ id: Int, pin: String? = nil) async throws {
        var request = try await request("/api/profiles/\(id)", method: "DELETE")
        if let pin { request.setValue(pin, forHTTPHeaderField: "X-Profile-Pin") }
        _ = try await send(request)
    }

    /// Throws 403 on a wrong PIN, 429 after too many in a row.
    func checkPin(_ id: Int, pin: String) async throws {
        _ = try await sendJSON("/api/profiles/\(id)/pin/check", method: "POST", body: ["pin": pin])
    }

    /// `pin` nil removes it; `current` is the PIN it has now, if any.
    func setPin(_ id: Int, pin: String?, current: String?) async throws {
        _ = try await sendJSON("/api/profiles/\(id)/pin", method: "PUT",
                               body: ["pin": pin ?? NSNull(), "current": current ?? NSNull()])
    }

    private func sendJSON(_ path: String, method: String, body: [String: Any]) async throws -> Data {
        var request = try await request(path, method: method)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await send(request)
    }

    private func send(_ request: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.badResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.status(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
        return data
    }

    func ratings(profile: Int) async throws -> [String: Int] {
        try await fetch([String: Int].self, "/api/profiles/\(profile)/ratings")
    }

    func rate(profile: Int, media: Int, value: Int) async {
        _ = try? await fetch(Empty.self, "/api/profiles/\(profile)/ratings/\(media)",
                             query: ["value": String(value)], method: "PUT")
    }

    func myListIDs(profile: Int) async throws -> [Int] {
        try await fetch([Int].self, "/api/profiles/\(profile)/my-list")
    }

    func clips() async throws -> [Clip] {
        try await fetch(ClipPage.self, "/api/clips").items
    }

    func saveClip(playID: String, start: Double, end: Double) async throws -> Clip {
        var request = try await request("/api/clips", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(
            withJSONObject: ["play_id": playID, "start": start, "end": end]
        )
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.badResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.status(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
        return try decoder.decode(Clip.self, from: data)
    }

    func clipVertical(_ id: Int) async throws -> ClipVertical {
        try await fetch(ClipVertical.self, "/api/clips/\(id)/vertical")
    }

    /// No keyframes means automatic.
    func saveClipVertical(_ id: Int, keyframes: [ClipVertical.Keyframe]) async throws {
        var request = try await request("/api/clips/\(id)/vertical", method: "PUT")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["keyframes": keyframes])
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw APIError.status((response as? HTTPURLResponse)?.statusCode ?? 0,
                                  String(data: data, encoding: .utf8) ?? "")
        }
    }

    func deleteClip(_ id: Int) async throws {
        _ = try await fetch(Empty.self, "/api/clips/\(id)", method: "DELETE")
    }

    func setInMyList(profile: Int, media: Int, _ inList: Bool) async throws {
        _ = try await fetch(Empty.self, "/api/profiles/\(profile)/my-list/\(media)",
                            method: inList ? "PUT" : "DELETE")
    }

    func myList() async throws -> [Card] {
        try await fetch(MyListPage.self, "/api/catalog/my-list").items
    }

    func downloads() async throws -> [DownloadState] {
        try await fetch([DownloadState].self, "/api/downloads")
    }

    @discardableResult
    /// `episode` fetches one episode of a pack; `everything` the whole pack; neither
    /// leaves a release already under way alone (Try again).
    func startDownload(torrent: Int, episode: Int? = nil, everything: Bool = false) async throws -> DownloadState {
        var query: [String: String] = [:]
        if let episode { query["episode"] = String(episode) }
        if everything { query["scope"] = "all" }
        return try await fetch(DownloadState.self, "/api/downloads/\(torrent)", query: query, method: "POST")
    }

    func downloadManager() async throws -> DownloadManager {
        try await fetch(DownloadManager.self, "/api/downloads/manager")
    }

    func deleteDownload(_ downloadID: Int) async throws {
        _ = try await fetch(OKResponse.self, "/api/downloads/\(downloadID)",
                            query: ["delete_files": "true"], method: "DELETE")
    }

    func deleteEpisode(_ episodeID: Int, of downloadID: Int) async throws {
        _ = try await fetch(OKResponse.self, "/api/downloads/\(downloadID)/episodes/\(episodeID)",
                            method: "DELETE")
    }

    func downloadJobs() async throws -> DownloadJobs {
        try await fetch(DownloadJobs.self, "/api/downloads/jobs")
    }

    func inspectJob(_ jobID: Int) async throws -> (JobInspection, DownloadJob?) {
        let request = try await request("/api/downloads/jobs/\(jobID)/inspect")
        let data = try await send(request)
        let snake = JSONDecoder()
        snake.keyDecodingStrategy = .convertFromSnakeCase
        struct JobOnly: Decodable { var job: DownloadJob? }
        return (try snake.decode(JobInspection.self, from: data),
                try? decoder.decode(JobOnly.self, from: data).job)
    }

    func deleteJob(_ jobID: Int) async throws {
        _ = try await fetch(OKResponse.self, "/api/downloads/jobs/\(jobID)", method: "DELETE")
    }

    /// `force` removes it before seeding is done, which the tracker counts against us.
    func removeSource(_ downloadID: Int, force: Bool = false) async throws {
        let request = try await request("/api/downloads/\(downloadID)/remove-source",
                                        query: force ? ["force": "true"] : [:], method: "POST")
        _ = try await send(request)
    }

    func playInfo(_ playID: String) async throws -> PlayInfo {
        try await fetch(PlayInfo.self, "/api/play/\(playID)/info")
    }

    func prepare(_ playID: String, audio: Int? = nil) async throws -> PlayInfo.Preparation {
        try await fetch(PlayInfo.Preparation.self, "/api/play/\(playID)/prepare",
                        query: audio.map { ["audio": String($0)] } ?? [:])
    }

    func trickplay(_ playID: String) async throws -> Trickplay {
        try await fetch(Trickplay.self, "/api/play/\(playID)/thumbs.json")
    }

    func sendTrace(_ playID: String, reason: String, lines: [String]) async {
        _ = try? await sendJSON("/api/play/\(playID)/trace", method: "POST",
                                body: ["reason": reason, "lines": Array(lines.suffix(600))])
    }

    func sendDiag(_ topic: String, reason: String, lines: [String]) async {
        _ = try? await sendJSON("/api/diag/\(topic)", method: "POST",
                                body: ["reason": reason, "lines": Array(lines.suffix(600))])
    }

    func reportProgress(_ playID: String, position: Double, duration: Double) async {
        _ = try? await fetch(Empty.self, "/api/play/\(playID)/progress",
                             query: ["position": String(Int(position)),
                                     "duration": String(Int(duration))],
                             method: "POST")
    }
}

private struct Empty: Decodable {}
private struct OKResponse: Decodable { let ok: Bool }

enum APIError: LocalizedError {
    case unreachable
    case badResponse
    case status(Int, String)

    var errorDescription: String? {
        switch self {
        case .unreachable:
            return "Cannot reach the VibeStream server on this network."
        case .badResponse:
            return "The server sent something unexpected."
        case let .status(code, body):
            // Show FastAPI's `detail` sentence rather than the raw body.
            if let data = body.data(using: .utf8),
               let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let detail = object["detail"] as? String, !detail.isEmpty {
                return detail.prefix(1).uppercased() + detail.dropFirst()
            }
            if code >= 500 { return "The server had a problem. Try again in a moment." }
            return "The server said no (\(code))."
        }
    }
}
