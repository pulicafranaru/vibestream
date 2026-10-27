import SwiftUI

struct DetailView: View {
    @Environment(AppState.self) private var state
    @Environment(\.dismiss) private var dismiss
    /// Set when this is the iPad's card, which `dismiss` cannot close.
    @Environment(\.closeTitle) private var closeTitle
    @Environment(\.openTitle) private var openTitle
    @State private var similar: [Card]?
    @Environment(\.horizontalSizeClass) private var sizeClass

    private var wide: Bool { sizeClass == .regular }

    let card: Card

    @State private var full: Card?
    @State private var unreachable = false
    @State private var tab: Tab
    // Inline playback in the artwork slot; sideways or Full Screen moves the same session to `fullScreen`.
    @State private var playing: PlayRequest?
    @State private var session: PlayerModel?
    @State private var fullScreen: FullScreenPlay?
    /// The whole screen gave the playback back rather than ending it.
    @State private var handedBack = false
    @State private var castPicking = false
    /// The episode the player ended on, which after autoplay is not the one pressed.
    @State private var lastPlayed: PlayRequest?
    @State private var seasonNumber: Int?
    @State private var episodesRevision = 0
    @State private var seasonStatus: SeasonStatus?
    @State private var queuingSeason = false
    @State private var confirmingSeasonDelete = false
    @State private var deletingSeason = false
    @State private var queuing = false
    /// Cancelled before the server said what to cancel.
    @State private var pendingCancel = false
    @State private var confirmingCancel = false
    @State private var collection: CollectionTarget?
    @State private var closeTint: Color = .white
    @State private var scrollPosition = ScrollPosition()

    private enum Tab: String, CaseIterable, Identifiable {
        case episodes = "Episodes", more = "Similar", versions = "Versions", about = "About"
        var id: String { rawValue }
    }

    private var tabs: [Tab] {
        shown.isSeries ? [.episodes, .more, .about, .versions] : [.more, .about, .versions]
    }

    init(card: Card, autoplay: PlayRequest? = nil) {
        self.card = card
        _playing = State(initialValue: autoplay)
        _lastPlayed = State(initialValue: autoplay)
        _tab = State(initialValue: card.isSeries ? .episodes : .more)
        #if DEBUG
        // -detailTab <about|versions|more>: open on that tab, for a script.
        let arguments = ProcessInfo.processInfo.arguments
        if let flag = arguments.firstIndex(of: "-detailTab"), flag + 1 < arguments.count,
           let wanted = Tab.allCases.first(where: {
               $0.rawValue.lowercased().hasPrefix(arguments[flag + 1].lowercased())
           }) {
            _tab = State(initialValue: wanted)
        }
        #endif
    }

    /// The refreshed copy once it arrives, so the sheet paints immediately.
    private var shown: Card { full ?? card }

    // Checks every release, not just the primary: the copy on disk may be a different encode.
    // The card's snapshot is used only before the first poll answers.
    private var live: DownloadState? {
        var ids = (shown.releases ?? []).map(\.id)
        if let primary = shown.primaryReleaseID { ids.append(primary) }
        let known = ids.compactMap { state.downloads[$0] }.filter { $0.state != "removed" }

        if let playable = known.first(where: \.isPlayable) { return playable }
        if let busy = known.first(where: { $0.isWorking || $0.isPreparing }) { return busy }
        if let any = known.first { return any }
        return state.downloads.isEmpty ? shown.download : nil
    }

    var body: some View {
        VStack(spacing: 0) {
            if let playing { inlinePlayer(playing) } else { artwork }
            page
        }
        .background(Palette.ground)
        .fullScreenCover(item: $fullScreen, onDismiss: {
            if handedBack {
                handedBack = false
            } else {
                stopPlaying()
            }
        }) { play in
            PlayerHost(request: play.request, handed: session, sideways: play.sideways,
                       onUpright: { model, request in
                           handedBack = true
                           session = model
                           lastPlayed = request
                           playing = request
                           var quietly = Transaction()
                           quietly.disablesAnimations = true
                           withTransaction(quietly) { fullScreen = nil }
                       }) { lastPlayed = $0 }
                .environment(state)
                .environment(\.openTitle, openTitle)
                // Clear, so the player fades out over this page. See PlayerView.close.
                .presentationBackground(.clear)
        }
        .overlay(alignment: .topTrailing) { if playing == nil { closeButton } }
    }

