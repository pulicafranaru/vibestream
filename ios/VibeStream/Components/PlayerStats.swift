import AVFoundation
import SwiftUI
import UIKit

// Sampled once a second from AVFoundation, only while the overlay is on screen.
@MainActor @Observable
final class PlayerStats {
    struct Sample {
        var kbps: Double
        var kilobytes: Double
        var buffer: Double
    }

    /// The last minute, oldest first.
    private(set) var samples: [Sample] = []
    private(set) var observedKbps: Double = 0
    private(set) var variantKbps: Double = 0
    private(set) var kilobytes: Double = 0
    private(set) var buffer: Double = 0
    private(set) var dropped = 0
    private(set) var watched: Double = 0
    private(set) var stalls = 0
    private(set) var presentation: CGSize = .zero
    private(set) var server: String?
    private(set) var now = Date()

    @ObservationIgnored private var task: Task<Void, Never>?
    @ObservationIgnored private var lastBytes: Int64 = 0

    func start(_ player: AVPlayer) {
        task?.cancel()
        task = Task { [weak self] in
            while !Task.isCancelled {
                self?.tick(player)
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    private func tick(_ player: AVPlayer) {
        now = Date()
        guard let item = player.currentItem else { return }
        let events = item.accessLog()?.events ?? []
        if let last = events.last {
            observedKbps = max(0, last.observedBitrate) / 1000
            variantKbps = max(0, last.indicatedBitrate) / 1000
            server = last.serverAddress ?? last.uri.flatMap { URL(string: $0)?.host() }
        }
        dropped = events.reduce(0) { $0 + max(0, $1.numberOfDroppedVideoFrames) }
        stalls = events.reduce(0) { $0 + max(0, $1.numberOfStalls) }
        watched = events.reduce(0) { $0 + max(0, $1.durationWatched) }
        let bytes = events.reduce(Int64(0)) { $0 + max(0, $1.numberOfBytesTransferred) }
        // A new item starts its log from nothing.
        kilobytes = bytes >= lastBytes ? Double(bytes - lastBytes) / 1024 : 0
        lastBytes = bytes

        let at = item.currentTime().seconds
        buffer = item.loadedTimeRanges.map(\.timeRangeValue)
            .first { $0.start.seconds <= at + 0.5 && at <= $0.end.seconds }
            .map { max(0, $0.end.seconds - at) } ?? 0
        presentation = item.presentationSize

        samples.append(Sample(kbps: observedKbps, kilobytes: kilobytes, buffer: buffer))
        if samples.count > 60 { samples.removeFirst(samples.count - 60) }
    }
}

struct StatsOverlay: View {
    let stats: PlayerStats
    let model: PlayerModel
    let area: CGSize

    var body: some View {
        let font = min(max(area.width / 62, 8.5), 13)
        Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: font * 0.8, verticalSpacing: font * 0.2) {
            row("Play ID / Engine", engine)
            row("File", file)
            row("Viewport / Frames", viewport)
            row("Current / Source Res", resolution)
            row("Volume", volume)
            row("Codecs", codecs)
            row("Color", color)
            graphRow("Connection Speed", "\(Int(stats.observedKbps.rounded())) Kbps",
                     values: stats.samples.map(\.kbps), tint: Self.blue, size: font)
            graphRow("Network Activity", "\(Int(stats.kilobytes.rounded())) KB",
                     values: stats.samples.map(\.kilobytes), tint: Self.teal, size: font)
            graphRow("Buffer Health", String(format: "%.2f s", stats.buffer),
                     values: stats.samples.map(\.buffer), tint: Self.lime, size: font)
            row("Stream", stream)
            row("Date", Self.date.string(from: stats.now))
        }
        .font(.system(size: font, weight: .regular).monospacedDigit())
        .foregroundStyle(.white)
        .shadow(color: .black.opacity(0.9), radius: 2)
        .padding(10)
        .background(.black.opacity(0.45), in: .rect(cornerRadius: 8))
        .allowsHitTesting(false)
    }

    private func row(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label).fontWeight(.bold).gridColumnAlignment(.trailing)
            Text(value).lineLimit(1).truncationMode(.middle)
        }
    }

