import Foundation

/// The extra sensors of design §9, as new packet types next to the unchanged `imu` packets.
/// Every packet has a running index `i` per (type, device), so gaps are counted like motion.
public final class SensorPacketWriter {
    private var counters: [String: Int] = [:]
    /// Every packet carries it, like the motion packets, so the Mac files it under the right session.
    public let session: String
    public init(session: String = "") { self.session = session }

    private func next(_ key: String) -> Int {
        let i = counters[key, default: 0]
        counters[key] = i + 1
        return i
    }

    /// Barometer (CMAltimeter, ~1 Hz): pressure in kPa and altitude change since start in m.
    public func barometer(device: String, t: Double, pressureKPa: Double, relativeAltitudeM: Double, bootToUnix: Double)
        -> Data?
    {
        PacketEncoder.packet([
            "v": MotionFormat.version, "session": session, "type": "baro", "device": device,
            "i": next("baro/\(device)"), "t": t,
            "pressure_kpa": pressureKPa, "rel_alt_m": relativeAltitudeM, "boot_to_unix": bootToUnix,
        ])
    }

    /// Calibrated magnetic field (µT, device frame) and its accuracy (-1 uncalibrated … 2 high).
    public func magnetometer(device: String, t: Double, field: [Double], accuracy: Int, bootToUnix: Double) -> Data? {
        PacketEncoder.packet([
            "v": MotionFormat.version, "session": session, "type": "mag", "device": device, "i": next("mag/\(device)"),
            "t": t,
            "field_ut": field, "accuracy": accuracy, "boot_to_unix": bootToUnix,
        ])
    }

    /// Sound level only: RMS and peak in dBFS over one block, and whether a sharp onset started in it.
    /// No audio samples are ever stored (test X3).
    public func audioLevel(t: Double, rmsDB: Double, peakDB: Double, onset: Bool, bootToUnix: Double) -> Data? {
        PacketEncoder.packet([
            "v": MotionFormat.version, "session": session, "type": "audio_level", "device": "phone", "i": next("audio"),
            "t": t,
            "rms_db": (rmsDB * 10).rounded() / 10, "peak_db": (peakDB * 10).rounded() / 10, "onset": onset,
            "boot_to_unix": bootToUnix,
        ])
    }

    /// Optional Watch ↔ phone distance (UWB, Nearby Interaction).
    public func distance(t: Double, meters: Double, bootToUnix: Double) -> Data? {
        PacketEncoder.packet([
            "v": MotionFormat.version, "session": session, "type": "uwb", "device": "phone", "i": next("uwb"), "t": t,
            "distance_m": meters,
            "boot_to_unix": bootToUnix,
        ])
    }
}

/// Turns microphone buffers into sound levels and onsets (ball strikes, claps, footsteps) without
/// keeping the audio (design §9).
public final class AudioLevelMeter {
    /// An onset is a block this many dB above the median of the last second.
    public static let onsetRiseDB = 12.0
    public static let floorDB = -100.0
    private var history: [Double] = []
    private let historyBlocks: Int

    /// `blockSeconds`: the length of each buffer passed to `process` (e.g. 0.05 s).
    public init(blockSeconds: Double = 0.05) {
        historyBlocks = max(1, Int((1 / blockSeconds).rounded()))
    }

    /// Level of one block of samples (−1…1). The samples are not kept.
    public func process(_ samples: [Float]) -> (rmsDB: Double, peakDB: Double, onset: Bool) {
        guard !samples.isEmpty else { return (Self.floorDB, Self.floorDB, false) }
        let ms = samples.reduce(0.0) { $0 + Double($1) * Double($1) } / Double(samples.count)
        let peak = samples.reduce(0.0) { max($0, abs(Double($1))) }
        let rms = ms > 0 ? max(Self.floorDB, 10 * log10(ms)) : Self.floorDB
        let peakDB = peak > 0 ? max(Self.floorDB, 20 * log10(peak)) : Self.floorDB
        let baseline = history.isEmpty ? rms : StreamStats.median(history)
        let onset = history.count >= historyBlocks / 2 && rms - baseline >= Self.onsetRiseDB
        history.append(rms)
        if history.count > historyBlocks { history.removeFirst() }
        return (rms, peakDB, onset)
    }
}
