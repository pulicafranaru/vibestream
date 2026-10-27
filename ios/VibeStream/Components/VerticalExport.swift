import AVFoundation
import CoreImage
import SwiftUI
import UIKit

// Rendered with the phone's encoder: on the server it would mean a CPU re-encode
// of 4K HDR.
enum VerticalExport {
    static let size = CGSize(width: 1080, height: 1920)

    enum Failure: LocalizedError {
        case cannotExport
        var errorDescription: String? { "The video could not be made on this device." }
    }

    /// `progress` runs from 0 to 1.
    static func make(clip: Clip, path: VerticalPath,
                     progress: @escaping @MainActor (Double) -> Void) async throws -> URL {
        let folder = FileManager.default.temporaryDirectory.appending(path: "vertical", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)

        // Download the clip first: exporting straight from the network reads at playback speed.
        let remote = try await APIClient.shared.url(for: clip.video)
        let (download, _) = try await URLSession.shared.download(from: remote)
        let source = folder.appending(path: "clip-\(clip.id)-wide.mp4")
        try? FileManager.default.removeItem(at: source)
        try FileManager.default.moveItem(at: download, to: source)
        await progress(0.05)

        let asset = AVURLAsset(url: source)
        let output = size
        let composition = try await AVMutableVideoComposition.videoComposition(
            with: asset,
            applyingCIFiltersWithHandler: { request in
                let image = request.sourceImage
                let extent = image.extent
                let window = path.window(at: request.compositionTime.seconds)
                // VerticalWindow measures from the top; Core Image from the bottom.
                let crop = window.rect(in: extent.size)
                let area = CGRect(x: extent.minX + crop.minX,
                                  y: extent.minY + extent.height - crop.maxY,
                                  width: crop.width, height: crop.height)
                let scale = output.height / max(area.height, 1)
                let framed = image.cropped(to: area)
                    .transformed(by: CGAffineTransform(translationX: -area.minX, y: -area.minY))
                    .transformed(by: CGAffineTransform(scaleX: scale, y: scale))
                    .cropped(to: CGRect(origin: .zero, size: output))
                request.finish(with: framed, context: nil)
            })
        composition.renderSize = output

        let name = clip.title.replacingOccurrences(of: "/", with: " ")
        let target = folder.appending(path: "\(name) (vertical).mp4")
        try? FileManager.default.removeItem(at: target)
        guard let session = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetHighestQuality)
        else { throw Failure.cannotExport }
        session.videoComposition = composition
        session.shouldOptimizeForNetworkUse = true

        let watcher = Task {
            for await state in session.states(updateInterval: 0.2) {
                if case .exporting(let made) = state {
                    await progress(0.05 + 0.95 * made.fractionCompleted)
                }
            }
        }
        defer { watcher.cancel() }
        try await session.export(to: target, as: .mp4)
        try? FileManager.default.removeItem(at: source)
        await progress(1)
        return target
    }
}

struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
