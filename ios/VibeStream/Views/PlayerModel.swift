import AVFoundation
import Combine
import SwiftUI

// AVPlayer against the server's HLS. The rendition is only served complete, so
// playback waits on /prepare before attaching it.
@MainActor
@Observable
final class PlayerModel {
    let playID: String
    let title: String

    private(set) var info: PlayInfo?
    private(set) var preparation: PlayInfo.Preparation?
    private(set) var trickplay: Trickplay?
    private(set) var ready = false
    private(set) var error: String?
    private(set) var ended = false

    var isPlaying = false
    private(set) var buffering = false
    var current: Double = 0
    var duration: Double = 0
    var rate: Float = 1.0

    /// Subtitles are an AVFoundation selection; audio needs a different server rendition.
    var subtitleID: String?
    var audioIndex: Int?

    let player = AVPlayer()
    var prefs = AppState.PlayerPrefs()

    private var timeObserver: Any?
    /// Where a pending seek is going, so time ticks do not drag the scrubber back.
    /// Numbered, so only the latest of several quick seeks lets go.
    private var seekTarget: Double?
    private var seekSerial = 0
    /// Drawn by the player, not AVFoundation. See CaptionReader.
    var caption: [String] = []
    private var captions: CaptionReader?
    private var statusTask: Task<Void, Never>?
    private var reportTask: Task<Void, Never>?
    /// The wait on /prepare and the attach after it. One at a time, and
    /// cancelled by stop.
    private var renditionTask: Task<Void, Never>?
    private var endTask: Task<Void, Never>?
    private var watchdog: Task<Void, Never>?
    private var rebuilt = false
    /// Paused by the person, which the start-up watchdog must not undo.
    private var heldByUser = false
    private var pendingResume: Double = 0
    @ObservationIgnored let trace: StartTrace
    private var traceTask: Task<Void, Never>?
    private var failTask: Task<Void, Never>?
    private var lastTick: Double = 0
    /// Playing the media playlist itself rather than the master: the way
    /// round iOS refusing an HDR variant to a screen being recorded. See
    /// recover(from:).
    private var directStream = false
    /// The subtitles read from the server's WebVTT while playing the media
    /// playlist on its own, which has none for AVFoundation to give.
    private var subtitleFile: SubtitleFile?
    private var cueObserver: Any?
    private var subtitleGeneration = 0
    private var startAt: Double?

    init(playID: String, title: String, startAt: Double? = nil) {
        self.playID = playID
        self.title = title
        self.startAt = startAt
        self.trace = StartTrace(playID: playID)
    }

    func start() async {
        configureAudioSession()
        trace.mark("asked to start, startAt \(startAt.map { String($0) } ?? "none")")
        #if DEBUG
        // -directStream: start on the media playlist alone, as after -11868.
        if ProcessInfo.processInfo.arguments.contains("-directStream") { directStream = true }
        #endif
        do {
            let info = try await APIClient.shared.playInfo(playID)
            self.info = info
            pendingResume = startAt ?? info.resume?.seconds ?? 0
            trace.mark("info: engine \(info.playback.engine ?? "?"), resume \(info.resume?.seconds ?? 0), "
                       + "runtime \(info.resume?.runtime ?? 0)")
            subtitleID = Self.preferredSubtitle(in: info.subtitles, prefs: prefs)
            rate = prefs.speed
            // Its own task, not the view's: a page over the player must not
            // cancel the wait. stop() does.
            await prepareRendition().value
        } catch {
            trace.mark("info failed: \(error.localizedDescription)")
            self.error = error.localizedDescription
        }
    }

    @discardableResult
    private func prepareRendition() -> Task<Void, Never> {
        renditionTask?.cancel()
        let task = Task<Void, Never> { [weak self] in await self?.waitForRendition() }
        renditionTask = task
        return task
    }

    private func waitForRendition() async {
        while !Task.isCancelled && !stopped {
            do {
                let state = try await APIClient.shared.prepare(playID, audio: audioIndex)
                guard !Task.isCancelled, !stopped else { return }
                preparation = state
                trace.mark("prepare: ready \(state.ready), error \(state.error ?? "none")")
                if let message = state.error { error = message; return }
                if state.ready { await attach(); return }
            } catch {
                // Transient; the server answers 503 while it is still muxing.
                trace.mark("prepare failed: \(error.localizedDescription)")
            }
            try? await Task.sleep(for: .seconds(2))
        }
    }

