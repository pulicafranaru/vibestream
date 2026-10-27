import SwiftUI

enum BrowseTarget: Hashable {
    case movies
    case shows
    case newAndHot
    case genre(String)
    /// A genre within Movies ("movie") or Shows ("tv"), from those tabs.
    case category(String, String)

    var title: String {
        switch self {
        case .movies: "Movies"
        case .shows: "Shows"
        case .newAndHot: "New & Hot"
        case let .genre(name): name
        case let .category(name, _): name
        }
    }

    var mediaType: String? {
        switch self {
        case .movies: "movie"
        case .shows: "tv"
        default: nil
        }
    }

    var isFlat: Bool {
        if case .genre = self { return true }
        if case .category = self { return true }
        return false
    }
}

struct BrowseView: View {
    @Environment(AppState.self) private var state
    @Environment(\.horizontalSizeClass) private var sizeClass

    let target: BrowseTarget
    @Binding var selection: Card?
    @Binding var playing: PlayRequest?

    @State private var rows: [HomeFeed.Row] = []
    @State private var hero: Card?
    @State private var flat: [Card] = []
    @State private var loading = true
    @State private var failure: String?
    @State private var categories: [GenreCount] = []
    @State private var category: String?

    private var showsGrid: Bool { target.isFlat || category != nil }

    private var wide: Bool { sizeClass == .regular }
    private var posterWidth: CGFloat { wide ? Metrics.posterWidthPad : Metrics.posterWidth }

