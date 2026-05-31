"""视频下载 & 格式转换 —— FastAPI 后端服务

提供以下 API 端点：
- POST /api/scrape      启动视频爬取任务
- GET  /api/progress     获取实时下载进度（SSE 流）
- POST /api/convert      执行视频格式转换
- GET  /api/history      获取下载/转换历史记录
- DELETE /api/history/{id}  删除单条历史记录
"""

from __future__ import annotations

import json  # JSON 序列化/反序列化，用于历史记录存储和 API 响应
import queue  # 线程安全队列，用于在爬取线程和 SSE 推送之间传递进度消息
import sys  # 系统相关，用于添加项目路径
import threading  # 线程支持，后台执行爬取任务不阻塞 API 响应
import time  # 时间戳，用于历史记录和任务 ID 生成
from datetime import datetime, timezone  # 带时区的日期时间处理
from pathlib import Path  # 面向对象的文件路径处理
from typing import Optional  # 可选类型注解

# 将项目 src 目录添加到 Python 路径，以便导入 video_scraper 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claude_project.video_scraper import (  # 导入视频爬取核心模块
    VideoScraper,  # 视频爬取器类
    VideoScrapeConfig,  # 爬取配置数据类
    VideoConverter,  # 视频格式转换器类
)

from fastapi import FastAPI, HTTPException, Query  # FastAPI 框架核心组件
from fastapi.middleware.cors import CORSMiddleware  # 跨域资源共享中间件
from fastapi.responses import StreamingResponse  # 流式响应，用于 SSE
from pydantic import BaseModel  # 请求/响应数据模型验证

# ——— 常量 ———

HISTORY_FILE = Path(__file__).resolve().parent / "history.json"  # 历史记录 JSON 文件路径
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "videos"  # 视频下载默认输出目录

# ——— 全局状态 ———

# 线程安全的进度消息队列，爬取线程向队列写入消息，SSE 端点从队列读取
_progress_queue: queue.Queue[str] = queue.Queue()
# 当前运行的任务 ID，None 表示没有活动任务
_current_task: Optional[str] = None
# 线程锁，保护 _current_task 的读写操作
_task_lock = threading.Lock()

# ——— 应用初始化 ———

app = FastAPI(  # 创建 FastAPI 应用实例
    title="视频下载 & 格式转换",  # API 文档标题
    version="1.0.0",  # 版本号
    description="网页视频爬取、下载、格式转换一体化服务",  # API 描述
)

app.add_middleware(  # 添加中间件
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源的跨域请求（开发阶段）
    allow_credentials=True,  # 允许携带 Cookie
    allow_methods=["*"],  # 允许所有 HTTP 方法
    allow_headers=["*"],  # 允许所有请求头
)


# ——— 数据模型 ———

class ScrapeRequest(BaseModel):
    """视频爬取请求模型"""
    url: str  # 目标网页 URL
    max_videos: int = 1  # 最大下载数量，默认 1
    concurrent: int = 1  # 并发线程数
    skip_head: bool = False  # 是否跳过 HEAD 预检
    timeout: int = 60  # 请求超时秒数


class BatchScrapeRequest(BaseModel):
    """批量视频爬取请求模型"""
    urls: list[str]  # 目标网页 URL 列表（最多 3 个，避免载荷过大）
    max_videos_per_url: int = 1  # 每个 URL 的最大下载数量
    concurrent: int = 1  # 并发线程数
    skip_head: bool = False  # 是否跳过 HEAD 预检
    timeout: int = 60  # 请求超时秒数


class ConvertRequest(BaseModel):
    """格式转换请求模型"""
    file_path: str  # 源视频文件的绝对路径
    target_format: str  # 目标格式，如 "webm"、"mkv"、"mov"
    preset: str = "medium"  # 编码速度预设
    remove_original: bool = False  # 转换成功后是否删除原文件


class HistoryItem(BaseModel):
    """历史记录条目模型"""
    id: str  # 唯一标识符
    url: str  # 目标 URL
    filename: str  # 下载的文件名
    file_size_mb: float  # 文件大小（MB）
    duration_sec: float  # 视频时长（秒）
    format: str  # 文件格式
    status: str  # 状态：completed / failed / converted
    created_at: str  # 创建时间（ISO 8601）


# ——— 历史记录管理 ———

def _load_history() -> list[dict]:
    """从 JSON 文件加载历史记录

    Returns:
        历史记录字典列表
    """
    if HISTORY_FILE.exists():  # 历史文件存在
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:  # 读取 JSON 文件
                return json.load(f)  # 解析并返回
        except (json.JSONDecodeError, OSError):
            return []  # 文件损坏或不可读，返回空列表
    return []  # 文件不存在，返回空列表


def _save_history(history: list[dict]) -> None:
    """将历史记录保存到 JSON 文件

    Args:
        history: 历史记录字典列表
    """
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:  # 写入 JSON 文件
        json.dump(history, f, ensure_ascii=False, indent=2)  # 格式化保存，支持中文


