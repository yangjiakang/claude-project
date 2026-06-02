import SwiftUI
import UniformTypeIdentifiers

/// 菜单栏弹出面板 — 快速粘贴 URL 下载 + 进度列表 + 拖拽 + 剪贴板检测
struct MenuBarView: View {
    @ObservedObject var store: DownloadStore
    @ObservedObject var backend: BackendManager
    @ObservedObject var clipboard: ClipboardManager
    @State private var urlText = ""
    @FocusState private var isFocused: Bool
    @State private var isDropTargeted = false

    var body: some View {
        VStack(spacing: 0) {
            // ═══ 剪贴板检测提示 ═══
            if clipboard.showClipboardHint, let detectedURL = clipboard.detectedURL {
                clipboardHintBar(url: detectedURL)
            }

            // ═══ 拖拽区域 ═══
            VStack(spacing: 0) {
                // 顶部：URL 输入区
                HStack(spacing: 8) {
                    TextField("粘贴视频 URL，按 Enter 下载...", text: $urlText)
                        .textFieldStyle(.plain)
                        .focused($isFocused)
                        .onSubmit { submitURL() }
                        .font(.system(size: 13))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .background(Color.primary.opacity(0.06))
                        .cornerRadius(8)
                        .disabled(store.isDownloading)

                    Button(action: submitURL) {
                        Image(systemName: store.isDownloading ? "stop.circle.fill" : "arrow.down.circle.fill")
                            .font(.system(size: 20))
                            .foregroundStyle(store.isDownloading ? .red : .blue)
                    }
                    .buttonStyle(.plain)
                    .keyboardShortcut(.return, modifiers: [])
                }
                .padding(.horizontal, 12)
                .padding(.top, 12)
                .padding(.bottom, 8)

                // 批量粘贴提示
                if !urlText.contains("\n") && urlText.isEmpty && !clipboard.showClipboardHint {
                    Text("支持多行批量粘贴（最多3个）· 拖拽 URL 到此处")
                        .font(.system(size: 10))
                        .foregroundColor(.secondary)
                        .padding(.bottom, 4)
                }
            }
            // 🎯 拖拽支持：接受 URL 和纯文本
            .onDrop(of: [.url, .plainText, .fileURL], isTargeted: $isDropTargeted) { providers in
                handleDrop(providers: providers)
                return true
            }
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .strokeBorder(
                        isDropTargeted ? Color.blue : Color.clear,
                        style: StrokeStyle(lineWidth: 2, dash: [5, 3])
                    )
            )
            .padding(.horizontal, 4)

            Divider()

            // ═══ 下载进度列表 ═══
            if store.tasks.isEmpty && store.completedTasks.isEmpty {
                emptyStateView
            } else {
                downloadListView
            }

            // ═══ 底部状态栏 ═══
            Divider()
            bottomBar
        }
        .frame(width: 360)
        .frame(minHeight: 200, maxHeight: 500)
        .onAppear { isFocused = true }
    }

    // MARK: - 剪贴板提示条

    private func clipboardHintBar(url: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "doc.on.clipboard")
                .font(.system(size: 12))
                .foregroundColor(.blue)
            Text("检测到视频链接:")
                .font(.system(size: 11, weight: .medium))
                .foregroundColor(.secondary)
            Text(url)
                .font(.system(size: 11))
                .lineLimit(1)
                .truncationMode(.middle)
                .foregroundColor(.blue)
            Spacer()
            Button("下载") {
                urlText = url
                submitURL()
                clipboard.dismissHint()
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
            .font(.system(size: 11))
            Button {
                clipboard.dismissHint()
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .font(.system(size: 12))
                    .foregroundColor(.secondary)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(Color.blue.opacity(0.08))
    }

    // MARK: - 拖拽处理

    private func handleDrop(providers: [NSItemProvider]) {
        for provider in providers {
            // 尝试读取 URL 类型
            if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                provider.loadItem(forTypeIdentifier: UTType.url.identifier, options: nil) { item, _ in
                    if let urlData = item as? Data,
                       let url = URL(dataRepresentation: urlData, relativeTo: nil) {
                        Task { @MainActor in self.addURL(url.absoluteString) }
                    }
                }
            }
            // 尝试读取纯文本（可能包含 URL）
            else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
                provider.loadItem(forTypeIdentifier: UTType.plainText.identifier, options: nil) { item, _ in
                    if let text = item as? String {
                        let urls = text.components(separatedBy: .newlines)
                            .map { $0.trimmingCharacters(in: .whitespaces) }
                            .filter { $0.hasPrefix("http://") || $0.hasPrefix("https://") }
                        Task { @MainActor in
                            for url in urls.prefix(3) { self.addURL(url) }
                        }
                    }
                }
            }
        }
    }

    private func addURL(_ url: String) {
        if urlText.isEmpty {
            urlText = url
        } else {
            urlText += "\n" + url
        }
        // 自动提交（可选：让用户手动点击）
    }

    // MARK: - 空状态

    private var emptyStateView: some View {
        VStack(spacing: 12) {
            Image(systemName: "arrow.down.to.line.circle")
                .font(.system(size: 36))
                .foregroundColor(.secondary.opacity(0.5))
            Text("粘贴链接 · 拖拽 URL · 复制后自动检测")
                .font(.system(size: 13))
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
            HStack(spacing: 4) {
                Image(systemName: "checkmark.circle.fill").font(.system(size: 10)).foregroundColor(.green)
                Text("后端 \(backend.isRunning ? "运行中 ✅" : "未启动 ❌")")
                    .font(.system(size: 11)).foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 40)
    }

    // MARK: - 下载列表

    private var downloadListView: some View {
        ScrollView {
            LazyVStack(spacing: 6) {
                ForEach(store.tasks) { task in
                    DownloadRowView(task: task, store: store)
                }
                if store.tasks.isEmpty && !store.completedTasks.isEmpty {
                    Section {
                        Text("最近完成")
                            .font(.system(size: 10))
                            .foregroundColor(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    ForEach(store.completedTasks.prefix(5)) { task in
                        DownloadRowView(task: task, store: store)
                    }
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
        }
    }

    // MARK: - 底部栏

    private var bottomBar: some View {
        HStack {
            HStack(spacing: 4) {
                Circle().frame(width: 7, height: 7).foregroundColor(statusDotColor)
                Text(store.statusMessage)
                    .font(.system(size: 11)).foregroundColor(.secondary).lineLimit(1)
            }
            Spacer()
            HStack(spacing: 8) {
                Button(action: { store.openOutputDirectory() }) {
                    Image(systemName: "folder.circle").font(.system(size: 15))
                }.buttonStyle(.plain).help("打开下载目录")
                if !store.completedTasks.isEmpty {
                    Button(action: { store.clearCompleted() }) {
                        Image(systemName: "trash.circle").font(.system(size: 15))
                    }.buttonStyle(.plain).help("清空历史")
                }
                Circle().frame(width: 7, height: 7)
                    .foregroundColor(backend.isRunning ? .green : .red)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    // MARK: - 辅助

    private var statusDotColor: Color {
        if store.isDownloading { return .blue }
        if store.statusMessage.contains("✅") { return .green }
        if store.statusMessage.contains("❌") { return .red }
        return .gray
    }

    private func submitURL() {
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
        urlText = ""
        isFocused = false
        clipboard.dismissHint()
    }
}

// MARK: - 下载条目行

struct DownloadRowView: View {
    let task: DownloadTask
    @ObservedObject var store: DownloadStore

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: statusIcon)
                .font(.system(size: 14))
                .foregroundColor(statusColor)
                .frame(width: 18)

            VStack(alignment: .leading, spacing: 2) {
                Text(task.filename.isEmpty ? extractFilename(from: task.url) : task.filename)
                    .font(.system(size: 12, weight: .medium)).lineLimit(1)
                if !task.url.isEmpty {
                    Text(task.url)
                        .font(.system(size: 10)).foregroundColor(.secondary).lineLimit(1)
                }
                // 下载中显示进度条
                if task.status == .downloading {
                    ProgressView(value: task.progress, total: 100)
                        .scaleEffect(x: 1, y: 0.5, anchor: .center)
                        .frame(height: 4)
                }
            }
            Spacer()
            if task.status == .downloading {
                VStack(alignment: .trailing, spacing: 1) {
                    Text("\(Int(task.progress))%")
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundColor(.blue)
                    if !store.downloadSpeed.isEmpty {
                        Text(store.downloadSpeed)
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundColor(.secondary)
                    }
                }
            } else if task.status == .completed {
                Text(task.fileSizeMB > 0 ? String(format: "%.1f MB", task.fileSizeMB) : "OK")
                    .font(.system(size: 10)).foregroundColor(.green)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill(task.status == .downloading ? Color.blue.opacity(0.08) : Color.clear)
        )
        .contextMenu {
            if task.status == .completed || task.status == .failed {
                Button("删除") { store.removeTask(task) }
            }
        }
    }

    private var statusIcon: String {
        switch task.status {
        case .pending: "hourglass.circle"
        case .downloading: "arrow.down.circle"
        case .converting: "arrow.triangle.2.circlepath"
        case .completed: "checkmark.circle.fill"
        case .failed: "xmark.circle.fill"
        }
    }
    private var statusColor: Color {
        switch task.status {
        case .pending: .gray; case .downloading: .blue
        case .converting: .orange; case .completed: .green; case .failed: .red
        }
    }
    private func extractFilename(from url: String) -> String {
        url.split(separator: "/").suffix(2).joined(separator: "/")
    }
}
