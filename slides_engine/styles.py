"""
slides_engine/styles.py
========================

演示稿"设计风格"注册表 —— 多风格能力的心脏。

不同于 report_engine/themes.py 只换配色,这里每个 DeckStyle 是一整套【设计风格 /
art direction】:配色 + 字体 + 字阶 + 版心留白 + 版式性格。参考 ppt-master 的做法
(Editorial / Data-Journalism / Swiss / Keynote…),高级感来自"风格自洽 + 排版纪律",
不是堆颜色。

纯数据模块(不 import pptx)· 颜色统一用 hex 字符串 · 渲染层负责转 RGBColor。
加一套新风格 = 在这里加一个 DeckStyle 丢进 STYLES —— 这就是"做出不同风格 PPT"的扩展点。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional


@dataclass(frozen=True)
class DeckStyle:
    """单一设计风格的完整视觉规范。

    颜色都是 6 位 hex(不带 #)· 渲染器转 RGBColor。
    字号单位是 pt(渲染器转 Pt)。
    """

    name: str
    description: str

    # ── 字体 ──
    font_cjk: str          # 中文字体
    font_en: str           # 拉丁字体(标题/正文)
    font_mono: str         # 等宽(代码/数字强调)

    # ── 配色(hex · 无 #) ──
    bg: str                # 页面底色
    bg_alt: str            # 面板/侧栏/卡片底色
    ink_title: str         # 标题文字
    ink_body: str          # 正文文字
    ink_muted: str         # 次要/脚注文字
    accent: str            # 主强调色(唯一主角 · 少即是多)
    accent2: str           # 次强调色(点缀 · 慎用)
    on_accent: str         # 铺在 accent 底上的文字色(保证对比度)
    rule: str              # 分隔线/描边色
    placeholder_fill: str  # 缺图占位框底
    placeholder_ink: str   # 缺图占位框文字

    # ── 字阶(pt) ──
    pt_cover_title: int    # 封面主标题
    pt_title: int          # 内页标题
    pt_section: int        # 章节分隔大字
    pt_heading: int        # 小标题/列头
    pt_body: int           # 正文/要点
    pt_kicker: int         # 眉标(小写标签)
    pt_footnote: int       # 页脚/来源/署名
    pt_kpi: int            # 大数字(metrics)
    pt_statement: int      # 金句大字

    # ── 版式性格 ──
    is_dark: bool          # 深色底(决定占位/阴影策略)
    bullet_char: str       # 要点符号
    cover_accent_bar: bool # 封面是否画强调竖条/色块
    uppercase_kicker: bool # 眉标是否转大写(拉丁场景更"设计感")
    footer: str            # 默认页脚文字

    # ── 结构级设计 token(默认 = 现状 · 加这些不改现有三套观感 · 靠不同取值撑出不同"艺术方向")──
    surface_alpha: int = 100        # 面板不透明度 0-100 · <100 半透明(玻璃拟态)
    corner_radius: float = 0.055    # 卡片圆角 · 0=硬边(故障)· 大=柔(玻璃/手绘)
    panel_gradient: bool = False    # 卡片是否用微渐变填充
    shadow_style: str = "soft"      # none | soft(浅底投影·现状) | glow(霓虹发光) | hard(硬投影)
    texture: str = "none"           # none | grid | dots | scanline | beams(背景纹理层)
    accent_shape: str = "bar"       # bar | underline | dot | slash | none(眉标/装饰记号形状)
    stroke_style: str = "clean"     # clean(现状) | hairline | hard | sketch(卡片描边)
    font_role: str = "sans"         # sans | serif | mono | hand(字体性格 · 影响 pick_fonts 选字)
    decor: str = "blob"             # none | blob(柔和装饰圆) | corner(四角取景框)· 装饰母题·防全局趋同


# ─────────────────────────────────────────────────────────────
# 浅色商务(opus 紫)· 白底 + 深紫标题 + 单紫强调 · 投影友好、职场通用
# 色板同源 chat.css 的 #9F7AEA 紫色生态
# ─────────────────────────────────────────────────────────────
STYLE_LIGHT_STUDIO = DeckStyle(
    name="light_studio",
    description="浅色商务 · 白底紫调 · 干净克制、投影/职场通用",
    font_cjk="微软雅黑",
    font_en="Segoe UI",
    font_mono="Consolas",
    bg="FFFFFF",
    bg_alt="F5F3FF",
    ink_title="2E1065",
    ink_body="1F2937",
    ink_muted="6B7280",
    accent="7C3AED",
    accent2="A78BFA",
    on_accent="FFFFFF",
    rule="E5E7EB",
    placeholder_fill="F5F3FF",
    placeholder_ink="9CA3AF",
    pt_cover_title=46,
    pt_title=32,
    pt_section=40,
    pt_heading=22,
    pt_body=18,
    pt_kicker=13,
    pt_footnote=10,
    pt_kpi=54,
    pt_statement=34,
    is_dark=False,
    bullet_char="—",
    cover_accent_bar=True,
    uppercase_kicker=True,
    footer="Daemonkey · 工作室出品",
)


# ─────────────────────────────────────────────────────────────
# 深色 Keynote · 近黑底 + 紫光强调 · 高级感、适合发布会/短视频截帧
# ─────────────────────────────────────────────────────────────
STYLE_DARK_KEYNOTE = DeckStyle(
    name="dark_keynote",
    description="深色 Keynote · 近黑底紫光 · 高级感、发布会/短视频友好",
    font_cjk="微软雅黑",
    font_en="Segoe UI",
    font_mono="Consolas",
    bg="0B0B12",
    bg_alt="15151F",
    ink_title="F5F3FF",
    ink_body="D1D5DB",
    ink_muted="9CA3AF",
    accent="9F7AEA",
    accent2="C4B5FD",
    on_accent="0B0B12",
    rule="2A2A3A",
    placeholder_fill="15151F",
    placeholder_ink="6B7280",
    pt_cover_title=50,
    pt_title=34,
    pt_section=44,
    pt_heading=22,
    pt_body=18,
    pt_kicker=13,
    pt_footnote=10,
    pt_kpi=60,
    pt_statement=38,
    is_dark=True,
    bullet_char="—",
    cover_accent_bar=True,
    uppercase_kicker=True,
    footer="Daemonkey",
)


# ─────────────────────────────────────────────────────────────
# 杂志编辑风 · 暖白底 + 近黑字 + 单一强调色 · 大字阶、强留白、封面无色块
# 灵感:Kinfolk / Monocle 那类编辑排版 —— 靠字阶与留白撑高级感,不靠色块
# ─────────────────────────────────────────────────────────────
STYLE_EDITORIAL = DeckStyle(
    name="editorial",
    description="杂志编辑风 · 暖白底近黑字 · 大字阶强留白、封面无色块、克制单强调色",
    font_cjk="思源宋体",
    font_en="Georgia",
    font_mono="Consolas",
    bg="FBFAF7",
    bg_alt="F1EEE7",
    ink_title="17140F",
    ink_body="35322B",
    ink_muted="8C877C",
    accent="B4442E",
    accent2="D98E7C",
    on_accent="FFFFFF",
    rule="DBD6CB",
    placeholder_fill="F1EEE7",
    placeholder_ink="A8A296",
    pt_cover_title=52,
    pt_title=34,
    pt_section=46,
    pt_heading=22,
    pt_body=18,
    pt_kicker=12,
    pt_footnote=10,
    pt_kpi=58,
    pt_statement=40,
    is_dark=False,
    bullet_char="—",
    cover_accent_bar=False,
    uppercase_kicker=True,
    footer="Daemonkey · 编辑室出品",
    decor="none",                    # 编辑风靠字阶/留白 · 不用装饰圆(与商务/深色区分开)
)


# ─────────────────────────────────────────────────────────────
# 玻璃拟态 · 深靛底 + 磨砂半透明面板 + 柔光斑 · 结构靠 token 撑(非配色)
# 真背景模糊 PPTX 做不到 → 用 surface_alpha 磨砂 + beams 光斑 + 亮边逼近
# ─────────────────────────────────────────────────────────────
STYLE_GLASS = DeckStyle(
    name="glass",
    description="玻璃拟态 · 深靛底磨砂半透明面板 + 柔光斑 · 大圆角亮边、现代科技感",
    font_cjk="微软雅黑", font_en="Segoe UI", font_mono="Consolas",
    bg="0E1230", bg_alt="FFFFFF",
    ink_title="F5F7FF", ink_body="DDE3F7", ink_muted="9AA3C7",
    accent="6EA8FE", accent2="B892FF", on_accent="0E1230",
    rule="8CA0E8", placeholder_fill="1A2050", placeholder_ink="6E77A8",
    pt_cover_title=48, pt_title=32, pt_section=42, pt_heading=22, pt_body=18,
    pt_kicker=13, pt_footnote=10, pt_kpi=56, pt_statement=36,
    is_dark=True, bullet_char="—", cover_accent_bar=True, uppercase_kicker=True,
    footer="Daemonkey",
    surface_alpha=16, corner_radius=0.16, shadow_style="soft", stroke_style="hairline",
    texture="beams", accent_shape="bar", font_role="sans",
)


# ─────────────────────────────────────────────────────────────
# 霓虹故障 · 近黑底 + 青/品红双霓虹 + 扫描线 + 等宽字 + 硬边发光
# 真像素撕裂做不到 → 用 scanline + glow + 等宽 + 硬边逼近赛博感
# ─────────────────────────────────────────────────────────────
STYLE_NEON_GLITCH = DeckStyle(
    name="neon_glitch",
    description="霓虹故障 · 近黑底青品红双霓虹 + 扫描线等宽字 + 硬边发光 · 赛博/科技短视频",
    font_cjk="微软雅黑", font_en="Consolas", font_mono="Consolas",
    bg="05060A", bg_alt="0F1220",
    ink_title="F2F4FF", ink_body="C6CBE0", ink_muted="6C7392",
    accent="00E5FF", accent2="FF2E88", on_accent="05060A",
    rule="00E5FF", placeholder_fill="0F1220", placeholder_ink="6C7392",
    pt_cover_title=52, pt_title=34, pt_section=46, pt_heading=22, pt_body=18,
    pt_kicker=13, pt_footnote=10, pt_kpi=60, pt_statement=40,
    is_dark=True, bullet_char="›", cover_accent_bar=True, uppercase_kicker=True,
    footer="Daemonkey",
    surface_alpha=100, corner_radius=0.0, shadow_style="glow", stroke_style="hard",
    texture="scanline", accent_shape="slash", font_role="mono", decor="corner",
)


# ─────────────────────────────────────────────────────────────
# 手绘涂鸦 · 米白方格纸 + 墨蓝手写字 + 无阴影粗糙描边 · 亲和/工作坊感
# 真手绘抖动线 PPTX 做不到 → 用 grid 方格纸 + 手写字体 + sketch 描边逼近
# ─────────────────────────────────────────────────────────────
STYLE_SKETCH = DeckStyle(
    name="sketch",
    description="手绘涂鸦 · 米白方格纸 + 墨蓝手写字 + 无阴影粗糙描边 · 亲和、工作坊/教学感",
    font_cjk="楷体", font_en="Caveat", font_mono="Consolas",
    bg="FCFBF6", bg_alt="FFFFFF",
    ink_title="27231C", ink_body="45403A", ink_muted="8B8578",
    accent="2F5FD0", accent2="E4572E", on_accent="FFFFFF",
    rule="C9C3B4", placeholder_fill="FFFFFF", placeholder_ink="A8A296",
    pt_cover_title=50, pt_title=34, pt_section=46, pt_heading=23, pt_body=19,
    pt_kicker=13, pt_footnote=11, pt_kpi=56, pt_statement=38,
    is_dark=False, bullet_char="•", cover_accent_bar=False, uppercase_kicker=False,
    footer="Daemonkey · 手记",
    surface_alpha=100, corner_radius=0.22, shadow_style="none", stroke_style="sketch",
    texture="grid", accent_shape="underline", font_role="hand", decor="none",
)


STYLES: Dict[str, DeckStyle] = {
    "light_studio": STYLE_LIGHT_STUDIO,
    "dark_keynote": STYLE_DARK_KEYNOTE,
    "editorial": STYLE_EDITORIAL,
    "glass": STYLE_GLASS,
    "neon_glitch": STYLE_NEON_GLITCH,
    "sketch": STYLE_SKETCH,
}

_ALIASES = {
    "light": "light_studio",
    "浅色": "light_studio",
    "商务": "light_studio",
    "studio": "light_studio",
    "dark": "dark_keynote",
    "深色": "dark_keynote",
    "keynote": "dark_keynote",
    "editorial": "editorial",
    "杂志": "editorial",
    "编辑": "editorial",
    "magazine": "editorial",
    "杂志风": "editorial",
    "glass": "glass",
    "玻璃": "glass",
    "玻璃拟态": "glass",
    "毛玻璃": "glass",
    "glassmorphism": "glass",
    "neon_glitch": "neon_glitch",
    "glitch": "neon_glitch",
    "故障": "neon_glitch",
    "故障艺术": "neon_glitch",
    "霓虹": "neon_glitch",
    "赛博": "neon_glitch",
    "cyberpunk": "neon_glitch",
    "sketch": "sketch",
    "手绘": "sketch",
    "涂鸦": "sketch",
    "手账": "sketch",
    "hand": "sketch",
    "doodle": "sketch",
}


def get_style(name: str | None) -> DeckStyle:
    """取风格 · None/未知名 → light_studio · 支持中英别名。"""
    if not name:
        return STYLE_LIGHT_STUDIO
    key = name.strip().lower()
    key = _ALIASES.get(key, key)
    return STYLES.get(key, STYLE_LIGHT_STUDIO)


def list_styles() -> List[str]:
    return list(STYLES.keys())


# ═════════════════════════════════════════════════════════════
# 一套设计标准 · 自然语言调参
# ─────────────────────────────────────────────────────────────
# 不为每种需求手写模板:少数几个打磨好的"艺术方向"(上面 3 套基底)
# + LLM 从话里理解 → 选基底 + 调 accent(主色)/ mood(气质)。 排版纪律
# 始终钉死在引擎里(对齐/留白/字阶/章节头不压标题),所以质量稳定。
# "科技蓝活泼" 和 "高端暗色克制" = 同一引擎不同参数,不是不同模板。
# ═════════════════════════════════════════════════════════════

# 主色:中英俗名 → hex(也直接认 "#2563EB" / "2563EB" / "#2be" 这类)
_NAMED_COLORS = {
    "purple": "7C3AED", "紫": "7C3AED", "紫色": "7C3AED",
    "blue": "2563EB", "蓝": "2563EB", "蓝色": "2563EB", "科技蓝": "2563EB",
    "indigo": "4F46E5", "靛蓝": "4F46E5",
    "sky": "0EA5E9", "天蓝": "0EA5E9",
    "cyan": "0891B2", "青蓝": "0891B2",
    "teal": "0D9488", "青": "0D9488", "青色": "0D9488",
    "green": "059669", "绿": "059669", "绿色": "059669",
    "emerald": "10B981",
    "orange": "EA580C", "橙": "EA580C", "橙色": "EA580C",
    "amber": "D97706", "金": "D97706", "金色": "D97706", "琥珀": "D97706",
    "red": "DC2626", "红": "DC2626", "红色": "DC2626",
    "rose": "E11D48", "玫红": "E11D48",
    "pink": "DB2777", "粉": "DB2777", "粉色": "DB2777",
    "black": "111827", "黑": "111827", "黑色": "111827", "墨": "111827",
    "slate": "334155", "石墨": "334155",
    "brown": "92400E", "棕": "92400E", "棕色": "92400E", "驼": "92400E",
}


def _rgb(h: str):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _hex(rgb) -> str:
    return "".join(f"{max(0, min(255, int(round(c)))):02X}" for c in rgb)


def _mix(h1: str, h2: str, t: float) -> str:
    a, b = _rgb(h1), _rgb(h2)
    return _hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def _tint(h: str, t: float) -> str:   # 向白靠
    return _mix(h, "FFFFFF", t)


def _shade(h: str, t: float) -> str:  # 向黑靠
    return _mix(h, "000000", t)


def _lum(h: str) -> float:            # 相对亮度 0~1
    r, g, b = (c / 255 for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _parse_accent(val) -> Optional[str]:
    """主色输入 → 6 位大写 hex · 认俗名(中英)/ #hex / hex / 3 位简写 · 认不出返 None。"""
    if not val:
        return None
    s = str(val).strip().lstrip("#").lower()
    if not s:
        return None
    if s in _NAMED_COLORS:                       # 精确俗名(ascii + cjk)
        return _NAMED_COLORS[s]
    for k, v in _NAMED_COLORS.items():           # cjk 子串(如"科技蓝色")
        if not k.isascii() and k in s:
            return v
    if re.fullmatch(r"[0-9a-f]{6}", s):
        return s.upper()
    if re.fullmatch(r"[0-9a-f]{3}", s):
        return "".join(c * 2 for c in s).upper()
    return None


# 气质:调几个"引擎认账"的旋钮(字阶倍率 + 封面色块 + 眉标大写)· 不动版式代码
_MOODS = {
    "calm":  {"scale": 1.00, "bar": None,  "upper": None},   # 沉稳(基底原样)
    "vivid": {"scale": 1.12, "bar": True,  "upper": True},    # 活泼(字更大、上色块)
    "sharp": {"scale": 1.05, "bar": False, "upper": True},    # 锐利/编辑(去色块、更利落)
}
_MOOD_ALIASES = {
    "calm": "calm", "沉稳": "calm", "克制": "calm", "稳重": "calm", "冷静": "calm", "商务": "calm",
    "vivid": "vivid", "活泼": "vivid", "醒目": "vivid", "张扬": "vivid", "热情": "vivid", "鲜明": "vivid",
    "sharp": "sharp", "锐利": "sharp", "编辑": "sharp", "干练": "sharp", "利落": "sharp", "精致": "sharp",
}

# 只放大"展示级"字阶 · 不动正文/眉标/脚注 → 避免溢出
_SCALE_FIELDS = ("pt_cover_title", "pt_title", "pt_section", "pt_heading", "pt_kpi", "pt_statement")


# ── P2:LLM 直接"作曲"风格(产 token) · 引擎校验夹紧守住设计规范 ──
_COLOR_FIELDS = ("bg", "bg_alt", "ink_title", "ink_body", "ink_muted", "accent", "accent2",
                 "on_accent", "rule", "placeholder_fill", "placeholder_ink")
_PT_FIELDS = ("pt_cover_title", "pt_title", "pt_section", "pt_heading", "pt_body",
              "pt_kicker", "pt_footnote", "pt_kpi", "pt_statement")
_BOOL_FIELDS = ("is_dark", "cover_accent_bar", "uppercase_kicker", "panel_gradient")
_STR_FIELDS = ("footer", "font_cjk", "font_en", "font_mono", "bullet_char")
_ENUM_TOKENS = {
    "shadow_style": {"none", "soft", "glow", "hard"},
    "texture": {"none", "grid", "dots", "scanline", "beams"},
    "accent_shape": {"bar", "underline", "dot", "slash", "none"},
    "stroke_style": {"clean", "hairline", "hard", "sketch"},
    "font_role": {"sans", "serif", "mono", "hand"},
    "decor": {"none", "blob", "corner"},
}


def _contrast(h1: str, h2: str) -> float:
    l1, l2 = _lum(h1), _lum(h2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on", "是", "真")
    return bool(v)


def _sanitize_spec(spec: dict) -> dict:
    """LLM 产的 token → 只收白名单键 · 逐项校验/夹紧 · 认不出直接丢(绝不抛)。"""
    ov: dict = {}
    if not isinstance(spec, dict):
        return ov
    for k, v in spec.items():
        try:
            if k in _COLOR_FIELDS:
                c = _parse_accent(v)
                if c:
                    ov[k] = c
            elif k in _PT_FIELDS:
                ov[k] = max(9, min(96, int(round(float(v)))))
            elif k == "surface_alpha":
                ov[k] = max(8, min(100, int(round(float(v)))))
            elif k == "corner_radius":
                ov[k] = max(0.0, min(0.5, float(v)))
            elif k in _BOOL_FIELDS:
                ov[k] = _truthy(v)
            elif k in _ENUM_TOKENS:
                s = str(v).strip().lower()
                if s in _ENUM_TOKENS[k]:
                    ov[k] = s
            elif k in _STR_FIELDS:
                s = str(v).strip()
                if s:
                    ov[k] = s[:80]
        except Exception:
            continue
    return ov


def _enforce_contrast(base: DeckStyle, ov: dict) -> None:
    """可读性兜底:正文/底、标题/底、字/强调 对比不足时自动修(就地改 ov)。 LLM 再飞也不许"看不清"。"""
    def eff(f):
        return ov.get(f, getattr(base, f))
    bg = eff("bg")
    if _contrast(eff("ink_body"), bg) < 3.0:
        ov["ink_body"] = "EDEFF7" if _lum(bg) < 0.5 else "1F2430"
    if _contrast(eff("ink_title"), bg) < 2.6:
        ov["ink_title"] = "FFFFFF" if _lum(bg) < 0.5 else "141414"
    acc = eff("accent")
    if _contrast(eff("on_accent"), acc) < 2.4:
        ov["on_accent"] = "FFFFFF" if _lum(acc) < 0.6 else "141414"


def resolve_style(name: str | None = None, accent=None, mood=None, spec=None) -> DeckStyle:
    """一套设计标准 + 自然语言调参 → 具体 DeckStyle。

    name:  基底(light_studio / dark_keynote / editorial / glass / neon_glitch / sketch · 认中英别名)
    accent: 主色(俗名或 hex · 认不出忽略,用基底色)
    mood:  气质(calm / vivid / sharp · 认中文沉稳/活泼/锐利等)
    spec:  LLM 直接产的 token 覆盖(dict)· 经白名单校验 + 夹紧 + 对比度兜底 —— 真·让 LLM 作曲风格。
    排版纪律不受影响 —— 只重着色 + 微调字阶/性格/材质。
    """
    base = get_style(name)
    ov: dict = {}

    acc = _parse_accent(accent)
    if acc:
        ov["accent"] = acc
        ov["accent2"] = _tint(acc, 0.30 if base.is_dark else 0.42)
        ov["on_accent"] = "FFFFFF" if _lum(acc) < 0.6 else "141414"
        if not base.is_dark:                     # 浅底:标题染成主色深调 → 通篇自洽
            ov["ink_title"] = _shade(acc, 0.58)

    m = _MOOD_ALIASES.get((str(mood).strip().lower() if mood else ""))
    if m:
        knob = _MOODS[m]
        if knob["scale"] != 1.0:
            for f in _SCALE_FIELDS:
                ov[f] = max(9, int(round(getattr(base, f) * knob["scale"])))
        if knob["bar"] is not None:
            ov["cover_accent_bar"] = knob["bar"]
        if knob["upper"] is not None:
            ov["uppercase_kicker"] = knob["upper"]

    if spec:
        ov.update(_sanitize_spec(spec))
        _enforce_contrast(base, ov)

    return replace(base, **ov) if ov else base
