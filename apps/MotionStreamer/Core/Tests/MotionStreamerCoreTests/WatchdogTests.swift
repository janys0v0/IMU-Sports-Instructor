import XCTest

@testable import MotionStreamerCore

/// Runs the watchdog and alert center once a second on a fake clock with a scripted situation.
final class WatchdogHarness {
    let clock = ManualClock()
    let voice: RecordingVoice
    let speaker: Speaker
    let watchdog: Watchdog
    let alerts: AlertCenter
    var events: [(String, [String: Any])] = []
    var actions: [Watchdog.Action] = []
    var input = WatchdogInput()

    init() {
        voice = RecordingVoice(clock: clock, secondsPerWord: 0)
        speaker = Speaker(clock: clock, outputs: [])
        speaker.outputs = [.init(name: "airpods", isAvailable: { true }, voice: voice)]
        watchdog = Watchdog(clock: clock)
        alerts = AlertCenter(speaker: speaker, clock: clock)
        alerts.onEvent = { [unowned self] in events.append(($0, $1)) }
        let healthy = WatchdogInput.Stream(required: true, lastSampleAge: 0.05, rate5s: 50, baselineHz: 50)
        input.streams = ["phone": healthy, "watch": healthy, "airpods": healthy]
    }

    /// Advances `seconds`, evaluating once a second; `change` adjusts the situation at each step.
    func run(_ seconds: Int, _ change: ((inout WatchdogInput, Int) -> Void)? = nil) {
        for k in 0..<seconds {
            clock.advance(1)
            change?(&input, k)
            let (problems, a) = watchdog.evaluate(input)
            actions += a
            alerts.update(problems)
        }
    }

    var spoken: [String] { voice.texts }
    func said(_ id: String) -> Bool { spoken.contains(VoiceScript.shared.alert(id)!.text) }
    func firstSpokenTime(_ id: String) -> Double? {
        voice.phrases.first { $0.text == VoiceScript.shared.alert(id)!.text }?.start
    }
}

final class WatchdogTests: XCTestCase {
    func test_A1_airpodsDisconnectSpokenWithin3sAndRecoveryAfterReconnect() {
        let h = WatchdogHarness()
        h.run(5)
        let start = h.clock.uptime
        h.run(10) { input, _ in
            input.airpodsConnected = false
            input.streams["airpods"]!.lastSampleAge = 5
        }
        let t = try! XCTUnwrap(h.firstSpokenTime("airpods_disconnected"))
        XCTAssertLessThanOrEqual(t - start, 3)
        h.run(2) { input, _ in  // reconnected
            input.airpodsConnected = true
            input.streams["airpods"]!.lastSampleAge = 0.05
        }
        XCTAssertEqual(h.spoken.last, VoiceScript.shared.alert("airpods_back")!.text)
        let reminder = CalibrationReminder(clock: h.clock)
        reminder.event("airpods_connected")
        XCTAssertTrue(reminder.tick(), "the reconnect asks for a recalibration")
    }

    func test_A1_oneSecondWithoutSamplesAlsoCounts() {
        let h = WatchdogHarness()
        h.run(5) { input, _ in input.streams["airpods"]!.lastSampleAge = 1.5 }
        XCTAssertTrue(h.said("airpods_disconnected"))
    }

    func test_A2_routeSwitchedAwayIsRedWithin3s() {
        let h = WatchdogHarness()
        h.run(3) { input, _ in
            input.airpodsRouteAway = true
            input.streams["airpods"]!.lastSampleAge = 3
        }
        XCTAssertTrue(h.said("airpods_switched"))
        XCTAssertFalse(h.said("airpods_disconnected"))
    }

    func test_A3_silentWatchLinkIsOnlyAWarning() {
        let h = WatchdogHarness()
        h.run(20) { input, _ in input.watchBatchAge = 5 }
        XCTAssertTrue(h.said("watch_preview_paused"))
        XCTAssertEqual(h.events.filter { $0.0 == "alert" && ($0.1["level"] as? String) == "red" }.count, 0)
    }

