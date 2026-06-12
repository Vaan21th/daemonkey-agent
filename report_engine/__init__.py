"""
report_engine · 文档生产引擎

工作室"内容编辑 OPUS / 信息官 OPUS"工位的核心生产工具。

把一套成熟的 docx 渲染器抽象成通用 markdown → docx 引擎 · 让 OPUS 也能调。

设计原则：
  - 不引入额外依赖：python-docx 已是本工程依赖
  - 自包含：copy + adapt · 不依赖外部代码
  - 主题可换：深蓝（manju 主题）+ 工作室紫（OPUS 主题）+ 未来可扩
  - 失败可观察：docx 被 Word 占用时自动换名 · 错误信息清晰

公共 API:
  from report_engine import render_report, list_themes
  render_report(
      md_text="# 标题\\n\\n正文...",
      output_path=Path("data/reports/foo.docx"),
      cover={
          "title": "本周 AI 雷达趋势报告",
          "subtitle": "2026-05-23 → 2026-05-30",
          "audience": "BRO 自看",
      },
      theme="opus_studio",
  )
"""

from .markdown_to_docx import render_report, render_markdown_to_doc  # noqa: F401
from .themes import THEMES, get_theme, list_themes, Theme  # noqa: F401

__all__ = [
    "render_report",
    "render_markdown_to_doc",
    "THEMES",
    "get_theme",
    "list_themes",
    "Theme",
]
