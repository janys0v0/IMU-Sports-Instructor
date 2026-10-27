import XCTest

@testable import MotionStreamerCore

/// Found on device 2026-10-27 (session 20261027-141601-P01): the Watch was stopped 27 s in and
/// started again for the same session, wrote chunk 000000 again over the first one, and the phone
/// replaced its copy too, so the first 47 s of Watch data were lost.
final class WatchRestartTests: XCTestCase {
    func files(_ store: MemoryFileStore, _ dir: String) throws -> [String: Data] {
        var out: [String: Data] = [:]
        for name in (try? store.list(dir)) ?? [] { out[name] = try store.read("\(dir)/\(name)") }
        return out
    }

    func test_W12_restartingAStoppedSessionContinuesAsANewSegment() throws {
        let h = try TransferHarness()
        h.run(seconds: 70)
        try h.watch.stop()
        let dir = "\(SessionRecorder.sessionsDir)/\(h.session)"
        let before = try files(h.watchStore, "\(dir)/watch")
        XCTAssertEqual(before.count, 2)

        let again = try WatchRecorder.open(
            store: h.watchStore, clock: h.clock, link: h.watchLink, sessionID: h.session, metadata: [:])
        XCTAssertEqual(again.motion.segment, 2)
        for k in 0..<120 {
            h.clock.advance(1.0 / 6)
            let samples = (0..<10).map { j in SyntheticMotionSource.still(h.clock.uptime + Double(j) / 60) }
            for (j, p) in PacketEncoder.imuPackets(
                header: ["type": "imu", "device": "watch", "loc": "right_wrist"], samples: samples,
                firstIndex: 10 * k
            ).enumerated() {
                again.recordMotion(p, firstIndex: 10 * k + 5 * j, count: 5)
            }
        }
        try again.stop()

        let after = try files(h.watchStore, "\(dir)/watch")
        for (name, data) in before { XCTAssertEqual(after[name], data, "\(name) was overwritten") }
        XCTAssertEqual(Set(after.keys).subtracting(before.keys), ["000002.jsonl"])
        let (entries, _) = try Journal.read(store: h.watchStore, path: "\(dir)/journal.jsonl")
        let reopen = entries.last { $0["j"] as? String == "segment_open" }
        XCTAssertEqual(reopen?["reason"] as? String, "restarted")
        XCTAssertEqual(entries.filter { $0["j"] as? String == "session_open" }.count, 1)
    }

    func test_W12_openStartsANewSessionOrRecoversACrashedOne() throws {
        let h = try TransferHarness()
        h.run(seconds: 5)  // left open, as after a crash
        let recovered = try WatchRecorder.open(
            store: h.watchStore, clock: h.clock, link: h.watchLink, sessionID: h.session, metadata: [:])
        XCTAssertEqual(recovered.motion.segment, 2)
        let fresh = try WatchRecorder.open(
            store: h.watchStore, clock: h.clock, link: h.watchLink, sessionID: "20261027-150000-P01", metadata: [:])
        XCTAssertEqual(fresh.motion.segment, 1)
    }

    func test_W13_phoneKeepsBothWhenADifferentChunkArrivesUnderTheSameName() throws {
        let store = MemoryFileStore()
        let (_, phoneLink) = FakeWatchLink.pair()
        let inbox = TransferInbox(store: store, clock: ManualClock(), link: phoneLink)
        let session = "20261027-141601-P01"
        func meta(_ data: Data) -> [String: String] {
            [
                TransferKey.session: session, TransferKey.file: "watch/000000.jsonl",
                TransferKey.sha256: sha256Hex(data), TransferKey.kind: "60hz",
            ]
        }
        let first = Data("first run\n".utf8)
        let second = Data("second run\n".utf8)
        XCTAssertEqual(inbox.receive(first, metadata: meta(first)), .stored)
        XCTAssertEqual(inbox.receive(second, metadata: meta(second)), .stored)
        XCTAssertEqual(inbox.receive(second, metadata: meta(second)), .duplicate, "a resend is still a duplicate")

        let dir = "\(SessionRecorder.sessionsDir)/\(session)/watch"
        XCTAssertEqual(try store.read("\(dir)/000000.jsonl"), first, "the first copy is kept")
        let others = try store.list(dir).filter { $0 != "000000.jsonl" }
        XCTAssertEqual(others.count, 1)
        XCTAssertEqual(try store.read("\(dir)/\(others[0])"), second)
        let (entries, _) = try Journal.read(
            store: store, path: "\(SessionRecorder.sessionsDir)/\(session)/journal.jsonl")
        XCTAssertEqual(entries.filter { $0["j"] as? String == "chunk_name_clash" }.count, 1)
        let acks = phoneLink.sentMessages.compactMap(LinkMessage.decode).filter { $0.kind == .ack }
        XCTAssertTrue(acks.contains { $0.sha256 == sha256Hex(second) }, "the Watch gets its ack and stops resending")
    }
}
