import SwiftUI

/// The season chooser's face, shared by the title page and the player.
struct SeasonMenuLabel: View {
    let name: String
    var large = false

    var body: some View {
        HStack(spacing: large ? 10 : 8) {
            Text(name)
                .font(large ? .title3.weight(.semibold) : .subheadline.weight(.semibold))
            Image(systemName: "chevron.down")
                .font(large ? .body.weight(.semibold) : .caption.weight(.bold))
        }
        .padding(.horizontal, large ? 20 : 14)
        .padding(.vertical, large ? 10 : 7)
        .background(Capsule().fill(Color.white.opacity(0.16)))
        .contentShape(.capsule)
    }
}

struct PlayerEpisodes: View {
    let mediaID: Int
    let playing: PlayInfo.Presentation.Episode
    let playID: String
    let onChoose: (EpisodeItem) -> Void
    var onPreview: ((EpisodeItem) -> Void)?
    /// The close button. Nil when stacked, where there is nothing to close.
    let onClose: (() -> Void)?
    var stacked = false
    /// False on an episode's own page, where the marked one is only the one shown.
    var playingNow = true
    @Environment(AppState.self) private var state
    @Environment(\.horizontalSizeClass) private var sizeClass

    @State private var seasons: [SeasonSummary] = []
    @State private var season: Int
    @State private var episodes: [EpisodeItem]?
    @State private var fetching: Set<Int> = []
    @State private var centred: Int?

    init(mediaID: Int, playing: PlayInfo.Presentation.Episode, playID: String,
         stacked: Bool = false, playingNow: Bool = true,
         onChoose: @escaping (EpisodeItem) -> Void, onPreview: ((EpisodeItem) -> Void)? = nil,
         onClose: (() -> Void)? = nil) {
        self.mediaID = mediaID
        self.playing = playing
        self.playID = playID
        self.onChoose = onChoose
        self.onPreview = onPreview
        self.onClose = onClose
        self.stacked = stacked
        self.playingNow = playingNow
        _season = State(initialValue: playing.season)
    }

    private var stillWidth: CGFloat { sizeClass == .regular ? 220 : 150 }
    private static let flowGap: CGFloat = 10

