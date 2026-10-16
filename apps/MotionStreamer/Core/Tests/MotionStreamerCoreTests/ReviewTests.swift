import SwiftUI
import XCTest

@testable import MotionStreamerCore

#if canImport(AppKit)
    import AppKit
#endif

/// Stage 4 gate (G4): the phone preview, tests P1-P5.
final class ReviewTests: XCTestCase {
    func test_P1_reviewReadsOnlyClosedChunks() throws {
        let h = try RecorderHarness()
        h.run(seconds: 70)  // chunk 0 closed, chunk 1 open and still being written
        let review = try ReviewLoader.load(store: h.store, sessionID: h.recorder.sessionID)
        let closed = Recording(jsonl: try h.store.read("\(h.dir)/phone/000000.jsonl")).sampleCount("phone")
        XCTAssertEqual(review.chunksRead, 1)
        XCTAssertEqual(review.devices["phone"]?.stats.samples, closed)
        XCTAssertLessThan(closed, h.nextIndex, "samples only in the open chunk never appear")
    }

    func test_P2_downsamplingKeepsPeaks() {
        var points = (0..<6000).map { ReviewData.Point(t: Double($0) / 100, value: sin(Double($0) / 50)) }
        points[1234].value = 9  // a short spike
        points[4321].value = -7
        let down = ReviewLoader.downsample(points, maxPoints: 500)
        XCTAssertLessThanOrEqual(down.count, 500)
        XCTAssertEqual(down.map(\.value).max(), 9)
        XCTAssertEqual(down.map(\.value).min(), -7)
        XCTAssertEqual(down.map(\.t), down.map(\.t).sorted(), "still in time order")
        // Every bucket's extremes are kept, so the envelope matches the full-rate curve.
        XCTAssertEqual(down.map(\.value).filter { $0 > 0.99 && $0 <= 1 }.isEmpty, false)
    }

    func test_P3_loadingOneChunkTakesUnder50ms() throws {
        let h = try RecorderHarness()
        h.run(seconds: 61)
        _ = try ReviewLoader.load(store: h.store, sessionID: h.recorder.sessionID)  // warm up
        let began = Date()
        let review = try ReviewLoader.load(store: h.store, sessionID: h.recorder.sessionID)
        XCTAssertLessThan(Date().timeIntervalSince(began), 0.05)
        XCTAssertEqual(review.chunksRead, 1)
    }

    func test_P4_gapsAndCalibrationMarksMatchTheJournal() {
        let review = ReviewLoader.build(sessionID: "s", packets: Self.syntheticPackets(), chunksRead: 3)
        let phone = try! XCTUnwrap(review.devices["phone"])
        XCTAssertEqual(phone.covered.count, 2, "one gap")
        XCTAssertEqual(phone.covered[0].upperBound, 1000 + 1799.0 / 60, accuracy: 0.001)
        XCTAssertEqual(phone.covered[1].lowerBound, 1000 + 34, accuracy: 0.001)
        XCTAssertEqual(review.calibrations, [1000 + 5, 1000 + 45])
        XCTAssertEqual(review.events.map(\.name), ["start", "calibrate", "airpods_disconnected", "calibrate"])
        XCTAssertEqual(review.verdict, "FAIL", "a 4 s gap fails the phone stream")
    }

    func test_liveDotsUseTheWorstCheck() {
        let fine = StreamSnapshot(samples: 100, measuredHz: 59, nominalHz: 60, coverage: 0.995, lastPacketAge: 0.1)
        XCTAssertEqual(LiveDots(snapshot: fine, baselineHz: 60).worst, .green)
        var late = fine
        late.lastPacketAge = 3
        XCTAssertEqual(LiveDots(snapshot: late, baselineHz: 60).worst, .red)
        var slow = fine
        slow.measuredHz = 48
        XCTAssertEqual(LiveDots(snapshot: slow, baselineHz: 60).rate, .yellow)
    }

    /// 60 s of phone + Watch data with a 4 s phone gap, two calibrations and an AirPods event.
    static func syntheticPackets() -> [[String: Any]] {
        var packets: [[String: Any]] = [["type": "event", "name": "start", "unix": 1000.0]]
        for device in ["phone", "watch"] {
            for k in stride(from: 0, to: 3600, by: 10) {
                let t = Double(k) / 60
                if device == "phone", t >= 30, t < 34 { continue }
                let samples = (0..<10).map { j -> [Double] in
                    let tt = t + Double(j) / 60
                    return SyntheticMotionSource.moving(rads: device == "phone" ? 1 : 3)(tt)
                }
                packets.append([
                    "type": "imu", "device": device, "first_index": k, "boot_to_unix": 1000.0, "s": samples,
                ])
            }
        }
        packets.append(["type": "event", "name": "calibrate", "unix": 1005.0])
        packets.append(["type": "event", "name": "airpods_disconnected", "unix": 1020.0])
        packets.append(["type": "event", "name": "calibrate", "unix": 1045.0])
        return packets
    }
}

