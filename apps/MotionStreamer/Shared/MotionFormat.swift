import CoreMotion
import Foundation
import MotionStreamerCore

// Device-only helpers. The packet format itself lives in MotionStreamerCore (Model/MotionFormat.swift).

extension CMDeviceMotion {
    var sample: MotionSample {
        let q = attitude.quaternion
        return [
            timestamp,
            q.x, q.y, q.z, q.w,
            userAcceleration.x, userAcceleration.y, userAcceleration.z,
            gravity.x, gravity.y, gravity.z,
            rotationRate.x, rotationRate.y, rotationRate.z,
        ]
    }
}

/// Seconds since boot, on the same clock as `CMDeviceMotion.timestamp`.
func uptime() -> Double { ProcessInfo.processInfo.systemUptime }

/// Add to an uptime timestamp to get Unix time according to this device's wall clock.
func bootToUnixOffset() -> Double { Date().timeIntervalSince1970 - uptime() }

/// Magnetic-north reference when the device has a usable magnetometer, so phone and
/// Watch share a heading; otherwise an arbitrary (drift-corrected) heading.
func preferredReferenceFrame() -> (frame: CMAttitudeReferenceFrame, name: String) {
    if CMMotionManager.availableAttitudeReferenceFrames().contains(.xMagneticNorthZVertical) {
        return (.xMagneticNorthZVertical, "xMagneticNorthZVertical")
    }
    return (.xArbitraryCorrectedZVertical, "xArbitraryCorrectedZVertical")
}

/// Hardware identifier such as "iPhone17,3" or "Watch7,1".
func hardwareModel() -> String {
    var info = utsname()
    uname(&info)
    return withUnsafeBytes(of: &info.machine) { buffer in
        String(decoding: buffer.prefix(while: { $0 != 0 }), as: UTF8.self)
    }
}
