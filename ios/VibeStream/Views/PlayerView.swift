import AVFoundation
import AVKit
import SwiftUI

// A plain AVPlayerLayer: the controls are custom, not AVKit's.
// The player is attached only once its item is ready: a layer holding the player while
// the item prepares makes AVFoundation refuse HDR titles (-11868 over -17223, "Cannot open").
struct PlayerSurface: UIViewRepresentable {
    let player: AVPlayer?
    var filling: Bool
    /// The layer, once made, for Picture in Picture to play from.
    var onLayer: ((AVPlayerLayer) -> Void)? = nil

    func makeUIView(context: Context) -> LayerView {
        let view = LayerView()
        if let onLayer {
            let layer = view.playerLayer
            DispatchQueue.main.async { onLayer(layer) }
        }
        view.playerLayer.player = player
        view.playerLayer.videoGravity = filling ? .resizeAspectFill : .resizeAspect
        view.backgroundColor = .black
        // Draw only: left hit-testable it swallows the taps that bring the controls back.
        view.isUserInteractionEnabled = false
        return view
    }

    func updateUIView(_ uiView: LayerView, context: Context) {
        // nil until the item is ready, so this is where the picture arrives.
        if uiView.playerLayer.player !== player {
            uiView.playerLayer.player = player
        }
        uiView.playerLayer.videoGravity = filling ? .resizeAspectFill : .resizeAspect
    }

    final class LayerView: UIView {
        override static var layerClass: AnyClass { AVPlayerLayer.self }
        var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
    }
}

// A new episode is a new PlayerView keyed by play id, so nothing leaks between episodes;
// the host stays put so the full screen cover is not dismissed and re-presented.
#if DEBUG
/// Counts players started in a run, for the debug launch switches.
enum DebugRun { @MainActor static var players = 0 }
#endif

struct PlayerHost: View {
    @State var request: PlayRequest
    var onAdvance: ((PlayRequest) -> Void)?
    var handed: PlayerModel?
    var sideways = false
    var onUpright: ((PlayerModel, PlayRequest) -> Void)?

    init(request: PlayRequest, handed: PlayerModel? = nil, sideways: Bool = false,
         onUpright: ((PlayerModel, PlayRequest) -> Void)? = nil,
         onAdvance: ((PlayRequest) -> Void)? = nil) {
        _request = State(initialValue: request)
        self.onAdvance = onAdvance
        self.handed = handed
        self.sideways = sideways
        self.onUpright = onUpright
    }

    var body: some View {
        PlayerView(request: request, handed: handed, sideways: sideways,
                   onUpright: onUpright) { next in
            request = next
            onAdvance?(next)
        }
        .id(request.playID)
    }
}

struct PlayerView: View {
    @State private var tall = false
    let request: PlayRequest
    var onNext: ((PlayRequest) -> Void)?

    /// Inline in the title page's picture; turning sideways or Full Screen hands the playback to the whole screen player.
    var inline = false
    /// Inline: false while the whole screen player has the playback, so this
    /// one neither draws it nor acts on it.
    var active = true
    var onFullScreen: ((PlayerModel, _ sideways: Bool) -> Void)?
    var onStop: (() -> Void)?
    var onClosePage: (() -> Void)?
    var onUpright: ((PlayerModel, PlayRequest) -> Void)?
    var startSideways = false
    /// Once sideways, so the upright it starts in is not taken for a turn back.
    @State private var wasSideways = false
    @State private var handingBack = false
    /// Whether turning sideways now counts as a turn: not when back from full screen still sideways.
    @State private var seenUpright = !UIDevice.current.orientation.isLandscape
    @Environment(AppState.self) private var state
    @Environment(\.dismiss) private var dismiss

    @State private var model: PlayerModel
    @State private var chromeVisible = true
    @State private var hideTask: Task<Void, Never>?
    @State private var locked = false
    @State private var lockHintVisible = false
    @State private var unlockOpen = false
    @State private var justUnlocked = false
    @State private var lockTask: Task<Void, Never>?
    @State private var locking = false
    @State private var closing = false
    @State private var episodesOpen = false
    @State private var clipping = false
    @State private var exiting = false
    /// Counted as a whole-screen player, which is what lets it rotate the app. See Orientation.playersOnScreen.
    @State private var counted = false
    @State private var presence: Double = 1
    @State private var scrubbing = false
    @State private var scrubTarget: Double = 0
    @State private var filling = false
    /// Leaving for the next episode, so the window must not turn back to portrait.
    @State private var advancing = false
    @State private var creditsChosen = false
    @State private var endFill: Double = 0
    private let resumed: Bool
    @State private var castPicking = false
    @State private var castToken: UUID?
    @State private var leavingFor: Card?
    @State private var previewing: EpisodeItem?
    @State private var previewShow: Card?
    /// The preview covers the player without stopping it or setting it up again.
    @State private var covered = false
    /// The window was turned by Full Screen and is held until the phone is turned to match.
    @State private var turnedTo: UIInterfaceOrientationMask?
    @Environment(\.openTitle) private var openTitle
    @State private var brightnessBefore: CGFloat?

    // Up next pills appear this many seconds before the end. The fill tracks the time left,
    // so it completes exactly at the end and stops while paused.
    private static let upNextLead: Double = 20
    private static let upNextAfterEnd: Double = 5

    private enum Tray { case speed, brightness }
    @State private var tray: Tray?
    @State private var settingsOpen = false
    @AppStorage("vibestream.player.stats") private var statsShown = false
    @State private var previewingLook = false
    @State private var stats = PlayerStats()

    init(request: PlayRequest, handed: PlayerModel? = nil, inline: Bool = false,
         active: Bool = true, sideways: Bool = false,
         onFullScreen: ((PlayerModel, Bool) -> Void)? = nil,
         onStop: (() -> Void)? = nil, onClosePage: (() -> Void)? = nil,
         onUpright: ((PlayerModel, PlayRequest) -> Void)? = nil,
         onNext: ((PlayRequest) -> Void)? = nil) {
        self.request = request
        self.onNext = onNext
        self.inline = inline
        self.active = active
        self.startSideways = sideways
        self.onFullScreen = onFullScreen
        self.onStop = onStop
        self.onClosePage = onClosePage
        self.onUpright = onUpright
        // Back from Picture in Picture, or between the page's picture and the whole screen: the same playback.
        let held = PictureInPicture.shared.takePlayback(for: request.playID)
        let given = handed?.playID == request.playID ? handed : nil
        resumed = held != nil || given != nil
        _model = State(initialValue: held ?? given ?? PlayerModel(playID: request.playID,
                                                                  title: request.title,
                                                                  startAt: request.startAt))
    }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea(edges: inline ? [] : .all)

