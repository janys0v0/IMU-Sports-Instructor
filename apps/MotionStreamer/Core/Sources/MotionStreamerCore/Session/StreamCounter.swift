import Foundation

/// Per-stream counters shown in the UI and saved in the manifest.
public struct StreamSnapshot: Equatable {
    public var samples = 0
    public var missing = 0
    public var measuredHz = 0.0
    /// Rate the device delivers (from sample timestamps); coverage is relative to this.
    public var nominalHz = 0.0
    public var coverage = 0.0
    public var lastPacketAge: Double?

    public init(
        samples: Int = 0, missing: Int = 0, measuredHz: Double = 0, nominalHz: Double = 0,
        coverage: Double = 0, lastPacketAge: Double? = nil
    ) {
        self.samples = samples
        self.missing = missing
        self.measuredHz = measuredHz
        self.nominalHz = nominalHz
        self.coverage = coverage
        self.lastPacketAge = lastPacketAge
    }
}

/// Counts samples, missing indices and rates for one stream as batches arrive.
public struct StreamCounter {
    public private(set) var startUptime = 0.0
    public private(set) var samples = 0
    public private(set) var missing = 0
    private var nextIndex: Int?
    private var lastPacketUptime: Double?
    private var windowStart = 0.0
    private var windowSamples = 0
    private var measuredHz = 0.0
    /// First sample intervals (device clock), used to find the rate the device actually delivers.
    private var intervals: [Double] = []
    private var lastSampleTime: Double?

    public init(start: Double) {
        startUptime = start
        windowStart = start
    }

    /// Delivered sample rate from the median sample interval.
    public var nominalHz: Double? {
        guard intervals.count >= 10 else { return nil }
        let median = intervals.sorted()[intervals.count / 2]
        return median > 0 ? 1 / median : nil
    }

    public mutating func add(samples batch: [MotionSample], firstIndex: Int, now: Double) {
        let count = batch.count
        if let expected = nextIndex, firstIndex < expected {
            // A retried batch arrived after later ones: it was counted as missing.
            missing = max(0, missing - count)
        } else {
            if let expected = nextIndex { missing += firstIndex - expected }
            nextIndex = firstIndex + count
            for sample in batch {
                if let last = lastSampleTime, intervals.count < 200 { intervals.append(sample[0] - last) }
                lastSampleTime = sample[0]
            }
        }
        samples += count
        lastPacketUptime = now
        windowSamples += count
        if now - windowStart >= 2 {
            measuredHz = Double(windowSamples) / (now - windowStart)
            windowStart = now
            windowSamples = 0
        }
    }

    public func snapshot(now: Double) -> StreamSnapshot {
        let elapsed = now - startUptime
        var coverage = 0.0
        if let hz = nominalHz, elapsed > 1 { coverage = Double(samples) / (hz * elapsed) }
        return StreamSnapshot(
            samples: samples, missing: missing, measuredHz: measuredHz,
            nominalHz: nominalHz ?? 0, coverage: coverage,
            lastPacketAge: lastPacketUptime.map { now - $0 })
    }

    public var dictionary: [String: Any] {
        ["samples": samples, "missing_samples": missing, "delivered_rate_hz": nominalHz ?? 0]
    }
}
