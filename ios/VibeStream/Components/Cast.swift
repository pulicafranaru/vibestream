import Security
import SwiftUI
import UIKit

// Play on another device: the other app plays from the server and this one becomes
// its remote. This app also receives play commands from others.

struct CastPlaying: Codable, Hashable, Sendable {
    var playID: String
    var mediaID: Int?
    var title: String
    var detail: String?
    var position: Double
    var duration: Double
    var paused: Bool
    var presentation: PlayInfo.Presentation?
    var subtitles: [PlayInfo.Track]?
    var audio: [PlayInfo.AudioTrack]?
    var subtitleID: String?
    var audioIndex: Int?
    var subtitleSize: SubtitleSize?
    var subtitleStyle: SubtitleStyle?

    enum CodingKeys: String, CodingKey {
        case title, detail, position, duration, paused, presentation, subtitles, audio
        case playID = "play_id"
        case mediaID = "media_id"
        case subtitleID = "subtitle_id"
        case audioIndex = "audio_index"
        case subtitleSize = "subtitle_size"
        case subtitleStyle = "subtitle_style"
    }

    /// Unknown sizes and styles from a newer app decode as none rather than failing.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        playID = try c.decode(String.self, forKey: .playID)
        mediaID = try c.decodeIfPresent(Int.self, forKey: .mediaID)
        title = try c.decode(String.self, forKey: .title)
        detail = try c.decodeIfPresent(String.self, forKey: .detail)
        position = try c.decode(Double.self, forKey: .position)
        duration = try c.decode(Double.self, forKey: .duration)
        paused = try c.decode(Bool.self, forKey: .paused)
        presentation = try? c.decodeIfPresent(PlayInfo.Presentation.self, forKey: .presentation)
        subtitles = try? c.decodeIfPresent([PlayInfo.Track].self, forKey: .subtitles)
        audio = try? c.decodeIfPresent([PlayInfo.AudioTrack].self, forKey: .audio)
        subtitleID = try? c.decodeIfPresent(String.self, forKey: .subtitleID)
        audioIndex = try? c.decodeIfPresent(Int.self, forKey: .audioIndex)
        subtitleSize = try? c.decodeIfPresent(SubtitleSize.self, forKey: .subtitleSize)
        subtitleStyle = try? c.decodeIfPresent(SubtitleStyle.self, forKey: .subtitleStyle)
    }

    init(playID: String, mediaID: Int?, title: String, detail: String?, position: Double,
         duration: Double, paused: Bool, presentation: PlayInfo.Presentation? = nil,
         subtitles: [PlayInfo.Track]? = nil, audio: [PlayInfo.AudioTrack]? = nil,
         subtitleID: String? = nil, audioIndex: Int? = nil,
         subtitleSize: SubtitleSize? = nil, subtitleStyle: SubtitleStyle? = nil) {
        self.playID = playID
        self.mediaID = mediaID
        self.title = title
        self.detail = detail
        self.position = position
        self.duration = duration
        self.paused = paused
        self.presentation = presentation
        self.subtitles = subtitles
        self.audio = audio
        self.subtitleID = subtitleID
        self.audioIndex = audioIndex
        self.subtitleSize = subtitleSize
        self.subtitleStyle = subtitleStyle
    }
}

struct CastDevice: Codable, Hashable, Identifiable, Sendable {
    var id: String
    var name: String
    var ownName: String?
    var kind: String
    var profileID: Int?
    var playing: CastPlaying?

    enum CodingKeys: String, CodingKey {
        case id, name, kind, playing
        case ownName = "own_name"
        case profileID = "profile_id"
    }

    var symbol: String {
        switch kind {
        case "tv": "tv"
        case "tablet": "ipad.landscape"
        case "phone": "iphone"
        default: "laptopcomputer"
        }
    }
}

struct CastCommand: Codable, Sendable {
    var type: String
    var playID: String?
    var title: String?
    var position: Double?
    var delta: Double?
    var profileID: Int?
    var sender: String?
    var senderID: String?
    /// "subtitle": a track's id, or "off".
    var subtitleID: String?
    /// "audio": a track's index.
    var audioIndex: Int?
    /// "appearance": either or both.
    var subtitleSize: String?
    var subtitleStyle: String?

    enum CodingKeys: String, CodingKey {
        case type, title, position, delta, sender
        case playID = "play_id"
        case profileID = "profile_id"
        case subtitleID = "subtitle_id"
        case audioIndex = "audio_index"
        case subtitleSize = "subtitle_size"
        case subtitleStyle = "subtitle_style"
        case senderID = "sender_id"
    }

