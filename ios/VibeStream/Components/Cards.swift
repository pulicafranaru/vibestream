import SwiftUI

struct PosterCard: View {
    @Environment(AppState.self) private var state
    let card: Card
    /// nil fills whatever cell it is put in, for grids.
    var width: CGFloat? = Metrics.posterWidth

    var body: some View {
        art
            .clipShape(.rect(cornerRadius: 6))
            .overlay { working }
            .overlay(alignment: .bottom) { resume }
            .overlay(alignment: .topTrailing) { badge }
            .overlay(alignment: .topLeading) { ready }
            .contentShape(.rect)
    }

    @ViewBuilder private var ready: some View {
        if card.playableDownloadID != nil {
            Circle()
                .fill(Palette.good)
                .frame(width: 8, height: 8)
                .overlay(Circle().stroke(Palette.ground.opacity(0.75), lineWidth: 2))
                .padding(6)
                .accessibilityLabel("Ready to play")
        }
    }

    @ViewBuilder private var art: some View {
        if let width {
            RemoteImage(url: card.poster.flatMap(URL.init(string:)))
                .frame(width: width, height: width / Metrics.posterAspect)
        } else {
            Color.clear
                .aspectRatio(Metrics.posterAspect, contentMode: .fit)
                .overlay { RemoteImage(url: card.poster.flatMap(URL.init(string:))) }
                .clipped()
        }
    }

    @ViewBuilder private var badge: some View {
        if card.quality?.resolution == "2160p" {
            Text("4K")
                .font(.system(size: 9, weight: .heavy))
                .padding(.horizontal, 4).padding(.vertical, 2)
                .background(.black.opacity(0.65), in: .rect(cornerRadius: 3))
                .padding(5)
        }
    }

    @ViewBuilder private var resume: some View {
        let percent = card.resumePercent ?? 0
        if percent > 1 {
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Rectangle().fill(.white.opacity(0.3))
                    Rectangle().fill(Palette.accent)
                        .frame(width: geo.size.width * min(1, percent / 100))
                }
            }
            .frame(height: 3)
        }
    }

    /// Live state from the poll: the card's own copy is a snapshot from the fetch.
    private var download: DownloadState? {
        if let primary = card.primaryReleaseID, let live = state.downloads[primary],
           live.state != "removed" {
            return live
        }
        return state.downloads.isEmpty ? card.download : nil
    }

    @ViewBuilder private var working: some View {
        if let download, download.isWorking || download.isPreparing {
            ZStack {
                Color.black.opacity(0.45)
                DownloadRing(
                    percent: download.isWorking && download.percent > 0
                        ? download.percent : nil,
                    size: 42
                )
            }
        }
    }
}

struct ContinueCard: View {
    let card: Card
    var width: CGFloat = 140

    var body: some View {
        VStack(spacing: 0) {
            ZStack {
                RemoteImage(url: card.poster.flatMap(URL.init(string:)))
                    .frame(width: width, height: width / Metrics.posterAspect)
                    .clipped()
                Circle()
                    .fill(.black.opacity(0.35))
                    .frame(width: 42, height: 42)
                    .overlay(Circle().stroke(.white.opacity(0.9), lineWidth: 1.5))
                    .overlay(
                        Image(systemName: "play.fill")
                            .font(.system(size: 16))
                            .offset(x: 1)
                    )
            }
            .frame(width: width, height: width / Metrics.posterAspect)
            .overlay(alignment: .bottomLeading) {
                if let label = card.resumeLabel {
                    Text(card.resumeKind == "next" ? "Next: \(label)" : label)
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 5).padding(.vertical, 2)
                        .background(.black.opacity(0.78), in: .rect(cornerRadius: 4))
                        .padding(6)
                }
            }

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Rectangle().fill(.white.opacity(0.28))
                    Rectangle().fill(Palette.accent)
                        .frame(width: geo.size.width * min(1, (card.resumePercent ?? 0) / 100))
                }
            }
            .frame(width: width, height: 3)
        }
        .clipShape(.rect(cornerRadius: 6))
        .contentShape(.rect)
    }
}

struct HeroCard: View {
    let card: Card
    var wide: Bool
    var download: DownloadState?
    var busy: Bool = false
    var onPlay: () -> Void
    var onDownload: () -> Void
    var onInfo: () -> Void
    var saved: Bool = false
    var onMyList: (() -> Void)?
    @State private var billboardWidth: CGFloat = 0

    var body: some View {
        if wide { billboard } else { poster }
    }

