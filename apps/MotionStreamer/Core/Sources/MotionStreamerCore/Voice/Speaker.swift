import Foundation

/// The spoken script (`Resources/voice_prompts.json`, design §7-§8).
public struct VoiceScript {
    public let raw: [String: Any]

    public static let shared: VoiceScript = {
        guard let url = Bundle.module.url(forResource: "voice_prompts", withExtension: "json"),
            let data = try? Data(contentsOf: url),
            let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { fatalError("voice_prompts.json missing from MotionStreamerCore resources") }
        return VoiceScript(raw: raw)
    }()

    public init(raw: [String: Any]) { self.raw = raw }

    public func calibration(_ id: String) -> String { section("calibration")[id] as? String ?? id }
    public func reason(_ id: String) -> String { section("reasons")[id] as? String ?? id }
    public func reminder(_ id: String) -> String { section("reminder")[id] as? String ?? id }
    public var audibility: String { raw["audibility"] as? String ?? "" }
    public var bannedWords: [String] { raw["banned_words"] as? [String] ?? [] }

    /// (level, text) of an alert, e.g. ("red", "Stop. The AirPods disconnected.").
    public func alert(_ id: String) -> (level: String, text: String)? {
        guard let a = section("alerts")[id] as? [String: String], let level = a["level"], let text = a["text"]
        else { return nil }
        return (level, text)
    }

    public var alertIDs: [String] { section("alerts").keys.sorted() }

    public func section(_ name: String) -> [String: Any] { raw[name] as? [String: Any] ?? [:] }

    /// Replaces `{name}` placeholders.
    public static func fill(_ text: String, _ values: [String: String]) -> String {
        values.reduce(text) { $0.replacingOccurrences(of: "{\($1.key)}", with: $1.value) }
    }

    public static func wordCount(_ text: String) -> Int {
        text.split { $0 == " " }.filter { $0.contains { $0.isLetter || $0.isNumber } }.count
    }
}

/// Speaks prompts and alerts (design §7 voice rules): one at a time, 🔴 alerts interrupt anything,
/// 🟡 warnings wait while a calibration runs, the first available output is used (AirPods → Watch
/// → phone speaker), every phrase is logged with its start and finish time, and Repeat replays
/// the last one.
public final class Speaker {
    public enum Priority: Int, Comparable {
        case warn = 0, prompt = 1, red = 2
        public static func < (a: Priority, b: Priority) -> Bool { a.rawValue < b.rawValue }
    }

    public struct Output {
        public var name: String
        public var isAvailable: () -> Bool
        public var voice: Voice
        public init(name: String, isAvailable: @escaping () -> Bool, voice: Voice) {
            self.name = name
            self.isAvailable = isAvailable
            self.voice = voice
        }
    }

    struct Utterance {
        var id: String
        var text: String
        var priority: Priority
        var completion: ((Bool) -> Void)?
    }

    public var outputs: [Output]
    /// While true, warnings wait (a calibration is running).
    public var holdWarnings = false {
        didSet { if !holdWarnings { startNextIfIdle() } }
    }
    /// Logs `prompt`, `voice_unavailable` and `voice_repeat` events.
    public var onEvent: ((String, [String: Any]) -> Void)?
    /// Haptic backup, played with every phrase.
    public var haptics: Haptics?

    private let clock: Clock
    private var queue: [Utterance] = []
    private var current: (utterance: Utterance, output: Output, start: Double)?
    public private(set) var last: (id: String, text: String)?

    public init(clock: Clock, outputs: [Output]) {
        self.clock = clock
        self.outputs = outputs
    }

    public var isSpeaking: Bool { current != nil }

    /// Queues a phrase. `completion(interrupted)` runs when it has finished (or was cut off).
    public func say(_ text: String, id: String, priority: Priority = .prompt, completion: ((Bool) -> Void)? = nil) {
        let u = Utterance(id: id, text: text, priority: priority, completion: completion)
        if priority == .red, let c = current, c.utterance.priority < .red {
            interruptCurrent()
            queue.insert(u, at: 0)
            queue.removeAll { $0.priority < .red && $0.id == c.utterance.id }
        } else {
            queue.append(u)
            queue.sort { $0.priority > $1.priority }
        }
        startNextIfIdle()
    }

    /// The Watch's Repeat button.
    public func repeatLast() {
        guard let last else { return }
        onEvent?("voice_repeat", ["id": last.id])
        say(last.text, id: last.id)
    }

    public func stopAll() {
        queue.removeAll()
        if current != nil { interruptCurrent() }
    }

    private func interruptCurrent() {
        guard let c = current else { return }
        current = nil
        c.output.voice.stopSpeaking()
        log(c.utterance, output: c.output.name, start: c.start, interrupted: true)
        c.utterance.completion?(true)
    }

    private func startNextIfIdle() {
        guard current == nil else { return }
        guard let index = queue.firstIndex(where: { !(holdWarnings && $0.priority == .warn) }) else { return }
        let u = queue.remove(at: index)
        guard let output = outputs.first(where: { $0.isAvailable() }) else {
            onEvent?("voice_unavailable", ["id": u.id, "text": u.text])
            haptics?.play(u.priority == .red ? .stop : .warn)
            u.completion?(false)
            startNextIfIdle()
            return
        }
        let start = clock.uptime
        current = (u, output, start)
        last = (u.id, u.text)
        haptics?.play(u.priority == .red ? .stop : u.priority == .warn ? .warn : .confirm)
        output.voice.speak(u.text) { [weak self] in
            guard let self, let c = self.current, c.utterance.id == u.id, c.start == start else { return }
            self.current = nil
            self.log(u, output: output.name, start: start, interrupted: false)
            u.completion?(false)
            self.startNextIfIdle()
        }
    }

    private func log(_ u: Utterance, output: String, start: Double, interrupted: Bool) {
        var fields: [String: Any] = [
            "id": u.id, "text": u.text, "output": output, "start": start, "finish": clock.uptime,
        ]
        if interrupted { fields["interrupted"] = true }
        onEvent?("prompt", fields)
    }
}

/// How the iPhone's audio session must be set up for speech (design §7, test V7): spoken audio
/// over A2DP with the built-in microphone, so the AirPods never switch to call mode.
public enum AudioSessionSpec {
    public static let category = "playAndRecord"
    public static let mode = "spokenAudio"
    public static let options: Set<String> = ["duckOthers", "allowBluetoothA2DP", "defaultToSpeaker"]
    /// Using the AirPods' microphone (HFP) would switch them to call mode.
    public static let forbiddenOptions: Set<String> = ["allowBluetooth", "allowBluetoothHFP"]
    public static let preferredInput = "builtInMic"
}
