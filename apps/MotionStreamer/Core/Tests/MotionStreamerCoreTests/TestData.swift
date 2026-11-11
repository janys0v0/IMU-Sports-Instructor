import Foundation
import XCTest

@testable import MotionStreamerCore

/// Locations of real recordings (data/recordings, not in git). Tests that need them skip when
/// they're missing, e.g. in CI.
enum TestData {
    static let repoRoot: URL = {
        var url = URL(fileURLWithPath: #filePath)
        while url.path != "/" {
            url.deleteLastPathComponent()
            if FileManager.default.fileExists(atPath: url.appendingPathComponent("CONTRIBUTING.md").path) {
                return url
            }
        }
        return url
    }()

    static let recordings = repoRoot.appendingPathComponent("data/recordings")

    /// Key fixtures from docs/plan/test-plan.md §0.
    static let keySessions = [
        "20261008-153213-P01",  // reference routine, all 3 devices
        "20261008-153037-P01",  // no calibrate events (the timer bug)
        "20261008-152437-P01",  // AirPods start after the first calibration
        "20261008-150130-P01",  // 4 min, AirPods with 1 s gaps
    ]

    static func recording(_ session: String) throws -> Recording {
        let url = recordings.appendingPathComponent(session).appendingPathComponent("mac_stream.jsonl")
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw XCTSkip("recording \(session) not available (data/recordings is not in git)")
        }
        return try Recording(contentsOf: url)
    }
}
