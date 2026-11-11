import Foundation

/// Writes one stream of a session (e.g. `sessions/<id>/phone/`) as numbered chunk files
/// (design §2): every record is written at once, synced every `syncInterval` s; every
/// `chunkSeconds` s the chunk is synced, closed, hashed, renamed from `.open` and journalled.
/// Not thread-safe: call it from one queue.
public final class ChunkWriter {
    public struct Current {
        public var path: String
        public var number: Int
        public var openedAt: Double
        public var lastSync: Double
        public var records = 0
        public var bytes = 0
        public var firstUnix: Double?
        public var lastUnix: Double?
        /// device -> [lowest, highest] sample index written in this chunk.
        public var indexRanges: [String: [Int]] = [:]
    }

    public let directory: String
    public let fileExtension: String
    public let chunkSeconds: Double
    public let syncInterval: Double
    /// Lines end with "\n" (JSON); binary chunks write records as they are.
    public let lineMode: Bool
    public var segment: Int
    public private(set) var current: Current?
    public private(set) var nextNumber: Int
    /// Records that could not be written even after opening a new chunk.
    public private(set) var lostRecords = 0
    /// Called with every write or sync error (the watchdog turns it into an alert).
    public var onWriteError: ((Error) -> Void)?
    /// Bytes written at the start of every chunk (the binary high-rate header), given the chunk number.
    public var chunkHeader: ((Int) -> Data)?
    /// Called with the journal entry of every closed chunk (the Watch queues it for transfer).
    public var onChunkClosed: (([String: Any]) -> Void)?

    private let store: FileStore
    private let clock: Clock
    private let journal: Journal

    public init(
        store: FileStore, clock: Clock, journal: Journal, directory: String, fileExtension: String = "jsonl",
        lineMode: Bool = true, chunkSeconds: Double = 60, syncInterval: Double = 1, segment: Int = 1,
        firstNumber: Int = 0
    ) {
        self.store = store
        self.clock = clock
        self.journal = journal
        self.directory = directory
        self.fileExtension = fileExtension
        self.lineMode = lineMode
        self.chunkSeconds = chunkSeconds
        self.syncInterval = syncInterval
        self.segment = segment
        self.nextNumber = firstNumber
    }

    public static func fileName(_ number: Int, ext: String) -> String {
        String(format: "%06d.%@", number, ext)
    }

    /// Writes one record. Returns false if it was lost (after an error and one retry).
    @discardableResult
    public func append(_ record: Data, device: String? = nil, firstIndex: Int? = nil, count: Int = 0) -> Bool {
        let bytes = lineMode ? record + Data([0x0A]) : record
        for attempt in 0..<2 {
            do {
                if current == nil { try openChunk() }
                try store.append(bytes, to: current!.path)
            } catch {
                report(error)
                if attempt == 0 { abandonCurrent() }
                continue
            }
            note(bytes.count, device: device, firstIndex: firstIndex, count: count)
            do {
                try tick()
            } catch {
                // The record is written; a failed sync closes this chunk so the next one starts clean.
                report(error)
                abandonCurrent()
            }
            return true
        }
        lostRecords += 1
        return false
    }

    /// Syncs and rotates on time. Call it regularly (every append does).
    public func tick() throws {
        guard var c = current else { return }
        let now = clock.uptime
        if now - c.openedAt >= chunkSeconds - 1e-6 {
            try closeCurrent()
        } else if now - c.lastSync >= syncInterval - 1e-6 {
            try store.sync(c.path)
            c.lastSync = now
            current = c
        }
    }

    /// Syncs, closes, hashes and renames the open chunk, and journals it.
    public func closeCurrent(recovered: Bool = false) throws {
        guard let c = current else { return }
        current = nil
        try store.close(c.path)
        let finalPath = String(c.path.dropLast(".open".count))
        try store.rename(c.path, to: finalPath)
        let data = try store.read(finalPath)
        var fields: [String: Any] = [
            "file": finalPath, "records": c.records, "bytes": data.count, "sha256": sha256Hex(data),
            "segment": segment, "index_ranges": c.indexRanges,
        ]
        if let u = c.firstUnix { fields["unix_first"] = u }
        if let u = c.lastUnix { fields["unix_last"] = u }
        if recovered { fields["recovered"] = true }
        let entry = try journal.write("chunk_closed", fields)
        onChunkClosed?(entry)
    }

    private func openChunk() throws {
        let path = "\(directory)/\(Self.fileName(nextNumber, ext: fileExtension)).open"
        try store.create(path)
        let now = clock.uptime
        current = Current(path: path, number: nextNumber, openedAt: now, lastSync: now)
        if let header = chunkHeader?(nextNumber) {
            try store.append(header, to: path)
            current!.bytes += header.count
        }
        nextNumber += 1
    }

    private func note(_ bytes: Int, device: String?, firstIndex: Int?, count: Int) {
        current!.records += 1
        current!.bytes += bytes
        let unix = clock.unixTime
        current!.firstUnix = current!.firstUnix ?? unix
        current!.lastUnix = unix
        if let device, let first = firstIndex, count > 0 {
            let last = first + count - 1
            if let r = current!.indexRanges[device] {
                current!.indexRanges[device] = [min(r[0], first), max(r[1], last)]
            } else {
                current!.indexRanges[device] = [first, last]
            }
        }
    }

    /// After a write error: keep what's on disk of the current chunk as a closed chunk, so the
    /// next attempt starts a fresh file.
    private func abandonCurrent() {
        guard current != nil else { return }
        do { try closeCurrent() } catch { current = nil }
    }

    private func report(_ error: Error) {
        onWriteError?(error)
        _ = try? journal.write("write_error", ["dir": directory, "error": String(describing: error)])
    }
}