def _add_history_entry(
    url: str, filename: str, file_size_mb: float, duration_sec: float,
    video_format: str, status: str = "completed",
) -> str:
    """向历史记录中添加一条新条目

    Args:
        url: 来源 URL
        filename: 文件名
        file_size_mb: 文件大小（MB）
        duration_sec: 时长（秒）
        video_format: 格式
        status: 状态

    Returns:
        新条目的 ID
    """
    history = _load_history()  # 加载现有历史
    entry_id = f"task_{int(time.time() * 1000)}"  # 基于时间戳生成唯一 ID
    entry = {  # 构建历史条目字典
        "id": entry_id,
        "url": url,
        "filename": filename,
        "file_size_mb": round(file_size_mb, 1),
        "duration_sec": round(duration_sec, 1),
        "format": video_format,
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),  # ISO 8601 格式时间戳
    }
    history.insert(0, entry)  # 最新记录插入到列表开头
    # 限制最多保留 100 条历史记录，超出部分截掉
    _save_history(history[:100])  # 保存到文件
    return entry_id  # 返回新条目 ID


# ——— SSE 进度推送 ———

def _push_progress(message: str) -> None:
    """向进度队列推送一条消息

    Args:
        message: JSON 格式的进度消息字符串
    """
    _progress_queue.put(message)  # 放入线程安全队列


# ——— API 端点 ———

@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    return {"status": "ok", "ffmpeg_available": bool(shutil_which("ffmpeg"))}  # 返回服务和 ffmpeg 状态


import shutil  # 延迟导入，避免循环依赖
shutil_which = shutil.which  # 别名，减少重复输入


