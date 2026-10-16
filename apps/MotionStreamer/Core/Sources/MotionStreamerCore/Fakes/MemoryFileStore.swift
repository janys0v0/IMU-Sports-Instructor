import Foundation

/// In-memory file store for tests. It remembers how much of each file was synced, so a test can
/// simulate a crash or power loss, and it can fail on command (disk full, write or sync errors).
public final class MemoryFileStore: FileStore {
    public struct File {
        public var data = Data()
        /// Bytes guaranteed on storage (written before the last `sync`).
        public var synced = 0
        public var isOpen = false
        public var syncCount = 0
        public var protected = false
    }

    public private(set) var files: [String: File] = [:]
    public private(set) var directories: Set<String> = [""]
    /// Fail the next `append` with this error, once.
    public var failNextAppend: FileStoreError?
    /// Fail the next `sync` with this error, once.
    public var failNextSync: FileStoreError?
    /// Total bytes the "disk" can hold; appends beyond it throw `diskFull`.
    public var capacity = Int64.max
    public private(set) var totalSyncs = 0

    public init() {}

    public var usedBytes: Int64 { Int64(files.values.reduce(0) { $0 + $1.data.count }) }
    public var freeBytes: Int64 { capacity == .max ? .max : capacity - usedBytes }

    public func createDirectory(_ path: String) throws {
        var parts: [String] = []
        for part in path.split(separator: "/") {
            parts.append(String(part))
            directories.insert(parts.joined(separator: "/"))
        }
    }

    public func exists(_ path: String) -> Bool { files[path] != nil || directories.contains(path) }

    public func list(_ path: String) throws -> [String] {
        let prefix = path.isEmpty ? "" : path + "/"
        let names = (Array(files.keys) + Array(directories)).compactMap { p -> String? in
            guard p.hasPrefix(prefix), p != path else { return nil }
            let rest = p.dropFirst(prefix.count)
            return rest.contains("/") || rest.isEmpty ? nil : String(rest)
        }
        return Array(Set(names)).sorted()
    }

    public func read(_ path: String) throws -> Data {
        guard let f = files[path] else { throw FileStoreError.notFound(path) }
        return f.data
    }

    public func size(_ path: String) throws -> Int { try read(path).count }

    public func create(_ path: String) throws {
        files[path] = File(isOpen: true, protected: true)
    }

    public func append(_ data: Data, to path: String) throws {
        if let error = failNextAppend {
            failNextAppend = nil
            throw error
        }
        guard files[path] != nil else { throw FileStoreError.notFound(path) }
        if capacity != .max, usedBytes + Int64(data.count) > capacity { throw FileStoreError.diskFull }
        files[path]!.data.append(data)
    }

    public func sync(_ path: String) throws {
        if let error = failNextSync {
            failNextSync = nil
            throw error
        }
        guard files[path] != nil else { throw FileStoreError.notFound(path) }
        files[path]!.synced = files[path]!.data.count
        files[path]!.syncCount += 1
        totalSyncs += 1
    }

    public func close(_ path: String) throws {
        guard files[path] != nil else { return }
        try sync(path)
        files[path]!.isOpen = false
    }

    public func rename(_ from: String, to: String) throws {
        guard var f = files.removeValue(forKey: from) else { throw FileStoreError.notFound(from) }
        f.isOpen = false
        files[to] = f
    }

    public func truncate(_ path: String, to length: Int) throws {
        guard files[path] != nil else { throw FileStoreError.notFound(path) }
        files[path]!.data = files[path]!.data.prefix(length)
        files[path]!.synced = min(files[path]!.synced, length)
    }

    public func remove(_ path: String) throws { files[path] = nil }

    public func writeAtomically(_ data: Data, to path: String) throws {
        files[path] = File(data: data, synced: data.count, isOpen: false, protected: true)
    }

    /// A copy of the store as it would be found after a crash: every file keeps its synced bytes
    /// plus `extraUnsynced(path, unsyncedCount)` of the bytes written after the last sync.
    public func afterCrash(extraUnsynced: (String, Int) -> Int = { _, _ in 0 }) -> MemoryFileStore {
        let copy = MemoryFileStore()
        copy.directories = directories
        for (path, f) in files {
            let unsynced = f.data.count - f.synced
            let keep = f.synced + max(0, min(unsynced, extraUnsynced(path, unsynced)))
            copy.files[path] = File(data: f.data.prefix(keep), synced: keep, protected: f.protected)
        }
        return copy
    }
}
