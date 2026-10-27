import SwiftUI

// An episode not downloaded yet, opened from its row: its still, Download or progress, then Play.
struct EpisodePreview: View {
    let card: Card
    @State var item: EpisodeItem
    var seasonPack: SeasonDetail.SeasonPack?
    var onPlay: (EpisodeItem) -> Void

    @Environment(AppState.self) private var state
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openTitle) private var openTitle
    @State private var starting = false
    @State private var pack: SeasonDetail.SeasonPack?

    private var phase: EpisodePhase { item.phase(in: state.downloads) }

    var body: some View {
        VStack(spacing: 0) {
            strip
            PlayerPage(playID: item.playID ?? "e\(item.id)",
                       title: card.title,
                       mediaID: card.mediaID,
                       presentation: PlayInfo.Presentation(
                           title: card.title, year: card.year, overview: item.overview,
                           episode: .init(season: item.season, number: item.episode, name: item.name)),
                       loaded: true,
                       onEpisode: { other in
                           if other.playable { play(other) } else { withAnimation(.snappy) { item = other } }
                       },
                       episodeID: item.id,
                       previewing: true,
                       onTitle: { other in
                           dismiss()
                           openTitle?(other)
                       })
        }
        .background(Palette.ground.ignoresSafeArea())
        .preferredColorScheme(.dark)
        .task {
            pack = seasonPack
            // Opened from the player, which has no season to hand over.
            if pack == nil { await refresh() }
        }
        .task(id: item.id) {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(4))
                guard phase.busy || starting else { continue }
                await refresh()
            }
        }
    }

    private var strip: some View {
        Color.clear
            .aspectRatio(16 / 9, contentMode: .fit)
            .overlay { RemoteImage(url: item.still.flatMap(URL.init(string:))) }
            .overlay {
                LinearGradient(colors: [.black.opacity(0.55), .black.opacity(0.35), .black.opacity(0.7)],
                               startPoint: .top, endPoint: .bottom)
            }
            .overlay(alignment: .topLeading) {
                Button { dismiss() } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 18, weight: .bold))
                        .shadow(color: .black.opacity(0.5), radius: 3)
                        .frame(width: 44, height: 44)
                        .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .padding(.leading, 4)
                .padding(.top, 2)
                .accessibilityLabel("Close")
            }
            .overlay { action.padding(.horizontal, 40) }
            .clipped()
            .foregroundStyle(.white)
    }

    @ViewBuilder private var action: some View {
        VStack(spacing: 10) {
            switch phase {
            case .playable:
                Button { play(item) } label: {
                    Label("Play", systemImage: "play.fill").frame(maxWidth: 260)
                }
                .buttonStyle(PillButtonStyle())
            case .downloadable:
                if let release = item.releases?.first {
                    Button { download(release) } label: {
                        HStack(spacing: 8) {
                            if starting { ProgressView().tint(.black) } else { Image(systemName: "arrow.down") }
                            Text("Download Episode")
                        }
                        .frame(maxWidth: 260)
                    }
                    .buttonStyle(PillButtonStyle())
                    .disabled(starting)
                    if let cost = release.episodeCost {
                        caption(cost)
                    }
                    if let pack, pack.completeRequest != true {
                        Button { downloadSeason(pack) } label: {
                            Text("Download Season" + (pack.sizeGB.map { String(format: " · %.1f GB", $0) } ?? ""))
                                .font(.footnote.weight(.semibold))
                                .padding(.horizontal, 14)
                                .frame(height: 32)
                                .background(Capsule().fill(.white.opacity(0.16)))
                        }
                        .buttonStyle(.plain)
                        .disabled(starting)
                    }
                }
            case .waiting:
                progress(nil, "Waiting for download")
            case .arriving(let percent):
                progress(percent, percent.map { "Downloading \(Int($0))%" } ?? "Downloading")
            case .preparing(let percent):
                progress(percent, percent.map { "Preparing \(Int($0))%" } ?? "Preparing")
            case .failed(let error):
                caption(error)
            case .unobtainable:
                if let date = item.comingOn {
                    caption("Coming \(date.formatted(.dateTime.day().month(.wide)))")
                } else {
                    caption("Not available yet")
                }
            }
        }
        .animation(.snappy, value: phase)
    }

    private func progress(_ percent: Double?, _ label: String) -> some View {
        VStack(spacing: 10) {
            DownloadRing(percent: percent, size: 48)
            caption(label)
        }
    }

    private func caption(_ text: String) -> some View {
        Text(text)
            .font(.subheadline.weight(.semibold))
            .multilineTextAlignment(.center)
            .shadow(color: .black.opacity(0.6), radius: 4)
    }

    private func play(_ episode: EpisodeItem) {
        dismiss()
        onPlay(episode)
    }

    private func download(_ release: EpisodeItem.EpisodeRelease) {
        starting = true
        Task {
            do {
                try await state.download(torrent: release.id, episode: release.seasonPack ? item.id : nil)
                await refresh()
            } catch {
                Toasts.shared.error(error.localizedDescription)
            }
            starting = false
        }
    }

    private func downloadSeason(_ pack: SeasonDetail.SeasonPack) {
        starting = true
        Task {
            do {
                try await state.download(torrent: pack.id, everything: pack.download != nil)
                await refresh()
            } catch {
                Toasts.shared.error(error.localizedDescription)
            }
            starting = false
        }
    }

    private func refresh() async {
        await state.refreshDownloads()
        guard let detail = try? await APIClient.shared.season(media: card.mediaID, number: item.season),
              let fresh = detail.episodes.first(where: { $0.id == item.id }) else { return }
        item = fresh
        pack = detail.seasonPack
    }
}
