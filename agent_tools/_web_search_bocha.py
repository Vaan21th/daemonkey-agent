"""博查 Web Search。不注册成工具。"""
from __future__ import annotations

import httpx

BOCHA_URL = "https://api.bochaai.com/v1/web-search"
TIMEOUT = 12.0


def _norm_date(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    return s.replace("T", " ")[:16]


def parse_bocha_payload(data: dict) -> list[dict]:
    if not isinstance(data, dict):
        return []
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    pages = inner.get("webPages") if isinstance(inner, dict) else None
    if not pages:
        pages = data.get("webPages") or {}
    rows = pages.get("value") if isinstance(pages, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        title = str(r.get("name") or r.get("title") or "").strip()
        url = str(r.get("url") or "").strip()
        if not title or not url:
            continue
        out.append({
            "title": title,
            "url": url,
            "snippet": str(r.get("snippet") or "").strip(),
            "summary": str(r.get("summary") or "").strip(),
            "site": str(r.get("siteName") or r.get("site") or "").strip(),
            "icon": str(r.get("siteIcon") or "").strip(),
            "date": _norm_date(str(r.get("datePublished") or r.get("dateLastCrawled") or "")),
        })
    return out


def search_bocha(query: str, limit: int, api_key: str) -> list[dict]:
    n = max(1, min(int(limit or 8), 10))
    resp = httpx.post(
        BOCHA_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"query": query, "summary": True, "count": n, "freshness": "noLimit"},
        timeout=TIMEOUT,
        follow_redirects=True,
    )
    if resp.status_code == 401:
        raise RuntimeError("key rejected")
    if resp.status_code == 402:
        raise RuntimeError("quota empty")
    if resp.status_code == 429:
        raise RuntimeError("rate limited")
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    data = resp.json()
    if isinstance(data, dict) and data.get("code") not in (None, 200, 0, "200"):
        raise RuntimeError(str(data.get("message") or data.get("code")))
    rows = parse_bocha_payload(data)
    if not rows:
        raise RuntimeError("0 results")
    return rows[:n]
