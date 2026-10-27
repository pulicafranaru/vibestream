import CoreGraphics
import Foundation

// The server's automatic path per shot, bent by hand keyframes within a shot.
// Positions are fractions of the wide frame; zoom 1 is the full picture height.
struct ClipVertical: Codable, Sendable {
    var picture: Picture?
    var crop: Crop?
    var keyframes: [Keyframe]

    struct Picture: Codable, Hashable, Sendable {
        var width: Double
        var height: Double
    }

    struct Crop: Codable, Hashable, Sendable {
        /// The clip's frame, width over height.
        var aspect: Double
        var shots: [Shot]

        struct Shot: Codable, Hashable, Sendable {
            var start: Double
            var end: Double
            /// [seconds, centre as a fraction of the width]; one point holds.
            var points: [[Double]]
        }
    }

    struct Keyframe: Codable, Hashable, Sendable {
        var t: Double
        var x: Double
        var y: Double = 0.5
        var zoom: Double = 1
    }
}

struct VerticalWindow: Equatable {
    var x: Double
    var y: Double
    var width: Double
    var height: Double
    var zoom: Double

    /// In a frame of `size` pixels, the rectangle to crop (top-left origin).
    func rect(in size: CGSize) -> CGRect {
        CGRect(x: (x - width / 2) * size.width, y: (y - height / 2) * size.height,
               width: width * size.width, height: height * size.height)
    }
}

struct VerticalPath: Sendable {
    var vertical: ClipVertical
    var aspect: Double
    var duration: Double

    static let tall = 9.0 / 16.0
    static let maxZoom = 4.0

    private var picture: ClipVertical.Picture { vertical.picture ?? .init(width: 1, height: 1) }

    func auto(at time: Double) -> Double {
        guard let shot = shot(at: time), let first = shot.points.first, first.count == 2 else { return 0.5 }
        if shot.points.count == 1 || time <= first[0] { return first[1] }
        for (a, b) in zip(shot.points, shot.points.dropFirst())
        where a.count == 2 && b.count == 2 && time >= a[0] && time <= b[0] {
            let span = b[0] - a[0]
            return span > 0 ? a[1] + (b[1] - a[1]) * (time - a[0]) / span : b[1]
        }
        return shot.points.last?.last ?? 0.5
    }

    var shots: [ClipVertical.Crop.Shot] {
        vertical.crop?.shots ?? [.init(start: 0, end: max(duration, 0.1), points: [[0, 0.5]])]
    }

    private func shot(at time: Double) -> ClipVertical.Crop.Shot? {
        shots.first { time >= $0.start && time < $0.end }
            ?? (time >= (shots.last?.end ?? 0) ? shots.last : shots.first)
    }

    private func sameShot(_ a: Double, _ b: Double) -> Bool {
        let shot = shot(at: a)
        return shot == self.shot(at: b)
    }

    func window(at time: Double) -> VerticalWindow {
        let base = auto(at: time)
        var dx = 0.0, y = 0.5, zoom = 1.0
        let mine = vertical.keyframes.filter { sameShot($0.t, time) }.sorted { $0.t < $1.t }
        if let first = mine.first, let last = mine.last {
            func offset(_ k: ClipVertical.Keyframe) -> Double { k.x - auto(at: k.t) }
            if time <= first.t {
                (dx, y, zoom) = (offset(first), first.y, first.zoom)
            } else if time >= last.t {
                (dx, y, zoom) = (offset(last), last.y, last.zoom)
            } else if let b = mine.first(where: { $0.t >= time }),
                      let a = mine.last(where: { $0.t <= time }) {
                let f = b.t > a.t ? (time - a.t) / (b.t - a.t) : 0
                dx = offset(a) + (offset(b) - offset(a)) * f
                y = a.y + (b.y - a.y) * f
                zoom = a.zoom + (b.zoom - a.zoom) * f
            }
        }
        return place(x: base + dx, y: y, zoom: zoom)
    }

    func place(x: Double, y: Double, zoom: Double) -> VerticalWindow {
        let zoom = min(max(zoom, 1), Self.maxZoom)
        let height = picture.height / zoom
        let width = min(1, height * Self.tall / max(aspect, 0.1))
        let barsX = (1 - picture.width) / 2, barsY = (1 - picture.height) / 2
        let clampedX = min(max(x, barsX + width / 2), 1 - barsX - width / 2)
        let clampedY = min(max(y, barsY + height / 2), 1 - barsY - height / 2)
        return VerticalWindow(x: width >= 1 - 2 * barsX ? 0.5 : clampedX,
                              y: height >= 1 - 2 * barsY ? 0.5 : clampedY,
                              width: width, height: height, zoom: zoom)
    }

    var cuts: [Double] { shots.dropFirst().map(\.start) }
}