    // Fixed three columns on a phone: an adaptive grid fitted only two on 375 to 393 pt widths.
    private var columns: [GridItem] {
        wide
            ? [GridItem(.adaptive(minimum: posterWidth), spacing: 12)]
            : Array(repeating: GridItem(.flexible(), spacing: 8), count: 3)
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 20) {
                if target.mediaType != nil && !categories.isEmpty {
                    categoriesMenu
                        .frame(maxWidth: .infinity)
                }

                if let hero {
                    HeroSection(card: hero, wide: wide,
                                selection: $selection, playing: $playing)
                        .padding(.horizontal, wide ? 0 : 12)
                }

                if showsGrid {
                    LazyVGrid(columns: columns, spacing: 14) {
                        ForEach(flat) { card in
                            PosterCard(card: card, width: wide ? posterWidth : nil)
                                .onTapGesture { selection = card }
                        }
                    }
                    .padding(.horizontal, 16)
                } else {
                    ForEach(rows) { row in
                        CardRow(title: row.title, items: row.items) { card in
                            PosterCard(card: card, width: posterWidth)
                                .onTapGesture { selection = card }
                        }
                    }
                }

                if !loading && (showsGrid ? flat.isEmpty && hero == nil : rows.isEmpty) {
                    empty
                }
            }
            .padding(.top, 8)
            .padding(.bottom, 24)
        }
        .background(Palette.ground)
        .softTopEdge()
        .scrollIndicators(.hidden)
        .navigationTitle(target.title)
        .navigationBarTitleDisplayMode(.inline)
        .overlay { if loading { BootSpinner() } }
        .task { await load() }
        .task { await loadCategories() }
        .refreshable { await load() }
        .onChange(of: category) { Task { await load() } }
    }

    private var categoriesMenu: some View {
        let all = target == .movies ? "All Movies" : "All Shows"
        return Menu {
            Button {
                category = nil
            } label: {
                if category == nil { Label(all, systemImage: "checkmark") } else { Text(all) }
            }
            Divider()
            ForEach(categories) { genre in
                Button {
                    category = genre.name
                } label: {
                    if category == genre.name {
                        Label(genre.name, systemImage: "checkmark")
                    } else {
                        Text(genre.name)
                    }
                }
            }
        } label: {
            HStack(spacing: 8) {
                Text(category ?? "Categories")
                    .font(.system(size: wide ? 17 : 15, weight: .semibold))
                Image(systemName: "arrowtriangle.down.fill")
                    .font(.system(size: 9))
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 18)
            .padding(.vertical, 10)
        }
        .buttonStyle(.glass)
        .accessibilityLabel(category.map { "Category: \($0)" } ?? "Categories")
    }

    private func loadCategories() async {
        guard let kind = target.mediaType else { return }
        categories = (try? await APIClient.shared.genres(mediaType: kind)) ?? []
        #if DEBUG
        // -category <name>: open narrowed to that genre.
        let arguments = ProcessInfo.processInfo.arguments
        if let flag = arguments.firstIndex(of: "-category"), arguments.index(after: flag) < arguments.endIndex {
            category = arguments[arguments.index(after: flag)]
        }
        #endif
    }

    private var empty: some View {
        VStack(spacing: 10) {
            Image(systemName: "film.stack").font(.largeTitle).foregroundStyle(Palette.faint)
            Text(failure ?? "Nothing here yet")
                .font(.subheadline).foregroundStyle(Palette.dim)
        }
        .frame(maxWidth: .infinity).padding(.top, 80)
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            // Drop a reply for a category no longer chosen: the two loads race.
            let asked = category
            if let category, let kind = target.mediaType {
                let items = try await APIClient.shared.catalog(genre: category, mediaType: kind)
                guard asked == self.category else { return }
                rows = []
                flat = items
                hero = items.first { $0.backdrop != nil && $0.overview != nil }
                if let hero { flat.removeAll { $0.mediaID == hero.mediaID } }
                failure = nil
                return
            }
            flat = []
            switch target {
            case .movies, .shows:
                let feed = try await APIClient.shared.home(mediaType: target.mediaType)
                guard asked == category else { return }
                rows = feed.rows.filter { !$0.items.isEmpty }
                hero = feed.hero
            case .newAndHot:
                // Recently added, not recently released: the catalog is swept from a tracker.
                let feed = try await APIClient.shared.home()
                rows = feed.rows.filter {
                    ["recent", "new", "uhd"].contains($0.id) && !$0.items.isEmpty
                }
                hero = rows.first?.items.first { $0.backdrop != nil }
            case let .category(name, kind):
                let items = try await APIClient.shared.catalog(genre: name, mediaType: kind)
                flat = items
                hero = items.first { $0.backdrop != nil && $0.overview != nil }
                if let hero { flat.removeAll { $0.mediaID == hero.mediaID } }
            case let .genre(name):
                let items = try await APIClient.shared.catalog(genre: name)
                flat = items
                hero = items.first { $0.backdrop != nil && $0.overview != nil }
                if let hero { flat.removeAll { $0.mediaID == hero.mediaID } }
            }
            failure = nil
        } catch {
            failure = error.localizedDescription
        }
    }
}

struct HeroSection: View {
    @Environment(AppState.self) private var state

    let card: Card
    let wide: Bool
    @Binding var selection: Card?
    @Binding var playing: PlayRequest?

    @State private var queuing = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HeroCard(
                card: card,
                wide: wide,
                download: live,
                busy: queuing,
                onPlay: play,
                onDownload: startDownload,
                onInfo: { selection = card },
                saved: state.myList.contains(card.mediaID),
                onMyList: { Task { await state.toggleMyList(card) } }
            )
        }
    }

    /// Polled state; the copy baked into the feed does not update.
    private var live: DownloadState? {
        if let primary = card.primaryReleaseID, let fresh = state.downloads[primary] {
            return fresh
        }
        return card.download
    }

    private func play() {
        // A show's download is a season pack (playing it by id starts the largest file),
        // so a show plays an episode.
        if card.isSeries {
            if let playID = card.resumePlayID {
                playing = PlayRequest(playID: playID, title: card.title)
            } else {
                selection = card
            }
            return
        }
        guard let id = live?.id ?? card.playableDownloadID else { return }
        playing = PlayRequest(downloadID: id, title: card.title)
    }

    private func startDownload() {
        guard let torrent = card.primaryReleaseID else { return }
        queuing = true
        Task {
            do {
                try await state.download(torrent: torrent)
            } catch {
                Toasts.shared.error(error.localizedDescription)
            }
            queuing = false
        }
    }
}
