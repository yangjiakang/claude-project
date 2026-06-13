import Foundation
import AppKit
import OSLog

/// 下载队列管理器 — 单任务串行 + 本地队列（最多 15 个）
/// SSE 事件始终对应 tasks[0]（当前活跃任务）
@MainActor
final class DownloadStore: ObservableObject {
    @Published var tasks: [DownloadTask] = []
    @Published var completedTasks: [DownloadTask] = []
    @Published var isDownloading = false
    @Published var totalProgress: Double = 0
    @Published var statusMessage = "就绪"
    @Published var downloadSpeed = ""
    @Published var settings = AppSettings.load()

    private let api: APIClient
    private let logger = Logger(subsystem: "com.downieclip.app", category: "Store")
    private let maxQueue = 15
    private let thumbnailGen = ThumbnailGenerator()

    var notificationManager: NotificationManager?

    init(api: APIClient) { self.api = api }

    // MARK: - 添加任务

    func downloadURLs(_ urls: [String]) {
        let valid = urls.filter { $0.hasPrefix("http://") || $0.hasPrefix("https://") }
        guard !valid.isEmpty else { return }

        let available = maxQueue - tasks.count
        guard available > 0 else {
            statusMessage = "⚠️ 队列已满（最多 \(maxQueue) 个）"
            return
        }

        let newTasks = valid.prefix(available).map { DownloadTask(url: $0, status: .queued) }
        tasks.append(contentsOf: newTasks)
        statusMessage = "📋 已添加 \(newTasks.count) 个任务"

        if !isDownloading { startNext() }
    }

    func downloadURL(_ url: String) { downloadURLs([url]) }

    // MARK: - 任务调度

    private func startNext() {
        guard let idx = tasks.firstIndex(where: { $0.status == .queued }) else {
            if tasks.allSatisfy({ $0.status == .completed || $0.status == .failed }) {
                finishAll()
            }
            return
        }

        isDownloading = true
        tasks[idx].status = .downloading
        objectWillChange.send()

        // 启动 SSE 监听
        api.stopListening()
        api.listenProgress { [weak self] event in
            Task { @MainActor in self?.handleSSEEvent(event) }
        }

        let url = tasks[idx].url
        Task {
            do {
                statusMessage = "🚀 开始下载..."
                let _ = try await api.startDownload(url: url, maxVideos: 1, timeout: 60)
            } catch {
                logger.error("提交失败: \(error.localizedDescription)")
                tasks[idx].status = .failed
                statusMessage = "❌ 提交失败: \(error.localizedDescription.prefix(40))"
                onTaskFailed(at: idx)
            }
        }
    }

    // MARK: - SSE 事件处理

    private func handleSSEEvent(_ event: SSEEvent) {
        guard !tasks.isEmpty else { return }
        let activeIdx = tasks.firstIndex(where: { $0.status == .downloading }) ?? 0

        objectWillChange.send()
        tasks[activeIdx].applySSEEvent(event)

        switch event.type {
        case "batch_complete", "complete":
            onActiveComplete()
            return  // ← 任务已移除，不能继续访问 tasks[activeIdx]
        case "url_error":
            tasks[activeIdx].status = .failed
            onTaskFailed(at: activeIdx)
            return  // ← 任务已移除
        default:
            break
        }

        // 以下代码仅在任务未完成时执行
        totalProgress = tasks[activeIdx].progress

        if event.type == "ffmpeg_progress" {
            if tasks[activeIdx].fileSizeMB > 0 {
                updateSpeed(currentSizeMB: tasks[activeIdx].fileSizeMB)
            }
        }
    }

    private func onActiveComplete() {
        // url_complete 已先将状态设为 .completed，所以这里匹配两种状态
        guard let idx = tasks.firstIndex(where: { $0.status == .downloading || $0.status == .completed }) else { return }
        tasks[idx].status = .completed
        tasks[idx].progress = 100

        let task = tasks[idx]
        completedTasks.insert(task, at: 0)
        tasks.remove(at: idx)

        // 通知
        let sizeStr = task.fileSizeMB > 0 ? String(format: "%.1f MB", task.fileSizeMB) : ""
        notificationManager?.sendDownloadComplete(filename: task.filename, fileSize: sizeStr, url: task.url)

        statusMessage = "✅ 下载完成"
        // 继续下一个
        startNext()
    }

    private func onTaskFailed(at idx: Int) {
        completedTasks.insert(tasks[idx], at: 0)
        tasks.remove(at: idx)
        startNext()
    }

    private func finishAll() {
        isDownloading = false
        downloadSpeed = ""
        statusMessage = "🎉 全部完成"
        api.stopListening()
        // 刷新历史
        Task {
            if let history = try? await api.fetchHistory() { completedTasks = history }
        }
    }

    // MARK: - 速度计算

    private var lastSize: Double = 0
    private var lastTime = Date()
    private func updateSpeed(currentSizeMB: Double) {
        let now = Date()
        let elapsed = now.timeIntervalSince(lastTime)
        guard elapsed > 1.0 else { return }
        let delta = currentSizeMB - lastSize
        if delta > 0 {
            let speed = delta / elapsed
            downloadSpeed = speed >= 10 ? String(format: "%.0f MB/s", speed)
                : speed >= 0.1 ? String(format: "%.1f MB/s", speed)
                : String(format: "%.0f KB/s", speed * 1024)
        }
        lastSize = currentSizeMB
        lastTime = now
    }

    // MARK: - 辅助

    func removeTask(_ task: DownloadTask) {
        tasks.removeAll { $0.id == task.id }
        completedTasks.removeAll { $0.id == task.id }
    }
    func clearCompleted() { completedTasks.removeAll() }

    func openOutputDirectory() {
        let path = settings.outputDirectory ?? defaultOutputDir
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    private var defaultOutputDir: String {
        var url = URL(fileURLWithPath: #filePath)
        while url.path != "/" {
            url = url.deletingLastPathComponent()
            if FileManager.default.fileExists(atPath: url.appendingPathComponent(".git").path) {
                return "\(url.path)/videos"
            }
        }
        return NSHomeDirectory() + "/Downloads"
    }
}

// MARK: - 设置

struct AppSettings: Codable {
    var outputDirectory: String?
    var clipboardMonitoring = true
    var autoOpenFolder = true
    static let key = "com.downieclip.settings"

    static func load() -> AppSettings {
        guard let data = UserDefaults.standard.data(forKey: key),
              let s = try? JSONDecoder().decode(AppSettings.self, from: data)
        else { return AppSettings() }
        return s
    }
    func save() {
        if let data = try? JSONEncoder().encode(self) { UserDefaults.standard.set(data, forKey: Self.key) }
    }
}
