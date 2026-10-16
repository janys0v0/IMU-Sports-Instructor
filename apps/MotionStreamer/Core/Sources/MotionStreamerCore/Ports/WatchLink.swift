import Foundation

/// The Watch ↔ iPhone connection (WatchConnectivity on devices). Messages are live and may be
/// dropped; file transfers are queued and retried by the system until they arrive (design §3).
public protocol WatchLink: AnyObject {
    var isReachable: Bool { get }
    /// Live message; dropped if the other side isn't reachable.
    func sendMessage(_ data: Data)
    /// Queues a file for transfer. `metadata` arrives with it.
    func transferFile(_ data: Data, metadata: [String: String])
    /// Called with each message from the other side.
    var onMessage: ((Data) -> Void)? { get set }
    /// Called with each file that arrives, and its metadata.
    var onFile: ((Data, [String: String]) -> Void)? { get set }
    var onReachabilityChange: ((Bool) -> Void)? { get set }
}
