import Foundation
import Network

/// Sends datagrams to the Mac receiver and listens for its once-per-second acks.
final class UDPSender {
    var onStateChange: ((String) -> Void)?
    /// Called with the receiver's total packet count from each ack.
    var onAck: ((Int) -> Void)?
    private(set) var sendErrors = 0

    private let connection: NWConnection
    private let queue: DispatchQueue

    init?(host: String, port: UInt16, queue: DispatchQueue) {
        guard !host.isEmpty, let nwPort = NWEndpoint.Port(rawValue: port) else { return nil }
        self.queue = queue
        connection = NWConnection(host: NWEndpoint.Host(host), port: nwPort, using: .udp)
    }

    func start() {
        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                self?.onStateChange?("ready")
                self?.receiveAck()
            case .waiting(let error): self?.onStateChange?("waiting: \(error.localizedDescription)")
            case .failed(let error): self?.onStateChange?("failed: \(error.localizedDescription)")
            case .cancelled: self?.onStateChange?("closed")
            default: break
            }
        }
        connection.start(queue: queue)
    }

    func send(_ data: Data) {
        connection.send(
            content: data,
            completion: .contentProcessed { [weak self] error in
                if error != nil { self?.sendErrors += 1 }
            })
    }

    func cancel() {
        connection.cancel()
    }

    private func receiveAck() {
        connection.receiveMessage { [weak self] data, _, _, error in
            guard let self, error == nil else { return }
            if let data,
                let ack = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                let received = ack["received"] as? Int
            {
                self.onAck?(received)
            }
            self.receiveAck()
        }
    }
}
