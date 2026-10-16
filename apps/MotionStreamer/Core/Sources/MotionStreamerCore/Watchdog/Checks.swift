import Foundation

/// The Go / No-Go check before Start (design §8 ①).
public struct GoNoGo {
    public struct Check: Equatable {
        public var id: String
        public var ok: Bool
        public var detail: String
        /// A failed blocking check stops Start; others only warn.
        public var blocking: Bool
    }

    public struct Input {
        /// device -> (samples per second now, expected rate)
        public var liveRates: [String: (rate: Double, expected: Double)] = [:]
        public var requiredDevices: Set<String> = ["phone", "watch", "airpods"]
        public var plannedMinutes: Double = 60
        public var batteryPhone: Double?
        public var batteryWatch: Double?
        /// Hours the AirPods have been connected since they were last charged (not readable directly).
        public var airpodsConnectedHours: Double = 0
        public var freeDiskPhone: Int64 = .max
        public var freeDiskWatch: Int64?
        public var lowPowerPhone = false
        public var lowPowerWatch = false
        public var signingDaysLeft: Double?
        public var heardVoice: Bool?
        public var landmark = ""
        public var highRateAvailable = true

        public init() {}
    }

    /// Battery drain per hour (measured in device tests; these are the planning defaults).
    public static let drainPerHour = ["phone": 0.15, "watch": 0.30]
    public static let airpodsHours = 3.5

    public let checks: [Check]
    public var canStart: Bool { checks.allSatisfy { $0.ok || !$0.blocking } }
    public var failures: [Check] { checks.filter { !$0.ok } }

    public init(_ i: Input) {
        var c: [Check] = []
        for device in ["phone", "watch", "airpods"] where i.requiredDevices.contains(device) {
            let live = i.liveRates[device]
            let ok = live.map { $0.rate >= 0.8 * $0.expected } ?? false
            c.append(
                Check(
                    id: "\(device)_live", ok: ok,
                    detail: live.map { String(format: "%.0f of %.0f samples/s", $0.rate, $0.expected) } ?? "no data",
                    blocking: true))
        }
        let hours = i.plannedMinutes / 60
        for (device, level) in [("phone", i.batteryPhone), ("watch", i.batteryWatch)] {
            guard i.requiredDevices.contains(device), let level else { continue }
            let left = level - Self.drainPerHour[device]! * hours
            let minutes = Int(max(0, level - 0.1) / Self.drainPerHour[device]! * 60)
            c.append(
                Check(id: "\(device)_battery", ok: left >= 0.1, detail: "enough for \(minutes) min", blocking: true))
        }
        if i.requiredDevices.contains("airpods") {
            let left = Self.airpodsHours - i.airpodsConnectedHours
            c.append(
                Check(
                    id: "airpods_battery", ok: left >= hours,
                    detail: String(format: "about %.1f h left (estimated)", max(0, left)), blocking: false))
        }
        c.append(
            Check(
                id: "phone_disk", ok: i.freeDiskPhone >= SessionRecorder.minFreeBytes,
                detail: String(format: "%.1f GB free", Double(i.freeDiskPhone) / 1e9), blocking: true))
        if let watchDisk = i.freeDiskWatch {
            c.append(
                Check(
                    id: "watch_disk", ok: watchDisk >= SessionRecorder.minFreeBytes,
                    detail: String(format: "%.1f GB free", Double(watchDisk) / 1e9), blocking: true))
        }
        c.append(
            Check(
                id: "low_power", ok: !i.lowPowerPhone && !i.lowPowerWatch, detail: "Low Power Mode must be off",
                blocking: true))
        if let days = i.signingDaysLeft {
            let ok = days * 24 * 60 > i.plannedMinutes
            c.append(
                Check(
                    id: "signing", ok: ok,
                    detail: ok
                        ? String(format: "app expires in %.0f days", days)
                        : "rebuild the app: it expires during the session",
                    blocking: true))
        }
        if i.requiredDevices.contains("watch") {
            c.append(
                Check(id: "high_rate", ok: i.highRateAvailable, detail: "800 / 200 Hz Watch stream", blocking: true))
        }
        if let heard = i.heardVoice {
            c.append(
                Check(
                    id: "audibility", ok: heard, detail: heard ? "voice heard" : "raise the volume or switch output",
                    blocking: true))
        }
        c.append(
            Check(
                id: "landmark", ok: !i.landmark.trimmingCharacters(in: .whitespaces).isEmpty,
                detail: "set what to face", blocking: true))
        checks = c
    }
}

/// Detects the sync gesture's 3 hops in phone motion: three acceleration peaks above 1 g, 0.25-1.5 s
/// apart, within 4 s.
public enum SyncGesture {
    public static func detected(_ phone: [MotionSample], from: Double, to: Double) -> Bool {
        var peaks: [Double] = []
        var above = false
        for s in phone where s[0] >= from && s[0] <= to {
            let a = ReviewLoader.norm(s[5], s[6], s[7])
            if a > 1.0, !above {
                peaks.append(s[0])
                above = true
            } else if a < 0.5 {
                above = false
            }
        }
        for k in 0..<max(0, peaks.count - 2) {
            let p = Array(peaks[k...(k + 2)])
            let gaps = zip(p.dropFirst(), p).map { $0 - $1 }
            if gaps.allSatisfy({ $0 >= 0.25 && $0 <= 1.5 }), p[2] - p[0] <= 4 { return true }
        }
        return false
    }
}