    var body: [String: Any] {
        var b: [String: Any] = ["type": type]
        if let playID { b["play_id"] = playID }
        if let title { b["title"] = title }
        if let position { b["position"] = position }
        if let delta { b["delta"] = delta }
        if let profileID { b["profile_id"] = profileID }
        if let sender { b["sender"] = sender }
        if let senderID { b["sender_id"] = senderID }
        if let subtitleID { b["subtitle_id"] = subtitleID }
        if let audioIndex { b["audio_index"] = audioIndex }
        if let subtitleSize { b["subtitle_size"] = subtitleSize }
        if let subtitleStyle { b["subtitle_style"] = subtitleStyle }
        return b
    }
}

private struct Ack: Decodable { var ok: Bool? }
private struct Inbox: Decodable { var commands: [CastCommand] }
private struct DeviceList: Decodable { var devices: [CastDevice] }

/// All optional, so an older server still decodes.
private struct HelloAnswer: Decodable {
    var ok: Bool?
    var token: String?
    var profileID: Int?
    var pinRequired: Bool?

    enum CodingKeys: String, CodingKey {
        case ok, token
        case profileID = "profile_id"
        case pinRequired = "pin_required"
    }
}

/// The token is a secret, so it lives in the Keychain, filed under the id it was
/// issued for.
private enum CastKeychain {
    private static let service = "xyz.pulicafranaru.vibestream.cast"

