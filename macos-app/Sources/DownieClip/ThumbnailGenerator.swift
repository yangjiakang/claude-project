import SwiftUI
import AppKit
import OSLog

/// 视频缩略图生成器 — 用 ffmpeg 从视频中提取帧
/// - 下载完成后提取缩略图用于历史记录展示
/// - 生成胶片条帧用于进度预览
@MainActor
final class ThumbnailGenerator: ObservableObject {
    private let logger = Logger(subsystem: "com.downieclip.app", category: "Thumbnail")
    private let cacheDir: URL

    /// 缩略图缓存（文件名 → 图片）
    @Published var cache: [String: NSImage] = [:]

    init() {
        cacheDir = FileManager.default
            .temporaryDirectory
            .appendingPathComponent("DownieClipThumbnails")
        try? FileManager.default.createDirectory(at: cacheDir, withIntermediateDirectories: true)
    }

    // MARK: - 历史缩略图（单帧）

    /// 从视频文件中提取缩略图（文件大小 > 1MB 时才处理）
    func generateThumbnail(for videoPath: String) async -> NSImage? {
        let path = videoPath as NSString
        let filename = path.lastPathComponent
        let cacheKey = "thumb_" + filename

        // 检查缓存
        if let cached = cache[cacheKey] { return cached }

        guard FileManager.default.fileExists(atPath: videoPath) else { return nil }

        // 检查文件大小（太小可能是占位文件）
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: videoPath),
              let fileSize = attrs[.size] as? Int64, fileSize > 1_000_000
        else { return nil }

        let outputPath = cacheDir.appendingPathComponent(cacheKey + ".jpg").path

        // ffmpeg 命令：在 20% 位置截取一帧
        let args = [
            "-y", "-ss", "20", "-i", videoPath,
            "-vframes", "1", "-q:v", "3",
            "-vf", "scale=320:180:force_original_aspect_ratio=decrease",
            outputPath
        ]

        do {
            try await runFFmpeg(args)
            if FileManager.default.fileExists(atPath: outputPath),
               let image = NSImage(contentsOfFile: outputPath) {
                cache[cacheKey] = image
                return image
            }
        } catch {
            logger.debug("缩略图提取失败: \(error.localizedDescription)")
        }
        return nil
    }

    // MARK: - 胶片条帧（10 帧）

    /// 从视频中提取 10 帧用于进度条胶片效果
    func generateFrameStrip(for videoPath: String) async -> [NSImage] {
        let path = videoPath as NSString
        let filename = path.lastPathComponent
        let cacheKey = "strip_" + filename

        if cache[cacheKey + "_0"] != nil { return loadStripFromCache(key: cacheKey) }

        guard FileManager.default.fileExists(atPath: videoPath),
              let attrs = try? FileManager.default.attributesOfItem(atPath: videoPath),
              let fileSize = attrs[.size] as? Int64, fileSize > 1_000_000
        else { return [] }

        // 获取视频时长
        let duration = await getVideoDuration(videoPath)
        guard duration > 1 else { return [] }

        var frames: [NSImage] = []
        let frameCount = 10
        let interval = duration / Double(frameCount + 1)

        for i in 1...frameCount {
            let time = Int(interval * Double(i))
            let outputPath = cacheDir.appendingPathComponent("\(cacheKey)_\(i).jpg").path
            let args = [
                "-y", "-ss", "\(time)", "-i", videoPath,
                "-vframes", "1", "-q:v", "5",
                "-vf", "scale=160:90:force_original_aspect_ratio=decrease",
                outputPath
            ]
            do {
                try await runFFmpeg(args)
                if let img = NSImage(contentsOfFile: outputPath) {
                    frames.append(img)
                }
            } catch {
                break // 后续帧可能也有问题
            }
        }

        return frames
    }

    // MARK: - 辅助

    private func runFFmpeg(_ args: [String]) async throws {
        let process = Process()
        // 自动查找 ffmpeg
        let ffmpegPath = findFFmpeg() ?? "ffmpeg"
        process.executableURL = URL(fileURLWithPath: ffmpegPath)
        process.arguments = args
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
        process.waitUntilExit()
    }

    private func getVideoDuration(_ path: String) async -> Double {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: findFFmpeg() ?? "ffprobe")
        process.arguments = [
            "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path
        ]
        let pipe = Pipe()
        process.standardOutput = pipe
        do {
            try process.run()
            process.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            return Double(output) ?? 0
        } catch {
            return 0
        }
    }

    private func findFFmpeg() -> String? {
        for path in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"] {
            if FileManager.default.fileExists(atPath: path) { return path }
        }
        return nil
    }

    private func loadStripFromCache(key: String) -> [NSImage] {
        var frames: [NSImage] = []
        for i in 1...10 {
            let path = cacheDir.appendingPathComponent("\(key)_\(i).jpg").path
            if let img = NSImage(contentsOfFile: path) {
                frames.append(img)
            }
        }
        return frames
    }

    /// 清除所有缓存
    func clearCache() {
        cache.removeAll()
        try? FileManager.default.removeItem(at: cacheDir)
        try? FileManager.default.createDirectory(at: cacheDir, withIntermediateDirectories: true)
    }
}
