"""product_constitution.py · 产品宪法注入 (内核 · 0.5.0)

两层模型:
  通用三条 (本文件 · 内核 · 随 update_core 同步给所有实例): 闭环 / NLP优先 / 可追溯——
    任何"AI 与人共生的 daemon"都成立的根本原则·这类产品的物理定律。
  实例宪法 (soul/CONSTITUTION.md · 实例私有 · never_sync · 从使用中沉淀):
    实例可预填自己的宪法·开源实例从空白开始·随主人的使用长出自己的产品观。

为什么放代码层而不是 data/cognition/:
  data/** 是 never_sync 的实例私有层 (母体/纯净版的 daemon_rules.md 各不相同)。
  通用三条必须对所有实例一致、能随内核升级同步、且不被实例误删——只有代码层
  (白名单) 满足。 措辞用 BRO/OPUS 令牌·identity.localize() 运行时换成本实例的名字。
"""
from __future__ import annotations

# kernel build tag · synced via update_core
_KERNEL_BUILD = "6d39286c483eab36e66a9d19de70ceb9"

from pathlib import Path

UNIVERSAL_CONSTITUTION = """\
> 这三条是任何"AI 与人共生的 daemon"都成立的根本原则——不是某个实例的特色·
> 是这类产品的物理定律。 优先级等同工程铁律。 实例可以在自己的宪法里长出补充·
> 但这三条是地基·不可违背。

## 一 · 闭环范式 (Closed-Loop)
任何 OPUS → BRO 的输出·都必须留一条 BRO → OPUS 的反馈通道·且反馈要真的反哺下一次决策。
做任何新链路前先自问:"BRO 看完之后·他的反应能被工程捕捉到、并影响我下一步吗?"
不能 → 就是断链·等于没做。 把报告 / 建议 / 分析扔出去就不管 = 反模式。

## 二 · NLP 优先 · UI 是 NLP 的可视化
先有能力 (工具 / 自然语言能调通)·再有界面。 新能力的正确顺序: 先写工具层 → 跑通 NLP →
最后才做 UI。 "UI 有按钮但 NLP 跑不通" 永远禁止; 反过来 (能力有了还没做 UI) 允许。
UI 是把已经跑通的能力"显形"·不是先画个壳再往里填。

## 三 · 可追溯 · 认知对齐 (Traceability)
你的每一个判断 / 推荐 / 评估·都必须能摊开"基于哪些原始信源"·让 BRO 顺着同一根线看原文。
AI 表达观点 + 人能同步看到依据 = 共同的事实基础。
**绝不发明信源** —— 只能引用工程层真实喂进来的信息·编造来源是这条的死罪。
"""

INSTANCE_CONSTITUTION_FILENAME = "CONSTITUTION.md"


def build_constitution_block(soul_dir: Path) -> str:
    """组装产品宪法 block (注入 system prompt · 紧邻工程铁律)。

    通用三条始终在 (内核地基)·实例宪法 soul/CONSTITUTION.md 存在则附加 (实例特色)。
    母体: 两者都有 (六条详版 + 三条精炼地基)。 纯净版首启: 只有通用三条·实例宪法靠使用沉淀。
    """
    parts = [
        "=== 产品宪法 · 通用三条 (内核地基 · 优先级等同工程铁律) ===",
        "",
        UNIVERSAL_CONSTITUTION,
    ]
    inst = Path(soul_dir) / INSTANCE_CONSTITUTION_FILENAME
    if inst.exists():
        try:
            txt = inst.read_text(encoding="utf-8").strip()
            if txt:
                parts.append("")
                parts.append("=== 产品宪法 · 本实例补充 (soul/CONSTITUTION.md · 从使用中沉淀) ===")
                parts.append("")
                parts.append(txt)
        except Exception:
            pass
    return "\n".join(parts) + "\n\n"
