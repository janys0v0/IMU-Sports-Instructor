import XCTest

@testable import MotionStreamerCore

#if canImport(Darwin)
    import Darwin

    /// Resident memory of this process in MB.
    func residentMB() -> Double {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size) / 4
        let result = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count)
            }
        }
        return result == KERN_SUCCESS ? Double(info.resident_size) / 1_048_576 : 0
    }
#endif

/// Stage 9: endurance tests L1 and L3 (docs/plan/test-plan.md §2 L).
final class EnduranceTests: XCTestCase {
    /// L1: 60 and 120 minutes on a real disk: one chunk per minute, no open-file leak, flat memory.
    func test_L1_twoHoursOnDiskStayFlat() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("L1-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let store = LocalFileStore(root: dir)
        let clock = ManualClock()
        let recorder = try SessionRecorder.start(store: store, clock: clock, sessionID: "L1", metadata: [:])
        recorder.healthProvider = { ["battery_phone": 0.8] }
        var index = 0
        var memoryAt60 = 0.0
        let began = Date()
        for second in 1...(120 * 60) {
            // The app drains autorelease pools after every queue block; a test loop must do it itself.
            autoreleasepool {
                for _ in 0..<12 {
                    clock.advance(1.0 / 12)
                    let samples = (0..<5).map { k in SyntheticMotionSource.still(clock.uptime + Double(k) / 60) }
                    let packet = PacketEncoder.imuPackets(
                        header: ["type": "imu", "device": "phone", "loc": "right_pocket"], samples: samples,
                        firstIndex: index)[0]
                    recorder.record(packet, device: "phone", firstIndex: index, count: 5)
                    index += 5
                }
                recorder.tick()
            }
            if second == 60 * 60 {
                // 59 closed + the 60th still open (it closes with the next packet).
                XCTAssertEqual((try store.list("sessions/L1/phone")).count, 60)
                XCTAssertLessThanOrEqual(store.openHandleCount, 2, "journal + the open chunk")
                memoryAt60 = residentMB()
            }
        }
        try recorder.stop()
        XCTAssertEqual((try store.list("sessions/L1/phone")).filter { $0.hasSuffix(".jsonl") }.count, 120)
        XCTAssertLessThanOrEqual(store.openHandleCount, 1)
        XCTAssertLessThan(residentMB() - memoryAt60, 30, "memory flat between 60 and 120 min")
        let (entries, _) = try Journal.read(store: store, path: "sessions/L1/journal.jsonl")
        XCTAssertEqual(entries.filter { $0["j"] as? String == "chunk_closed" }.count, 120)
        XCTAssertEqual(entries.filter { $0["j"] as? String == "health" }.count, 120)
        print("L1: 120 min recorded in \(Int(Date().timeIntervalSince(began))) s, \(entries.count) journal lines")
    }

    /// L3: 120 random faults over a 60-min session: every fault is logged with its cause, and no
    /// sample is lost on disk except those a fault itself prevented.
    func test_L3_faultStormLosesNothingSilently() throws {
        var rng = SystemRandomNumberGenerator()
        let h = try RecorderHarness()
        let fileFaults = Set((0..<120).map { _ in Int.random(in: 10..<3590, using: &rng) })
        var injected = 0
        // Watchdog problems at random times alongside the file faults.
        let wd = WatchdogHarness()
        wd.clock.uptime = h.clock.uptime
        var episodes = 0
        var episodeEnds = 0
        for second in 0..<3600 {
            if fileFaults.contains(second) {
                if second % 2 == 0 {
                    h.store.failNextAppend = .diskFull
                } else {
                    h.store.failNextSync = .ioError("fsync")
                }
                injected += 1
            }
            h.run(seconds: 1)
            // A watchdog episode of 3-8 s every ~2 min: AirPods out, Low Power, heat in turn.
            let phase = second % 120
            let kind = (second / 120) % 3
            let inEpisode = phase >= 30 && phase < 30 + 3 + (second / 120) % 6
            if phase == 30 { episodes += 1 }
            wd.clock.uptime = h.clock.uptime
            var input = wd.input
            input.airpodsConnected = !(inEpisode && kind == 0)
            input.lowPower = inEpisode && kind == 1
            input.thermal = inEpisode && kind == 2 ? 2 : 0
            input.streams["airpods"]!.lastSampleAge = inEpisode && kind == 0 ? 5 : 0.05
            let (problems, _) = wd.watchdog.evaluate(input)
            let before = wd.events.filter { $0.0 == "alert_cleared" }.count
            wd.alerts.update(problems)
            episodeEnds += wd.events.filter { $0.0 == "alert_cleared" }.count - before
        }
        try h.recorder.stop()
        let writeErrors = h.entries("write_error").count
        XCTAssertEqual(writeErrors, injected, "every file fault is in the journal with its cause")
        XCTAssertEqual(h.errors.count, injected)
        let onDisk = h.indicesOnDisk()
        let lost = h.recorder.phone.lostRecords * 5
        XCTAssertEqual(onDisk.count + lost, h.nextIndex, "only samples a fault prevented are missing")
        XCTAssertEqual(Set(onDisk).count, onDisk.count, "no duplicates")
        XCTAssertEqual(episodeEnds, episodes, "every watchdog problem is logged and cleared")
        print("L3: \(injected) file faults, \(episodes) watchdog episodes, \(lost) samples lost")
    }
}
