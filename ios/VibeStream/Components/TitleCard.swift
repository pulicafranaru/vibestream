import SwiftUI

// Drawn by hand on the iPad: no presentation size gives a near full screen card.
struct TitleCard: View {
    let card: Card?
    var autoplay: PlayRequest? = nil
    let close: () -> Void

    private let portraitWidth: CGFloat = 1040
    private let landscapeWidth: CGFloat = 720

    var body: some View {
        GeometryReader { geo in
            let landscape = geo.size.width > geo.size.height
            ZStack(alignment: .top) {
                if let card {
                    Rectangle()
                        .fill(.ultraThinMaterial)
                        .overlay(Color.black.opacity(0.55))
                        .environment(\.colorScheme, .dark)
                        .ignoresSafeArea()
                        .onTapGesture(perform: close)
                        .transition(.opacity)

                    DetailView(card: card, autoplay: autoplay)
                        .environment(\.closeTitle, close)
                        .background(Palette.ground)
                        .clipShape(UnevenRoundedRectangle(topLeadingRadius: 18,
                                                          topTrailingRadius: 18))
                        .frame(maxWidth: landscape ? landscapeWidth : portraitWidth)
                        .padding(.horizontal, 14)
                        .padding(.top, 6)
                        .ignoresSafeArea(edges: .bottom)
                        .transition(.move(edge: .bottom))
                        .id(card.mediaID)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .top)
            .animation(.spring(duration: 0.4, bounce: 0.08), value: card?.mediaID)
        }
    }
}

extension EnvironmentValues {
    /// Set where the page is a card, where `dismiss` has nothing to dismiss.
    @Entry var closeTitle: (() -> Void)? = nil
    @Entry var openTitle: ((Card) -> Void)? = nil
}
