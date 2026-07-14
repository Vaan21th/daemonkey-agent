"""
slides_engine/parse.py
=======================

分页 markdown → 结构化幻灯片模型(Slide)。

约定(教给 LLM 的写法 · 见 generate_presentation 工具描述 + soul):
  · 用一行 `---` 分隔每一页
  · 每页可带指令注释(各占一行):
      <!-- layout: cover|section|bullets|image|statement|two_col|metrics|sources|closing -->
      <!-- kicker: 小眉标 -->      <!-- image: 相对图片路径 -->
      <!-- caption: 图注 -->        <!-- notes: 演讲备注 -->
  · `# 标题`  `## 小标题/列头`  `> 金句`  `- 要点`(缩进=子级)  `![](图路径)`
  · metrics 页:每条要点写成 `值 | 说明`(如 `92% | 用户满意度`)
  · two_col 页:两个 `##` 各起一列 · 其下的 `-` 归入该列
  · sources 页:每条要点 = 一条信源

没写 layout 指令时按结构启发式推断 · 但显式指令最稳(弱模型也不跑偏)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

_LAYOUTS = {
    "cover", "section", "bullets", "image", "statement",
    "two_col", "metrics", "sources", "closing", "chart", "flow", "process",
    "pillars", "features", "cards",
}

_ICON_RE = re.compile(r"^\s*\{\s*([a-zA-Z_]+)\s*\}\s*")

# 指令注释:整行 or 一行多条 or 行内混排都认(根治"两条指令写一行→整条被当正文丢掉")
_DIRECTIVE_RE = re.compile(r"<!--\s*([a-zA-Z_]+)\s*:\s*(.*?)\s*-->")
_IMAGE_RE = re.compile(r"!\[(.*?)\]\((.*?)\)")


@dataclass
class Slide:
    layout: str = "bullets"
    kicker: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    statement: Optional[str] = None
    image: Optional[str] = None
    image_prompt: Optional[str] = None                     # 配图提示词(无图时占位卡显示)
    image_side: Optional[str] = None                       # image 版式图放哪:left/right(默认自动左右交替)
    caption: Optional[str] = None
    notes: Optional[str] = None
    footer: Optional[str] = None
    bullets: List[dict] = field(default_factory=list)      # {text, level}
    columns: List[dict] = field(default_factory=list)      # {title, bullets:[{text,level}]}
    metrics: List[dict] = field(default_factory=list)      # {value, label}
    sources: List[str] = field(default_factory=list)
    chart_type: Optional[str] = None                       # pie/doughnut/bar/column/line
    categories: List[str] = field(default_factory=list)    # 图表横轴/扇区标签
    series: List[dict] = field(default_factory=list)       # [{name, values:[float]}]
    pillars: List[dict] = field(default_factory=list)      # {icon, title, desc}


def _split_slides(md: str) -> List[str]:
    """按独占一行的 `---` 切页。 去掉全空的块。"""
    lines = (md or "").replace("\r\n", "\n").split("\n")
    blocks: List[List[str]] = [[]]
    for ln in lines:
        if ln.strip() == "---":
            blocks.append([])
        else:
            blocks[-1].append(ln)
    out = ["\n".join(b).strip() for b in blocks]
    return [b for b in out if b.strip()]


def _bullet_level(raw: str) -> int:
    indent = len(raw) - len(raw.lstrip(" "))
    return min(indent // 2, 2)


def _parse_block(block: str, is_first: bool) -> Optional[Slide]:
    s = Slide()
    directives: dict = {}
    body_lines: List[str] = []

    for ln in block.split("\n"):
        found = list(_DIRECTIVE_RE.finditer(ln))
        if found:
            for m in found:
                directives[m.group(1).lower()] = m.group(2).strip()
            residual = _DIRECTIVE_RE.sub("", ln).strip()
            if residual:                       # 指令后还剩正文 → 保留
                body_lines.append(residual)
        else:
            body_lines.append(ln)

    # 指令
    if "kicker" in directives:
        s.kicker = directives["kicker"] or None
    if "image" in directives:
        s.image = directives["image"] or None
    if "prompt" in directives:
        s.image_prompt = directives["prompt"] or None
    if "caption" in directives:
        s.caption = directives["caption"] or None
    if "image_side" in directives:
        s.image_side = (directives["image_side"] or "").lower() or None
    if "notes" in directives:
        s.notes = directives["notes"] or None
    if "footer" in directives:
        s.footer = directives["footer"] or None

    # 收集结构元素
    cur_col: Optional[dict] = None
    statement_parts: List[str] = []
    for raw in body_lines:
        line = raw.strip()
        if not line:
            continue
        img = _IMAGE_RE.search(line)
        if img:
            if not s.image:
                s.image = img.group(2).strip()
            if not s.caption and img.group(1).strip():
                s.caption = img.group(1).strip()
            continue
        if line.startswith("## "):
            head = line[3:].strip()
            # two_col: 每个 ## 起一列;否则当副标题
            cur_col = {"title": head, "bullets": []}
            s.columns.append(cur_col)
            if not s.subtitle:
                s.subtitle = head
            continue
        if line.startswith("# "):
            s.title = line[2:].strip()
            continue
        if line.startswith(">"):
            statement_parts.append(line.lstrip(">").strip())
            continue
        if re.match(r"^[-*]\s+", line):
            text = re.sub(r"^[-*]\s+", "", line)
            icon, text = _extract_icon(text)     # 行首 {icon} 一次性抽出·存进 item·正文不再残留(卷七十九事故)
            item = {"text": text, "level": _bullet_level(raw), "icon": icon}
            s.bullets.append(item)
            if cur_col is not None:
                cur_col["bullets"].append(item)
            continue
        # 裸段落 → 当作正文要点(level 0)
        icon, txt = _extract_icon(line)
        s.bullets.append({"text": txt, "level": 0, "icon": icon})

    if statement_parts:
        s.statement = " ".join(statement_parts)

    # 布局:显式指令 > 推断
    layout = (directives.get("layout") or "").strip().lower()
    if layout not in _LAYOUTS:
        layout = _infer_layout(s, is_first)
    if layout == "process":
        layout = "flow"
    if layout in ("features", "cards"):
        layout = "pillars"
    s.layout = layout

    # 按布局做二次成形
    if layout == "metrics":
        s.metrics = _bullets_to_metrics(s.bullets)
    elif layout == "pillars":
        s.pillars = _bullets_to_pillars(s.bullets)
    elif layout == "sources":
        s.sources = [b["text"] for b in s.bullets]
    elif layout == "chart":
        s.chart_type, s.categories, s.series = _parse_chart(body_lines, directives, s.bullets, s.title)
        s.bullets = []
    elif layout == "two_col" and not s.columns and s.bullets:
        # 没写 ## 分列 → 把要点平均劈两列兜底
        mid = (len(s.bullets) + 1) // 2
        s.columns = [
            {"title": "", "bullets": s.bullets[:mid]},
            {"title": "", "bullets": s.bullets[mid:]},
        ]

    if _is_empty(s):
        return None
    return s


def _infer_layout(s: Slide, is_first: bool) -> str:
    if s.statement and not s.bullets and not s.image:
        return "statement"
    if s.image or s.image_prompt:
        return "image"
    if is_first and s.title and not s.bullets:
        return "cover"
    if s.title and not s.bullets and not s.subtitle and not s.image:
        return "section"
    return "bullets"


def _num(v: str) -> float:
    v = re.sub(r"[^0-9.\-]", "", v or "")
    try:
        return float(v) if v not in ("", "-", ".", "-.") else 0.0
    except ValueError:
        return 0.0


def _cells(row: str) -> List[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _parse_chart(body_lines, directives, bullets, title):
    """图表数据:优先 markdown 表格(多序列)· 否则 `标签 | 数值` 要点(单序列)。"""
    ctype = (directives.get("chart") or "bar").strip().lower()
    rows = [ln for ln in body_lines if ln.strip().startswith("|")]
    rows = [r for r in rows if set(r.replace("|", "").strip()) - set("-: ")]  # 去分隔行
    if len(rows) >= 2:
        header = _cells(rows[0])
        ncol = max(len(header) - 1, 1)
        svals = [[] for _ in range(ncol)]
        cats = []
        for r in rows[1:]:
            c = _cells(r)
            if not c:
                continue
            cats.append(c[0])
            for i in range(ncol):
                svals[i].append(_num(c[i + 1]) if i + 1 < len(c) else 0.0)
        series = [{"name": (header[i + 1] if i + 1 < len(header) and header[i + 1] else f"系列{i + 1}"),
                   "values": svals[i]} for i in range(ncol)]
        return ctype, cats, series
    cats, vals = [], []
    for b in bullets:
        t = b.get("text", "")
        if "|" in t:
            lab, val = t.split("|", 1)
            cats.append(lab.strip()); vals.append(_num(val))
        else:
            cats.append(t.strip()); vals.append(0.0)
    return ctype, cats, [{"name": title or "数值", "values": vals}]


def _extract_icon(text: str):
    """抽出开头的 `{iconname}` token · 返回 (icon_or_None, 余下文本)。"""
    m = _ICON_RE.match(text or "")
    if m:
        return m.group(1).strip().lower(), text[m.end():].strip()
    return None, (text or "").strip()


def _bullets_to_metrics(bullets: List[dict]) -> List[dict]:
    out = []
    for b in bullets:
        # icon 已在解析阶段抽出;text 也已剥掉 {icon}(兼容旧路径再抽一次)
        icon, txt = (b.get("icon"), b.get("text", ""))
        if icon is None:
            icon, txt = _extract_icon(txt)
        if "|" in txt:
            value, label = txt.split("|", 1)
            out.append({"value": value.strip(), "label": label.strip(), "icon": icon})
        else:
            out.append({"value": txt.strip(), "label": "", "icon": icon})
    return out


def _bullets_to_pillars(bullets: List[dict]) -> List[dict]:
    """图标磁贴:`{icon} 标题 :: 描述`(:: 或 | 都可分隔;描述可省)。 只取顶层要点。"""
    out = []
    seq = ["star", "target", "rocket", "gear", "people", "idea"]
    for b in bullets:
        if b.get("level", 0) > 0:
            continue
        icon, txt = (b.get("icon"), b.get("text", ""))
        if icon is None:
            icon, txt = _extract_icon(txt)
        sep = "::" if "::" in txt else ("|" if "|" in txt else None)
        if sep:
            title, desc = txt.split(sep, 1)
            title, desc = title.strip(), desc.strip()
        else:
            title, desc = txt.strip(), ""
        if not icon:
            icon = seq[len(out) % len(seq)]
        out.append({"icon": icon, "title": title, "desc": desc})
    return out[:4]


def _is_empty(s: Slide) -> bool:
    return not any([
        s.title, s.subtitle, s.statement, s.image,
        s.bullets, s.columns, s.metrics, s.sources, s.pillars,
    ])


def parse_deck(md: str) -> List[Slide]:
    """分页 markdown → Slide 列表。"""
    blocks = _split_slides(md)
    slides: List[Slide] = []
    for i, block in enumerate(blocks):
        sl = _parse_block(block, is_first=(i == 0))
        if sl is not None:
            slides.append(sl)
    return slides
