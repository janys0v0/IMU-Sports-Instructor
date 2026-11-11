import CryptoKit
import Foundation

/// The session's append-only log (design §2): one JSON object per line, each written and synced
/// as it happens. It is the source of truth for the session's state; `manifest.json` is rebuilt
/// from it.
public final class Journal {
    public let path: String
    private let store: FileStore
    private let clock: Clock

    public init(store: FileStore, clock: Clock, path: String) {
        self.store = store
        self.clock = clock
        self.path = path
    }

    /// Creates the journal file if it doesn't exist yet.
    public func open() throws {
        if !store.exists(path) { try store.create(path) }
    }

    /// Appends one entry (`j` = entry type) with the current times, and syncs it.
    @discardableResult
    public func write(_ type: String, _ fields: [String: Any] = [:]) throws -> [String: Any] {
        var entry = fields
        entry["j"] = type
        entry["unix"] = entry["unix"] ?? clock.unixTime
        entry["t"] = entry["t"] ?? clock.uptime
        guard let data = PacketEncoder.packet(entry) else { throw FileStoreError.ioError("bad journal entry") }
        try store.append(data + Data([0x0A]), to: path)
        try store.sync(path)
        return entry
    }

    /// Reads a journal. A torn last line (crash mid-write) is skipped and reported (test J5).
    public static func read(store: FileStore, path: String) throws -> (entries: [[String: Any]], warnings: [String]) {
        let data = try store.read(path)
        var entries: [[String: Any]] = []
        var warnings: [String] = []
        let lines = data.split(separator: 0x0A, omittingEmptySubsequences: false)
        for (n, line) in lines.enumerated() where !line.isEmpty {
            if let obj = try? JSONSerialization.jsonObject(with: Data(line)) as? [String: Any] {
                entries.append(obj)
            } else {
                warnings.append("journal line \(n + 1) is unreadable (torn write); ignored")
            }
        }
        return (entries, warnings)
    }
}

/// Builds the readable `manifest.json` from journal entries (test J2: rebuilt == live).
public enum Manifest {
    public static func build(from entries: [[String: Any]]) -> [String: Any] {
        var manifest: [String: Any] = [:]
        var chunks: [[String: Any]] = []
        var events: [[String: Any]] = []
        var segments = 1
        var lastHealth: [String: Any]?
        for e in entries {
            switch e["j"] as? String {
            case "session_open":
                for (k, v) in e where !["j", "t"].contains(k) { manifest[k] = v }
                manifest["start_unix"] = e["unix"]
            case "chunk_closed", "chunk_received":
                chunks.append(e)
            case "segment_open":
                segments = max(segments, (e["segment"] as? Int ?? segments))
            case "health":
                lastHealth = e
            case "correction":
                if let field = e["field"] as? String { manifest[field] = e["new"] }
            case "session_close":
                manifest["stop_unix"] = e["unix"]
                manifest["clean"] = e["clean"]
            default:
                events.append(e)
            }
        }
        manifest["segments"] = segments
        manifest["chunks"] = chunks.count
        manifest["chunk_files"] = chunks.compactMap { $0["file"] as? String }
        manifest["events"] = events.count
        if let h = lastHealth { manifest["last_health"] = h }
        if let start = manifest["start_unix"] as? Double, let stop = manifest["stop_unix"] as? Double {
            manifest["duration_s"] = stop - start
        }
        return manifest
    }
}

/// SHA-256 of some bytes, as lowercase hex.
public func sha256Hex(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}
