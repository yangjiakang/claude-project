"""网页视频爬取器 —— 从指定 URL 抓取并下载视频"""
# 启用 future annotations，让 Python 3.9 兼容 `str | None` 类型注解写法
from __future__ import annotations

import json  # JSON 解析，用于处理 DPlayer 等播放器的 data-config 配置
import re  # 正则表达式，用于从 HTML/JS 中提取视频链接
import sys  # 系统相关，用于输出到 stderr
import threading  # 线程锁，用于保护并发下载时的共享状态（seen_urls / 计数器）
from concurrent.futures import ThreadPoolExecutor, as_completed  # 线程池，用于并发下载视频
from dataclasses import dataclass, field  # 数据类，用于配置和数据结构
from pathlib import Path  # 面向对象的文件系统路径处理
from urllib.parse import urljoin, urlparse  # URL 解析和拼接

import requests  # HTTP 请求库，用于下载网页和视频
from requests.adapters import HTTPAdapter  # HTTP 适配器，用于配置连接池大小
from urllib3.util.retry import Retry  # 重试策略，用于配置自动重试机制
import shutil  # 文件操作工具，用于检查 ffmpeg 等命令行工具是否可用
import subprocess  # 子进程管理，用于调用 ffmpeg 命令行工具执行转码
from bs4 import BeautifulSoup  # HTML 解析库，用于提取视频标签

# ——— 常量定义 ———

# 默认的浏览器 User-Agent，模拟 Chrome 浏览器访问，避免被网站拒绝
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "  # 操作系统标识
    "AppleWebKit/537.36 (KHTML, like Gecko) "  # 浏览器引擎标识
    "Chrome/125.0.0.0 Safari/537.36"  # 浏览器版本
)

# 支持的视频 Content-Type 集合，用于识别服务器返回的是否为视频文件
VIDEO_CONTENT_TYPES = {
    "video/mp4",  # MP4 格式，最通用
    "video/webm",  # WebM 格式，网页常用
    "video/ogg",  # Ogg 视频格式
    "video/quicktime",  # QuickTime 格式 (.mov)
    "video/x-msvideo",  # AVI 格式
    "video/x-flv",  # Flash 视频格式
    "video/x-matroska",  # MKV 格式
    "video/mpeg",  # MPEG 格式
    "video/3gpp",  # 3GP 手机视频格式
    "video/x-ms-wmv",  # WMV 格式
    "application/x-mpegURL",  # HLS 流媒体 (.m3u8)
    "application/vnd.apple.mpegurl",  # HLS 流媒体 (Apple 变体)
}

# Content-Type 到文件扩展名的映射表，用于给下载的视频添加正确的后缀
VIDEO_EXTENSION_MAP = {
    "video/mp4": ".mp4",  # MP4 → .mp4
    "video/webm": ".webm",  # WebM → .webm
    "video/ogg": ".ogv",  # Ogg Video → .ogv
    "video/quicktime": ".mov",  # QuickTime → .mov
    "video/x-msvideo": ".avi",  # AVI → .avi
    "video/x-flv": ".flv",  # Flash Video → .flv
    "video/x-matroska": ".mkv",  # Matroska → .mkv
    "video/mpeg": ".mpeg",  # MPEG → .mpeg
    "video/3gpp": ".3gp",  # 3GPP → .3gp
    "video/x-ms-wmv": ".wmv",  # WMV → .wmv
    "application/x-mpegURL": ".m3u8",  # HLS → .m3u8
    "application/vnd.apple.mpegurl": ".m3u8",  # HLS (Apple) → .m3u8
}

# 常见视频网站域名列表，用于识别嵌入式视频来源
VIDEO_HOSTING_DOMAINS = {
    "youtube.com",  # YouTube
    "youtu.be",  # YouTube 短链
    "vimeo.com",  # Vimeo
    "bilibili.com",  # 哔哩哔哩
    "b23.tv",  # B站短链
    "youku.com",  # 优酷
    "iqiyi.com",  # 爱奇艺
    "qq.com",  # 腾讯视频
    "douyin.com",  # 抖音
    "kuaishou.com",  # 快手
    "dailymotion.com",  # Dailymotion
    "twitch.tv",  # Twitch
}

# 需要检测的播放器配置属性列表，用于从 data-* 属性中提取视频 URL
# 每个元组包含 (CSS 选择器, data 属性名, 配置类型标签)
_PLAYER_CONFIG_SELECTORS = [
    (".dplayer", "data-config", "DPlayer"),  # DPlayer 弹幕播放器，国内网站常用
    (".plyr", "data-plyr-config", "Plyr"),  # Plyr 播放器
    (".plyr", "data-config", "Plyr"),  # Plyr 的备选属性名
    ("[data-player]", "data-config", "GenericPlayer"),  # 通用 data-player 标签
    ("[data-video-config]", "data-video-config", "GenericPlayer"),  # 另一种通用配置写法
    (".jwplayer", "data-setup", "JWPlayer"),  # JW Player
    ("video-js", "data-setup", "VideoJS"),  # Video.js 播放器
    (".video-js", "data-setup", "VideoJS"),  # Video.js（类选择器形式）
]

def _is_m3u8_url(url: str) -> bool:
    """判断 URL 是否为 m3u8/HLS 流媒体地址

    处理 URL 可能携带查询参数的情况（如 ?sign=xxx&t=yyy），
    避免 .endswith('.m3u8') 因查询参数导致误判。

    Args:
        url: 待检测的 URL

    Returns:
        是否为 m3u8 地址
    """
    if not url:
        return False
    # 去除查询参数和锚点后再判断扩展名
    path_only = url.split("?")[0].split("#")[0]
    return path_only.endswith(".m3u8")


# HLS/m3u8 URL 匹配正则，用于从 HTML/JS 中检测流媒体地址
_HLS_URL_PATTERN = re.compile(
    r'(?:"|\'|&quot;|&#x27;)'  # 引号开头（支持 HTML 实体编码）
    r'(https?://[^"\'<>\s]+?\.m3u8[^"\'<>\s]*)'  # 以 .m3u8 结尾的完整 URL
    r'(?:"|\'|&quot;|&#x27;)',  # 引号结尾
    re.IGNORECASE,  # 忽略大小写
)

# 加密/不可下载的 blob URL 模式
_BLOB_URL_PATTERN = re.compile(r'(?:blob|blob-encrypted):https?://', re.IGNORECASE)

# ——— 数据模型 ———


@dataclass
class VideoScrapeConfig:
    """视频爬取配置数据类"""
    url: str  # 目标网页的 URL 地址
    output_dir: Path = Path("videos")  # 视频保存目录，默认 ./videos
    max_videos: int = 0  # 最大下载数量，0 表示不限制
    min_size_kb: int = 0  # 最小文件大小（KB），用于过滤太小的无效视频
    extensions: set = field(default_factory=set)  # 允许的文件扩展名集合，空集合表示不过滤
    recursive: bool = False  # 是否递归爬取同域名下的其他页面
    max_depth: int = 1  # 递归爬取的最大页面深度
    timeout: int = 30  # 单个 HTTP 请求的超时时间（秒）
    user_agent: str = DEFAULT_USER_AGENT  # 自定义 User-Agent
    concurrent: int = 1  # 并发下载数，1 为串行；设为 3~5 可大幅提升多视频下载速度
    skip_head: bool = False  # 跳过 HEAD 预检请求，省去一次网络往返，加快下载启动速度
    convert_to: str = ""  # 下载后自动转换的目标格式（如 "mp4"、"webm"），空字符串表示不转换
    convert_preset: str = "medium"  # 编码速度预设：fast(快)/medium(平衡)/slow(高质量)
    convert_remove_original: bool = False  # 转换成功后是否删除原始文件


@dataclass
class VideoInfo:
    """视频信息数据类，存储每个发现视频的元数据"""
    url: str  # 视频的绝对 URL 地址
    title: str = ""  # 视频标题（从 alt、title 等属性提取）
    duration: str = ""  # 视频时长（如果能从页面中提取到）
    source_type: str = "unknown"  # 来源类型：video_tag / source_tag / link / embed / iframe / meta
    is_hls: bool = False  # 是否为 HLS 流媒体（.m3u8）


