"""workers/notebook_tiers.py
========================
画像分层 (2026-08-20 · 0.9.6 知识体系三件套之一)。

why: 画像涨到 57.8K 字符后全量注入 = 每轮白烧 2-3 万 token, 占 128K 窗口约四成。
实测画像 66% 体量是历史流水 (事件流 27.4K + 更新流水 11.1K) —— 它们的价值是可追溯,
不是每轮在场。 画像全文已在 memory_chunks(source=BRO-NOTEBOOK) 有索引, 历史层折叠后
recall_memory / read_file 都能取回, 可追溯性不丢。

切分方向的安全选择: 核心层走白名单 (已知当下维度), 未命中的一律进历史层 ——
未来画像新增维度默认不推高每轮注入体量 (体量安全), 要进核心层必须在此显式登记。

2026-08-29 · 核心层再收一刀:
过往细节一个字不删, 只是不再焊进前缀。核心层只留会改「怎么对你说话 / 怎么做决定」
的短条; 图鉴教材、月度压缩、风险长文、给下一根毛, 用时 recall_memory。
出声纪律从风险章里捞回 —— 那是判断骨头, 不是故事。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 白名单最初只按母体 BRO-NOTEBOOK 的章节名写, 但 onboarding 给新实例生成的模板
# (onboarding/proto_tools.py:30-37) 用的是另一套叫法 —— 六维里有四维对不上, 结果新用户
# 在初见里认真回答的偏好/口吻/关怀点全被归档、每轮读不到, 只剩「当下画像」在场。
# 开发机自己命中的是左列, 所以这个洞在开发侧永远测不出来, 只有用户会觉得"她不懂我"。
# 两套叫法都登记, 直到两边章节名真正统一为止。
#
# 2026-08-29 从核心拿掉: 对话图鉴 / 压缩段 / 风险与弱点 / 给下一根毛。
# 「对话风格」「一句话速写」「关怀雷达」是纯净模板的短章, 仍留。
@dataclass(frozen=True)
class SectionMeta:
    """画像里一格的「元信息」—— 任何 LLM 看工具回报就知道这条该放哪。"""

    key: str                    # 短名 (工具 section 参数)
    anchor: tuple[str, ...]     # 段标题定位候选 (按序·兼容迁移期两套叫法)
    prefix: tuple[str, ...]     # 段标题含其一 → 进每轮前缀
    distill: bool               # 有没有「折叠→提炼→毕业」管道
    dated_ok: bool              # 收不收「日期开头」的流水
    writable: bool              # 工具能不能写它
    what: str                   # 这格放什么 (一句话)


# ⚠ BRO 2026-09-18 原则: 母体 = 多用了几个月的纯净版, 两边**不许分叉**;
#   母体独有的东西 (自传/成长/回忆) 单独放私有柜, 不混进结构。
#   下面 anchor 里同时登记「母体叫法 / 纯净版模板叫法」是**迁移期兼容**, 待归一 —— 不是永久两套。
SECTIONS: dict[str, SectionMeta] = {
    "state": SectionMeta(
        "state", ("〇、状态卡",), (), False, True, True,
        "当下状态的 8 个字段（工作/作息/健康/情绪/主线/家庭/预算/忌口）· 替换式更新不追加。"
        "走状态卡通道单独注入，不依赖画像分层。",
    ),
    "understanding": SectionMeta(
        "understanding", ("了解层",), ("了解层",), False, True, False,
        "周度凝练的产物：稳定下来的了解（跨周不变的）。只有凝练器或他显式说才写。",
    ),
    "background": SectionMeta(
        "background", ("背景档案", "当下画像"), (), False, False, True,
        "背景档案：已沉淀的定位/节点/硬件等背景。已退役、不再高频更新 —— 写进来每轮读不到。",
    ),
    "stories": SectionMeta(
        "stories", ("他经历的事", "关键事件流"), (), True, True, True,
        "日期开头的故事/流水放这里（唯一带提炼管道的格）：周度凝练会把重要的提炼进「了解层」。",
    ),
    # key 曾叫 "rules" —— 与铁律 daemon_rules.md 撞词，2026-09-18 改名 about-user：
    # 「rules」这个词只留给铁律。类目名语义唯一，换谁来当图书管理员都知道书该上哪个架。
    "about-user": SectionMeta(
        "about-user", ("本体约束", "长期偏好与边界"), ("关于他", "长期偏好与边界"), False, False, True,
        # 2026-09-19 wish-a1580b98: 这格曾经被当成「他说过的一切要求」的筐 —— 37 行产品/功能决策
        #   落进来。根因不是没闸，是定义太宽：只写了「不要日期、不要流水」，没说明「描述的是他这个人，
        #   不是我们做的东西」。现在把定义收窄 + 给三条明确出口，让不该进来的自己就不想来。
        "放「改判断」的短条：描述**他这个人**的原则/偏好/边界（跨场景稳定、换件事也成立）。"
        "不装这三样：① 产品/功能决策（界面怎么做/按钮放哪/分组怎么分）→ 走 wish_add 或代码注释；"
        "② 工程纪律（怎么干活）→ 走 daemon_rules.md 铁律或 playbook；"
        "③ 带日期的流水 → 自动改道 stories。自问：把主语换成别人，这条还成立吗？成立才是「关于他」。",
    ),
    # 2026-09-28 wish-a4c007bb 拆格：原本只有 about-user 一格，混着两类东西 ——
    #   ① 「他是谁 / 生活情感陪伴」（换别人不成立）
    #   ② 「怎么跟他干活」（授权风格 / 验收标准 / 沟通纪律）
    #   混着导致定义写不窄（8 条里 5 条是后者）→ 拆成两格，让每格的定义都能窄到
    #   「不该进来的自己就不想来」。物理上第二条落在「三之二、怎么跟他干活」段。
    "how-we-work": SectionMeta(
        "how-we-work", ("怎么跟他干活",), ("怎么跟他干活",), False, False, True,
        "放「我该怎么跟他开工」：授权风格 / 验收标准 / 沟通纪律。"
        "不装这三样：①「他是谁 / 怎么陪他」→ about-user；② 界面/产品怎么做 → wish_add 或代码注释；"
        "③ 怎么改 daemon（工程纪律）→ daemon_rules.md 铁律或 playbook。"
        "判据：这条是在说他这个人（→about-user），还是在说我干活的方式（→这里）？",
    ),
    "moments": SectionMeta(
        "moments", ("口头记号", "对话图鉴", "对话风格"), ("对话风格",), False, False, True,
        "称呼、说话习惯、心情图。母体=像朋友圈的心情图/口头记号；纯净版模板=对话风格短条（进前缀）。",
    ),
    "archive": SectionMeta(
        "archive", ("月度长档", "压缩段", "一句话速写"), ("一句话速写",), False, False, True,
        "长期沉淀的长档。母体=月度压缩长文；纯净版模板=一句话速写（进前缀）。",
    ),
    "watch": SectionMeta(
        "watch", ("我留意的信号", "风险与弱点", "关怀雷达"), ("关怀雷达",), False, True, True,
        "我留意到的、该关照他的地方（性格/状态信号）。母体=伴侣观察长文；纯净版模板=关怀雷达（进前缀）。",
    ),
    "changelog": SectionMeta(
        "changelog", ("改动记录", "近期更新流水"), (), False, True, False,
        "机器写的操作流水（每次改画像自动追加）。",
    ),
    "next-mate": SectionMeta(
        "next-mate", ("给下一根毛",), (), False, True, False,
        "给下一根毛的交接提示。",
    ),
}

# 已折进历史层的章里, 仍要每轮在场的 ### 子节。
CORE_SUBSECTION_KEYS = ("出声纪律",)

# 判「进不进每轮前缀」的识别词 —— 从上面的表展平（外部/测试仍在 import 这个名字）。
CORE_SECTION_KEYS = tuple(
    dict.fromkeys(
        [k for m in SECTIONS.values() for k in m.prefix] + list(CORE_SUBSECTION_KEYS)
    )
)

# ── 段落归位查询 (wish-9118bdab · 2026-09-17) ────────────────────────
# 病根: 写入端 (agent_tools/update_bro_note.py) 硬编码「profile/rules 进前缀」,
# 但 profile 段 (「一、当下画像」) 早已退役出核心层 —— 白名单里没有它。
# 结果: 每次写 profile 工具都回报「✓ 进前缀 (每轮注入)」, 实际每轮读不到。
# 同一个事实写在两处, 迟早不一致 (同 SECTION_MARKS 那类漂移)。
# 修法: 只留一个判据来源 —— 就是上面的 CORE_SECTION_KEYS。


def is_core_section(title: str) -> bool:
    """磁盘上的**真实段标题**进不进每轮前缀。

    传段头那一行的原文, 不要传 SECTIONS 短映射:
      「三、本体约束 · 关于他 / 怎么相处（缓变）」 → True (含「关于他」)
      但如果传短映射「本体约束」 → False (误判!)
      「一、当下画像 · Profile（高频更新）」      → False (已退役)
    """
    t = title or ""
    return any(k in t for k in CORE_SECTION_KEYS)


# 折叠层里, 哪些段有「折叠 → 提炼 → 毕业进核心层」的管道。
# 目前只有 events: workers/state_condenser.py 读事件流 → 写了解层 (周度凝练)。
# 不在表里的折叠段 (dialogue / profile / 风险与弱点…) 是**单向阀** ——
# 写进去不会再自己浮上来, 只能靠 recall_memory 主动召回。
# 管道来源: workers/state_condenser.py 读事件流 → 写了解层 (周度凝练)。
# 没有管道的折叠格是**单向阀** —— 写进去不会再自己浮上来, 只能靠 recall_memory 召回。
_DISTILLED_SECTIONS = frozenset(m.key for m in SECTIONS.values() if m.distill)


def has_distill_pipeline(section_key: str) -> bool:
    """该段有没有提炼管道 (写了将来会自己浮上来)。"""
    m = SECTIONS.get((section_key or "").strip().lower())
    return bool(m and m.distill)


def section_key_for_title(title: str) -> str | None:
    """磁盘真实段标题 → 格子短名 (面板/文档/工具定位用)。"""
    t = title or ""
    for m in SECTIONS.values():
        if any(k in t for k in m.prefix):
            return m.key
    for m in SECTIONS.values():
        if any(k in t for k in m.anchor):
            return m.key
    return None


def section_meta(section_key: str) -> SectionMeta | None:
    """短名 → 格子元信息 (工具回报「这格放什么」用)。"""
    return SECTIONS.get((section_key or "").strip().lower())

# 写路径: 日期故事不要再堆进图鉴/压缩段 (那些章已不进前缀, 越写越找不到)。
_STORY_WRITE_SECTIONS = frozenset(m.key for m in SECTIONS.values() if not m.dated_ok)
_DATE_LEAD_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}")

_SECTION_RE = re.compile(r"(?m)^(?=## )")
_SUBSECTION_RE = re.compile(r"(?m)^(?=### )")
_HEAD_FACT_CAP = 80


# 落位校验（wish-0c8602ff · 2026-09-16）：只对「可能进每轮前缀」的格生效（判据读 SECTIONS 表）。
# 判据全部可判定：① 待办/约定开头（会过期·过期即误导）② 超长（画像条目不是文档）。
_TODO_LEAD_RE = re.compile(r"^(?:已定|他拍板|约定|待办|待落地|下一步先|回头再|最后一起)[：:，,]")
_ENTRY_CHAR_CAP = 420


def validate_entry(section_key: str, content: str, operation: str = "append") -> str | None:
    """写前落位校验 · 拒收返回原因，放行返回 None（force 由调用方负责跳过）。"""
    if (operation or "append").strip().lower() != "append":
        return None      # replace_section 是整节重写·长度天然大·不收口
    key = (section_key or "").strip().lower()
    m = SECTIONS.get(key)
    if not (m and m.prefix):     # 只有「可能进每轮前缀」的格才收口 (历史仓不收)
        return None
    text = (content or "").strip()
    if _TODO_LEAD_RE.match(text):
        return (
            "拒收：这条像【带期限的待办/约定】（\"已定/约定/待办\"开头）——画像每轮注入，"
            "过期条目会误导按旧状态办事。请写成无期限的偏好/原则（去掉开头标记词），"
            "或去 track_task / wish 记账。确要强写：force=true。"
        )
    if len(text) > _ENTRY_CHAR_CAP:
        return (
            f"拒收：单条 {len(text)} 字 · 超过画像条目上限 {_ENTRY_CHAR_CAP} 字。"
            "画像条目要短 · 长内容请落 data/dev 设计档或 SELF-EVOLUTION。确要强写：force=true。"
        )
    return None


def route_write_section(section_key: str, operation: str, content: str) -> str:
    """日期故事默认进 stories。改判断的短条仍由调用方写 about-user。

    P0 写时闸 (wish-31fd335e · 2026-09-16): about-user 也收进日期闸 ——
    '2026-09-16 ...' 这类日志型条目一律改道 stories (不进每轮前缀);
    确要留 about-user 的判断条请去掉日期前缀。
    """
    op = (operation or "append").strip().lower()
    key = (section_key or "").strip().lower()
    if op == "append" and key in _STORY_WRITE_SECTIONS:
        if _DATE_LEAD_RE.match((content or "").lstrip()):
            return "stories"
    return key


def _slim_head(head: str) -> str:
    """文件头长说明书每轮白烧; 短前言留下, 长头只留 # 标题。"""
    if not (head or "").strip():
        return ""
    facts = []
    for line in head.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(">") or s.startswith("---"):
            continue
        facts.append(s)
    if len("".join(facts)) <= _HEAD_FACT_CAP:
        return head if head.endswith("\n") else head + "\n"
    for line in head.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            return line.rstrip() + "\n\n"
    return ""


