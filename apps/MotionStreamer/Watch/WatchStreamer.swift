import CoreMotion
import Foundation
import HealthKit
import MotionStreamerCore
import WatchConnectivity
import WatchKit

/// Records wrist motion on the Watch's own disk (60 Hz chunks sent as they close, high-rate chunks
/// after Stop) and sends live preview batches to the iPhone (design §3).
/// A workout session keeps the app running while the wrist is down.
final class WatchStreamer: NSObject, ObservableObject {
    static let shared = WatchStreamer()

    @Published private(set) var isRunning = false
    @Published private(set) var phoneReachable = false
    @Published private(set) var samplesRecorded = 0
    @Published private(set) var measuredHz = 0.0
    @Published private(set) var status = "Idle"
    @Published private(set) var chunksSaved = 0
    @Published private(set) var chunksAcked = 0
    @Published private(set) var highRateStatus = "Off"

    /// Live preview batches kept while the iPhone is unreachable; the full data is on disk anyway.
    private let maxPendingBatches = 60

    private let motion = CMMotionManager()
    private let healthStore = HKHealthStore()
    private var workout: HKWorkoutSession?
    private let link = WCSessionLink()
    private let store = LocalFileStore(
        root: FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0])
    private let clock = SystemClock()
    private var tickTimer: Timer?
    private var highRateTasks: [Task<Void, Never>] = []
    private let batched = CMBatchedSensorManager()
    private let speech = WatchSpeech()
    private let altimeter = CMAltimeter()
    private var sensors = SensorPacketWriter()
    private var lastMagnetic = 0.0

    // State below is touched only on `queue`.
    private let queue: OperationQueue = {
        let q = OperationQueue()
        q.maxConcurrentOperationCount = 1
        q.name = "WatchStreamer"
        return q
    }()
    private var recorder: WatchRecorder?
    private var loc = "wrist"
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
        speech.onFinished = { [weak self] id in
            self?.link.sendMessage(LinkMessage(kind: .spoken, session: "", utterance: id).encoded)
        }
        link.onMessage = { [weak self] data in
            guard let message = LinkMessage.decode(data) else { return }
            if message.kind == .speak, let text = message.detail, let id = message.utterance {
                DispatchQueue.main.async { self?.speech.speak(text, id: id) }
                WKInterfaceDevice.current().play(.click)
                return
            }
            self?.queue.addOperation {
                self?.recorder?.outbox.handle(message)
                self?.publishTransfer()
            }
        }
        let workoutType = HKObjectType.workoutType()
        healthStore.requestAuthorization(toShare: [workoutType], read: []) { _, _ in }
    }

    /// Starts recording. `sessionID` comes from the iPhone; without one the Watch makes its own.
    func start(sessionID: String? = nil, loc: String? = nil, mirror: Bool = false) {
        guard !isRunning else { return }
        guard motion.isDeviceMotionAvailable else {
            setStatus("Device motion unavailable")
            return
        }
        startWorkout(mirror: mirror)

        let ref = preferredReferenceFrame()
        let osVersion = WKInterfaceDevice.current().systemVersion
        let id = sessionID ?? Self.newSessionID()
        queue.addOperation {
            self.loc = loc ?? self.loc
            self.recorder = self.openRecorder(id: id, ref: ref.name, os: osVersion)
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
        startHighRate()
        startExtraSensors()
        tickTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            self?.queue.addOperation {
                self?.recorder?.tick()
                self?.publishTransfer()
            }
        }
        DispatchQueue.main.async {
            self.isRunning = true
            self.samplesRecorded = 0
            self.status = "Recording (\(ref.name))"
        }
    }

    func stop() {
        guard isRunning else { return }
        motion.stopDeviceMotionUpdates()
        stopHighRate()
        altimeter.stopRelativeAltitudeUpdates()
        tickTimer?.invalidate()
        tickTimer = nil
        queue.addOperation {
            if !self.buffer.isEmpty { self.enqueueBatch() }
            self.flush()
            try? self.recorder?.stop()
            self.publishTransfer()
        }
        workout?.end()
        workout = nil
        DispatchQueue.main.async {
            self.isRunning = false
            self.status = "Stopped; sending the rest to the iPhone"
        }
    }

    /// The Watch's session buttons (design §7): one tap each, handled on the iPhone.
    func send(command: String) {
        guard WCSession.default.activationState == .activated, WCSession.default.isReachable else {
            WKInterfaceDevice.current().play(.failure)
            return
        }
        WCSession.default.sendMessage(["cmd": command], replyHandler: nil, errorHandler: nil)
        WKInterfaceDevice.current().play(.click)
    }

    /// The Watch's "Resend session" button: every chunk again (duplicates are harmless).
    func resendSession() {
        queue.addOperation { self.recorder?.outbox.resendAll() }
    }

    // MARK: - Recorder (on queue)

    private func openRecorder(id: String, ref: String, os: String) -> WatchRecorder? {
        let metadata: [String: Any] = [
            "model": hardwareModel(), "os": os, "ref_frame": ref, "loc": loc,
            "sample_rate_hz": MotionFormat.sampleRateHz,
        ]
        do {
            if SessionRecorder.unclosedSessions(store: store).contains(id) {
                _ = try SessionRecorder.recover(store: store, clock: clock, sessionID: id)
                return try WatchRecorder.resume(store: store, clock: clock, link: link, sessionID: id)
            }
            let r = try WatchRecorder.start(store: store, clock: clock, link: link, sessionID: id, metadata: metadata)
            return r
        } catch {
            setStatus("Cannot record: \(error)")
            return nil
        }
    }

    private static func newSessionID() -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        return "\(formatter.string(from: Date()))-W"
    }

    private func publishTransfer() {
        let saved = (recorder?.outbox.items.count) ?? 0
        let acked = (recorder?.outbox.acked.count) ?? 0
        DispatchQueue.main.async {
            self.chunksSaved = saved
            self.chunksAcked = acked
        }
    }

    // MARK: - Motion (on queue)

    private func handle(_ data: CMDeviceMotion) {
        buffer.append(data.sample)
        if data.timestamp - lastMagnetic >= 1 {
            lastMagnetic = data.timestamp
            let f = data.magneticField
            if let packet = sensors.magnetometer(
                device: "watch", t: data.timestamp, field: [f.field.x, f.field.y, f.field.z],
                accuracy: Int(f.accuracy.rawValue), bootToUnix: bootToUnixOffset())
            {
                recorder?.recordOther(packet)
            }
        }
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
        // The durable copy: the same JSON packets the iPhone writes for the Watch stream.
        let header: [String: Any] = [
            "v": MotionFormat.version, "type": "imu", "session": recorder?.sessionID ?? "", "device": "watch",
            "loc": loc, "seq": seq, "rate_hz": MotionFormat.sampleRateHz, "boot_to_unix": batch.bootToUnix,
            "ref_frame": refFrameName, "source": "watch_disk",
        ]
        for (k, packet) in PacketEncoder.imuPackets(header: header, samples: buffer, firstIndex: nextIndex).enumerated()
        {
            let first = nextIndex + k * MotionFormat.samplesPerPacket
            recorder?.recordMotion(
                packet, firstIndex: first,
                count: min(MotionFormat.samplesPerPacket, buffer.count - k * MotionFormat.samplesPerPacket))
        }
        seq += 1
        nextIndex += buffer.count
        buffer = []
        pending.append(batch)
        if pending.count > maxPendingBatches { pending.removeFirst() }  // preview only; the disk has it
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
            session.sendMessageData(data, replyHandler: nil, errorHandler: nil)
        }
    }

    private func makeHello(refFrame: String, os: String) -> Data? {
        let hello = WatchHello(
            model: hardwareModel(), os: os,
            refFrame: refFrame, rateHz: MotionFormat.sampleRateHz)
        return try? JSONEncoder().encode(hello)
    }

    // MARK: - Extra sensors (design §9)

    private func startExtraSensors() {
        sensors = SensorPacketWriter()
        guard CMAltimeter.isRelativeAltitudeAvailable() else { return }
        altimeter.startRelativeAltitudeUpdates(to: queue) { [weak self] data, _ in
            guard let self, let data,
                let packet = self.sensors.barometer(
                    device: "watch", t: data.timestamp, pressureKPa: data.pressure.doubleValue,
                    relativeAltitudeM: data.relativeAltitude.doubleValue, bootToUnix: bootToUnixOffset())
            else { return }
            self.recorder?.recordOther(packet)
        }
    }

    // MARK: - High-rate stream (CMBatchedSensorManager, design §2)

    private func startHighRate() {
        guard CMBatchedSensorManager.isAccelerometerSupported, CMBatchedSensorManager.isDeviceMotionSupported else {
            queue.addOperation { self.recorder?.highRateFailed("not supported on this Watch") }
            DispatchQueue.main.async { self.highRateStatus = "Not supported" }
            return
        }
        DispatchQueue.main.async { self.highRateStatus = "800 / 200 Hz" }
        let accel = Task { [weak self, batched] in
            do {
                for try await batch in batched.accelerometerUpdates() {
                    let records = batch.map {
                        HighRateFormat.Record.accel([
                            $0.timestamp, $0.acceleration.x, $0.acceleration.y, $0.acceleration.z,
                        ])
                    }
                    self?.queue.addOperation { self?.recorder?.recordHighRate(records) }
                }
            } catch {
                self?.highRateStopped(error)
            }
        }
        let deviceMotion = Task { [weak self, batched] in
            do {
                for try await batch in batched.deviceMotionUpdates() {
                    let records = batch.map { HighRateFormat.Record.motion($0.sample) }
                    self?.queue.addOperation { self?.recorder?.recordHighRate(records) }
                }
            } catch {
                self?.highRateStopped(error)
            }
        }
        highRateTasks = [accel, deviceMotion]
    }

    private func stopHighRate() {
        highRateTasks.forEach { $0.cancel() }
        highRateTasks = []
        batched.stopAccelerometerUpdates()
        batched.stopDeviceMotionUpdates()
    }

    private func highRateStopped(_ error: Error) {
        guard !(error is CancellationError) else { return }
        queue.addOperation { self.recorder?.highRateFailed(error.localizedDescription) }
        DispatchQueue.main.async { self.highRateStatus = "Stopped: \(error.localizedDescription)" }
    }

    // MARK: - Workout

    private func startWorkout(mirror: Bool) {
        guard workout == nil else { return }
        let config = HKWorkoutConfiguration()
        config.activityType = .other
        config.locationType = .indoor
        do {
            let session = try HKWorkoutSession(healthStore: healthStore, configuration: config)
            session.delegate = self
            // Prepare before mirroring: starting it earlier hangs on iOS/watchOS 26.0-26.1 (device-research §1).
            session.prepare()
            session.startActivity(with: Date())
            workout = session
            if mirror {
                session.startMirroringToCompanionDevice { [weak self] success, error in
                    if !success { self?.setStatus("Mirroring failed: \(error?.localizedDescription ?? "unknown")") }
                }
            }
        } catch {
            setStatus("Workout failed: \(error.localizedDescription)")
        }
    }

    /// After a crash watchOS relaunches the app with the workout still running: take it back,
    /// and resume the open session's recording as a new segment (design §4).
    func recoverWorkout() {
        healthStore.recoverActiveWorkoutSession { [weak self] session, _ in
            guard let self, let session else { return }
            DispatchQueue.main.async {
                session.delegate = self
                self.workout = session
                if let id = SessionRecorder.unclosedSessions(store: self.store).last {
                    self.start(sessionID: id)
                }
            }
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
    ) {
        // Ended without our Stop (crown press, watchOS): tell the iPhone, which relaunches us (test W7).
        guard toState == .ended, workoutSession === workout else { return }
        queue.addOperation { self.recorder?.workoutEnded("workout ended (\(fromState.rawValue) → ended)") }
    }

    func workoutSession(_ workoutSession: HKWorkoutSession, didFailWithError error: Error) {
        setStatus("Workout error: \(error.localizedDescription)")
        queue.addOperation { self.recorder?.workoutEnded("workout failed: \(error.localizedDescription)") }
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
        if reachable {
            queue.addOperation {
                self.flush()
                self.recorder?.outbox.tick()
            }
        }
    }

    func session(_ session: WCSession, didReceiveMessageData messageData: Data) {
        link.received(messageData: messageData)
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
        let session = message["session"] as? String
        let loc = message["loc"] as? String
        switch message["cmd"] as? String {
        case "start":
            let mirror = message["mirror"] as? Bool ?? false
            DispatchQueue.main.async { self.start(sessionID: session, loc: loc, mirror: mirror) }
        case "stop": DispatchQueue.main.async { self.stop() }
        case "resend": resendSession()
        default: break
        }
    }
}
