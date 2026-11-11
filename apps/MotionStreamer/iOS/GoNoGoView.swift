import MotionStreamerCore
import SwiftUI

/// The Go / No-Go screen before Start (design §8 ①): Start is allowed only when every blocking
/// check passes; recording without a device is an explicit, logged choice.
struct GoNoGoView: View {
    @EnvironmentObject private var controller: StreamController
    @Environment(\.dismiss) private var dismiss
    @State private var result: GoNoGo?
    @State private var plannedMinutes = 60.0
    @State private var withoutAirPods = false
    @State private var withoutWatch = false
    @State private var voiceState: AudibilityCheck.State?
    private let poll = Timer.publish(every: 0.5, on: .main, in: .common).autoconnect()

    private var required: Set<String> {
        var r: Set<String> = ["phone", "watch", "airpods"]
        if withoutAirPods { r.remove("airpods") }
        if withoutWatch { r.remove("watch") }
        return r
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Session") {
                    Stepper("Planned: \(Int(plannedMinutes)) min", value: $plannedMinutes, in: 10...180, step: 10)
                    Toggle("Record without AirPods", isOn: $withoutAirPods)
                    Toggle("Record without the Watch", isOn: $withoutWatch)
                }
                Section("Voice") {
                    Button("Test the voice") {
                        controller.startAudibilityCheck()
                        voiceState = .waiting
                    }
                    if voiceState == .waiting {
                        Text("Tap OK on the Watch (or here) when you hear it.").font(.footnote)
                        Button("I heard it") { controller.audibility.tapReceived() }
                    }
                    if let voiceState, voiceState != .waiting {
                        Text(voiceState == .heard ? "Voice heard ✓" : "Not heard: raise the volume or switch output")
                            .foregroundStyle(voiceState == .heard ? .green : .red)
                    }
                }
                Section("Checks") {
                    Button("Run checks") { run() }
                    if let result {
                        ForEach(result.checks, id: \.id) { c in
                            HStack {
                                Image(
                                    systemName: c.ok
                                        ? "checkmark.circle.fill"
                                        : (c.blocking ? "xmark.octagon.fill" : "exclamationmark.triangle.fill")
                                )
                                .foregroundStyle(c.ok ? .green : (c.blocking ? .red : .orange))
                                Text(c.id.replacingOccurrences(of: "_", with: " "))
                                Spacer()
                                Text(c.detail).font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                Section {
                    Button("Start") {
                        controller.start()
                        dismiss()
                    }
                    .disabled(!(result?.canStart ?? false))
                }
            }
            .navigationTitle("Go / No-Go")
            .toolbar { Button("Cancel") { dismiss() } }
            .onReceive(poll) { _ in
                if voiceState == .waiting { voiceState = controller.audibility.tick() }
            }
        }
    }

    private func run() {
        let heard: Bool? = voiceState.map { $0 == .heard }
        controller.preflight(plannedMinutes: plannedMinutes, required: required, heardVoice: heard) { result = $0 }
    }
}
