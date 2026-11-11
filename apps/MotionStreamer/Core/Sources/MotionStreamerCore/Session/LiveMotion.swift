import Foundation

/// The live motion plot after Start (design §6): the last few seconds of each sensor's rotation
/// speed and acceleration, so a glance shows every device is recording and moves with the person.
public enum LiveMotion {
    public struct Point: Equatable {
        /// Seconds before now (≤ 0).
        public var t: Double
        /// Rotation speed, °/s.
        public var rotation: Double
        /// Acceleration without gravity, g.
        public var acceleration: Double
    }

    public static let window: Double = 10
    public static let pointsPerSecond: Double = 20

    /// Points for one device from its recent samples (phone arrival time, sample). Times come from
    /// the device's own sample clock, anchored at the newest sample's arrival, so batched arrivals
    /// (the Watch sends 10 samples at once) still plot evenly. Each point keeps the largest value in
    /// its 1/20 s, so short peaks survive the thinning.
    public static func points(
        _ recent: [(arrival: Double, sample: MotionSample)], now: Double, window: Double = window
    ) -> [Point] {
        guard let last = recent.last, last.sample.count >= 14 else { return [] }
        let offset = last.arrival - now - last.sample[0]
        let bins = Int(window * pointsPerSecond)
        var rotation = [Double?](repeating: nil, count: bins)
        var acceleration = [Double](repeating: 0, count: bins)
        for (_, s) in recent.reversed() {
            let t = s[0] + offset
            if t < -window { break }
            let k = min(bins - 1, Int((t + window) * pointsPerSecond))
            guard k >= 0 else { continue }
            let w = (s[11] * s[11] + s[12] * s[12] + s[13] * s[13]).squareRoot() * 180 / .pi
            let a = (s[5] * s[5] + s[6] * s[6] + s[7] * s[7]).squareRoot()
            rotation[k] = max(rotation[k] ?? 0, w)
            acceleration[k] = max(acceleration[k], a)
        }
        return (0..<bins).compactMap { k in
            rotation[k].map {
                Point(t: (Double(k) + 0.5) / pointsPerSecond - window, rotation: $0, acceleration: acceleration[k])
            }
        }
    }
}
