import Foundation

/// One session on the Watch (design §2, §3): the 60 Hz stream in `watch/` (JSON chunks, sent as each
/// closes) and the high-rate stream in `watch_hf/` (binary chunks, sent after Stop), with a journal.
/// The Watch writes whether or not the phone is reachable. Not thread-safe: call from one queue.
public final class WatchRecorder {
    public let sessionID: String
    public let directory: String
    public let journal: Journal
    public let motion: ChunkWriter
    public let highRate: ChunkWriter
    public let outbox: TransferOutbox
    public private(set) var isClosed = false
    /// Called when the high-rate stream fails (the watchdog speaks a 🔴 alert; test W9).
    public var onHighRateFailed: ((String) -> Void)?

    private let store: FileStore
    private let clock: Clock
    private let link: WatchLink
    /// Running sample counts of the high-rate stream, written into each chunk's header.
    public private(set) var accelCount = 0
    public private(set) var motionCount = 0

    private init(
        store: FileStore, clock: Clock, link: WatchLink, sessionID: String, segment: Int, firstChunk: (Int, Int)
    ) {
        self.store = store
        self.clock = clock
        self.link = link
        self.sessionID = sessionID
        directory = "\(SessionRecorder.sessionsDir)/\(sessionID)"
        journal = Journal(store: store, clock: clock, path: "\(directory)/journal.jsonl")
        motion = ChunkWriter(
            store: store, clock: clock, journal: journal, directory: "\(directory)/watch", segment: segment,
            firstNumber: firstChunk.0)
        highRate = ChunkWriter(
            store: store, clock: clock, journal: journal, directory: "\(directory)/watch_hf", fileExtension: "bin",
            lineMode: false, segment: segment, firstNumber: firstChunk.1)
        outbox = TransferOutbox(
            store: store, clock: clock, link: link, journal: journal, sessionID: sessionID, sessionDir: directory)
        motion.onChunkClosed = { [unowned self] entry in outbox.add(chunkEntry: entry, kind: "60hz") }
        highRate.onChunkClosed = { [unowned self] entry in outbox.add(chunkEntry: entry, kind: "hf") }
        highRate.chunkHeader = { [unowned self] number in
            HighRateFormat.header([
                "session": sessionID, "segment": highRate.segment, "chunk": number,
                "first_index": ["accel": accelCount, "motion": motionCount],
                "boot_to_unix": clock.bootToUnix,
            ])
        }
    }

    /// Starts a session on the Watch. Blocks below 2 GB free, like the phone.
    public static func start(
        store: FileStore, clock: Clock, link: WatchLink, sessionID: String, metadata: [String: Any]
    ) throws -> WatchRecorder {
        guard store.freeBytes >= SessionRecorder.minFreeBytes else {
            throw SessionRecorder.StartError.lowDisk(freeBytes: store.freeBytes)
        }
        let r = WatchRecorder(
            store: store, clock: clock, link: link, sessionID: sessionID, segment: 1, firstChunk: (0, 0))
        for sub in ["watch", "watch_hf"] { try store.createDirectory("\(r.directory)/\(sub)") }
        try r.journal.open()
        var fields = metadata
        fields["session"] = sessionID
        fields["device"] = "watch"
        fields["boot_to_unix"] = clock.bootToUnix
        try r.journal.write("session_open", fields)
        return r
    }

    /// Continues a Watch session after a crash as a new segment (the Watch's half of design §4).
    public static func resume(store: FileStore, clock: Clock, link: WatchLink, sessionID: String) throws
        -> WatchRecorder
    {
        let dir = "\(SessionRecorder.sessionsDir)/\(sessionID)"
        let (entries, _) = try Journal.read(store: store, path: "\(dir)/journal.jsonl")
        let segment = SessionRecorder.currentSegment(entries) + 1
        func next(_ sub: String) -> Int {
            (((try? store.list("\(dir)/\(sub)")) ?? []).compactMap { Int($0.prefix(6)) }.max() ?? -1) + 1
        }
        let r = WatchRecorder(
            store: store, clock: clock, link: link, sessionID: sessionID, segment: segment,
            firstChunk: (next("watch"), next("watch_hf")))
        // Chunks closed before the crash but never acked go back into the outbox.
        let acked = Set(entries.filter { $0["j"] as? String == "chunk_acked" }.compactMap { $0["file"] as? String })
        for e in entries where e["j"] as? String == "chunk_closed" {
            guard let path = e["file"] as? String,
                !acked.contains(String(path.dropFirst(r.directory.count + 1)))
            else { continue }
            r.outbox.add(chunkEntry: e, kind: path.contains("/watch_hf/") ? "hf" : "60hz")
        }
        try r.journal.write("segment_open", ["segment": segment, "reason": "recovered_after_crash"])
        return r
    }

