import SwiftUI

// Clips run from 2 s to 2 min; pushing a handle past 2 min drags the other end along.
// The preview is a second layer on the same AVPlayer, looped by seeking.
struct ClipEditor: View {
    let model: PlayerModel
    let playID: String
    let onClose: () -> Void
    @Environment(AppState.self) private var state

    static let longest: Double = 120
    static let shortest: Double = 2
    private static let span: Double = 130
    /// How close to an edge of the strip the clip may come before it scrolls.
    private static let margin: Double = 4

    @State private var start: Double
    @State private var end: Double
    @State private var windowStart: Double
    @State private var windowEnd: Double
    @State private var thumbs: [Int: ThumbFrame] = [:]
    @State private var coast: Task<Void, Never>?
    @State private var previewing = true
    @State private var saving = false
    @State private var saved = false
    @State private var failure: String?
    @State private var dragFrom: (start: Double, end: Double, window: Double)?
    @State private var grip: Grip?
    /// How far the drag has gone, and how much the film has rolled on its
    /// own while a handle was held at an edge, both in seconds.
    @State private var travelled: Double = 0
    @State private var rolled: Double = 0
    @State private var rolling = 0
    @State private var upright = false

    init(model: PlayerModel, playID: String, onClose: @escaping () -> Void) {
        self.model = model
        self.playID = playID
        self.onClose = onClose
        let duration = max(model.duration, 1)
        // Thirty seconds ending where the viewer was: the moment that made
        // them reach for the button has usually just happened.
        let end = min(duration, max(model.current, min(duration, 30)))
        let start = max(0, end - 30)
        let windowStart = max(0, min(start - Self.margin, duration - Self.span))
        _start = State(initialValue: start)
        _end = State(initialValue: end)
        _windowStart = State(initialValue: windowStart)
        _windowEnd = State(initialValue: min(duration, windowStart + Self.span))
    }

