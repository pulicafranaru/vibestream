import SwiftUI

// Dragging does not seek until release: seeking on every touch update floods a 4K stream with exact seeks.
struct Scrubber: View {
    let model: PlayerModel
    @Binding var scrubbing: Bool
    @Binding var target: Double
    var onInteract: () -> Void

    @State private var preview: ThumbFrame?
    @State private var previewX: CGFloat = 0
    @State private var previewTask: Task<Void, Never>?

    private var shown: Double { scrubbing ? target : model.current }

    var body: some View {
        HStack(spacing: 14) {
            GeometryReader { geo in
                let width = geo.size.width
                let fraction = model.duration > 0 ? min(1, max(0, shown / model.duration)) : 0

                ZStack(alignment: .leading) {
                    Capsule().fill(.white.opacity(0.3)).frame(height: 4)
                    Capsule().fill(Palette.accent).frame(width: width * fraction, height: 4)
                    Circle()
                        .fill(Palette.accent)
                        .frame(width: scrubbing ? 18 : 13, height: scrubbing ? 18 : 13)
                        .offset(x: width * fraction - (scrubbing ? 9 : 6.5))
                }
                .frame(height: 26)
                .contentShape(.rect)
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { value in
                            guard model.duration > 0 else { return }
                            scrubbing = true
                            let ratio = min(1, max(0, value.location.x / width))
                            target = ratio * model.duration
                            previewX = value.location.x
                            onInteract()
                        }
                        .onEnded { _ in
                            model.seek(to: target)
                            scrubbing = false
                            preview = nil
                            previewTask?.cancel()
                            previewTask = nil
                            onInteract()
                        }
                )
                .overlay(alignment: .bottomLeading) {
                    if scrubbing { thumbnail(width: width) }
                }
                .animation(.easeOut(duration: 0.12), value: scrubbing)
            }
            .frame(height: 26)

            Text(timecode(max(0, model.duration - shown)))
                .font(.footnote.monospacedDigit())
                .foregroundStyle(.white)
                .fixedSize()
        }
        // Driven by the value, so any change of target (a drag or a remote seek) gets a preview.
        .onChange(of: target) { _, _ in if scrubbing { schedulePreview() } }
        .onChange(of: scrubbing) { _, active in
            if active { schedulePreview() } else { preview = nil }
        }
    }

    @ViewBuilder private func thumbnail(width: CGFloat) -> some View {
        let tileWidth: CGFloat = 150
        let ratio = preview.map { $0.cell.height / $0.cell.width } ?? 9.0 / 16.0

        VStack(spacing: 5) {
            Group {
                if let preview {
                    SpriteFrame(frame: preview, width: tileWidth)
                } else {
                    Rectangle().fill(.black.opacity(0.6))
                        .frame(width: tileWidth, height: tileWidth * ratio)
                }
            }
            .clipShape(.rect(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(.white.opacity(0.9), lineWidth: 1.5))

            Text(timecode(target))
                .font(.caption2.monospacedDigit())
                .padding(.horizontal, 7).padding(.vertical, 2)
                .background(.black.opacity(0.8), in: .rect(cornerRadius: 4))
        }
        .offset(x: min(max(previewX - tileWidth / 2, 0), width - tileWidth), y: -34)
        .allowsHitTesting(false)
    }

    // One lookup at a time, each for wherever the knob is by then. A debounce never fires
    // while a finger moves, since a 120 Hz screen reports every 8 ms.
    private func schedulePreview() {
        guard previewTask == nil else { return }
        previewTask = Task {
            while !Task.isCancelled && scrubbing {
                let at = target
                let found = await model.thumbnail(at: at)
                guard !Task.isCancelled else { break }
                if let found { preview = found }
                if target == at { break }
            }
            previewTask = nil
        }
    }
}

struct ThumbFrame: Equatable, Hashable {
    let url: URL
    let cell: CGRect
}

// Cropped out of the decoded sheet: CGImage.cropping shares pixels, so a drag costs one
// decode per sheet. The last frame stays up while the next loads.
struct SpriteFrame: View {
    let frame: ThumbFrame
    let width: CGFloat

    @State private var tile: UIImage?