@app.post("/api/scrape")
async def scrape_video(req: ScrapeRequest):
    """启动视频爬取任务（异步后台执行）

    Args:
        req: 爬取请求参数

    Returns:
        包含任务 ID 和立即结果的响应
    """
    global _current_task  # 声明使用全局变量

    with _task_lock:  # 加锁保护
        if _current_task is not None:  # 已有任务在运行
            raise HTTPException(status_code=409, detail="已有任务在运行，请等待完成后再试")
        task_id = f"task_{int(time.time() * 1000)}"  # 生成任务 ID
        _current_task = task_id  # 标记当前活动任务

    # 构建爬取配置
    config = VideoScrapeConfig(  # 创建配置对象
        url=req.url,
        output_dir=OUTPUT_DIR,
        max_videos=req.max_videos,
        concurrent=req.concurrent if req.concurrent > 0 else 1,
        skip_head=req.skip_head,
        timeout=req.timeout,
    )

    def _run_scrape():
        """在后台线程中执行爬取任务"""
        global _current_task  # 声明使用全局变量
        try:
            # —— 清理残留的 .m3u8 文件，避免重复处理旧数据 ——
            _cleanup_stale_m3u8(OUTPUT_DIR)  # 删除上次可能遗留的 m3u8 播放列表

            # 推送批量风格事件（单 URL 包装为 batch=1，与批量模式统一格式）
            _push_progress(json.dumps({
                "type": "batch_start",
                "total": 1,
                "message": "📋 开始分析页面...",
            }, ensure_ascii=False))
            _push_progress(json.dumps({
                "type": "url_start",
                "url_index": 0,
                "total": 1,
                "url": req.url,
                "message": f"[1/1] 🔍 分析: {req.url[:60]}...",
            }, ensure_ascii=False))

            scraper = VideoScraper(config)  # 实例化爬取器

            # 重写爬取器的 print 输出，将所有输出重定向到进度队列
            original_print = print  # 保存原始 print 函数

            def _progress_print(*args, **kwargs):
                """拦截 print 输出，转为进度消息推送"""
                msg = " ".join(str(a) for a in args)  # 拼接输出内容
                if msg.strip():  # 非空消息
                    _push_progress(json.dumps({  # 推送为 JSON 进度消息
                        "type": "log",
                        "url_index": 0,  # 关联到 url_index=0 的进度卡片
                        "message": msg.strip(),
                    }, ensure_ascii=False))

            import builtins  # 内置函数模块
            builtins.print = _progress_print  # 全局替换 print 函数

            try:
                result = scraper.scrape()  # 执行爬取
            finally:
                builtins.print = original_print  # 恢复原始 print

            # —— 处理 HLS/m3u8 流媒体：自动用 ffmpeg 下载实际视频 ——
            downloaded_files = list(OUTPUT_DIR.glob("*"))  # 获取输出目录中的所有文件
            downloaded_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)  # 按修改时间倒序

            m3u8_files = [f for f in downloaded_files if f.suffix.lower() == ".m3u8"]  # 筛选 m3u8 文件
            real_video_files: list[Path] = []  # 存储最终的视频文件路径

            for m3u8_file in m3u8_files:
                # 读取已下载的 m3u8 播放列表内容
                try:
                    m3u8_content = m3u8_file.read_text(encoding="utf-8")  # 读取 m3u8 播放列表
                except OSError:
                    m3u8_content = ""

                _push_progress(json.dumps({
                    "type": "log",
                    "url_index": 0,
                    "message": f"⚡ 检测到 HLS 流媒体，使用 ffmpeg 下载实际视频...",
                }, ensure_ascii=False))

                # —— 获取 m3u8 URL 和网页标题 ——
                # 优先从爬取结果中获取 m3u8 URL（省去重复请求页面的时间）
                saved_m3u8_urls: list[str] = result.get("m3u8_urls", [])  # 爬取器已发现的 m3u8 URL
                m3u8_url = saved_m3u8_urls[0] if saved_m3u8_urls else ""  # 取第一个
                page_title = ""  # 网页标题，用于文件命名

                if m3u8_url:
                    # 已有 m3u8 URL，只需获取页面标题（尝试轻量方式）
                    _push_progress(json.dumps({
                        "type": "log",
                        "url_index": 0,
                        "message": "📡 使用已发现的视频源...",
                    }, ensure_ascii=False))
                    # 从 m3u8 文件同目录查找可能的页面标题（从之前 print 拦截的日志中获取）
                    # 如果 m3u8 内容中包含标题信息，提取之
                else:
                    # 回退：重新获取页面提取 m3u8 URL 和标题
                    _push_progress(json.dumps({
                        "type": "log",
                        "url_index": 0,
                        "message": "重新分析页面获取视频源 URL...",
                    }, ensure_ascii=False))

                # 如果还没有 m3u8 URL 或没有标题，重新获取页面
                if not m3u8_url or not page_title:
                    try:
                        import requests as req_lib
                        import re as regex

                        page_resp = req_lib.get(req.url, headers={
                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                        }, timeout=config.timeout)
                        page_resp.raise_for_status()
                        page_html = page_resp.text

                        # 提取网页标题
                        if not page_title:
                            page_title = _extract_page_title(page_html)
                            if page_title:
                                _push_progress(json.dumps({
                                    "type": "log",
                                    "url_index": 0,
                                    "message": f"📄 网页标题: {page_title}",
                                }, ensure_ascii=False))

                        # 如果还没有 m3u8 URL，从页面提取
                        if not m3u8_url:
                            config_match = regex.search(r"data-config='([^']+)'", page_html)
                            if config_match:
                                import html as html_mod
                                config_json = html_mod.unescape(config_match.group(1))
                                try:
                                    config_data = json.loads(config_json)
                                    video_block = config_data.get("video", {})
                                    m3u8_url = video_block.get("url2") or video_block.get("url") or ""
                                except json.JSONDecodeError:
                                    pass
                            if not m3u8_url:
                                m3u8_matches = regex.findall(
                                    r'https?://[^"\'<>]+\.m3u8[^"\'<>]*', page_html
                                )
                                if m3u8_matches:
                                    m3u8_url = m3u8_matches[0]
                    except Exception as page_err:
                        _push_progress(json.dumps({
                            "type": "log",
                            "url_index": 0,
                            "message": f"⚠️ 页面分析异常: {page_err}",
                        }, ensure_ascii=False))

                if m3u8_url:
                    _push_progress(json.dumps({
                        "type": "log",
                        "url_index": 0,
                        "message": f"📡 视频源: {m3u8_url[:80]}...",
                    }, ensure_ascii=False))

                    # 基于网页标题生成输出文件名
                    output_name = _make_output_name(req.url, ".mp4", title=page_title)
                    output_path = OUTPUT_DIR / output_name
                    counter = 1
                    while output_path.exists():
                        counter += 1
                        output_path = OUTPUT_DIR / f"{Path(output_name).stem}_{counter}.mp4"

                    _push_progress(json.dumps({
                        "type": "log",
                        "url_index": 0,
                        "message": f"📁 输出文件: {output_path.name}",
                    }, ensure_ascii=False))

                    # 用 ffmpeg 下载 HLS 流
                    import subprocess as sp

                    # —— 从 m3u8 播放列表解析总时长（#EXTINF 标签），省去 ffprobe 网络请求 ——
                    total_duration_s = _parse_m3u8_duration(m3u8_content)  # 从本地 m3u8 文件解析
                    if total_duration_s <= 0:
                        # 本地解析失败，尝试 ffprobe 快速探测（10s 超时）
                        try:
                            probe_result = sp.run(
                                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "default=noprint_wrappers=1:nokey=1", m3u8_url],
                                capture_output=True, text=True, timeout=10,
                            )
                            if probe_result.returncode == 0 and probe_result.stdout.strip():
                                total_duration_s = float(probe_result.stdout.strip())
                        except Exception:
                            total_duration_s = 0.0

                    # 构建 ffmpeg 命令（包含性能优化参数）
                    ffmpeg_cmd = [
                        "ffmpeg",
                        "-user_agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                        "-multiple_requests", "1",  # 启用持久连接，并行下载 HLS 分片（提速显著）
                        "-reconnect", "1",  # 断线自动重连
                        "-reconnect_streamed", "1",  # 流媒体断线重连
                        "-reconnect_delay_max", "5",  # 最大重连延迟 5 秒
                        "-i", m3u8_url,
                        "-c", "copy",  # 流复制，不重新编码
                        "-bsf:a", "aac_adtstoasc",  # 音频比特流过滤器
                        "-movflags", "+faststart",  # MP4 优化：moov atom 前置，边下边播
                        "-threads", "0",  # 自动检测最优线程数
                        "-progress", "pipe:1",
                        "-nostats",
                        "-loglevel", "error",
                        "-y",
                        str(output_path),
                    ]

                    process = sp.Popen(ffmpeg_cmd, stdout=sp.PIPE, stderr=sp.PIPE,
                                      text=True, encoding="utf-8", errors="replace")

                    # 解析 ffmpeg -progress 输出，计算实时百分比并推送
                    last_progress_pct = -1
                    for line in process.stdout:
                        line = line.strip()
                        if line.startswith("out_time_ms="):
                            try:
                                current_us = int(line.split("=")[1])
                                if total_duration_s > 0:
                                    pct = min(int(current_us / (total_duration_s * 1_000_000) * 100), 99)
                                    if pct >= last_progress_pct + 5:
                                        last_progress_pct = pct
                                        _push_progress(json.dumps({
                                            "type": "ffmpeg_progress",
                                            "url_index": 0,
                                            "percent": pct,
                                            "message": f"⬇ 下载中 {pct}%",
                                        }, ensure_ascii=False))
                            except ValueError:
                                pass

                    process.wait(timeout=7200)

                    if process.returncode == 0 and output_path.exists():
                        size_mb = output_path.stat().st_size / (1024 * 1024)
                        _push_progress(json.dumps({
                            "type": "ffmpeg_progress",
                            "url_index": 0,
                            "percent": 100,
                            "message": f"✅ 下载完成: {output_path.name} ({size_mb:.1f} MB)",
                        }, ensure_ascii=False))
                        m3u8_file.unlink(missing_ok=True)
                        real_video_files.append(output_path)
                    else:
                        _push_progress(json.dumps({
                            "type": "log",
                            "url_index": 0,
                            "message": f"❌ ffmpeg 下载失败 (exit={process.returncode})",
                        }, ensure_ascii=False))
                else:
                    _push_progress(json.dumps({
                        "type": "log",
                        "url_index": 0,
                        "message": "❌ 未找到可用的视频源 URL",
                    }, ensure_ascii=False))

            # 收集最终的文件列表（非 m3u8 的常规文件 + ffmpeg 下载的 mp4）
            all_files = [f for f in OUTPUT_DIR.glob("*") if f.suffix.lower() != ".m3u8"]
            all_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            final_files = all_files[:req.max_videos or len(all_files)]

            for file_path in final_files:
                if file_path.suffix.lower() in (".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv"):
                    try:
                        size_mb = file_path.stat().st_size / (1024 * 1024)  # 计算文件大小 MB
                        # 跳过过小的文件（< 500KB，通常是 GIF 预览或错误页面）
                        if size_mb < 0.5:
                            _push_progress(json.dumps({
                                "type": "log",
                                "url_index": 0,
                                "message": f"⚠️ 跳过过小文件: {file_path.name} ({size_mb:.2f} MB)",
                            }, ensure_ascii=False))
                            file_path.unlink(missing_ok=True)  # 删除无效文件
                            continue
                        duration = _get_video_duration(str(file_path))  # 获取视频时长
                        _add_history_entry(  # 写入历史记录
                            url=req.url,
                            filename=file_path.name,
                            file_size_mb=size_mb,
                            duration_sec=duration,
                            video_format=file_path.suffix.lstrip("."),
                            status="completed",
                        )
                    except OSError:
                        pass  # 文件访问失败则跳过

            # 自动打开输出目录（macOS Finder）
            import platform as _platform  # 检测操作系统
            import subprocess as _sp  # 子进程调用
            try:
                if _platform.system() == "Darwin":  # macOS
                    _sp.run(["open", str(OUTPUT_DIR)])  # 在 Finder 中打开文件夹
                elif _platform.system() == "Windows":  # Windows
                    _sp.run(["explorer", str(OUTPUT_DIR)])  # 在资源管理器中打开
                else:  # Linux
                    _sp.run(["xdg-open", str(OUTPUT_DIR)])  # 用默认文件管理器打开
            except Exception:
                pass  # 打开文件夹失败不影响主流程

            # 推送 url_complete（单 URL 包装为 url_index=0）
            _push_progress(json.dumps({
                "type": "url_complete",
                "url_index": 0,
                "total": 1,
                "url": req.url,
                "downloaded": result.get("downloaded", 0),
                "message": f"[1/1] ✅ 完成: {result.get('downloaded', 0)} 个视频",
            }, ensure_ascii=False))

            # 推送 batch_complete 触发前端清理
            _push_progress(json.dumps({
                "type": "batch_complete",
                "total": 1,
                "downloaded": result.get("downloaded", 0),
                "message": f"🎉 下载完成！成功 {result.get('downloaded', 0)} 个，跳过 {result.get('skipped', 0)}",
                "output_dir": str(OUTPUT_DIR),
            }, ensure_ascii=False))

        except Exception as e:
            # 推送 url_error + batch_complete，与批量模式格式统一
            _push_progress(json.dumps({
                "type": "url_error",
                "url_index": 0,
                "total": 1,
                "url": req.url,
                "message": f"[1/1] ❌ 失败: {e}",
            }, ensure_ascii=False))
            _push_progress(json.dumps({
                "type": "batch_complete",
                "total": 1,
                "downloaded": 0,
                "message": f"❌ 任务失败: {e}",
            }, ensure_ascii=False))
        finally:
            with _task_lock:  # 加锁清理
                _current_task = None  # 清除活动任务标记

    # 启动后台线程执行爬取
    thread = threading.Thread(target=_run_scrape, daemon=True)  # daemon 线程随主进程退出
    thread.start()  # 开始执行

    return {  # 立即返回响应（不等任务完成）
        "task_id": task_id,
        "status": "started",
        "output_dir": str(OUTPUT_DIR),
    }


