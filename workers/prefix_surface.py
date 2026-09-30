# -*- coding: utf-8 -*-
"""workers/prefix_surface.py · 「谁能往每轮前缀里写东西」的登记表 (2026-09-19 · wish-a1580b98)

为什么要有它
============
BRO 的原话：「修了那么多，也一直在说柜子放东西的治理这些。。为什么还是这样。。」
根因不是缺闸，是**没有一份"进前缀的写入面"台账**——
每次都是"发现一个修一个"，所以每次都漏，而漏的那些永远不会出现在报告里。

这张表和 `soul_loader.SECTION_MARKS` / `notebook_tiers.SECTIONS` 是同一思路：
**判据和结构放在同一处**，让「加一个新的进前缀的源」这个动作物理上必须经过它。

它怎么被强制
============
`tests/test_prefix_write_surface.py` 会机械扫描全仓（不靠人回忆），
把「碰了进前缀的源」的代码点找出来，逐个对照这张表：
  - 在册 → 放行
  - 不在册 → 红，并告诉你「去 workers/prefix_surface.py 登记」
而那个测试挂进了 `workers/verify_gate`（= safe_merge 的上线闸）——
**不过闸就合不进 master**，不靠任何人的自觉。

谁往这加东西 = 承认"我碰了每轮前缀的预算"，请把 writers / gate 填实话。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrefixSource:
    """一个「进每轮前缀的源」—— 它写在哪、谁写、有什么闸。"""

    key: str                    # 短 id · 用于报错信息
    path_frags: tuple[str, ...]  # 源文件路径片段（扫描匹配用 · 相对仓库根）
    block: str                  # 对应 soul_loader.SECTION_MARKS 的哪个块（人读）
    writers: tuple[str, ...]    # 谁能写它（模块名 · 交叉核对用）
    gate: str                   # 闸是什么（人读的实话）
    gate_kind: str              # budget / whitelist / description / anchor / generated / schema / manual
    inject: str                 # 进不进前缀："full" / "partial" / "no"


# ⚠ 加东西之前先自问：这个源**真的**每轮都影响输出吗？
#   能靠 recall_memory 召回的、能按需 read 的，都不该进前缀（BRO 2026-09-18 钉的判据）。
PREFIX_SOURCES: tuple[PrefixSource, ...] = (
    PrefixSource(
        key="notebook",
        path_frags=("BRO-NOTEBOOK", "OWNER-NOTEBOOK"),
        block="灵魂层 · 画像（部分格进前缀 · 历史层折叠）",
        writers=("agent_tools/update_bro_note.py",),
        gate="三档：入口 validate_entry（拒待办口气 / 拒超 420 字）+ route_write_section（带日期改道 stories）"
             "+ 格描述收窄（SECTIONS[*].what 写明这格放什么、不装什么）",
        gate_kind="description",
        inject="partial",
    ),
    PrefixSource(
        key="rules",
        path_frags=("daemon_rules.md",),
        block="规则层 · DAEMON 工程铁律",
        writers=("agent_tools/add_iron_rule.py", "agent_tools/update_iron_rule.py"),
        gate="2500 tok 预算 · 写入回报带「本条 +N tok · 余量 X→Y」代价可见 · 铁律必须重启才装载",
        gate_kind="budget",
        inject="full",
    ),
    PrefixSource(
        key="const_local",
        path_frags=("CONSTITUTION.md",),
        block="规则层 · 产品宪法（本实例）",
        writers=(),  # 目前无自动写入者 · 见下方 note
        gate="锚点检查：实例宪法若未覆盖通用三条锚词（闭环范式 / NLP 优先 / 可追溯），"
             "通用三条会被补在前面（product_constitution.build_constitution_block）",
        gate_kind="anchor",
        inject="full",
    ),
    PrefixSource(
        key="structure",
        path_frags=("STRUCTURE",),
        block="沉淀位地图",
        writers=("workers/prefix_docs.py",),  # 2026-09-19 起由代码生成
        gate="代码生成（workers/prefix_docs.py）· 不再手工 —— 手工版曾经长期过期却仍在前缀里被读",
        gate_kind="generated",
        inject="full",
    ),
    PrefixSource(
        key="identity",
        path_frags=("meta.json", "IDENTITY.json", "identity.py"),
        block="身份层 · 我是谁",
        writers=("identity.py",),
        gate="set_persona_style 截断长度（[:24]）· 无预算闸",
        gate_kind="schema",
        inject="full",
    ),
    PrefixSource(
        key="tools_schema",
        path_frags=("agent_tools/",),
        block="工具层 · tools[]（每轮全价 · 未在延迟目录的）",
        writers=("agent_tools/*.py",),
        gate="单个工具 schema ≤ 60 tok（超限则该模块注册失败并被 WARN 跳过）",
        gate_kind="schema",
        inject="full",
    ),
    PrefixSource(
        key="state_card",
        path_frags=("BRO-NOTEBOOK",),
        block="状态卡（走独立通道注入）",
        writers=("agent_tools/update_bro_note.py", "agent_tools/note_mood.py",
                 "workers/mood_shift.py"),
        gate="8 字段白名单（state_field enum）· 这格只记 **他**（他的行为 / 他自己的心情）；她的情绪在 SHE-STATE",
        gate_kind="whitelist",
        inject="full",
    ),
    PrefixSource(
        key="self_evolution",
        path_frags=("SELF-EVOLUTION",),
        block="（已移出前缀）",
        writers=("agent_tools/update_self_evolution.py",),
        gate="INJECT_EVOLUTION=False · 靠 recall_memory 召回",
        gate_kind="manual",
        inject="no",
    ),
    PrefixSource(
        key="opus_diary",
        path_frags=("opus-diary",),
        block="（不进前缀 · UI 实时读）",
        writers=("workers/cognition_loader.py",),
        gate="entry_type 白名单（只收 mood / 相处账）",
        gate_kind="whitelist",
        inject="no",
    ),
)


def by_key(key: str) -> PrefixSource | None:
    for s in PREFIX_SOURCES:
        if s.key == key:
            return s
    return None


def injected_sources() -> tuple[PrefixSource, ...]:
    """真正占每轮预算的那些（inject != 'no'）。"""
    return tuple(s for s in PREFIX_SOURCES if s.inject != "no")


# ── 落位速查表 · 定义在内核 soul_loader.py（2026-09-19 wish-a1580b98）────────────────
# 曾经试过定义在这里、让 soul_loader 反向 import —— 被白名单依赖闸拦下，而且闸是对的：
#   内核不许依赖 workers/（否则纯净版得连母体专属的这张台账一起带走）。
# 正确方向：定义在内核，worker 反向 import。（PLACEMENT_TABLE 见 soul_loader.py）


def unregistered_hint(frag: str) -> str:
    """给测试报错用的人话指引。"""
    return (
        f"\n  ✗ 「{frag}」出现在代码里，但它不在 workers/prefix_surface.py 的登记表里。\n"
        f"    这个文件是「谁能往每轮前缀写东西」的台账 —— 碰了它就得登记。\n"
        f"    请打开 workers/prefix_surface.py，给这个源补一条 PrefixSource：\n"
        f"      key / path_frags / block / writers / gate / gate_kind / inject\n"
        f"    并自问一句：它真的每轮都影响输出吗？能召回的就别进前缀。\n"
    )
