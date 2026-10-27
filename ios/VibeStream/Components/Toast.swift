import SwiftUI
import UIKit

// Toasts live in their own window: one drawn in the root view sits under every sheet.
@MainActor @Observable
final class Toasts {
    static let shared = Toasts()

    struct Item: Identifiable, Equatable {
        let id = UUID()
        let message: String
    }

    private(set) var current: Item?
    @ObservationIgnored private var window: UIWindow?
    @ObservationIgnored private var hiding: Task<Void, Never>?

    func error(_ message: String) {
        install()
        current = Item(message: message)
        UINotificationFeedbackGenerator().notificationOccurred(.error)
        hiding?.cancel()
        hiding = Task { [weak self] in
            try? await Task.sleep(for: .seconds(4.5))
            guard !Task.isCancelled else { return }
            self?.current = nil
        }
    }

    func dismiss() {
        hiding?.cancel()
        current = nil
    }

    private func install() {
        guard window == nil else { return }
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        guard let scene = scenes.first(where: { $0.activationState == .foregroundActive }) ?? scenes.first
        else { return }
        let window = PassThroughWindow(windowScene: scene)
        window.windowLevel = .alert + 1
        let host = UIHostingController(rootView: ToastLayer())
        host.view.backgroundColor = .clear
        window.rootViewController = host
        window.isHidden = false
        self.window = window
    }
}

private final class PassThroughWindow: UIWindow {
    override func hitTest(_ point: CGPoint, with event: UIEvent?) -> UIView? {
        let hit = super.hitTest(point, with: event)
        return hit === rootViewController?.view ? nil : hit
    }
}

private struct ToastLayer: View {
    @State private var toasts = Toasts.shared

    var body: some View {
        VStack {
            if let item = toasts.current {
                ToastView(message: item.message)
                    .id(item.id)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .onTapGesture { toasts.dismiss() }
                    .gesture(DragGesture(minimumDistance: 8).onEnded { drag in
                        if drag.translation.height < 0 { toasts.dismiss() }
                    })
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16)
        .padding(.top, 6)
        .animation(.spring(duration: 0.4, bounce: 0.2), value: toasts.current)
    }
}

private struct ToastView: View {
    let message: String

    var body: some View {
        HStack(spacing: 12) {
            ErrorBadge(size: 26)
            Text(message)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.white)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .frame(maxWidth: 520)
        .glassEffect(.regular.tint(.black.opacity(0.45)), in: .rect(cornerRadius: 22))
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isStaticText)
    }
}

struct ErrorBadge: View {
    var size: CGFloat = 22

    var body: some View {
        Image(systemName: "exclamationmark.circle.fill")
            .resizable()
            .symbolRenderingMode(.palette)
            .foregroundStyle(.white, Palette.danger)
            .frame(width: size, height: size)
            .accessibilityLabel("Failed")
    }
}
