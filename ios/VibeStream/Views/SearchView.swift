import SwiftUI

struct SearchView: View {
    @Environment(AppState.self) private var state
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Binding var selection: Card?
    @Binding var playing: PlayRequest?

    @State private var term = ""
    @State private var results: [Card] = []
    @State private var searching = false
    /// The query the results are for, so "nothing matched" is only said once a search finishes.
    @State private var answered: String?
    @State private var failed = false
    @FocusState private var typing: Bool
    @State private var voice = VoiceSearch()
    var active = true

    private var wide: Bool { sizeClass == .regular }

    private var shown: [Card] {
        term.trimmingCharacters(in: .whitespaces).isEmpty ? suggestions : results
    }

    /// Deduplicated: a lazy stack given the same id twice draws one as an empty gap.
    private var suggestions: [Card] {
        var seen = Set<Int>()
        return state.rows.filter { $0.id != "continue" }
            .flatMap(\.items)
            .filter { seen.insert($0.mediaID).inserted }
            .prefix(30)
            .map { $0 }
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: wide ? 12 : 8) {
                if let problem = voice.problem {
                    Text(problem)
                        .font(.footnote)
                        .foregroundStyle(Palette.dim)
                        .padding(.horizontal, 16)
                        .padding(.top, 4)
                }

                Text(term.isEmpty ? "Recommended TV Shows & Movies" : "Results")
                    .font(.system(size: wide ? 24 : 18, weight: .bold))
                    .padding(.horizontal, 16)
                    .padding(.top, 6)
                    .padding(.bottom, wide ? 6 : 4)

                ForEach(shown) { card in
                    row(card)
                }

                let query = term.trimmingCharacters(in: .whitespaces)
                if failed && !searching {
                    VStack(spacing: 10) {
                        Text("Couldn't search right now.")
                            .font(.subheadline).foregroundStyle(Palette.dim)
                        Button("Try Again") { Task { await run(force: true) } }
                            .buttonStyle(.glass).foregroundStyle(.white)
                    }
                    .frame(maxWidth: .infinity).padding(.top, 50)
                } else if !query.isEmpty, answered == query, results.isEmpty, !searching {
                    Text("Nothing matched \u{201C}\(query)\u{201D}")
                        .font(.subheadline).foregroundStyle(Palette.dim)
                        .frame(maxWidth: .infinity).padding(.top, 50)
                }
            }
            .padding(.bottom, 24)
        }
        .scrollIndicators(.hidden)
        .scrollDismissesKeyboard(.immediately)
        .safeAreaInset(edge: .top, spacing: 8) { field }
        .task(id: term) { await run() }
        .onChange(of: active) { _, now in if !now { voice.cancel() } }
        #if DEBUG
        // -search <term>: open with that typed.
        .task {
            let arguments = ProcessInfo.processInfo.arguments
            if let flag = arguments.firstIndex(of: "-search"), flag + 1 < arguments.count {
                term = arguments[flag + 1]
            }
        }
        #endif
    }

    private var field: some View {
        HStack(spacing: 10) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: wide ? 20 : 17))
                    .foregroundStyle(Palette.dim)
                if voice.listening {
                    Text(voice.heard.isEmpty ? "Listening..." : voice.heard)
                        .font(.system(size: wide ? 19 : 16))
                        .foregroundStyle(voice.heard.isEmpty ? Palette.dim : .white)
                        .lineLimit(1)
                        .truncationMode(.head)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .contentTransition(.opacity)
                } else {
                    TextField("", text: $term,
                              prompt: Text("Search shows, movies, genres...").foregroundStyle(Palette.dim))
                        .font(.system(size: wide ? 19 : 16))
                        .foregroundStyle(.white)
                        .tint(.white)
                        .focused($typing)
                        .submitLabel(.search)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                }
                if searching {
                    BootSpinner(size: 18, line: 2.5)
                } else if !term.isEmpty && !voice.listening {
                    Button { term = "" } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(Palette.dim)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Clear")
                }
            }
            .padding(.horizontal, wide ? 20 : 16)
            .frame(height: fieldHeight)
            .background(Color.white.opacity(0.14), in: .capsule)
            .contentShape(.capsule)
            .onTapGesture { if voice.listening { voice.stop() } else { typing = true } }

            microphone
        }
        // Focus on becoming the active tab, a beat later or the field cannot take it yet. Not on appear:
        // every tab is built at launch. On the row, since the field is swapped out during voice search.
        .onChange(of: active, initial: true) { _, now in
            guard now else { typing = false; return }
            Task {
                try? await Task.sleep(for: .milliseconds(150))
                if active { typing = true }
            }
        }
        .padding(.horizontal, 16)
        .padding(.bottom, 6)
        .background(Palette.ground)
        .animation(.snappy(duration: 0.25), value: voice.listening)
    }

    private var fieldHeight: CGFloat { wide ? 56 : 44 }

    private var microphone: some View {
        Button {
            if voice.listening {
                voice.stop()
            } else {
                typing = false
                Task { await voice.start(hints: hints) { heard in Task { await searchSpoken(heard) } } }
            }
        } label: {
            Image(systemName: voice.listening ? "mic.fill" : "mic")
                .font(.system(size: wide ? 22 : 18, weight: .semibold))
                .foregroundStyle(voice.listening ? Color.black : .white)
                .symbolEffect(.pulse, isActive: voice.listening)
                .frame(width: fieldHeight, height: fieldHeight)
                .background(voice.listening ? Color.white : Color.white.opacity(0.14), in: .circle)
                .contentShape(.circle)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(voice.listening ? "Stop listening" : "Search by voice")
    }

    private var hints: [String] {
        var seen = Set<String>()
        return state.rows.flatMap(\.items).map(\.title).filter { seen.insert($0).inserted }
    }

    private func searchSpoken(_ heard: [String]) async {
        searching = true
        let meant = (try? await APIClient.shared.spoken(heard)) ?? heard.first ?? ""
        searching = false
        term = meant
    }

    private func row(_ card: Card) -> some View {
        let artWidth: CGFloat = wide ? 270 : 146
        return HStack(spacing: wide ? 20 : 12) {
            RemoteImage(url: (card.backdrop ?? card.poster).flatMap(URL.init(string:)))
                .frame(width: artWidth, height: artWidth * 9 / 16)
                .clipShape(.rect(cornerRadius: 4))

            Text(card.title)
                .font(.system(size: wide ? 21 : 15, weight: .semibold))
                .foregroundStyle(.white)
                .lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)

            if card.playableDownloadID != nil {
                Button { playOrOpen(card) } label: {
                    Image(systemName: "play.circle")
                        .font(.system(size: wide ? 44 : 32, weight: .thin))
                        .foregroundStyle(.white)
                        .frame(width: wide ? 60 : 44, height: wide ? 60 : 44)
                        .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Play \(card.title)")
            }
        }
        .padding(.horizontal, 16)
        .contentShape(.rect)
        .onTapGesture {
            typing = false
            selection = card
        }
    }

    /// A show not started opens its page: given the show's download the server would play the largest file.
    private func playOrOpen(_ card: Card) {
        typing = false
        if card.isSeries && card.resumeDownloadID == nil {
            selection = card
        } else if let id = card.playableDownloadID {
            playing = PlayRequest(downloadID: id, title: card.isSeries ? card.resumeTitle : card.title)
        }
    }

    private func run(force: Bool = false) async {
        let query = term.trimmingCharacters(in: .whitespaces)
        failed = false
        guard query.count >= 2 else {
            results = []
            answered = nil
            return
        }
        // Debounce: typing "documentary" should be one request, not eleven.
        if !force { try? await Task.sleep(for: .milliseconds(280)) }
        guard !Task.isCancelled else { return }
        searching = true
        defer { searching = false }
        do {
            results = try await APIClient.shared.search(query)
            answered = query
        } catch {
            if !Task.isCancelled { failed = true }
        }
    }
}

