import AVFoundation
import SwiftUI

// A clip's 9:16 version. The tall frame follows the server's crop path; drags and pinches
// add keyframes. Edits are stored on the server; export renders 1080x1920 on device.
struct VerticalEditor: View {
    let clip: Clip
    var orientationAfter: UIInterfaceOrientationMask = Orientation.base
    @Environment(\.dismiss) private var dismiss

    @State private var player = AVPlayer()
    @State private var vertical = ClipVertical(picture: nil, crop: nil, keyframes: [])
    @State private var aspect: Double = 16.0 / 9.0
    @State private var duration: Double = 0
    @State private var time: Double = 0
    @State private var playing = false
    @State private var loaded = false
    @State private var observer: Any?
    @State private var gestureFrom: VerticalWindow?
    @State private var wasPlaying = false
    @State private var saveTask: Task<Void, Never>?
    @State private var confirmingAuto = false
    @State private var exporting: Double?
    @State private var exported: URL?
    @State private var failure: String?

    private var path: VerticalPath { VerticalPath(vertical: vertical, aspect: aspect, duration: duration) }

    private var keyframeHere: Int? {
        vertical.keyframes.firstIndex { abs($0.t - time) < 0.2 }
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            GeometryReader { geo in
                let height = min(geo.size.height - 12, geo.size.width * 0.86 * 16 / 9)
                preview(height: height)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            status
                .padding(.top, 10)
            timeline
                .padding(.horizontal, 20)
                .padding(.top, 14)
            controls
                .padding(.horizontal, 20)
                .padding(.vertical, 14)
        }
        .foregroundStyle(.white)
        .background(Color.black.ignoresSafeArea())
        .overlay { if let exporting { exportProgress(exporting) } }
        .sheet(item: Binding(get: { exported.map(ExportedFile.init) },
                             set: { if $0 == nil { finishSharing() } })) { file in
            ShareSheet(items: [file.url])
                .presentationDetents([.medium, .large])
        }
        .alert("Back to automatic?", isPresented: $confirmingAuto) {
            Button("Cancel", role: .cancel) {}
            Button("Clear Keyframes", role: .destructive) { setKeyframes([]) }
        } message: {
            Text("Every keyframe placed by hand goes, and the frame follows the action on its own again.")
        }
        .preferredColorScheme(.dark)
        .statusBarHidden()
        .task { await load() }
        .task {
            // The server computes the path after a clip is saved; until then, poll.
            while !Task.isCancelled && vertical.crop == nil {
                try? await Task.sleep(for: .seconds(2))
                if let fresh = try? await APIClient.shared.clipVertical(clip.id), fresh.crop != nil {
                    vertical.crop = fresh.crop
                    vertical.picture = fresh.picture
                }
            }
        }
        .onAppear { Orientation.lock(.portrait) }
        .onDisappear {
            if let observer { player.removeTimeObserver(observer) }
            player.pause()
            saveTask?.cancel()
            Orientation.lock(orientationAfter, everywhere: false)
        }
    }

