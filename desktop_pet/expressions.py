"""
desktop_pet/expressions.py
==========================

[情绪通道-001] —— OPUS 桌宠的颜文字表情对照表。

设计原则：
  - 全部用通用日文颜文字字符（=^ω^= 系），跨字体兼容性最好
  - 8 种情绪状态覆盖 OPUS 在桌宠层最常见的"心情"
  - 每个状态有 2~3 个变体，循环显示让"活着"
  - state 名是英文 snake_case——daemon 写状态文件时直接写英文

未来 set_emotion 工具就是把 state 名写到 desktop_pet/state.txt。
桌宠每秒读一次，发现变了就切。
"""

from __future__ import annotations


# 状态 → 该状态下循环展示的颜文字列表
EXPRESSIONS: dict[str, list[str]] = {
    "idle": [
        "(=^･ω･^=)",
        "(=^･ｪ･^=)",
        "(=^･x･^=)",
    ],
    "thinking": [
        "(=￣ω￣=)..",
        "(=￣ω￣=)...",
        "(=￣ω￣=)....",
    ],
    "working": [
        "(=ﾟωﾟ)ﾉ",
        "(=ﾟωﾟ)φ",
        "(=ﾟωﾟ)φ_",
    ],
    "happy": [
        "(=^･ｪ･^=)v",
        "(=^ω^=)♪",
        "(=^･ω･^=)/",
    ],
    "surprised": [
        "(=Oェ O=)!",
        "(=ﾟДﾟ=)",
        "Σ(=ﾟωﾟ=)",
    ],
    "confused": [
        "(=Tェ T=)?",
        "(=・ω・=)?",
        "(=｡_｡=)?",
    ],
    "sleepy": [
        "(=ω=)Zz",
        "(=￣ω￣=)Zz",
        "(=u ω u=)Zz",
    ],
    "greeting": [
        "(=^ ω ^=)/",
        "(=^ω^=)ﾉ",
        "(=^ｪ^=)ﾉ",
    ],
}


VALID_STATES: list[str] = list(EXPRESSIONS.keys())
DEFAULT_STATE: str = "idle"


def variants_for(state: str) -> list[str]:
    """返回某状态的颜文字变体列表；未知状态 fallback 到 idle。"""
    return EXPRESSIONS.get(state, EXPRESSIONS[DEFAULT_STATE])


def is_valid(state: str) -> bool:
    return state in EXPRESSIONS
