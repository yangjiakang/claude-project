import SwiftUI

/// 主界面 — 可爱风视频下载器
struct HomeView: View {
    @ObservedObject var store: DownloadStore
    @ObservedObject var backend: BackendManager
    @ObservedObject var clipboard: ClipboardManager

    @State private var urlText = ""
    @State private var isInputFocused = false
    @State private var showConfetti = false
    @FocusState private var textFieldFocused: Bool

    // 吉祥物状态
    private var mascotState: MascotView.MascotState {
        if store.statusMessage.contains("❌") { return .error }
        if store.isDownloading { return .downloading(progress: store.totalProgress) }
        if clipboard.showClipboardHint { return .detected }
        if store.statusMessage.contains("✅") { return .completed }
        return .idle
    }

    var body: some View {
        ZStack {
            // ─── 背景 ───
            backgroundLayer

            // ─── 主内容 ───
            VStack(spacing: 0) {
                // 顶部标题栏
                titleBar
                    .padding(.horizontal, 30)
                    .padding(.top, 24)

                ScrollView {
                    VStack(spacing: 24) {
                        // ─── 吉祥物 ───
                        MascotView(state: mascotState)
                            .padding(.top, 10)

                        // ─── 状态提示语 ───
                        statusBubble
                            .padding(.horizontal, 20)

                        // ─── URL 输入区 ───
                        inputSection
                            .padding(.horizontal, 30)

                        // ─── 下载列表 ───
                        if !store.tasks.isEmpty || !store.completedTasks.isEmpty {
                            downloadSection
                                .padding(.horizontal, 24)
                        }

                        // ─── 最近完成 ───
                        if !store.completedTasks.isEmpty && store.tasks.isEmpty {
                            recentSection
                                .padding(.horizontal, 24)
                        }

                        Spacer(minLength: 80)
                    }
                }

                // ─── 底部状态栏 ───
                bottomBar
            }
        }
        .frame(minWidth: 480, idealWidth: 520, maxWidth: 600,
               minHeight: 640, idealHeight: 720, maxHeight: 900)
        .onAppear {
            clipboard.startMonitoring()
            store.notificationManager?.requestPermission()
        }
        .onDisappear { clipboard.stopMonitoring() }
    }

    // MARK: - 背景

    private var backgroundLayer: some View {
        ZStack {
            Color(hex: "1E1B2E").ignoresSafeArea()

            // 装饰性光斑
            Circle()
                .fill(KawaiiTheme.primary.opacity(0.12))
                .frame(width: 280)
                .blur(radius: 60)
                .offset(x: -120, y: -200)

            Circle()
                .fill(KawaiiTheme.secondary.opacity(0.10))
                .frame(width: 220)
                .blur(radius: 50)
                .offset(x: 140, y: 100)

            Circle()
                .fill(KawaiiTheme.accent.opacity(0.06))
                .frame(width: 180)
                .blur(radius: 40)
                .offset(x: -60, y: 300)
        }
    }

    // MARK: - 标题栏

