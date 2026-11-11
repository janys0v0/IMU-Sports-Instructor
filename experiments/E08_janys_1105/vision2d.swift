// 2D body keypoints from a video with Apple Vision (VNDetectHumanBodyPoseRequest), for syncing a
// camera clip to OpenCap and fitting its projection. Every person found is kept (the player is
// picked later in Python by matching OpenCap).
//
// Usage (repo root):
//   swift experiments/E08_janys_1105/vision2d.swift VIDEO OUT.json [--stride N] [--start S] [--seconds N]
//
// Writes {"video", "fps", "stride", "size": [w, h], "frames": [{"t", "people": [{name: [x, y, conf]}]}]}
// with x, y in pixels of the displayed (upright) frame, origin top-left.

import AVFoundation
import Foundation
import Vision

let args = CommandLine.arguments
guard args.count >= 3 else {
    print("usage: vision2d.swift VIDEO OUT.json [--stride N] [--start S] [--seconds N]")
    exit(2)
}
func opt(_ name: String, _ dflt: Double) -> Double {
    if let i = args.firstIndex(of: name), i + 1 < args.count, let v = Double(args[i + 1]) { return v }
    return dflt
}
let stride = Int(opt("--stride", 3))
let start = opt("--start", 0)
let seconds = opt("--seconds", 1e9)

let asset = AVURLAsset(url: URL(fileURLWithPath: args[1]))
guard let track = try await asset.loadTracks(withMediaType: .video).first else {
    print("no video track")
    exit(1)
}
let fps = Double(try await track.load(.nominalFrameRate))
let natural = try await track.load(.naturalSize)
// The clip may be stored rotated (a phone held the other way up); Vision must see it upright,
// and the points must be in the displayed frame, as OpenCV shows it.
let tf = try await track.load(.preferredTransform)
var orientation = CGImagePropertyOrientation.up
var size = natural
if tf.a == -1 && tf.d == -1 {
    orientation = .down
} else if tf.b == 1 && tf.c == -1 {
    orientation = .right; size = CGSize(width: natural.height, height: natural.width)
} else if tf.b == -1 && tf.c == 1 {
    orientation = .left; size = CGSize(width: natural.height, height: natural.width)
}
print("orientation", orientation.rawValue, "size", size)
let reader = try AVAssetReader(asset: asset)
reader.timeRange = CMTimeRange(
    start: CMTime(seconds: start, preferredTimescale: 600),
    duration: CMTime(seconds: seconds, preferredTimescale: 600))
let output = AVAssetReaderTrackOutput(
    track: track,
    outputSettings: [
        kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
    ])
reader.add(output)
reader.startReading()

var frames: [[String: Any]] = []
var k = 0
let names: [VNHumanBodyPoseObservation.JointName: String] = [
    .nose: "Nose", .neck: "Neck", .rightShoulder: "RShoulder", .rightElbow: "RElbow",
    .rightWrist: "RWrist", .leftShoulder: "LShoulder", .leftElbow: "LElbow", .leftWrist: "LWrist",
    .rightHip: "RHip", .rightKnee: "RKnee", .rightAnkle: "RAnkle", .leftHip: "LHip",
    .leftKnee: "LKnee", .leftAnkle: "LAnkle", .root: "midHip",
]
let w = Double(size.width), h = Double(size.height)
while let sample = output.copyNextSampleBuffer() {
    defer { k += 1 }
    if k % stride != 0 { continue }
    guard let pixels = CMSampleBufferGetImageBuffer(sample) else { continue }
    let t = CMSampleBufferGetPresentationTimeStamp(sample).seconds
    let request = VNDetectHumanBodyPoseRequest()
    try? VNImageRequestHandler(cvPixelBuffer: pixels, orientation: orientation, options: [:]).perform([request])
    var people: [[String: [Double]]] = []
    for obs in request.results ?? [] {
        var p: [String: [Double]] = [:]
        for (jn, name) in names {
            if let pt = try? obs.recognizedPoint(jn), pt.confidence > 0.2 {
                p[name] = [Double(pt.location.x) * w, (1 - Double(pt.location.y)) * h, Double(pt.confidence)]
            }
        }
        if !p.isEmpty { people.append(p) }
    }
    frames.append(["t": t, "people": people])
    if frames.count % 2000 == 0 { print("frames", frames.count, "t", Int(t)) }
}
let out: [String: Any] = ["video": args[1], "fps": fps, "stride": stride, "size": [w, h], "frames": frames]
try JSONSerialization.data(withJSONObject: out).write(to: URL(fileURLWithPath: args[2]))
print("wrote", frames.count, "frames")