    private func attach() async {
        guard let info, !stopped else { return }
        var path = info.playback.hls
        if directStream { path = path.replacingOccurrences(of: "master.m3u8", with: "index.m3u8") }
        if let audioIndex { path += "?audio=\(audioIndex)" }
        guard let url = try? await APIClient.shared.url(for: path) else {
            error = "Cannot reach the server"
            return
        }
        guard !stopped, !Task.isCancelled else { return }

        let item = AVPlayerItem(url: url)
        let reader = CaptionReader()
        reader.onLines = { [weak self] lines in
            guard let self, !self.directStream else { return }
            self.caption = lines
        }
        item.add(reader.output)
        captions = reader
        caption = []
        if directStream { Task { await loadSubtitleFile() } } else { dropSubtitleFile() }
        trace.watch(item, player: player)
        trace.mark("attach \(url.path)\(url.query.map { "?" + $0 } ?? "")")
        trace.mark("replace item (had one: \(player.currentItem != nil))")
        player.replaceCurrentItem(with: item)
        player.actionAtItemEnd = .pause
        traceStart(item)
        isPlaying = true
        heldByUser = false
        observe(item)
        loadTrickplay()
        watchStart(item)
    }

    // Strictly in order: ready, subtitles, seek to the resume point, then play.
    // Playing first and seeking on the first tick could leave AVPlayer paused on black at 0:00.
    private func begin(_ item: AVPlayerItem) async {
        let length = item.duration.seconds
        if length.isFinite && length > 0 { duration = length }
        trace.mark("begin: duration \(length), pending \(pendingResume), startAt \(startAt.map { String($0) } ?? "none")")
        if let target = resumeTarget() {
            seekSerial += 1
            current = target
            seekTarget = target
            trace.mark("seek to \(target)")
            let finished = await player.seek(to: CMTime(seconds: target, preferredTimescale: 600),
                                             toleranceBefore: .zero, toleranceAfter: .zero)
            trace.mark("seek done, finished \(finished), now at \(player.currentTime().seconds)")
            seekTarget = nil
        } else {
            trace.mark("no resume")
        }
        guard !stopped, player.currentItem === item else {
            trace.mark("begin abandoned: stopped \(stopped), item replaced \(player.currentItem !== item)")
            return
        }
        ready = true
        if !heldByUser {
            player.play()
            if rate != 1 { player.rate = rate }
            trace.mark("play, rate \(player.rate)")
        } else {
            trace.mark("held by the user, not played")
        }
    }

    private func resumeTarget() -> Double? {
        defer { startAt = nil }
        if startAt != nil {
            return duration > 0 ? min(pendingResume, duration - 1) : pendingResume
        }
        guard pendingResume > 30, duration == 0 || pendingResume < duration - 60 else { return nil }
        return pendingResume
    }

