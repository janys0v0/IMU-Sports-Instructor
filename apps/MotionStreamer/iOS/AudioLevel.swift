import AVFoundation
import MotionStreamerCore

/// Sound level from the phone's built-in microphone, in 50 ms blocks (design §9). Only the level
/// and onset flags leave this class: the audio itself is never stored.
final class AudioLevelRecorder {
    private let engine = AVAudioEngine()
    private let meter = AudioLevelMeter(blockSeconds: 0.05)
    private(set) var isRunning = false
    /// (uptime, RMS dBFS, peak dBFS, onset), called on the audio thread.
    var onLevel: ((Double, Double, Double, Bool) -> Void)?

    func start() {
        guard !isRunning else { return }
        AVAudioApplication.requestRecordPermission { [weak self] granted in
            guard granted else { return }
            DispatchQueue.main.async { self?.startEngine() }
        }
    }

    private func startEngine() {
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0 else { return }  // no microphone (e.g. the simulator)
        let block = AVAudioFrameCount(format.sampleRate * 0.05)
        input.installTap(onBus: 0, bufferSize: block, format: format) { [weak self] buffer, _ in
            guard let self, let channel = buffer.floatChannelData?[0] else { return }
            let samples = Array(UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength)))
            let level = self.meter.process(samples)
            self.onLevel?(ProcessInfo.processInfo.systemUptime, level.rmsDB, level.peakDB, level.onset)
        }
        do {
            try engine.start()
            isRunning = true
        } catch {
            input.removeTap(onBus: 0)
        }
    }

    func stop() {
        guard isRunning else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        isRunning = false
    }
}
