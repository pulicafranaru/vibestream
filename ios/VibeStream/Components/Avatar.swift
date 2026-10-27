import SwiftUI

enum AvatarArt {
    /// The ids are the server's, verbatim: they are the contract every client shares.
    static var colours: [(id: String, top: Color, bottom: Color)] { AvatarPalette.colours }

    static var faces: [String] { AvatarPalette.faces }

    static var all: [String] { colours.flatMap { c in faces.map { "\(c.id)-\($0)" } } }

    static func parts(_ id: String?) -> (colour: (id: String, top: Color, bottom: Color), face: String) {
        let pieces = (id ?? "crimson-smile").split(separator: "-", maxSplits: 1)
        let colour = colours.first { $0.id == pieces.first.map(String.init) } ?? colours[0]
        let face = pieces.count > 1 ? String(pieces[1]) : faces[0]
        return (colour, faces.contains(face) ? face : faces[0])
    }
}

struct Avatar: View {
    let id: String?
    var size: CGFloat = 96

    var body: some View {
        let (colour, face) = AvatarArt.parts(id)
        Circle()
            .fill(LinearGradient(colors: [colour.top, colour.bottom],
                                 startPoint: .top, endPoint: .bottom))
            .frame(width: size, height: size)
            .overlay { Image("avatar-\(face)").resizable().frame(width: size, height: size) }
    }
}
