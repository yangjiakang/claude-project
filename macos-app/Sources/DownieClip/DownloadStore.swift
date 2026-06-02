import Foundation
import AppKit
import OSLog

/// 全局下载状态管理器
/// 管理下载队列、进度更新、历史记录、通知触发、速度显示
@MainActor
final class DownloadStore: ObservableObject {
    @Published var tasks: [DownloadTask] = []          // 当前下载队列
    @Published var completedTasks: [DownloadTask] = [] // 已完成/历史记录
    @Published var isDownloading = false               // 是否有任务在下载
    @Published var totalProgress: Double = 0           // 总进度 0-100
    @Published var statusMessage = "就绪"               // 状态栏消息
    @Published var downloadSpeed = ""                  // 当前下载速度 "4.2 MB/s"

    /// 用户设置（持久化到 UserDefaults）
    @Published var settings = AppSettings.load()

    private let api: APIClient
    private let logger = Logger(subsystem: "com.downieclip.app", category: "Store")
    private var activeTaskIndex: Int?
    private var lastFileSize: Double = 0               // 上次文件大小（计算速度）
    private var lastProgressTime: Date = Date()

    /// 外部注入的通知管理器（Phase 2）
    var notificationManager: NotificationManager?

    /// 下载完成回调（供 MainApp 注入通知逻辑）
    var onDownloadComplete: ((String, String, String) -> Void)?

    init(api: APIClient) { self.api = api }

    // MARK: - 速度计算

    /// 根据文件大小变化计算下载速度
    func updateSpeed(currentSizeMB: Double) {
        let now = Date()
        let elapsed = now.timeIntervalSince(lastProgressTime)
        guard elapsed > 1.0 else { return } // 至少间隔 1 秒

        let delta = currentSizeMB - lastFileSize
        if delta > 0 && elapsed > 0 {
            let speed = delta / elapsed
            if speed >= 10 {
                downloadSpeed = String(format: "%.0f MB/s", speed)
            } else if speed >= 0.1 {
                downloadSpeed = String(format: "%.1f MB/s", speed)
            } else {
                downloadSpeed = String(format: "%.0f KB/s", speed * 1024)
            }
        } else {
            downloadSpeed = ""
        }
        lastFileSize = currentSizeMB
        lastProgressTime = now
    }

    // MARK: - 下载操作

    /// 添加并开始下载单个 URL
    func downloadURL(_ url: String) {
        guard !url.isEmpty, !isDownloading else { return }

        let task = DownloadTask(url: url, status: .pending)
        tasks.insert(task, at: 0)         // 🔝 新任务插入到列表最前面
        activeTaskIndex = 0
        isDownloading = true
        statusMessage = "正在提交..."

        Task {
            do {
                let _ = try await api.startDownload(url: url)
                statusMessage = "下载中..."
                startProgressListening()
            } catch {
                handleError(error, forTaskAt: 0)
            }
        }
    }

    /// 添加并开始批量下载
    func downloadURLs(_ urls: [String]) {
        guard !urls.isEmpty, !isDownloading else { return }

        let newTasks = urls.map { DownloadTask(url: $0, status: .pending) }
        tasks.insert(contentsOf: newTasks, at: 0)  // 🔝 新任务插入到前面
        activeTaskIndex = 0
        isDownloading = true
        statusMessage = "正在提交 \(urls.count) 个任务..."

        Task {
            do {
                let _ = try await api.startBatchDownload(urls: urls)
                statusMessage = "批量下载中..."
                startProgressListening()
            } catch {
                handleError(error, forTaskAt: 0)
            }
        }
    }

    // MARK: - SSE 进度监听

    private func startProgressListening() {
        api.stopListening()
        api.listenProgress { [weak self] event in
            Task { @MainActor in await self?.handleSSEEvent(event) }
        }
    }