    var body: some View {
        let ratio = frame.cell.height / max(1, frame.cell.width)
        Group {
            if let tile {
                Image(uiImage: tile).resizable().scaledToFill()
            } else {
                Rectangle().fill(.black.opacity(0.6))
            }
        }
        .frame(width: width, height: width * ratio)
        .task(id: frame) { await load() }
    }

    private func load() async {
        guard let full = await SheetStore.shared.sheet(frame.url),
              !Task.isCancelled,
              let cropped = full.cropping(to: frame.cell) else { return }
        tile = UIImage(cgImage: cropped)
    }
}

// Sprite sheets, fetched once and shared. Fetches are unstructured so a cancelled view task
// does not abort them. JPEGs are kept; only the last few stay decoded (about 9 MB each).
@MainActor
final class SheetStore {
    static let shared = SheetStore()

    private var data: [URL: Data] = [:]
    private var loading: [URL: Task<Data?, Never>] = [:]
    private var decoded: [(URL, CGImage)] = []
    private let keepDecoded = 3

    func sheet(_ url: URL) async -> CGImage? {
        if let hit = decoded.first(where: { $0.0 == url }) { return hit.1 }
        guard let bytes = await bytes(url) else { return nil }
        if let hit = decoded.first(where: { $0.0 == url }) { return hit.1 }
        let image = await Task.detached(priority: .userInitiated) {
            UIImage(data: bytes)?.cgImage
        }.value
        guard let image else { return nil }
        decoded.removeAll { $0.0 == url }
        decoded.append((url, image))
        if decoded.count > keepDecoded { decoded.removeFirst(decoded.count - keepDecoded) }
        return image
    }

    func prefetch(_ urls: [URL]) {
        Task {
            for url in urls { _ = await bytes(url) }
        }
    }

    func forget(_ urls: [URL]) {
        for url in urls { data[url] = nil }
        decoded.removeAll { entry in urls.contains(entry.0) }
    }

    private func bytes(_ url: URL) async -> Data? {
        if let kept = data[url] { return kept }
        if let pending = loading[url] { return await pending.value }
        // Unstructured, so a caller giving up does not cancel the fetch.
        let task = Task<Data?, Never> {
            try? await URLSession.shared.data(from: url).0
        }
        loading[url] = task
        let result = await task.value
        loading[url] = nil
        if let result { data[url] = result }
        return result
    }
}

// Audio & Subtitles, for this player or another device's through its remote.
struct TrackChoices {
    var audio: [PlayInfo.AudioTrack]
    var audioIndex: Int?
    var subtitles: [PlayInfo.Track]
    var subtitleID: String?
    var size: SubtitleSize
    var style: SubtitleStyle
    var chooseAudio: (Int) -> Void
    var chooseSubtitle: (String?) -> Void
    var setLook: (SubtitleSize?, SubtitleStyle?) -> Void
}

extension TrackChoices {
    @MainActor init(model: PlayerModel, state: AppState) {
        audio = model.info?.audio ?? []
        audioIndex = model.audioIndex ?? model.info?.defaultAudioIndex
        subtitles = model.info?.subtitles ?? []
        subtitleID = model.subtitleID
        size = model.prefs.subtitleSize
        style = model.prefs.subtitleStyle
        chooseAudio = { model.chooseAudio($0) }
        chooseSubtitle = { model.chooseSubtitle($0) }
        setLook = { size, style in
            if let size { model.prefs.subtitleSize = size }
            if let style { model.prefs.subtitleStyle = style }
            model.applySubtitleAppearance()
            var prefs = state.playerPrefs
            prefs.subtitleSize = model.prefs.subtitleSize
            prefs.subtitleStyle = model.prefs.subtitleStyle
            state.playerPrefs = prefs
        }
    }
}

struct TrackSettings: View {
    let choices: TrackChoices
    var wide = false

    var body: some View {
        if wide {
            HStack(alignment: .top, spacing: 22) {
                tracks
                appearance
            }
        } else {
            VStack(spacing: 22) { tracks; appearance }
        }
    }

