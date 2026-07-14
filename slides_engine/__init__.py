"""
slides_engine · 演示稿(PPTX)生产引擎
=====================================

镜像 report_engine 的定位:把"分页 markdown → 精排 .pptx"抽象成通用引擎,
让 OPUS 用自然语言产出【原生可编辑、有高级感、可切换设计风格】的演示稿。

设计取向(研究了 anthropics/skills·pptx / ppt-master / slide-kit 后):
  · 原生 DrawingML 形状(不是一页一张图)· 生成后随便改
  · 多"设计风格"(art direction)· 不只是换配色 —— 见 styles.py
  · CRAP 排版纪律 + 出片前 QA 关(溢出/字号/缺图)

公共 API:
  from slides_engine import render_markdown_deck, list_styles
  path, slides, warnings = render_markdown_deck(
      md_text="<!-- layout: cover -->\\n# 标题\\n## 副标题\\n---\\n...",
      output_path=Path("data/presentations/foo.pptx"),
      cover={"title": "...", "subtitle": "...", "audience": "..."},
      style="dark_keynote",
      here_dir="data/presentations/_assets/foo",
  )
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from .parse import Slide, parse_deck  # noqa: F401
from .qa import audit_deck  # noqa: F401
from .render import render_deck  # noqa: F401
from .styles import STYLES, DeckStyle, get_style, list_styles, resolve_style  # noqa: F401

__all__ = [
    "render_markdown_deck",
    "render_deck",
    "parse_deck",
    "audit_deck",
    "list_styles",
    "get_style",
    "resolve_style",
    "STYLES",
    "DeckStyle",
    "Slide",
]


def render_markdown_deck(
    md_text: str,
    output_path,
    *,
    cover: Optional[dict] = None,
    style: str = "light_studio",
    here_dir=None,
) -> Tuple[Path, List[Slide], List[str]]:
    """分页 markdown → .pptx 一步到位。 返回 (最终路径, slide 列表, QA 告警)。"""
    slides = parse_deck(md_text)
    warnings = audit_deck(slides, here_dir)
    path = render_deck(slides, output_path, cover=cover, style=style, here_dir=here_dir)
    return path, slides, warnings
