import SwiftUI

@main
struct VibeStreamApp: App {
    // Present only to vend the orientation mask; see Orientation.swift.
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var state = AppState()
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(state)
                .preferredColorScheme(.dark)
                #if DEBUG
                .modifier(LandscapeProbe())
                #endif
        }
        // Refetch on return: the poll is suspended in the background.
        .onChange(of: phase) { _, now in
            guard now == .active else { return }
            Task {
                await state.refreshDownloads()
                state.startPolling()
                if state.profile != nil, state.feed != nil || !state.feeds.isEmpty { await state.loadFeed() }
            }
        }
    }
}

#if DEBUG
/// -landscape: draw a landscape iPad frame scaled into the portrait simulator,
/// which cannot be turned from code.
private struct LandscapeProbe: ViewModifier {
    func body(content: Content) -> some View {
        if ProcessInfo.processInfo.arguments.contains("-landscape") {
            GeometryReader { geo in
                let size = CGSize(width: geo.size.height, height: geo.size.width)
                content
                    .frame(width: size.width, height: size.height)
                    .scaleEffect(geo.size.width / size.width, anchor: .topLeading)
                    .frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
            }
            .ignoresSafeArea()
        } else {
            content
        }
    }
}
#endif
