import CoreLocation
import MotionStreamerCore

/// Keeps the app running in the background with the cheapest location updates (3 km accuracy,
/// no distance updates in practice). Apple DTS confirms this keeps Core Motion delivering in the
/// background (docs/research/device-research.md §1). The app isn't going to the App Store.
final class LocationKeepAlive: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    var onChange: ((Bool) -> Void)?
    private(set) var isRunning = false

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyThreeKilometers
        manager.distanceFilter = 3000
        manager.pausesLocationUpdatesAutomatically = false
    }

    func start() {
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
        manager.allowsBackgroundLocationUpdates = true
        manager.showsBackgroundLocationIndicator = true
        manager.startUpdatingLocation()
        isRunning = true
        onChange?(authorized)
    }

    func stop() {
        manager.stopUpdatingLocation()
        isRunning = false
        onChange?(false)
    }

    var authorized: Bool {
        [.authorizedWhenInUse, .authorizedAlways].contains(manager.authorizationStatus)
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        onChange?(isRunning && authorized)
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {}
    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {}
}
