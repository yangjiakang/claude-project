import SwiftUI
import AppKit
import OSLog

/// 剪贴板监听器 —— 模仿 Downie 4 的自动检测 URL 功能
/// 定时检查 NSPasteboard，发现视频 URL 时弹出提示
@MainActor
final class ClipboardManager: ObservableObject {
    @Published var detectedURL: String?       // 当前检测到的视频 URL
    @Published var showClipboardHint = false // 是否显示「粘贴」提示
    @Published var isMonitoring = false      // 是否正在监听

    private var lastChangeCount: Int = 0
    private var monitorTimer: Timer?
    private let logger = Logger(subsystem: "com.downieclip.app", category: "Clipboard")
    private let pasteboard = NSPasteboard.general

    /// 可识别的视频网站域名模式
    private let videoSitePatterns: [String] = [
        "hl718.com", "pornhub.com", "phncdn.com",
        "youtube.com", "youtu.be", "bilibili.com",
        "vimeo.com", "dailymotion.com", "twitch.tv",
        "douyin.com", "tiktok.com", "ixigua.com",
        ".m3u8", ".mp4", ".webm", ".mkv",
    ]

    /// 开始监听剪贴板（每秒检查一次）
    func startMonitoring() {
        guard !isMonitoring else { return }
        isMonitoring = true
        lastChangeCount = pasteboard.changeCount
        logger.info("剪贴板监听已启动")

        monitorTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.checkPasteboard() }
        }
    }

    /// 停止监听
    func stopMonitoring() {
        monitorTimer?.invalidate()
        monitorTimer = nil
        isMonitoring = false
        showClipboardHint = false
        logger.info("剪贴板监听已停止")
    }

    /// 检查剪贴板内容
    private func checkPasteboard() {
        let currentCount = pasteboard.changeCount
        guard currentCount != lastChangeCount else { return }
        lastChangeCount = currentCount

        // 读取剪贴板文本
        guard let items = pasteboard.pasteboardItems else { return }
        for item in items {
            if let urlString = item.string(forType: .URL) ?? item.string(forType: .string) {
                let trimmed = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
                if isVideoURL(trimmed) {
                    detectedURL = trimmed
                    showClipboardHint = true
                    logger.info("检测到视频 URL: \(trimmed.prefix(60))...")
                    return
                }
            }
        }

        // 无匹配 URL 时隐藏提示
        showClipboardHint = false
        detectedURL = nil
    }

    /// 判断 URL 是否为视频链接
    private func isVideoURL(_ url: String) -> Bool {
        guard url.hasPrefix("http://") || url.hasPrefix("https://") else { return false }
        let lowercased = url.lowercased()
        return videoSitePatterns.contains { lowercased.contains($0) }
    }

    /// 用户已处理当前检测到的 URL，清除提示
    func dismissHint() {
        detectedURL = nil
        showClipboardHint = false
    }
}
