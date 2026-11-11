import XCTest

@testable import MotionStreamerCore

final class ModelTests: XCTestCase {
    private func sample(_ t: Double) -> MotionSample { [t] + Array(repeating: 0.5, count: 13) }

    func test_imuPacketsSplitIntoFiveSampleChunksWithIndices() throws {
        let samples = (0..<12).map { sample(Double($0)) }
        let packets = PacketEncoder.imuPackets(
            header: ["type": "imu", "device": "phone"], samples: samples, firstIndex: 100)
        XCTAssertEqual(packets.count, 3)
        let decoded = try packets.map { try XCTUnwrap(JSONSerialization.jsonObject(with: $0) as? [String: Any]) }
        XCTAssertEqual(decoded.map { $0["first_index"] as? Int }, [100, 105, 110])
        XCTAssertEqual((decoded[2]["s"] as? [[Double]])?.count, 2)
        XCTAssertEqual(decoded[0]["device"] as? String, "phone")
    }

    func test_recordingParsesPacketsAndDropsDuplicatesAndTornLines() {
        let lines = [
            #"{"type":"imu","device":"phone","loc":"left_pocket","first_index":0,"s":[[1,0,0,0,1,0,0,0,0,-1,0,0,0,0],[2,0,0,0,1,0,0,0,0,-1,0,0,0,0]]}"#,
            #"{"type":"imu","device":"phone","loc":"left_pocket","first_index":1,"s":[[2,0,0,0,1,0,0,0,0,-1,0,0,0,0]]}"#,
            #"{"type":"event","name":"start"}"#,
            #"{"type":"imu","device":"pho"#,
        ]
        let recording = Recording(jsonl: Data(lines.joined(separator: "\n").utf8))
        XCTAssertEqual(recording.sampleCount("phone"), 2)
        XCTAssertEqual(recording.events.count, 1)
        XCTAssertEqual(recording.streams["phone"]?.loc, "left_pocket")
    }

    func test_streamCounterCountsMissingAndLateBatches() {
        var counter = StreamCounter(start: 0)
        counter.add(samples: (0..<10).map { sample(Double($0) / 60) }, firstIndex: 0, now: 1)
        counter.add(samples: (20..<30).map { sample(Double($0) / 60) }, firstIndex: 20, now: 2)
        XCTAssertEqual(counter.missing, 10)
        counter.add(samples: (10..<20).map { sample(Double($0) / 60) }, firstIndex: 10, now: 3)
        XCTAssertEqual(counter.missing, 0, "a late batch fills its gap")
        XCTAssertEqual(counter.samples, 30)
        XCTAssertEqual(counter.nominalHz ?? 0, 60, accuracy: 0.5)
    }

    func test_memoryFileStoreKeepsOnlySyncedBytesAfterCrash() throws {
        let store = MemoryFileStore()
        try store.create("a")
        try store.append(Data("one\n".utf8), to: "a")
        try store.sync("a")
        try store.append(Data("two\n".utf8), to: "a")
        let crashed = store.afterCrash()
        XCTAssertEqual(try crashed.read("a"), Data("one\n".utf8))
        let partial = store.afterCrash { _, _ in 2 }
        XCTAssertEqual(try partial.read("a"), Data("one\ntw".utf8))
    }

    func test_localFileStoreRoundTrip() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: dir) }
        let store = LocalFileStore(root: dir)
        try store.createDirectory("s/phone")
        try store.create("s/phone/0.jsonl.open")
        try store.append(Data("x\n".utf8), to: "s/phone/0.jsonl.open")
        try store.sync("s/phone/0.jsonl.open")
        try store.rename("s/phone/0.jsonl.open", to: "s/phone/0.jsonl")
        XCTAssertEqual(try store.list("s/phone"), ["0.jsonl"])
        XCTAssertEqual(try store.read("s/phone/0.jsonl"), Data("x\n".utf8))
        try store.writeAtomically(Data("{}".utf8), to: "s/manifest.json")
        XCTAssertEqual(try store.size("s/manifest.json"), 2)
        XCTAssertGreaterThan(store.freeBytes, 0)
    }
}
