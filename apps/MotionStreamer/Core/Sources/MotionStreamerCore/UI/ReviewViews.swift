import Charts
import SwiftUI

/// Color of a status dot.
public func dotColor(_ dot: Dot) -> Color {
    switch dot {
    case .green: return .green
    case .yellow: return .yellow
    case .red: return .red
    }
}

public func verdictColor(_ verdict: String) -> Color {
    switch verdict {
    case "PASS": return .green
    case "WARN": return .orange
    default: return .red
    }
}

/// Fixed display order and names of the devices.
let deviceOrder = ["phone", "watch", "airpods"]
let deviceNames = ["phone": "Phone", "watch": "Watch", "airpods": "AirPods"]

/// The review screen (design §6 ②): whole-session timeline and last-60-s plots, from disk.
public struct ReviewScreen: View {
    public let data: ReviewData
    /// Time zone for event times (local on the phone; fixed in snapshot tests).
    public let timeZone: TimeZone
    @State private var selected: String

    public init(data: ReviewData, timeZone: TimeZone = .current) {
        self.data = data
        self.timeZone = timeZone
        _selected = State(initialValue: deviceOrder.first { data.devices[$0] != nil } ?? "phone")
    }

    private var devices: [ReviewData.Device] { deviceOrder.compactMap { data.devices[$0] } }

    public var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text(data.sessionID).font(.headline.monospaced())
                Spacer()
                if let s = data.start, let e = data.end {
                    Text(Self.duration(e - s)).font(.subheadline.monospaced())
                }
            }
            Text("Whole session · \(data.chunksRead) saved chunks").font(.subheadline.bold())
            ForEach(devices, id: \.device) { d in
                HStack(spacing: 8) {
                    Text(deviceNames[d.device] ?? d.device).font(.caption).frame(width: 56, alignment: .leading)
                    TimelineBar(device: d, start: data.start ?? 0, end: data.end ?? 1, calibrations: data.calibrations)
                        .frame(height: 14)
                }
            }
            HStack(spacing: 6) {
                ForEach(devices, id: \.device) { d in
                    Button {
                        selected = d.device
                    } label: {
                        Text(deviceNames[d.device] ?? d.device)
                            .font(.caption.bold())
                            .padding(.horizontal, 10)
                            .padding(.vertical, 4)
                            .background(
                                selected == d.device ? Color.accentColor.opacity(0.2) : Color.gray.opacity(0.12)
                            )
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }
            if let d = data.devices[selected] {
                Text("Last 60 s").font(.subheadline.bold())
                PlotRow(title: "rotation (rad/s)", points: d.rotation)
                PlotRow(title: "acceleration (g)", points: d.acceleration)
                PlotRow(title: "angle since calibration (°)", points: d.angle)
            }
            ForEach(devices, id: \.device) { d in
                HStack {
                    Circle().fill(verdictColor(d.verdict)).frame(width: 8, height: 8)
                    Text(
                        String(
                            format: "%@ %.0f Hz · %.1f%% · %d gaps", deviceNames[d.device] ?? d.device,
                            d.stats.deliveredHz, d.stats.coverage * 100, d.stats.gapsOverThreshold)
                    )
                    .font(.caption.monospaced())
                }
            }
            if !data.events.isEmpty {
                Text(
                    data.events.suffix(4).map {
                        "\(Self.clock($0.t, timeZone)) \($0.name.replacingOccurrences(of: "_", with: " "))"
                    }
                    .joined(separator: " · ")
                )
                .font(.caption2)
                .foregroundStyle(.secondary)
            }
        }
        .padding()
    }

    static func duration(_ s: Double) -> String { String(format: "%d:%02d", Int(s) / 60, Int(s) % 60) }

    static func clock(_ unix: Double, _ timeZone: TimeZone) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        f.timeZone = timeZone
        return f.string(from: Date(timeIntervalSince1970: unix))
    }
}

/// One device's coverage over the session: green where data was saved; calibrations marked.
struct TimelineBar: View {
    let device: ReviewData.Device
    let start: Double
    let end: Double
    let calibrations: [Double]

    var body: some View {
        Canvas { context, size in
            let span = max(end - start, 1e-6)
            func x(_ t: Double) -> CGFloat { CGFloat((t - start) / span) * size.width }
            context.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.red.opacity(0.35)))
            for r in device.covered {
                let rect = CGRect(
                    x: x(r.lowerBound), y: 0, width: max(1, x(r.upperBound) - x(r.lowerBound)), height: size.height)
                context.fill(Path(rect), with: .color(.green))
            }
            for c in calibrations where c >= start && c <= end {
                context.fill(Path(CGRect(x: x(c) - 1, y: 0, width: 2, height: size.height)), with: .color(.blue))
            }
        }
    }
}

struct PlotRow: View {
    let title: String
    let points: [ReviewData.Point]

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption2).foregroundStyle(.secondary)
            Chart(Array(points.enumerated()), id: \.offset) { item in
                LineMark(x: .value("t", item.element.t), y: .value(title, item.element.value))
            }
            .chartXScale(domain: (points.first?.t ?? 0)...(max(points.last?.t ?? 1, (points.first?.t ?? 0) + 1e-3)))
            .chartXAxis(.hidden)
            .frame(height: 60)
        }
    }
}

/// The session check card shown after Stop (design §6 ③).
public struct SessionCheckCard: View {
    public let data: ReviewData

    public init(data: ReviewData) { self.data = data }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Session check").font(.headline)
                Spacer()
                Text(data.verdict).font(.title2.bold()).foregroundStyle(verdictColor(data.verdict))
            }
            ForEach(deviceOrder.compactMap { data.devices[$0] }, id: \.device) { d in
                HStack {
                    Text(deviceNames[d.device] ?? d.device).frame(width: 64, alignment: .leading)
                    Text(
                        String(
                            format: "%.1f%% · longest gap %.1f s", d.stats.coverage * 100, d.stats.longestGapMs / 1000)
                    )
                    .font(.caption.monospaced())
                    Spacer()
                    Text(d.verdict).font(.caption.bold()).foregroundStyle(verdictColor(d.verdict))
                }
            }
            Text("\(data.calibrations.count) calibrations · \(data.chunksRead) chunks saved").font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding()
    }
}

/// A stream's live status dot (worst of age, rate and coverage).
public struct LiveDotView: View {
    public let dots: LiveDots
    public init(dots: LiveDots) { self.dots = dots }
    public var body: some View { Circle().fill(dotColor(dots.worst)).frame(width: 10, height: 10) }
}
