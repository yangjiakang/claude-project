import Foundation
import OSLog

// MARK: - 数据模型

/// 下载任务状态
struct DownloadTask: Identifiable, Codable, Equatable {
    let id: String
    var url: String
    var filename: String
    var progress: Double       // 0-100
    var speed: String          // 如 "4.2 MB/s"
    var status: TaskStatus
    var fileSizeMB: Double
    var durationSec: Double
    var format: String
    var createdAt: Date

    enum TaskStatus: String, Codable, Equatable {
        case pending     // 排队中
        case downloading // 下载中
        case converting  // 转换中
        case completed   // 已完成
        case failed      // 失败
    }

    init(id: String = UUID().uuidString,
         url: String = "",
         filename: String = "",
         progress: Double = 0,
         speed: String = "",
         status: TaskStatus = .pending,
         fileSizeMB: Double = 0,
         durationSec: Double = 0,
         format: String = "mp4",
         createdAt: Date = Date()) {
        self.id = id
        self.url = url
        self.filename = filename
        self.progress = progress
        self.speed = speed
        self.status = status
        self.createdAt = createdAt
        self.fileSizeMB = fileSizeMB
        self.durationSec = durationSec
        self.format = format
    }

    /// 从 SSE 事件更新任务状态
    mutating func applySSEEvent(_ event: SSEEvent) {
        switch event.type {
        case "url_start":
            self.url = event.url ?? self.url
            self.status = .downloading
        case "ffmpeg_progress":
            self.progress = Double(event.percent ?? 0)
            self.status = .downloading
        case "url_complete":
            self.status = .completed
            self.progress = 100
        case "url_error":
            self.status = .failed
        case "batch_complete":
            if self.status != .failed { self.status = .completed; self.progress = 100 }
        case "convert_start":
            self.status = .converting
            self.progress = 0
        case "convert_complete":
            self.status = .completed
            self.progress = 100
        default:
            break
        }
    }
}

/// SSE 事件（从 /api/progress 流解析）
struct SSEEvent: Decodable {
    let type: String
    let urlIndex: Int?
    let percent: Int?
    let message: String?
    let url: String?
    let downloaded: Int?
    let total: Int?
    let outputDir: String?

    enum CodingKeys: String, CodingKey {
        case type, message, url, downloaded, total, percent
        case urlIndex = "url_index"
        case outputDir = "output_dir"
    }
}

// MARK: - API 客户端

/// 与 Python 后端通信的 HTTP + SSE 客户端
@MainActor
final class APIClient: ObservableObject {
    private let baseURL: String
    private let logger = Logger(subsystem: "com.downieclip.app", category: "API")
    private var sseTask: Task<Void, Never>?

    init(baseURL: String) { self.baseURL = baseURL }

    // MARK: - REST API

    /// 提交单个 URL 下载
    func startDownload(url: String, maxVideos: Int = 1, concurrent: Int = 1, timeout: Int = 60) async throws -> String {
        let body: [String: Any] = [
            "url": url, "max_videos": maxVideos,
            "concurrent": concurrent, "timeout": timeout,
        ]
        return try await post("/api/scrape", body: body)
    }

    /// 提交批量 URL 下载
    func startBatchDownload(urls: [String], maxVideos: Int = 1, concurrent: Int = 1, timeout: Int = 60) async throws -> String {
        let body: [String: Any] = [
            "urls": urls, "max_videos_per_url": maxVideos,
            "concurrent": concurrent, "timeout": timeout,
        ]
        return try await post("/api/scrape-batch", body: body)
    }

    /// 获取下载历史
    func fetchHistory(limit: Int = 50) async throws -> [DownloadTask] {
        let data = try await get("/api/history?limit=\(limit)")
        struct HistoryItem: Decodable {
            let id: String; let url: String; let filename: String
            let file_size_mb: Double; let duration_sec: Double
            let format: String; let status: String; let created_at: String
        }
        let items = try JSONDecoder().decode([HistoryItem].self, from: data)
        let formatter = ISO8601DateFormatter()
        return items.map { item in
            DownloadTask(
                id: item.id, url: item.url, filename: item.filename,
                progress: 100, status: item.status == "completed" ? .completed : .failed,
                fileSizeMB: item.file_size_mb, durationSec: item.duration_sec,
                format: item.format,
                createdAt: formatter.date(from: item.created_at) ?? Date()
            )
        }
    }

    /// 获取已下载文件列表
    func fetchFiles() async throws -> Data { try await get("/api/files") }

    // MARK: - SSE 进度流

    /// 开始监听下载进度事件
    /// - Parameter onEvent: 每收到一个 SSE 事件时回调
    func listenProgress(onEvent: @escaping (SSEEvent) -> Void) {
        sseTask?.cancel()
        sseTask = Task {
            guard let url = URL(string: "\(baseURL)/api/progress") else { return }
            var request = URLRequest(url: url)
            request.timeoutInterval = 300 // 5 分钟长连接

            do {
                let (bytes, _) = try await URLSession.shared.bytes(for: request)
                for try await line in bytes.lines {
                    guard !Task.isCancelled else { break }
                    // SSE 格式: "data: {...json...}"
                    guard line.hasPrefix("data: ") else { continue }
                    let jsonStr = String(line.dropFirst(6))
                    guard let jsonData = jsonStr.data(using: .utf8),
                          let event = try? JSONDecoder().decode(SSEEvent.self, from: jsonData)
                    else { continue }
                    onEvent(event)
                }
            } catch {
                if !Task.isCancelled {
                    logger.warning("SSE 连接断开: \(error.localizedDescription)")
                }
            }
        }
    }

    /// 停止 SSE 监听
    func stopListening() {
        sseTask?.cancel()
        sseTask = nil
    }

    // MARK: - HTTP 辅助方法

    private func post(_ path: String, body: [String: Any]) async throws -> String {
        guard let url = URL(string: "\(baseURL)\(path)") else { throw URLError(.badURL) }
        var request = URLRequest(url: url, timeoutInterval: 15)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        guard httpResponse.statusCode == 200 else {
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let detail = json["detail"] as? String { throw NSError(domain: "API", code: httpResponse.statusCode, userInfo: [NSLocalizedDescriptionKey: detail]) }
            throw URLError(.badServerResponse)
        }
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let taskId = json["task_id"] as? String else { throw URLError(.cannotParseResponse) }
        return taskId
    }

    private func get(_ path: String) async throws -> Data {
        guard let url = URL(string: "\(baseURL)\(path)") else { throw URLError(.badURL) }
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else { throw URLError(.badServerResponse) }
        return data
    }
}