def _pluck_core_subsections(seg: str) -> str:
    parts = _SUBSECTION_RE.split(seg)
    kept = []
    for part in parts[1:]:
        title = part.split("\n", 1)[0]
        if any(k in title for k in CORE_SUBSECTION_KEYS):
            kept.append(part)
    return "".join(kept)


def split_tiers(text: str) -> tuple[str, list[tuple[str, int]]]:
    """把画像按二级标题切成 (核心层文本, [(历史层标题, 字符数)])。

    无 `## ` 维度标题的画像 (新装实例/极简画像) 整体视为核心层, 原样返回。

    缓存纪律 (2026-09-19 · 前缀分层原则)：**core 按文件里的先后顺序拼** ——
    所以往画像加新的进前缀段时，记得**往文件后面加**。
    缓存按前缀逐字节匹配，第一个不同处之后全失效 —— 越靠后的段，改了秧及范围越小。
    母体现状「了解层(周度凝练) → 关于他(他拍板时) → 出声纪律」已经是由冷到热，
    别把新段插到最前面。反例：状态卡（变得最勤）就不在这条线上 —— 它 prefix=()，
    走独立通道注入，根本不参与画像分层。
    """
    if not text or not text.strip():
        return text or "", []
    parts = _SECTION_RE.split(text)
    head, sections = parts[0], parts[1:]
    if not sections:
        return text, []
    core, archived = [], []
    for seg in sections:
        title = seg.split("\n", 1)[0].lstrip("# ").strip()
        if any(k in title for k in CORE_SECTION_KEYS):
            core.append(seg)
            continue
        plucked = _pluck_core_subsections(seg)
        if plucked:
            core.append("## 出声纪律\n\n" + plucked)
        archived.append((title, len(seg)))
    return _slim_head(head) + "".join(core), archived


