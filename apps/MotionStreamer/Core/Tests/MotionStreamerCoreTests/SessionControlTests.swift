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
