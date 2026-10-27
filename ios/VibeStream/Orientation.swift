import OSLog
import SwiftUI
import UIKit

// iPhone: the app is portrait and the player turns with the phone. iPad: turns freely.
// requestGeometryUpdate needs both `allowed` updated and the root controller told
// to ask again; either alone silently does nothing.
final class AppDelegate: NSObject, UIApplicationDelegate {
    static var allowed: UIInterfaceOrientationMask = Orientation.base

    func application(
        _ application: UIApplication,
        supportedInterfaceOrientationsFor window: UIWindow?
    ) -> UIInterfaceOrientationMask {
        AppDelegate.allowed
    }

    func application(
        _ application: UIApplication,
        configurationForConnecting session: UISceneSession,
        options: UIScene.ConnectionOptions
    ) -> UISceneConfiguration {
        let configuration = UISceneConfiguration(name: nil, sessionRole: session.role)
        configuration.delegateClass = SceneDelegate.self
        return configuration
    }
}

// Opens full size on the iPad. The system restores a remembered window frame and
// only honours a minimum size, so that is set to the screen briefly and then let
// go (leaving it pins the size on rotation). UIRequiresFullScreen is ignored on iPadOS 26.
final class SceneDelegate: NSObject, UIWindowSceneDelegate {
    func scene(
        _ scene: UIScene,
        willConnectTo session: UISceneSession,
        options connectionOptions: UIScene.ConnectionOptions
    ) {
        guard UIDevice.current.userInterfaceIdiom == .pad,
              let windowScene = scene as? UIWindowScene,
              let restrictions = windowScene.sizeRestrictions else { return }
        let relaxed = restrictions.minimumSize
        restrictions.minimumSize = windowScene.screen.bounds.size
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
            restrictions.minimumSize = relaxed
        }
    }
}

enum Orientation {
    private static var freeToTurn: Bool {
        UIDevice.current.userInterfaceIdiom == .pad
    }

    static var base: UIInterfaceOrientationMask { freeToTurn ? .all : .portrait }

    // Only a player on screen may turn the app. A closing player is counted off at
    // once, so a late request from it is refused.
    private(set) static var playersOnScreen = 0

    static func playerAppeared() {
        playersOnScreen += 1
        note("player on screen (\(playersOnScreen))")
    }

    /// `release` false when the next player takes its place at once.
    static func playerLeft(release: Bool = true) {
        playersOnScreen = max(0, playersOnScreen - 1)
        note("player off screen (\(playersOnScreen)), release \(release)")
        if release && playersOnScreen == 0 { Orientation.release() }
    }

    /// A no-op where the app turns freely, unless `everywhere`. `fromPlayer` needs a
    /// player on screen.
    static func lock(_ mask: UIInterfaceOrientationMask, everywhere: Bool = false,
                     fromPlayer: Bool = false) {
        guard everywhere || !freeToTurn else { return }
        if fromPlayer && playersOnScreen == 0 {
            note("refused a player's \(name(mask)): no player on screen")
            return
        }
        AppDelegate.allowed = mask
        note("lock \(name(mask))\(fromPlayer ? " for the player" : "")")
        guard let scene = UIApplication.shared.connectedScenes
            .compactMap({ $0 as? UIWindowScene }).first else { return }
        scene.keyWindow?.rootViewController?.setNeedsUpdateOfSupportedInterfaceOrientations()
        scene.requestGeometryUpdate(.iOS(interfaceOrientations: mask)) { error in
            // Refusals are not exceptional: iPad multitasking declines them.
            Logger(subsystem: "VibeStream", category: "orientation")
                .debug("orientation request refused: \(error.localizedDescription)")
            let text = "refused by the system: \(error.localizedDescription)"
            Task { @MainActor in note(text) }
        }
    }

    static func release() {
        lock(base, everywhere: true)
        settleUpright()
    }

    // Recent orientation events, sent to the server if the app is still sideways
    // 8 s after going back to portrait.
    private static var events: [String] = []
    private static let started = Date()

    static func note(_ text: String) {
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        let window = scene.map { describe($0.effectiveGeometry.interfaceOrientation) } ?? "-"
        let device = describe(UIDevice.current.orientation)
        events.append(String(format: "%9.3f  ", Date().timeIntervalSince(started))
                      + "\(text) [window \(window), phone \(device), allowed \(name(AppDelegate.allowed))]")
        if events.count > 200 { events.removeFirst(events.count - 200) }
    }

    private static func name(_ mask: UIInterfaceOrientationMask) -> String {
        switch mask {
        case .portrait: return "portrait"
        case .landscape: return "landscape"
        case .landscapeLeft: return "landscapeLeft"
        case .landscapeRight: return "landscapeRight"
        case .allButUpsideDown: return "allButUpsideDown"
        case .all: return "all"
        case .portraitUpsideDown: return "upsideDown"
        default: return "mask \(mask.rawValue)"
        }
    }

    private static func describe(_ orientation: UIInterfaceOrientation) -> String {
        switch orientation {
        case .portrait: return "portrait"
        case .portraitUpsideDown: return "upsideDown"
        case .landscapeLeft: return "landscapeLeft"
        case .landscapeRight: return "landscapeRight"
        default: return "unknown"
        }
    }

    private static func describe(_ orientation: UIDeviceOrientation) -> String {
        switch orientation {
        case .portrait: return "portrait"
        case .portraitUpsideDown: return "upsideDown"
        case .landscapeLeft: return "landscapeLeft"
        case .landscapeRight: return "landscapeRight"
        case .faceUp: return "faceUp"
        case .faceDown: return "faceDown"
        default: return "unknown"
        }
    }

    // A request made mid-rotation can be refused with no retry, so keep asking until settled.
    private static func settleUpright() {
        guard !freeToTurn else { return }
        let delays = [0.3, 0.7, 1.3, 2.2, 3.5, 5.0, 6.5, 8.0]
        for delay in delays {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
                guard AppDelegate.allowed == base, playersOnScreen == 0,
                      let scene = UIApplication.shared.connectedScenes
                        .compactMap({ $0 as? UIWindowScene }).first,
                      scene.effectiveGeometry.interfaceOrientation.isLandscape else { return }
                if delay == delays.last {
                    note("still sideways \(delay) s after release")
                    let lines = events
                    Task { await APIClient.shared.sendDiag("orientation", reason: "stuck", lines: lines) }
                }
                note("settle at \(delay) s: still sideways, asking again")
                lock(base, everywhere: true)
            }
        }
    }

    static var player: UIInterfaceOrientationMask { freeToTurn ? .all : .allButUpsideDown }

    static func holdCurrent() {
        guard playersOnScreen > 0 else { note("refused a player's hold: no player on screen"); return }
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        let mask: UIInterfaceOrientationMask
        switch scene?.effectiveGeometry.interfaceOrientation {
        case .landscapeLeft: mask = .landscapeLeft
        case .landscapeRight: mask = .landscapeRight
        case .portraitUpsideDown: mask = .portraitUpsideDown
        default: mask = .portrait
        }
        lock(mask, everywhere: true, fromPlayer: true)
    }
}
