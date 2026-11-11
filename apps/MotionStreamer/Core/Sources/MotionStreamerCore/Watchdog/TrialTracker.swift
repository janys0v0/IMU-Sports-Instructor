import Foundation

/// The Watch's Trial button (design §9): one tap starts a trial, the next ends it; each ended trial
/// is checked at once (design §8 ③) and kept or marked for redo. The court-exit check reads `trials`.
public final class TrialTracker {
    public enum Tap: Equatable {
        case started(Int)
        case ended(Int, keep: Bool, spoken: String?)
    }

    public private(set) var trials: [(number: Int, keep: Bool)] = []
    public private(set) var openTrial: (number: Int, start: Double)?
    /// Logs `marker` (start / end) and `trial_check` events.
    public var onEvent: ((String, [String: Any]) -> Void)?

    private let clock: Clock

    public init(clock: Clock) { self.clock = clock }

    /// `check` builds the trial check for (number, start, end) when a trial ends.
    @discardableResult
    public func tap(check: (Int, Double, Double) -> TrialCheck) -> Tap {
        let now = clock.uptime
        if let open = openTrial {
            openTrial = nil
            let result = check(open.number, open.start, now)
            trials.append((open.number, result.keep))
            onEvent?("marker", ["trial": open.number, "edge": "end"])
            onEvent?(
                "trial_check",
                ["trial": open.number, "keep": result.keep, "reasons": result.reasons, "start": open.start, "end": now])
            return .ended(open.number, keep: result.keep, spoken: result.spoken)
        }
        let number = (trials.map(\.number).max() ?? 0) + 1
        openTrial = (number, now)
        onEvent?("marker", ["trial": number, "edge": "start"])
        return .started(number)
    }
}
