import CoreMotion
import Foundation
import HealthKit
import MotionStreamerCore
import WatchConnectivity
import WatchKit

/// Records wrist motion and forwards it to the iPhone in batches.
/// A workout session keeps the app running while the wrist is down.
final class WatchStreamer: NSObject, ObservableObject {
    static let shared = WatchStreamer()

    @Published private(set) var isRunning = false
    @Published private(set) var phoneReachable = false
    @Published private(set) var samplesRecorded = 0
    @Published private(set) var pendingBatches = 0
    @Published private(set) var droppedSamples = 0
    @Published private(set) var measuredHz = 0.0
    @Published private(set) var status = "Idle"

    /// Batches kept while the iPhone is unreachable (60 x 10 samples = 10 s at 60 Hz).
    private let maxPendingBatches = 60

    private let motion = CMMotionManager()
    private let healthStore = HKHealthStore()
    private var workout: HKWorkoutSession?

    // State below is touched only on `queue`.
    private let queue: OperationQueue = {
        let q = OperationQueue()
        q.maxConcurrentOperationCount = 1
        q.name = "WatchStreamer"
        return q
    }()
    private var buffer: [MotionSample] = []
    private var pending: [WatchBatch] = []
    private var seq = 0
    private var nextIndex = 0
    private var refFrameName = ""
    private var helloPending: Data?
    private var rateWindowStart = 0.0
    private var rateWindowCount = 0

    func activate() {
        if WCSession.isSupported() {
            WCSession.default.delegate = self
            WCSession.default.activate()
        }
        let workoutType = HKObjectType.workoutType()
        healthStore.requestAuthorization(toShare: [workoutType], read: []) { _, _ in }
    }

    func start() {
        guard !isRunning else { return }
        guard motion.isDeviceMotionAvailable else {
            setStatus("Device motion unavailable")
            return
        }
        startWorkout()

        let ref = preferredReferenceFrame()
        let osVersion = WKInterfaceDevice.current().systemVersion
        queue.addOperation {
            self.buffer = []
            self.pending = []
            self.seq = 0
            self.nextIndex = 0
            self.refFrameName = ref.name
            self.rateWindowStart = uptime()
            self.rateWindowCount = 0
            self.helloPending = self.makeHello(refFrame: ref.name, os: osVersion)
            self.flush()
        }

        motion.deviceMotionUpdateInterval = 1.0 / MotionFormat.sampleRateHz
        motion.startDeviceMotionUpdates(using: ref.frame, to: queue) { [weak self] data, error in
            guard let self, let data, error == nil else { return }
            self.handle(data)
        }
        DispatchQueue.main.async {
            self.isRunning = true
            self.samplesRecorded = 0
            self.droppedSamples = 0
            self.status = "Streaming (\(ref.name))"
        }
    }

    func stop() {
        guard isRunning else { return }
        motion.stopDeviceMotionUpdates()
        queue.addOperation {
            if !self.buffer.isEmpty { self.enqueueBatch() }
            self.flush()
        }
        workout?.end()
        workout = nil
        DispatchQueue.main.async {
            self.isRunning = false
            self.status = "Stopped"
        }
    }

    // MARK: - Motion (on queue)

    private func handle(_ data: CMDeviceMotion) {
        buffer.append(data.sample)
        rateWindowCount += 1
        let now = uptime()
        if now - rateWindowStart >= 2 {
            let hz = Double(rateWindowCount) / (now - rateWindowStart)
            rateWindowStart = now
            rateWindowCount = 0
            DispatchQueue.main.async { self.measuredHz = hz }
        }
        if buffer.count >= MotionFormat.batchSize {
            enqueueBatch()
            flush()
        }
    }

    private func enqueueBatch() {
        let batch = WatchBatch(
            seq: seq, firstIndex: nextIndex, bootToUnix: bootToUnixOffset(),
            refFrame: refFrameName, sentWatch: 0, samples: buffer)
        seq += 1
        nextIndex += buffer.count
        buffer = []
        pending.append(batch)
        if pending.count > maxPendingBatches {
            let lost = pending.removeFirst().samples.count
            DispatchQueue.main.async { self.droppedSamples += lost }
        }
        let recorded = nextIndex
        DispatchQueue.main.async { self.samplesRecorded = recorded }
    }

    private func flush() {
        let session = WCSession.default
        if let hello = helloPending, session.activationState == .activated, session.isReachable {
            session.sendMessage(["hello": hello], replyHandler: nil, errorHandler: nil)
            helloPending = nil
        }
        while session.activationState == .activated, session.isReachable, !pending.isEmpty {
            var batch = pending.removeFirst()
            batch.sentWatch = uptime()
            guard let data = try? JSONEncoder().encode(batch) else { continue }
            session.sendMessageData(data, replyHandler: nil) { [weak self] _ in
                // Delivery failed: put the batch back so it is retried in order.
                self?.queue.addOperation {
                    self?.pending.insert(batch, at: 0)
                    self?.publishPending()
                }
            }
        }
        publishPending()
    }

    private func publishPending() {
        let count = pending.count
        DispatchQueue.main.async { self.pendingBatches = count }
    }

    private func makeHello(refFrame: String, os: String) -> Data? {
        let hello = WatchHello(
            model: hardwareModel(), os: os,
            refFrame: refFrame, rateHz: MotionFormat.sampleRateHz)
        return try? JSONEncoder().encode(hello)
    }

    // MARK: - Workout

    private func startWorkout() {
        guard workout == nil else { return }
        let config = HKWorkoutConfiguration()
        config.activityType = .other
        config.locationType = .indoor
        do {
            let session = try HKWorkoutSession(healthStore: healthStore, configuration: config)
            session.delegate = self
            session.startActivity(with: Date())
            workout = session
        } catch {
            setStatus("Workout failed: \(error.localizedDescription)")
        }
    }

    private func setStatus(_ text: String) {
        DispatchQueue.main.async { self.status = text }
    }
}

extension WatchStreamer: HKWorkoutSessionDelegate {
    func workoutSession(
        _ workoutSession: HKWorkoutSession, didChangeTo toState: HKWorkoutSessionState,
        from fromState: HKWorkoutSessionState, date: Date
    ) {}

    func workoutSession(_ workoutSession: HKWorkoutSession, didFailWithError error: Error) {
        setStatus("Workout error: \(error.localizedDescription)")
    }
}

extension WatchStreamer: WCSessionDelegate {
    func session(
        _ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        let reachable = session.isReachable
        DispatchQueue.main.async { self.phoneReachable = reachable }
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        let reachable = session.isReachable
        DispatchQueue.main.async { self.phoneReachable = reachable }
        if reachable { queue.addOperation { self.flush() } }
    }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        handleCommand(message)
    }

    func session(
        _ session: WCSession, didReceiveMessage message: [String: Any],
        replyHandler: @escaping ([String: Any]) -> Void
    ) {
        // Clock-sync ping: reply with this device's uptime.
        if message["ping"] != nil {
            replyHandler(["t_watch": uptime()])
            return
        }
        handleCommand(message)
        replyHandler([:])
    }

    func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        handleCommand(applicationContext)
    }

    private func handleCommand(_ message: [String: Any]) {
        switch message["cmd"] as? String {
        case "start": DispatchQueue.main.async { self.start() }
        case "stop": DispatchQueue.main.async { self.stop() }
        default: break
        }
    }
}
