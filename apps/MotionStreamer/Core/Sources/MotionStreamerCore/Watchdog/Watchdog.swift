import Foundation

/// What the watchdog sees each second (design §8).
public struct WatchdogInput {
    public struct Stream {
        public var required: Bool
        public var lastSampleAge: Double?
        /// Samples per second over the last 5 s.
        public var rate5s: Double
        /// The stream's normal rate (its first minute, or the Go/No-Go measurement).
        public var baselineHz: Double?
        /// Samples of the last 5 s (frozen-sensor check).
        public var recent: [MotionSample]

        public init(
            required: Bool, lastSampleAge: Double?, rate5s: Double, baselineHz: Double?, recent: [MotionSample] = []
        ) {
            self.required = required
            self.lastSampleAge = lastSampleAge
            self.rate5s = rate5s
            self.baselineHz = baselineHz
            self.recent = recent
        }
    }

    public var streams: [String: Stream] = [:]
    public var airpodsConnected = true
    /// Connected but the audio route moved to another device (Mac/iPad automatic switching).
    public var airpodsRouteAway = false
    public var watchReachable = true
    public var watchBatchAge: Double?
    public var watchStopped = false
    public var highRateFailed = false
    public var batteryPhone: Double?
    public var batteryWatch: Double?
    public var lowPower = false
    public var thermal = 0
    public var freeDiskBytes: Int64 = .max
    public var writeErrorRecently = false
    public var phoneDropped = false
    /// The phone's magnetometer accuracy is low (court fences and posts disturb it; test X2).
    public var compassAccuracyLow = false

    public init() {}
}

/// The per-second checks of design §8. Returns the active problems (for `AlertCenter`) and the
/// automatic fixes to try.
public final class Watchdog {
    public enum Action: Equatable {
        /// Pause preview plots and the UDP stream to give the sensors CPU.
        case shedLoad
        /// Stop and start one device's motion updates (frozen sensor).
        case restartUpdates(String)
    }

    public static let frozenSeconds = 5.0
    public static let frozenRestartGrace = 3.0
    public static let lowRateFraction = 0.8
    public static let minFreeBytes: Int64 = 500_000_000

    private let clock: Clock
    private var restartedAt: [String: Double] = [:]

    public init(clock: Clock) { self.clock = clock }

    public func evaluate(_ input: WatchdogInput) -> (
        problems: [String: (level: AlertCenter.Level, detail: String?)], actions: [Watchdog.Action]
    ) {
        var problems: [String: (level: AlertCenter.Level, detail: String?)] = [:]
        var actions: [Action] = []
        let now = clock.uptime

        // Connection and device
        if let air = input.streams["airpods"], air.required {
            if input.airpodsRouteAway {
                problems["airpods_switched"] = (.red, "audio route moved to another device")
            } else if !input.airpodsConnected || (air.lastSampleAge ?? .infinity) > 1 {
                problems["airpods_disconnected"] = (.red, input.airpodsConnected ? "no samples" : "disconnected")
            }
        }
        if input.watchStopped {
            problems["watch_stopped"] = (.red, nil)
        } else if input.streams["watch"]?.required == true, !input.watchReachable || (input.watchBatchAge ?? 0) > 3 {
            problems["watch_preview_paused"] = (.yellow, "the Watch keeps recording on its own disk")
        }
        if input.highRateFailed { problems["high_rate_failed"] = (.red, nil) }

        // Sampling quality
        let cause = input.thermal >= 2 ? "heat" : input.lowPower ? "Low Power Mode" : "CPU load"
        for (device, s) in input.streams.sorted(by: { $0.key < $1.key }) where s.required {
            // The Watch's live preview arrives in bursts over the link, so its rate here says nothing
            // about phone CPU load; link problems are `watch_preview_paused`, its recording is on its disk.
            if device != "watch", let base = s.baselineHz, base > 0, (s.lastSampleAge ?? .infinity) <= 1,
                s.rate5s / base < Self.lowRateFraction
            {
                problems["rate_dropping"] = (.yellow, "\(device) at \(Int(s.rate5s / base * 100)) % (\(cause))")
                actions.append(.shedLoad)
            }
            if isFrozen(s.recent), input.streams.contains(where: { $0.key != device && isMoving($0.value.recent) }) {
                if let at = restartedAt[device] {
                    if now - at >= Self.frozenRestartGrace { problems["frozen_sensor"] = (.red, device) }
                } else {
                    restartedAt[device] = now
                    actions.append(.restartUpdates(device))
                }
            } else {
                restartedAt[device] = nil
            }
        }
        if input.lowPower { problems["low_power"] = (.red, nil) }
        if input.compassAccuracyLow { problems["compass_disturbed"] = (.yellow, nil) }
        if input.thermal >= 2 {
            problems["phone_hot"] = (.yellow, nil)
            actions.append(.shedLoad)
        }

        // Body, power and storage
        if input.phoneDropped { problems["phone_dropped"] = (.red, nil) }
        let battery = [input.batteryPhone, input.batteryWatch].compactMap { $0 }.min()
        if let b = battery, b <= 0.10 {
            problems["battery_critical"] = (.red, String(format: "%.0f %%", b * 100))
        } else if let b = battery, b <= 0.20 {
            problems["battery_low"] = (.yellow, String(format: "%.0f %%", b * 100))
        }
        if input.writeErrorRecently || input.freeDiskBytes < Self.minFreeBytes {
            problems["write_error"] = (.red, input.writeErrorRecently ? "write failed" : "disk almost full")
        }
        var unique: [Action] = []
        for a in actions where !unique.contains(a) { unique.append(a) }
        return (problems, unique)
    }

