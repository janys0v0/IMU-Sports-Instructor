import Charts
import SwiftUI

/// The live motion plot shown while recording: one row per device with its rotation speed over the
/// last 10 s. A flat line when you move, or "no data", means that sensor is not recording.
public struct LiveMotionPanel: View {
    public struct Row: Equatable {
        public var device: String
        public var points: [LiveMotion.Point]
        /// Seconds since the device's last sample arrived (nil: none yet).
        public var age: Double?

        public init(device: String, points: [LiveMotion.Point], age: Double?) {
            self.device = device
            self.points = points
            self.age = age
        }
    }

    /// A device counts as silent after this long without a sample.
    public static let silentAfter: Double = 1.5

    public let rows: [Row]

    public init(rows: [Row]) { self.rows = rows }

    public var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Live motion · rotation speed, last 10 s").font(.caption).foregroundStyle(.secondary)
            ForEach(rows, id: \.device) { row in
                LiveMotionRow(row: row)
            }
        }
    }
}

struct LiveMotionRow: View {
    let row: LiveMotionPanel.Row

    private var silent: Bool { (row.age ?? .infinity) > LiveMotionPanel.silentAfter }
    private var color: Color { ["phone": .blue, "watch": .green, "airpods": .purple][row.device] ?? .gray }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(deviceNames[row.device] ?? row.device).font(.caption.bold())
                Spacer()
                if silent {
                    Text(row.age.map { String(format: "no data for %.0f s", $0) } ?? "no data yet")
                        .font(.caption.bold()).foregroundStyle(.red)
                } else if let now = row.points.last {
                    Text(String(format: "%.0f °/s", now.rotation)).font(.caption.monospacedDigit())
                }
            }
            Chart(Array(row.points.enumerated()), id: \.offset) { item in
                LineMark(x: .value("s", item.element.t), y: .value("°/s", item.element.rotation))
                    .foregroundStyle(color)
                    .interpolationMethod(.linear)
            }
            .chartXScale(domain: -LiveMotion.window...0)
            .chartYScale(domain: 0...max(200, (row.points.map(\.rotation).max() ?? 0) * 1.1))
            .chartXAxis {
                AxisMarks(values: [-10, -5, 0]) { value in
                    AxisGridLine()
                    AxisValueLabel { Text("\(value.as(Int.self) ?? 0) s") }
                }
            }
            .chartYAxis { AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) }
            .frame(height: 64)
            .opacity(silent ? 0.35 : 1)
        }
    }
}
