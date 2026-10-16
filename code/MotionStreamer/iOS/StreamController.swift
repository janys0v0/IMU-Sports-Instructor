import AudioToolbox
import CoreMotion
import Foundation
import HealthKit
import UIKit
import WatchConnectivity

/// Per-stream counters shown in the UI and saved in the manifest.
struct StreamSnapshot {
    var samples = 0
    var missing = 0
    var measuredHz = 0.0
    /// Rate the device delivers (from sample timestamps); coverage is relative to this.
    var nominalHz = 0.0
    var coverage = 0.0
    var lastPacketAge: Double?
}

private struct StreamCounter {
    var startUptime = 0.0
    var samples = 0
    var missing = 0
    var nextIndex: Int?
    var lastPacketUptime: Double?
    var windowStart = 0.0
    var windowSamples = 0
    var measuredHz = 0.0
    /// First sample intervals (device clock), used to find the rate iOS actually delivers.
    var intervals: [Double] = []
    var lastSampleTime: Double?

    init(start: Double) {
        startUptime = start
        windowStart = start
    }

    /// Delivered sample rate from the median sample interval.
    var nominalHz: Double? {
        guard intervals.count >= 10 else { return nil }
        let median = intervals.sorted()[intervals.count / 2]
        return median > 0 ? 1 / median : nil
    }

    mutating func add(samples batch: [MotionSample], firstIndex: Int, now: Double) {
        let count = batch.count
        if let expected = nextIndex, firstIndex < expected {
            // A retried batch arrived after later ones: it was counted as missing.
            missing = max(0, missing - count)
        } else {
            if let expected = nextIndex { missing += firstIndex - expected }
            nextIndex = firstIndex + count
            for sample in batch {
                if let last = lastSampleTime, intervals.count < 200 { intervals.append(sample[0] - last) }
                lastSampleTime = sample[0]
            }
        }
        samples += count
        lastPacketUptime = now
        windowSamples += count
        if now - windowStart >= 2 {
            measuredHz = Double(windowSamples) / (now - windowStart)
            windowStart = now
            windowSamples = 0
        }
    }

    func snapshot(now: Double) -> StreamSnapshot {
        let elapsed = now - startUptime
        var coverage = 0.0
        if let hz = nominalHz, elapsed > 1 { coverage = Double(samples) / (hz * elapsed) }
        return StreamSnapshot(
            samples: samples, missing: missing, measuredHz: measuredHz,
            nominalHz: nominalHz ?? 0, coverage: coverage,
            lastPacketAge: lastPacketUptime.map { now - $0 })
    }

    var dictionary: [String: Any] {
        ["samples": samples, "missing_samples": missing, "delivered_rate_hz": nominalHz ?? 0]
    }
}

enum WatchWrist: String, CaseIterable, Identifiable {
    case left, right
    var id: String { rawValue }
}

/// Which way the phone's screen faces in the front trouser pocket. Used on the Mac
/// to find which way the body faces at calibration.
enum PocketScreen: String, CaseIterable, Identifiable {
    case leg, outward
    var id: String { rawValue }
}

/// Records phone motion, receives Watch batches, sends both to the Mac over UDP
/// and saves them on the phone.
final class StreamController: NSObject, ObservableObject {
    // Settings (persisted).
    @Published var macHost: String { didSet { defaults.set(macHost, forKey: "macHost") } }
    @Published var macPort: String { didSet { defaults.set(macPort, forKey: "macPort") } }
    @Published var participant: String { didSet { defaults.set(participant, forKey: "participant") } }
    @Published var activity: String { didSet { defaults.set(activity, forKey: "activity") } }
    @Published var wrist: WatchWrist { didSet { defaults.set(wrist.rawValue, forKey: "wrist") } }
    @Published var pocketScreen: PocketScreen {
        didSet { defaults.set(pocketScreen.rawValue, forKey: "pocketScreen") }
    }

