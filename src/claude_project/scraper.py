"""网页图片爬取器 —— 从指定 URL 抓取并下载图片"""

from __future__ import annotations  # 启用延迟注解求值，兼容 Python 3.9

import json  # 解析搜索引擎结果中的 JSON 数据块
import re  # 正则匹配，解析 style 属性与内联脚本
import sys  # 标准错误输出与命令行输出
from dataclasses import dataclass, field  # 定义 ScrapeConfig 数据类
from pathlib import Path  # 跨平台文件路径操作
from urllib.parse import urljoin, urlparse  # URL 解析、域名提取、相对路径拼接

import requests  # HTTP 请求，获取网页 HTML 与图片二进制数据
from bs4 import BeautifulSoup  # HTML 解析，遍历 DOM 树

# ─── 常量定义 ───

DEFAULT_USER_AGENT = (  # 默认 User-Agent，模拟 Chrome 浏览器
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

IMAGE_CONTENT_TYPES = {  # 允许下载的图片 MIME 类型集合
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/bmp",
    "image/tiff",
    "image/x-icon",
    "image/vnd.microsoft.icon",
}

EXTENSION_MAP = {  # MIME 类型 → 文件扩展名映射
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}

# ─── 搜索引擎图片正则模式 ───
# 各搜索引擎将图片 URL 放在内联脚本的 JSON 字段中，字段名各不相同：
#   Bing   → "murl"
#   Google → "mediaurl"
#   Baidu  → "objURL"
# 以下正则列表按字段名逐一匹配，覆盖主流搜索引擎结果页。

_SEARCH_ENGINE_PATTERNS = [  # 搜索引擎图片 URL 正则模式列表
    re.compile(r'"murl"\s*:\s*"([^"]+)"'),  # Bing 图片搜索
    re.compile(r'"mediaurl"\s*:\s*"([^"]+)"'),  # Google 图片搜索
    re.compile(r'"objURL"\s*:\s*"([^"]+)"'),  # Baidu 图片搜索
    re.compile(r'"thumbUrl"\s*:\s*"([^"]+)"'),  # 通用缩略图字段
]


@dataclass  # 将 ScrapeConfig 声明为数据类
class ScrapeConfig:
    """爬取配置"""
    url: str  # 起始爬取 URL
    output_dir: Path = Path("images")  # 图片下载输出目录
    max_images: int = 0  # 最大下载图片数，0 = 不限制
    extensions: set = field(default_factory=set)  # 文件扩展名过滤集合，空 = 不限制
    recursive: bool = False  # 是否递归爬取子页面
    max_depth: int = 1  # 递归爬取最大深度
    timeout: int = 30  # HTTP 请求超时时间（秒）
    user_agent: str = DEFAULT_USER_AGENT  # 请求 User-Agent 头


class ImageScraper:
    """网页图片爬取器"""

    def __init__(self, config: ScrapeConfig):  # 构造方法，接收配置对象
        self.config = config  # 绑定爬取配置
        self.config.output_dir.mkdir(parents=True, exist_ok=True)  # 确保输出目录存在
        self._seen_urls: set[str] = set()  # 已处理过的图片 URL 去重集合
        self._downloaded_names: set[str] = set()  # 已下载的文件名集合
        self._session = requests.Session()  # 创建复用的 HTTP 会话
        self._session.headers["User-Agent"] = self.config.user_agent  # 设置 UA 头

    # ─── 公开接口 ───

    def scrape(self) -> dict:  # 主流程入口，返回统计信息字典
        """主流程：爬取图片，返回统计字典"""
        result = {  # 统计结果字典
            "downloaded": 0,  # 成功下载数
            "skipped": 0,  # 跳过数
            "errors": 0,  # 错误数
            "pages_visited": 0,  # 访问的页面数
        }

        if self.config.recursive and self.config.max_depth > 1:  # 递归模式且深度大于 1
            page_urls = self._collect_pages(  # BFS 收集同域页面 URL
                self.config.url, self.config.max_depth
            )
        else:  # 单页面模式
            page_urls = [self.config.url]  # 仅爬取当前页面

        result["pages_visited"] = len(page_urls)  # 记录访问页面总数
        all_image_urls: list[str] = []  # 收集到的所有图片 URL

        for page_url in page_urls:  # 遍历每个页面 URL
            html = self._fetch_page(page_url)  # GET 请求获取 HTML
            if html is None:  # 页面获取失败
                continue  # 跳过此页面
            img_urls = self._extract_image_urls(html)  # 从 HTML 提取图片 URL
            for u in img_urls:  # 遍历提取到的每个 URL
                resolved = self._resolve_url(page_url, u)  # 转为绝对 URL
                if resolved and resolved not in self._seen_urls:  # 有效且未重复
                    self._seen_urls.add(resolved)  # 加入去重集合
                    all_image_urls.append(resolved)  # 加入结果列表

        total = len(all_image_urls)  # 去重后的图片总数
        if total == 0:  # 没有找到任何图片
            print("未找到任何图片。")  # 提示用户
            return result  # 返回空统计

        if self.config.extensions:  # 配置了扩展名过滤
            filtered = [  # 过滤后的列表
                u for u in all_image_urls
                if self._match_extension(u)  # 检查扩展名是否匹配
            ]
            result["skipped"] += len(all_image_urls) - len(filtered)  # 统计被跳过的数量
            all_image_urls = filtered  # 替换为过滤后列表

        if self.config.max_images > 0:  # 配置了最大下载数
            all_image_urls = all_image_urls[:self.config.max_images]  # 截取指定数量

        total = len(all_image_urls)  # 最终待下载图片数量
        print(f"找到 {total} 张图片，开始下载...\n")  # 打印下载提示

        for idx, url in enumerate(all_image_urls, 1):  # 遍历下载，索引从 1 开始
            if self.config.max_images > 0 and result["downloaded"] >= self.config.max_images:  # 已达上限
                break  # 停止下载

            success, msg = self._download_one(url, idx, total)  # 下载单张图片
            if success:  # 下载成功
                result["downloaded"] += 1  # 成功计数 +1
                print(f"  [{idx}/{total}] ✅ {msg}")  # 打印成功信息
            elif "跳过" in msg:  # 跳过（如已存在同名文件）
                result["skipped"] += 1  # 跳过计数 +1
                print(f"  [{idx}/{total}] ⏭️  {msg}")  # 打印跳过信息
            else:  # 下载失败
                result["errors"] += 1  # 错误计数 +1
                print(f"  [{idx}/{total}] ❌ {msg}", file=sys.stderr)  # 输出到 stderr

        return result  # 返回最终统计结果

    # ─── 页面获取 ───

    def _fetch_page(self, url: str) -> str | None:  # 获取页面 HTML，失败返回 None
        """GET 请求获取页面 HTML"""
        try:  # 尝试请求
            resp = self._session.get(url, timeout=self.config.timeout)  # 发送 GET 请求
            resp.raise_for_status()  # 非 2xx 状态码抛出异常
            resp.encoding = resp.apparent_encoding or "utf-8"  # 自动检测编码，回退 UTF-8
            return resp.text  # 返回页面 HTML 文本
        except requests.RequestException as e:  # 捕获所有请求异常
            print(f"  ⚠️  无法访问页面 {url}: {e}", file=sys.stderr)  # 输出警告
            return None  # 返回 None 表示失败

    # ─── 图片 URL 提取 ───

    def _extract_image_urls(self, html: str) -> list[str]:  # 从 HTML 提取所有图片 URL
        """从 HTML 中提取所有图片 URL（含懒加载、搜索引擎、noscript 回退）"""
        soup = BeautifulSoup(html, "html.parser")  # 创建 BeautifulSoup 解析树
        urls: list[str] = []  # 收集提取到的图片 URL

        # 1. <img> 标签 — 标准图片元素
        for img in soup.find_all("img"):  # 遍历所有 <img> 标签
            url = self._pick_image_url(img)  # 从标签属性中按优先级提取 URL
            if url:  # 提取到有效 URL
                urls.append(url)  # 加入结果列表

        # 2. <picture> 内的 <source> 标签 — 响应式图片候选项
        for picture in soup.find_all("picture"):  # 遍历所有 <picture> 容器
            for source in picture.find_all("source"):  # 遍历每个 <source> 子元素
                url = self._pick_image_url(source)  # 从 src/srcset/data-srcset 提取
                if url:  # 提取到有效 URL
                    urls.append(url)  # 加入结果列表

        # 3. <link rel="icon"> / <link rel="apple-touch-icon"> — 网站图标
        for link in soup.find_all("link"):  # 遍历所有 <link> 标签
            rel = link.get("rel", [])  # 获取 rel 属性值
            if isinstance(rel, str):  # 如果是字符串
                rel = [rel]  # 转为列表统一处理
            rel_lower = [r.lower() for r in rel]  # 转为小写便于比较
            if any(r in rel_lower for r in ("icon", "apple-touch-icon", "apple-touch-icon-precomposed")):  # 匹配图标类型
                href = link.get("href", "")  # 获取 href 属性
                if href:  # href 非空
                    urls.append(href)  # 加入结果列表

        # 4. <meta> og:image / twitter:image — Open Graph 社交分享图片
        for meta in soup.find_all("meta"):  # 遍历所有 <meta> 标签
            prop = meta.get("property", "").lower()  # 获取 property 属性
            name = meta.get("name", "").lower()  # 获取 name 属性
            content = meta.get("content", "")  # 获取 content 属性
            if content and ("og:image" in prop or "twitter:image" in name):  # 匹配社交分享图片
                urls.append(content)  # 加入结果列表

        # 5. 背景图: style 属性中的 url(...) — 内联 CSS 背景图片
        for tag in soup.find_all(style=True):  # 遍历所有含 style 属性的标签
            style = tag.get("style", "")  # 获取 style 属性值
            bg_urls = re.findall(r'url\(["\']?([^)"\']+)["\']?\)', style)  # 正则提取 url(...)
            urls.extend(bg_urls)  # 批量加入结果列表

        # 6. <noscript> 标签内的回退图片 — 懒加载框架常把真实 URL 放在这里
        for noscript in soup.find_all("noscript"):  # 遍历所有 <noscript> 标签
            inner_html = noscript.decode_contents()  # 获取 noscript 内部 HTML
            if inner_html.strip():  # 内部有内容
                inner_soup = BeautifulSoup(inner_html, "html.parser")  # 二次解析内部 HTML
                for img in inner_soup.find_all("img"):  # 查找内部 <img> 标签
                    url = self._pick_image_url(img)  # 从标签属性提取 URL
                    if url:  # 提取到有效 URL
                        urls.append(url)  # 加入结果列表
                # 也处理 <noscript> 内的 <picture> 元素
                for picture in inner_soup.find_all("picture"):  # 查找内部 <picture> 标签
                    for source in picture.find_all("source"):  # 查找 <source> 子元素
                        url = self._pick_image_url(source)  # 提取 URL
                        if url:  # 有效 URL
                            urls.append(url)  # 加入结果列表

        # 7. 搜索引擎图片结果提取 — Bing/Google/Baidu 的内联脚本数据
        search_urls = self._extract_search_engine_images(html)  # 从脚本/JSON 中提取
        urls.extend(search_urls)  # 合并搜索引擎提取的 URL

        # 8. 检测 JS 渲染：页面内容大但 <img> 标签极少时发出警告
        img_tag_count = len(soup.find_all("img"))  # 统计页面上的 <img> 标签数量
        if img_tag_count < 5 and len(html) > 50000:  # HTML >50KB 但 <img> 少于 5 个
            print(  # 输出警告信息
                "  ⚠️  页面 <img> 标签极少（仅 {} 个），图片可能由 JavaScript 动态渲染，"
                "建议使用 headless 浏览器抓取".format(img_tag_count),
                file=sys.stderr,  # 输出到标准错误
            )

        return urls  # 返回所有提取到的 URL 列表

    def _pick_image_url(self, tag) -> str | None:  # 从单个标签提取最佳 URL
        """从单个 tag 中按优先级提取图片 URL"""
        # 懒加载属性优先 — data-src / data-lazy-src / data-original
        for attr in ("data-src", "data-lazy-src", "data-original"):  # 按优先级遍历懒加载属性
            val = tag.get(attr, "")  # 获取属性值
            if val and not val.startswith("data:"):  # 非 data URI 则有效
                return val.strip()  # 返回去除空白的 URL

        # data-srcset — 响应式图片的懒加载版本，取第一个候选项
        srcset = tag.get("data-srcset", "")  # 获取 data-srcset 属性
        if srcset:  # 存在 data-srcset
            first = self._first_srcset_candidate(srcset)  # 取第一个 URL 候选项
            if first:  # 有效候选项
                return first  # 返回第一个 URL

        # src — 标准图片 URL
        src = tag.get("src", "")  # 获取 src 属性
        if src and not src.startswith("data:"):  # 非 data URI 则有效
            return src.strip()  # 返回去除空白的 URL

        # srcset — 标准响应式图片，取第一个候选项
        srcset = tag.get("srcset", "")  # 获取 srcset 属性
        if srcset:  # 存在 srcset
            first = self._first_srcset_candidate(srcset)  # 取第一个 URL 候选项
            if first:  # 有效候选项
                return first  # 返回第一个 URL

        return None  # 未找到任何有效图片 URL

    @staticmethod  # 静态方法，无需访问实例
    def _first_srcset_candidate(srcset: str) -> str | None:  # 提取 srcset 第一候选 URL
        """从 srcset 中提取第一个 URL 候选项"""
        parts = srcset.split(",")  # 按逗号分割多个候选项
        if parts:  # 存在候选项
            first = parts[0].strip()  # 取第一个候选项并去除空白
            # 格式: "url 1x" 或 "url 100w" — 空格前为 URL
            candidate = first.split(" ")[0].strip()  # 取空格分隔的第一部分
            if candidate:  # URL 非空
                return candidate  # 返回 URL
        return None  # 无有效候选项

    # ─── 搜索引擎图片提取 ───

    def _extract_search_engine_images(self, html: str) -> list[str]:  # 从搜索引擎结果提取图片 URL
        """从搜索引擎（Bing/Google/Baidu）结果页的内联脚本和 JSON 数据中提取图片 URL"""
        urls: list[str] = []  # 收集提取到的图片 URL

        # 方式 1：从 <script> 标签内容中正则在索
        soup = BeautifulSoup(html, "html.parser")  # 再次解析 HTML（轻量，仅遍历 script）
        for script in soup.find_all("script"):  # 遍历所有 <script> 标签
            script_text = script.string or ""  # 获取脚本文本内容
            if not script_text:  # 空脚本跳过
                continue  # 下一个
            for pattern in _SEARCH_ENGINE_PATTERNS:  # 遍历所有搜索引擎正则模式
                matches = pattern.findall(script_text)  # 在脚本文本中搜索匹配
                urls.extend(matches)  # 合并匹配结果

        # 方式 2：从内联 JSON 数据块中提取（Bing 等会将图片数据放在 JSON 对象中）
        json_blocks = re.findall(  # 正则匹配包含搜索引擎键的 JSON 对象
            r'\{[^{}]*"(?:murl|mediaurl|objURL)"[^{}]*\}', html
        )
        for json_str in json_blocks:  # 遍历匹配到的 JSON 字符串
            try:  # 尝试解析 JSON
                data = json.loads(json_str)  # 解析 JSON 字符串
                for key in ("murl", "mediaurl", "objURL"):  # 检查已知的搜索引擎图片字段
                    if key in data and isinstance(data[key], str) and data[key]:  # 字段存在且为非空字符串
                        urls.append(data[key])  # 加入结果列表
            except (json.JSONDecodeError, TypeError):  # JSON 解析失败或类型错误
                pass  # 静默跳过，不影响其他提取

        # 方式 3：整页正则搜刮 — 对 JSON 片段不完整的场景做兜底
        for pattern in _SEARCH_ENGINE_PATTERNS:  # 再次遍历所有搜索引擎正则
            body = re.sub(r'<[^>]+>', ' ', html)  # 去除 HTML 标签，保留纯文本/JSON
            matches = pattern.findall(body)  # 在纯文本中搜索
            for m in matches:  # 遍历匹配结果
                if m not in urls:  # 去重检查
                    urls.append(m)  # 加入结果列表

        return urls  # 返回所有提取到的搜索引擎图片 URL

    # ─── URL 处理 ───

    def _resolve_url(self, base_url: str, img_url: str) -> str | None:  # 相对 URL 转绝对 URL
        """将相对 URL 转换为绝对 URL"""
        try:  # 尝试解析
            resolved = urljoin(base_url, img_url)  # 使用 urljoin 拼接
            # 过滤明显的非图片 URL
            parsed = urlparse(resolved)  # 解析绝对 URL
            if not parsed.scheme or not parsed.netloc:  # 协议或域名缺失
                return None  # 视为无效 URL
            return resolved  # 返回有效绝对 URL
        except ValueError:  # URL 格式非法
            return None  # 返回 None

    def _match_extension(self, url: str) -> bool:  # 检查 URL 扩展名是否匹配配置
        """检查 URL 是否匹配配置的扩展名过滤"""
        if not self.config.extensions:  # 未配置扩展名过滤
            return True  # 全部通过
        path = urlparse(url).path.lower()  # 提取 URL 路径并转小写
        if not path:  # 路径为空
            return True  # 无法判断则不排除
        return any(path.endswith(ext.lower()) for ext in self.config.extensions)  # 检查任一扩展名匹配

    # ─── 图片下载 ───

    def _download_one(self, url: str, index: int, total: int) -> tuple[bool, str]:  # 下载单张图片
        """下载单张图片，返回 (成功, 消息)"""
        try:  # 尝试下载
            resp = self._session.get(url, timeout=self.config.timeout, stream=True)  # 流式 GET 请求
            resp.raise_for_status()  # 非 2xx 抛出异常

            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()  # 提取 MIME 类型

            # 检查是否是图片 — 非图片 MIME 类型不阻止下载（可能是缺 Content-Type 头的图片）
            if content_type and content_type not in IMAGE_CONTENT_TYPES:  # MIME 不在白名单
                pass  # 仍然允许保存，避免误杀无 Content-Type 的图片

            filename = self._safe_filename(url, index, content_type)  # 生成安全文件名
            filepath = self.config.output_dir / filename  # 拼接完整输出路径

            # 避免覆盖：如果已存在则加序号
            filepath = self._ensure_unique(filepath)  # 确保文件名不重复

            with open(filepath, "wb") as f:  # 以二进制写模式打开文件
                for chunk in resp.iter_content(chunk_size=8192):  # 按 8KB 块迭代响应体
                    f.write(chunk)  # 写入文件

            return True, filepath.name  # 返回成功及文件名

        except requests.RequestException as e:  # 网络请求异常
            return False, f"{url}: 网络错误 - {e}"  # 返回网络错误信息
        except OSError as e:  # 文件系统异常
            return False, f"{url}: 写入失败 - {e}"  # 返回写入错误信息

    def _safe_filename(self, url: str, index: int, content_type: str = "") -> str:  # 生成安全文件名
        """从 URL 生成安全的文件名"""
        parsed = urlparse(url)  # 解析 URL
        path = parsed.path or ""  # 提取路径部分
        filename = Path(path).name  # 取路径最后一段作为文件名

        # 如果 URL 路径没有合适的文件名
        if not filename or filename in ("/", ""):  # 无有效文件名
            filename = f"image_{index}"  # 使用索引生成默认文件名

        # 去除查询参数残留和非法字符
        name, ext = Path(filename).stem, Path(filename).suffix  # 分离名称与扩展名
        name = re.sub(r'[<>:"/\\|?*]', "_", name)  # 替换非法字符为下划线
        if not name:  # 替换后名称为空
            name = f"image_{index}"  # 使用默认名称

        # 确保有正确的扩展名
        if not ext or len(ext) > 6:  # 无扩展名或扩展名异常长
            ext = EXTENSION_MAP.get(content_type, ".jpg")  # 根据 MIME 映射，默认 .jpg

        return f"{name}{ext}"  # 拼接安全文件名

    def _ensure_unique(self, filepath: Path) -> Path:  # 确保文件名不重复
        """如果文件已存在，生成不重复的文件名"""
        if not filepath.exists():  # 文件不存在
            return filepath  # 直接返回原路径
        stem, suffix = filepath.stem, filepath.suffix  # 分离词干与后缀
        counter = 2  # 起始计数器
        while True:  # 循环查找可用文件名
            new_path = filepath.with_name(f"{stem}_{counter}{suffix}")  # 生成带序号的文件名
            if not new_path.exists():  # 该文件名不存在
                return new_path  # 返回可用路径
            counter += 1  # 计数器递增

    # ─── 递归页面收集 ───

    def _collect_pages(self, start_url: str, max_depth: int) -> list[str]:  # BFS 收集同域页面
        """BFS 收集同域下的页面 URL"""
        base_domain = urlparse(start_url).netloc  # 提取起始 URL 的域名
        visited: set[str] = set()  # 已访问 URL 集合
        queue: list[tuple[str, int]] = [(start_url, 1)]  # BFS 队列：(URL, 深度)
        pages: list[str] = []  # 收集到的页面 URL 列表

        while queue:  # 队列非空时继续
            url, depth = queue.pop(0)  # 弹出队首元素（FIFO）
            if url in visited:  # 已访问过
                continue  # 跳过
            visited.add(url)  # 标记为已访问
            pages.append(url)  # 加入页面列表

            if depth >= max_depth:  # 达到最大递归深度
                continue  # 不再展开子链接

            html = self._fetch_page(url)  # 获取页面 HTML
            if html is None:  # 获取失败
                continue  # 跳过

            soup = BeautifulSoup(html, "html.parser")  # 解析 HTML
            for a in soup.find_all("a", href=True):  # 遍历所有带 href 的 <a> 标签
                href = a["href"].strip()  # 获取并清理链接
                resolved = urljoin(url, href)  # 转换为绝对 URL
                parsed = urlparse(resolved)  # 解析 URL
                # 只收集同域链接，去掉 fragment
                if parsed.netloc == base_domain and resolved not in visited:  # 同域且未访问
                    clean = resolved.split("#")[0]  # 去掉 # 片段标识符
                    if clean not in visited:  # 清理后的 URL 未访问
                        queue.append((clean, depth + 1))  # 加入队列，深度 +1

        return pages  # 返回收集到的页面列表
