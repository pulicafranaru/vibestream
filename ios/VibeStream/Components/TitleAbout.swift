import SwiftUI

// Names and genres are CollectionTarget links; the host catches them with openURL.
struct TitleAbout: View {
    let card: Card
    var heading = true
    var overview = false

    var body: some View {
        let facts = card.facts
        let cast = facts?.castAll ?? facts?.cast ?? []
        return VStack(alignment: .leading, spacing: 14) {
            if heading {
                Text("About \(card.title)")
                    .font(.title3.weight(.bold))
                    .foregroundStyle(.white)
            }
            if overview, let text = card.overview, !text.isEmpty {
                Text(text).font(.subheadline).foregroundStyle(Palette.dim)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let heading = facts?.crewHeading, let crew = facts?.crew, !crew.isEmpty {
                linkRow(heading, crew.map(person))
            }
            if !cast.isEmpty {
                linkRow("Cast", cast.map(person))
            }
            if let genres = card.genres, !genres.isEmpty {
                linkRow("Genres", genres.map { ($0, CollectionTarget(kind: .genre($0), title: $0)) })
            }
            if let keywords = facts?.keywords, !keywords.isEmpty {
                aboutRow(card.isSeries ? "This show is about" : "This movie is about",
                         keywords.map { $0.prefix(1).uppercased() + $0.dropFirst() }
                            .joined(separator: ", "))
            }
            if let rating = facts?.certification, !rating.isEmpty {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("Maturity Rating:").foregroundStyle(Palette.faint)
                    Text(rating)
                        .font(.footnote.weight(.semibold))
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .overlay(RoundedRectangle(cornerRadius: 3)
                            .strokeBorder(.white.opacity(0.6), lineWidth: 1))
                        .foregroundStyle(.white)
                    if let meaning = Self.ratingMeaning[rating] {
                        Text(meaning).foregroundStyle(.white)
                    }
                }
            }
            if let quality = card.quality {
                aboutRow("Quality", [quality.source, quality.codec, quality.audio]
                    .compactMap { $0 }.joined(separator: "  ·  "))
            }
        }
        .font(.subheadline)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func person(_ name: String) -> (String, CollectionTarget?) {
        let id = card.facts?.personIDs?[name]
        return (name, id.map { CollectionTarget(kind: .person($0), title: name) })
    }

    private func linkRow(_ label: String, _ values: [(String, CollectionTarget?)]) -> some View {
        Self.linkRow(label, values)
    }

    static func linkRow(_ label: String, _ values: [(String, CollectionTarget?)]) -> some View {
        var text = AttributedString("\(label): ")
        text.foregroundColor = Palette.faint
        for (index, (name, target)) in values.enumerated() {
            if index > 0 {
                var comma = AttributedString(", ")
                comma.foregroundColor = Palette.faint
                text += comma
            }
            var part = AttributedString(name)
            if let url = target?.url {
                part.link = url
                part.foregroundColor = .white
            } else {
                part.foregroundColor = Palette.dim
            }
            text += part
        }
        return Text(text)
            .tint(.white)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func aboutRow(_ label: String, _ value: String) -> some View {
        Text("\(Text("\(label): ").foregroundStyle(Palette.faint))\(value)")
            .foregroundStyle(.white)
            .fixedSize(horizontal: false, vertical: true)
    }

    private static let ratingMeaning: [String: String] = [
        "G": "General Audiences", "PG": "Parental Guidance Suggested",
        "PG-13": "Parents Strongly Cautioned", "R": "Restricted",
        "NC-17": "Adults Only", "TV-Y": "All Children", "TV-Y7": "Ages 7+",
        "TV-G": "General Audience", "TV-PG": "Parental Guidance Suggested",
        "TV-14": "Parents Strongly Cautioned", "TV-MA": "Mature Audience Only",
    ]
}