    private var titleBar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 8) {
                    Text("🐱")
                        .font(.system(size: 28))
                        .float()
                    Text("DownieClip")
                        .font(.system(size: 24, weight: .bold, design: .rounded))
                        .foregroundColor(.white)
                }
                Text("可爱的视频下载助手 ✨")
                    .font(.system(size: 12, weight: .medium, design: .rounded))
                    .foregroundColor(KawaiiTheme.textSecondary)
            }
            Spacer()
            // 后端状态
            HStack(spacing: 6) {
                Circle()
                    .fill(backend.isRunning ? KawaiiTheme.success : KawaiiTheme.error)
                    .frame(width: 8, height: 8)
                Text(backend.isRunning ? "就绪" : "离线")
                    .font(.system(size: 11, design: .rounded))
                    .foregroundColor(KawaiiTheme.textMuted)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(Color.white.opacity(0.06))
            .cornerRadius(KawaiiTheme.radiusFull)
        }
    }

    // MARK: - 状态提示气泡

    private var statusBubble: some View {
        Text(statusMessage)
            .font(.system(size: 14, weight: .medium, design: .rounded))
            .foregroundColor(statusBubbleColor)
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .background(statusBubbleBg)
            .cornerRadius(KawaiiTheme.radiusFull)
            .animation(.easeInOut(duration: 0.5), value: store.statusMessage)
    }

    private var statusMessage: String {
        if clipboard.showClipboardHint { return "✨ 检测到视频链接，快来下载吧～" }
        if store.isDownloading {
            let active = store.tasks.filter { $0.status == .downloading }.count
            let queued = store.tasks.filter { $0.status == .queued }.count
            return "🐱 下载中 \(active) 个" + (queued > 0 ? " · 排队 \(queued) 个" : "")
        }
        if store.statusMessage.contains("✅") { return "🎉 下载完成啦！好棒！" }
        if store.statusMessage.contains("❌") { return "😿 呜呜，下载失败了..." }
        return "💜 粘贴视频链接，小 Downie 帮你下载～"
    }

    private var statusBubbleColor: Color {
        if clipboard.showClipboardHint { return KawaiiTheme.accent }
        if store.isDownloading { return KawaiiTheme.info }
        if store.statusMessage.contains("✅") { return KawaiiTheme.success }
        if store.statusMessage.contains("❌") { return KawaiiTheme.error }
        return KawaiiTheme.textSecondary
    }

    private var statusBubbleBg: Color {
        if clipboard.showClipboardHint { return KawaiiTheme.accent.opacity(0.12) }
        if store.isDownloading { return KawaiiTheme.info.opacity(0.12) }
        if store.statusMessage.contains("✅") { return KawaiiTheme.success.opacity(0.12) }
        if store.statusMessage.contains("❌") { return KawaiiTheme.error.opacity(0.12) }
        return Color.white.opacity(0.05)
    }

    // MARK: - 输入区

    private var inputSection: some View {
        VStack(spacing: 10) {
            // 剪贴板提示
            if clipboard.showClipboardHint, let url = clipboard.detectedURL {
                HStack(spacing: 8) {
                    Text("📋").font(.system(size: 16)).bounce()
                    Text("已检测到链接：")
                        .font(.system(size: 12, design: .rounded))
                        .foregroundColor(KawaiiTheme.accent)
                    Text(url)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(KawaiiTheme.textSecondary)
                        .lineLimit(1)
                    Spacer()
                    Button("使用它 →") {
                        urlText = url
                        clipboard.dismissHint()
                    }
                    .font(.system(size: 11, weight: .bold, design: .rounded))
                    .foregroundColor(KawaiiTheme.accent)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(KawaiiTheme.accent.opacity(0.08))
                .cornerRadius(KawaiiTheme.radiusSm)
                .transition(.move(edge: .top).combined(with: .opacity))
            }

            // URL 输入框
            HStack(spacing: 12) {
                TextField("", text: $urlText)
                    .focused($textFieldFocused)
                    .textFieldStyle(.plain)
                    .font(.system(size: 14, design: .rounded))
                    .foregroundColor(.white)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 16)
                    .background(KawaiiTheme.bgInput)
                    .cornerRadius(KawaiiTheme.radiusFull)
                    .overlay(
                        HStack {
                            if urlText.isEmpty {
                                Text("粘贴视频 URL，小 Downie 帮你下载... 🎀")
                                    .font(.system(size: 13, design: .rounded))
                                    .foregroundColor(KawaiiTheme.textMuted)
                                    .padding(.leading, 24)
                                    .allowsHitTesting(false)
                            }
                            Spacer()
                        }
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: KawaiiTheme.radiusFull)
                            .stroke(
                                isInputFocused
                                ? KawaiiTheme.primary.opacity(0.6)
                                : Color.white.opacity(0.08),
                                lineWidth: 2
                            )
                    )
                    .onChange(of: textFieldFocused) { isInputFocused = $0 }
                    .onSubmit { submitDownload() }
                    .disabled(store.isDownloading)

                // 下载按钮
                Button(action: submitDownload) {
                    ZStack {
                        Circle()
                            .fill(KawaiiTheme.gradientPrimary)
                            .frame(width: 52, height: 52)
                            .shadow(color: KawaiiTheme.primary.opacity(0.4), radius: 10, y: 4)

                        if store.isDownloading {
                            ProgressView()
                                .progressViewStyle(CircularProgressViewStyle(tint: .white))
                                .scaleEffect(0.8)
                        } else {
                            Image(systemName: "arrow.down")
                                .font(.system(size: 20, weight: .bold))
                                .foregroundColor(.white)
                        }
                    }
                }
                .buttonStyle(.plain)
                .disabled(urlText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.isDownloading)
                .scaleEffect(urlText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.92 : 1.0)
                .animation(.spring(response: 0.3, dampingFraction: 0.6), value: urlText)
            }

            // 快捷提示
            HStack(spacing: 16) {
                Label("支持批量（最多3个）", systemImage: "square.stack.3d.up")
                    .font(.system(size: 10, design: .rounded))
                    .foregroundColor(KawaiiTheme.textMuted)
                Label("拖拽链接到窗口", systemImage: "hand.draw")
                    .font(.system(size: 10, design: .rounded))
                    .foregroundColor(KawaiiTheme.textMuted)
                Label("Enter  快速下载", systemImage: "keyboard")
                    .font(.system(size: 10, design: .rounded))
                    .foregroundColor(KawaiiTheme.textMuted)
            }
        }
    }

    // MARK: - 下载列表

    private var downloadSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("📥 下载队列")
                    .font(.system(size: 14, weight: .bold, design: .rounded))
                    .foregroundColor(.white)
                Spacer()
                let queued = store.tasks.filter { $0.status == .queued }.count
                Text("\(store.tasks.count) 个任务" + (queued > 0 ? " · \(queued) 等待中" : ""))
                    .font(.system(size: 10, design: .rounded))
                    .foregroundColor(KawaiiTheme.textMuted)
            }

            ForEach(store.tasks) { task in
                DownloadCardView(task: task, store: store)
            }
        }
    }

    // MARK: - 最近完成

    private var recentSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("🏆 最近完成")
                    .font(.system(size: 14, weight: .bold, design: .rounded))
                    .foregroundColor(.white)
                Spacer()
                Button("清空") { store.clearCompleted() }
                    .font(.system(size: 11, design: .rounded))
                    .foregroundColor(KawaiiTheme.textMuted)
            }

            ForEach(store.completedTasks.prefix(5)) { task in
                DownloadCardView(task: task, store: store)
            }
        }
    }

    // MARK: - 底部栏

    private var bottomBar: some View {
        HStack(spacing: 20) {
            Button(action: { store.openOutputDirectory() }) {
                Label("打开文件夹", systemImage: "folder")
                    .font(.system(size: 11, design: .rounded))
            }
            .buttonStyle(.plain)
            .foregroundColor(KawaiiTheme.textSecondary)

            Spacer()

            Text("v0.3")
                .font(.system(size: 10, design: .monospaced))
                .foregroundColor(KawaiiTheme.textMuted.opacity(0.5))
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
        .background(Color(hex: "161322"))
    }

    // MARK: - 动作

    private func submitDownload() {
        let text = urlText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }

        let lines = text.components(separatedBy: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { $0.hasPrefix("http://") || $0.hasPrefix("https://") }
            .prefix(3)

        if lines.count > 1 {
            store.downloadURLs(Array(lines))
        } else if let url = lines.first {
            store.downloadURL(url)
        }

        withAnimation(.spring(response: 0.4, dampingFraction: 0.6)) {
            urlText = ""
        }
        textFieldFocused = false
        clipboard.dismissHint()
    }
}

