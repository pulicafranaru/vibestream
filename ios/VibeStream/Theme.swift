import SwiftUI

// The ground is near black, not pure black, which reads as a hole beside artwork on OLED.
enum Palette {
    static let accent = Color(red: 1.0, green: 0.416, blue: 0.0)   // #ff6a00
    static let ember = [Color(red: 1.0, green: 0.69, blue: 0.0),
                        Color(red: 1.0, green: 0.416, blue: 0.0),
                        Color(red: 1.0, green: 0.18, blue: 0.388)]
    static let good = Color(red: 1.0, green: 0.69, blue: 0.0)   // #ffb000
    static let ground = Color(red: 0.055, green: 0.039, blue: 0.031)   // #0e0a08, warm black
    static let dim = Color(white: 0.72)
    static let faint = Color(white: 0.49)
    static let chip = Color(red: 0.165, green: 0.133, blue: 0.110)   // #2a221c
    static let tile = Color(red: 0.118, green: 0.098, blue: 0.082)   // #1e1915
    static let danger = Color(red: 0.898, green: 0.196, blue: 0.176)   // #e5322d
}

extension View {
    func glassCard(_ radius: CGFloat = 14) -> some View {
        glassEffect(.regular, in: .rect(cornerRadius: radius))
    }

    func softTopEdge() -> some View {
        scrollEdgeEffectStyle(.soft, for: .top)
    }
}

enum Metrics {
    static let posterAspect: CGFloat = 2.0 / 3.0
    static let posterWidth: CGFloat = 116
    static let posterWidthPad: CGFloat = 152
    static let rowSpacing: CGFloat = 10
}

func timecode(_ seconds: Double) -> String {
    guard seconds.isFinite, seconds >= 0 else { return "0:00" }
    let total = Int(seconds)
    let h = total / 3600, m = (total % 3600) / 60, s = total % 60
    return h > 0
        ? String(format: "%d:%02d:%02d", h, m, s)
        : String(format: "%d:%02d", m, s)
}
