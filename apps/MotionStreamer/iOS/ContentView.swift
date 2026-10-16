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
        .onAppear { if ReplaySettings.autoStart { controller.start() } }
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
                controller.isRecording ? controller.stop() : controller.start()
            } label: {
                Label(
                    controller.isRecording ? "Stop" : "Start",
                    systemImage: controller.isRecording ? "stop.circle.fill" : "record.circle"
                )
                .frame(maxWidth: .infinity)
                .font(.headline)
            }
            .tint(controller.isRecording ? .red : .green)
            if controller.isRecording {
                Text("\(controller.sessionID) · \(formatDuration(controller.elapsed))")
                    .font(.footnote.monospaced())
                HStack {
                    Button("Calibrate") {
                        controller.startCalibration()
                        pocketMode = true
                        controller.setPocketMode(true)
                    }
                    .buttonStyle(.bordered)
                    .disabled(controller.calibrationStatus != nil)
                    Spacer()
                    Button("Trial marker") { controller.markTrial() }
                        .buttonStyle(.bordered)
                    Spacer()
                    Button("Pocket mode") {
                        pocketMode = true
                        controller.setPocketMode(true)
                    }
                    .buttonStyle(.bordered)
                }
                Text(
                    "Calibrate: tap, pocket the phone within 10 s and stand straight. One buzz: hold still 3 s. Two buzzes: done."
                )
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
            Text(title).font(.subheadline.bold())
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
