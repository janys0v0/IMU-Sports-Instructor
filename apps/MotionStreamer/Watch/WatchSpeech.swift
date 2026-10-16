import AVFoundation
import MotionStreamerCore

/// Speaks phrases the iPhone sends when the AirPods are out, and reports back when each one has
/// finished so calibration holds still start when "now" ends (design §7).
final class WatchSpeech: NSObject, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private var current: String?
    var onFinished: ((String) -> Void)?

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func speak(_ text: String, id: String) {
        current = id
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.92
        synthesizer.speak(utterance)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        if let id = current { onFinished?(id) }
        current = nil
    }
}
