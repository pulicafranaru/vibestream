import SwiftUI

// A person's or a genre's titles as a poster grid, in a sheet over the title page.
struct CollectionTarget: Identifiable, Hashable {
    enum Kind: Hashable {
        case person(Int)
        case genre(String)
    }

    let kind: Kind
    let title: String

    var id: String {
        switch kind {
        case let .person(id): "person-\(id)"
        case let .genre(name): "genre-\(name)"
        }
    }

    /// URL scheme for About tab links; the title page handles them, never the system.
    static let scheme = "vibestream-collection"

    var url: URL? {
        var parts = URLComponents()
        parts.scheme = Self.scheme
        switch kind {
        case let .person(id):
            parts.host = "person"
            parts.queryItems = [.init(name: "id", value: String(id)), .init(name: "name", value: title)]
        case let .genre(name):
            parts.host = "genre"
            parts.queryItems = [.init(name: "name", value: name)]
        }
        return parts.url
    }

    init(kind: Kind, title: String) {
        self.kind = kind
        self.title = title
    }

    init?(url: URL) {
        guard url.scheme == Self.scheme,
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems
        else { return nil }
        let value = { (key: String) in items.first { $0.name == key }?.value }
        switch url.host() {
        case "person":
            guard let id = value("id").flatMap(Int.init), let name = value("name") else { return nil }
            self.init(kind: .person(id), title: name)
        case "genre":
            guard let name = value("name") else { return nil }
            self.init(kind: .genre(name), title: name)
        default:
            return nil
        }
    }
}

struct CollectionView: View {
    let target: CollectionTarget
    var onOpen: (Card) -> Void
    var onClose: () -> Void

    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var items: [Card]?
    @State private var subtitle: String?
    @State private var failure: String?

    private var wide: Bool { sizeClass == .regular }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let subtitle {
                        Text(subtitle).font(.subheadline).foregroundStyle(Palette.dim)
                    }
                    grid
                }
                .padding(.horizontal, wide ? 28 : 16)
                .padding(.bottom, 30)
            }
            .scrollIndicators(.hidden)
            .background(Palette.ground)
            .navigationTitle(target.title)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    CloseButton(action: onClose)
                }
            }
        }
        .task(id: target) { await load() }
    }

    @ViewBuilder private var grid: some View {
        if let items, !items.isEmpty {
            let columns = Array(repeating: GridItem(.flexible(), spacing: 12), count: wide ? 5 : 3)
            LazyVGrid(columns: columns, spacing: 12) {
                ForEach(items) { card in
                    PosterCard(card: card, width: nil)
                        .onTapGesture { onOpen(card) }
                        .accessibilityAddTraits(.isButton)
                        .accessibilityLabel(card.title)
                }
            }
        } else if items != nil || failure != nil {
            Text(failure ?? "Nothing in the catalog yet")
                .font(.footnote).foregroundStyle(Palette.faint)
                .frame(maxWidth: .infinity).padding(.top, 60)
        } else {
            BootSpinner(size: 32, line: 3).frame(maxWidth: .infinity).padding(.top, 60)
        }
    }

    private func load() async {
        do {
            switch target.kind {
            case let .person(id):
                let page = try await APIClient.shared.person(id)
                items = page.items
                subtitle = page.knownFor.map { $0 == "Acting" ? "Actor" : $0 }
            case let .genre(name):
                items = try await APIClient.shared.catalog(genre: name)
            }
        } catch {
            failure = error.localizedDescription
        }
    }
}