@app.post("/api/scrape-batch")
async def scrape_video_batch(req: BatchScrapeRequest):
    """批量爬取多个网页的视频

    逐一处理每个 URL，每个 URL 完成后推送独立进度消息。
    全部完成后自动打开输出文件夹。

    Args:
        req: 批量爬取请求参数

    Returns:
        包含任务 ID 和 URL 数量的响应
    """
    global _current_task

    # 限制最多 3 个 URL，避免载荷过大
    if len(req.urls) > 3:
        raise HTTPException(status_code=400, detail=f"最多同时爬取 3 个 URL，当前 {len(req.urls)} 个")

    with _task_lock:
        if _current_task is not None:
            raise HTTPException(status_code=409, detail="已有任务在运行，请等待完成后再试")
        task_id = f"batch_{int(time.time() * 1000)}"
        _current_task = task_id

    total_urls = len(req.urls)

    def _run_batch_scrape():
        """后台逐 URL 处理批量爬取"""
        global _current_task

        # —— 清理残留的 .m3u8 文件，避免重复处理旧数据 ——
        _cleanup_stale_m3u8(OUTPUT_DIR)  # 删除上次可能遗留的 m3u8 播放列表

        # 推送批量任务开始
        _push_progress(json.dumps({
            "type": "batch_start",
            "total": total_urls,
            "message": f"📋 批量任务开始，共 {total_urls} 个 URL",
        }, ensure_ascii=False))

        overall_downloaded = 0  # 总计下载数

        for url_idx, url in enumerate(req.urls):
            url = url.strip()
            if not url:
                continue

            # 推送当前 URL 开始处理
            _push_progress(json.dumps({
                "type": "url_start",
                "url_index": url_idx,
                "total": total_urls,
                "url": url,
                "message": f"[{url_idx + 1}/{total_urls}] 🔍 分析: {url[:60]}...",
            }, ensure_ascii=False))

            # 为每个 URL 构建独立配置
            url_config = VideoScrapeConfig(
                url=url,
                output_dir=OUTPUT_DIR,
                max_videos=req.max_videos_per_url,
                concurrent=req.concurrent if req.concurrent > 0 else 1,
                skip_head=req.skip_head,
                timeout=req.timeout,
            )

            try:
                scraper = VideoScraper(url_config)
                # 拦截 print 输出转为进度推送
                import builtins
                original_print = print

                def _progress_print(*args, **kwargs):
                    msg = " ".join(str(a) for a in args)
                    if msg.strip():
                        _push_progress(json.dumps({
                            "type": "log",
                            "url_index": url_idx,
                            "message": msg.strip(),
                        }, ensure_ascii=False))

                builtins.print = _progress_print
                try:
                    result = scraper.scrape()
                finally:
                    builtins.print = original_print

                overall_downloaded += result.get("downloaded", 0)

                # 处理 HLS/m3u8
                m3u8_files = list(OUTPUT_DIR.glob("*.m3u8"))
                # 从爬取结果获取已发现的 m3u8 URL（省去重复请求页面）
                saved_m3u8_urls: list[str] = result.get("m3u8_urls", [])
                # 从 m3u8 播放列表解析总时长（省去 ffprobe 网络请求）
                m3u8_duration = 0.0

                for m3u8_file in m3u8_files:
                    # 读取 m3u8 内容用于时长解析
                    try:
                        m3u8_content = m3u8_file.read_text(encoding="utf-8")
                    except OSError:
                        m3u8_content = ""

                    _push_progress(json.dumps({
                        "type": "log",
                        "url_index": url_idx,
                        "message": "⚡ 检测到 HLS，使用 ffmpeg 下载...",
                    }, ensure_ascii=False))

                    # 优先使用爬取器已发现的 m3u8 URL
                    if saved_m3u8_urls:
                        m3u8_url = saved_m3u8_urls.pop(0)  # 按顺序取出
                    else:
                        m3u8_url = ""  # 回退到页面解析

                    # 提取 m3u8 URL 和页面标题
                    import requests as req_lib, re as regex, subprocess as sp
                    page_title = ""
                    try:
                        if not m3u8_url:
                            # 没有已保存的 URL，需要重新获取页面
                            page_resp = req_lib.get(url, headers={
                                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                            }, timeout=url_config.timeout)
                            page_html = page_resp.text
                            page_title = _extract_page_title(page_html)

                            config_match = regex.search(r"data-config='([^']+)'", page_html)
                            if config_match:
                                import html as html_mod
                                config_json = html_mod.unescape(config_match.group(1))
                                try:
                                    config_data = json.loads(config_json)
                                    m3u8_url = (config_data.get("video", {}).get("url2") or
                                               config_data.get("video", {}).get("url") or "")
                                except json.JSONDecodeError:
                                    pass
                            if not m3u8_url:
                                m3u8_matches = regex.findall(r'https?://[^"\'<>]+\.m3u8[^"\'<>]*', page_html)
                                if m3u8_matches:
                                    m3u8_url = m3u8_matches[0]

                        if m3u8_url:
                            # 从本地 m3u8 文件解析时长（比 ffprobe 快）
                            if m3u8_duration <= 0 and m3u8_content:
                                m3u8_duration = _parse_m3u8_duration(m3u8_content)
                            if m3u8_duration <= 0:
                                # 回退：ffprobe 快速探测（10s 超时）
                                try:
                                    probe_result = sp.run(
                                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                         "-of", "default=noprint_wrappers=1:nokey=1", m3u8_url],
                                        capture_output=True, text=True, timeout=10,
                                    )
                                    if probe_result.returncode == 0:
                                        m3u8_duration = float(probe_result.stdout.strip())
                                except Exception:
                                    pass

                            output_name = _make_output_name(url, ".mp4", title=page_title)
                            output_path = OUTPUT_DIR / output_name
                            counter = 1
                            while output_path.exists():
                                counter += 1
                                output_path = OUTPUT_DIR / f"{Path(output_name).stem}_{counter}.mp4"

                            # ffmpeg 下载（含性能优化参数）
                            process = sp.Popen([
                                "ffmpeg", "-user_agent",
                                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                                "-multiple_requests", "1",  # 并行下载 HLS 分片
                                "-reconnect", "1",  # 断线重连
                                "-reconnect_streamed", "1",
                                "-reconnect_delay_max", "5",
                                "-i", m3u8_url, "-c", "copy", "-bsf:a", "aac_adtstoasc",
                                "-movflags", "+faststart",  # MP4 优化
                                "-threads", "0",  # 自动线程数
                                "-progress", "pipe:1", "-nostats", "-loglevel", "error",
                                "-y", str(output_path),
                            ], stdout=sp.PIPE, stderr=sp.PIPE, text=True, encoding="utf-8", errors="replace")

                            last_pct = -1
                            for line in process.stdout:
                                line = line.strip()
                                if line.startswith("out_time_ms="):
                                    try:
                                        cur_us = int(line.split("=")[1])
                                        if m3u8_duration > 0:
                                            pct = min(int(cur_us / (m3u8_duration * 1_000_000) * 100), 99)
                                            if pct >= last_pct + 5:
                                                last_pct = pct
                                                _push_progress(json.dumps({
                                                    "type": "ffmpeg_progress",
                                                    "url_index": url_idx,
                                                    "percent": pct,
                                                    "message": f"[{url_idx + 1}/{total_urls}] ⬇ {pct}%",
                                                }, ensure_ascii=False))
                                    except ValueError:
                                        pass

                            process.wait(timeout=7200)
                            if process.returncode == 0 and output_path.exists():
                                m3u8_file.unlink(missing_ok=True)
                    except Exception:
                        pass

                # 写入历史记录
                new_files = sorted(
                    [f for f in OUTPUT_DIR.glob("*") if f.suffix != ".m3u8"],
                    key=lambda p: p.stat().st_mtime, reverse=True
                )[:req.max_videos_per_url or 5]
                for fp in new_files:
                    if fp.suffix.lower() in (".mp4", ".webm", ".mkv", ".mov", ".avi"):
                        try:
                            _add_history_entry(
                                url=url, filename=fp.name,
                                file_size_mb=fp.stat().st_size / (1024 * 1024),
                                duration_sec=_get_video_duration(str(fp)),
                                video_format=fp.suffix.lstrip("."), status="completed",
                            )
                        except OSError:
                            pass

                # 推送当前 URL 完成
                _push_progress(json.dumps({
                    "type": "url_complete",
                    "url_index": url_idx,
                    "total": total_urls,
                    "url": url,
                    "downloaded": result.get("downloaded", 0),
                    "message": f"[{url_idx + 1}/{total_urls}] ✅ 完成: {result.get('downloaded', 0)} 个视频",
                }, ensure_ascii=False))

            except Exception as e:
                _push_progress(json.dumps({
                    "type": "url_error",
                    "url_index": url_idx,
                    "total": total_urls,
                    "url": url,
                    "message": f"[{url_idx + 1}/{total_urls}] ❌ 失败: {e}",
                }, ensure_ascii=False))

        # 全部完成后打开文件夹
        import platform as _platform, subprocess as _sp
        try:
            if _platform.system() == "Darwin":
                _sp.run(["open", str(OUTPUT_DIR)])
            elif _platform.system() == "Windows":
                _sp.run(["explorer", str(OUTPUT_DIR)])
            else:
                _sp.run(["xdg-open", str(OUTPUT_DIR)])
        except Exception:
            pass

        _push_progress(json.dumps({
            "type": "batch_complete",
            "total": total_urls,
            "downloaded": overall_downloaded,
            "message": f"🎉 全部完成！共处理 {total_urls} 个 URL，下载 {overall_downloaded} 个视频",
            "output_dir": str(OUTPUT_DIR),
        }, ensure_ascii=False))

        with _task_lock:
            _current_task = None

    thread = threading.Thread(target=_run_batch_scrape, daemon=True)
    thread.start()

    return {"task_id": task_id, "status": "started", "total_urls": total_urls}