    private static func query(_ id: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: id]
    }

    static func token(for id: String) -> String? {
        var lookup = query(id)
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var found: AnyObject?
        guard SecItemCopyMatching(lookup as CFDictionary, &found) == errSecSuccess,
              let data = found as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func save(_ token: String, for id: String) {
        let data = Data(token.utf8)
        let status = SecItemUpdate(query(id) as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        guard status == errSecItemNotFound else { return }
        var add = query(id)
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        _ = SecItemAdd(add as CFDictionary, nil)
    }

    static func delete(for id: String) {
        _ = SecItemDelete(query(id) as CFDictionary)
    }
}

@MainActor @Observable
final class Cast {
    static let shared = Cast()

    private static let idKey = "vibestream.castID"

    private static func storedID() -> String {
        if let id = UserDefaults.standard.string(forKey: idKey) { return id }
        let id = "ios-" + UUID().uuidString.lowercased()
        UserDefaults.standard.set(id, forKey: idKey)
        return id
    }

    private(set) var id: String
    private var token: String?
    /// Sent with the next hello as that profile, then forgotten. Never stored.
    private var pins: [Int: String] = [:]

    private init() {
        id = Cast.storedID()
        token = CastKeychain.token(for: id)
    }

    private var tokenHeader: [String: String] {
        token.map { ["X-Cast-Token": $0] } ?? [:]
    }

    func unlocked(_ profile: Int, pin: String) { pins[profile] = pin }

    let name = UIDevice.current.model
    private var kind: String { UIDevice.current.userInterfaceIdiom == .pad ? "tablet" : "phone" }

    var onPlay: ((CastCommand) -> Void)?

    private var loop: Task<Void, Never>?
    private var greeted = false
    private var controls: [UUID: (CastCommand) -> Void] = [:]
    private var lastState: CastPlaying??

    func start(profile: Int?) {
        loop?.cancel()
        greeted = false
        loop = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                do {
                    if !self.greeted {
                        try await self.hello(profile: profile)
                        self.greeted = true
                    }
                    let inbox = try await APIClient.shared.cast(
                        Inbox.self, "inbox", query: ["id": self.id, "wait": "25"],
                        headers: self.tokenHeader, timeout: 40)
                    for command in inbox.commands { self.handle(command) }
                } catch APIError.status(404, _) {
                    // The server restarted and forgot this device: say hello again.
                    self.greeted = false
                } catch APIError.status(403, let detail) {
                    // Refused: hello again. A wrong PIN is dropped; otherwise the token was lost, so
                    // this becomes a new device.
                    if self.greeted {
                        self.greeted = false
                    } else if detail.contains("wrong pin") {
                        if let profile { self.pins[profile] = nil }
                    } else {
                        self.startOver()
                    }
                    try? await Task.sleep(for: .seconds(1))
                } catch {
                    if Task.isCancelled { return }
                    try? await Task.sleep(for: .seconds(5))
                }
            }
        }
    }

    private func hello(profile: Int?) async throws {
        var body: [String: Any] = ["id": id, "name": name, "kind": kind]
        if let profile { body["profile_id"] = profile }
        var headers = tokenHeader
        let pin = profile.flatMap { pins[$0] }
        if let pin { headers["X-Profile-Pin"] = pin }
        let answer = try await APIClient.shared.cast(
            HelloAnswer.self, "hello", method: "POST", body: body, headers: headers)
        guard let given = answer.token else { return }
        if token == nil {
            token = given
            CastKeychain.save(given, for: id)
            // Hello again with the PIN, which binds the id.
            if pin != nil { try await hello(profile: profile) }
            return
        }
        // The server now remembers the PIN for this device, so it is sent once.
        if let profile, pin != nil, answer.profileID == profile { pins[profile] = nil }
    }

    private func startOver() {
        CastKeychain.delete(for: id)
        token = nil
        UserDefaults.standard.removeObject(forKey: Cast.idKey)
        id = Cast.storedID()
    }

    private func handle(_ command: CastCommand) {
        if command.type == "play" { onPlay?(command) }
        else { controls.values.forEach { $0(command) } }
    }

    func onControl(_ handler: @escaping (CastCommand) -> Void) -> UUID {
        let token = UUID()
        controls[token] = handler
        return token
    }

    func removeControl(_ token: UUID) { controls[token] = nil }

    func report(_ playing: CastPlaying?) {
        guard greeted, lastState != .some(playing) else { return }
        lastState = .some(playing)
        var body: [String: Any] = ["id": id]
        if let playing, let data = try? JSONEncoder().encode(playing),
           let object = try? JSONSerialization.jsonObject(with: data) {
            body["playing"] = object
        } else {
            body["playing"] = NSNull()
        }
        let headers = tokenHeader
        Task {
            _ = try? await APIClient.shared.cast(Ack.self, "state", method: "POST", body: body, headers: headers)
        }
    }

    func devices() async -> [CastDevice] {
        (try? await APIClient.shared.cast(DeviceList.self, "devices", query: ["exclude": id],
                                          headers: tokenHeader).devices) ?? []
    }

    /// A phone is visible only to its own profile.
    private func record(_ deviceID: String) async throws -> CastDevice {
        try await APIClient.shared.cast(CastDevice.self, "devices/\(deviceID)",
                                        query: ["sender_id": id], headers: tokenHeader)
    }

    @discardableResult
    func send(_ command: CastCommand, to device: CastDevice) async -> Bool {
        var command = command
        command.sender = command.sender ?? name
        command.senderID = id
        do {
            _ = try await APIClient.shared.cast(Ack.self, "devices/\(device.id)/command",
                                                method: "POST", body: command.body, headers: tokenHeader)
            return true
        } catch {
            return false
        }
    }

    @discardableResult
    func rename(_ deviceID: String, to name: String) async -> Bool {
        struct Renamed: Decodable { var name: String? }
        guard let renamed = try? await APIClient.shared.cast(
            Renamed.self, "devices/\(deviceID)/name", method: "PUT", body: ["name": name]) else { return false }
        let shown = renamed.name ?? name
        for index in elsewhere.indices where elsewhere[index].id == deviceID { elsewhere[index].name = shown }
        if target?.id == deviceID { target?.name = shown }
        if deviceID == id { myName = shown }
        return true
    }

    private(set) var myName: String?

    private(set) var elsewhere: [CastDevice] = []
    private var elsewhereLoop: Task<Void, Never>?

    func watchElsewhere() {
        guard elsewhereLoop == nil else { return }
        elsewhereLoop = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                let all = await self.devices()
                let playing = all.filter { $0.playing != nil }
                if playing != self.elsewhere {
                    withAnimation(.snappy) { self.elsewhere = playing }
                }
                if let me = try? await self.record(self.id) {
                    self.myName = me.name
                }
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    func follow(remoteFor device: CastDevice) {
        target = device
        state = device.playing
        follow(device)
        remoteShown = true
    }

    private(set) var target: CastDevice?
    private(set) var state: CastPlaying?
    var remoteShown = false
    private var watch: Task<Void, Never>?

    func play(_ request: PlayRequest, at position: Double?, on device: CastDevice, profile: Int?) async -> Bool {
        let ok = await send(CastCommand(type: "play", playID: request.playID, title: request.title,
                                        position: position, profileID: profile), to: device)
        guard ok else { return false }
        target = device
        state = nil
        follow(device)
        // Deferred: a sheet cannot appear while the player or title page is still leaving.
        Task {
            try? await Task.sleep(for: .milliseconds(800))
            if target?.id == device.id { remoteShown = true }
        }
        return true
    }

    private func follow(_ device: CastDevice) {
        watch?.cancel()
        watch = Task { [weak self] in
            // Grace period for the other app to open its player before "nothing playing"
            // means it stopped.
            let started = Date()
            var seen = false
            while !Task.isCancelled {
                guard let self else { return }
                do {
                    let now = try await self.record(device.id)
                    self.state = now.playing
                    if now.playing != nil { seen = true }
                    if now.playing == nil && (seen || Date().timeIntervalSince(started) > 20) {
                        self.end()
                        return
                    }
                } catch APIError.status(404, _) {
                    self.end()
                    return
                } catch {}
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    func control(_ command: CastCommand) {
        guard let target else { return }
        // Optimistic, rather than waiting for the next state.
        if var shown = state {
            switch command.type {
            case "pause": shown.paused = true
            case "resume": shown.paused = false
            case "seek": shown.position = command.position ?? shown.position
            case "skip": shown.position = max(0, min(shown.duration, shown.position + (command.delta ?? 0)))
            case "subtitle": shown.subtitleID = command.subtitleID == "off" ? nil : command.subtitleID
            case "audio": shown.audioIndex = command.audioIndex
            case "appearance":
                if let size = command.subtitleSize.flatMap(SubtitleSize.init(rawValue:)) { shown.subtitleSize = size }
                if let style = command.subtitleStyle.flatMap(SubtitleStyle.init(rawValue:)) { shown.subtitleStyle = style }
            default: break
            }
            state = shown
        }
        Task { await send(command, to: target) }
    }

    func playThere(_ playID: String, title: String, profile: Int?) {
        guard let target else { return }
        Task { await send(CastCommand(type: "play", playID: playID, title: title, profileID: profile), to: target) }
    }

    var trackChoices: TrackChoices? {
        guard let state, let audio = state.audio, let subtitles = state.subtitles else { return nil }
        return TrackChoices(
            audio: audio, audioIndex: state.audioIndex,
            subtitles: subtitles, subtitleID: state.subtitleID,
            size: state.subtitleSize ?? .medium, style: state.subtitleStyle ?? .shadow,
            chooseAudio: { [weak self] in self?.control(CastCommand(type: "audio", audioIndex: $0)) },
            chooseSubtitle: { [weak self] in self?.control(CastCommand(type: "subtitle", subtitleID: $0 ?? "off")) },
            setLook: { [weak self] size, style in
                self?.control(CastCommand(type: "appearance", subtitleSize: size?.rawValue,
                                          subtitleStyle: style?.rawValue))
            })
    }

    func stop() {
        control(CastCommand(type: "stop"))
        end()
    }

    private func end() {
        watch?.cancel()
        withAnimation(.easeOut(duration: 0.25)) {
            target = nil
            state = nil
            remoteShown = false
        }
    }
}

struct CastPicker: View {
    var onChoose: (CastDevice) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var devices: [CastDevice]?
    @State private var renaming: DeviceRename?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 0) {
                    if let devices, devices.isEmpty {
                        VStack(spacing: 10) {
                            Image(systemName: "tv.slash").font(.system(size: 34)).foregroundStyle(Palette.faint)
                            Text("Nothing to play on")
                                .font(.headline)
                            Text("Open VibeStream on the TV or another device, and it will show up here.")
                                .font(.subheadline)
                                .foregroundStyle(Palette.dim)
                                .multilineTextAlignment(.center)
                        }
                        .padding(.top, 40)
                        .padding(.horizontal, 30)
                    } else if let devices {
                        VStack(spacing: 0) {
                            ForEach(devices) { device in
                                Button {
                                    dismiss()
                                    onChoose(device)
                                } label: { row(device) }
                                .buttonStyle(.plain)
                                .contextMenu {
                                    Button("Rename", systemImage: "pencil") { renaming = DeviceRename(device) }
                                }
                            }
                        }
                        .background(Color.white.opacity(0.06), in: .rect(cornerRadius: 16))
                        .padding(.horizontal, 18)
                        Text("Touch and hold a device to rename it.")
                            .font(.footnote)
                            .foregroundStyle(Palette.faint)
                            .padding(.top, 10)
                    } else {
                        BootSpinner(size: 36, line: 3).padding(.top, 50)
                    }
                }
                .padding(.top, 8)

                thisDevice
                    .padding(.horizontal, 18)
                    .padding(.top, 26)
            }
            .background(Palette.ground)
            .navigationTitle("Play on")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { CloseButton { dismiss() } }
            }
        }
        .preferredColorScheme(.dark)
        .deviceRename($renaming)
        .task {
            while !Task.isCancelled {
                devices = await Cast.shared.devices()
                try? await Task.sleep(for: .seconds(3))
            }
        }
        .onChange(of: renaming == nil) { _, done in
            if done { Task { devices = await Cast.shared.devices() } }
        }
    }

    private var thisDevice: some View {
        let cast = Cast.shared
        return HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("This \(cast.name)")
                    .font(.footnote)
                    .foregroundStyle(Palette.faint)
                Text(cast.myName ?? cast.name).font(.body.weight(.semibold))
            }
            Spacer(minLength: 0)
            Button("Rename") {
                renaming = DeviceRename(id: cast.id, current: cast.myName ?? cast.name, own: cast.name)
            }
            .font(.subheadline.weight(.semibold))
            .buttonStyle(.plain)
            .foregroundStyle(Palette.accent)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(Color.white.opacity(0.06), in: .rect(cornerRadius: 16))
    }

    private func row(_ device: CastDevice) -> some View {
        HStack(spacing: 14) {
            Image(systemName: device.symbol)
                .font(.system(size: 22))
                .frame(width: 34)
            VStack(alignment: .leading, spacing: 2) {
                Text(device.name).font(.body.weight(.semibold))
                if let playing = device.playing {
                    Text("Playing \(playing.title)")
                        .font(.footnote)
                        .foregroundStyle(Palette.dim)
                        .lineLimit(1)
                } else if let own = device.ownName, own != device.name {
                    Text(own)
                        .font(.footnote)
                        .foregroundStyle(Palette.dim)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Palette.faint)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 15)
        .contentShape(.rect)
    }
}

