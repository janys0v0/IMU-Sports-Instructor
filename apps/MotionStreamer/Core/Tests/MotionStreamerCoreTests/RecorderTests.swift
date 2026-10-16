import XCTest

@testable import MotionStreamerCore

/// Drives a session recorder with synthetic phone packets on a fake clock.
final class RecorderHarness {
    let clock = ManualClock()
    let store: MemoryFileStore
    var recorder: SessionRecorder
    var nextIndex = 0
    var errors: [Error] = []

    init(store: MemoryFileStore = MemoryFileStore(), id: String = "20261020-120000-P01") throws {
        self.store = store
        recorder = try SessionRecorder.start(
            store: store, clock: clock, sessionID: id, metadata: ["participant": "P01"])
        recorder.phone.onWriteError = { [weak self] in self?.errors.append($0) }
    }

    /// Records `seconds` of phone data: one 5-sample packet every 5/60 s, ticking as the app does.
    func run(seconds: Double) {
        let packetsPerSecond = 12
        for _ in 0..<Int(seconds * Double(packetsPerSecond)) {
            clock.advance(1 / Double(packetsPerSecond))
            let samples = (0..<5).map { k in SyntheticMotionSource.still(clock.uptime - Double(4 - k) / 60) }
            let packet = PacketEncoder.imuPackets(
                header: ["type": "imu", "device": "phone", "loc": "left_pocket"], samples: samples,
                firstIndex: nextIndex)[0]
            recorder.record(packet, device: "phone", firstIndex: nextIndex, count: 5)
            nextIndex += 5
            recorder.tick()
        }
    }

    var dir: String { recorder.directory }
    func phoneFiles() -> [String] { (try? store.list("\(dir)/phone")) ?? [] }
    func journal() -> [[String: Any]] { (try? Journal.read(store: store, path: "\(dir)/journal.jsonl").entries) ?? [] }
    func entries(_ type: String) -> [[String: Any]] { journal().filter { $0["j"] as? String == type } }

    /// Every sample index found in the phone chunks, in file order.
    func indicesOnDisk(_ store: FileStore? = nil) -> [Int] {
        let s = store ?? self.store
        return ((try? s.list("\(dir)/phone")) ?? []).flatMap { name -> [Int] in
            let data = (try? s.read("\(dir)/phone/\(name)")) ?? Data()
            return Recording(jsonl: data).streams["phone"]?.samples.map(\.index) ?? []
        }
    }
}

final class RecorderTests: XCTestCase {
    func test_R1_threeMinutesGiveThreeClosedChunksAndOneOpen() throws {
        let h = try RecorderHarness()
        h.run(seconds: 185)
        let files = h.phoneFiles()
        XCTAssertEqual(files.filter { $0.hasSuffix(".jsonl") }.count, 3)
        XCTAssertEqual(files.filter { $0.hasSuffix(".open") }.count, 1)
        XCTAssertEqual(h.indicesOnDisk(), Array(0..<h.nextIndex), "every sample exactly once, in order")
    }

    func test_R2_syncOncePerSecondAndAtClose() throws {
        let h = try RecorderHarness()
        h.run(seconds: 125)
        let first = try XCTUnwrap(h.store.files["\(h.dir)/phone/000000.jsonl"])
        // 60 s of 1 s syncs (the last one coincides with closing) + the close itself.
        XCTAssertEqual(Double(first.syncCount), 61, accuracy: 1)
    }

    func test_R3_closedChunkHashMatchesAndIsNeverWrittenAgain() throws {
        let h = try RecorderHarness()
        h.run(seconds: 65)
        let closed = try XCTUnwrap(h.entries("chunk_closed").first)
        let path = try XCTUnwrap(closed["file"] as? String)
        XCTAssertTrue(path.hasSuffix("000000.jsonl"))
        let before = try h.store.read(path)
        XCTAssertEqual(closed["sha256"] as? String, sha256Hex(before))
        h.run(seconds: 30)
        XCTAssertEqual(try h.store.read(path), before)
        XCTAssertNil(h.store.files[path + ".open"])
    }

