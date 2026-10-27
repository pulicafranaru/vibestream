import AVFoundation
import CoreMedia
import SwiftUI

// Three sizes and four styles, the same as the TV app.
enum SubtitleSize: String, Codable, CaseIterable, Identifiable {
    case small, medium, large
    var id: String { rawValue }

    var label: String {
        switch self {
        case .small: "Small"
        case .medium: "Medium"
        case .large: "Large"
        }
    }

    var scale: Double {
        switch self {
        case .small: 0.75
        case .medium: 1
        case .large: 1.4
        }
    }
}

enum SubtitleStyle: String, Codable, CaseIterable, Identifiable {
    case shadow, outline, yellow, boxed
    var id: String { rawValue }

    var label: String {
        switch self {
        case .shadow: "Drop Shadow"
        case .outline: "Outline"
        case .yellow: "Yellow"
        case .boxed: "Boxed"
        }
    }
}

enum SubtitleLook {
    static let yellow = Color(red: 0.96, green: 0.816, blue: 0.125)

    static func rules(size: SubtitleSize, style: SubtitleStyle) -> [AVTextStyleRule] {
        var attributes: [String: Any] = [
            kCMTextMarkupAttribute_RelativeFontSize as String: size.scale * 100,
            kCMTextMarkupAttribute_BoldStyle as String: true,
        ]
        // Colours are alpha, red, green, blue, each 0 to 1.
        switch style {
        case .shadow:
            attributes[kCMTextMarkupAttribute_ForegroundColorARGB as String] = [1, 1, 1, 1]
            attributes[kCMTextMarkupAttribute_CharacterEdgeStyle as String] =
                kCMTextMarkupCharacterEdgeStyle_DropShadow
            attributes[kCMTextMarkupAttribute_CharacterBackgroundColorARGB as String] = [0, 0, 0, 0]
        case .outline:
            attributes[kCMTextMarkupAttribute_ForegroundColorARGB as String] = [1, 1, 1, 1]
            attributes[kCMTextMarkupAttribute_CharacterEdgeStyle as String] =
                kCMTextMarkupCharacterEdgeStyle_Uniform
            attributes[kCMTextMarkupAttribute_CharacterBackgroundColorARGB as String] = [0, 0, 0, 0]
        case .yellow:
            attributes[kCMTextMarkupAttribute_ForegroundColorARGB as String] = [1, 0.96, 0.816, 0.125]
            attributes[kCMTextMarkupAttribute_CharacterEdgeStyle as String] =
                kCMTextMarkupCharacterEdgeStyle_DropShadow
            attributes[kCMTextMarkupAttribute_CharacterBackgroundColorARGB as String] = [0, 0, 0, 0]
        case .boxed:
            attributes[kCMTextMarkupAttribute_ForegroundColorARGB as String] = [1, 1, 1, 1]
            attributes[kCMTextMarkupAttribute_CharacterEdgeStyle as String] =
                kCMTextMarkupCharacterEdgeStyle_None
            attributes[kCMTextMarkupAttribute_CharacterBackgroundColorARGB as String] = [0.78, 0, 0, 0]
        }
        return AVTextStyleRule(textMarkupAttributes: attributes).map { [$0] } ?? []
    }
}

struct SubtitleSample: View {
    let text: String
    var size: SubtitleSize = .medium
    var style: SubtitleStyle
    var base: CGFloat = 17

    var body: some View {
        let label = Text(text)
            .font(.system(size: base * size.scale, weight: .bold))
            .foregroundStyle(style == .yellow ? SubtitleLook.yellow : .white)
        switch style {
        case .shadow, .yellow:
            label.shadow(color: .black.opacity(0.9), radius: 3, y: 1.5)
        case .outline:
            label
                .shadow(color: .black, radius: 0, x: 1.2, y: 1.2)
                .shadow(color: .black, radius: 0, x: -1.2, y: -1.2)
                .shadow(color: .black, radius: 0, x: 1.2, y: -1.2)
                .shadow(color: .black, radius: 0, x: -1.2, y: 1.2)
        case .boxed:
            label
                .padding(.horizontal, 8)
                .padding(.vertical, 2)
                .background(.black.opacity(0.78), in: .rect(cornerRadius: 4))
        }
    }
}