struct CastRemote: View {
    var onTitle: (Card) -> Void = { _ in }
    @Environment(AppState.self) private var appState
    @Environment(\.dismiss) private var dismiss
    @State private var card: Card?
    private var cast: Cast { Cast.shared }

    var body: some View {
        let state = cast.state
        VStack(spacing: 0) {
            strip(state)
            PlayerPage(playID: state?.playID ?? "",
                       title: state?.title ?? "Starting…",
                       mediaID: state?.mediaID,
                       presentation: state?.presentation,
                       loaded: state != nil,
                       onEpisode: { item in
                           guard let playID = item.playID else { return }
                           cast.playThere(playID, title: state?.presentation?.title ?? state?.title ?? "",
                                          profile: appState.profile?.id)
                       },
                       tracks: cast.trackChoices,
                       onTitle: { other in
                           dismiss()
                           onTitle(other)
                       })
        }
        .background(Palette.ground)
        .preferredColorScheme(.dark)
        .task(id: state?.mediaID) {
            if let id = state?.mediaID, card?.mediaID != id {
                card = try? await APIClient.shared.media(id)
            }
        }
        .onChange(of: cast.target == nil) { _, gone in if gone { dismiss() } }
    }

    private func strip(_ state: CastPlaying?) -> some View {
        let art = (card?.backdrop ?? card?.poster).flatMap(URL.init(string:))
        return Color.clear
            .aspectRatio(16 / 9, contentMode: .fit)
            .overlay { RemoteImage(url: art) }
            .overlay {
                LinearGradient(colors: [.black.opacity(0.7), .black.opacity(0.35), .black.opacity(0.75)],
                               startPoint: .top, endPoint: .bottom)
            }
            .overlay { controls(state) }
            .clipped()
            .foregroundStyle(.white)
    }