    private var header: some View {
        HStack {
            Button { dismiss() } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 18, weight: .bold))
                    .frame(width: 44, height: 44)
                    .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Close")
            Spacer()
            Text("Vertical").font(.headline)
            Spacer()
            Button { export() } label: {
                Text("Export")
                    .font(.headline)
                    .foregroundStyle(.black)
                    .padding(.horizontal, 16)
                    .frame(height: 34)
                    .background(Capsule().fill(.white))
            }
            .buttonStyle(.plain)
            .disabled(!loaded || exporting != nil)
        }
        .padding(.horizontal, 12)
        .padding(.top, 6)
    }

    // The wide frame scaled so the tall window fills the preview, re-read every frame while playing.
    private func preview(height: CGFloat) -> some View {
        let width = height * VerticalPath.tall
        return TimelineView(.animation(minimumInterval: nil, paused: !playing)) { _ in
            let window = path.window(at: playing ? currentTime : time)
            let fullHeight = height / window.height
            let fullWidth = fullHeight * aspect
            PlayerSurface(player: player, filling: false)
                .frame(width: fullWidth, height: fullHeight)
                .offset(x: (0.5 - window.x) * fullWidth, y: (0.5 - window.y) * fullHeight)
                .frame(width: width, height: height)
                .clipped()
        }
        .frame(width: width, height: height)
        .background(Color(white: 0.06))
        .clipShape(.rect(cornerRadius: 14))
        .overlay {
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(.white.opacity(gestureFrom == nil ? 0.12 : 0.6), lineWidth: 1)
        }
        .overlay { if !loaded { BootSpinner(size: 36, line: 3) } }
        .contentShape(.rect)
        .gesture(drag(height: height))
        .simultaneousGesture(pinch)
        .onTapGesture { togglePlay() }
    }

    private var currentTime: Double {
        let now = player.currentTime().seconds
        return now.isFinite ? now : time
    }

    private func drag(height: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 4)
            .onChanged { value in
                let from = beginGesture()
                let fullHeight = height / from.height
                let fullWidth = fullHeight * aspect
                let moved = path.place(x: from.x - value.translation.width / fullWidth,
                                       y: from.y - value.translation.height / fullHeight,
                                       zoom: from.zoom)
                placeKeyframe(moved)
            }
            .onEnded { _ in endGesture() }
    }

    private var pinch: some Gesture {
        MagnifyGesture(minimumScaleDelta: 0.01)
            .onChanged { value in
                let from = beginGesture()
                placeKeyframe(path.place(x: from.x, y: from.y, zoom: from.zoom * value.magnification))
            }
            .onEnded { _ in endGesture() }
    }

    private func beginGesture() -> VerticalWindow {
        if let gestureFrom { return gestureFrom }
        wasPlaying = playing
        if playing { pause() }
        let from = path.window(at: time)
        gestureFrom = from
        return from
    }

    private func endGesture() {
        gestureFrom = nil
        scheduleSave()
    }

    private var status: some View {
        Group {
            if vertical.crop == nil && loaded {
                Label("Finding the action…", systemImage: "sparkle.magnifyingglass")
            } else if let failure {
                Text(failure).foregroundStyle(Palette.accent)
            } else if vertical.keyframes.isEmpty {
                Text("Following the action automatically. Drag to reframe, pinch to zoom.")
            } else {
                Text(vertical.keyframes.count == 1 ? "1 keyframe" : "\(vertical.keyframes.count) keyframes")
            }
        }
        .font(.footnote)
        .foregroundStyle(Palette.dim)
        .multilineTextAlignment(.center)
        .padding(.horizontal, 24)
        .frame(height: 34)
    }

    private var timeline: some View {
        GeometryReader { geo in
            let width = geo.size.width
            let span = max(duration, 0.1)
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 6).fill(Color.white.opacity(0.1))
                    .frame(height: 36)
                ForEach(path.cuts, id: \.self) { cut in
                    Rectangle().fill(.white.opacity(0.35))
                        .frame(width: 1.5, height: 20)
                        .offset(x: width * cut / span)
                }
                ForEach(Array(vertical.keyframes.enumerated()), id: \.offset) { index, keyframe in
                    Circle()
                        .fill(index == keyframeHere ? .white : Palette.accent)
                        .frame(width: 12, height: 12)
                        .offset(x: width * keyframe.t / span - 6)
                        .onTapGesture { seek(to: keyframe.t) }
                }
                Capsule().fill(.white)
                    .frame(width: 3, height: 48)
                    .offset(x: width * min(1, time / span) - 1.5)
                    .allowsHitTesting(false)
            }
            .frame(height: 48)
            .contentShape(.rect)
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        if playing { pause() }
                        seek(to: min(max(0, value.location.x / width), 1) * span)
                    }
            )
        }
        .frame(height: 48)
    }

    private var controls: some View {
        HStack(spacing: 18) {
            Button { togglePlay() } label: {
                Image(systemName: playing ? "pause.fill" : "play.fill")
                    .font(.system(size: 22))
                    .frame(width: 44, height: 44)
                    .contentTransition(.symbolEffect(.replace))
            }
            .accessibilityLabel(playing ? "Pause" : "Play")
            Text("\(clock(time)) / \(clock(duration))")
                .font(.footnote.monospacedDigit())
                .foregroundStyle(Palette.dim)
            Spacer()
            if let index = keyframeHere {
                Button {
                    var keyframes = vertical.keyframes
                    keyframes.remove(at: index)
                    setKeyframes(keyframes)
                } label: {
                    tool("Remove", systemImage: "diamond.slash")
                }
                .accessibilityLabel("Remove keyframe")
            }
            Button { confirmingAuto = true } label: {
                tool("Automatic", systemImage: "wand.and.sparkles")
            }
            .disabled(vertical.keyframes.isEmpty)
            .opacity(vertical.keyframes.isEmpty ? 0.4 : 1)
        }
        .buttonStyle(.plain)
    }

    private func tool(_ title: String, systemImage: String) -> some View {
        VStack(spacing: 4) {
            Image(systemName: systemImage).font(.system(size: 19))
            Text(title).font(.caption2.weight(.semibold)).lineLimit(1).fixedSize()
        }
        .frame(minWidth: 56, minHeight: 44)
        .contentShape(.rect)
    }

    private func exportProgress(_ done: Double) -> some View {
        ZStack {
            Color.black.opacity(0.7).ignoresSafeArea()
            VStack(spacing: 14) {
                DownloadRing(percent: done * 100, size: 56)
                Text("Making the vertical video… \(Int(done * 100))%")
                    .font(.subheadline.weight(.semibold))
            }
        }
    }

    private func export() {
        failure = nil
        exporting = 0
        pause()
        let path = self.path
        Task {
            do {
                exported = try await VerticalExport.make(clip: clip, path: path) { exporting = $0 }
            } catch {
                failure = "Couldn't make the video: \(error.localizedDescription)"
            }
            exporting = nil
        }
    }

    private func finishSharing() {
        if let exported { try? FileManager.default.removeItem(at: exported) }
        exported = nil
    }

    private func load() async {
        if let url = try? await APIClient.shared.url(for: clip.video) {
            let item = AVPlayerItem(url: url)
            // .none: stopping at the end leaves it paused after the jump back.
            player.actionAtItemEnd = .none
            player.replaceCurrentItem(with: item)
            let asset = item.asset
            if let track = try? await asset.loadTracks(withMediaType: .video).first,
               let (size, transform) = try? await track.load(.naturalSize, .preferredTransform) {
                let shown = size.applying(transform)
                if abs(shown.height) > 0 { aspect = abs(shown.width / shown.height) }
            }
            if let length = try? await asset.load(.duration).seconds, length.isFinite {
                duration = length
            }
            observer = player.addPeriodicTimeObserver(
                forInterval: CMTime(seconds: 0.1, preferredTimescale: 600), queue: .main
            ) { now in
                MainActor.assumeIsolated {
                    guard gestureFrom == nil else { return }
                    time = now.seconds.isFinite ? now.seconds : time
                    if duration > 0 && time >= duration - 0.08 && playing {
                        player.seek(to: .zero, toleranceBefore: .zero, toleranceAfter: .zero) { _ in
                            Task { @MainActor in if playing { player.play() } }
                        }
                    }
                }
            }
        }
        if let fresh = try? await APIClient.shared.clipVertical(clip.id) {
            vertical = fresh
            if let crop = fresh.crop { aspect = crop.aspect }
        }
        if duration == 0 { duration = clip.duration }
        loaded = true
        player.play()
        playing = true
        #if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        // -verticalNudge: a local-only keyframe two seconds in (never sent).
        if arguments.contains("-verticalNudge") {
            vertical.keyframes = [.init(t: 2, x: 0.25, y: 0.45, zoom: 1.5)]
            seek(to: 2)
            pause()
        }
        // -verticalExport: export and leave a copy in Documents.
        if arguments.contains("-verticalExport") {
            let path = self.path
            if let made = try? await VerticalExport.make(clip: clip, path: path, progress: { _ in }) {
                let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
                let copy = documents.appending(path: "vertical-test.mp4")
                try? FileManager.default.removeItem(at: copy)
                try? FileManager.default.copyItem(at: made, to: copy)
            }
        }
        #endif
    }

    private func togglePlay() {
        if playing { pause() } else { player.play(); playing = true }
    }

    private func pause() {
        player.pause()
        playing = false
        time = currentTime
    }

    private func seek(to seconds: Double) {
        time = seconds
        player.seek(to: CMTime(seconds: seconds, preferredTimescale: 600),
                    toleranceBefore: .zero, toleranceAfter: .zero)
    }

    private func placeKeyframe(_ window: VerticalWindow) {
        let keyframe = ClipVertical.Keyframe(t: time, x: window.x, y: window.y, zoom: window.zoom)
        if let index = keyframeHere {
            vertical.keyframes[index] = ClipVertical.Keyframe(t: vertical.keyframes[index].t,
                                                              x: window.x, y: window.y, zoom: window.zoom)
        } else {
            vertical.keyframes.append(keyframe)
            vertical.keyframes.sort { $0.t < $1.t }
        }
    }

    private func setKeyframes(_ keyframes: [ClipVertical.Keyframe]) {
        withAnimation(.snappy) { vertical.keyframes = keyframes }
        scheduleSave()
    }

    private func scheduleSave() {
        saveTask?.cancel()
        let keyframes = vertical.keyframes
        saveTask = Task {
            try? await Task.sleep(for: .milliseconds(500))
            guard !Task.isCancelled else { return }
            do {
                try await APIClient.shared.saveClipVertical(clip.id, keyframes: keyframes)
            } catch {
                failure = "Couldn't keep the change: \(error.localizedDescription)"
            }
        }
    }

    private func clock(_ seconds: Double) -> String {
        let s = Int(max(0, seconds).rounded(.down))
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}

private struct ExportedFile: Identifiable {
    let url: URL
    var id: URL { url }
}
