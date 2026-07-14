"""
slides_engine/qa.py
====================

出片前的轻量 QA 关(参考 Anthropic pptx skill 的自动质检思路)。

渲染层已做要点 auto-fit 收字;这里只做【结构级告警】——把可能导致
"看起来 low"的问题(要点太多、单条太长、图缺失)挑出来回给上层,
让 OPUS 有机会拆页/精简/补图,而不是闷头出一份挤爆的稿。
纯启发式 · 只警告不阻断。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .parse import Slide

_MAX_BULLETS = 7        # 单页要点超过这个数 → 建议拆页
_MAX_BULLET_CHARS = 90  # 单条要点超过 → 可能溢出


def audit_deck(slides: List[Slide], here_dir: Optional[str | Path] = None,
               *, cover: Optional[dict] = None) -> List[str]:
    warnings: List[str] = []
    here = Path(here_dir) if here_dir else None
    for i, s in enumerate(slides, 1):
        if s.image:
            p = Path(s.image)
            if not p.is_absolute() and here:
                p = here / s.image
            if not p.exists():
                warnings.append(f"第{i}页图片未找到:{s.image}(会用占位框 · 先 web_search_image 取图)")
        if len(s.bullets) > _MAX_BULLETS:
            warnings.append(f"第{i}页要点 {len(s.bullets)} 条偏多 · 建议拆成两页或精简到 ≤6 条(留白才高级)")
        for b in s.bullets:
            if len(b.get("text", "")) > _MAX_BULLET_CHARS:
                warnings.append(f"第{i}页有超长要点(>{_MAX_BULLET_CHARS}字)· 一句话讲不完就拆条 · 免得溢出")
                break

    # deck 级:整份没配图意识 → 会很平(BRO 痛点 · 卷七十九)
    n = len(slides)
    cover_has_visual = bool(cover and (cover.get("image") or cover.get("prompt")))
    visual_pages = sum(1 for s in slides
                       if s.image or s.image_prompt or (s.layout in ("chart", "image")))
    if n >= 4 and visual_pages == 0 and not cover_has_visual:
        warnings.insert(0,
            f"整份 {n} 页没有任何配图/图表 · 会显得很平 —— 封面加 cover_prompt、讲场景/氛围/产品的页加 "
            "<!-- layout: image --><!-- prompt: 画面描述 -->(没配生图模型也会渲成提示词占位卡·用户能后补)")
    elif n >= 8 and visual_pages * 3 < n and not cover_has_visual:
        warnings.append(
            f"{n} 页里只有 {visual_pages} 页有视觉(图/图表)· 偏文字 · 封面 + 每 3~4 页补一个视觉承载会立刻不平")
    return warnings
