import Foundation
import AppKit
import UserNotifications
import OSLog

/// 系统通知管理器 —— 下载完成时推送 macOS 原生通知
/// 模仿 Downie 4 的「下载完成」弹窗
@MainActor
final class NotificationManager: NSObject, ObservableObject {
    private let logger = Logger(subsystem: "com.downieclip.app", category: "Notification")
    private var center: UNUserNotificationCenter?
    private(set) var isAvailable = false  // 通知是否可用（Bundle ID 存在时才可用）

    override init() {
        super.init()
        // 命令行运行的 Swift 可执行文件没有 Bundle ID，UNUserNotificationCenter 会崩溃
        // 所以这里用安全检查
        if Bundle.main.bundleIdentifier != nil {
            center = UNUserNotificationCenter.current()
            center?.delegate = self
            isAvailable = true
            logger.info("通知系统可用")
        } else {
            logger.warning("无 Bundle ID，通知系统不可用（需打包为 .app 后运行）")
        }
    }

    /// 请求通知权限
    func requestPermission() {
        guard let center, isAvailable else { return }
        center.requestAuthorization(options: [.alert, .sound, .badge]) { granted, error in
            if let error {
                self.logger.error("通知权限请求失败: \(error)")
            } else {
                self.logger.info("通知权限: \(granted ? "已授权" : "已拒绝")")
            }
        }
    }

    /// 发送下载完成通知
    /// - Parameters:
    ///   - filename: 下载的文件名
    ///   - fileSize: 文件大小描述（如 "123.7 MB"）
    ///   - url: 来源网址（用于点击跳转）
    func sendDownloadComplete(filename: String, fileSize: String, url: String = "") {
        let content = UNMutableNotificationContent()
        content.title = "⬇ 下载完成"
        content.body = filename.isEmpty ? "视频已保存" : filename
        if !fileSize.isEmpty {
            content.subtitle = "大小: \(fileSize)"
        }
        content.sound = .default

        // 点击通知后打开下载目录
        if let repoRoot = findRepoRoot() {
            content.userInfo = ["outputDir": "\(repoRoot)/videos"]
        }

        // 附加缩略图（如果有）
        content.categoryIdentifier = "DOWNLOAD_COMPLETE"

        let request = UNNotificationRequest(
            identifier: "download-\(Date().timeIntervalSince1970)",
            content: content,
            trigger: nil  // 立即发送
        )

        center?.add(request) { error in
            if let error {
                self.logger.error("通知发送失败: \(error)")
            } else {
                self.logger.info("通知已发送: \(filename)")
            }
        }
    }

    /// 发送下载失败通知
    func sendDownloadFailed(url: String, error: String) {
        let content = UNMutableNotificationContent()
        content.title = "❌ 下载失败"
        content.body = url.prefix(80).description
        content.subtitle = error
        content.sound = .default

        let request = UNNotificationRequest(
            identifier: "fail-\(Date().timeIntervalSince1970)",
            content: content,
            trigger: nil
        )
        center?.add(request) { _ in }
    }

    /// 发送批量下载完成通知
    func sendBatchComplete(total: Int, downloaded: Int) {
        let content = UNMutableNotificationContent()
        content.title = "🎉 批量下载完成"
        content.body = "共 \(total) 个任务，成功 \(downloaded) 个"
        content.sound = .default

        let request = UNNotificationRequest(
            identifier: "batch-\(Date().timeIntervalSince1970)",
            content: content,
            trigger: nil
        )
        center?.add(request) { _ in }
    }

    // MARK: - 辅助

    private func findRepoRoot() -> String? {
        var url = URL(fileURLWithPath: #filePath)
        while url.path != "/" {
            url = url.deletingLastPathComponent()
            if FileManager.default.fileExists(atPath: url.appendingPathComponent(".git").path) { return url.path }
        }
        return nil
    }
}

// MARK: - UNUserNotificationCenterDelegate

extension NotificationManager: UNUserNotificationCenterDelegate {
    /// 即使 App 在前台也显示通知横幅
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .badge])
    }

    /// 用户点击通知后的操作
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        if let outputDir = response.notification.request.content.userInfo["outputDir"] as? String {
            DispatchQueue.main.async {
                NSWorkspace.shared.open(URL(fileURLWithPath: outputDir))
            }
        }
        completionHandler()
    }
}
