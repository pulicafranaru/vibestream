import AVKit
import SwiftUI

// Holds the PlayerModel while its screen is away, and hands it to the next player
// screen opened for the same title.
@MainActor
final class PictureInPicture: NSObject, AVPictureInPictureControllerDelegate {
    static let shared = PictureInPicture()

    static var supported: Bool { AVPictureInPictureController.isPictureInPictureSupported() }

    var reopen: ((PlayRequest) -> Void)?

    private var controller: AVPictureInPictureController?
    private weak var layer: AVPlayerLayer?
    private var model: PlayerModel?
    private var request: PlayRequest?
    private var leave: (() -> Void)?
    private var leaveOnStart = false
    private var screenAway = false
    private var restoring = false

    func attach(layer: AVPlayerLayer, model: PlayerModel, request: PlayRequest,
                leave: @escaping () -> Void) {
        guard Self.supported else { return }
        if screenAway, let old = self.model, old !== model {
            screenAway = false
            controller?.stopPictureInPicture()
            old.stop()
        }
        if self.layer !== layer {
            let controller = AVPictureInPictureController(playerLayer: layer)
            controller?.delegate = self
            controller?.canStartPictureInPictureAutomaticallyFromInline = true
            // Only play/pause on the window: seeking stays in the player.
            controller?.requiresLinearPlayback = true
            self.controller = controller
            self.layer = layer
        }
        self.model = model
        self.request = request
        self.leave = leave
    }

    /// False when the window cannot be had right now.
    @discardableResult
    func start() -> Bool {
        guard let controller, controller.isPictureInPicturePossible else { return false }
        leaveOnStart = true
        controller.startPictureInPicture()
        return true
    }

    func detach(_ model: PlayerModel) {
        guard self.model === model, !screenAway else { return }
        controller?.stopPictureInPicture()
        forget()
    }

    /// True during the hand-over to the window, which must not stop playback.
    func isHoldingPlayback(_ model: PlayerModel) -> Bool {
        screenAway && self.model === model
    }

    func takePlayback(for playID: String) -> PlayerModel? {
        guard screenAway, request?.playID == playID else { return nil }
        screenAway = false
        return model
    }

    private func forget() {
        controller = nil
        layer = nil
        model = nil
        request = nil
        leave = nil
        leaveOnStart = false
        screenAway = false
    }

    nonisolated func pictureInPictureControllerWillStartPictureInPicture(
        _ controller: AVPictureInPictureController
    ) {
        Task { @MainActor in model?.systemDrawsCaptions(true) }
    }

    nonisolated func pictureInPictureControllerWillStopPictureInPicture(
        _ controller: AVPictureInPictureController
    ) {
        Task { @MainActor in model?.systemDrawsCaptions(false) }
    }

    nonisolated func pictureInPictureControllerDidStartPictureInPicture(
        _ controller: AVPictureInPictureController
    ) {
        Task { @MainActor in
            guard leaveOnStart else { return }
            leaveOnStart = false
            screenAway = true
            leave?()
        }
    }

    nonisolated func pictureInPictureController(
        _ controller: AVPictureInPictureController,
        restoreUserInterfaceForPictureInPictureStopWithCompletionHandler completion: @escaping (Bool) -> Void
    ) {
        Task { @MainActor in
            guard screenAway, let request else {
                completion(true)
                return
            }
            restoring = true
            reopen?(request)
            // Let the player screen appear before the window flies back into it.
            try? await Task.sleep(for: .milliseconds(600))
            completion(true)
        }
    }

    nonisolated func pictureInPictureControllerDidStopPictureInPicture(
        _ controller: AVPictureInPictureController
    ) {
        Task { @MainActor in
            if restoring {
                restoring = false
                return
            }
            if screenAway {
                model?.stop()
                forget()
            }
        }
    }
}
