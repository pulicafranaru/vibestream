import SwiftUI

/// What the Download Season button stands for, for the season on screen.
enum SeasonStatus: Equatable {
    case offer(SeasonDetail.SeasonPack)
    /// Every aired episode is here, each with the download that holds it.
    case downloaded([HeldEpisode])
}

struct HeldEpisode: Hashable {
    let episode: Int
    let download: Int
}

struct EpisodeList: View {
    @Environment(AppState.self) private var state

    let card: Card
    /// Owned by the title sheet so it survives tab switches and the player.
    @Binding var seasonNumber: Int?
    @Binding var seasonStatus: SeasonStatus?
    var revision: Int = 0
    var playingID: String? = nil
    var onPlay: (PlayRequest) -> Void

    @State private var episodes: [EpisodeItem] = []
    @State private var episodesFor: Int?
    @State private var failureFor: Int?
    @State private var failure: String?
    @State private var downloadNote: String?
    @State private var seasonPack: SeasonDetail.SeasonPack?
    @State private var queuingSeason = false
    @State private var queuing: Set<Int> = []
    @State private var confirmingDelete: EpisodeItem?
    @State private var removing: Set<Int> = []
    @Environment(\.openTitle) private var openTitle

    private var seasons: [SeasonSummary] { card.seasons ?? [] }

    private var current: SeasonSummary? {
        seasons.first { $0.number == seasonNumber } ?? seasons.first
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if seasons.count > 1 {
                picker
            } else if let only = seasons.first {
                Text(only.name)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Palette.dim)
            }
            if waiting {
                BootSpinner(size: 32, line: 3).frame(maxWidth: .infinity).padding(.vertical, 30)
            }

            if let downloadNote {
                Text(downloadNote).font(.footnote).foregroundStyle(Palette.accent)
            }

            ForEach(shownEpisodes) { episode in
                row(episode)
            }

