import Foundation

/// The session controls (design §7). Either device sends one of these to the iPhone, which owns
/// the session; the Watch never starts or stops a session on its own while the iPhone is reachable.
public enum SessionCommand: String, CaseIterable, Codable {
    case start, stop, calibrate, trial
    case repeatPrompt = "repeat"
    case acknowledge
}

/// What the iPhone broadcasts to the Watch after every change, so both screens show the same
/// state and the same buttons.
public struct ControlState: Codable, Equatable {
    public enum Phase: String, Codable {
        case idle, starting, recording, stopping
    }

    /// The Watch shows "iPhone not reachable" when the newest state is older than this.
    public static let staleAfter: Double = 10
    static let messageKey = "control"

    public var phase: Phase = .idle
    public var sessionID: String?
    public var startedUnix: Double?
    public var calibrating = false
    public var openTrial: Int?
    public var trialsKept = 0
    public var trialsRedo = 0
    /// The most urgent active alert, if any.
    public var alert: String?
    /// The result of the last command ("Calibrating: follow the voice", "No-Go: watch battery", …).
    public var message: String?
    public var sentUnix: Double = 0

    public init() {}

    /// The buttons both devices show, in order. One rule, so the two screens never differ.
    public var buttons: [SessionCommand] {
        switch phase {
        case .idle: return [.start]
        case .starting, .stopping: return []
        case .recording:
            return calibrating
                ? [.repeatPrompt, .acknowledge, .stop] : [.trial, .calibrate, .repeatPrompt, .acknowledge, .stop]
        }
    }

    public func label(_ command: SessionCommand) -> String {
        switch command {
        case .start: return "Start"
        case .stop: return "Stop"
        case .calibrate: return "Calibrate"
        case .trial: return openTrial.map { "End trial \($0)" } ?? "Trial"
        case .repeatPrompt: return "Repeat"
        case .acknowledge: return "OK"
        }
    }

    public func isStale(nowUnix: Double) -> Bool { nowUnix - sentUnix > Self.staleAfter }

    /// As a WatchConnectivity message or application context.
    public func wcMessage() -> [String: Any] {
        [Self.messageKey: (try? JSONEncoder().encode(self)) ?? Data()]
    }

    public init?(message: [String: Any]) {
        guard let data = message[Self.messageKey] as? Data,
            let state = try? JSONDecoder().decode(ControlState.self, from: data)
        else { return nil }
        self = state
    }
}
