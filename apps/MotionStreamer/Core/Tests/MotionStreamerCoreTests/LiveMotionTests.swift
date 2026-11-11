import XCTest

@testable import MotionStreamerCore

/// The live motion plot after Start: the last 10 s of each sensor, so a person can see at a glance
/// that every device is recording and moves when they move.
final class LiveMotionTests: XCTestCase {
    /// [t, qx, qy, qz, qw, user acc (g) ×3, gravity ×3, rotation rate (rad/s) ×3]
    func sample(_ t: Double, rotation: Double = 0, acc: Double = 0) -> MotionSample {
        [t, 0, 0, 0, 1, acc, 0, 0, 0, 0, -1, rotation, 0, 0]
    }

    func test_lastTenSecondsAt20PointsPerSecond() {
        let recent = (0..<(15 * 60)).map { k in (arrival: Double(k) / 60, sample: sample(Double(k) / 60, rotation: 1)) }
        let points = LiveMotion.points(recent, now: 15)
        XCTAssertEqual(points.count, 200, accuracy: 2)
        XCTAssertEqual(points.first!.t, -10, accuracy: 0.1)
        XCTAssertEqual(points.last!.t, 0, accuracy: 0.1)
        XCTAssertEqual(points[50].rotation, 57.3, accuracy: 0.1, "°/s")
    }

    func test_batchedArrivalsAreSpreadByTheDevicesOwnClock() {
        // The Watch's preview arrives 10 samples at a time; its sample times keep them apart.
        let recent = (0..<600).map { k in
            (arrival: Double(k / 10) / 6 + 0.2, sample: sample(500 + Double(k) / 60, rotation: 1))
        }
        let points = LiveMotion.points(recent, now: recent.last!.arrival)
        let gaps = zip(points.dropFirst(), points).map { $0.t - $1.t }
        XCTAssertLessThanOrEqual(gaps.max()!, 0.051, "no batch-sized holes")
    }

    func test_peaksSurviveTheThinning() {
        var recent = (0..<600).map { k in (arrival: Double(k) / 60, sample: sample(Double(k) / 60)) }
        recent[300].sample = sample(5, rotation: 10, acc: 3)
        let points = LiveMotion.points(recent, now: 10)
        XCTAssertEqual(points.map(\.rotation).max()!, 573, accuracy: 1)
        XCTAssertEqual(points.map(\.acceleration).max()!, 3, accuracy: 0.01)
    }

    func test_aGapShowsAsMissingPoints() {
        let recent = (0..<600).filter { !(240..<420).contains($0) }.map { k in
            (arrival: Double(k) / 60, sample: sample(Double(k) / 60, rotation: 1))
        }
        let points = LiveMotion.points(recent, now: 10)
        XCTAssertFalse(points.contains { $0.t > -6 && $0.t < -3.1 })
        XCTAssertTrue(points.contains { $0.t < -6 })
    }

    func test_nothingRecordedGivesNoPoints() {
        XCTAssertEqual(LiveMotion.points([], now: 10), [])
    }
}