    private func controls(_ state: CastPlaying?) -> some View {
        ZStack {
            VStack(spacing: 0) {
                HStack(spacing: 8) {
                    Button { dismiss() } label: {
                        Image(systemName: "chevron.down")
                            .font(.system(size: 18, weight: .semibold))
                            .frame(width: 44, height: 44)
                            .contentShape(.rect)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Hide remote")
                    if let target = cast.target {
                        Label("Playing on \(target.name)", systemImage: target.symbol)
                            .font(.footnote.weight(.semibold))
                            .lineLimit(1)
                            .foregroundStyle(Palette.good)
                    }
                    Spacer(minLength: 8)
                    Button { cast.stop(); dismiss() } label: {
                        Text("Stop")
                            .font(.subheadline.weight(.semibold))
                            .padding(.horizontal, 14)
                            .frame(height: 32)
                            .background(Capsule().fill(.white.opacity(0.18)))
                            .contentShape(.capsule)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Stop playing on the TV")
                }
                .padding(.leading, 4)
                .padding(.trailing, 12)
                .padding(.top, 6)
                Spacer(minLength: 0)
                RemoteScrubber(state: state) { cast.control(CastCommand(type: "seek", position: $0)) }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 10)
            }

            HStack(spacing: 46) {
                Button { cast.control(CastCommand(type: "skip", delta: -10)) } label: {
                    Image(systemName: "gobackward.10").font(.system(size: 24))
                }
                Button {
                    cast.control(CastCommand(type: (state?.paused ?? false) ? "resume" : "pause"))
                } label: {
                    Image(systemName: (state?.paused ?? false) ? "play.fill" : "pause.fill")
                        .font(.system(size: 34))
                        .frame(width: 44)
                        .contentTransition(.symbolEffect(.replace))
                }
                Button { cast.control(CastCommand(type: "skip", delta: 10)) } label: {
                    Image(systemName: "goforward.10").font(.system(size: 24))
                }
            }
            .buttonStyle(.plain)
            .shadow(color: .black.opacity(0.4), radius: 4)
            .disabled(state == nil)
            .opacity(state == nil ? 0.4 : 1)
        }
    }
}

private struct RemoteScrubber: View {
    let state: CastPlaying?
    var onSeek: (Double) -> Void
    @State private var dragging: Double?