@app.get("/api/progress")
async def stream_progress():
    """SSE（Server-Sent Events）端点 —— 实时推送下载进度

    客户端通过 EventSource 连接到该端点，服务端持续推送进度消息。
    每 500ms 检查一次队列，有消息立即推送，无消息发送心跳注释。
    """
    def _event_generator():
        """SSE 事件生成器"""
        idle_count = 0  # 空闲心跳计数，用于判断任务是否真正结束
        while True:
            try:
                msg = _progress_queue.get(timeout=0.5)  # 阻塞 0.5s 等待消息
                idle_count = 0  # 有消息则重置空闲计数
                yield f"data: {msg}\n\n"  # SSE 格式：data: <json>\n\n
            except queue.Empty:  # 没有新消息（超时）
                yield ": heartbeat\n\n"  # 发送 SSE 心跳注释（保持连接存活）
                with _task_lock:  # 检查任务状态
                    if _current_task is None:  # 任务已标记结束
                        idle_count += 1  # 累加空闲心跳
                        if idle_count >= 4:  # 连续 2 秒（4×0.5s）无消息才真正断开
                            break  # 退出循环，关闭 SSE 连接

    return StreamingResponse(  # 返回流式响应
        _event_generator(),
        media_type="text/event-stream",  # SSE MIME 类型
        headers={
            "Cache-Control": "no-cache",  # 禁止缓存
            "Connection": "keep-alive",  # 保持连接
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )


@app.post("/api/convert")
async def convert_video(req: ConvertRequest):
    """执行视频格式转换

    Args:
        req: 转换请求参数

    Returns:
        转换结果
    """
    input_path = Path(req.file_path)  # 转为 Path 对象
    if not input_path.exists():  # 源文件不存在
        raise HTTPException(status_code=404, detail=f"文件不存在: {req.file_path}")

    try:
        converter = VideoConverter()  # 实例化转换器
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))  # ffmpeg 未安装

    # 将转换过程的输出通过进度队列推送
    def _run_convert():
        """后台执行转换并推送进度"""
        _push_progress(json.dumps({  # 推送开始消息
            "type": "convert_start",
            "message": f"开始转换为 {req.target_format}...",
        }, ensure_ascii=False))

        output_path = converter.convert(  # 调用转换器
            input_path,
            req.target_format,
            preset=req.preset,
            remove_original=req.remove_original,
        )

        if output_path is not None:  # 转换成功
            try:
                size_mb = output_path.stat().st_size / (1024 * 1024)  # 计算新文件大小
                duration = _get_video_duration(str(output_path))  # 获取时长
                _add_history_entry(  # 写入历史记录
                    url=f"convert://{input_path.name}",  # 标记为转换任务
                    filename=output_path.name,
                    file_size_mb=size_mb,
                    duration_sec=duration,
                    video_format=req.target_format,
                    status="converted",  # 状态：已转换
                )
            except OSError:
                pass
            _push_progress(json.dumps({  # 推送成功消息
                "type": "convert_complete",
                "message": f"转换完成 → {output_path.name}",
                "output_path": str(output_path),
                "output_size_mb": round(size_mb, 1) if 'size_mb' in dir() else 0,
            }, ensure_ascii=False))
        else:
            _push_progress(json.dumps({  # 推送失败消息
                "type": "convert_error",
                "message": "格式转换失败",
            }, ensure_ascii=False))

    thread = threading.Thread(target=_run_convert, daemon=True)  # 后台线程
    thread.start()  # 启动

    return {"status": "started", "message": "转换任务已提交"}  # 立即返回


