"""
agent_tools/web_search.py
=========================

Web 搜索工具（DuckDuckGo HTML，免 API key 版本）。

设计：
  - 调用 DuckDuckGo 的 HTML 端点（https://html.duckduckgo.com/html/）
  - 用 stdlib html.parser 解析（不引 BeautifulSoup——成本桅杆）
  - 默认返回 8 条结果（标题 / URL / 摘要）
  - AUTO 档——只读外网，无副作用

技术债 / v0.0.2 计划：
  - DuckDuckGo HTML 偶尔会返回 anti-bot 页，要带 retry + 真 UA
  - 想要更稳定可以接 Brave Search API（2000 次/月免费，要 key）
    或 Tavily API（专为 LLM agent 设计，要 key）
  - 现在的 v0.0.1 够用——验证 OPUS 能在本项目查网页这件事

用法：
  args = {"query": "MCP protocol 2026", "limit": 5}
"""

from __future__ import annotations

import urllib.parse
from html.parser import HTMLParser

import httpx

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


SEARCH_URL = "https://html.duckduckgo.com/html/"
DEFAULT_LIMIT = 8
MAX_LIMIT = 20

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class _DDGResultParser(HTMLParser):
    """
    极简解析器——只抓 DuckDuckGo HTML 端的三个关键 class：
      a.result__a            标题 + 链接
      a.result__snippet      摘要
    """

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_title_a = False
        self._in_snippet_a = False
        self._cur: dict[str, str] = {}
        self._capture_chars: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag != "a":
            return
        cls = dict(attrs).get("class", "") or ""
        href = dict(attrs).get("href", "") or ""

        if "result__a" in cls:
            self._flush_pending_text()
            if self._cur:
                self.results.append(self._cur)
            self._cur = {"title": "", "url": self._unwrap_ddg_redirect(href), "snippet": ""}
            self._in_title_a = True
            self._capture_chars = []

        elif "result__snippet" in cls:
            self._flush_pending_text()
            self._in_snippet_a = True
            self._capture_chars = []

    def handle_endtag(self, tag: str):
        if tag != "a":
            return
        if self._in_title_a:
            self._cur["title"] = "".join(self._capture_chars).strip()
            self._in_title_a = False
            self._capture_chars = []
        elif self._in_snippet_a:
            self._cur["snippet"] = "".join(self._capture_chars).strip()
            self._in_snippet_a = False
            self._capture_chars = []

    def handle_data(self, data: str):
        if self._in_title_a or self._in_snippet_a:
            self._capture_chars.append(data)

    def close(self):
        super().close()
        self._flush_pending_text()
        if self._cur and self._cur not in self.results:
            self.results.append(self._cur)

    def _flush_pending_text(self):
        if self._in_title_a and self._cur:
            self._cur["title"] = "".join(self._capture_chars).strip()
        elif self._in_snippet_a and self._cur:
            self._cur["snippet"] = "".join(self._capture_chars).strip()

    @staticmethod
    def _unwrap_ddg_redirect(href: str) -> str:
        """DuckDuckGo 返回的链接是 //duckduckgo.com/l/?uddg=<encoded_real_url>。"""
        if not href:
            return ""
        if "uddg=" in href:
            try:
                qs = href.split("?", 1)[1]
                params = urllib.parse.parse_qs(qs)
                real = params.get("uddg", [""])[0]
                if real:
                    return urllib.parse.unquote(real)
            except Exception:
                pass
        if href.startswith("//"):
            return "https:" + href
        return href


def _summarize(args: dict) -> str:
    q = (args.get("query") or "").strip()
    limit = args.get("limit", DEFAULT_LIMIT)
    return f"web_search  query={q!r}  limit={limit}"


def _run(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, output="", error="empty query")

    limit = int(args.get("limit") or DEFAULT_LIMIT)
    limit = max(1, min(limit, MAX_LIMIT))

    try:
        resp = httpx.post(
            SEARCH_URL,
            data={"q": query},
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            },
            timeout=15.0,
            follow_redirects=True,
        )
    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"network error: {e!r}")

    if resp.status_code != 200:
        return ToolResult(
            ok=False, output="",
            error=f"DuckDuckGo HTTP {resp.status_code} (anti-bot? try later or pick a different query)",
        )

    parser = _DDGResultParser()
    try:
        parser.feed(resp.text)
        parser.close()
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"parse error: {e!r}")

    results = [r for r in parser.results if r.get("url") and r.get("title")][:limit]
    if not results:
        return ToolResult(
            ok=True,
            output=f"web_search: 0 results for {query!r} (DuckDuckGo HTML 可能返回了反爬页)",
        )

    lines = [f"web_search · {query!r} · {len(results)} results", ""]
    for i, r in enumerate(results, start=1):
        lines.append(f"[{i}] {r['title']}")
        lines.append(f"    {r['url']}")
        snippet = r.get("snippet", "")
        if snippet:
            lines.append(f"    {snippet[:280]}")
        lines.append("")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="web_search",
    description=(
        "Search the web via DuckDuckGo (HTML endpoint, no API key required). "
        "Returns a list of {title, url, snippet} for the query. Use this to find sources "
        "before deciding what URLs to fetch with web_fetch. "
        "Note: DuckDuckGo HTML may occasionally return anti-bot pages—if you get 0 results, "
        "try rephrasing or wait a moment."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query (English usually returns more results than Chinese)",
            },
            "limit": {
                "type": "integer",
                "description": f"Max results (1-{MAX_LIMIT}, default {DEFAULT_LIMIT})",
            },
        },
        "required": ["query"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
