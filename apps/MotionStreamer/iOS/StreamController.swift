import AudioToolbox
import CoreMotion
import Foundation
import HealthKit
import MotionStreamerCore
import UIKit
import WatchConnectivity

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
    /// What to face at every calibration (design §7), e.g. "the net".
    @Published var landmark: String { didSet { defaults.set(landmark, forKey: "landmark") } }
    /// Minutes between calibration reminders (default 10 until test T20 measures it).
    @Published var reminderMinutes: Double {
        didSet {
            defaults.set(reminderMinutes, forKey: "reminderMinutes")
            reminder.interval = reminderMinutes * 60
        }
    }
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
    /// "Watch: 58 / 60 chunks · high-rate 12 / 60" for the status section (design §3).
    @Published private(set) var watchTransfer = "–"
    /// A session a crash left open, offered for Resume at launch (design §4).
    @Published private(set) var interrupted: (id: String, at: Date)?

    private let defaults = UserDefaults.standard
    private let motion = CMMotionManager()
    private let headphones = CMHeadphoneMotionManager()
    private let healthStore = HKHealthStore()
    private var statsTimer: Timer?
    private var syncTimer: Timer?
    private var calibrationTimer: Timer?
    private lazy var phoneVoice = PhoneVoice()
    private lazy var watchVoice = WatchVoice(link: link)
    private lazy var speaker = Speaker(clock: clock, outputs: [])
    private lazy var flow = CalibrationFlow(speaker: speaker, clock: clock) { [weak self] device, from, to in
        self?.ioQueue.sync { self?.recentSamples(device, from, to) } ?? []
    }
    private lazy var reminder = CalibrationReminder(clock: clock)
    /// Last 30 s of samples per device, by arrival time, for the calibration checks (ioQueue).
    private var recent: [String: [(arrival: Double, sample: MotionSample)]] = [:]

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
    private let store = LocalFileStore(
        root: FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0])
    private let clock = SystemClock()
    private var replay: ReplayMotionSource?
    private let link = WCSessionLink()
    private lazy var inbox = TransferInbox(store: store, clock: clock, link: link)
    private lazy var supervisor = WatchSupervisor(clock: clock)
    /// Copies of the link state for the recording queue (the @Published ones belong to the main thread).
    private var ioWatchReachable = false
    private var ioAirPodsConnected = false
    private var replayTimer: DispatchSourceTimer?
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
        landmark = defaults.string(forKey: "landmark") ?? "the net"
        let minutes = defaults.double(forKey: "reminderMinutes")
        reminderMinutes = minutes > 0 ? minutes : 10
        super.init()
        setUpSpeech()
        if WCSession.isSupported() {
            WCSession.default.delegate = self
            WCSession.default.activate()
        }
        healthStore.requestAuthorization(toShare: [HKObjectType.workoutType()], read: []) { _, _ in }
        headphones.delegate = self
        UIDevice.current.isBatteryMonitoringEnabled = true
        observeLifecycle()
        findInterruptedSession()
        setUpWatchTransfer()
    }

    /// Watch chunks arrive as files; acks and the Watch's summary as messages (design §3).
    private func setUpWatchTransfer() {
        link.onFile = { [weak self] data, metadata in
            self?.ioQueue.async { self?.inbox.receive(data, metadata: metadata) }
        }
        ioQueue.async {
            self.inbox.onChange = { [weak self] session in self?.publishTransfer(session) }
            self.supervisor.onRelaunch = { [weak self] in DispatchQueue.main.async { self?.launchWatch() } }
            self.supervisor.onEvent = { [weak self] name, detail in self?.logEvent(name, detail: detail) }
            // Spoken in stage 7; logged now so every Watch stop is on record.
            self.supervisor.onAlert = { [weak self] id in self?.logEvent("alert", detail: id) }
        }
    }

    private func publishTransfer(_ session: String) {
        let main = inbox.progress(session: session, kind: "60hz")
        let hf = inbox.progress(session: session, kind: "hf")
        let text =
            "\(main.received) / \(main.total.map(String.init) ?? "…") chunks · high-rate \(hf.received) / \(hf.total.map(String.init) ?? "…")"
        DispatchQueue.main.async { self.watchTransfer = text }
    }

    var phoneLocation: String { "\(wrist.rawValue)_pocket" }
    var watchLocation: String { "\(wrist.rawValue)_wrist" }

    // MARK: - Controls

    func start() { begin(resuming: nil) }

    /// Continues the interrupted session as a new segment.
    func resumeInterrupted() {
        guard let id = interrupted?.id else { return }
        interrupted = nil
        begin(resuming: id)
    }

    /// Ends the interrupted session without resuming it.
    func closeInterrupted() {
        guard let id = interrupted?.id else { return }
        interrupted = nil
        ioQueue.async { try? SessionRecorder.closeInterrupted(store: self.store, clock: self.clock, sessionID: id) }
    }

    private func begin(resuming resumeID: String?) {
        guard !isRecording else { return }
        // Record-only mode: no Mac IP means no UDP; the phone still saves everything.
        let host = macHost.trimmingCharacters(in: .whitespaces)
        var sender: UDPSender?
        if !host.isEmpty {
            guard let port = UInt16(macPort), let s = UDPSender(host: host, port: port, queue: ioQueue) else {
                errorMessage = "The Mac IP or port is invalid. Clear the Mac IP to record on the phone only."
                return
            }
            sender = s
        }
        let replayRecording = ReplaySettings.recording()
        guard replayRecording != nil || motion.isDeviceMotionAvailable else {
            errorMessage = "Device motion is not available on this device."
            return
        }

        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let id = resumeID ?? "\(formatter.string(from: Date()))-\(participant.isEmpty ? "P00" : participant)"
        let ref = preferredReferenceFrame()
        let metadata: [String: Any] = [
            "format_version": MotionFormat.version,
            "participant": participant,
            "activity": activity,
            "sample_rate_hz": MotionFormat.sampleRateHz,
            "batch_size": MotionFormat.batchSize,
            "samples_per_packet": MotionFormat.samplesPerPacket,
            "sample_fields": MotionFormat.sampleFields,
            "units": ["t": "s since device boot", "a": "g (gravity removed)", "g": "g", "r": "rad/s"],
            "receiver": host.isEmpty ? "none (record-only)" : "\(host):\(macPort)",
            "app_version": Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?",
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
            "replay": replayRecording != nil,
        ]
        let recorder: SessionRecorder
        do {
            if let resumeID {
                recorder = try SessionRecorder.resume(store: store, clock: clock, sessionID: resumeID)
            } else {
                recorder = try SessionRecorder.start(store: store, clock: clock, sessionID: id, metadata: metadata)
            }
        } catch SessionRecorder.StartError.lowDisk(let free) {
            errorMessage = String(format: "Needs 2 GB free to record; %.1f GB left.", Double(free) / 1e9)
            return
        } catch {
            errorMessage = "Could not create the session: \(error.localizedDescription)"
            return
        }
        recorder.phone.onWriteError = { [weak self] error in
            self?.ioQueue.async { self?.logEvent("write_error", detail: String(describing: error)) }
        }
        recorder.healthProvider = { [weak self] in self?.healthFields() ?? [:] }

        sender?.onStateChange = { [weak self] state in
            DispatchQueue.main.async { self?.macStatus = state }
        }
        sender?.onAck = { [weak self] received in
            guard let self else { return }
            self.lastAckUptime = uptime()
            DispatchQueue.main.async { self.macReceived = received }
        }

        let screen = pocketScreen.rawValue
        let now = uptime()
        ioQueue.async {
            self.udp = sender
            self.recorder = recorder
            self.manifest = ["session": id]
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
            sender?.start()
            self.logEvent(
                resumeID == nil ? "start" : "resume",
                extra: ["loc": self.phoneLocation, "pocket_screen": screen, "segment": recorder.segment])
        }

        if let replayRecording {
            startReplay(replayRecording)
        } else {
            motion.deviceMotionUpdateInterval = 1.0 / MotionFormat.sampleRateHz
            motion.startDeviceMotionUpdates(using: ref.frame, to: motionQueue) { [weak self] data, error in
                guard let self, let data, error == nil else { return }
                self.handlePhone(data.sample)
            }
            startHeadphones()
        }

        sessionID = id
        if replayRecording == nil { launchWatch() }
        isRecording = true
        packetsSent = 0
        macReceived = nil
        recentEvents = []
        errorMessage = nil
        UIApplication.shared.isIdleTimerDisabled = true
        statsTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            self?.publishStats()
            self?.remindIfDue()
            self?.ioQueue.async {
                guard let self else { return }
                self.recorder?.tick()
                if self.recorder?.checkClock() == true { self.logEvent("clock_jump") }
                if self.active { self.supervisor.tick(watchReachable: self.ioWatchReachable) }
            }
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
        calibrationTimer = nil
        flow.cancel()
        speaker.stopAll()
        calibrationStatus = nil
        sendWatchCommand("stop")
        stopReplay()
        ioQueue.async {
            if !self.phoneBuffer.isEmpty { self.emitPhoneBatch() }
            if !self.headBuffer.isEmpty { self.emitHeadBatch() }
            self.logEvent("stop")
            self.recorder?.journalEvent(
                "stats",
                [
                    "packets_sent": self.sent, "udp_send_errors": self.udp?.sendErrors ?? 0,
                    "lost_records": self.recorder?.phone.lostRecords ?? 0,
                    "phone": self.phoneCounter.dictionary, "watch": self.watchCounter.dictionary,
                    "airpods": self.headCounter.dictionary,
                ])
            try? self.recorder?.stop()
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

    /// The spoken calibration (design §7), started from the Watch or the phone.
    func startCalibration() {
        guard isRecording, !flow.isRunning else { return }
        flow.landmark = landmark
        flow.requireAirPods = airPodsConnected
        flow.requireWatch = watchReachable
        ioQueue.async { self.logEvent("calibrate_requested") }
        calibrationStatus = "Calibrating: follow the voice"
        flow.start()
        calibrationTimer?.invalidate()
        calibrationTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] timer in
            guard let self else { return timer.invalidate() }
            self.flow.tick()
            if !self.flow.isRunning {
                timer.invalidate()
                self.calibrationTimer = nil
            }
        }
    }

    /// The Watch's Repeat button.
    func repeatPrompt() { speaker.repeatLast() }

    private func setUpSpeech() {
        PhoneVoice.configureAudioSession()
        speaker.outputs = [
            .init(name: "airpods", isAvailable: { PhoneVoice.airPodsAreOutput }, voice: phoneVoice),
            .init(
                name: "watch", isAvailable: { [weak self] in self?.watchVoice.isReachable ?? false }, voice: watchVoice),
            .init(name: "speaker", isAvailable: { true }, voice: phoneVoice),
        ]
        let log: (String, [String: Any]) -> Void = { [weak self] name, fields in
            self?.ioQueue.async { self?.logEvent(name, extra: fields) }
        }
        speaker.onEvent = log
        flow.onEvent = log
        flow.airpodsConnected = { [weak self] in self?.airPodsConnected ?? false }
        flow.onFinish = { [weak self] result in
            guard let self else { return }
            self.calibrationStatus = result.passed ? nil : "Calibration didn't work: \(result.failure?.rawValue ?? "")"
            if result.passed { self.reminder.calibrated() }
        }
        reminder.interval = reminderMinutes * 60
    }

    /// Called every 0.5 s while recording: speaks the reminder when it's due.
    private func remindIfDue() {
        guard isRecording, !flow.isRunning, reminder.tick() else { return }
        let script = VoiceScript.shared
        speaker.say(script.reminder("R1"), id: "R1")
        speaker.say(VoiceScript.fill(script.reminder("R2"), ["landmark": landmark]), id: "R2")
    }

    /// Samples of one device that arrived between two uptimes (ioQueue).
    private func recentSamples(_ device: String, _ from: Double, _ to: Double) -> [MotionSample] {
        (recent[device] ?? []).filter { $0.arrival >= from && $0.arrival <= to }.map(\.sample)
    }

    private func remember(_ device: String, _ samples: [MotionSample]) {
        let now = uptime()
        recent[device, default: []] += samples.map { (now, $0) }
        if let first = recent[device]?.first, now - first.arrival > 40 {
            recent[device]?.removeAll { now - $0.arrival > 30 }
        }
    }

    /// Marks a trial boundary (for example a clap).
    func markTrial() { ioQueue.async { self.logEvent("marker") } }

    /// Turns the screen off when the phone is in a pocket; the app keeps running.
    func setPocketMode(_ on: Bool) {
        UIDevice.current.isProximityMonitoringEnabled = on
    }

    // MARK: - Phone motion (ioQueue)

    private func handlePhone(_ sample: MotionSample) {
        guard active else { return }
        remember("phone", [sample])
        phoneBuffer.append(sample)
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
            self.remember("airpods", [data.sample])
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
        remember("watch", batch.samples)
    }

    private func handleHello(_ data: Data) {
        guard let hello = try? JSONDecoder().decode(WatchHello.self, from: data) else { return }
        ioQueue.async {
            self.recorder?.journalEvent(
                "watch_info",
                [
                    "model": hello.model, "os": hello.os, "location": self.watchLocation,
                    "ref_frame": hello.refFrame, "rate_hz": hello.rateHz,
                ])
            self.logEvent("watch_hello", detail: "\(hello.model) watchOS \(hello.os) \(hello.refFrame)")
        }
        DispatchQueue.main.async { self.watchInfo = "\(hello.model), watchOS \(hello.os)" }
    }

    // MARK: - Output (ioQueue)

    /// Sends samples in packets of `samplesPerPacket`, each with its own `first_index`.
    private func emitIMU(_ header: [String: Any], samples: [MotionSample], firstIndex: Int) {
        let device = header["device"] as? String
        let packets = PacketEncoder.imuPackets(header: header, samples: samples, firstIndex: firstIndex)
        for (k, data) in packets.enumerated() {
            let first = firstIndex + k * MotionFormat.samplesPerPacket
            send(
                data, device: device, firstIndex: first,
                count: min(MotionFormat.samplesPerPacket, samples.count - k * MotionFormat.samplesPerPacket))
        }
    }

    private func emit(_ packet: [String: Any]) {
        guard let data = PacketEncoder.packet(packet) else { return }
        send(data)
    }

    private func send(_ data: Data, device: String? = nil, firstIndex: Int? = nil, count: Int = 0) {
        udp?.send(data)
        recorder?.record(data, device: device, firstIndex: firstIndex, count: count)
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
        if Self.journalledEvents.contains(name) || name.hasPrefix("app_") {
            recorder?.journalEvent(name, event)
        }
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
        // Also send a start command in case the Watch app is already open; the session ID makes the
        // Watch save its chunks under the same session (and resume it after a relaunch).
        sendWatchCommand("start", extra: ["session": sessionID, "loc": watchLocation])
    }

    private func sendWatchCommand(_ command: String, extra: [String: Any] = [:]) {
        let session = WCSession.default
        guard session.activationState == .activated else { return }
        var message = extra
        message["cmd"] = command
        message["at"] = Date().timeIntervalSince1970
        if session.isReachable {
            session.sendMessage(message, replyHandler: nil, errorHandler: nil)
        } else {
            try? session.updateApplicationContext(message)
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

    /// Events also copied into the journal, so they survive even if a chunk is lost.
    private static let journalledEvents: Set<String> = [
        "start", "resume", "stop", "calibrate_requested", "calibrate", "calibrate_done", "marker",
        "watch_reachable", "watch_unreachable", "watch_launch_failed", "airpods_connected",
        "airpods_disconnected", "write_error", "clock_jump",
    ]

    // MARK: - Health, lifecycle, recovery

    /// Device conditions for the journal's 60 s `health` entries (design §2).
    private func healthFields() -> [String: Any] {
        var fields: [String: Any] = [
            "thermal": ProcessInfo.processInfo.thermalState.rawValue,
            "low_power": ProcessInfo.processInfo.isLowPowerModeEnabled,
            "free_disk_bytes": store.freeBytes,
            "lost_records": recorder?.phone.lostRecords ?? 0,
        ]
        let level = UIDevice.current.batteryLevel
        if level >= 0 { fields["battery_phone"] = Double(level) }
        fields["airpods_connected"] = ioAirPodsConnected
        fields["watch_reachable"] = ioWatchReachable
        return fields
    }

    private func observeLifecycle() {
        let names: [(Notification.Name, String)] = [
            (UIApplication.willResignActiveNotification, "app_inactive"),
            (UIApplication.didEnterBackgroundNotification, "app_background"),
            (UIApplication.willEnterForegroundNotification, "app_foreground"),
            (UIApplication.willTerminateNotification, "app_terminate"),
            (UIApplication.didReceiveMemoryWarningNotification, "app_memory_warning"),
        ]
        for (name, event) in names {
            NotificationCenter.default.addObserver(forName: name, object: nil, queue: nil) { [weak self] _ in
                self?.ioQueue.sync {
                    guard self?.active == true else { return }
                    self?.logEvent(event)
                    self?.recorder?.tick()
                }
            }
        }
    }

    /// At launch: close the open chunks of any session a crash left open, and offer the latest
    /// one (if under 2 hours old) for Resume; older ones are closed as interrupted.
    private func findInterruptedSession() {
        ioQueue.async {
            var newest: (id: String, at: Date)?
            for id in SessionRecorder.unclosedSessions(store: self.store) {
                guard let report = try? SessionRecorder.recover(store: self.store, clock: self.clock, sessionID: id)
                else { continue }
                let at = Date(timeIntervalSince1970: report.lastActivityUnix ?? 0)
                if Date().timeIntervalSince(at) < 2 * 3600, newest.map({ at > $0.at }) ?? true {
                    if let older = newest {
                        try? SessionRecorder.closeInterrupted(store: self.store, clock: self.clock, sessionID: older.id)
                    }
                    newest = (id, at)
                } else {
                    try? SessionRecorder.closeInterrupted(store: self.store, clock: self.clock, sessionID: id)
                }
            }
            DispatchQueue.main.async {
                self.interrupted = newest
                if newest != nil, ReplaySettings.autoResume { self.resumeInterrupted() }
            }
        }
    }

    // MARK: - Replay (simulator demos)

    private func startReplay(_ recording: Recording) {
        let source = ReplayMotionSource(recording: recording, device: "phone")
        guard let first = source.firstTime else { return }
        let shifted = ReplayMotionSource(recording: recording, device: "phone", timeShift: uptime() - first)
        shifted.start { [weak self] sample in self?.handlePhone(sample) }
        replay = shifted
        let timer = DispatchSource.makeTimerSource(queue: ioQueue)
        timer.schedule(deadline: .now(), repeating: .milliseconds(50))
        timer.setEventHandler { [weak self] in self?.replay?.emit(until: uptime()) }
        timer.resume()
        replayTimer = timer
    }

    private func stopReplay() {
        replayTimer?.cancel()
        replayTimer = nil
        replay = nil
    }

    // MARK: - Review (design §6)

    /// The review of a session, read from its closed chunks on disk (never from memory).
    func loadReview(_ id: String, completion: @escaping (ReviewData?) -> Void) {
        ioQueue.async {
            let review = try? ReviewLoader.load(store: self.store, sessionID: id)
            DispatchQueue.main.async { completion(review) }
        }
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
        ioQueue.async { self.ioWatchReachable = reachable }
    }

    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        let reachable = session.isReachable
        DispatchQueue.main.async { self.watchReachable = reachable }
        ioQueue.async { self.ioWatchReachable = reachable }
        ioQueue.async {
            guard self.active else { return }
            self.logEvent(reachable ? "watch_reachable" : "watch_unreachable")
        }
    }

    func session(_ session: WCSession, didReceiveMessageData messageData: Data) {
        if let message = LinkMessage.decode(messageData) {
            if message.kind == .spoken, let id = message.utterance {
                DispatchQueue.main.async { self.watchVoice.finished(id) }
                return
            }
            ioQueue.async {
                self.inbox.handle(message)
                self.supervisor.handle(message)
            }
        } else {
            ioQueue.async {
                self.handleWatch(messageData)
                self.supervisor.batchReceived()
            }
        }
    }

    func session(_ session: WCSession, didReceive file: WCSessionFile) {
        link.received(file: file)
    }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        if let hello = message["hello"] as? Data { handleHello(hello) }
        // The Watch's buttons (design §7: every action during a session is one Watch tap).
        DispatchQueue.main.async {
            switch message["cmd"] as? String {
            case "calibrate": self.startCalibration()
            case "repeat": self.repeatPrompt()
            case "acknowledge": self.ioQueue.async { self.logEvent("alert_acknowledged") }
            default: break
            }
        }
    }
}

extension StreamController: CMHeadphoneMotionManagerDelegate {
    func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) {
        DispatchQueue.main.async { self.airPodsConnected = true }
        ioQueue.async { self.ioAirPodsConnected = true }
        ioQueue.async { if self.active { self.logEvent("airpods_connected") } }
    }

    func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) {
        DispatchQueue.main.async { self.airPodsConnected = false }
        ioQueue.async { self.ioAirPodsConnected = false }
        ioQueue.async { if self.active { self.logEvent("airpods_disconnected") } }
    }
}
