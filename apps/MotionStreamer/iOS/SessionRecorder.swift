import Foundation

/// Writes every packet of a session to Documents/sessions/<id>/stream.jsonl,
/// plus a readable manifest.json. Visible in the Files app and in Finder.
final class SessionRecorder {
    let directory: URL
    private let handle: FileHandle

    init(sessionID: String) throws {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        directory = documents.appendingPathComponent("sessions/\(sessionID)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let streamURL = directory.appendingPathComponent("stream.jsonl")
        FileManager.default.createFile(atPath: streamURL.path, contents: nil)
        handle = try FileHandle(forWritingTo: streamURL)
    }

    func append(_ line: Data) {
        handle.write(line)
        handle.write(Data([0x0A]))
    }

    func writeManifest(_ manifest: [String: Any]) {
        guard
            let data = try? JSONSerialization.data(
                withJSONObject: manifest,
                options: [.prettyPrinted, .sortedKeys])
        else { return }
        try? data.write(to: directory.appendingPathComponent("manifest.json"))
    }

    func close() {
        try? handle.synchronize()
        try? handle.close()
    }
}