    private func handleSSEEvent(_ event: SSEEvent) async {
        // 根据 url_index 更新对应任务的进度
        let idx = event.urlIndex ?? activeTaskIndex ?? 0
        if idx < tasks.count {
            tasks[idx].applySSEEvent(event)
        }

        // 处理批量事件
        switch event.type {
        case "batch_start":
            statusMessage = "开始下载 (\(event.total ?? 0) 个URL)"
        case "url_start":
            if let url = event.url, let idx = event.urlIndex, idx < tasks.count {
                tasks[idx].url = url
                tasks[idx].status = .downloading
            }
        case "url_complete":
            if let idx = event.urlIndex, idx < tasks.count {
                tasks[idx].status = .completed
                tasks[idx].progress = 100
            }
        case "url_error":
            if let idx = event.urlIndex, idx < tasks.count {
                tasks[idx].status = .failed
            }
        case "ffmpeg_progress":
            if let idx = event.urlIndex, idx < tasks.count {
                tasks[idx].status = .downloading
                tasks[idx].progress = Double(event.percent ?? 0)
            }
        case "batch_complete", "complete":
            await onDownloadComplete()
        case "convert_complete":
            statusMessage = "转换完成"
        default:
            break
        }

        // 计算总进度
        if !tasks.isEmpty {
            totalProgress = tasks.reduce(0) { $0 + $1.progress } / Double(tasks.count)
        }
    }

    /// 下载全部完成后刷新历史
    private func onDownloadComplete() async {
        isDownloading = false
        activeTaskIndex = nil
        statusMessage = "✅ 下载完成"
        api.stopListening()

        // 🔔 发送系统通知
        let done = tasks.filter { $0.status == .completed }
        let failed = tasks.filter { $0.status == .failed }

        if done.count == 1, let task = done.first {
            // 单文件完成通知
            let sizeStr = task.fileSizeMB > 0 ? String(format: "%.1f MB", task.fileSizeMB) : ""
            notificationManager?.sendDownloadComplete(
                filename: task.filename, fileSize: sizeStr, url: task.url
            )
            onDownloadComplete?(task.filename, sizeStr, task.url)
        } else if done.count > 1 {
            // 批量完成通知
            notificationManager?.sendBatchComplete(total: done.count + failed.count, downloaded: done.count)
        } else if !failed.isEmpty {
            // 失败通知
            if let task = failed.first {
                notificationManager?.sendDownloadFailed(url: task.url, error: "下载失败")
            }
        }

        // 移动已完成的任务到历史列表
        completedTasks.insert(contentsOf: done, at: 0)
        tasks.removeAll { $0.status == .completed }
        if failed.isEmpty { tasks.removeAll() }

        // 从后端刷新历史
        if let history = try? await api.fetchHistory() {
            completedTasks = history
        }
    }

    // MARK: - 错误处理

    private func handleError(_ error: Error, forTaskAt index: Int) {
        statusMessage = "❌ \(error.localizedDescription)"
        isDownloading = false
        if index < tasks.count {
            tasks[index].status = .failed
        }
    }

    // MARK: - 辅助操作

    /// 移除任务
    func removeTask(_ task: DownloadTask) {
        tasks.removeAll { $0.id == task.id }
        completedTasks.removeAll { $0.id == task.id }
    }

    /// 清空已完成列表
    func clearCompleted() { completedTasks.removeAll() }

    private func findRepoRoot() -> String? {
        var url = URL(fileURLWithPath: #filePath)
        while url.path != "/" {
            url = url.deletingLastPathComponent()
            if FileManager.default.fileExists(atPath: url.appendingPathComponent(".git").path) { return url.path }
        }
        return nil
    }

    /// 打开输出目录（使用设置中保存的路径，或默认路径）
    func openOutputDirectory() {
        let path = settings.outputDirectory ?? defaultOutputDir
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    private var defaultOutputDir: String {
        findRepoRoot().map { "\($0)/videos" } ?? NSHomeDirectory() + "/Downloads"
    }
}

// MARK: - 应用设置（UserDefaults 持久化）

/// 用户偏好设置，自动持久化到 UserDefaults
struct AppSettings: Codable {
    var outputDirectory: String?          // 自定义输出目录
    var clipboardMonitoring: Bool = true  // 剪贴板监听开关
    var maxConcurrent: Int = 1            // 并发下载数
    var autoOpenFolder: Bool = true       // 下载完成自动打开目录

    static let key = "com.downieclip.settings"

    /// 从 UserDefaults 加载
    static func load() -> AppSettings {
        guard let data = UserDefaults.standard.data(forKey: key),
              let settings = try? JSONDecoder().decode(AppSettings.self, from: data)
        else { return AppSettings() }
        return settings
    }

    /// 保存到 UserDefaults
    func save() {
        if let data = try? JSONEncoder().encode(self) {
            UserDefaults.standard.set(data, forKey: Self.key)
        }
    }
}
