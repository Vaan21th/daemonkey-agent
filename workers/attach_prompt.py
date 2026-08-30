"""附件说明只喂模型，不进气泡 / jsonl 正文。"""
from __future__ import annotations

MARK = "[用户上传了"
SEP = "\n---\n"


def for_ui(content: str) -> str:
    text = content or ""
    head = text[:500]
    if MARK not in text[:80] and "路径 B ·" not in head and "竞速池 winner" not in head:
        return text
    idx = text.rfind(SEP)
    if idx >= 0:
        return text[idx + len(SEP) :].strip()
    if text.lstrip().startswith(MARK):
        return ""
    return text


def for_llm(content: str, meta: dict | None = None) -> str:
    text = content or ""
    prefix = ""
    if isinstance(meta, dict):
        prefix = str(meta.get("attach_prompt") or "")
    if prefix and MARK not in text[:80]:
        return prefix + text
    return text


def extract_prompt(content: str) -> str:
    text = content or ""
    if MARK not in text[:80]:
        return ""
    idx = text.rfind(SEP)
    if idx < 0:
        return text if text.lstrip().startswith(MARK) else ""
    return text[: idx + len(SEP)]
