import SwiftUI

struct PlayerSettings: View {
    let choices: TrackChoices
    @Binding var statsShown: Bool
    @Binding var previewingLook: Bool
    var onClose: () -> Void

    private enum Page: String { case root, subtitles, appearance, audio, debug }
    @State private var page: Page = .root
    @State private var forward = true

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    switch page {
                    case .root: root
                    case .subtitles: subtitles
                    case .appearance: appearance
                    case .audio: audio
                    case .debug: debug
                    }
                }
                .id(page)
                .transition(.asymmetric(
                    insertion: .move(edge: forward ? .trailing : .leading).combined(with: .opacity),
                    removal: .opacity))
                .padding(.bottom, 16)
            }
            .scrollIndicators(.hidden)
        }
        .foregroundStyle(.white)
        .sensoryFeedback(.selection, trigger: choices.subtitleID)
        .sensoryFeedback(.selection, trigger: choices.audioIndex)
        .sensoryFeedback(.selection, trigger: statsShown)
        .onChange(of: page, initial: true) { _, now in previewingLook = now == .appearance }
        .onDisappear { previewingLook = false }
        #if DEBUG
        // -settingsPage <page>: open on that page, to look at it.
        .onAppear {
            let args = ProcessInfo.processInfo.arguments
            if let at = args.firstIndex(of: "-settingsPage"), at + 1 < args.count,
               let wanted = Page(rawValue: args[at + 1]) {
                page = wanted
            }
        }
        #endif
    }

    private var header: some View {
        HStack(spacing: 10) {
            if page != .root {
                Button { go(.root, forward: false) } label: {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 18, weight: .bold))
                        .frame(width: 44, height: 44)
                        .contentShape(.rect)
                }
                .buttonStyle(Pressed())
                .accessibilityLabel("Back")
            }
            Text(title).font(.title3.weight(.bold))
                .lineLimit(1).minimumScaleFactor(0.75)
            Spacer(minLength: 8)
            Button(action: onClose) {
                Image(systemName: "xmark")
                    .font(.system(size: 18, weight: .bold))
                    .frame(width: 44, height: 44)
                    .contentShape(.rect)
            }
            .buttonStyle(Pressed())
            .accessibilityLabel("Close settings")
        }
    }

    private var title: String {
        switch page {
        case .root: "Settings"
        case .subtitles: "Subtitles"
        case .appearance: "Subtitle Appearance"
        case .audio: "Audio"
        case .debug: "Debug"
        }
    }

    private var root: some View {
        Group {
            entry("Subtitles", systemImage: "captions.bubble",
                  value: choices.subtitles.first { $0.id == choices.subtitleID }?.label ?? "Off") {
                go(.subtitles)
            }
            entry("Subtitle Appearance", systemImage: "textformat.size",
                  value: "\(choices.size.label), \(choices.style.label)") { go(.appearance) }
            entry("Audio", systemImage: "speaker.wave.2",
                  value: choices.audio.first { $0.index == choices.audioIndex }?.label ?? "Default") {
                go(.audio)
            }
            entry("Debug", systemImage: "ladybug", value: statsShown ? "On" : "Off") {
                go(.debug)
            }
        }
    }

    private var subtitles: some View {
        Group {
            choice("Off", chosen: choices.subtitleID == nil) { choices.chooseSubtitle(nil) }
            ForEach(choices.subtitles) { track in
                choice(track.label, chosen: track.id == choices.subtitleID) {
                    choices.chooseSubtitle(track.id)
                }
            }
        }
    }

    private var audio: some View {
        ForEach(choices.audio) { track in
            choice(track.label, chosen: track.index == choices.audioIndex) {
                choices.chooseAudio(track.index)
            }
        }
    }

    private var appearance: some View {
        Group {
            Captions(lines: ["This is how subtitles will look."], size: choices.size,
                     style: choices.style, height: 380)
                .frame(maxWidth: .infinity, minHeight: 64)
                .background(
                    LinearGradient(colors: [Color(white: 0.28), Color(white: 0.12)],
                                   startPoint: .top, endPoint: .bottom),
                    in: .rect(cornerRadius: 16))
            sectionLabel("Size")
            pills(SubtitleSize.allCases, label: \.label, chosen: { $0 == choices.size }) {
                choices.setLook($0, nil)
            }
            sectionLabel("Style")
            pills(SubtitleStyle.allCases, label: \.label, chosen: { $0 == choices.style }) {
                choices.setLook(nil, $0)
            }
        }
    }

    private var debug: some View {
        Group {
            sectionLabel("Playback stats")
            choice("Off", chosen: !statsShown) { statsShown = false }
            choice("On", chosen: statsShown) { statsShown = true }
        }
    }

    private func entry(_ title: String, systemImage: String, value: String,
                       action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: systemImage)
                    .font(.system(size: 17, weight: .semibold))
                    .frame(width: 24)
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(.body.weight(.semibold))
                    Text(value).font(.footnote).foregroundStyle(Palette.dim)
                        .lineLimit(1).truncationMode(.middle)
                }
                Spacer(minLength: 8)
                Image(systemName: "chevron.right")
                    .font(.footnote.weight(.bold))
                    .foregroundStyle(Palette.dim)
            }
            .padding(.horizontal, 18)
            .padding(.vertical, 11)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.chip, in: .capsule)
            .contentShape(.capsule)
        }
        .buttonStyle(Pressed())
    }

    private func choice(_ title: String, chosen: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Text(title).font(.body.weight(.semibold)).lineLimit(1)
                Spacer(minLength: 8)
                if chosen { Image(systemName: "checkmark").font(.footnote.weight(.bold)) }
            }
            .foregroundStyle(chosen ? .black : .white)
            .padding(.horizontal, 18)
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(chosen ? Color.white : Palette.chip, in: .capsule)
            .contentShape(.capsule)
        }
        .buttonStyle(Pressed())
    }

    private func pills<Item: Hashable>(_ items: [Item], label: KeyPath<Item, String>,
                                       chosen: @escaping (Item) -> Bool,
                                       action: @escaping (Item) -> Void) -> some View {
        FlowRow(spacing: 8) {
            ForEach(items, id: \.self) { item in
                let on = chosen(item)
                Button { action(item) } label: {
                    Text(item[keyPath: label])
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(on ? .black : .white)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)
                        .background(on ? Color.white : Palette.chip, in: .capsule)
                        .contentShape(.capsule)
                }
                .buttonStyle(Pressed())
            }
        }
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text.uppercased())
            .font(.caption.weight(.bold))
            .foregroundStyle(Palette.faint)
            .padding(.top, 6)
            .padding(.leading, 4)
    }

    private func go(_ next: Page, forward: Bool = true) {
        self.forward = forward
        withAnimation(.snappy(duration: 0.28)) { page = next }
    }
}

private struct Pressed: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .opacity(configuration.isPressed ? 0.75 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

private struct FlowRow: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(width: proposal.width ?? .infinity, subviews: subviews)
        let height = rows.reduce(0) { $0 + $1.height } + spacing * CGFloat(max(0, rows.count - 1))
        return CGSize(width: proposal.width ?? rows.map(\.width).max() ?? 0, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(width: bounds.width, subviews: subviews) {
            var x = bounds.minX
            for index in row.items {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row { var items: [Int] = []; var width: CGFloat = 0; var height: CGFloat = 0 }

    private func arrange(width: CGFloat, subviews: Subviews) -> [Row] {
        var rows: [Row] = [Row()]
        for (index, subview) in subviews.enumerated() {
            let size = subview.sizeThatFits(.unspecified)
            if !rows[rows.count - 1].items.isEmpty, rows[rows.count - 1].width + spacing + size.width > width {
                rows.append(Row())
            }
            var row = rows[rows.count - 1]
            row.width += (row.items.isEmpty ? 0 : spacing) + size.width
            row.height = max(row.height, size.height)
            row.items.append(index)
            rows[rows.count - 1] = row
        }
        return rows
    }
}
