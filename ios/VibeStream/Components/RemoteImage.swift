import CoreImage
import SwiftUI

// AsyncImage refetches on identity change and fades in every time; this caches
// decoded images by URL so only the first appearance animates.
@MainActor
final class ImageCache {
    static let shared = ImageCache()
    private var store = NSCache<NSURL, UIImage>()

    init() {
        store.countLimit = 400
        store.totalCostLimit = 96 << 20
    }

    func image(for url: URL) -> UIImage? { store.object(forKey: url as NSURL) }

    func insert(_ image: UIImage, for url: URL) {
        let cost = image.cgImage.map { $0.bytesPerRow * $0.height } ?? 0
        store.setObject(image, forKey: url as NSURL, cost: cost)
    }
}

struct RemoteImage: View {
    let url: URL?
    var contentMode: ContentMode = .fill
    var onImage: ((UIImage) -> Void)?

    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: contentMode)
            } else {
                Palette.tile
                if failed {
                    Image(systemName: "film")
                        .font(.title3)
                        .foregroundStyle(Palette.faint)
                }
            }
        }
        .task(id: url) { await load() }
    }

    private func load() async {
        guard let url else { failed = true; return }
        if let cached = ImageCache.shared.image(for: url) {
            image = cached
            onImage?(cached)
            return
        }
        do {
            // A bare path is the server's (episode stills); TMDB URLs are absolute.
            let address = url.host == nil ? try await APIClient.shared.url(for: url.relativeString) : url
            let (data, _) = try await URLSession.shared.data(from: address)
            guard let decoded = UIImage(data: data) else { failed = true; return }
            ImageCache.shared.insert(decoded, for: url)
            withAnimation(.easeOut(duration: 0.18)) { image = decoded }
            onImage?(decoded)
        } catch {
            failed = true
        }
    }
}

enum ArtworkTint {
    private static let context = CIContext(options: [.workingColorSpace: NSNull()])

    /// 0 (black) to 1 (white). `region` is in unit coordinates, origin top left.
    static func luminance(of image: UIImage, region: CGRect) -> CGFloat? {
        guard let full = image.cgImage else { return nil }
        let size = CGSize(width: full.width, height: full.height)
        let rect = CGRect(
            x: region.minX * size.width, y: region.minY * size.height,
            width: max(1, region.width * size.width),
            height: max(1, region.height * size.height)
        )
        guard let cropped = full.cropping(to: rect) else { return nil }

        let ciImage = CIImage(cgImage: cropped)
        guard let average = CIFilter(
            name: "CIAreaAverage",
            parameters: [
                kCIInputImageKey: ciImage,
                kCIInputExtentKey: CIVector(cgRect: ciImage.extent),
            ]
        )?.outputImage else { return nil }

        var pixel = [UInt8](repeating: 0, count: 4)
        context.render(
            average, toBitmap: &pixel, rowBytes: 4,
            bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
            format: .RGBA8, colorSpace: nil
        )
        // Rec. 709 weights: green carries most of what the eye reads as bright.
        return (0.2126 * CGFloat(pixel[0]) + 0.7152 * CGFloat(pixel[1])
                + 0.0722 * CGFloat(pixel[2])) / 255
    }

    static func onTopTrailing(of image: UIImage) -> Color {
        let corner = CGRect(x: 0.7, y: 0, width: 0.3, height: 0.25)
        guard let brightness = luminance(of: image, region: corner) else { return .white }
        // Biased towards white: the artwork is usually dark.
        return brightness > 0.62 ? .black : .white
    }
}
