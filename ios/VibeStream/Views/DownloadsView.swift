import Charts
import SwiftUI

// Downloads live on the server: this lists what it holds, not an offline library.
// Deleting before seeding is done counts as a hit and run against the tracker account.
struct DownloadsView: View {
    @Environment(AppState.self) private var state
    @Environment(\.dismiss) private var dismiss

    /// Set to play after this sheet has closed: two full screen presentations at once break.
    @Binding var playing: PlayRequest?

    @State private var data: DownloadJobs?
    @State private var loadError: String?
    @State private var confirming: DownloadJob?
    @State private var inspecting: DownloadJob?
    @State private var working: Set<Int> = []
    @State private var note: String?

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 14) {
                if let totals = data?.totals { summary(totals) }

                if let data, !data.live {
                    Label(
                        "qBittorrent is not answering, so speeds and peers are the last known values.",
                        systemImage: "exclamationmark.triangle"
                    )
                    .font(.footnote)
                    .foregroundStyle(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                ForEach(data?.items ?? []) { job in
                    row(job)
                }

                if let data, data.items.isEmpty {
                    empty
                }
                if data == nil, let loadError {
                    Text(loadError)
                        .font(.footnote).foregroundStyle(Palette.dim)
                        .padding(.top, 40)
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 30)
        }
        .background(Palette.ground)
        .softTopEdge()
        .scrollIndicators(.hidden)
        .navigationTitle("My Downloads")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) { CloseButton { dismiss() } }
        }
        .refreshable { await load() }
        .navigationDestination(item: $inspecting) { job in
            JobInspector(job: job, onPlay: { play($0) }) { await load() }
        }
        .overlay { if data == nil && loadError == nil { BootSpinner() } }
        .overlay(alignment: .bottom) {
            if let note {
                Text(note)
                    .font(.footnote)
                    .padding(.horizontal, 16).padding(.vertical, 10)
                    .glassCard(12)
                    .padding(.bottom, 18)
                    .transition(.opacity)
            }
        }
        .task {
            #if DEBUG
            // -inspectJob <id>: open that job's inspector, to look at it.
            let args = ProcessInfo.processInfo.arguments
            if let at = args.firstIndex(of: "-inspectJob"), at + 1 < args.count,
               let wanted = Int(args[at + 1]) {
                await load()
                inspecting = data?.items.first { $0.id == wanted }
            }
            #endif
            while !Task.isCancelled {
                await load()
                try? await Task.sleep(for: .seconds(3))
            }
        }
    }

    private struct Slice: Identifiable {
        let label: String
        let bytes: Int
        let color: Color
        var id: String { label }
    }

    private func summary(_ totals: DownloadManager.Totals) -> some View {
        var slices: [Slice] = []
        if let playback = totals.playbackBytes, let torrents = totals.torrentBytes {
            slices.append(Slice(label: "Playback", bytes: playback, color: Palette.accent))
            slices.append(Slice(label: "Torrents", bytes: torrents, color: Palette.good))
        } else {
            slices.append(Slice(label: "On disk", bytes: totals.sizeBytes, color: Palette.accent))
        }
        if let free = totals.freeBytes {
            slices.append(Slice(label: "Free", bytes: free, color: Color(white: 0.24)))
        }
        let used = slices.filter { $0.label != "Free" }.reduce(0) { $0 + $1.bytes }
        let whole = slices.reduce(0) { $0 + $1.bytes }

        return VStack(spacing: 14) {
            HStack(spacing: 22) {
                Chart(slices) { slice in
                    SectorMark(angle: .value("Bytes", max(slice.bytes, 1)),
                               innerRadius: .ratio(0.68), angularInset: 1.5)
                        .cornerRadius(3)
                        .foregroundStyle(slice.color)
                }
                .chartLegend(.hidden)
                .frame(width: 128, height: 128)
                .overlay {
                    VStack(spacing: 1) {
                        Text(fileSize(used))
                            .font(.system(size: 17, weight: .bold))
                            .minimumScaleFactor(0.7)
                            .lineLimit(1)
                        if totals.freeBytes != nil {
                            Text("of \(fileSize(whole))")
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(Palette.faint)
                        }
                    }
                    .frame(width: 80)
                }

                VStack(alignment: .leading, spacing: 11) {
                    ForEach(slices) { slice in
                        HStack(spacing: 10) {
                            Circle().fill(slice.color).frame(width: 10, height: 10)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(fileSize(slice.bytes))
                                    .font(.system(size: 16, weight: .semibold))
                                Text(slice.label)
                                    .font(.system(size: 12))
                                    .foregroundStyle(Palette.faint)
                            }
                        }
                    }
                }
                Spacer(minLength: 0)
            }

            HStack(spacing: 6) {
                Text(totals.count == 1 ? "1 download" : "\(totals.count) downloads")
                Text("·")
                Text("\(fileSize(totals.uploadedBytes)) shared")
                if totals.downloading > 0 {
                    Text("·")
                    Label(speed(totals.dlSpeed), systemImage: "arrow.down")
                    Label(speed(totals.upSpeed), systemImage: "arrow.up")
                }
                Spacer(minLength: 0)
            }
            .font(.system(size: 13))
            .foregroundStyle(Palette.dim)
            .labelStyle(.titleAndIcon)
        }
        .padding(18)
        .frame(maxWidth: .infinity)
        .glassCard(18)
    }

    private func speed(_ bytesPerSecond: Int) -> String {
        "\(fileSize(bytesPerSecond))/s"
    }

    private func row(_ job: DownloadJob) -> some View {
        HStack(alignment: .top, spacing: 12) {
            artwork(job)

            VStack(alignment: .leading, spacing: 5) {
                Text(job.title)
                    .font(.system(size: 16, weight: .semibold))
                    .lineLimit(2)
                if let subtitle = subtitle(job) {
                    Text(subtitle)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Palette.dim)
                        .lineLimit(2)
                }

                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    if job.state == "failed" { ErrorBadge(size: 14) }
                    Text(statusLine(job))
                        .font(.system(size: 12, weight: job.state == "ready" ? .semibold : .regular))
                        .foregroundStyle(job.state == "ready" ? Self.readyGreen : Palette.dim)
                        .lineLimit(2)
                }

                if job.state == "downloading" || job.state == "paused" {
                    ProgressView(value: min(1, job.percent / 100))
                        .tint(Palette.accent)
                        .padding(.top, 2)
                } else if job.state == "preparing" {
                    ProgressView(value: min(1, (job.preparePercent ?? 0) / 100))
                        .tint(.white)
                        .padding(.top, 2)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            menu(job)
        }
        .padding(12)
        .glassCard(16)
        .contentShape(.rect)
        .onTapGesture { inspecting = job }
        .opacity(working.contains(job.id) ? 0.5 : 1)
    }

    @ViewBuilder private func artwork(_ job: DownloadJob) -> some View {
        if let still = job.episode?.still {
            RemoteImage(url: URL(string: still))
                .frame(width: 112, height: 63)
                .clipShape(.rect(cornerRadius: 6))
        } else {
            RemoteImage(url: job.poster.flatMap(URL.init(string:)))
                .frame(width: 62, height: 93)
                .clipShape(.rect(cornerRadius: 6))
        }
    }

    private func subtitle(_ job: DownloadJob) -> String? {
        if let episode = job.episode {
            return [job.label, episode.name].compactMap { $0 }.joined(separator: " · ")
        }
        if let label = job.label { return label }
        return job.year.map { String($0) }
    }

    private func statusLine(_ job: DownloadJob) -> String {
        switch job.state {
        case "queued": return "Queued"
        case "paused": return "Paused at \(Int(job.percent))%"
        case "downloading":
            // Under one percent looks like a stall; show no figure until there is one.
            var parts = [job.percent >= 1 ? "Downloading \(Int(job.percent))%" : "Downloading"]
            if job.dlSpeed > 0 { parts.append("\(fileSize(job.dlSpeed))/s") }
            if let eta = job.etaSeconds, eta > 0, eta < 360_000 { parts.append("\(max(1, eta / 60))m left") }
            return parts.joined(separator: " · ")
        case "preparing":
            return job.preparePercent.map { "Preparing \(Int($0))%" } ?? "Preparing"
        case "failed": return job.errorMessage ?? "Something went wrong. Try again."
        default:
            return ["Ready", job.sizeBytes.map(fileSize)].compactMap { $0 }.joined(separator: " · ")
        }
    }

    private func menu(_ job: DownloadJob) -> some View {
        Menu {
            if job.state == "ready" {
                Button("Play", systemImage: "play.fill") { play(job) }
            }
            if job.state == "failed" {
                Button("Try again", systemImage: "arrow.clockwise") {
                    Task { await retry(job) }
                }
            }
            Button("Details", systemImage: "info.circle") { inspecting = job }
            Button(role: .destructive) {
                confirming = job
            } label: {
                Label("Delete", systemImage: "trash")
            }
        } label: {
            Image(systemName: "ellipsis")
                .font(.system(size: 16, weight: .semibold))
                // The sheet does not inherit the app's white tint.
                .foregroundStyle(.white)
                .frame(width: 34, height: 34)
                .contentShape(.rect)
        }
        .disabled(working.contains(job.id))
        // On the row's button so the iPad popover points at this row.
        .confirmationDialog(
            "Delete \(deleteName(job))?",
            isPresented: Binding(get: { confirming?.id == job.id },
                                 set: { if !$0 { confirming = nil } }),
            titleVisibility: .visible
        ) {
            Button(job.sizeBytes.map { "Delete and free \(fileSize($0))" } ?? "Delete",
                   role: .destructive) {
                Task { await remove(job) }
            }
        } message: {
            Text(deleteMessage(job))
        }
    }

    private func deleteName(_ job: DownloadJob) -> String {
        [job.title, job.label].compactMap { $0 }.joined(separator: " ")
    }

    /// What deleting costs. One episode of a pack others still use leaves
    /// the torrent; the last of it takes the torrent, and before its seeding
    /// is done that is a hit and run.
    private func deleteMessage(_ job: DownloadJob) -> String {
        if job.kind == "episode" && job.sharesTorrent {
            return "This removes the episode from the server and from your library. The rest of the season stays."
        }
        if !job.seeding.met {
            return "This removes it and its files from the server. It has only \(job.seeding.detail), so deleting now counts as a hit and run on filelist."
        }
        return "This removes it and its files from the server."
    }

    static let readyGreen = Color(red: 0.27, green: 0.83, blue: 0.41)

    private var empty: some View {
        VStack(spacing: 10) {
            Image(systemName: "arrow.down.circle").font(.largeTitle).foregroundStyle(Palette.faint)
            Text("Nothing downloaded yet")
                .font(.subheadline).foregroundStyle(Palette.dim)
        }
        .frame(maxWidth: .infinity).padding(.top, 60)
    }

    private func load() async {
        do {
            data = try await APIClient.shared.downloadJobs()
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
    }

    private func play(_ job: DownloadJob) {
        if let playID = job.playID {
            playing = PlayRequest(playID: playID, title: job.title,
                                  season: job.episode?.season, episode: job.episode?.number)
            dismiss()
            return
        }
        guard let media = job.mediaID else { return }
        Task {
            if let card = try? await APIClient.shared.media(media), let next = card.nextUp {
                playing = PlayRequest(playID: next.playID, title: job.title,
                                      season: next.season, episode: next.number)
                dismiss()
            } else {
                show("Open \(job.title) to choose an episode")
            }
        }
    }

    private func retry(_ job: DownloadJob) async {
        working.insert(job.id)
        defer { working.remove(job.id) }
        do {
            _ = try await state.download(torrent: job.torrentID, episode: job.episode?.id)
            await load()
            show("Trying \(deleteName(job)) again")
        } catch {
            Toasts.shared.error(error.localizedDescription)
        }
    }

    private func remove(_ job: DownloadJob) async {
        working.insert(job.id)
        defer { working.remove(job.id) }
        do {
            try await APIClient.shared.deleteJob(job.id)
            await load()
            // Catalog rows carry download state, so they are stale now.
            await state.loadFeed()
            show("Removed \(deleteName(job))")
        } catch {
            Toasts.shared.error("Couldn't remove it. Try again.")
        }
    }

    private func show(_ message: String) {
        withAnimation { note = message }
        Task {
            try? await Task.sleep(for: .seconds(3))
            withAnimation { if note == message { note = nil } }
        }
    }
}

/// Zero is spelled out because the byteCount format renders "Zero kB".
func fileSize(_ bytes: Int) -> String {
    bytes <= 0 ? "0 B" : bytes.formatted(.byteCount(style: .file))
}
