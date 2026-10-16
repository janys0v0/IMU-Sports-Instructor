import XCTest

@testable import MotionStreamerCore

/// A simulated person who follows the spoken prompts, wearing phone, Watch and AirPods.
final class CalibrationHarness {
    let clock = ManualClock()
    let voice: RecordingVoice
    let speaker: Speaker
    let flow: CalibrationFlow
    var events: [(name: String, fields: [String: Any])] = []
    var result: CalibrationFlow.Result?

    // What the person does.
    var phoneGravityY = -1.0
    var movesDuringHold = 0  // number of standing holds in which they move
    var armsNeverLevel = false
    var armsLevelDelay = 0.0  // seconds after "raise both arms" before arms are level
    var watchSending = true
    var airpodsConnected = true

    private var holdsMoved = 0
    private var armsCommandAt: Double?

    init(outputs: [String] = ["airpods"]) {
        voice = RecordingVoice(clock: clock, secondsPerWord: 0.3)
        speaker = Speaker(clock: clock, outputs: [])
        var made: [Speaker.Output] = []
        for name in outputs { made.append(Speaker.Output(name: name, isAvailable: { true }, voice: voice)) }
        speaker.outputs = made
        var samplesRef: CalibrationFlow.SampleSource = { _, _, _ in [] }
        flow = CalibrationFlow(speaker: speaker, clock: clock, samples: { samplesRef($0, $1, $2) })
        samplesRef = { [unowned self] device, from, to in samples(device, from, to) }
        flow.landmark = "the net"
        flow.airpodsConnected = { [unowned self] in airpodsConnected }
        let log: (String, [String: Any]) -> Void = { [unowned self] name, fields in events.append((name, fields)) }
        flow.onEvent = log
        speaker.onEvent = log
        flow.onFinish = { [unowned self] in result = $0 }
    }

    var lastPrompt: String? { voice.texts.last }

    /// The person fidgets for 1.5 s at the start of each of their first `movesDuringHold` standing holds.
    /// A standing hold starts when "Hold still… now." follows the posture prompt, or after "You moved".
    private func isMoving(_ t: Double) -> Bool {
        let stand = VoiceScript.shared.calibration("C3")
        var standingStarts: [Double] = []
        for (i, p) in voice.phrases.enumerated() {
            guard let finish = p.finish, finish <= t else { continue }
            let previous = i > 0 ? voice.phrases[i - 1].text : ""
            if p.text == "You moved. Hold still." || (p.text == "Hold still… now." && previous == stand) {
                standingStarts.append(finish)
            }
        }
        guard let last = standingStarts.last, standingStarts.count <= movesDuringHold else { return false }
        return t - last <= 1.5
    }

    private func armsOut(_ t: Double) -> Bool {
        guard let i = voice.phrases.lastIndex(where: { $0.text.hasPrefix("Now raise") }) else { return false }
        if voice.phrases[i...].contains(where: { $0.text == "Arms down." }) { return false }
        if armsNeverLevel { return false }
        return t >= (voice.phrases[i].finish ?? .infinity) + armsLevelDelay
    }

    func samples(_ device: String, _ from: Double, _ to: Double) -> [MotionSample] {
        if device == "watch", !watchSending { return [] }
        if device == "airpods", !airpodsConnected { return [] }
        var out: [MotionSample] = []
        var t = (from * 50).rounded(.up) / 50
        while t <= to {
            let rot = isMoving(t) ? 1.0 : 0.01
            switch device {
            case "phone":
                out.append([
                    t, 0, 0, 0, 1, 0, 0, 0, 0, phoneGravityY, -(1 - phoneGravityY * phoneGravityY).squareRoot(), rot, 0,
                    0,
                ])
            case "watch":
                let g = armsOut(t) ? [0.0, 0, -1] : [-1.0, 0, 0]
                out.append([t, 0, 0, 0, 1, 0, 0, 0] + g + [rot, 0, 0])
            default: out.append([t, 0, 0, 0, 1, 0, 0, 0, 0, 0, -1, rot, 0, 0])
            }
            t += 0.02
        }
        return out
    }

    /// Runs until the flow finishes (or `seconds` pass).
    func run(seconds: Double = 200) {
        let end = clock.uptime + seconds
        while flow.isRunning, clock.uptime < end {
            clock.advance(0.1)
            flow.tick()
        }
    }

    func eventNames(_ name: String) -> [[String: Any]] { events.filter { $0.name == name }.map(\.fields) }
}