    // A start with no play and no new data for 15 s is rebuilt once, then shown as an error.
    // Only the start: once it has played, a pause is external (a call, AirPods out).
    private func watchStart(_ item: AVPlayerItem) {
        watchdog?.cancel()
        watchdog = Task { [weak self] in
            var loaded = -1.0
            var still = 0
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard let self, !self.stopped, self.player.currentItem === item else { return }
                if item.status == .failed { return }
                if self.player.timeControlStatus == .playing && self.current > 0 { return }
                if self.heldByUser { return }
                let now = item.loadedTimeRanges.reduce(0.0) { $0 + $1.timeRangeValue.duration.seconds }
                if now != loaded {
                    loaded = now
                    still = 0
                    continue
                }
                still += 1
                guard still >= 15 else { continue }
                self.trace.mark("watchdog: nothing for 15 s, rebuilt before \(self.rebuilt)")
                self.trace.send("stall")
                if self.rebuilt {
                    self.error = "The video stopped loading. Try again."
                    self.player.pause()
                } else {
                    self.rebuilt = true
                    self.restart(at: self.seekTarget ?? (self.current > 0 ? self.current : self.pendingResume))
                }
                return
            }
        }
    }

    private func traceStart(_ item: AVPlayerItem) {
        traceTask?.cancel()
        traceTask = Task { [weak self] in
            var firstMoving: Double?
            for _ in 0..<90 {
                try? await Task.sleep(for: .seconds(1))
                guard let self, !self.stopped, self.player.currentItem === item else { return }
                self.trace.snapshot(self.player, model: self.current)
                let now = self.player.currentTime().seconds
                if self.player.timeControlStatus == .playing {
                    // Ten seconds, not one: a rewind a second in must land inside the trace.
                    if let first = firstMoving, now - first >= 10 {
                        self.trace.send("ok")
                        return
                    }
                    if firstMoving == nil { firstMoving = now }
                }
            }
            self?.trace.mark("watched for 90 s without ten seconds of play")
            self?.trace.send("slow")
        }
    }

    private func restart(at position: Double) {
        trace.mark("restart at \(position)")
        ready = false
        error = nil
        startAt = position
        pendingResume = position
        prepareRendition()
    }

    // -11868: iOS refuses an HDR variant to an external display, which includes screen recording
    // and mirroring. Retried once on the media playlist alone, with subtitles from the WebVTT file.
    static let noCompatibleAlternates = -11868

    private func recover(from failure: NSError?) {
        trace.mark("failed: \(failure.map { "\($0.domain) \($0.code) \($0.localizedDescription)" } ?? "no error")")
        let position = seekTarget ?? (current > 0 ? current : pendingResume)
        if failure?.code == Self.noCompatibleAlternates {
            if !directStream {
                directStream = true
                trace.mark("retrying from the media playlist, subtitles from their file")
                restart(at: position)
                return
            }
            error = "HDR video can't play while the screen is being recorded or mirrored. "
                + "Stop the recording, then try again."
        } else {
            error = failure.map { "\($0.localizedDescription) · \($0.domain) \($0.code)" }
                ?? "Playback stopped."
        }
        trace.mark("shown: \(error ?? "")")
        trace.send("failed")
        player.pause()
    }

    func retry() {
        directStream = false
        trace.mark("Try Again pressed")
        rebuilt = false
        restart(at: current > 0 ? current : pendingResume)
    }

    /// Off stays off. A forced track is passed over for a full one in the same language.
    static func preferredSubtitle(in tracks: [PlayInfo.Track], prefs: AppState.PlayerPrefs) -> String? {
        if prefs.subtitlesOff { return nil }
        if let language = prefs.subtitleLanguage {
            let matching = tracks.filter { $0.language == language }
            if let full = matching.first(where: { $0.forced != true }) ?? matching.first {
                return full.id
            }
        }
        return tracks.first(where: { $0.default == true })?.id
    }

    private func observe(_ item: AVPlayerItem) {
        // Four ticks a second: enough for the scrubber to look continuous,
        // few enough not to re-render the chrome constantly.
        if let timeObserver { player.removeTimeObserver(timeObserver) }
        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.25, preferredTimescale: 600), queue: .main
        ) { [weak self] time in
            guard let self else { return }
            MainActor.assumeIsolated {
                if self.seekTarget == nil && time.seconds < self.lastTick - 0.3 {
                    self.trace.mark("clock went back from \(self.lastTick) to \(time.seconds)")
                }
                self.lastTick = time.seconds
                if self.seekTarget == nil { self.current = time.seconds }
                // From the player itself: calls, AirPods and the end of the file pause it too.
                let status = self.player.timeControlStatus
                self.isPlaying = status != .paused
                self.buffering = status == .waitingToPlayAtSpecifiedRate
                if self.duration == 0 {
                    let reported = item.duration.seconds
                    self.duration = reported.isFinite && reported > 0
                        ? reported
                        : (self.info?.resume?.runtime ?? 0)
                }
            }
        }

        statusTask?.cancel()
        statusTask = Task { [weak self] in
            // AVPlayerItem reports readiness asynchronously and there is no
            // async sequence for it, so poll briefly rather than bolt on KVO.
            while !Task.isCancelled {
                guard let self else { return }
                if item.status == .readyToPlay {
                    self.applySubtitleSelection()
                    self.applySubtitleAppearance()
                    await self.begin(item)
                    return
                }
                if item.status == .failed {
                    if (item.error as NSError?)?.code == Self.noCompatibleAlternates {
                        self.recover(from: item.error as NSError?)
                    } else {
                        self.error = Self.failure(item)
                    }
                    return
                }
                try? await Task.sleep(for: .milliseconds(200))
            }
        }

        endTask?.cancel()
        endTask = Task { [weak self] in
            let ends = NotificationCenter.default.notifications(
                named: AVPlayerItem.didPlayToEndTimeNotification, object: item
            )
            for await _ in ends {
                guard let self else { return }
                self.ended = true
                self.report()   // the end counts as watched straight away
            }
        }

        // A mid-play failure only arrives here: the item stays "ready" on a black picture.
        failTask?.cancel()
        failTask = Task { [weak self] in
            let failures = NotificationCenter.default.notifications(
                named: AVPlayerItem.failedToPlayToEndTimeNotification, object: item
            )
            for await note in failures {
                guard let self else { return }
                let failure = note.userInfo?[AVPlayerItemFailedToPlayToEndTimeErrorKey] as? NSError
                self.recover(from: failure)
                return
            }
        }

        startReporting()
    }

    func stop() {
        // Called on X and again as the screen goes; the second is a no-op.
        guard !stopped else { return }
        stopped = true
        trace.mark("stop, at \(player.currentTime().seconds)")
        if !trace.hasSent("ok") { trace.send("closed") }
        trace.unwatch()
        renditionTask?.cancel()
        traceTask?.cancel()
        failTask?.cancel()
        dropSubtitleFile()
        Task { SheetStore.shared.forget(await sheetURLs()) }
        reportTask?.cancel()
        endTask?.cancel()
        statusTask?.cancel()
        watchdog?.cancel()
        if let timeObserver { player.removeTimeObserver(timeObserver) }
        timeObserver = nil
        report()                 // last position on the way out
        player.pause()
        player.replaceCurrentItem(with: nil)
        // Deactivating the session blocks until the system is done, so do it off the main thread.
        Task.detached(priority: .utility) {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    private var stopped = false

    func togglePlay() {
        if player.timeControlStatus == .paused {
            heldByUser = false
            player.play()
            player.rate = rate
            isPlaying = true
        } else {
            heldByUser = true
            player.pause()
            isPlaying = false
        }
    }

    func seek(to seconds: Double, from caller: String = #fileID, line: Int = #line) {
        trace.mark("seek(to: \(seconds)) from \(caller):\(line), at \(player.currentTime().seconds)")
        if seconds < duration - 1 { ended = false }
        let clamped = max(0, min(seconds, max(duration - 1, 0)))
        current = clamped
        // Zero tolerance: the complete VOD rendition makes any position reachable.
        seekSerial += 1
        let serial = seekSerial
        seekTarget = clamped
        player.seek(to: CMTime(seconds: clamped, preferredTimescale: 600),
                    toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.seekSerial == serial else { return }
                self.seekTarget = nil
            }
        }
    }

    func skip(_ delta: Double) { seek(to: current + delta) }

    func setRate(_ value: Float) {
        rate = value
        if isPlaying { player.rate = value }
    }

    private func applySubtitleSelection() {
        guard let item = player.currentItem,
              let group = item.asset.mediaSelectionGroup(forMediaCharacteristic: .legible)
        else { return }

        guard let subtitleID,
              let label = info?.subtitles.first(where: { $0.id == subtitleID })?.label,
              let option = group.options.first(where: { $0.displayName == label })
                ?? group.options.first
        else {
            item.select(nil, in: group)
            return
        }
        item.select(option, in: group)
    }

    func chooseSubtitle(_ id: String?) {
        subtitleID = id
        if id == nil { caption = [] }
        applySubtitleSelection()
        if directStream { Task { await loadSubtitleFile() } }
    }

    /// For the media playlist alone: the chosen track fetched whole and timed here, ten looks a second.
    private func loadSubtitleFile() async {
        dropSubtitleFile()
        // Only the latest load attaches: a drop or a newer load moves this on.
        let generation = subtitleGeneration
        guard let subtitleID,
              let url = try? await APIClient.shared.url(for: "/api/play/\(playID)/subs/\(subtitleID).vtt"),
              let (data, _) = try? await URLSession.shared.data(from: url),
              let text = String(data: data, encoding: .utf8),
              subtitleID == self.subtitleID, !stopped, generation == subtitleGeneration else {
            trace.mark("subtitles from the file: none")
            return
        }
        let file = SubtitleFile(vtt: text)
        subtitleFile = file
        trace.mark("subtitles from the file: \(subtitleID), \(file.cues.count) cues")
        if let cueObserver { player.removeTimeObserver(cueObserver) }
        cueObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.1, preferredTimescale: 600), queue: .main
        ) { [weak self] time in
            MainActor.assumeIsolated {
                guard let self, let file = self.subtitleFile else { return }
                let lines = file.lines(at: time.seconds)
                if lines != self.caption { self.caption = lines }
            }
        }
    }

    private func dropSubtitleFile() {
        subtitleGeneration += 1
        if let cueObserver { player.removeTimeObserver(cueObserver) }
        cueObserver = nil
        subtitleFile = nil
    }

    /// AVFoundation draws the subtitles while the picture is in the system's
    /// window, which the app cannot draw into; the player draws them
    /// everywhere else.
    func systemDrawsCaptions(_ yes: Bool) {
        captions?.output.suppressesPlayerRendering = !yes
        if yes { caption = [] }
    }

    /// Only for picture in picture, and only as far as the device's caption settings allow.
    func applySubtitleAppearance() {
        player.currentItem?.textStyleRules = SubtitleLook.rules(size: prefs.subtitleSize,
                                                                 style: prefs.subtitleStyle)
    }

    /// Switching audio means a different rendition on the server, so the item
    /// is rebuilt and the position carried across.
    func chooseAudio(_ index: Int?) {
        guard index != audioIndex else { return }
        let resumeAt = current
        audioIndex = index
        player.pause()
        ready = false
        startAt = resumeAt
        pendingResume = resumeAt
        prepareRendition()
    }

    private func loadTrickplay() {
        Task { [playID] in
            guard let manifest = try? await APIClient.shared.trickplay(playID),
                  manifest.isUsable else { return }
            self.trickplay = manifest
            try? await Task.sleep(for: .seconds(4))
            let urls = await self.sheetURLs()
            SheetStore.shared.prefetch(urls)
        }
    }

    func sheetURLs() async -> [URL] {
        guard let t = trickplay, t.isUsable, let base = t.url,
              let perSheet = t.perSheet, perSheet > 0, let count = t.count else { return [] }
        let sheets = (count + perSheet - 1) / perSheet
        var urls: [URL] = []
        for sheet in 0..<sheets {
            if let url = try? await APIClient.shared.url(for: "\(base)/\(sheet).jpg") { urls.append(url) }
        }
        return urls
    }

    func thumbnail(at seconds: Double) async -> ThumbFrame? {
        guard let t = trickplay, t.isUsable,
              let base = t.url, let columns = t.columns,
              let perSheet = t.perSheet, let width = t.tileWidth, let height = t.tileHeight
        else { return nil }

        let index = t.frameIndex(at: seconds)
        let sheet = index / perSheet
        let cell = index % perSheet
        guard let url = try? await APIClient.shared.url(for: "\(base)/\(sheet).jpg") else {
            return nil
        }
        return ThumbFrame(
            url: url,
            cell: CGRect(x: CGFloat(cell % columns) * CGFloat(width),
                         y: CGFloat(cell / columns) * CGFloat(height),
                         width: CGFloat(width), height: CGFloat(height))
        )
    }

    private func startReporting() {
        reportTask?.cancel()
        reportTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(10))
                guard let self else { return }
                if self.isPlaying { self.report() }
            }
        }
    }

    func saveProgress() { report() }

    private func report() {
        guard duration > 0, current > 0 else { return }
        #if DEBUG
        // Scripted runs must not write watch history.
        if ProcessInfo.processInfo.arguments.contains("-noProgress") { return }
        #endif
        Task { [playID, current, duration] in
            await APIClient.shared.reportProgress(playID, position: current, duration: duration)
        }
    }

    /// AVFoundation's description is only "Cannot open"; the cause is in the underlying error and the error log.
    private static func failure(_ item: AVPlayerItem) -> String {
        guard let error = item.error as NSError? else {
            return "This title could not be played."
        }
        var parts = [error.localizedDescription]
        if let under = error.userInfo[NSUnderlyingErrorKey] as? NSError {
            parts.append("\(under.domain) \(under.code)")
        } else {
            parts.append("\(error.domain) \(error.code)")
        }
        if let event = item.errorLog()?.events.last {
            if let comment = event.errorComment, !comment.isEmpty {
                parts.append(comment)
            }
            if event.errorStatusCode != 0 {
                parts.append("status \(event.errorStatusCode)")
            }
        }
        return parts.joined(separator: " · ")
    }

    private func configureAudioSession() {
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .moviePlayback)
        try? session.setActive(true)
    }
}