class VideoScraper:
    """网页视频爬取器

    核心功能：
    1. 解析 HTML 中的 <video> / <source> / <a> 链接 / <iframe> 嵌入
    2. 提取 og:video / twitter:video 等社交分享元数据
    3. 支持通过 JSON-LD 结构化数据发现视频
    4. 检测 DPlayer / Plyr / Video.js / JW Player 等播放器配置中的视频（真实场景常用）
    5. 检测 HLS（.m3u8）流媒体地址，提示用户使用 ffmpeg 下载
    6. 警告加密 blob URL，避免用户浪费时间尝试下载
    7. 流式下载，支持大文件，显示下载进度
    8. 递归模式：从当前页面出发，BFS 收集同域名下的所有页面
    """

    def __init__(self, config: VideoScrapeConfig):
        """初始化爬取器

        Args:
            config: VideoScrapeConfig 实例，包含所有爬取参数
        """
        self.config = config  # 保存用户配置
        self.config.output_dir.mkdir(parents=True, exist_ok=True)  # 确保输出目录存在（递归创建）
        self._seen_urls: set[str] = set()  # 已见过的视频 URL 集合，用于去重
        self._session = requests.Session()  # 创建持久 HTTP 会话，复用连接提升性能
        self._session.headers["User-Agent"] = self.config.user_agent  # 设置浏览器标识
        self._blob_warnings: set[str] = set()  # 记录已警告过的 blob URL 来源域名，避免重复提示
        self._page_title: str = ""  # 网页标题，用于生成有意义的下载文件名

        # ——— 优化连接池配置，提升并发下载性能 ———
        pool_size = max(self.config.concurrent * 2, 10)  # 连接池 = 并发数 × 2，最少 10 个
        adapter = HTTPAdapter(  # 创建自定义 HTTP 适配器
            pool_connections=pool_size,  # 连接池最大数量（跨域名连接数）
            pool_maxsize=pool_size,  # 单个连接池最大连接数（同域名并发数）
            max_retries=Retry(total=2, backoff_factor=0.1),  # 自动重试 2 次，退避因子 0.1s
        )
        self._session.mount("https://", adapter)  # 为 HTTPS 协议挂载适配器
        self._session.mount("http://", adapter)  # 为 HTTP 协议挂载适配器

        # ——— 用于并发下载的线程安全锁 ———
        self._download_lock = threading.Lock()  # 保护 _seen_urls / 计数器等共享状态

    # ——— 公开接口 ———

    def scrape(self) -> dict:
        """主流程：爬取视频，返回统计字典

        执行步骤：
        1. 根据是否递归决定要访问的页面列表
        2. 遍历每个页面，提取所有视频 URL
        3. 去重、过滤、限制数量
        4. 对 HLS 流媒体给出 ffmpeg 下载提示
        5. 逐个下载视频

        Returns:
            dict: 包含 downloaded/skipped/errors/pages_visited/hls_found 的统计信息
        """
        result = {  # 初始化统计字典，记录各阶段的计数
            "downloaded": 0,  # 成功下载的视频数量
            "skipped": 0,  # 跳过的视频数量（扩展名不匹配或已存在）
            "errors": 0,  # 下载失败的视频数量
            "pages_visited": 0,  # 访问过的页面总数
            "hls_found": 0,  # 发现的 HLS 流媒体数量
        }

        # —— 第一步：决定要爬取哪些页面 ——
        if self.config.recursive and self.config.max_depth > 1:
            # 递归模式：BFS 遍历同域名下的页面，收集符合条件的页面列表
            page_urls = self._collect_pages(
                self.config.url, self.config.max_depth  # 起始 URL 和最大深度
            )
        else:
            page_urls = [self.config.url]  # 非递归模式：只处理用户指定的单个页面

        result["pages_visited"] = len(page_urls)  # 记录访问的页面数
        all_video_infos: list[VideoInfo] = []  # 存放所有发现的视频信息

        # —— 第二步：遍历每个页面，提取视频信息 ——
        for page_url in page_urls:
            html = self._fetch_page(page_url)  # 获取页面 HTML 内容
            if html is None:  # 如果获取失败（网络错误等），跳过该页面
                continue
            # 从第一个页面提取网页标题，用于后续文件命名
            if not self._page_title and html:
                self._page_title = self._extract_page_title(html)  # 提取并保存页面标题
            video_infos = self._extract_video_infos(html)  # 从 HTML 中提取所有视频信息
            for info in video_infos:
                resolved_url = self._resolve_url(page_url, info.url)  # 将相对 URL 转为绝对 URL
                if resolved_url and resolved_url not in self._seen_urls:  # 去重：只添加未处理过的 URL
                    self._seen_urls.add(resolved_url)  # 标记为已处理
                    info.url = resolved_url  # 更新为绝对 URL
                    info.source_type = (
                        f"{info.source_type} (from {page_url[:50]})"  # 标记来源页面
                        if page_url != self.config.url
                        else info.source_type
                    )
                    all_video_infos.append(info)  # 加入待下载列表

        total = len(all_video_infos)  # 找到的唯视频总数
        if total == 0:
            print("未找到任何视频。")  # 没找到视频时给用户反馈
            return result

        # —— 第三步：扩展名过滤 ——
        if self.config.extensions:
            filtered = [  # 只保留扩展名匹配的视频
                v for v in all_video_infos
                if self._match_extension(v.url)  # 检查 URL 扩展名是否在允许列表中
            ]
            result["skipped"] += len(all_video_infos) - len(filtered)  # 统计被过滤掉的数量
            all_video_infos = filtered

        # —— 优先级排序：HLS/m3u8 > 真实视频 > GIF预览/其他 ——
        def _video_priority(info: VideoInfo) -> int:
            """计算视频优先级分数（数字越小越优先）"""
            url = info.url
            # 第一优先级：HLS/m3u8 流媒体
            if info.is_hls or _is_m3u8_url(url):
                return 0  # 第一优先
            # 第二优先级：直接视频链接（.mp4/.webm/.mkv 等）
            if any(url.lower().endswith(ext) for ext in (".mp4", ".webm", ".mkv", ".mov", ".flv", ".avi")):
                return 10  # 第二优先
            # 第三优先级：通用视频 URL（通过 Content-Type 判断的）
            if self._looks_like_video_url(url):
                return 20  # 第三优先
            # 最低优先级：其他
            return 30  # 最低优先

        all_video_infos.sort(key=_video_priority)  # 按优先级升序排列，HLS 优先下载

        # —— 第四步：限制下载数量 ——
        if self.config.max_videos > 0:
            all_video_infos = all_video_infos[:self.config.max_videos]  # 截取前 N 个

        total = len(all_video_infos)  # 最终要下载的视频数量
        print(f"找到 {total} 个视频，开始下载...\n")  # 告知用户开始下载

        # —— 第五步：对 HLS 流媒体给出 ffmpeg 下载提示 ——
        hls_infos = [v for v in all_video_infos if v.is_hls or _is_m3u8_url(v.url)]
        # 筛选出所有 HLS/m3u8 视频
        result["hls_found"] = len(hls_infos)  # 记录 HLS 数量到统计结果
        result["m3u8_urls"] = [info.url for info in hls_infos]  # 保存 m3u8 URL 列表，供后端直接使用（省去重新爬页面的时间）
        if hls_infos:
            print("\n" + "=" * 60)  # 分隔线
            print("⚠️  检测到 HLS/m3u8 流媒体视频，浏览器无法直接下载。")  # 提示用户
            print("   推荐使用 ffmpeg 下载：\n")  # 推荐工具
            for hls_info in hls_infos:
                # 逐条输出 ffmpeg 下载命令
                safe_name = self._safe_filename(hls_info.url, 0)  # 生成安全文件名
                ffmpeg_cmd = f'  ffmpeg -i "{hls_info.url}" -c copy "{safe_name}"'  # 构造 ffmpeg 命令
                source_label = f"  # 来源: {hls_info.source_type}"  # 标注来源类型
                if hls_info.title:
                    source_label += f" ({hls_info.title})"  # 附加标题信息
                print(source_label)  # 输出来源说明
                print(ffmpeg_cmd)  # 输出 ffmpeg 命令
                print()  # 空行分隔
            print("=" * 60 + "\n")  # 分隔线

        # —— 第六步：下载视频（并发模式） ——
        concurrent = max(1, min(self.config.concurrent, total))  # 并发数不能超过视频总数
        if concurrent > 1:
            print(f"🚀 启用并发下载（{concurrent} 线程）\n")  # 提示并发模式

        # 使用带序号的列表，保持输出有序
        indexed_infos = list(enumerate(all_video_infos, 1))  # [(1, info1), (2, info2), ...]

        if concurrent <= 1:
            # —— 串行模式（默认，兼容旧行为） ——
            for idx, info in indexed_infos:
                if self.config.max_videos > 0 and result["downloaded"] >= self.config.max_videos:
                    break  # 达到最大下载数，提前终止
                self._download_and_report(info, idx, total, result)  # 串行下载+输出
        else:
            # —— 并发模式：线程池并行下载 ——
            with ThreadPoolExecutor(max_workers=concurrent) as executor:  # 创建线程池
                future_map = {}  # Future → (index, info) 映射表
                for idx, info in indexed_infos:
                    # 提交所有下载任务到线程池
                    future = executor.submit(self._download_one, info.url, idx, total)
                    # submit 返回 Future 对象，代表异步执行的任务
                    future_map[future] = (idx, info)  # 记录 Future 对应的序号和信息

                for future in as_completed(future_map):  # 按完成顺序（非提交顺序）迭代
                    idx, info = future_map[future]  # 反查对应的序号和信息
                    try:
                        result_tuple = future.result()  # 获取下载结果 (success, msg)
                    except Exception as e:
                        result_tuple = (False, f"{info.url}: 线程异常 - {e}")
                        # 线程级别的未预期异常也捕获处理
                    # 检查是否达到最大下载数限制
                    with self._download_lock:
                        if self.config.max_videos > 0 and result["downloaded"] >= self.config.max_videos:
                            for f in future_map:  # 取消所有尚未完成的 Future
                                f.cancel()
                            break
                    # 传入已完成的结果，避免重复下载
                    self._download_and_report(info, idx, total, result, pre_result=result_tuple)

        # —— 第七步：格式转换（可选） ——
        if self.config.convert_to:  # 用户指定了目标格式
            # 收集成功下载的文件路径
            downloaded_files = [  # 列出输出目录中存在的视频文件
                self.config.output_dir / self._safe_filename(info.url, idx)
                for idx, info in indexed_infos
            ]
            # 只保留确实存在的文件
            existing_files = [p for p in downloaded_files if p.exists()]
            if existing_files:
                print(f"\n🔄 转换为 {self.config.convert_to} 格式...")  # 提示开始转换
                converted = self.convert_downloaded(  # 调用批量转换
                    existing_files,
                    self.config.convert_to,  # 目标格式
                    preset=self.config.convert_preset,  # 编码预设
                )
                result["converted"] = len(converted)  # 记录转换成功数

        return result  # 返回最终统计结果

    def _download_and_report(
        self, info: VideoInfo, idx: int, total: int, result: dict,
        pre_result: tuple[bool, str] | None = None
    ) -> None:
        """线程安全的下载结果记录与输出

        串行模式下：内部调用 _download_one 执行下载。
        并发模式下：调用方已通过 Future 完成下载，传入 pre_result 避免重复下载。

        Args:
            info: 视频信息对象
            idx: 序号
            total: 总数
            result: 结果字典（会原位修改 downloaded/skipped/errors）
            pre_result: 并发模式下预先完成的 (success, msg) 结果
        """
        if pre_result is not None:
            success, msg = pre_result  # 并发模式：使用已完成的下载结果
        else:
            success, msg = self._download_one(info.url, idx, total)  # 串行模式：在此处执行下载
        with self._download_lock:  # 加锁保护共享计数器
            if success:
                result["downloaded"] += 1  # 成功计数 +1
                print(f"  [{idx}/{total}] ✅ {msg}")  # 成功消息
            elif "跳过" in msg or "太小" in msg:
                result["skipped"] += 1  # 跳过计数 +1
                print(f"  [{idx}/{total}] ⏭️  {msg}")  # 跳过消息
            else:
                result["errors"] += 1  # 失败计数 +1
                print(f"  [{idx}/{total}] ❌ {msg}", file=sys.stderr)  # 输出到 stderr

    # ——— 页面获取 ———

    def _fetch_page(self, url: str) -> str | None:
        """GET 请求获取页面 HTML 内容

        Args:
            url: 要获取的页面 URL

        Returns:
            页面的 HTML 文本字符串；网络错误时返回 None
        """
        try:
            resp = self._session.get(url, timeout=self.config.timeout)  # 发起 GET 请求
            resp.raise_for_status()  # 如果 HTTP 状态码不是 2xx，抛出异常
            resp.encoding = resp.apparent_encoding or "utf-8"  # 自动检测编码，fallback 到 UTF-8
            return resp.text  # 返回解码后的 HTML 文本
        except requests.RequestException as e:
            print(f"  ⚠️  无法访问页面 {url}: {e}", file=sys.stderr)  # 输出警告信息
            return None  # 返回空值表示失败

    # ——— 视频 URL 提取 ———

    def _extract_video_infos(self, html: str) -> list[VideoInfo]:
        """从 HTML 中提取所有视频信息

        检测策略（按优先级排列）：
        1. <video> 标签及其 <source> 子标签（最标准的 HTML5 视频）
        2. <a> 链接指向视频文件（直接下载链接）
        3. <iframe> 嵌入（第三方视频平台内嵌）
        4. <meta> og:video / twitter:video（社交分享元数据）
        5. JSON-LD 结构化数据中的 video 字段
        6. 页面 JS 变量中的数据（如 window.__INITIAL_STATE__）
        7. DPlayer / Plyr / Video.js / JW Player 播放器配置的 data-* 属性
        8. HLS/m3u8 流媒体检测（页面任意位置的 .m3u8 URL）
        9. 加密 blob URL 检测并警告用户

        Args:
            html: 页面的 HTML 文本

        Returns:
            VideoInfo 对象列表
        """
        soup = BeautifulSoup(html, "html.parser")  # 用 BeautifulSoup 解析 HTML
        infos: list[VideoInfo] = []  # 存储所有提取到的视频信息

        # ——— 策略 1：<video> 标签 ———
        for video_tag in soup.find_all("video"):  # 查找页面中所有的 <video> 元素
            # 1a: <video src="..."> 直接属性
            src = (video_tag.get("src") or "").strip()  # 获取 video 标签上的 src 属性
            if src:
                if src.startswith("blob:"):
                    # blob: 开头的是浏览器内存中的临时对象，无法直接下载，需警告用户
                    self._warn_blob_url(src, "video_tag")
                elif not src.startswith("data:"):
                    # data: 开头是 Base64 内嵌数据，也不可下载；其余正常处理
                    title = self._extract_video_title(video_tag)  # 尝试提取视频标题
                    infos.append(VideoInfo(url=src, title=title, source_type="video_tag",
                                          is_hls=src.endswith(".m3u8")))

            # 1b: <video> 内的 <source> 子标签
            for source_tag in video_tag.find_all("source"):  # 查找 <video> 内的每个 <source>
                src = (source_tag.get("src") or "").strip()  # 获取 source 的 src 属性
                if src:
                    if src.startswith("blob:"):
                        self._warn_blob_url(src, "source_tag")  # blob URL 警告
                    elif not src.startswith("data:"):
                        title = self._extract_video_title(video_tag)  # 使用父级 <video> 的标题
                        infos.append(VideoInfo(url=src, title=title, source_type="source_tag",
                                              is_hls=src.endswith(".m3u8")))

            # 1c: <video> 的 data-* 懒加载属性（包括 data-mp4 / data-webm）
            for attr in ("data-src", "data-video-url", "data-url", "data-mp4", "data-webm"):
                val = (video_tag.get(attr) or "").strip()  # 获取属性值
                if val:
                    # 跳过 GIF 预览链接（如 pornhub /pics/gifs/*.mp4，只是缩略图动图）
                    if "/pics/gifs/" in val:
                        continue  # 这些是预览片段，不是真实视频
                    if val.startswith("blob:"):
                        self._warn_blob_url(val, f"video_{attr}")  # blob URL 警告
                    elif not val.startswith("data:"):
                        # 跳过被标记为 gifVideo 的预览元素
                        video_classes = " ".join(video_tag.get("class", []) if isinstance(video_tag.get("class"), list) else [video_tag.get("class", "")]).lower()
                        if "gifvideo" in video_classes:
                            continue  # 这些是 GIF 预览，不是真实视频
                        title = self._extract_video_title(video_tag)
                        infos.append(VideoInfo(url=val, title=title, source_type=f"video_{attr}",
                                              is_hls=val.endswith(".m3u8")))

        # ——— 策略 2：<a> 链接指向视频文件 ———
        for a_tag in soup.find_all("a", href=True):  # 遍历所有带 href 属性的 <a> 标签
            href = a_tag["href"].strip()  # 获取链接地址
            if self._looks_like_video_url(href):  # 判断 URL 是否像视频文件
                title = (a_tag.get("title") or a_tag.get_text(strip=True) or "")[:100]
                # 取 title 属性或链接文本作为标题，截断到 100 字符
                infos.append(VideoInfo(url=href, title=title, source_type="a_link",
                                      is_hls=href.endswith(".m3u8")))

        # ——— 策略 3：<iframe> 嵌入 ———
        for iframe_tag in soup.find_all("iframe"):  # 遍历所有 <iframe> 标签
            src = (iframe_tag.get("src") or "").strip()  # 获取 iframe 的 src
            if src:
                # 检测 iframe 源是否为知名视频平台
                hostname = urlparse(src).hostname or ""  # 提取主机名
                if any(domain in hostname for domain in VIDEO_HOSTING_DOMAINS):
                    # 如果属于已知视频平台域名
                    title = (iframe_tag.get("title") or hostname)[:100]
                    # 标记为 embed 类型，用户可自行处理第三方平台视频
                    infos.append(VideoInfo(url=src, title=title, source_type=f"embed:{hostname}",
                                          is_hls=src.endswith(".m3u8")))
                elif self._looks_like_video_url(src):  # 或者直接是视频文件链接
                    title = (iframe_tag.get("title") or "")[:100]
                    infos.append(VideoInfo(url=src, title=title, source_type="iframe",
                                          is_hls=src.endswith(".m3u8")))

        # ——— 策略 4：<meta> 社交分享标签 ———
        for meta_tag in soup.find_all("meta"):  # 遍历所有 <meta> 标签
            prop = meta_tag.get("property", "").lower()  # Open Graph 属性
            name = meta_tag.get("name", "").lower()  # Twitter Card 属性
            content = (meta_tag.get("content") or "").strip()  # 元数据内容值
            if content and (  # 条件：有内容 且
                "og:video" in prop  # 是 Open Graph 视频
                or "og:video:url" in prop  # 是 Open Graph 视频 URL
                or "twitter:player" in name  # 是 Twitter 播放器
                or "twitter:player:stream" in name  # 是 Twitter 视频流
            ):
                title = self._extract_meta_title(soup)  # 尝试从页面标题获取视频名称
                infos.append(VideoInfo(url=content, title=title, source_type="meta",
                                      is_hls=content.endswith(".m3u8")))

        # ——— 策略 5：JSON-LD 结构化数据 ———
        for script_tag in soup.find_all("script", type="application/ld+json"):
            # 查找 schema.org 结构化数据
            try:
                data = json.loads(script_tag.string or "{}")  # 解析 JSON
                if isinstance(data, dict):
                    if "video" in data and isinstance(data["video"], dict):
                        # schema.org VideoObject 内嵌
                        video_data = data["video"]
                        content_url = video_data.get("contentUrl", "")  # 获取视频内容 URL
                        if content_url:
                            infos.append(VideoInfo(
                                url=content_url,
                                title=video_data.get("name", "")[:100],
                                duration=video_data.get("duration", ""),  # 时长
                                source_type="jsonld",
                                is_hls=content_url.endswith(".m3u8"),
                            ))
                    elif data.get("@type") == "VideoObject":  # JSON-LD 自身就是 VideoObject
                        content_url = data.get("contentUrl", "")
                        if content_url:
                            infos.append(VideoInfo(
                                url=content_url,
                                title=data.get("name", "")[:100],
                                duration=data.get("duration", ""),
                                source_type="jsonld",
                                is_hls=content_url.endswith(".m3u8"),
                            ))
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass  # JSON 解析失败则跳过，不影响其他策略

        # ——— 策略 6：页面内嵌 JS 变量 ———
        js_patterns = [  # 常见的 JS 全局变量中携带视频 URL 的模式
            r'"(?:videoUrl|videoSrc|mp4Url|video_url|video_src)\s*"\s*:\s*"(https?://[^"]+)"',
            r"'(?:videoUrl|videoSrc|mp4Url|video_url|video_src)\s*'\s*:\s*'(https?://[^']+)'",
            r'"(?:contentUrl|content_url)\s*"\s*:\s*"(https?://[^"]+(?:\.mp4|\.webm)[^"]*)"',
            r'"play_url"\s*:\s*"(https?://[^"]+)"',  # 抖音等平台的 play_url
            r'"(?:url|src|video)"\s*:\s*"(https?://[^"]+?\.m3u8[^"]*)"',  # 内嵌的 m3u8 URL
            # Pornhub mediaDefinitions 格式（JSON 中反斜杠转义的 URL：https:\/\/...）
            r'"videoUrl"\s*:\s*"(https?:\\?/\\?/[^"]+\.m3u8[^"]*)"',
        ]
        for pattern in js_patterns:  # 遍历每个正则表达式模式
            matches = re.findall(pattern, html, re.IGNORECASE)  # 在 HTML 中搜索匹配项
            for match in matches:
                url = match if isinstance(match, str) else match[0]  # 提取 URL 部分
                # 修复 JSON 转义的斜杠（Pornhub 等网站的 mediaDefinitions 格式）
                url = url.replace(r"\/", "/")  # 将 \/ 还原为 /
                if url.startswith("blob:"):
                    self._warn_blob_url(url, "js_variable")  # blob URL 警告
                    continue
                if self._looks_like_video_url(url) or ".mp4" in url or ".m3u8" in url:
                    # 判断是否为视频 URL（处理查询参数导致 .endswith('.m3u8') 失败的情况）
                    infos.append(VideoInfo(url=url, title="", source_type="js_variable",
                                          is_hls=_is_m3u8_url(url)))

        # ——— 策略 7：播放器 data-* 配置检测（DPlayer / Plyr / Video.js / JW Player） ———
        player_infos = self._extract_player_configs(soup, html)
        # 调用播放器配置提取方法，从 data-config 等属性中解析视频 URL
        for p_info in player_infos:
            url = p_info.url  # 提取到的视频 URL
            if url.startswith("blob:"):
                self._warn_blob_url(url, p_info.source_type)  # blob URL 警告
                continue
            if url and url not in self._seen_urls:
                infos.append(p_info)  # 添加到结果列表

        # ——— 策略 8：HLS/m3u8 流媒体深度检测 ———
        hls_infos = self._detect_hls_streams(html, soup)
        # 调用 HLS 专项检测方法，发现页面中所有 .m3u8 URL
        for hls_info in hls_infos:
            if hls_info.url not in self._seen_urls:
                infos.append(hls_info)  # 添加到结果列表（去重）

        # ——— 策略 9：全局 blob URL 警告（在原始 HTML 文本中搜索） ———
        blob_matches = _BLOB_URL_PATTERN.findall(html)
        # 在整个 HTML 中搜索 blob 或 blob-encrypted URL
        for blob_match in blob_matches:
            self._warn_blob_url(blob_match, "inline_script")
            # 对每个匹配到的 blob URL 发出警告

        return infos  # 返回所有提取到的视频信息

    def _extract_player_configs(self, soup: BeautifulSoup, html: str = "") -> list[VideoInfo]:
        """从播放器 data-* 配置属性中提取视频 URL

        支持检测以下播放器类型：
        - DPlayer：国内网站常用，配置在 .dplayer 的 data-config 属性中，
          格式为 JSON，视频 URL 通常在 video.url 或 video.url2 字段
        - Plyr：通过 .plyr 的 data-plyr-config 或 data-config 属性
        - Video.js：通过 video-js / .video-js 的 data-setup 属性
        - JW Player：通过 .jwplayer 的 data-setup 属性
        - 通用播放器：通过 [data-player] / [data-video-config] 的 data-config 属性

        真实案例：
        —— 某中文视频站返回的 DPlayer 配置 ——
        <div class="dplayer" data-config='{"video":{"url":"https://...mp4","url2":"https://...m3u8"}}'></div>

        Args:
            soup: BeautifulSoup 解析后的 HTML 对象
            html: 原始 HTML 文本（用于正则回退搜索）

        Returns:
            VideoInfo 对象列表
        """
        infos: list[VideoInfo] = []  # 存储从播放器配置中提取到的视频信息

        for selector, attr, player_name in _PLAYER_CONFIG_SELECTORS:
            # 遍历每种播放器选择器配置
            elements = soup.select(selector)  # 使用 CSS 选择器查找元素
            for element in elements:
                config_raw = (element.get(attr) or "").strip()  # 获取 data-* 属性值
                if not config_raw:
                    continue  # 属性值为空则跳过

                # 尝试解析 JSON 配置
                try:
                    config = json.loads(config_raw)  # 将 JSON 字符串解析为字典
                except json.JSONDecodeError:
                    # JSON 解析失败，跳过该元素
                    continue

                if not isinstance(config, dict):
                    continue  # 不是字典类型则跳过

                # —— DPlayer 配置解析 ——
                # 标准 DPlayer config 结构：{"video":{"url":"...","url2":"...","pic":"..."}}
                if player_name == "DPlayer" or "video" in config:
                    video_block = config.get("video", config)
                    # 尝试取得 video 子对象，如果没有则用 config 本身
                    if isinstance(video_block, dict):
                        # 主视频 URL（url 字段）
                        main_url = (video_block.get("url") or "").strip()
                        if main_url and not main_url.startswith("data:"):
                            infos.append(VideoInfo(
                                url=main_url,
                                title=f"DPlayer 主源",
                                source_type=f"dplayer_config",
                                is_hls=main_url.endswith(".m3u8"),
                            ))
                        # 备用视频 URL（url2 字段，常见于 .m3u8 备用源）
                        alt_url = (video_block.get("url2") or "").strip()
                        if alt_url and not alt_url.startswith("data:") and alt_url != main_url:
                            infos.append(VideoInfo(
                                url=alt_url,
                                title=f"DPlayer 备用源",
                                source_type=f"dplayer_config",
                                is_hls=alt_url.endswith(".m3u8"),
                            ))

                # —— Plyr 配置解析 ——
                # Plyr config 结构：{"sources":[{"src":"...","type":"video/mp4"}]}
                if "sources" in config and isinstance(config["sources"], list):
                    for src_obj in config["sources"]:
                        if isinstance(src_obj, dict):
                            src_url = (src_obj.get("src") or "").strip()
                            if src_url and not src_url.startswith("data:"):
                                src_type = src_obj.get("type", "")
                                infos.append(VideoInfo(
                                    url=src_url,
                                    title=f"" if player_name == "DPlayer" else f"{player_name} 源",
                                    source_type=f"{player_name.lower()}_config",
                                    is_hls=src_url.endswith(".m3u8") or "mpegurl" in src_type,
                                ))

                # —— Video.js / JW Player 配置解析 ——
                # Video.js 可能在 data-setup 中包含 sources
                # JW Player 使用 "file" 字段指定视频 URL
                if isinstance(config, dict):
                    # 直接查找 file / src / sources 等常见键
                    for key in ("file", "src", "videoUrl", "video_url"):
                        val = (config.get(key) or "").strip()
                        if val and not val.startswith("data:") and not val.startswith("blob:"):
                            if self._looks_like_video_url(val) or any(
                                val.endswith(ext) for ext in (".mp4", ".webm", ".m3u8", ".mov", ".flv", ".mkv")
                            ):
                                infos.append(VideoInfo(
                                    url=val,
                                    title=f"{player_name} 视频",
                                    source_type=f"{player_name.lower()}_config",
                                    is_hls=val.endswith(".m3u8"),
                                ))
                    # 递归查找嵌套对象中的视频 URL
                    for deep_key, deep_val in config.items():
                        if isinstance(deep_val, dict):
                            for sub_key in ("url", "src", "file", "videoUrl"):
                                sub_val = (deep_val.get(sub_key) or "").strip()
                                if sub_val and not sub_val.startswith("data:") and not sub_val.startswith("blob:"):
                                    if self._looks_like_video_url(sub_val) or any(
                                        sub_val.endswith(ext) for ext in (".mp4", ".webm", ".m3u8", ".mov", ".flv", ".mkv")
                                    ):
                                        infos.append(VideoInfo(
                                            url=sub_val,
                                            title=f"{player_name} {deep_key}.{sub_key}",
                                            source_type=f"{player_name.lower()}_config",
                                            is_hls=sub_val.endswith(".m3u8"),
                                        ))

        # —— 正则回退：在原始 HTML 中搜索 data-config JSON 中的视频 URL ——
        # 有些网站的 data-config 可能被 HTML 实体编码或嵌套在复杂标签中
        # 使用正则表达式直接匹配 data-config 属性值中的视频 URL
        config_url_pattern = re.compile(
            r'(?:url|url2|src|file)\s*["\']\s*:\s*["\']\s*'  # JSON 键值对模式
            r'(https?://[^"\'<>]+?(?:\.mp4|\.webm|\.m3u8|\.mov|\.mkv|\.flv|\.avi|\.ts|\.m4v)'  # 视频文件扩展名
            r'[^"\'<>]*)',  # URL 剩余部分
            re.IGNORECASE,
        )
        for match in config_url_pattern.finditer(html):
            url = match.group(1)  # 提取匹配到的 URL
            if url and url not in self._seen_urls:
                infos.append(VideoInfo(
                    url=url,
                    title="",
                    source_type="player_config_regex",  # 来源：正则回退匹配
                    is_hls=url.endswith(".m3u8"),
                ))

        return infos  # 返回从播放器配置中提取的所有视频信息

    def _detect_hls_streams(self, html: str, soup: BeautifulSoup | None = None) -> list[VideoInfo]:
        """专项检测页面中的 HLS（.m3u8）流媒体地址

        扫描以下位置：
        1. 所有 HTML 标签的 data-* 属性值中的 .m3u8 URL
        2. <script> 标签内嵌 JavaScript 中的 .m3u8 URL
        3. 页面纯文本（内联脚本）中的 .m3u8 URL
        4. 使用自定义正则从原始 HTML 中匹配 .m3u8 URL

        真实案例：
        —— 某直播站点的 m3u8 地址隐藏在 data-video 属性中 ——
        <div data-video="https://example.com/live/stream.m3u8?token=abc"></div>

        —— 某视频站的内联脚本 ——
        <script>var player = {url: 'https://cdn.example.com/video/index.m3u8'};</script>

        Args:
            html: 原始 HTML 文本
            soup: BeautifulSoup 对象（可选，用于标签属性扫描）

        Returns:
            VideoInfo 对象列表，每个包含 .m3u8 URL
        """
        infos: list[VideoInfo] = []  # 存储检测到的 HLS 流媒体信息
        seen_m3u8: set[str] = set()  # 本次检测的去重集合

        def _add_m3u8(url: str, source: str, title: str = ""):
            """内部辅助函数：添加 m3u8 URL 到结果列表（去重）

            Args:
                url: m3u8 URL
                source: 来源类型标签
                title: 视频标题
            """
            nonlocal infos, seen_m3u8  # 引用外部变量
            cleaned = url.strip()  # 去除首尾空白
            if not cleaned or not cleaned.endswith(".m3u8"):
                return  # 不是 .m3u8 URL 则忽略
            if cleaned in seen_m3u8:
                return  # 已检测过，跳过
            # 简单校验 URL 格式
            if not cleaned.startswith("http") and not cleaned.startswith("//"):
                return  # 不是有效 URL
            seen_m3u8.add(cleaned)  # 标记为已处理
            infos.append(VideoInfo(url=cleaned, title=title[:100] if title else "",
                                   source_type=source, is_hls=True))

        # —— 方法 1：从原始 HTML 中使用 HLS 正则匹配 ——
        for match in _HLS_URL_PATTERN.finditer(html):
            url = match.group(1)  # 提取捕获组中的 URL
            _add_m3u8(url, "hls_regex")  # 添加到结果

        # —— 方法 2：扫描所有标签的 data-* 属性中的 m3u8 ——
        if soup is not None:
            for tag in soup.find_all(True):  # True 表示匹配所有标签
                for attr_name, attr_value in tag.attrs.items():
                    # 遍历标签的所有属性
                    if not isinstance(attr_value, str):
                        continue  # 跳过非字符串属性（如 class list）
                    if ".m3u8" not in attr_value:
                        continue  # 属性值不含 .m3u8，快速跳过
                    # 在属性值中用简单正则提取 .m3u8 URL
                    attr_urls = re.findall(
                        r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)',
                        attr_value,
                        re.IGNORECASE,
                    )
                    for url in attr_urls:
                        _add_m3u8(url, f"hls_data_attr:{attr_name}")  # 标注来源属性名

        # —— 方法 3：扫描 <script> 标签中的 m3u8 ——
        if soup is not None:
            for script_tag in soup.find_all("script"):
                script_text = script_tag.string or ""  # 获取脚本内容
                if ".m3u8" not in script_text:
                    continue  # 快速跳过不含 m3u8 的脚本
                script_urls = re.findall(
                    r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)',
                    script_text,
                    re.IGNORECASE,
                )
                for url in script_urls:
                    _add_m3u8(url, "hls_script")  # 来源：script 标签

        # —— 方法 4：从原始 HTML 中用更宽泛的正则搜索 m3u8 ——
        # 有些 m3u8 URL 可能没有用引号包裹（如直接写在内联 JS 中）
        broad_matches = re.findall(
            r'(?:https?://[^\s"\'<>\[\]{}()]+?\.m3u8[^\s"\'<>\[\]{}()]*)',
            html,
            re.IGNORECASE,
        )
        for url in broad_matches:
            # 清理 URL 末尾可能附带的非 URL 字符
            cleaned_url = re.sub(r'[,;)}\]]+$', '', url)
            # 去除末尾可能被错误匹配的标点符号
            _add_m3u8(cleaned_url, "hls_broad")  # 来源：宽泛扫描

        return infos  # 返回所有检测到的 HLS 流媒体信息

    def _warn_blob_url(self, url: str, source_type: str = "") -> None:
        """检测到加密 blob URL 时输出警告信息

        blob: URL 是浏览器内存中的临时对象，无法通过 HTTP 直接下载。
        blob-encrypted: 前缀表示加密的媒体流（如 Netflix、Amazon Prime 等 DRM 保护内容），
        这些内容几乎不可能通过常规手段下载。

        Args:
            url: 检测到的 blob URL（用于提取域名信息）
            source_type: 发现该 blob URL 的来源类型标签
        """
        # 提取域名用于去重警告（同一域名只警告一次）
        domain = "未知域名"  # 默认域名标签
        try:
            parsed = urlparse(url)  # 尝试解析 URL
            domain = parsed.netloc or domain  # 获取主机名部分
        except Exception:
            pass  # 解析失败则使用默认值

        # 生成去重键：域名 + 来源类型
        warning_key = f"{domain}:{source_type}"
        if warning_key in self._blob_warnings:
            return  # 已经对该域名+来源发出过警告，跳过重复提示

        self._blob_warnings.add(warning_key)  # 记录已警告，避免重复

        # 判断是否为加密 blob（DRM 保护内容）
        is_encrypted = "blob-encrypted" in url.lower() or "encrypted" in url.lower()
        if is_encrypted:
            print(
                f"  🔒 检测到加密 blob URL（DRM 保护）：{url[:80]}...",
                file=sys.stderr,
            )
            print(
                f"      来源：{source_type} | 该内容受 DRM 保护，无法通过常规手段下载。",
                file=sys.stderr,
            )
        else:
            print(
                f"  ⚠️  检测到 blob URL（浏览器临时对象）：{url[:60]}...",
                file=sys.stderr,
            )
            print(
                f"      来源：{source_type} | blob: URL 无法直接下载，"
                f"需要通过浏览器开发者工具获取实际媒体地址。",
                file=sys.stderr,
            )

    def _extract_video_title(self, tag) -> str:
        """从视频标签及其父级结构中提取标题文本

        Args:
            tag: BeautifulSoup Tag 对象

        Returns:
            提取到的标题字符串，截断到 100 字符
        """
        # 优先级：aria-label > title 属性 > 内部文本 > 附近标题标签
        aria = (tag.get("aria-label") or "").strip()  # 无障碍标签
        if aria:
            return aria[:100]
        title_attr = (tag.get("title") or "").strip()  # HTML title 属性
        if title_attr:
            return title_attr[:100]
        # 查找父级中的 <h1>~<h5> 标题标签作为视频名称
        parent = tag.parent  # 获取父级元素
        for _ in range(5):  # 向上查找最多 5 层
            if parent is None:
                break  # 到达顶层，退出循环
            h_tag = parent.find(["h1", "h2", "h3", "h4", "h5"])  # 在当前层级找标题标签
            if h_tag:
                text = h_tag.get_text(strip=True)  # 获取纯文本
                if text:
                    return text[:100]
            parent = parent.parent  # 继续向上查找
        return ""  # 没有找到任何标题

    def _extract_meta_title(self, soup: BeautifulSoup) -> str:
        """从页面的 <title> 或 og:title 中提取页面标题

        Args:
            soup: BeautifulSoup 对象

        Returns:
            页面标题字符串
        """
        og_title = soup.find("meta", property="og:title")  # 查找 Open Graph 标题
        if og_title and og_title.get("content"):
            return og_title["content"].strip()[:100]  # 取 OG 标题
        title_tag = soup.find("title")  # 查找 <title> 标签
        if title_tag and title_tag.string:
            return title_tag.string.strip()[:100]  # 取页面标题
        return ""  # 没有找到任何标题

    def _looks_like_video_url(self, url: str) -> bool:
        """判断 URL 是否像视频文件（根据扩展名）

        Args:
            url: 要检查的 URL

        Returns:
            True 表示像视频链接
        """
        path = urlparse(url).path.lower()  # 提取 URL 路径部分并转小写
        video_extensions = (  # 常见视频文件扩展名元组
            ".mp4", ".webm", ".ogv", ".mov", ".avi",
            ".flv", ".mkv", ".mpeg", ".mpg", ".wmv",
            ".3gp", ".m4v", ".ts", ".m3u8",
        )
        return path.endswith(video_extensions)  # 检查路径是否以视频扩展名结尾

    # ——— URL 处理 ———

    def _resolve_url(self, base_url: str, raw_url: str) -> str | None:
        """将相对 URL 解析为绝对 URL

        Args:
            base_url: 页面基础 URL
            raw_url: 可能为相对路径的原始 URL

        Returns:
            绝对 URL 字符串；无效则返回 None
        """
        try:
            resolved = urljoin(base_url, raw_url)  # urllib 的 URL 拼接，自动处理相对路径
            parsed = urlparse(resolved)  # 解析拼接后的 URL
            if not parsed.scheme or not parsed.netloc:
                return None  # 缺少协议或主机名，无效 URL
            return resolved
        except ValueError:
            return None  # 完全无效的 URL

    def _match_extension(self, url: str) -> bool:
        """检查 URL 的扩展名是否在用户指定的允许列表中

        Args:
            url: 视频 URL

        Returns:
            True 表示匹配（或未设置过滤）
        """
        if not self.config.extensions:
            return True  # 未设置扩展名过滤，全部通过
        path = urlparse(url).path.lower()  # 提取路径并转小写
        if not path:
            return True  # 无法判断扩展名时不排除
        return any(path.endswith(ext.lower()) for ext in self.config.extensions)
        # 检查路径是否以任意一个允许的扩展名结尾

    # ——— 视频下载 ———

    def _download_one(self, url: str, index: int, total: int) -> tuple[bool, str]:
        """下载单个视频文件

        使用流式下载（stream=True），分块写入磁盘，避免大视频撑爆内存。
        同时显示实时下载进度条。

        Args:
            url: 视频的绝对 URL
            index: 当前序号（1-based）
            total: 总数

        Returns:
            (成功标志, 消息描述)
        """
        try:
            content_type = ""  # Content-Type 初始为空
            content_length = 0  # 文件大小初始为 0

            # 发起 HEAD 请求先探测文件大小和类型（如果不跳过）
            if not self.config.skip_head:
                head_resp = self._session.head(url, timeout=self.config.timeout)
                content_type = head_resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                # 获取 Content-Type 并去除 charset 等参数
                content_length = int(head_resp.headers.get("Content-Length", 0))
                # 获取文件总大小

                # 检查最小文件大小过滤（仅在 HEAD 请求成功时生效）
                if self.config.min_size_kb > 0 and content_length > 0:
                    if content_length < self.config.min_size_kb * 1024:
                        # 文件小于最小阈值
                        return False, f"跳过（文件太小: {content_length / 1024:.0f} KB）"

            # 构建文件名
            filename = self._safe_filename(url, index, content_type)
            filepath = self.config.output_dir / filename  # 拼接完整输出路径
            filepath = self._ensure_unique(filepath)  # 避免覆盖已存在的文件

            # 流式下载视频（skip_head 模式下直接 GET，省去 HEAD 往返时间）
            resp = self._session.get(url, timeout=self.config.timeout, stream=True)
            # stream=True 启用流式传输，避免一次性加载到内存
            resp.raise_for_status()  # 检查 HTTP 状态码

            total_size = int(resp.headers.get("Content-Length", 0))  # 获取文件总大小
            downloaded_size = 0  # 已下载字节数
            last_progress = -1  # 上次打印进度的百分比，用于减少输出频率

            with open(filepath, "wb") as f:  # 以二进制写入模式打开文件
                for chunk in resp.iter_content(chunk_size=1024 * 1024):  # 每次读 1MB，减少 I/O 次数
                    if chunk:
                        f.write(chunk)  # 写入当前数据块
                        downloaded_size += len(chunk)  # 累加已下载字节数

                        # 每增加 10% 显示一次进度
                        if total_size > 0:
                            progress = int(downloaded_size / total_size * 100)  # 计算当前百分比
                            if progress >= last_progress + 10:  # 每 10% 输出一次
                                last_progress = progress  # 更新上次进度标记
                                size_mb = downloaded_size / (1024 * 1024)  # 已下载 MB
                                total_mb = total_size / (1024 * 1024)  # 总大小 MB
                                print(
                                    f"  [{index}/{total}] ⬇ {progress}% "
                                    f"({size_mb:.1f}/{total_mb:.1f} MB)",
                                    end="\r",  # \r 回到行首，实现原地刷新进度
                                    flush=True,  # 立即输出，不缓冲
                                )

            final_size = filepath.stat().st_size  # 获取最终文件大小
            size_mb = final_size / (1024 * 1024)  # 转换为 MB
            return True, f"{filepath.name} ({size_mb:.1f} MB)"

        except requests.RequestException as e:
            return False, f"{url}: 网络错误 - {e}"
        except OSError as e:
            return False, f"{url}: 写入失败 - {e}"

    def _extract_page_title(self, html: str) -> str:
        """从 HTML 中提取网页标题（<title> 标签内容）

        用于生成有意义的下载文件名。提取到的标题会经过清理：
        - 去掉网站名后缀（如 " - hl718"）
        - 截断到合理长度

        Args:
            html: 网页 HTML 源代码

        Returns:
            清理后的网页标题；提取失败返回空字符串
        """
        import html as _html  # HTML 实体解码
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        title = match.group(1).strip()  # 提取标题文本并去除首尾空白
        title = _html.unescape(title)  # 解码 HTML 实体（如 &amp; → &）
        # 去掉常见网站名后缀：分隔符 + 网站名
        title = re.sub(r"\s*[-–—|_]\s*[^-–—|_\s]+$", "", title).strip()
        # 合并多余空白
        title = re.sub(r"\s+", " ", title)
        # 截断到 80 字符
        if len(title) > 80:
            title = title[:80]
        return title

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """清理文件名，移除非法字符

        处理 Windows / macOS / Linux 文件系统不允许的字符。

        Args:
            name: 原始文件名（不含扩展名）

        Returns:
            清理后的安全文件名
        """
        # 替换 Windows/macOS 非法字符为下划线
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        # 替换换行、制表等控制字符
        name = re.sub(r'[\x00-\x1f]', "", name)
        # 去除首尾空格和点号
        name = name.strip(" .")
        if not name:
            name = "video"
        return name

    def _safe_filename(self, url: str, index: int, content_type: str = "") -> str:
        """从 URL 生成安全的文件名（去除非法字符）

        优先使用网页标题命名（对通用文件名如 index.m3u8），
        回退到 URL 中的原始文件名。

        Args:
            url: 视频 URL
            index: 序号（用于生成兜底文件名）
            content_type: HTTP Content-Type 头（用于推断扩展名）

        Returns:
            安全的文件名字符串
        """
        parsed = urlparse(url)  # 解析 URL
        path = parsed.path or ""  # 取出路径部分
        filename = Path(path).name  # 提取路径中的文件名（去除目录）

        if not filename or filename in ("/", ""):  # 如果没有文件名
            filename = f"video_{index}"  # 使用带序号兜底名

        name, ext = Path(filename).stem, Path(filename).suffix  # 分离文件名和扩展名
        name = re.sub(r'[<>:"/\\|?*]', "_", name)  # 将 Windows/macOS 非法字符替换为下划线
        if not name:
            name = f"video_{index}"  # 如果替换后文件名为空，使用兜底名

        # 如果 URL 文件名是通用名（如 index、1、playlist）且有网页标题，优先使用标题命名
        generic_names = {"index", "1", "2", "playlist", "video", "output", "master", "stream"}
        if name.lower() in generic_names and self._page_title:
            safe_title = self._sanitize_filename(self._page_title)  # 清理标题中的非法字符
            if safe_title:
                name = safe_title  # 使用网页标题替代通用文件名

        if not ext or len(ext) > 6:  # 如果扩展名不存在或过长（不合法）
            ext = VIDEO_EXTENSION_MAP.get(content_type, ".mp4")  # 根据 Content-Type 推断扩展名

        # 如果 URL 中包含查询参数（如 ?token=xxx），去除参数部分
        if "?" in name:
            name = name.split("?")[0]  # 截取问号前的部分

        return f"{name}{ext}"  # 返回拼接后的完整文件名

    def _ensure_unique(self, filepath: Path) -> Path:
        """如果目标路径已存在，在文件名后追加序号避免覆盖

        Args:
            filepath: 目标文件路径

        Returns:
            不重复的文件路径
        """
        if not filepath.exists():  # 文件不存在，直接返回
            return filepath
        stem, suffix = filepath.stem, filepath.suffix  # 分离文件名和扩展名
        counter = 2  # 从 _2 开始
        while True:
            new_path = filepath.with_name(f"{stem}_{counter}{suffix}")  # 构造新文件名
            if not new_path.exists():  # 找到可用的文件名
                return new_path
            counter += 1  # 序号递增

    # ——— 递归页面收集 ———

    def _collect_pages(self, start_url: str, max_depth: int) -> list[str]:
        """使用 BFS（广度优先搜索）递归收集同域名下的所有页面 URL

        从起始 URL 出发，逐层访问同级域名页面，直到达到最大深度。
        使用 visited 集合避免循环访问。

        Args:
            start_url: 起始页面 URL
            max_depth: 最大搜索深度

        Returns:
            收集到的页面 URL 列表
        """
        base_domain = urlparse(start_url).netloc  # 提取起始 URL 的域名
        visited: set[str] = set()  # 已访问 URL 集合，防止重复
        queue: list[tuple[str, int]] = [(start_url, 1)]  # BFS 队列：(URL, 当前深度)
        pages: list[str] = []  # 收集到的页面列表

        while queue:  # 当队列非空时继续
            url, depth = queue.pop(0)  # 取出队首元素（FIFO）
            if url in visited:  # 已访问过，跳过
                continue
            visited.add(url)  # 标记为已访问
            pages.append(url)  # 加入结果列表

            if depth >= max_depth:  # 达到最大深度，不继续深入
                continue

            html = self._fetch_page(url)  # 获取当前页面 HTML
            if html is None:  # 获取失败，跳过
                continue

            soup = BeautifulSoup(html, "html.parser")  # 解析 HTML
            for a in soup.find_all("a", href=True):  # 遍历所有链接
                href = a["href"].strip()  # 获取链接地址
                resolved = urljoin(url, href)  # 转换为绝对 URL
                parsed = urlparse(resolved)  # 解析 URL
                # 只收集同域名、未访问过的 URL
                if parsed.netloc == base_domain and resolved not in visited:
                    clean = resolved.split("#")[0]  # 去掉 URL 中的锚点（#xxx）
                    if clean not in visited:
                        queue.append((clean, depth + 1))  # 加入队列，深度 +1

        return pages  # 返回收集到的所有页面

    # ——— 格式转换集成 ———

    def convert_downloaded(self, downloaded_files: list[Path], target_format: str,
                           preset: str = "medium") -> list[Path]:
        """下载完成后，批量转换视频格式

        Args:
            downloaded_files: 已下载的视频文件路径列表
            target_format: 目标格式（如 "mp4"、"webm"、"mkv"）
            preset: 编码预设（fast / medium / slow），影响速度与质量的平衡

        Returns:
            转换后的文件路径列表
        """
        converter = VideoConverter()  # 实例化视频格式转换器
        converted: list[Path] = []  # 存储转换成功的文件路径

        for idx, src_path in enumerate(downloaded_files, 1):  # 遍历每个已下载的文件
            if not src_path.exists():  # 源文件不存在
                print(f"  [{idx}/{len(downloaded_files)}] ⚠️  {src_path.name} 不存在，跳过转换", file=sys.stderr)
                continue  # 跳过不存在的文件
            if src_path.suffix.lstrip(".") == target_format.lstrip("."):
                # 已经是目标格式，无需转换
                print(f"  [{idx}/{len(downloaded_files)}] ⏭️  {src_path.name} 已是 {target_format} 格式，跳过")
                converted.append(src_path)  # 保留原文件路径
                continue

            dst_path = converter.convert(src_path, target_format, preset=preset)
            # 执行单个视频的格式转换
            if dst_path is not None:
                converted.append(dst_path)  # 转换成功，添加到结果列表

        return converted  # 返回所有转换后的文件路径


