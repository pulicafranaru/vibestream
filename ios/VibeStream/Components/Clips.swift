import AVKit
import SwiftUI

struct ClipCard: View {
    let clip: Clip
    let width: CGFloat
    @State private var thumb: URL?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            RemoteImage(url: thumb)
                .frame(width: width, height: width * 9 / 16)
                .clipped()
                .background(Color.black)
                .overlay(alignment: .bottomTrailing) {
                    Text(Self.length(clip.duration))
                        .font(.caption.weight(.semibold).monospacedDigit())
                        .padding(.horizontal, 6).padding(.vertical, 3)
                        .background(Capsule().fill(.black.opacity(0.7)))
                        .padding(6)
                }
                .overlay {
                    Image(systemName: "play.fill")
                        .font(.system(size: 16))
                        .frame(width: 38, height: 38)
                        .background(Circle().fill(.black.opacity(0.45)))
                        .overlay(Circle().strokeBorder(.white.opacity(0.85), lineWidth: 1.5))
                }
                .clipShape(.rect(cornerRadius: 6))
            Text(clip.title).font(.subheadline.weight(.semibold)).lineLimit(1)
            if let subtitle = clip.subtitle {
                Text(subtitle).font(.caption).foregroundStyle(Palette.dim).lineLimit(1)
            }
        }
        .frame(width: width, alignment: .leading)
        .foregroundStyle(.white)
        .contentShape(.rect)
        .task { thumb = try? await APIClient.shared.url(for: clip.thumb) }
    }

    static func length(_ seconds: Double) -> String {
        let total = Int(seconds.rounded())
        return String(format: "%d:%02d", total / 60, total % 60)
    }
}

// No audio or subtitle choice: clips are cut with one audio track and no subtitles.
struct ClipPlayer: View {
    let clip: Clip
    var onOpen: ((Card) -> Void)?
    @Environment(\.dismiss) private var dismiss

    @State private var player: AVPlayer?
    @State private var current: Double = 0
    @State private var playing = false
    @State private var observer: Any?
    @State private var chrome = true
    @State private var hide: Task<Void, Never>?
    @State private var scrubbing = false
    @State private var target: Double = 0
    @State private var brightness: CGFloat = ClipPlayer.screen?.brightness ?? 0.5
    @State private var framing = false

