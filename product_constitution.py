"""product_constitution.py · 产品宪法注入 (内核 · 0.5.0)

两层模型:
  通用三条 (本文件 · 内核 · 随 update_core 同步给所有实例): 闭环 / NLP优先 / 可追溯——
    任何"AI 与人共生的 daemon"都成立的根本原则·这类产品的物理定律。
  实例宪法 (soul/CONSTITUTION.md · 实例私有 · never_sync · 从使用中沉淀):
    母体预填Daemonkey六条·开源实例从空白开始·随主人的使用长出自己的产品观。

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


# ── 段头常量（单一真相源 · 2026-09-19 wish-50e6d578）────────────────────────
# why: 这三行段头原来只在本文件里硬编码，而 soul_loader.SECTION_MARKS 另抄了一份
#      当面板切块锚点 —— 两张皮一旦漂移，面板就给这块显示 0 tok、并把它的量并进
#      相邻那块。2026-09-19 正是这么坏的：段头加了「· 已含内核地基」而锚点没跟，
#      959 tok 在面板上隐形、「工程铁律」虚高 959。
# 现在段头只在这里定义一处，soul_loader 反向 import（它本来就 import 本模块，
# 方向天然成立、不会循环）—— 改段头只改这里，面板自动跟上。
MARK_CONST_COMMON = "=== 规则层 · 产品宪法（通用三条 · 内核地基 · 优先级等同工程铁律） ==="
MARK_CONST_LOCAL = "=== 规则层 · 产品宪法（本实例 · soul/CONSTITUTION.md） ==="
MARK_CONST_EXTRA = "=== 规则层 · 改装纪律（本实例 · 随内核下发） ==="


def build_constitution_block(soul_dir: Path, *, include_common: bool = True,
                             include_local: bool = True) -> str:
    """组装产品宪法 block (注入 system prompt · 紧邻工程铁律)。

    include_common / include_local（wish-e1178ade · 层配置开关）：默认全 True
    = 逐字节现状；预设关段时从这里过滤（整区全关 → 返回空串）。

    **两者只留一份** —— soul/CONSTITUTION.md 自己的第 3 行就写着
    「二 / 四 / 五条是通用三条在Daemonkey语境的具体展开」。所以只要实例宪法在，
    通用三条就是纯重复：2026-09-18 前缀审计实测 583 tok 付两遍钱，
    且措辞已经漂移（闭环写「任何 OPUS→BRO」vs「任何 AI→BRO」·
    可追溯写「绝不发明信源」vs「LLM 不许发明信源」）。

    - 有实例宪法（母体）→ 只注入实例六条
    - 无实例宪法（纯净版首启 / 开源实例）→ 注入通用三条（它唯一的地基）
    改装纪律 (constitution_extra) 与宪法无关 · 两边照旧。
    """
    inst = Path(soul_dir) / INSTANCE_CONSTITUTION_FILENAME
    inst_txt = ""
    if inst.exists():
        try:
            inst_txt = inst.read_text(encoding="utf-8").strip()
        except Exception:
            inst_txt = ""

    parts: list[str] = []
    if inst_txt:
        # ⚠ 这里原来是「有实例就用实例·通用三条整块丢掉」——纯净版用户往自己的
        #   CONSTITUTION.md 里加一条自己的规则（增量而非重写），通用三条就静默消失、
        #   没有任何提示（code_review 2026-09-19 第 8 条·已回源码坐实）。
        #   现在加一道「是否已含地基」的锚点检查：母体六条里明确写了「(= 内核通用第 N 条)」，
        #   三个锚词全中 → 判定已含 → 只注入实例（就是原来省的 583 tok）；
        #   命中不全 → 说明这份实例宪法没盖住地基 → **把通用三条补在前面**。
        #   宁可多花 token 也不能丢地基：这是「根本不会发生」的做法，不是事后提醒。
        # ⚠ 段头两种情形**共用一个字面量**（MARK_CONST_LOCAL）—— 2026-09-19 wish-50e6d578：
        #   原来 covered 写「· 已含内核地基」、not-covered 写「· 本实例补充」，两个变体，
        #   而 soul_loader.SECTION_MARKS 只登记了后者 → 母体面板给这块显示 0 tok、
        #   并把 959 tok 并进上一块。段头只该说「这是什么」，不说「跟别的东西什么关系」
        #   （not-covered 时那层关系由结构自己表达：上面就摆着通用三条的段头）。
        anchors = ("闭环范式", "NLP 优先", "可追溯")
        covered = all(a in inst_txt for a in anchors)
        # wish-e1178ade · 层配置：include_local=False 时实例宪法整段去掉；
        # covered 且 common 被关时——common 内容本来就不独立存在（被实例覆盖）→ 也去掉。
        if include_local:
            if covered or not include_common:
                parts = [MARK_CONST_LOCAL, "", inst_txt]
            else:
                parts = [
                    MARK_CONST_COMMON, "",
                    UNIVERSAL_CONSTITUTION, "",
                    MARK_CONST_LOCAL, "", inst_txt,
                ]
        elif include_common and not covered:
            parts = [MARK_CONST_COMMON, "", UNIVERSAL_CONSTITUTION]
    else:
        if include_common:
            parts = [MARK_CONST_COMMON, "", UNIVERSAL_CONSTITUTION]
    # 改装纪律：宪法区两段全关 = 整区移除（extra 跟随；默认路径行为不变）
    if include_common or include_local:
        try:
            from workers.overlay_policy import constitution_extra
            extra = constitution_extra()
            if extra:
                parts.append("")
                parts.append(MARK_CONST_EXTRA)
                parts.append("")
                parts.append(extra.strip())
        except Exception:
            pass
    if not parts:
        return ""
    return "\n".join(parts) + "\n\n"