    var body: some View {
        Group {
            if stacked { list } else { flow }
        }
        .task { seasons = (try? await APIClient.shared.media(mediaID).seasons) ?? [] }
        .task(id: season) {
            episodes = nil
            await load()
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                guard episodes?.contains(where: { phase($0).busy }) == true
                else { continue }
                await load()
            }
        }
    }

    private var list: some View {
        VStack(alignment: .leading, spacing: 16) {
            seasonMenu
            if let episodes {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(episodes, id: \.id) { row($0) }
                }
            } else {
                BootSpinner(size: 32, line: 3).frame(maxWidth: .infinity).padding(.vertical, 30)
            }
        }
        .foregroundStyle(.white)
    }

    private var flow: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                seasonMenu
                Spacer(minLength: 8)
                if let onClose {
                    Button(action: onClose) {
                        Image(systemName: "xmark")
                            .font(.system(size: 18, weight: .bold))
                            .frame(width: 44, height: 44)
                            .contentShape(.rect)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Close episodes")
                }
            }

            if let episodes {
                GeometryReader { geo in
                    let height = stillWidth * 9 / 16
                    let middle = geo.size.height / 2
                    let centreY = geo.frame(in: .global).midY
                    let step = height + Self.flowGap
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: Self.flowGap) {
                            ForEach(episodes, id: \.id) { item in
                                flowRow(item, height: height)
                                    // Scaled from the left edge, so the stills stay in one column.
                                    .visualEffect { content, proxy in
                                        let y = proxy.frame(in: .global).midY
                                        let away = min(1, abs(y - centreY) / step)
                                        return content
                                            .scaleEffect(1 - 0.16 * away, anchor: .leading)
                                            .opacity(1 - 0.62 * away)
                                    }
                            }
                        }
                        .padding(.horizontal, 6)
                        .scrollTargetLayout()
                    }
                    // Every row is one height, so these margins let the first and last reach the middle.
                    .contentMargins(.vertical, max(0, middle - height / 2), for: .scrollContent)
                    .scrollTargetBehavior(.viewAligned(limitBehavior: .always))
                    .scrollPosition(id: $centred, anchor: .center)
                    .scrollIndicators(.hidden)
                    .mask {
                        LinearGradient(stops: [.init(color: .clear, location: 0),
                                               .init(color: .black, location: 0.1),
                                               .init(color: .black, location: 0.9),
                                               .init(color: .clear, location: 1)],
                                       startPoint: .top, endPoint: .bottom)
                    }
                    .onAppear {
                        centred = episodes.first { isCurrent($0) }?.id ?? episodes.first?.id
                        #if DEBUG
                        // -flowAt <number>: that episode in the middle, to look at.
                        let args = ProcessInfo.processInfo.arguments
                        if let at = args.firstIndex(of: "-flowAt"), at + 1 < args.count,
                           let number = Int(args[at + 1]) {
                            centred = episodes.first { $0.episode == number }?.id ?? centred
                        }
                        #endif
                    }
                }
            } else {
                BootSpinner(size: 32, line: 3).frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .foregroundStyle(.white)
    }

    private func flowRow(_ item: EpisodeItem, height: CGFloat) -> some View {
        let current = isCurrent(item)
        let middle = centred == item.id
        return HStack(alignment: .top, spacing: 12) {
            ZStack {
                still(item, width: stillWidth, marked: middle)
                flowMark(item, middle: middle)
            }
            .shadow(color: .black.opacity(middle ? 0.9 : 0), radius: 14, y: 8)
            VStack(alignment: .leading, spacing: 3) {
                Text("\(item.episode). \(item.name)")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(current ? Palette.dim : .white)
                    .lineLimit(2)
                if let line = statusLine(item) {
                    Text(line).font(.caption).foregroundStyle(Palette.dim).lineLimit(1)
                }
                if let overview = item.overview, !overview.isEmpty {
                    Text(overview).font(.caption).foregroundStyle(Palette.dim)
                        .layoutPriority(-1)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(height: height)
        .contentShape(.rect)
        .onTapGesture { flowTap(item) }
        .accessibilityAddTraits(.isButton)
        .animation(.easeOut(duration: 0.2), value: middle)
    }

    @ViewBuilder private func flowMark(_ item: EpisodeItem, middle: Bool) -> some View {
        switch phase(item) {
        case .waiting:
            DownloadRing(percent: nil, size: 40)
        case .arriving(let percent), .preparing(let percent):
            DownloadRing(percent: percent, size: 40, showsLabel: false)
        case .downloadable where middle && item.releases?.first != nil:
            Image(systemName: "arrow.down.to.line")
                .font(.system(size: 16, weight: .semibold))
                .frame(width: 40, height: 40)
                .background(Circle().fill(.black.opacity(0.45)))
                .overlay(Circle().strokeBorder(.white.opacity(0.85), lineWidth: 1.5))
                .accessibilityLabel("Download episode \(item.episode)")
        default:
            EmptyView()
        }
    }

    private func flowTap(_ item: EpisodeItem) {
        guard centred == item.id else {
            withAnimation(.snappy(duration: 0.3)) { centred = item.id }
            return
        }
        guard !isCurrent(item) else { return }
        if item.playable {
            onChoose(item)
        } else if phase(item) == .downloadable, let release = item.releases?.first {
            fetch(item, release)
        }
    }

    private func load() async {
        if let fresh = try? await APIClient.shared.season(media: mediaID, number: season).episodes {
            episodes = fresh
        } else if episodes == nil {
            episodes = []
        }
    }

    private var seasonMenu: some View {
        Menu {
            ForEach(seasons) { item in
                Button(item.name) { season = item.number }
            }
        } label: {
            SeasonMenuLabel(name: seasons.first { $0.number == season }?.name ?? "Season \(season)",
                            large: !stacked)
        }
        .disabled(seasons.count < 2)
    }

    private func row(_ item: EpisodeItem) -> some View {
        let current = isCurrent(item)
        return VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center, spacing: 12) {
                still(item, width: 136)
                VStack(alignment: .leading, spacing: 4) {
                    Text("\(item.episode). \(item.name)")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(current ? Palette.faint : .white)
                        .lineLimit(2)
                    if let line = statusLine(item) {
                        Text(line).font(.footnote).foregroundStyle(Palette.faint)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                fetchControl(item)
            }
            if let overview = item.overview, !overview.isEmpty {
                Text(overview)
                    .font(.footnote)
                    .foregroundStyle(current ? Palette.faint : Palette.dim)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .contentShape(.rect)
        .onTapGesture { tap(item) }
        .accessibilityAddTraits(!current ? .isButton : [])
        .opacity(phase(item) == .unobtainable ? 0.55 : 1)
    }

    private func tap(_ item: EpisodeItem) {
        guard !isCurrent(item) else { return }
        if item.playable { onChoose(item) } else { onPreview?(item) }
    }

    private func phase(_ item: EpisodeItem) -> EpisodePhase {
        fetching.contains(item.id) ? .waiting : item.phase(in: state.downloads)
    }

    private func statusLine(_ item: EpisodeItem) -> String? {
        if playingNow && isCurrent(item) { return "Now playing" }
        switch phase(item) {
        case .waiting: return "Waiting for download"
        case .arriving(let percent):
            var parts = [percent.map { "Downloading \(Int($0))%" } ?? "Downloading"]
            if let live = item.liveDownload(in: state.downloads) {
                if let speed = live.dlSpeed, speed > 0 { parts.append("\(fileSize(speed))/s") }
                if let eta = live.etaSeconds, eta > 0, eta < 360_000 { parts.append("\(max(1, eta / 60))m left") }
            }
            return parts.joined(separator: " · ")
        case .preparing(let percent): return percent.map { "Preparing \(Int($0))%" } ?? "Preparing"
        case .failed(let error): return error
        default:
            guard let runtime = item.runtime, runtime > 0 else { return nil }
            return runtime >= 60 ? "\(runtime / 60)h \(runtime % 60)m" : "\(runtime)m"
        }
    }

    /// An episode not downloaded has no play id; its page passes "e" and its id.
    private func isCurrent(_ item: EpisodeItem) -> Bool {
        (item.playID != nil && item.playID == playID) || "e\(item.id)" == playID
    }

    private func still(_ item: EpisodeItem, width: CGFloat, marked: Bool = true) -> some View {
        let current = isCurrent(item)
        return ZStack {
                RemoteImage(url: item.still.flatMap(URL.init(string:)))
                    .frame(width: width, height: width * 9 / 16)
                    .clipped()
                if current {
                    Color.black.opacity(0.55)
                    if playingNow {
                        Image(systemName: "waveform")
                            .font(.system(size: 26, weight: .bold))
                            .foregroundStyle(.white)
                            .shadow(color: .black.opacity(0.6), radius: 4)
                            .symbolEffect(.variableColor.iterative)
                            .accessibilityLabel("Now playing")
                    }
                } else if item.playable && marked {
                    Image(systemName: "play.fill")
                        .font(.system(size: 16))
                        .frame(width: 40, height: 40)
                        .background(Circle().fill(.black.opacity(0.45)))
                        .overlay(Circle().strokeBorder(.white.opacity(0.85), lineWidth: 1.5))
                }
                if item.watched || item.resumePercent > 1 {
                    VStack {
                        Spacer()
                        GeometryReader { geo in
                            ZStack(alignment: .leading) {
                                Rectangle().fill(Color.white.opacity(0.35))
                                Rectangle().fill(Palette.accent)
                                    .frame(width: geo.size.width * (item.watched ? 1 : item.resumePercent / 100))
                            }
                        }
                        .frame(height: 3)
                    }
                }
            }
            .frame(width: width, height: width * 9 / 16)
            .background(Color.black)
            .clipShape(.rect(cornerRadius: 4))
    }

    @ViewBuilder private func fetchControl(_ item: EpisodeItem) -> some View {
        switch phase(item) {
        case .waiting:
            DownloadRing(percent: nil, size: 30).frame(width: 40, height: 40)
        case .arriving(let percent), .preparing(let percent):
            DownloadRing(percent: percent, size: 30, showsLabel: false).frame(width: 40, height: 40)
        case .downloadable:
            if let release = item.releases?.first {
                Button { fetch(item, release) } label: {
                    Image(systemName: "arrow.down.to.line")
                        .font(.system(size: 17, weight: .semibold))
                        .frame(width: 40, height: 40)
                        .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.white)
                .accessibilityLabel("Download episode \(item.episode)")
            }
        default:
            EmptyView()
        }
    }

    private func fetch(_ item: EpisodeItem, _ release: EpisodeItem.EpisodeRelease) {
        fetching.insert(item.id)
        Task {
            _ = try? await state.download(torrent: release.id,
                                          episode: release.seasonPack ? item.id : nil)
            await load()
            fetching.remove(item.id)
        }
    }
}