# ============================================================
#  VideoConverter —— 视频格式转换器
# ============================================================

# 支持的视频输出格式及其编码参数映射表
# 格式名 → (容器格式, 视频编码器, 音频编码器, 额外参数)
_SUPPORTED_FORMATS: dict[str, tuple[str, str, str, list[str]]] = {
    "mp4": ("mp4", "libx264", "aac", ["-movflags", "+faststart"]),
    # MP4：H.264 视频 + AAC 音频，faststart 让网页可边下边播
    "webm": ("webm", "libvpx-vp9", "libopus", ["-deadline", "good"]),
    # WebM：VP9 视频 + Opus 音频，浏览器原生支持
    "mkv": ("matroska", "libx264", "aac", []),
    # MKV：Matroska 容器，无损封装，支持多音轨字幕
    "mov": ("mov", "libx264", "aac", []),
    # MOV：QuickTime 容器，Apple 生态常用
    "avi": ("avi", "libx264", "mp3", []),
    # AVI：经典容器格式，兼容性最广
    "flv": ("flv", "libx264", "aac", []),
    # FLV：Flash Video 格式
    "wmv": ("asf", "libx264", "wmav2", []),
    # WMV：Windows Media Video
    "m4v": ("ipod", "libx264", "aac", []),
    # M4V：iTunes/Apple 设备优化格式
    "ogg": ("ogg", "libtheora", "libvorbis", []),
    # OGG：开源免专利格式
    "gif": ("gif", "gif", "", []),
    # GIF：动图格式，无音频
}

