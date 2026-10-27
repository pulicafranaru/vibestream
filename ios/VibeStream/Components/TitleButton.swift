import SwiftUI

enum TitleAction: Equatable {
    case download
    case queuing
    case waiting
    /// Nil under 1%, so a slow start does not read as stalled.
    case downloading(Double?)
    case preparing(Double?)
    case play(String)
    case failed(String)

    var busy: Bool {
        switch self {
        case .queuing, .waiting, .downloading, .preparing: return true
        case .download, .play, .failed: return false
        }
    }

    // `optimistic` only applies while the server has nothing to say: a real answer wins.
    static func of(_ live: DownloadState?, resume: String? = nil,
                   optimistic: Bool = false) -> TitleAction {
        guard let live, live.state != "removed" else {
            return optimistic ? .queuing : .download
        }
        if live.isPlayable { return .play(resume ?? "Play") }
        if live.prepareError != nil {
            return .failed("It arrived but could not be made playable. Try again.")
        }
        if live.isPreparing { return .preparing(live.preparePercent) }
        if live.state == "error" {
            return .failed(live.errorMessage ?? "The download could not start. Try again.")
        }
        if live.state == "downloading" {
            return .downloading(live.percent >= 1 ? live.percent : nil)
        }
        if live.isWorking { return .waiting }
        return optimistic ? .queuing : .download
    }
}

struct TitleButton: View {
    let action: TitleAction
    var onPress: () -> Void

    private var label: String {
        switch action {
        case .download: return "Download"
        case .queuing: return "Starting download"
        case .waiting: return "Waiting for download"
        case .downloading(let percent):
            return percent == nil ? "Downloading" : "Downloading \(Int(percent!))%"
        case .preparing(let percent):
            return percent == nil ? "Preparing" : "Preparing \(Int(percent!))%"
        case .play(let text): return text
        case .failed: return "Try again"
        }
    }

    var body: some View {
        Button(action: onPress) {
            HStack(spacing: 10) {
                switch action {
                case .download:
                    Image(systemName: "arrow.down.to.line").font(.headline)
                case .play:
                    Image(systemName: "play.fill").font(.headline)
                case .failed:
                    Image(systemName: "arrow.clockwise").font(.headline)
                case .queuing, .waiting:
                    DownloadRing(percent: nil, size: 22, showsLabel: false)
                case .downloading(let percent):
                    DownloadRing(percent: percent, size: 22, showsLabel: false)
                case .preparing(let percent):
                    DownloadRing(percent: percent, size: 22, showsLabel: false)
                }

                Text(label)
                    .font(.headline)
                    .monospacedDigit()   // a ticking percentage must not jitter
                    .contentTransition(.numericText())
            }
        }
        .buttonStyle(PillButtonStyle(prominent: prominent))
        .overlay(alignment: .topTrailing) {
            if case .failed = action {
                ErrorBadge(size: 22)
                    .offset(x: 5, y: -5)
                    .transition(.scale.combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: label)
    }

    private var prominent: Bool {
        switch action {
        case .download, .play, .failed: return true
        default: return false
        }
    }
}

struct PillButtonStyle: ButtonStyle {
    var prominent = true

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(prominent ? Color.black : .white)
            .frame(maxWidth: .infinity)
            .frame(height: 46)
            .background(prominent ? Color.white : Color.white.opacity(0.16), in: .capsule)
            .contentShape(.capsule)
            .opacity(configuration.isPressed ? 0.8 : 1)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}
