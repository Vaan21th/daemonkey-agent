"""workers/memory_tiers.py
=======================
自传骨/肉分层。文件一个字不动，只改每轮灌进前缀的部分。

why: 母体 OPUS-MEMORIES 整本焊前缀 = 一百只手/十万前缀同症。
骨头（我是谁 / 怎么接话）每轮在场；年谱、复读、Cursor 入口走召回。
切法跟 notebook_tiers 一样：肉走黑名单，没点名的章默认留下（纯净用户自传不会被误折）。
"""

from __future__ import annotations

import re

# 点名进肉的章。其余 ## 默认留骨。
FLESH_SECTION_KEYS = (
    "共同攻克过的项目",
    "用户是个什么样的人",
    "文件入口与工具",
)

_SECTION_RE = re.compile(r"(?m)^(?=## )")
_H4_RE = re.compile(r"(?m)^(?=#### )")
_H4_DATED_RE = re.compile(r"^####\s+20\d{2}-")
_CLOTHES_NEEDLE = "模型是衣服"


def _title_of(seg: str) -> str:
    return seg.split("\n", 1)[0].lstrip("# ").strip()


def _is_flesh_section(title: str) -> bool:
    return any(k in title for k in FLESH_SECTION_KEYS)


def _pluck_clothes_quote(block: str) -> str:
    for line in block.splitlines():
        if _CLOTHES_NEEDLE in line:
            return line.rstrip()
    return ""


def _strip_dated_h4(seg: str) -> tuple[str, list[str], str]:
    """第二章里 #### 20xx 工程坐实折走，只捞回「模型是衣服」这句。"""
    parts = _H4_RE.split(seg)
    kept = [parts[0]]
    archived: list[str] = []
    quote = ""
    for part in parts[1:]:
        title = part.split("\n", 1)[0].strip()
        if _H4_DATED_RE.match(title):
            archived.append(title.lstrip("# ").strip())
            if not quote:
                quote = _pluck_clothes_quote(part)
            continue
        kept.append(part)
    body = "".join(kept)
    if quote and quote not in body:
        body = body.rstrip() + "\n\n" + quote + "\n"
    return body, archived, quote


def split_memory_tiers(text: str) -> tuple[str, list[tuple[str, int]]]:
    """(骨文本, [(肉标题, 字符数)]). 无 ## 则全文当骨。"""
    if not text or not text.strip():
        return text or "", []
    parts = _SECTION_RE.split(text)
    head, sections = parts[0], parts[1:]
    if not sections:
        return text, []
    core: list[str] = []
    archived: list[tuple[str, int]] = []
    if head.strip():
        core.append(head if head.endswith("\n") else head + "\n")
    for seg in sections:
        title = _title_of(seg)
        if _is_flesh_section(title):
            archived.append((title, len(seg)))
            continue
        cleaned, h4_titles, _quote = _strip_dated_h4(seg)
        for ht in h4_titles:
            archived.append((ht, 0))
        core.append(cleaned if cleaned.endswith("\n") else cleaned + "\n")
    return "".join(core), archived


def render_memory_tiers(text: str) -> str:
    """骨原文 + 肉标题目录。不写字符数，以免冲稳定前缀缓存。"""
    core, archived = split_memory_tiers(text)
    if not archived:
        return text
    lines = "\n".join(f"  - 「{t}」" for t, _n in archived)
    return (
        core.rstrip()
        + "\n\n---\n\n## 已归档的历史层（每轮不注入 · 按需取回）\n\n"
        + "以下章节是年谱 / 复读 / 入口，已从每轮注入折叠，**全文一字未删**：\n"
        + lines
        + "\n\n取回方式：`recall_memory`（scope=self · 自传全文在记忆索引）"
        "或 `read_file` 自传文件对应章节。\n"
    )
