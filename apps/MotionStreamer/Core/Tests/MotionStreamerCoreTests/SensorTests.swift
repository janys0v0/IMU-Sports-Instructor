import XCTest

@testable import MotionStreamerCore

/// Stage 8 gate (G8): extra sensors X1-X3 and the Trial button.
final class SensorTests: XCTestCase {
    func test_X1_barometerPacketsHaveSensorTimesAndCountableGaps() throws {
        let writer = SensorPacketWriter()
        var items: [(index: Int, t: Double)] = []
        for k in 0..<120 where !(50..<55).contains(k) {  // 5 s missing
            let data = try XCTUnwrap(
                writer.barometer(
                    device: "phone", t: 100 + Double(k), pressureKPa: 101.3, relativeAltitudeM: 0.1, bootToUnix: 1.79e9)
            )
            let p = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            XCTAssertEqual(p["type"] as? String, "baro")
            XCTAssertEqual(p["t"] as? Double, 100 + Double(k))
            items.append((p["i"] as! Int, p["t"] as! Double))
        }
        // The writer numbers packets it writes; a sensor gap shows as a time gap (like motion).
        let stats = StreamStats(items: items, gapSeconds: 1.5)
        XCTAssertEqual(stats.gapsOverThreshold, 1)
        XCTAssertEqual(stats.longestGapMs, 6000)
    }

    func test_X5_everySensorPacketCarriesTheSession() throws {
        // Without it the Mac viewer took them for another session (found on device 2026-10-19).
        let writer = SensorPacketWriter(session: "20261019-115058-P01")
        let packets = [
            writer.barometer(device: "phone", t: 1, pressureKPa: 101, relativeAltitudeM: 0, bootToUnix: 0),
            writer.magnetometer(device: "phone", t: 1, field: [1, 2, 3], accuracy: 2, bootToUnix: 0),
            writer.audioLevel(t: 1, rmsDB: -40, peakDB: -30, onset: false, bootToUnix: 0),
            writer.distance(t: 1, meters: 1.5, bootToUnix: 0),
        ]
        for data in packets {
            let p = try JSONSerialization.jsonObject(with: XCTUnwrap(data)) as! [String: Any]
            XCTAssertEqual(p["session"] as? String, "20261019-115058-P01", "\(p["type"] ?? "")")
        }
    }

    func test_X2_magnetometerLoggedPerDeviceAndLowAccuracyWarns() throws {
        let writer = SensorPacketWriter()
        let phone =
            try JSONSerialization.jsonObject(
                with: XCTUnwrap(
                    writer.magnetometer(device: "phone", t: 1, field: [20, -5, 40], accuracy: 0, bootToUnix: 0)))
            as! [String: Any]
        let watch =
            try JSONSerialization.jsonObject(
                with: XCTUnwrap(
                    writer.magnetometer(device: "watch", t: 1, field: [1, 2, 3], accuracy: 2, bootToUnix: 0)))
            as! [String: Any]
        XCTAssertEqual(phone["device"] as? String, "phone")
        XCTAssertEqual(watch["accuracy"] as? Int, 2)
        XCTAssertEqual(phone["i"] as? Int, 0)
        let h = WatchdogHarness()
        h.run(3) { input, _ in input.compassAccuracyLow = true }
        XCTAssertTrue(h.said("compass_disturbed"))
    }