    /// No change at all in 5 s of samples (a stuck sensor delivers the same values).
    func isFrozen(_ s: [MotionSample]) -> Bool {
        guard s.count >= 10, let span = s.last.map({ $0[0] - s[0][0] }), span >= Self.frozenSeconds - 0.5 else {
            return false
        }
        return (1..<14).allSatisfy { k in
            let values = s.map { $0[k] }
            return (values.max()! - values.min()!) < 1e-9
        }
    }

    func isMoving(_ s: [MotionSample]) -> Bool {
        guard !s.isEmpty else { return false }
        let ms = s.map { $0[11] * $0[11] + $0[12] * $0[12] + $0[13] * $0[13] }.reduce(0, +) / Double(s.count)
        return ms.squareRoot() > 0.2
    }
}

/// "Phone fell out of the pocket" (design §8): free fall, then an impact, then the phone lies flat
/// and still for 5 s while the Watch keeps moving. Jumps make free fall and impacts too, but the
/// phone stays upright in the pocket, so they don't count (test A8).
public final class PhoneDropDetector {
    public static let freeFallG = 0.3
    public static let freeFallSeconds = 0.12
    public static let impactG = 2.5
    public static let stillSeconds = 5.0

    public private(set) var dropped = false
    private var freeFallStart: Double?
    private var impactAt: Double?
    private var flatSince: Double?

    public init() {}

    /// Feed every phone sample; `watchMoving` = the Watch is moving right now.
    public func add(_ s: MotionSample, watchMoving: Bool) {
        let t = s[0]
        let total = ReviewLoader.norm(s[5] + s[8], s[6] + s[9], s[7] + s[10])
        let user = ReviewLoader.norm(s[5], s[6], s[7])
        let rot = ReviewLoader.norm(s[11], s[12], s[13])
        if total < Self.freeFallG {
            freeFallStart = freeFallStart ?? t
        } else {
            if let start = freeFallStart, t - start >= Self.freeFallSeconds, user > Self.impactG { impactAt = t }
            freeFallStart = nil
        }
        guard let impact = impactAt else { return }
        if t - impact > Self.stillSeconds + 3 {
            impactAt = nil
            flatSince = nil
            return
        }
        let flat = abs(s[10]) > 0.9 && rot < 0.1
        if flat {
            flatSince = flatSince ?? t
            if t - flatSince! >= Self.stillSeconds, watchMoving { dropped = true }
        } else {
            flatSince = nil
        }
    }

    /// The phone is back in a pocket (picked up and upright again).
    public func reset() {
        dropped = false
        impactAt = nil
        flatSince = nil
    }
}