    func test_R4_diskFullClosesChunkLogsErrorAndStartsNewChunk() throws {
        let h = try RecorderHarness()
        h.run(seconds: 10)
        h.store.failNextAppend = .diskFull
        h.run(seconds: 10)
        XCTAssertEqual(h.errors.first as? FileStoreError, .diskFull, "the watchdog is told (it speaks the alert)")
        XCTAssertEqual(h.entries("write_error").count, 1)
        XCTAssertEqual(h.entries("chunk_closed").count, 1, "the interrupted chunk was closed")
        XCTAssertEqual(h.recorder.phone.lostRecords, 0, "the retry in a new chunk kept the packet")
        XCTAssertEqual(h.indicesOnDisk(), Array(0..<h.nextIndex))
    }

    func test_R4_lostPacketIsCountedNotSilent() throws {
        let h = try RecorderHarness()
        h.run(seconds: 2)
        h.store.capacity = h.store.usedBytes + 10  // nothing more fits
        h.run(seconds: 1)
        XCTAssertGreaterThan(h.recorder.phone.lostRecords, 0)
        XCTAssertFalse(h.errors.isEmpty)
    }

    func test_R5_syncFailureIsReportedAndRecordingContinues() throws {
        let h = try RecorderHarness()
        h.run(seconds: 5)
        h.store.failNextSync = .ioError("fsync")
        h.run(seconds: 5)
        XCTAssertEqual(h.errors.count, 1)
        h.run(seconds: 60)
        XCTAssertEqual(h.indicesOnDisk(), Array(0..<h.nextIndex))
    }

    func test_R6_startIsBlockedBelowTwoGigabytes() {
        let store = MemoryFileStore()
        store.capacity = 1_500_000_000
        XCTAssertThrowsError(
            try SessionRecorder.start(store: store, clock: ManualClock(), sessionID: "x", metadata: [:])
        ) { error in
            XCTAssertEqual(error as? SessionRecorder.StartError, .lowDisk(freeBytes: 1_500_000_000))
        }
    }

    func test_R7_everyFileUsesTheUntilFirstUnlockProtection() throws {
        let h = try RecorderHarness()
        h.run(seconds: 70)
        try h.recorder.stop()
        XCTAssertFalse(h.store.files.isEmpty)
        for (path, file) in h.store.files { XCTAssertTrue(file.protected, path) }
    }

    /// R8 part 1: write a session to disk for the Python check (tests/test_recorder_format.py).
    func test_R8_exportSessionForPythonCheck() throws {
        guard let out = ProcessInfo.processInfo.environment["MSC_EXPORT_DIR"] else {
            throw XCTSkip("set MSC_EXPORT_DIR (tools/run_tests.sh does) to export a session")
        }
        let root = URL(fileURLWithPath: out)
        try? FileManager.default.removeItem(at: root)
        let store = LocalFileStore(root: root)
        let clock = ManualClock()
        let recorder = try SessionRecorder.start(
            store: store, clock: clock, sessionID: "20261020-120000-P98", metadata: [:])
        var index = 0
        for _ in 0..<(12 * 130) {
            clock.advance(1.0 / 12)
            let samples = (0..<5).map { k in SyntheticMotionSource.moving()(clock.uptime + Double(k) / 60) }
            for packet in PacketEncoder.imuPackets(
                header: [
                    "type": "imu", "device": "phone", "loc": "left_pocket", "boot_to_unix": clock.bootToUnix,
                    "ref_frame": "xMagneticNorthZVertical", "rate_hz": 60,
                ],
                samples: samples, firstIndex: index)
            {
                recorder.record(packet, device: "phone", firstIndex: index, count: 5)
            }
            index += 5
            recorder.tick()
        }
        try recorder.stop()
    }
}

