import Foundation

/// Builds the JSON packets that go over UDP and into the session files.
public enum PacketEncoder {
    /// Splits samples into packets of `MotionFormat.samplesPerPacket`, each with its own
    /// `first_index`, and encodes `header` + `"s"` (the samples) as one JSON object per packet.
    public static func imuPackets(header: [String: Any], samples: [MotionSample], firstIndex: Int)
        -> [Data]
    {
        stride(from: 0, to: samples.count, by: MotionFormat.samplesPerPacket).compactMap { start in
            let chunk = Array(samples[start..<min(start + MotionFormat.samplesPerPacket, samples.count)])
            var fields = header
            fields["first_index"] = firstIndex + start
            guard
                let headerData = try? JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys]),
                var json = String(data: headerData, encoding: .utf8), json.hasSuffix("}")
            else { return nil }
            json.removeLast()
            json += ",\"s\":" + samplesJSON(chunk) + "}"
            return Data(json.utf8)
        }
    }

    /// Any other packet (event, sync): one JSON object.
    public static func packet(_ fields: [String: Any]) -> Data? {
        try? JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys])
    }
}
