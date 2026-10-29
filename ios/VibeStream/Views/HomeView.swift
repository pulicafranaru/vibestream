import SwiftUI

struct HomeView: View {
    @Environment(AppState.self) private var state
    @Environment(\.horizontalSizeClass) private var sizeClass

    /// "movie" or "tv".
    let kind: String
    @Binding var selection: Card?
    @Binding var playing: PlayRequest?

    @State private var destination: BrowseTarget?
    @State private var genres: [GenreCount] = []

    private static let genreMinimum = 12
    private static let genreLimit = 18

    private var wide: Bool { sizeClass == .regular }
    private var posterWidth: CGFloat { wide ? Metrics.posterWidthPad : Metrics.posterWidth }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 22) {
                if let hero = state.feeds[kind]?.hero {
                    HeroSection(card: hero, wide: wide,
                                selection: $selection, playing: $playing)
                        .padding(.horizontal, wide ? 0 : 12)
                }

                PlayingElsewhereRow(width: wide ? 340 : 260)

                if !state.rows(kind).contains(where: { $0.id == "continue" }) {
                    chips
                }

                ForEach(state.rows(kind)) { row in
                    if row.id == "continue" {
                        CardRow(title: "Resume Watching",
                                items: row.items) { card in
                            ContinueCard(card: card, width: posterWidth * 1.2)
                            .onTapGesture { play(card) }
                        }
                        chips
                    } else {
                        CardRow(title: row.title, items: row.items) { card in
                            PosterCard(card: card, width: posterWidth)
                                .onTapGesture { if !card.isLocked { selection = card } }
                        }
                    }
                }

                if state.rows(kind).isEmpty && !state.loading {
                    empty
                }
            }
            .padding(.bottom, 24)
        }
        .softTopEdge()
        .scrollIndicators(.hidden)
        // Explicit background: in an iPad window the stack gets a raised grey and the fade shows a seam.
        .background(Palette.ground.ignoresSafeArea())
        #if DEBUG
        // -scrollEnd: open scrolled to the very bottom, to see the last row.
        .defaultScrollAnchor(ProcessInfo.processInfo.arguments.contains("-scrollEnd") ? .bottom : nil)
        #endif
        .refreshable { await state.loadFeed() }
        .overlay { if state.loading && state.feeds[kind] == nil { BootSpinner() } }
        .navigationDestination(item: $destination) { target in
            BrowseView(target: target, selection: $selection, playing: $playing)
                .environment(state)
        }
        .task {
            guard genres.isEmpty else { return }
            genres = ((try? await APIClient.shared.genres(mediaType: kind)) ?? [])
                .filter { $0.count >= Self.genreMinimum }
            #if DEBUG
            openDebugDestination()
            #endif
        }
    }

    #if DEBUG
    /// Launch arguments for the simulator, which cannot tap a SwiftUI Button:
    ///     -browse movies | shows | new | Action
    ///     -media <mediaID>
    private func openDebugDestination() {
        let arguments = ProcessInfo.processInfo.arguments

        if let flag = arguments.firstIndex(of: "-media"),
           arguments.index(after: flag) < arguments.endIndex,
           let id = Int(arguments[arguments.index(after: flag)]) {
            Task {
                if let card = try? await APIClient.shared.media(id) { selection = card }
            }
        }

        guard let flag = arguments.firstIndex(of: "-browse"),
              arguments.index(after: flag) < arguments.endIndex else { return }
        switch arguments[arguments.index(after: flag)] {
        case "movies": destination = .movies
        case "shows": destination = .shows
        case "new": destination = .newAndHot
        case let name: destination = .genre(name)
        }
    }
    #endif

    @ViewBuilder private var chips: some View {
        if !genres.isEmpty {
            ScrollView(.horizontal) {
                HStack(spacing: 8) {
                    ForEach(genres.prefix(Self.genreLimit)) { genre in
                        Button { destination = .category(genre.name, kind) } label: {
                            Text(genre.name.uppercased())
                                .font(.system(size: 14, weight: .bold))
                                .tracking(0.4)
                                .lineLimit(1)
                                .foregroundStyle(.white)
                                .padding(.horizontal, 20)
                                .frame(minWidth: 112, minHeight: 58)
                                .background {
                                    let colour = GenreColor.of(genre.name)
                                    RoundedRectangle(cornerRadius: 10)
                                        .fill(Palette.chip)
                                        .overlay(
                                            LinearGradient(colors: [colour.opacity(0.42), colour.opacity(0.12)],
                                                           startPoint: .topLeading, endPoint: .bottomTrailing),
                                            in: .rect(cornerRadius: 10))
                                }
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 16)
            }
            .scrollIndicators(.hidden)
        }
    }

    private var empty: some View {
        VStack(spacing: 10) {
            Image(systemName: "film.stack").font(.largeTitle).foregroundStyle(Palette.faint)
            Text(state.loadError ?? "Nothing in the catalog yet")
                .font(.subheadline).foregroundStyle(Palette.dim)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity).padding(.top, 60)
    }

    private func play(_ card: Card) {
        // The play id names the episode; the download id would start the pack's largest file.
        if let playID = card.resumePlayID {
            playing = PlayRequest(playID: playID, title: card.resumeTitle)
        } else if let id = card.playableDownloadID {
            playing = PlayRequest(playID: String(id), title: card.title)
        } else {
            selection = card
        }
    }
}

/// `buttonStyle` takes a concrete type, so the style is erased to pick one at runtime.
struct AnyButtonStyle: PrimitiveButtonStyle {
    private let make: (Configuration) -> AnyView

    init<S: PrimitiveButtonStyle>(_ style: S) {
        make = { config in
            AnyView(
                Button(role: config.role, action: config.trigger) { config.label }
                    .buttonStyle(style)
            )
        }
    }

    func makeBody(configuration: Configuration) -> some View { make(configuration) }
}

/// A film is `"12"`; an episode is `"e34"`, since a season pack's download id cannot name one episode.
struct PlayRequest: Identifiable, Hashable {
    let playID: String
    let title: String
    var season: Int? = nil
    var episode: Int? = nil
    var startAt: Double? = nil
    var id: String { playID }

    init(playID: String, title: String, season: Int? = nil, episode: Int? = nil,
         startAt: Double? = nil) {
        self.playID = playID
        self.title = title
        self.season = season
        self.episode = episode
        self.startAt = startAt
    }

    init(downloadID: Int, title: String) {
        self.init(playID: String(downloadID), title: title)
    }
}