def render_tiered(text: str) -> str:
    """分层渲染: 核心层原文 + 历史层折叠成归档指引 (全文一字未删, 取回方式写清)。

    归档指引只列标题不带字符数 —— 历史层每天追加事件流, 字符数每轮变,
    挂在指引里会冲掉 system 前缀缓存 (0.8x 缓存前缀稳定化: 字节不变才命中)。
    """
    core, archived = split_tiers(text)
    if not archived:
        return text
    lines = "\n".join(f"  - 「{t}」" for t, _n in archived)
    return (
        core.rstrip()
        + "\n\n---\n\n## 已归档的历史层（每轮不注入 · 按需取回）\n\n"
        + "以下维度是历史流水，已从每轮注入折叠，**全文一字未删**：\n"
        + lines
        + "\n\n取回方式：`recall_memory`（画像全文在记忆索引）"
        "或 `read_file` 画像文件对应维度段。\n"
    )


# ── P0 写时闸 (wish-31fd335e · 2026-09-16) ─────────────────────────────
# 核心层 (会进每轮前缀的段) 总量预算。BRO 标准模式前缀目标 15-20K tok，
# 核心层是其中最大一块。超 → 写入拒绝并提示先清理 (force=true 可跳过)。
PREFIX_CORE_BUDGET_TOK = 5000


