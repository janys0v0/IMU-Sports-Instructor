// swift-tools-version:5.9
// Platform-independent logic of the MotionStreamer app: recording, transfer, checks.
// Everything outside (sensors, files, radios, speech, time) sits behind a protocol in Ports/,
// so the same code runs in `swift test` on the Mac, in the simulators and on devices.
import PackageDescription

let package = Package(
    name: "MotionStreamerCore",
    platforms: [.macOS(.v13), .iOS(.v17), .watchOS(.v10)],
    products: [
        .library(name: "MotionStreamerCore", targets: ["MotionStreamerCore"])
    ],
    targets: [
        .target(
            name: "MotionStreamerCore",
            resources: [.copy("Resources/quality_thresholds.json"), .copy("Resources/voice_prompts.json")]),
        .testTarget(name: "MotionStreamerCoreTests", dependencies: ["MotionStreamerCore"]),
    ]
)