            // Black before the window turns, so the rotation happens against black.
            if !closing && !(onUpright != nil && phone && !wasSideways) {
                // One surface whichever way up, so turning moves the picture instead of rebinding it (which goes black).
                GeometryReader { geo in
                    VStack(spacing: 0) {
                        stage
                            .frame(width: boxed ? box(in: geo.size).width : nil,
                                   height: upright ? (geo.size.width * 9 / 16).rounded()
                                       : boxed ? box(in: geo.size).height : geo.size.height)
                            .clipShape(.rect(cornerRadius: boxed ? 22 : 0))
                            .shadow(color: .black.opacity(boxed ? 0.6 : 0), radius: 24)
                            .padding(.leading, boxed ? 6 : 0)
                            .frame(maxWidth: .infinity,
                                   maxHeight: upright ? nil : geo.size.height,
                                   alignment: .leading)
                        if upright && !inline && onUpright == nil {
                            PlayerPage(playID: request.playID, title: request.title,
                                       mediaID: model.info?.mediaID,
                                       presentation: model.info?.presentation,
                                       loaded: model.info != nil,
                                       onEpisode: onNext == nil ? nil : { playEpisode($0) },
                                       onPreview: onNext == nil ? nil : { preview($0) },
                                       tracks: model.ready ? choices : nil,
                                       onTitle: { leave(for: $0) })
                                .transition(.opacity)
                        }
                    }
                    .overlay(alignment: .trailing) {
                        if boxed {
                            Group {
                                if settingsOpen {
                                    PlayerSettings(choices: choices, statsShown: $statsShown,
                                                   previewingLook: $previewingLook,
                                                   onClose: closeSettings)
                                } else if let media = mediaID,
                                          let episode = model.info?.presentation?.episode {
                                    PlayerEpisodes(mediaID: media, playing: episode,
                                                   playID: request.playID,
                                                   onChoose: { playEpisode($0) },
                                                   onClose: closeEpisodes)
                                }
                            }
                            .frame(width: max(240, geo.size.width - box(in: geo.size).width - 34))
                            .padding(.vertical, 14)
                            .transition(.move(edge: .trailing).combined(with: .opacity))
                        }
                    }
                }
            }
        }
        .overlay {
            if clipping {
                ClipEditor(model: model, playID: request.playID) {
                    withAnimation(.easeOut(duration: 0.2)) { clipping = false }
                    showChrome()
                }
                .transition(.opacity)
            }
        }
        .onGeometryChange(for: Bool.self) { $0.size.height > $0.size.width } action: {
            tall = $0
            if !$0 { wasSideways = true }
        }
        .opacity(presence)
        .statusBarHidden(!inline && !upright)
        .persistentSystemOverlays(inline ? .automatic : .hidden)
        .onChange(of: upright) { _, now in
            if now {
                if episodesOpen { closeEpisodes() }
                tray = nil
                settingsOpen = false
            }
            if !now { wasSideways = true }
            if now && wasSideways && onUpright != nil && phone { handBack() }
            showChrome()
        }
        .onReceive(NotificationCenter.default.publisher(for: UIDevice.orientationDidChangeNotification)) { _ in
            settleTurn()
            let device = UIDevice.current.orientation
            if !device.isLandscape { seenUpright = true }
            if inline && active && phone && seenUpright && model.ready && model.error == nil
                && device.isLandscape {
                seenUpright = false
                onFullScreen?(model, false)
            }
        }
        .onChange(of: active) { _, now in
            if now { seenUpright = !UIDevice.current.orientation.isLandscape }
        }
        // Keep the screen awake while playing, inline too: AVPlayer's own idle prevention does not cover the strip.
        .onChange(of: model.isPlaying && active, initial: true) { _, awake in
            if active { UIApplication.shared.isIdleTimerDisabled = awake }
        }
        .onChange(of: statsShown && model.ready, initial: true) { _, sampling in
            if sampling { stats.start(model.player) } else { stats.stop() }
        }
        .onDisappear { if !covered { stats.stop() } }
        .onAppear {
            model.trace.mark("view appeared: inline \(inline), active \(active), resumed \(resumed)")
        }
        .task {
            if covered {
                covered = false
                return
            }
            // The player rotates with the phone; on iPad this does nothing by design (see Orientation.swift).
            if inline {
                UIDevice.current.beginGeneratingDeviceOrientationNotifications()
            } else {
                if !counted && !exiting {
                    counted = true
                    Orientation.playerAppeared()
                }
                Orientation.lock(Orientation.player, fromPlayer: true)
                brightnessBefore = Screen.brightness
                if startSideways && phone { turn(to: .landscapeRight) }
            }
            if !resumed {
                model.prefs = state.playerPrefs
                await model.start()
            }
            showChrome()
            #if DEBUG
            // -locked: start locked.
            if ProcessInfo.processInfo.arguments.contains("-locked") { lock() }
            // -chrome: keep the controls up, to look at them.
            if ProcessInfo.processInfo.arguments.contains("-chrome") {
                Task {
                    try? await Task.sleep(for: .seconds(6))
                    showChrome()
                }
            }
            DebugRun.players += 1
            let index = DebugRun.players
            // -nearEnd: jump to the closing seconds, first player only.
            if ProcessInfo.processInfo.arguments.contains("-nearEnd") && index == 1 {
                while model.duration == 0 { try? await Task.sleep(for: .milliseconds(200)) }
                try? await Task.sleep(for: .seconds(1))
                model.seek(to: model.duration - 14)
            }
            // -closeOnSecond: leave from the episode autoplay moved on to.
            if ProcessInfo.processInfo.arguments.contains("-closeOnSecond") && index == 2 {
                try? await Task.sleep(for: .seconds(10))
                close()
            }
            // -clipEditor: open Clip a Moment once it is playing.
            if ProcessInfo.processInfo.arguments.contains("-clipEditor") {
                try? await Task.sleep(for: .seconds(9))
                openClip()
            }
            // -fullScreenAfter <s>: press Full Screen; -uprightAfter <s>: turn back upright.
            let turns = ProcessInfo.processInfo.arguments
            if inline, let flag = turns.firstIndex(of: "-fullScreenAfter"), flag + 1 < turns.count,
               let seconds = Double(turns[flag + 1]) {
                try? await Task.sleep(for: .seconds(seconds))
                if model.ready { onFullScreen?(model, true) }
            }
            if onUpright != nil, let flag = turns.firstIndex(of: "-uprightAfter"), flag + 1 < turns.count,
               let seconds = Double(turns[flag + 1]) {
                try? await Task.sleep(for: .seconds(seconds))
                withAnimation(.easeOut(duration: 0.12)) { closing = true }
                turn(to: .portrait)
            }
            // -stats: the playback stats over the picture.
            if ProcessInfo.processInfo.arguments.contains("-stats") { statsShown = true }
            // -settings: open Settings beside the picture once it is playing.
            if ProcessInfo.processInfo.arguments.contains("-settings") {
                try? await Task.sleep(for: .seconds(7))
                openSettings()
            }
            // -subStyle <style> [-subSize <size>]: draw subtitles that way.
            let args = ProcessInfo.processInfo.arguments
            if let flag = args.firstIndex(of: "-subStyle"), flag + 1 < args.count,
               let style = SubtitleStyle(rawValue: args[flag + 1]) {
                model.prefs.subtitleStyle = style
                if let sizeFlag = args.firstIndex(of: "-subSize"), sizeFlag + 1 < args.count,
                   let size = SubtitleSize(rawValue: args[sizeFlag + 1]) {
                    model.prefs.subtitleSize = size
                }
                model.applySubtitleAppearance()
                if model.subtitleID == nil, let first = model.info?.subtitles.first {
                    model.chooseSubtitle(first.id)
                }
            }
            // -tray speed|brightness: open that panel over the picture.
            if let flag = ProcessInfo.processInfo.arguments.firstIndex(of: "-tray"),
               flag + 1 < ProcessInfo.processInfo.arguments.count {
                try? await Task.sleep(for: .seconds(7))
                tray = ProcessInfo.processInfo.arguments[flag + 1] == "speed" ? .speed : .brightness
                showChrome()
            }
            // -episodesPanel: open Episodes once the episode is playing.
            if ProcessInfo.processInfo.arguments.contains("-episodesPanel") {
                try? await Task.sleep(for: .seconds(7))
                openEpisodes()
            }
            // -closeAfter <seconds>: press X.
            let arguments = ProcessInfo.processInfo.arguments
            if let flag = arguments.firstIndex(of: "-closeAfter"), flag + 1 < arguments.count,
               let seconds = Double(arguments[flag + 1]) {
                try? await Task.sleep(for: .seconds(seconds))
                close()
            }
            if ProcessInfo.processInfo.arguments.contains("-scrubProbe") {
                try? await Task.sleep(for: .seconds(2))
                scrubTarget = model.duration * 0.4
                scrubbing = true
            }
            // -scrubSweep: drag the knob from 10% to 70% over six seconds at a 120 Hz touch rate.
            if ProcessInfo.processInfo.arguments.contains("-scrubSweep") {
                try? await Task.sleep(for: .seconds(6))
                showChrome()
                scrubbing = true
                for step in 0...750 {
                    scrubTarget = model.duration * (0.1 + 0.6 * Double(step) / 750)
                    try? await Task.sleep(for: .milliseconds(8))
                }
            }
            #endif
        }
        .task(id: model.ended && active) { await runEndOfEpisode() }
        .fullScreenCover(item: $previewing) { episode in
            if let previewShow {
                EpisodePreview(card: previewShow, item: episode) { chosen in
                    Task {
                        try? await Task.sleep(for: .milliseconds(400))
                        playEpisode(chosen)
                    }
                }
                .environment(state)
                .environment(\.openTitle) { leave(for: $0) }
            }
        }
        .sheet(isPresented: $castPicking) {
            CastPicker { device in handOff(to: device) }
                .presentationDetents([.medium])
        }
        // Another device's remote: commands in, status out every two seconds while playing.
        .task(id: model.ready && active) {
            guard model.ready, active else { return }
            if castToken == nil {
                castToken = Cast.shared.onControl { command in obey(command) }
            }
            while !Task.isCancelled {
                Cast.shared.report(CastPlaying(
                    playID: request.playID,
                    mediaID: model.info?.mediaID,
                    title: model.info?.presentation?.title ?? request.title,
                    detail: model.info?.presentation?.episodeLine,
                    position: model.current.rounded(),
                    duration: model.duration.rounded(),
                    paused: !model.isPlaying,
                    presentation: model.info?.presentation,
                    subtitles: model.info?.subtitles,
                    audio: model.info?.audio,
                    subtitleID: model.subtitleID,
                    audioIndex: model.audioIndex ?? model.info?.defaultAudioIndex,
                    subtitleSize: model.prefs.subtitleSize,
                    subtitleStyle: model.prefs.subtitleStyle))
                try? await Task.sleep(for: .seconds(2))
            }
        }
        .onChange(of: model.subtitleID) { _, id in
            guard model.ready else { return }
            var prefs = state.playerPrefs
            prefs.subtitlesOff = id == nil
            if let id, let language = model.info?.subtitles.first(where: { $0.id == id })?.language {
                prefs.subtitleLanguage = language
            }
            state.playerPrefs = prefs
        }
        .onChange(of: model.rate) { _, rate in
            guard model.ready else { return }
            var prefs = state.playerPrefs
            prefs.speed = rate
            state.playerPrefs = prefs
        }
        .onChange(of: model.current) { _, now in
            if creditsChosen && model.duration - now > Self.upNextLead + 5 { creditsChosen = false }
        }
        .onDisappear {
            model.trace.mark("view gone: inline \(inline), active \(active), handing back \(handingBack)")
            if covered && !exiting && !advancing && !handingBack { return }
            if let castToken { Cast.shared.removeControl(castToken) }
            castToken = nil
            if active { Cast.shared.report(nil) }
            // Handed to Picture in Picture or between inline and full screen: it plays on there.
            if !PictureInPicture.shared.isHoldingPlayback(model) && !handingBack && active {
                PictureInPicture.shared.detach(model)
                model.stop()
            }
            hideTask?.cancel()
            lockTask?.cancel()
            if active && !handingBack { UIApplication.shared.isIdleTimerDisabled = false }
            if let brightnessBefore { Screen.brightness = brightnessBefore }
            if counted {
                counted = false
                Orientation.playerLeft(release: !advancing)
            } else if !advancing && !inline {
                Orientation.release()
            }
            if let leavingFor { openTitle?(leavingFor) }
        }
    }

    private var stage: some View {
        ZStack {
            Color.black
            // Bound only once the item is ready; see PlayerSurface.
            PlayerSurface(player: model.ready && active ? model.player : nil,
                          filling: filling && !upright) { layer in
                PictureInPicture.shared.attach(layer: layer, model: model, request: request) {
                    close(keepPlaying: true)
                }
            }
            // Recreated on return from full screen, so Picture in Picture plays from this layer.
            .id(active)
            .ignoresSafeArea(edges: upright || boxed ? [] : .all)

            // Subtitles are drawn here, not by AVFoundation (see Captions).
            let lines = boxed && previewingLook ? [Self.sampleCaption] : model.caption
            if !lines.isEmpty {
                GeometryReader { geo in
                    Captions(lines: lines, size: model.prefs.subtitleSize,
                             style: model.prefs.subtitleStyle, height: geo.size.height)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                        .padding(.bottom, geo.size.height * (chromeVisible && !locked && !boxed
                            ? (upright ? 0.24 : 0.2) : 0.06))
                        .animation(.easeOut(duration: 0.2), value: chromeVisible)
                }
            }

            if let error = model.error {
                failure(error)
            } else if !model.ready {
                preparing
            }

            if model.ready && model.buffering && model.error == nil {
                BootSpinner(size: upright ? 36 : 48, line: upright ? 3 : 4)
            }

            Group {
                if boxed && model.ready && !model.isPlaying && !model.buffering && model.error == nil {
                    Image(systemName: "play.fill")
                        .font(.system(size: 30, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(width: 64, height: 64)
                        .background(.black.opacity(0.45), in: .circle)
                        .allowsHitTesting(false)
                        .transition(.opacity.combined(with: .scale(scale: 0.85)))
                }
            }
            .animation(.easeOut(duration: 0.18), value: model.isPlaying)

            if statsShown && model.ready {
                let clear = chromeVisible && !locked && !boxed && model.error == nil
                GeometryReader { geo in
                    StatsOverlay(stats: stats, model: model, area: geo.size)
                        .scaleEffect(boxed ? 0.85 : 1, anchor: .topLeading)
                        .padding(.top, (upright || boxed ? 8 : 14) + (clear ? (upright ? 40 : 58) : 0))
                        .padding(.leading, upright || boxed ? 8 : 14)
                        .animation(.easeOut(duration: 0.2), value: clear)
                }
                .transition(.opacity)
            }

            if chromeVisible && !locked && !boxed && model.error == nil {
                Group {
                    if upright { compactChrome } else { chrome }
                }
                .transition(.opacity)
            }

            if let next = upNext, !boxed {
                upNextPills(next)
                    .scaleEffect(upright ? 0.78 : 1, anchor: .bottomTrailing)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
                    .padding(.trailing, upright ? 12 : 24)
                    .padding(.bottom, upright ? (chromeVisible ? 46 : 10) : (chromeVisible ? 104 : 26))
                    .transition(.opacity)
            }

            if locked && lockHintVisible {
                lockHint
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                    .padding(.bottom, 34)
                    .transition(.opacity)
            }

            if justUnlocked {
                Image(systemName: "lock.open.fill")
                    .font(.system(size: 40, weight: .semibold))
                    .foregroundStyle(.white)
                    .shadow(color: .black.opacity(0.5), radius: 6)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                    .padding(.bottom, 34)
                    .allowsHitTesting(false)
                    .transition(.opacity.combined(with: .scale(scale: 0.8)))
            }
        }
        .contentShape(.rect)
        .onTapGesture {
            if locked { showLockHint() }
            else if boxed { model.togglePlay() }
            else if tray != nil { withAnimation(.easeOut(duration: 0.18)) { tray = nil }; showChrome() }
            else { toggleChrome() }
        }
        // Sideways, a pinch toggles fill and fit.
        .simultaneousGesture(
            MagnifyGesture(minimumScaleDelta: 0.05)
                .onEnded { value in
                    guard !upright, !locked, !episodesOpen, !clipping, !boxed else { return }
                    let fill = value.magnification > 1
                    guard fill != filling else { return }
                    withAnimation(.easeInOut(duration: 0.2)) { filling = fill }
                },
            including: .all
        )
    }

    private var compactChrome: some View {
        ZStack {
            LinearGradient(colors: [.black.opacity(0.55), .black.opacity(0.15), .black.opacity(0.65)],
                           startPoint: .top, endPoint: .bottom)
                .allowsHitTesting(false)

            VStack(spacing: 0) {
                HStack(spacing: 0) {
                    chromeButton("xmark", weight: .bold) {
                        if inline, let onClosePage { onClosePage() } else { close() }
                    }
                    Spacer(minLength: 8)
                    if model.ready {
                        castButton
                        if PictureInPicture.supported {
                            chromeButton("pip.enter") { PictureInPicture.shared.start() }
                                .accessibilityLabel("Picture in Picture")
                        }
                    }
                }
                Spacer(minLength: 0)
                if model.ready {
                    HStack(spacing: 6) {
                        Scrubber(model: model, scrubbing: $scrubbing, target: $scrubTarget) {
                            showChrome()
                        }
                        // A phone can be rotated for the viewer; an iPad cannot.
                        if inline {
                            chromeButton("arrow.up.left.and.arrow.down.right") { onFullScreen?(model, true) }
                                .accessibilityLabel("Full Screen")
                        } else if phone {
                            chromeButton("arrow.up.left.and.arrow.down.right") { turn(to: .landscapeRight) }
                                .accessibilityLabel("Full Screen")
                        }
                    }
                    .padding(.leading, 12)
                }
            }
            .padding(.horizontal, 4)
            .foregroundStyle(.white)

            if model.ready { centreControls(compact: true) }
        }
    }

    /// The next episode while the pills are up. Not while locked, where a resting palm could press them.
    private var upNext: PlayInfo.NextEpisode? {
        guard onNext != nil, model.ready, model.error == nil, !locked,
              let next = model.info?.next, model.duration > 0 else { return nil }
        if model.ended { return next }
        let remaining = model.duration - model.current
        return !creditsChosen && remaining <= Self.upNextLead ? next : nil
    }

    /// How full the Next Episode pill is, from 0 to 1.
    private var fill: Double {
        if model.ended { return creditsChosen ? endFill : 1 }
        let remaining = max(0, model.duration - model.current)
        return min(1, max(0, 1 - remaining / Self.upNextLead))
    }

    private func runEndOfEpisode() async {
        guard model.ended else {
            endFill = 0
            return
        }
        guard model.info?.next != nil, onNext != nil else {
            close()
            return
        }
        guard creditsChosen else {
            playNext()
            return
        }
        withAnimation(.linear(duration: Self.upNextAfterEnd)) { endFill = 1 }
        try? await Task.sleep(for: .seconds(Self.upNextAfterEnd))
        if !Task.isCancelled { playNext() }
    }

    private func playNext() {
        guard let next = model.info?.next, let onNext, !advancing else { return }
        advancing = true
        model.stop()
        onNext(PlayRequest(playID: next.playID, title: request.title,
                           season: next.season, episode: next.number))
    }

    private func openClip() {
        hideTask?.cancel()
        if model.isPlaying { model.togglePlay() }
        withAnimation(.easeOut(duration: 0.2)) { clipping = true }
    }

    private func openEpisodes() {
        withAnimation(.spring(duration: 0.42, bounce: 0.15)) {
            tray = nil
            settingsOpen = false
            episodesOpen = true
        }
    }

    private func closeEpisodes() {
        withAnimation(.spring(duration: 0.42, bounce: 0.15)) { episodesOpen = false }
        showChrome()
    }

    private func playEpisode(_ item: EpisodeItem) {
        guard let playID = item.playID, let onNext, !advancing else { return }
        advancing = true
        model.stop()
        onNext(PlayRequest(playID: playID, title: request.title,
                           season: item.season, episode: item.episode))
    }

    private func upNextPills(_ next: PlayInfo.NextEpisode) -> some View {
        VStack(alignment: .trailing, spacing: 10) {
            Text("Next: S\(next.season):E\(next.number) \(next.name)")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.white.opacity(0.88))
                .shadow(color: .black.opacity(0.7), radius: 6)
                .lineLimit(1)
                .frame(maxWidth: 360, alignment: .trailing)

            HStack(spacing: 12) {
                if !model.ended {
                    Button { creditsChosen = true } label: {
                        Text("Watch Credits")
                            .font(.subheadline.weight(.semibold))
                            .padding(.horizontal, 18)
                            .frame(height: 44)
                            .background(Capsule().fill(Color(white: 0.22).opacity(0.88)))
                            .contentShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.white)
                }
                Button { playNext() } label: { nextPill }
                    .buttonStyle(.plain)
            }
        }
    }

    // A white fill clips a black copy of the label, so the text inverts as the fill passes.
    private var nextPill: some View {
        let width: CGFloat = 196
        let label = HStack(spacing: 8) {
            Image(systemName: "play.fill")
            Text("Next Episode")
        }
        .font(.subheadline.weight(.bold))
        .frame(width: width, height: 44)

        return label
            .foregroundStyle(.white)
            .background(Color(white: 0.22).opacity(0.88))
            .overlay(alignment: .leading) {
                label
                    .foregroundStyle(.black)
                    .frame(width: width * fill, alignment: .leading)
                    .background(Color.white)
                    .clipped()
                    .animation(.linear(duration: 0.25), value: fill)
            }
            .clipShape(Capsule())
            .contentShape(Capsule())
    }

    private var preparing: some View {
        BootSpinner(size: upright ? 40 : 52, line: 4)
    }

    private func failure(_ message: String) -> some View {
        VStack(spacing: 12) {
            Text("Cannot play this title").font(.headline).foregroundStyle(Palette.accent)
            Text(message).font(.footnote).foregroundStyle(Palette.dim)
                .multilineTextAlignment(.center)
            HStack(spacing: 10) {
                Button("Try Again") { model.retry() }.buttonStyle(.glassProminent).tint(Palette.accent)
                Button("Close") { close() }.buttonStyle(.glass)
            }
        }
        .padding(upright ? 14 : 26)
        .glassCard(20)
        .padding(upright ? 10 : 40)
    }

    private var chrome: some View {
        VStack(spacing: 0) {
            topBar
            Spacer()
            if model.ready {
                centreControls()
                    .opacity(tray == nil ? 1 : 0)
                    .allowsHitTesting(tray == nil)
                    .animation(.easeOut(duration: 0.18), value: tray == nil)
                Spacer()
                if let tray {
                    Group {
                        switch tray {
                        case .speed: SpeedTray(model: model) { showChrome() }
                        case .brightness: BrightnessTray { showChrome() }
                        }
                    }
                    .padding(.bottom, 12)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
                }
                bottomBar
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background {
            LinearGradient(colors: [.black.opacity(0.65), .clear, .black.opacity(0.8)],
                           startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
                .allowsHitTesting(false)
        }
    }

    private var topBar: some View {
        HStack(spacing: 14) {
            if !offersExit {
                chromeButton("xmark", weight: .bold) { close() }
            }
            // The title from the server, so it follows autoplay instead of naming the episode pressed.
            VStack(alignment: .leading, spacing: 2) {
                Text(model.info?.presentation?.title ?? request.title)
                    .font(.headline).lineLimit(1)
                if let line = model.info?.presentation?.episodeLine {
                    Text(line).font(.footnote).foregroundStyle(.white.opacity(0.75)).lineLimit(1)
                }
            }
            Spacer(minLength: 12)

            if model.ready { castButton }
            if PictureInPicture.supported && model.ready {
                chromeButton("pip.enter") { PictureInPicture.shared.start() }
                    .accessibilityLabel("Picture in Picture")
            }
            chromeButton(locking ? "lock.fill" : "lock.open", action: lock)
                .contentTransition(.symbolEffect(.replace))
        }
        .foregroundStyle(.white)
    }

    private var castButton: some View {
        Button { castPicking = true } label: {
            // Custom glyph drawn to sit with the SF Symbols.
            Image("CastGlyph")
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .frame(width: 22, height: 22)
                .shadow(color: .black.opacity(0.5), radius: 3)
                .frame(width: 44, height: 44)
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Play on another device")
    }

    // A bare glyph with a soft dark halo for contrast; the tap target stays finger sized.
    private func chromeButton(
        _ symbol: String,
        weight: Font.Weight = .regular,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: weight))
                .shadow(color: .black.opacity(0.5), radius: 3)
                .frame(width: 44, height: 44)
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
    }


    private func centreControls(compact: Bool = false) -> some View {
        HStack(spacing: compact ? 46 : 54) {
            Button { model.skip(-10); showChrome() } label: {
                Image(systemName: "gobackward.10").font(.system(size: compact ? 24 : 34))
            }
            Button { model.togglePlay(); showChrome() } label: {
                Image(systemName: model.isPlaying ? "pause.fill" : "play.fill")
                    .font(.system(size: compact ? 34 : 46))
                    .contentTransition(.symbolEffect(.replace))
            }
            Button { model.skip(10); showChrome() } label: {
                Image(systemName: "goforward.10").font(.system(size: compact ? 24 : 34))
            }
        }
        .shadow(color: .black.opacity(compact ? 0.4 : 0), radius: 4)
        .foregroundStyle(.white)
        .buttonStyle(.plain)
    }

    private var bottomBar: some View {
        VStack(spacing: 8) {
            Scrubber(model: model, scrubbing: $scrubbing, target: $scrubTarget) {
                showChrome()
            }

            HStack(spacing: phone ? 22 : 30) {
                Button { openClip() } label: {
                    barLabel("Clip", systemImage: "scissors")
                }
                Spacer(minLength: 0)
                if onNext != nil, mediaID != nil, model.info?.presentation?.episode != nil {
                    Button { openEpisodes() } label: {
                        barLabel("Episodes", systemImage: "rectangle.stack")
                    }
                }
                if onNext != nil, model.info?.next != nil {
                    Button { playNext() } label: {
                        barLabel("Next Episode", systemImage: "forward.end")
                    }
                }
                Button { toggle(.speed) } label: {
                    barLabel("Speed (\(speedLabel))", systemImage: "speedometer")
                        .opacity(tray == .speed ? 1 : tray == nil ? 1 : 0.5)
                }
                Button { toggle(.brightness) } label: {
                    barLabel("Brightness", systemImage: "sun.max")
                        .opacity(tray == .brightness ? 1 : tray == nil ? 1 : 0.5)
                }
                Button { openSettings() } label: {
                    barLabel("Settings", systemImage: "gearshape")
                }
                if phone {
                    Button {
                        if onUpright != nil { withAnimation(.easeOut(duration: 0.12)) { closing = true } }
                        turn(to: .portrait)
                    } label: {
                        barLabel("Exit Full Screen", systemImage: "arrow.down.right.and.arrow.up.left")
                    }
                } else if offersExit {
                    Button { handBack() } label: {
                        barLabel("Exit Full Screen", systemImage: "arrow.down.right.and.arrow.up.left")
                    }
                }
            }
            .font(.footnote.weight(.medium))
            .lineLimit(1)
            .foregroundStyle(.white)
            .buttonStyle(.plain)
        }
    }

    private var phone: Bool { UIDevice.current.userInterfaceIdiom == .phone }

    private var offersExit: Bool { phone || onUpright != nil }

    /// By the window's shape, not its size class, which is regular on an iPad either way.
    private var upright: Bool {
        if inline { return true }
        if onUpright != nil && !phone { return false }
        return tall
    }

    private func barLabel(_ title: String, systemImage: String) -> some View {
        Image(systemName: systemImage)
            .font(.system(size: phone ? 20 : 22, weight: .semibold))
            .frame(minWidth: 44, minHeight: 44)
            .contentShape(.rect)
            .accessibilityLabel(title)
    }

    private var speedLabel: String {
        model.rate == 1 ? "1x" : String(format: "%gx", model.rate)
    }

    // From the server: a play id like "e34" says nothing about its show.
    private var mediaID: Int? { model.info?.mediaID }

    // Locked shows nothing: a tap summons the padlock, a tap on it opens the slider, a full slide unlocks.
    private var lockHint: some View {
        SlideToUnlock(open: unlockOpen, onOpen: {
            withAnimation(.spring(duration: 0.35, bounce: 0.15)) { unlockOpen = true }
            showLockHint()
        }, onUnlock: unlock, onTouch: { dragging in
            if dragging { lockTask?.cancel() } else { showLockHint() }
        })
    }

    private func lock() {
        guard !locking else { return }
        hideTask?.cancel()
        // Let the padlock finish closing first: it is the only confirmation the action gives.
        withAnimation(.easeOut(duration: 0.25)) { locking = true }
        Task {
            try? await Task.sleep(for: .milliseconds(420))
            withAnimation(.easeOut(duration: 0.2)) {
                locked = true
                chromeVisible = false
            }
            locking = false
            Orientation.holdCurrent()
            showLockHint()
        }
    }

    private func showLockHint() {
        withAnimation(.easeOut(duration: 0.2)) { lockHintVisible = true }
        lockTask?.cancel()
        lockTask = Task {
            try? await Task.sleep(for: .seconds(4))
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.25)) {
                lockHintVisible = false
                unlockOpen = false
            }
        }
    }

    private func unlock() {
        lockTask?.cancel()
        // Removed without fading: fading the track during a fast slide drew it over the knob.
        var instantly = Transaction()
        instantly.disablesAnimations = true
        withTransaction(instantly) {
            locked = false
            lockHintVisible = false
            unlockOpen = false
        }
        Orientation.lock(Orientation.player, everywhere: true, fromPlayer: true)
        withAnimation(.spring(duration: 0.3, bounce: 0.2)) { justUnlocked = true }
        Task {
            try? await Task.sleep(for: .seconds(1))
            withAnimation(.easeOut(duration: 0.5)) { justUnlocked = false }
        }
    }

    /// Leave the player. `keepPlaying` hands the film to the Picture in Picture window.
    /// Black out and ask for portrait before dismissing, so the rotation happens behind black.
    /// The cover has a clear background (see RootView), so fading the player reveals the page.
    private func close(keepPlaying: Bool = false) {
        guard !exiting else { return }
        if inline {
            if !keepPlaying {
                model.player.pause()
                model.stop()
            }
            hideTask?.cancel()
            onStop?()
            return
        }
        exiting = true
        if !keepPlaying { model.player.pause() }
        hideTask?.cancel()
        lockTask?.cancel()
        withAnimation(.easeOut(duration: 0.15)) { chromeVisible = false }
        let turning = UIDevice.current.userInterfaceIdiom == .phone && isLandscape
        // Stop counting now: a turn in the moment before it is gone must not rotate the app.
        if counted {
            counted = false
            Orientation.playerLeft()
        } else {
            Orientation.release()
        }
        Task {
            if turning {
                if !keepPlaying { model.stop() }
                withAnimation(.easeOut(duration: 0.12)) { closing = true }
                try? await Task.sleep(for: .milliseconds(340))
            }
            withAnimation(.easeOut(duration: 0.28)) { presence = 0 }
            try? await Task.sleep(for: .milliseconds(290))
            if !keepPlaying { model.stop() }
            var quietly = Transaction()
            quietly.disablesAnimations = true
            withTransaction(quietly) { dismiss() }
        }
    }

    private func handBack() {
        guard let onUpright, !handingBack, !exiting else { return }
        handingBack = true
        hideTask?.cancel()
        onUpright(model, request)
    }

    private var choices: TrackChoices { TrackChoices(model: model, state: state) }

    private func preview(_ episode: EpisodeItem) {
        guard let mediaID else { return }
        Task {
            if previewShow?.mediaID != mediaID {
                previewShow = try? await APIClient.shared.media(mediaID)
            }
            guard previewShow != nil else { return }
            if model.isPlaying { model.togglePlay() }
            covered = true
            previewing = episode
        }
    }

    private func leave(for card: Card) {
        leavingFor = card
        close()
    }

    // The window turns regardless of how the phone is held, and the hold lasts only until
    // the phone is turned to match; after that it follows the phone again.
    private func turn(to mask: UIInterfaceOrientationMask) {
        guard !exiting else { return }
        UIDevice.current.beginGeneratingDeviceOrientationNotifications()
        turnedTo = mask
        Orientation.lock(mask, fromPlayer: true)
        settleTurn()
    }

    private func settleTurn() {
        guard let turnedTo, !locked, !exiting else { return }
        let device = UIDevice.current.orientation
        let matches = turnedTo == .portrait ? device == .portrait : device.isLandscape
        guard matches else { return }
        self.turnedTo = nil
        Orientation.lock(Orientation.player, fromPlayer: true)
    }

    private var isLandscape: Bool {
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        return scene?.effectiveGeometry.interfaceOrientation.isLandscape ?? false
    }

    private func toggleChrome() {
        if chromeVisible { withAnimation(.easeOut(duration: 0.2)) { chromeVisible = false } }
        else { showChrome() }
    }

    private func handOff(to device: CastDevice) {
        model.saveProgress()
        let at = model.current
        Task {
            if await Cast.shared.play(request, at: at, on: device, profile: state.profile?.id) {
                close()
            }
        }
    }

    private func obey(_ command: CastCommand) {
        model.trace.mark("remote command \(command.type), active \(active)")
        // The page's picture while the whole screen has it: that one obeys.
        guard active else { return }
        switch command.type {
        case "pause": if model.isPlaying { model.togglePlay() }
        case "resume": if !model.isPlaying { model.togglePlay() }
        case "seek": if let at = command.position { model.trace.mark("remote seek"); model.seek(to: at) }
        case "skip": if let by = command.delta { model.skip(by) }
        case "stop": close()
        case "subtitle":
            choices.chooseSubtitle(command.subtitleID == "off" ? nil : command.subtitleID)
        case "audio": if let index = command.audioIndex { choices.chooseAudio(index) }
        case "appearance":
            choices.setLook(command.subtitleSize.flatMap(SubtitleSize.init(rawValue:)),
                            command.subtitleStyle.flatMap(SubtitleStyle.init(rawValue:)))
        default: break
        }
        showChrome()
    }

    private var boxed: Bool { (settingsOpen || episodesOpen) && !upright }

    private static let sampleCaption = "This is how subtitles will look."

    private func box(in size: CGSize) -> CGSize {
        let width = min(size.width * 0.58, (size.height - 36) * 16 / 9)
        return CGSize(width: width.rounded(), height: (width * 9 / 16).rounded())
    }

    private func openSettings() {
        withAnimation(.spring(duration: 0.42, bounce: 0.15)) {
            tray = nil
            episodesOpen = false
            settingsOpen = true
        }
    }

    private func closeSettings() {
        withAnimation(.spring(duration: 0.42, bounce: 0.15)) { settingsOpen = false }
        showChrome()
    }

    private func toggle(_ which: Tray) {
        withAnimation(.snappy(duration: 0.22)) { tray = tray == which ? nil : which }
        showChrome()
    }

    private func showChrome() {
        withAnimation(.easeOut(duration: 0.2)) { chromeVisible = true }
        hideTask?.cancel()
        hideTask = Task {
            try? await Task.sleep(for: .seconds(4))
            guard !Task.isCancelled, !scrubbing, !episodesOpen, !clipping, tray == nil else { return }
            withAnimation(.easeOut(duration: 0.25)) { chromeVisible = false }
        }
    }
}