@app.get("/api/history")
async def get_history(
    limit: int = Query(50, ge=1, le=200),  # 限制返回条数，默认 50，范围 1-200
):
    """获取下载/转换历史记录

    Args:
        limit: 返回条数上限

    Returns:
        历史记录列表（按时间倒序）
    """
    history = _load_history()  # 加载历史数据
    return history[:limit]  # 返回前 N 条


@app.delete("/api/history/{entry_id}")
async def delete_history(entry_id: str):
    """删除单条历史记录

    Args:
        entry_id: 要删除的条目 ID

    Returns:
        删除结果
    """
    history = _load_history()  # 加载现有历史
    original_len = len(history)  # 原始长度
    history = [h for h in history if h["id"] != entry_id]  # 过滤掉目标条目
    if len(history) == original_len:  # 没有匹配的条目
        raise HTTPException(status_code=404, detail=f"历史记录不存在: {entry_id}")
    _save_history(history)  # 保存更新后的历史
    return {"status": "deleted", "id": entry_id}


@app.get("/api/files")
async def list_files():
    """列出已下载的视频文件

    Returns:
        文件信息列表
    """
    files = []  # 存储文件信息
    if OUTPUT_DIR.exists():  # 输出目录存在
        for f in sorted(OUTPUT_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            # 按修改时间倒序排列所有文件
            if f.is_file() and f.suffix.lower() in (
                ".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv", ".m4v", ".ogg", ".gif"
            ):
                try:
                    files.append({  # 构建文件信息字典
                        "name": f.name,  # 文件名
                        "path": str(f.resolve()),  # 绝对路径
                        "size_mb": round(f.stat().st_size / (1024 * 1024), 1),  # 大小 MB
                        "format": f.suffix.lstrip("."),  # 格式（去掉点号）
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),  # 修改时间
                    })
                except OSError:
                    pass  # 文件访问失败则跳过
    return files  # 返回文件列表


