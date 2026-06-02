import Foundation
import OSLog

/// 管理 Python 后端（FastAPI 服务器）的生命周期
/// App 启动时自动拉起 server.py，退出时自动终止
@MainActor
final class BackendManager: ObservableObject {
    // MARK: - 状态发布
    @Published var isRunning = false       // 后端是否在运行
    @Published var port: UInt16 = 8520     // API 端口（默认 8520）
    @Published var startupLog: String = "" // 启动日志（调试用）

    // MARK: - 内部状态
    private var process: Process?
    private let logger = Logger(subsystem: "com.downieclip.app", category: "Backend")

    /// 后端 API 的基础 URL
    var baseURL: String { "http://localhost:\(port)" }

    // MARK: - 启动后端

    /// 查找后端项目的根目录（包含 backend/server.py）
    private var backendRoot: String? {
        // 开发模式：从项目根目录查找
        let candidates = [
            // 同仓库下的 backend/ 目录
            Bundle.main.resourcePath.map { ($0 as NSString).deletingLastPathComponent + "/../../backend" },
            // 硬编码的绝对路径（开发时使用）
            ProcessInfo.processInfo.environment["DOWNIECLIP_BACKEND_ROOT"],
        ]
        for path in candidates {
            if let path, FileManager.default.fileExists(atPath: "\(path)/server.py") {
                return path
            }
        }
        // 回退：假设 app 在项目仓库中运行
        let repoRoot = findRepoRoot()
        if let root = repoRoot, FileManager.default.fileExists(atPath: "\(root)/backend/server.py") {
            return "\(root)/backend"
        }
        return nil
    }

    /// 查找项目仓库根目录
    private func findRepoRoot() -> String? {
        var url = URL(fileURLWithPath: #filePath)
        while url.path != "/" {
            url = url.deletingLastPathComponent()
            let gitDir = url.appendingPathComponent(".git")
            if FileManager.default.fileExists(atPath: gitDir.path) { return url.path }
        }
        return nil
    }

    /// 启动 Python 后端服务
    func start() {
        guard !isRunning else { return }
        guard let backendPath = backendRoot else {
            startupLog = "❌ 找不到 backend/server.py"
            logger.error("找不到后端目录，请设置 DOWNIECLIP_BACKEND_ROOT 环境变量")
            return
        }
        guard let pythonPath = findPython() else {
            startupLog = "❌ 找不到 Python 解释器"
            logger.error("找不到 .venv/bin/python，请先安装依赖")
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = ["backend/server.py"]
        process.currentDirectoryURL = URL(fileURLWithPath: backendPath)

        // 传递端口号
        var env = ProcessInfo.processInfo.environment
        env["PORT"] = String(port)
        process.environment = env

        // 捕获标准输出用于调试
        let stdoutPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stdoutPipe

        // 读取启动日志
        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let self else { return }
            let text = String(decoding: data, as: UTF8.self)
            Task { @MainActor in
                self.startupLog += text
                // 截断过长日志
                if self.startupLog.count > 2000 {
                    self.startupLog = String(self.startupLog.suffix(1000))
                }
            }
        }

        process.terminationHandler = { [weak self] proc in
            Task { @MainActor in
                self?.isRunning = false
                self?.logger.info("后端进程已退出 (exit=\(proc.terminationStatus))")
            }
        }

        do {
            try process.run()
            self.process = process
            self.isRunning = true
            startupLog = "🚀 后端启动中...\n端口: \(port)\n路径: \(backendPath)"
            logger.info("后端已启动 (pid=\(process.processIdentifier))")
        } catch {
            startupLog = "❌ 启动失败: \(error.localizedDescription)"
            logger.error("启动后端失败: \(error)")
        }
    }

    /// 停止 Python 后端服务
    func stop() {
        guard let process, process.isRunning else { return }
        process.terminate()
        // 给进程 2 秒时间优雅退出
        DispatchQueue.global().asyncAfter(deadline: .now() + 2) { [weak process] in
            if process?.isRunning == true { process?.interrupt() }
        }
        self.process = nil
        isRunning = false
        logger.info("后端已停止")
    }

    /// 重启后端
    func restart() {
        stop()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            self?.start()
        }
    }

    // MARK: - 健康检查（轮询等待后端就绪）

    /// 等待后端就绪（最多等待 `timeout` 秒）
    func waitUntilReady(timeout: TimeInterval = 10) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let ready = try? await checkHealth(), ready { return true }
            try? await Task.sleep(nanoseconds: 500_000_000) // 0.5s 间隔
        }
        return false
    }

    /// 检查后端健康状态
    private func checkHealth() async throws -> Bool {
        guard let url = URL(string: "\(baseURL)/api/health") else { return false }
        var request = URLRequest(url: url, timeoutInterval: 3)
        request.httpMethod = "GET"
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else { return false }
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        return json["status"] as? String == "ok"
    }

    // MARK: - 查找 Python 解释器

    private func findPython() -> String? {
        let candidates = [
            // 项目 .venv 中的 Python
            "\(findRepoRoot() ?? "")/.venv/bin/python",
            // 系统 Python
            "/usr/bin/python3",
        ]
        for path in candidates {
            let trimmed = path.trimmingCharacters(in: .whitespaces)
            if !trimmed.isEmpty && FileManager.default.fileExists(atPath: trimmed) { return trimmed }
        }
        // 使用 which python3
        let which = Process()
        which.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        which.arguments = ["which", "python3"]
        let pipe = Pipe()
        which.standardOutput = pipe
        do {
            try which.run()
            which.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let path = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            if !path.isEmpty { return path }
        } catch {}
        return nil
    }
}
