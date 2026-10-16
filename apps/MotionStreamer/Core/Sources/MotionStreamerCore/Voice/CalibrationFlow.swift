import Foundation

/// The spoken calibration (design §7): standing pose, then arms-out pose, every step spoken, holds
/// timed from when "now" finishes speaking, checked on the phone right after each hold, retried
/// at most twice. Driven by speech completions and `tick()` (call about 10 times a second).
public final class CalibrationFlow {
    public enum Failure: String {
        case moved, phoneNotUpright = "phone_not_upright", armsNotLevel = "arms_not_level"
        case airpodsMissing = "airpods_missing", watchSilent = "watch_silent", interrupted
    }

    public struct Result {
        public var passed: Bool
        public var failure: Failure?
        /// Uptime spans of the two holds.
        public var standingWindow: ClosedRange<Double>?
        public var armsWindow: ClosedRange<Double>?
        /// device -> mean gravity over its hold (device frame).
        public var gravity: [String: [Double]]
        /// device -> mean attitude quaternion (x, y, z, w) over its hold.
        public var attitude: [String: [Double]]
        /// device -> degrees the gravity direction moved since the previous calibration.
        public var driftDegrees: [String: Double]
    }

    /// Motion the flow reads: samples of a device that arrived between two uptimes.
    public typealias SampleSource = (_ device: String, _ from: Double, _ to: Double) -> [MotionSample]

    public static let holdSeconds = 3.0
    public static let holdDelay = 0.3
    public static let stillRMS = 0.15
    public static let uprightMin = 0.85
    /// Arms count as level when the forearm (Watch x axis) is within 20° of horizontal.
    public static let armsLevelMax = sin(20 * Double.pi / 180)
    public static let nudgeAfter = 6.0
    public static let armsTimeout = 15.0
    public static let maxRetries = 2

    public var landmark = "the same direction as last time"
    public var requireWatch = true
    public var requireAirPods = true
    public var airpodsConnected: () -> Bool = { true }
    /// Logs `calibrate`, `calibrate_arms`, `cal_hold_end` and `calibrate_result`.
    public var onEvent: ((String, [String: Any]) -> Void)?
    public var onFinish: ((Result) -> Void)?
    /// Gravity per device at the last good calibration (for drift).
    public var previousGravity: [String: [Double]] = [:]
    public private(set) var isRunning = false

    private enum Phase {
        case idle, speaking
        case hold(arms: Bool, start: Double, warned: Bool)
        case waitArms(since: Double, nudged: Bool)
    }

    private let speaker: Speaker
    private let clock: Clock
    private let samples: SampleSource
    private let script: VoiceScript
    private var phase = Phase.idle
    private var retries = 0
    private var result = Result(passed: false, gravity: [:], attitude: [:], driftDegrees: [:])

    public init(speaker: Speaker, clock: Clock, samples: @escaping SampleSource, script: VoiceScript = .shared) {
        self.speaker = speaker
        self.clock = clock
        self.samples = samples
        self.script = script
    }

    public func start() {
        guard !isRunning else { return }
        isRunning = true
        retries = 0
        speaker.holdWarnings = true
        begin()
    }

    public func cancel() {
        guard isRunning else { return }
        finish(passed: false, failure: .interrupted, speak: false)
    }

    // MARK: - Steps

    private func begin() {
        result = Result(passed: false, gravity: [:], attitude: [:], driftDegrees: [:])
        say(["C1", "C2", "C3", "C4"]) { [weak self] in self?.startHold(arms: false, warned: false) }
    }

    private func startHold(arms: Bool, warned: Bool) {
        phase = .hold(arms: arms, start: clock.uptime + Self.holdDelay, warned: warned)
    }

    public func tick() {
        guard isRunning else { return }
        let now = clock.uptime
        switch phase {
        case .hold(let arms, let start, let warned):
            guard now >= start else { return }
            if moving(from: start, to: now) {
                if warned { return fail(.moved) }
                phase = .speaking
                say(["C5"]) { [weak self] in self?.startHold(arms: arms, warned: true) }
                return
            }
            if now >= start + Self.holdSeconds { endHold(arms: arms, window: start...(start + Self.holdSeconds)) }
        case .waitArms(let since, let nudged):
            if armsLevel(from: now - 0.5, to: now) {
                phase = .speaking
                say(["C9"]) { [weak self] in self?.startHold(arms: true, warned: false) }
            } else if now - since >= Self.armsTimeout {
                fail(.armsNotLevel)
            } else if !nudged, now - since >= Self.nudgeAfter {
                phase = .speaking
                say(["C8"]) { [weak self] in
                    guard let self else { return }
                    self.phase = .waitArms(since: since, nudged: true)
                }
            }
        case .idle, .speaking:
            return
        }
    }

