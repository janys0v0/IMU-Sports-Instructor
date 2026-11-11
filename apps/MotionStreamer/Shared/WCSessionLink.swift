import Foundation
import MotionStreamerCore
import WatchConnectivity

/// `WatchLink` over WatchConnectivity. The app's existing `WCSessionDelegate` forwards incoming
/// message data and files here (`received(...)`), so there is still one delegate per app.
final class WCSessionLink: WatchLink {
    var onMessage: ((Data) -> Void)?
    var onFile: ((Data, [String: String]) -> Void)?
    var onReachabilityChange: ((Bool) -> Void)?

    var isReachable: Bool {
        WCSession.isSupported() && WCSession.default.activationState == .activated && WCSession.default.isReachable
    }

    func sendMessage(_ data: Data) {
        guard isReachable else { return }
        WCSession.default.sendMessageData(data, replyHandler: nil, errorHandler: nil)
    }

    /// Writes the bytes to a temporary file and queues it; the system retries until it arrives.
    func transferFile(_ data: Data, metadata: [String: String]) {
        guard WCSession.isSupported(), WCSession.default.activationState == .activated else { return }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        guard (try? data.write(to: url)) != nil else { return }
        WCSession.default.transferFile(url, metadata: metadata)
    }

    // MARK: Forwarded by the WCSessionDelegate

    func received(messageData: Data) { onMessage?(messageData) }

    /// The file must be read before the delegate method returns: the system deletes it afterwards.
    func received(file: WCSessionFile) {
        guard let data = try? Data(contentsOf: file.fileURL) else { return }
        let metadata = (file.metadata ?? [:]).compactMapValues { $0 as? String }
        onFile?(data, metadata)
    }

    func reachabilityChanged() { onReachabilityChange?(isReachable) }
}