final class CalibrationTests: XCTestCase {
    let script = VoiceScript.shared

    func test_C2_V2_cleanRunSpeaksTheScriptInOrderAndTimesHoldsFromSpeech() throws {
        let h = CalibrationHarness()
        h.flow.start()
        h.run()
        let result = try XCTUnwrap(h.result)
        XCTAssertTrue(result.passed)
        let expected = ["C1", "C2", "C3", "C4", "C6", "C7", "C9", "C10", "C11"].map {
            VoiceScript.fill(script.calibration($0), ["landmark": "the net"])
        }
        XCTAssertEqual(h.voice.texts, expected)
        let now = try XCTUnwrap(h.voice.phrases.first { $0.text == "Hold still… now." }?.finish)
        XCTAssertEqual(result.standingWindow?.lowerBound ?? 0, now + 0.3, accuracy: 1e-9)
        let event = try XCTUnwrap(h.eventNames("calibrate").first)
        XCTAssertEqual(event["t_phone"] as! Double + 0.3, now + 0.3, accuracy: 1e-9)
        XCTAssertEqual(event["hold_s"] as? Double, 3.3)
        XCTAssertNotNil(h.eventNames("calibrate_arms").first)
        XCTAssertEqual(h.eventNames("calibrate_result").last?["result"] as? String, "pass")
    }

    func test_C3_movingOnceGetsOneWarningThenPasses() throws {
        let h = CalibrationHarness()
        h.movesDuringHold = 1
        h.flow.start()
        h.run()
        XCTAssertEqual(h.voice.texts.filter { $0 == "You moved. Hold still." }.count, 1)
        XCTAssertTrue(try XCTUnwrap(h.result).passed)
    }

    func test_C3_movingEveryTimeFailsAfterTwoRetries() throws {
        let h = CalibrationHarness()
        h.movesDuringHold = 99
        h.flow.start()
        h.run(seconds: 400)
        let result = try XCTUnwrap(h.result)
        XCTAssertFalse(result.passed)
        XCTAssertEqual(result.failure, .moved)
        XCTAssertEqual(h.voice.texts.filter { $0 == "Let's try again." }.count, 2)
        XCTAssertEqual(h.voice.texts.last, script.calibration("C12_final"))
    }

    func test_C4_armsNotLevelAfter6sGetsNudgeThenProceeds() throws {
        let h = CalibrationHarness()
        h.armsLevelDelay = 8
        h.flow.start()
        h.run()
        XCTAssertTrue(h.voice.texts.contains(script.calibration("C8")))
        XCTAssertTrue(try XCTUnwrap(h.result).passed)
    }

    func test_C5_eachFailureSpeaksItsReason() throws {
        let cases: [(CalibrationFlow.Failure, (CalibrationHarness) -> Void)] = [
            (.phoneNotUpright, { $0.phoneGravityY = -0.5 }),
            (.airpodsMissing, { $0.airpodsConnected = false }),
            (.watchSilent, { $0.watchSending = false }),
            (.armsNotLevel, { $0.armsNeverLevel = true }),
        ]
        for (failure, setUp) in cases {
            let h = CalibrationHarness()
            setUp(h)
            h.flow.start()
            h.run(seconds: 600)
            XCTAssertEqual(h.result?.failure, failure)
            let phrase = VoiceScript.fill(script.calibration("C12a"), ["reason": script.reason(failure.rawValue)])
            XCTAssertTrue(h.voice.texts.contains(phrase), "\(failure)")
        }
    }

    func test_driftSinceLastCalibrationIsReported() throws {
        let h = CalibrationHarness()
        h.flow.previousGravity = ["phone": [0, -1, 0.5]]
        h.flow.start()
        h.run()
        let drift = try XCTUnwrap(h.result?.driftDegrees["phone"])
        XCTAssertEqual(drift, 26.6, accuracy: 0.5)
    }

    func test_C6_C10_reminderFollowsTheIntervalSettingAndRepeats() {
        let clock = ManualClock()
        let reminder = CalibrationReminder(clock: clock, interval: 600)
        clock.advance(599)
        XCTAssertFalse(reminder.tick())
        clock.advance(1)
        XCTAssertTrue(reminder.tick())
        clock.advance(60)
        XCTAssertFalse(reminder.tick(), "not again before 2 min")
        clock.advance(60)
        XCTAssertTrue(reminder.tick(), "repeats every 2 min")
        reminder.calibrated()
        reminder.event("drift_check")  // T20's drift-check poses are not calibrations and don't trigger it
        XCTAssertFalse(reminder.tick())
        reminder.event("airpods_connected")
        XCTAssertTrue(reminder.tick(), "a reconnect makes it due at once")
        reminder.calibrated()
        reminder.interval = 300  // the setting
        clock.advance(300)
        XCTAssertTrue(reminder.tick())
    }
}

