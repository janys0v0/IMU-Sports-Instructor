import Foundation
import MotionStreamerCore

/// Launch settings for simulator demos and UI tests (the simulator has no motion sensors):
/// - `MOTIONSTREAMER_REPLAY`: path to a `mac_stream.jsonl`; its phone stream replays in real time.
/// - `MOTIONSTREAMER_AUTORESUME=1`: resume an interrupted session at launch without asking.
/// - `MOTIONSTREAMER_AUTOSTART=1`: start recording at launch.
enum ReplaySettings {
    static var environment: [String: String] { ProcessInfo.processInfo.environment }

    static func recording() -> Recording? {
        guard let path = environment["MOTIONSTREAMER_REPLAY"] else { return nil }
        return try? Recording(contentsOf: URL(fileURLWithPath: path))
    }

    static var autoResume: Bool { environment["MOTIONSTREAMER_AUTORESUME"] == "1" }
    static var autoStart: Bool { environment["MOTIONSTREAMER_AUTOSTART"] == "1" }
}
