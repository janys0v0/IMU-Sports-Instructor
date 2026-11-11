import Foundation

/// Decides what keeps the iPhone app recording in a pocket (design §5) and when to fall back to
/// pocket mode (app in the foreground, screen off by the proximity sensor).
///
/// Core Motion doesn't keep an app awake on its own; a background mode must. Background location
/// at 3 km accuracy is the recommended keep-alive (device-research §1); workout mirroring is an
/// optional extra. If the app goes to the background with no keep-alive running, or AirPods motion
/// stops while it's in the background, recording must move to pocket mode.
public final class KeepAlivePolicy {
    public enum Method: String, CaseIterable {
        case location, mirroring, pocketMode = "pocket_mode"
    }

    public enum Advice: Equatable {
        case fine
        /// Go back to the foreground (pocket mode); `reason` is logged and spoken as a warning.
        case usePocketMode(reason: String)
    }

    /// Seconds without AirPods samples, while in the background and connected, that count as stopped.
    public static let airPodsSilence = 3.0

    public var method: Method
    public private(set) var inBackground = false
    public private(set) var keepAliveRunning = false
    private var backgroundSince: Double?
    private let clock: Clock

    public init(clock: Clock, method: Method = .location) {
        self.clock = clock
        self.method = method
    }

    /// The keep-alive (location updates or a mirrored workout) started or stopped.
    public func keepAlive(running: Bool) { keepAliveRunning = running }

    public func enteredBackground() -> Advice {
        inBackground = true
        backgroundSince = clock.uptime
        if method == .pocketMode { return .usePocketMode(reason: "pocket mode is the chosen method") }
        return keepAliveRunning ? .fine : .usePocketMode(reason: "no background keep-alive is running")
    }

    public func enteredForeground() {
        inBackground = false
        backgroundSince = nil
    }

    /// Call about once a second while recording.
    public func check(airPodsConnected: Bool, lastAirPodsSample: Double?) -> Advice {
        guard inBackground, airPodsConnected, let since = backgroundSince else { return .fine }
        let last = max(lastAirPodsSample ?? since, since)
        if clock.uptime - last > Self.airPodsSilence {
            return .usePocketMode(reason: "AirPods motion stopped in the background")
        }
        return .fine
    }
}
