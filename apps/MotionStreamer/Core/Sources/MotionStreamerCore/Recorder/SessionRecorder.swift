import Foundation

/// One recording session on the phone (design §2, §4): journal, manifest and the `phone/` chunk
/// stream. Also finds, recovers and resumes sessions that a crash left open.
/// Not thread-safe: call it from one queue.
public final class SessionRecorder {
    public enum StartError: Error, Equatable {
        case lowDisk(freeBytes: Int64)
    }

    public struct RecoveryReport: Equatable {
        public var sessionID: String
        /// Chunks that were still open and were trimmed and closed.
        public var recoveredChunks: [String]
        /// Bytes cut from the end of open chunks (a torn last line).
        public var trimmedBytes: Int
        /// Unix time of the last journal entry or chunk write.
        public var lastActivityUnix: Double?
        public var warnings: [String]
    }

    public static let minFreeBytes: Int64 = 2_000_000_000
    public static let healthInterval: Double = 60
    public static let sessionsDir = "sessions"

    public let sessionID: String
    public let directory: String
    public let journal: Journal
    public let phone: ChunkWriter
    public private(set) var segment: Int
    public private(set) var isClosed = false
    /// Device conditions for the 60 s `health` entries.
    public var healthProvider: (() -> [String: Any])?

    private let store: FileStore
    private let clock: Clock
    private var lastHealth: Double
    private var bootToUnix: Double

    private init(store: FileStore, clock: Clock, sessionID: String, segment: Int, firstChunk: Int) {
        self.store = store
        self.clock = clock
        self.sessionID = sessionID
        self.segment = segment
        directory = "\(Self.sessionsDir)/\(sessionID)"
        journal = Journal(store: store, clock: clock, path: "\(directory)/journal.jsonl")
        phone = ChunkWriter(
            store: store, clock: clock, journal: journal, directory: "\(directory)/phone", segment: segment,
            firstNumber: firstChunk)
        lastHealth = clock.uptime
        bootToUnix = clock.bootToUnix
    }

    // MARK: - Start, record, stop

    /// Starts a new session. Blocks with `lowDisk` when less than 2 GB is free (test R6).
    public static func start(store: FileStore, clock: Clock, sessionID: String, metadata: [String: Any])
        throws -> SessionRecorder
    {
        guard store.freeBytes >= minFreeBytes else { throw StartError.lowDisk(freeBytes: store.freeBytes) }
        let recorder = SessionRecorder(store: store, clock: clock, sessionID: sessionID, segment: 1, firstChunk: 0)
        for sub in ["phone", "watch", "watch_hf"] { try store.createDirectory("\(recorder.directory)/\(sub)") }
        try recorder.journal.open()
        var fields = metadata
        fields["session"] = sessionID
        fields["boot_to_unix"] = clock.bootToUnix
        fields["free_disk_bytes"] = store.freeBytes
        try recorder.journal.write("session_open", fields)
        try recorder.writeManifest()
        return recorder
    }

    /// Writes one packet to the phone stream. Returns false if it was lost.
    @discardableResult
    public func record(_ packet: Data, device: String? = nil, firstIndex: Int? = nil, count: Int = 0) -> Bool {
        phone.append(packet, device: device, firstIndex: firstIndex, count: count)
    }

    /// Copies an important event into the journal too (lifecycle, errors, calibrations).
    public func journalEvent(_ name: String, _ fields: [String: Any] = [:]) {
        var f = fields
        f["name"] = name
        _ = try? journal.write("event", f)
    }

    /// Call about once a second: syncs/rotates the chunk and writes `health` every 60 s.
    public func tick() {
        do { try phone.tick() } catch { phone.onWriteError?(error) }
        let now = clock.uptime
        if now - lastHealth >= Self.healthInterval - 1e-6 {
            lastHealth = now
            _ = try? journal.write("health", healthProvider?() ?? [:])
        }
    }

    /// A wall-clock change or reboot shows up as a new boot-to-Unix offset: start a new segment
    /// so the Mac never mixes two clocks (test J6). Returns true if a segment was started.
    @discardableResult
    public func checkClock(threshold: Double = 1.0) -> Bool {
        let now = clock.bootToUnix
        guard abs(now - bootToUnix) > threshold else { return false }
        let jump = now - bootToUnix
        bootToUnix = now
        try? phone.closeCurrent()
        segment += 1
        phone.segment = segment
        _ = try? journal.write("segment_open", ["segment": segment, "reason": "clock_jump", "jump_s": jump])
        return true
    }

    /// Closes the open chunk and the session.
    public func stop() throws {
        guard !isClosed else { return }
        try phone.closeCurrent()
        try journal.write("session_close", ["clean": true])
        isClosed = true
        try writeManifest()
    }

