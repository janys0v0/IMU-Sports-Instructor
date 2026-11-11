import XCTest

@testable import MotionStreamerCore

/// Gate G0: the test harness itself (docs/plan/dev-plan.md, stage 0).
final class HarnessTests: XCTestCase {
    func test_G0_replayKeyRecordingsDeliversEverySample() throws {
        for session in TestData.keySessions {
            let recording = try TestData.recording(session)
            XCTAssertGreaterThan(recording.sampleCount("phone"), 0, session)
            for device in recording.streams.keys {
                let source = ReplayMotionSource(recording: recording, device: device)
                var delivered = 0
                var lastTime = -Double.infinity
                source.start { sample in
                    delivered += 1
                    XCTAssertGreaterThanOrEqual(sample[0], lastTime - 1e-9, "\(session) \(device) out of order")
                    lastTime = sample[0]
                    XCTAssertEqual(sample.count, MotionFormat.sampleFields.count)
                }
                source.emit(until: .infinity)
                XCTAssertEqual(delivered, recording.sampleCount(device), "\(session) \(device)")
            }
        }
    }

    func test_G0_sixtyMinuteSessionOnFakeClockRunsInSeconds() {
        let clock = ManualClock()
        let start = clock.uptime
        let sources: [SyntheticMotionSource] = [
            SyntheticMotionSource(device: "phone", rateHz: 60, start: start),
            SyntheticMotionSource(device: "watch", rateHz: 60, start: start),
            SyntheticMotionSource(device: "airpods", rateHz: 25, start: start),
        ]
        var counters = Dictionary(uniqueKeysWithValues: sources.map { ($0.device, StreamCounter(start: start)) })
        var nextIndex: [String: Int] = [:]
        for source in sources {
            source.start { sample in
                let i = nextIndex[source.device, default: 0]
                counters[source.device]!.add(samples: [sample], firstIndex: i, now: clock.uptime)
                nextIndex[source.device] = i + 1
            }
        }
        let began = Date()
        for _ in 0..<3600 {
            clock.advance(1)
            for source in sources { source.emit(until: clock.uptime) }
        }
        XCTAssertLessThan(Date().timeIntervalSince(began), 10)
        XCTAssertEqual(counters["phone"]!.samples, 60 * 3600 + 1)
        XCTAssertEqual(counters["airpods"]!.samples, 25 * 3600 + 1)
        XCTAssertEqual(counters["phone"]!.missing, 0)
    }

    func test_C1_stopDuringCalibrationDoesNotBlockTheNextOne() {
        let h = CalibrationHarness()
        h.flow.start()
        h.run(seconds: 3)
        XCTAssertTrue(h.flow.isRunning)
        h.flow.cancel()  // Stop pressed during the calibration
        XCTAssertFalse(h.flow.isRunning)
        h.flow.start()
        h.run()
        XCTAssertEqual(h.result?.passed, true, "a new calibration runs to the end")
    }
}

/// Stage 0 "no change in behaviour": the moved encoder rebuilds today's packets exactly.
final class PacketCompatibilityTests: XCTestCase {
    func test_G0_encoderRebuildsReferenceRecordingPackets() throws {
        let recording = try TestData.recording("20261008-153213-P01")
        let imu = recording.packets.filter { $0["type"] as? String == "imu" }
        XCTAssertGreaterThan(imu.count, 100)
        for original in imu {
            var header = original
            header.removeValue(forKey: "s")
            header.removeValue(forKey: "first_index")
            header.removeValue(forKey: "recv_mac_unix")  // added by the Mac receiver
            let samples = try XCTUnwrap(original["s"] as? [[Double]])
            let rebuilt = PacketEncoder.imuPackets(
                header: header, samples: samples, firstIndex: original["first_index"] as! Int)
            XCTAssertEqual(rebuilt.count, 1)
            var parsed = try XCTUnwrap(JSONSerialization.jsonObject(with: rebuilt[0]) as? [String: Any])
            parsed["recv_mac_unix"] = original["recv_mac_unix"]
            XCTAssertEqual(NSDictionary(dictionary: parsed), NSDictionary(dictionary: original))
        }
    }
}
