import Foundation

/// The phone's side of the Watch transfer (design §3): checks each arriving chunk's SHA-256,
/// stores it in the session folder, journals it and acks it. Damaged chunks are asked for again;
/// duplicates are acked again but stored and journalled only once (tests W2-W4, W6).
public final class TransferInbox {
    public enum Outcome: Equatable {
        case stored, duplicate, rejected(String)
    }

    /// session -> kind -> files received
    public private(set) var received: [String: [String: Set<String>]] = [:]
    /// session -> totals the Watch reported at Stop (60 Hz, high-rate).
    public private(set) var expected: [String: (chunks60Hz: Int, chunksHighRate: Int)] = [:]
    /// Called after every stored chunk (UI counts, watchdog).
    public var onChange: ((String) -> Void)?

    private let store: FileStore
    private let clock: Clock
    private let link: WatchLink

    public init(store: FileStore, clock: Clock, link: WatchLink) {
        self.store = store
        self.clock = clock
        self.link = link
    }

    public func count(session: String, kind: String) -> Int { received[session]?[kind]?.count ?? 0 }

    /// "Watch: 58 / 60 chunks" style text for one kind; nil total until the Watch reports it.
    public func progress(session: String, kind: String) -> (received: Int, total: Int?) {
        let total = expected[session].map { kind == "hf" ? $0.chunksHighRate : $0.chunks60Hz }
        return (count(session: session, kind: kind), total)
    }

    /// True once every chunk the Watch reported has arrived.
    public func isComplete(session: String, includeHighRate: Bool) -> Bool {
        guard let e = expected[session] else { return false }
        return count(session: session, kind: "60hz") >= e.chunks60Hz
            && (!includeHighRate || count(session: session, kind: "hf") >= e.chunksHighRate)
    }

    @discardableResult
    public func receive(_ data: Data, metadata: [String: String]) -> Outcome {
        guard let session = metadata[TransferKey.session], let file = metadata[TransferKey.file],
            let sha = metadata[TransferKey.sha256], let kind = metadata[TransferKey.kind],
            !file.contains(".."), !session.contains("/")
        else { return .rejected("missing metadata") }
        guard sha256Hex(data) == sha else {
            link.sendMessage(LinkMessage(kind: .resend, session: session, file: file).encoded)
            journal(session).flatMap { try? $0.write("chunk_rejected", ["file": file, "reason": "sha256 mismatch"]) }
            return .rejected("sha256 mismatch")
        }
        let dir = "\(SessionRecorder.sessionsDir)/\(session)"
        var path = "\(dir)/\(file)"
        var stored = file
        let outcome: Outcome
        if let existing = copy(of: sha, at: path) {
            outcome = .duplicate
            stored = existing
        } else {
            // A different chunk under a name already used (a Watch that restarted a session with an
            // older build): never replace the first copy, keep this one next to it.
            if store.exists(path) {
                stored = Self.clashName(file, sha: sha)
                path = "\(dir)/\(stored)"
                journal(session).flatMap {
                    try? $0.write("chunk_name_clash", ["file": "\(dir)/\(file)", "stored_as": path, "sha256": sha])
                }
            }
            do {
                try store.createDirectory((path as NSString).deletingLastPathComponent)
                try store.writeAtomically(data, to: path)
                try journal(session)?.write(
                    "chunk_received",
                    ["file": path, "sha256": sha, "bytes": data.count, "kind": kind, "verified": true])
                outcome = .stored
            } catch {
                return .rejected("cannot store: \(error)")
            }
        }
        received[session, default: [:]][kind, default: []].insert(stored)
        link.sendMessage(LinkMessage(kind: .ack, session: session, file: file, sha256: sha).encoded)
        onChange?(session)
        return outcome
    }

    /// "watch/000000.jsonl" -> "watch/000000.clash-<first 8 of sha>.jsonl"
    static func clashName(_ file: String, sha: String) -> String {
        let ext = (file as NSString).pathExtension
        let base = (file as NSString).deletingPathExtension
        return "\(base).clash-\(sha.prefix(8)).\(ext)"
    }

    /// The name this exact chunk is already stored under, if any (the original or a clash copy).
    private func copy(of sha: String, at path: String) -> String? {
        let dir = "\(SessionRecorder.sessionsDir)/"
        let clash =
            (path as NSString).deletingPathExtension + ".clash-\(sha.prefix(8))." + (path as NSString).pathExtension
        for candidate in [path, clash] where store.exists(candidate) {
            if let old = try? store.read(candidate), sha256Hex(old) == sha {
                let session = candidate.dropFirst(dir.count).split(separator: "/", maxSplits: 1)
                return session.count == 2 ? String(session[1]) : nil
            }
        }
        return nil
    }

    /// Handles the Watch's Stop summary.
    public func handle(_ message: LinkMessage) {
        guard message.kind == .summary else { return }
        let counts = (message.chunks60Hz ?? 0, message.chunksHighRate ?? 0)
        // The Watch resends the summary until this ack arrives (test W11).
        link.sendMessage(LinkMessage(kind: .ack, session: message.session, file: WatchRecorder.summaryAckFile).encoded)
        if let known = expected[message.session], known == counts { return }
        expected[message.session] = counts
        journal(message.session).flatMap {
            try? $0.write(
                "watch_summary",
                ["chunks_60hz": message.chunks60Hz ?? 0, "chunks_hf": message.chunksHighRate ?? 0])
        }
        onChange?(message.session)
    }

    /// The session's journal on the phone, created if the phone never saw this session start.
    private func journal(_ session: String) -> Journal? {
        let dir = "\(SessionRecorder.sessionsDir)/\(session)"
        let j = Journal(store: store, clock: clock, path: "\(dir)/journal.jsonl")
        if !store.exists(j.path) {
            try? store.createDirectory(dir)
            try? j.open()
        }
        return j
    }
}