// MARK: - 下载卡片

/// 可爱的下载进度卡片 — 进度条始终可见 + 历史缩略图
struct DownloadCardView: View {
    let task: DownloadTask
    @ObservedObject var store: DownloadStore
    @State private var thumbnail: NSImage?

    private let thumbnailGen = ThumbnailGenerator()

    var body: some View {
        VStack(spacing: 0) {
            // ─── 内容行 ───
            HStack(spacing: 12) {
                // 缩略图 / 状态图标
                if let thumb = thumbnail {
                    Image(nsImage: thumb)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .frame(width: 60, height: 36)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                } else {
                    statusIconView
                        .frame(width: 34, height: 34)
                }

                VStack(alignment: .leading, spacing: 3) {
                    Text(displayName)
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .foregroundColor(.white)
                        .lineLimit(1)

                    if task.status == .completed {
                        Text(task.fileSizeMB > 0 ? String(format: "%.1f MB", task.fileSizeMB) : "完成")
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(KawaiiTheme.success)
                    }
                }

                Spacer()

                // 百分比（下载中时显示）
                if task.status == .downloading {
                    Text("\(Int(task.progress))%")
                        .font(.system(size: 16, weight: .bold, design: .monospaced))
                        .foregroundColor(KawaiiTheme.primary)
                }
            }
            .padding(.horizontal, 14)
            .padding(.top, 12)
            .padding(.bottom, task.status == .downloading ? 4 : 12)

            // ─── 进度条（下载中时始终显示） ───
            if task.status == .downloading {
                FrameProgressBar(
                    progress: task.progress,
                    isActive: true,
                    speed: store.downloadSpeed
                )
                .padding(.horizontal, 14)
                .padding(.bottom, 12)
            }
        }
        .background(KawaiiTheme.bgCard)
        .cornerRadius(KawaiiTheme.radiusMd)
        .overlay(
            RoundedRectangle(cornerRadius: KawaiiTheme.radiusMd)
                .stroke(
                    task.status == .downloading
                    ? KawaiiTheme.primary.opacity(0.3)
                    : Color.white.opacity(0.05),
                    lineWidth: 1.5
                )
        )
        .task {
            if task.status == .completed && !task.filename.isEmpty && thumbnail == nil {
                await loadThumbnail()
            }
        }
        .onChange(of: task.status) { _, newStatus in
            if newStatus == .completed { Task { await loadThumbnail() } }
        }
    }