    var body: some View {
        ZStack {
            LinearGradient(colors: [.black, Color(white: 0.09)], startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
            VStack(spacing: 0) {
                header
                Spacer(minLength: 20)
                if upright {
                    VStack(spacing: 22) {
                        preview
                        HStack {
                            bound("Start", start, Color(red: 0.18, green: 0.75, blue: 0.43))
                            Spacer()
                            bound("End", end, Palette.accent)
                        }
                        .padding(.horizontal, 8)
                    }
                    .padding(.horizontal, 16)
                } else {
                    HStack(spacing: 28) {
                        bound("Start", start, Color(red: 0.18, green: 0.75, blue: 0.43))
                        preview
                        bound("End", end, Palette.accent)
                    }
                    .padding(.horizontal, 24)
                }
                Spacer(minLength: 20)
                timeline
                    .padding(.horizontal, 16)
                    .padding(.bottom, 24)
            }
            if saved {
                Label("Saved to Library", systemImage: "checkmark.circle.fill")
                    .font(.headline)
                    .padding(.horizontal, 22).padding(.vertical, 14)
                    .background(Capsule().fill(Color(white: 0.16)))
                    .transition(.scale.combined(with: .opacity))
            }
        }
        .foregroundStyle(.white)
        .contentShape(.rect)
        .onTapGesture {}
        .onGeometryChange(for: Bool.self) { $0.size.height > $0.size.width } action: { upright = $0 }
        .task {
            model.seek(to: start)
            if !model.isPlaying { model.togglePlay() }
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(150))
                if previewing && (model.current >= end || model.current < start - 1) {
                    model.seek(to: start)
                }
            }
        }
        .task(id: firstCell) { await loadThumbs() }
        #if DEBUG
        // -clipSlide: push the end handle 150 s on.
        .task {
            guard ProcessInfo.processInfo.arguments.contains("-clipSlide") else { return }
            try? await Task.sleep(for: .seconds(3))
            moveEnd(to: end + 150)
            replay()
        }
        // -clipRoll: fling the film and let it coast.
        .task {
            guard ProcessInfo.processInfo.arguments.contains("-clipRoll") else { return }
            try? await Task.sleep(for: .seconds(3))
            begin(.film)
            fling(from: 0, speed: 60)
        }
        #endif
    }

    private var header: some View {
        ZStack {
            Text("Clip a Moment").font(.headline)
            HStack {
                Button(action: leave) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 22, weight: .medium))
                        .frame(width: 44, height: 44)
                        .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Back")
                Spacer()
                Button(action: save) {
                    Group {
                        if saving {
                            ProgressView().tint(.black)
                        } else {
                            Text("Save").font(.headline)
                        }
                    }
                    .foregroundStyle(.black)
                    .frame(minWidth: 70)
                    .padding(.horizontal, 16).padding(.vertical, 10)
                    .background(RoundedRectangle(cornerRadius: 6).fill(.white))
                }
                .buttonStyle(.plain)
                .disabled(saving || saved)
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .overlay(alignment: .bottom) {
            if let failure {
                Text(failure).font(.footnote).foregroundStyle(Palette.accent)
                    .offset(y: 26)
            }
        }
    }

    private func bound(_ label: String, _ seconds: Double, _ tint: Color) -> some View {
        VStack(spacing: 6) {
            Text(label).font(.headline).foregroundStyle(tint)
            Text(clock(seconds))
                .font(.system(size: upright ? 32 : 38, weight: .regular).monospacedDigit())
                .contentTransition(.numericText())
        }
        .frame(minWidth: 110)
    }

    private var preview: some View {
        PlayerSurface(player: model.player, filling: false)
            .aspectRatio(16 / 9, contentMode: .fit)
            .frame(maxWidth: 640)
            .background(Color.black)
            .clipShape(.rect(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.white.opacity(0.3), lineWidth: 1.5))
            .overlay(alignment: .bottom) {
                HStack {
                    Button { togglePreview() } label: {
                        Image(systemName: previewing ? "pause.fill" : "play.fill")
                            .font(.system(size: 22))
                            .frame(width: 44, height: 44)
                    }
                    Spacer()
                    Button { replay() } label: {
                        Image(systemName: "arrow.counterclockwise.circle")
                            .font(.system(size: 26))
                            .frame(width: 44, height: 44)
                    }
                    .accessibilityLabel("Play from the start")
                }
                .buttonStyle(.plain)
                .padding(10)
            }
    }

    private enum Grip { case start, end, film }

    // Seconds across the window map onto the strip's width, inset by a handle's width each side.
    private var timeline: some View {
        GeometryReader { geo in
            let handle: CGFloat = 36
            let width = max(1, geo.size.width - handle * 2)
            let span = max(1, windowEnd - windowStart)
            let x = { (t: Double) in handle + CGFloat((t - windowStart) / span) * width }
            let height: CGFloat = 64
            let seconds = { (dx: CGFloat) in Double(dx / width) * span }

            ZStack(alignment: .topLeading) {
                let cell = width * CGFloat(step / span)
                ZStack(alignment: .topLeading) {
                    ForEach(Array(firstCell..<lastCell), id: \.self) { index in
                        Group {
                            if let frame = thumbs[index] {
                                // Wide enough to fill the film's height, the
                                // sides cut off, rather than a band of picture.
                                SpriteFrame(frame: frame, width: max(cell + 1, height * 16 / 9))
                            } else {
                                Rectangle().fill(Color(white: 0.12))
                            }
                        }
                        .frame(width: cell + 1, height: height)
                        .clipped()
                        .offset(x: CGFloat((Double(index) * step - windowStart) / span) * width)
                    }
                }
                .frame(width: width, height: height, alignment: .topLeading)
                .background(Color(white: 0.12))
                .clipShape(.rect(cornerRadius: 4))
                .contentShape(.rect)
                .offset(x: handle, y: 30)
                .gesture(DragGesture(minimumDistance: 4).onChanged { value in
                    begin(.film)
                    travelled = -seconds(value.translation.width)
                    rollFilm(by: travelled)
                }.onEnded { value in
                    fling(from: travelled, speed: -seconds(value.velocity.width))
                })

                RoundedRectangle(cornerRadius: 10)
                    .strokeBorder(.white, lineWidth: 3)
                    .frame(width: max(handle * 2, x(end) - x(start) + handle * 2), height: height + 12)
                    .offset(x: x(start) - handle, y: 24)
                    .allowsHitTesting(false)

                let playhead = min(max(model.current, start), end)
                Text(clock(playhead))
                    .font(.footnote.weight(.semibold).monospacedDigit())
                    .fixedSize()
                    .position(x: x(playhead), y: 10)
                Capsule().fill(.white)
                    .frame(width: 4, height: height + 4)
                    .position(x: x(playhead), y: 30 + height / 2)
                    .allowsHitTesting(false)

                handleView(tint: Color(red: 0.18, green: 0.75, blue: 0.43), width: handle, height: height)
                    .position(x: x(start) - handle / 2, y: 30 + height / 2)
                    .gesture(handleDrag(.start, width: geo.size.width, seconds: seconds))
                    .accessibilityLabel("Start")

                handleView(tint: Palette.accent, width: handle, height: height)
                    .position(x: x(end) + handle / 2, y: 30 + height / 2)
                    .gesture(handleDrag(.end, width: geo.size.width, seconds: seconds))
                    .accessibilityLabel("End")
            }
            .coordinateSpace(.named("strip"))
        }
        .frame(height: 30 + 64 + 12)
        // While a handle is held at an edge, roll ten seconds of film per second.
        .task {
            let tick = 1.0 / 60
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(tick))
                guard rolling != 0, let grip else { continue }
                rolled += Double(rolling) * 10 * tick
                apply(grip)
            }
        }
    }

    private func handleDrag(_ which: Grip, width: CGFloat,
                            seconds: @escaping (CGFloat) -> Double) -> some Gesture {
        DragGesture(minimumDistance: 0, coordinateSpace: .named("strip"))
            .onChanged { value in
                begin(which)
                travelled = seconds(value.translation.width)
                let edge: CGFloat = 42
                rolling = value.location.x < edge ? -1 : value.location.x > width - edge ? 1 : 0
                apply(which)
            }
            .onEnded { _ in finish() }
    }

    private func handleView(tint: Color, width: CGFloat, height: CGFloat) -> some View {
        RoundedRectangle(cornerRadius: 8)
            .fill(tint)
            .frame(width: width, height: height + 12)
            .overlay {
                HStack(spacing: 2) {
                    Image(systemName: "arrowtriangle.left.fill")
                    Image(systemName: "arrowtriangle.right.fill")
                }
                .font(.system(size: 9))
            }
            .contentShape(.rect.inset(by: -10))
    }

    private func begin(_ which: Grip) {
        if coast != nil {
            coast?.cancel()
            coast = nil
            dragFrom = nil
        }
        guard dragFrom == nil else { return }
        dragFrom = (start, end, windowStart)
        grip = which
        travelled = 0
        rolled = 0
    }

    private func finish() {
        dragFrom = nil
        grip = nil
        rolling = 0
        replay()
    }

    private func apply(_ which: Grip) {
        guard let from = dragFrom else { return }
        switch which {
        case .start: moveStart(to: from.start + travelled + rolled)
        case .end: moveEnd(to: from.end + travelled + rolled)
        case .film: break
        }
    }

    /// Let go while moving: decelerate like a scroll view until it stops or hits an end.
    private func fling(from delta: Double, speed: Double) {
        guard abs(speed) > 4 else { finish(); return }
        coast = Task {
            let tick = 1.0 / 60
            var delta = delta, speed = speed
            while !Task.isCancelled && abs(speed) > 1 {
                try? await Task.sleep(for: .seconds(tick))
                if Task.isCancelled { return }
                let before = start
                delta += speed * tick
                rollFilm(by: delta)
                if start == before { break }
                speed *= 0.94
            }
            if Task.isCancelled { return }
            coast = nil
            finish()
        }
    }

    private func rollFilm(by delta: Double) {
        guard let from = dragFrom else { return }
        let length = from.end - from.start
        let newStart = min(max(0, from.start + delta), duration - length)
        start = newStart
        end = newStart + length
        let moved = newStart - from.start
        let window = max(0, min(from.window + moved, duration - Self.span))
        if window != windowStart {
            windowStart = window
            windowEnd = min(duration, window + Self.span)
        }
        hold(at: start)
    }

    private var duration: Double { max(model.duration, Self.shortest) }

    // Measured from the drag's own travel, not the finger's position, because the strip moves.
    private func moveStart(to wanted: Double) {
        let newStart = min(max(0, wanted), end - Self.shortest, duration - Self.shortest)
        start = newStart
        if end - start > Self.longest { end = start + Self.longest }
        follow()
        hold(at: start)
    }

    private func moveEnd(to wanted: Double) {
        let newEnd = max(min(duration, wanted), start + Self.shortest, Self.shortest)
        end = newEnd
        if end - start > Self.longest { start = end - Self.longest }
        follow()
        hold(at: max(start, end - 1))
    }

    private func follow() {
        var from = windowStart
        if end > windowEnd - Self.margin { from = end + Self.margin - Self.span }
        if start < from + Self.margin { from = start - Self.margin }
        from = max(0, min(from, duration - Self.span))
        if from != windowStart {
            windowStart = from
            windowEnd = min(duration, from + Self.span)
        }
    }

    private var step: Double { min(Self.span, duration) / 16 }
    private var firstCell: Int { Int((windowStart / step).rounded(.down)) }
    private var lastCell: Int { max(firstCell + 1, Int((windowEnd / step).rounded(.up))) }

    private func loadThumbs() async {
        let from = max(0, firstCell - 4)
        let to = min(Int((duration / step).rounded(.up)), lastCell + 4)
        guard from < to else { return }
        for index in from..<to where thumbs[index] == nil {
            if Task.isCancelled { return }
            if let frame = await model.thumbnail(at: (Double(index) + 0.5) * step) {
                thumbs[index] = frame
            }
        }
    }

    private func hold(at seconds: Double) {
        if model.isPlaying { model.togglePlay() }
        previewing = false
        model.seek(to: seconds)
    }

    private func replay() {
        model.seek(to: start)
        if !model.isPlaying { model.togglePlay() }
        previewing = true
    }

    private func togglePreview() {
        model.togglePlay()
        previewing = model.isPlaying
    }

    private func leave() {
        coast?.cancel()
        if model.isPlaying { model.togglePlay() }
        onClose()
    }

    private func save() {
        saving = true
        failure = nil
        Task {
            do {
                _ = try await state.saveClip(playID: playID, start: start, end: end)
                saving = false
                withAnimation(.spring(duration: 0.3)) { saved = true }
                try? await Task.sleep(for: .seconds(1.2))
                leave()
            } catch {
                saving = false
                failure = "Couldn't save the clip. Try again."
            }
        }
    }

    private func clock(_ seconds: Double) -> String {
        let total = Int(max(0, seconds).rounded(.down))
        let h = total / 3600, m = (total % 3600) / 60, s = total % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%d:%02d", m, s)
    }
}
