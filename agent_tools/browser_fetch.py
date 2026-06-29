"""
agent_tools/browser_fetch.py
============================

OPUS 用浏览器抓需要 JS 渲染 / 需要登录才能看的网页。

两种工作模式（自动选）：

  模式 A · CDP attach（首选，需 BRO 一次性配置）
    BRO 的 Edge 启动时加 --remote-debugging-port=9222
    OPUS 用 Playwright 的 connect_over_cdp 直接 attach 到 BRO 正在用的 Edge 实例
    →  共享所有 cookies / sessions / 登录态
    →  能访问公司内网 / 微信公众号原文 / 付费墙等任何 BRO 自己能看的页面

  模式 B · 独立 profile（fallback，无配置成本）
    起一个独立的 Playwright Edge 实例，没有 BRO 的 cookies
    能跑 JS、能渲染 SPA，但访问需登录的页面会撞登录墙
    比 web_fetch 强（能跑 JS），比模式 A 弱（没登录态）

为什么不直接复制 BRO Edge cookies？
  - Edge 在跑时用 OS share-deny 锁住 cookies SQLite
  - sqlite3 immutable=1 也打不开
  - 用 Backup API 需要 admin / SeBackupPrivilege
  - BRO 26 个 Edge 进程开着不可能关——所以走 CDP

成本：
  - 模式 A：连接快（< 1s），共享 BRO 已开的 page，零启动成本
  - 模式 B：每次启动 3-5s，不复用

风险：
  - 模式 A：OPUS 能开新 page、能浏览任何 BRO 能浏览的页面
    → 这就是为什么本工具是 CONFIRM 档
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool
from ._browser import CDP_URL, cdp_available, ensure_cdp


PROJECT_ROOT = Path(__file__).resolve().parent.parent

PW_PROFILE = PROJECT_ROOT / "sessions" / "browser_profile_standalone"

DEFAULT_MAX_CHARS = 8000
DEFAULT_WAIT_SECONDS = 3
SKIP_TAGS = {"script", "style", "noscript", "iframe", "svg", "form", "nav", "footer", "aside"}


class _TextExtractor(HTMLParser):
    """提取主体文字——和 web_fetch 同源逻辑。"""

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


def _fetch_via_cdp(url: str, wait_seconds: int) -> tuple[bool, str, str, str]:
    """用 CDP attach 到 BRO 现有 Edge 实例。返回 (ok, html, title, final_url) 或 (False, error_msg, '', '')。"""
    try:
        from playwright.sync_api import sync_playwright as _sp
    except ImportError:
        try:
            from playwright.sync_api import sync_playwright as _sp
        except ImportError:
            return False, "playwright not installed", "", ""

    try:
        with _sp() as p:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(wait_seconds * 1000)
                final_url = page.url
                title = page.title() or ""
                html = page.content()
            finally:
                try:
                    page.close()
                except Exception:
                    pass
            return True, html, title, final_url
    except Exception as e:
        return False, f"CDP fetch failed: {type(e).__name__}: {e}", "", ""


def _fetch_via_standalone(url: str, wait_seconds: int, visible: bool) -> tuple[bool, str, str, str]:
    """启动独立 Playwright Edge profile——没 BRO 的登录态，但能跑 JS。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "playwright not installed", "", ""

    PW_PROFILE.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            try:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=str(PW_PROFILE),
                    channel="msedge",
                    headless=not visible,
                    args=["--disable-blink-features=AutomationControlled"],
                )
            except Exception as e:
                return False, (
                    f"failed to launch standalone Edge: {type(e).__name__}: {e}"
                ), "", ""

            try:
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(wait_seconds * 1000)
                final_url = page.url
                title = page.title() or ""
                html = page.content()
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
            return True, html, title, final_url
    except Exception as e:
        return False, f"standalone fetch error: {type(e).__name__}: {e}", "", ""


def _summarize(args: dict) -> str:
    url = (args.get("url") or "").strip()
    mode = (args.get("mode") or "auto").lower()
    visible = bool(args.get("visible", False))
    return f"browser_fetch  url={url}  mode={mode}{'  (visible)' if visible else ''}"