    // Status.
    @Published private(set) var isRecording = false
    @Published private(set) var sessionID = ""
    @Published private(set) var elapsed = 0.0
    @Published private(set) var macStatus = "Not connected"
    @Published private(set) var packetsSent = 0
    @Published private(set) var macReceived: Int?
    @Published private(set) var lastAckAge: Double?
    @Published private(set) var watchReachable = false
    @Published private(set) var watchInfo = "Unknown"
    @Published private(set) var phone = StreamSnapshot()
    @Published private(set) var watch = StreamSnapshot()
    @Published private(set) var head = StreamSnapshot()
    @Published private(set) var airPodsConnected = false
    @Published private(set) var recentEvents: [String] = []
    @Published var errorMessage: String?
    /// Countdown / hold text while a calibration is in progress.
    @Published private(set) var calibrationStatus: String?

    private let defaults = UserDefaults.standard
    private let motion = CMMotionManager()
    private let headphones = CMHeadphoneMotionManager()
    private let healthStore = HKHealthStore()
    private var statsTimer: Timer?
    private var syncTimer: Timer?
    private var calibrationTimer: Timer?

    // State below is touched only on `ioQueue`.
    private let ioQueue = DispatchQueue(label: "StreamController.io")
    private lazy var motionQueue: OperationQueue = {
        let q = OperationQueue()
        q.maxConcurrentOperationCount = 1
        q.underlyingQueue = ioQueue
        return q
    }()
    private var udp: UDPSender?
    private var recorder: SessionRecorder?
    private var manifest: [String: Any] = [:]
    private var events: [[String: Any]] = []
    private var phoneBuffer: [MotionSample] = []
    private var phoneSeq = 0
    private var phoneIndex = 0
    private var phoneCounter = StreamCounter(start: 0)
    private var watchCounter = StreamCounter(start: 0)
    private var headCounter = StreamCounter(start: 0)
    private var headBuffer: [MotionSample] = []
    private var headSeq = 0
    private var headIndex = 0
    private var sent = 0
    private var lastAckUptime: Double?
    private var startUptime = 0.0
    private var phoneRefFrame = ""
    private var active = false

    override init() {
        macHost = defaults.string(forKey: "macHost") ?? ""
        macPort = defaults.string(forKey: "macPort") ?? "5005"
        participant = defaults.string(forKey: "participant") ?? "P01"
        activity = defaults.string(forKey: "activity") ?? "test"
        wrist = WatchWrist(rawValue: defaults.string(forKey: "wrist") ?? "") ?? .left
        pocketScreen = PocketScreen(rawValue: defaults.string(forKey: "pocketScreen") ?? "") ?? .leg
        super.init()
        if WCSession.isSupported() {
            WCSession.default.delegate = self
            WCSession.default.activate()
        }
        healthStore.requestAuthorization(toShare: [HKObjectType.workoutType()], read: []) { _, _ in }
        headphones.delegate = self
    }

    var phoneLocation: String { "\(wrist.rawValue)_pocket" }
    var watchLocation: String { "\(wrist.rawValue)_wrist" }

    // MARK: - Controls