private struct SlideToUnlock: View {
    var open: Bool
    var onOpen: () -> Void
    var onUnlock: () -> Void
    var onTouch: (Bool) -> Void

    @State private var offset: CGFloat = 0
    /// Its own state, changed in an animation, so the padlock morphs open rather than swapping symbols.
    @State private var shackleOpen = false
    private let width: CGFloat = 250
    private let knob: CGFloat = 48
    private let inset: CGFloat = 4
    private var travel: CGFloat { width - knob - inset * 2 }

    var body: some View {
        ZStack(alignment: .leading) {
            if open {
                Text("Slide to unlock")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.white.opacity(0.85))
                    .lineLimit(1)
                    .fixedSize()
                    .frame(maxWidth: .infinity)
                    .padding(.leading, knob * 0.6)
                    .opacity(1 - Double(offset / travel) * 1.6)
                    .transition(.opacity)
            }

            Circle()
                .fill(.white)
                .frame(width: knob, height: knob)
                .overlay(
                    Image(systemName: shackleOpen ? "lock.open.fill" : "lock.fill")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(.black)
                        .contentTransition(.symbolEffect(.replace.magic(fallback: .replace)))
                        // The open symbol is wider (22 pt vs 16); leading alignment keeps the body still while the shackle swings.
                        .frame(width: 22, height: 19, alignment: .leading)
                        .offset(x: 3)
                )
                .offset(x: inset + offset)
                .onTapGesture { if !open { onOpen() } }
                .gesture(
                    DragGesture(minimumDistance: open ? 0 : 10_000)
                        .onChanged { value in
                            onTouch(true)
                            offset = min(max(0, value.translation.width), travel)
                        }
                        .onEnded { _ in
                            if offset > travel * 0.85 {
                                withAnimation(.easeOut(duration: 0.12)) { offset = travel }
                                withAnimation(.snappy(duration: 0.25)) { shackleOpen = true }
                                Task {
                                    try? await Task.sleep(for: .milliseconds(280))
                                    onUnlock()
                                }
                            } else {
                                withAnimation(.spring(duration: 0.35, bounce: 0.25)) { offset = 0 }
                                onTouch(false)
                            }
                        }
                )
        }
        .frame(width: open ? width : knob + inset * 2, height: knob + inset * 2)
        .background {
            if open {
                Capsule().fill(.clear).glassEffect(.regular, in: .capsule)
                    .transition(.opacity)
            }
        }
        .onChange(of: offset > travel * 0.85) { _, past in
            withAnimation(.snappy(duration: 0.25)) { shackleOpen = past }
        }
        .sensoryFeedback(.impact(weight: .medium), trigger: shackleOpen) { _, now in now }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Screen locked")
        .accessibilityAction(named: "Unlock") { onUnlock() }
        .accessibilityAddTraits(open ? [] : .isButton)
    }
}

