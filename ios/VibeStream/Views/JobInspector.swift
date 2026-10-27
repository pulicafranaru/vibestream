import SwiftUI

// The torrent behind a download. Trackers appear by host only: their URLs carry the passkey.
struct JobInspector: View {
    @State var job: DownloadJob
    var onPlay: (DownloadJob) -> Void
    var onChange: () async -> Void

    @Environment(AppState.self) private var state
    @Environment(\.dismiss) private var dismiss
    @State private var data: JobInspection?
    @State private var loadError: String?
    @State private var confirmingDelete = false
    @State private var confirmingSource = false
    @State private var working = false

    var body: some View {
        ScrollViewReader { proxy in
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                if let data {
                    if !data.live {
                        Label("qBittorrent is not answering, so this is what was last recorded.",
                              systemImage: "exclamationmark.triangle")
                            .font(.footnote)
                            .foregroundStyle(.orange)
                    }
                    activity(data)
                    if data.pieces.count > 0 { pieces(data) }
                    if !data.files.isEmpty { files(data) }
                    if data.live { peers(data) }
                    if !data.trackers.isEmpty { trackers(data) }
                    information(data)
                    if let release = data.release { releaseFacts(release) }
                } else if let loadError {
                    Text(loadError).font(.footnote).foregroundStyle(Palette.dim)
                } else {
                    BootSpinner(size: 32, line: 3).frame(maxWidth: .infinity).padding(.top, 40)
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 30)
        }
        .background(Palette.ground)
        .scrollIndicators(.hidden)
        #if DEBUG
        // -inspectSection <Title>: scrolled to that section, to look at it.
        .onChange(of: data != nil) { _, loaded in
            let args = ProcessInfo.processInfo.arguments
            if loaded, let at = args.firstIndex(of: "-inspectSection"), at + 1 < args.count {
                proxy.scrollTo(args[at + 1], anchor: .top)
            }
        }
        #endif
        }
        .navigationTitle("Details")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            while !Task.isCancelled {
                await load()
                try? await Task.sleep(for: .seconds(3))
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            RemoteImage(url: (job.episode?.still ?? job.backdrop ?? job.poster).flatMap(URL.init(string:)))
                .frame(maxWidth: .infinity)
                .frame(height: 180)
                .clipShape(.rect(cornerRadius: 14))

            Text(job.title).font(.title3.weight(.bold))
            if let line = [job.label, job.episode?.name].compactMap({ $0 }).joined(separator: " · ")
                .nilIfEmpty {
                Text(line).font(.subheadline.weight(.medium)).foregroundStyle(Palette.dim)
            }

            HStack(spacing: 6) {
                if job.state == "failed" { ErrorBadge(size: 16) }
                Text(stateWords).font(.subheadline.weight(.semibold))
            }
            if job.state == "downloading" || job.state == "paused" {
                ProgressView(value: min(1, job.percent / 100)).tint(Palette.accent)
            }

            HStack(spacing: 10) {
                if job.state == "ready" {
                    Button { onPlay(job) } label: {
                        Label("Play", systemImage: "play.fill").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.white)
                    .foregroundStyle(.black)
                }
                Button(role: .destructive) { confirmingDelete = true } label: {
                    Label("Delete", systemImage: "trash").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .tint(Palette.danger)
                .disabled(working)
            }
            .controlSize(.large)
            .padding(.top, 4)
            .confirmationDialog("Delete \(name)?", isPresented: $confirmingDelete,
                                titleVisibility: .visible) {
                Button(job.sizeBytes.map { "Delete and free \(fileSize($0))" } ?? "Delete",
                       role: .destructive) {
                    Task { await delete() }
                }
            } message: {
                Text(job.kind == "episode" && job.sharesTorrent
                     ? "This removes the episode from the server and from your library. The rest of the season stays."
                     : job.seeding.met
                     ? "This removes it and its files from the server."
                     : "This removes it and its files from the server. It has only \(job.seeding.detail), so deleting now counts as a hit and run on filelist.")
            }
        }
    }

    private var name: String { [job.title, job.label].compactMap { $0 }.joined(separator: " ") }

    private var stateWords: String {
        switch job.state {
        case "queued": return "Queued"
        case "paused": return "Paused at \(Int(job.percent))%"
        case "downloading":
            var parts = [job.percent >= 1 ? "Downloading \(Int(job.percent))%" : "Downloading"]
            if job.dlSpeed > 0 { parts.append("\(fileSize(job.dlSpeed))/s") }
            if let eta = job.etaSeconds, eta > 0, eta < 360_000 { parts.append("\(duration(eta)) left") }
            return parts.joined(separator: " · ")
        case "preparing": return job.preparePercent.map { "Preparing \(Int($0))%" } ?? "Preparing"
        case "failed": return job.errorMessage ?? "Something went wrong. Try again."
        default: return "Ready"
        }
    }