    private func graphRow(_ label: String, _ value: String, values: [Double], tint: Color,
                          size: CGFloat) -> some View {
        GridRow(alignment: .center) {
            Text(label).fontWeight(.bold).gridColumnAlignment(.trailing)
            HStack(spacing: size * 0.6) {
                Sparkline(values: values, tint: tint)
                    .frame(width: size * 13, height: size * 1.35)
                Text(value)
            }
        }
    }

    private static let date: DateFormatter = {
        let format = DateFormatter()
        format.locale = Locale(identifier: "en_US_POSIX")
        format.dateFormat = "EEE MMM d yyyy HH:mm:ss 'GMT'xxx"
        return format
    }()

    private static let blue = Color(red: 0.16, green: 0.5, blue: 0.78)
    private static let teal = Color(red: 0.36, green: 0.75, blue: 0.62)
    private static let lime = Color(red: 0.86, green: 0.94, blue: 0.56)

    private var info: PlayInfo? { model.info }

    private var engine: String {
        let id = info?.playID ?? "?"
        let engine = info?.playback.engine == "live" ? "live remux" : "prepared rendition"
        let mode = info?.playback.mode ?? "?"
        return "\(id) / \(engine), \(mode)"
    }

    private var file: String {
        let name = info?.file?.name ?? "?"
        guard let bytes = info?.file?.sizeBytes else { return name }
        return "\(name) (\(ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)))"
    }

    private var viewport: String {
        let scale = UIScreen.main.scale
        let frames = Int((stats.watched * (info?.media?.video?.frameRate ?? 24)).rounded())
        return "\(Int(area.width))x\(Int(area.height))*\(String(format: "%.2f", scale))"
            + " / \(stats.dropped) dropped of \(frames)"
    }

    private var resolution: String {
        let current = stats.presentation == .zero ? "?"
            : "\(Int(stats.presentation.width))x\(Int(stats.presentation.height))"
        guard let video = info?.media?.video, let w = video.width, let h = video.height else {
            return current
        }
        let fps = video.frameRate.map { String(format: "@%g", ($0 * 100).rounded() / 100) } ?? ""
        return "\(current) / \(w)x\(h)\(fps)"
    }

    private var volume: String {
        let app = Int((model.player.volume * 100).rounded())
        let system = Int((AVAudioSession.sharedInstance().outputVolume * 100).rounded())
        return "\(app)% / \(system)% device" + (model.player.isMuted ? ", muted" : "")
    }

    private var codecs: String {
        let video = info?.media?.video
        let videoPart = [video?.codec, video?.profile].compactMap { $0 }.joined(separator: " ")
            + (video?.bitDepth.map { " \($0)-bit" } ?? "")
        let index = model.audioIndex ?? info?.defaultAudioIndex
        let source = info?.media?.audio?.first { $0.index == index }
        var audioPart = [source?.codec, source?.channels.map { "\($0)ch" }]
            .compactMap { $0 }.joined(separator: " ")
        if info?.playback.audioTranscoded == true { audioPart += " > aac" }
        return "\(videoPart.isEmpty ? "?" : videoPart) / \(audioPart.isEmpty ? "?" : audioPart)"
    }

    private var color: String {
        guard let video = info?.media?.video else { return "?" }
        if video.dolbyVision == true { return "Dolby Vision" + (video.hdr == true ? " / HDR10 base" : "") }
        if video.hdr == true { return "HDR (\(video.bitDepth ?? 10)-bit)" }
        return "SDR"
    }

    private var stream: String {
        let variant = stats.variantKbps > 0 ? "\(Int(stats.variantKbps.rounded())) Kbps variant" : "variant ?"
        let container = info?.media?.container.map { ", \($0)" } ?? ""
        return "\(variant)\(container), \(stats.stalls) stalls, \(stats.server ?? "?")"
    }
}

private struct Sparkline: View {
    let values: [Double]
    let tint: Color

    var body: some View {
        Canvas { context, size in
            let slots = 60
            let width = size.width / CGFloat(slots)
            let top = max(values.max() ?? 0, 0.0001)
            context.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.white.opacity(0.08)))
            for (i, value) in values.enumerated() {
                let x = CGFloat(slots - values.count + i) * width
                let height = max(1, size.height * CGFloat(value / top))
                let bar = CGRect(x: x, y: size.height - height, width: max(1, width - 0.5), height: height)
                context.fill(Path(bar), with: .color(tint))
            }
        }
    }
}
