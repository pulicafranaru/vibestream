import SwiftUI

// Only shown while something plays elsewhere.
struct PlayingElsewhereRow: View {
    var width: CGFloat = 260
    @State private var renaming: DeviceRename?
    private var cast: Cast { Cast.shared }

    var body: some View {
        if !cast.elsewhere.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text("Playing on Other Devices")
                    .font(.system(size: 17, weight: .bold))
                    .padding(.horizontal, 16)
                ScrollView(.horizontal) {
                    LazyHStack(spacing: 12) {
                        ForEach(cast.elsewhere) { device in
                            ElsewhereCard(device: device, width: width)
                                .onTapGesture { cast.follow(remoteFor: device) }
                                .accessibilityAddTraits(.isButton)
                                .contextMenu {
                                    Button("Control", systemImage: "playpause") {
                                        cast.follow(remoteFor: device)
                                    }
                                    Button("Rename \(device.name)", systemImage: "pencil") {
                                        renaming = DeviceRename(device)
                                    }
                                    Button("Stop Playing", systemImage: "stop.fill", role: .destructive) {
                                        Task { await cast.send(CastCommand(type: "stop"), to: device) }
                                    }
                                }
                        }
                    }
                    .padding(.horizontal, 16)
                }
                .scrollIndicators(.hidden)
            }
            .deviceRename($renaming)
            .transition(.opacity)
        }
    }
}

private struct ElsewhereCard: View {
    let device: CastDevice
    let width: CGFloat
    @State private var card: Card?

    var body: some View {
        let playing = device.playing
        let progress = playing.map { $0.duration > 0 ? min(1, $0.position / $0.duration) : 0 } ?? 0
        VStack(alignment: .leading, spacing: 0) {
            RemoteImage(url: (card?.backdrop ?? card?.poster).flatMap(URL.init(string:)))
                .frame(width: width, height: width * 9 / 16)
                .clipped()
                .overlay {
                    LinearGradient(colors: [.black.opacity(0.55), .clear, .black.opacity(0.8)],
                                   startPoint: .top, endPoint: .bottom)
                }
                .overlay(alignment: .topLeading) {
                    HStack(spacing: 6) {
                        Image(systemName: device.symbol).font(.system(size: 12, weight: .semibold))
                        Text(device.name).font(.caption.weight(.semibold)).lineLimit(1)
                    }
                    .padding(.horizontal, 10)
                    .frame(height: 26)
                    .glassEffect(.regular.tint(.black.opacity(0.3)), in: .capsule)
                    .padding(8)
                }
                .overlay(alignment: .bottomLeading) {
                    HStack(alignment: .bottom, spacing: 8) {
                        VStack(alignment: .leading, spacing: 1) {
                            Text(playing?.title ?? "")
                                .font(.subheadline.weight(.bold))
                                .lineLimit(1)
                            if let detail = playing?.presentation?.episodeLine ?? playing?.detail {
                                Text(detail)
                                    .font(.caption)
                                    .foregroundStyle(.white.opacity(0.8))
                                    .lineLimit(1)
                            }
                        }
                        Spacer(minLength: 0)
                        Image(systemName: playing?.paused == true ? "pause.fill" : "waveform")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(Palette.accent)
                            .symbolEffect(.variableColor.iterative, isActive: playing?.paused == false)
                    }
                    .padding(.horizontal, 10)
                    .padding(.bottom, 8)
                }

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Rectangle().fill(.white.opacity(0.28))
                    Rectangle().fill(Palette.accent).frame(width: geo.size.width * progress)
                }
            }
            .frame(width: width, height: 3)
            .animation(.linear(duration: 0.5), value: progress)
        }
        .clipShape(.rect(cornerRadius: 8))
        .foregroundStyle(.white)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(playing?.title ?? "") on \(device.name)")
        .task(id: playing?.mediaID) {
            if let id = playing?.mediaID, card?.mediaID != id {
                card = try? await APIClient.shared.media(id)
            }
        }
    }
}

struct DeviceRename: Identifiable {
    let id: String
    let current: String
    let own: String?

    init(_ device: CastDevice) {
        id = device.id
        current = device.name
        own = device.ownName
    }

    init(id: String, current: String, own: String?) {
        self.id = id
        self.current = current
        self.own = own
    }
}

extension View {
    func deviceRename(_ target: Binding<DeviceRename?>) -> some View {
        modifier(DeviceRenamePrompt(target: target))
    }
}

private struct DeviceRenamePrompt: ViewModifier {
    @Binding var target: DeviceRename?
    @State private var draft = ""

    func body(content: Content) -> some View {
        content
            .alert("Name This Device",
                   isPresented: Binding(get: { target != nil }, set: { if !$0 { target = nil } }),
                   presenting: target) { device in
                TextField(device.own ?? "Name", text: $draft)
                    .textInputAutocapitalization(.words)
                Button("Save") {
                    let name = draft
                    Task { await Cast.shared.rename(device.id, to: name) }
                }
                Button("Cancel", role: .cancel) {}
            } message: { device in
                Text(device.own.map { "Every device will show this name. Leave it empty to go back to \"\($0)\"." }
                     ?? "Every device will show this name.")
            }
            .onChange(of: target?.id) {
                draft = target.map { $0.current == $0.own ? "" : $0.current } ?? ""
            }
    }
}
