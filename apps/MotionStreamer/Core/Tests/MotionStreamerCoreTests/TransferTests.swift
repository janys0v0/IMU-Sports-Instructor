import XCTest

@testable import MotionStreamerCore

/// A Watch and a phone joined by a fake link, each with its own disk.
final class TransferHarness {
    let clock = ManualClock()
    let watchStore = MemoryFileStore()
    let phoneStore = MemoryFileStore()
    let watchLink: FakeWatchLink
    let phoneLink: FakeWatchLink
    let watch: WatchRecorder
    let inbox: TransferInbox
    let supervisor: WatchSupervisor
    var index = 0
    var dropAcks = false
    let session = "20261020-120000-P01"

    init() throws {
        (watchLink, phoneLink) = FakeWatchLink.pair()
        watch = try WatchRecorder.start(
            store: watchStore, clock: clock, link: watchLink, sessionID: session, metadata: [:])
        inbox = TransferInbox(store: phoneStore, clock: clock, link: phoneLink)
        supervisor = WatchSupervisor(clock: clock)
        phoneLink.onFile = { [unowned self] data, meta in inbox.receive(data, metadata: meta) }
        phoneLink.onMessage = { [unowned self] data in
            if let m = LinkMessage.decode(data) {
                inbox.handle(m)
                supervisor.handle(m)
            } else {
                supervisor.batchReceived()
            }
        }
        watchLink.onMessage = { [unowned self] data in
            guard !dropAcks, let m = LinkMessage.decode(data) else { return }
            watch.outbox.handle(m)
        }
    }

    /// Records Watch motion for `seconds` (60 Hz, 10-sample packets), delivering transfers each second.
    func run(seconds: Int, deliver: Bool = true, highRate: Bool = false) {
        for _ in 0..<seconds {
            for _ in 0..<6 {
                clock.advance(1.0 / 6)
                let samples = (0..<10).map { k in SyntheticMotionSource.still(clock.uptime + Double(k) / 60) }
                let packet = PacketEncoder.imuPackets(
                    header: ["type": "imu", "device": "watch", "loc": "right_wrist"], samples: samples,
                    firstIndex: index)
                for (k, p) in packet.enumerated() { watch.recordMotion(p, firstIndex: index + 5 * k, count: 5) }
                index += 10
                watchLink.sendMessage(Data("{}".utf8))  // the live preview batch
            }
            if highRate { watch.recordHighRate(Self.highRateSecond(clock.uptime)) }
            watch.tick()
            if deliver { watchLink.deliver() }
        }
    }

    /// One second of synthetic high-rate data: 800 accel + 200 motion records.
    static func highRateSecond(_ end: Double) -> [HighRateFormat.Record] {
        let start = end - 1
        var records: [HighRateFormat.Record] = []
        records.reserveCapacity(1000)
        for k in 0..<800 { records.append(.accel([start + Double(k) / 800, 0.5, -1, 0.25])) }
        for k in 0..<200 { records.append(.motion(SyntheticMotionSource.still(start + Double(k) / 200))) }
        return records
    }

    /// After Stop: keep delivering and resending until everything is acked (or give up).
    func drain(maxSeconds: Int = 600) {
        for _ in 0..<maxSeconds {
            watchLink.deliver()
            if watch.outbox.unacked.isEmpty { return }
            clock.advance(1)
            watch.outbox.tick()
        }
    }

    func watchIndices() -> [Int] {
        ((try? watchStore.list("\(watch.directory)/watch")) ?? []).flatMap { name in
            Recording(jsonl: (try? watchStore.read("\(watch.directory)/watch/\(name)")) ?? Data())
                .streams["watch"]?.samples.map(\.index) ?? []
        }
    }

    func phoneJournal(_ type: String) -> [[String: Any]] {
        let path = "\(SessionRecorder.sessionsDir)/\(session)/journal.jsonl"
        return ((try? Journal.read(store: phoneStore, path: path).entries) ?? []).filter { $0["j"] as? String == type }
    }
}

