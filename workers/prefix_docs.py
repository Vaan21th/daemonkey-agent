# -*- coding: utf-8 -*-
"""workers/prefix_docs.py · 沉淀位看板生成器 (2026-09-19 · wish-a1580b98)

治的是什么
==========
`data/cognition/STRUCTURE.md` 曾经是**纯手工文件** —— 全仓没有任何工具会写它。
结果：它写着几个月前的结构，代码改了 N 轮它没跟上，**而它还在每轮前缀里被读**。
BRO 的原话：「我已经完全看不懂了」——**拿一份过期说明对现在的系统，当然对不上。**

怎么治
======
让它**由代码生成**：
  - 层 / 块 / 注入与否 / 谁写 / 什么闸 → 全部从 `workers/prefix_surface.py`
    与 `soul_loader.SECTION_MARKS` / `notebook_tiers.SECTIONS` 现取
  - 文件结构：`<!-- AUTO-BEGIN -->` … `<!-- AUTO-END -->` 之间自动维护
  - 标记之外的内容（人写的补充、沿革说明）**原样保留**，生成时不会被冲掉

用法
====
    python -m workers.prefix_docs            # 重新生成（幂等）
    python -m workers.prefix_docs --check    # 只校验是否与当前代码一致（CI / 闸用）

`--check` 是给闸留的口子：看板过期 → 非零退出。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "data" / "cognition" / "STRUCTURE.md"

AUTO_BEGIN = "<!-- AUTO-BEGIN · 下面由 workers/prefix_docs.py 生成 · 改它请改代码 -->"
AUTO_END = "<!-- AUTO-END -->"

# 手工段的种子：首次生成时用（BRO 手写的那份内容的主干，之后归人维护）
_SEED_TAIL = """## 二·七 · 不进前缀的柜子（靠召回 / 按需读）

- `soul/SELF-EVOLUTION.md` · 成长档案 —— 靠 `recall_memory` 召回
- `data/cognition/opus-diary.md` · 心情图 / 相处账 —— UI 实时读
- `data/playbooks/` · 操作手册 —— 命中即自动检索注入
- `data/cognition/scenarios/` · 工艺合同 —— `read_scenario` 按需读
- 知识库 / 客户档案 / 信息雷达 / 工坊产物 / 心愿单 / 市集 —— 各自召回或界面读

**判据（BRO 2026-09-18 钉）**：能召回的就不进前缀。
前缀只留「每轮都可能影响输出、且召不回来」的东西。
"""


def _import_sources():
    from workers.prefix_surface import PREFIX_SOURCES, injected_sources
    return PREFIX_SOURCES, injected_sources


def _marks():
    try:
        from soul_loader import SECTION_MARKS
        return SECTION_MARKS
    except Exception:
        return {}


def build_auto_section() -> str:
    """生成自动段（纯函数 · 不写盘 · 方便 --check 比对）。"""
    PREFIX_SOURCES, injected = _import_sources()
    marks = _marks()
    n_inj = len(injected())
    total = len(PREFIX_SOURCES)

    L: list[str] = []
    from soul_loader import PLACEMENT_TABLE
    L.append("### 落位速查（模型每轮在结构段里看的就是下面这段 · 与 `soul_loader` 同源）")
    L.append("")
    L.append("```")
    L.append((PLACEMENT_TABLE or "").strip())
    L.append("```")
    L.append("")
    L.append("## 二·六 · 进前缀的写入面台账（自动生成 · 单一真相源）")
    L.append("")
    L.append(f"> 全仓共 **{total}** 个「每轮前缀的源」，其中 **{n_inj}** 个占每轮预算。")
    L.append("> 这张表由 `workers/prefix_docs.py` 从 `workers/prefix_surface.py` 生成。")
    L.append("> **加一个新的进前缀的源 = 必须去登记**，否则 `tests/test_prefix_write_surface.py` 红，")
    L.append("> 而那个测试挂在 `safe_merge` 上线闸上 —— 不过闸合不进 master。")
    L.append("")
    L.append("| 源 | 进前缀 | 对应块 | 谁写 | 闸 |")
    L.append("|---|---|---|---|---|")
    for s in PREFIX_SOURCES:
        inj = {"full": "✅ 整块", "partial": "◐ 部分", "no": "✗ 不进"}.get(s.inject, s.inject)
        writers = " · ".join(f"`{w}`" for w in s.writers) if s.writers else "**（无自动写入者）**"
        gate = s.gate.replace("|", "/")
        L.append(f"| `{s.key}` | {inj} | {s.block} | {writers} | {gate} |")
    L.append("")
    L.append(f"_闸类型图例：{('/'.join(sorted({s.gate_kind for s in PREFIX_SOURCES})))}_")
    L.append("")
    # 段头顺序（前缀里的真实出现顺序）
    if marks:
        L.append("### 前缀里的真实出现顺序（段头常量表 · `soul_loader.SECTION_MARKS`）")
        L.append("")
        for i, (k, line) in enumerate(marks.items(), 1):
            L.append(f"{i}. `{k}` → `{line}`")
        L.append("")
    L.append("### 判据（BRO 2026-09-18 钉）")
    L.append("")
    L.append("**能召回的就不进前缀。** 前缀只留「每轮都可能影响输出、且召不回来」的东西。")
    L.append("")
    L.append("一个格该不该装某条内容，自问：**把主语换成别人，这条还成立吗？**")
    L.append("成立 → 那是「关于他」；不成立（描述的是我们做的东西）→ 走 wish / 代码注释。")
    L.append("")
    return "\n".join(L)


def render(full_text: str | None = None) -> str:
    """把自动段合进全文（替换标记区间 · 标记外原样保留）。"""
    auto = build_auto_section()
    if full_text is None:
        full_text = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
    if AUTO_BEGIN in full_text and AUTO_END in full_text:
        pre = full_text.split(AUTO_BEGIN)[0]
        post = full_text.split(AUTO_END, 1)[1]
        return pre + AUTO_BEGIN + "\n\n" + auto + AUTO_END + post
    # 首次：保留原文（当手工段）+ 自动段插在前面
    head = full_text.strip()
    if not head:
        head = "# 沉淀位地图 · 完整定义\n"
    return (head + "\n\n" + AUTO_BEGIN + "\n\n" + auto + AUTO_END + "\n\n" + _SEED_TAIL)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    now = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
    want = render(now)
    if check:
        if want.strip() != now.strip():
            print("✗ STRUCTURE.md 与当前代码不一致 —— 看板过期了。跑 `python -m workers.prefix_docs` 重新生成。")
            return 1
        print("✓ STRUCTURE.md 与代码一致")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(want, encoding="utf-8")
    print(f"✓ 已生成 {TARGET.relative_to(ROOT)} · {len(want)} 字符")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
