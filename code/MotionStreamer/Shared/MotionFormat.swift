import CoreMotion
import Foundation

/// Packet format shared by the Watch, the iPhone and the Mac receiver.
///
/// One motion sample is 14 numbers:
///   [t, qx, qy, qz, qw, ax, ay, az, gx, gy, gz, rx, ry, rz]
/// - t: `CMDeviceMotion.timestamp`, seconds since that device booted (monotonic, per device)
/// - q: attitude quaternion in the reference frame named by `ref_frame`
/// - a: user acceleration (gravity removed), in g
/// - g: gravity, in g
/// - r: rotation rate, rad/s
enum MotionFormat {
    static let version = 1
    /// Requested rate. iOS may deliver less (an iPhone 16 delivers 33.4 Hz); the
    /// delivered rate is measured from sample timestamps.
    static let sampleRateHz = 60.0
    /// Samples per Watch -> iPhone message.
    static let batchSize = 10
    /// Samples per UDP packet. Keeps datagrams near 1 KB; larger ones fail with "Message too long".
    static let samplesPerPacket = 5
}

/// Compact JSON array for samples: 6 decimals per value (~150 bytes per sample).
func samplesJSON(_ samples: [MotionSample]) -> String {
    "["
        + samples.map { sample in
            "[" + sample.map { String(format: "%.6f", $0) }.joined(separator: ",") + "]"
        }.joined(separator: ",") + "]"
}

typealias MotionSample = [Double]

extension CMDeviceMotion {
    var sample: MotionSample {
        let q = attitude.quaternion
        return [
            timestamp,
            q.x, q.y, q.z, q.w,
            userAcceleration.x, userAcceleration.y, userAcceleration.z,
            gravity.x, gravity.y, gravity.z,
            rotationRate.x, rotationRate.y, rotationRate.z,
        ]
    }
}

/// Seconds since boot, on the same clock as `CMDeviceMotion.timestamp`.
func uptime() -> Double { ProcessInfo.processInfo.systemUptime }

/// Add to an uptime timestamp to get Unix time according to this device's wall clock.
func bootToUnixOffset() -> Double { Date().timeIntervalSince1970 - uptime() }

/// Magnetic-north reference when the device has a usable magnetometer, so phone and
/// Watch share a heading; otherwise an arbitrary (drift-corrected) heading.
func preferredReferenceFrame() -> (frame: CMAttitudeReferenceFrame, name: String) {
    if CMMotionManager.availableAttitudeReferenceFrames().contains(.xMagneticNorthZVertical) {
        return (.xMagneticNorthZVertical, "xMagneticNorthZVertical")
    }
    return (.xArbitraryCorrectedZVertical, "xArbitraryCorrectedZVertical")
}

/// Hardware identifier such as "iPhone17,3" or "Watch7,1".
func hardwareModel() -> String {
    var info = utsname()
    uname(&info)
    return withUnsafeBytes(of: &info.machine) { buffer in
        String(decoding: buffer.prefix(while: { $0 != 0 }), as: UTF8.self)
    }
}

/// Watch -> iPhone message body (JSON, default key names).
struct WatchBatch: Codable {
    var seq: Int
    /// Index of the first sample in this batch; indices are contiguous across batches.
    var firstIndex: Int
    var bootToUnix: Double
    var refFrame: String
    var sentWatch: Double
    var samples: [MotionSample]
}

/// Watch -> iPhone message sent once when streaming starts.
struct WatchHello: Codable {
    var model: String
    var os: String
    var refFrame: String
    var rateHz: Double
}
