import XCTest

@testable import MotionStreamerCore

/// One control system for both devices: the iPhone owns the session, both screens show the same
/// buttons from the state it broadcasts.
final class SessionControlTests: XCTestCase {
    func test_idleShowsOnlyStart() {
        XCTAssertEqual(ControlState().buttons, [.start])
    }

    func test_recordingShowsTheSessionButtons() {
        var s = ControlState()
        s.phase = .recording
        XCTAssertEqual(s.buttons, [.trial, .calibrate, .repeatPrompt, .acknowledge, .stop])
        XCTAssertEqual(s.label(.trial), "Trial")
        s.openTrial = 2
        XCTAssertEqual(s.label(.trial), "End trial 2")
    }

    func test_calibratingHidesTrialAndCalibrate() {
        var s = ControlState()
        s.phase = .recording
        s.calibrating = true
        XCTAssertEqual(s.buttons, [.repeatPrompt, .acknowledge, .stop])
    }

    func test_noButtonsWhileStartingOrStopping() {
        for phase in [ControlState.Phase.starting, .stopping] {
            var s = ControlState()
            s.phase = phase
            XCTAssertEqual(s.buttons, [])
        }
    }

    func test_stateRoundTripsThroughAWatchMessage() throws {
        var s = ControlState()
        s.phase = .recording
        s.sessionID = "20261017-170818-P01"
        s.openTrial = 3
        s.trialsKept = 2
        s.trialsRedo = 1
        s.alert = "AirPods disconnected"
        s.message = "Trial 3 started"
        s.sentUnix = 1_792_271_298
        let decoded = try XCTUnwrap(ControlState(message: s.wcMessage()))
        XCTAssertEqual(decoded, s)
        XCTAssertNil(ControlState(message: ["cmd": "start"]))
    }

    func test_commandsParseFromTheWireNames() {
        XCTAssertEqual(SessionCommand(rawValue: "repeat"), .repeatPrompt)
        XCTAssertEqual(
            SessionCommand.allCases.map(\.rawValue), ["start", "stop", "calibrate", "trial", "repeat", "acknowledge"])
    }

    func test_oldStateCountsAsStale() {
        var s = ControlState()
        s.sentUnix = 1000
        XCTAssertFalse(s.isStale(nowUnix: 1000 + ControlState.staleAfter - 1))
        XCTAssertTrue(s.isStale(nowUnix: 1000 + ControlState.staleAfter + 1))
    }
}

/// The devices a session is held to are the ones chosen at Go / No-Go (found on device 2026-10-19:
/// AirPods that connected on their own alarmed for 5 min in a phone + Watch session).
final class DevicePlanTests: XCTestCase {
    func test_unplannedAirPodsAreNotRequiredEvenWhenConnected() {
        XCTAssertEqual(DevicePlan.required(planned: ["phone", "watch"], watchStarted: true), ["phone", "watch"])
    }

    func test_plannedAirPodsAreRequiredBeforeTheirFirstSample() {
        XCTAssertTrue(
            DevicePlan.required(planned: ["phone", "watch", "airpods"], watchStarted: true).contains("airpods"))
    }

    func test_watchCountsOnlyOnceItStreams() {
        XCTAssertEqual(DevicePlan.required(planned: ["phone", "watch"], watchStarted: false), ["phone"])
    }

    func test_phoneIsAlwaysRequired() {
        XCTAssertEqual(DevicePlan.required(planned: [], watchStarted: true), ["phone"])
    }
}

/// Both screens show the Watch → iPhone transfer in the same words (found on device 2026-10-19:
/// the Watch showed one combined count including its journal, the iPhone two separate ones).
final class TransferProgressTests: XCTestCase {
    func test_sameTextOnBothScreens() {
        let p = TransferProgress(main: 12, mainTotal: 12, highRate: 11, highRateTotal: 11)
        XCTAssertEqual(p.text, "On iPhone: 60 Hz 12/12 · high-rate 11/11 ✓")
        XCTAssertTrue(p.isComplete)
    }

    func test_unknownTotalsBeforeStop() {
        let p = TransferProgress(main: 3, mainTotal: nil, highRate: 0, highRateTotal: nil)
        XCTAssertEqual(p.text, "On iPhone: 60 Hz 3/… · high-rate 0/…")
        XCTAssertFalse(p.isComplete)
    }
}