    func test_A4_lowRateWarnsThenEscalatesAt30sWithCause() {
        let h = WatchdogHarness()
        h.run(40) { input, _ in
            input.streams["phone"]!.rate5s = 35
            input.thermal = 2
        }
        XCTAssertTrue(h.said("rate_dropping"))
        XCTAssertTrue(h.said("low_rate"))
        let warned = h.firstSpokenTime("rate_dropping")!
        let red = h.firstSpokenTime("low_rate")!
        XCTAssertEqual(red - warned, 28, accuracy: 1.01, "🟡 at 2 s, 🔴 at 30 s")
        let detail = h.events.first { ($0.1["id"] as? String) == "rate_dropping" }?.1["detail"] as? String
        XCTAssertTrue(detail?.contains("heat") == true, "the cause is shown")
        XCTAssertTrue(h.actions.contains(.shedLoad))
    }

    func test_A5_lowPowerBlocksStartAndIsRedMidSession() {
        var i = GoNoGo.Input()
        i.liveRates = ["phone": (33, 33), "watch": (60, 60), "airpods": (50, 50)]
        i.landmark = "the net"
        i.lowPowerPhone = true
        XCTAssertFalse(GoNoGo(i).canStart)
        XCTAssertEqual(GoNoGo(i).failures.map(\.id), ["low_power"])
        let h = WatchdogHarness()
        h.run(3) { input, _ in input.lowPower = true }
        XCTAssertTrue(h.said("low_power"))
    }

    func test_A6_heatWarnsAndPausesPlots() {
        let h = WatchdogHarness()
        h.run(3) { input, _ in input.thermal = 2 }
        XCTAssertTrue(h.said("phone_hot"))
        XCTAssertTrue(h.actions.contains(.shedLoad))
    }

    func test_A7_frozenSensorIsRestartedThenRedIfStillFrozen() {
        let h = WatchdogHarness()
        let frozen = (0..<300).map { k -> MotionSample in [Double(k) / 50, 0, 0, 0, 1, 0.1, 0, 0, 0, -1, 0, 0.01, 0, 0]
        }
        let moving = (0..<300).map { k in SyntheticMotionSource.moving(rads: 2)(Double(k) / 50) }
        h.run(8) { input, _ in
            input.streams["airpods"]!.recent = frozen
            input.streams["phone"]!.recent = moving
        }
        XCTAssertEqual(h.actions.filter { $0 == .restartUpdates("airpods") }.count, 1, "one restart first")
        XCTAssertTrue(h.said("frozen_sensor"), "still frozen after the restart")
    }

    func test_A8_droppedPhoneIsDetected() {
        let d = PhoneDropDetector()
        var t = 0.0
        func add(_ s: MotionSample) {
            d.add(s, watchMoving: true)
            t += 0.02
        }
        for _ in 0..<50 { add([t, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0.5, 0, 0]) }  // walking, upright
        for _ in 0..<15 { add([t, 0, 0, 0, 1, 0, 1, 0, 0, -1, 0, 3, 2, 1]) }  // free fall: total ≈ 0 g
        add([t, 0, 0, 0, 1, 0, 4, 0, 0, -1, 0, 5, 5, 5])  // impact
        for _ in 0..<300 { add([t, 0, 0, 0, 1, 0, 0, 0, 0, 0, -1, 0.01, 0, 0]) }  // flat on the grass
        XCTAssertTrue(d.dropped)
    }

    func test_A8_noFalseAlarmDuringReferenceJumpingJacks() throws {
        let recording = try TestData.recording("20261008-153213-P01")
        let d = PhoneDropDetector()
        for item in recording.streams["phone"]!.samples { d.add(item.sample, watchMoving: true) }
        XCTAssertFalse(d.dropped)
    }

    func test_A9_batteryWarnsAt20AndIsRedAt10() {
        let h = WatchdogHarness()
        h.run(3) { input, _ in input.batteryWatch = 0.19 }
        XCTAssertTrue(h.said("battery_low"))
        XCTAssertFalse(h.said("battery_critical"))
        h.run(3) { input, _ in input.batteryWatch = 0.09 }
        XCTAssertTrue(h.said("battery_critical"))
    }