enum Screen {
    static var brightness: CGFloat {
        get { current?.brightness ?? 0.5 }
        set { current?.brightness = min(1, max(0, newValue)) }
    }

    private static var current: UIScreen? {
        UIApplication.shared.connectedScenes.compactMap { ($0 as? UIWindowScene)?.screen }.first
    }
}

private struct TrayCard<Content: View>: View {
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .padding(.horizontal, 22)
            .padding(.vertical, 16)
            .frame(maxWidth: 380)
            .glassEffect(.regular.tint(.black.opacity(0.35)), in: .rect(cornerRadius: 22))
            .foregroundStyle(.white)
    }
}

private struct SpeedTray: View {
    let model: PlayerModel
    var onTouch: () -> Void

    private let stops: [Float] = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

    var body: some View {
        TrayCard {
            VStack(alignment: .leading, spacing: 14) {
                Text("Playback Speed")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.white.opacity(0.7))
                GeometryReader { geo in
                    let step = geo.size.width / CGFloat(stops.count - 1)
                    ZStack(alignment: .leading) {
                        Capsule().fill(.white.opacity(0.25)).frame(height: 2)
                        ForEach(Array(stops.enumerated()), id: \.offset) { index, stop in
                            let chosen = model.rate == stop
                            Circle()
                                .fill(.white.opacity(chosen ? 1 : 0.55))
                                .frame(width: chosen ? 20 : 8, height: chosen ? 20 : 8)
                                .position(x: CGFloat(index) * step, y: geo.size.height / 2)
                                .animation(.snappy(duration: 0.2), value: chosen)
                        }
                    }
                    .contentShape(.rect)
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .onChanged { value in
                                let index = Int((value.location.x / step).rounded())
                                let stop = stops[min(max(index, 0), stops.count - 1)]
                                if stop != model.rate { model.setRate(stop) }
                                onTouch()
                            }
                    )
                }
                .frame(height: 24)
                .padding(.horizontal, 10)
                HStack(spacing: 0) {
                    ForEach(Array(stops.enumerated()), id: \.offset) { index, stop in
                        Text(label(stop))
                            .font(.caption.weight(model.rate == stop ? .bold : .regular))
                            .foregroundStyle(.white.opacity(model.rate == stop ? 1 : 0.6))
                            .frame(maxWidth: .infinity)
                    }
                }
                .padding(.horizontal, -12)
            }
        }
        .sensoryFeedback(.selection, trigger: model.rate)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Playback speed")
        .accessibilityValue(label(model.rate))
        .accessibilityAdjustableAction { direction in
            guard let at = stops.firstIndex(of: model.rate) else { return }
            switch direction {
            case .increment: if at + 1 < stops.count { model.setRate(stops[at + 1]) }
            case .decrement: if at > 0 { model.setRate(stops[at - 1]) }
            default: break
            }
        }
    }

    private func label(_ stop: Float) -> String {
        stop == 1 ? "1x" : String(format: "%gx", stop)
    }
}

private struct BrightnessTray: View {
    var onTouch: () -> Void

    @State private var level: CGFloat = Screen.brightness

    var body: some View {
        TrayCard {
            HStack(spacing: 14) {
                Image(systemName: "sun.min.fill").font(.system(size: 14))
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Capsule().fill(.white.opacity(0.25))
                        Capsule().fill(.white).frame(width: geo.size.width * level)
                    }
                    .frame(height: 6)
                    .frame(maxHeight: .infinity)
                    .contentShape(.rect)
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .onChanged { value in
                                level = min(1, max(0, value.location.x / geo.size.width))
                                Screen.brightness = level
                                onTouch()
                            }
                    )
                }
                .frame(height: 30)
                Image(systemName: "sun.max.fill").font(.system(size: 18))
            }
        }
        .onAppear { level = Screen.brightness }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Brightness")
        .accessibilityValue("\(Int(level * 100)) percent")
        .accessibilityAdjustableAction { direction in
            switch direction {
            case .increment: level = min(1, level + 0.1)
            case .decrement: level = max(0, level - 0.1)
            default: break
            }
            Screen.brightness = level
        }
    }
}