    /// Writes one 60 Hz packet (today's JSON format).
    @discardableResult
    public func recordMotion(_ packet: Data, firstIndex: Int, count: Int) -> Bool {
        motion.append(packet, device: "watch", firstIndex: firstIndex, count: count)
    }

    /// Writes any other packet (barometer, magnetometer) to the 60 Hz stream's chunks.
    @discardableResult
    public func recordOther(_ packet: Data) -> Bool { motion.append(packet) }

    /// Writes one batch of high-rate records (CMBatchedSensorManager delivers ~1 s per batch).
    @discardableResult
    public func recordHighRate(_ records: [HighRateFormat.Record]) -> Bool {
        guard !records.isEmpty else { return true }
        var data = Data()
        for r in records { data += HighRateFormat.encode(r) }
        let ok = highRate.append(data)
        if ok {
            for r in records {
                if case .accel = r { accelCount += 1 } else { motionCount += 1 }
            }
        }
        return ok
    }

    /// The high-rate stream didn't start or stopped; the 60 Hz stream carries on (test W9).
    public func highRateFailed(_ reason: String) {
        _ = try? journal.write("event", ["name": "high_rate_failed", "detail": reason])
        link.sendMessage(LinkMessage(kind: .highRateFailed, session: sessionID, detail: reason).encoded)
        onHighRateFailed?(reason)
    }

    /// The workout ended without Stop; tells the phone, which relaunches the Watch app (test W7).
    public func workoutEnded(_ reason: String) {
        _ = try? journal.write("event", ["name": "workout_ended", "detail": reason])
        link.sendMessage(LinkMessage(kind: .workoutEnded, session: sessionID, detail: reason).encoded)
    }

    /// Call about once a second: syncs/rotates chunks and resends overdue chunks.
    public func tick() {
        for writer in [motion, highRate] {
            do { try writer.tick() } catch { writer.onWriteError?(error) }
        }
        outbox.tick()
    }

    /// Closes both streams, then sends the high-rate chunks, a journal snapshot and the summary.
    public func stop() throws {
        guard !isClosed else { return }
        try motion.closeCurrent()
        try highRate.closeCurrent()
        try journal.write("session_close", ["clean": true])
        isClosed = true
        outbox.releaseHighRate()
        sendJournalSnapshot()
        link.sendMessage(
            LinkMessage(
                kind: .summary, session: sessionID, chunks60Hz: outbox.count(kind: "60hz"),
                chunksHighRate: outbox.count(kind: "hf")
            ).encoded)
    }

    /// A copy of the Watch journal goes to the phone so the Mac sees the Watch's side of the session.
    public func sendJournalSnapshot() {
        guard let data = try? store.read(journal.path) else { return }
        let path = "\(directory)/watch_journal.jsonl"
        guard (try? store.writeAtomically(data, to: path)) != nil else { return }
        outbox.add(chunkEntry: ["file": path, "sha256": sha256Hex(data)], kind: "journal")
    }

    /// True when every high-rate chunk is closed on the Watch disk (the court-exit check's condition).
    public var highRateClosedOnDisk: Bool { highRate.current == nil }
}

/// Phone side: notices when the Watch stops recording and asks it to restart (test W7).
public final class WatchSupervisor {
    /// No preview batch for this long while the Watch is reachable means it stopped.
    public var silenceTimeout: Double = 10
    public var onRelaunch: (() -> Void)?
    public var onEvent: ((String, String) -> Void)?
    /// Alert id for the watchdog (stage 7 speaks it): "watch_stopped", "high_rate_failed".
    public var onAlert: ((String) -> Void)?

    private let clock: Clock
    private var lastBatch: Double?
    private var relaunchedAt: Double?

    public init(clock: Clock) { self.clock = clock }

    public func batchReceived() {
        lastBatch = clock.uptime
        relaunchedAt = nil
    }

    public func handle(_ message: LinkMessage) {
        switch message.kind {
        case .workoutEnded:
            onEvent?("watch_workout_ended", message.detail ?? "")
            onAlert?("watch_stopped")
            relaunch()
        case .highRateFailed:
            onEvent?("watch_high_rate_failed", message.detail ?? "")
            onAlert?("high_rate_failed")
        default:
            break
        }
    }

    /// Call about once a second while recording.
    public func tick(watchReachable: Bool) {
        let now = clock.uptime
        guard watchReachable, let last = lastBatch, now - last > silenceTimeout else { return }
        guard relaunchedAt.map({ now - $0 > 30 }) ?? true else { return }
        onEvent?("watch_silent", String(format: "%.0f s without data", now - last))
        onAlert?("watch_stopped")
        relaunch()
    }

    private func relaunch() {
        relaunchedAt = clock.uptime
        onRelaunch?()
    }
}
