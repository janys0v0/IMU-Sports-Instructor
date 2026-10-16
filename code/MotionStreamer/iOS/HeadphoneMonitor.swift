import CoreMotion
import Foundation

/// AirPods head-motion check: connection state, delivered rate and live head angles.
/// Not yet part of the recorded stream.
final class HeadphoneMonitor: NSObject, ObservableObject {
    @Published private(set) var connection = "Not checked"
    @Published private(set) var isRunning = false
    @Published private(set) var measuredHz = 0.0
    @Published private(set) var samples = 0
    @Published private(set) var sensor = "–"
    /// Pitch, roll, yaw in degrees (arbitrary heading).
    @Published private(set) var angles = (pitch: 0.0, roll: 0.0, yaw: 0.0)
    @Published private(set) var lastTimestamp: Double?

    private let manager = CMHeadphoneMotionManager()
    private let queue: OperationQueue = {
        let q = OperationQueue()
        q.maxConcurrentOperationCount = 1
        return q
    }()
    private var windowStart: Double?
    private var windowSamples = 0

    override init() {
        super.init()
        manager.delegate = self
    }

    var authorization: String {
        switch CMHeadphoneMotionManager.authorizationStatus() {
        case .authorized: return "Authorized"
        case .denied: return "Denied (Settings > Privacy > Motion & Fitness)"
        case .restricted: return "Restricted"
        case .notDetermined: return "Not asked yet"
        @unknown default: return "Unknown"
        }
    }

    func toggle() { isRunning ? stop() : start() }

    func start() {
        guard manager.isDeviceMotionAvailable else {
            connection = "Head motion unavailable on this iPhone"
            return
        }
        samples = 0
        measuredHz = 0
        windowStart = nil
        windowSamples = 0
        isRunning = true
        connection = "Waiting for AirPods…"
        manager.startDeviceMotionUpdates(to: queue) { [weak self] data, error in
            guard let self else { return }
            if let error {
                DispatchQueue.main.async { self.connection = "Error: \(error.localizedDescription)" }
                return
            }
            guard let data else { return }
            self.handle(data)
        }
    }

    func stop() {
        manager.stopDeviceMotionUpdates()
        isRunning = false
        connection = "Stopped"
    }

    private func handle(_ data: CMDeviceMotion) {
        let t = data.timestamp
        if windowStart == nil { windowStart = t }
        windowSamples += 1
        var hz: Double?
        if let start = windowStart, t - start >= 1.0 {
            hz = Double(windowSamples - 1) / (t - start)
            windowStart = t
            windowSamples = 1
        }
        let deg = 180.0 / .pi
        let a = data.attitude
        let location: String
        switch data.sensorLocation {
        case .headphoneLeft: location = "Left bud"
        case .headphoneRight: location = "Right bud"
        case .default: location = "Default"
        @unknown default: location = "Unknown"
        }
        DispatchQueue.main.async {
            self.samples += 1
            if let hz { self.measuredHz = hz }
            self.angles = (a.pitch * deg, a.roll * deg, a.yaw * deg)
            self.sensor = location
            self.lastTimestamp = t
            self.connection = "Streaming"
        }
    }
}

extension HeadphoneMonitor: CMHeadphoneMotionManagerDelegate {
    func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) {
        DispatchQueue.main.async { self.connection = "Connected" }
    }

    func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) {
        DispatchQueue.main.async { self.connection = "Disconnected" }
    }
}
