import SwiftUI
import AppKit

/// 🐱 DownieClip — 可爱风 macOS 视频下载器
/// 独立窗口 App（非菜单栏），模仿 Downie 4 体验
@main
struct KawaiiDownieApp: App {
    @StateObject private var backend = BackendManager()
    @StateObject private var store: DownloadStore
    @StateObject private var clipboard = ClipboardManager()
    @StateObject private var notifications = NotificationManager()

    init() {
        let api = APIClient(baseURL: "http://localhost:8520")
        let store = DownloadStore(api: api)
        _store = StateObject(wrappedValue: store)

        // 启动后端 + 注入通知
        store.notificationManager = notifications
    }

    var body: some Scene {
        // ─── 主窗口 ───
        WindowGroup {
            HomeView(store: store, backend: backend, clipboard: clipboard)
                .onAppear {
                    // 自动启动 Python 后端
                    if !backend.isRunning { backend.start() }
                    clipboard.startMonitoring()
                    notifications.requestPermission()
                    store.notificationManager = notifications
                }
                .onDisappear {
                    clipboard.stopMonitoring()
                }
                .preferredColorScheme(.dark)
        }
        .windowStyle(.titleBar)
        .windowToolbarStyle(.unifiedCompact)
        .windowResizability(.contentSize)
        .defaultSize(width: 520, height: 720)
        .commands {
            // 菜单栏命令
            CommandGroup(replacing: .newItem) {}
            CommandMenu("下载") {
                Button("从剪贴板粘贴") {
                    if let url = NSPasteboard.general.string(forType: .string),
                       url.hasPrefix("http") {
                        // 触发下载（通过通知）
                        NotificationCenter.default.post(name: .init("downloadURL"), object: url)
                    }
                }
                .keyboardShortcut("v", modifiers: [.command, .shift])
            }
        }

        // ─── 设置窗口 ───
        Settings {
            SettingsView(backend: backend, store: store, clipboard: clipboard, notifications: notifications)
        }
    }
}

// MARK: - 设置窗口

struct SettingsView: View {
    @ObservedObject var backend: BackendManager
    @ObservedObject var store: DownloadStore
    @ObservedObject var clipboard: ClipboardManager
    @ObservedObject var notifications: NotificationManager

    var body: some View {
        TabView {
            // ═══ 通用 ═══
            Form {
                Section {
                    HStack {
                        Text("后端状态")
                        Spacer()
                        Circle().frame(width: 8, height: 8)
                            .foregroundColor(backend.isRunning ? .green : .red)
                        Text(backend.isRunning ? "运行中" : "已停止")
                            .font(.caption)
                        Button(backend.isRunning ? "重启" : "启动") {
                            if backend.isRunning { backend.restart() } else { backend.start() }
                        }
                    }
                } header: { Text("服务").font(.headline) }

                Section {
                    Toggle("剪贴板自动检测", isOn: Binding(
                        get: { clipboard.isMonitoring },
                        set: { if $0 { clipboard.startMonitoring() } else { clipboard.stopMonitoring() } }
                    ))
                    Text("检测到视频 URL 时自动提示").font(.caption).foregroundColor(.secondary)
                } header: { Text("功能").font(.headline) }

                Section {
                    Button("打开下载目录") { store.openOutputDirectory() }
                } header: { Text("文件").font(.headline) }
            }
            .tabItem { Label("通用", systemImage: "gearshape.fill") }
            .padding()

            // ═══ 通知 ═══
            Form {
                Section {
                    Button("请求通知权限") { notifications.requestPermission() }
                    Button("发送测试通知") {
                        notifications.sendDownloadComplete(
                            filename: "测试视频.mp4", fileSize: "123.7 MB"
                        )
                    }
                } header: { Text("系统通知").font(.headline) }
            }
            .tabItem { Label("通知", systemImage: "bell.fill") }
            .padding()

            // ═══ 关于 ═══
            VStack(spacing: 16) {
                Text("🐱").font(.system(size: 56))
                Text("DownieClip").font(.title).fontWeight(.bold).fontDesign(.rounded)
                Text("可爱的视频下载助手 ✨")
                    .font(.subheadline).foregroundColor(.secondary)
                Divider().frame(width: 160)
                VStack(spacing: 6) {
                    Text("🐱 SwiftUI 原生界面").font(.caption).foregroundColor(.secondary)
                    Text("🐍 Python 后端引擎").font(.caption).foregroundColor(.secondary)
                    Text("🎬 ffmpeg 视频处理").font(.caption).foregroundColor(.secondary)
                }
                Text("版本 3.0 — Kawaii Edition 💜")
                    .font(.caption2).foregroundColor(.secondary)
            }
            .tabItem { Label("关于", systemImage: "heart.fill") }
            .padding()
            .frame(width: 300, height: 280)
        }
    }
}
