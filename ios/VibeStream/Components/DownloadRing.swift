import SwiftUI

// Indeterminate (nil) before qBittorrent reports anything, rather than a
// stalled-looking 0%.
struct DownloadRing: View {
    /// 0...100, or nil while there is nothing to report yet.
    var percent: Double?
    var size: CGFloat = 34
    var showsLabel: Bool = true

    @State private var spin = false

    private var stroke: CGFloat { max(2.5, size * 0.09) }

    var body: some View {
        ZStack {
            Circle()
                .stroke(.white.opacity(0.28), lineWidth: stroke)

            if let percent {
                Circle()
                    .trim(from: 0, to: max(0.02, min(1, percent / 100)))
                    .stroke(Palette.accent,
                            style: StrokeStyle(lineWidth: stroke, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .animation(.easeOut(duration: 0.35), value: percent)

                if showsLabel && size >= 30 {
                    Text("\(Int(percent))")
                        .font(.system(size: size * 0.3, weight: .bold))
                        .foregroundStyle(.white)
                }
            } else {
                Circle()
                    .trim(from: 0, to: 0.25)
                    .stroke(Palette.accent,
                            style: StrokeStyle(lineWidth: stroke, lineCap: .round))
                    .rotationEffect(.degrees(spin ? 360 : 0))
                    .animation(.linear(duration: 1).repeatForever(autoreverses: false),
                               value: spin)
                    .onAppear { spin = true }
            }
        }
        .frame(width: size, height: size)
        .background(Circle().fill(.black.opacity(0.45)).padding(-stroke))
    }
}