    public func writeManifest() throws {
        let (entries, _) = try Journal.read(store: store, path: journal.path)
        guard
            let data = try? JSONSerialization.data(
                withJSONObject: Manifest.build(from: entries), options: [.prettyPrinted, .sortedKeys])
        else { return }
        try store.writeAtomically(data, to: "\(directory)/manifest.json")
    }

    // MARK: - Crash recovery (design §4)

    /// Sessions whose journal has no `session_close`.
    public static func unclosedSessions(store: FileStore) -> [String] {
        guard let ids = try? store.list(sessionsDir) else { return [] }
        return ids.filter { id in
            let path = "\(sessionsDir)/\(id)/journal.jsonl"
            guard let (entries, _) = try? Journal.read(store: store, path: path) else { return false }
            return !entries.contains { $0["j"] as? String == "session_close" }
        }
    }

    /// Trims every open chunk of a session to its last whole record and closes it.
    public static func recover(store: FileStore, clock: Clock, sessionID: String) throws -> RecoveryReport {
        let dir = "\(sessionsDir)/\(sessionID)"
        let journal = Journal(store: store, clock: clock, path: "\(dir)/journal.jsonl")
        let (entries, warnings) = try Journal.read(store: store, path: journal.path)
        let segment = currentSegment(entries)
        var report = RecoveryReport(
            sessionID: sessionID, recoveredChunks: [], trimmedBytes: 0,
            lastActivityUnix: entries.compactMap { $0["unix"] as? Double }.max(), warnings: warnings)
        for sub in ["phone", "watch", "watch_hf"] {
            let streamDir = "\(dir)/\(sub)"
            guard let names = try? store.list(streamDir) else { continue }
            for name in names where name.hasSuffix(".open") {
                let path = "\(streamDir)/\(name)"
                let data = try store.read(path)
                let keep = wholeRecordLength(data, binary: name.contains(".bin"))
                if keep < data.count {
                    try store.truncate(path, to: keep)
                    report.trimmedBytes += data.count - keep
                }
                let finalPath = String(path.dropLast(".open".count))
                try store.rename(path, to: finalPath)
                let kept = try store.read(finalPath)
                try journal.write(
                    "chunk_closed",
                    [
                        "file": finalPath, "bytes": kept.count, "sha256": sha256Hex(kept), "segment": segment,
                        "records": name.contains(".bin") ? 0 : kept.split(separator: 0x0A).count, "recovered": true,
                    ])
                report.recoveredChunks.append(finalPath)
            }
        }
        return report
    }

    /// Continues a recovered session as a new segment: same ID, chunk numbers continue (test J4).
    public static func resume(
        store: FileStore, clock: Clock, sessionID: String, reason: String = "recovered_after_crash"
    )
        throws -> SessionRecorder
    {
        let dir = "\(sessionsDir)/\(sessionID)"
        let (entries, _) = try Journal.read(store: store, path: "\(dir)/journal.jsonl")
        let segment = currentSegment(entries) + 1
        let numbers = ((try? store.list("\(dir)/phone")) ?? []).compactMap { Int($0.prefix(6)) }
        let recorder = SessionRecorder(
            store: store, clock: clock, sessionID: sessionID, segment: segment,
            firstChunk: (numbers.max() ?? -1) + 1)
        try recorder.journal.write(
            "segment_open", ["segment": segment, "reason": reason, "boot_to_unix": clock.bootToUnix])
        try recorder.writeManifest()
        return recorder
    }

    /// Ends a recovered session without resuming it.
    public static func closeInterrupted(store: FileStore, clock: Clock, sessionID: String) throws {
        let dir = "\(sessionsDir)/\(sessionID)"
        let journal = Journal(store: store, clock: clock, path: "\(dir)/journal.jsonl")
        try journal.write("session_close", ["clean": false])
        let (entries, _) = try Journal.read(store: store, path: journal.path)
        if let data = try? JSONSerialization.data(
            withJSONObject: Manifest.build(from: entries), options: [.prettyPrinted, .sortedKeys])
        {
            try store.writeAtomically(data, to: "\(dir)/manifest.json")
        }
    }

    static func currentSegment(_ entries: [[String: Any]]) -> Int {
        entries.filter { $0["j"] as? String == "segment_open" }.compactMap { $0["segment"] as? Int }.max() ?? 1
    }

    /// Length of the prefix that holds only whole records: up to the last newline for JSON lines;
    /// for binary chunks, the header line plus whole fixed-size records (HighRateFormat).
    static func wholeRecordLength(_ data: Data, binary: Bool) -> Int {
        if binary { return HighRateFormat.wholeRecordLength(data) }
        guard let last = data.lastIndex(of: 0x0A) else { return 0 }
        return data.distance(from: data.startIndex, to: last) + 1
    }
}