    func test_A10_debounceGapAndEscalation() {
        let h = WatchdogHarness()
        h.run(1) { input, _ in input.thermal = 2 }  // 1 s blip
        h.run(3) { input, _ in input.thermal = 0 }
        XCTAssertFalse(h.said("phone_hot"), "problems under 2 s never alert")
        h.run(3) { input, _ in input.thermal = 2 }
        h.run(1) { input, _ in input.thermal = 0 }
        h.run(3) { input, _ in input.thermal = 2 }
        XCTAssertEqual(
            h.spoken.filter { $0 == VoiceScript.shared.alert("phone_hot")!.text }.count, 1, "at most once a minute")
        h.run(40) { input, _ in input.thermal = 2 }
        let red = h.events.filter { ($0.1["level"] as? String) == "red" }
        XCTAssertFalse(red.isEmpty, "a 🟡 lasting 30 s becomes 🔴")
    }

    func test_redRepeatsEvery30sUntilAcknowledged() {
        let h = WatchdogHarness()
        h.run(65) { input, _ in input.lowPower = true }
        let count = h.spoken.filter { $0 == VoiceScript.shared.alert("low_power")!.text }.count
        XCTAssertEqual(count, 3, "at 2 s, 32 s and 62 s")
        h.alerts.acknowledge()
        h.run(40) { input, _ in input.lowPower = true }
        XCTAssertEqual(h.spoken.filter { $0 == VoiceScript.shared.alert("low_power")!.text }.count, 3)
    }

    func test_A11_trialWithFiveSecondAirPodsGapIsRedone() {
        func items(_ rate: Double, gap: ClosedRange<Double>? = nil) -> [(index: Int, t: Double)] {
            (0..<Int(70 * rate)).compactMap { k in
                let t = 100 + Double(k) / rate
                return gap?.contains(t) == true ? nil : (k, t)
            }
        }
        var input = TrialCheck.Input(
            trial: 4, start: 105, end: 160,
            items: ["phone": items(33), "watch": items(60), "airpods": items(50, gap: 120...125)],
            requiredDevices: ["phone", "watch", "airpods"], syncGestureDetected: true)
        input.baselineHz = ["phone": 33, "watch": 60, "airpods": 50]
        input.lastGoodCalibration = 90
        let check = TrialCheck(input)
        XCTAssertFalse(check.keep)
        XCTAssertEqual(check.spoken, "Redo trial 4. The AirPods were missing for 5 seconds.")
        input.items["airpods"] = items(50)
        XCTAssertTrue(TrialCheck(input).keep)
    }

    func test_A11_checkRunAsTheTrialEndsDoesNotSeeAFalseGap() {
        let items = (0..<3300).map { k in (index: k, t: 100 + Double(k) / 33) }  // data up to 200 s
        var input = TrialCheck.Input(
            trial: 1, start: 110, end: 200, items: ["phone": items], requiredDevices: ["phone"],
            syncGestureDetected: true)
        input.lastGoodCalibration = 105
        input.dataUntil = 200
        XCTAssertTrue(TrialCheck(input).keep, "no gap from the 2 s padding that hasn't happened yet")
        input.dataUntil = nil
        XCTAssertFalse(TrialCheck(input).keep)
    }

    func test_A12_courtExitCheck() {
        let trials = [(number: 1, keep: true), (number: 2, keep: false), (number: 3, keep: true)]
        XCTAssertEqual(
            CourtExitCheck(trials: trials, watchSummary: (60, 60, true), chunks60HzOnPhone: 60).verdict,
            .redo(trials: [2]))
        let kept = [(number: 1, keep: true)]
        XCTAssertEqual(
            CourtExitCheck(trials: kept, watchSummary: (60, 60, true), chunks60HzOnPhone: 58).verdict,
            .waiting("2 Watch chunks still on their way"))
        XCTAssertEqual(CourtExitCheck(trials: kept, watchSummary: (60, 60, true), chunks60HzOnPhone: 60).verdict, .safe)
    }

