"""
workers/fact_check.py
=====================

卷三十五补丁3 · 事实较量 facade · 让 feasibility / trend / opportunity worker
能在跑 LLM 之前·先拉一遍真实搜索·把客观市场实证塞进 prompt。

为什么这个文件存在:
  - 卷三十五补丁2 给 LLM 加了"不许编事实"红线·但只是 prompt 提醒
  - BRO 卷三十五补丁3 要求"web_search 真扎根 · 做到 OK"
  - 这个文件是 A 路径的实现 —— LLM 跑之前先 search · 把真实结果塞 prompt

设计:
  - 复用 agent_tools/web_search.py 的 _run() (DuckDuckGo HTML · 免费)
  - search 失败 / 0 结果 时优雅退化 · 返回"信源不足"提示
  - 默认拉 5 条 · 单条 snippet 截 280 字 · 总 prompt 段 < 2000 字
  - 失败不阻塞 LLM · 工程红线
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from agent_tools.web_search import _DDGResultParser, SEARCH_URL, USER_AGENT, MAX_LIMIT


logger = logging.getLogger("opus.fact_check")


def search_for_evidence(
    query: str,
    *,
    limit: int = 5,
) -> dict:
    """跑一次 web_search · 返回结构化结果 · 喂 worker

    Returns:
      {
        "ok": True/False,
        "query": "...",
        "results": [{"title": "...", "url": "...", "snippet": "..."}],
        "error": "...",  # ok=False 时有
      }
    """
    query = (query or "").strip()
    if not query:
        return {"ok": False, "query": query, "results": [], "error": "empty query"}

    limit = max(1, min(int(limit or 5), MAX_LIMIT))

    try:
        import httpx
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
    except Exception as e:
        logger.warning("fact_check network error · q=%r · %r", query, e)
        return {"ok": False, "query": query, "results": [], "error": f"network: {e!r}"}

    if resp.status_code != 200:
        return {
            "ok": False, "query": query, "results": [],
            "error": f"http {resp.status_code} (DDG anti-bot 可能·建议换查询)",
        }

    parser = _DDGResultParser()
    try:
        parser.feed(resp.text)
        parser.close()
    except Exception as e:
        return {"ok": False, "query": query, "results": [], "error": f"parse: {e!r}"}

    results = [r for r in parser.results if r.get("url") and r.get("title")][:limit]
    return {"ok": True, "query": query, "results": results}


def render_evidence_block(
    evidence: dict,
    *,
    title: str = "市场实证 · web_search 拉的真实信源",
) -> str:
    """把 search 结果渲染成 prompt 用的 markdown 段

    LLM 看到这段 · 应该 cite 这些真实信源 · 不再凭空编市场细节。
    """
    if not evidence or not evidence.get("ok"):
        err = (evidence or {}).get("error") or "未知"
        return (
            f"## {title}\n\n"
            f"(搜索失败 · {err} · LLM 请明确标注「客观信源不足·依靠 prompt 上下文判断」)"
        )

    results = evidence.get("results") or []
    if not results:
        return (
            f"## {title}\n\n"
            f"(查询 `{evidence.get('query', '?')}` 0 结果 · 可能这件事真没什么市场公开讨论)"
        )

    q = evidence.get("query", "?")
    lines = [
        f"## {title}",
        "",
        f"基于查询 `{q}` · DuckDuckGo 返回 {len(results)} 条公开信源·**这些是真实的·"
        f"LLM 写「市场已有 X」时必须 cite 这里的具体条目**：",
        "",
    ]
    for i, r in enumerate(results, start=1):
        title_t = (r.get("title") or "").strip()
        url_t = (r.get("url") or "").strip()
        snippet_t = (r.get("snippet") or "").strip()
        if len(snippet_t) > 280:
            snippet_t = snippet_t[:280] + "..."
        lines.append(f"**[{i}] {title_t}**")
        lines.append(f"- URL: {url_t}")
        if snippet_t:
            lines.append(f"- 摘要: {snippet_t}")
        lines.append("")
    lines.append(
        "**写 summary 时**: 引用具体编号 (如「据[2]报道」) · 不要拼凑数字 · 不要编项目名。"
    )
    return "\n".join(lines).strip()


# ─────────────────────────────────────────────────────────────────────
# 给 worker 用的高层 API · 一行调
# ─────────────────────────────────────────────────────────────────────
def fetch_evidence_for_opp(opp: dict, *, limit: int = 5) -> dict:
    """根据机会卡里的 title / summary 构造查询·返回 evidence dict"""
    title = (opp.get("title") or "").strip()
    summary = (opp.get("summary") or "").strip()
    # 简单去除符号·组合查询
    query = title
    if summary and len(query) < 30:
        query = f"{title} {summary[:50]}"
    return search_for_evidence(query, limit=limit)


def fetch_evidence_for_topic(topic: str, *, limit: int = 5) -> dict:
    """主题字符串直接查"""
    return search_for_evidence(topic, limit=limit)


# ─────────────────────────────────────────────────────────────────────
# claim 级 verify · 给"佐证"按钮用
# ─────────────────────────────────────────────────────────────────────
_NUMBER_RE = re.compile(r"\d+[\.\d%kmKM]*")


def verify_claim(claim: str, *, limit: int = 5) -> dict:
    """验证一条具体的 claim · 比如「ChatGPT 月活 1000 万」

    返回:
      {
        "ok": True/False,
        "claim": "...",
        "query": "...",
        "results": [...],
        "verdict": "supported|partial|unsupported|inconclusive",
        "notes": "供 UI 显示的人类可读简评",
      }
    """
    claim = (claim or "").strip()
    if not claim:
        return {
            "ok": False, "claim": claim, "query": "",
            "results": [], "verdict": "inconclusive",
            "notes": "claim 为空·没法验证",
        }

    # 这里 query 暂时直接用 claim · 后续可以加 LLM 改写 query
    ev = search_for_evidence(claim, limit=limit)
    if not ev.get("ok"):
        return {
            "ok": False, "claim": claim, "query": claim,
            "results": [], "verdict": "inconclusive",
            "notes": f"搜索失败·{ev.get('error', '?')}",
        }

    results = ev.get("results") or []
    if not results:
        return {
            "ok": True, "claim": claim, "query": claim,
            "results": [], "verdict": "unsupported",
            "notes": "0 结果 · 这条 claim 在公开网上找不到佐证 · BRO 谨慎采信",
        }

    # 朴素判定 · 抽 claim 里的数字 · 看有没有在任何结果的 snippet/title 出现
    numbers = _NUMBER_RE.findall(claim)
    has_match = False
    for r in results:
        haystack = (r.get("title", "") + " " + r.get("snippet", "")).lower()
        for n in numbers:
            if n.lower() in haystack:
                has_match = True
                break
        if has_match:
            break

    if numbers and has_match:
        verdict = "supported"
        notes = "搜索结果中找到匹配数字 · 较可信"
    elif numbers and not has_match:
        verdict = "partial"
        notes = "找到相关网页但数字未直接验证 · 需 BRO 看原文确认"
    else:
        verdict = "partial"
        notes = "找到相关网页·BRO 自行判断与 claim 的吻合度"

    return {
        "ok": True,
        "claim": claim,
        "query": claim,
        "results": results,
        "verdict": verdict,
        "notes": notes,
    }