struct MyLibraryView: View {
    @Environment(AppState.self) private var state
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Binding var selection: Card?
    @Binding var playing: PlayRequest?

    private var wide: Bool { sizeClass == .regular }
    private var posterWidth: CGFloat { wide ? Metrics.posterWidthPad : Metrics.posterWidth }

    private var continueRow: [Card] {
        state.rows.first { $0.id == "continue" }?.items ?? []
    }

    private var library: [Card] {
        state.rows.first { $0.id == "library" }?.items ?? []
    }

    @State private var showingMyList = false
    @State private var playingClip: Clip?
    @State private var framingClip: Clip?

    private var myList: [Card] {
        state.rows.first { $0.id == "mylist" }?.items ?? []
    }

    private var watchAgain: [Card] {
        state.library?.rows.first { $0.id == "watchagain" }?.items ?? []
    }

    private var arriving: [DownloadState] {
        state.downloads.values
            .filter { $0.isWorking || $0.isPreparing }
            .sorted { $0.id < $1.id }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if !continueRow.isEmpty {
                    CardRow(title: "Resume Watching", items: continueRow) { card in
                        ContinueCard(card: card, width: posterWidth * 1.2)
                        .onTapGesture { resume(card) }
                    }
                }

                if !myList.isEmpty {
                    VStack(alignment: .leading, spacing: 0) {
                        Color.clear.frame(height: 0)
                            .navigationDestination(isPresented: $showingMyList) {
                                MyListView(selection: $selection, playing: $playing)
                            }
                        CardRow(title: "Watchlist", items: myList) { card in
                            PosterCard(card: card, width: posterWidth).onTapGesture { selection = card }
                        }
                        .overlay(alignment: .topTrailing) {
                            Button { showingMyList = true } label: {
                                HStack(spacing: 4) {
                                    Text("See All")
                                    Image(systemName: "chevron.right")
                                }
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(.white)
                            }
                            .padding(.trailing, 16)
                        }
                    }
                }

                if !watchAgain.isEmpty {
                    CardRow(title: "Watch It Again", items: watchAgain) { card in
                        PosterCard(card: card, width: posterWidth).onTapGesture { selection = card }
                    }
                }

                if !state.clips.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Clips you've saved")
                            .font(.system(size: 17, weight: .bold))
                            .padding(.horizontal, 16)
                        ScrollView(.horizontal) {
                            LazyHStack(alignment: .top, spacing: Metrics.rowSpacing) {
                                ForEach(state.clips) { clip in
                                    ClipCard(clip: clip, width: posterWidth * 1.6)
                                        .onTapGesture { playingClip = clip }
                                        .contextMenu {
                                            Button("Make Vertical", systemImage: "rectangle.portrait") {
                                                framingClip = clip
                                            }
                                            Button("Delete Clip", systemImage: "trash", role: .destructive) {
                                                Task { await state.deleteClip(clip) }
                                            }
                                        }
                                }
                            }
                            .padding(.horizontal, 16)
                        }
                        .scrollIndicators(.hidden)
                        .fixedSize(horizontal: false, vertical: true)
                    }
                }

                if !library.isEmpty {
                    CardRow(title: "Ready to Play", items: library) { card in
                        PosterCard(card: card, width: posterWidth).onTapGesture { selection = card }
                    }
                }

                downloadsSection

                if continueRow.isEmpty && myList.isEmpty && watchAgain.isEmpty && library.isEmpty
                    && arriving.isEmpty && state.clips.isEmpty {
                    if state.loading && state.feed == nil {
                        BootSpinner()
                            .frame(maxWidth: .infinity).padding(.top, 80)
                    } else {
                        VStack(spacing: 10) {
                            Image(systemName: "rectangle.stack")
                                .font(.largeTitle).foregroundStyle(Palette.faint)
                            Text("Nothing here yet")
                                .font(.headline)
                            Text("Titles you download, and anything you start watching, show up here.")
                                .font(.subheadline).foregroundStyle(Palette.dim)
                                .multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.top, 80)
                        .padding(.horizontal, 32)
                    }
                }
            }
            .padding(.bottom, 24)
        }
        .fullScreenCover(item: $playingClip) { clip in
            ClipPlayer(clip: clip) { selection = $0 }
        }
        .fullScreenCover(item: $framingClip) { clip in
            VerticalEditor(clip: clip)
        }
        .task {
            await state.loadClips()
            #if DEBUG
            // -vertical <clip id>: open that clip's vertical editor.
            let arguments = ProcessInfo.processInfo.arguments
            if let flag = arguments.firstIndex(of: "-vertical"), flag + 1 < arguments.count,
               let id = Int(arguments[flag + 1]) {
                framingClip = state.clips.first { $0.id == id }
            }
            // -clipPlay: open the first saved clip.
            if ProcessInfo.processInfo.arguments.contains("-clipPlay") {
                playingClip = state.clips.first
            }
            #endif
        }
        .softTopEdge()
        .scrollIndicators(.hidden)
        .refreshable { await state.loadFeed() }
        #if DEBUG
        // -myList: open the whole list.
        .task(id: myList.isEmpty) {
            if !myList.isEmpty, ProcessInfo.processInfo.arguments.contains("-myList") {
                showingMyList = true
            }
        }
        #endif
    }

    private func resume(_ card: Card) {
        if let playID = card.resumePlayID {
            playing = PlayRequest(playID: playID, title: card.title)
        } else {
            selection = card
        }
    }

    private func title(for download: DownloadState) -> String {
        for card in state.rows.flatMap(\.items) {
            if card.primaryReleaseID == download.torrentID
                || (card.releases ?? []).contains(where: { $0.id == download.torrentID }) {
                return card.title
            }
        }
        return "Download"
    }

    @ViewBuilder private var downloadsSection: some View {
        if !arriving.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Text("On its way to the server")
                    .font(.system(size: 17, weight: .bold))
                    .padding(.horizontal, 16)

                ForEach(arriving) { item in
                    HStack(spacing: 12) {
                        DownloadRing(
                            percent: item.isWorking && item.percent >= 1 ? item.percent : nil,
                            size: 34
                        )
                        VStack(alignment: .leading, spacing: 2) {
                            Text(title(for: item)).font(.subheadline.weight(.semibold)).lineLimit(1)
                            Text(item.isPreparing
                                 ? "Preparing"
                                 : item.percent >= 1 ? "Downloading \(Int(item.percent))%" : "Waiting")
                                .font(.caption).foregroundStyle(Palette.faint)
                        }
                        Spacer()
                    }
                    .padding(.horizontal, 16)
                }
            }
        }
    }
}
