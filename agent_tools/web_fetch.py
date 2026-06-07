"""
agent_tools/web_fetch.py
========================

抓一个 URL，提取主体文字（去 script/style/导航/菜单），返回干净的纯文本。

设计：
  - 用 httpx 抓
  - 用 stdlib html.parser 提取（不引 BeautifulSoup——成本桅杆）
  - 返回 max_chars 截断（默认 8000，避免一次抓回 50MB 把 token 烧光）
  - AUTO 档——只读外网，无副作用

技术债 / v0.0.2：
  - 没有 readability-style 正文识别——纯靠"扔掉 script/style"，对 SPA / 重 JS 网站效果差
  - 不处理 PDF / 二进制
  - 想要更准的正文识别可以引 trafilatura，但 trafilatura 依赖巨大，先不引
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import httpx

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


DEFAULT_MAX_CHARS = 8000
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB hard cap

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

SKIP_TAGS = {"script", "style", "noscript", "iframe", "svg", "form", "nav", "footer", "aside"}


class _TextExtractor(HTMLParser):
    """提取正文：跳过 script/style/nav/footer 等噪声标签。保留 title。"""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self.title: str = ""

    def handle_starttag(self, tag: str, _attrs):
        if tag == "title":
            self._in_title = True
        elif tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag in ("br", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "div"):
            self._chunks.append("\n")

    def handle_endtag(self, tag: str):
        if tag == "title":
            self._in_title = False
        elif tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in ("p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "div"):
            self._chunks.append("\n")

    def handle_data(self, data: str):
        if self._skip_depth > 0:
            return
        if self._in_title:
            self.title += data
            return
        self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n[ \t]+", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _summarize(args: dict) -> str:
    url = (args.get("url") or "").strip()
    return f"web_fetch  url={url}"


def _run(args: dict) -> ToolResult:
    url = (args.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, output="", error="empty url")
    if not (url.startswith("http://") or url.startswith("https://")):
        return ToolResult(ok=False, output="", error=f"only http(s) urls allowed, got: {url!r}")

    max_chars = int(args.get("max_chars") or DEFAULT_MAX_CHARS)
    max_chars = max(500, min(max_chars, 50000))

    try:
        resp = httpx.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            },
            timeout=20.0,
            follow_redirects=True,
        )
    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"network error: {e!r}")

    if resp.status_code != 200:
        return ToolResult(
            ok=False, output="",
            error=f"HTTP {resp.status_code} from {resp.url}",
        )

    raw_bytes = resp.content
    if len(raw_bytes) > MAX_RESPONSE_BYTES:
        return ToolResult(
            ok=False, output="",
            error=f"response too large: {len(raw_bytes)} bytes (cap: {MAX_RESPONSE_BYTES})",
        )

    content_type = (resp.headers.get("content-type") or "").lower()

    if "html" not in content_type and not raw_bytes.strip().startswith(b"<"):
        try:
            text = raw_bytes.decode(resp.encoding or "utf-8", errors="replace")
        except Exception:
            text = raw_bytes.decode("utf-8", errors="replace")
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]
        out = (
            f"web_fetch · {url}\n"
            f"content-type: {content_type or 'unknown'}\n"
            f"size: {len(raw_bytes)} bytes\n"
            f"---\n{text}"
        )
        if truncated:
            out += f"\n\n[... truncated to {max_chars} chars ...]"
        return ToolResult(ok=True, output=out)

    extractor = _TextExtractor()
    try:
        extractor.feed(resp.text)
        extractor.close()
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"html parse error: {e!r}")

    text = extractor.text()
    title = extractor.title.strip()
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    out_lines = [
        f"web_fetch · {resp.url}",
    ]
    if title:
        out_lines.append(f"title: {title}")
    out_lines.append(f"size: {len(raw_bytes)} bytes  ·  extracted: {len(text)} chars")
    out_lines.append("---")
    out_lines.append(text)
    if truncated:
        out_lines.append(f"\n[... truncated to {max_chars} chars; pass max_chars to read more ...]")
    return ToolResult(ok=True, output="\n".join(out_lines))


SPEC = ToolSpec(
    name="web_fetch",
    description=(
        "Fetch a URL and extract the main text (strips script/style/nav/footer). "
        "Use this AFTER web_search to read the actual content of a result. "
        "Default returns first 8000 chars of extracted text—pass max_chars to get more "
        "(up to 50000). Only http(s) URLs allowed."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full URL to fetch (must start with http:// or https://)",
            },
            "max_chars": {
                "type": "integer",
                "description": "Max chars to return from extracted text (500-50000, default 8000)",
            },
        },
        "required": ["url"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