# 可以直接 stream copy 的格式对集合（源后缀, 目标后缀）
# 在相同容器族内转换时，优先使用 -c copy 无损复制，速度极快
_STREAM_COPY_FRIENDLY: set[tuple[str, str]] = {
    (".mp4", ".m4v"), (".m4v", ".mp4"),  # MP4 和 M4V 本质相同容器
    (".mkv", ".mp4"), (".mp4", ".mkv"),  # MKV ↔ MP4 互转
    (".mov", ".mp4"), (".mp4", ".mov"),  # MOV ↔ MP4
    (".webm", ".mkv"), (".mkv", ".webm"),  # WebM ↔ MKV
}


class VideoConverter:
    """视频格式转换器

    基于 ffmpeg 实现智能视频格式转换，核心特性：
    1. 两阶段转换策略：优先 stream copy（秒级），失败后 fallback 到重编码
    2. 实时进度跟踪：通过 ffmpeg -progress pipe 解析转换进度
    3. 批量并行转换：ThreadPoolExecutor 多线程并行
    4. 自动检测 ffmpeg 可用性

    参考实现借鉴：
    - Proton1917/video-format-converter（两阶段策略 + 并行处理）
    - vjackl001/ytdownloader（subprocess + ffmpeg 集成模式）
    """

    def __init__(self):
        """初始化转换器 —— 检查 ffmpeg 可用性"""
        self._ffmpeg_path: str = self._find_ffmpeg()  # 查找 ffmpeg 可执行文件路径

    @staticmethod
    def _find_ffmpeg() -> str:
        """查找系统中 ffmpeg 的安装路径

        Returns:
            ffmpeg 可执行文件路径字符串

        Raises:
            RuntimeError: 如果系统中未安装 ffmpeg
        """
        ffmpeg_path = shutil.which("ffmpeg")  # 在系统 PATH 中搜索 ffmpeg 命令
        if ffmpeg_path is None:  # 未找到 ffmpeg
            raise RuntimeError(
                "未检测到 ffmpeg，请先安装：\n"  # 错误提示
                "  macOS: brew install ffmpeg\n"  # macOS 安装指引
                "  Ubuntu: sudo apt install ffmpeg\n"  # Ubuntu 安装指引
                "  Windows: choco install ffmpeg"  # Windows 安装指引
            )
        return ffmpeg_path  # 返回找到的路径

    # ——— 公开接口 ———

    def convert(
        self, input_path: Path, target_format: str, preset: str = "medium",
        remove_original: bool = False,
    ) -> Path | None:
        """转换单个视频文件到指定格式

        采用两阶段策略：
        阶段 1 —— stream copy：如果源和目标格式兼容，尝试 -c copy 无损复制，
                 速度极快（通常只需几秒），无画质损失
        阶段 2 —— re-encode：如果 stream copy 不适用或失败，使用编码器重新编码

        Args:
            input_path: 输入视频文件路径
            target_format: 目标格式（如 "mp4"、"webm"、"mkv"），不含点号
            preset: 编码速度预设（fast / medium / slow），默认 medium

        Returns:
            转换后的文件路径；失败返回 None
        """
        # 归一化目标格式（去除前导点号并转小写）
        target_format = target_format.lstrip(".").lower()  # 统一格式名

        # 验证目标格式是否受支持
        if target_format not in _SUPPORTED_FORMATS:
            supported = ", ".join(_SUPPORTED_FORMATS.keys())  # 列出所有支持的格式
            print(f"  ❌ 不支持的格式: {target_format}，支持: {supported}", file=sys.stderr)
            return None  # 不支持的格式

        # 构建输出路径（同目录，新扩展名）
        output_path = input_path.with_suffix(f".{target_format}")  # 替换扩展名
        output_path = self._ensure_unique_path(output_path)  # 避免覆盖已有文件

        # 获取该格式的编码参数
        container, vcodec, acodec, extra_args = _SUPPORTED_FORMATS[target_format]
        # 解包编码配置元组

        # ——— 阶段 1：尝试 stream copy（无损快速转换） ———
        src_suffix = input_path.suffix.lower()  # 获取源文件扩展名并转小写
        can_stream_copy = (src_suffix, f".{target_format}") in _STREAM_COPY_FRIENDLY
        # 检查源格式和目标格式是否属于可无损复制的格式对

        if can_stream_copy:  # 源和目标容器兼容
            print(f"  🚀 尝试 stream copy（无损模式）...")  # 提示用户
            success = self._run_ffmpeg_stream_copy(
                input_path, output_path, container,  # 源文件、目标文件、容器格式
            )
            if success:
                final_size = output_path.stat().st_size / (1024 * 1024)  # 文件大小 MB
                print(f"  ✅ stream copy 成功 → {output_path.name} ({final_size:.1f} MB)")
                if remove_original:  # 如果要求删除原文件
                    input_path.unlink()  # 删除原始文件
                return output_path  # 返回转换后的路径

        # ——— 阶段 2：re-encode 重编码 ———
        print(f"  🎬 使用编码器重新编码（{preset} 预设）...")  # 提示用户
        success = self._run_ffmpeg_encode(
            input_path, output_path, vcodec, acodec,  # 输入输出 + 编码器
            extra_args, preset,  # 额外参数 + 速度预设
        )
        if success:
            final_size = output_path.stat().st_size / (1024 * 1024)  # 文件大小 MB
            print(f"  ✅ 转换完成 → {output_path.name} ({final_size:.1f} MB)")
            if remove_original:  # 如果要求删除原文件
                input_path.unlink()  # 删除原始文件
            return output_path  # 返回转换后的路径
        else:
            # 转换失败，清理残留的部分文件
            if output_path.exists():
                output_path.unlink()  # 删除不完整的输出文件
            return None  # 返回 None 表示失败

    def convert_batch(
        self, input_paths: list[Path], target_format: str,
        preset: str = "medium", max_workers: int = 2,
    ) -> list[Path]:
        """批量并行转换多个视频文件

        Args:
            input_paths: 输入文件路径列表
            target_format: 目标格式
            preset: 编码预设
            max_workers: 并行工作线程数（默认 2，避免过多 I/O 争抢）

        Returns:
            转换成功的文件路径列表
        """
        results: list[Path] = []  # 存储成功转换的结果
        total = len(input_paths)  # 总文件数

        with ThreadPoolExecutor(max_workers=max_workers) as executor:  # 创建线程池
            future_map = {}  # Future → 文件路径映射
            for i, path in enumerate(input_paths):
                future = executor.submit(self.convert, path, target_format, preset)
                # 提交异步转换任务
                future_map[future] = (i + 1, path)  # 记录序号和路径

            for future in as_completed(future_map):  # 按完成顺序迭代
                idx, src_path = future_map[future]  # 反查序号和源路径
                try:
                    result = future.result()  # 获取转换结果
                    if result is not None:
                        results.append(result)  # 添加到成功列表
                        print(f"  [{idx}/{total}] ✅ {src_path.name} → {result.name}")
                    else:
                        print(f"  [{idx}/{total}] ❌ {src_path.name} 转换失败", file=sys.stderr)
                except Exception as e:
                    print(f"  [{idx}/{total}] ❌ {src_path.name}: {e}", file=sys.stderr)

        return results  # 返回所有成功转换的文件路径

    # ——— 内部实现 ———

    def _run_ffmpeg_stream_copy(
        self, input_path: Path, output_path: Path, container: str,
    ) -> bool:
        """执行 ffmpeg stream copy（-c copy）无损容器转换

        Args:
            input_path: 输入文件
            output_path: 输出文件
            container: 目标容器格式

        Returns:
            True 表示成功
        """
        cmd = [  # 构建 ffmpeg 命令列表
            self._ffmpeg_path,  # ffmpeg 可执行文件路径
            "-y",  # 自动覆盖已存在的输出文件
            "-i", str(input_path),  # 指定输入文件
            "-c", "copy",  # 所有流（视频+音频+字幕）直接复制，不重新编码
            "-f", container,  # 强制指定输出容器格式
            str(output_path),  # 输出文件路径
        ]
        return self._execute_ffmpeg(cmd, "stream_copy")  # 执行命令并返回结果

    def _run_ffmpeg_encode(
        self, input_path: Path, output_path: Path,
        vcodec: str, acodec: str, extra_args: list[str], preset: str,
    ) -> bool:
        """执行 ffmpeg 重编码

        Args:
            input_path: 输入文件
            output_path: 输出文件
            vcodec: 视频编码器
            acodec: 音频编码器
            extra_args: 额外 ffmpeg 参数
            preset: 编码速度预设

        Returns:
            True 表示成功
        """
        cmd = [  # 构建 ffmpeg 命令列表
            self._ffmpeg_path,  # ffmpeg 路径
            "-y",  # 覆盖已存在文件
            "-i", str(input_path),  # 输入文件
            "-c:v", vcodec,  # 视频编码器
            "-preset", preset,  # 编码速度预设（fast/medium/slow）
            "-crf", "23",  # 恒定质量因子（0-51，23 为默认平衡值）
        ]
        if acodec:  # 如果需要音频编码器（GIF 等格式不需要）
            cmd.extend(["-c:a", acodec])  # 音频编码器
            cmd.extend(["-b:a", "128k"])  # 音频码率 128kbps
        if extra_args:  # 如果有额外参数
            cmd.extend(extra_args)  # 追加到命令
        cmd.append(str(output_path))  # 输出文件路径（最后的位置参数）

        return self._execute_ffmpeg(cmd, "encode")  # 执行命令并返回结果

    def _execute_ffmpeg(self, cmd: list[str], mode: str) -> bool:
        """执行 ffmpeg 命令并实时解析进度

        通过 ffmpeg 的 -progress 管道获取结构化进度信息，
        解析 "out_time_ms" 字段计算转换百分比并显示进度条。

        参考：Proton1917/video-format-converter 的进度跟踪模式

        Args:
            cmd: ffmpeg 命令行参数列表
            mode: 模式标签（"stream_copy" / "encode"），用于进度显示

        Returns:
            True 表示转换成功
        """
        # 先探测视频总时长（用于进度百分比计算）
        total_duration_us = self._get_duration(cmd[cmd.index("-i") + 1])
        # 从命令行参数中取出输入文件路径，获取视频时长（微秒）

        # 在命令中插入 -progress 参数，让 ffmpeg 输出结构化进度信息
        progress_cmd = cmd[:1] + ["-progress", "pipe:1", "-nostats", "-loglevel", "error"]
        # -progress pipe:1 → 进度信息输出到 stdout（管道）
        # -nostats → 禁用默认的统计输出
        # -loglevel error → 只输出错误信息
        progress_cmd += cmd[1:]  # 追加原始命令参数

        try:
            process = subprocess.Popen(  # 启动 ffmpeg 子进程
                progress_cmd,
                stdout=subprocess.PIPE,  # 捕获 stdout（进度信息）
                stderr=subprocess.PIPE,  # 捕获 stderr（错误信息）
                text=True,  # 以文本模式处理输出
                encoding="utf-8",  # UTF-8 编码
                errors="replace",  # 编码错误时替换为替代字符
            )

            last_pct = -5  # 上次显示的百分比（步长 5% 更新一次）
            for line in process.stdout:  # 逐行读取 ffmpeg 的进度输出
                line = line.strip()  # 去除首尾空白
                if line.startswith("out_time_ms="):  # 当前输出时间戳（微秒）
                    try:
                        current_us = int(line.split("=")[1])  # 提取时间值（微秒）
                    except ValueError:
                        continue  # 解析失败则跳过本行
                    if total_duration_us and total_duration_us > 0:
                        # 计算进度百分比
                        pct = min(int(current_us / total_duration_us * 100), 99)
                        if pct >= last_pct + 5:  # 每 5% 输出一次（减少终端闪烁）
                            last_pct = pct  # 更新上次百分比
                            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                            # 用 █░ 字符绘制简易进度条（20 格 = 100%）
                            print(
                                f"\r  [{mode}] {bar} {pct}%",  # 进度条格式
                                end="",  # 不换行，原地刷新
                                flush=True,  # 立即输出
                            )

            # 等待子进程结束
            returncode = process.wait(timeout=3600)  # 最多等待 1 小时
            if returncode == 0:  # 正常退出
                print(f"\r  [{mode}] ████████████████████ 100%")  # 完成进度条
                return True  # 转换成功
            else:
                # 读取 stderr 中的错误信息
                stderr_text = process.stderr.read() if process.stderr else ""
                print(f"\n  ❌ ffmpeg 错误 (code={returncode}): {stderr_text[:200]}", file=sys.stderr)
                return False  # 转换失败

        except subprocess.TimeoutExpired:
            process.kill()  # 超时则强制终止 ffmpeg 子进程
            print(f"\n  ❌ 转换超时（超过 1 小时）", file=sys.stderr)
            return False  # 超时失败
        except Exception as e:
            print(f"\n  ❌ ffmpeg 执行异常: {e}", file=sys.stderr)
            return False  # 异常失败

    @staticmethod
    def _get_duration(filepath: str) -> int:
        """使用 ffprobe 获取视频总时长（微秒）

        Args:
            filepath: 视频文件路径

        Returns:
            时长微秒数，获取失败返回 0
        """
        try:
            result = subprocess.run(  # 执行 ffprobe 命令
                [
                    "ffprobe",  # ffprobe 媒体信息探测工具
                    "-v", "error",  # 只显示错误信息
                    "-show_entries", "format=duration",  # 只输出时长信息
                    "-of", "default=noprint_wrappers=1:nokey=1",  # 纯数字输出格式
                    filepath,  # 目标文件
                ],
                capture_output=True,  # 捕获输出
                text=True,  # 文本模式
                timeout=30,  # 30 秒超时
            )
            if result.returncode == 0:  # 执行成功
                duration_sec = float(result.stdout.strip())  # 解析秒数（浮点数）
                return int(duration_sec * 1_000_000)  # 转换为微秒整数
        except (subprocess.TimeoutExpired, ValueError, OSError):
            pass  # 探测失败则降级处理（无法显示百分比进度）
        return 0  # 获取失败返回 0

    @staticmethod
    def _ensure_unique_path(filepath: Path) -> Path:
        """确保输出文件路径不冲突（追加序号避免覆盖）

        Args:
            filepath: 期望的输出路径

        Returns:
            不冲突的可用路径
        """
        if not filepath.exists():  # 文件不存在
            return filepath  # 直接使用
        stem = filepath.stem  # 文件名（不含扩展名）
        suffix = filepath.suffix  # 扩展名
        counter = 2  # 从 _2 开始
        while True:
            new_path = filepath.with_name(f"{stem}_{counter}{suffix}")  # 构造新文件名
            if not new_path.exists():  # 可用
                return new_path
            counter += 1  # 递增计数器
