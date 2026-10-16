import Foundation

/// Files under one root folder, addressed by relative paths ("sessions/<id>/phone/000000.jsonl").
/// Writes are appends; `sync` makes them durable (fsync). See design §2.
public protocol FileStore: AnyObject {
    func createDirectory(_ path: String) throws
    func exists(_ path: String) -> Bool
    /// Names (not paths) of the entries in a folder, sorted.
    func list(_ path: String) throws -> [String]
    func read(_ path: String) throws -> Data
    func size(_ path: String) throws -> Int
    /// Creates an empty file (replacing any old one) with the "until first unlock" protection class.
    func create(_ path: String) throws
    func append(_ data: Data, to path: String) throws
    /// Flushes everything appended so far to storage.
    func sync(_ path: String) throws
    func close(_ path: String) throws
    func rename(_ from: String, to: String) throws
    func truncate(_ path: String, to length: Int) throws
    func remove(_ path: String) throws
    /// Writes a whole small file through a temporary file and a rename, so it is never half-written.
    func writeAtomically(_ data: Data, to path: String) throws
    var freeBytes: Int64 { get }
}

public enum FileStoreError: Error, Equatable {
    case notFound(String)
    case notOpen(String)
    case diskFull
    case ioError(String)
}

/// The real file store: plain files under `root`.
public final class LocalFileStore: FileStore {
    public let root: URL
    private var handles: [String: FileHandle] = [:]
    private let fm = FileManager.default

    public init(root: URL) {
        self.root = root
    }

    private func url(_ path: String) -> URL { root.appendingPathComponent(path) }

    public func createDirectory(_ path: String) throws {
        try fm.createDirectory(at: url(path), withIntermediateDirectories: true)
    }

    public func exists(_ path: String) -> Bool { fm.fileExists(atPath: url(path).path) }

    public func list(_ path: String) throws -> [String] {
        try fm.contentsOfDirectory(atPath: url(path).path).filter { !$0.hasPrefix(".") }.sorted()
    }

    public func read(_ path: String) throws -> Data {
        guard exists(path) else { throw FileStoreError.notFound(path) }
        return try Data(contentsOf: url(path))
    }

    public func size(_ path: String) throws -> Int {
        let attributes = try fm.attributesOfItem(atPath: url(path).path)
        return (attributes[.size] as? NSNumber)?.intValue ?? 0
    }

    public func create(_ path: String) throws {
        try? handles.removeValue(forKey: path)?.close()
        var attributes: [FileAttributeKey: Any] = [:]
        #if os(iOS) || os(watchOS)
            attributes[.protectionKey] = FileProtectionType.completeUntilFirstUserAuthentication
        #endif
        guard fm.createFile(atPath: url(path).path, contents: nil, attributes: attributes) else {
            throw FileStoreError.ioError("cannot create \(path)")
        }
        handles[path] = try FileHandle(forWritingTo: url(path))
    }

    private func handle(_ path: String) throws -> FileHandle {
        if let h = handles[path] { return h }
        guard exists(path) else { throw FileStoreError.notFound(path) }
        let h = try FileHandle(forWritingTo: url(path))
        try h.seekToEnd()
        handles[path] = h
        return h
    }

    public func append(_ data: Data, to path: String) throws {
        do {
            try handle(path).write(contentsOf: data)
        } catch let error as NSError where error.code == NSFileWriteOutOfSpaceError {
            throw FileStoreError.diskFull
        }
    }

    public func sync(_ path: String) throws { try handle(path).synchronize() }

    public func close(_ path: String) throws {
        guard let h = handles.removeValue(forKey: path) else { return }
        try h.synchronize()
        try h.close()
    }

    public func rename(_ from: String, to: String) throws {
        try close(from)
        if exists(to) { try fm.removeItem(at: url(to)) }
        try fm.moveItem(at: url(from), to: url(to))
    }

    public func truncate(_ path: String, to length: Int) throws {
        let h = try handle(path)
        try h.truncate(atOffset: UInt64(length))
        try h.synchronize()
    }

    public func remove(_ path: String) throws {
        try? handles.removeValue(forKey: path)?.close()
        if exists(path) { try fm.removeItem(at: url(path)) }
    }

    public func writeAtomically(_ data: Data, to path: String) throws {
        #if os(iOS) || os(watchOS)
            try data.write(to: url(path), options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        #else
            try data.write(to: url(path), options: [.atomic])
        #endif
    }

    public var freeBytes: Int64 {
        let attributes = try? fm.attributesOfFileSystem(forPath: root.path)
        return (attributes?[.systemFreeSize] as? NSNumber)?.int64Value ?? Int64.max
    }
}