    private func activity(_ data: JobInspection) -> some View {
        let t = data.torrent
        return section("Activity") {
            facts([
                ("State", t.state.map(Self.qbitState)),
                ("Progress", t.progress.map { String(format: "%.1f%%", $0) }),
                ("Size", t.sizeBytes.map(fileSize)),
                ("Downloaded", t.downloadedBytes.map(fileSize)),
                ("Uploaded", t.uploadedBytes.map(fileSize)),
                ("Ratio", t.ratio.map { String(format: "%.2f", $0) }),
                ("Download speed", speeds(t.dlSpeed, t.dlSpeedAvg)),
                ("Upload speed", speeds(t.upSpeed, t.upSpeedAvg)),
                ("Time left", t.etaSeconds.flatMap { $0 > 0 && $0 < 8_640_000 ? duration($0) : nil }),
                ("Seeds", pair(t.seeds, t.seedsTotal)),
                ("Leechers", pair(t.leechers, t.leechersTotal)),
                ("Connections", pair(t.connections, t.connectionsLimit)),
                ("Wasted", t.wastedBytes.flatMap { $0 > 0 ? fileSize($0) : nil }),
                ("Active for", t.elapsedSeconds.flatMap { $0 > 0 ? duration($0) : nil }),
                ("Seeding for", t.seedingSeconds.flatMap { $0 > 0 ? duration($0) : nil }),
                ("Seeding goal", data.library.sourceRemoved ? nil :
                    (job.seeding.met ? "Met" : "Not yet: \(job.seeding.detail)")),
                ("Next announce", t.reannounceSeconds.flatMap { $0 > 0 ? duration($0) : nil }),
            ])
        }
    }

