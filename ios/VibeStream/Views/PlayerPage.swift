import SwiftUI

// What sits under the picture when a phone is held upright; also the remote for a film playing elsewhere.
struct PlayerPage: View {
    let playID: String
    let title: String
    let mediaID: Int?
    let presentation: PlayInfo.Presentation?
    var loaded: Bool
    var onEpisode: ((EpisodeItem) -> Void)?
    var onPreview: ((EpisodeItem) -> Void)? = nil
    var tracks: TrackChoices?
    /// For the episode's About when the play id does not say (an episode not downloaded has none).
    var episodeID: Int? = nil
    var previewing = false
    var onTitle: (Card) -> Void

    @Environment(AppState.self) private var state
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var tab: Tab?
    @State private var card: Card?
    @State private var similar: [Card]?
    @State private var similarFor: Int?
    @State private var episodeAbout: EpisodeAbout?
    @State private var collection: CollectionTarget?
    @State private var expanded = false

    private enum Tab: String, Identifiable {
        case episodes = "Episodes", about = "About", similar = "Similar", tracks = "Audio & Subtitles"
        var id: String { rawValue }
    }

    private var tabs: [Tab] {
        var list: [Tab] = presentation?.episode != nil && onEpisode != nil ? [.episodes] : []
        list += [.about, .similar]
        if tracks != nil { list.append(.tracks) }
        return list
    }

    #if DEBUG
    /// -pageTab <episodes|about|similar|audio>: open on that tab.
    init(playID: String, title: String, mediaID: Int?, presentation: PlayInfo.Presentation?,
         loaded: Bool, onEpisode: ((EpisodeItem) -> Void)? = nil,
         onPreview: ((EpisodeItem) -> Void)? = nil, tracks: TrackChoices? = nil,
         episodeID: Int? = nil, previewing: Bool = false, onTitle: @escaping (Card) -> Void) {
        self.playID = playID
        self.title = title
        self.mediaID = mediaID
        self.presentation = presentation
        self.loaded = loaded
        self.onEpisode = onEpisode
        self.onPreview = onPreview
        self.tracks = tracks
        self.episodeID = episodeID
        self.previewing = previewing
        self.onTitle = onTitle
        let args = ProcessInfo.processInfo.arguments
        if let flag = args.firstIndex(of: "-pageTab"), flag + 1 < args.count {
            _tab = State(initialValue: [Tab.episodes, .about, .similar, .tracks]
                .first { $0.rawValue.lowercased().hasPrefix(args[flag + 1].lowercased()) })
        }
    }
    #endif

