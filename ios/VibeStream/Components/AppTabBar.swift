import SwiftUI

// Drawn by hand: the iOS 26 system tab bar is glass only, with no opaque appearance.
struct AppTabBar: View {
    @Binding var tab: String
    let avatar: String?
    @Namespace private var pill

    static let clearance: CGFloat = 70

    var body: some View {
        HStack(spacing: 4) {
            item("movie", "Movies") {
                Image(systemName: "film").font(.system(size: 18, weight: .regular))
            }
            item("tv", "Shows") {
                Image("ShowsGlyph")
                    .renderingMode(.template)
                    .resizable()
                    .scaledToFit()
                    .frame(width: 22, height: 22)
            }
            item("search", "Search") {
                Image(systemName: "magnifyingglass").font(.system(size: 18, weight: .regular))
            }
            item("mine", "Library") {
                Avatar(id: avatar, size: 22)
            }
        }
        .padding(4)
        .animation(.spring(duration: 0.4, bounce: 0.18), value: tab)
        .background(Capsule().fill(Color(white: 0.085)))
        .overlay(Capsule().strokeBorder(Color.white.opacity(0.09), lineWidth: 1))
        .shadow(color: .black.opacity(0.55), radius: 18, y: 6)
        .frame(maxWidth: 420)
        .padding(.horizontal, 18)
        .padding(.bottom, 2)
    }

    private func item<Icon: View>(
        _ value: String, _ label: String, @ViewBuilder icon: () -> Icon
    ) -> some View {
        let chosen = tab == value
        return Button {
            tab = value
        } label: {
            VStack(spacing: 3) {
                icon().frame(height: 22)
                Text(label)
                    .font(.system(size: 10, weight: .medium))
                    .lineLimit(1)
            }
            .foregroundStyle(chosen ? Color.white : Color(white: 0.62))
            .frame(maxWidth: .infinity)
            .padding(.vertical, 6)
            .background {
                if chosen {
                    Capsule().fill(Color(white: 0.17))
                        .matchedGeometryEffect(id: "pill", in: pill)
                }
            }
            .contentShape(.capsule)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityAddTraits(chosen ? .isSelected : [])
    }
}
