import AVFoundation
import MotionStreamerCore
import UIKit

/// Speech on the iPhone: through the AirPods when they're connected, else the phone speaker.
/// The audio session follows `AudioSessionSpec`: built-in microphone and A2DP only, so the
/// AirPods never switch to call mode (design §7, test V7).
final class PhoneVoice: NSObject, Voice, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private var completion: (() -> Void)?

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    static func configureAudioSession() {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(
                .playAndRecord, mode: .spokenAudio, options: [.duckOthers, .allowBluetoothA2DP, .defaultToSpeaker])
            try session.setActive(true)
            if let mic = session.availableInputs?.first(where: { $0.portType == .builtInMic }) {
                try session.setPreferredInput(mic)
            }
        } catch {
            print("audio session: \(error)")
        }
    }

    /// True when speech would go to Bluetooth headphones (the AirPods).
    static var airPodsAreOutput: Bool {
        AVAudioSession.sharedInstance().currentRoute.outputs.contains { $0.portType == .bluetoothA2DP }
    }

    func speak(_ text: String, completion: (() -> Void)?) {
        self.completion = completion
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.92  // slightly slower than default
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        synthesizer.speak(utterance)
    }

    func stopSpeaking() {
        completion = nil
        synthesizer.stopSpeaking(at: .immediate)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        let done = completion
        completion = nil
        done?()
    }
}

/// Speech on the Watch, used when the AirPods are out. The Watch reports when each phrase has
/// finished, so holds still start when "now" ends; if no report comes, a word-count estimate does.
final class WatchVoice: Voice {
    private let link: WCSessionLink
    private var pending: (id: String, completion: (() -> Void)?)?
    var isReachable: Bool { link.isReachable }

    init(link: WCSessionLink) { self.link = link }

    func speak(_ text: String, completion: (() -> Void)?) {
        let id = UUID().uuidString
        pending = (id, completion)
        link.sendMessage(LinkMessage(kind: .speak, session: "", detail: text, utterance: id).encoded)
        let estimate = Double(VoiceScript.wordCount(text)) * 0.45 + 1.5
        DispatchQueue.main.asyncAfter(deadline: .now() + estimate) { [weak self] in self?.finished(id) }
    }

    func stopSpeaking() { pending = nil }

    /// Called when the Watch's `spoken` message arrives (or the estimate runs out).
    func finished(_ id: String) {
        guard let p = pending, p.id == id else { return }
        pending = nil
        p.completion?()
    }
}
