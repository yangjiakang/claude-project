import SwiftUI

// MARK: - Kawaii Design System

/// 可爱风格配色方案
struct KawaiiTheme {
    // 主色调 — 柔和粉紫渐变
    static let primary    = Color(hex: "B794F4")  // 淡紫
    static let secondary  = Color(hex: "F472B6")  // 粉色
    static let accent     = Color(hex: "FBBF24")  // 暖黄

    // 背景色系
    static let bgDark     = Color(hex: "1E1B2E")  // 深紫黑
    static let bgCard     = Color(hex: "2D2944")  // 卡片紫
    static let bgInput    = Color(hex: "1A1728")  // 输入框
    static let bgOverlay  = Color(hex: "363154")  // 悬浮层

    // 文字
    static let textPrimary   = Color.white
    static let textSecondary = Color(hex: "A8A4C8")
    static let textMuted     = Color(hex: "6B6785")

    // 状态色
    static let success    = Color(hex: "6EE7B7")  // 薄荷绿
    static let error      = Color(hex: "FCA5A5")  // 柔红
    static let warning    = Color(hex: "FCD34D")  // 暖黄
    static let info       = Color(hex: "93C5FD")  // 天蓝

    // 渐变
    static let gradientPrimary = LinearGradient(
        colors: [Color(hex: "B794F4"), Color(hex: "F472B6")],
        startPoint: .topLeading, endPoint: .bottomTrailing
    )
    static let gradientCard = LinearGradient(
        colors: [Color(hex: "2D2944"), Color(hex: "252140")],
        startPoint: .top, endPoint: .bottom
    )
    static let gradientCelebrate = LinearGradient(
        colors: [Color(hex: "F472B6"), Color(hex: "FBBF24"), Color(hex: "6EE7B7"), Color(hex: "93C5FD"), Color(hex: "B794F4")],
        startPoint: .leading, endPoint: .trailing
    )

    // 圆角
    static let radiusSm: CGFloat = 12
    static let radiusMd: CGFloat = 20
    static let radiusLg: CGFloat = 28
    static let radiusFull: CGFloat = 999

    // 阴影
    static func cardShadow(_ color: Color = .black) -> some View {
        color.opacity(0.25).blur(radius: 20).offset(y: 8)
    }
}

extension Color {
    init(hex: String) {
        let scanner = Scanner(string: hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted))
        var rgb: UInt64 = 0
        scanner.scanHexInt64(&rgb)
        self.init(
            red: Double((rgb >> 16) & 0xFF) / 255.0,
            green: Double((rgb >> 8) & 0xFF) / 255.0,
            blue: Double(rgb & 0xFF) / 255.0
        )
    }
}

// MARK: - 自定义 View Modifiers

/// 卡片样式
struct KawaiiCard: ViewModifier {
    var padding: CGFloat = 20
    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(KawaiiTheme.gradientCard)
            .cornerRadius(KawaiiTheme.radiusMd)
            .shadow(color: .black.opacity(0.2), radius: 15, y: 6)
    }
}

/// 毛玻璃效果
struct FrostedGlass: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(.ultraThinMaterial)
            .cornerRadius(KawaiiTheme.radiusMd)
    }
}

/// 按钮样式
struct KawaiiButton: ViewModifier {
    var isPrimary: Bool = true
    func body(content: Content) -> some View {
        content
            .font(.system(size: 15, weight: .bold, design: .rounded))
            .foregroundColor(.white)
            .padding(.horizontal, 30)
            .padding(.vertical, 14)
            .background(
                isPrimary
                ? AnyView(KawaiiTheme.gradientPrimary)
                : AnyView(Color.white.opacity(0.1))
            )
            .cornerRadius(KawaiiTheme.radiusFull)
            .shadow(color: KawaiiTheme.primary.opacity(isPrimary ? 0.4 : 0), radius: 10, y: 4)
    }
}

/// 弹跳动画
struct BounceAnimation: ViewModifier {
    @State private var bouncing = false
    func body(content: Content) -> some View {
        content
            .scaleEffect(bouncing ? 1.08 : 1.0)
            .onAppear {
                withAnimation(.easeInOut(duration: 0.6).repeatForever(autoreverses: true)) {
                    bouncing = true
                }
            }
    }
}

/// 浮动动画
struct FloatAnimation: ViewModifier {
    @State private var offset: CGFloat = 0
    func body(content: Content) -> some View {
        content
            .offset(y: offset)
            .onAppear {
                withAnimation(.easeInOut(duration: 2.5).repeatForever(autoreverses: true)) {
                    offset = -8
                }
            }
    }
}

// MARK: - 便捷扩展

extension View {
    func kawaiiCard(padding: CGFloat = 20) -> some View {
        modifier(KawaiiCard(padding: padding))
    }
    func kawaiiButton(isPrimary: Bool = true) -> some View {
        modifier(KawaiiButton(isPrimary: isPrimary))
    }
    func bounce() -> some View {
        modifier(BounceAnimation())
    }
    func float() -> some View {
        modifier(FloatAnimation())
    }
}
