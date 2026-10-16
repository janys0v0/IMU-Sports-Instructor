import Foundation

/// A recorded session (`mac_stream.jsonl` or an on-phone stream), parsed into per-device samples
/// and events. Used to replay real data through the app logic in tests and simulators.
public struct Recording {
    public struct Stream {
        public var device: String
        public var loc: String
        /// (sample index, sample), sorted by index, duplicates removed.
        public var samples: [(index: Int, sample: MotionSample)]
    }

    public var packets: [[String: Any]]
    public var streams: [String: Stream]
    public var events: [[String: Any]]

    /// One JSON object per line; lines that don't parse (a torn last line) are skipped.
    public static func packets(jsonl data: Data) -> [[String: Any]] {
        var packets: [[String: Any]] = []
        for line in data.split(separator: 0x0A) where !line.isEmpty {
            if let obj = try? JSONSerialization.jsonObject(with: Data(line)) as? [String: Any] {
                packets.append(obj)
            }
        }
        return packets
    }

    public init(jsonl data: Data) {
        let packets = Self.packets(jsonl: data)
        self.packets = packets
        var streams: [String: Stream] = [:]
        var seen: [String: Set<Int>] = [:]
        for p in packets where p["type"] as? String == "imu" {
            guard let device = p["device"] as? String, let first = p["first_index"] as? Int,
                let raw = p["s"] as? [[Double]]
            else { continue }
            var stream = streams[device] ?? Stream(device: device, loc: p["loc"] as? String ?? "", samples: [])
            for (k, sample) in raw.enumerated() where seen[device, default: []].insert(first + k).inserted {
                stream.samples.append((first + k, sample))
            }
            streams[device] = stream
        }
        for key in streams.keys { streams[key]!.samples.sort { $0.index < $1.index } }
        self.streams = streams
        self.events = packets.filter { $0["type"] as? String == "event" }
    }

    public init(contentsOf url: URL) throws {
        self.init(jsonl: try Data(contentsOf: url))
    }

    /// Number of distinct samples recorded for a device.
    public func sampleCount(_ device: String) -> Int { streams[device]?.samples.count ?? 0 }
}

/// Replays one device of a recording, in its own timestamps, as a stepped motion source.
public final class ReplayMotionSource: SteppedMotionSource {
    public let device: String
    public var isAvailable: Bool { !samples.isEmpty }
    private let samples: [MotionSample]
    private var next = 0
    private var handler: ((MotionSample) -> Void)?
    /// Added to every timestamp, to line the replay up with a test clock.
    public let timeShift: Double

    public init(recording: Recording, device: String, timeShift: Double = 0) {
        self.device = device
        self.timeShift = timeShift
        self.samples = (recording.streams[device]?.samples ?? []).map { item in
            var s = item.sample
            s[0] += timeShift
            return s
        }
    }

    public var firstTime: Double? { samples.first?[0] }
    public var lastTime: Double? { samples.last?[0] }
    public var remaining: Int { samples.count - next }

    public func start(_ handler: @escaping (MotionSample) -> Void) { self.handler = handler }
    public func stop() { handler = nil }

    public func emit(until uptime: Double) {
        while next < samples.count, samples[next][0] <= uptime {
            handler?(samples[next])
            next += 1
        }
    }
}