    private func pieces(_ data: JobInspection) -> some View {
        let cells = data.pieces
        let grid = Array(repeating: GridItem(.flexible(), spacing: 2), count: 24)
        return section("Pieces") {
            VStack(alignment: .leading, spacing: 10) {
                LazyVGrid(columns: grid, spacing: 2) {
                    ForEach(cells.have.indices, id: \.self) { i in
                        RoundedRectangle(cornerRadius: 2)
                            .fill(colour(have: cells.have[i],
                                         busy: i < cells.busy.count && cells.busy[i] == 1))
                            .aspectRatio(1, contentMode: .fit)
                    }
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(pieceCaption(data))

                Text(pieceCaption(data))
                    .font(.footnote)
                    .foregroundStyle(Palette.dim)
            }
        }
    }

    private func colour(have: Int, busy: Bool) -> Color {
        if busy { return .white }
        if have == 0 { return Color(white: 0.18) }
        return Palette.accent.opacity(0.3 + 0.7 * Double(have) / 100)
    }

    private func pieceCaption(_ data: JobInspection) -> String {
        let t = data.torrent
        var parts: [String] = []
        if let count = t.piecesCount {
            parts.append("\(count.formatted()) pieces" + (t.pieceSize.map { " of \(fileSize($0))" } ?? ""))
        }
        if let have = t.piecesHave { parts.append("\(have.formatted()) here") }
        return parts.joined(separator: " · ")
    }

    private func files(_ data: JobInspection) -> some View {
        section(data.files.count == 1 ? "File" : "Files (\(data.files.count))") {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(data.files) { file in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            if file.mine && data.files.count > 1 {
                                Circle().fill(Palette.accent).frame(width: 7, height: 7)
                                    .accessibilityLabel("This download")
                            }
                            Text((file.name as NSString).lastPathComponent)
                                .font(.system(size: 13, weight: file.mine ? .semibold : .regular))
                                .foregroundStyle(file.priority == 0 ? Palette.faint : .white)
                                .lineLimit(2)
                                .truncationMode(.middle)
                        }
                        HStack(spacing: 8) {
                            ProgressView(value: min(1, file.progress / 100))
                                .tint(file.priority == 0 ? Palette.faint : Palette.accent)
                            Text(file.priority == 0 ? "Skipped" : String(format: "%.0f%%", file.progress))
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(Palette.dim)
                                .frame(width: 58, alignment: .trailing)
                            Text(fileSize(file.sizeBytes))
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(Palette.dim)
                                .frame(width: 66, alignment: .trailing)
                        }
                    }
                }
            }
        }
    }

    private func peers(_ data: JobInspection) -> some View {
        section(data.peers.isEmpty ? "Peers" : "Peers (\(data.peers.count))") {
            if data.peers.isEmpty {
                Text("No peers connected").font(.footnote).foregroundStyle(Palette.dim)
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(data.peers) { peer in
                        HStack(alignment: .top, spacing: 10) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(peer.address ?? "?")
                                    .font(.system(size: 13, weight: .medium).monospacedDigit())
                                    .lineLimit(1)
                                Text([peer.client, peer.country, peer.connection, peer.flags]
                                        .compactMap { $0 }.joined(separator: " · "))
                                    .font(.caption)
                                    .foregroundStyle(Palette.faint)
                                    .lineLimit(1)
                            }
                            Spacer(minLength: 6)
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(String(format: "%.0f%%", peer.progress))
                                    .font(.caption.monospacedDigit())
                                Text("↓ \(fileSize(peer.dlSpeed))/s  ↑ \(fileSize(peer.upSpeed))/s")
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(Palette.dim)
                            }
                        }
                    }
                }
            }
        }
    }

    private func trackers(_ data: JobInspection) -> some View {
        section("Trackers") {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(data.trackers) { tracker in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(tracker.host).font(.system(size: 13, weight: .medium))
                            Spacer()
                            Text(tracker.status.capitalized)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(tracker.status == "working" ? DownloadsView.readyGreen
                                                 : tracker.status == "not working" ? Palette.danger
                                                 : Palette.dim)
                        }
                        let counts = [("seeds", tracker.seeds), ("leechers", tracker.leechers),
                                      ("peers", tracker.peers)]
                            .compactMap { label, n in n.flatMap { $0 >= 0 ? "\($0) \(label)" : nil } }
                        if !counts.isEmpty {
                            Text(counts.joined(separator: " · "))
                                .font(.caption).foregroundStyle(Palette.faint)
                        }
                        if let message = tracker.message {
                            Text(message).font(.caption).foregroundStyle(Palette.dim)
                        }
                    }
                }
            }
        }
    }

    private func information(_ data: JobInspection) -> some View {
        let t = data.torrent
        let library = data.library
        return section("Information") {
            VStack(alignment: .leading, spacing: 12) {
                facts([
                    ("Torrent", t.name),
                    ("Info hash", t.infoHash),
                    ("Saved in", t.savePath),
                    ("Content", t.contentPath),
                    ("In the library", library.libraryPath),
                    ("Asked for", library.wanted.map { $0.joined(separator: ", ") } ?? "All of it"),
                    ("Preparation", preparation(library.preparation)),
                    ("Created by", t.createdBy),
                    ("Created", date(t.createdAt)),
                    ("Requested", date(library.requestedAt)),
                    ("Added", date(t.addedAt)),
                    ("Completed", date(t.completedAt)),
                    ("Torrent's copy", library.sourceRemoved ? "Removed; plays from what was built"
                        : library.sourceRemovable ? "Can go: \(fileSize(library.sourceBytes ?? 0)) back"
                        : "Kept"),
                ], wide: true)
                if library.sourceRemovable && !library.sourceRemoved {
                    Button { confirmingSource = true } label: {
                        Label("Remove the torrent's copy", systemImage: "externaldrive.badge.minus")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .tint(.white)
                    .disabled(working)
                    .confirmationDialog("Remove the torrent's copy?", isPresented: $confirmingSource,
                                        titleVisibility: .visible) {
                        Button("Remove and free \(fileSize(library.sourceBytes ?? 0))",
                               role: .destructive) {
                            Task { await removeSource() }
                        }
                    } message: {
                        Text(job.seeding.met
                             ? "It still plays, from what was built from it. It stops seeding."
                             : "It still plays, from what was built from it. It has only \(job.seeding.detail), so removing it now counts as a hit and run on filelist.")
                    }
                }
            }
        }
    }

    private func releaseFacts(_ release: JobInspection.Release) -> some View {
        section("Release") {
            facts([
                ("Category", release.categoryName),
                ("Size", release.sizeBytes.map(fileSize)),
                ("Video", [release.resolution, release.source, release.videoCodec, release.hdr]
                    .compactMap { $0 }.joined(separator: " · ").nilIfEmpty),
                ("Audio", release.audioCodec),
                ("Group", release.releaseGroup),
                ("Uploaded", date(release.uploadDate)),
                ("On the tracker", pair(release.seeders, release.leechers).map { "\($0) seeds/leechers" }),
                ("Flags", [release.freeleech == true ? "Freeleech" : nil,
                           release.internal == true ? "Internal" : nil]
                    .compactMap { $0 }.joined(separator: " · ").nilIfEmpty),
            ])
        }
    }

    private func section<Content: View>(_ title: String,
                                        @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title.uppercased())
                .font(.caption.weight(.bold))
                .foregroundStyle(Palette.faint)
            content()
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(16)
        .id(title.components(separatedBy: " (").first ?? title)
    }

    /// Rows with no value are left out. Wide puts the value under its label.
    private func facts(_ rows: [(String, String?)], wide: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: wide ? 10 : 7) {
            ForEach(rows.compactMap { label, value in value.map { (label, $0) } }, id: \.0) { label, value in
                if wide {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(label).font(.caption).foregroundStyle(Palette.faint)
                        Text(value).font(.system(size: 13)).textSelection(.enabled)
                    }
                } else {
                    HStack(alignment: .firstTextBaseline) {
                        Text(label).font(.system(size: 13)).foregroundStyle(Palette.dim)
                        Spacer(minLength: 12)
                        Text(value).font(.system(size: 13, weight: .medium).monospacedDigit())
                            .multilineTextAlignment(.trailing)
                    }
                }
            }
        }
    }

    private func speeds(_ now: Int?, _ average: Int?) -> String? {
        guard let now else { return nil }
        // qBittorrent reports a few bytes a second of chatter on an idle
        // torrent; that is nothing moving.
        let current = "\(fileSize(now < 1000 ? 0 : now))/s"
        guard let average, average > 0 else { return current }
        return "\(current), \(fileSize(average))/s average"
    }

    private func pair(_ a: Int?, _ b: Int?) -> String? {
        guard let a else { return nil }
        guard let b, b >= 0 else { return "\(a)" }
        return "\(a) of \(b)"
    }

    private func preparation(_ prep: JobInspection.Library.Preparation?) -> String? {
        guard let prep else { return nil }
        if prep.error != nil { return "Could not be made playable" }
        if prep.ready == true { return "Done" }
        if let percent = prep.percent, percent > 0 {
            return "\(prep.stage?.capitalized ?? "Working") \(Int(percent))%"
        }
        return prep.stage?.capitalized
    }

    static func qbitState(_ raw: String) -> String {
        [
            "downloading": "Downloading", "stalledDL": "Waiting for peers", "metaDL": "Fetching metadata",
            "queuedDL": "Queued", "forcedDL": "Downloading (forced)", "checkingDL": "Checking",
            "pausedDL": "Paused", "stoppedDL": "Stopped", "allocating": "Allocating space",
            "uploading": "Seeding", "stalledUP": "Seeding, nobody downloading", "queuedUP": "Queued to seed",
            "forcedUP": "Seeding (forced)", "checkingUP": "Checking", "pausedUP": "Finished",
            "stoppedUP": "Finished", "checkingResumeData": "Checking", "moving": "Moving",
            "missingFiles": "Files missing", "error": "Error",
        ][raw] ?? raw
    }

    private func date(_ iso: String?) -> String? {
        guard let iso else { return nil }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plain = ISO8601DateFormatter()
        guard let date = parser.date(from: iso) ?? plain.date(from: iso) else { return iso }
        return date.formatted(date: .abbreviated, time: .shortened)
    }

    private func duration(_ seconds: Int) -> String {
        let days = seconds / 86_400, hours = seconds % 86_400 / 3600, minutes = seconds % 3600 / 60
        if days > 0 { return "\(days)d \(hours)h" }
        if hours > 0 { return "\(hours)h \(minutes)m" }
        return "\(max(1, minutes))m"
    }

    private func load() async {
        do {
            let (fresh, current) = try await APIClient.shared.inspectJob(job.id)
            data = fresh
            if let current { job = current }
            loadError = nil
        } catch {
            if data == nil { loadError = error.localizedDescription }
        }
    }

    private func delete() async {
        working = true
        defer { working = false }
        do {
            try await APIClient.shared.deleteJob(job.id)
            await onChange()
            await state.loadFeed()
            dismiss()
        } catch {
            Toasts.shared.error("Couldn't remove it. Try again.")
        }
    }

    private func removeSource() async {
        working = true
        defer { working = false }
        do {
            try await APIClient.shared.removeSource(job.downloadID, force: !job.seeding.met)
            await load()
            await onChange()
        } catch {
            Toasts.shared.error("Couldn't remove the torrent's copy. Try again.")
        }
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
