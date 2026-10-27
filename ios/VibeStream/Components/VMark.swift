import SwiftUI

/// Drawn in a 1600 by 1466 box.
struct VMark: View {
    var height: CGFloat = 40

    var body: some View {
        VShape()
            .fill(LinearGradient(colors: Palette.ember, startPoint: .topLeading, endPoint: .bottomTrailing))
            .frame(width: height * 1600 / 1466, height: height)
            .accessibilityLabel("VibeStream")
    }
}

private struct VShape: Shape {
    private static let points: [CGPoint] = [
        CGPoint(x: 5, y: 0), CGPoint(x: 479, y: 0), CGPoint(x: 809, y: 1055), CGPoint(x: 1134, y: 0),
        CGPoint(x: 1594, y: 0), CGPoint(x: 1050, y: 1466), CGPoint(x: 559, y: 1466),
    ]

    func path(in rect: CGRect) -> Path {
        let sx = rect.width / 1600, sy = rect.height / 1466
        var path = Path()
        path.addLines(Self.points.map { CGPoint(x: rect.minX + $0.x * sx, y: rect.minY + $0.y * sy) })
        path.closeSubpath()
        return path
    }
}
