import SwiftUI

// Turned by the clock, not by an appear animation, so a redraw never restarts it.
struct BootSpinner: View {
    var size: CGFloat = 48
    var line: CGFloat = 4

    var body: some View {
        TimelineView(.animation) { context in
            let period = 0.9
            let turn = context.date.timeIntervalSinceReferenceDate
                .truncatingRemainder(dividingBy: period) / period
            ZStack {
                Circle()
                    .stroke(.white.opacity(0.14), lineWidth: line)
                Circle()
                    .trim(from: 0.625, to: 0.875)
                    .stroke(Palette.accent, lineWidth: line)
            }
            .frame(width: size - line, height: size - line)
            .rotationEffect(.degrees(turn * 360))
        }
        .frame(width: size, height: size)
        .accessibilityLabel("Loading")
    }
}
