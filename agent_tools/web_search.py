"""
agent_tools/web_search.py
=========================

Web 搜索工具（免 API key，多引擎自动降级）。

设计：
  - **Bing（cn.bing.com）为主引擎**——大陆可直连，全球也可用
  - **DuckDuckGo HTML 为兜底**——Bing 失败/0 结果时再试（大陆通常连不上，作冗余）
  - 用 stdlib html.parser 解析（不引 BeautifulSoup——成本桅杆）
  - 默认返回 8 条结果（标题 / URL / 摘要）
  - AUTO 档——只读外网，无副作用

为什么 Bing 优先：DuckDuckGo 的 html 端点在大陆被墙（连接超时），
若仍把它当主引擎，大陆用户每次搜索都先白等一个超时。Bing 大陆全球都通，
所以排在前面；DDG 留作兜底，给能访问它的环境多一层冗余。

用法：
  args = {"query": "MCP protocol 2026", "limit": 5}
"""

from __future__ import annotations

import base64
import urllib.parse
from html.parser import HTMLParser

import httpx

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


SEARCH_URL_BING = "https://cn.bing.com/search"
SEARCH_URL_DDG = "https://html.duckduckgo.com/html/"
DEFAULT_LIMIT = 8
MAX_LIMIT = 20
PER_ENGINE_TIMEOUT = 12.0

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ───────────────────────── DuckDuckGo 解析 ─────────────────────────

class _DDGResultParser(HTMLParser):
    """
    极简解析器——只抓 DuckDuckGo HTML 端的两个关键 class：
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


# ───────────────────────── Bing 解析 ─────────────────────────

def _unwrap_bing_redirect(href: str) -> str:
    """
    Bing 的结果链接常是 https://www.bing.com/ck/a?...&u=a1<base64url(real_url)>。
    能解就还原成真 URL，解不开就原样返回（点击仍会跳转到真地址）。
    """
    if not href:
        return ""
    if "bing.com/ck/a" in href and "u=" in href:
        try:
            qs = href.split("?", 1)[1]
            params = urllib.parse.parse_qs(qs)
            u = params.get("u", [""])[0]
            if u.startswith("a1"):
                b = u[2:]
                b += "=" * (-len(b) % 4)
                decoded = base64.urlsafe_b64decode(b).decode("utf-8", "replace")
                if decoded.startswith(("http://", "https://")):
                    return decoded
        except Exception:
            pass
    return href


class _BingResultParser(HTMLParser):
    """
    抓 Bing 搜索结果：每条结果在 <li class="b_algo"> 里，
      <h2><a href=...>标题</a></h2>  +  <p>摘要</p>
    """

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_algo = False
        self._in_h2 = False
        self._in_title_a = False
        self._in_p = False
        self._cur: dict[str, str] = {}
        self._chars: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        ad = dict(attrs)
        cls = (ad.get("class", "") or "").split()

        if tag == "li" and "b_algo" in cls:
            self._flush()
            self._cur = {"title": "", "url": "", "snippet": ""}
            self._in_algo = True
            return

        if not self._in_algo:
            return

        if tag == "h2":
            self._in_h2 = True
        elif tag == "a" and self._in_h2 and not self._cur.get("url"):
            self._in_title_a = True
            self._cur["url"] = _unwrap_bing_redirect(ad.get("href", "") or "")
            self._chars = []
        elif tag == "p" and not self._in_title_a and not self._cur.get("snippet"):
            self._in_p = True
            self._chars = []

    def handle_endtag(self, tag: str):
        if not self._in_algo:
            return
        if tag == "a" and self._in_title_a:
            self._cur["title"] = "".join(self._chars).strip()
            self._in_title_a = False
            self._chars = []
        elif tag == "h2":
            self._in_h2 = False
        elif tag == "p" and self._in_p:
            self._cur["snippet"] = "".join(self._chars).strip()
            self._in_p = False
            self._chars = []

    def handle_data(self, data: str):
        if self._in_title_a or self._in_p:
            self._chars.append(data)

    def _flush(self):
        if self._cur and self._cur.get("url") and self._cur.get("title"):
            self.results.append(self._cur)
        self._cur = {}
        self._in_h2 = self._in_title_a = self._in_p = False

    def close(self):
        super().close()
        self._flush()
        self._in_algo = False


# ───────────────────────── 引擎 ─────────────────────────

def _search_bing(query: str, limit: int) -> list[dict[str, str]]:
    resp = httpx.get(
        SEARCH_URL_BING,
        params={"q": query, "setlang": "zh-CN"},
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        timeout=PER_ENGINE_TIMEOUT,
        follow_redirects=True,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    parser = _BingResultParser()
    parser.feed(resp.text)
    parser.close()
    return [r for r in parser.results if r.get("url") and r.get("title")][:limit]


def _search_ddg(query: str, limit: int) -> list[dict[str, str]]:
    resp = httpx.post(
        SEARCH_URL_DDG,
        data={"q": query},
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        },
        timeout=PER_ENGINE_TIMEOUT,
        follow_redirects=True,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} (anti-bot?)")
    parser = _DDGResultParser()
    parser.feed(resp.text)
    parser.close()
    return [r for r in parser.results if r.get("url") and r.get("title")][:limit]


_ENGINES = (("Bing", _search_bing), ("DuckDuckGo", _search_ddg))


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

    attempts: list[str] = []
    for engine_name, fn in _ENGINES:
        try:
            results = fn(query, limit)
        except httpx.HTTPError as e:
            attempts.append(f"{engine_name}: network error {e!r}")
            continue
        except Exception as e:
            attempts.append(f"{engine_name}: {type(e).__name__}: {e}")
            continue
        if results:
            lines = [f"web_search · {query!r} · {len(results)} results (via {engine_name})", ""]
            for i, r in enumerate(results, start=1):
                lines.append(f"[{i}] {r['title']}")
                lines.append(f"    {r['url']}")
                snippet = r.get("snippet", "")
                if snippet:
                    lines.append(f"    {snippet[:280]}")
                lines.append("")
            return ToolResult(ok=True, output="\n".join(lines))
        attempts.append(f"{engine_name}: 0 results")

    return ToolResult(
        ok=False,
        output="",
        error="web_search 所有引擎都没拿到结果：" + " | ".join(attempts)
        + "（可换个说法重试，或用 web_fetch 直接抓已知 URL）",
    )


SPEC = ToolSpec(
    name="web_search",
    description=(
        "Search the web via Bing (cn.bing.com, accessible in mainland China) with a "
        "DuckDuckGo fallback. No API key required. Returns a list of {title, url, snippet} "
        "for the query. Use this to find sources before deciding what URLs to fetch with "
        "web_fetch. If you get 0 results, try rephrasing the query."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
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
