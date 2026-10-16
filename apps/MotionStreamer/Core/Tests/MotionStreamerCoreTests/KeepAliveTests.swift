import XCTest

@testable import MotionStreamerCore

/// Stage 6 (simulated part): when the app must fall back to pocket mode.
final class KeepAliveTests: XCTestCase {
    func test_backgroundWithLocationRunningIsFine() {
        let policy = KeepAlivePolicy(clock: ManualClock())
        policy.keepAlive(running: true)
        XCTAssertEqual(policy.enteredBackground(), .fine)
    }

    func test_backgroundWithoutKeepAliveFallsBackToPocketMode() {
        let policy = KeepAlivePolicy(clock: ManualClock())
        guard case .usePocketMode = policy.enteredBackground() else { return XCTFail("expected pocket mode") }
    }

    func test_airPodsStoppingInTheBackgroundFallsBackToPocketMode() {
        let clock = ManualClock()
        let policy = KeepAlivePolicy(clock: clock)
        policy.keepAlive(running: true)
        _ = policy.enteredBackground()
        clock.advance(2)
        XCTAssertEqual(policy.check(airPodsConnected: true, lastAirPodsSample: clock.uptime - 0.1), .fine)
        clock.advance(5)
        XCTAssertEqual(
            policy.check(airPodsConnected: true, lastAirPodsSample: clock.uptime - 5),
            .usePocketMode(reason: "AirPods motion stopped in the background"))
        XCTAssertEqual(
            policy.check(airPodsConnected: false, lastAirPodsSample: nil), .fine, "not connected: no AirPods to keep")
        policy.enteredForeground()
        XCTAssertEqual(policy.check(airPodsConnected: true, lastAirPodsSample: nil), .fine)
    }

    func test_pocketModeMethodAlwaysAsksForPocketMode() {
        let policy = KeepAlivePolicy(clock: ManualClock(), method: .pocketMode)
        policy.keepAlive(running: true)
        guard case .usePocketMode = policy.enteredBackground() else { return XCTFail("expected pocket mode") }
    }
}
