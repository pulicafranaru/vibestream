import SwiftUI

// The server builds the list. Unread is counted per device, against the newest
// item this profile has seen here.
struct NotificationItem: Codable, Hashable, Identifiable, Sendable {
    var id: String
    var kind: String
    var heading: String
    var text: String
    var image: String?
    var mediaID: Int?
    var at: String

    enum CodingKeys: String, CodingKey {
        case id, kind, heading, text, image, at
        case mediaID = "media_id"
    }

    var date: Date? {
        let precise = ISO8601DateFormatter()
        precise.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = precise.date(from: at) { return date }
        let plain = ISO8601DateFormatter()
        if let date = plain.date(from: at) { return date }
        // Naive timestamps, which the server writes in UTC.
        return plain.date(from: at + "Z")
    }

    var ago: String {
        guard let date else { return "" }
        let days = Int(Date().timeIntervalSince(date) / 86_400)
        if days <= 0 { return "Today" }
        if days == 1 { return "1 day ago" }
        if days < 7 { return "\(days) days ago" }
        let weeks = days / 7
        return weeks == 1 ? "1 week ago" : "\(weeks) weeks ago"
    }
}

struct NotificationFeed: Codable, Sendable {
    var items: [NotificationItem]
}

struct NotificationsBell: View {
    @Environment(AppState.self) private var state
    @Binding var selection: Card?
    var onDownloads: () -> Void

    @State private var items: [NotificationItem] = []
    @State private var open = false

    private var seenKey: String { "vibestream.notifications.seen.\(state.profile?.id ?? 0)" }

    // ISO timestamps from one server compare correctly as strings.
    private var unread: Int { items.filter { $0.at > state.notificationsSeen }.count }

    var body: some View {
        Button(action: show) {
            Image(systemName: "bell")
                .font(.system(size: 19, weight: .regular))
                .foregroundStyle(.white)
                .frame(width: 40, height: 40)
                .overlay(alignment: .topTrailing) {
                    if unread > 0 {
                        Circle()
                            .fill(Palette.accent)
                            .frame(width: 9, height: 9)
                            .overlay(Circle().stroke(Palette.ground, lineWidth: 2))
                            .offset(x: -8, y: 8)
                    }
                }
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(unread > 0 ? "Notifications, \(unread) new" : "Notifications")
        .popover(isPresented: $open, arrowEdge: .top) {
            list
                .frame(minWidth: 360, idealWidth: 400, minHeight: 300, idealHeight: 520)
                .presentationCompactAdaptation(.sheet)
                .presentationDetents([.medium, .large])
        }
        .task(id: state.profile?.id) {
            state.notificationsSeen = UserDefaults.standard.string(forKey: seenKey) ?? ""
            #if DEBUG
            // -notifications: open the list, for looking at from a script.
            if ProcessInfo.processInfo.arguments.contains("-notifications") {
                await load()
                open = true
            }
            #endif
            while !Task.isCancelled {
                await load()
                try? await Task.sleep(for: .seconds(300))
            }
        }
    }

    private var list: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    if items.isEmpty {
                        Text("Nothing new yet")
                            .font(.subheadline)
                            .foregroundStyle(Palette.dim)
                            .frame(maxWidth: .infinity)
                            .padding(.top, 60)
                    }
                    ForEach(items) { item in
                        Button { choose(item) } label: { row(item) }
                            .buttonStyle(.plain)
                    }
                }
                .padding(.vertical, 8)
            }
            .background(Palette.ground)
            .navigationTitle("Notifications")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { CloseButton { open = false } }
            }
        }
        .preferredColorScheme(.dark)
    }

    private func row(_ item: NotificationItem) -> some View {
        HStack(alignment: .top, spacing: 12) {
            RemoteImage(url: item.image.flatMap(URL.init(string:)))
                .frame(width: 112, height: 63)
                .clipShape(.rect(cornerRadius: 4))
            VStack(alignment: .leading, spacing: 3) {
                Text(item.heading)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(item.kind == "failed" ? Palette.accent : .white)
                Text(item.text)
                    .font(.footnote)
                    .foregroundStyle(Palette.dim)
                    .lineLimit(2)
                Text(item.ago)
                    .font(.caption2)
                    .foregroundStyle(Palette.faint)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .contentShape(.rect)
    }

    private func show() {
        open = true
        Task { await load() }
        markRead()
    }

    /// The newest item, not the clock, marks the place.
    private func markRead() {
        guard let newest = items.first?.at, newest > state.notificationsSeen else { return }
        state.notificationsSeen = newest
        UserDefaults.standard.set(newest, forKey: seenKey)
    }

    private func choose(_ item: NotificationItem) {
        open = false
        if item.kind == "failed" {
            onDownloads()
            return
        }
        guard let id = item.mediaID else { return }
        Task {
            if let card = try? await APIClient.shared.media(id) { selection = card }
        }
    }

    private func load() async {
        guard let feed = try? await APIClient.shared.notifications() else { return }
        items = feed.items
        if open { markRead() }
    }
}