    private func endHold(arms: Bool, window: ClosedRange<Double>) {
        phase = .speaking
        onEvent?("cal_hold_end", ["pose": arms ? "arms_out" : "standing"])
        if arms {
            guard armsLevel(from: window.lowerBound, to: window.upperBound) else { return fail(.armsNotLevel) }
            result.armsWindow = window
            measure("watch", window)
            onEvent?(
                "calibrate_arms",
                ["t_phone": window.lowerBound - Self.holdDelay, "hold_s": Self.holdSeconds + Self.holdDelay])
            say(["C10", "C11"]) { [weak self] in self?.finish(passed: true, failure: nil, speak: false) }
            return
        }
        if let failure = standingFailure(window) { return fail(failure) }
        result.standingWindow = window
        for device in ["phone", "airpods"] { measure(device, window) }
        // Same fields as today's calibrate event, so pipeline/preprocessing/calibration.py reads it.
        onEvent?(
            "calibrate",
            [
                "t_phone": window.lowerBound - Self.holdDelay, "hold_s": Self.holdSeconds + Self.holdDelay,
                "pose": "standing",
            ])
        if requireWatch {
            say(["C6", "C7"]) { [weak self] in
                guard let self else { return }
                self.phase = .waitArms(since: self.clock.uptime, nudged: false)
            }
        } else {
            say(["C6", "C11"]) { [weak self] in self?.finish(passed: true, failure: nil, speak: false) }
        }
    }

    private func fail(_ failure: Failure) {
        phase = .speaking
        let reason = VoiceScript.fill(script.calibration("C12a"), ["reason": script.reason(failure.rawValue)])
        onEvent?("calibrate_result", ["result": "fail", "reason": failure.rawValue, "attempt": retries + 1])
        if retries < Self.maxRetries {
            retries += 1
            speaker.say(reason, id: "C12a") { [weak self] interrupted in
                guard !interrupted else { self?.finish(passed: false, failure: .interrupted, speak: false); return }
                self?.say(["C12b"]) { self?.begin() }
            }
        } else {
            speaker.say(reason, id: "C12a")
            say(["C12_final"]) { [weak self] in self?.finish(passed: false, failure: failure, speak: false) }
        }
    }

    private func finish(passed: Bool, failure: Failure?, speak: Bool) {
        isRunning = false
        phase = .idle
        speaker.holdWarnings = false
        result.passed = passed
        result.failure = failure
        if passed {
            for (device, g) in result.gravity {
                if let old = previousGravity[device] { result.driftDegrees[device] = ReviewLoader.angleDegrees(g, old) }
            }
            previousGravity.merge(result.gravity) { $1 }
            onEvent?(
                "calibrate_result",
                [
                    "result": "pass", "gravity": result.gravity, "attitude": result.attitude,
                    "drift_deg": result.driftDegrees,
                ])
        } else if failure == .interrupted {
            onEvent?("calibrate_result", ["result": "fail", "reason": "interrupted"])
        }
        onFinish?(result)
    }

    /// Speaks the given calibration phrases in order, then runs `then`. An interruption (a 🔴 alert)
    /// ends the calibration.
    private func say(_ ids: [String], then: @escaping () -> Void) {
        phase = .speaking
        guard let id = ids.first else { return then() }
        let text = VoiceScript.fill(script.calibration(id), ["landmark": landmark])
        speaker.say(text, id: id) { [weak self] interrupted in
            guard let self, self.isRunning else { return }
            if interrupted { return self.finish(passed: false, failure: .interrupted, speak: false) }
            self.say(Array(ids.dropFirst()), then: then)
        }
    }

    // MARK: - Checks

    private var devices: [String] {
        ["phone"] + (requireWatch ? ["watch"] : []) + (requireAirPods ? ["airpods"] : [])
    }

    private func moving(from: Double, to: Double) -> Bool {
        devices.contains { device in
            let s = samples(device, from, to)
            guard !s.isEmpty else { return false }
            let ms = s.map { $0[11] * $0[11] + $0[12] * $0[12] + $0[13] * $0[13] }.reduce(0, +) / Double(s.count)
            return ms.squareRoot() > Self.stillRMS
        }
    }

