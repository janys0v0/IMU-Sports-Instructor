import HealthKit
import MotionStreamerCore
import SwiftUI
import WatchKit

@main
struct MotionStreamerWatchApp: App {
    @WKApplicationDelegateAdaptor(WatchAppDelegate.self) private var delegate

    var body: some Scene {
        WindowGroup {
            WatchContentView()
                .environmentObject(WatchStreamer.shared)
        }
    }
}

final class WatchAppDelegate: NSObject, WKApplicationDelegate {
    func applicationDidFinishLaunching() {
        WatchStreamer.shared.activate()
    }

    /// watchOS relaunched the app after a crash while its workout kept running.
    func handleActiveWorkoutRecovery() {
        WatchStreamer.shared.recoverWorkout()
    }

    /// Called when the iPhone app launches this app with `HKHealthStore.startWatchApp`.
    func handle(_ workoutConfiguration: HKWorkoutConfiguration) {
        WatchStreamer.shared.launchedByPhone()
    }
}

struct WatchContentView: View {
    @EnvironmentObject private var streamer: WatchStreamer
    @State private var confirmStop = false

    var body: some View {
        // Re-checked every second so the screen notices when the iPhone stops answering.
        TimelineView(.periodic(from: .now, by: 1)) { context in
            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    if streamer.phoneInControl(nowUnix: context.date.timeIntervalSince1970),
                        let control = streamer.control
                    {
                        sessionControls(control)
                    } else {
                        watchOnlyControls
                    }
                    recordingInfo
                }
            }
        }
    }

    /// The same buttons as the iPhone, from the state it sends; each tap is a command to the iPhone.
    @ViewBuilder
    private func sessionControls(_ control: ControlState) -> some View {
        Label(phaseText(control), systemImage: "iphone").foregroundStyle(.green)
        if let alert = control.alert { Text(alert).font(.footnote).foregroundStyle(.red) }
        if let message = control.message { Text(message).font(.footnote) }
        if control.phase == .recording, control.trialsKept + control.trialsRedo > 0 {
            Text("Trials: \(control.trialsKept) kept, \(control.trialsRedo) redo").font(.footnote)
        }
        ForEach(control.buttons, id: \.self) { command in
            Button(control.label(command)) { streamer.send(command: command.rawValue) }
                .tint(tint(command))
                .font(command == .trial ? .title3.bold() : .body)
        }
    }

    /// Without the iPhone the Watch can still record alone; the iPhone joins it when it comes back.
    @ViewBuilder
    private var watchOnlyControls: some View {
        Label("iPhone not reachable", systemImage: "iphone.slash").foregroundStyle(.orange)
        Text(streamer.status).font(.footnote)
        Button(streamer.isRunning ? "Stop Watch recording" : "Record on Watch only") {
            if streamer.isRunning { confirmStop = true } else { streamer.start() }
        }
        .tint(streamer.isRunning ? .red : .gray)
        .confirmationDialog("Stop recording on the Watch?", isPresented: $confirmStop) {
            Button("Stop", role: .destructive) { streamer.stop() }
            Button("Keep recording", role: .cancel) {}
        } message: {
            Text("The iPhone may still be recording this session. The Watch keeps recording without it.")
        }
    }

    @ViewBuilder
    private var recordingInfo: some View {
        if streamer.isRunning {
            Text(String(format: "Watch %.1f Hz · %d samples", streamer.measuredHz, streamer.samplesRecorded))
                .font(.footnote)
            Text("High-rate: \(streamer.highRateStatus)").font(.footnote)
        }
        if let transfer = streamer.transfer, (transfer.mainTotal ?? 0) > 0 {
            Text(transfer.text).font(.footnote)
            Button("Resend session") { streamer.resendSession() }
        }
    }

    private func phaseText(_ control: ControlState) -> String {
        switch control.phase {
        case .idle: return "Ready"
        case .starting: return "Checking devices"
        case .recording:
            let minutes = control.startedUnix.map { Int((Date().timeIntervalSince1970 - $0) / 60) }
            return minutes.map { "Recording · \($0) min" } ?? "Recording"
        case .stopping: return "Stopping"
        }
    }

    private func tint(_ command: SessionCommand) -> Color {
        switch command {
        case .start: return .green
        case .stop: return .red
        case .trial: return .orange
        case .calibrate: return .blue
        case .repeatPrompt, .acknowledge: return .gray
        }
    }
}
