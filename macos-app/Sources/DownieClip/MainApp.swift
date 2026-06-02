import SwiftUI
import AppKit

/// DownieClip — 模仿 Downie 4 的 macOS 菜单栏视频下载器
/// Phase 2: 剪贴板检测 + 拖拽 URL + 系统通知 + 下载进度条
@main
struct DownieClipApp: App {
    @StateObject private var backend = BackendManager()
    @StateObject private var store: DownloadStore
    @StateObject private var clipboard = ClipboardManager()
    @StateObject private var notifications = NotificationManager()

    init() {
        let api = APIClient(baseURL: "http://localhost:8520")
        let store = DownloadStore(api: api)
        _store = StateObject(wrappedValue: store)
    }

    var body: some Scene {
        // ═══ 菜单栏图标 + 弹出面板 ═══
        MenuBarExtra {
            MenuBarView(store: store, backend: backend, clipboard: clipboard)
                .onAppear {
                    clipboard.startMonitoring()
                    notifications.requestPermission()
                    store.notificationManager = notifications  // 注入通知管理器
                }
                .onDisappear {
                    clipboard.stopMonitoring()
                }
        } label: {
            Image(systemName: menuBarIcon)
                .foregroundColor(menuBarColor)
        }
        .menuBarExtraStyle(.window)

        // ═══ 设置窗口 ═══
        Settings {
            SettingsView(backend: backend, store: store, clipboard: clipboard, notifications: notifications)
        }
    }

    // MARK: - 菜单栏图标

    private var menuBarIcon: String {
        if clipboard.showClipboardHint { return "doc.on.clipboard.fill" } // 剪贴板检测到 URL
        if store.isDownloading { return "arrow.down.circle.fill" }
        if !backend.isRunning { return "xmark.circle" }
        return "arrow.down.to.line.circle"
    }

    private var menuBarColor: Color {
        if clipboard.showClipboardHint { return .orange }
        if store.isDownloading { return .blue }
        if !backend.isRunning { return .red }
        return .primary
    }
}

// MARK: - 设置窗口

struct SettingsView: View {
    @ObservedObject var backend: BackendManager
    @ObservedObject var store: DownloadStore
    @ObservedObject var clipboard: ClipboardManager
    @ObservedObject var notifications: NotificationManager

    @State private var outputDir: String = ""

    var body: some View {
        TabView {
            // ═══ 通用设置 ═══
            Form {
                Section("后端服务") {
                    HStack {
                        Text("状态:")
                        Circle().frame(width: 8, height: 8).foregroundColor(backend.isRunning ? .green : .red)
                        Text(backend.isRunning ? "运行中" : "已停止").font(.caption)
                        Spacer()
                        Button(backend.isRunning ? "重启" : "启动") {
                            if backend.isRunning { backend.restart() } else { backend.start() }
                        }
                    }
                    if !backend.startupLog.isEmpty {
                        Text(backend.startupLog)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(.secondary)
                            .lineLimit(8)
                    }
                }

                Section("功能开关") {
                    Toggle("剪贴板自动检测", isOn: Binding(
                        get: { clipboard.isMonitoring },
                        set: { if $0 { clipboard.startMonitoring() } else { clipboard.stopMonitoring() } }
                    ))
                    Text("检测到视频 URL 时自动提示").font(.caption).foregroundColor(.secondary)
                }

                Section("下载目录") {
                    HStack {
                        TextField("输出路径", text: $outputDir).font(.system(size: 12))
                        Button("浏览...") {
                            let panel = NSOpenPanel()
                            panel.canChooseDirectories = true
                            panel.canChooseFiles = false
                            if panel.runModal() == .OK {
                                outputDir = panel.url?.path ?? outputDir
                            }
                        }
                    }
                    Button("在 Finder 中打开") { store.openOutputDirectory() }
                }
            }
            .tabItem { Label("通用", systemImage: "gear") }
            .padding()

            // ═══ 通知 ═══
            Form {
                Section("系统通知") {
                    Button("请求通知权限") {
                        notifications.requestPermission()
                    }
                    Button("发送测试通知") {
                        notifications.sendDownloadComplete(
                            filename: "测试视频.mp4",
                            fileSize: "123.7 MB",
                            url: "https://example.com"
                        )
                    }
                    Text("下载完成时自动推送 macOS 通知").font(.caption).foregroundColor(.secondary)
                }
            }
            .tabItem { Label("通知", systemImage: "bell") }
            .padding()

            // ═══ 关于 ═══
            VStack(spacing: 12) {
                Image(systemName: "arrow.down.to.line.circle").font(.system(size: 48)).foregroundColor(.blue)
                Text("DownieClip").font(.title2).fontWeight(.bold)
                Text("模仿 Downie 4 的 macOS 视频下载器").font(.caption).foregroundColor(.secondary)
                Text("SwiftUI + Python 后端 + ffmpeg").font(.caption2).foregroundColor(.secondary)
                Divider().frame(width: 200)
                Text("Phase 2 功能").font(.headline)
                Text("• 剪贴板自动检测 URL\n• 拖拽 URL 到输入区\n• 下载完成系统通知\n• 内嵌进度条").font(.caption).foregroundColor(.secondary)
                Text("版本 0.2.0").font(.caption2).foregroundColor(.secondary)
            }
            .tabItem { Label("关于", systemImage: "info.circle") }
            .padding()
            .frame(width: 320, height: 260)
        }
    }
}
