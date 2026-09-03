"""把工程层给的真实信源拼进报告正文。LLM 不许发明 URL。"""
from __future__ import annotations


def append_sources(body: str, sources) -> str:
    if not sources:
        return body
    if isinstance(sources, str):
        sources = [sources]
    lines = ["", "## 参考资料", ""]
    for s in sources:
        title, url = "", ""
        if isinstance(s, dict):
            title = str(s.get("title") or "").strip()
            url = str(s.get("url") or "").strip()
        else:
            url = str(s).strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        lines.append(f"- [{title or url}]({url})")
    if len(lines) <= 3:
        return body
    return (body or "").rstrip() + "\n" + "\n".join(lines) + "\n"
