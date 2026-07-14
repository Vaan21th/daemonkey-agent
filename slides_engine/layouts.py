"""
slides_engine/layouts.py
=========================

重新设计的 9 种版式 —— 从"白底文本框"升级到"有设计感"。

设计手法(拉开档次的关键):
  · cover  —— 非对称:左字右渐变色块 + 装饰圆(不再居中平铺)
  · section—— 满版渐变 + 章节巨型数字水印(编辑设计最"高级"的一招)
  · metrics/two_col —— 圆角卡片 + 柔和投影 + 顶部强调条(卡片浮起)
  · statement —— 超大金句 + 巨型引号水印 + 强调竖条
  · 全内页统一 _header(眉标 hairline 在标题之上)· 彻底消灭眉标压标题
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from ._draw import (
    BODY_TOP, CONTENT_W, MARGIN, SLIDE_H, SLIDE_W,
    _bg, _bullets, _corner_marks, _fill_photo, _fit_pt, _footer, _grad_rect, _header, _image_cover,
    _kicker_row, _mix, _oval, _panel, _para, _rect, _round, _scrim, _tb, _watermark,
)
from .diagrams import draw_chart, draw_flow
from .icons import draw_icon
from .parse import Slide
from .styles import DeckStyle

_BAND = Inches(4.7)


def cover(slide, s: Slide, style: DeckStyle, here=None, mode="auto"):
    img = _resolve_img(s.image, here) if s.image else None
    if img is not None and img.exists():
        if (mode or "auto").lower() == "hero":
            _cover_hero(slide, s, style, img)      # 左字右图·分栏
        else:
            _cover_full(slide, s, style, img)      # auto/full · 满版大图 + 遮罩(默认)
        return
    if style.is_dark:
        _grad_rect(slide, 0, 0, SLIDE_W, SLIDE_H, style.bg, _mix(style.accent, style.bg, 0.30), 115)
    else:
        _bg(slide, style)
    # 右侧渐变色块(结构)+ 装饰圆(仅 decor=blob · 防各风格趋同)
    band_x = SLIDE_W - _BAND
    dec = getattr(style, "decor", "blob")
    if style.is_dark:
        _grad_rect(slide, band_x, 0, _BAND, SLIDE_H, _mix(style.accent, style.bg, 0.55), style.accent, 55)
        if dec == "blob":
            _oval(slide, band_x + Inches(1.0), Inches(-1.4), Inches(4.6), Inches(4.6),
                  _mix(style.accent, style.bg, 0.72))
            _oval(slide, band_x + Inches(2.6), Inches(4.6), Inches(3.2), Inches(3.2),
                  _mix(style.accent, style.bg, 0.66))
    else:
        _grad_rect(slide, band_x, 0, _BAND, SLIDE_H, style.accent, style.accent2, 55)
        if dec == "blob":
            _oval(slide, band_x + Inches(1.0), Inches(-1.4), Inches(4.6), Inches(4.6),
                  _mix(style.accent2, "FFFFFF", 0.30))
            _oval(slide, band_x + Inches(2.7), Inches(4.7), Inches(3.0), Inches(3.0),
                  _mix(style.accent, style.accent2, 0.35))
    if dec == "corner":
        _corner_marks(slide, style, style.on_accent if not style.is_dark else style.accent)
    # 左侧内容
    cw = band_x - MARGIN - Inches(0.4)
    _kicker_row(slide, style, s.kicker or "", Inches(1.95))
    _rect(slide, MARGIN, Inches(2.42), Inches(1.3), Pt(4.5), style.accent)
    _, tf = _tb(slide, MARGIN, Inches(2.6), cw, Inches(3.2))
    _para(tf, s.title or "", style, style.pt_cover_title, style.ink_title, bold=True,
          first=True, space_after=10, line_spacing=1.04, display=True)
    if s.subtitle:
        _para(tf, s.subtitle, style, style.pt_heading, style.ink_muted, space_after=0, line_spacing=1.12)
    ft = s.footer if s.footer is not None else style.footer
    if ft:
        _, tf2 = _tb(slide, MARGIN, SLIDE_H - Inches(0.75), cw, Inches(0.35))
        _para(tf2, ft, style, style.pt_footnote, style.ink_muted, first=True, space_after=0)


def _cover_hero(slide, s: Slide, style: DeckStyle, img):
    """有图封面(大片):左侧背景+文字 · 右侧整幅照片 · 中间强调竖缝。"""
    if style.is_dark:
        _grad_rect(slide, 0, 0, SLIDE_W, SLIDE_H, style.bg, _mix(style.accent, style.bg, 0.22), 115)
    else:
        _bg(slide, style)
    img_w = int(SLIDE_W * 0.46)
    img_x = int(SLIDE_W) - img_w
    _fill_photo(slide, img, img_x, 0, img_w, int(SLIDE_H))
    _rect(slide, img_x - Pt(6), 0, Pt(6), SLIDE_H, style.accent)      # 照片左缘强调竖缝
    cw = img_x - int(MARGIN) - int(Inches(0.5))
    _kicker_row(slide, style, s.kicker or "", Inches(1.95))
    _rect(slide, MARGIN, Inches(2.42), Inches(1.3), Pt(4.5), style.accent)
    _, tf = _tb(slide, MARGIN, Inches(2.6), cw, Inches(3.2))
    _para(tf, s.title or "", style, style.pt_cover_title, style.ink_title, bold=True,
          first=True, space_after=10, line_spacing=1.04, display=True)
    if s.subtitle:
        _para(tf, s.subtitle, style, style.pt_heading, style.ink_muted, space_after=0, line_spacing=1.12)
    ft = s.footer if s.footer is not None else style.footer
    if ft:
        _, tf2 = _tb(slide, MARGIN, SLIDE_H - Inches(0.75), cw, Inches(0.35))
        _para(tf2, ft, style, style.pt_footnote, style.ink_muted, first=True, space_after=0)


def _cover_full(slide, s: Slide, style: DeckStyle, img):
    """满版大图封面:整幅照片铺底 + 左侧「暗→透」渐变遮罩 + 底部薄遮罩 · 白字叠上(超大图底图)。"""
    _fill_photo(slide, img, 0, 0, SLIDE_W, SLIDE_H)
    scrim = "090B14"
    _scrim(slide, 0, 0, SLIDE_W, SLIDE_H, scrim, a1=90, a2=4, angle=0)          # 左暗右透
    _scrim(slide, 0, SLIDE_H - Inches(2.6), SLIDE_W, Inches(2.6), scrim, a1=0, a2=74, angle=90)  # 底部压暗
    ink, sub_ink = "FFFFFF", "E7EAF5"
    _kicker_row(slide, style, s.kicker or "", Inches(1.9), ink=style.accent2)
    _rect(slide, MARGIN, Inches(2.4), Inches(1.3), Pt(4.5), style.accent)
    _, tf = _tb(slide, MARGIN, Inches(2.58), Inches(8.6), Inches(3.2))
    _para(tf, s.title or "", style, style.pt_cover_title, ink, bold=True,
          first=True, space_after=10, line_spacing=1.04, display=True)
    if s.subtitle:
        _para(tf, s.subtitle, style, style.pt_heading, sub_ink, space_after=0, line_spacing=1.12)
    ft = s.footer if s.footer is not None else style.footer
    if ft:
        _, tf2 = _tb(slide, MARGIN, SLIDE_H - Inches(0.72), Inches(9), Inches(0.35))
        _para(tf2, ft, style, style.pt_footnote, sub_ink, first=True, space_after=0)


def section(slide, s: Slide, style: DeckStyle, sec_no: int = 0):
    if style.is_dark:
        _grad_rect(slide, 0, 0, SLIDE_W, SLIDE_H, style.bg, style.bg_alt, 120)
        ink, sub_ink = style.ink_title, style.accent2
        wm = _mix(style.bg, style.accent, 0.34)
    else:
        _grad_rect(slide, 0, 0, SLIDE_W, SLIDE_H, style.accent, _mix(style.accent, "000000", 0.24), 120)
        ink, sub_ink = style.on_accent, _mix(style.accent, "FFFFFF", 0.75)
        wm = _mix(style.accent, "FFFFFF", 0.15)
    # 巨型水印:章节序号(01/02…)当设计元素;kicker 短(≤3字符)才用 kicker · 否则永不用 §/长中文
    kick = (s.kicker or "").strip()
    wm_text = kick if (kick and len(kick) <= 3) else (f"{sec_no:02d}" if sec_no else "")
    if wm_text:
        _watermark(slide, style, wm_text, wm)
    _rect(slide, MARGIN, Inches(2.75), Inches(1.4), Pt(5), sub_ink if style.is_dark else style.on_accent)
    if s.kicker:
        _, tfk = _tb(slide, MARGIN, Inches(2.98), Inches(8), Inches(0.4))
        _para(tfk, "SECTION" if style.uppercase_kicker else "章节", style, style.pt_kicker,
              sub_ink, bold=True, first=True, space_after=0, tracking=True)
    _, tf = _tb(slide, MARGIN, Inches(3.5), Inches(8.4), Inches(2.2), MSO_ANCHOR.TOP)
    _para(tf, s.title or "", style, style.pt_section, ink, bold=True, first=True,
          space_after=4, line_spacing=1.02, display=True)
    if s.subtitle:
        _para(tf, s.subtitle, style, style.pt_heading, sub_ink, space_after=0, line_spacing=1.12)


def bullets(slide, s: Slide, style: DeckStyle, page):
    _bg(slide, style)
    dec = getattr(style, "decor", "blob")
    if dec == "blob":
        _oval(slide, SLIDE_W - Inches(3.1), SLIDE_H - Inches(3.1), Inches(5.0), Inches(5.0),
              _mix(style.bg, style.accent, 0.12 if style.is_dark else 0.05))
    elif dec == "corner":
        _corner_marks(slide, style)
    top = _header(slide, style, s.kicker, s.title, s.subtitle)
    _bullets(slide, style, s.bullets, MARGIN, top, CONTENT_W * 0.70, SLIDE_H - top - Inches(0.95))
    _footer(slide, style, page, s.footer)


def image(slide, s: Slide, style: DeckStyle, page, here, img_no: int = 0):
    _bg(slide, style)
    top = _header(slide, style, s.kicker, s.title, s.subtitle if s.bullets else None)
    img = _resolve_img(s.image, here)
    if s.bullets:
        # 左右交替:偶数配图页图在左、奇数在右 → 打破"图永远钉在右侧"的呆板节奏(BRO 反馈)
        # 显式 <!-- image_side: left|right --> 可覆盖自动交替
        side = (getattr(s, "image_side", "") or "").lower()
        img_left = side == "left" if side in ("left", "right") else (img_no % 2 == 0)
        gap = Inches(0.42)
        img_w = CONTENT_W * 0.50
        txt_w = CONTENT_W * 0.44
        if img_left:
            img_l, txt_l = MARGIN, MARGIN + img_w + gap
        else:
            txt_l, img_l = MARGIN, MARGIN + txt_w + gap
        _bullets(slide, style, s.bullets, txt_l, top, txt_w, SLIDE_H - top - Inches(0.95))
        _image_cover(slide, img, img_l, top, img_w, SLIDE_H - top - Inches(0.7),
                     style, s.caption, s.image_prompt)
    else:
        _image_cover(slide, img, MARGIN, top, CONTENT_W, SLIDE_H - top - Inches(0.9), style,
                     s.caption, s.image_prompt)
    _footer(slide, style, page, s.footer)


def statement(slide, s: Slide, style: DeckStyle, page):
    if style.is_dark:
        _grad_rect(slide, 0, 0, SLIDE_W, SLIDE_H, style.bg, _mix(style.accent, style.bg, 0.16), 120)
    else:
        _bg(slide, style)
    # 巨型引号水印
    _, tfq = _tb(slide, MARGIN - Inches(0.15), Inches(0.9), Inches(4), Inches(2.6))
    _para(tfq, "\u201c", style, 220, _mix(style.bg, style.accent, 0.30 if style.is_dark else 0.14),
          bold=True, first=True, space_after=0)
    _rect(slide, MARGIN, Inches(2.95), Inches(0.10), Inches(1.9), style.accent)
    _, tf = _tb(slide, MARGIN + Inches(0.42), Inches(2.9), CONTENT_W - Inches(0.5), Inches(2.6), MSO_ANCHOR.TOP)
    _para(tf, s.statement or s.title or "", style, style.pt_statement, style.ink_title, bold=True,
          first=True, space_after=0, line_spacing=1.14, display=True)
    if s.subtitle:
        _, tf2 = _tb(slide, MARGIN + Inches(0.42), SLIDE_H - Inches(1.35), CONTENT_W, Inches(0.5))
        _para(tf2, "— " + s.subtitle, style, style.pt_heading, style.ink_muted, first=True, space_after=0)
    _footer(slide, style, page, s.footer)


def two_col(slide, s: Slide, style: DeckStyle, page):
    _bg(slide, style)
    top = _header(slide, style, s.kicker, s.title, None)
    cols = s.columns[:2] if s.columns else []
    gap = Inches(0.55)
    cw = (CONTENT_W - gap) / 2
    ch = SLIDE_H - top - Inches(0.9)
    for i, col in enumerate(cols):
        cl = MARGIN + i * (cw + gap)
        _panel(slide, style, cl, top, cw, ch)
        pad = Inches(0.4)
        _rect(slide, cl + pad, top + Inches(0.36), Inches(0.5), Pt(5), style.accent)
        _, tf = _tb(slide, cl + pad, top + Inches(0.5), cw - pad * 2, Inches(0.5))
        _para(tf, col.get("title", "") or f"栏目 {i + 1}", style, style.pt_heading, style.accent,
              bold=True, first=True, space_after=0)
        _bullets(slide, style, col.get("bullets", []), cl + pad, top + Inches(1.15),
                 cw - pad * 2, ch - Inches(1.4))
    _footer(slide, style, page, s.footer)


def metrics(slide, s: Slide, style: DeckStyle, page):
    _bg(slide, style)
    top = _header(slide, style, s.kicker, s.title, s.subtitle)
    ms = s.metrics[:4]
    if not ms:
        _footer(slide, style, page, s.footer)
        return
    n = len(ms)
    gap = Inches(0.45)
    cw = (CONTENT_W - gap * (n - 1)) / n
    ct = top + Inches(0.25)
    ch = Inches(3.05)
    has_icon = any(m.get("icon") for m in ms)
    for i, m in enumerate(ms):
        cl = MARGIN + i * (cw + gap)
        _panel(slide, style, cl, ct, cw, ch)
        _rect(slide, cl, ct, cw, Pt(7), style.accent)
        vy = ct + Inches(0.5)
        if has_icon:
            tile = int(Inches(0.82))
            tx = int(cl) + (int(cw) - tile) // 2
            _oval(slide, tx, int(ct) + int(Inches(0.34)), tile, tile,
                  _mix(style.accent, style.bg, 0.80 if not style.is_dark else 0.66))
            draw_icon(slide, m.get("icon") or "star", tx + int(tile * 0.19),
                      int(ct) + int(Inches(0.34)) + int(tile * 0.19), int(tile * 0.62), style.accent)
            vy = ct + Inches(1.35)
        val = m.get("value", "")
        # KPI 位常被塞非数字长词(如"市场定位")· 按卡宽收字号,防大字溢出压说明(卷七十九事故)
        vsize = _fit_pt(val, style.pt_kpi, cw - Inches(0.34), max_lines=1, min_pt=20)
        _, tf = _tb(slide, cl + Inches(0.15), vy, cw - Inches(0.3), Inches(1.2), MSO_ANCHOR.MIDDLE)
        _para(tf, val, style, vsize, style.accent, bold=True, first=True,
              align=PP_ALIGN.CENTER, space_after=0, line_spacing=0.95)
        _, tf2 = _tb(slide, cl + Inches(0.2), ct + ch - Inches(0.9), cw - Inches(0.4), Inches(0.8))
        _para(tf2, m.get("label", ""), style, style.pt_body, style.ink_body, first=True,
              align=PP_ALIGN.CENTER, space_after=0, line_spacing=1.1)
    _footer(slide, style, page, s.footer)


def pillars(slide, s: Slide, style: DeckStyle, page):
    """图标磁贴:2~4 张卡,每张 = 彩色图标砖 + 标题 + 一句描述。 商务 PPT 的"支柱/特性"页。"""
    _bg(slide, style)
    top = _header(slide, style, s.kicker, s.title, s.subtitle)
    ps = s.pillars[:4]
    if not ps:
        _footer(slide, style, page, s.footer)
        return
    n = len(ps)
    gap = Inches(0.45)
    cw = (CONTENT_W - gap * (n - 1)) / n
    ct = top + Inches(0.2)
    ch = SLIDE_H - ct - Inches(0.95)
    pad = Inches(0.36)
    tile = int(Inches(0.94))
    for i, p in enumerate(ps):
        cl = MARGIN + i * (cw + gap)
        _panel(slide, style, cl, ct, cw, ch)
        _round(slide, cl + pad, ct + pad, tile, tile,
               _mix(style.accent, style.bg, 0.80 if not style.is_dark else 0.62), radius=0.3)
        draw_icon(slide, p.get("icon") or "star", int(cl + pad) + int(tile * 0.19),
                  int(ct + pad) + int(tile * 0.19), int(tile * 0.62), style.accent)
        ty = ct + pad + tile + Inches(0.26)
        ttl = p.get("title", "")
        tsize = _fit_pt(ttl, style.pt_heading, cw - pad * 2, max_lines=2, min_pt=15)
        _, tf = _tb(slide, cl + pad, ty, cw - pad * 2, Inches(0.75))
        _para(tf, ttl, style, tsize, style.ink_title, bold=True,
              first=True, space_after=3, line_spacing=1.04)
        if p.get("desc"):
            desc_top = ty + Inches(0.74)
            avail_h = ct + ch - desc_top - pad
            base_pt = max(style.pt_body - 1, 13)
            line_h = int(Pt(base_pt) * 1.22) or 1
            # 按卡内可用高度算能塞几行 · 再据此把字号往下收 —— 治描述过长溢出卡/页面(Fig 3)
            max_lines = max(2, int(avail_h / line_h))
            dsize = _fit_pt(p["desc"], base_pt, cw - pad * 2, max_lines=max_lines, min_pt=11)
            _, tf2 = _tb(slide, cl + pad, desc_top, cw - pad * 2, avail_h)
            _para(tf2, p["desc"], style, dsize, style.ink_muted,
                  first=True, space_after=0, line_spacing=1.18)
    _footer(slide, style, page, s.footer)


def chart(slide, s: Slide, style: DeckStyle, page):
    _bg(slide, style)
    top = _header(slide, style, s.kicker, s.title, s.subtitle)
    draw_chart(slide, style, s, MARGIN, top, CONTENT_W, SLIDE_H - top - Inches(0.95))
    _footer(slide, style, page, s.footer)


def flow(slide, s: Slide, style: DeckStyle, page):
    _bg(slide, style)
    top = _header(slide, style, s.kicker, s.title, s.subtitle)
    draw_flow(slide, style, s.bullets, MARGIN, top, CONTENT_W, SLIDE_H - top - Inches(0.95))
    _footer(slide, style, page, s.footer)


def sources(slide, s: Slide, style: DeckStyle, page):
    _bg(slide, style)
    top = _header(slide, style, s.kicker or "TRACEABILITY", s.title or "信息来源", None)
    _, tf = _tb(slide, MARGIN, top, CONTENT_W, SLIDE_H - top - Inches(0.95))
    for i, src in enumerate(s.sources):
        _para(tf, src, style, max(style.pt_body - 3, 13), style.ink_muted, first=(i == 0),
              space_after=9, line_spacing=1.25, marker=f"[{i + 1}]", marker_color=style.accent)
    _footer(slide, style, page, s.footer)


def closing(slide, s: Slide, style: DeckStyle):
    if style.is_dark:
        _grad_rect(slide, 0, 0, SLIDE_W, SLIDE_H, style.bg, _mix(style.accent, style.bg, 0.30), 120)
        ink, sub = style.ink_title, style.accent2
    else:
        _grad_rect(slide, 0, 0, SLIDE_W, SLIDE_H, style.accent, _mix(style.accent, "000000", 0.22), 120)
        ink, sub = style.on_accent, _mix(style.accent, "FFFFFF", 0.78)
    dec = getattr(style, "decor", "blob")
    if dec == "blob":
        _oval(slide, SLIDE_W - Inches(3.4), SLIDE_H - Inches(3.4), Inches(5.2), Inches(5.2),
              _mix(style.accent, style.bg if style.is_dark else "FFFFFF", 0.16))
    elif dec == "corner":
        _corner_marks(slide, style, style.on_accent if not style.is_dark else style.accent)
    _rect(slide, MARGIN, Inches(2.9), Inches(1.4), Pt(5), sub if style.is_dark else style.on_accent)
    _, tf = _tb(slide, MARGIN, Inches(3.15), Inches(10.5), Inches(2.2))
    _para(tf, s.title or "谢谢", style, style.pt_section, ink, bold=True, first=True,
          space_after=8, line_spacing=1.02, display=True)
    if s.subtitle:
        _para(tf, s.subtitle, style, style.pt_heading, sub, space_after=0, line_spacing=1.12)


_ROOT = Path(__file__).resolve().parents[1]
# harvest / 生图落盘目录名和 PPT 默认 embed 目录常对不上(卷七十九续 · 脑科学 PPT 实测)。
# 给出兜底:image 只是个文件名、here/文件名 又不存在时,按 basename 扫这些常见素材目录。
_IMG_SEARCH_DIRS = (
    _ROOT / "data" / "presentations" / "_assets",
    _ROOT / "data" / "presentations" / "generated",
    _ROOT / "data" / "workshop" / "outputs",
)
_BASENAME_CACHE: dict = {}


def _find_by_basename(name: str) -> Optional[Path]:
    """在常见素材目录里按文件名找 · 治"harvest 目录名和 embed 目录对不上"。
    只缓存命中(且用前复查存在)· 未命中不缓存 · 保证之后新落盘的图仍能被找到。"""
    if not name:
        return None
    hit = _BASENAME_CACHE.get(name)
    if hit is not None and hit.exists():
        return hit
    for d in _IMG_SEARCH_DIRS:
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.name == name:
                _BASENAME_CACHE[name] = f
                return f
    return None


def _resolve_img(image: Optional[str], here: Optional[Path]) -> Optional[Path]:
    if not image:
        return None
    p = Path(image)
    if p.is_absolute():
        return p
    # ① 优先 embed 目录(here / 相对路径)
    if here:
        cand = Path(here) / image
        if cand.exists():
            return cand
    # ② here 里没有 → 按 basename 兜底搜常见素材目录(harvest 目录名对不上时救场)
    hit = _find_by_basename(Path(image).name)
    if hit is not None:
        return hit
    return p
