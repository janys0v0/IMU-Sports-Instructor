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
public enum MotionFormat {
    public static let version = 1
    /// Requested rate. iOS may deliver less (an iPhone 16 delivers 33.4 Hz); the
    /// delivered rate is measured from sample timestamps.
    public static let sampleRateHz = 60.0
    /// Samples per Watch -> iPhone message.
    public static let batchSize = 10
    /// Samples per UDP packet. Keeps datagrams near 1 KB; larger ones fail with "Message too long".
    public static let samplesPerPacket = 5
    /// Names of the 14 values in a sample, in order.
    public static let sampleFields = [
        "t", "qx", "qy", "qz", "qw", "ax", "ay", "az", "gx", "gy", "gz", "rx", "ry", "rz",
    ]
}

/// One motion sample: the 14 numbers described in `MotionFormat`.
public typealias MotionSample = [Double]

/// Compact JSON array for samples: 6 decimals per value (~150 bytes per sample).
public func samplesJSON(_ samples: [MotionSample]) -> String {
    "["
        + samples.map { sample in
            "[" + sample.map { String(format: "%.6f", $0) }.joined(separator: ",") + "]"
        }.joined(separator: ",") + "]"
}

/// Watch -> iPhone message body (JSON, default key names).
public struct WatchBatch: Codable, Equatable {
    public var seq: Int
    /// Index of the first sample in this batch; indices are contiguous across batches.
    public var firstIndex: Int
    public var bootToUnix: Double
    public var refFrame: String
    public var sentWatch: Double
    public var samples: [MotionSample]

    public init(
        seq: Int, firstIndex: Int, bootToUnix: Double, refFrame: String, sentWatch: Double,
        samples: [MotionSample]
    ) {
        self.seq = seq
        self.firstIndex = firstIndex
        self.bootToUnix = bootToUnix
        self.refFrame = refFrame
        self.sentWatch = sentWatch
        self.samples = samples
    }
}

/// Watch -> iPhone message sent once when streaming starts.
public struct WatchHello: Codable, Equatable {
    public var model: String
    public var os: String
    public var refFrame: String
    public var rateHz: Double

    public init(model: String, os: String, refFrame: String, rateHz: Double) {
        self.model = model
        self.os = os
        self.refFrame = refFrame
        self.rateHz = rateHz
    }
}