    private func inlinePlayer(_ request: PlayRequest) -> some View {
        PlayerView(request: request, handed: session, inline: true,
                   active: fullScreen == nil,
                   onFullScreen: { model, sideways in
                       guard fullScreen == nil, !handedBack else { return }
                       session = model
                       // No animation: the window rotates as it appears, and both together jolt.
                       var quietly = Transaction()
                       quietly.disablesAnimations = true
                       withTransaction(quietly) {
                           fullScreen = FullScreenPlay(request: playing ?? request, sideways: sideways)
                       }
                   },
                   onStop: { stopPlaying() },
                   onClosePage: { closeTitle?() ?? dismiss() }) { next in
            session = nil
            lastPlayed = next
            playing = next
            if let season = next.season { seasonNumber = season }
        }
        .id(request.playID)
        .environment(\.openTitle, openTitle)
        .aspectRatio(16 / 9, contentMode: .fit)
        .frame(maxWidth: .infinity)
        .background(.black)
        .transition(.opacity)
    }

    private func stopPlaying() {
        withAnimation(.easeOut(duration: 0.2)) { playing = nil }
        session = nil
        afterPlayback()
    }

    private var page: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0, pinnedViews: [.sectionHeaders]) {
                VStack(alignment: .leading, spacing: 14) {
                    Text(shown.title).font(.system(size: wide ? 30 : 24, weight: .bold))
                    metaRow
                    actionRow
                }
                .padding(.horizontal, wide ? 28 : 16)
                .padding(.top, 4)
                .padding(.bottom, 14)

                Section {
                    content
                        .padding(.horizontal, wide ? 28 : 16)
                        .padding(.top, 20)
                } header: {
                    tabStrip
                        .padding(.horizontal, wide ? 28 : 16)
                        .padding(.top, 14)
                        .padding(.bottom, 4)
                        .background(Palette.ground)
                        .overlay(alignment: .bottom) {
                            LinearGradient(colors: [Palette.ground, Palette.ground.opacity(0)],
                                           startPoint: .top, endPoint: .bottom)
                                .frame(height: 22)
                                .offset(y: 22)
                                .allowsHitTesting(false)
                        }
                }
            }
            .padding(.bottom, 30)
        }
        .scrollIndicators(.hidden)
        .scrollPosition($scrollPosition)
        .task {
            chooseSeason()
            // The card may be minutes old and the next poll seconds away.
            await state.refreshDownloads()
            full = await loadFull()
            if shown.isSeries { tab = .episodes }
            chooseSeason()
            #if DEBUG
            // -pageScroll <points>: open scrolled that far.
            let scrollArgs = ProcessInfo.processInfo.arguments
            if let flag = scrollArgs.firstIndex(of: "-pageScroll"), flag + 1 < scrollArgs.count,
               let y = Double(scrollArgs[flag + 1]) {
                try? await Task.sleep(for: .seconds(4))
                withAnimation { scrollPosition.scrollTo(y: y) }
            }
            // -sheetPlay: press the show's Play button.
            if ProcessInfo.processInfo.arguments.contains("-sheetPlay"), let next = shown.nextUp {
                try? await Task.sleep(for: .seconds(2))
                playNextUp(next)
            }
            #endif
        }
        .onChange(of: seasonNumber) { _, number in
            if let number { state.lastSeason[card.mediaID] = number }
        }
        // The About tab's names and genres are links to these, caught here.
        .environment(\.openURL, OpenURLAction { url in
            guard let target = CollectionTarget(url: url) else { return .discarded }
            collection = target
            return .handled
        })
        .sheet(item: $collection) { target in
            CollectionView(target: target) { other in
                collection = nil
                openTitle?(other)
            } onClose: {
                collection = nil
            }
            .environment(state)
            .presentationBackground(Palette.ground)
        }
        .alert("Cancel download?", isPresented: $confirmingCancel) {
            Button("Keep downloading", role: .cancel) {}
            Button("Cancel download", role: .destructive) { cancelPressed() }
        } message: {
            Text("\(shown.title) will stop, and anything already downloaded "
                 + "will be deleted from the server.")
        }
    }

    private var artwork: some View {
        // The whole 16:9 frame: a fixed-height slot cropped the backdrop on an iPad's wider sheet.
        Color.clear
            .aspectRatio(16 / 9, contentMode: .fit)
            .frame(maxWidth: .infinity)
            .overlay(alignment: .top) {
                RemoteImage(
                    url: (shown.backdrop ?? shown.poster).flatMap(URL.init(string:)),
                    onImage: { closeTint = ArtworkTint.onTopTrailing(of: $0) }
                )
            }
            .clipped()
            .overlay(alignment: .bottom) {
                LinearGradient(colors: [.clear, Palette.ground],
                               startPoint: .center, endPoint: .bottom)
                    .frame(height: 90)
            }
            .overlay { heroButton }
    }

    // No plate behind the glyph: its colour comes from the corner it covers, with an opposite halo.
    private var closeButton: some View {
        let tint: Color = closeTint
        return Button { closeTitle?() ?? dismiss() } label: {
            Image(systemName: "xmark")
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(tint)
                .shadow(color: (tint == .black ? Color.white : .black).opacity(0.45),
                        radius: 3)
                .frame(width: 44, height: 44)
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .padding(.trailing, 4)
        .padding(.top, 2)
        .animation(.easeOut(duration: 0.2), value: tint)
    }

    // One line, never wrapped: badges drop before anything wraps.
    private var metaRow: some View {
        ViewThatFits(in: .horizontal) {
            metaLine(badges: true)
            metaLine(badges: false)
        }
        .font(.footnote)
        .foregroundStyle(Palette.dim)
    }

    private func metaLine(badges: Bool) -> some View {
        HStack(spacing: 8) {
            if let score = shown.voteAverage, score > 0 {
                Text(String(format: "%.1f", score))
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Palette.good)
            }
            if let year = shown.year { Text(String(year)) }
            if shown.isSeries, let count = shown.seasons?.filter({ $0.number > 0 }).count, count > 0 {
                Text(count == 1 ? "1 Season" : "\(count) Seasons")
            } else if !shown.isSeries, let runtime = shown.runtime, runtime > 0 {
                Text(runtime >= 60
                     ? (runtime % 60 == 0 ? "\(runtime / 60)h" : "\(runtime / 60)h \(runtime % 60)m")
                     : "\(runtime)m")
            }
            if let rating = shown.facts?.certification, !rating.isEmpty {
                Text(rating)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 5).padding(.vertical, 2)
                    .overlay(RoundedRectangle(cornerRadius: 3).strokeBorder(.white.opacity(0.6), lineWidth: 1))
            }
            if badges {
                ForEach(pictureBadges, id: \.self) { badge in
                    Text(badge)
                        .font(.caption2.weight(.semibold))
                        .padding(.horizontal, 5).padding(.vertical, 2)
                        .overlay(RoundedRectangle(cornerRadius: 3).stroke(Palette.faint, lineWidth: 1))
                }
            }
        }
        .lineLimit(1)
        .fixedSize()
    }

    private var pictureBadges: [String] {
        var out: [String] = []
        if shown.quality?.resolution == "2160p" { out.append("4K") }
        if let hdr = shown.quality?.hdr { out.append(hdr) }
        return out
    }

    private struct Hero {
        enum Kind { case play, download, retry, busy(Double?) }
        let kind: Kind
        var caption: String? = nil
        let label: String
        let press: () -> Void
    }

    private var hero: Hero? {
        if shown.isSeries, let next = shown.nextUp {
            return Hero(kind: .play, caption: next.label,
                        label: next.isResume ? "Resume \(next.label)" : "Play \(next.label)") {
                playNextUp(next)
            }
        }
        if shown.isSeries && isHere { return nil }
        switch action {
        case .play: return Hero(kind: .play, label: "Play") { press() }
        case .download: return Hero(kind: .download, label: "Download") { press() }
        case .failed: return Hero(kind: .retry, caption: "Try again", label: "Try again") { press() }
        case .queuing, .waiting:
            return Hero(kind: .busy(nil), label: "Waiting for download") { press() }
        case .downloading(let percent):
            return Hero(kind: .busy(percent), label: "Downloading") { press() }
        case .preparing(let percent):
            return Hero(kind: .busy(percent), caption: "Preparing", label: "Preparing") { press() }
        }
    }

    @ViewBuilder private var heroButton: some View {
        if let hero {
            Button(action: hero.press) {
                VStack(spacing: 10) {
                    disc(hero.kind)
                    if let caption = hero.caption {
                        Text(caption)
                            .font(.footnote.weight(.semibold))
                            .padding(.horizontal, 10).padding(.vertical, 4)
                            .background(.black.opacity(0.55), in: .capsule)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.white)
            .accessibilityLabel(hero.label)
        }
    }

    private func disc(_ kind: Hero.Kind) -> some View {
        let size: CGFloat = wide ? 88 : 72
        return ZStack {
            Circle().fill(.black.opacity(0.45))
            switch kind {
            case .busy(let percent):
                DownloadRing(percent: percent, size: size, showsLabel: false)
                if let percent {
                    Text("\(Int(percent))%")
                        .font(.system(size: size * 0.22, weight: .bold))
                        .monospacedDigit()
                        .contentTransition(.numericText())
                }
            default:
                Circle().strokeBorder(.white.opacity(0.9), lineWidth: 2)
                Group {
                    switch kind {
                    // Nudged towards its point, so it looks centred in the
                    // circle rather than measures it.
                    case .play: Image(systemName: "play.fill").offset(x: size * 0.04)
                    case .retry: Image(systemName: "arrow.clockwise")
                    default: Image(systemName: "arrow.down.to.line")
                    }
                }
                .font(.system(size: size * 0.38, weight: .semibold))
            }
        }
        .frame(width: size, height: size)
        .shadow(color: .black.opacity(0.4), radius: 12, y: 6)
        .overlay(alignment: .topTrailing) {
            if case .retry = kind { ErrorBadge(size: 22).offset(x: 2, y: -2) }
        }
    }

    private var castRequest: PlayRequest? {
        if shown.isSeries {
            return shown.nextUp.map {
                PlayRequest(playID: $0.playID, title: shown.title, season: $0.season, episode: $0.number)
            }
        }
        if case .play = action, let id = live?.id ?? shown.playableDownloadID {
            return PlayRequest(downloadID: id, title: shown.title)
        }
        return nil
    }

    private var castButton: some View {
        Button { castPicking = true } label: {
            VStack(spacing: 6) {
                Image("CastGlyph")
                    .renderingMode(.template)
                    .resizable()
                    .scaledToFit()
                    .frame(width: 24, height: 24)
                    .frame(height: 26)
                Text("Play on").font(.caption2)
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
        .foregroundStyle(.white)
        .accessibilityLabel("Play on another device")
        .sheet(isPresented: $castPicking) {
            CastPicker { device in
                guard let request = castRequest else { return }
                Task {
                    if await Cast.shared.play(request, at: nil, on: device, profile: state.profile?.id) {
                        closeTitle?() ?? dismiss()
                    }
                }
            }
            .presentationDetents([.medium])
        }
    }

    private func playNextUp(_ next: Card.NextUp) {
        play(PlayRequest(playID: next.playID, title: shown.title,
                         season: next.season, episode: next.number))
    }

    private func play(_ request: PlayRequest) {
        guard request.playID != playing?.playID else { return }
        lastPlayed = request
        session = nil
        withAnimation(.easeOut(duration: 0.2)) { playing = request }
        if let season = request.season { seasonNumber = season }
    }

    // Retried until it arrives, so a server restart does not leave the page without Play.
    private func loadFull() async -> Card? {
        var delay = 1.0
        while !Task.isCancelled {
            if let fresh = try? await APIClient.shared.media(card.mediaID) {
                unreachable = false
                return fresh
            }
            unreachable = true
            try? await Task.sleep(for: .seconds(delay))
            delay = min(delay * 2, 8)
        }
        return nil
    }

    private func afterPlayback() {
        if let season = lastPlayed?.season { seasonNumber = season }
        episodesRevision += 1
        Task {
            if let fresh = try? await APIClient.shared.media(card.mediaID) { full = fresh }
            await state.loadFeed()
        }
    }

    /// The season to open on: the one last looked at, then the one the Play
    /// button is in, then the first one with files, then the first.
    private func chooseSeason() {
        guard seasonNumber == nil, let seasons = shown.seasons, !seasons.isEmpty else { return }
        #if DEBUG
        // -season <n>: open on that season.
        let arguments = ProcessInfo.processInfo.arguments
        if let flag = arguments.firstIndex(of: "-season"), arguments.index(after: flag) < arguments.endIndex,
           let number = Int(arguments[arguments.index(after: flag)]) {
            seasonNumber = number
            return
        }
        #endif
        if let remembered = state.lastSeason[card.mediaID],
           seasons.contains(where: { $0.number == remembered }) {
            seasonNumber = remembered
        } else if let next = shown.nextUp?.season, seasons.contains(where: { $0.number == next }) {
            seasonNumber = next
        } else {
            seasonNumber = seasons.first(where: \.hasFiles)?.number ?? seasons.first?.number
        }
    }

    private var action: TitleAction {
        TitleAction.of(live, resume: resumeLabel, optimistic: queuing)
    }

    private var isHere: Bool { live?.isPlayable == true }

    private func press() {
        if action.busy {
            confirmingCancel = true
            return
        }
        // The id comes from the live row, not from the card: the card can say
        // "playable" about a copy that has since been deleted.
        if case .play = action, let id = live?.id ?? shown.playableDownloadID {
            // A show's download is a season pack: playing it by id would pick the largest file.
            if shown.isSeries {
                if let next = shown.nextUp { playNextUp(next) } else { tab = .episodes }
                return
            }
            play(PlayRequest(downloadID: id, title: shown.title))
            return
        }
        // Retry the failed release, not the primary, or a second download of another version starts.
        if case .failed = action, let failed = live?.torrentID {
            startDownload(failed)
            return
        }
        startDownload(shown.primaryReleaseID)
    }

    private var resumeLabel: String {
        if let seconds = shown.resumeSeconds, seconds > 30 {
            return "Resume from \(timecode(seconds))"
        }
        return "Play"
    }

    private var actionRow: some View {
        HStack(alignment: .top, spacing: 0) {
            myListButton
            rateButton(-1, "hand.thumbsdown", "Not for me")
            rateButton(1, "hand.thumbsup", "Like it!")
            if castRequest != nil { castButton }
            if shown.isSeries {
                switch seasonStatus {
                case .offer(let pack): seasonButton(pack)
                case .downloaded(let held): seasonDownloadedButton(held)
                case nil: EmptyView()
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func seasonButton(_ pack: SeasonDetail.SeasonPack) -> some View {
        let live = state.downloads[pack.id]
        let arriving = pack.completeRequest == true && (live.map { TitleAction.of($0).busy } ?? true)
        let season = seasonNumber.map { "Season \($0)" } ?? "Season"
        let percent: Double? = {
            guard let live, case .downloading(let value) = TitleAction.of(live) else { return nil }
            return value
        }()
        return Button {
            startSeason(pack)
        } label: {
            VStack(spacing: 6) {
                Group {
                    if arriving || queuingSeason {
                        DownloadRing(percent: queuingSeason ? nil : percent, size: 24, showsLabel: false)
                    } else {
                        Image("SeasonGlyph")
                            .resizable()
                            .scaledToFit()
                            .frame(width: 26, height: 26)
                    }
                }
                .frame(height: 26)
                Text("\(arriving ? "Downloading" : "Download")\n\(season)")
                    .font(.caption2)
                    .multilineTextAlignment(.center)
                    .fixedSize()
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
        .foregroundStyle(.white)
        .disabled(arriving || queuingSeason)
        .accessibilityLabel(arriving ? "Downloading \(season)" : "Download \(season)")
        .accessibilityValue(pack.sizeGB.map { String(format: "%.1f gigabytes", $0) } ?? "")
    }

    private func seasonDownloadedButton(_ held: [HeldEpisode]) -> some View {
        let season = seasonNumber.map { "Season \($0)" } ?? "Season"
        return Button {
            confirmingSeasonDelete = true
        } label: {
            VStack(spacing: 6) {
                Group {
                    if deletingSeason {
                        DownloadRing(percent: nil, size: 24, showsLabel: false)
                    } else {
                        Image(systemName: "checkmark.circle")
                            .font(.system(size: 24))
                    }
                }
                .frame(height: 26)
                Text(deletingSeason ? "Deleting\n\(season)" : "\(season)\nDownloaded")
                    .font(.caption2)
                    .multilineTextAlignment(.center)
                    .fixedSize()
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
        .foregroundStyle(.white)
        .disabled(deletingSeason)
        .accessibilityLabel("\(season) downloaded")
        .accessibilityHint("Offers to delete the season")
        .confirmationDialog("Delete \(season)?", isPresented: $confirmingSeasonDelete,
                            titleVisibility: .visible) {
            Button("Delete \(season)", role: .destructive) { deleteSeason(held) }
        } message: {
            Text("This removes all \(held.count) episodes of \(season.lowercased()) from the server and from your library.")
        }
    }

    /// One episode at a time: a pack can hold more than this season.
    private func deleteSeason(_ held: [HeldEpisode]) {
        deletingSeason = true
        Task {
            do {
                for item in held {
                    try await APIClient.shared.deleteEpisode(item.episode, of: item.download)
                }
            } catch {
                Toasts.shared.error("Couldn't delete the whole season. Try again.")
            }
            await state.refreshDownloads()
            episodesRevision += 1
            deletingSeason = false
        }
    }

    private func startSeason(_ pack: SeasonDetail.SeasonPack) {
        queuingSeason = true
        Task {
            do {
                // A pack already being fetched an episode at a time is asked
                // for whole; one not started yet is simply started.
                try await state.download(torrent: pack.id, everything: pack.download != nil)
                episodesRevision += 1
            } catch {
                Toasts.shared.error(error.localizedDescription)
            }
            queuingSeason = false
        }
    }

    private var myListButton: some View {
        let saved = state.myList.contains(shown.mediaID)
        return Button {
            Task { await state.toggleMyList(shown) }
        } label: {
            VStack(spacing: 6) {
                Image(systemName: saved ? "checkmark" : "plus")
                    .font(.system(size: 22))
                    .frame(height: 26)
                Text("Watchlist").font(.caption2)
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
        .foregroundStyle(.white)
        .contentTransition(.symbolEffect(.replace))
        .accessibilityLabel(saved ? "Remove from Watchlist" : "Add to Watchlist")
    }

    private func rateButton(_ value: Int, _ symbol: String, _ label: String) -> some View {
        let active = state.ratings[shown.mediaID] == value
        return Button {
            Task { await state.rate(shown.mediaID, value) }
        } label: {
            VStack(spacing: 6) {
                Image(systemName: active ? "\(symbol).fill" : symbol)
                    .font(.system(size: 22))
                    .frame(height: 26)
                Text(label).font(.caption2)
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
        .foregroundStyle(active ? Palette.accent : .white)
        .contentTransition(.symbolEffect(.replace))
    }

    @ViewBuilder private var moreLikeThis: some View {
        let columns = Array(repeating: GridItem(.flexible(), spacing: 12),
                            count: wide ? 4 : 3)
        Group {
            if let similar, similar.isEmpty {
                Text("Nothing like this in the catalog yet")
                    .font(.footnote).foregroundStyle(Palette.faint)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if let similar {
                LazyVGrid(columns: columns, spacing: 12) {
                    ForEach(similar) { other in
                        PosterCard(card: other, width: nil)
                            .onTapGesture { openTitle?(other) }
                            .accessibilityAddTraits(.isButton)
                            .accessibilityLabel(other.title)
                    }
                }
            } else {
                BootSpinner(size: 32, line: 3).frame(maxWidth: .infinity).padding(.vertical, 30)
            }
        }
        .task(id: card.mediaID) {
            guard similar == nil else { return }
            similar = (try? await APIClient.shared.similar(card.mediaID)) ?? []
        }
    }

    private var tabStrip: some View {
        HStack(spacing: 20) {
            ForEach(tabs) { option in
                Button { withAnimation(.snappy) { tab = option } } label: {
                    VStack(spacing: 6) {
                        Text(option.rawValue)
                            .font(.subheadline.weight(tab == option ? .bold : .regular))
                            .foregroundStyle(tab == option ? .white : Palette.faint)
                        Rectangle()
                            .fill(tab == option ? Palette.accent : .clear)
                            .frame(height: 3)
                    }
                }
                .buttonStyle(.plain)
                .fixedSize()
            }
            Spacer()
        }
    }

    @ViewBuilder private var content: some View {
        switch tab {
        case .episodes:
            if full == nil {
                HStack(spacing: 10) {
                    BootSpinner(size: 18, line: 2.5)
                    if unreachable {
                        Text("Can't reach the server. Trying again.")
                            .font(.footnote).foregroundStyle(Palette.faint)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 8)
            } else {
                EpisodeList(card: shown, seasonNumber: $seasonNumber,
                            seasonStatus: $seasonStatus,
                            revision: episodesRevision,
                            playingID: playing?.playID) { play($0) }
                    .environment(state)
            }
        case .more:
            moreLikeThis
        case .versions:
            VStack(spacing: 8) {
                ForEach(shown.releases ?? []) { release in
                    versionRow(release)
                }
                if (shown.releases ?? []).isEmpty {
                    Text("No releases known for this title yet")
                        .font(.footnote).foregroundStyle(Palette.faint)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        case .about:
            TitleAbout(card: shown, overview: true)
        }
    }

    private func versionRow(_ release: Release) -> some View {
        let downloadState = state.downloads[release.id] ?? release.download
        let best = release.id == shown.primaryReleaseID

        return Button {
            if let d = downloadState, d.isPlayable {
                if shown.isSeries {
                    if let next = shown.nextUp { playNextUp(next) } else { tab = .episodes }
                } else {
                    play(PlayRequest(downloadID: d.id, title: shown.title))
                }
            } else if downloadState?.isWorking == true || downloadState?.isPreparing == true {
            } else {
                startDownload(release.id)
            }
        } label: {
            VStack(alignment: .leading, spacing: 6) {
                Text(release.name)
                    .font(.caption)
                    .lineLimit(2)
                    .foregroundStyle(.white)

                HStack(spacing: 5) {
                    if best {
                        tag("BEST", tint: Palette.accent)
                    }
                    if let origin = release.originLabel { originTag(origin) }
                    if release.debrid == true { originTag("Debrid") }
                    ForEach(release.tags, id: \.self) { tag($0) }
                    if let seeders = release.seeders { tag("\(seeders) seeders") }
                    if let downloadState, downloadState.state != "removed" {
                        tag(releaseStatus(downloadState),
                            tint: downloadState.isPlayable
                                ? Palette.good.opacity(0.5) : Color(white: 0.3))
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
            .glassCard(10)
        }
        .buttonStyle(.plain)
    }

    /// Same source as the big button, so a row and the button cannot disagree.
    private func releaseStatus(_ download: DownloadState) -> String {
        switch TitleAction.of(download) {
        case .play: return "Downloaded"
        case .preparing(let percent):
            return percent == nil ? "Preparing" : "Preparing \(Int(percent!))%"
        case .downloading(let percent):
            return percent == nil ? "Downloading" : "Downloading \(Int(percent!))%"
        case .waiting, .queuing: return "Waiting"
        case .failed: return "Failed"
        case .download: return download.state
        }
    }

    private func tag(_ text: String, tint: Color = Color(white: 0.22)) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .medium))
            .padding(.horizontal, 5).padding(.vertical, 2)
            .background(tint, in: .rect(cornerRadius: 3))
    }

    private func originTag(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .medium))
            .padding(.horizontal, 5).padding(.vertical, 2)
            .overlay(RoundedRectangle(cornerRadius: 3).strokeBorder(.white.opacity(0.3), lineWidth: 1))
    }

    // `queuing` lasts only as long as the request; the reply's row goes straight into the shared map.
    private func startDownload(_ torrent: Int?) {
        guard let torrent, !queuing else { return }
        queuing = true
        Task {
            do {
                let started = try await state.download(torrent: torrent)
                // Cancelled while the request was still in flight: there was
                // no id to cancel then, and there is one now.
                if pendingCancel { await cancel(started) }
            } catch {
                Toasts.shared.error(error.localizedDescription)
            }
            pendingCancel = false
            queuing = false
        }
    }

    private func cancelPressed() {
        guard let live else {
            // Still queuing: no row exists yet, so remember the decision and
            // act on it the moment the start request answers.
            pendingCancel = true
            return
        }
        Task { await cancel(live) }
    }

    private func cancel(_ download: DownloadState) async {
        do {
            try await state.cancel(download: download.id, torrent: download.torrentID)
        } catch {
            Toasts.shared.error("Couldn't stop the download. Try again.")
        }
    }
}


struct FullScreenPlay: Identifiable {
    let request: PlayRequest
    let sideways: Bool
    var id: String { request.playID }
}
