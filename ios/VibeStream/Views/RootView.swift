import SwiftUI

struct RootView: View {
    @Environment(AppState.self) private var state
    /// The window's real width class, handed back to the screens after the tab bar is told otherwise.
    @Environment(\.horizontalSizeClass) private var sizeClass

    @Environment(\.accessibilityReduceMotion) private var stillMotion
    @Environment(\.scenePhase) private var scenePhase
    @State private var tab = "movie"
    @State private var typing = false
    @State private var selection: Card?
    @State private var playing: PlayRequest?
    @State private var autoplay: PlayRequest?
    @State private var playingAlone: PlayRequest?
    @State private var switchingProfile = false
    @State private var showingDownloads = false
    @State private var downloadsDetent: PresentationDetent = .medium
    @State private var cast = Cast.shared
    @State private var introPlayed = false

    var body: some View {
        Group {
            if state.startingUp {
                LaunchView()
            } else if state.profile == nil && state.profiles.isEmpty && state.loadError != nil {
                StartupFailure()
            } else if state.profile == nil {
                ProfilesView(dismissable: false)
            } else {
                tabs
            }
        }
        .overlay {
            if sizeClass == .regular {
                TitleCard(card: selection, autoplay: autoplay) { selection = nil }
                    .environment(\.openTitle) { selection = $0 }
            }
        }
        .overlay {
            if !introPlayed && !state.startingUp && state.profile != nil {
                IntroView { introPlayed = true }
            }
        }
        .tint(.white)
        .background(Palette.ground)
        // Full screen, not a sheet, so the tab bar's glass does not hover over the film.
        // Closing the player refreshes the rows, Continue Watching above all.
        .onChange(of: playing) { _, request in
            guard let request else { return }
            playing = nil
            Task { await openPlaying(request) }
        }
        .fullScreenCover(item: $playingAlone, onDismiss: {
            Task { await state.loadFeed() }
        }) { request in
            PlayerHost(request: request)
                .environment(state)
                .environment(\.openTitle) { selection = $0 }
                // Clear, so the player fades out over the page it was opened
                // from instead of leaving as a black sheet. See PlayerView.close.
                .presentationBackground(.clear)
        }
        // Reload the rows when the app returns to the front, or a film on another device stops.
        .onChange(of: scenePhase) { _, phase in
            if phase == .active && state.profile != nil && !state.loading {
                Task { await state.loadFeed() }
            }
        }
        .onChange(of: Cast.shared.target == nil) { _, ended in
            if ended { Task { await state.loadFeed() } }
        }
        .task(id: state.profile?.id) {
            Cast.shared.start(profile: state.profile?.id)
            Cast.shared.watchElsewhere()
        }
        // After an update, once: what is new for whoever is watching.
        .sheet(item: Binding(get: { state.news }, set: { if $0 == nil { state.newsSeen() } })) { news in
            WhatsNewView(news: news) { state.newsSeen() }
                .presentationDetents([.medium, .large])
                .presentationBackground(Palette.ground)
        }
        .sheet(isPresented: $cast.remoteShown) {
            CastRemote { card in
                // After the remote's sheet has gone: one sheet at a time.
                Task {
                    try? await Task.sleep(for: .milliseconds(450))
                    selection = card
                }
            }
                .environment(state)
                .presentationBackground(Palette.ground)
        }
        .sheet(item: phoneSelection) { card in
            DetailView(card: card, autoplay: autoplay)
                .environment(state)
                .environment(\.openTitle) { selection = $0 }
                .presentationDetents([.large])
                .presentationBackground(Palette.ground)
        }
        .task {
            let presenting = $playing
            PictureInPicture.shared.reopen = { presenting.wrappedValue = $0 }
            let appState = state
            Cast.shared.onPlay = { command in
                guard let playID = command.playID else { return }
                Task { @MainActor in
                    if let wanted = command.profileID, wanted != appState.profile?.id,
                       let profile = appState.profiles.first(where: { $0.id == wanted }) {
                        await appState.pick(profile)
                    }
                    presenting.wrappedValue = PlayRequest(playID: playID, title: command.title ?? "",
                                                          startAt: command.position)
                }
            }
            await state.start()
            #if DEBUG
            // -landscape: turn the window sideways.
            if ProcessInfo.processInfo.arguments.contains("-landscape") {
                Orientation.lock(.landscape, everywhere: true)
            }
            // -tab <home|search|mine>: start on a tab other than Home.
            if let flag = ProcessInfo.processInfo.arguments.firstIndex(of: "-tab"),
               flag + 1 < ProcessInfo.processInfo.arguments.count {
                tab = ProcessInfo.processInfo.arguments[flag + 1]
            }
            // -tabAway: go to Home after eight seconds and back four seconds later.
            if ProcessInfo.processInfo.arguments.contains("-tabAway") {
                let start = tab
                try? await Task.sleep(for: .seconds(8))
                tab = "movie"
                try? await Task.sleep(for: .seconds(4))
                tab = start
            }
            // -castDemo [kind or id]: cast to the first online TV (or that kind or device) from 300 s.
            if let flag = ProcessInfo.processInfo.arguments.firstIndex(of: "-castDemo") {
                let args = ProcessInfo.processInfo.arguments
                let kind = flag + 1 < args.count && !args[flag + 1].hasPrefix("-") ? args[flag + 1] : "tv"
                try? await Task.sleep(for: .seconds(8))
                if let tv = await Cast.shared.devices().first(where: { $0.kind == kind || $0.id == kind }) {
                    _ = await Cast.shared.play(PlayRequest(playID: "e1926", title: "Breaking Bad"),
                                               at: 300, on: tv, profile: state.profile?.id)
                }
            }
            if ProcessInfo.processInfo.arguments.contains("-showDownloads") {
                if ProcessInfo.processInfo.arguments.contains("-inspectJob") { downloadsDetent = .large }
                showingDownloads = true
            }
            // -switchProfile: open the profile sheet.
            if ProcessInfo.processInfo.arguments.contains("-switchProfile") {
                switchingProfile = true
            }
            // -play <playID>: straight into the player, "12" or "e34".
            let arguments = ProcessInfo.processInfo.arguments
            if let flag = arguments.firstIndex(of: "-play"),
               arguments.index(after: flag) < arguments.endIndex {
                // -at <seconds>: from there instead of the profile's place.
                let at = arguments.firstIndex(of: "-at").flatMap {
                    arguments.index(after: $0) < arguments.endIndex
                        ? Double(arguments[arguments.index(after: $0)]) : nil
                }
                playing = PlayRequest(playID: arguments[arguments.index(after: flag)],
                                      title: "Debug", startAt: at)
            }
            #endif
        }
        .onChange(of: state.needsProfilePick) { _, wants in
            if wants && state.profile != nil { switchingProfile = true }
        }
    }

