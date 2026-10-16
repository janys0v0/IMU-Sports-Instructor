import Foundation

/// Turns problems the watchdog sees into spoken alerts (design §8): a problem must last 2 s before
/// it alerts, each problem alerts at most once a minute, a 🟡 lasting 30 s becomes 🔴, a 🔴 repeats
/// every 30 s until fixed or acknowledged, and a fixed 🔴 says it has recovered.
public final class AlertCenter {
    public enum Level: String { case yellow, red }

    public struct Active {
        public var id: String
        public var level: Level
        public var since: Double
        public var lastSpoken: Double?
        /// The level it was last spoken at (an escalation to 🔴 is spoken at once).
        public var spokenLevel: Level?
        public var acknowledged = false
        public var detail: String?
    }

    public static let debounce = 2.0
    public static let minGap = 60.0
    public static let escalateAfter = 30.0
    public static let redRepeat = 30.0
    /// Yellow alert id → the red alert it escalates to (if different).
    public static let escalation: [String: String] = ["rate_dropping": "low_rate", "battery_low": "battery_critical"]

    public private(set) var active: [String: Active] = [:]
    /// Logs `alert`, `alert_cleared` and `alert_acknowledged` events.
    public var onEvent: ((String, [String: Any]) -> Void)?

    private let speaker: Speaker
    private let clock: Clock
    private let script: VoiceScript
    private var lastSpokenByID: [String: Double] = [:]

    public init(speaker: Speaker, clock: Clock, script: VoiceScript = .shared) {
        self.speaker = speaker
        self.clock = clock
        self.script = script
    }

    /// Reports the problems seen now (id → level, optional detail). Problems not listed are cleared.
    public func update(_ problems: [String: (level: Level, detail: String?)]) {
        let now = clock.uptime
        for (id, p) in problems {
            if active[id] == nil { active[id] = Active(id: id, level: p.level, since: now, detail: p.detail) }
            active[id]!.detail = p.detail ?? active[id]!.detail
            if p.level == .red { active[id]!.level = .red }
        }
        for id in active.keys where problems[id] == nil { clear(id) }
        for id in active.keys.sorted() { evaluate(id, now: now) }
    }

    /// One tap on the Watch: stops the repeats of every active 🔴.
    public func acknowledge() {
        for id in active.keys where active[id]!.level == .red { active[id]!.acknowledged = true }
        onEvent?("alert_acknowledged", ["ids": active.keys.sorted()])
    }

    private func evaluate(_ id: String, now: Double) {
        guard var a = active[id], now - a.since >= Self.debounce else { return }
        if a.level == .yellow, now - a.since >= Self.escalateAfter { a.level = .red }
        let spokenID = a.level == .red ? (Self.escalation[id] ?? id) : id
        let due: Bool
        if let last = a.lastSpoken {
            let escalated = a.level == .red && a.spokenLevel == .yellow
            due = escalated || (a.level == .red && !a.acknowledged && now - last >= Self.redRepeat)
        } else {
            due = (lastSpokenByID[spokenID].map { now - $0 >= Self.minGap } ?? true) || a.level == .red
        }
        if due, let alert = script.alert(spokenID) {
            a.lastSpoken = now
            a.spokenLevel = a.level
            lastSpokenByID[spokenID] = now
            speaker.say(alert.text, id: spokenID, priority: a.level == .red ? .red : .warn)
            onEvent?("alert", ["id": spokenID, "level": a.level.rawValue, "detail": a.detail ?? ""])
        }
        active[id] = a
    }

    private func clear(_ id: String) {
        guard let a = active.removeValue(forKey: id) else { return }
        onEvent?("alert_cleared", ["id": id, "after_s": clock.uptime - a.since])
        if a.level == .red, a.lastSpoken != nil, let text = recoveredText(id) {
            speaker.say(text, id: "recovered", priority: .warn)
        }
    }

    private func recoveredText(_ id: String) -> String? {
        switch id {
        case "airpods_disconnected", "airpods_switched": return script.alert("airpods_back")?.text
        case "watch_stopped", "high_rate_failed": return script.alert("watch_back")?.text
        default: return nil
        }
    }
}