    private var shownTab: Tab { tab.flatMap { tabs.contains($0) ? $0 : nil } ?? tabs[0] }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header
                if loaded {
                    tabStrip
                    content
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 14)
            .padding(.bottom, 30)
        }
        .scrollIndicators(.hidden)
        .background(Palette.ground)
        .task(id: mediaID) {
            // On a remote, the TV can move on to another title altogether.
            guard let mediaID, card?.mediaID != mediaID else { return }
            card = try? await APIClient.shared.media(mediaID)
        }
        .environment(\.openURL, OpenURLAction { url in
            guard let target = CollectionTarget(url: url) else { return .discarded }
            collection = target
            return .handled
        })
        .sheet(item: $collection) { target in
            CollectionView(target: target) { other in
                collection = nil
                onTitle(other)
            } onClose: {
                collection = nil
            }
            .environment(state)
            .presentationBackground(Palette.ground)
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(presentation?.title ?? title)
                .font(.title3.weight(.bold))
                .foregroundStyle(.white)
            if let line = presentation?.episodeLine {
                Text(line)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.white.opacity(0.85))
            }
            if let meta = metaLine {
                Text(meta).font(.footnote).foregroundStyle(Palette.faint)
            }
            if let overview = presentation?.overview, !overview.isEmpty {
                Text(overview)
                    .font(.subheadline)
                    .foregroundStyle(Palette.dim)
                    .lineLimit(expanded ? nil : 3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 4)
                    .contentShape(.rect)
                    .onTapGesture { withAnimation(.snappy) { expanded.toggle() } }
                    .accessibilityAddTraits(.isButton)
                    .accessibilityHint(expanded ? "Shows less" : "Shows all of it")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var metaLine: String? {
        var parts: [String] = []
        if let year = presentation?.year ?? card?.year { parts.append(String(year)) }
        if let score = card?.voteAverage, score > 0 { parts.append(String(format: "%.1f", score)) }
        if let genres = card?.genres, !genres.isEmpty { parts.append(genres.prefix(2).joined(separator: ", ")) }
        return parts.isEmpty ? nil : parts.joined(separator: "  ·  ")
    }

    private var tabStrip: some View {
        // Four tabs do not fit across a phone at full size.
        ViewThatFits(in: .horizontal) {
            tabRow(.subheadline, spacing: 22)
            tabRow(.footnote, spacing: 18)
            tabRow(.caption, spacing: 14)
        }
    }

    private func tabRow(_ font: Font, spacing: CGFloat) -> some View {
        HStack(spacing: spacing) {
            ForEach(tabs) { option in
                let chosen = option == shownTab
                Button { withAnimation(.snappy) { tab = option } } label: {
                    VStack(spacing: 6) {
                        Text(option.rawValue)
                            .font(font.weight(chosen ? .bold : .regular))
                            .foregroundStyle(chosen ? .white : Palette.faint)
                        Rectangle()
                            .fill(chosen ? Palette.accent : .clear)
                            .frame(height: 3)
                    }
                }
                .buttonStyle(.plain)
                .fixedSize()
            }
        }
    }

    @ViewBuilder private var content: some View {
        switch shownTab {
        case .episodes:
            if let mediaID, let episode = presentation?.episode, let onEpisode {
                PlayerEpisodes(mediaID: mediaID, playing: episode, playID: playID,
                               stacked: true, playingNow: !previewing,
                               onChoose: onEpisode, onPreview: onPreview)
                    .id(playID)
            }
        case .about:
            if let card {
                VStack(alignment: .leading, spacing: 14) {
                    if presentation?.episode != nil, let episodeAbout {
                        episodeSection(episodeAbout)
                        Divider().overlay(Color.white.opacity(0.1)).padding(.vertical, 6)
                    }
                    if presentation?.episode != nil {
                        Text("About \(card.title)")
                            .font(.title3.weight(.bold))
                            .foregroundStyle(.white)
                    }
                    if presentation?.episode != nil, let overview = card.overview, !overview.isEmpty {
                        Text(overview).font(.subheadline).foregroundStyle(Palette.dim)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    TitleAbout(card: card, heading: presentation?.episode == nil)
                }
                .task(id: playID) {
                    // An episode's play id is "e" and its id.
                    guard presentation?.episode != nil,
                          let id = episodeID ?? (playID.hasPrefix("e") ? Int(playID.dropFirst()) : nil)
                    else { return }
                    episodeAbout = nil
                    episodeAbout = try? await APIClient.shared.episodeAbout(id)
                }
            } else {
                loading
            }
        case .similar:
            similarGrid
        case .tracks:
            if let tracks { TrackSettings(choices: tracks) }
        }
    }

    @ViewBuilder private var similarGrid: some View {
        Group {
            if let similar, similar.isEmpty {
                Text("Nothing like this in the catalog yet")
                    .font(.footnote).foregroundStyle(Palette.faint)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if let similar {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12),
                                         count: sizeClass == .regular ? 5 : 3),
                          spacing: 12) {
                    ForEach(similar) { other in
                        PosterCard(card: other, width: nil)
                            .onTapGesture { onTitle(other) }
                            .accessibilityAddTraits(.isButton)
                            .accessibilityLabel(other.title)
                    }
                }
            } else {
                loading
            }
        }
        .task(id: mediaID) {
            guard let mediaID, similarFor != mediaID else { return }
            similar = nil
            similar = (try? await APIClient.shared.similar(mediaID)) ?? []
            similarFor = mediaID
        }
    }

    private func episodeSection(_ about: EpisodeAbout) -> some View {
        let person: (String) -> (String, CollectionTarget?) = { name in
            (name, about.personIDs?[name].map { CollectionTarget(kind: .person($0), title: name) })
        }
        var meta: [String] = []
        if let aired = about.airDate, let date = Self.airDate.date(from: aired) {
            meta.append("Aired \(date.formatted(.dateTime.day().month(.wide).year()))")
        }
        if let runtime = about.runtime, runtime > 0 {
            meta.append(runtime >= 60 ? "\(runtime / 60)h \(runtime % 60)m" : "\(runtime)m")
        }
        if let score = about.voteAverage, score > 0 { meta.append(String(format: "%.1f", score)) }
        return VStack(alignment: .leading, spacing: 12) {
            Text("This Episode")
                .font(.title3.weight(.bold))
                .foregroundStyle(.white)
            if !meta.isEmpty {
                Text(meta.joined(separator: "  ·  ")).foregroundStyle(Palette.dim)
            }
            if let directors = about.directors, !directors.isEmpty {
                TitleAbout.linkRow(directors.count == 1 ? "Directed by" : "Directors", directors.map(person))
            }
            if let writers = about.writers, !writers.isEmpty {
                TitleAbout.linkRow("Written by", writers.map(person))
            }
            if let guests = about.guestStars, !guests.isEmpty {
                TitleAbout.linkRow("Guest Stars", guests.map { guest in
                    let (name, target) = person(guest.name)
                    return (guest.character.map { "\(name) (\($0))" } ?? name, target)
                })
            }
        }
        .font(.subheadline)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private static let airDate: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        return formatter
    }()

    private var loading: some View {
        BootSpinner(size: 32, line: 3).frame(maxWidth: .infinity).padding(.vertical, 30)
    }
}