# ——— 工具函数 ———

def _cleanup_stale_m3u8(directory: Path) -> int:
    """清理输出目录中残留的 .m3u8 文件

    在每次爬取开始前调用，避免旧下载残留的 m3u8 文件
    导致重复处理同一视频流。

    Args:
        directory: 输出目录路径

    Returns:
        删除的文件数量
    """
    count = 0  # 已删除计数
    if directory.exists():
        for m3u8_file in directory.glob("*.m3u8"):  # 遍历所有 m3u8 文件
            try:
                m3u8_file.unlink()  # 删除文件
                count += 1
            except OSError:
                pass  # 无法删除则跳过（如权限问题）
    return count


def _extract_page_title(html: str) -> str:
    """从 HTML 中提取网页标题（<title> 标签内容）

    用于生成有意义的下载文件名。提取到的标题会经过清理：
    - 去掉网站名后缀（如 " - hl718"）、竖线分隔的后缀等
    - 截断到合理长度

    Args:
        html: 网页 HTML 源代码

    Returns:
        清理后的网页标题；提取失败返回空字符串
    """
    import re as _re  # 正则表达式
    match = _re.search(r"<title[^>]*>(.*?)</title>", html, _re.IGNORECASE | _re.DOTALL)
    if not match:
        return ""
    title = match.group(1).strip()  # 提取标题文本并去除首尾空白
    # 解码常见 HTML 实体
    import html as _html
    title = _html.unescape(title)
    # 去掉常见网站名后缀：分隔符 + 网站名（如 "视频标题 - hl718"、"视频标题_网站名"）
    # 常见分隔符： - | — – |
    title = _re.sub(r"\s*[-–—|_]\s*[^-–—|_\s]+$", "", title).strip()
    # 去掉多余空白
    title = _re.sub(r"\s+", " ", title)
    # 截断到 80 字符（保留完整语义且不超出文件系统限制）
    if len(title) > 80:
        title = title[:80]
    return title