final class VoiceTests: XCTestCase {
    let script = VoiceScript.shared

    func test_V1_scriptLint() {
        let longestReason = script.section("reasons").values.compactMap { $0 as? String }
            .max { VoiceScript.wordCount($0) < VoiceScript.wordCount($1) }!
        let filler = ["landmark": "the far fence", "reason": longestReason, "trial": "twelve", "device": "The watch"]
        var phrases: [(String, String)] = []
        for id in ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12a", "C12b", "C12_final"] {
            let text = script.calibration(id)
            XCTAssertNotEqual(text, id, "\(id) missing")
            phrases.append((id, text))
        }
        phrases += script.section("reminder").compactMap { k, v in (v as? String).map { (k, $0) } }
        phrases.append(("audibility", script.audibility))
        for id in script.alertIDs {
            let alert = script.alert(id)!
            XCTAssertTrue(["red", "yellow", "redo", "ok"].contains(alert.level), id)
            phrases.append((id, alert.text))
        }
        for (id, text) in phrases {
            var filled = VoiceScript.fill(text, filler)
            if id == "redo_trial" { filled = VoiceScript.fill(text, ["trial": "twelve", "reason": ""]) }
            XCTAssertLessThanOrEqual(VoiceScript.wordCount(filled), 12, "\(id): \(filled)")
            XCTAssertFalse(filled.contains("{"), "\(id) has an unfilled placeholder")
            for banned in script.bannedWords {
                XCTAssertFalse(filled.lowercased().contains(banned.lowercased()), "\(id) uses \(banned)")
            }
        }
        for id in ["watch_stopped", "airpods_disconnected", "phone_dropped", "write_error", "redo_trial"] {
            XCTAssertNotNil(script.alert(id), "every 🔴 / redo alert has a phrase: \(id)")
        }
    }

    func test_V3_everyPromptIsLoggedWithStartAndFinish() throws {
        let h = CalibrationHarness()
        h.flow.start()
        h.run()
        let prompts = h.eventNames("prompt")
        XCTAssertEqual(prompts.count, h.voice.phrases.count)
        for (p, phrase) in zip(prompts, h.voice.phrases) {
            XCTAssertEqual(p["text"] as? String, phrase.text)
            XCTAssertEqual(p["start"] as? Double, phrase.start)
            XCTAssertEqual(p["finish"] as? Double, phrase.finish)
        }
    }

    func test_V4_redInterruptsCalibrationWhileWarningsWait() throws {
        let clock = ManualClock()
        let voice = RecordingVoice(clock: clock, finishesImmediately: false)
        let speaker = Speaker(clock: clock, outputs: [.init(name: "airpods", isAvailable: { true }, voice: voice)])
        var interrupted = false
        speaker.holdWarnings = true
        speaker.say("Calibration. Face the net and stand still.", id: "C1") { interrupted = $0 }
        speaker.say("Heads up: the phone is getting hot.", id: "phone_hot", priority: .warn)
        speaker.say("Stop. The AirPods disconnected.", id: "airpods_disconnected", priority: .red)
        XCTAssertTrue(interrupted, "🔴 cuts the calibration phrase off")
        XCTAssertEqual(voice.texts.last, "Stop. The AirPods disconnected.")
        voice.finishCurrent()
        XCTAssertEqual(voice.texts.count, 2, "🟡 waits while the calibration runs")
        speaker.holdWarnings = false
        XCTAssertEqual(voice.texts.last, "Heads up: the phone is getting hot.")
    }

    func test_V4_redAlertEndsARunningCalibration() throws {
        let h = CalibrationHarness()
        h.flow.start()
        h.clock.advance(0.1)
        h.flow.tick()
        // The flow is in its first hold; an alert arrives during the next phrase.
        h.run(seconds: 4)
        h.speaker.say("Stop. The watch stopped recording.", id: "watch_stopped", priority: .red)
        h.run()
        XCTAssertFalse(h.flow.isRunning)
    }

    func test_V5_outputFallsBackAndLogsWhenNoneIsAvailable() {
        let clock = ManualClock()
        let airpods = RecordingVoice(clock: clock)
        let watch = RecordingVoice(clock: clock)
        var airpodsIn = false
        var watchOn = true
        var events: [String] = []
        let speaker = Speaker(
            clock: clock,
            outputs: [
                .init(name: "airpods", isAvailable: { airpodsIn }, voice: airpods),
                .init(name: "watch", isAvailable: { watchOn }, voice: watch),
            ])
        speaker.onEvent = { name, _ in events.append(name) }
        speaker.say("Good.", id: "C6")
        XCTAssertEqual(watch.texts, ["Good."], "AirPods out → the Watch speaks")
        airpodsIn = true
        speaker.say("Good.", id: "C6")
        XCTAssertEqual(airpods.texts, ["Good."])
        airpodsIn = false
        watchOn = false
        let haptics = RecordingHaptics()
        speaker.haptics = haptics
        speaker.say("Stop. The phone can't save data.", id: "write_error", priority: .red)
        XCTAssertEqual(events.last, "voice_unavailable")
        XCTAssertEqual(haptics.played.last, .stop, "haptics still fire")
    }

    func test_V6_repeatReplaysTheLastPromptAndLogsIt() {
        let clock = ManualClock()
        let voice = RecordingVoice(clock: clock)
        let speaker = Speaker(clock: clock, outputs: [.init(name: "airpods", isAvailable: { true }, voice: voice)])
        var events: [String] = []
        speaker.onEvent = { name, _ in events.append(name) }
        speaker.say("Arms down.", id: "C10")
        speaker.repeatLast()
        XCTAssertEqual(voice.texts, ["Arms down.", "Arms down."])
        XCTAssertTrue(events.contains("voice_repeat"))
    }

    func test_V7_audioSessionKeepsAirPodsOutOfCallMode() {
        XCTAssertTrue(AudioSessionSpec.options.isDisjoint(with: AudioSessionSpec.forbiddenOptions))
        XCTAssertTrue(AudioSessionSpec.options.contains("allowBluetoothA2DP"))
        XCTAssertEqual(AudioSessionSpec.preferredInput, "builtInMic")
        XCTAssertEqual(AudioSessionSpec.mode, "spokenAudio")
    }

    func test_V8_audibilityCheck() {
        let clock = ManualClock()
        let voice = RecordingVoice(clock: clock)
        let speaker = Speaker(clock: clock, outputs: [.init(name: "airpods", isAvailable: { true }, voice: voice)])
        let check = AudibilityCheck(clock: clock)
        check.start(speaker: speaker)
        XCTAssertEqual(voice.texts, [VoiceScript.shared.audibility])
        clock.advance(9)
        XCTAssertEqual(check.tick(), .waiting)
        clock.advance(2)
        XCTAssertEqual(check.tick(), .notHeard, "no tap in 10 s")
        let again = AudibilityCheck(clock: clock)
        again.start(speaker: speaker)
        again.tapReceived()
        XCTAssertEqual(again.tick(), .heard)
    }

    /// C7 part 1: the on-phone hold summary of the reference calibration, for the Python comparison.
    func test_C7_exportReferenceCalibrationCheck() throws {
        guard let out = ProcessInfo.processInfo.environment["MSC_EXPORT_DIR"] else {
            throw XCTSkip("set MSC_EXPORT_DIR (tools/run_tests.sh does)")
        }
        let recording = try TestData.recording("20261008-153213-P01")
        let cal = try XCTUnwrap(recording.events.last { $0["name"] as? String == "calibrate" })
        let t0 = (cal["t_phone"] as! Double) + 0.3
        let t1 = (cal["t_phone"] as! Double) + (cal["hold_s"] as? Double ?? 3)
        let phone = (recording.streams["phone"]?.samples ?? []).map(\.sample).filter { $0[0] >= t0 && $0[0] <= t1 }
        let summary = try XCTUnwrap(CalibrationFlow.holdSummary(phone))
        let still = summary.rotRMS < CalibrationFlow.stillRMS
        let upright = abs(summary.gravity[1]) > CalibrationFlow.uprightMin
        let json: [String: Any] = [
            "window": [t0, t1], "rot_rms": summary.rotRMS, "gravity": summary.gravity,
            "attitude": summary.attitude, "passed": still && upright,
        ]
        try JSONSerialization.data(withJSONObject: json).write(
            to: URL(fileURLWithPath: out).appendingPathComponent("c7_phone_check.json"))
    }
}
