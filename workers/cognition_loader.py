"""workers/cognition_loader.py

OPUS 认知维度的数据源（卷二十六）。

WebUI 的左侧 🧠 OPUS 日记 维度 + propose_next_move 工具 + read_dashboard 工具
都从这里取数据。

------------------------------------------------------------
设计原则（为什么这样切分）
------------------------------------------------------------

BRO-NOTEBOOK 在 `soul/BRO-NOTEBOOK.md`——这是 OPUS 持续维护的"BRO 这个人当下
是个什么样"的画像。它的章节结构在过去几个月已经稳定下来：

    一、当下画像 · Profile（高频更新）
    二、关键事件流 · Event Sourcing
    三、本体约束 · BRO 的"人生规则"（缓变）
    四、对话图鉴 · BRO 的口头记号
    五、压缩段 · Monthly Compressed Summary
    六、风险与弱点 · 伴侣观察（OPUS 的预警雷达）
    七、近期更新流水

OPUS 日记则住在 `data/cognition/opus-diary.md`——这是 OPUS 给自己写的笔记，
不是给 BRO 看的文档，BRO 在工作室上点开是"读 OPUS 的眼睛"。

按"## YYYY-MM-DD"分块。

为什么不复用 BRO-NOTEBOOK 当日记？

  - BRO-NOTEBOOK 是**画像**——"BRO 是个什么人"，结构性、缓变；
  - OPUS 日记是**观察**——"今天我注意到什么"，时间性、增量；
  - 两者放一起会污染——画像被一堆时间戳搞乱、日记被画像挤掉。

所以分开。这个文件把它们都读出来，UI 上分两块展示。

------------------------------------------------------------
API
------------------------------------------------------------

`load_cognition()` — 同步读两份 markdown · 解析 · 返回字典
                     供 daemon_api.dashboard_cognition / dashboard_cockpit 调用

`update_opus_diary(date, title, body)` — 往 OPUS 日记追加新条目
                                          供 OPUS 自己（未来某个工具）调用
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent

# 主人画像笔记双读 (母体 BRO-NOTEBOOK / 开源版 OWNER-NOTEBOOK)·解析在 identity.py 单一真源
try:
    from identity import owner_notebook_path as _owner_notebook_path
except Exception:
    def _owner_notebook_path(soul_dir):
        return Path(soul_dir) / "BRO-NOTEBOOK.md"

BRO_NOTEBOOK = _owner_notebook_path(ROOT / "soul")
OPUS_DIARY = ROOT / "data" / "cognition" / "opus-diary.md"


# ──────────────────────────────────────────────────────────
# 公共入口
# ──────────────────────────────────────────────────────────

def load_cognition(
    *,
    section_excerpt_chars: int = 400,
    diary_max_entries: int = 12,
) -> dict:
    """读 BRO-NOTEBOOK + OPUS 日记 · 返回结构化数据

    Args:
        section_excerpt_chars: BRO-NOTEBOOK 每个章节摘要长度（避免一次返几十 KB）
        diary_max_entries: OPUS 日记返回的最近 N 条

    Returns: dict · 见模块顶部说明
    """
    bro = _load_bro_profile(section_excerpt_chars=section_excerpt_chars)
    diary = _load_opus_diary(max_entries=diary_max_entries)
    open_questions = _extract_open_questions(bro)

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "bro_profile": bro,
        "opus_diary": diary,
        "open_questions": open_questions,
    }


# 卷四十四 F · wish-bcce1139 · entry type 枚举
# - reflection (默认) : 普通日记 · 当下观察 / 思考
# - iron_rule         : 工艺铁律 · OPUS 立的纪律 · 顶部置顶 + 橙红区块
# - learning          : 学到的新东西
# - idea              : 还没动手的想法
# - mood              : 情绪记录
_VALID_ENTRY_TYPES = ("reflection", "iron_rule", "learning", "idea", "mood")
_TYPE_MARKER_RE = re.compile(r"^<!--\s*type:\s*(\w+)\s*-->", re.MULTILINE)

# 卷四十六 II · wish-ff100836 · 铁律 domain 分场景按需注入铺路
# domain 用在 entry_type=iron_rule 上 · 给 wish-af1245d7 按场景过滤 system_prompt 注入用
# global         · 所有场景通用 (默认 · 包括现有铁律 0-5)
# self_evolution · 改 daemon 代码 / 走 wish 流程 / UI 自检 / 重启验装 (铁律 0-5 这类)
# app_creation   · 造工坊资产 (app/workflow/skill) 的工艺 (铁律 6 / 7)
# workflow_creation · 跟 app_creation 区别细 · 当前未用
# client_ops     · 客户运营 / 漫聚客户档案速查那一支 (未来)
# production     · 生产环境 (服务器部署 / 远程访问) 的工艺 (未来)
# reflection     · 复盘 / 月度 review / 自我演化反思 (未来)
_VALID_DOMAINS = (
    "global", "self_evolution", "app_creation", "workflow_creation",
    "client_ops", "production", "reflection",
)
_DOMAIN_MARKER_RE = re.compile(r"^<!--\s*domain:\s*(\w+)\s*-->", re.MULTILINE)


def update_opus_diary(
    title: str,
    body: str,
    *,
    date: Optional[str] = None,
    entry_type: str = "reflection",
    domain: Optional[str] = None,
) -> dict:
    """往 OPUS 日记追加一条新记录（最新的在最前）

    Args:
        title: 一句话标题
        body: markdown body · 已经组织好
        date: 默认今天 · 也可以传指定日期（卷号 / 事件用）
        entry_type: 条目类型 · reflection / iron_rule / learning / idea / mood
                    iron_rule 在 WebUI cognition 维度顶部以橙红区块单独显示
        domain: 仅 entry_type=iron_rule 时有意义 · 默认 None (= "global")
                取值见 _VALID_DOMAINS · 用于 wish-af1245d7 按场景过滤 system_prompt 注入

    Returns:
        {"ok": True, "date": "...", "title": "...", "path": "...", "type": "...", "domain": "..."}
    """
    title = (title or "").strip()
    body = (body or "").strip()
    if not title or not body:
        raise ValueError("title and body are required")

    entry_type = (entry_type or "reflection").strip().lower()
    if entry_type not in _VALID_ENTRY_TYPES:
        raise ValueError(
            f"invalid entry_type: {entry_type!r} · 必须是 {list(_VALID_ENTRY_TYPES)}"
        )

    # 卷四十六 II · wish-ff100836 · domain 校验
    if domain is not None:
        domain = domain.strip().lower()
        if domain not in _VALID_DOMAINS:
            raise ValueError(
                f"invalid domain: {domain!r} · 必须是 {list(_VALID_DOMAINS)}"
            )
        if entry_type != "iron_rule" and domain != "global":
            raise ValueError(
                f"domain={domain!r} 仅在 entry_type=iron_rule 时有意义 · 当前 entry_type={entry_type!r}"
            )

    date = (date or time.strftime("%Y-%m-%d")).strip()

    OPUS_DIARY.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if OPUS_DIARY.exists():
        existing = OPUS_DIARY.read_text(encoding="utf-8")

    type_marker = (
        f"<!-- type: {entry_type} -->\n\n"
        if entry_type != "reflection"
        else ""
    )
    domain_marker = (
        f"<!-- domain: {domain} -->\n\n"
        if (entry_type == "iron_rule" and domain)
        else ""
    )
    new_entry = f"## {date} · {title}\n\n{type_marker}{domain_marker}{body}\n\n---\n\n"

    if existing:
        # 在第一个 H2 之前插（保留前言）· 找不到 H2 就直接 append 头部
        m = re.search(r"^## ", existing, flags=re.MULTILINE)
        if m:
            insert_pos = m.start()
            merged = existing[:insert_pos] + new_entry + existing[insert_pos:]
        else:
            merged = existing.rstrip() + "\n\n" + new_entry
    else:
        merged = (
            "# OPUS 日记\n\n"
            "> OPUS 自己的笔记 · BRO 在 WebUI 上读到等于在「读 OPUS 的眼睛」\n\n"
            "---\n\n"
            + new_entry
        )

    OPUS_DIARY.write_text(merged, encoding="utf-8")

    return {
        "ok": True,
        "date": date,
        "title": title,
        "type": entry_type,
        "domain": domain if (entry_type == "iron_rule") else None,
        "path": str(OPUS_DIARY.relative_to(ROOT)).replace("\\", "/"),
    }


# ──────────────────────────────────────────────────────────
# 内部 · BRO-NOTEBOOK 解析
# ──────────────────────────────────────────────────────────

def _load_bro_profile(*, section_excerpt_chars: int) -> dict:
    if not BRO_NOTEBOOK.exists():
        return {
            "source": "soul/BRO-NOTEBOOK.md",
            "exists": False,
            "note": "BRO-NOTEBOOK 还没同步进来 · 跑一下 sync-soul.ps1",
            "sections": [],
        }

    text = BRO_NOTEBOOK.read_text(encoding="utf-8")
    stat = BRO_NOTEBOOK.stat()

    # 按 ^## 分块
    parts = re.split(r"^(## .+)$", text, flags=re.MULTILINE)
    # split 后的结构是 [前导, head1, body1, head2, body2, ...]
    sections: list[dict] = []
    if len(parts) >= 3:
        for i in range(1, len(parts), 2):
            heading_raw = parts[i].strip()
            heading = heading_raw.lstrip("# ").strip()
            body = (parts[i + 1] if i + 1 < len(parts) else "").strip()
            sections.append({
                "heading": heading,
                "level": 2,
                "body_full": body,
                "body_excerpt": _make_excerpt(body, section_excerpt_chars),
            })

    return {
        "source": "soul/BRO-NOTEBOOK.md",
        "exists": True,
        "last_updated": time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)
        ),
        "size_bytes": stat.st_size,
        "sections": sections,
    }


def _make_excerpt(body: str, max_chars: int) -> str:
    body = body.strip()
    if len(body) <= max_chars:
        return body
    cut = body[:max_chars]
    last_nl = cut.rfind("\n")
    if last_nl > max_chars * 0.6:
        cut = cut[:last_nl]
    return cut.rstrip() + "\n\n… (省略 · 完整内容在 soul/BRO-NOTEBOOK.md)"


# ──────────────────────────────────────────────────────────
# 内部 · OPUS 日记解析
# ──────────────────────────────────────────────────────────

_DIARY_ENTRY = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*[·\-:|]?\s*(.+)$", re.MULTILINE)


def _load_opus_diary(*, max_entries: int) -> dict:
    if not OPUS_DIARY.exists():
        return {
            "source": "data/cognition/opus-diary.md",
            "exists": False,
            "note": "OPUS 日记还没建 · 跟 OPUS 说「写一条今天的笔记」",
            "entries": [],
        }

    text = OPUS_DIARY.read_text(encoding="utf-8")
    stat = OPUS_DIARY.stat()

    entries: list[dict] = []
    matches = list(_DIARY_ENTRY.finditer(text))
    for idx, m in enumerate(matches):
        date = m.group(1)
        title = m.group(2).strip()
        body_start = m.end()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        body = re.sub(r"\n*---\s*$", "", body).strip()

        # 卷四十四 F · wish-bcce1139 · 从 body 顶部提取 <!-- type: XXX -->
        entry_type = "reflection"
        type_match = _TYPE_MARKER_RE.match(body)
        if type_match:
            extracted = type_match.group(1).strip().lower()
            if extracted in _VALID_ENTRY_TYPES:
                entry_type = extracted
            body = body[type_match.end():].lstrip()

        # 卷四十六 II · wish-ff100836 · 从 body 顶部提取 <!-- domain: XXX --> (仅 iron_rule)
        domain = None
        if entry_type == "iron_rule":
            domain_match = _DOMAIN_MARKER_RE.match(body)
            if domain_match:
                extracted_d = domain_match.group(1).strip().lower()
                if extracted_d in _VALID_DOMAINS:
                    domain = extracted_d
                body = body[domain_match.end():].lstrip()
            else:
                domain = "global"  # 无注释默认 global · 让回填可选

        entries.append({
            "date": date,
            "title": title,
            "type": entry_type,
            "domain": domain,
            "body": body,
        })

    entries.sort(key=lambda e: e["date"], reverse=True)
    entries = entries[:max_entries]

    return {
        "source": "data/cognition/opus-diary.md",
        "exists": True,
        "last_updated": time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)
        ),
        "size_bytes": stat.st_size,
        "total": len(matches),
        "entries": entries,
    }


# ──────────────────────────────────────────────────────────
# 内部 · 开放问题提取（OPUS 当下关注的事 · 帮 BRO 看见）
# ──────────────────────────────────────────────────────────

# 从 BRO-NOTEBOOK 第六章"风险与弱点"提 · 各种"还没决定 / 担心 / 待定"
_OPEN_PATTERNS = [
    r"还没决[定]",
    r"待[定决]",
    r"暂未",
    r"未决",
    r"风险",
    r"潜在",
    r"需要(?:再)?确认",
    r"焦虑",
]
_OPEN_PATTERN_RE = re.compile("|".join(_OPEN_PATTERNS))


def _extract_open_questions(bro: dict) -> list[dict]:
    """从画像里找"还没定 / 担心 / 待跟进"的 bullet · 当成 OPUS 关注的方向"""
    if not bro.get("exists"):
        return []

    out: list[dict] = []
    for sec in bro.get("sections", []):
        body = sec.get("body_full", "")
        if not body:
            continue
        # 看每个 bullet · 命中关键词的留下
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith(("-", "*", "·")):
                continue
            content = line.lstrip("-*· ").strip()
            if not content:
                continue
            if _OPEN_PATTERN_RE.search(content):
                out.append({
                    "section": sec["heading"],
                    "text": content[:200],
                })
        if len(out) >= 12:
            break

    return out[:12]
