#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# DownieClip — macOS App 打包脚本
# 将 Swift 二进制 + Python 后端 + ffmpeg 打包为可分发的 .app
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

APP_NAME="DownieClip"
VERSION="${1:-0.3.0}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$SCRIPT_DIR/.build"
APP_BUNDLE="$SCRIPT_DIR/$APP_NAME.app"
CONTENTS="$APP_BUNDLE/Contents"
MACOS_DIR="$CONTENTS/MacOS"
RESOURCES_DIR="$CONTENTS/Resources"
FRAMEWORKS_DIR="$CONTENTS/Frameworks"

echo "╔══════════════════════════════════════════════╗"
echo "║   DownieClip 打包脚本 v$VERSION              ║"
echo "╚══════════════════════════════════════════════╝"

# ── Step 1: 编译 Swift App ──
echo ""
echo "📦 Step 1/5: 编译 Swift App..."
cd "$SCRIPT_DIR"
swift build -c release 2>&1 | tail -2
SWIFT_BIN="$BUILD_DIR/release/$APP_NAME"
if [ ! -f "$SWIFT_BIN" ]; then
    echo "⚠️  Release 编译失败，使用 Debug 版本..."
    swift build 2>&1 | tail -2
    SWIFT_BIN="$BUILD_DIR/debug/$APP_NAME"
fi
echo "   ✅ Swift 二进制: $SWIFT_BIN"

# ── Step 2: 创建 App Bundle 结构 ──
echo ""
echo "📁 Step 2/5: 创建 App Bundle..."
rm -rf "$APP_BUNDLE"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$FRAMEWORKS_DIR"

# 复制主程序
cp "$SWIFT_BIN" "$MACOS_DIR/$APP_NAME"
chmod +x "$MACOS_DIR/$APP_NAME"

# 创建 Info.plist
cat > "$CONTENTS/Info.plist" << PLEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>zh_CN</string>
    <key>CFBundleDisplayName</key>
    <string>DownieClip</string>
    <key>CFBundleExecutable</key>
    <string>DownieClip</string>
    <key>CFBundleIdentifier</key>
    <string>com.downieclip.app</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>DownieClip</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundleVersion</key>
    <string>$(echo $VERSION | tr -d '.')</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSHumanReadableCopyright</key>
    <string>Copyright © 2026 DownieClip. MIT License.</string>
</dict>
</plist>
PLEOF
echo "   ✅ Bundle 结构已创建"

# ── Step 3: 复制 Python 后端 ──
echo ""
echo "🐍 Step 3/5: 打包 Python 后端..."
BACKEND_SRC="$PROJECT_ROOT/backend"
PYTHON_RESOURCES="$RESOURCES_DIR/backend"

mkdir -p "$PYTHON_RESOURCES"
# 复制 Python 源码
cp "$BACKEND_SRC/server.py" "$PYTHON_RESOURCES/"
# 复制 video_scraper 模块
mkdir -p "$PYTHON_RESOURCES/claude_project"
cp "$PROJECT_ROOT/src/claude_project/video_scraper.py" "$PYTHON_RESOURCES/claude_project/"
touch "$PYTHON_RESOURCES/claude_project/__init__.py"
# 复制 requirements（如果有）
[ -f "$PROJECT_ROOT/requirements.txt" ] && cp "$PROJECT_ROOT/requirements.txt" "$RESOURCES_DIR/"

echo "   ✅ Python 后端已复制"

# ── Step 4: 检测并复制 ffmpeg ──
echo ""
echo "🎬 Step 4/5: 打包 ffmpeg..."
FFMPEG_PATH=""
FFPROBE_PATH=""
for candidate in $(which ffmpeg 2>/dev/null) \
                 /opt/homebrew/bin/ffmpeg \
                 /usr/local/bin/ffmpeg \
                 /usr/bin/ffmpeg; do
    if [ -x "$candidate" ]; then
        FFMPEG_PATH="$candidate"
        FFPROBE_PATH="${candidate%ffmpeg}ffprobe"
        break
    fi
done

if [ -n "$FFMPEG_PATH" ]; then
    cp "$FFMPEG_PATH" "$FRAMEWORKS_DIR/ffmpeg"
    chmod +x "$FRAMEWORKS_DIR/ffmpeg"
    [ -x "$FFPROBE_PATH" ] && cp "$FFPROBE_PATH" "$FRAMEWORKS_DIR/ffprobe" && chmod +x "$FRAMEWORKS_DIR/ffprobe"
    echo "   ✅ ffmpeg: $(file "$FFMPEG_PATH" | cut -d, -f1)"
else
    echo "   ⚠️  未找到 ffmpeg（用户需自行安装）"
fi

# ── Step 5: 创建启动脚本 ──
echo ""
echo "📜 Step 5/5: 创建启动脚本..."
cat > "$MACOS_DIR/launch-backend.sh" << 'SHEOF'
#!/bin/bash
# DownieClip 后端启动脚本（App Bundle 内调用）
BUNDLE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RESOURCES="$BUNDLE_DIR/Resources"
FRAMEWORKS="$BUNDLE_DIR/Frameworks"

# 查找 Python
PYTHON=""
for p in "$RESOURCES/python/bin/python3" \
         /usr/bin/python3 \
         /opt/homebrew/bin/python3 \
         /usr/local/bin/python3; do
    if [ -x "$p" ]; then PYTHON="$p"; break; fi
done

if [ -z "$PYTHON" ]; then
    echo "❌ 未找到 Python3" >&2
    exit 1
fi

# 在 PATH 前添加内嵌 ffmpeg
export PATH="$FRAMEWORKS:$PATH"

# 启动 FastAPI 后端
exec "$PYTHON" "$RESOURCES/backend/server.py"
SHEOF
chmod +x "$MACOS_DIR/launch-backend.sh"
echo "   ✅ 启动脚本已创建"

# ── 创建 DMG（可选） ──
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ 打包完成!"
echo ""
echo "  App:  $APP_BUNDLE"
echo "  大小: $(du -sh "$APP_BUNDLE" | cut -f1)"
echo ""
echo "  运行: open $APP_BUNDLE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 如果安装了 create-dmg，创建 DMG
if command -v create-dmg &>/dev/null; then
    DMG_PATH="$SCRIPT_DIR/$APP_NAME-$VERSION.dmg"
    echo ""
    echo "📀 创建 DMG 安装包..."
    create-dmg \
        --volname "$APP_NAME $VERSION" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "$APP_NAME.app" 150 190 \
        --hide-extension "$APP_NAME.app" \
        --app-drop-link 450 190 \
        "$DMG_PATH" \
        "$SCRIPT_DIR" 2>/dev/null
    echo "   ✅ DMG: $DMG_PATH"
fi
