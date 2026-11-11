import Foundation

/// What the review screen shows (design §6), built only from closed chunks on disk (test P1):
/// if it appears here, it is saved.
public struct ReviewData {
    public struct Point: Equatable {
        public var t: Double
        public var value: Double
        public init(t: Double, value: Double) {
            self.t = t
            self.value = value
        }
    }

    public struct Device {
        public var device: String
        /// Spans with data, on the Unix time axis; anything between them is a gap.
        public var covered: [ClosedRange<Double>]
        public var stats: StreamStats
        public var verdict: String
        /// Last 60 s, downsampled: rotation-rate size (rad/s), user-acceleration size (g),
        /// tilt since the last calibration (degrees).
        public var rotation: [Point]
        public var acceleration: [Point]
        public var angle: [Point]
    }

    public var sessionID: String
    public var start: Double?
    public var end: Double?
    public var devices: [String: Device]
    /// Unix times of calibrations (`calibrate` events).
    public var calibrations: [Double]
    /// (Unix time, name) of notable events, newest last.
    public var events: [(t: Double, name: String)]
    public var chunksRead: Int
    /// Session check: the worst stream verdict (PASS / WARN / FAIL).
    public var verdict: String {
        devices.isEmpty ? "FAIL" : SessionCheck.worst(devices.values.map(\.verdict))
    }
}

public enum ReviewLoader {
    public static let maxPlotPoints = 500
    public static let plotWindow: Double = 60
    static let notableEvents: Set<String> = [
        "start", "resume", "stop", "calibrate", "marker", "airpods_disconnected", "airpods_connected",
        "watch_unreachable", "watch_reachable", "write_error", "clock_jump", "app_background",
    ]

    /// Reads a session's closed chunks (phone/ and watch/) and builds the review.
    public static func load(store: FileStore, sessionID: String) throws -> ReviewData {
        let dir = "\(SessionRecorder.sessionsDir)/\(sessionID)"
        let (journal, _) = try Journal.read(store: store, path: "\(dir)/journal.jsonl")
        var files: [String] = []
        for e in journal where ["chunk_closed", "chunk_received"].contains(e["j"] as? String ?? "") {
            guard let path = e["file"] as? String, path.hasSuffix(".jsonl"), !path.hasSuffix("watch_journal.jsonl")
            else { continue }
            files.append(path)
        }
        var packets: [[String: Any]] = []
        for path in files where store.exists(path) {
            packets += Recording.packets(jsonl: try store.read(path))
        }
        return build(sessionID: sessionID, packets: packets, chunksRead: files.count)
    }

    /// Builds the review from packets (in any order). Watch samples come from the Watch's own
    /// chunks when present, otherwise from the phone's copy of the preview.
    public static func build(sessionID: String, packets: [[String: Any]], chunksRead: Int) -> ReviewData {
        var samples: [String: [(index: Int, unix: Double, sample: MotionSample)]] = [:]
        var events: [(t: Double, name: String)] = []
        var calibrations: [Double] = []
        let watchDisk = packets.contains { $0["source"] as? String == "watch_disk" }
        for p in packets {
            switch p["type"] as? String {
            case "imu":
                guard let device = p["device"] as? String, let first = p["first_index"] as? Int,
                    let raw = p["s"] as? [[Double]]
                else { continue }
                if device == "watch", watchDisk, p["source"] as? String != "watch_disk" { continue }
                let boot = p["boot_to_unix"] as? Double ?? 0
                for (k, s) in raw.enumerated() { samples[device, default: []].append((first + k, s[0] + boot, s)) }
            case "event":
                guard let name = p["name"] as? String, let t = p["unix"] as? Double else { continue }
                if name == "calibrate" { calibrations.append(t) }
                if notableEvents.contains(name) { events.append((t, name)) }
            default:
                continue
            }
        }
        let gap = QualityThresholds.shared.gapSeconds
        var devices: [String: ReviewData.Device] = [:]
        var start = Double.infinity
        var end = -Double.infinity
        for (device, all) in samples {
            let sorted = all.sorted { $0.unix < $1.unix }
            guard let first = sorted.first, let last = sorted.last else { continue }
            start = min(start, first.unix)
            end = max(end, last.unix)
            var covered: [ClosedRange<Double>] = []
            var spanStart = first.unix
            var previous = first.unix
            for s in sorted.dropFirst() {
                if s.unix - previous > gap {
                    covered.append(spanStart...previous)
                    spanStart = s.unix
                }
                previous = s.unix
            }
            covered.append(spanStart...previous)
            let stats = StreamStats(items: all.map { ($0.index, $0.unix) })
            let recent = sorted.filter { $0.unix >= last.unix - plotWindow }
            let reference = calibrationGravity(sorted, calibrations: calibrations)
            func series(_ value: (MotionSample) -> Double) -> [ReviewData.Point] {
                downsample(
                    recent.map { ReviewData.Point(t: $0.unix, value: value($0.sample)) }, maxPoints: maxPlotPoints)
            }
            devices[device] = ReviewData.Device(
                device: device, covered: covered, stats: stats,
                verdict: SessionCheck.verdict(stats, device: device),
                rotation: series { norm($0[11], $0[12], $0[13]) },
                acceleration: series { norm($0[5], $0[6], $0[7]) },
                angle: series { angleDegrees([$0[8], $0[9], $0[10]], reference) })
        }
        return ReviewData(
            sessionID: sessionID, start: start.isFinite ? start : nil, end: end.isFinite ? end : nil,
            devices: devices, calibrations: calibrations.sorted(), events: events.sorted { $0.t < $1.t },
            chunksRead: chunksRead)
    }