    var body: some View {
        let duration = max(state?.duration ?? 0, 1)
        let shown = dragging ?? state?.position ?? 0
        HStack(spacing: 12) {
            GeometryReader { geo in
                let width = geo.size.width
                let fraction = min(1, max(0, shown / duration))
                ZStack(alignment: .leading) {
                    Capsule().fill(.white.opacity(0.3)).frame(height: 4)
                    Capsule().fill(Palette.accent).frame(width: width * fraction, height: 4)
                    Circle()
                        .fill(Palette.accent)
                        .frame(width: dragging != nil ? 18 : 13, height: dragging != nil ? 18 : 13)
                        .offset(x: width * fraction - (dragging != nil ? 9 : 6.5))
                }
                .frame(height: 26)
                .contentShape(.rect)
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { value in
                            guard state != nil else { return }
                            dragging = min(1, max(0, value.location.x / width)) * duration
                        }
                        .onEnded { _ in
                            if let dragging { onSeek(dragging) }
                            dragging = nil
                        }
                )
            }
            .frame(height: 26)
            Text(timecode(max(0, duration - shown)))
                .font(.footnote.monospacedDigit())
                .fixedSize()
        }
        .opacity(state == nil ? 0.4 : 1)
        .animation(.easeOut(duration: 0.12), value: dragging != nil)
    }

    private func timecode(_ seconds: Double) -> String {
        let s = Int(seconds)
        return s >= 3600
            ? String(format: "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60)
            : String(format: "%d:%02d", s / 60, s % 60)
    }
}

struct CastBar: View {
    private var cast: Cast { Cast.shared }

    var body: some View {
        if let target = cast.target {
            let state = cast.state
            HStack(spacing: 12) {
                Image(systemName: target.symbol)
                    .font(.system(size: 17))
                    .foregroundStyle(Palette.good)
                VStack(alignment: .leading, spacing: 1) {
                    Text(state?.title ?? "Starting…")
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(1)
                    Text("Playing on \(target.name)")
                        .font(.caption)
                        .foregroundStyle(Palette.dim)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
                Button {
                    cast.control(CastCommand(type: (state?.paused ?? false) ? "resume" : "pause"))
                } label: {
                    Image(systemName: (state?.paused ?? false) ? "play.fill" : "pause.fill")
                        .font(.system(size: 18))
                        .frame(width: 40, height: 40)
                        .contentTransition(.symbolEffect(.replace))
                }
                .buttonStyle(.plain)
                .disabled(state == nil)
            }
            .padding(.leading, 16)
            .padding(.trailing, 8)
            .padding(.vertical, 6)
            .background(Capsule().fill(Color(white: 0.12)))
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.09), lineWidth: 1))
            .shadow(color: .black.opacity(0.5), radius: 14, y: 4)
            .contentShape(.capsule)
            .onTapGesture { cast.remoteShown = true }
            .foregroundStyle(.white)
            .frame(maxWidth: 420)
            .padding(.horizontal, 18)
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }
}
