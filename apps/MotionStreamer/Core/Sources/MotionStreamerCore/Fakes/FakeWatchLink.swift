import Foundation

/// Two connected in-memory link ends. Messages and files are delivered on `deliver()`, so a test
/// controls timing; the link can drop, duplicate, reorder or corrupt them on command.
public final class FakeWatchLink: WatchLink {
    public weak var peer: FakeWatchLink?
    public var isReachable = true {
        didSet { if isReachable != oldValue { onReachabilityChange?(isReachable) } }
    }
    public var onMessage: ((Data) -> Void)?
    public var onFile: ((Data, [String: String]) -> Void)?
    public var onReachabilityChange: ((Bool) -> Void)?

    /// Fraction of files dropped (0...1), decided by `random`.
    public var dropFiles = 0.0
    public var duplicateFiles = 0.0
    public var reorderFiles = false
    /// Flip one byte in the next N files.
    public var corruptNextFiles = 0
    public var random: () -> Double = { Double.random(in: 0..<1) }

    private var outbox: [(Data, [String: String])] = []
    public private(set) var sentMessages: [Data] = []
    public private(set) var filesSent = 0

    public init() {}

    /// Connects two ends to each other.
    public static func pair() -> (FakeWatchLink, FakeWatchLink) {
        let a = FakeWatchLink()
        let b = FakeWatchLink()
        a.peer = b
        b.peer = a
        return (a, b)
    }

    public func sendMessage(_ data: Data) {
        sentMessages.append(data)
        guard isReachable, peer?.isReachable == true else { return }
        peer?.onMessage?(data)
    }

    public func transferFile(_ data: Data, metadata: [String: String]) {
        filesSent += 1
        outbox.append((data, metadata))
    }

    public var pendingFiles: Int { outbox.count }

    /// Delivers queued files (as WatchConnectivity would once both sides are reachable).
    public func deliver() {
        guard isReachable, let peer, peer.isReachable else { return }
        var batch = outbox
        outbox = []
        if reorderFiles { batch.reverse() }
        for (data, metadata) in batch {
            if random() < dropFiles {
                outbox.append((data, metadata))  // the system retries a failed transfer later
                continue
            }
            var payload = data
            if corruptNextFiles > 0, !payload.isEmpty {
                corruptNextFiles -= 1
                payload[payload.count / 2] ^= 0xFF
            }
            peer.onFile?(payload, metadata)
            if random() < duplicateFiles { peer.onFile?(payload, metadata) }
        }
    }
}