final class TransferTests: XCTestCase {
    func test_W1_watchKeepsEverythingWhilePhoneIsUnreachable() throws {
        let h = try TransferHarness()
        h.phoneLink.isReachable = false
        h.run(seconds: 600)
        XCTAssertEqual(h.watchIndices(), Array(0..<h.index), "all Watch data on the Watch disk")
        XCTAssertEqual(h.inbox.count(session: h.session, kind: "60hz"), 0)
        h.phoneLink.isReachable = true
        h.drain()
        XCTAssertEqual(h.inbox.count(session: h.session, kind: "60hz"), 9, "the 9 chunks closed so far arrive")
    }

    func test_W2_flakyTransferEndsWithEveryChunkExactlyOnce() throws {
        let h = try TransferHarness()
        var rng = SystemRandomNumberGenerator()
        h.watchLink.random = { Double.random(in: 0..<1, using: &rng) }
        h.watchLink.dropFiles = 0.2
        h.watchLink.duplicateFiles = 0.2
        h.watchLink.reorderFiles = true
        h.run(seconds: 3600)
        try h.watch.stop()
        h.drain()
        XCTAssertEqual(h.watch.outbox.count(kind: "60hz"), 60)
        let progress = h.inbox.progress(session: h.session, kind: "60hz")
        XCTAssertEqual(progress.received, 60)
        XCTAssertEqual(progress.total, 60, "Watch: 60 / 60 chunks")
        let received = h.phoneJournal("chunk_received").filter { $0["kind"] as? String == "60hz" }
        XCTAssertEqual(received.count, 60, "each chunk stored and journalled once")
        for e in received {
            XCTAssertEqual(sha256Hex(try h.phoneStore.read(e["file"] as! String)), e["sha256"] as? String)
        }
    }

    func test_W3_damagedChunkIsRejectedAndSentAgain() throws {
        let h = try TransferHarness()
        h.watchLink.corruptNextFiles = 1
        h.run(seconds: 61)
        XCTAssertEqual(h.phoneJournal("chunk_rejected").count, 1)
        h.drain()
        XCTAssertEqual(h.inbox.count(session: h.session, kind: "60hz"), 1)
        XCTAssertEqual(h.phoneJournal("chunk_received").count, 1)
    }

    func test_W4_lostAckLeadsToResendThatPhoneTreatsAsDuplicate() throws {
        let h = try TransferHarness()
        h.dropAcks = true
        h.run(seconds: 61)
        XCTAssertEqual(h.watch.outbox.unacked.count, 1)
        h.dropAcks = false
        h.clock.advance(31)
        h.watch.outbox.tick()
        h.watchLink.deliver()
        XCTAssertTrue(h.watch.outbox.unacked.isEmpty)
        XCTAssertEqual(h.phoneJournal("chunk_received").count, 1, "the duplicate isn't stored twice")
    }

    func test_W5_watchNeverDeletesBeforeMacVerification() throws {
        let h = try TransferHarness()
        h.run(seconds: 130)
        try h.watch.stop()
        h.drain()
        XCTAssertTrue(h.watch.outbox.unacked.isEmpty)
        XCTAssertEqual((try h.watchStore.list("\(h.watch.directory)/watch")).count, 3, "files remain after acks")
        XCTAssertEqual(try TransferOutbox.clearVerified(store: h.watchStore, verified: ["other"]), [])
        XCTAssertEqual(try TransferOutbox.clearVerified(store: h.watchStore, verified: [h.session]), [h.session])
        XCTAssertTrue((try h.watchStore.list("\(h.watch.directory)/watch")).isEmpty)
    }

    func test_W6_resendSessionIsHarmless() throws {
        let h = try TransferHarness()
        h.run(seconds: 130)
        try h.watch.stop()
        h.drain()
        let before = h.phoneJournal("chunk_received").count
        let sent = h.watchLink.filesSent
        h.watch.outbox.resendAll()
        h.watchLink.deliver()
        XCTAssertEqual(h.watchLink.filesSent, sent + h.watch.outbox.items.count)
        XCTAssertEqual(h.phoneJournal("chunk_received").count, before)
    }

    func test_W7_workoutEndedMakesPhoneRelaunchWatch() throws {
        let h = try TransferHarness()
        var relaunched = 0
        var alerts: [String] = []
        var events: [String] = []
        h.supervisor.onRelaunch = { relaunched += 1 }
        h.supervisor.onAlert = { alerts.append($0) }
        h.supervisor.onEvent = { name, _ in events.append(name) }
        h.run(seconds: 5)
        h.watch.workoutEnded("crown pressed")
        XCTAssertEqual(relaunched, 1)
        XCTAssertEqual(alerts, ["watch_stopped"])
        XCTAssertEqual(events, ["watch_workout_ended"])
        // Silence while reachable (no message at all) is also caught.
        h.clock.advance(40)
        h.supervisor.tick(watchReachable: true)
        XCTAssertEqual(relaunched, 2)
    }

