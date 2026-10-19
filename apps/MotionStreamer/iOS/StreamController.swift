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
    /// What keeps the app recording in a pocket (design §5; decided after the stage 0b check).
    @Published var keepAliveMethod: KeepAlivePolicy.Method {
        didSet {
            defaults.set(keepAliveMethod.rawValue, forKey: "keepAliveMethod")
            keepAlivePolicy.method = keepAliveMethod
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
    /// "Trial 3 running" / "Trial 3 ✅ keep" / "Trial 3 🔁 redo".
    @Published private(set) var trialStatus: String?
    /// The court-exit check after Stop (design §8 ④).
    @Published private(set) var courtExit: CourtExitCheck.Verdict?
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
    private let locationKeepAlive = LocationKeepAlive()
    private lazy var keepAlivePolicy = KeepAlivePolicy(clock: clock, method: keepAliveMethod)
    /// The mirrored workout from the Watch, kept so it stays alive (method `.mirroring`).
    private var mirroredWorkout: HKWorkoutSession?
    /// Last 3 min of samples per device, by arrival time, for calibration and trial checks (ioQueue).
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
    // Watchdog state (ioQueue unless noted).
    private let dropDetector = PhoneDropDetector()
    private var lastGoodCalibration: Double?
    private var calibrationResets: [Double] = []
    private var compassLow = false
    private lazy var trials = TrialTracker(clock: clock)
    private var sensors = SensorPacketWriter()
    private let altimeter = CMAltimeter()
    private let audioLevel = AudioLevelRecorder()
    private var lastMagnetic = 0.0
    private var lastWatchBatch: Double?
    private var lastWriteError: Double?
    private var watchStopped = false
    private var highRateFailed = false
    /// Load shedding: skip UDP while the sensors need the CPU (design §8).
    private var shedLoad = false
    private var startUptime = 0.0
    private var phoneRefFrame = ""
    private var active = false
    /// One control system (design §7): the Watch's buttons are commands to this controller, and
    /// the Watch shows the state broadcast from here.
    private var controlMessage: String?
    private var startingFromWatch = false
    private var lastControlSent: ControlState?
    private var lastControlSentUnix = 0.0
    private var controlTimer: Timer?
    /// Planned minutes and required devices from the last Go / No-Go, reused for a Start from the Watch.
    private var lastPlan: (minutes: Double, required: Set<String>) = (60, ["phone", "watch", "airpods"])

    override init() {
        macHost = defaults.string(forKey: "macHost") ?? ""
        macPort = defaults.string(forKey: "macPort") ?? "5005"
        participant = defaults.string(forKey: "participant") ?? "P01"
        activity = defaults.string(forKey: "activity") ?? "test"
        wrist = WatchWrist(rawValue: defaults.string(forKey: "wrist") ?? "") ?? .left
        pocketScreen = PocketScreen(rawValue: defaults.string(forKey: "pocketScreen") ?? "") ?? .leg
        landmark = defaults.string(forKey: "landmark") ?? "the net"
        keepAliveMethod =
            KeepAlivePolicy.Method(rawValue: defaults.string(forKey: "keepAliveMethod") ?? "") ?? .location
        let minutes = defaults.double(forKey: "reminderMinutes")
        reminderMinutes = minutes > 0 ? minutes : 10
        super.init()
        setUpSpeech()
        setUpKeepAlive()
        if WCSession.isSupported() {
            WCSession.default.delegate = self
            WCSession.default.activate()
        }
        healthStore.requestAuthorization(toShare: [HKObjectType.workoutType()], read: []) { _, _ in }
        headphones.delegate = self
        UIDevice.current.isBatteryMonitoringEnabled = true
        observeLifecycle()
        findInterruptedSession()
        controlTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            self?.broadcastControl()
        }
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
            self.supervisor.onAlert = { [weak self] id in
                if id == "watch_stopped" { self?.watchStopped = true }
                if id == "high_rate_failed" { self?.highRateFailed = true }
            }
        }
    }

    /// The court-exit check (design §8 ④): every trial kept, the Watch's 60 Hz chunks on the phone,
    /// its high-rate chunks closed (they may still be on the Watch).
    private func updateCourtExit(_ session: String) {
        let summary = inbox.expected[session].map { ($0.chunks60Hz, $0.chunksHighRate, true) }
        let watchUsed = lastWatchBatch != nil || summary != nil
        let verdict = CourtExitCheck(
            trials: trials.trials, watchSummary: summary,
            chunks60HzOnPhone: inbox.count(session: session, kind: "60hz"),
            watchRequired: watchUsed
        ).verdict
        DispatchQueue.main.async { self.courtExit = verdict }
    }

    private func publishTransfer(_ session: String) {
        updateCourtExit(session)
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
        controlMessage = nil
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
            self?.ioQueue.async {
                self?.lastWriteError = uptime()
                self?.logEvent("write_error", detail: String(describing: error))
            }
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
            self.dropDetector.reset()
            self.sensors = SensorPacketWriter(session: id)
            self.calibrationResets = []
            self.lastGoodCalibration = nil
            self.lastWatchBatch = nil
            self.watchStopped = false
            self.highRateFailed = false
            self.active = true
            sender?.start()
            if let g = self.lastGoNoGo {
                self.logEvent(
                    "gonogo",
                    extra: [
                        "can_start": g.canStart,
                        "checks": g.checks.map { ["id": $0.id, "ok": $0.ok, "detail": $0.detail] },
                    ])
            }
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
                self.handleMagnetic(data)
            }
            startHeadphones()
        }

        sessionID = id
        trials = TrialTracker(clock: clock)
        trials.onEvent = { [weak self] name, fields in self?.ioQueue.async { self?.logEvent(name, extra: fields) } }
        trialStatus = nil
        courtExit = nil
        if replayRecording == nil { launchWatch() }
        startExtraSensors()
        if keepAliveMethod == .location { locationKeepAlive.start() }
        isRecording = true
        packetsSent = 0
        macReceived = nil
        recentEvents = []
        errorMessage = nil
        UIApplication.shared.isIdleTimerDisabled = true
        statsTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            self?.publishStats()
            self?.remindIfDue()
            self?.runWatchdog()
            self?.checkKeepAlive()
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
        controlMessage = nil
        motion.stopDeviceMotionUpdates()
        headphones.stopDeviceMotionUpdates()
        statsTimer?.invalidate()
        syncTimer?.invalidate()
        calibrationTimer?.invalidate()
        calibrationTimer = nil
        flow.cancel()
        speaker.stopAll()
        locationKeepAlive.stop()
        altimeter.stopRelativeAltitudeUpdates()
        audioLevel.stop()
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
            if let id = self.manifest["session"] as? String { self.updateCourtExit(id) }
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
    /// Returns why it didn't start, or nil when it did (shown on the Watch).
    @discardableResult
    func startCalibration() -> String? {
        guard isRecording else { return "Press Start first" }
        guard !flow.isRunning else { return "Already calibrating" }
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
        return nil
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
            if result.passed {
                self.reminder.calibrated()
                self.ioQueue.async { self.lastGoodCalibration = uptime() }
            }
        }
        reminder.interval = reminderMinutes * 60
        trials.onEvent = { [weak self] name, fields in self?.ioQueue.async { self?.logEvent(name, extra: fields) } }
    }

    /// Called every 0.5 s while recording: speaks the reminder when it's due.
    private func remindIfDue() {
        guard isRecording, !flow.isRunning, reminder.tick() else { return }
        let script = VoiceScript.shared
        speaker.say(script.reminder("R1"), id: "R1")
        speaker.say(VoiceScript.fill(script.reminder("R2"), ["landmark": landmark]), id: "R2")
    }

    // MARK: - Keeping the app alive (design §5)

    private func setUpKeepAlive() {
        locationKeepAlive.onChange = { [weak self] running in
            guard let self else { return }
            self.keepAlivePolicy.keepAlive(running: running || self.mirroredWorkout != nil)
        }
        // Workout mirroring: the Watch hands its workout to the phone, launching it in the background.
        healthStore.workoutSessionMirroringStartHandler = { [weak self] session in
            DispatchQueue.main.async {
                self?.mirroredWorkout = session
                self?.keepAlivePolicy.keepAlive(running: true)
                self?.ioQueue.async { self?.logEvent("workout_mirrored") }
            }
        }
        NotificationCenter.default.addObserver(
            forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main
        ) { [weak self] _ in
            guard let self, self.isRecording else { return }
            self.apply(self.keepAlivePolicy.enteredBackground())
        }
        NotificationCenter.default.addObserver(
            forName: UIApplication.willEnterForegroundNotification, object: nil, queue: .main
        ) { [weak self] _ in self?.keepAlivePolicy.enteredForeground() }
    }

    private func checkKeepAlive() {
        guard isRecording else { return }
        let last = ioQueue.sync { recent["airpods"]?.last?.arrival }
        apply(keepAlivePolicy.check(airPodsConnected: airPodsConnected, lastAirPodsSample: last))
    }

    private var lastPocketAdvice: Double = 0

    /// Pocket mode is needed: log it and say so (at most once a minute).
    private func apply(_ advice: KeepAlivePolicy.Advice) {
        guard case .usePocketMode(let reason) = advice, uptime() - lastPocketAdvice > 60 else { return }
        lastPocketAdvice = uptime()
        ioQueue.async { self.logEvent("pocket_mode_needed", detail: reason) }
        if let alert = VoiceScript.shared.alert("keep_app_open") {
            speaker.say(alert.text, id: "keep_app_open", priority: .warn)
        }
    }

    /// Samples of one device that arrived between two uptimes (ioQueue).
    private func recentSamples(_ device: String, _ from: Double, _ to: Double) -> [MotionSample] {
        (recent[device] ?? []).filter { $0.arrival >= from && $0.arrival <= to }.map(\.sample)
    }

    private func remember(_ device: String, _ samples: [MotionSample]) {
        let now = uptime()
        recent[device, default: []] += samples.map { (now, $0) }
        if let first = recent[device]?.first, now - first.arrival > 200 {
            recent[device]?.removeAll { now - $0.arrival > 180 }
        }
    }

    /// Marks a trial boundary (for example a clap).
    // MARK: - Extra sensors (design §9)

    private func startExtraSensors() {
        if CMAltimeter.isRelativeAltitudeAvailable() {
            altimeter.startRelativeAltitudeUpdates(to: motionQueue) { [weak self] data, _ in
                guard let self, let data, self.active,
                    let packet = self.sensors.barometer(
                        device: "phone", t: data.timestamp, pressureKPa: data.pressure.doubleValue,
                        relativeAltitudeM: data.relativeAltitude.doubleValue, bootToUnix: bootToUnixOffset())
                else { return }
                self.send(packet)
            }
        }
        audioLevel.onLevel = { [weak self] t, rms, peak, onset in
            self?.ioQueue.async {
                guard let self, self.active,
                    let packet = self.sensors.audioLevel(
                        t: t, rmsDB: rms, peakDB: peak, onset: onset, bootToUnix: bootToUnixOffset())
                else { return }
                self.send(packet)
            }
        }
        audioLevel.start()
    }

    /// Magnetometer once a second (ioQueue); low accuracy feeds the "compass disturbed" check.
    private func handleMagnetic(_ data: CMDeviceMotion) {
        guard active, data.timestamp - lastMagnetic >= 1 else { return }
        lastMagnetic = data.timestamp
        let f = data.magneticField
        compassLow = f.accuracy == .uncalibrated || f.accuracy == .low
        if let packet = sensors.magnetometer(
            device: "phone", t: data.timestamp, field: [f.field.x, f.field.y, f.field.z],
            accuracy: Int(f.accuracy.rawValue),
            bootToUnix: bootToUnixOffset())
        {
            send(packet)
        }
    }

    /// The Trial button (Watch or phone): starts a trial, or ends it and checks it (design §8 ③, §9).
    func markTrial() {
        guard isRecording else { return }
        let result = trials.tap { [weak self] number, start, end in
            self?.trialCheck(number, start, end)
                ?? TrialCheck(
                    TrialCheck.Input(
                        trial: number, start: start, end: end, items: [:], requiredDevices: [],
                        syncGestureDetected: false))
        }
        switch result {
        case .started(let n):
            trialStatus = "Trial \(n) running: do the 3 hops"
        case .ended(let n, let keep, let spoken):
            trialStatus = keep ? "Trial \(n) ✅ keep" : "Trial \(n) 🔁 redo"
            if let spoken { speaker.say(spoken, id: "redo_trial") }
        }
    }

    private func trialCheck(_ number: Int, _ start: Double, _ end: Double) -> TrialCheck {
        ioQueue.sync {
            var items: [String: [(index: Int, t: Double)]] = [:]
            for (device, list) in recent {
                items[device] = list.enumerated().map { ($0.offset, $0.element.arrival) }
            }
            let now = uptime()
            let phone = (recent["phone"] ?? []).map(\.sample)
            let hops = SyncGesture.detected(phone, from: start - 2, to: start + 8)
            var required: Set<String> = ["phone"]
            if lastWatchBatch.map({ now - $0 < 30 }) ?? false { required.insert("watch") }
            if headIndex > 0 { required.insert("airpods") }
            var input = TrialCheck.Input(
                trial: number, start: start, end: end, items: items, requiredDevices: required,
                syncGestureDetected: hops)
            input.baselineHz = [
                "phone": phoneCounter.nominalHz ?? 0, "watch": watchCounter.nominalHz ?? 0,
                "airpods": headCounter.nominalHz ?? 0,
            ].filter { $0.value > 0 }
            input.lastGoodCalibration = lastGoodCalibration
            input.calibrationResets = calibrationResets
            input.reminderInterval = reminderMinutes * 60
            input.dataUntil = now
            return TrialCheck(input)
        }
    }

    /// Turns the screen off when the phone is in a pocket; the app keeps running.
    func setPocketMode(_ on: Bool) {
        UIDevice.current.isProximityMonitoringEnabled = on
    }

    // MARK: - Phone motion (ioQueue)

    private func handlePhone(_ sample: MotionSample) {
        guard active else { return }
        let watchRecent = (recent["watch"] ?? []).suffix(30).map(\.sample)
        dropDetector.add(sample, watchMoving: watchRecent.contains { abs($0[11]) + abs($0[12]) + abs($0[13]) > 0.6 })
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
        lastWatchBatch = now
        watchStopped = false
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
        if !shedLoad { udp?.send(data) }
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

    /// A session button pressed on the phone: the same path as the Watch's buttons.
    func perform(_ command: SessionCommand) {
        _ = handleCommand(command.rawValue)
    }

    /// Start pressed on the Watch: the same Go / No-Go as the phone's Start screen, with the last
    /// plan; Start only if every blocking check passes, otherwise the Watch shows why.
    private func startFromWatch() {
        startingFromWatch = true
        preflight(plannedMinutes: lastPlan.minutes, required: lastPlan.required, heardVoice: nil) { [weak self] go in
            guard let self else { return }
            self.startingFromWatch = false
            self.lastGoNoGo = go
            if go.canStart {
                self.start()
                self.controlMessage = "Recording"
            } else {
                let failed = go.failures.filter(\.blocking).map { $0.id.replacingOccurrences(of: "_", with: " ") }
                self.controlMessage = "No-Go: " + failed.joined(separator: ", ")
            }
            self.broadcastControl(force: true)
        }
    }

    /// The state both screens show (main thread).
    var controlState: ControlState {
        var s = ControlState()
        s.phase = isRecording ? .recording : (startingFromWatch ? .starting : .idle)
        s.sessionID = isRecording ? sessionID : nil
        s.startedUnix = isRecording ? Date().timeIntervalSince1970 - elapsed : nil
        s.calibrating = flow.isRunning
        s.openTrial = trials.openTrial?.number
        s.trialsKept = trials.trials.filter(\.keep).count
        s.trialsRedo = trials.trials.count - s.trialsKept
        let alerts = alertCenter.active.values.filter { !$0.acknowledged }
        let top = alerts.first { $0.level == .red } ?? alerts.first
        s.alert = top.map { $0.detail ?? $0.id.replacingOccurrences(of: "_", with: " ") }
        s.message = controlMessage
        s.sentUnix = Date().timeIntervalSince1970
        return s
    }

    /// Sends the state to the Watch when it changes, and every 3 s so the Watch can tell the
    /// iPhone is still there (main thread).
    private func broadcastControl(force: Bool = false) {
        let session = WCSession.default
        guard WCSession.isSupported(), session.activationState == .activated, session.isReachable else { return }
        var state = controlState
        var comparable = state
        comparable.sentUnix = 0
        let now = state.sentUnix
        guard force || comparable != lastControlSent || now - lastControlSentUnix >= 3 else { return }
        lastControlSent = comparable
        lastControlSentUnix = now
        state.sentUnix = now
        session.sendMessage(state.wcMessage(), replyHandler: nil, errorHandler: nil)
    }

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
        sendWatchCommand(
            "start", extra: ["session": sessionID, "loc": watchLocation, "mirror": keepAliveMethod == .mirroring])
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
        "airpods_disconnected", "write_error", "clock_jump", "gonogo", "calibrate_arms", "calibrate_result",
        "trial_check", "alert", "alert_acknowledged", "pocket_mode_needed", "sensor_restart", "workout_mirrored",
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

    // MARK: - Go / No-Go (design §8 ①)

    /// Measures the sensors for 2 s and gathers everything the Go / No-Go check needs.
    func preflight(
        plannedMinutes: Double, required: Set<String>, heardVoice: Bool?, completion: @escaping (GoNoGo) -> Void
    ) {
        lastPlan = (plannedMinutes, required)
        var phoneCount = 0
        var headCount = 0
        let probe = CMMotionManager()
        probe.deviceMotionUpdateInterval = 1.0 / MotionFormat.sampleRateHz
        if probe.isDeviceMotionAvailable {
            probe.startDeviceMotionUpdates(to: .main) { data, _ in if data != nil { phoneCount += 1 } }
        }
        let headProbe = CMHeadphoneMotionManager()
        if headProbe.isDeviceMotionAvailable {
            headProbe.startDeviceMotionUpdates(to: .main) { data, _ in if data != nil { headCount += 1 } }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            guard let self else { return }
            probe.stopDeviceMotionUpdates()
            headProbe.stopDeviceMotionUpdates()
            var i = GoNoGo.Input()
            i.requiredDevices = required
            i.plannedMinutes = plannedMinutes
            // Delivered rates vary by model (an iPhone 16 gives ~33 Hz); 25 Hz is the floor that works.
            i.liveRates["phone"] = (Double(phoneCount) / 2, 30)
            if let replay = ReplaySettings.recording(), let s = replay.streams["phone"]?.samples, s.count > 1 {
                // Simulator runs replay a recording: its rate stands in for the phone's sensor.
                i.liveRates["phone"] = (Double(s.count - 1) / (s.last!.sample[0] - s.first!.sample[0]), 30)
            }
            i.liveRates["airpods"] = (Double(headCount) / 2, 20)
            i.liveRates["watch"] = (self.watchReachable ? 60 : 0, 60)  // the Watch streams only after Start
            let level = UIDevice.current.batteryLevel
            i.batteryPhone = level >= 0 ? Double(level) : nil
            i.freeDiskPhone = self.store.freeBytes
            i.lowPowerPhone = ProcessInfo.processInfo.isLowPowerModeEnabled
            i.signingDaysLeft = Self.signingDaysLeft()
            i.heardVoice = heardVoice
            i.landmark = self.landmark
            completion(GoNoGo(i))
        }
    }

    /// Days until the provisioning profile expires (free Apple ID builds last 7 days); nil if unknown.
    static func signingDaysLeft() -> Double? {
        guard let url = Bundle.main.url(forResource: "embedded", withExtension: "mobileprovision"),
            let data = try? Data(contentsOf: url), let text = String(data: data, encoding: .isoLatin1),
            let key = text.range(of: "<key>ExpirationDate</key>"),
            let open = text.range(of: "<date>", range: key.upperBound..<text.endIndex),
            let close = text.range(of: "</date>", range: open.upperBound..<text.endIndex)
        else { return nil }
        let formatter = ISO8601DateFormatter()
        guard let date = formatter.date(from: String(text[open.upperBound..<close.lowerBound])) else { return nil }
        return date.timeIntervalSinceNow / 86400
    }

    /// The last Go / No-Go result, logged when the session starts.
    var lastGoNoGo: GoNoGo?

    /// The audibility check: speaks the question; `tapReceived()` comes from the Watch's OK or the phone.
    private(set) lazy var audibility = AudibilityCheck(clock: clock)
    func startAudibilityCheck() { audibility.start(speaker: speaker) }

    // MARK: - Watchdog (design §8)

    private lazy var watchdog = Watchdog(clock: clock)
    private lazy var alertCenter: AlertCenter = {
        let center = AlertCenter(speaker: speaker, clock: clock)
        center.onEvent = { [weak self] name, fields in self?.ioQueue.async { self?.logEvent(name, extra: fields) } }
        return center
    }()
    private var lastWatchdog = 0.0

    /// Builds the watchdog's view of the session, runs it once a second, applies the fixes.
    private func runWatchdog() {
        guard isRecording, uptime() - lastWatchdog >= 1 else { return }
        lastWatchdog = uptime()
        var input = ioQueue.sync { () -> WatchdogInput in
            var input = WatchdogInput()
            let now = uptime()
            func stream(_ device: String, _ snap: StreamSnapshot, required: Bool) -> WatchdogInput.Stream {
                let samples = (recent[device] ?? []).filter { now - $0.arrival <= 5 }
                return .init(
                    required: required, lastSampleAge: (recent[device]?.last?.arrival).map { now - $0 },
                    rate5s: Double(samples.count) / 5, baselineHz: snap.nominalHz > 0 ? snap.nominalHz : nil,
                    recent: samples.map(\.sample))
            }
            input.streams = [
                "phone": stream("phone", phoneCounter.snapshot(now: now), required: true),
                "watch": stream(
                    "watch", watchCounter.snapshot(now: now), required: ioWatchReachable || lastWatchBatch != nil),
                "airpods": stream("airpods", headCounter.snapshot(now: now), required: headIndex > 0),
            ]
            input.watchBatchAge = lastWatchBatch.map { now - $0 }
            input.watchReachable = ioWatchReachable
            input.watchStopped = watchStopped
            input.highRateFailed = highRateFailed
            input.writeErrorRecently = lastWriteError.map { now - $0 < 10 } ?? false
            input.freeDiskBytes = store.freeBytes
            input.phoneDropped = dropDetector.dropped
            input.compassAccuracyLow = compassLow
            input.airpodsConnected = ioAirPodsConnected
            return input
        }
        input.airpodsRouteAway =
            airPodsConnected && !PhoneVoice.airPodsAreOutput && (input.streams["airpods"]?.lastSampleAge ?? 0) > 1
        let level = UIDevice.current.batteryLevel
        input.batteryPhone = level >= 0 ? Double(level) : nil
        input.lowPower = ProcessInfo.processInfo.isLowPowerModeEnabled
        input.thermal = ProcessInfo.processInfo.thermalState.rawValue
        let (problems, actions) = watchdog.evaluate(input)
        alertCenter.update(problems)
        let shed = actions.contains(.shedLoad)
        ioQueue.async { self.shedLoad = shed }
        for case .restartUpdates(let device) in actions { restartUpdates(device) }
    }

    /// The frozen-sensor fix: stop and start that device's motion updates.
    private func restartUpdates(_ device: String) {
        ioQueue.async { self.logEvent("sensor_restart", detail: device) }
        switch device {
        case "airpods":
            headphones.stopDeviceMotionUpdates()
            startHeadphones()
        case "phone":
            motion.stopDeviceMotionUpdates()
            motion.startDeviceMotionUpdates(using: preferredReferenceFrame().frame, to: motionQueue) {
                [weak self] data, error in
                guard let self, let data, error == nil else { return }
                self.handlePhone(data.sample)
                self.handleMagnetic(data)
            }
        default:
            launchWatch()
        }
    }

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
        DispatchQueue.main.async { _ = self.handleCommand(message["cmd"] as? String) }
    }

    /// Watch buttons send with a reply handler, so the Watch can show what happened.
    func session(
        _ session: WCSession, didReceiveMessage message: [String: Any],
        replyHandler: @escaping ([String: Any]) -> Void
    ) {
        DispatchQueue.main.async { replyHandler(["result": self.handleCommand(message["cmd"] as? String)]) }
    }

    /// The Watch's buttons (design §7: every action during a session is one Watch tap).
    /// Returns the text the Watch shows.
    private func handleCommand(_ cmd: String?) -> String {
        let result = runCommand(cmd)
        controlMessage = result
        broadcastControl(force: true)
        return result
    }

    private func runCommand(_ cmd: String?) -> String {
        switch cmd {
        case "start":
            guard !isRecording else { return "Already recording" }
            guard !startingFromWatch else { return "Running checks" }
            startFromWatch()
            return "Running checks"
        case "stop":
            guard isRecording else { return "Not recording" }
            stop()
            return "Stopped; the Watch sends the rest"
        case "calibrate": return startCalibration() ?? "Calibrating: follow the voice"
        case "trial":
            guard isRecording else { return "Press Start first" }
            markTrial()
            return trialStatus ?? "Trial marked"
        case "repeat":
            repeatPrompt()
            return "Repeating"
        case "acknowledge":
            alertCenter.acknowledge()
            audibility.tapReceived()
            return "OK"
        default: return "Unknown command"
        }
    }
}

extension StreamController: CMHeadphoneMotionManagerDelegate {
    func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) {
        DispatchQueue.main.async { self.airPodsConnected = true }
        ioQueue.async { self.ioAirPodsConnected = true }
        ioQueue.async {
            guard self.active else { return }
            self.logEvent("airpods_connected")
            self.calibrationResets.append(uptime())
        }
    }

    func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) {
        DispatchQueue.main.async { self.airPodsConnected = false }
        ioQueue.async { self.ioAirPodsConnected = false }
        ioQueue.async { if self.active { self.logEvent("airpods_disconnected") } }
    }
}
