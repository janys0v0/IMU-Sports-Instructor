import Foundation

/// Thresholds from `Resources/quality_thresholds.json`, shared with the Mac ingest script.
public struct QualityThresholds {
    public let raw: [String: Any]

    public static let shared: QualityThresholds = {
        guard let url = Bundle.module.url(forResource: "quality_thresholds", withExtension: "json"),
            let data = try? Data(contentsOf: url),
            let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { fatalError("quality_thresholds.json missing from MotionStreamerCore resources") }
        return QualityThresholds(raw: raw)
    }()

    public init(raw: [String: Any]) { self.raw = raw }

    public func value(_ path: String) -> Double {
        var node: Any? = raw
        for key in path.split(separator: ".") { node = (node as? [String: Any])?[String(key)] }
        guard let n = node as? NSNumber else { fatalError("threshold \(path) missing") }
        return n.doubleValue
    }

    public var gapSeconds: Double { value("gap_s") }
}

public enum Dot: String, Comparable {
    case green, yellow, red

    public static func < (a: Dot, b: Dot) -> Bool {
        let order: [Dot] = [.green, .yellow, .red]
        return order.firstIndex(of: a)! < order.firstIndex(of: b)!
    }
}

/// Status dots for the live strip and the Watch (design §6). Values exactly on a boundary are yellow.
public struct StatusDots {
    public let t: QualityThresholds

    public init(_ thresholds: QualityThresholds = .shared) { t = thresholds }

    public func lastSampleAge(_ seconds: Double) -> Dot {
        if seconds < t.value("status_dots.last_sample_age_s.green_below") { return .green }
        if seconds > t.value("status_dots.last_sample_age_s.red_above") { return .red }
        return .yellow
    }

    public func rateVsBaseline(_ ratio: Double) -> Dot {
        if ratio > t.value("status_dots.rate_vs_baseline.green_above") { return .green }
        if ratio < t.value("status_dots.rate_vs_baseline.red_below") { return .red }
        return .yellow
    }

    public func coverage(_ fraction: Double) -> Dot {
        if fraction > t.value("status_dots.coverage_60s.green_above") { return .green }
        if fraction < t.value("status_dots.coverage_60s.red_below") { return .red }
        return .yellow
    }

    public func watchChunksPending(_ count: Int) -> Dot {
        if Double(count) <= t.value("status_dots.watch_chunks_pending.green_max") { return .green }
        if Double(count) > t.value("status_dots.watch_chunks_pending.red_above") { return .red }
        return .yellow
    }
}

/// Exact sample accounting for one stream from (index, time) pairs — the same numbers as
/// experiments/common/stream_quality.py (E03) and pipeline/ingest (contract tests S2, S4).
public struct StreamStats: Equatable {
    public var samples = 0
    public var duplicates = 0
    public var missingFromIndex = 0
    public var backwardsTimestamps = 0
    public var deliveredHz = 0.0
    public var expectedAtDeliveredRate = 0
    public var coverage = 0.0
    public var gapsOverThreshold = 0
    public var longestGapMs = 0.0

    public init() {}

    /// `items`: every received sample's index and time (s), in arrival order, duplicates included.
    /// `window`: the span the stream should cover (e.g. Start → Stop); defaults to first → last
    /// sample. Only samples inside it count, and the expected count uses its length.
    public init(
        items: [(index: Int, t: Double)], window: ClosedRange<Double>? = nil,
        gapSeconds: Double = QualityThresholds.shared.gapSeconds
    ) {
        let sorted = items.enumerated().sorted { a, b in
            a.element.index != b.element.index ? a.element.index < b.element.index : a.offset < b.offset
        }.map(\.element)
        var unique: [(index: Int, t: Double)] = []
        for item in sorted {
            if let last = unique.last, last.index == item.index { duplicates += 1 } else { unique.append(item) }
        }
        guard let first = unique.first, let last = unique.last else { return }
        missingFromIndex = (last.index - first.index + 1) - unique.count
        let span = window ?? (first.t...last.t)
        let inside = unique.filter { span.contains($0.t) }
        samples = inside.count
        let dt = zip(inside.dropFirst(), inside).map { ($0.t - $1.t) * 1000 }
        backwardsTimestamps = dt.filter { $0 < 0 }.count
        guard !dt.isEmpty else { return }
        let medianDt = Self.median(dt)
        deliveredHz = Self.round(1000 / medianDt, 2)
        let medianRate = Self.median(dt.map { 1000 / $0 })
        expectedAtDeliveredRate = Int(((span.upperBound - span.lowerBound) * medianRate).rounded(.toNearestOrEven))
        coverage = expectedAtDeliveredRate > 0 ? Self.round(Double(samples) / Double(expectedAtDeliveredRate), 4) : 0
        let gaps = dt.filter { $0 > gapSeconds * 1000 }
        gapsOverThreshold = gaps.count
        longestGapMs = Self.round(gaps.max() ?? dt.max()!, 1)
    }

    /// numpy-style median (mean of the two middle values for an even count).
    static func median(_ values: [Double]) -> Double {
        let s = values.sorted()
        let n = s.count
        return n % 2 == 1 ? s[n / 2] : (s[n / 2 - 1] + s[n / 2]) / 2
    }

    /// Round half to even at `digits` decimals, like Python's round().
    static func round(_ value: Double, _ digits: Int) -> Double {
        let p = pow(10.0, Double(digits))
        return (value * p).rounded(.toNearestOrEven) / p
    }
}