    // MARK: - 加载缩略图

    private func loadThumbnail() async {
        guard let root = findRepoRoot() else { return }
        let videoPath = "\(root)/videos/\(task.filename)"
        guard FileManager.default.fileExists(atPath: videoPath) else { return }
        thumbnail = await thumbnailGen.generateThumbnail(for: videoPath)
    }

    private func findRepoRoot() -> String? {
        var url = URL(fileURLWithPath: #filePath)
        while url.path != "/" {
            url = url.deletingLastPathComponent()
            if FileManager.default.fileExists(atPath: url.appendingPathComponent(".git").path) {
                return url.path
            }
        }
        return nil
    }

    // MARK: - 辅助

    private var displayName: String {
        if !task.filename.isEmpty { return task.filename }
        return task.url.split(separator: "/").suffix(2).joined(separator: "/")
    }

    @ViewBuilder
    private var statusIconView: some View {
        switch task.status {
        case .queued:
            Text("⏳").font(.system(size: 20)).opacity(0.5)
        case .pending:
            Text("⏳").font(.system(size: 20))
        case .downloading:
            Text("🐱").font(.system(size: 20)).bounce()
        case .converting:
            Text("🔄").font(.system(size: 20))
        case .completed:
            ZStack {
                Circle()
                    .fill(KawaiiTheme.success.opacity(0.2))
                    .frame(width: 34, height: 34)
                Text("🎀").font(.system(size: 16))
            }
        case .failed:
            Text("💔").font(.system(size: 20))
        }
    }
}