def _estimate_tok(s: str) -> int:
    """tiktoken 真算 · 不可用时按中文实测 ≈1.2 字符/token 退算。"""
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(s))
    except Exception:
        return int(len(s) / 1.2)


def core_budget_estimate(text: str) -> tuple[int, int]:
    """估核心层 token (与 split_tiers 同一把尺) · 返回 (used, cap)。"""
    core, _archived = split_tiers(text or "")
    return _estimate_tok(core), PREFIX_CORE_BUDGET_TOK


# ── 分格配额 (2026-09-29 wish-65ea4984 step5) ───────────────────────────
# 病根：一口大锅 5000 会「一格吃光」—— 本体约束曾独占 3866 (77%)，
#   其他格想写时被整锅的剩余量拒掉：新内容进不来，也不告诉你「该清哪一格」。
# 改成每格一口小锅：满了只拒该格，并点名「去清这一格」。
#
# 数值依据：**实测现值 + 20~30% 余量**，不是拍脑袋 —— 它的作用是「防止无限涨」，
#   不是「一上线就逼你清」。校正记录（2026-09-29 实测）：
#     state 936 · understanding 760 · about-user 2373 · how-we-work 1144
# 没登记的格子（stories / moments / background / archive 等归档层）走兼底，
#   它们不进每轮前缀，配额只是防呆。
SECTION_BUDGET_TOK: dict[str, int] = {
    "state": 1200,         # 8 个字段的当下状态 · 替换式更新不追加
    "understanding": 1000,  # 周度凝练的产物 · 只有凝练器写
    "about-user": 2800,     # 他是谁 + 相处边界 + 红线
    "how-we-work": 1700,    # 授权风格 / 验收标准 / 沟通纪律
}
DEFAULT_SECTION_BUDGET_TOK = 2000   # 表里没登记的格子 · 兜底（宽松：归档层不卡）


def _iter_sections(text: str):
    """按 `^## ` 切段 · yield (标题行, 段正文)。

    只用于配额统计 —— 与写入口（update_bro_note._find_section）分开是故意的：
    那边管「能不能写进去」，这边只管「占了多少」。
    """
    import re as _re
    for chunk in _re.split(r"\n(?=## )", text or ""):
        head = chunk.strip().split("\n")[0].lstrip("# ").strip()
        if head:
            yield head, chunk


def section_budget_estimate(text: str, section_key: str) -> tuple[int, int]:
    """估某一格自己的 token · 返回 (used, cap)。不存在的格子 → (0, 兼底)。"""
    anchors = tuple(SECTIONS[section_key].anchor) if section_key in SECTIONS else ()
    used = 0
    for head, chunk in _iter_sections(text):
        if any(a in head for a in anchors):
            used = _estimate_tok(chunk)
            break
    return used, SECTION_BUDGET_TOK.get(section_key, DEFAULT_SECTION_BUDGET_TOK)
