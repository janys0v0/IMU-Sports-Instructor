import Foundation
import MotionStreamerCore

/// Launch settings for simulator demos and UI tests (the simulator has no motion sensors):
/// - `MOTIONSTREAMER_REPLAY`: path to a `mac_stream.jsonl`; its phone stream replays in real time.
/// - `MOTIONSTREAMER_AUTORESUME=1`: resume an interrupted session at launch without asking.
/// - `MOTIONSTREAMER_AUTOSTART=1`: start recording at launch.
/// - `MOTIONSTREAMER_OPEN_REVIEW=<s>`: open the review screen this many seconds after launch.
enum ReplaySettings {
    static var environment: [String: String] { ProcessInfo.processInfo.environment }

    static func recording() -> Recording? {
        guard let path = environment["MOTIONSTREAMER_REPLAY"] else { return nil }
        return try? Recording(contentsOf: URL(fileURLWithPath: path))
    }

    static var autoResume: Bool { environment["MOTIONSTREAMER_AUTORESUME"] == "1" }
    static var autoStart: Bool { environment["MOTIONSTREAMER_AUTOSTART"] == "1" }
    static var openReviewAfter: Double? { environment["MOTIONSTREAMER_OPEN_REVIEW"].flatMap(Double.init) }

    /// `MOTIONSTREAMER_SCRIPT=gonogo@2,start@5,calibrate@8,trial@60,…,stop@200`: drives the app's
    /// controller at those seconds after launch (end-to-end test E1 in the simulator).
    static var script: [(action: String, at: Double)] {
        (environment["MOTIONSTREAMER_SCRIPT"] ?? "").split(separator: ",").compactMap { step in
            let parts = step.split(separator: "@")
            guard parts.count == 2, let at = Double(parts[1]) else { return nil }
            return (String(parts[0]), at)
        }
    }
}
