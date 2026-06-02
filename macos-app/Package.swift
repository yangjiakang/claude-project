// swift-tools-version: 5.9
// DownieClip — macOS 菜单栏视频下载器，模仿 Downie 4
// Python 后端作为子进程内嵌，SwiftUI 原生界面

import PackageDescription

let package = Package(
    name: "DownieClip",
    platforms: [
        .macOS(.v14)  // 使用 MenuBarExtra 需要 macOS 14+
    ],
    targets: [
        .executableTarget(
            name: "DownieClip",
            path: "Sources/DownieClip",
            resources: [
                .process("Resources")  // 后端 Python 脚本等资源
            ]
        ),
    ]
)