    /// Gravity at the last calibration (mean over its hold), or the first sample's when none.
    static func calibrationGravity(
        _ sorted: [(index: Int, unix: Double, sample: MotionSample)], calibrations: [Double]
    ) -> [Double] {
        guard let first = sorted.first else { return [0, -1, 0] }
        guard let cal = calibrations.last(where: { $0 <= sorted.last!.unix }) else {
            return [first.sample[8], first.sample[9], first.sample[10]]
        }
        let hold = sorted.filter { $0.unix >= cal + 0.3 && $0.unix <= cal + 3 }
        guard !hold.isEmpty else { return [first.sample[8], first.sample[9], first.sample[10]] }
        return (8...10).map { k in hold.map { $0.sample[k] }.reduce(0, +) / Double(hold.count) }
    }

    /// Keeps the min and max of each bucket so peaks survive (test P2); returns ≤ `maxPoints` points.
    public static func downsample(_ points: [ReviewData.Point], maxPoints: Int) -> [ReviewData.Point] {
        guard points.count > maxPoints, maxPoints >= 2 else { return points }
        let buckets = maxPoints / 2
        let size = Double(points.count) / Double(buckets)
        var out: [ReviewData.Point] = []
        out.reserveCapacity(maxPoints)
        for b in 0..<buckets {
            let lo = Int(Double(b) * size)
            let hi = min(points.count, Int(Double(b + 1) * size))
            guard lo < hi else { continue }
            let slice = points[lo..<hi]
            let mn = slice.min { $0.value < $1.value }!
            let mx = slice.max { $0.value < $1.value }!
            out += mn.t <= mx.t ? [mn, mx] : [mx, mn]
        }
        return out
    }

    static func norm(_ x: Double, _ y: Double, _ z: Double) -> Double { (x * x + y * y + z * z).squareRoot() }

    static func angleDegrees(_ a: [Double], _ b: [Double]) -> Double {
        let dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
        let n = norm(a[0], a[1], a[2]) * norm(b[0], b[1], b[2])
        guard n > 0 else { return 0 }
        return acos(max(-1, min(1, dot / n))) * 180 / .pi
    }
}

/// The live strip's dots for one stream (design §6).
public struct LiveDots: Equatable {
    public var age: Dot
    public var rate: Dot
    public var coverage: Dot
    public var worst: Dot { max(age, rate, coverage) }

    /// `baselineHz`: the stream's rate over its first minute.
    public init(snapshot: StreamSnapshot, baselineHz: Double?, dots: StatusDots = StatusDots()) {
        age = snapshot.lastPacketAge.map(dots.lastSampleAge) ?? .red
        if let base = baselineHz, base > 0 {
            rate = dots.rateVsBaseline(snapshot.measuredHz / base)
        } else {
            rate = .green
        }
        coverage = snapshot.samples == 0 ? .red : dots.coverage(snapshot.coverage)
    }
}