// Drawn by the app: AVFoundation's own styling is capped by the system caption
// settings, which keep a translucent box. AVFoundation still parses and times the cues.
final class CaptionReader: NSObject, AVPlayerItemLegibleOutputPushDelegate {
    let output = AVPlayerItemLegibleOutput()
    var onLines: (([String]) -> Void)?

    override init() {
        super.init()
        output.suppressesPlayerRendering = true
        output.setDelegate(self, queue: .main)
    }

    nonisolated func legibleOutput(_ output: AVPlayerItemLegibleOutput,
                                   didOutputAttributedStrings strings: [NSAttributedString],
                                   nativeSampleBuffers: [Any],
                                   forItemTime itemTime: CMTime) {
        let lines = strings
            .flatMap { $0.string.components(separatedBy: .newlines) }
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        MainActor.assumeIsolated { onLines?(lines) }
    }
}

struct Captions: View {
    let lines: [String]
    let size: SubtitleSize
    let style: SubtitleStyle
    let height: CGFloat

    var body: some View {
        VStack(spacing: style == .boxed ? 3 : 1) {
            ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                SubtitleSample(text: line, size: size, style: style,
                               base: min(34, max(13, height * 0.048)))
                    .multilineTextAlignment(.center)
            }
        }
        .padding(.horizontal, 24)
        .allowsHitTesting(false)
    }
}

// The server's WebVTT, parsed directly for when the media playlist plays alone
// (see PlayerModel.recover) and so has no subtitle renditions.
struct SubtitleFile: Sendable {
    struct Cue: Sendable {
        let start: Double
        let end: Double
        let lines: [String]
    }

    let cues: [Cue]

    init(vtt text: String) {
        var cues: [Cue] = []
        let blocks = text.replacingOccurrences(of: "\r\n", with: "\n")
            .components(separatedBy: "\n\n")
        for block in blocks {
            let rows = block.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
            guard let timing = rows.firstIndex(where: { $0.contains("-->") }) else { continue }
            let parts = rows[timing].components(separatedBy: "-->")
            guard parts.count == 2,
                  let start = Self.seconds(parts[0]),
                  let end = Self.seconds(parts[1].split(separator: " ", omittingEmptySubsequences: true)
                                            .first.map(String.init) ?? "") else { continue }
            let lines = rows[(timing + 1)...].map(Self.plain).filter { !$0.isEmpty }
            if !lines.isEmpty { cues.append(Cue(start: start, end: end, lines: lines)) }
        }
        self.cues = cues.sorted { $0.start < $1.start }
    }

    func lines(at time: Double) -> [String] {
        // The last cue starting at or before `time`, then back through any
        // earlier ones still running alongside it.
        var low = 0, high = cues.count - 1, found = -1
        while low <= high {
            let mid = (low + high) / 2
            if cues[mid].start <= time { found = mid; low = mid + 1 } else { high = mid - 1 }
        }
        guard found >= 0 else { return [] }
        var showing: [Cue] = []
        var index = found
        while index >= 0 && found - index < 8 {
            if cues[index].end > time { showing.insert(cues[index], at: 0) }
            index -= 1
        }
        return showing.flatMap(\.lines)
    }

    /// "01:02:03.456" or "02:03.456".
    private static func seconds(_ raw: String) -> Double? {
        let fields = raw.trimmingCharacters(in: .whitespaces).split(separator: ":")
        guard (2...3).contains(fields.count),
              let last = Double(fields.last!.replacingOccurrences(of: ",", with: ".")) else { return nil }
        var total = last
        var unit = 60.0
        for field in fields.dropLast().reversed() {
            guard let value = Double(field) else { return nil }
            total += value * unit
            unit *= 60
        }
        return total
    }

    private static func plain(_ line: String) -> String {
        var text = line.replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
        for (entity, character) in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " "),
                                    ("&lrm;", ""), ("&rlm;", "")] {
            text = text.replacingOccurrences(of: entity, with: character)
        }
        return text.trimmingCharacters(in: .whitespaces)
    }
}