    // The wide hero: edge to edge, artwork pinned to the top so heads survive the crop.
    private var billboard: some View {
        Color.clear
            // Capped so a 16:9 backdrop is not cropped too far.
            .containerRelativeFrame(.vertical) { length, _ in
                let landscape = billboardWidth > length
                let byHeight = max(360, length * (landscape ? 0.82 : 0.66))
                return billboardWidth > 0 ? min(byHeight, max(360, billboardWidth * 0.62)) : byHeight
            }
            .frame(maxWidth: .infinity)
            .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { billboardWidth = $0 }
            .overlay(alignment: .top) {
                RemoteImage(url: artworkURL)
            }
            .clipped()
            .overlay {
                EllipticalGradient(
                    stops: [
                        .init(color: Palette.ground.opacity(0.85), location: 0),
                        .init(color: .clear, location: 0.72),
                    ],
                    center: .bottomLeading, startRadiusFraction: 0, endRadiusFraction: 0.85
                )
            }
            .overlay {
                LinearGradient(
                    stops: [
                        .init(color: .clear, location: 0.5),
                        .init(color: Palette.ground.opacity(0.7), location: 0.82),
                        .init(color: Palette.ground, location: 1.0),
                    ],
                    startPoint: .top, endPoint: .bottom
                )
            }
            .overlay(alignment: .bottomLeading) {
                VStack(alignment: .leading, spacing: 12) {
                    Text(card.title)
                        .font(.system(size: 44, weight: .heavy))
                        .foregroundStyle(.white)
                        .lineLimit(2)
                        .minimumScaleFactor(0.6)
                        .shadow(color: .black.opacity(0.5), radius: 10)

                    if !facts.isEmpty {
                        Text(facts.joined(separator: "  •  "))
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.white.opacity(0.9))
                    }

                    if let overview = card.overview, !overview.isEmpty {
                        Text(overview)
                            .font(.callout)
                            .foregroundStyle(.white.opacity(0.82))
                            .lineLimit(3)
                    }

                    HStack(spacing: 12) {
                        action.frame(width: 230)
                        myListButton.frame(width: 230)
                    }
                    .controlSize(.large)
                    .padding(.top, 6)
                }
                .frame(maxWidth: 560, alignment: .leading)
                .padding(.leading, 28)
                .padding(.bottom, 26)
            }
            .contentShape(.rect)
            .onTapGesture(perform: onInfo)
    }

    private var facts: [String] {
        var out: [String] = []
        if let year = card.year { out.append(String(year)) }
        if let runtime = card.runtime, runtime > 0 {
            out.append(runtime >= 60 ? "\(runtime / 60)h \(runtime % 60)m" : "\(runtime)m")
        }
        out.append(contentsOf: (card.genres ?? []).prefix(3))
        return out
    }

    // The whole poster at 2:3: a fixed height cut off the title at its top.
    private var poster: some View {
        Color.clear
            .aspectRatio(Metrics.posterAspect, contentMode: .fit)
            .frame(maxWidth: .infinity)
            .overlay { RemoteImage(url: artworkURL) }
            .clipped()
            .overlay {
                LinearGradient(
                    stops: [
                        .init(color: .clear, location: 0.38),
                        .init(color: .black.opacity(0.55), location: 0.68),
                        .init(color: .black.opacity(0.96), location: 1.0),
                    ],
                    startPoint: .top, endPoint: .bottom
                )
            }
            .overlay(alignment: .bottom) {
                // No title text: the poster carries its own.
                VStack(spacing: 12) {
                    if let genres = card.genres, !genres.isEmpty {
                        Text(genres.prefix(3).joined(separator: "  •  "))
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(.white)
                            .shadow(radius: 6)
                    }

                    HStack(spacing: 10) {
                        action
                        myListButton
                    }
                    .controlSize(.large)
                    .padding(.horizontal, 14)
                }
                .padding(.bottom, 16)
            }
            .clipShape(.rect(cornerRadius: 10))
            .contentShape(.rect)
            .onTapGesture(perform: onInfo)
    }

    /// The live download wins over the feed's snapshot.
    private var titleAction: TitleAction {
        if download == nil, card.playableDownloadID != nil { return .play("Play") }
        return TitleAction.of(download, optimistic: busy)
    }

    private var action: some View {
        TitleButton(action: titleAction) {
            switch titleAction {
            case .play: onPlay()
            case .download, .failed: onDownload()
            default: onInfo()
            }
        }
    }

    @ViewBuilder private var myListButton: some View {
        if let onMyList {
            Button(action: onMyList) {
                Label("Watchlist", systemImage: saved ? "checkmark" : "plus")
                    .font(.headline).frame(maxWidth: .infinity)
                    .contentTransition(.symbolEffect(.replace))
            }
            .buttonStyle(PillButtonStyle(prominent: false))
            .accessibilityLabel(saved ? "Remove from Watchlist" : "Add to Watchlist")
        }
    }

    private var artworkURL: URL? {
        let raw = wide ? (card.backdrop ?? card.poster) : (card.poster ?? card.backdrop)
        return raw.flatMap(URL.init(string:))
    }
}

struct CardRow<Tile: View>: View {
    let title: String
    let items: [Card]
    @ViewBuilder var tile: (Card) -> Tile

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 17, weight: .bold))
                .padding(.horizontal, 16)

            ScrollView(.horizontal) {
                LazyHStack(spacing: Metrics.rowSpacing) {
                    ForEach(items) { tile($0) }
                }
                .padding(.horizontal, 16)
                .scrollTargetLayout()
            }
            .scrollIndicators(.hidden)
        }
    }
}