final class JournalTests: XCTestCase {
    func test_J1_oneJournalLinePerStateChange() throws {
        let h = try RecorderHarness()
        h.recorder.healthProvider = { ["battery_phone": 0.8] }
        h.run(seconds: 130)
        try h.recorder.stop()
        let types = h.journal().compactMap { $0["j"] as? String }
        XCTAssertEqual(types.first, "session_open")
        XCTAssertEqual(types.last, "session_close")
        XCTAssertEqual(types.filter { $0 == "chunk_closed" }.count, 3)  // 2 rotations + the final one
        XCTAssertEqual(types.filter { $0 == "health" }.count, 2)
        XCTAssertEqual(h.entries("health").first?["battery_phone"] as? Double, 0.8)
    }

    func test_J2_manifestRebuiltFromJournalMatchesLiveOne() throws {
        let h = try RecorderHarness()
        h.run(seconds: 70)
        try h.recorder.stop()
        let live = try JSONSerialization.jsonObject(with: h.store.read("\(h.dir)/manifest.json")) as! [String: Any]
        let rebuilt = Manifest.build(from: h.journal())
        let roundTripped =
            try JSONSerialization.jsonObject(
                with: JSONSerialization.data(withJSONObject: rebuilt, options: [.sortedKeys])) as! [String: Any]
        XCTAssertEqual(NSDictionary(dictionary: live), NSDictionary(dictionary: roundTripped))
        XCTAssertEqual(live["chunks"] as? Int, 2)
        XCTAssertEqual(live["clean"] as? Bool, true)
    }

    func test_J3_randomCrashPointsLoseNothingThatWasSynced() throws {
        var rng = SystemRandomNumberGenerator()
        var h = try RecorderHarness()
        var checks = 0
        while checks < 1000 {
            if checks % 25 == 0 { h = try RecorderHarness() }  // keep each session short so the test stays fast
            h.run(seconds: Double.random(in: 0.05...3, using: &rng))
            // What is guaranteed: every sample whose bytes were synced before the crash.
            let syncedOnly = h.store.afterCrash()
            let mustSurvive = Set(h.indicesOnDisk(syncedOnly))
            let crashed = h.store.afterCrash { _, unsynced in Int.random(in: 0...unsynced, using: &rng) }
            let report = try SessionRecorder.recover(store: crashed, clock: h.clock, sessionID: h.recorder.sessionID)
            let recovered = h.indicesOnDisk(crashed)
            XCTAssertTrue(mustSurvive.isSubset(of: Set(recovered)), "lost synced data at check \(checks)")
            XCTAssertEqual(recovered, Array(0..<recovered.count), "no holes, no duplicates")
            XCTAssertTrue((try crashed.list("\(h.dir)/phone")).allSatisfy { !$0.hasSuffix(".open") })
            for path in report.recoveredChunks {
                let data = try crashed.read(path)
                XCTAssertTrue(data.isEmpty || data.last == 0x0A, "trimmed to the last full line")
            }
            checks += 1
        }
    }

