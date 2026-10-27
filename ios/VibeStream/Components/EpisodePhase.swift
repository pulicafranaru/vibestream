import Foundation

// An episode's state from the season payload and the live download poll together.
// A live download that has not failed wins over a stale payload.
enum EpisodePhase: Equatable {
    case playable
    case waiting
    case arriving(Double?)
    case preparing(Double?)
    case failed(String)
    case downloadable
    case unobtainable

    var busy: Bool {
        switch self {
        case .waiting, .arriving, .preparing: true
        default: false
        }
    }
}

extension EpisodeItem {
    // By release id, but a pack fetched an episode at a time counts only for the
    // episodes asked for.
    func liveDownload(in downloads: [Int: DownloadState]) -> DownloadState? {
        let label = "S\(season):E\(episode)"
        for release in releases ?? [] {
            if let fresh = downloads[release.id], fresh.state != "removed" {
                if let wanted = fresh.episodes, !wanted.contains(label) { continue }
                return fresh
            }
        }
        return downloads.isEmpty ? download : nil
    }

    private static let unprepared = "Arrived, but could not be made playable."

    func phase(in downloads: [Int: DownloadState]) -> EpisodePhase {
        if playable { return .playable }
        if let live = liveDownload(in: downloads) {
            if live.isWorking {
                // Not via TitleAction.of, which answers Play first for a pack already partly playable.
                if live.state == "downloading" { return .arriving(live.percent >= 1 ? live.percent : nil) }
                return .waiting
            }
            if live.state == "error" {
                return .failed(live.errorMessage ?? "The download could not start.")
            }
            if live.prepareError != nil || prepareError != nil { return .failed(Self.unprepared) }
            // Settled without error: preparing, even if the payload has not caught up.
            if live.error == nil { return .preparing(live.preparePercent) }
        }
        if preparing { return .preparing(nil) }
        if prepareError != nil { return .failed(Self.unprepared) }
        if available { return .preparing(nil) }
        return (releases ?? []).isEmpty ? .unobtainable : .downloadable
    }
}
