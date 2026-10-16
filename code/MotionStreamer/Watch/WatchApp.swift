import HealthKit
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

    /// Called when the iPhone app launches this app with `HKHealthStore.startWatchApp`.
    func handle(_ workoutConfiguration: HKWorkoutConfiguration) {
        WatchStreamer.shared.start()
    }
}

struct WatchContentView: View {
    @EnvironmentObject private var streamer: WatchStreamer

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 6) {
                Label(
                    streamer.phoneReachable ? "iPhone connected" : "iPhone not reachable",
                    systemImage: streamer.phoneReachable ? "iphone" : "iphone.slash"
                )
                .foregroundStyle(streamer.phoneReachable ? .green : .orange)
                Text(streamer.status).font(.footnote)
                if streamer.isRunning {
                    Text(String(format: "%.1f Hz", streamer.measuredHz))
                    Text("Samples: \(streamer.samplesRecorded)")
                    Text("Queued batches: \(streamer.pendingBatches)")
                    if streamer.droppedSamples > 0 {
                        Text("Dropped: \(streamer.droppedSamples)").foregroundStyle(.red)
                    }
                }
                Button(streamer.isRunning ? "Stop" : "Start") {
                    streamer.isRunning ? streamer.stop() : streamer.start()
                }
                .tint(streamer.isRunning ? .red : .green)
                Text("Normally started from the iPhone app.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