    func test_A13_highRateStillOnWatchIsSafeOnlyWhenClosed() {
        let kept = [(number: 1, keep: true)]
        XCTAssertEqual(
            CourtExitCheck(trials: kept, watchSummary: (60, 60, true), chunks60HzOnPhone: 60).verdict, .safe,
            "high-rate chunks may still be on the Watch: closed is enough")
        XCTAssertEqual(
            CourtExitCheck(trials: kept, watchSummary: (60, 60, false), chunks60HzOnPhone: 60).verdict,
            .waiting("a high-rate chunk is still open on the Watch"))
        XCTAssertEqual(
            CourtExitCheck(trials: kept, watchSummary: nil, chunks60HzOnPhone: 60).verdict,
            .waiting("waiting for the Watch to finish"))
    }

    func test_goNoGoBlocksMissingDevicesAndShortBattery() {
        var i = GoNoGo.Input()
        i.liveRates = ["phone": (33, 33), "watch": (60, 60)]
        i.landmark = "the net"
        i.batteryWatch = 0.3
        i.plannedMinutes = 60
        let g = GoNoGo(i)
        XCTAssertEqual(Set(g.failures.map(\.id)), ["airpods_live", "watch_battery"])
        i.requiredDevices = ["phone", "watch"]  // "Record without AirPods" override
        i.batteryWatch = 0.9
        XCTAssertTrue(GoNoGo(i).canStart)
    }

    func test_syncGestureDetection() {
        var s: [MotionSample] = []
        for k in 0..<250 {
            let t = Double(k) / 50
            let hop = [1.0, 1.7, 2.4].contains { abs(t - $0) < 0.05 }
            s.append([t, 0, 0, 0, 1, 0, hop ? 2 : 0, 0, 0, -1, 0, 0, 0, 0])
        }
        XCTAssertTrue(SyncGesture.detected(s, from: 0, to: 5))
        XCTAssertFalse(SyncGesture.detected(s, from: 2, to: 5), "only one hop left")
    }
}

/// Stage 7 demo: the reference recording replayed second by second with the AirPods disconnected
/// from 20 s to 28 s after Start. "Stop. The AirPods disconnected." comes within 3 s, and
/// "The AirPods are back." after they reconnect.
final class WatchdogDemoTests: XCTestCase {
    func test_demo_replayedSessionWithScriptedAirPodsDisconnect() throws {
        let recording = try TestData.recording("20261008-153213-P01")
        let start = try XCTUnwrap(recording.events.first { $0["name"] as? String == "start" }?["t_phone"] as? Double)
        let airpodsTimes = (recording.streams["airpods"]?.samples ?? []).map { $0.sample[0] }
        let phoneTimes = (recording.streams["phone"]?.samples ?? []).map { $0.sample[0] }
        let h = WatchdogHarness()
        h.clock.uptime = start
        let gap = (start + 20)...(start + 28)
        var spokenAt: [String: Double] = [:]
        for second in 1...60 {
            h.clock.uptime = start + Double(second)
            let now = h.clock.uptime
            func age(_ times: [Double], skipping: ClosedRange<Double>? = nil) -> Double? {
                times.last { $0 <= now && !(skipping?.contains($0) ?? false) }.map { now - $0 }
            }
            h.input.airpodsConnected = !gap.contains(now)
            h.input.streams["airpods"]!.lastSampleAge = age(airpodsTimes, skipping: gap)
            h.input.streams["phone"]!.lastSampleAge = age(phoneTimes)
            h.input.streams["watch"]!.lastSampleAge = 0.1
            let (problems, _) = h.watchdog.evaluate(h.input)
            h.alerts.update(problems)
            for p in h.voice.phrases where spokenAt[p.text] == nil { spokenAt[p.text] = p.start - start }
        }
        let stopped = try XCTUnwrap(spokenAt["Stop. The AirPods disconnected."])
        XCTAssertLessThanOrEqual(stopped - 20, 3)
        let back = try XCTUnwrap(spokenAt["The AirPods are back."])
        XCTAssertGreaterThan(back, 28)
        XCTAssertLessThanOrEqual(back - 28, 2)
        print("demo: disconnected spoken at \(stopped) s, back at \(back) s after Start")
    }
}
