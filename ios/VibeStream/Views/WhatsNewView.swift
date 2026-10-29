import SwiftUI

/// What is new since this device last said, once after an update: a few
/// lines for whoever is watching, from the server's release notes.
struct WhatsNewView: View {
    let news: WhatsNew
    var onDone: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("New in \(news.version)")
                .font(.title2.weight(.bold))
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(news.releases.flatMap(\.items), id: \.self) { item in
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Circle().fill(Palette.accent).frame(width: 7, height: 7)
                            Text("\(Text(item.title).bold().foregroundStyle(.white))\(item.text)")
                                .foregroundStyle(Palette.dim)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            Button(action: onDone) {
                Text("Got it").font(.headline).frame(maxWidth: .infinity)
            }
            .buttonStyle(PillButtonStyle(prominent: true))
        }
        .padding(24)
    }
}
