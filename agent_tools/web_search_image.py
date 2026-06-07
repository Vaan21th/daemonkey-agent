"""
agent_tools/web_search_image.py
================================

按 query 搜图片 · 返回 markdown 块给 LLM 直接贴进回答 · 用户 在 chat 里看缩略图 + 点进原始页。

wish-4f25c4a1 (用户 2026-05-25 19:36) — daemon OPUS 思考链:
  「我目前的工具链里确实没有直接的搜图片→返回 URL 工具」
用户: 「所以你没别的办法能拿到搜索引擎的图吗?」

设计:
  - backend: 百度图片 acjson 公开 endpoint (https://image.baidu.com/search/acjson)
  - 国内服务 · 中文友好 · 反爬弱 · query mismatch 几乎为零
  - 解析 JSON · 字段 thumbURL / replaceUrl[0].ObjURL / replaceUrl[0].FromURL / fromPageTitleEnc
  - 自动下载 thumbURL (百度 CDN 缩略图 ~30-100KB) 到 `data/workshop/outputs/searches/<hash>/<i>.jpg`
  - 走 wish-f3b4958e 的 /workshop/outputs/{filename:path} endpoint · chat.js 见 ![]() 自动渲染
  - 返回 markdown · 5 张缩略图 · 每张点进 source page

为什么用百度而不是 Bing/Google/DDG:
  - Bing image 反爬 · 没 cookie 时大量 query mismatch (实测 'ayumi hamasaki' → 'El Reno tornado')
  - DDG i.js endpoint 已 403 反爬升级
  - Google / Wikimedia / Yandex 国内网络不稳 (用户 在国内)
  - 百度图片 acjson 是浏览器 ajax 真实端点 · UA 伪装即可 · 无需 token

红线:
  - 只下载缩略图 (百度 CDN) 落 `data/workshop/outputs/searches/<hash>/` · 不下载原图
  - 来源页 URL 必须保留 (replaceUrl[0].FromURL) · 让 用户 能溯源
  - TIER_AUTO · 只搜公开图 · 没破坏性

已知边界:
  - replaceUrl 偶尔为空 (老结果) · fallback 跳过该 item
  - fromPageTitleEnc 含 # / 换行 · 不影响渲染
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import httpx

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


# ───────────────────────────── 常量 ─────────────────────────────

DEFAULT_MAX_RESULTS = 5
HARD_MAX_RESULTS = 12
BAIDU_ACJSON = "https://image.baidu.com/search/acjson"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

ROOT = Path(__file__).resolve().parent.parent
# 注：目录名不能以 `_` 开头 ( 用户 远程浏览器实测 · `_search/` 路径会裂图 ·
#     `searches/` 同样的子结构能正常加载 · 真根因未钉死但工程上规避).
SEARCH_OUTPUT_DIR = ROOT / "data" / "workshop" / "outputs" / "searches"


# ───────────────────────────── helpers ─────────────────────────────

def _query_hash(query: str) -> str:
    """query 哈希 · 当目录名 · 同 query 复用同目录避免重复下载"""
    h = hashlib.md5(query.encode("utf-8")).hexdigest()[:10]
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", query)[:24] or "q"
    return f"{safe}_{h}"


def _baidu_search(query: str, max_results: int) -> list[dict]:
    """调百度 acjson · 返候选列表 · 不下载图"""
    # rn 多拿一些 · 因为 replaceUrl 为空的会被丢
    rn = max(max_results * 2, 10)
    with httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://image.baidu.com/",
        },
        follow_redirects=True,
        timeout=15.0,
    ) as client:
        resp = client.get(
            BAIDU_ACJSON,
            params={
                "tn": "resultjson_com",
                "ipn": "rj",
                "ct": "201326592",
                "fp": "result",
                "queryWord": query,
                "cl": "2",
                "lm": "-1",
                "ie": "utf-8",
                "oe": "utf-8",
                "word": query,
                "pn": "0",
                "rn": str(rn),
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(f"百度 HTTP {resp.status_code}")

    try:
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"百度返回非 JSON: {e!r}")

    raw_items = data.get("data") or []
    items: list[dict] = []
    seen_thumbs: set[str] = set()
    for x in raw_items:
        if not x or not isinstance(x, dict):
            continue
        thumb = x.get("thumbURL") or ""
        if not thumb or thumb in seen_thumbs:
            continue
        seen_thumbs.add(thumb)

        # 优先取 replaceUrl[0] · 那是真实的原图 + 来源页
        # fallback · 用 fromURLHost 当 page (至少有个域名指向)
        ru = x.get("replaceUrl") or []
        if ru and isinstance(ru, list) and ru[0]:
            obj_url = ru[0].get("ObjURL") or ""
            from_url = ru[0].get("FromURL") or ""
        else:
            obj_url = ""
            from_url = ""
        if not from_url:
            host = x.get("fromURLHost") or ""
            from_url = f"https://{host}" if host else ""

        title = (x.get("fromPageTitleEnc") or "").replace("\n", " ").strip()
        items.append({
            "title": title,
            "page_url": from_url,
            "image_url": obj_url,
            "thumbnail_url": thumb,
            "width": x.get("width"),
            "height": x.get("height"),
        })
        if len(items) >= max_results:
            break
    return items


def _download_thumbnail(client: httpx.Client, url: str, dst: Path) -> bool:
    """下载缩略图到 dst · 已存在跳过 · 失败返 False"""
    if dst.exists() and dst.stat().st_size > 0:
        return True
    try:
        resp = client.get(url, timeout=15.0)
        if resp.status_code != 200:
            return False
        ct = (resp.headers.get("Content-Type") or "").lower()
        if "image" not in ct:
            return False
        dst.write_bytes(resp.content)
        return True
    except Exception:
        return False


def _summarize(args: dict) -> str:
    q = (args.get("query") or "").strip()
    n = args.get("max_results") or DEFAULT_MAX_RESULTS
    return f"web_search_image  query={q!r}  max_results={n}"


def _run(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, output="", error="empty query")

    max_results = int(args.get("max_results") or DEFAULT_MAX_RESULTS)
    max_results = max(1, min(max_results, HARD_MAX_RESULTS))

    try:
        items = _baidu_search(query, max_results)
    except Exception as e:
        return ToolResult(
            ok=False, output="",
            error=f"百度图片搜索失败: {e!r} (反爬升级? 网络问题? 退化方案: 写 web_fetch 拿图片页·或问 用户 申请 Brave Search API key)",
        )

    if not items:
        return ToolResult(
            ok=True,
            output=f"web_search_image: 0 results for {query!r} · 试换关键词更具体一些",
        )

    dirname = _query_hash(query)
    out_dir = SEARCH_OUTPUT_DIR / dirname
    out_dir.mkdir(parents=True, exist_ok=True)

    download_ok = 0
    with httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://image.baidu.com/",
        },
        follow_redirects=True,
        timeout=15.0,
    ) as client:
        for i, item in enumerate(items, start=1):
            local_name = f"{i:02d}.jpg"
            local_path = out_dir / local_name
            ok = _download_thumbnail(client, item["thumbnail_url"], local_path)
            if ok:
                # 用 file mtime 当 cache buster · 防浏览器对同 URL 的负缓存
                # (相同 query 复用同目录但 mtime 稳定时 url 仍稳定 · 浏览器命中正缓存)
                mtime = int(local_path.stat().st_mtime)
                item["local_url"] = f"/workshop/outputs/searches/{dirname}/{local_name}?v={mtime}"
                download_ok += 1
            else:
                item["local_url"] = None
            time.sleep(0.15)  # 简单限速 · 避免被百度限流

    # 输出 · 给 LLM 看的 markdown 块 · 直接贴进最终回答 · 用户 chat 框渲染
    lines = [
        f"web_search_image · query={query!r} · {len(items)} results · {download_ok}/{len(items)} thumbnails ok",
        "",
        "**使用方式** · 把下面 markdown 直接贴进最终回答 · 用户 chat 框会渲染缩略图:",
        "",
    ]
    for i, it in enumerate(items, start=1):
        title = (it["title"][:80] or "(无标题)").strip()
        page_url = it["page_url"]
        local_url = it["local_url"]
        size_hint = f" · {it.get('width')}x{it.get('height')}" if it.get("width") else ""
        if local_url:
            lines.append(f"[{i}] **{title}**{size_hint}")
            lines.append(f"![{title}]({local_url})")
        else:
            lines.append(f"[{i}] **{title}**{size_hint} (缩略图本地下载失败 · 用 CDN 直链)")
            lines.append(f"![{title}]({it['thumbnail_url']})")
        if page_url:
            lines.append(f"[来源页 {i}]({page_url})")
        lines.append("")
    if any(it.get("image_url") for it in items):
        lines.append("---")
        lines.append("原图链接 (LLM 内部参考 · 不要直接贴给 用户 · 缩略图够用):")
        for i, it in enumerate(items, start=1):
            if it.get("image_url"):
                lines.append(f"  [{i}] {it['image_url']}")

    return ToolResult(ok=True, output="\n".join(lines))


# ───────────────────────────── 注册 ─────────────────────────────

SPEC = ToolSpec(
    name="web_search_image",
    description=(
        "按 query 搜图片 · 返回缩略图本地链 + 来源页 URL · LLM 把返回的 markdown 块直接贴进最终回答 · "
        "用户 在 chat 看到嵌入的缩略图 · 点击进 source page 看上下文。\n\n"
        "**何时用**:\n"
        "  - 用户 让 OPUS 找某个人 / 地点 / 物品的照片 (滨崎步 / 樱花 / 故宫 / iPhone 16 等)\n"
        "  - 给 用户 找参考图 / inspiration / illustration\n"
        "  - 验证某个视觉概念 (logo / 截图 / 商品外观) 跟 用户 描述是否一致\n\n"
        "**红线**:\n"
        "  - 只下载缩略图 (百度 CDN · ~30-100KB) 落 `data/workshop/outputs/searches/<hash>/` · 不下载原图\n"
        "  - 来源页 URL 必须保留 · 让 用户 能溯源\n"
        "  - 直接把返回的 markdown 块贴进回答 · 不要拆字段重新拼\n\n"
        "**实战提示**:\n"
        "  - 用百度图片 backend · 中文 / 英文 / 中英混合都好使\n"
        "  - 中文 query 准 (滨崎步 → 真的滨崎步图)\n"
        "  - 长 query 比短 query 准 ('滨崎步 演唱会' 比 '滨崎步' 更精)\n"
        "  - 来源主要是抖音 / 微博 / 百度百科 / 摄影站 · 用户 点进去能看完整内容\n"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "图片搜索 query · 中英文都好使 · 加上下文词更准 (例如 '滨崎步 演唱会' 比 '滨崎步')",
            },
            "max_results": {
                "type": "integer",
                "description": f"最多返回多少张 (1-{HARD_MAX_RESULTS}, 默认 {DEFAULT_MAX_RESULTS})",
            },
        },
        "required": ["query"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