    /// Every tab has its own live toolbar copy; only the shown tab's button may present.
    private func onTab(_ flag: Binding<Bool>, _ value: String) -> Binding<Bool> {
        Binding(get: { flag.wrappedValue && tab == value },
                set: { flag.wrappedValue = $0 })
    }

    // The title's page opens, playing; if no title matches, the whole screen player plays alone.
    private func openPlaying(_ request: PlayRequest) async {
        guard let info = try? await APIClient.shared.playInfo(request.playID),
              let mediaID = info.mediaID,
              let card = try? await APIClient.shared.media(mediaID) else {
            playingAlone = request
            return
        }
        if showingDownloads || selection != nil {
            showingDownloads = false
            selection = nil
            try? await Task.sleep(for: .milliseconds(450))
        }
        autoplay = request
        selection = card
        // Only for this opening: the next time this page opens, it does not play.
        try? await Task.sleep(for: .seconds(1))
        autoplay = nil
    }

    private var phoneSelection: Binding<Card?> {
        Binding(get: { sizeClass == .regular ? nil : selection },
                set: { selection = $0 })
    }

    private static let order = ["movie", "tv", "search", "mine"]

    // Tabs drawn here rather than by a TabView, which swaps pages without animating
    // and stops updating hidden ones. Every page stays alive; only the chosen one shows.
    private var tabs: some View {
        ZStack {
            page("movie") {
                NavigationStack {
                    HomeView(kind: "movie", selection: $selection, playing: $playing)
                        .toolbar { toolbar("Movies", tab: "movie") }
                        .modifier(BarTitle())
                }
            }
            page("tv") {
                NavigationStack {
                    HomeView(kind: "tv", selection: $selection, playing: $playing)
                        .toolbar { toolbar("Shows", tab: "tv") }
                        .modifier(BarTitle())
                }
            }
            page("search") {
                NavigationStack {
                    SearchView(selection: $selection, playing: $playing, active: tab == "search")
                        .toolbar { toolbar("Search", tab: "search") }
                        .modifier(BarTitle())
                }
            }
            page("mine") {
                NavigationStack {
                    MyLibraryView(selection: $selection, playing: $playing)
                        .toolbar { toolbar("Library", tab: "mine") }
                        .modifier(BarTitle())
                }
            }
        }
        // Hidden while the keyboard is up, or it is lifted onto the keyboard.
        .overlay(alignment: .bottom) {
            if !typing {
                VStack(spacing: 10) {
                    CastBar()
                    AppTabBar(tab: $tab, avatar: state.profile?.avatar)
                }
                .animation(.snappy(duration: 0.3), value: cast.target)
                .transition(.opacity)
            }
        }
        .onChange(of: tab) { _, now in
            if now == "mine" { Task { await state.loadClips() } }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { _ in
            withAnimation(.easeOut(duration: 0.15)) { typing = true }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in
            withAnimation(.easeIn(duration: 0.2)) { typing = false }
        }
    }

    private func page<Content: View>(
        _ value: String, @ViewBuilder _ content: () -> Content
    ) -> some View {
        let here = Self.order.firstIndex(of: value) ?? 0
        let shown = Self.order.firstIndex(of: tab) ?? 0
        let chosen = here == shown
        let side: CGFloat = chosen ? 0 : (here < shown ? -1 : 1)
        return content()
            .modifier(OwnTabBar())
            .opacity(chosen ? 1 : 0)
            .offset(x: stillMotion ? 0 : side * 34)
            .allowsHitTesting(chosen)
            .accessibilityHidden(!chosen)
            .zIndex(chosen ? 1 : 0)
            .animation(chosen ? .spring(duration: 0.45, bounce: 0.1) : .easeOut(duration: 0.16),
                       value: tab)
    }

    @ToolbarContentBuilder private func toolbar(_ title: String, tab value: String) -> some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            HStack(spacing: 10) {
                VMark(height: 22)

                Text(title)
                    .font(.title2.weight(.bold))
                    .foregroundStyle(.white)
                    .fixedSize()
            }
        }
        .sharedBackgroundVisibility(.hidden)
        ToolbarItem(placement: .topBarTrailing) {
            Button { showingDownloads = true } label: {
                Image("DownloadGlyph")
                    .renderingMode(.template)
                    .resizable()
                    .scaledToFit()
                    .frame(width: 22, height: 22)
                    .foregroundStyle(.white)
                    .frame(width: 40, height: 40)
                    .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("My Downloads")
            .popover(isPresented: onTab($showingDownloads, value), arrowEdge: .top) {
                NavigationStack { DownloadsView(playing: $playing) }
                    .environment(state)
                    .frame(minWidth: 420, idealWidth: 480, minHeight: 420, idealHeight: 640)
                    .presentationCompactAdaptation(.sheet)
                    .presentationDetents([.medium, .large], selection: $downloadsDetent)
                    .preferredColorScheme(.dark)
                    .onDisappear { downloadsDetent = .medium }
            }
        }
        .sharedBackgroundVisibility(.hidden)
        ToolbarItem(placement: .topBarTrailing) {
            // Once the bell's list has gone: one popover cannot open while another is closing.
            NotificationsBell(selection: $selection) {
                Task {
                    try? await Task.sleep(for: .milliseconds(450))
                    showingDownloads = true
                }
            }
        }
        .sharedBackgroundVisibility(.hidden)
        ToolbarItem(placement: .topBarTrailing) {
            Button { switchingProfile = true } label: {
                Avatar(id: state.profile?.avatar, size: 30)
                    .frame(width: 40, height: 40)
                    .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Switch profile")
            .popover(isPresented: onTab($switchingProfile, value), arrowEdge: .top) {
                NavigationStack { ProfilesView(dismissable: true) }
                    .environment(state)
                    .frame(minWidth: 400, idealWidth: 580, minHeight: 240, idealHeight: 300)
                    .presentationCompactAdaptation(.sheet)
                    .presentationDetents([.medium, .large])
                    .preferredColorScheme(.dark)
            }
        }
        .sharedBackgroundVisibility(.hidden)
    }
}

private struct OwnTabBar: ViewModifier {
    func body(content: Content) -> some View {
        content
            // A margin on every scroll view in the tab, pushed pages included: extra safe area did not reach them.
            .contentMargins(.bottom, AppTabBar.clearance, for: .scrollContent)
    }
}

/// No navigation title: the screen's name is drawn next to the V in the toolbar.
private struct BarTitle: ViewModifier {
    func body(content: Content) -> some View {
        content
            .navigationTitle("")
            .navigationBarTitleDisplayMode(.inline)
    }
}

private struct LaunchView: View {
    var body: some View {
        ZStack {
            Palette.ground.ignoresSafeArea()
            BootSpinner()
        }
    }
}

private struct StartupFailure: View {
    @Environment(AppState.self) private var state

    var body: some View {
        ZStack {
            Palette.ground.ignoresSafeArea()
            VStack(spacing: 14) {
                Image(systemName: "wifi.exclamationmark")
                    .font(.system(size: 40))
                    .foregroundStyle(Palette.faint)
                Text("Can't reach VibeStream")
                    .font(.title3.weight(.bold))
                Text("Check that the server is running and that this device is online.")
                    .font(.subheadline)
                    .foregroundStyle(Palette.dim)
                    .multilineTextAlignment(.center)
                Button("Try Again") { Task { await state.retryStartup() } }
                    .buttonStyle(.borderedProminent)
                    .tint(.white)
                    .foregroundStyle(.black)
                    .padding(.top, 6)
            }
            .padding(32)
        }
    }
}
