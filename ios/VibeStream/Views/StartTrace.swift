import AVFoundation
import UIKit

// The player's side of a start, for the server's event log: each step and everything
// AVFoundation reports, sent as "stall", "closed" (left before playing) or "ok".
@MainActor
final class StartTrace {
    private let began = Date()
    private(set) var lines: [String] = []
    private var observations: [NSKeyValueObservation] = []
    private var tokens: [NSObjectProtocol] = []
    private var sent: Set<String> = []
    private let playID: String

    init(playID: String) {
        self.playID = playID
        mark("start \(playID) on \(Self.device), iOS \(UIDevice.current.systemVersion)")
    }

    func mark(_ text: String, at date: Date = Date()) {
        guard lines.count < 600 else { return }
        lines.append(String(format: "+%7.3f  ", date.timeIntervalSince(began)) + text)
    }

    func watch(_ item: AVPlayerItem, player: AVPlayer) {
        unwatch()
        mark("item for \(item.asset is AVURLAsset ? (item.asset as! AVURLAsset).url.path : "?")")

        func hop(_ text: @escaping @Sendable () -> String) -> @Sendable () -> Void {
            { [weak self] in
                let now = Date()
                let line = text()
                Task { @MainActor in self?.mark(line, at: now) }
            }
        }

        observations.append(item.observe(\.status, options: [.new]) { item, _ in
            let error = (item.error as NSError?).map { " \($0.domain) \($0.code) \($0.localizedDescription)" } ?? ""
            hop { "item status \(Self.name(item.status))\(error)" }()
        })
        observations.append(item.observe(\.isPlaybackLikelyToKeepUp, options: [.new]) { item, _ in
            hop { "likely to keep up \(item.isPlaybackLikelyToKeepUp)" }()
        })
        observations.append(item.observe(\.isPlaybackBufferEmpty, options: [.new]) { item, _ in
            hop { "buffer empty \(item.isPlaybackBufferEmpty)" }()
        })
        observations.append(item.observe(\.loadedTimeRanges, options: [.new]) { item, _ in
            hop { "loaded \(Self.ranges(item.loadedTimeRanges))" }()
        })
        observations.append(player.observe(\.timeControlStatus, options: [.new]) { player, _ in
            hop { "player \(Self.describe(player))" }()
        })
        observations.append(player.observe(\.status, options: [.new]) { player, _ in
            hop { "player status \(player.status.rawValue)" }()
        })

        let center = NotificationCenter.default
        tokens.append(center.addObserver(forName: AVPlayerItem.newAccessLogEntryNotification,
                                         object: item, queue: .main) { [weak self] _ in
            guard let event = item.accessLog()?.events.last else { return }
            let text = "access \(event.uri?.split(separator: "/").suffix(2).joined(separator: "/") ?? "-") "
                + "requests \(event.numberOfMediaRequests) stalls \(event.numberOfStalls) "
                + "indicated \(Int(event.indicatedBitrate / 1000))k observed \(Int(event.observedBitrate / 1000))k"
            MainActor.assumeIsolated { self?.mark(text) }
        })
        tokens.append(center.addObserver(forName: AVPlayerItem.newErrorLogEntryNotification,
                                         object: item, queue: .main) { [weak self] _ in
            guard let event = item.errorLog()?.events.last else { return }
            let text = "error log \(event.errorDomain) \(event.errorStatusCode) "
                + "\(event.errorComment ?? "") \(event.uri?.split(separator: "/").suffix(2).joined(separator: "/") ?? "")"
            MainActor.assumeIsolated { self?.mark(text) }
        })
        tokens.append(center.addObserver(forName: AVPlayerItem.playbackStalledNotification,
                                         object: item, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.mark("playback stalled") }
        })
        tokens.append(center.addObserver(forName: AVPlayerItem.failedToPlayToEndTimeNotification,
                                         object: item, queue: .main) { [weak self] note in
            let error = note.userInfo?[AVPlayerItemFailedToPlayToEndTimeErrorKey] as? NSError
            let text = "failed to play to end \(error.map { "\($0.domain) \($0.code)" } ?? "")"
            MainActor.assumeIsolated { self?.mark(text) }
        })
    }

    func unwatch() {
        observations.forEach { $0.invalidate() }
        observations = []
        tokens.forEach { NotificationCenter.default.removeObserver($0) }
        tokens = []
    }

    func snapshot(_ player: AVPlayer, model current: Double) {
        let item = player.currentItem
        let now = player.currentTime().seconds
        mark(String(format: "tick time %.2f model %.2f rate %.2f ", now, current, player.rate)
             + "\(Self.describe(player)) item \(item.map { Self.name($0.status) } ?? "none") "
             + "loaded \(item.map { Self.ranges($0.loadedTimeRanges) } ?? "-")")
    }

    /// Sent once per reason; each carries everything so far.
    func send(_ reason: String) {
        guard !sent.contains(reason) else { return }
        sent.insert(reason)
        mark("sent as \(reason)")
        let lines = lines
        Task { [playID] in await APIClient.shared.sendTrace(playID, reason: reason, lines: lines) }
    }

    func hasSent(_ reason: String) -> Bool { sent.contains(reason) }

    nonisolated static func describe(_ player: AVPlayer) -> String {
        switch player.timeControlStatus {
        case .paused: return "paused"
        case .playing: return "playing"
        case .waitingToPlayAtSpecifiedRate:
            return "waiting (\(player.reasonForWaitingToPlay?.rawValue ?? "no reason"))"
        @unknown default: return "unknown"
        }
    }

    nonisolated static func name(_ status: AVPlayerItem.Status) -> String {
        switch status {
        case .unknown: return "unknown"
        case .readyToPlay: return "ready"
        case .failed: return "failed"
        @unknown default: return "?"
        }
    }

    nonisolated static func ranges(_ ranges: [NSValue]) -> String {
        if ranges.isEmpty { return "nothing" }
        return ranges.map {
            let r = $0.timeRangeValue
            return String(format: "%.1f-%.1f", r.start.seconds, (r.start + r.duration).seconds)
        }.joined(separator: ",")
    }

    private static var device: String {
        var info = utsname()
        uname(&info)
        return withUnsafeBytes(of: &info.machine) { raw in
            String(decoding: raw.prefix { $0 != 0 }, as: UTF8.self)
        }
    }
}