    func test_J4_resumeContinuesSessionAsNewSegment() throws {
        let h = try RecorderHarness()
        h.run(seconds: 70)  // 1 closed + 1 open chunk
        let crashed = h.store.afterCrash()
        _ = try SessionRecorder.recover(store: crashed, clock: h.clock, sessionID: h.recorder.sessionID)
        XCTAssertEqual(SessionRecorder.unclosedSessions(store: crashed), [h.recorder.sessionID])
        let resumed = try SessionRecorder.resume(store: crashed, clock: h.clock, sessionID: h.recorder.sessionID)
        XCTAssertEqual(resumed.sessionID, h.recorder.sessionID)
        XCTAssertEqual(resumed.segment, 2)
        XCTAssertEqual(resumed.phone.nextNumber, 2, "chunk numbers continue")
        resumed.record(
            Data(#"{"type":"imu","device":"phone","first_index":0,"s":[]}"#.utf8), device: "phone", firstIndex: 0,
            count: 1)
        try resumed.stop()
        let entries = try Journal.read(store: crashed, path: "\(h.dir)/journal.jsonl").entries
        let lastChunk = entries.last { $0["j"] as? String == "chunk_closed" }
        XCTAssertEqual(lastChunk?["segment"] as? Int, 2)
        XCTAssertEqual(lastChunk?["file"] as? String, "\(h.dir)/phone/000002.jsonl")
        XCTAssertTrue(SessionRecorder.unclosedSessions(store: crashed).isEmpty)
    }

    func test_J4_closeInterruptedEndsSessionUncleanly() throws {
        let h = try RecorderHarness()
        h.run(seconds: 5)
        let crashed = h.store.afterCrash()
        _ = try SessionRecorder.recover(store: crashed, clock: h.clock, sessionID: h.recorder.sessionID)
        try SessionRecorder.closeInterrupted(store: crashed, clock: h.clock, sessionID: h.recorder.sessionID)
        let manifest = try JSONSerialization.jsonObject(with: crashed.read("\(h.dir)/manifest.json")) as! [String: Any]
        XCTAssertEqual(manifest["clean"] as? Bool, false)
    }

    func test_J5_tornLastJournalLineIsIgnoredWithWarning() throws {
        let h = try RecorderHarness()
        h.run(seconds: 65)
        try h.store.append(Data(#"{"j":"health","bat"#.utf8), to: "\(h.dir)/journal.jsonl")
        let (entries, warnings) = try Journal.read(store: h.store, path: "\(h.dir)/journal.jsonl")
        XCTAssertEqual(warnings.count, 1)
        XCTAssertEqual(entries.filter { $0["j"] as? String == "chunk_closed" }.count, 1, "earlier lines kept")
    }

    func test_J6_clockJumpStartsNewSegment() throws {
        let h = try RecorderHarness()
        h.run(seconds: 5)
        XCTAssertFalse(h.recorder.checkClock())
        h.clock.unixOffset += 3600  // wall clock changed (or the device rebooted)
        XCTAssertTrue(h.recorder.checkClock())
        XCTAssertEqual(h.recorder.segment, 2)
        let segment = try XCTUnwrap(h.entries("segment_open").first)
        XCTAssertEqual(segment["reason"] as? String, "clock_jump")
    }
}

final class QualityTests: XCTestCase {
    func test_S1_indexGapsDuplicatesAndBackwardsTimestampsAreCountedExactly() {
        var items: [(index: Int, t: Double)] = (0..<100).map { ($0, Double($0) / 50) }
        items.removeSubrange(40..<45)  // 5 missing
        items.append((10, 10.0 / 50))  // 1 duplicate
        items.append((10, 10.0 / 50))  // 2 duplicates
        items[60] = (items[60].index, items[59].t - 0.001)  // 1 backwards timestamp
        let stats = StreamStats(items: items)
        XCTAssertEqual(stats.samples, 95)
        XCTAssertEqual(stats.missingFromIndex, 5)
        XCTAssertEqual(stats.duplicates, 2)
        XCTAssertEqual(stats.backwardsTimestamps, 1)
        XCTAssertEqual(stats.deliveredHz, 50)
        XCTAssertEqual(stats.gapsOverThreshold, 1, "the 5 missing samples make one 120 ms gap")
    }

    /// The reference session's whole-session numbers from E03 (experiments/E03_stream_quality).
    func test_S2_replayMatchesE03Numbers() throws {
        let recording = try TestData.recording("20261008-153213-P01")
        let url = TestData.repoRoot.appendingPathComponent(
            "experiments/E03_stream_quality/results/20261008-153213-P01/metrics.json")
        let e03 = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
        let streams = e03["streams"] as! [String: [String: Any]]
        // E03's whole session runs Start → Stop on the phone clock; Watch times are mapped onto it.
        func eventTime(_ name: String) -> Double {
            recording.events.first { $0["name"] as? String == name }!["t_phone"] as! Double
        }
        let start = eventTime("start")
        let stop = eventTime("stop")
        func boot(_ device: String) -> Double {
            recording.packets.first { $0["type"] as? String == "imu" && $0["device"] as? String == device }![
                "boot_to_unix"] as! Double
        }
        for (loc, info) in streams {
            let device = info["device"] as! String
            let whole = info["whole_session"] as! [String: Any]
            let toPhone = device == "watch" ? boot("watch") - boot("phone") : 0
            var items: [(index: Int, t: Double)] = []
            for p in recording.packets where p["type"] as? String == "imu" && p["device"] as? String == device {
                let first = p["first_index"] as! Int
                for (k, s) in (p["s"] as! [[Double]]).enumerated() { items.append((first + k, s[0] + toPhone)) }
            }
            let stats = StreamStats(items: items, window: start...stop)
            XCTAssertEqual(stats.samples, whole["samples"] as? Int, loc)
            XCTAssertEqual(stats.missingFromIndex, whole["missing_from_index"] as? Int, loc)
            XCTAssertEqual(stats.duplicates, whole["duplicates"] as? Int, loc)
            XCTAssertEqual(stats.gapsOverThreshold, whole["gaps_over_100ms"] as? Int, loc)
            XCTAssertEqual(stats.longestGapMs, whole["longest_gap_ms"] as! Double, accuracy: 0.11, loc)
            XCTAssertEqual(stats.deliveredHz, whole["delivered_hz"] as! Double, accuracy: 0.011, loc)
            XCTAssertEqual(stats.expectedAtDeliveredRate, whole["expected_at_delivered_rate"] as? Int, loc)
            XCTAssertEqual(stats.coverage, whole["coverage"] as! Double, accuracy: 0.00011, loc)
        }
    }

    func test_S3_statusDotsFlipExactlyAtTheirThresholds() {
        let dots = StatusDots()
        XCTAssertEqual(dots.lastSampleAge(0.49), .green)
        XCTAssertEqual(dots.lastSampleAge(0.5), .yellow)
        XCTAssertEqual(dots.lastSampleAge(2.0), .yellow)
        XCTAssertEqual(dots.lastSampleAge(2.01), .red)
        XCTAssertEqual(dots.rateVsBaseline(0.91), .green)
        XCTAssertEqual(dots.rateVsBaseline(0.9), .yellow)
        XCTAssertEqual(dots.rateVsBaseline(0.7), .yellow)
        XCTAssertEqual(dots.rateVsBaseline(0.69), .red)
        XCTAssertEqual(dots.coverage(0.995), .green)
        XCTAssertEqual(dots.coverage(0.99), .yellow)
        XCTAssertEqual(dots.coverage(0.95), .yellow)
        XCTAssertEqual(dots.coverage(0.949), .red)
        XCTAssertEqual(dots.watchChunksPending(2), .green)
        XCTAssertEqual(dots.watchChunksPending(3), .yellow)
        XCTAssertEqual(dots.watchChunksPending(5), .yellow)
        XCTAssertEqual(dots.watchChunksPending(6), .red)
    }

    func test_highRateFormatRoundTripsAndTrimsTornRecords() {
        var data = HighRateFormat.header(["session": "s"])
        data += HighRateFormat.encode(.accel([1.5, 0.25, -1, 16]))
        data += HighRateFormat.encode(.motion(SyntheticMotionSource.moving()(2.0)))
        let whole = data.count
        data += HighRateFormat.encode(.accel([3, 0, 0, 0])).prefix(7)
        XCTAssertEqual(HighRateFormat.wholeRecordLength(data), whole)
        let (header, records) = HighRateFormat.decode(data)
        XCTAssertEqual(header["format"] as? String, "watch_hf")
        XCTAssertEqual(records.count, 2)
        XCTAssertEqual(records[0], .accel([1.5, 0.25, -1, 16]))
    }
}
