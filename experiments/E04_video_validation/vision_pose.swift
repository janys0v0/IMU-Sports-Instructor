// 3D body pose from a video with Apple Vision (VNDetectHumanBodyPose3DRequest, built into macOS 14+).
//
// Usage (repo root):
//   swift experiments/E04_video_validation/vision_pose.swift VIDEO OUT.json [--stride 2]
//
// Writes {"video", "fps", "stride", "frames": [{"t", "height", "joints": {name: [x, y, z]}}]}.
// Positions are in metres relative to the body root, in Vision's model space. Frames without a
// detected person are left out. A mirrored video (Photo Booth) is handled later by swapping
// left and right names in Python: joint angles do not change under a reflection.

import AVFoundation
import Foundation
import Vision

let args = CommandLine.arguments
guard args.count >= 3 else {
    print("usage: vision_pose.swift VIDEO OUT.json [--stride N]")
    exit(2)
}
let videoURL = URL(fileURLWithPath: args[1])
let outURL = URL(fileURLWithPath: args[2])
var stride = 2
if let i = args.firstIndex(of: "--stride"), i + 1 < args.count, let n = Int(args[i + 1]) { stride = n }

let asset = AVURLAsset(url: videoURL)
guard let track = try await asset.loadTracks(withMediaType: .video).first else {
    print("no video track")
    exit(1)
}
let fps = Double(try await track.load(.nominalFrameRate))
let reader = try AVAssetReader(asset: asset)
let output = AVAssetReaderTrackOutput(
    track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
reader.add(output)
reader.startReading()

var frames: [[String: Any]] = []
var index = -1
var detected = 0
let started = Date()
while let sample = output.copyNextSampleBuffer() {
    index += 1
    guard index % stride == 0, let pixels = CMSampleBufferGetImageBuffer(sample) else { continue }
    let t = CMSampleBufferGetPresentationTimeStamp(sample).seconds
    let request = VNDetectHumanBodyPose3DRequest()
    try VNImageRequestHandler(cvPixelBuffer: pixels, orientation: .up).perform([request])
    guard let body = request.results?.first else { continue }
    var joints: [String: [Double]] = [:]
    for name in body.availableJointNames {
        guard let point = try? body.recognizedPoint(name) else { continue }
        let p = point.position.columns.3
        joints[name.rawValue.rawValue] = [Double(p.x), Double(p.y), Double(p.z)]
    }
    frames.append(["t": t, "height": Double(body.bodyHeight), "joints": joints])
    detected += 1
    if index % 300 == 0 { print(String(format: "%.0f s: %d frames with a body", t, detected)) }
}
let result: [String: Any] = ["video": videoURL.lastPathComponent, "fps": fps, "stride": stride, "frames": frames]
try JSONSerialization.data(withJSONObject: result).write(to: outURL)
print(
    String(
        format: "%d of %d frames with a body, %.0f s", detected, index / stride + 1, Date().timeIntervalSince(started)))
