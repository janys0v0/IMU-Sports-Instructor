import Foundation

/// Today's calibration timing: a countdown to pocket the phone, then a still hold.
/// The app calls `tick()` once per second; each call returns what to do. `cancel()` runs on Stop,
/// so a countdown interrupted by Stop never blocks the next calibration (test C1).
public struct CalibrationCountdown {
    public enum Step: Equatable {
        /// Show "Pocket the phone, stand straight: N".
        case countdown(remaining: Int)
        /// One buzz; log the `calibrate` event; the hold starts.
        case holdStarted
        /// Two buzzes; log `calibrate_done`.
        case finished
    }

    public static let countdownSeconds = 10
    public static let holdSeconds = 3

    public private(set) var isRunning = false
    private var remaining = 0

    public init() {}

    /// Starts a calibration. Returns nil if one is already running.
    public mutating func start() -> Step? {
        guard !isRunning else { return nil }
        isRunning = true
        remaining = Self.countdownSeconds
        return .countdown(remaining: remaining)
    }

    /// Advances one second.
    public mutating func tick() -> Step? {
        guard isRunning else { return nil }
        remaining -= 1
        if remaining > 0 { return .countdown(remaining: remaining) }
        if remaining == 0 { return .holdStarted }
        if remaining == -Self.holdSeconds {
            isRunning = false
            return .finished
        }
        return nil
    }

    /// Stops a running calibration (on Stop or when the session ends).
    public mutating func cancel() {
        isRunning = false
    }
}