    func test_X3_audioKeepsOnlyLevelsAndOnsets() throws {
        let meter = AudioLevelMeter(blockSeconds: 0.05)
        let writer = SensorPacketWriter()
        var onsets: [Int] = []
        var packets: [Data] = []
        for block in 0..<60 {
            let amplitude: Float = block == 40 ? 0.9 : 0.01  // a ball strike in block 40
            let samples = (0..<2205).map { k in amplitude * sin(Float(k) * 0.3) }
            let level = meter.process(samples)
            if level.onset { onsets.append(block) }
            packets.append(
                try XCTUnwrap(
                    writer.audioLevel(
                        t: Double(block) / 20, rmsDB: level.rmsDB, peakDB: level.peakDB, onset: level.onset,
                        bootToUnix: 0)))
        }
        XCTAssertEqual(onsets, [40])
        for data in packets {
            let p = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            XCTAssertEqual(
                Set(p.keys), ["v", "session", "type", "device", "i", "t", "rms_db", "peak_db", "onset", "boot_to_unix"])
            XCTAssertFalse(p.values.contains { $0 is [Any] }, "no sample arrays: no raw audio")
            XCTAssertLessThan(data.count, 200)
        }
        XCTAssertEqual(AudioSessionSpec.preferredInput, "builtInMic")
    }

    func test_X4_exportSessionWithExtraPacketsForPython() throws {
        guard let out = ProcessInfo.processInfo.environment["MSC_EXPORT_DIR"] else {
            throw XCTSkip("set MSC_EXPORT_DIR (tools/run_tests.sh does)")
        }
        let writer = SensorPacketWriter()
        var lines: [Data] = []
        for k in 0..<240 {
            let t = 100 + Double(k) / 60 * 5
            let samples = (0..<5).map { j in SyntheticMotionSource.still(t + Double(j) / 60) }
            lines += PacketEncoder.imuPackets(
                header: ["type": "imu", "device": "phone", "loc": "right_pocket", "boot_to_unix": 0.0],
                samples: samples,
                firstIndex: 5 * k)
            if k % 12 == 0 {
                lines.append(
                    writer.barometer(device: "phone", t: t, pressureKPa: 101.3, relativeAltitudeM: 0, bootToUnix: 0)!)
                lines.append(
                    writer.magnetometer(device: "phone", t: t, field: [20, 0, 40], accuracy: 1, bootToUnix: 0)!)
            }
            lines.append(writer.audioLevel(t: t, rmsDB: -40, peakDB: -30, onset: k == 100, bootToUnix: 0)!)
        }
        let url = URL(fileURLWithPath: out).appendingPathComponent("x4_stream.jsonl")
        try lines.map { String(data: $0, encoding: .utf8)! }.joined(separator: "\n").appending("\n")
            .write(to: url, atomically: true, encoding: .utf8)
    }

    func test_trialButtonStartsEndsAndChecksEachTrial() {
        let clock = ManualClock()
        let tracker = TrialTracker(clock: clock)
        var events: [String] = []
        tracker.onEvent = { name, _ in events.append(name) }
        func check(keep: Bool) -> (Int, Double, Double) -> TrialCheck {
            { n, start, end in
                var input = TrialCheck.Input(
                    trial: n, start: start, end: end,
                    items: ["phone": (0..<4000).map { ($0, start - 3 + Double($0) / 33) }],
                    requiredDevices: ["phone"], syncGestureDetected: keep)
                input.lastGoodCalibration = start - 10
                return TrialCheck(input)
            }
        }
        XCTAssertEqual(tracker.tap(check: check(keep: true)), .started(1))
        clock.advance(30)
        XCTAssertEqual(tracker.tap(check: check(keep: true)), .ended(1, keep: true, spoken: nil))
        XCTAssertEqual(tracker.tap(check: check(keep: false)), .started(2))
        clock.advance(30)
        guard case .ended(2, keep: false, let spoken) = tracker.tap(check: check(keep: false)) else {
            return XCTFail("trial 2 should need a redo")
        }
        XCTAssertEqual(spoken, "Redo trial 2. The three hops weren't detected.")
        XCTAssertEqual(events, ["marker", "marker", "trial_check", "marker", "marker", "trial_check"])
        XCTAssertEqual(
            CourtExitCheck(trials: tracker.trials, watchSummary: nil, chunks60HzOnPhone: 0, watchRequired: false)
                .verdict,
            .redo(trials: [2]))
    }
}