    func start() {
        guard !isRecording else { return }
        guard let port = UInt16(macPort),
            let sender = UDPSender(host: macHost.trimmingCharacters(in: .whitespaces), port: port, queue: ioQueue)
        else {
            errorMessage = "Enter the Mac's IP address and port."
            return
        }
        guard motion.isDeviceMotionAvailable else {
            errorMessage = "Device motion is not available on this device."
            return
        }

        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let id = "\(formatter.string(from: Date()))-\(participant.isEmpty ? "P00" : participant)"
        let recorder: SessionRecorder
        do {
            recorder = try SessionRecorder(sessionID: id)
        } catch {
            errorMessage = "Could not create session folder: \(error.localizedDescription)"
            return
        }

        let ref = preferredReferenceFrame()
        let now = uptime()
        let baseManifest: [String: Any] = [
            "format_version": MotionFormat.version,
            "session": id,
            "participant": participant,
            "activity": activity,
            "sample_rate_hz": MotionFormat.sampleRateHz,
            "batch_size": MotionFormat.batchSize,
            "samples_per_packet": MotionFormat.samplesPerPacket,
            "sample_fields": ["t", "qx", "qy", "qz", "qw", "ax", "ay", "az", "gx", "gy", "gz", "rx", "ry", "rz"],
            "units": ["t": "s since device boot", "a": "g (gravity removed)", "g": "g", "r": "rad/s"],
            "receiver": "\(macHost):\(macPort)",
            "start_unix": Date().timeIntervalSince1970,
            "phone": [
                "model": hardwareModel(), "os": UIDevice.current.systemVersion,
                "location": phoneLocation, "ref_frame": ref.name,
                "pocket_screen": pocketScreen.rawValue,
            ],
            "watch": ["location": watchLocation],
            "airpods": [
                "location": "head", "ref_frame": "headphoneArbitrary",
                "available": headphones.isDeviceMotionAvailable,
            ],
        ]

        sender.onStateChange = { [weak self] state in
            DispatchQueue.main.async { self?.macStatus = state }
        }
        sender.onAck = { [weak self] received in
            guard let self else { return }
            self.lastAckUptime = uptime()
            DispatchQueue.main.async { self.macReceived = received }
        }

        let screen = pocketScreen.rawValue
        ioQueue.async {
            self.udp = sender
            self.recorder = recorder
            self.manifest = baseManifest
            self.events = []
            self.phoneBuffer = []
            self.phoneSeq = 0
            self.phoneIndex = 0
            self.phoneCounter = StreamCounter(start: now)
            self.watchCounter = StreamCounter(start: now)
            self.headCounter = StreamCounter(start: now)
            self.headBuffer = []
            self.headSeq = 0
            self.headIndex = 0
            self.sent = 0
            self.lastAckUptime = nil
            self.startUptime = now
            self.phoneRefFrame = ref.name
            self.active = true
            sender.start()
            recorder.writeManifest(baseManifest)
            self.logEvent("start", extra: ["loc": self.phoneLocation, "pocket_screen": screen])
        }

        motion.deviceMotionUpdateInterval = 1.0 / MotionFormat.sampleRateHz
        motion.startDeviceMotionUpdates(using: ref.frame, to: motionQueue) { [weak self] data, error in
            guard let self, let data, error == nil else { return }
            self.handlePhone(data)
        }
        launchWatch()
        startHeadphones()

        sessionID = id
        isRecording = true
        packetsSent = 0
        macReceived = nil
        recentEvents = []
        errorMessage = nil
        UIApplication.shared.isIdleTimerDisabled = true
        statsTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            self?.publishStats()
        }
        syncTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.pingWatch()
        }
    }

    func stop() {
        guard isRecording else { return }
        motion.stopDeviceMotionUpdates()
        headphones.stopDeviceMotionUpdates()
        statsTimer?.invalidate()
        syncTimer?.invalidate()
        calibrationTimer?.invalidate()
        calibrationStatus = nil
        sendWatchCommand("stop")
        ioQueue.async {
            if !self.phoneBuffer.isEmpty { self.emitPhoneBatch() }
            self.logEvent("stop")
            let now = uptime()
            self.manifest["stop_unix"] = Date().timeIntervalSince1970
            self.manifest["duration_s"] = now - self.startUptime
            self.manifest["packets_sent"] = self.sent
            self.manifest["udp_send_errors"] = self.udp?.sendErrors ?? 0
            if !self.headBuffer.isEmpty { self.emitHeadBatch() }
            self.manifest["stats"] = [
                "phone": self.phoneCounter.dictionary, "watch": self.watchCounter.dictionary,
                "airpods": self.headCounter.dictionary,
            ]
            self.manifest["events"] = self.events
            self.recorder?.writeManifest(self.manifest)
            self.recorder?.close()
            self.recorder = nil
            self.active = false
            // Give the last datagrams time to leave before closing the socket.
            let udp = self.udp
            self.udp = nil
            self.ioQueue.asyncAfter(deadline: .now() + 1) { udp?.cancel() }
        }
        publishStats()
        isRecording = false
        UIApplication.shared.isIdleTimerDisabled = false
        UIDevice.current.isProximityMonitoringEnabled = false
    }

    static let calibrationCountdown = 10
    static let calibrationHold = 3

    /// Countdown so the phone can be pocketed first. One buzz: stand still.
    /// Two buzzes: done. Events mark the still window for the Mac.
    func startCalibration() {
        guard isRecording, calibrationTimer == nil else { return }
        let screen = pocketScreen.rawValue
        let location = phoneLocation
        ioQueue.async { self.logEvent("calibrate_requested") }
        var remaining = Self.calibrationCountdown
        calibrationStatus = "Pocket the phone, stand straight: \(remaining)"
        calibrationTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] timer in
            guard let self else { return timer.invalidate() }
            remaining -= 1
            if remaining > 0 {
                self.calibrationStatus = "Pocket the phone, stand straight: \(remaining)"
            } else if remaining == 0 {
                AudioServicesPlaySystemSound(kSystemSoundID_Vibrate)
                self.calibrationStatus = "Hold still…"
                self.ioQueue.async {
                    self.logEvent(
                        "calibrate",
                        extra: [
                            "hold_s": Self.calibrationHold, "loc": location,
                            "pocket_screen": screen,
                        ])
                }
            } else if remaining == -Self.calibrationHold {
                timer.invalidate()
                self.calibrationTimer = nil
                AudioServicesPlaySystemSound(kSystemSoundID_Vibrate)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    AudioServicesPlaySystemSound(kSystemSoundID_Vibrate)
                }
                self.ioQueue.async { self.logEvent("calibrate_done") }
                self.calibrationStatus = nil
            }
        }
    }

    /// Marks a trial boundary (for example a clap).
    func markTrial() { ioQueue.async { self.logEvent("marker") } }

    /// Turns the screen off when the phone is in a pocket; the app keeps running.
    func setPocketMode(_ on: Bool) {
        UIDevice.current.isProximityMonitoringEnabled = on
    }

    // MARK: - Phone motion (ioQueue)

    private func handlePhone(_ data: CMDeviceMotion) {
        guard active else { return }
        phoneBuffer.append(data.sample)
        if phoneBuffer.count >= MotionFormat.batchSize { emitPhoneBatch() }
    }

    private func emitPhoneBatch() {
        let now = uptime()
        emitIMU(
            [
                "v": MotionFormat.version, "type": "imu", "session": manifest["session"] ?? "",
                "device": "phone", "loc": phoneLocation, "seq": phoneSeq,
                "rate_hz": MotionFormat.sampleRateHz, "boot_to_unix": bootToUnixOffset(),
                "ref_frame": phoneRefFrame, "send_phone": now,
            ], samples: phoneBuffer, firstIndex: phoneIndex)
        phoneCounter.add(samples: phoneBuffer, firstIndex: phoneIndex, now: now)
        phoneSeq += 1
        phoneIndex += phoneBuffer.count
        phoneBuffer = []
    }

    // MARK: - AirPods

    /// AirPods head motion (~25 Hz). Timestamps use the iPhone's uptime clock; the
    /// attitude reference is arbitrary (relative to where tracking started).
    private func startHeadphones() {
        let status = CMHeadphoneMotionManager.authorizationStatus()
        let statusName = ["notDetermined", "restricted", "denied", "authorized"][min(Int(status.rawValue), 3)]
        ioQueue.async { self.logEvent("airpods_auth", detail: statusName) }
        guard headphones.isDeviceMotionAvailable else {
            ioQueue.async { self.logEvent("airpods_unavailable") }
            return
        }
        headphones.startDeviceMotionUpdates(to: motionQueue) { [weak self] data, error in
            guard let self else { return }
            if let error {
                self.logEvent("airpods_error", detail: error.localizedDescription)
                return
            }
            guard let data, self.active else { return }
            if self.headIndex == 0 && self.headBuffer.isEmpty { self.logEvent("airpods_first_sample") }
            self.headBuffer.append(data.sample)
            if self.headBuffer.count >= MotionFormat.samplesPerPacket { self.emitHeadBatch() }
        }
    }

    private func emitHeadBatch() {
        let now = uptime()
        emitIMU(
            [
                "v": MotionFormat.version, "type": "imu", "session": manifest["session"] ?? "",
                "device": "airpods", "loc": "head", "seq": headSeq,
                "rate_hz": 25.0, "boot_to_unix": bootToUnixOffset(),
                "ref_frame": "headphoneArbitrary", "send_phone": now,
            ], samples: headBuffer, firstIndex: headIndex)
        headCounter.add(samples: headBuffer, firstIndex: headIndex, now: now)
        headSeq += 1
        headIndex += headBuffer.count
        headBuffer = []
    }

    // MARK: - Watch (ioQueue)

    private func handleWatch(_ data: Data) {
        guard active, let batch = try? JSONDecoder().decode(WatchBatch.self, from: data) else { return }
        let now = uptime()
        emitIMU(
            [
                "v": MotionFormat.version, "type": "imu", "session": manifest["session"] ?? "",
                "device": "watch", "loc": watchLocation, "seq": batch.seq,
                "rate_hz": MotionFormat.sampleRateHz, "boot_to_unix": batch.bootToUnix,
                "ref_frame": batch.refFrame, "sent_watch": batch.sentWatch,
                "recv_phone": now, "send_phone": now,
            ], samples: batch.samples, firstIndex: batch.firstIndex)
        watchCounter.add(samples: batch.samples, firstIndex: batch.firstIndex, now: now)
    }

    private func handleHello(_ data: Data) {
        guard let hello = try? JSONDecoder().decode(WatchHello.self, from: data) else { return }
        ioQueue.async {
            self.manifest["watch"] = [
                "model": hello.model, "os": hello.os, "location": self.watchLocation,
                "ref_frame": hello.refFrame, "rate_hz": hello.rateHz,
            ]
            self.recorder?.writeManifest(self.manifest)
            self.logEvent("watch_hello", detail: "\(hello.model) watchOS \(hello.os) \(hello.refFrame)")
        }
        DispatchQueue.main.async { self.watchInfo = "\(hello.model), watchOS \(hello.os)" }
    }

    // MARK: - Output (ioQueue)

    /// Sends samples in packets of `samplesPerPacket`, each with its own `first_index`.
    private func emitIMU(_ header: [String: Any], samples: [MotionSample], firstIndex: Int) {
        for start in stride(from: 0, to: samples.count, by: MotionFormat.samplesPerPacket) {
            let chunk = Array(samples[start..<min(start + MotionFormat.samplesPerPacket, samples.count)])
            var fields = header
            fields["first_index"] = firstIndex + start
            guard let headerData = try? JSONSerialization.data(withJSONObject: fields),
                var json = String(data: headerData, encoding: .utf8), json.hasSuffix("}")
            else { continue }
            json.removeLast()
            json += ",\"s\":" + samplesJSON(chunk) + "}"
            send(Data(json.utf8))
        }
    }

    private func emit(_ packet: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: packet) else { return }
        send(data)
    }

    private func send(_ data: Data) {
        udp?.send(data)
        recorder?.append(data)
        sent += 1
    }

    private func logEvent(_ name: String, detail: String? = nil, extra: [String: Any] = [:]) {
        var event: [String: Any] = ["t_phone": uptime(), "unix": Date().timeIntervalSince1970, "name": name]
        if let detail { event["detail"] = detail }
        event.merge(extra) { $1 }
        events.append(event)
        var packet = event
        packet["v"] = MotionFormat.version
        packet["type"] = "event"
        packet["session"] = manifest["session"] ?? ""
        emit(packet)
        let text = detail.map { "\(name): \($0)" } ?? name
        DispatchQueue.main.async {
            self.recentEvents = Array((self.recentEvents + [text]).suffix(5))
        }
    }

    // MARK: - Watch control

    private func launchWatch() {
        let config = HKWorkoutConfiguration()
        config.activityType = .other
        config.locationType = .indoor
        healthStore.startWatchApp(with: config) { [weak self] success, error in
            guard let self else { return }
            if !success {
                self.ioQueue.async {
                    self.logEvent("watch_launch_failed", detail: error?.localizedDescription ?? "unknown")
                }
            }
        }
        // Also send a start command in case the Watch app is already open.
        sendWatchCommand("start")
    }

    private func sendWatchCommand(_ command: String) {
        let session = WCSession.default
        guard session.activationState == .activated else { return }
        if session.isReachable {
            session.sendMessage(["cmd": command], replyHandler: nil, errorHandler: nil)
        } else if command == "stop" {
            try? session.updateApplicationContext(["cmd": "stop", "at": Date().timeIntervalSince1970])
        }
    }

    /// Clock-sync sample: phone uptime before/after and Watch uptime in between.
    private func pingWatch() {
        let session = WCSession.default
        guard session.activationState == .activated, session.isReachable else { return }
        let sent = uptime()
        session.sendMessage(
            ["ping": sent],
            replyHandler: { [weak self] reply in
                let received = uptime()
                guard let self, let watchTime = reply["t_watch"] as? Double else { return }
                self.ioQueue.async {
                    guard self.active else { return }
                    self.emit([
                        "v": MotionFormat.version, "type": "sync", "session": self.manifest["session"] ?? "",
                        "t_phone_send": sent, "t_watch": watchTime, "t_phone_recv": received,
                    ])
                }
            }, errorHandler: nil)
    }

    // MARK: - UI

    private func publishStats() {
        ioQueue.async {
            let now = uptime()
            let phone = self.phoneCounter.snapshot(now: now)
            let watch = self.watchCounter.snapshot(now: now)
            let head = self.headCounter.snapshot(now: now)
            let sent = self.sent
            let ackAge = self.lastAckUptime.map { now - $0 }
            let elapsed = now - self.startUptime
            DispatchQueue.main.async {
                self.phone = phone
                self.watch = watch
                self.head = head
                self.packetsSent = sent
                self.lastAckAge = ackAge
                self.elapsed = elapsed
            }
        }
    }
}

extension StreamController: WCSessionDelegate {
    func session(
        _ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        let reachable = session.isReachable
        DispatchQueue.main.async { self.watchReachable = reachable }
    }

    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        let reachable = session.isReachable
        DispatchQueue.main.async { self.watchReachable = reachable }
        ioQueue.async {
            guard self.active else { return }
            self.logEvent(reachable ? "watch_reachable" : "watch_unreachable")
        }
    }

    func session(_ session: WCSession, didReceiveMessageData messageData: Data) {
        ioQueue.async { self.handleWatch(messageData) }
    }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        if let hello = message["hello"] as? Data { handleHello(hello) }
    }
}

extension StreamController: CMHeadphoneMotionManagerDelegate {
    func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) {
        DispatchQueue.main.async { self.airPodsConnected = true }
        ioQueue.async { if self.active { self.logEvent("airpods_connected") } }
    }

    func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) {
        DispatchQueue.main.async { self.airPodsConnected = false }
        ioQueue.async { if self.active { self.logEvent("airpods_disconnected") } }
    }
}
