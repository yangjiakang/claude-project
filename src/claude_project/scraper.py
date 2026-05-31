"""网页图片爬取器 —— 从指定 URL 抓取并下载图片"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

IMAGE_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "image/svg+xml", "image/bmp", "image/tiff", "image/x-icon",
    "image/vnd.microsoft.icon",
}

EXTENSION_MAP = {
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


@dataclass
class ScrapeConfig:
    """爬取配置"""
    url: str
    output_dir: Path = Path("images")
    max_images: int = 0          # 0 = 不限制
    extensions: set = field(default_factory=set)  # 空 = 不限制
    recursive: bool = False
    max_depth: int = 1
    timeout: int = 30
    user_agent: str = DEFAULT_USER_AGENT


class ImageScraper:
    """网页图片爬取器"""

    def __init__(self, config: ScrapeConfig):
        self.config = config
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self._seen_urls: set[str] = set()
        self._downloaded_names: set[str] = set()
        self._session = requests.Session()
        self._session.headers["User-Agent"] = self.config.user_agent

    # ─── 公开接口 ───

    def scrape(self) -> dict:
        """主流程：爬取图片，返回统计字典"""
        result = {
            "downloaded": 0,
            "skipped": 0,
            "errors": 0,
            "pages_visited": 0,
        }

        if self.config.recursive and self.config.max_depth > 1:
            page_urls = self._collect_pages(
                self.config.url, self.config.max_depth
            )
        else:
            page_urls = [self.config.url]

        result["pages_visited"] = len(page_urls)
        all_image_urls: list[str] = []

        for page_url in page_urls:
            html = self._fetch_page(page_url)
            if html is None:
                continue
            img_urls = self._extract_image_urls(html)
            for u in img_urls:
                resolved = self._resolve_url(page_url, u)
                if resolved and resolved not in self._seen_urls:
                    self._seen_urls.add(resolved)
                    all_image_urls.append(resolved)

        total = len(all_image_urls)
        if total == 0:
            print("未找到任何图片。")
            return result

        if self.config.extensions:
            filtered = [
                u for u in all_image_urls
                if self._match_extension(u)
            ]
            result["skipped"] += len(all_image_urls) - len(filtered)
            all_image_urls = filtered

        if self.config.max_images > 0:
            all_image_urls = all_image_urls[:self.config.max_images]

        total = len(all_image_urls)
        print(f"找到 {total} 张图片，开始下载...\n")

        for idx, url in enumerate(all_image_urls, 1):
            if self.config.max_images > 0 and result["downloaded"] >= self.config.max_images:
                break

            success, msg = self._download_one(url, idx, total)
            if success:
                result["downloaded"] += 1
                print(f"  [{idx}/{total}] ✅ {msg}")
            elif "跳过" in msg:
                result["skipped"] += 1
                print(f"  [{idx}/{total}] ⏭️  {msg}")
            else:
                result["errors"] += 1
                print(f"  [{idx}/{total}] ❌ {msg}", file=sys.stderr)

        return result

    # ─── 页面获取 ───

    def _fetch_page(self, url: str) -> str | None:
        """GET 请求获取页面 HTML"""
        try:
            resp = self._session.get(url, timeout=self.config.timeout)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException as e:
            print(f"  ⚠️  无法访问页面 {url}: {e}", file=sys.stderr)
            return None

    # ─── 图片 URL 提取 ───

    def _extract_image_urls(self, html: str) -> list[str]:
        """从 HTML 中提取所有图片 URL（含懒加载属性）"""
        soup = BeautifulSoup(html, "html.parser")
        urls: list[str] = []

        # 1. <img> 标签
        for img in soup.find_all("img"):
            url = self._pick_image_url(img)
            if url:
                urls.append(url)

        # 2. <picture> 内的 <source> 标签
        for picture in soup.find_all("picture"):
            for source in picture.find_all("source"):
                url = self._pick_image_url(source)
                if url:
                    urls.append(url)

        # 3. <link rel="icon"> / <link rel="apple-touch-icon">
        for link in soup.find_all("link"):
            rel = link.get("rel", [])
            if isinstance(rel, str):
                rel = [rel]
            rel_lower = [r.lower() for r in rel]
            if any(r in rel_lower for r in ("icon", "apple-touch-icon", "apple-touch-icon-precomposed")):
                href = link.get("href", "")
                if href:
                    urls.append(href)

        # 4. <meta> og:image / twitter:image
        for meta in soup.find_all("meta"):
            prop = meta.get("property", "").lower()
            name = meta.get("name", "").lower()
            content = meta.get("content", "")
            if content and ("og:image" in prop or "twitter:image" in name):
                urls.append(content)

        # 5. 背景图: style 属性中的 url(...)
        for tag in soup.find_all(style=True):
            style = tag.get("style", "")
            bg_urls = re.findall(r'url\(["\']?([^)"\']+)["\']?\)', style)
            urls.extend(bg_urls)

        return urls

    def _pick_image_url(self, tag) -> str | None:
        """从单个 tag 中按优先级提取图片 URL"""
        # 懒加载属性优先
        for attr in ("data-src", "data-lazy-src", "data-original"):
            val = tag.get(attr, "")
            if val and not val.startswith("data:"):
                return val.strip()

        # data-srcset — 取第一个候选项
        srcset = tag.get("data-srcset", "")
        if srcset:
            first = self._first_srcset_candidate(srcset)
            if first:
                return first

        # src
        src = tag.get("src", "")
        if src and not src.startswith("data:"):
            return src.strip()

        # srcset
        srcset = tag.get("srcset", "")
        if srcset:
            first = self._first_srcset_candidate(srcset)
            if first:
                return first

        return None

    @staticmethod
    def _first_srcset_candidate(srcset: str) -> str | None:
        """从 srcset 中提取第一个 URL 候选项"""
        parts = srcset.split(",")
        if parts:
            first = parts[0].strip()
            # 格式: "url 1x" 或 "url 100w"
            candidate = first.split(" ")[0].strip()
            if candidate:
                return candidate
        return None

    # ─── URL 处理 ───

    def _resolve_url(self, base_url: str, img_url: str) -> str | None:
        """将相对 URL 转换为绝对 URL"""
        try:
            resolved = urljoin(base_url, img_url)
            # 过滤明显的非图片 URL
            parsed = urlparse(resolved)
            if not parsed.scheme or not parsed.netloc:
                return None
            return resolved
        except ValueError:
            return None

    def _match_extension(self, url: str) -> bool:
        """检查 URL 是否匹配配置的扩展名过滤"""
        if not self.config.extensions:
            return True
        path = urlparse(url).path.lower()
        if not path:
            return True  # 无法判断则不排除
        return any(path.endswith(ext.lower()) for ext in self.config.extensions)

    # ─── 图片下载 ───

    def _download_one(self, url: str, index: int, total: int) -> tuple[bool, str]:
        """下载单张图片，返回 (成功, 消息)"""
        try:
            resp = self._session.get(url, timeout=self.config.timeout, stream=True)
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()

            # 检查是否是图片
            if content_type and content_type not in IMAGE_CONTENT_TYPES:
                # 非图片但允许保存（可能是没有 Content-Type 头的图片）
                pass

            filename = self._safe_filename(url, index, content_type)
            filepath = self.config.output_dir / filename

            # 避免覆盖：如果已存在则加序号
            filepath = self._ensure_unique(filepath)

            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            return True, filepath.name

        except requests.RequestException as e:
            return False, f"{url}: 网络错误 - {e}"
        except OSError as e:
            return False, f"{url}: 写入失败 - {e}"

    def _safe_filename(self, url: str, index: int, content_type: str = "") -> str:
        """从 URL 生成安全的文件名"""
        parsed = urlparse(url)
        path = parsed.path or ""
        filename = Path(path).name

        # 如果 URL 路径没有合适的文件名
        if not filename or filename in ("/", ""):
            filename = f"image_{index}"

        # 去除查询参数残留和非法字符
        name, ext = Path(filename).stem, Path(filename).suffix
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        if not name:
            name = f"image_{index}"

        # 确保有正确的扩展名
        if not ext or len(ext) > 6:
            ext = EXTENSION_MAP.get(content_type, ".jpg")

        return f"{name}{ext}"

    def _ensure_unique(self, filepath: Path) -> Path:
        """如果文件已存在，生成不重复的文件名"""
        if not filepath.exists():
            return filepath
        stem, suffix = filepath.stem, filepath.suffix
        counter = 2
        while True:
            new_path = filepath.with_name(f"{stem}_{counter}{suffix}")
            if not new_path.exists():
                return new_path
            counter += 1

    # ─── 递归页面收集 ───

    def _collect_pages(self, start_url: str, max_depth: int) -> list[str]:
        """BFS 收集同域下的页面 URL"""
        base_domain = urlparse(start_url).netloc
        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(start_url, 1)]
        pages: list[str] = []

        while queue:
            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            pages.append(url)

            if depth >= max_depth:
                continue

            html = self._fetch_page(url)
            if html is None:
                continue

            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                resolved = urljoin(url, href)
                parsed = urlparse(resolved)
                # 只收集同域链接，去掉 fragment
                if parsed.netloc == base_domain and resolved not in visited:
                    clean = resolved.split("#")[0]
                    if clean not in visited:
                        queue.append((clean, depth + 1))

        return pages
