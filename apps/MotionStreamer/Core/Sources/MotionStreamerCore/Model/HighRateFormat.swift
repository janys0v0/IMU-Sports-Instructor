import Foundation

/// Binary chunk format for the high-rate Watch stream (design §2):
/// one JSON header line ending in "\n", then little-endian records, each a 1-byte tag and a
/// fixed-size body:
///   tag 1 accel  (800 Hz): t Float64 · ax ay az Float32           = 1 + 20 bytes
///   tag 2 motion (200 Hz): t Float64 · 13 × Float32 (MotionSample) = 1 + 60 bytes
public enum HighRateFormat {
    public static let version = 1
    public static let accelTag: UInt8 = 1
    public static let motionTag: UInt8 = 2
    public static let accelSize = 1 + 8 + 3 * 4
    public static let motionSize = 1 + 8 + 13 * 4

    public enum Record: Equatable {
        /// [t, ax, ay, az] in g.
        case accel([Double])
        /// A full 14-value motion sample.
        case motion(MotionSample)
    }

    public static func header(_ fields: [String: Any]) -> Data {
        var f = fields
        f["format"] = "watch_hf"
        f["version"] = version
        f["records"] = [
            "1": "accel: t f64, ax ay az f32 (g)",
            "2": "motion: t f64, qx qy qz qw ax ay az gx gy gz rx ry rz f32",
        ]
        return (PacketEncoder.packet(f) ?? Data("{}".utf8)) + Data([0x0A])
    }

    public static func encode(_ record: Record) -> Data {
        var out = Data()
        func f64(_ v: Double) { withUnsafeBytes(of: v.bitPattern.littleEndian) { out.append(contentsOf: $0) } }
        func f32(_ v: Double) { withUnsafeBytes(of: Float(v).bitPattern.littleEndian) { out.append(contentsOf: $0) } }
        switch record {
        case .accel(let a):
            out.append(accelTag)
            f64(a[0])
            a[1...3].forEach(f32)
        case .motion(let s):
            out.append(motionTag)
            f64(s[0])
            s[1...13].forEach(f32)
        }
        return out
    }

    /// Splits a chunk into its header and records. Stops at the first incomplete or unknown record.
    public static func decode(_ data: Data) -> (header: [String: Any], records: [Record]) {
        let bytes = [UInt8](data)
        guard let nl = bytes.firstIndex(of: 0x0A) else { return ([:], []) }
        let header = (try? JSONSerialization.jsonObject(with: Data(bytes[..<nl])) as? [String: Any]) ?? [:]
        var records: [Record] = []
        var i = nl + 1
        func f64(_ at: Int) -> Double {
            Double(
                bitPattern: bytes[at..<at + 8].enumerated().reduce(UInt64(0)) {
                    $0 | UInt64($1.element) << (8 * $1.offset)
                })
        }
        func f32(_ at: Int) -> Double {
            Double(
                Float(
                    bitPattern: bytes[at..<at + 4].enumerated().reduce(UInt32(0)) {
                        $0 | UInt32($1.element) << (8 * $1.offset)
                    }))
        }
        while i < bytes.count {
            let size = recordSize(bytes[i])
            guard size > 0, i + size <= bytes.count else { break }
            if bytes[i] == accelTag {
                records.append(.accel([f64(i + 1)] + (0..<3).map { f32(i + 9 + 4 * $0) }))
            } else {
                records.append(.motion([f64(i + 1)] + (0..<13).map { f32(i + 9 + 4 * $0) }))
            }
            i += size
        }
        return (header, records)
    }

    /// Bytes that hold the header and whole records only (used to trim a torn chunk).
    public static func wholeRecordLength(_ data: Data) -> Int {
        let bytes = [UInt8](data)
        guard let nl = bytes.firstIndex(of: 0x0A) else { return 0 }
        var i = nl + 1
        while i < bytes.count {
            let size = recordSize(bytes[i])
            guard size > 0, i + size <= bytes.count else { break }
            i += size
        }
        return i
    }

    static func recordSize(_ tag: UInt8) -> Int {
        switch tag {
        case accelTag: return accelSize
        case motionTag: return motionSize
        default: return 0
        }
    }
}
