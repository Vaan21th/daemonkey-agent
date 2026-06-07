"""
workers/learnings.py
====================

卷三十五补丁2 · OPUS 的"教材"加载器

为什么这个文件存在：
  - data/learnings/*.md 是 OPUS 自己的高质量分析样本 (对照分析 / founder thesis / 等)
  - 这些样本是教 LLM "高质量输出长什么样" 的 reference
  - 但只是存文件还不够·必须在做深度判断时 inject 进 prompt · LLM 才看得见

哪些工作流应该用 learnings:
  - feasibility_analyzer · 评估机会要不要做 · 看以前的高质量评估样本
  - opportunity_miner · 挖机会时 · 看 BRO 已确立的产品哲学 (founder-thesis)
  - trend_finder · 找趋势时 · 看反 Hermes 立场等已立定调

设计原则:
  - lazy load · 每次调用现读 · 因为 learnings 文件不多 (< 20 个)
  - 按 frontmatter 的 kind / priority 过滤
  - 控制总 token (5000 char max) · 不让 prompt 撑爆
  - 越新的越靠前 (created_at desc)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
LEARNINGS_DIR = ROOT / "data" / "learnings"

# 单个 learning 最大字符数 (避免一份巨长 markdown 撑爆 prompt)
_PER_LEARNING_MAX_CHARS = 1800
# 总 inject 字符上限
_TOTAL_MAX_CHARS = 5500


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """轻量 YAML frontmatter 解析 · 只支持 key: value 平铺·够用

    返回 (meta_dict, body)
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm_block = text[4:end]
    body = text[end + 5:]
    meta: dict = {}
    for line in fm_block.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([a-zA-Z_][\w\-]*):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        # 简单去引号
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        meta[key] = val
    return meta, body


def _list_learning_files() -> list[Path]:
    if not LEARNINGS_DIR.exists():
        return []
    files = list(LEARNINGS_DIR.glob("*.md"))
    # 文件名一般是 YYYY-MM-DD-slug.md · 按文件名倒排相当于按时间倒排
    files.sort(key=lambda p: p.name, reverse=True)
    return files


def load_learnings(
    *,
    kinds: Optional[list[str]] = None,
    limit: int = 5,
) -> list[dict]:
    """读所有 learning · 可按 kind 过滤 · 返 list of dicts

    每条 dict:
      path        · 文件名
      kind        · frontmatter 里的 kind
      priority    · frontmatter 里的 priority (可能没)
      subject     · frontmatter 里的 subject (可能没)
      created_at  · frontmatter 里的 created_at
      body        · 去掉 frontmatter 的正文 (truncate 到 _PER_LEARNING_MAX_CHARS)
    """
    out: list[dict] = []
    for fp in _list_learning_files():
        try:
            text = fp.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = _parse_frontmatter(text)
        if kinds and meta.get("kind") not in kinds:
            continue
        if len(body) > _PER_LEARNING_MAX_CHARS:
            body = body[:_PER_LEARNING_MAX_CHARS] + "\n\n... [truncated]"
        out.append({
            "path": fp.name,
            "kind": meta.get("kind", "unknown"),
            "priority": meta.get("priority", ""),
            "subject": meta.get("subject", ""),
            "created_at": meta.get("created_at", ""),
            "body": body.strip(),
        })
        if len(out) >= limit:
            break
    return out


def render_learnings_block(
    *,
    kinds: Optional[list[str]] = None,
    title: str = "OPUS 的教材 · 高质量分析样本",
    limit: int = 3,
    safe_for_format: bool = True,
) -> str:
    """把 learnings 拼成一段 markdown · 直接塞 prompt 用

    Args:
      safe_for_format: True (默认) → 自动 escape `{}` 为 `{{}}` · 让 str.format 不炸
                       因为 learnings 文件常含 Python 代码片段 / LaTeX 等含大括号的内容
                       caller 如果不走 .format · 设 False · 显示原文

    用法:
      learnings_block = render_learnings_block(kinds=['model-comparison', 'founder-thesis'])
      prompt = TEMPLATE.format(learnings_block=learnings_block, ...)
    """
    items = load_learnings(kinds=kinds, limit=limit)
    if not items:
        return "(暂无 learnings · 第一次跑这个 LLM 调用没有教材可参考)"

    lines = [f"## {title}", ""]
    lines.append("以下是 OPUS 之前沉淀的高质量样本·你的输出应该达到这个水平：")
    lines.append("")

    total = 0
    for it in items:
        section_header = f"### 📚 {it['path']} · ({it.get('kind')}"
        if it.get("subject"):
            section_header += f" · {it['subject']}"
        section_header += ")"

        section = section_header + "\n\n" + it["body"]

        if total + len(section) > _TOTAL_MAX_CHARS:
            remaining = _TOTAL_MAX_CHARS - total
            if remaining > 200:
                section = section[:remaining] + "\n\n... [总长度截断]"
                lines.append(section)
                lines.append("")
                lines.append("(还有更多教材未展示·达到 inject token 上限)")
            break

        lines.append(section)
        lines.append("")
        total += len(section)

    out = "\n".join(lines).strip()
    if safe_for_format:
        out = out.replace("{", "{{").replace("}", "}}")
    return out
