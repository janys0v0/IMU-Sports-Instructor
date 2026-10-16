import Foundation

/// The Watch's send queue (design §3): every closed 60 Hz chunk is sent at once; high-rate chunks
/// wait until the session ends. A chunk counts as delivered only when the phone acks its checksum;
/// unacked chunks are sent again. Nothing is ever deleted here (test W5).
public final class TransferOutbox {
    public struct Item: Equatable {
        public var file: String
        public var sha256: String
        public var kind: String
        public var lastSent: Double?
    }

    /// Seconds without an ack before a chunk is sent again.
    public var ackTimeout: Double = 30
    public let sessionID: String
    public private(set) var items: [String: Item] = [:]
    public private(set) var acked: Set<String> = []
    public private(set) var transfers = 0
    /// High-rate chunks are held back until `releaseHighRate()` (after Stop).
    public private(set) var highRateReleased = false

    private let store: FileStore
    private let clock: Clock
    private let link: WatchLink
    private let journal: Journal
    private let sessionDir: String

    public init(
        store: FileStore, clock: Clock, link: WatchLink, journal: Journal, sessionID: String, sessionDir: String
    ) {
        self.store = store
        self.clock = clock
        self.link = link
        self.journal = journal
        self.sessionID = sessionID
        self.sessionDir = sessionDir
    }

    public var unacked: [Item] { items.values.filter { !acked.contains($0.file) }.sorted { $0.file < $1.file } }
    public func count(kind: String) -> Int { items.values.filter { $0.kind == kind }.count }
    public func ackedCount(kind: String) -> Int {
        items.values.filter { $0.kind == kind && acked.contains($0.file) }.count
    }

    /// Adds a closed chunk (its journal entry); sends it now unless it's high-rate and held back.
    public func add(chunkEntry entry: [String: Any], kind: String) {
        guard let path = entry["file"] as? String, let sha = entry["sha256"] as? String else { return }
        let file = String(path.dropFirst(sessionDir.count + 1))
        items[file] = Item(file: file, sha256: sha, kind: kind, lastSent: nil)
        if kind != "hf" || highRateReleased { send(file) }
    }

    /// After Stop: send every high-rate chunk.
    public func releaseHighRate() {
        highRateReleased = true
        for item in unacked where item.kind == "hf" && item.lastSent == nil { send(item.file) }
    }

    /// Handles an ack or a resend request from the phone.
    public func handle(_ message: LinkMessage) {
        guard message.session == sessionID, let file = message.file else {
            if message.kind == .resendAll, message.session == sessionID { resendAll() }
            return
        }
        switch message.kind {
        case .ack where message.sha256 == items[file]?.sha256:
            if acked.insert(file).inserted { _ = try? journal.write("chunk_acked", ["file": file]) }
        case .resend:
            send(file)
        default:
            break
        }
    }

    /// Sends again every chunk whose ack is overdue. Call regularly and when the phone becomes reachable.
    public func tick() {
        let now = clock.uptime
        for item in unacked {
            guard let sent = item.lastSent, now - sent >= ackTimeout else { continue }
            send(item.file)
        }
    }

    /// The Watch's "Resend session" button (test W6): everything again, acked or not.
    public func resendAll() {
        for item in items.values.sorted(by: { $0.file < $1.file }) where item.kind != "hf" || highRateReleased {
            send(item.file)
        }
    }

    private func send(_ file: String) {
        guard let item = items[file], let data = try? store.read("\(sessionDir)/\(file)") else { return }
        link.transferFile(
            data,
            metadata: [
                TransferKey.session: sessionID, TransferKey.file: file, TransferKey.sha256: item.sha256,
                TransferKey.kind: item.kind,
            ])
        items[file]?.lastSent = clock.uptime
        transfers += 1
    }

    /// Deletes Watch sessions, but only those the Mac has verified (listed in `verified`).
    public static func clearVerified(store: FileStore, verified: Set<String>) throws -> [String] {
        let sessions = (try? store.list(SessionRecorder.sessionsDir)) ?? []
        var removed: [String] = []
        for id in sessions where verified.contains(id) {
            let dir = "\(SessionRecorder.sessionsDir)/\(id)"
            for sub in ["watch", "watch_hf"] {
                for name in (try? store.list("\(dir)/\(sub)")) ?? [] { try store.remove("\(dir)/\(sub)/\(name)") }
            }
            for name in (try? store.list(dir)) ?? [] { try? store.remove("\(dir)/\(name)") }
            removed.append(id)
        }
        return removed
    }
}
