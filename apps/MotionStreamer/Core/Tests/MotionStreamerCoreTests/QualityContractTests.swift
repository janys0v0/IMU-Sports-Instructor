import XCTest

@testable import MotionStreamerCore

/// S4: the Swift stats and session check give exactly the numbers the Python ingest gives, on the
/// shared fixtures in tests/fixtures/contract/ (written by make_fixtures.py).
final class QualityContractTests: XCTestCase {
    func test_S4_swiftMatchesPythonOnEveryContractFixture() throws {
        let dir = TestData.repoRoot.appendingPathComponent("tests/fixtures/contract")
        let files = try FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }
        XCTAssertGreaterThanOrEqual(files.count, 7)
        for url in files {
            let f = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
            let name = f["name"] as! String
            let items = (f["items"] as! [[NSNumber]]).map { (index: $0[0].intValue, t: $0[1].doubleValue) }
            let window = (f["window"] as? [Double]).map { $0[0]...$0[1] }
            let e = f["expected"] as! [String: Any]
            let s = StreamStats(items: items, window: window)
            XCTAssertEqual(s.samples, e["samples"] as? Int, name)
            XCTAssertEqual(s.duplicates, e["duplicates"] as? Int, name)
            XCTAssertEqual(s.missingFromIndex, e["missing_from_index"] as? Int, name)
            XCTAssertEqual(s.backwardsTimestamps, e["backwards_timestamps"] as? Int, name)
            XCTAssertEqual(s.deliveredHz, (e["delivered_hz"] as! NSNumber).doubleValue, name)
            XCTAssertEqual(s.expectedAtDeliveredRate, e["expected_at_delivered_rate"] as? Int, name)
            XCTAssertEqual(s.coverage, (e["coverage"] as! NSNumber).doubleValue, name)
            XCTAssertEqual(s.gapsOverThreshold, e["gaps_over_threshold"] as? Int, name)
            XCTAssertEqual(s.longestGapMs, (e["longest_gap_ms"] as! NSNumber).doubleValue, name)
            XCTAssertEqual(SessionCheck.verdict(s, device: f["device"] as! String), e["verdict"] as? String, name)
        }
    }
}