    func test_W8_highRateSixtyMinutesHeldUntilStop() throws {
        let h = try TransferHarness()
        h.run(seconds: 3600, deliver: false, highRate: true)
        let hf = (try h.watchStore.list("\(h.watch.directory)/watch_hf")).filter { $0.hasSuffix(".bin") }
        XCTAssertEqual(hf.count, 59)
        XCTAssertTrue(
            h.watch.outbox.items.values.filter { $0.kind == "hf" }.allSatisfy { $0.lastSent == nil },
            "not sent during play")
        try h.watch.stop()
        XCTAssertEqual(h.watch.outbox.count(kind: "hf"), 60)
        XCTAssertTrue(h.watch.outbox.items.values.filter { $0.kind == "hf" }.allSatisfy { $0.lastSent != nil })
        var total = 0
        var expectedFirst = 0
        for name in try h.watchStore.list("\(h.watch.directory)/watch_hf") {
            let data = try h.watchStore.read("\(h.watch.directory)/watch_hf/\(name)")
            total += data.count
            let (header, records) = HighRateFormat.decode(data)
            let first = (header["first_index"] as? [String: Int])?["accel"]
            XCTAssertEqual(first, expectedFirst, "indices continue across chunks")
            expectedFirst += records.filter { if case .accel = $0 { return true } else { return false } }.count
        }
        XCTAssertEqual(expectedFirst, 800 * 3600)
        XCTAssertEqual(Double(total) / 1e6, 101, accuracy: 6, "about 100 MB per hour")
    }

    func test_W9_highRateFailureAlertsAndKeeps60HzRunning() throws {
        let h = try TransferHarness()
        var alerts: [String] = []
        var watchSide: [String] = []
        h.supervisor.onAlert = { alerts.append($0) }
        h.watch.onHighRateFailed = { watchSide.append($0) }
        h.run(seconds: 10, highRate: true)
        h.watch.highRateFailed("CMBatchedSensorManager stopped")
        h.run(seconds: 70)
        XCTAssertEqual(alerts, ["high_rate_failed"])
        XCTAssertEqual(watchSide.count, 1)
        XCTAssertEqual(h.watchIndices(), Array(0..<h.index), "60 Hz unaffected")
    }

    func test_W10_tornBinaryChunkIsTrimmedToWholeRecords() throws {
        var rng = SystemRandomNumberGenerator()
        for _ in 0..<200 {
            let h = try TransferHarness()
            h.run(seconds: Int.random(in: 1...20, using: &rng), deliver: false, highRate: true)
            let crashed = h.watchStore.afterCrash { _, unsynced in Int.random(in: 0...unsynced, using: &rng) }
            _ = try SessionRecorder.recover(store: crashed, clock: h.clock, sessionID: h.session)
            for name in try crashed.list("\(h.watch.directory)/watch_hf") {
                XCTAssertFalse(name.hasSuffix(".open"))
                let data = try crashed.read("\(h.watch.directory)/watch_hf/\(name)")
                XCTAssertEqual(HighRateFormat.wholeRecordLength(data), data.count, "only whole records remain")
            }
        }
    }

    /// W10 part 2: a high-rate chunk with known values for the Python loader to read back exactly.
    func test_W10_exportHighRateChunkForPython() throws {
        guard let out = ProcessInfo.processInfo.environment["MSC_EXPORT_DIR"] else {
            throw XCTSkip("set MSC_EXPORT_DIR (tools/run_tests.sh does)")
        }
        var data = HighRateFormat.header(["session": "export", "first_index": ["accel": 7, "motion": 3]])
        for k in 0..<5 { data += HighRateFormat.encode(.accel([100 + Double(k) / 800, 0.5, -1.25, Double(k)])) }
        data += HighRateFormat.encode(.motion([200.5] + (1...13).map { Double($0) / 4 }))
        let url = URL(fileURLWithPath: out).appendingPathComponent("watch_hf_sample.bin")
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: url)
    }
}
