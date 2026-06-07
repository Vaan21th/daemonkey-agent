"""workers/studio_workshop.py

工作室出品工坊（卷二十六）——content / design / dev / docs 四个维度共享的
loader + 创建器。

------------------------------------------------------------
形态
------------------------------------------------------------

这 4 个维度本质同构：都是"OPUS 帮 BRO 产出的 markdown 文档"，只是触发场景不同：

    🎬 内容制作 (content) · 选题 / 口播稿 / 视频脚本 / 标题库
    🎨 产品设计 (design)  · spec / wireframe / 用户旅程 / 原型说明
    💻 产品开发 (dev)     · TODO 列表 / 项目笔记 / 周报 / repo 概览
    📄 文档撰写 (docs)    · 内部 wiki / FAQ / 操作手册

每个维度对应 `data/<domain>/*.md`——一个文件 = 一条产出。文件头 yaml-frontmatter
存元数据（kind/title/created_at）。

------------------------------------------------------------
API
------------------------------------------------------------

`load_workshop(domain)` — 列该维度所有产出
`create_workshop_item(domain, title, body, kind="")` — 落一份新文件
`workshop_meta(domain)` — 该维度的 icon/label/kinds 等元信息

下游：
- daemon_api.dashboard_cockpit / dashboard("/<domain>")
- agent_tools.draft_studio · OPUS 在对话里 NLP 触发
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "data"


WORKSHOP_META = {
    "content": {
        "label": "内容制作",
        "icon": "🎬",
        "dir": "content",
        "kinds": ["选题", "口播稿", "视频脚本", "标题库"],
        "empty_hint": (
            "还没产出 · 跟 OPUS 说「给我写一个 AI 创业的选题」"
            "或「来一份关于 X 的口播稿」"
        ),
        "description": "选题 / 口播稿 / 视频脚本——做内容出货的弹药",
    },
    "design": {
        "label": "产品设计",
        "icon": "🎨",
        "dir": "design",
        "kinds": ["spec", "wireframe", "用户旅程", "原型说明"],
        "empty_hint": (
            "还没产出 · 跟 OPUS 说「出个 X 产品的 spec」"
            "或「画一下 Y 用户的旅程」"
        ),
        "description": "spec / wireframe / 用户旅程——把「想做的产品」落成文",
    },
    "dev": {
        "label": "产品开发",
        "icon": "💻",
        "dir": "dev",
        "kinds": ["TODO", "项目笔记", "周报", "技术调研"],
        "empty_hint": (
            "还没产出 · 跟 OPUS 说「列一下 X 项目的 TODO」"
            "或「写一份 Y 技术调研」"
        ),
        "description": "TODO / 项目笔记 / 周报——产品开发过程的 notebook",
    },
    "docs": {
        "label": "文档撰写",
        "icon": "📄",
        "dir": "docs",
        "kinds": ["FAQ", "wiki", "操作手册", "API 文档"],
        "empty_hint": (
            "还没产出 · 跟 OPUS 说「写一条关于 X 的 FAQ」"
            "或「整理一份 Y 的操作手册」"
        ),
        "description": "FAQ / wiki / 操作手册——内部知识库 + 用户文档",
    },
}


# ──────────────────────────────────────────────────────────
# 公共入口
# ──────────────────────────────────────────────────────────

def workshop_meta(domain: str) -> dict:
    """该维度的元信息 · 找不到抛 ValueError"""
    if domain not in WORKSHOP_META:
        raise ValueError(f"unknown workshop domain: {domain}")
    return dict(WORKSHOP_META[domain])


def load_workshop(domain: str, *, max_items: int = 60) -> dict:
    """读该维度的所有 markdown 产出 · 时间倒序

    Returns:
        {
            "domain": "content",
            "label": "...",
            "icon": "...",
            "directory": "data/content",
            "kinds": [...],
            "items": [
                {
                    "name": "20260523-XXX.md",
                    "title": "...",
                    "kind": "...",
                    "created_at": "ISO",
                    "size_bytes": ...,
                    "excerpt": "前 200 字",
                    "path": "data/content/20260523-xxx.md",
                },
                ...
            ],
            "empty_hint": "...",
        }
    """
    meta = workshop_meta(domain)
    d = DATA_ROOT / meta["dir"]
    items: list[dict] = []
    if d.exists():
        for p in sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            stat = p.stat()
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            parsed = _parse_frontmatter(text)
            items.append({
                "name": p.name,
                "title": parsed["meta"].get("title") or p.stem,
                "kind": parsed["meta"].get("kind", ""),
                "created_at": (
                    parsed["meta"].get("created_at")
                    or time.strftime(
                        "%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)
                    )
                ),
                "size_bytes": stat.st_size,
                "excerpt": _make_excerpt(parsed["body"], 200),
                "path": str(p.relative_to(ROOT)).replace("\\", "/"),
            })
            if len(items) >= max_items:
                break

    return {
        "domain": domain,
        "label": meta["label"],
        "icon": meta["icon"],
        "directory": f"data/{meta['dir']}",
        "kinds": meta["kinds"],
        "description": meta["description"],
        "items": items,
        "empty_hint": meta["empty_hint"],
    }


def create_workshop_item(
    domain: str,
    title: str,
    body: str,
    *,
    kind: Optional[str] = None,
) -> dict:
    """在 data/<domain>/ 下落一个新 markdown 文件

    返回:
        {"ok": True, "path": "data/content/20260523-xxx.md", ...}
    """
    meta = workshop_meta(domain)
    title = (title or "").strip()
    body = (body or "").strip()
    if not title:
        raise ValueError("title is required")
    if not body:
        raise ValueError("body is required")

    d = DATA_ROOT / meta["dir"]
    d.mkdir(parents=True, exist_ok=True)

    safe_title = _safe_slug(title) or "untitled"
    ts = time.strftime("%Y%m%d-%H%M%S")
    filename = f"{ts}-{safe_title}.md"
    p = d / filename

    created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    kind = (kind or "").strip()

    header_lines = ["---"]
    header_lines.append(f"title: {title}")
    if kind:
        header_lines.append(f"kind: {kind}")
    header_lines.append(f"created_at: {created_at}")
    header_lines.append(f"domain: {domain}")
    header_lines.append("---")
    header = "\n".join(header_lines) + "\n\n"

    p.write_text(header + body + "\n", encoding="utf-8")

    return {
        "ok": True,
        "domain": domain,
        "label": meta["label"],
        "name": filename,
        "title": title,
        "kind": kind,
        "path": str(p.relative_to(ROOT)).replace("\\", "/"),
        "size_bytes": p.stat().st_size,
        "created_at": created_at,
    }


# ──────────────────────────────────────────────────────────
# 内部
# ──────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.+?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict:
    """简易 yaml-frontmatter parser · 不依赖 PyYAML"""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {"meta": {}, "body": text}
    raw = m.group(1)
    body = text[m.end():]
    meta: dict = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return {"meta": meta, "body": body}


def _make_excerpt(body: str, max_chars: int) -> str:
    body = body.strip()
    if len(body) <= max_chars:
        return body
    cut = body[:max_chars]
    last_nl = cut.rfind("\n")
    if last_nl > max_chars * 0.5:
        cut = cut[:last_nl]
    return cut.rstrip() + "…"


# Windows 文件名安全：去掉非法字符 · 控制长度 · 保留中英文
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_slug(s: str, max_len: int = 40) -> str:
    s = _UNSAFE.sub("", s.strip())
    s = re.sub(r"\s+", "-", s)
    return s[:max_len].rstrip("-_.")
