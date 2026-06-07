"""
report_engine/themes.py
========================

文档视觉主题 · 给 markdown_to_docx 渲染器用

每个 Theme 决定一份 docx 的"长相"——
  - 标题 / 正文字体
  - H1/H2/H3 颜色
  - 表头底色 + 隔行底色
  - 引用块 / 代码块底色
  - 主要色板（封面强调色 / 列表 bullet 色等）

默认版（opus_studio）色板基于 chat.css 的 #9F7AEA 紫色生态
另有一套深蓝版（manju）备选
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

# RGB 三元组（避免在主题层 import docx · 主题模块要轻量纯数据）
RGB = Tuple[int, int, int]


@dataclass(frozen=True)
class Theme:
    """单一主题视觉规范

    所有颜色都是 (r, g, b) 三元组 · 渲染器自己负责转 docx RGBColor / hex
    """

    name: str
    description: str

    # 字体
    font_cjk: str       # 中文字体名
    font_en: str        # 英文 / 代码字体名

    # 标题 / 正文颜色（RGB 三元组）
    color_title: RGB    # 一级标题（最大）
    color_h2: RGB       # 二级标题
    color_h3: RGB       # 三级标题（包含 4-6 级）
    color_quote: RGB    # 引用块文字
    color_hint: RGB     # 提示 / 灰色文字
    color_code_inline: RGB  # 行内代码红字

    # 块底色（hex 字符串 · docx 的 fill 用 hex）
    table_header_fill: str
    table_alt_fill: str
    quote_fill: str
    code_fill: str
    placeholder_fill: str    # 缺失图片占位框底色
    placeholder_border: str  # 缺失图片占位框边框色

    # 引用块左侧竖线颜色
    quote_border: str


# ─── 深蓝主题 ────────────────────────────────────────────────────
THEME_MANJU = Theme(
    name="manju",
    description="深蓝主题 · 深蓝标题 + 蓝头白字表 + 隔行灰底",
    font_cjk="微软雅黑",
    font_en="Consolas",
    color_title=(0x1A, 0x36, 0x5D),
    color_h2=(0x2B, 0x6C, 0xB0),
    color_h3=(0x2C, 0x52, 0x82),
    color_quote=(0x4A, 0x55, 0x68),
    color_hint=(0x71, 0x80, 0x96),
    color_code_inline=(0xC0, 0x39, 0x2B),
    table_header_fill="1A365D",
    table_alt_fill="F7FAFC",
    quote_fill="EBF4FF",
    code_fill="F1F5F9",
    placeholder_fill="FEF5E7",
    placeholder_border="DD6B20",
    quote_border="2B6CB0",
)


# ─── 默认主题（紫色） ────────────────────────────────────────────
# 基于 chat.css --opus #9F7AEA 紫色色调 · 同源整体视觉
THEME_OPUS_STUDIO = Theme(
    name="opus_studio",
    description="默认紫色主题 · 紫色标题 + 浅紫底表头 + 同源 chat.css 视觉",
    font_cjk="微软雅黑",
    font_en="Consolas",
    color_title=(0x4C, 0x1D, 0x95),    # 深紫 · 比 #9F7AEA 暗一档作为标题
    color_h2=(0x7B, 0x5D, 0xC4),       # opus-dim
    color_h3=(0x6B, 0x46, 0xC1),       # 中紫
    color_quote=(0x4A, 0x55, 0x68),    # 中性灰
    color_hint=(0x71, 0x80, 0x96),     # 浅灰
    color_code_inline=(0xC0, 0x39, 0x2B),  # 代码红
    table_header_fill="6B46C1",        # 中紫底
    table_alt_fill="F5F3FF",           # 极浅紫
    quote_fill="EDE9FE",               # 浅紫
    code_fill="F1F5F9",                # 中性灰
    placeholder_fill="FEF3C7",         # 暖色提醒
    placeholder_border="D97706",       # 橙色边
    quote_border="9F7AEA",             # opus 紫
)


# ─── 暗色主题（远期 · 黑色幻灯片风） ────────────────────────────
# 留作扩展 · 当前不暴露在 list_themes
THEME_DARK_PURPLE = Theme(
    name="dark_purple",
    description="暗色紫主题 · 适合演示稿 / 仪表盘报告（未启用）",
    font_cjk="微软雅黑",
    font_en="Consolas",
    color_title=(0xC9, 0xB6, 0xFF),
    color_h2=(0x9F, 0x7A, 0xEA),
    color_h3=(0x7B, 0x5D, 0xC4),
    color_quote=(0xCB, 0xD5, 0xE0),
    color_hint=(0x71, 0x80, 0x96),
    color_code_inline=(0xF5, 0x6E, 0x6E),
    table_header_fill="4C1D95",
    table_alt_fill="2D2D2D",
    quote_fill="2D2D2D",
    code_fill="1F1F1F",
    placeholder_fill="3D2D0F",
    placeholder_border="D97706",
    quote_border="9F7AEA",
)


THEMES: Dict[str, Theme] = {
    "manju": THEME_MANJU,
    "opus_studio": THEME_OPUS_STUDIO,
    # dark_purple 暂不暴露 · 等远期实测
}


def get_theme(name: str | None) -> Theme:
    """获取主题 · None 或未知名都 fallback 到 opus_studio"""
    if not name:
        return THEME_OPUS_STUDIO
    return THEMES.get(name.lower(), THEME_OPUS_STUDIO)


def list_themes() -> list[str]:
    return list(THEMES.keys())
