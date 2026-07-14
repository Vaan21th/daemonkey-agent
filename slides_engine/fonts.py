"""
slides_engine/fonts.py
=======================

读用户的字体库 · 挑一套更"高级"的字体 —— 字体是设计感的一半。

Windows 默认只有微软雅黑,平。但很多人装过 MiSans / 思源黑体 / 阿里普惠 / 得意黑(Smiley Sans)
这类设计感强的免费字体。这个模块:
  1. 枚举系统已装字体(Windows 注册表 + 字体目录 · macOS/Linux 扫字体目录)
  2. 按优先级挑:标题(display)/ 正文(body)/ 拉丁 三档,选到第一款装了的
  3. 都没有 → 退回微软雅黑 / Segoe UI(永远有)

只返回"字体族名"给 python-pptx 用(PowerPoint 按名字找字体)。结果缓存,避免每页重扫。
"""
from __future__ import annotations

import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Set

# 优先级:越靠前越"高级" · 名字用 PowerPoint 认得的字体族名
# 匹配时两边都做"归一化"(去空格/下划线/连字符/点)· 所以带不带空格都能命中
_CJK_DISPLAY = [
    "得意黑", "Smiley Sans", "Smiley Sans Oblique",
    "阿里巴巴普惠体 3.0", "Alibaba PuHuiTi 3.0", "阿里巴巴普惠体 2.0", "阿里巴巴普惠体",
    "MiSans", "MiSans VF", "HarmonyOS Sans SC", "OPPO Sans 4.0",
    "思源黑体 CN", "Source Han Sans CN", "Source Han Sans SC",
    "Noto Sans SC", "Noto Sans CJK SC",
    "苹方-简", "PingFang SC", "YYB Sans", "汉仪中黑", "DengXian", "等线",
    "微软雅黑", "Microsoft YaHei",
]
_CJK_BODY = [
    "MiSans", "HarmonyOS Sans SC", "阿里巴巴普惠体 3.0", "Alibaba PuHuiTi 3.0",
    "思源黑体 CN", "Source Han Sans CN", "Source Han Sans SC",
    "Noto Sans SC", "Noto Sans CJK SC",
    "OPPO Sans 4.0", "苹方-简", "PingFang SC", "YYB Sans", "DengXian", "等线",
    "微软雅黑", "Microsoft YaHei",
]
_LATIN = [
    "Inter", "Inter Display", "Poppins", "Montserrat", "SF Pro Display",
    "Artifakt Element", "HarmonyOS Sans", "Bahnschrift",
    "Segoe UI Variable Display", "Segoe UI", "Helvetica Neue", "Arial",
]

_FALLBACK = {"cjk_display": "微软雅黑", "cjk_body": "微软雅黑", "latin": "Segoe UI"}


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-.]+", "", (s or "").lower())


def _installed_names() -> Set[str]:
    """收集所有已装字体名 + 字体文件名(原始 · 未归一化)。"""
    names: Set[str] = set()
    if sys.platform.startswith("win"):
        try:
            import winreg
            for root, sub in (
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
            ):
                try:
                    with winreg.OpenKey(root, sub) as k:
                        i = 0
                        while True:
                            try:
                                name, val, _ = winreg.EnumValue(k, i)
                            except OSError:
                                break
                            names.add(name); names.add(str(val)); i += 1
                except OSError:
                    pass
        except Exception:
            pass
    # 目录扫描(所有平台兜底 · macOS/Linux 主路径)
    dirs: List[Path] = []
    if sys.platform.startswith("win"):
        dirs = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts"]
    elif sys.platform == "darwin":
        dirs = [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library/Fonts"]
    else:
        dirs = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
                Path.home() / ".local/share/fonts"]
    for d in dirs:
        try:
            if d and d.exists():
                for f in d.rglob("*"):
                    if f.suffix.lower() in (".ttf", ".otf", ".ttc", ".otc"):
                        names.add(f.stem)
        except Exception:
            pass
    return names


def _pick(prefs: List[str], blob: str, fallback: str) -> str:
    for fam in prefs:
        if _norm(fam) in blob:
            return fam
    return fallback


@lru_cache(maxsize=1)
def pick_fonts() -> Dict[str, str]:
    """挑一套 {cjk_display, cjk_body, latin} · 结果缓存。 归一化子串匹配(带不带空格都命中)。"""
    try:
        names = _installed_names()
    except Exception:
        return dict(_FALLBACK)
    if not names:
        return dict(_FALLBACK)
    blob = "|".join(_norm(n) for n in names)   # "|" 隔开 · 防跨条误命中
    return {
        "cjk_display": _pick(_CJK_DISPLAY, blob, _FALLBACK["cjk_display"]),
        "cjk_body": _pick(_CJK_BODY, blob, _FALLBACK["cjk_body"]),
        "latin": _pick(_LATIN, blob, _FALLBACK["latin"]),
    }


# 按"字体性格"(font_role)偏选 —— 让故障=等宽、手绘=手写、编辑=衬线更到位
_MONO = ["Cascadia Code", "Cascadia Mono", "JetBrains Mono", "Sarasa Mono SC",
         "更纱黑体 Mono SC", "Fira Code", "Source Code Pro", "Consolas", "DejaVu Sans Mono"]
_HAND_LATIN = ["Caveat", "Gochi Hand", "Segoe Print", "Ink Free", "Bradley Hand",
               "Comic Sans MS", "Segoe Script"]
_HAND_CJK = ["华文行楷", "STXingkai", "方正静蕾简体", "方正卡通简体", "汉仪秀英体",
             "手札体-简", "华文琥珀", "楷体", "KaiTi", "STKaiti"]
_SERIF_LATIN = ["Playfair Display", "Georgia", "Garamond", "Times New Roman"]
_SERIF_CJK = ["思源宋体 CN", "Source Han Serif CN", "Source Han Serif SC", "Noto Serif SC",
              "方正书宋", "宋体", "SimSun", "STSong"]


def pick_fonts_for(role: str = "sans") -> Dict[str, str]:
    """在 pick_fonts() 基础上按 font_role 偏选(mono/hand/serif)· 找不到就回落无衬线选择。"""
    base = dict(pick_fonts())
    role = (role or "sans").lower()
    if role == "sans":
        return base
    try:
        names = _installed_names()
        blob = "|".join(_norm(n) for n in names)
    except Exception:
        return base
    if role == "mono":
        base["latin"] = _pick(_MONO, blob, "Consolas")
    elif role == "hand":
        base["latin"] = _pick(_HAND_LATIN, blob, base["latin"])
        h = _pick(_HAND_CJK, blob, "楷体")            # 楷体在 Windows 几乎必装 · 手写感兜底
        base["cjk_display"] = base["cjk_body"] = h
    elif role == "serif":
        base["latin"] = _pick(_SERIF_LATIN, blob, "Georgia")
        sc = _pick(_SERIF_CJK, blob, base["cjk_body"])
        base["cjk_display"] = base["cjk_body"] = sc
    return base


def describe() -> str:
    f = pick_fonts()
    return f"标题 {f['cjk_display']} · 正文 {f['cjk_body']} · 拉丁 {f['latin']}"