def _sanitize_filename(name: str) -> str:
    """清理文件名，移除非法字符

    处理 Windows / macOS / Linux 文件系统不允许的字符，
    以及可能导致问题的特殊字符。

    Args:
        name: 原始文件名（不含扩展名）

    Returns:
        清理后的安全文件名
    """
    import re as _re  # 正则表达式
    # 替换 Windows/macOS 非法字符为下划线
    name = _re.sub(r'[<>:"/\\|?*]', "_", name)
    # 替换换行、制表等控制字符
    name = _re.sub(r'[\x00-\x1f]', "", name)
    # 去除首尾空格和点号（Windows 不允许以点结尾）
    name = name.strip(" .")
    # 如果清理后为空，使用兜底名
    if not name:
        name = "video"
    return name


def _make_output_name(url: str, suffix: str = ".mp4", title: str = "") -> str:
    """生成有意义的输出文件名

    优先级：网页标题 > URL 路径标识 > 时间戳兜底

    Args:
        url: 来源 URL
        suffix: 文件扩展名（默认 .mp4）
        title: 网页标题（可选，优先使用）

    Returns:
        生成的唯一文件名

    Examples:
        - title="大疆 DJI Flip 评测" → 大疆 DJI Flip 评测.mp4
        - title="" + hl718.com/archives/34321 → hl718_34321.mp4
        - 兜底 → hl718_1717000000.mp4
    """
    # 如果有网页标题且标题有意义，优先使用标题命名
    if title and len(title) >= 2:
        safe_title = _sanitize_filename(title)  # 清理标题中的非法字符
        if safe_title:
            return f"{safe_title}{suffix}"  # 使用网页标题作为文件名

    # 回退方案：从 URL 提取域名和路径标识
    from urllib.parse import urlparse
    parsed = urlparse(url)
    # 提取域名最后一段（如 hl718.com → hl718）
    domain_parts = (parsed.netloc or "unknown").split(".")
    domain = domain_parts[-2] if len(domain_parts) >= 2 else domain_parts[0]
    # 提取路径中的数字或最后一段路径名
    path_segments = [s for s in parsed.path.strip("/").split("/") if s]
    if path_segments:
        # 取最后一个有意义的路径段（通常是文章 ID）
        last_seg = path_segments[-1]
        # 去掉常见无意义名称
        if last_seg.lower() in ("index.m3u8", "index", "1", "playlist"):
            # 用倒数第二段或域名
            if len(path_segments) >= 2:
                last_seg = path_segments[-2]
            else:
                last_seg = f"video_{int(time.time())}"
        return f"{domain}_{last_seg}{suffix}"
    # 兜底：时间戳
    return f"{domain}_{int(time.time())}{suffix}"


def _parse_m3u8_duration(m3u8_content: str) -> float:
    """从 m3u8 播放列表内容中解析视频总时长

    通过累加 #EXTINF 标签中的每段时长来计算总时长，
    比 ffprobe 网络探测快 5-15 秒（无需额外网络请求）。

    Args:
        m3u8_content: m3u8 播放列表的文本内容

    Returns:
        总时长（秒）；解析失败返回 0.0
    """
    import re as _re  # 正则表达式
    if not m3u8_content:
        return 0.0
    total = 0.0  # 累计总时长
    for match in _re.finditer(r"#EXTINF:\s*([\d.]+)", m3u8_content):
        try:
            total += float(match.group(1))  # 累加每段时长
        except ValueError:
            continue  # 解析失败跳过该段
    return total if total > 0 else 0.0  # 返回累计时长，无效则返回 0


def _get_video_duration(filepath: str) -> float:
    """使用 ffprobe 获取视频时长（秒）

    Args:
        filepath: 视频文件路径

    Returns:
        时长秒数；获取失败返回 0.0
    """
    try:
        import subprocess  # 子进程调用
        result = subprocess.run(  # 执行 ffprobe 命令
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", filepath],
            capture_output=True, text=True, timeout=15,  # 15 秒超时
        )
        if result.returncode == 0:  # 执行成功
            return float(result.stdout.strip())  # 解析为浮点数
    except (subprocess.TimeoutExpired, ValueError, OSError, FileNotFoundError):
        pass  # 任何异常都返回 0
    return 0.0  # 获取失败


# ——— 启动入口 ———

if __name__ == "__main__":
    import uvicorn  # ASGI 服务器
    uvicorn.run(app, host="0.0.0.0", port=8520, log_level="info")  # 启动服务
    # 监听所有网络接口的 8520 端口
