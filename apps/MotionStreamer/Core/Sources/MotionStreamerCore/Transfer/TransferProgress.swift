import Foundation

/// What both screens show about the Watch → iPhone transfer, in one format so they match: the
/// Watch fills it from the chunks the iPhone has acked, the iPhone from the chunks it has received.
/// Only the data chunks count (not the Watch's journal copy).
public struct TransferProgress: Equatable {
    public var main: Int
    public var mainTotal: Int?
    public var highRate: Int
    public var highRateTotal: Int?

    public init(main: Int, mainTotal: Int?, highRate: Int, highRateTotal: Int?) {
        self.main = main
        self.mainTotal = mainTotal
        self.highRate = highRate
        self.highRateTotal = highRateTotal
    }

    /// On the Watch: acked of saved, per kind.
    public init(outbox: TransferOutbox) {
        self.init(
            main: outbox.ackedCount(kind: "60hz"), mainTotal: outbox.count(kind: "60hz"),
            highRate: outbox.ackedCount(kind: "hf"), highRateTotal: outbox.count(kind: "hf"))
    }

    /// On the iPhone: received of what the Watch reported at Stop (unknown until then).
    public init(inbox: TransferInbox, session: String) {
        let main = inbox.progress(session: session, kind: "60hz")
        let hf = inbox.progress(session: session, kind: "hf")
        self.init(main: main.received, mainTotal: main.total, highRate: hf.received, highRateTotal: hf.total)
    }

    public var isComplete: Bool {
        guard let mainTotal, let highRateTotal else { return false }
        return main >= mainTotal && highRate >= highRateTotal
    }

    public var text: String {
        func of(_ n: Int, _ total: Int?) -> String { "\(n)/\(total.map(String.init) ?? "…")" }
        return "On iPhone: 60 Hz \(of(main, mainTotal)) · high-rate \(of(highRate, highRateTotal))"
            + (isComplete ? " ✓" : "")
    }
}