            if let failure, shownEpisodes.isEmpty, failureFor == seasonNumber {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Couldn't load this season.")
                        .font(.subheadline.weight(.semibold))
                    Text(failure).font(.footnote).foregroundStyle(Palette.faint).lineLimit(2)
                    Button("Try Again") {
                        failureFor = nil
                        Task { await load() }
                    }
                        .buttonStyle(.glass)
                        .foregroundStyle(.white)
                }
            }
            if episodes.isEmpty && failure == nil && seasons.isEmpty {
                Text("No episode information for this show yet.")
                    .font(.footnote).foregroundStyle(Palette.faint)
            }
        }
        // Refetch while anything in the season is moving: preparation finishes on the server
        // minutes after the download settles, with nothing to notify the app.
        #if DEBUG
        // -switchSeason <n>: switch to that season three seconds in.
        .task {
            let arguments = ProcessInfo.processInfo.arguments
            guard let flag = arguments.firstIndex(of: "-switchSeason"),
                  arguments.index(after: flag) < arguments.endIndex,
                  let number = Int(arguments[arguments.index(after: flag)]) else { return }
            try? await Task.sleep(for: .seconds(3))
            seasonNumber = number
        }
        #endif
        .task(id: LoadKey(season: seasonNumber, revision: revision)) {
            while !Task.isCancelled {
                await load()
                guard episodes.contains(where: isBusy) else { return }
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    // Derived from what is held, not a shared loading flag, which a cancelled poll could clear.
    private var waiting: Bool {
        guard let seasonNumber else { return !seasons.isEmpty }
        return episodesFor != seasonNumber && failureFor != seasonNumber
    }

    private var shownEpisodes: [EpisodeItem] {
        episodesFor == seasonNumber ? episodes : []
    }

    private struct LoadKey: Equatable {
        var season: Int?
        var revision: Int
    }

    private var picker: some View {
        Menu {
            ForEach(seasons) { season in
                Button {
                    seasonNumber = season.number
                } label: {
                    // The tick marks the season on screen, as in any menu.
                    if season.number == current?.number {
                        Label(season.name, systemImage: "checkmark")
                    } else {
                        Text(season.name)
                    }
                    if season.hasFiles {
                        Text("Downloaded")
                    }
                }
            }
        } label: {
            SeasonMenuLabel(name: current?.name ?? "Season")
        }
        .buttonStyle(.plain)
        .foregroundStyle(.white)
    }

    private func row(_ episode: EpisodeItem) -> some View {
        let phase = phase(of: episode)
        let now = playingID != nil && episode.playID == playingID
        return VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 12) {
                still(episode, phase, playing: now)
                    .overlay(alignment: .bottomLeading) {
                        if now {
                            Image(systemName: "waveform")
                                .font(.caption.weight(.bold))
                                .foregroundStyle(.white)
                                .padding(.horizontal, 7).padding(.vertical, 4)
                                .background(.black.opacity(0.6), in: .capsule)
                                .padding(5)
                        }
                    }

                VStack(alignment: .leading, spacing: 3) {
                    Text("\(episode.episode). \(episode.name)")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(phase == .unobtainable ? Palette.dim : .white)
                        .lineLimit(2)
                    if let length = episode.lengthLabel {
                        Text(length).font(.caption).foregroundStyle(Palette.faint)
                    }
                    if now {
                        Text("Playing").font(.caption.weight(.semibold)).foregroundStyle(Palette.accent)
                    } else {
                        status(episode, phase)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                action(episode, phase)
            }

            if let overview = episode.overview, !overview.isEmpty {
                Text(overview)
                    .font(.footnote)
                    .foregroundStyle(Palette.dim)
                    .lineLimit(3)
            }
        }
        .padding(.vertical, 6)
        .padding(.horizontal, now ? 8 : 0)
        .background {
            if now { RoundedRectangle(cornerRadius: 12).fill(.white.opacity(0.07)) }
        }
        .padding(.horizontal, now ? -8 : 0)
        .contentShape(.rect)
        .onTapGesture { if !now { open(episode) } }
        .accessibilityAddTraits(.isButton)
        .opacity(phase == .unobtainable ? 0.55 : 1)
    }

    private func phase(of episode: EpisodeItem) -> EpisodePhase {
        queuing.contains(episode.id) ? .waiting : episode.phase(in: state.downloads)
    }

    private func still(_ episode: EpisodeItem, _ phase: EpisodePhase, playing: Bool = false) -> some View {
        ZStack {
            RemoteImage(url: episode.still.flatMap(URL.init(string:)))
                .frame(width: 116, height: 66)
                .clipped()

            if phase == .playable && !playing {
                Circle()
                    .fill(.black.opacity(0.35))
                    .frame(width: 30, height: 30)
                    .overlay(Circle().stroke(.white.opacity(0.9), lineWidth: 1.2))
                    .overlay(Image(systemName: "play.fill").font(.system(size: 12)).offset(x: 1))
            } else if phase == .downloadable {
                Circle()
                    .fill(.black.opacity(0.35))
                    .frame(width: 30, height: 30)
                    .overlay(Circle().stroke(.white.opacity(0.9), lineWidth: 1.2))
                    .overlay(Image(systemName: "arrow.down.to.line").font(.system(size: 12, weight: .semibold)))
            } else if phase == .unobtainable {
                Image(systemName: episode.comingOn != nil ? "clock" : "icloud.slash")
                    .font(.system(size: 15))
                    .foregroundStyle(.white.opacity(0.85))
            }
        }
        .frame(width: 116, height: 66)
        .clipShape(.rect(cornerRadius: 6))
        .overlay(alignment: .bottom) {
            if episode.resumePercent > 1 && !episode.watched {
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Rectangle().fill(.white.opacity(0.3))
                        Rectangle().fill(Palette.accent)
                            .frame(width: geo.size.width * min(1, episode.resumePercent / 100))
                    }
                }
                .frame(height: 3)
            }
        }
    }

    // Download Episode fetches only that file, even from a season pack.
    @ViewBuilder private func action(_ episode: EpisodeItem, _ phase: EpisodePhase) -> some View {
        switch phase {
        case .playable:
            if episode.downloadID != nil { deleteButton(episode) }
        case .waiting:
            DownloadRing(percent: nil, size: 30).frame(width: 40, height: 40)
        case .arriving(let percent), .preparing(let percent):
            DownloadRing(percent: percent, size: 30).frame(width: 40, height: 40)
        case .downloadable:
            downloadMenu(episode)
        case .failed, .unobtainable:
            EmptyView()
        }
    }

    @ViewBuilder private func deleteButton(_ episode: EpisodeItem) -> some View {
        if removing.contains(episode.id) {
            BootSpinner(size: 20, line: 2.5).frame(width: 40, height: 40)
        } else {
            Button {
                confirmingDelete = episode
            } label: {
                Image(systemName: "trash")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 40, height: 40)
                    .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Delete episode \(episode.episode)")
            // On the button so the iPad popover points at this row.
            .confirmationDialog(
                "Delete S\(episode.season):E\(episode.episode)?",
                isPresented: Binding(get: { confirmingDelete?.id == episode.id },
                                     set: { if !$0 { confirmingDelete = nil } }),
                titleVisibility: .visible
            ) {
                Button("Delete Episode", role: .destructive) { remove(episode) }
            } message: {
                Text("This removes the episode from the server and from your library. The rest of the season stays.")
            }
        }
    }

    private func downloadMenu(_ episode: EpisodeItem) -> some View {
        let releases = episode.releases ?? []
        return Menu {
            ForEach(releases) { release in
                Button {
                    start(release, for: episode)
                } label: {
                    Text("Download Episode" + (release.episodeCost.map { " · \($0)" } ?? ""))
                    Text(release.resolution ?? release.name)
                }
            }
            if let pack = seasonPack, pack.completeRequest != true {
                Button {
                    startSeason(pack)
                } label: {
                    Text("Download Season" + (pack.sizeGB.map { String(format: " · %.1f GB", $0) } ?? ""))
                }
            }
        } label: {
            Image(systemName: "arrow.down.to.line")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 40, height: 40)
                .contentShape(.rect)
        }
        .accessibilityLabel("Download episode \(episode.episode)")
    }

    @ViewBuilder private func status(_ episode: EpisodeItem, _ phase: EpisodePhase) -> some View {
        switch phase {
        case .waiting:
            Text("Waiting for download").font(.caption2).foregroundStyle(Palette.dim)
        case .arriving(let percent):
            Text(percent.map { "Downloading \(Int($0))%" } ?? "Downloading")
                .font(.caption2).foregroundStyle(Palette.dim)
        case .preparing(let percent):
            Text(percent.map { "Preparing \(Int($0))%" } ?? "Preparing")
                .font(.caption2).foregroundStyle(Palette.faint)
        case .failed(let error):
            HStack(spacing: 4) {
                ErrorBadge(size: 12)
                Text(error).font(.caption2).foregroundStyle(Palette.danger).lineLimit(1)
            }
        case .playable:
            if episode.watched {
                Label("Watched", systemImage: "checkmark.circle.fill")
                    .font(.caption2)
                    .foregroundStyle(Color(red: 0.27, green: 0.83, blue: 0.41))
            }
        case .unobtainable:
            if let date = episode.comingOn {
                Text("Coming \(date.formatted(.dateTime.day().month(.abbreviated)))")
                    .font(.caption2).foregroundStyle(Palette.faint)
            } else {
                // Aired, but nobody has uploaded it. Not the same as "coming".
                Text("Not available yet").font(.caption2).foregroundStyle(Palette.faint)
            }
        case .downloadable:
            Text("Not downloaded").font(.caption2).foregroundStyle(Palette.faint)
        }
    }

    private func open(_ episode: EpisodeItem) {
        if let playID = episode.playID, episode.playable {
            onPlay(PlayRequest(playID: playID, title: card.title,
                               season: episode.season, episode: episode.episode))
        } else if phase(of: episode) == .downloadable, let release = episode.releases?.first {
            start(release, for: episode)
        }
    }

    /// Judged with the live download as well as the payload, or polling stops in the gap between them.
    private func isBusy(_ episode: EpisodeItem) -> Bool {
        phase(of: episode).busy
    }

    private func start(_ release: EpisodeItem.EpisodeRelease, for episode: EpisodeItem) {
        queuing.insert(episode.id)
        Task {
            do {
                downloadNote = nil
                try await state.download(torrent: release.id,
                                         episode: release.seasonPack ? episode.id : nil)
                await load()
            } catch {
                downloadNote = "Couldn't start the download: \(error.localizedDescription)"
            }
            queuing.remove(episode.id)
        }
    }

    private func startSeason(_ pack: SeasonDetail.SeasonPack) {
        queuingSeason = true
        Task {
            do {
                downloadNote = nil
                // A pack already being fetched an episode at a time is asked
                // for whole; one not started yet is simply started.
                try await state.download(torrent: pack.id, everything: pack.download != nil)
                await load()
            } catch {
                downloadNote = "Couldn't start the download: \(error.localizedDescription)"
            }
            queuingSeason = false
        }
    }

    static func status(of detail: SeasonDetail) -> SeasonStatus? {
        let held = detail.episodes.compactMap { episode in
            episode.available ? episode.downloadID.map { HeldEpisode(episode: episode.id, download: $0) } : nil
        }
        let missing = detail.episodes.contains { !$0.available && $0.comingOn == nil }
        if !missing && !held.isEmpty { return .downloaded(held) }
        if detail.episodes.contains(where: { !$0.available }), let pack = detail.seasonPack {
            return .offer(pack)
        }
        return nil
    }

    private func remove(_ episode: EpisodeItem) {
        guard let download = episode.downloadID else { return }
        removing.insert(episode.id)
        Task {
            do {
                downloadNote = nil
                try await APIClient.shared.deleteEpisode(episode.id, of: download)
                await state.refreshDownloads()
                await load()
            } catch {
                downloadNote = "Couldn't delete the episode: \(error.localizedDescription)"
            }
            removing.remove(episode.id)
        }
    }

    private func load() async {
        guard let number = seasonNumber else { return }
        // Another season's offer must not sit under this season's name.
        if episodesFor != number { seasonStatus = nil }
        let media = card.mediaID
        // Fetched in its own Task so cancelling the view's task (a season change) does not drop the reply.
        let result = await Task {
            try await APIClient.shared.season(media: media, number: number)
        }.result
        // A reply for a season that is no longer the chosen one is dropped.
        guard number == seasonNumber else { return }
        switch result {
        case .success(let detail):
            episodes = detail.episodes
            seasonPack = detail.seasonPack
            seasonStatus = Self.status(of: detail)
            episodesFor = number
            failure = nil
            failureFor = nil
        case .failure(let error):
            // A poll that fails keeps the season it already has on screen.
            guard episodesFor != number else { return }
            failure = error.localizedDescription
            failureFor = number
        }
    }
}
