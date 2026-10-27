import SwiftUI

struct MyListView: View {
    @Environment(AppState.self) private var state
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Binding var selection: Card?
    @Binding var playing: PlayRequest?

    @State private var items: [Card] = []
    @State private var loaded = false
    @State private var kind: String?          // "tv" | "movie"
    @State private var started: Bool?
    @State private var sort: Sort = .added

    private enum Sort: String, CaseIterable, Identifiable {
        case added = "Recently Added", title = "A to Z", year = "Release Year"
        var id: String { rawValue }
    }

    private var wide: Bool { sizeClass == .regular }

    private var shown: [Card] {
        let filtered = items.filter { card in
            state.myList.contains(card.mediaID)
                && (kind == nil || card.mediaType == kind)
                && (started == nil || (card.started ?? false) == started)
        }
        switch sort {
        case .added: return filtered
        case .title: return filtered.sorted { $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending }
        case .year: return filtered.sorted { ($0.year ?? 0) > ($1.year ?? 0) }
        }
    }

    var body: some View {
        List {
            Section {
                ForEach(shown) { card in
                    row(card)
                        .listRowBackground(Palette.ground)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: 6, leading: 16, bottom: 6, trailing: 16))
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                Task { await state.toggleMyList(card) }
                            } label: {
                                Label("Remove", systemImage: "minus.circle")
                            }
                        }
                }
            } header: {
                controls
            }

            if loaded && shown.isEmpty {
                empty
                    .listRowBackground(Palette.ground)
                    .listRowSeparator(.hidden)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(Palette.ground)
        .navigationTitle("Watchlist")
        .navigationBarTitleDisplayMode(.inline)
        .overlay { if !loaded { BootSpinner() } }
        .task { await load() }
        .refreshable { await load() }
        .onChange(of: state.myList) { old, new in
            if !new.subtracting(old).isEmpty { Task { await load() } }
        }
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 12) {
            ScrollView(.horizontal) {
                HStack(spacing: 8) {
                    chip("TV Shows", on: kind == "tv") { kind = kind == "tv" ? nil : "tv" }
                    chip("Movies", on: kind == "movie") { kind = kind == "movie" ? nil : "movie" }
                    chip("Haven't Started", on: started == false) { started = started == false ? nil : false }
                    chip("Started", on: started == true) { started = started == true ? nil : true }
                }
            }
            .scrollIndicators(.hidden)

            Menu {
                Picker("Sort By", selection: $sort) {
                    ForEach(Sort.allCases) { Text($0.rawValue).tag($0) }
                }
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Sort By").font(.caption).foregroundStyle(Palette.dim)
                    HStack(spacing: 6) {
                        Text(sort.rawValue).font(.headline)
                        Image(systemName: "chevron.down").font(.caption.weight(.bold))
                    }
                    .foregroundStyle(.white)
                }
            }
        }
        .padding(.vertical, 8)
        .textCase(nil)
        .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 0, trailing: 16))
        .background(Palette.ground)
    }

    private func chip(_ label: String, on: Bool, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .font(.subheadline.weight(.semibold))
                .padding(.horizontal, 14).padding(.vertical, 8)
                .foregroundStyle(on ? .black : .white)
                .background(on ? Color.white : Color.clear, in: .capsule)
                .overlay(Capsule().strokeBorder(Color.white.opacity(on ? 0 : 0.35)))
        }
        .buttonStyle(.plain)
    }

    private func row(_ card: Card) -> some View {
        let artWidth: CGFloat = wide ? 240 : 150
        return HStack(spacing: 14) {
            RemoteImage(url: (card.backdrop ?? card.poster).flatMap(URL.init(string:)))
                .frame(width: artWidth, height: artWidth * 9 / 16)
                .clipShape(.rect(cornerRadius: 6))

            VStack(alignment: .leading, spacing: 4) {
                Text(card.title)
                    .font(.system(size: wide ? 19 : 15, weight: .semibold))
                    .lineLimit(2)
                Text(subtitle(card))
                    .font(.caption).foregroundStyle(Palette.dim)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if let id = playableFilm(card) {
                Button {
                    playing = PlayRequest(downloadID: id, title: card.title)
                } label: {
                    Image(systemName: "play.circle")
                        .font(.system(size: 34, weight: .light))
                        .foregroundStyle(.white)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Play \(card.title)")
            }
        }
        .contentShape(.rect)
        .onTapGesture { selection = card }
    }

    private var empty: some View {
        VStack(spacing: 10) {
            Image(systemName: "plus.rectangle.on.rectangle")
                .font(.largeTitle).foregroundStyle(Palette.faint)
            Text(items.isEmpty ? "Your list is empty" : "Nothing matches these filters")
                .font(.headline)
            if items.isEmpty {
                Text("Tap Watchlist on any title to save it here for later.")
                    .font(.subheadline).foregroundStyle(Palette.dim)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 60)
    }

    private func subtitle(_ card: Card) -> String {
        var parts: [String] = []
        if let year = card.year { parts.append(String(year)) }
        parts.append(card.isSeries ? "Series" : "Film")
        if card.started == true { parts.append("Started") }
        return parts.joined(separator: " · ")
    }

    private func playableFilm(_ card: Card) -> Int? {
        card.isSeries ? nil : card.playableDownloadID
    }

    private func load() async {
        if let fresh = try? await APIClient.shared.myList() { items = fresh }
        loaded = true
    }
}