#if canImport(AppKit)
    /// P5: the screens render the same as their committed reference images. A missing reference is
    /// recorded (and the test says so); rendering differs between machines, so CI skips this.
    @MainActor
    final class SnapshotTests: XCTestCase {
        static let dir = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("Snapshots")

        func snapshot<V: View>(_ name: String, _ view: V, size: CGSize) throws {
            if ProcessInfo.processInfo.environment["CI"] != nil { throw XCTSkip("snapshots are machine-specific") }
            let renderer = ImageRenderer(
                content: view.frame(width: size.width, height: size.height).background(Color.white))
            renderer.scale = 1
            let image = try XCTUnwrap(renderer.nsImage)
            let rep = try XCTUnwrap(NSBitmapImageRep(data: try XCTUnwrap(image.tiffRepresentation)))
            let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
            let url = Self.dir.appendingPathComponent("\(name).png")
            guard let reference = try? Data(contentsOf: url) else {
                try FileManager.default.createDirectory(at: Self.dir, withIntermediateDirectories: true)
                try png.write(to: url)
                print("recorded new snapshot \(url.lastPathComponent)")
                return
            }
            let a = try XCTUnwrap(NSBitmapImageRep(data: reference))
            XCTAssertEqual(a.pixelsWide, rep.pixelsWide, name)
            XCTAssertEqual(a.pixelsHigh, rep.pixelsHigh, name)
            var differing = 0
            for x in stride(from: 0, to: rep.pixelsWide, by: 2) {
                for y in stride(from: 0, to: rep.pixelsHigh, by: 2)
                where a.colorAt(x: x, y: y) != rep.colorAt(x: x, y: y) {
                    differing += 1
                }
            }
            let total = (rep.pixelsWide / 2) * (rep.pixelsHigh / 2)
            XCTAssertLessThan(
                Double(differing) / Double(total), 0.01, "\(name) changed; delete the reference to re-record")
        }

        func test_P5_reviewScreen() throws {
            let review = ReviewLoader.build(
                sessionID: "20261020-120000-P01", packets: ReviewTests.syntheticPackets(), chunksRead: 3)
            try snapshot(
                "review_screen", ReviewScreen(data: review, timeZone: TimeZone(identifier: "UTC")!),
                size: CGSize(width: 390, height: 640))
        }

        func test_P5_sessionCheckCard() throws {
            let review = ReviewLoader.build(
                sessionID: "20261020-120000-P01", packets: ReviewTests.syntheticPackets(), chunksRead: 3)
            try snapshot("session_check_card", SessionCheckCard(data: review), size: CGSize(width: 390, height: 160))
        }
    }
#endif

#if canImport(AppKit)
    /// Stage 4 demo: the reference routine with a 5 s AirPods gap cut in. The thigh angle shows the
    /// 3 squats and the gap shows in the timeline. Writes demo_review.png to $MSC_EXPORT_DIR.
    @MainActor
    final class ReviewDemoTests: XCTestCase {
        func test_demo_referenceSquatsAndInjectedAirPodsGap() throws {
            let recording = try TestData.recording("20261008-153213-P01")
            let start = try XCTUnwrap(recording.events.first { $0["name"] as? String == "start" }?["unix"] as? Double)
            var packets: [[String: Any]] = []
            for var p in recording.packets {
                if p["device"] as? String == "airpods", let raw = p["s"] as? [[Double]],
                    let boot = p["boot_to_unix"] as? Double
                {
                    let kept = raw.filter { !((start + 40)...(start + 45)).contains($0[0] + boot) }
                    if kept.isEmpty { continue }
                    p["s"] = kept
                }
                packets.append(p)
            }
            let review = ReviewLoader.build(sessionID: "20261008-153213-P01", packets: packets, chunksRead: 1)
            let airpods = try XCTUnwrap(review.devices["airpods"])
            let gap = zip(airpods.covered, airpods.covered.dropFirst()).map { $1.lowerBound - $0.upperBound }.max() ?? 0
            XCTAssertEqual(gap, 5, accuracy: 0.3, "the injected 5 s gap is in the timeline")
            // Squats: separate excursions of the thigh angle above 40° between 47.5 and 56.2 s.
            let phone = try XCTUnwrap(review.devices["phone"])
            var squats = 0
            var above = false
            for p in phone.angle where p.t >= start + 47.5 && p.t <= start + 56.2 {
                if !above, p.value > 40 { squats += 1 }
                above = p.value > 30 ? (above || p.value > 40) : false
            }
            XCTAssertEqual(squats, 3, "the thigh-angle plot shows the 3 squats")
            if let out = ProcessInfo.processInfo.environment["MSC_EXPORT_DIR"] {
                let renderer = ImageRenderer(
                    content: ReviewScreen(data: review).frame(width: 390, height: 640).background(Color.white))
                renderer.scale = 2
                if let tiff = renderer.nsImage?.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                    let png = rep.representation(using: .png, properties: [:])
                {
                    try png.write(to: URL(fileURLWithPath: out).appendingPathComponent("demo_review.png"))
                }
            }
        }
    }
#endif
