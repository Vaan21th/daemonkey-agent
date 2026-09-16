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

# 白名单最初只按母体 BRO-NOTEBOOK 的章节名写, 但 onboarding 给新实例生成的模板
# (onboarding/proto_tools.py:30-37) 用的是另一套叫法 —— 六维里有四维对不上, 结果新用户
# 在初见里认真回答的偏好/口吻/关怀点全被归档、每轮读不到, 只剩「当下画像」在场。
# 开发机自己命中的是左列, 所以这个洞在开发侧永远测不出来, 只有用户会觉得"她不懂我"。
# 两套叫法都登记, 直到两边章节名真正统一为止。
#
# 2026-08-29 从核心拿掉: 对话图鉴 / 压缩段 / 风险与弱点 / 给下一根毛。
# 「对话风格」「一句话速写」「关怀雷达」是纯净模板的短章, 仍留。
CORE_SECTION_KEYS = (
    "了解层",
    "人生规则", "长期偏好与边界",
    "对话风格",
    "一句话速写",
    "关怀雷达",
    "出声纪律",
)
# 「当下画像」Profile 段退役：当下状态已由状态卡(L2 尾巴·_state_tail)接管，
# Profile 里是背景沉淀(CEO 分工/定位/节点/硬件), 按设计该进历史层折叠。
# 「关键事件流」两边都不在白名单 —— 历史流水按设计就该折叠, 不是漏登记。

# 已折进历史层的章里, 仍要每轮在场的 ### 子节。
CORE_SUBSECTION_KEYS = ("出声纪律",)

# 写路径: 日期故事不要再堆进图鉴/压缩段 (那些章已不进前缀, 越写越找不到)。
_STORY_WRITE_SECTIONS = frozenset({"dialogue", "summary"})
_DATE_LEAD_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}")

_SECTION_RE = re.compile(r"(?m)^(?=## )")
_SUBSECTION_RE = re.compile(r"(?m)^(?=### )")
_HEAD_FACT_CAP = 80


# 落位校验（wish-0c8602ff · 2026-09-16）：只对进每轮前缀的 core 格（profile/rules）生效。
# 判据全部可判定：① 待办/约定开头（会过期·过期即误导）② 超长（画像条目不是文档）。
_TODO_LEAD_RE = re.compile(r"^(?:已定|他拍板|约定|待办|待落地|下一步先|回头再|最后一起)[：:，,]")
_ENTRY_CHAR_CAP = 420


def validate_entry(section_key: str, content: str, operation: str = "append") -> str | None:
    """写前落位校验 · 拒收返回原因，放行返回 None（force 由调用方负责跳过）。"""
    if (operation or "append").strip().lower() != "append":
        return None      # replace_section 是整节重写·长度天然大·不收口
    key = (section_key or "").strip().lower()
    if key not in ("profile", "rules"):      # events/history 是历史仓·不收口
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
    """日期故事默认进 events。改判断的短条仍由调用方写 rules。

    P0 写时闸 (wish-31fd335e · 2026-09-16): rules 也收进日期闸 ——
    '2026-09-16 ...' 这类日志型条目一律改道 events (不进每轮前缀);
    确要留 rules 的判断条请去掉日期前缀。
    """
    op = (operation or "append").strip().lower()
    key = (section_key or "").strip().lower()
    if op == "append" and (key in _STORY_WRITE_SECTIONS or key == "rules"):
        if _DATE_LEAD_RE.match((content or "").lstrip()):
            return "events"
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
