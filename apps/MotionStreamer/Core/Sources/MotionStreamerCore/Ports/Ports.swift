import Foundation

// Everything the core needs from the outside world. Each protocol has a real version in the
// app targets and a fake in Fakes/ for tests (docs/plan/test-plan.md §0).

/// Time. `uptime` is the device's monotonic clock (same as `CMDeviceMotion.timestamp`).
public protocol Clock: AnyObject {
    var uptime: Double { get }
    var unixTime: Double { get }
}

extension Clock {
    /// Add to an uptime timestamp to get Unix time according to this device's wall clock.
    public var bootToUnix: Double { unixTime - uptime }
}

/// The real clock.
public final class SystemClock: Clock {
    public init() {}
    public var uptime: Double { ProcessInfo.processInfo.systemUptime }
    public var unixTime: Double { Date().timeIntervalSince1970 }
}

/// A stream of motion samples from one device.
public protocol MotionSource: AnyObject {
    /// Device name used in packets: "phone", "watch" or "airpods".
    var device: String { get }
    var isAvailable: Bool { get }
    /// Starts delivering samples. `handler` may be called on any queue.
    func start(_ handler: @escaping (MotionSample) -> Void)
    func stop()
}

/// Spoken prompts. Implementations call `completion` when the phrase has finished speaking.
public protocol Voice: AnyObject {
    func speak(_ text: String, completion: (() -> Void)?)
    func stopSpeaking()
}

/// Device conditions the watchdog reads (design §8).
public protocol DeviceStatus: AnyObject {
    /// 0...1, or nil when unknown.
    var batteryLevel: Double? { get }
    var isLowPowerMode: Bool { get }
    /// 0 nominal, 1 fair, 2 serious, 3 critical (as `ProcessInfo.ThermalState`).
    var thermalState: Int { get }
    var freeDiskBytes: Int64 { get }
    /// Current audio output, e.g. "airpods", "watch", "speaker", or "none".
    var audioOutput: String { get }
}

/// Short vibrations, used as a backup to speech.
public protocol Haptics: AnyObject {
    func play(_ pattern: HapticPattern)
}

public enum HapticPattern: String {
    case warn, stop, redo, confirm
}
