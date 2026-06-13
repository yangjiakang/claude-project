import SwiftUI

/// 简洁的视频进度条 — 带胶片风格动画
struct FrameProgressBar: View {
    let progress: Double      // 0-100
    let isActive: Bool        // 是否正在下载
    let speed: String         // 下载速度

    @State private var shinePos: CGFloat = -0.3

    var body: some View {
        VStack(spacing: 6) {
            // ─── 进度条主体 ───
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    // 背景轨道
                    RoundedRectangle(cornerRadius: 6)
                        .fill(Color.white.opacity(0.08))
                        .frame(height: 4)

                    // 已下载部分 — 粉紫渐变
                    RoundedRectangle(cornerRadius: 6)
                        .fill(
                            LinearGradient(
                                colors: [Color(hex: "B794F4"), Color(hex: "F472B6")],
                                startPoint: .leading, endPoint: .trailing
                            )
                        )
                        .frame(width: max(0, geo.size.width * progress / 100), height: 10)

                    // 光泽扫描线
                    if isActive {
                        RoundedRectangle(cornerRadius: 6)
                            .fill(Color.white.opacity(0.25))
                            .frame(width: 30, height: 10)
                            .offset(x: geo.size.width * shinePos)
                            .animation(
                                .linear(duration: 1.8).repeatForever(autoreverses: false),
                                value: shinePos
                            )
                    }
                }
            }
            .frame(height: 4)

            // ─── 百分比 + 速度 ───
            HStack {
                Text("\(Int(progress))%")
                    .font(.system(size: 14, weight: .bold, design: .monospaced))
                    .foregroundColor(isActive ? KawaiiTheme.primary : KawaiiTheme.success)

                if isActive && !speed.isEmpty {
                    Text("·")
                        .foregroundColor(KawaiiTheme.textMuted)
                    Text(speed)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(KawaiiTheme.textSecondary)
                }

                Spacer()

                if isActive {
                    HStack(spacing: 3) {
                        ForEach(0..<3, id: \.self) { i in
                            Circle()
                                .fill(KawaiiTheme.primary)
                                .frame(width: 5, height: 5)
                                .opacity(dotOpacity(i))
                                .animation(
                                    .easeInOut(duration: 0.5).repeatForever().delay(Double(i) * 0.2),
                                    value: progress
                                )
                        }
                    }
                } else if progress >= 100 {
                    Text("✅")
                        .font(.system(size: 13))
                }
            }
        }
        .onAppear {
            if isActive { shinePos = 1.0 }
        }
    }

    func dotOpacity(_ index: Int) -> Double {
        // 基于进度的小动画
        let p = progress / 100.0
        let offset = Double(index) * 0.33
        let val = (p + offset).truncatingRemainder(dividingBy: 1.0)
        return val < 0.5 ? 1.0 : 0.3
    }
}