/// The check after each trial (design §8 ③): every required stream complete in the trial window.
public struct TrialCheck {
    public struct Input {
        public var trial: Int
        public var start: Double
        public var end: Double
        /// device -> (index, time on the phone clock) of every sample received.
        public var items: [String: [(index: Int, t: Double)]]
        public var baselineHz: [String: Double] = [:]
        public var requiredDevices: Set<String>
        public var lastGoodCalibration: Double?
        /// Times of events that spoil a calibration (AirPods reconnect, phone moved, …).
        public var calibrationResets: [Double] = []
        public var reminderInterval: Double = 600
        public var syncGestureDetected: Bool
        /// The newest time data can have (the check runs as the trial ends, so the window's
        /// padding after the end is clipped here instead of counting as a gap).
        public var dataUntil: Double?

        public init(
            trial: Int, start: Double, end: Double, items: [String: [(index: Int, t: Double)]],
            requiredDevices: Set<String>, syncGestureDetected: Bool
        ) {
            self.trial = trial
            self.start = start
            self.end = end
            self.items = items
            self.requiredDevices = requiredDevices
            self.syncGestureDetected = syncGestureDetected
        }
    }

    public let keep: Bool
    public let reasons: [String]
    /// What is spoken when the trial must be redone.
    public let spoken: String?

    public init(_ i: Input, thresholds t: QualityThresholds = .shared, script: VoiceScript = .shared) {
        var reasons: [String] = []
        let pad = t.value("trial_check.window_padding_s")
        let window = (i.start - pad)...max(i.start, min(i.end + pad, i.dataUntil ?? .infinity))
        let names = ["phone": ("phone", "was"), "watch": ("watch", "was"), "airpods": ("AirPods", "were")]
        for device in ["phone", "watch", "airpods"] where i.requiredDevices.contains(device) {
            let items = (i.items[device] ?? []).filter { window.contains($0.t) }
            let (name, verb) = names[device]!
            guard items.count > 1 else {
                reasons.append("The \(name) recorded nothing.")
                continue
            }
            let sorted = items.map(\.t).sorted()
            var longest = max(sorted.first! - window.lowerBound, window.upperBound - sorted.last!)
            for (a, b) in zip(sorted, sorted.dropFirst()) { longest = max(longest, b - a) }
            let rate = Double(items.count) / (window.upperBound - window.lowerBound)
            let base = i.baselineHz[device] ?? rate
            if longest > t.value("trial_check.max_gap_s") {
                reasons.append("The \(name) \(verb) missing for \(Int(longest.rounded())) seconds.")
            } else if rate / base < t.value("trial_check.min_rate_vs_baseline") {
                reasons.append("The \(name) recorded too slowly.")
            } else if Double(items.count) / ((window.upperBound - window.lowerBound) * base)
                < t.value("trial_check.min_coverage")
            {
                reasons.append("The \(name) missed some data.")
            }
        }
        if let cal = i.lastGoodCalibration {
            if i.start - cal > i.reminderInterval || i.calibrationResets.contains(where: { $0 > cal && $0 < i.end }) {
                reasons.append("Calibrate again first.")
            }
        } else {
            reasons.append("Calibrate first.")
        }
        if !i.syncGestureDetected { reasons.append("The three hops weren't detected.") }
        keep = reasons.isEmpty
        self.reasons = reasons
        spoken =
            keep
            ? nil
            : script.alert("redo_trial").map {
                VoiceScript.fill($0.text, ["trial": "\(i.trial)", "reason": reasons[0]])
            }
    }
}

/// The court-exit check before Stop (design §8 ④): every trial kept, every 60 Hz Watch chunk on the
/// phone, every high-rate chunk closed on the Watch (the transfer itself can come later).
public struct CourtExitCheck {
    public enum Verdict: Equatable {
        case safe
        case redo(trials: [Int])
        case waiting(String)
    }

    public let verdict: Verdict

    /// `watchSummary`: (60 Hz chunks, high-rate chunks, every high-rate chunk closed) from the Watch at Stop.
    public init(
        trials: [(number: Int, keep: Bool)],
        watchSummary: (chunks60Hz: Int, chunksHighRate: Int, highRateClosed: Bool)?,
        chunks60HzOnPhone: Int, watchRequired: Bool = true
    ) {
        let redo = trials.filter { !$0.keep }.map(\.number)
        if !redo.isEmpty {
            verdict = .redo(trials: redo)
        } else if !watchRequired {
            verdict = .safe
        } else if let s = watchSummary {
            if !s.highRateClosed {
                verdict = .waiting("a high-rate chunk is still open on the Watch")
            } else if chunks60HzOnPhone < s.chunks60Hz {
                verdict = .waiting("\(s.chunks60Hz - chunks60HzOnPhone) Watch chunks still on their way")
            } else {
                verdict = .safe
            }
        } else {
            verdict = .waiting("waiting for the Watch to finish")
        }
    }
}
