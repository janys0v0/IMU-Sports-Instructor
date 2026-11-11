import Foundation

/// A clock that only moves when a test moves it.
public final class ManualClock: Clock {
    public var uptime: Double
    public var unixOffset: Double

    public init(uptime: Double = 1000, unixOffset: Double = 1_790_000_000) {
        self.uptime = uptime
        self.unixOffset = unixOffset
    }

    public var unixTime: Double { uptime + unixOffset }

    public func advance(_ seconds: Double) { uptime += seconds }
}

/// Records every phrase with its start and finish time instead of speaking.
public final class RecordingVoice: Voice {
    public struct Phrase: Equatable {
        public var text: String
        public var start: Double
        public var finish: Double?
    }

    public private(set) var phrases: [Phrase] = []
    private let clock: ManualClock?
    /// Seconds per word when `clock` is set; speaking advances the clock by this much.
    public var secondsPerWord: Double
    /// If false, `completion` waits for `finishCurrent()`.
    public var finishesImmediately: Bool
    private var pending: (() -> Void)?

    public init(clock: ManualClock? = nil, secondsPerWord: Double = 0.4, finishesImmediately: Bool = true) {
        self.clock = clock
        self.secondsPerWord = secondsPerWord
        self.finishesImmediately = finishesImmediately
    }

    public var texts: [String] { phrases.map(\.text) }

    public func speak(_ text: String, completion: (() -> Void)?) {
        phrases.append(Phrase(text: text, start: clock?.uptime ?? 0, finish: nil))
        pending = completion
        if finishesImmediately { finishCurrent() }
    }

    public func finishCurrent() {
        guard let i = phrases.indices.last, phrases[i].finish == nil else { return }
        let words = Double(phrases[i].text.split(separator: " ").count)
        clock?.advance(words * secondsPerWord)
        phrases[i].finish = clock?.uptime ?? 0
        let completion = pending
        pending = nil
        completion?()
    }

    public func stopSpeaking() {
        if let i = phrases.indices.last, phrases[i].finish == nil { phrases[i].finish = clock?.uptime ?? 0 }
        pending = nil
    }
}

/// Settable device conditions.
public final class FakeDeviceStatus: DeviceStatus {
    public var batteryLevel: Double? = 0.9
    public var isLowPowerMode = false
    public var thermalState = 0
    public var freeDiskBytes: Int64 = 50_000_000_000
    public var audioOutput = "airpods"
    public init() {}
}

/// Records haptic patterns.
public final class RecordingHaptics: Haptics {
    public private(set) var played: [HapticPattern] = []
    public init() {}
    public func play(_ pattern: HapticPattern) { played.append(pattern) }
}

/// Motion that a test pushes forward explicitly: `emit(until:)` delivers every sample with a
/// timestamp up to that uptime.
public protocol SteppedMotionSource: MotionSource {
    func emit(until uptime: Double)
}

/// Synthetic motion: a generator gives the sample for each time; gaps drop samples.
public final class SyntheticMotionSource: SteppedMotionSource {
    public let device: String
    public let rateHz: Double
    public var isAvailable = true
    /// Time ranges (device uptime) with no samples.
    public var gaps: [ClosedRange<Double>] = []
    public var generator: (Double) -> MotionSample
    private var handler: ((MotionSample) -> Void)?
    private let startTime: Double
    /// Index of the next sample; its time is computed from the index so long runs don't drift.
    private var n = 0

    public init(
        device: String, rateHz: Double, start: Double,
        generator: @escaping (Double) -> MotionSample = SyntheticMotionSource.still
    ) {
        self.device = device
        self.rateHz = rateHz
        self.startTime = start
        self.generator = generator
    }

    public func start(_ handler: @escaping (MotionSample) -> Void) { self.handler = handler }
    public func stop() { handler = nil }

    public func emit(until uptime: Double) {
        while startTime + Double(n) / rateHz <= uptime + 1e-9 {
            let t = startTime + Double(n) / rateHz
            n += 1
            if gaps.contains(where: { $0.contains(t) }) { continue }
            handler?(generator(t))
        }
    }

    /// Standing still, upright: gravity along -y, nothing else.
    public static func still(_ t: Double) -> MotionSample {
        [t, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, 0]
    }

    /// Rotating about z at `rads` rad/s with a matching sine acceleration.
    public static func moving(rads: Double = 2) -> (Double) -> MotionSample {
        { t in
            let a = rads * t / 2
            return [t, 0, 0, sin(a), cos(a), 0.3 * sin(t * 6), 0.2 * cos(t * 6), 0, 0, -1, 0, 0, 0, rads]
        }
    }
}
