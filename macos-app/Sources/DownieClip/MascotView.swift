import SwiftUI

/// 可爱吉祥物 — 小 Downie 猫猫 🐱
/// 根据下载状态显示不同表情和动画
struct MascotView: View {
    let state: MascotState
    @State private var blink = false
    @State private var wiggle = false
    @State private var sparkles: [Sparkle] = []

    enum MascotState: Equatable {
        case idle        // 等待中
        case detected    // 检测到 URL
        case downloading(progress: Double) // 下载中
        case completed   // 完成
        case error       // 失败
    }

    var body: some View {
        ZStack {
            // 飘落的装饰粒子
            ForEach(sparkles) { s in
                Circle()
                    .fill(s.color)
                    .frame(width: s.size, height: s.size)
                    .position(s.position)
                    .opacity(s.opacity)
            }

            VStack(spacing: 2) {
                // ─── 耳朵 ───
                HStack(spacing: 28) {
                    ear(isLeft: true)
                    ear(isLeft: false)
                }
                .offset(y: 4)

                // ─── 脸 ───
                ZStack {
                    // 脸部背景
                    RoundedRectangle(cornerRadius: 30)
                        .fill(
                            LinearGradient(
                                colors: [Color(hex: "FFF0F5"), Color(hex: "FDE2F3")],
                                startPoint: .top, endPoint: .bottom
                            )
                        )
                        .frame(width: 100, height: 85)
                        .shadow(color: .pink.opacity(0.2), radius: 12, y: 4)

                    // 腮红
                    Circle()
                        .fill(Color.pink.opacity(0.3))
                        .frame(width: 14, height: 10)
                        .offset(x: -26, y: 10)
                    Circle()
                        .fill(Color.pink.opacity(0.3))
                        .frame(width: 14, height: 10)
                        .offset(x: 26, y: 10)

                    // ─── 表情 ───
                    faceExpression
                        .offset(y: -2)
                }

                // ─── 身体 ───
                RoundedRectangle(cornerRadius: 14)
                    .fill(
                        LinearGradient(
                            colors: [Color(hex: "FFF0F5"), Color(hex: "FCE4EC")],
                            startPoint: .top, endPoint: .bottom
                        )
                    )
                    .frame(width: 52, height: 32)
                    .offset(y: -4)
            }
            .rotationEffect(.degrees(wiggle ? 3 : -3))
        }
        .frame(width: 160, height: 160)
        .onAppear {
            // 眨眼定时器
            Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { _ in
                withAnimation(.easeOut(duration: 0.1)) { blink = true }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                    withAnimation(.easeIn(duration: 0.1)) { blink = false }
                }
            }
            // 身体摇摆
            withAnimation(.easeInOut(duration: 2.0).repeatForever(autoreverses: true)) {
                wiggle = true
            }
            // 完成时放烟花
            if state == .completed { spawnSparkles() }
        }
        .onChange(of: state) { newState in
            if newState == .completed { spawnSparkles() }
        }
    }

    // MARK: - 部件

    private func ear(isLeft: Bool) -> some View {
        Triangle()
            .fill(
                LinearGradient(
                    colors: [Color(hex: "FFD6E0"), Color(hex: "FFACC5")],
                    startPoint: .top, endPoint: .bottom
                )
            )
            .overlay(
                Triangle()
                    .fill(Color.pink.opacity(0.3))
                    .scaleEffect(0.55)
            )
            .frame(width: 22, height: 24)
            .rotationEffect(.degrees(isLeft ? -15 : 15))
    }

    @ViewBuilder
    private var faceExpression: some View {
        switch state {
        case .idle:
            happyFace
        case .detected:
            excitedFace
        case .downloading:
            focusedFace
        case .completed:
            loveFace
        case .error:
            sadFace
        }
    }

    // 😊 开心（等待）
    private var happyFace: some View {
        VStack(spacing: 6) {
            HStack(spacing: 32) {
                Circle().fill(Color(hex: "3D2C2E")).frame(width: 9, height: 10)
                Circle().fill(Color(hex: "3D2C2E")).frame(width: 9, height: 10)
            }
            .scaleEffect(y: blink ? 0.1 : 1)

            // 😊 微笑
            CurvedMouth()
                .stroke(Color(hex: "3D2C2E"), style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                .frame(width: 18, height: 8)
        }
    }

    // 🤩 兴奋（检测到 URL）
    private var excitedFace: some View {
        VStack(spacing: 5) {
            HStack(spacing: 28) {
                // 星星眼
                Text("✨").font(.system(size: 14))
                Text("✨").font(.system(size: 14))
            }
            // 张大的嘴
            Ellipse()
                .fill(Color(hex: "5D3A3A"))
                .frame(width: 14, height: 9)
        }
    }

    // 🧐 专注（下载中）
    private var focusedFace: some View {
        VStack(spacing: 5) {
            HStack(spacing: 34) {
                Circle().fill(Color(hex: "3D2C2E")).frame(width: 8, height: 9)
                    .scaleEffect(y: blink ? 0.1 : 1)
                Circle().fill(Color(hex: "3D2C2E")).frame(width: 8, height: 9)
            }
            // 认真的嘴巴
            Text("⚡")
                .font(.system(size: 12))
        }
    }

    // 🥰 爱心眼（完成）
    private var loveFace: some View {
        VStack(spacing: 4) {
            HStack(spacing: 30) {
                Text("❤️").font(.system(size: 13))
                Text("❤️").font(.system(size: 13))
            }
            // 开心的嘴
            CurvedMouth()
                .stroke(Color(hex: "3D2C2E"), style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                .frame(width: 20, height: 10)
                .scaleEffect(y: 1.2)
        }
    }

    // 😿 难过（失败）
    private var sadFace: some View {
        VStack(spacing: 5) {
            HStack(spacing: 32) {
                Circle().fill(Color(hex: "3D2C2E")).frame(width: 9, height: 10)
                Circle().fill(Color(hex: "3D2C2E")).frame(width: 9, height: 10)
            }
            // 难过的嘴（倒弧）
            CurvedMouth(inverted: true)
                .stroke(Color(hex: "3D2C2E"), style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                .frame(width: 14, height: 7)
            // 泪滴
            Text("💧")
                .font(.system(size: 10))
                .offset(x: 20, y: -4)
        }
    }

    // MARK: - 烟花粒子

    private func spawnSparkles() {
        let colors: [Color] = [.pink, .purple, .yellow, .mint, .blue, .orange]
        for i in 0..<18 {
            let angle = Double(i) * .pi * 2 / 18
            let sparkle = Sparkle(
                id: UUID(),
                color: colors[i % colors.count],
                position: CGPoint(x: 80 + cos(angle) * 30, y: 80 + sin(angle) * 30),
                size: CGFloat.random(in: 4...8),
                opacity: 1.0
            )
            sparkles.append(sparkle)
            withAnimation(.easeOut(duration: 1.0).delay(Double.random(in: 0...0.3))) {
                if let idx = sparkles.firstIndex(where: { $0.id == sparkle.id }) {
                    sparkles[idx].position = CGPoint(
                        x: sparkle.position.x + cos(angle) * 60,
                        y: sparkle.position.y + sin(angle) * 60
                    )
                    sparkles[idx].opacity = 0
                }
            }
        }
        // 清理
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
            sparkles.removeAll()
        }
    }
}

// MARK: - 辅助形状

struct Triangle: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: rect.midX, y: rect.minY))
        p.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
        p.closeSubpath()
        return p
    }
}

struct CurvedMouth: Shape {
    var inverted: Bool = false
    func path(in rect: CGRect) -> Path {
        var p = Path()
        if inverted {
            p.move(to: CGPoint(x: rect.minX, y: rect.maxY))
            p.addQuadCurve(to: CGPoint(x: rect.maxX, y: rect.maxY),
                           control: CGPoint(x: rect.midX, y: rect.minY))
        } else {
            p.move(to: CGPoint(x: rect.minX, y: rect.minY))
            p.addQuadCurve(to: CGPoint(x: rect.maxX, y: rect.minY),
                           control: CGPoint(x: rect.midX, y: rect.maxY))
        }
        return p
    }
}

struct Sparkle: Identifiable {
    let id: UUID
    var color: Color
    var position: CGPoint
    var size: CGFloat
    var opacity: Double
}