    private var tracks: some View {
        VStack(spacing: 0) {
            menuRow("Audio", systemImage: "speaker.wave.2",
                    value: choices.audio.first { $0.index == choices.audioIndex }?.label ?? "Default") {
                Picker("Audio", selection: Binding(
                    get: { choices.audioIndex ?? -1 },
                    set: { if $0 >= 0 { choices.chooseAudio($0) } })) {
                    ForEach(choices.audio) { Text($0.label).tag($0.index) }
                }
            }
            Divider().overlay(Color.white.opacity(0.06)).padding(.leading, 52)
            menuRow("Subtitles", systemImage: "captions.bubble",
                    value: choices.subtitles.first { $0.id == choices.subtitleID }?.label ?? "Off") {
                Picker("Subtitles", selection: Binding(
                    get: { choices.subtitleID ?? "" },
                    set: { choices.chooseSubtitle($0.isEmpty ? nil : $0) })) {
                    Text("Off").tag("")
                    Section {
                        ForEach(choices.subtitles) { Text($0.label).tag($0.id) }
                    }
                }
            }
        }
        .background(Color.white.opacity(0.06), in: .rect(cornerRadius: 16))
        .frame(maxWidth: .infinity)
        .sensoryFeedback(.selection, trigger: choices.subtitleID)
        .sensoryFeedback(.selection, trigger: choices.audioIndex)
    }

    private func menuRow<Items: View>(
        _ title: String, systemImage: String, value: String,
        @ViewBuilder items: () -> Items
    ) -> some View {
        Menu {
            items()
        } label: {
            HStack(spacing: 12) {
                Image(systemName: systemImage)
                    .font(.system(size: 17))
                    .frame(width: 24)
                    .foregroundStyle(Palette.dim)
                Text(title).font(.body)
                Spacer(minLength: 12)
                Text(value)
                    .font(.body.weight(.semibold))
                    .lineLimit(1)
                    .truncationMode(.middle)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Palette.faint)
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 16)
            .frame(minHeight: 54)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
        .accessibilityValue(value)
    }

    private var appearance: some View {
        VStack(alignment: .leading, spacing: 10) {
            heading("Subtitle Appearance")
            VStack(alignment: .leading, spacing: 18) {
                ZStack(alignment: .bottom) {
                    LinearGradient(colors: [Color(white: 0.32), Color(white: 0.12)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing)
                    SubtitleSample(text: "Where are we going?",
                                   size: choices.size, style: choices.style)
                        .padding(.bottom, 16)
                }
                .frame(height: 110)
                .clipShape(.rect(cornerRadius: 12))
                .animation(.snappy(duration: 0.2), value: choices.size)

                VStack(alignment: .leading, spacing: 8) {
                    caption("Size")
                    HStack(spacing: 8) {
                        ForEach(SubtitleSize.allCases) { size in
                            let on = choices.size == size
                            Button { set(size: size) } label: {
                                Text(size.label)
                                    .font(.subheadline.weight(on ? .semibold : .regular))
                                    .foregroundStyle(on ? .black : .white)
                                    .frame(maxWidth: .infinity)
                                    .frame(height: 38)
                                    .background(on ? Color.white : Color.white.opacity(0.1), in: .capsule)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                VStack(alignment: .leading, spacing: 8) {
                    caption("Style")
                    LazyVGrid(columns: [GridItem(.flexible(), spacing: 8), GridItem(.flexible(), spacing: 8)],
                              spacing: 8) {
                        ForEach(SubtitleStyle.allCases) { style in
                            let on = choices.style == style
                            Button { set(style: style) } label: {
                                VStack(spacing: 6) {
                                    SubtitleSample(text: "Aa", style: style, base: 20)
                                        .frame(height: 30)
                                    Text(style.label)
                                        .font(.caption.weight(on ? .semibold : .regular))
                                        .foregroundStyle(on ? .white : Palette.dim)
                                }
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 12)
                                .background(Color(white: 0.24), in: .rect(cornerRadius: 12))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 12)
                                        .strokeBorder(.white, lineWidth: on ? 2 : 0)
                                )
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .padding(16)
            .background(Color.white.opacity(0.06), in: .rect(cornerRadius: 16))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .sensoryFeedback(.selection, trigger: choices.style)
        .sensoryFeedback(.selection, trigger: choices.size)
    }

    private func set(size: SubtitleSize? = nil, style: SubtitleStyle? = nil) {
        choices.setLook(size, style)
    }

    private func heading(_ title: String) -> some View {
        Text(title).font(.headline).padding(.leading, 4)
    }

    private func caption(_ title: String) -> some View {
        Text(title.uppercased())
            .font(.system(size: 11, weight: .semibold))
            .tracking(0.6)
            .foregroundStyle(Palette.faint)
    }
}

