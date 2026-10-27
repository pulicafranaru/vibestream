import AVFoundation
import SwiftUI

// The launch intro, played from the bundle so it never waits on the network. A tap skips it.
struct IntroView: View {
    var onFinish: () -> Void

    @State private var fading = false
    @State private var finished = false
    // Created on appear: a property initialiser would make a new player on every redraw.
    @State private var player: AVPlayer?

    private var portrait: Bool { UIDevice.current.userInterfaceIdiom == .phone }

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            let width = min(size.height * 16 / 9, size.width * 1.8)
            ZStack {
                Color.black
                if let player, portrait {
                    PlayerLayerView(player: player)
                } else if let player {
                    PlayerLayerView(player: player)
                        .frame(width: max(width, size.width), height: max(width, size.width) * 9 / 16)
                }
            }
            .frame(width: size.width, height: size.height)
            .clipped()
        }
        .ignoresSafeArea()
        .opacity(fading ? 0 : 1)
        .contentShape(.rect)
        .onTapGesture { finish() }
        .accessibilityHidden(true)
        .onAppear(perform: start)
        .onReceive(NotificationCenter.default.publisher(for: AVPlayerItem.didPlayToEndTimeNotification)) { note in
            if (note.object as? AVPlayerItem) === player?.currentItem { finish() }
        }
    }

    private func start() {
        guard player == nil else { return }
        let name = portrait ? "intro-portrait" : "intro"
        guard let url = Bundle.main.url(forResource: name, withExtension: "mp4") else {
            finish()
            return
        }
        let player = AVPlayer(url: url)
        self.player = player
        // Ambient: the silent switch mutes it and other audio keeps playing.
        try? AVAudioSession.sharedInstance().setCategory(.ambient, options: .mixWithOthers)
        player.preventsDisplaySleepDuringVideoPlayback = false
        player.play()
    }

    private func finish() {
        guard !finished else { return }
        finished = true
        player?.pause()
        withAnimation(.easeOut(duration: 0.7)) { fading = true } completion: {
            onFinish()
        }
    }
}
