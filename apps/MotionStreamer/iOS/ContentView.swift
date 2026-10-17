import MotionStreamerCore
import SwiftUI

@main
struct MotionStreamerApp: App {
    @StateObject private var controller = StreamController()
    @StateObject private var headphones = HeadphoneMonitor()

    var body: some Scene {
        WindowGroup {
            ContentView().environmentObject(controller).environmentObject(headphones)
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var controller: StreamController
    @EnvironmentObject private var headphones: HeadphoneMonitor
    @State private var pocketMode = false
    @State private var lastSession = ""
    @State private var checkReview: ReviewData?
    @State private var showReview = false
    @State private var showGoNoGo = false

    var body: some View {
        NavigationStack {
            Form {
                setupSection
                controlSection
                statusSection
                airPodsSection
                if !controller.recentEvents.isEmpty {
                    Section("Events") {
                        ForEach(controller.recentEvents, id: \.self) { Text($0).font(.footnote) }
                    }
                }
            }
            .navigationTitle("MotionStreamer")
        }
        .overlay { if pocketMode { pocketOverlay } }
        .alert(
            "Recording was interrupted",
            isPresented: Binding(
                get: { controller.interrupted != nil && !controller.isRecording },
                set: { _ in })
        ) {
            Button("Resume") { controller.resumeInterrupted() }
            Button("Close it", role: .cancel) { controller.closeInterrupted() }
        } message: {
            Text(
                "Session \(controller.interrupted?.id ?? "") stopped at \(controller.interrupted?.at.formatted(date: .omitted, time: .standard) ?? ""). Resume it as a new segment?"
            )
        }
        .onAppear {
            if ReplaySettings.autoStart { controller.start() }
            for step in ReplaySettings.script {
                DispatchQueue.main.asyncAfter(deadline: .now() + step.at) {
                    switch step.action {
                    case "gonogo":
                        controller.preflight(plannedMinutes: 10, required: ["phone"], heardVoice: nil) {
                            controller.lastGoNoGo = $0
                        }
                    case "start": controller.start()
                    case "calibrate": controller.startCalibration()
                    case "trial": controller.markTrial()
                    case "stop": controller.stop()
                    default: break
                    }
                }
            }
            if let delay = ReplaySettings.openReviewAfter {
                DispatchQueue.main.asyncAfter(deadline: .now() + delay) { showReview = true }
            }
        }
        .sheet(isPresented: $showGoNoGo) { GoNoGoView().environmentObject(controller) }
        .sheet(isPresented: $showReview) {
            NavigationStack { ReviewContainer(sessionID: controller.sessionID) }.environmentObject(controller)
        }
        .alert(
            "Cannot start",
            isPresented: Binding(
                get: { controller.errorMessage != nil },
                set: { if !$0 { controller.errorMessage = nil } })
        ) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(controller.errorMessage ?? "")
        }
    }

    private var setupSection: some View {
        Section("Setup") {
            LabeledContent("Mac IP") {
                TextField("none: record on phone", text: $controller.macHost)
                    .keyboardType(.numbersAndPunctuation)
                    .multilineTextAlignment(.trailing)
            }
            LabeledContent("Port") {
                TextField("5005", text: $controller.macPort)
                    .keyboardType(.numberPad)
                    .multilineTextAlignment(.trailing)
            }
            LabeledContent("Participant") {
                TextField("P01", text: $controller.participant).multilineTextAlignment(.trailing)
            }
            LabeledContent("Activity") {
                TextField("test", text: $controller.activity).multilineTextAlignment(.trailing)
            }
            Picker("Watch wrist", selection: $controller.wrist) {
                ForEach(WatchWrist.allCases) { Text($0.rawValue.capitalized).tag($0) }
            }
            .pickerStyle(.segmented)
            LabeledContent("Face at calibration") {
                TextField("the net", text: $controller.landmark).multilineTextAlignment(.trailing)
            }
            Stepper(
                "Recalibrate every \(Int(controller.reminderMinutes)) min", value: $controller.reminderMinutes,
                in: 2...60,
                step: 1)
            Picker("Keep recording in pocket", selection: $controller.keepAliveMethod) {
                Text("Location (recommended)").tag(KeepAlivePolicy.Method.location)
                Text("Workout mirroring").tag(KeepAlivePolicy.Method.mirroring)
                Text("Pocket mode only").tag(KeepAlivePolicy.Method.pocketMode)
            }
            Picker("Phone screen faces", selection: $controller.pocketScreen) {
                Text("Leg").tag(PocketScreen.leg)
                Text("Outward").tag(PocketScreen.outward)
            }
            Text("Put the iPhone in the \(controller.wrist.rawValue) front trouser pocket, flat against the thigh.")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .disabled(controller.isRecording)
    }

    private var controlSection: some View {
        Section {
            Button {
                if controller.isRecording {
                    lastSession = controller.sessionID
                    controller.stop()
                    // The session check reads the closed chunks once Stop has written them.
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
                        controller.loadReview(lastSession) { checkReview = $0 }
                    }
                } else {
                    showGoNoGo = true
                }
            } label: {
                Label(
                    controller.isRecording ? "Stop" : "Start",
                    systemImage: controller.isRecording ? "stop.circle.fill" : "record.circle"
                )
                .frame(maxWidth: .infinity)
                .font(.headline)
            }
            .tint(controller.isRecording ? .red : .green)
            if controller.isRecording || !lastSession.isEmpty {
                NavigationLink("Review saved data") {
                    ReviewContainer(sessionID: controller.isRecording ? controller.sessionID : lastSession)
                }
            }
            if let checkReview, !controller.isRecording {
                SessionCheckCard(data: checkReview)
            }
            if let status = controller.trialStatus, controller.isRecording {
                Text(status).font(.headline)
            }
            if let verdict = controller.courtExit, !controller.isRecording {
                CourtExitCard(verdict: verdict)
            }
            if controller.isRecording {
                Text("\(controller.sessionID) · \(formatDuration(controller.elapsed))")
                    .font(.footnote.monospaced())
                // The same session buttons as the Watch (ControlState.buttons); Start / Stop is above.
                let control = controller.controlState
                HStack {
                    ForEach(control.buttons.filter { $0 != .start && $0 != .stop }, id: \.self) { command in
                        Button(control.label(command)) {
                            controller.perform(command)
                            if command == .calibrate {
                                pocketMode = true
                                controller.setPocketMode(true)
                            }
                        }
                        .buttonStyle(.bordered)
                    }
                    Spacer()
                    Button("Pocket mode") {
                        pocketMode = true
                        controller.setPocketMode(true)
                    }
                    .buttonStyle(.bordered)
                }
                Text("Calibrate: follow the voice (start it from the Watch while the phone is in your pocket).")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var statusSection: some View {
        Section("Status") {
            LabeledContent("Mac", value: macText)
            LabeledContent("Watch", value: controller.watchReachable ? "Reachable" : "Not reachable")
            LabeledContent("Watch model", value: controller.watchInfo)
            streamRow("iPhone stream", controller.phone)
            streamRow("Watch stream", controller.watch)
            LabeledContent("Watch chunks", value: controller.watchTransfer)
            LabeledContent("AirPods", value: controller.airPodsConnected ? "Connected" : "Not connected")
            streamRow("AirPods stream", controller.head)
        }
    }

    private var airPodsSection: some View {
        Section("AirPods") {
            Button(headphones.isRunning ? "Stop AirPods check" : "Check AirPods") { headphones.toggle() }
            LabeledContent("State", value: headphones.connection)
            LabeledContent("Permission", value: headphones.authorization)
            if headphones.samples > 0 {
                LabeledContent(
                    "Rate", value: String(format: "%.1f Hz · %d samples", headphones.measuredHz, headphones.samples))
                LabeledContent("Sensor", value: headphones.sensor)
                Text(
                    String(
                        format: "pitch %+.0f°  roll %+.0f°  yaw %+.0f°",
                        headphones.angles.pitch, headphones.angles.roll, headphones.angles.yaw)
                )
                .font(.footnote.monospaced())
            }
            Text("Wear both AirPods, then nod and turn your head: pitch and yaw should follow.")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }

    private var macText: String {
        guard controller.isRecording else { return controller.macStatus }
        var text = "sent \(controller.packetsSent)"
        if let received = controller.macReceived { text += ", Mac got \(received)" }
        if let age = controller.lastAckAge, age > 3 { text += " (no ack \(Int(age)) s)" }
        if controller.macReceived == nil { text += " (no ack yet)" }
        return text
    }

    private func streamRow(_ title: String, _ s: StreamSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                if controller.isRecording { LiveDotView(dots: LiveDots(snapshot: s, baselineHz: s.nominalHz)) }
                Text(title).font(.subheadline.bold())
            }
            Text(
                String(
                    format: "%.1f Hz (device %.1f) · %d samples · coverage %.0f%%",
                    s.measuredHz, s.nominalHz, s.samples, s.coverage * 100)
            )
            .font(.footnote.monospaced())
            .foregroundStyle(s.coverage >= 0.95 || s.samples == 0 ? Color.primary : Color.orange)
            if s.missing > 0 {
                Text("Missing samples: \(s.missing)").font(.footnote).foregroundStyle(.red)
            }
            if let age = s.lastPacketAge, age > 1 {
                Text(String(format: "Last packet %.0f s ago", age)).font(.footnote).foregroundStyle(.orange)
            }
        }
    }

    /// Black screen while the phone is in a pocket. Long-press to leave.
    private var pocketOverlay: some View {
        Color.black
            .ignoresSafeArea()
            .overlay {
                VStack(spacing: 8) {
                    Text("Recording").font(.title2).foregroundStyle(.white)
                    if let status = controller.calibrationStatus {
                        Text(status).font(.title3).foregroundStyle(.yellow)
                    }
                    Text("Long-press to unlock").foregroundStyle(.gray)
                }
            }
            .onLongPressGesture(minimumDuration: 1.5) {
                pocketMode = false
                controller.setPocketMode(false)
            }
    }

    private func formatDuration(_ seconds: Double) -> String {
        let s = Int(seconds)
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}

/// Loads the review from disk and refreshes it every 10 s while the session records.
struct ReviewContainer: View {
    @EnvironmentObject private var controller: StreamController
    let sessionID: String
    @State private var review: ReviewData?
    private let refresh = Timer.publish(every: 10, on: .main, in: .common).autoconnect()

    var body: some View {
        ScrollView {
            if let review {
                ReviewScreen(data: review)
            } else {
                ProgressView("Reading saved chunks…").padding()
            }
        }
        .navigationTitle("Review")
        .onAppear(perform: load)
        .onReceive(refresh) { _ in if controller.isRecording { load() } }
    }

    private func load() { controller.loadReview(sessionID) { review = $0 } }
}

/// The court-exit check after Stop (design §8 ④).
struct CourtExitCard: View {
    let verdict: CourtExitCheck.Verdict

    var body: some View {
        switch verdict {
        case .safe:
            Label("Safe to leave", systemImage: "checkmark.seal.fill").foregroundStyle(.green).font(.headline)
        case .redo(let trials):
            Label(
                "Redo trials \(trials.map(String.init).joined(separator: ", "))", systemImage: "arrow.counterclockwise"
            )
            .foregroundStyle(.orange).font(.headline)
        case .waiting(let why):
            Label("Not yet: \(why)", systemImage: "hourglass").foregroundStyle(.secondary)
        }
    }
}