    private func standingFailure(_ window: ClosedRange<Double>) -> Failure? {
        let phone = samples("phone", window.lowerBound, window.upperBound)
        guard !phone.isEmpty else { return .phoneNotUpright }
        let gy = phone.map { $0[9] }.reduce(0, +) / Double(phone.count)
        if abs(gy) < Self.uprightMin { return .phoneNotUpright }
        if requireAirPods, !airpodsConnected() || samples("airpods", window.lowerBound, window.upperBound).isEmpty {
            return .airpodsMissing
        }
        if requireWatch, samples("watch", window.lowerBound, window.upperBound).isEmpty { return .watchSilent }
        return nil
    }

    private func armsLevel(from: Double, to: Double) -> Bool {
        let watch = samples("watch", from, to)
        guard !watch.isEmpty else { return false }
        let gx = watch.map { $0[8] }.reduce(0, +) / Double(watch.count)
        return abs(gx) <= Self.armsLevelMax
    }

    private func measure(_ device: String, _ window: ClosedRange<Double>) {
        guard let summary = Self.holdSummary(samples(device, window.lowerBound, window.upperBound)) else { return }
        result.gravity[device] = summary.gravity
        result.attitude[device] = summary.attitude
    }

    /// Rotation-rate RMS (rad/s), mean gravity (device frame) and mean attitude quaternion
    /// (x, y, z, w; normalised average, same hemisphere) of a hold. Matches calibration.py (test C7).
    public static func holdSummary(_ s: [MotionSample]) -> (rotRMS: Double, gravity: [Double], attitude: [Double])? {
        guard !s.isEmpty else { return nil }
        let n = Double(s.count)
        let rms = (s.map { $0[11] * $0[11] + $0[12] * $0[12] + $0[13] * $0[13] }.reduce(0, +) / n).squareRoot()
        let gravity = (8...10).map { k in s.map { $0[k] }.reduce(0, +) / n }
        let ref = s[0]
        var q = (1...4).map { k in
            s.map { x in
                let same = x[1] * ref[1] + x[2] * ref[2] + x[3] * ref[3] + x[4] * ref[4] >= 0
                return x[k] * (same ? 1 : -1)
            }.reduce(0, +) / n
        }
        let norm = q.map { $0 * $0 }.reduce(0, +).squareRoot()
        if norm > 0 { q = q.map { $0 / norm } }
        return (rms, gravity, q)
    }
}

/// Spoken reminder to recalibrate (design §7): after `interval` without a good calibration, or right
/// after an event that spoils it; repeats every 2 min until done or dismissed.
public final class CalibrationReminder {
    public var interval: Double
    public var repeatEvery: Double = 120
    public static let resetEvents: Set<String> = [
        "airpods_connected", "segment_open", "resume", "phone_moved", "watch_strap",
    ]

    private let clock: Clock
    private var lastGood: Double
    private var lastSpoken: Double?
    private var dueNow = false
    private var dismissedUntil: Double?

    public init(clock: Clock, interval: Double = 600) {
        self.clock = clock
        self.interval = interval
        lastGood = clock.uptime
    }

    public func calibrated() {
        lastGood = clock.uptime
        lastSpoken = nil
        dueNow = false
        dismissedUntil = nil
    }

    public func event(_ name: String) { if Self.resetEvents.contains(name) { dueNow = true } }

    public func dismiss() { dismissedUntil = clock.uptime + interval }

    /// True when the reminder should be spoken now.
    public func tick() -> Bool {
        let now = clock.uptime
        if let until = dismissedUntil, now < until { return false }
        guard dueNow || now - lastGood >= interval else { return false }
        if let spoken = lastSpoken, now - spoken < repeatEvery { return false }
        lastSpoken = now
        return true
    }
}

/// "Can you hear me? Tap the watch if you can." at Go/No-Go (test V8).
public final class AudibilityCheck {
    public enum State: Equatable { case waiting, heard, notHeard }
    public static let timeout = 10.0
    public private(set) var state = State.waiting
    private let clock: Clock
    private var askedAt: Double?

    public init(clock: Clock) { self.clock = clock }

    public func start(speaker: Speaker, script: VoiceScript = .shared) {
        state = .waiting
        speaker.say(script.audibility, id: "audibility") { [weak self] _ in self?.askedAt = self?.clock.uptime }
    }

    public func tapReceived() { if state == .waiting { state = .heard } }

    @discardableResult
    public func tick() -> State {
        if state == .waiting, let at = askedAt, clock.uptime - at > Self.timeout { state = .notHeard }
        return state
    }
}
