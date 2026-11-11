import Foundation

/// Small control messages between Watch and phone (sent with `WatchLink.sendMessage`).
/// Motion preview batches (`WatchBatch`) use the same channel; they have no `kind` key.
public struct LinkMessage: Codable, Equatable {
    public enum Kind: String, Codable {
        /// Phone → Watch: this chunk arrived and its checksum matched.
        case ack
        /// Phone → Watch: this chunk arrived damaged; send it again.
        case resend
        /// Watch → phone, at Stop: how many chunks exist, so the phone can show N / M.
        case summary
        /// Watch → phone: the workout ended without a Stop (crown press, watchOS).
        case workoutEnded = "workout_ended"
        /// Watch → phone: the high-rate stream could not start or stopped.
        case highRateFailed = "high_rate_failed"
        /// Phone → Watch: send every chunk of the session again.
        case resendAll = "resend_all"
        /// Phone → Watch: speak this phrase (`detail`) on the Watch (no AirPods connected).
        case speak
        /// Watch → phone: the phrase `utterance` has finished speaking.
        case spoken
    }

    public var kind: Kind
    public var session: String
    public var file: String?
    public var sha256: String?
    public var chunks60Hz: Int?
    public var chunksHighRate: Int?
    public var detail: String?
    /// Identifies a phrase for `speak` / `spoken`.
    public var utterance: String?

    public init(
        kind: Kind, session: String, file: String? = nil, sha256: String? = nil, chunks60Hz: Int? = nil,
        chunksHighRate: Int? = nil, detail: String? = nil, utterance: String? = nil
    ) {
        self.kind = kind
        self.session = session
        self.file = file
        self.sha256 = sha256
        self.chunks60Hz = chunks60Hz
        self.chunksHighRate = chunksHighRate
        self.detail = detail
        self.utterance = utterance
    }

    public var encoded: Data { (try? JSONEncoder().encode(self)) ?? Data() }

    /// Decodes a control message; nil for anything else (e.g. a motion preview batch).
    public static func decode(_ data: Data) -> LinkMessage? {
        try? JSONDecoder().decode(LinkMessage.self, from: data)
    }
}

/// Metadata keys sent with every transferred file.
public enum TransferKey {
    public static let session = "session"
    /// Path inside the session folder, e.g. "watch/000003.jsonl".
    public static let file = "file"
    public static let sha256 = "sha256"
    /// "60hz", "hf" or "journal".
    public static let kind = "kind"
}
