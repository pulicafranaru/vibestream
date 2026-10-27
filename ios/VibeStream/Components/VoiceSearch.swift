import AVFoundation
import Speech

// On device only (`requiresOnDeviceRecognition`), primed with catalog titles.
@MainActor @Observable
final class VoiceSearch {
    private(set) var listening = false
    private(set) var heard = ""
    var problem: String?

    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var readings: [String] = []
    private var quiet: Task<Void, Never>?
    private var limit: Task<Void, Never>?
    private var done: (([String]) -> Void)?

    private let pause: Duration = .milliseconds(1300)
    private let longest: Duration = .seconds(12)

    func start(hints: [String], done: @escaping ([String]) -> Void) async {
        guard !listening else { return }
        problem = nil
        guard await allowed() else {
            problem = "Voice search needs the microphone and speech recognition. Turn them on for VibeStream in Settings."
            return
        }
        guard let recognizer = Self.recognizer() else {
            problem = "This iPhone cannot recognise speech on the device for its language, and voice search does not send your voice anywhere else."
            return
        }

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = true
        request.taskHint = .search
        request.addsPunctuation = false
        request.contextualStrings = Array(hints.prefix(100))

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            let input = engine.inputNode
            input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { buffer, _ in
                request.append(buffer)
            }
            engine.prepare()
            try engine.start()
        } catch {
            teardown()
            problem = "The microphone is not available right now."
            return
        }

        self.request = request
        self.done = done
        readings = []
        heard = ""
        listening = true
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            let texts = result.map { r in
                [r.bestTranscription.formattedString] + r.transcriptions.map(\.formattedString)
            }
            let final = result?.isFinal ?? false
            let failed = error != nil
            Task { @MainActor in self?.update(texts, final: final, failed: failed) }
        }
        limit = Task { [weak self, longest] in
            try? await Task.sleep(for: longest)
            if !Task.isCancelled { self?.stop() }
        }
    }

    func stop() {
        guard listening else { return }
        request?.endAudio()
        quiet?.cancel()
        quiet = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(700))
            if !Task.isCancelled { self?.finish() }
        }
    }

    func cancel() {
        guard listening else { return }
        done = nil
        task?.cancel()
        teardown()
    }

    private func update(_ texts: [String]?, final: Bool, failed: Bool) {
        guard listening else { return }
        if let texts, let best = texts.first, !best.isEmpty {
            var unique: [String] = []
            for t in texts where !t.isEmpty && !unique.contains(t) { unique.append(t) }
            readings = Array(unique.prefix(6))
            heard = best
            quiet?.cancel()
            quiet = Task { [weak self, pause] in
                try? await Task.sleep(for: pause)
                if !Task.isCancelled { self?.stop() }
            }
        }
        if final || failed { finish() }
    }

    private func finish() {
        guard listening else { return }
        let heard = readings
        let done = self.done
        task?.finish()
        teardown()
        if heard.isEmpty {
            problem = "Didn't catch that. Try again?"
        } else {
            done?(heard)
        }
    }

    private func teardown() {
        quiet?.cancel()
        limit?.cancel()
        if engine.isRunning { engine.stop() }
        engine.inputNode.removeTap(onBus: 0)
        request = nil
        task = nil
        done = nil
        listening = false
        heard = ""
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    /// Falls back to English, which every on-device model covers.
    private static func recognizer() -> SFSpeechRecognizer? {
        for locale in [Locale.current, Locale(identifier: "en-US")] {
            if let r = SFSpeechRecognizer(locale: locale), r.supportsOnDeviceRecognition, r.isAvailable {
                return r
            }
        }
        return nil
    }

    private func allowed() async -> Bool {
        let speech = await withCheckedContinuation { (go: CheckedContinuation<Bool, Never>) in
            SFSpeechRecognizer.requestAuthorization { go.resume(returning: $0 == .authorized) }
        }
        guard speech else { return false }
        return await AVAudioApplication.requestRecordPermission()
    }
}