def _run(args: dict) -> ToolResult:
    url = (args.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, output="", error="empty url")
    if not (url.startswith("http://") or url.startswith("https://")):
        return ToolResult(ok=False, output="", error=f"only http(s) urls allowed, got: {url!r}")

    wait_seconds = int(args.get("wait_seconds") or DEFAULT_WAIT_SECONDS)
    wait_seconds = max(1, min(wait_seconds, 30))
    max_chars = int(args.get("max_chars") or DEFAULT_MAX_CHARS)
    max_chars = max(500, min(max_chars, 50000))
    visible = bool(args.get("visible", False))
    mode = (args.get("mode") or "auto").lower()

    chosen_mode = ""
    if mode == "cdp":
        # 显式要 cdp → 自动拉起 daemon 专属 Edge（独立 profile，不碰用户主浏览器）
        if not ensure_cdp(launch=True):
            return ToolResult(
                ok=False, output="",
                error=(
                    f"CDP requested but daemon Edge not up on {CDP_URL}. "
                    f"通常是没装 Edge / 装在非标准路径；或先触发一次 browser_act 让它拉起专属 Edge。"
                ),
            )
        chosen_mode = "cdp"
    elif mode == "standalone":
        chosen_mode = "standalone"
    else:
        # auto：专属 Edge 已在就 attach（眼手共用同一实例），否则走轻量 standalone
        chosen_mode = "cdp" if cdp_available() else "standalone"

    if chosen_mode == "cdp":
        ok, payload, title, final_url = _fetch_via_cdp(url, wait_seconds)
    else:
        ok, payload, title, final_url = _fetch_via_standalone(url, wait_seconds, visible)

    if not ok:
        return ToolResult(ok=False, output="", error=f"[{chosen_mode}] {payload}")

    extractor = _TextExtractor()
    try:
        extractor.feed(payload)
        extractor.close()
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"html parse error: {e!r}")

    text = extractor.text()
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    from identity import localize_narration as _ln
    out_lines = [
        f"browser_fetch · {final_url}",
        # 只本地化这条 meta 行(BRO→主人名)·正文 text 是透传网页内容·不动
        _ln(f"mode: {chosen_mode}{' (dedicated Edge · its own login)' if chosen_mode == 'cdp' else ' (no login state)'}"),
    ]
    if title:
        out_lines.append(f"title: {title}")
    out_lines.append(f"extracted: {len(text)} chars")
    out_lines.append("---")
    out_lines.append(text)
    if truncated:
        out_lines.append(f"\n[... truncated to {max_chars} chars ...]")

    return ToolResult(ok=True, output="\n".join(out_lines))


SPEC = ToolSpec(
    name="browser_fetch",
    description=(
        "Fetch a URL using a real browser (Edge via Playwright). Two modes:\n"
        "  - 'cdp' (preferred): auto-launch & attach the daemon's DEDICATED Edge (own profile, "
        "isolated from the user's daily browser). Login once per site in that window; persists.\n"
        "  - 'standalone': launch independent headless Edge, no login state but full JS rendering.\n"
        "  - 'auto' (default): attach the dedicated Edge if it's already up, else standalone.\n"
        "Use this for: pages requiring login, JS-heavy SPAs, anywhere web_fetch returned a wall. "
        "Slower than web_fetch (1-5s) — prefer web_fetch for static content."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL to fetch (http(s) only)"},
            "mode": {
                "type": "string",
                "enum": ["auto", "cdp", "standalone"],
                "description": "auto (default) | cdp (use BRO's Edge cookies) | standalone (no login)",
            },
            "wait_seconds": {
                "type": "integer",
                "description": "Seconds to wait after load for JS render (1-30, default 3)",
            },
            "max_chars": {
                "type": "integer",
                "description": "Max chars of extracted text (500-50000, default 8000)",
            },
            "visible": {
                "type": "boolean",
                "description": "If true and using standalone mode, open visible Edge window",
            },
        },
        "required": ["url"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