    /// The file's real length, which the countdown has to reach 0:00 with.
    @State private var measured: Double?
    private var duration: Double { max(measured ?? clip.duration, 0.1) }
    private var shown: Double { scrubbing ? target : current }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            PlayerSurface(player: player, filling: false).ignoresSafeArea()
            if player == nil {
                BootSpinner()
            }
            if chrome {
                controls.transition(.opacity)
            }
        }
        .foregroundStyle(.white)
        .contentShape(.rect)
        .onTapGesture {
            withAnimation(.easeInOut(duration: 0.2)) { chrome.toggle() }
            if chrome { later() }
        }
        .statusBarHidden()
        .persistentSystemOverlays(.hidden)
        .fullScreenCover(isPresented: $framing) {
            VerticalEditor(clip: clip)
        }
        .task { await start() }
        #if DEBUG
        // -clipOpen: follow the link to the title, as a tap on it would.
        .task {
            guard ProcessInfo.processInfo.arguments.contains("-clipOpen") else { return }
            try? await Task.sleep(for: .seconds(3))
            openSource()
        }
        #endif
        .onDisappear {
            hide?.cancel()
            if let observer { player?.removeTimeObserver(observer) }
            player?.pause()
        }
    }

    private var controls: some View {
        ZStack {
            LinearGradient(colors: [.black.opacity(0.65), .clear, .black.opacity(0.8)],
                           startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
                .allowsHitTesting(false)
            VStack(spacing: 0) {
                top
                Spacer()
                centre
                Spacer()
                bottom
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
            HStack {
                BrightnessSlider(value: $brightness) { later() }
                Spacer()
            }
            .padding(.leading, 14)
        }
    }

    private var top: some View {
        HStack(alignment: .top) {
            Button(action: openSource) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Starts at \(ClipCard.length(clip.start))")
                        .font(.headline)
                    HStack(spacing: 4) {
                        Text(clip.subtitle ?? clip.title).lineLimit(1)
                        Image(systemName: "chevron.right").font(.footnote.weight(.semibold))
                    }
                    .font(.subheadline)
                    .foregroundStyle(.white.opacity(0.75))
                }
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .disabled(clip.mediaID == nil || onOpen == nil)
            .accessibilityHint("Opens \(clip.title)")
            Spacer()
            Button {
                player?.pause()
                playing = false
                framing = true
            } label: {
                Image(systemName: "rectangle.portrait")
                    .font(.system(size: 20, weight: .regular))
                    .frame(width: 44, height: 44)
                    .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Make Vertical")
            Button { dismiss() } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 22, weight: .regular))
                    .frame(width: 44, height: 44)
                    .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Close")
        }
    }

    private var centre: some View {
        HStack(spacing: 0) {
            Spacer()
            Button { skip(-10) } label: {
                Image(systemName: "gobackward.10").font(.system(size: 34))
            }
            Spacer()
            Button { toggle() } label: {
                Image(systemName: playing ? "pause.fill" : "play.fill")
                    .font(.system(size: 46))
                    .contentTransition(.symbolEffect(.replace))
            }
            Spacer()
            Button { skip(10) } label: {
                Image(systemName: "goforward.10").font(.system(size: 34))
            }
            Spacer()
        }
        .buttonStyle(.plain)
    }

    private var bottom: some View {
        HStack(spacing: 14) {
            GeometryReader { geo in
                let width = geo.size.width
                let fraction = min(1, max(0, shown / duration))
                ZStack(alignment: .leading) {
                    Capsule().fill(.white.opacity(0.3)).frame(height: 4)
                    Capsule().fill(Palette.accent).frame(width: width * fraction, height: 4)
                    Circle()
                        .fill(Palette.accent)
                        .frame(width: scrubbing ? 18 : 13, height: scrubbing ? 18 : 13)
                        .offset(x: width * fraction - (scrubbing ? 9 : 6.5))
                }
                .frame(height: 26)
                .contentShape(.rect)
                .gesture(DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        scrubbing = true
                        target = min(1, max(0, value.location.x / width)) * duration
                        hide?.cancel()
                    }
                    .onEnded { _ in
                        seek(to: target)
                        scrubbing = false
                        later()
                    })
                .animation(.easeOut(duration: 0.12), value: scrubbing)
            }
            .frame(height: 26)
            Text(ClipCard.length(max(0, duration - shown)))
                .font(.footnote.monospacedDigit())
        }
    }

    private func start() async {
        guard let url = try? await APIClient.shared.url(for: clip.video) else { return }
        let player = AVPlayer(url: url)
        observer = player.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.25, preferredTimescale: 600), queue: .main
        ) { time in
            MainActor.assumeIsolated {
                if !scrubbing { current = time.seconds.isFinite ? time.seconds : 0 }
                if let length = player.currentItem?.duration.seconds, length.isFinite, length > 0 {
                    measured = length
                }
                playing = player.timeControlStatus != .paused
            }
        }
        self.player = player
        player.play()
        playing = true
        later()
    }

    private func toggle() {
        guard let player else { return }
        if playing {
            player.pause()
            playing = false
            hide?.cancel()
        } else {
            if current >= duration - 0.3 { seek(to: 0) }
            player.play()
            playing = true
            later()
        }
    }

    private func skip(_ seconds: Double) {
        seek(to: min(max(0, current + seconds), duration))
        later()
    }

    private func seek(to seconds: Double) {
        current = seconds
        player?.seek(to: CMTime(seconds: seconds, preferredTimescale: 600),
                     toleranceBefore: .zero, toleranceAfter: .zero)
    }

    private func later() {
        hide?.cancel()
        hide = Task {
            try? await Task.sleep(for: .seconds(4))
            guard !Task.isCancelled, playing, !scrubbing else { return }
            withAnimation(.easeInOut(duration: 0.3)) { chrome = false }
        }
    }

    private func openSource() {
        guard let id = clip.mediaID else { return }
        Task {
            guard let card = try? await APIClient.shared.media(id) else { return }
            dismiss()
            try? await Task.sleep(for: .milliseconds(350))
            onOpen?(card)
        }
    }

    fileprivate static var screen: UIScreen? {
        UIApplication.shared.connectedScenes.compactMap { ($0 as? UIWindowScene)?.screen }.first
    }
}

private struct BrightnessSlider: View {
    @Binding var value: CGFloat
    var onChange: () -> Void

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "sun.max").font(.system(size: 18))
            GeometryReader { geo in
                let height = geo.size.height
                ZStack(alignment: .bottom) {
                    Capsule().fill(.white.opacity(0.3))
                    Capsule().fill(.white).frame(height: height * value)
                }
                .frame(width: 5)
                .frame(maxWidth: .infinity)
                .contentShape(.rect)
                .gesture(DragGesture(minimumDistance: 0).onChanged { drag in
                    value = min(1, max(0, 1 - drag.location.y / height))
                    ClipPlayer.screen?.brightness = value
                    onChange()
                })
            }
            .frame(width: 36, height: 260)
        }
        .accessibilityElement()
        .accessibilityLabel("Brightness")
        .accessibilityValue("\(Int(value * 100)) percent")
        .accessibilityAdjustableAction { direction in
            value = min(1, max(0, value + (direction == .increment ? 0.1 : -0.1)))
            ClipPlayer.screen?.brightness = value
        }
    }
}
