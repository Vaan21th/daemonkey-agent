"""把搜索结果编成给模型的正文 + 给前端的 [[DK-HITS]] 卡。"""
from __future__ import annotations

import json
import re

HITS_RE = re.compile(r"[ \t]*\[\[DK-HITS\]\](.+?)[ \t]*(?:\n|$)")


def format_search_output(query: str, rows: list[dict], engine: str) -> str:
    lines = [f"web_search · {query!r} · {len(rows)} results (via {engine})", ""]
    items: list[dict[str, str]] = []
    for i, r in enumerate(rows or [], start=1):
        title = str(r.get("title") or "").strip()
        url = str(r.get("url") or "").strip()
        site = str(r.get("site") or "").strip()
        date = str(r.get("date") or "").strip()
        snippet = str(r.get("snippet") or "").strip()
        summary = str(r.get("summary") or "").strip()
        body = summary or snippet
        lines.append(f"[{i}] {title}")
        meta = " · ".join(x for x in (site, date) if x)
        if meta:
            lines.append(f"    {meta}")
        lines.append(f"    {url}")
        if body:
            lines.append(f"    {body[:500]}")
        lines.append("")
        items.append({
            "t": title[:160],
            "u": url[:500],
            "n": site[:80],
            "i": str(r.get("icon") or "")[:300],
            "d": date[:32],
            "s": (snippet or summary)[:180],
            "e": engine[:32],
        })
    payload = {"engine": engine, "items": items}
    lines.append("[[DK-HITS]]" + json.dumps(payload, ensure_ascii=False))
    return "\n".join(lines)


def strip_hits(text: str) -> tuple[str, list[dict]]:
    if not text:
        return "", []
    m = HITS_RE.search(text)
    if not m:
        return text, []
    clean = HITS_RE.sub("", text).rstrip() + "\n"
    try:
        data = json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return clean, []
    raw = data.get("items") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return clean, []
    engine = str((data.get("engine") if isinstance(data, dict) else "") or "")
    out: list[dict] = []
    for it in raw[:8]:
        if not isinstance(it, dict):
            continue
        url = str(it.get("u") or "").strip()
        title = str(it.get("t") or "").strip()
        if not url or not title:
            continue
        out.append({
            "title": title[:160],
            "url": url[:500],
            "site": str(it.get("n") or "")[:80],
            "icon": str(it.get("i") or "")[:300],
            "date": str(it.get("d") or "")[:32],
            "snippet": str(it.get("s") or "")[:180],
            "engine": str(it.get("e") or engine)[:32],
        })
    return clean, out
